import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy import or_, func, cast, String
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import crud, models, schemas, security
from app.database import get_db
from app.config import settings
from app.services import analytics
from app.services.session_engine import utcnow

logger = logging.getLogger("backend.problems")

router = APIRouter(prefix="/problems", tags=["problems"])


SORTABLE = {
    "created_at": models.Problem.created_at,
    "updated_at": models.Problem.updated_at,
    "title": models.Problem.title,
    "difficulty": models.Problem.difficulty,
    "estimated_time": models.Problem.estimated_time,
    "attempts": models.Problem.attempts,
    "completions": models.Problem.completions,
    "success_rate": models.Problem.success_rate,
    "avg_rating": models.Problem.avg_rating,
    "bookmark_count": models.Problem.bookmark_count,
}


def _as_list(value) -> list:
    """Legacy catalog rows sometimes store a plain string where a list is expected."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def map_problem(p: models.Problem, bookmarked: Optional[bool] = None,
                completed: Optional[bool] = None) -> schemas.ProblemResponse:
    return schemas.ProblemResponse(
        id=p.id, title=p.title, description=p.description,
        requirements=p.requirements or {}, constraints=p.constraints or [],
        difficulty=p.difficulty, category=p.category, subcategory=p.subcategory,
        estimated_time=p.estimated_time, company=p.company, status=p.status,
        meta=schemas.ProblemMeta(
            interview_round=p.interview_round,
            key_concepts=_as_list(p.key_concepts),
            similar_problems=_as_list(p.similar_problems),
            why_this_problem=p.why_this_problem,
            what_youll_learn=_as_list(p.what_youll_learn),
            next_level_problems=_as_list(p.next_level_problems),
            sources=_as_list(p.sources),
        ),
        stats=schemas.ProblemStats(
            attempts=p.attempts or 0, completions=p.completions or 0,
            success_rate=p.success_rate or 0.0, avg_rating=p.avg_rating or 0.0,
            rating_count=p.rating_count or 0, bookmark_count=p.bookmark_count or 0,
            avg_attempts_to_solve=p.avg_attempts_to_solve or 0.0,
        ),
        version=p.version, created_by=p.created_by, updated_by=p.updated_by,
        created_at=p.created_at, updated_at=p.updated_at,
        bookmarked=bookmarked, completed=completed,
    )


def _user_flags(db: Session, user_id: Optional[str], problem_ids: List[str]):
    """Return (bookmarked_ids, completed_ids) for the given user."""
    if not user_id or not problem_ids:
        return set(), set()
    bookmarked = {b.problem_id for b in db.query(models.Bookmark)
                  .filter(models.Bookmark.user_id == user_id,
                          models.Bookmark.problem_id.in_(problem_ids)).all()}
    completed = {s.problem_id for s in db.query(models.Session)
                 .filter(models.Session.user_id == user_id,
                         models.Session.status == models.SESSION_COMPLETED,
                         models.Session.problem_id.in_(problem_ids)).all()}
    return bookmarked, completed


def _paginated(db: Session, items: List[models.Problem], total: int,
               limit: int, offset: int, user_id: Optional[str]):
    bm, cp = _user_flags(db, user_id, [p.id for p in items])
    data = [map_problem(p,
                        bookmarked=(p.id in bm) if user_id else None,
                        completed=(p.id in cp) if user_id else None)
            for p in items]
    return schemas.PaginatedResponse[schemas.ProblemResponse](
        data=data,
        meta=schemas.PageMeta(total=total, limit=limit, offset=offset,
                              returned=len(data), has_more=offset + len(data) < total),
    )


@router.get("/", response_model=schemas.PaginatedResponse[schemas.ProblemResponse])
def read_problems(
    search: Optional[str] = None,
    status_filter: Optional[str] = Query("published", alias="status"),
    difficulty: Optional[str] = None,
    company: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    interview_round: Optional[str] = None,
    key_concept: Optional[str] = None,
    max_estimated_time: Optional[int] = None,
    completed: Optional[bool] = Query(None, description="Filter by completion for user_id"),
    bookmarked: Optional[bool] = Query(None, description="Filter by bookmark for user_id"),
    user_id: Optional[str] = Query(None, description="Enables per-user flags/filters"),
    sort_by: str = Query("created_at", enum=list(SORTABLE.keys())),
    order: str = Query("desc", enum=["asc", "desc"]),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    query = db.query(models.Problem)
    if status_filter and status_filter != "all":
        query = query.filter(models.Problem.status == status_filter)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(models.Problem.title.ilike(like),
                                 models.Problem.description.ilike(like),
                                 models.Problem.id.ilike(like)))
    if difficulty:
        query = query.filter(func.lower(models.Problem.difficulty) == difficulty.lower())
    if company:
        query = query.filter(func.lower(models.Problem.company) == company.lower())
    if category:
        query = query.filter(func.lower(models.Problem.category) == category.lower())
    if subcategory:
        query = query.filter(func.lower(models.Problem.subcategory) == subcategory.lower())
    if interview_round:
        query = query.filter(func.lower(models.Problem.interview_round) == interview_round.lower())
    if key_concept:
        # Portable JSON-array containment check (works on PG and SQLite)
        query = query.filter(cast(models.Problem.key_concepts, String).ilike(f'%"{key_concept}"%'))
    if max_estimated_time is not None:
        query = query.filter(models.Problem.estimated_time <= max_estimated_time)

    if user_id and bookmarked is not None:
        sub = db.query(models.Bookmark.problem_id).filter(models.Bookmark.user_id == user_id)
        query = query.filter(models.Problem.id.in_(sub) if bookmarked
                             else ~models.Problem.id.in_(sub))
    if user_id and completed is not None:
        sub = db.query(models.Session.problem_id).filter(
            models.Session.user_id == user_id,
            models.Session.status == models.SESSION_COMPLETED)
        query = query.filter(models.Problem.id.in_(sub) if completed
                             else ~models.Problem.id.in_(sub))

    total = query.count()
    col = SORTABLE[sort_by]
    query = query.order_by(col.asc() if order == "asc" else col.desc(), models.Problem.id.asc())
    items = query.offset(offset).limit(limit).all()
    return _paginated(db, items, total, limit, offset, user_id)


@router.get("/trending", response_model=schemas.PaginatedResponse[schemas.ProblemResponse])
def trending_problems(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),
    user_id: Optional[str] = None,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    counts = dict(
        db.query(models.Session.problem_id, func.count(models.Session.id))
        .filter(models.Session.created_at >= since.replace(tzinfo=None))
        .group_by(models.Session.problem_id).all()
    )
    problems = db.query(models.Problem).filter(models.Problem.status == "published").all()
    problems.sort(key=lambda p: (counts.get(p.id, 0), p.attempts or 0), reverse=True)
    items = problems[:limit]
    return _paginated(db, items, len(problems), limit, 0, user_id)


@router.get("/recommended", response_model=schemas.PaginatedResponse[schemas.ProblemResponse])
def recommended_problems(
    user_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    """Heuristic recommendations: unfinished problems in the user's categories,
    then next_level_problems of solved ones, then globally popular."""
    completed_ids = {s.problem_id for s in db.query(models.Session).filter(
        models.Session.user_id == user_id,
        models.Session.status == models.SESSION_COMPLETED).all()}
    solved = db.query(models.Problem).filter(models.Problem.id.in_(completed_ids)).all() if completed_ids else []
    preferred_categories = {p.category for p in solved}
    next_level = {pid for p in solved for pid in (p.next_level_problems or [])}

    candidates = db.query(models.Problem).filter(
        models.Problem.status == "published",
        ~models.Problem.id.in_(completed_ids) if completed_ids else True).all()

    def score(p: models.Problem):
        return (
            2 if p.id in next_level else 0,
            1 if p.category in preferred_categories else 0,
            p.success_rate or 0,
            p.attempts or 0,
        )
    candidates.sort(key=score, reverse=True)
    items = candidates[:limit]
    return _paginated(db, items, len(candidates), limit, 0, user_id)


@router.get("/daily-challenge", response_model=schemas.DailyChallengeResponse)
def daily_challenge(
    user_id: Optional[str] = None,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    """Deterministic daily pick, persisted so everyone sees the same problem."""
    today = utcnow().date().isoformat()
    challenge = db.query(models.DailyChallenge).filter_by(challenge_date=today).first()
    if not challenge:
        published = (db.query(models.Problem)
                     .filter(models.Problem.status == "published")
                     .order_by(models.Problem.id.asc()).all())
        if not published:
            raise HTTPException(status_code=404, detail="No published problems available.")
        idx = int(hashlib.sha256(today.encode()).hexdigest(), 16) % len(published)
        challenge = models.DailyChallenge(challenge_date=today, problem_id=published[idx].id)
        db.add(challenge)
        db.commit()
        db.refresh(challenge)
    problem = db.query(models.Problem).filter_by(id=challenge.problem_id).first()
    bm, cp = _user_flags(db, user_id, [problem.id])
    return schemas.DailyChallengeResponse(
        challenge_date=today,
        problem=map_problem(problem,
                            bookmarked=(problem.id in bm) if user_id else None,
                            completed=(problem.id in cp) if user_id else None))


@router.get("/bookmarks", response_model=schemas.PaginatedResponse[schemas.ProblemResponse])
def list_bookmarks(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    base = (db.query(models.Problem)
            .join(models.Bookmark, models.Bookmark.problem_id == models.Problem.id)
            .filter(models.Bookmark.user_id == user_id)
            .order_by(models.Bookmark.created_at.desc()))
    total = base.count()
    items = base.offset(offset).limit(limit).all()
    return _paginated(db, items, total, limit, offset, user_id)


@router.get("/recently-viewed", response_model=schemas.PaginatedResponse[schemas.ProblemResponse])
def list_recently_viewed(
    user_id: str,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    base = (db.query(models.Problem)
            .join(models.RecentlyViewed, models.RecentlyViewed.problem_id == models.Problem.id)
            .filter(models.RecentlyViewed.user_id == user_id)
            .order_by(models.RecentlyViewed.viewed_at.desc()))
    total = base.count()
    items = base.offset(offset).limit(limit).all()
    return _paginated(db, items, total, limit, offset, user_id)


@router.get("/admin/audit-logs", response_model=List[schemas.AuditLogResponse])
def read_audit_logs(
    limit: Optional[int] = 50,
    offset: Optional[int] = 0,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key),
):
    return crud.get_audit_logs(db, limit=limit, offset=offset)


@router.get("/{problem_id}", response_model=schemas.ProblemResponse)
def read_problem(
    problem_id: str,
    user_id: Optional[str] = None,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Problem with ID '{problem_id}' not found.")
    if user_id:
        crud.touch_recently_viewed(db, user_id, problem_id)
    bm, cp = _user_flags(db, user_id, [problem_id])
    return map_problem(problem,
                       bookmarked=(problem_id in bm) if user_id else None,
                       completed=(problem_id in cp) if user_id else None)


@router.get("/{problem_id}/stats")
def problem_stats(
    problem_id: str,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail=f"Problem with ID '{problem_id}' not found.")
    stats = analytics.problem_average_stats(db, problem_id)
    stats.update({
        "attempts": problem.attempts or 0,
        "completions": problem.completions or 0,
        "success_rate": problem.success_rate or 0.0,
        "avg_rating": problem.avg_rating or 0.0,
        "rating_count": problem.rating_count or 0,
        "bookmark_count": problem.bookmark_count or 0,
        "avg_attempts_to_solve": problem.avg_attempts_to_solve or 0.0,
    })
    return stats


@router.post("/{problem_id}/rate", response_model=schemas.ProblemResponse)
def rate_problem(
    problem_id: str,
    req: schemas.RatingRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail=f"Problem with ID '{problem_id}' not found.")
    crud.upsert_rating(db, req.user_id, problem_id, req.rating)
    db.refresh(problem)
    return map_problem(problem)


@router.post("/{problem_id}/bookmark")
def toggle_bookmark(
    problem_id: str,
    req: schemas.BookmarkRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key),
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail=f"Problem with ID '{problem_id}' not found.")
    bookmarked = crud.toggle_bookmark(db, req.user_id, problem_id)
    return {"problem_id": problem_id, "user_id": req.user_id, "bookmarked": bookmarked,
            "bookmark_count": problem.bookmark_count}


@router.post("/", response_model=schemas.ProblemResponse, status_code=status.HTTP_201_CREATED)
def create_problem(
    problem_in: schemas.ProblemCreate,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key),
    x_admin_user: Optional[str] = Header(None, alias="X-Admin-User"),
):
    existing = crud.get_problem(db, problem_in.id)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Problem with ID '{problem_in.id}' already exists.")
    creator = x_admin_user or settings.ADMIN_USERNAME
    try:
        return map_problem(crud.create_problem(db, problem_in, creator=creator))
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        logger.error("DB error creating problem '%s': %s", problem_in.id, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Database error creating problem '{problem_in.id}'. "
                "This may indicate a schema mismatch between the application model and the "
                "live database. Check that all required columns exist and match the model definition."
            ),
        )


@router.patch("/{problem_id}", response_model=schemas.ProblemResponse)
def update_problem(
    problem_id: str,
    problem_update: schemas.ProblemUpdate,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key),
    x_admin_user: Optional[str] = Header(None, alias="X-Admin-User"),
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Problem with ID '{problem_id}' not found.")
    updater = x_admin_user or settings.ADMIN_USERNAME
    return map_problem(crud.update_problem(db, problem_id, problem_update, updater=updater))


@router.delete("/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_problem(
    problem_id: str,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key),
    x_admin_user: Optional[str] = Header(None, alias="X-Admin-User"),
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Problem with ID '{problem_id}' not found.")
    performed_by = x_admin_user or settings.ADMIN_USERNAME
    crud.delete_problem(db, problem_id, performed_by=performed_by)
    return None
