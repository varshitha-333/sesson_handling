from typing import List, Dict, Any, Optional, Generic, TypeVar, Union
from datetime import datetime
from pydantic import BaseModel, Field, conint

# ---------------------------------------------------------------------------
# Pagination / envelope
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int
    returned: int
    has_more: bool


class PaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    meta: PageMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------------------------------------------------------------------------
# User Schemas
# ---------------------------------------------------------------------------

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


# ─── Authentication Schemas ──────────────────────────────────────────────────

class UserRegister(BaseModel):
    name: str = Field(..., min_length=1, description="Display name")
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=6, description="Password (min 6 characters)")


class UserLogin(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class AuthUserResponse(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    auth_provider: str = "local"
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Problem Schemas (new catalog schema: normalized lookups + flat stats)
# ---------------------------------------------------------------------------

class ProblemMeta(BaseModel):
    interview_round: Optional[str] = None
    key_concepts: List[str] = Field(default_factory=list)
    similar_problems: List[str] = Field(default_factory=list)
    why_this_problem: Optional[str] = None
    what_youll_learn: List[str] = Field(default_factory=list)
    next_level_problems: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)


class ProblemStats(BaseModel):
    attempts: int = 0
    completions: int = 0
    success_rate: float = 0.0
    avg_rating: float = 0.0
    rating_count: int = 0
    bookmark_count: int = 0
    avg_attempts_to_solve: float = 0.0


class ProblemBase(BaseModel):
    id: str = Field(..., description="Unique slug for the problem, e.g., 'design-parking-lot'")
    title: str
    description: str
    # The live catalog stores several shapes: dict of str->str, dict of
    # str->list[str] (e.g. {"functional": [...], "deliverables": [...]}),
    # or a plain list of strings. Accept all of them.
    requirements: Union[Dict[str, Any], List[str]] = Field(default_factory=dict)
    constraints: Union[List[str], Dict[str, Any]] = Field(default_factory=list)
    difficulty: str = "Medium"
    category: str = "General"
    subcategory: Optional[str] = None
    estimated_time: int = 45
    company: Optional[str] = None
    status: str = "published"


class ProblemCreate(ProblemBase):
    meta: ProblemMeta = Field(default_factory=ProblemMeta)


class ProblemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[Union[Dict[str, Any], List[str]]] = None
    constraints: Optional[Union[List[str], Dict[str, Any]]] = None
    difficulty: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    estimated_time: Optional[int] = None
    company: Optional[str] = None
    status: Optional[str] = None
    # Meta fields (flat, all optional)
    interview_round: Optional[str] = None
    key_concepts: Optional[List[str]] = None
    similar_problems: Optional[List[str]] = None
    why_this_problem: Optional[str] = None
    what_youll_learn: Optional[List[str]] = None
    next_level_problems: Optional[List[str]] = None
    sources: Optional[List[str]] = None


class ProblemResponse(ProblemBase):
    meta: ProblemMeta
    stats: ProblemStats
    version: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    # Per-user flags (populated when user_id supplied on list/read)
    bookmarked: Optional[bool] = None
    completed: Optional[bool] = None

    class Config:
        from_attributes = True


class RatingRequest(BaseModel):
    user_id: str
    rating: conint(ge=1, le=5)


class BookmarkRequest(BaseModel):
    user_id: str


class AuditLogResponse(BaseModel):
    id: str
    action: str
    target_id: str
    target_title: Optional[str] = None
    performed_by: str
    details: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Message / Canvas (C2 contract shapes — locked)
# ---------------------------------------------------------------------------

class Message(BaseModel):
    role: str = Field(..., description="Either 'user' or 'assistant'")
    content: str
    timestamp: str = Field(..., description="ISO-8601 formatted timestamp")


class CanvasSnapshot(BaseModel):
    turn_id: str
    canvas_json: Dict[str, Any] = Field(..., description="Canvas layout JSON containing nodes and edges")


# ---------------------------------------------------------------------------
# Session Schemas (legacy + interview engine)
# ---------------------------------------------------------------------------

class SessionResponse(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    problem_id: Optional[str] = None
    created_at: Optional[datetime] = None
    status: str = Field("active", description="active|paused|completed|cancelled|abandoned|expired")
    history: List[Message]
    canvas_snapshots: List[CanvasSnapshot]

    class Config:
        from_attributes = True


class SessionCreate(BaseModel):
    problem_id: str
    user_id: Optional[str] = None


class SessionUpdate(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID for ownership verification")
    status: Optional[str] = Field(None, description="New status value, e.g., 'active' or 'completed'")
    canvas_state: Optional[Dict[str, Any]] = Field(None, description="Optional canvas layout snapshot containing node positions")


class TurnRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID for ownership verification")
    text: str = Field(..., description="User message/reply")
    c1Snapshot: Optional[Dict[str, Any]] = Field(None, description="Optional canvas diagram state snapshot")


# --- Interview engine ---

class TimerState(BaseModel):
    mode: str = Field("stopwatch", description="'countdown' when a time limit is set, else 'stopwatch'")
    time_limit_minutes: Optional[int] = None
    elapsed_seconds: int = 0            # active (unpaused) seconds
    remaining_seconds: Optional[int] = None
    paused_seconds: int = 0
    idle_seconds: int = 0
    thinking_seconds: int = 0           # gaps between assistant question and user reply
    speaking_seconds: int = 0           # heuristic: user message length based
    started_at: Optional[datetime] = None
    is_paused: bool = False
    is_expired: bool = False


class InterviewStartRequest(BaseModel):
    problem_id: str
    user_id: str
    browser_id: Optional[str] = None
    device_id: Optional[str] = None
    time_limit_minutes: Optional[int] = Field(None, ge=1, le=240)
    takeover: bool = Field(False, description="Cancel/steal any existing live interview for this user")


class InterviewResumeRequest(BaseModel):
    browser_id: Optional[str] = None
    device_id: Optional[str] = None
    takeover: bool = False


class HeartbeatRequest(BaseModel):
    browser_id: Optional[str] = None
    is_idle: bool = False


class AutosaveRequest(BaseModel):
    autosave_state: Optional[Dict[str, Any]] = None
    canvas_state: Optional[Dict[str, Any]] = None


class FinishRequest(BaseModel):
    reason: Optional[str] = None


class InterviewStateResponse(BaseModel):
    session_id: str
    user_id: Optional[str] = None
    problem_id: str
    status: str
    session_token: Optional[str] = None   # only returned to the owning client
    attempt_number: int = 1
    lock_version: int = 0
    timer: TimerState
    last_heartbeat_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    autosave_state: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class SessionConflict(BaseModel):
    code: str = "SESSION_CONFLICT"
    message: str
    active_session_id: str
    problem_id: str
    status: str
    started_at: Optional[datetime] = None


class HeartbeatResponse(BaseModel):
    status: str
    server_time: datetime
    timer: TimerState
    idle_timeout_in: Optional[int] = None


# ---------------------------------------------------------------------------
# Feedback Schemas (C2 contract — locked shapes)
# ---------------------------------------------------------------------------

class FeedbackScores(BaseModel):
    requirements: conint(ge=1, le=5)
    scalability: conint(ge=1, le=5)
    reliability: conint(ge=1, le=5)
    communication: conint(ge=1, le=5)
    tradeoffs: conint(ge=1, le=5)


class ArchitectureFeedback(BaseModel):
    components_identified: int
    single_points_of_failure: List[str] = Field(default_factory=list)
    missing_components: List[str] = Field(default_factory=list)
    architecture_notes: str


class CommunicationFeedback(BaseModel):
    clarity: str
    depth: str
    tradeoff_discussion: str


class FeedbackMetadata(BaseModel):
    session_id: str
    problem_id: str
    turn_count: int
    topics_covered: List[str] = Field(default_factory=list)
    topics_remaining: List[str] = Field(default_factory=list)
    generated_at: str


class FeedbackCreate(BaseModel):
    scores: FeedbackScores
    strengths: List[str]
    improvements: List[str]
    summary: str
    # C2 superset fields — optional per contract §5.3 (subset must still persist)
    architecture_feedback: Optional[ArchitectureFeedback] = None
    communication_feedback: Optional[CommunicationFeedback] = None
    feedback_metadata: Optional[FeedbackMetadata] = Field(None, alias="metadata")

    class Config:
        populate_by_name = True


class FeedbackResponse(BaseModel):
    id: str
    session_id: str
    scores: FeedbackScores
    strengths: List[str]
    improvements: List[str]
    summary: str
    architecture_feedback: Optional[ArchitectureFeedback] = None
    communication_feedback: Optional[CommunicationFeedback] = None
    feedback_metadata: Optional[FeedbackMetadata] = Field(None, alias="metadata")
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ---------------------------------------------------------------------------
# Ranking / Leaderboard Schemas
# ---------------------------------------------------------------------------

class EvaluationResponse(BaseModel):
    id: str
    session_id: str
    user_id: str
    problem_id: str
    technical_score: float
    communication_score: float
    correctness_score: float
    optimization_score: float
    confidence_score: float
    time_taken_seconds: int
    retry_count: int
    difficulty_multiplier: float
    composite_score: float
    created_at: datetime

    class Config:
        from_attributes = True


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    user_name: Optional[str] = None
    composite_score: float
    interviews_completed: int
    best_score: float = 0.0


class UserRankResponse(BaseModel):
    user_id: str
    scope: str                       # global|problem|company|weekly|monthly
    scope_id: Optional[str] = None   # problem_id / company for scoped ranks
    rank: Optional[int] = None
    total_ranked: int = 0
    percentile: Optional[float] = None
    composite_score: Optional[float] = None
    rank_change: Optional[int] = Field(None, description="Positive = climbed since previous period (weekly/monthly scopes)")


# ---------------------------------------------------------------------------
# History / Analytics Schemas
# ---------------------------------------------------------------------------

class HistoryItem(BaseModel):
    session_id: str
    problem_id: str
    problem_title: Optional[str] = None
    difficulty: Optional[str] = None
    status: str
    attempt_number: int = 1
    duration_seconds: int = 0
    composite_score: Optional[float] = None
    feedback_summary: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class HistoryDetail(HistoryItem):
    history: List[Message] = Field(default_factory=list)          # transcript replay
    canvas_snapshots: List[CanvasSnapshot] = Field(default_factory=list)
    events: List[Dict[str, Any]] = Field(default_factory=list)
    feedback: Optional[FeedbackResponse] = None
    evaluation: Optional[EvaluationResponse] = None


class TopicStat(BaseModel):
    topic: str
    avg_score: float
    samples: int


class DashboardResponse(BaseModel):
    user_id: str
    problems_solved: int = 0
    problems_attempted: int = 0
    completion_rate: float = 0.0
    success_rate: float = 0.0
    average_score: Optional[float] = None
    average_time_seconds: Optional[float] = None
    personal_best_score: Optional[float] = None
    weak_topics: List[TopicStat] = Field(default_factory=list)
    strong_topics: List[TopicStat] = Field(default_factory=list)
    current_streak_days: int = 0
    longest_streak_days: int = 0
    interview_readiness: float = Field(0.0, description="0-100 blended readiness estimate")
    company_readiness: Dict[str, float] = Field(default_factory=dict)
    learning_curve: List[Dict[str, Any]] = Field(default_factory=list)  # [{date, avg_score}]


# ---------------------------------------------------------------------------
# Notifications / Achievements
# ---------------------------------------------------------------------------

class NotificationResponse(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    body: Optional[str] = None
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AchievementResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    earned_at: Optional[datetime] = None


class DailyChallengeResponse(BaseModel):
    challenge_date: str
    problem: ProblemResponse
