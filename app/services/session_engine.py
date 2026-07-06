"""Interview session engine.

Owns the session lifecycle state machine, single-active-interview
concurrency control, heartbeats, timers, auto-save and crash recovery.

State machine:
    start   -> active
    pause   -> paused        (from active)
    resume  -> active        (from paused, or from active/stale after refresh)
    finish  -> completed     (from active/paused)
    cancel  -> cancelled     (from active/paused)
    sweep   -> abandoned     (live session whose heartbeat exceeded the
                              recovery window)
    countdown reaches zero -> expired

Concurrency: one live (active|paused) interview per user, guarded by a
rotating session token bound to browser/device. A second tab or device
presenting a stale token receives 409 SESSION_CONFLICT unless it asks for
takeover.
"""

import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session as DbSession

from app import models, schemas
from app.config import settings
from app.errors import ApiError

logger = logging.getLogger("backend.session_engine")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize DB datetimes (naive UTC in Postgres) to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _seconds_between(start: Optional[datetime], end: Optional[datetime]) -> int:
    if not start or not end:
        return 0
    return max(0, int((as_utc(end) - as_utc(start)).total_seconds()))


def log_event(db: DbSession, session_id: str, event_type: str, details: dict = None):
    db.add(models.SessionEvent(session_id=session_id, event_type=event_type, details=details or {}))


def _ensure_user(db: DbSession, user_id: str):
    if not db.query(models.User).filter(models.User.id == user_id).first():
        db.add(models.User(id=user_id))
        db.flush()


def verify_token(session: models.Session, token: Optional[str], strict: bool = False):
    """Reject callers presenting a stale token.

    Lenient mode (legacy clients that never fetched a token) allows a missing
    header; strict mode (heartbeat/lifecycle mutations) requires it once the
    session has one.
    """
    if session.session_token is None:
        return
    if token is None:
        if strict:
            raise ApiError(401, "SESSION_TOKEN_REQUIRED",
                           "This session requires the X-Session-Token header.")
        return
    if token != session.session_token:
        raise ApiError(409, "SESSION_CONFLICT",
                       "This interview is active in another tab, browser or device.",
                       details={"active_session_id": session.id, "problem_id": session.problem_id,
                                "status": session.status})


def compute_timer(session: models.Session) -> schemas.TimerState:
    now = utcnow()
    started = as_utc(session.started_at) or as_utc(session.created_at)
    is_paused = session.status == models.SESSION_PAUSED

    if session.status in (models.SESSION_COMPLETED, models.SESSION_CANCELLED,
                          models.SESSION_ABANDONED, models.SESSION_EXPIRED):
        end = as_utc(session.completed_at) or as_utc(session.updated_at) or now
    elif is_paused:
        end = as_utc(session.paused_at) or now
    else:
        end = now

    elapsed = max(0, _seconds_between(started, end) - (session.total_paused_seconds or 0))

    remaining = None
    is_expired = False
    if session.time_limit_minutes:
        remaining = session.time_limit_minutes * 60 - elapsed
        is_expired = remaining <= 0
        remaining = max(0, remaining)

    # Thinking time: gaps between an assistant question and the next user reply.
    # Speaking time heuristic: ~2.5 words/second of the user's messages.
    thinking = 0
    speaking = 0
    prev_assistant_ts = None
    for msg in (session.history or []):
        ts = msg.get("timestamp")
        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        except (ValueError, AttributeError):
            ts_dt = None
        if msg.get("role") == "assistant":
            prev_assistant_ts = ts_dt
        elif msg.get("role") == "user":
            if prev_assistant_ts and ts_dt:
                thinking += max(0, int((as_utc(ts_dt) - as_utc(prev_assistant_ts)).total_seconds()))
            speaking += int(len(str(msg.get("content", "")).split()) / 2.5)
            prev_assistant_ts = None

    return schemas.TimerState(
        mode="countdown" if session.time_limit_minutes else "stopwatch",
        time_limit_minutes=session.time_limit_minutes,
        elapsed_seconds=elapsed,
        remaining_seconds=remaining,
        paused_seconds=session.total_paused_seconds or 0,
        idle_seconds=session.idle_seconds or 0,
        thinking_seconds=min(thinking, elapsed),
        speaking_seconds=min(speaking, elapsed),
        started_at=started,
        is_paused=is_paused,
        is_expired=is_expired,
    )


def to_state_response(session: models.Session, include_token: bool = False) -> schemas.InterviewStateResponse:
    return schemas.InterviewStateResponse(
        session_id=session.id,
        user_id=session.user_id,
        problem_id=session.problem_id,
        status=session.status,
        session_token=session.session_token if include_token else None,
        attempt_number=session.attempt_number or 1,
        lock_version=session.lock_version or 0,
        timer=compute_timer(session),
        last_heartbeat_at=as_utc(session.last_heartbeat_at),
        last_activity_at=as_utc(session.last_activity_at),
        autosave_state=session.autosave_state,
        created_at=as_utc(session.created_at),
    )


