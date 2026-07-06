from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas, security
from app.database import get_db
from app.errors import ApiError
from app.services import analytics

history_router = APIRouter(
    prefix="/history",
    tags=["history"],
    dependencies=[Depends(security.verify_api_key)],
)

analytics_router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(security.verify_api_key)],
)


@history_router.get("/", response_model=schemas.PaginatedResponse[schemas.HistoryItem])
def get_history(
    user_id: str,
    status: Optional[str] = Query(None, description="Filter: completed|cancelled|abandoned|expired|active|paused"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = analytics.get_history(db, user_id, status=status, limit=limit, offset=offset)
    return schemas.PaginatedResponse[schemas.HistoryItem](
        data=items,
        meta=schemas.PageMeta(total=total, limit=limit, offset=offset,
                              returned=len(items), has_more=offset + len(items) < total),
    )


@history_router.get("/{session_id}", response_model=schemas.HistoryDetail)
def get_history_detail(session_id: str, db: Session = Depends(get_db)):
    """Full replay payload: transcript, canvas snapshots, lifecycle events,
    feedback and evaluation."""
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Session with ID '{session_id}' not found.")
    return analytics.get_history_detail(db, session)


@analytics_router.get("/dashboard", response_model=schemas.DashboardResponse)
def get_dashboard(user_id: str, db: Session = Depends(get_db)):
    """Progress dashboard: solved/attempted, averages, weak/strong topics,
    streaks, readiness, learning curve."""
    return analytics.get_dashboard(db, user_id)
