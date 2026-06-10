from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

# User Schemas
class UserBase(BaseModel):
    id: str = Field(..., description="Unique identifier for the user (e.g. auth sub or username)")
    name: Optional[str] = None
    email: Optional[str] = None

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    created_at: datetime

    class Config:
        from_attributes = True


# Problem Schemas
class ProblemBase(BaseModel):
    id: str = Field(..., description="Unique slug for the problem, e.g., 'design-parking-lot'")
    title: str
    description: str
    requirements: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)

class ProblemCreate(ProblemBase):
    pass

class ProblemResponse(ProblemBase):
    class Config:
        from_attributes = True

# Message Schema (for chat history)
class Message(BaseModel):
    role: str = Field(..., description="Either 'user' or 'assistant'")
    content: str
    timestamp: str = Field(..., description="ISO-8601 formatted timestamp")

# Canvas Snapshot Schema
class CanvasSnapshot(BaseModel):
    turn_id: str
    canvas_json: Dict[str, Any] = Field(..., description="Canvas layout JSON containing nodes and edges")

# Session Response Schema (matching Person C's request)
class SessionResponse(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    status: str = Field("active", description="Status of the session, e.g., 'active' or 'completed'")
    history: List[Message]
    canvas_snapshots: List[CanvasSnapshot]

    class Config:
        from_attributes = True

# Create Session Request Schema
class SessionCreate(BaseModel):
    problem_id: str
    user_id: Optional[str] = None

# Update Session Request Schema
class SessionUpdate(BaseModel):
    status: str = Field(..., description="New status value, e.g., 'active' or 'completed'")

# Post Turn Request Schema
class TurnRequest(BaseModel):
    text: str = Field(..., description="User message/reply")
    c1Snapshot: Optional[Dict[str, Any]] = Field(None, description="Optional canvas diagram state snapshot")


# Feedback Schemas
class FeedbackScores(BaseModel):
    requirements: int
    scalability: int
    reliability: int
    communication: int
    tradeoffs: int

class FeedbackCreate(BaseModel):
    scores: FeedbackScores
    strengths: List[str]
    improvements: List[str]
    summary: str

class FeedbackResponse(BaseModel):
    id: str
    session_id: str
    scores: FeedbackScores
    strengths: List[str]
    improvements: List[str]
    summary: str
    created_at: datetime

    class Config:
        from_attributes = True

