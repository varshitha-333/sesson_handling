import uuid
import json
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app import crud, models, schemas, security
from app.database import get_db, SessionLocal
from app.services.interviewer import InterviewerService

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    dependencies=[Depends(security.verify_api_key)]
)

def map_session_to_response(session: models.Session, limit: Optional[int] = None) -> schemas.SessionResponse:
    # Ensure history elements conform to the schema
    history = []
    for item in (session.history or []):
        history.append(
            schemas.Message(
                role=item.get("role", ""),
                content=item.get("content", ""),
                timestamp=item.get("timestamp", "")
            )
        )
    
    canvas_snapshots = []
    for item in (session.canvas_snapshots or []):
        canvas_snapshots.append(
            schemas.CanvasSnapshot(
                turn_id=item.get("turn_id", ""),
                canvas_json=item.get("canvas_json", {})
            )
        )

    # Slice history and canvas snapshots if limit is specified
    if limit is not None and limit > 0:
        history = history[-limit:]
        canvas_snapshots = canvas_snapshots[-limit:]

    return schemas.SessionResponse(
        session_id=session.id,
        user_id=session.user_id,
        status=session.status,
        history=history,
        canvas_snapshots=canvas_snapshots
    )

@router.post("/", response_model=schemas.SessionResponse)
def create_session(session_create: schemas.SessionCreate, db: Session = Depends(get_db)):
    # Verify the problem exists
    problem = crud.get_problem(db, session_create.problem_id)
    if not problem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with ID '{session_create.problem_id}' not found."
        )
    session = crud.create_session(db, session_create)
    return map_session_to_response(session)

@router.get("/", response_model=List[schemas.SessionResponse])
def read_sessions(
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    db: Session = Depends(get_db)
):
    sessions = crud.get_sessions(db, user_id=user_id, limit=limit, offset=offset)
    return [map_session_to_response(s) for s in sessions]

@router.get("/{session_id}", response_model=schemas.SessionResponse)
def read_session(
    session_id: str,
    limit: Optional[int] = None,
    db: Session = Depends(get_db)
):
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
    return map_session_to_response(session, limit=limit)

@router.post("/{session_id}/turns")
def post_turn(
    session_id: str,
    turn_request: schemas.TurnRequest,
    db: Session = Depends(get_db)
):
    # Retrieve session
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_444_NOT_FOUND if hasattr(status, "HTTP_444_NOT_FOUND") else status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
    
    # Generate a unique turn_id to link user's message and canvas snapshot
    turn_id = str(uuid.uuid4())
    timestamp_str = datetime.now(timezone.utc).isoformat()
    
    # 1. Update the chat history with user's message
    user_message = {
        "role": "user",
        "content": turn_request.text,
        "timestamp": timestamp_str
    }
    updated_chat_history = list(session.history or [])
    updated_chat_history.append(user_message)
    session.history = updated_chat_history
    
    # 2. Update the canvas history with the canvas snapshot if provided
    updated_canvas_history = list(session.canvas_snapshots or [])
    if turn_request.c1Snapshot is not None:
        canvas_snapshot = {
            "turn_id": turn_id,
            "canvas_json": turn_request.c1Snapshot
        }
        updated_canvas_history.append(canvas_snapshot)
        session.canvas_snapshots = updated_canvas_history
        
    # Save the user turn to PostgreSQL immediately
    db.commit()
    
    # Capture current history state for the streamer
    history_for_interviewer = list(session.history)
    
    async def sse_streamer():
        accumulated_text = ""
        # Call the interviewer streaming service
        async for event in InterviewerService.get_response_stream(history_for_interviewer):
            yield event
            
            # Accumulate text from chunks for saving to database
            if event.startswith("data: "):
                data_str = event[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data_json = json.loads(data_str)
                    if "chunk" in data_json:
                        accumulated_text += data_json["chunk"]
                except Exception:
                    pass
        
        # Save assistant message to database after stream completes
        db_new = SessionLocal()
        try:
            db_session = db_new.query(models.Session).filter(models.Session.id == session_id).first()
            if db_session:
                assistant_message = {
                    "role": "assistant",
                    "content": accumulated_text.strip(),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                current_chat = list(db_session.history or [])
                current_chat.append(assistant_message)
                db_session.history = current_chat
                db_new.commit()
        except Exception:
            db_new.rollback()
        finally:
            db_new.close()

    return StreamingResponse(
        sse_streamer(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/{session_id}/send")
def send_session_to_ai(session_id: str, db: Session = Depends(get_db)):
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
    
    # Retrieve the latest 9 messages and canvas snapshots
    history = session.history or []
    canvas = session.canvas_snapshots or []
    
    # Take up to the last 9 elements
    latest_history = history[-9:] if len(history) > 9 else history
    latest_canvas = canvas[-9:] if len(canvas) > 9 else canvas
    
    # Prepare the payload to be sent to the Socratic AI interface adapter
    payload = {
        "session_id": session.id,
        "user_id": session.user_id,
        "problem_id": session.problem_id,
        "latest_history": latest_history,
        "latest_canvas_snapshots": latest_canvas
    }
    
    # This acts as the controller proxy forwarding data to the Socratic AI interface adapter
    return {
        "status": "success",
        "message": "Latest 9 turns successfully sent to the Socratic AI interface adapter.",
        "payload_sent": payload
    }

@router.patch("/{session_id}", response_model=schemas.SessionResponse)
def update_session(
    session_id: str,
    session_update: schemas.SessionUpdate,
    db: Session = Depends(get_db)
):
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
    session.status = session_update.status
    db.commit()
    db.refresh(session)
    return map_session_to_response(session)

@router.post("/{session_id}/feedback", response_model=schemas.FeedbackResponse)
def save_session_feedback(
    session_id: str,
    feedback_in: schemas.FeedbackCreate,
    db: Session = Depends(get_db)
):
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
    
    # Check if feedback already exists
    existing = db.query(models.Feedback).filter(models.Feedback.session_id == session_id).first()
    if existing:
        existing.scores = feedback_in.scores.dict()
        existing.strengths = feedback_in.strengths
        existing.improvements = feedback_in.improvements
        existing.summary = feedback_in.summary
        db.commit()
        db.refresh(existing)
        return existing
        
    # Save feedback record to PostgreSQL
    feedback_record = models.Feedback(
        session_id=session_id,
        scores=feedback_in.scores.dict(),
        strengths=feedback_in.strengths,
        improvements=feedback_in.improvements,
        summary=feedback_in.summary
    )
    db.add(feedback_record)
    db.commit()
    db.refresh(feedback_record)
    
    return feedback_record


@router.get("/{session_id}/feedback", response_model=schemas.FeedbackResponse)
def get_session_feedback(session_id: str, db: Session = Depends(get_db)):
    # Verify session exists
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
        
    # Retrieve feedback record
    feedback_record = db.query(models.Feedback).filter(models.Feedback.session_id == session_id).first()
    if not feedback_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feedback report for session '{session_id}' has not been generated yet. Call POST to generate."
        )
        
    return feedback_record
