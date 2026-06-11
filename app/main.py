from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, verify_db_connection, SessionLocal
from app import crud, models
from app.config import settings
from app.routes import problems, sessions, users
from app.services.cache import session_cache

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Skip database initialization if we are running in testing mode
    if not settings.TESTING:
        # 1. Verify connection to PostgreSQL on startup
        # This will fail and crash the application if connection cannot be established
        verify_db_connection()
        
        # 2. Create tables in PostgreSQL database
        Base.metadata.create_all(bind=engine)
        
        # 3. Seed initial problems into catalog
        db = SessionLocal()
        try:
            crud.seed_problems(db)
        finally:
            db.close()
        
    yield

from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
import httpx
import json
import uuid
from datetime import datetime, timezone
from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db

app = FastAPI(
    title="Archie Backend",
    description="Python FastAPI backend for Archie",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration to allow local/web clients to connect securely
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Chat Schema ---
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
    title = ""
    if isinstance(problem_input, str):
        title = problem_input
    elif isinstance(problem_input, dict) and "title" in problem_input:
        title = problem_input["title"]
    else:
        title = str(problem_input)
        
    problems = db.query(models.Problem).all()
    for p in problems:
        if p.id.lower() in title.lower() or p.title.lower() in title.lower():
            return p.id
    return "design-rate-limiter"

# Combined /chat persistence and AI routing proxy
@app.post("/chat")
async def chat_endpoint(request: ChatRequestSchema, db: Session = Depends(get_db)):
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
        
    db.commit()
    session_cache.invalidate(f"session:{request.session_id}")
    
    # 4. Stream response from local AI engine (port 8001)
    async def sse_forwarder():
        accumulated_text = ""
        ai_engine_url = "http://127.0.0.1:8001/chat"
        
        # Prepare payload to send to the stateless AI engine
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
                async with client.stream("POST", ai_engine_url, json=payload) as response:
                    if response.status_code != 200:
                        err_msg = f"AI Engine error status: {response.status_code}"
                        yield f"data: {json.dumps({'error': err_msg})}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                        
                    async for line in response.aiter_lines():
                        if line:
                            yield line + "\n"
                            
                            # Accumulate text chunks to save to DB
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
            err_msg = f"Failed to connect to local AI Engine: {str(e)}"
            yield f"data: {json.dumps({'error': err_msg})}\n\n"
        finally:
            # Save AI response to DB
            if accumulated_text.strip():
                db_new = SessionLocal()
                try:
                    session_in_db = db_new.query(models.Session).filter(models.Session.id == request.session_id).first()
                    if session_in_db:
                        ai_msg = {
                            "role": "assistant",
                            "content": accumulated_text.strip(),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                        current_hist = list(session_in_db.history or [])
                        current_hist.append(ai_msg)
                        session_in_db.history = current_hist
                        db_new.commit()
                        session_cache.invalidate(f"session:{request.session_id}")
                except Exception:
                    db_new.rollback()
                finally:
                    db_new.close()
            yield "data: [DONE]\n\n"
            
    return StreamingResponse(sse_forwarder(), media_type="text/event-stream")

# Root endpoint for health checking
@app.get("/")
def read_root():
    return {"status": "running", "service": "Archie Backend"}

# Mount the routes
app.include_router(problems.router)
app.include_router(sessions.router)
app.include_router(users.router)
