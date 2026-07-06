"""History, progress-tracking and dashboard aggregation."""

from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session as DbSession

from app import models, schemas
from app.services.session_engine import compute_timer, as_utc


def _history_item(session: models.Session, problem: Optional[models.Problem],
                  evaluation: Optional[models.Evaluation],
                  feedback: Optional[models.Feedback]) -> schemas.HistoryItem:
    return schemas.HistoryItem(
        session_id=session.id,
        problem_id=session.problem_id,
        problem_title=problem.title if problem else None,
        difficulty=problem.difficulty if problem else None,
        status=session.status,
        attempt_number=session.attempt_number or 1,
        duration_seconds=compute_timer(session).elapsed_seconds,
        composite_score=evaluation.composite_score if evaluation else None,
        feedback_summary=feedback.summary if feedback else None,
        created_at=as_utc(session.created_at),
        completed_at=as_utc(session.completed_at),
    )


def get_history(db: DbSession, user_id: str, status: Optional[str] = None,
                limit: int = 20, offset: int = 0) -> Tuple[List[schemas.HistoryItem], int]:
    query = db.query(models.Session).filter(models.Session.user_id == user_id)
    if status:
        query = query.filter(models.Session.status == status)
    total = query.count()
    sessions = query.order_by(models.Session.created_at.desc()).offset(offset).limit(limit).all()

    ids = [s.id for s in sessions]
    problem_ids = {s.problem_id for s in sessions}
    problems = {p.id: p for p in db.query(models.Problem).filter(models.Problem.id.in_(problem_ids)).all()} if problem_ids else {}
    evals = {e.session_id: e for e in db.query(models.Evaluation).filter(models.Evaluation.session_id.in_(ids)).all()} if ids else {}
    feedbacks = {f.session_id: f for f in db.query(models.Feedback).filter(models.Feedback.session_id.in_(ids)).all()} if ids else {}

    items = [_history_item(s, problems.get(s.problem_id), evals.get(s.id), feedbacks.get(s.id))
             for s in sessions]
    return items, total


def get_history_detail(db: DbSession, session: models.Session) -> schemas.HistoryDetail:
    problem = db.query(models.Problem).filter(models.Problem.id == session.problem_id).first()
    evaluation = db.query(models.Evaluation).filter(models.Evaluation.session_id == session.id).first()
    feedback = db.query(models.Feedback).filter(models.Feedback.session_id == session.id).first()
    events = (db.query(models.SessionEvent)
              .filter(models.SessionEvent.session_id == session.id)
              .order_by(models.SessionEvent.created_at.asc()).all())

    base = _history_item(session, problem, evaluation, feedback)

    feedback_resp = None
    if feedback:
        feedback_resp = schemas.FeedbackResponse(
            id=feedback.id, session_id=feedback.session_id,
            scores=schemas.FeedbackScores(**feedback.scores),
            strengths=feedback.strengths, improvements=feedback.improvements,
            summary=feedback.summary,
            architecture_feedback=feedback.architecture_feedback,
            communication_feedback=feedback.communication_feedback,
            feedback_metadata=feedback.feedback_metadata,
            created_at=feedback.created_at,
        )

    return schemas.HistoryDetail(
        **base.model_dump(),
        history=[schemas.Message(role=m.get("role", ""), content=m.get("content", ""),
                                 timestamp=m.get("timestamp", "")) for m in (session.history or [])],
        canvas_snapshots=[schemas.CanvasSnapshot(turn_id=c.get("turn_id", ""),
                                                 canvas_json=c.get("canvas_json", {}))
                          for c in (session.canvas_snapshots or [])],
        events=[{"event_type": e.event_type, "details": e.details,
                 "created_at": as_utc(e.created_at).isoformat()} for e in events],
        feedback=feedback_resp,
        evaluation=schemas.EvaluationResponse.model_validate(evaluation) if evaluation else None,
    )


def _streaks(completion_dates: List[date]) -> Tuple[int, int]:
    if not completion_dates:
        return 0, 0
    days = sorted(set(completion_dates))
    longest = current_run = 1
    for prev, cur in zip(days, days[1:]):
        current_run = current_run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, current_run)

    today = datetime.now(timezone.utc).date()
    current = 0
    if days[-1] in (today, today - timedelta(days=1)):
        current = 1
        for prev, cur in zip(reversed(days[:-1]), reversed(days[1:])):
            if (cur - prev).days == 1:
                current += 1
            else:
                break
    return current, longest


