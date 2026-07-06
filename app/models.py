import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, JSON, DateTime, ForeignKey, Integer, Float,
    Boolean, UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class Problem(Base):
    __tablename__ = "problems"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(JSON, nullable=False, default=dict)
    constraints = Column(JSON, nullable=False, default=list)

    # Classification
    difficulty = Column(String, nullable=False, default="Medium", index=True)
    category = Column(String, nullable=False, default="General", index=True)
    subcategory = Column(String, nullable=True)
    estimated_time = Column(Integer, nullable=False, default=45)  # minutes
    # Live Neon column is NOT NULL DEFAULT 'Practice' — keep the model compatible
    company = Column(String, nullable=False, default="Practice", index=True)
    status = Column(String, nullable=False, default="published", index=True)

    # Meta (learning context)
    interview_round = Column(String, nullable=True)  # e.g. "phone-screen", "onsite"
    key_concepts = Column(JSON, nullable=False, default=list)       # list[str]
    similar_problems = Column(JSON, nullable=False, default=list)   # list[str] problem ids
    why_this_problem = Column(Text, nullable=True)
    what_youll_learn = Column(JSON, nullable=False, default=list)   # list[str]
    next_level_problems = Column(JSON, nullable=False, default=list)  # list[str] problem ids
    sources = Column(JSON, nullable=False, default=list)            # list[str] URLs/references

    # Stats (denormalized; maintained by session engine / rating endpoints)
    attempts = Column(Integer, nullable=False, default=0)
    completions = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=False, default=0.0)        # completions/attempts
    avg_rating = Column(Float, nullable=False, default=0.0)          # 1-5
    rating_count = Column(Integer, nullable=False, default=0)
    bookmark_count = Column(Integer, nullable=False, default=0)
    avg_attempts_to_solve = Column(Float, nullable=False, default=0.0)

    # Auditing
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String, nullable=False, default="admin")
    updated_by = Column(String, nullable=False, default="admin")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    sessions = relationship("Session", back_populates="problem", cascade="all, delete-orphan")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True, default=new_uuid)
    action = Column(String, nullable=False)  # "CREATE", "UPDATE", "DELETE"
    target_id = Column(String, nullable=False, index=True)
    target_title = Column(String, nullable=True)
    performed_by = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    sessions = relationship("Session", back_populates="user")


# Session lifecycle statuses used by the interview engine.
SESSION_ACTIVE = "active"
SESSION_PAUSED = "paused"
SESSION_COMPLETED = "completed"
SESSION_CANCELLED = "cancelled"
SESSION_ABANDONED = "abandoned"
SESSION_EXPIRED = "expired"
LIVE_STATUSES = (SESSION_ACTIVE, SESSION_PAUSED)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_status", "user_id", "status"),
        Index("ix_sessions_problem_id", "problem_id"),
    )

    id = Column(String, primary_key=True, index=True, default=new_uuid)
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, nullable=False, default=SESSION_ACTIVE)

    # JSON history storage (shape locked by the C2 contract — do not retype)
    history = Column(JSON, nullable=False, default=list)
    canvas_snapshots = Column(JSON, nullable=False, default=list)

    # Concurrency / device binding (interview engine)
    session_token = Column(String, nullable=True, index=True)
    browser_id = Column(String, nullable=True)
    device_id = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    lock_version = Column(Integer, nullable=False, default=0)  # optimistic locking

    # Liveness / timers
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    last_activity_at = Column(DateTime, nullable=True)
    total_paused_seconds = Column(Integer, nullable=False, default=0)
    idle_seconds = Column(Integer, nullable=False, default=0)
    time_limit_minutes = Column(Integer, nullable=True)  # countdown; None = stopwatch only
    attempt_number = Column(Integer, nullable=False, default=1)

    # Crash recovery scratch state (frontend-defined blob: notes, draft answer, timer UI…)
    autosave_state = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    problem = relationship("Problem", back_populates="sessions")
    user = relationship("User", back_populates="sessions")
    events = relationship("SessionEvent", back_populates="session", cascade="all, delete-orphan")


class SessionEvent(Base):
    """Activity log for a session (start/pause/resume/heartbeat-timeout/finish/…)."""
    __tablename__ = "session_events"

    id = Column(String, primary_key=True, default=new_uuid)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    session = relationship("Session", back_populates="events")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String, primary_key=True, index=True, default=new_uuid)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True)
    scores = Column(JSON, nullable=False)  # {requirements, scalability, reliability, communication, tradeoffs}
    strengths = Column(JSON, nullable=False, default=list)
    improvements = Column(JSON, nullable=False, default=list)
    summary = Column(Text, nullable=False)

    # C2 Feedback Contract superset fields ("metadata" column name kept for compatibility)
    architecture_feedback = Column(JSON, nullable=True)
    communication_feedback = Column(JSON, nullable=True)
    feedback_metadata = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)

    session = relationship("Session", backref="feedback_record")


class Evaluation(Base):
    """Per-completed-interview scoring record feeding the ranking engine."""
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_problem_score", "problem_id", "composite_score"),
        Index("ix_evaluations_user_created", "user_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=new_uuid)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)

    technical_score = Column(Float, nullable=False, default=0.0)      # 0-100
    communication_score = Column(Float, nullable=False, default=0.0)  # 0-100
    correctness_score = Column(Float, nullable=False, default=0.0)    # 0-100
    optimization_score = Column(Float, nullable=False, default=0.0)   # 0-100
    confidence_score = Column(Float, nullable=False, default=0.0)     # 0-100
    time_taken_seconds = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    difficulty_multiplier = Column(Float, nullable=False, default=1.0)
    composite_score = Column(Float, nullable=False, default=0.0, index=True)  # 0-100 weighted

    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)


class ProblemRating(Base):
    __tablename__ = "problem_ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_rating_user_problem"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rating_range"),
    )

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    created_at = Column(DateTime, nullable=False, default=utcnow)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "problem_id", name="uq_bookmark_user_problem"),)

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class RecentlyViewed(Base):
    __tablename__ = "recently_viewed"
    __table_args__ = (UniqueConstraint("user_id", "problem_id", name="uq_recent_user_problem"),)

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False, index=True)
    viewed_at = Column(DateTime, nullable=False, default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String, nullable=False, default="info")  # info|achievement|ranking|reminder
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(String, primary_key=True)  # slug, e.g. "first-interview"
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),)

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    achievement_id = Column(String, ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False)
    earned_at = Column(DateTime, nullable=False, default=utcnow)

    achievement = relationship("Achievement")


class DailyChallenge(Base):
    __tablename__ = "daily_challenges"

    id = Column(String, primary_key=True, default=new_uuid)
    challenge_date = Column(String, nullable=False, unique=True, index=True)  # "YYYY-MM-DD"
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    problem = relationship("Problem")