def _bump(session: models.Session):
    session.lock_version = (session.lock_version or 0) + 1
    session.updated_at = utcnow()


def sweep_stale_sessions(db: DbSession, user_id: Optional[str] = None):
    """Lazily abandon live sessions whose heartbeat exceeded the recovery window."""
    cutoff = utcnow() - timedelta(seconds=settings.SESSION_RECOVERY_WINDOW_SECONDS)
    query = db.query(models.Session).filter(models.Session.status.in_(models.LIVE_STATUSES))
    if user_id:
        query = query.filter(models.Session.user_id == user_id)
    for s in query.all():
        last_seen = as_utc(s.last_heartbeat_at) or as_utc(s.last_activity_at) or as_utc(s.created_at)
        if last_seen and last_seen < cutoff:
            s.status = models.SESSION_ABANDONED
            s.completed_at = utcnow()
            _bump(s)
            log_event(db, s.id, "abandoned", {"reason": "recovery window exceeded"})
    db.flush()


def get_live_session(db: DbSession, user_id: str) -> Optional[models.Session]:
    sweep_stale_sessions(db, user_id)
    return (
        db.query(models.Session)
        .filter(models.Session.user_id == user_id,
                models.Session.status.in_(models.LIVE_STATUSES))
        .order_by(models.Session.created_at.desc())
        .first()
    )


def start_interview(db: DbSession, req: schemas.InterviewStartRequest,
                    ip_address: Optional[str] = None) -> models.Session:
    problem = db.query(models.Problem).filter(models.Problem.id == req.problem_id).first()
    if not problem:
        raise ApiError(404, "PROBLEM_NOT_FOUND", f"Problem with ID '{req.problem_id}' not found.")

    _ensure_user(db, req.user_id)

    existing = get_live_session(db, req.user_id)
    if existing:
        if not req.takeover:
            raise ApiError(409, "SESSION_CONFLICT",
                           "You already have a live interview. Finish it or pass takeover=true.",
                           details={"active_session_id": existing.id,
                                    "problem_id": existing.problem_id,
                                    "status": existing.status,
                                    "started_at": as_utc(existing.started_at).isoformat() if existing.started_at else None})
        existing.status = models.SESSION_CANCELLED
        existing.completed_at = utcnow()
        _bump(existing)
        log_event(db, existing.id, "cancelled", {"reason": "takeover by new interview"})

    attempt_number = (
        db.query(models.Session)
        .filter(models.Session.user_id == req.user_id,
                models.Session.problem_id == req.problem_id)
        .count()
    ) + 1

    now = utcnow()
    session = models.Session(
        problem_id=req.problem_id,
        user_id=req.user_id,
        status=models.SESSION_ACTIVE,
        history=[],
        canvas_snapshots=[],
        session_token=secrets.token_urlsafe(32),
        browser_id=req.browser_id,
        device_id=req.device_id,
        ip_address=ip_address,
        started_at=now,
        last_heartbeat_at=now,
        last_activity_at=now,
        time_limit_minutes=req.time_limit_minutes or problem.estimated_time,
        attempt_number=attempt_number,
    )
    db.add(session)

    problem.attempts = (problem.attempts or 0) + 1
    problem.success_rate = round((problem.completions or 0) / problem.attempts, 4)

    db.flush()
    log_event(db, session.id, "started", {
        "attempt_number": attempt_number,
        "browser_id": req.browser_id,
        "device_id": req.device_id,
        "ip_address": ip_address,
        "time_limit_minutes": session.time_limit_minutes,
    })
    db.commit()
    db.refresh(session)
    return session


def _require_live(session: models.Session):
    if session.status not in models.LIVE_STATUSES:
        raise ApiError(409, "INVALID_SESSION_STATE",
                       f"Session is '{session.status}'; this operation requires an active or paused interview.")


def heartbeat(db: DbSession, session: models.Session, token: Optional[str],
              req: schemas.HeartbeatRequest) -> schemas.HeartbeatResponse:
    verify_token(session, token, strict=True)
    _require_live(session)

    now = utcnow()
    prev = as_utc(session.last_heartbeat_at) or now
    delta = min(int((now - prev).total_seconds()), settings.SESSION_HEARTBEAT_TIMEOUT_SECONDS)

    session.last_heartbeat_at = now
    if req.is_idle:
        session.idle_seconds = (session.idle_seconds or 0) + max(0, delta)
    else:
        session.last_activity_at = now
    _bump(session)

    timer = compute_timer(session)
    if timer.is_expired and session.status == models.SESSION_ACTIVE:
        finish(db, session, token=None, reason="time limit reached", final_status=models.SESSION_EXPIRED)
        timer = compute_timer(session)
    else:
        db.commit()

    idle_for = _seconds_between(session.last_activity_at, now)
    return schemas.HeartbeatResponse(
        status=session.status,
        server_time=now,
        timer=timer,
        idle_timeout_in=max(0, settings.SESSION_IDLE_TIMEOUT_SECONDS - idle_for),
    )