def get_dashboard(db: DbSession, user_id: str) -> schemas.DashboardResponse:
    sessions = db.query(models.Session).filter(models.Session.user_id == user_id).all()
    evaluations = (db.query(models.Evaluation)
                   .filter(models.Evaluation.user_id == user_id)
                   .order_by(models.Evaluation.created_at.asc()).all())

    completed = [s for s in sessions if s.status == models.SESSION_COMPLETED]
    attempted_problems = {s.problem_id for s in sessions}
    solved_problems = {s.problem_id for s in completed}

    avg_score = round(sum(e.composite_score for e in evaluations) / len(evaluations), 2) if evaluations else None
    best_score = round(max((e.composite_score for e in evaluations), default=0.0), 2) if evaluations else None
    durations = [e.time_taken_seconds for e in evaluations if e.time_taken_seconds]
    avg_time = round(sum(durations) / len(durations), 1) if durations else None

    # Topic strengths from problem category/key_concepts weighted by composite score
    problems = {p.id: p for p in db.query(models.Problem)
                .filter(models.Problem.id.in_({e.problem_id for e in evaluations})).all()} if evaluations else {}
    topic_scores = defaultdict(list)
    company_scores = defaultdict(list)
    for e in evaluations:
        p = problems.get(e.problem_id)
        if not p:
            continue
        topics = [p.category] + list(p.key_concepts or [])
        for t in topics:
            if t:
                topic_scores[t].append(e.composite_score)
        if p.company:
            company_scores[p.company].append(e.composite_score)

    topic_stats = sorted(
        (schemas.TopicStat(topic=t, avg_score=round(sum(v) / len(v), 2), samples=len(v))
         for t, v in topic_scores.items()),
        key=lambda s: s.avg_score,
    )
    weak = [t for t in topic_stats if t.avg_score < 60][:5] or topic_stats[:3]
    strong = [t for t in reversed(topic_stats) if t.avg_score >= 60][:5]

    current_streak, longest_streak = _streaks(
        [as_utc(s.completed_at).date() for s in completed if s.completed_at])

    # Readiness: recent performance (last 10 evals) blended with breadth
    recent = evaluations[-10:]
    recent_avg = sum(e.composite_score for e in recent) / len(recent) if recent else 0.0
    breadth = min(1.0, len(solved_problems) / 10)  # 10 distinct problems = full breadth credit
    readiness = round(0.7 * recent_avg + 30 * breadth, 1)

    learning_curve = []
    by_day = defaultdict(list)
    for e in evaluations:
        by_day[as_utc(e.created_at).date().isoformat()].append(e.composite_score)
    for day in sorted(by_day):
        learning_curve.append({"date": day, "avg_score": round(sum(by_day[day]) / len(by_day[day]), 2)})

    return schemas.DashboardResponse(
        user_id=user_id,
        problems_solved=len(solved_problems),
        problems_attempted=len(attempted_problems),
        completion_rate=round(len(completed) / len(sessions), 4) if sessions else 0.0,
        success_rate=round(len(solved_problems) / len(attempted_problems), 4) if attempted_problems else 0.0,
        average_score=avg_score,
        average_time_seconds=avg_time,
        personal_best_score=best_score,
        weak_topics=weak,
        strong_topics=strong,
        current_streak_days=current_streak,
        longest_streak_days=longest_streak,
        interview_readiness=min(100.0, readiness),
        company_readiness={c: round(sum(v) / len(v), 1) for c, v in company_scores.items()},
        learning_curve=learning_curve,
    )


def problem_average_stats(db: DbSession, problem_id: str) -> dict:
    """Average candidate statistics for a problem (avg time, avg score, best time)."""
    evals = db.query(models.Evaluation).filter(models.Evaluation.problem_id == problem_id).all()
    times = [e.time_taken_seconds for e in evals if e.time_taken_seconds]
    return {
        "problem_id": problem_id,
        "candidates_evaluated": len(evals),
        "avg_time_seconds": round(sum(times) / len(times), 1) if times else None,
        "best_time_seconds": min(times) if times else None,
        "avg_composite_score": round(sum(e.composite_score for e in evals) / len(evals), 2) if evals else None,
    }
