import uuid
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app import crud, models, schemas, security
from app.database import get_db, SessionLocal
from app.services.interviewer import InterviewerService
from app.services.cache import session_cache

logger = logging.getLogger("backend.sessions")

router = APIRouter(
    prefix="/sessions",
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
        problem_id=session.problem_id,
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
    response_data = map_session_to_response(session)
    session_cache.set(f"session:{session.id}", response_data)
    return response_data

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
    cache_key = f"session:{session_id}"
    cached_response = session_cache.get(cache_key)
    if cached_response is not None:
        if limit is not None and limit > 0:
            sliced_history = cached_response.history[-limit:]
            sliced_snapshots = cached_response.canvas_snapshots[-limit:]
            return schemas.SessionResponse(
                session_id=cached_response.session_id,
                user_id=cached_response.user_id,
                problem_id=cached_response.problem_id,
                status=cached_response.status,
                history=sliced_history,
                canvas_snapshots=sliced_snapshots
            )
        return cached_response

    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{session_id}' not found."
        )
    response_data = map_session_to_response(session)
    session_cache.set(cache_key, response_data)
    
    if limit is not None and limit > 0:
        return map_session_to_response(session, limit=limit)
    return response_data

def save_assistant_message(session_id: str, text: str):
    if not text.strip():
        return
    db_new = SessionLocal()
    try:
        db_session = db_new.query(models.Session).filter(models.Session.id == session_id).first()
        if db_session:
            assistant_message = {
                "role": "assistant",
                "content": text.strip(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            current_chat = list(db_session.history or [])
            current_chat.append(assistant_message)
            db_session.history = current_chat
            db_new.commit()
            session_cache.invalidate(f"session:{session_id}")
    except Exception:
        db_new.rollback()
    finally:
        db_new.close()

@router.post("/{session_id}/turns")
def post_turn(
    session_id: str,
    turn_request: schemas.TurnRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Retrieve session
    session = crud.get_session(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
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
    session_cache.invalidate(f"session:{session_id}")
    
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
        
        # Save assistant message to database after stream completes via BackgroundTasks
        background_tasks.add_task(save_assistant_message, session_id, accumulated_text)

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
    cache_key = f"session:{session_id}"
    cached_response = session_cache.get(cache_key)
    
    if cached_response is not None:
        user_id = cached_response.user_id
        problem_id = cached_response.problem_id
        history = [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in cached_response.history
        ]
        canvas = [
            {"turn_id": c.turn_id, "canvas_json": c.canvas_json}
            for c in cached_response.canvas_snapshots
        ]
    else:
        session = crud.get_session(db, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID '{session_id}' not found."
            )
        user_id = session.user_id
        problem_id = session.problem_id
        history = session.history or []
        canvas = session.canvas_snapshots or []
        
        # Populate the cache
        response_data = map_session_to_response(session)
        session_cache.set(cache_key, response_data)
    
    # Retrieve the latest 9 messages and canvas snapshots
    # Take up to the last 9 elements
    latest_history = history[-9:] if len(history) > 9 else history
    latest_canvas = canvas[-9:] if len(canvas) > 9 else canvas
    
    # Prepare the payload to be sent to the Socratic AI interface adapter
    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "problem_id": problem_id,
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
        # Legacy behavior kept for frontend compatibility: auto-create a session
        # if a canvas save arrives before chat initialization. Logged because it
        # usually indicates a client-side ordering bug.
        logger.warning("PATCH /sessions/%s auto-created a session (canvas save before init)", session_id)
        session = models.Session(
            id=session_id,
            problem_id="design-rate-limiter",
            status="active",
            history=[],
            canvas_snapshots=[]
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    
    if session_update.status is not None:
        session.status = session_update.status
        
    if session_update.canvas_state is not None:
        # Append the new canvas layout containing node positions to the session history
        new_snapshot = {
            "turn_id": str(uuid.uuid4()),
            "canvas_json": session_update.canvas_state
        }
        current_snapshots = list(session.canvas_snapshots or [])
        current_snapshots.append(new_snapshot)
        session.canvas_snapshots = current_snapshots
        
    db.commit()
    db.refresh(session)
    session_cache.invalidate(f"session:{session_id}")
    return map_session_to_response(session)


def map_feedback_to_response(feedback: models.Feedback) -> schemas.FeedbackResponse:
    # Explicit mapping helper to bypass SQLAlchemy metadata keyword conflict
    return schemas.FeedbackResponse(
        id=feedback.id,
        session_id=feedback.session_id,
        scores=schemas.FeedbackScores(**feedback.scores),
        strengths=feedback.strengths,
        improvements=feedback.improvements,
        summary=feedback.summary,
        architecture_feedback=schemas.ArchitectureFeedback(**feedback.architecture_feedback) if feedback.architecture_feedback else None,
        communication_feedback=schemas.CommunicationFeedback(**feedback.communication_feedback) if feedback.communication_feedback else None,
        feedback_metadata=schemas.FeedbackMetadata(**feedback.feedback_metadata) if feedback.feedback_metadata else None,
        created_at=feedback.created_at
    )


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

    # Upsert the feedback record (locked C2 contract shape)
    feedback_record = db.query(models.Feedback).filter(models.Feedback.session_id == session_id).first()
    if not feedback_record:
        feedback_record = models.Feedback(session_id=session_id)
        db.add(feedback_record)
    feedback_record.scores = feedback_in.scores.model_dump()
    feedback_record.strengths = feedback_in.strengths
    feedback_record.improvements = feedback_in.improvements
    feedback_record.summary = feedback_in.summary
    feedback_record.architecture_feedback = feedback_in.architecture_feedback.model_dump() if feedback_in.architecture_feedback else None
    feedback_record.communication_feedback = feedback_in.communication_feedback.model_dump() if feedback_in.communication_feedback else None
    feedback_record.feedback_metadata = feedback_in.feedback_metadata.model_dump() if feedback_in.feedback_metadata else None
    db.commit()
    db.refresh(feedback_record)

    # Ranking pipeline: scores arrived, so compute/refresh the evaluation for
    # ranked (non-anonymous) sessions and re-check achievements.
    if session.user_id:
        try:
            from app.services.ranking import compute_evaluation
            from app.services.achievements import check_and_award
            compute_evaluation(db, session, feedback_record)
            db.commit()
            check_and_award(db, session.user_id)
        except Exception:
            db.rollback()
            logger.exception("Evaluation/achievement computation failed for session %s", session_id)

    return map_feedback_to_response(feedback_record)


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
        
    return map_feedback_to_response(feedback_record)
