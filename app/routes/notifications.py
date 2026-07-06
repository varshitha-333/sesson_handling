from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas, security
from app.database import get_db
from app.errors import ApiError

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(security.verify_api_key)],
)

achievements_router = APIRouter(
    prefix="/achievements",
    tags=["achievements"],
    dependencies=[Depends(security.verify_api_key)],
)


@router.get("/", response_model=schemas.PaginatedResponse[schemas.NotificationResponse])
def list_notifications(
    user_id: str,
    unread_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(models.Notification).filter(models.Notification.user_id == user_id)
    if unread_only:
        query = query.filter(models.Notification.read.is_(False))
    total = query.count()
    items = query.order_by(models.Notification.created_at.desc()).offset(offset).limit(limit).all()
    return schemas.PaginatedResponse[schemas.NotificationResponse](
        data=[schemas.NotificationResponse.model_validate(n) for n in items],
        meta=schemas.PageMeta(total=total, limit=limit, offset=offset,
                              returned=len(items), has_more=offset + len(items) < total),
    )


@router.post("/{notification_id}/read", response_model=schemas.NotificationResponse)
def mark_read(notification_id: str, db: Session = Depends(get_db)):
    notification = db.query(models.Notification).filter(models.Notification.id == notification_id).first()
    if not notification:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", f"Notification '{notification_id}' not found.")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/read-all")
def mark_all_read(user_id: str, db: Session = Depends(get_db)):
    updated = (db.query(models.Notification)
               .filter(models.Notification.user_id == user_id,
                       models.Notification.read.is_(False))
               .update({models.Notification.read: True}, synchronize_session=False))
    db.commit()
    return {"user_id": user_id, "marked_read": updated}


@achievements_router.get("/", response_model=List[schemas.AchievementResponse])
def list_achievements(
    user_id: Optional[str] = Query(None, description="When set, includes earned_at for earned achievements only if earned_only, else all with earned flag"),
    earned_only: bool = False,
    db: Session = Depends(get_db),
):
    achievements = db.query(models.Achievement).all()
    earned = {}
    if user_id:
        earned = {ua.achievement_id: ua.earned_at
                  for ua in db.query(models.UserAchievement)
                  .filter(models.UserAchievement.user_id == user_id).all()}
    result = []
    for a in achievements:
        if earned_only and a.id not in earned:
            continue
        result.append(schemas.AchievementResponse(
            id=a.id, name=a.name, description=a.description, icon=a.icon,
            earned_at=earned.get(a.id)))
    return result
