import json
import uuid
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

import httpx
from fastapi import FastAPI, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import crud, models
from app.config import settings
from app.database import engine, verify_db_connection, schema_sync, SessionLocal, get_db
from app.errors import register_error_handlers
from app.rate_limit import RateLimitMiddleware
from app.routes import problems, sessions, users, lifecycle, rankings, history, notifications
from app.services.cache import session_cache
from app.services.achievements import seed_achievements

logger = logging.getLogger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Skip database initialization when running in testing mode
    if not settings.TESTING:
        # 1. Verify connectivity (crashes startup on failure — fail fast)
        verify_db_connection()
        # 2. Create missing tables / add missing columns (dev safety net;
        #    production releases run `alembic upgrade head` first)
        schema_sync()
        # 3. Seed initial catalog + achievements
        db = SessionLocal()
        try:
            crud.seed_problems(db)
            seed_achievements(db)
        finally:
            db.close()
    yield


app = FastAPI(
    title="Archie Backend",
    description="FastAPI backend for Archie — session handling, interview engine, "
                "problem catalog, rankings, history and analytics.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS: pinned origins via CORS_ORIGINS env (comma-separated); "*" keeps the
# permissive dev behavior using a regex so credentials still work.
if settings.CORS_ORIGINS.strip() == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex="https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(RateLimitMiddleware)
register_error_handlers(app)


# --- Chat Schema (legacy /chat proxy) ---
class ChatMessageSchema(BaseModel):
    role: str
    content: str


class ChatRequestSchema(BaseModel):
    session_id: str
    problem: Any
    chat_history: Optional[List[ChatMessageSchema]] = None
    history: Optional[List[ChatMessageSchema]] = None
    message: str
    canvas_snapshot: Optional[Dict[str, Any]] = None

    def get_history(self) -> List[ChatMessageSchema]:
        if self.chat_history is not None:
            return self.chat_history
        if self.history is not None:
            return self.history
        return []


def resolve_problem_id(db: Session, problem_input: Any) -> str:
    if isinstance(problem_input, str):
        title = problem_input
    elif isinstance(problem_input, dict) and "title" in problem_input:
        title = problem_input["title"]
    else:
        title = str(problem_input)

    title_lower = title.lower()
    problems_list = db.query(models.Problem.id, models.Problem.title).all()
    for pid, ptitle in problems_list:
        if pid.lower() in title_lower or ptitle.lower() in title_lower:
            return pid
    return "design-rate-limiter"


def save_assistant_message_chat(session_id: str, text_content: str):
    if not text_content.strip():
        return
    db_new = SessionLocal()
    try:
        session_in_db = db_new.query(models.Session).filter(models.Session.id == session_id).first()
        if session_in_db:
            ai_msg = {
                "role": "assistant",
                "content": text_content.strip(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            current_hist = list(session_in_db.history or [])
            current_hist.append(ai_msg)
            session_in_db.history = current_hist
            db_new.commit()
            session_cache.invalidate(f"session:{session_id}")
    except Exception:
        db_new.rollback()
        logger.exception("Failed to persist assistant message for session %s", session_id)
    finally:
        db_new.close()


# Combined /chat persistence and AI routing proxy
@app.post("/chat")
async def chat_endpoint(request: ChatRequestSchema, background_tasks: BackgroundTasks,
                        db: Session = Depends(get_db)):
    # 1. Fetch or create session in database
    db_session = crud.get_session(db, request.session_id)
    if not db_session:
        problem_id = resolve_problem_id(db, request.problem)
        db_session = models.Session(
            id=request.session_id,
            problem_id=problem_id,
            status="active",
            history=[],
            canvas_snapshots=[]
        )
        db.add(db_session)
        db.commit()
        db.refresh(db_session)

    # 2. Append user's new message to database history
    user_msg = {
        "role": "user",
        "content": request.message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    current_history = list(db_session.history or [])
    current_history.append(user_msg)
    db_session.history = current_history

    # 3. Append canvas snapshot if provided
    if request.canvas_snapshot:
        snapshot = {
            "turn_id": str(uuid.uuid4()),
            "canvas_json": request.canvas_snapshot
        }
        current_snapshots = list(db_session.canvas_snapshots or [])
        current_snapshots.append(snapshot)
        db_session.canvas_snapshots = current_snapshots

    # Turn activity also counts as liveness for the interview engine
    db_session.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    session_cache.invalidate(f"session:{request.session_id}")

    # 4. Stream response from the AI engine
    async def sse_forwarder():
        accumulated_text = ""
        history_list = request.get_history()
        payload = {
            "session_id": request.session_id,
            "problem": request.problem,
            "chat_history": [{"role": m.role, "content": m.content} for m in history_list],
            "message": request.message,
            "canvas_snapshot": request.canvas_snapshot
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream("POST", settings.AI_ENGINE_URL, json=payload) as response:
                    if response.status_code != 200:
                        err_msg = f"AI Engine error status: {response.status_code}"
                        yield f"data: {json.dumps({'error': err_msg})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    async for line in response.aiter_lines():
                        if line:
                            yield line + "\n"
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data_json = json.loads(data_str)
                                    if "content" in data_json:
                                        accumulated_text += data_json["content"]
                                except Exception:
                                    pass
        except Exception as e:
            err_msg = f"Failed to connect to AI Engine: {str(e)}"
            yield f"data: {json.dumps({'error': err_msg})}\n\n"
        finally:
            background_tasks.add_task(save_assistant_message_chat, request.session_id, accumulated_text)
            yield "data: [DONE]\n\n"

    return StreamingResponse(sse_forwarder(), media_type="text/event-stream")


# --- Health endpoints (Railway healthcheck targets /health) ---

@app.api_route("/", methods=["GET", "HEAD"], tags=["health"])
def read_root():
    return {"status": "running", "service": "Archie Backend", "version": app.version}


@app.get("/health", tags=["health"])
def health():
    """Liveness probe — no dependencies, always fast."""
    return {"status": "ok"}


@app.get("/health/db", tags=["health"])
def health_db():
    """Readiness probe — verifies the database connection."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503,
                            content={"status": "degraded", "database": f"error: {e}"})


# --- Router mounting ---
# Canonical prefix is /api/v1; /api is kept as a backward-compatible alias so
# existing frontend calls keep working. `lifecycle` is registered before
# `sessions` so literal paths (/start, /active) win over /{session_id}.
API_ROUTERS = [
    lifecycle.router,
    sessions.router,
    problems.router,
    users.router,
    rankings.router,
    history.history_router,
    history.analytics_router,
    notifications.router,
    notifications.achievements_router,
]

for router in API_ROUTERS:
    app.include_router(router, prefix="/api")
for router in API_ROUTERS:
    app.include_router(router, prefix="/api/v1")
