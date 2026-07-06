from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import schemas, security
from app.database import get_db
from app.services import ranking

router = APIRouter(
    prefix="/rankings",
    tags=["rankings"],
    dependencies=[Depends(security.verify_api_key)],
)


@router.get("/leaderboard", response_model=schemas.PaginatedResponse[schemas.LeaderboardEntry])
def get_leaderboard(
    scope: str = Query("global", enum=["global", "weekly", "monthly"]),
    problem_id: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Leaderboard ranked by average composite score (ties: interviews completed).
    Combine scope with problem_id or company for scoped boards."""
    entries, total = ranking.leaderboard(db, scope=scope, problem_id=problem_id,
                                         company=company, limit=limit, offset=offset)
    return schemas.PaginatedResponse[schemas.LeaderboardEntry](
        data=entries,
        meta=schemas.PageMeta(total=total, limit=limit, offset=offset,
                              returned=len(entries), has_more=offset + len(entries) < total),
    )


@router.get("/me", response_model=schemas.UserRankResponse)
def get_my_rank(
    user_id: str,
    scope: str = Query("global", enum=["global", "weekly", "monthly"]),
    problem_id: Optional[str] = None,
    company: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """User's rank, percentile and rank change (weekly/monthly scopes)."""
    return ranking.user_rank(db, user_id, scope=scope, problem_id=problem_id, company=company)