def pause(db: DbSession, session: models.Session, token: Optional[str]) -> models.Session:
    verify_token(session, token, strict=False)
    if session.status != models.SESSION_ACTIVE:
        raise ApiError(409, "INVALID_SESSION_STATE", f"Cannot pause a '{session.status}' session.")
    session.status = models.SESSION_PAUSED
    session.paused_at = utcnow()
    _bump(session)
    log_event(db, session.id, "paused")
    db.commit()
    db.refresh(session)
    return session


def resume(db: DbSession, session: models.Session, token: Optional[str],
           req: schemas.InterviewResumeRequest, ip_address: Optional[str] = None) -> models.Session:
    """Resume a paused session, or re-attach after a refresh/crash.

    Rotates the session token when the caller proves ownership (matching
    token or same browser_id) or explicitly requests takeover.
    """
    if session.status in (models.SESSION_COMPLETED, models.SESSION_CANCELLED, models.SESSION_EXPIRED):
        raise ApiError(409, "INVALID_SESSION_STATE", f"Cannot resume a '{session.status}' session.")

    same_client = (
        (token and token == session.session_token)
        or (req.browser_id and req.browser_id == session.browser_id)
    )
    if not same_client and not req.takeover:
        raise ApiError(409, "SESSION_CONFLICT",
                       "This interview belongs to another tab/browser/device. Pass takeover=true to take over.",
                       details={"active_session_id": session.id, "problem_id": session.problem_id,
                                "status": session.status})

    now = utcnow()
    if session.status == models.SESSION_PAUSED and session.paused_at:
        session.total_paused_seconds = (session.total_paused_seconds or 0) + \
            _seconds_between(session.paused_at, now)
        session.paused_at = None

    recovered = session.status == models.SESSION_ABANDONED
    session.status = models.SESSION_ACTIVE
    session.session_token = secrets.token_urlsafe(32)   # rotate: invalidates other tabs
    session.browser_id = req.browser_id or session.browser_id
    session.device_id = req.device_id or session.device_id
    session.ip_address = ip_address or session.ip_address
    session.last_heartbeat_at = now
    session.last_activity_at = now
    _bump(session)
    log_event(db, session.id, "recovered" if recovered else "resumed",
              {"takeover": req.takeover, "browser_id": req.browser_id})
    db.commit()
    db.refresh(session)
    return session


def autosave(db: DbSession, session: models.Session, token: Optional[str],
             req: schemas.AutosaveRequest) -> models.Session:
    verify_token(session, token, strict=False)
    _require_live(session)
    now = utcnow()
    if req.autosave_state is not None:
        session.autosave_state = req.autosave_state
    if req.canvas_state is not None:
        snapshots = list(session.canvas_snapshots or [])
        snapshots.append({"turn_id": f"autosave-{int(now.timestamp())}", "canvas_json": req.canvas_state})
        session.canvas_snapshots = snapshots
    session.last_activity_at = now
    session.last_heartbeat_at = now
    _bump(session)
    db.commit()
    db.refresh(session)
    return session


def finish(db: DbSession, session: models.Session, token: Optional[str],
           reason: Optional[str] = None, final_status: str = models.SESSION_COMPLETED) -> models.Session:
    verify_token(session, token, strict=False)
    _require_live(session)

    now = utcnow()
    if session.status == models.SESSION_PAUSED and session.paused_at:
        session.total_paused_seconds = (session.total_paused_seconds or 0) + \
            _seconds_between(session.paused_at, now)
        session.paused_at = None

    session.status = final_status
    session.completed_at = now
    _bump(session)
    log_event(db, session.id, "finished" if final_status == models.SESSION_COMPLETED else final_status,
              {"reason": reason})

    if final_status == models.SESSION_COMPLETED:
        problem = db.query(models.Problem).filter(models.Problem.id == session.problem_id).first()
        if problem:
            problem.completions = (problem.completions or 0) + 1
            if problem.attempts:
                problem.success_rate = round(problem.completions / problem.attempts, 4)
            # Incremental mean of attempt_number across completing sessions
            n = problem.completions
            prev_avg = problem.avg_attempts_to_solve or 0.0
            problem.avg_attempts_to_solve = round((prev_avg * (n - 1) + (session.attempt_number or 1)) / n, 2)

    db.commit()
    db.refresh(session)
    return session


def cancel(db: DbSession, session: models.Session, token: Optional[str],
           reason: Optional[str] = None) -> models.Session:
    verify_token(session, token, strict=False)
    _require_live(session)
    session.status = models.SESSION_CANCELLED
    session.completed_at = utcnow()
    _bump(session)
    log_event(db, session.id, "cancelled", {"reason": reason})
    db.commit()
    db.refresh(session)
    return session
