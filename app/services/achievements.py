"""Achievement rules + notification fan-out.

check_and_award() is called after an interview finishes and after an
evaluation is computed. Awards are idempotent (unique constraint on
user_id + achievement_id).
"""

from sqlalchemy.orm import Session as DbSession

from app import models

DEFAULT_ACHIEVEMENTS = [
    {"id": "first-interview", "name": "First Steps",
     "description": "Started your first interview.", "icon": "🎬"},
    {"id": "first-completion", "name": "Finisher",
     "description": "Completed your first interview.", "icon": "✅"},
    {"id": "five-completions", "name": "Marathoner",
     "description": "Completed 5 interviews.", "icon": "🏃"},
    {"id": "high-scorer", "name": "High Scorer",
     "description": "Scored 85+ on an interview.", "icon": "🏆"},
    {"id": "perfectionist", "name": "Perfectionist",
     "description": "Scored 95+ on an interview.", "icon": "💎"},
    {"id": "streak-3", "name": "On a Roll",
     "description": "Completed interviews on 3 consecutive days.", "icon": "🔥"},
    {"id": "explorer", "name": "Explorer",
     "description": "Attempted problems in 3 different categories.", "icon": "🧭"},
]


def seed_achievements(db: DbSession):
    existing = {a.id for a in db.query(models.Achievement.id).all()}
    for spec in DEFAULT_ACHIEVEMENTS:
        if spec["id"] not in existing:
            db.add(models.Achievement(**spec))
    db.commit()


def _award(db: DbSession, user_id: str, achievement_id: str) -> bool:
    exists = db.query(models.UserAchievement).filter_by(
        user_id=user_id, achievement_id=achievement_id).first()
    if exists:
        return False
    achievement = db.query(models.Achievement).filter_by(id=achievement_id).first()
    if not achievement:
        return False
    db.add(models.UserAchievement(user_id=user_id, achievement_id=achievement_id))
    db.add(models.Notification(
        user_id=user_id, type="achievement",
        title=f"Achievement unlocked: {achievement.name}",
        body=achievement.description,
    ))
    return True


def check_and_award(db: DbSession, user_id: str):
    """Evaluate all rules for a user; awards are idempotent. Commits."""
    if not user_id:
        return

    sessions = db.query(models.Session).filter(models.Session.user_id == user_id).all()
    completed = [s for s in sessions if s.status == models.SESSION_COMPLETED]

    if sessions:
        _award(db, user_id, "first-interview")
    if completed:
        _award(db, user_id, "first-completion")
    if len(completed) >= 5:
        _award(db, user_id, "five-completions")

    best = (db.query(models.Evaluation)
            .filter(models.Evaluation.user_id == user_id)
            .order_by(models.Evaluation.composite_score.desc()).first())
    if best and best.composite_score >= 85:
        _award(db, user_id, "high-scorer")
    if best and best.composite_score >= 95:
        _award(db, user_id, "perfectionist")

    from app.services.analytics import _streaks
    from app.services.session_engine import as_utc
    current, longest = _streaks([as_utc(s.completed_at).date() for s in completed if s.completed_at])
    if longest >= 3:
        _award(db, user_id, "streak-3")

    categories = set()
    if sessions:
        problem_ids = {s.problem_id for s in sessions}
        categories = {p.category for p in db.query(models.Problem)
                      .filter(models.Problem.id.in_(problem_ids)).all() if p.category}
    if len(categories) >= 3:
        _award(db, user_id, "explorer")

    db.commit()
