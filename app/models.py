import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, JSON, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from app.database import Base

class Problem(Base):
    __tablename__ = "problems"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(JSON, nullable=False, default=list)
    constraints = Column(JSON, nullable=False, default=list)

    # Metadata & Auditing columns
    difficulty = Column(String, nullable=False, default="Medium")
    category = Column(String, nullable=False, default="General", index=True)
    estimated_time = Column(Integer, nullable=False, default=45)
    status = Column(String, nullable=False, default="published", index=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String, nullable=False, default="admin")
    updated_by = Column(String, nullable=False, default="admin")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    sessions = relationship("Session", back_populates="problem", cascade="all, delete-orphan")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    action = Column(String, nullable=False)  # "CREATE", "UPDATE", "DELETE"
    target_id = Column(String, nullable=False, index=True)
    target_title = Column(String, nullable=True)
    performed_by = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    sessions = relationship("Session", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    problem_id = Column(String, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, nullable=False, default="active")
    
    # JSON history storage
    history = Column(JSON, nullable=False, default=list)
    canvas_snapshots = Column(JSON, nullable=False, default=list)
    
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    problem = relationship("Problem", back_populates="sessions")
    user = relationship("User", back_populates="sessions")


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, unique=True)
    scores = Column(JSON, nullable=False)  # dict: {requirements, scalability, reliability, communication, tradeoffs}
    strengths = Column(JSON, nullable=False, default=list)  # list of strings
    improvements = Column(JSON, nullable=False, default=list)  # list of strings
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    session = relationship("Session", backref="feedback_record")
