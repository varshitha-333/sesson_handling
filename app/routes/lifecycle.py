"""Interview engine endpoints (session lifecycle).

Mounted at /api/sessions/* and /api/v1/sessions/* alongside the legacy
session CRUD router. Registered BEFORE the legacy router so literal paths
like /active and /start take precedence over /{session_id}.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, Query
from sqlalchemy.orm import Session

from app import models, schemas, security
from app.database import get_db
from app.errors import ApiError
from app.services import session_engine as engine
from app.services.cache import session_cache

router = APIRouter(
    prefix="/sessions",
    tags=["interview-engine"],
    dependencies=[Depends(security.verify_api_key)],
)


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _get_session_or_404(db: Session, session_id: str) -> models.Session:
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Session with ID '{session_id}' not found.")
    return session


def _invalidate(session_id: str):
    session_cache.invalidate(f"session:{session_id}")


@router.post("/start", response_model=schemas.InterviewStateResponse, status_code=201)
def start_interview(req: schemas.InterviewStartRequest, request: Request,
                    db: Session = Depends(get_db)):
    """Start a new interview. Enforces one live interview per user;
    409 SESSION_CONFLICT unless takeover=true."""
    session = engine.start_interview(db, req, ip_address=_client_ip(request))
    return engine.to_state_response(session, include_token=True)


@router.get("/active", response_model=Optional[schemas.InterviewStateResponse])
def get_active_interview(user_id: str = Query(...), db: Session = Depends(get_db)):
    """Resume-after-refresh/crash discovery: returns the user's live interview
    (active or paused) or null. Token is NOT returned here — call /resume to
    prove ownership and obtain a fresh token."""
    session = engine.get_live_session(db, user_id)
    db.commit()  # persist any lazy sweep transitions
    if not session:
        return None
    return engine.to_state_response(session, include_token=False)


@router.post("/{session_id}/heartbeat", response_model=schemas.HeartbeatResponse)
def heartbeat(session_id: str, req: schemas.HeartbeatRequest,
              x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
              db: Session = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    return engine.heartbeat(db, session, x_session_token, req)


@router.post("/{session_id}/pause", response_model=schemas.InterviewStateResponse)
def pause_interview(session_id: str,
                    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
                    db: Session = Depends(get_db)):
    session = engine.pause(db, _get_session_or_404(db, session_id), x_session_token)
    _invalidate(session_id)
    return engine.to_state_response(session, include_token=False)


@router.post("/{session_id}/resume", response_model=schemas.InterviewStateResponse)
def resume_interview(session_id: str, req: schemas.InterviewResumeRequest, request: Request,
                     x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
                     db: Session = Depends(get_db)):
    """Resume a paused interview, re-attach after refresh, or take over from
    another tab/device (takeover=true). Rotates and returns the session token."""
    session = engine.resume(db, _get_session_or_404(db, session_id), x_session_token,
                            req, ip_address=_client_ip(request))
    _invalidate(session_id)
    return engine.to_state_response(session, include_token=True)


@router.post("/{session_id}/autosave", response_model=schemas.InterviewStateResponse)
def autosave(session_id: str, req: schemas.AutosaveRequest,
             x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
             db: Session = Depends(get_db)):
    session = engine.autosave(db, _get_session_or_404(db, session_id), x_session_token, req)
    _invalidate(session_id)
    return engine.to_state_response(session, include_token=False)


@router.post("/{session_id}/finish", response_model=schemas.InterviewStateResponse)
def finish_interview(session_id: str, req: schemas.FinishRequest = None,
                     x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
                     db: Session = Depends(get_db)):
    session = engine.finish(db, _get_session_or_404(db, session_id), x_session_token,
                            reason=req.reason if req else None)
    _invalidate(session_id)

    from app.services.achievements import check_and_award
    check_and_award(db, session.user_id)
    return engine.to_state_response(session, include_token=False)


@router.post("/{session_id}/cancel", response_model=schemas.InterviewStateResponse)
def cancel_interview(session_id: str, req: schemas.FinishRequest = None,
                     x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
                     db: Session = Depends(get_db)):
    session = engine.cancel(db, _get_session_or_404(db, session_id), x_session_token,
                            reason=req.reason if req else None)
    _invalidate(session_id)
    return engine.to_state_response(session, include_token=False)


@router.get("/{session_id}/timer", response_model=schemas.TimerState)
def get_timer(session_id: str, db: Session = Depends(get_db)):
    """Timer state: countdown/stopwatch, elapsed, paused, idle,
    thinking/speaking split."""
    return engine.compute_timer(_get_session_or_404(db, session_id))


@router.get("/{session_id}/state", response_model=schemas.InterviewStateResponse)
def get_state(session_id: str, db: Session = Depends(get_db)):
    return engine.to_state_response(_get_session_or_404(db, session_id), include_token=False)
