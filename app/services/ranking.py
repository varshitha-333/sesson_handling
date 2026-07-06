"""Ranking engine.

An Evaluation row is created whenever C2 feedback is stored for a completed
session. The composite score is NOT a raw average — it blends dimension
scores with time, retries and difficulty:

    dimension scores (0-100, from C2 feedback 1-5 scale x 20):
        technical      = mean(scalability, reliability) x 20
        correctness    = requirements x 20
        communication  = communication x 20
        optimization   = tradeoffs x 20
        confidence     = 100 - 12 x stddev(all five 1-5 scores)
                         (consistent performance across dimensions reads as
                          confidence; erratic scoring reads as guessing)

    base = 0.30*technical + 0.20*correctness + 0.20*communication
         + 0.15*optimization + 0.15*confidence

    time_multiplier   = clamp(1.05 - 0.10 * max(0, actual/expected - 1), 0.70, 1.05)
                        (small bonus for finishing on time, growing penalty
                         for overtime; expected = problem.estimated_time)
    retry_multiplier  = max(0.85, 1 - 0.05 * (attempt_number - 1))
    difficulty_multiplier: Easy 0.90 | Medium 1.00 | Hard 1.15

    composite = clamp(base * time * retry * difficulty, 0, 100)

Leaderboards rank users by average composite score in the scope window,
ties broken by interviews completed.
"""

import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app import models, schemas

DIFFICULTY_MULTIPLIERS = {"easy": 0.90, "medium": 1.00, "hard": 1.15}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def compute_evaluation(db: DbSession, session: models.Session,
                       feedback: models.Feedback) -> Optional[models.Evaluation]:
    """Create/refresh the Evaluation for a session once feedback scores exist."""
    if not session.user_id:
        return None  # anonymous sessions are not ranked

    scores = feedback.scores or {}
    req = int(scores.get("requirements", 3))
    sca = int(scores.get("scalability", 3))
    rel = int(scores.get("reliability", 3))
    com = int(scores.get("communication", 3))
    tra = int(scores.get("tradeoffs", 3))

    technical = (sca + rel) / 2 * 20
    correctness = req * 20
    communication = com * 20
    optimization = tra * 20
    spread = statistics.pstdev([req, sca, rel, com, tra])
    confidence = _clamp(100 - 12 * spread, 0, 100)

    base = (0.30 * technical + 0.20 * correctness + 0.20 * communication
            + 0.15 * optimization + 0.15 * confidence)

    problem = db.query(models.Problem).filter(models.Problem.id == session.problem_id).first()
    expected_seconds = (problem.estimated_time if problem else 45) * 60

    from app.services.session_engine import compute_timer
    time_taken = compute_timer(session).elapsed_seconds

    over_ratio = max(0.0, time_taken / expected_seconds - 1) if expected_seconds else 0.0
    time_mult = _clamp(1.05 - 0.10 * over_ratio, 0.70, 1.05)
    retry_count = max(0, (session.attempt_number or 1) - 1)
    retry_mult = max(0.85, 1 - 0.05 * retry_count)
    diff_mult = DIFFICULTY_MULTIPLIERS.get((problem.difficulty if problem else "Medium").lower(), 1.0)

    composite = round(_clamp(base * time_mult * retry_mult * diff_mult, 0, 100), 2)

    evaluation = db.query(models.Evaluation).filter(
        models.Evaluation.session_id == session.id).first()
    if not evaluation:
        evaluation = models.Evaluation(session_id=session.id, user_id=session.user_id,
                                       problem_id=session.problem_id)
        db.add(evaluation)

    evaluation.technical_score = round(technical, 2)
    evaluation.communication_score = round(communication, 2)
    evaluation.correctness_score = round(correctness, 2)
    evaluation.optimization_score = round(optimization, 2)
    evaluation.confidence_score = round(confidence, 2)
    evaluation.time_taken_seconds = time_taken
    evaluation.retry_count = retry_count
    evaluation.difficulty_multiplier = diff_mult
    evaluation.composite_score = composite
    db.flush()
    return evaluation


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------

def _window(scope: str) -> Optional[datetime]:
    now = datetime.now(timezone.utc)
    if scope == "weekly":
        return now - timedelta(days=7)
    if scope == "monthly":
        return now - timedelta(days=30)
    return None


def _aggregate_query(db: DbSession, since: Optional[datetime] = None,
                     problem_id: Optional[str] = None, company: Optional[str] = None):
    q = (
        db.query(
            models.Evaluation.user_id.label("user_id"),
            func.avg(models.Evaluation.composite_score).label("avg_score"),
            func.max(models.Evaluation.composite_score).label("best_score"),
            func.count(models.Evaluation.id).label("completed"),
        )
    )
    if company:
        q = q.join(models.Problem, models.Problem.id == models.Evaluation.problem_id) \
             .filter(func.lower(models.Problem.company) == company.lower())
    if problem_id:
        q = q.filter(models.Evaluation.problem_id == problem_id)
    if since:
        q = q.filter(models.Evaluation.created_at >= since.replace(tzinfo=None))
    return q.group_by(models.Evaluation.user_id) \
            .order_by(func.avg(models.Evaluation.composite_score).desc(),
                      func.count(models.Evaluation.id).desc())


def leaderboard(db: DbSession, scope: str = "global", problem_id: Optional[str] = None,
                company: Optional[str] = None, limit: int = 20, offset: int = 0
                ) -> Tuple[List[schemas.LeaderboardEntry], int]:
    since = _window(scope)
    rows = _aggregate_query(db, since, problem_id, company).all()
    total = len(rows)
    names = dict(db.query(models.User.id, models.User.name).all())
    entries = [
        schemas.LeaderboardEntry(
            rank=i + 1,
            user_id=r.user_id,
            user_name=names.get(r.user_id),
            composite_score=round(float(r.avg_score), 2),
            interviews_completed=int(r.completed),
            best_score=round(float(r.best_score), 2),
        )
        for i, r in enumerate(rows)
    ]
    return entries[offset:offset + limit], total


def user_rank(db: DbSession, user_id: str, scope: str = "global",
              problem_id: Optional[str] = None, company: Optional[str] = None
              ) -> schemas.UserRankResponse:
    since = _window(scope)
    rows = _aggregate_query(db, since, problem_id, company).all()
    total = len(rows)
    rank = None
    score = None
    for i, r in enumerate(rows):
        if r.user_id == user_id:
            rank = i + 1
            score = round(float(r.avg_score), 2)
            break

    percentile = None
    if rank is not None and total > 0:
        percentile = round((total - rank) / total * 100, 1)

    # Rank change: compare against the previous equal-length window
    rank_change = None
    if scope in ("weekly", "monthly") and rank is not None:
        span = timedelta(days=7 if scope == "weekly" else 30)
        prev_rows = (
            _aggregate_query(db, since - span, problem_id, company)
            .filter(models.Evaluation.created_at < since.replace(tzinfo=None))
            .all()
        )
        prev_rank = next((i + 1 for i, r in enumerate(prev_rows) if r.user_id == user_id), None)
        if prev_rank is not None:
            rank_change = prev_rank - rank  # positive = climbed

    return schemas.UserRankResponse(
        user_id=user_id,
        scope=scope,
        scope_id=problem_id or company,
        rank=rank,
        total_ranked=total,
        percentile=percentile,
        composite_score=score,
        rank_change=rank_change,
    )
