from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app import crud, schemas, security
from app.database import get_db

router = APIRouter(
    prefix="/api/problems",
    tags=["problems"]
)

@router.get("/", response_model=List[schemas.ProblemResponse])
def read_problems(
    search: Optional[str] = None,
    status: Optional[str] = "published",
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key)
):
    problems = crud.get_problems(db, search=search, status=status, limit=limit, offset=offset)
    return problems

@router.get("/admin/audit-logs", response_model=List[schemas.AuditLogResponse])
def read_audit_logs(
    limit: Optional[int] = 50,
    offset: Optional[int] = 0,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key)
):
    return crud.get_audit_logs(db, limit=limit, offset=offset)

@router.get("/{problem_id}", response_model=schemas.ProblemResponse)
def read_problem(
    problem_id: str,
    db: Session = Depends(get_db),
    api_key: str = Depends(security.verify_api_key)
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with ID '{problem_id}' not found."
        )
    return problem

@router.post("/", response_model=schemas.ProblemResponse, status_code=status.HTTP_201_CREATED)
def create_problem(
    problem_in: schemas.ProblemCreate,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key)
):
    existing = crud.get_problem(db, problem_in.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Problem with ID '{problem_in.id}' already exists."
        )
    return crud.create_problem(db, problem_in)

@router.patch("/{problem_id}", response_model=schemas.ProblemResponse)
def update_problem(
    problem_id: str,
    problem_update: schemas.ProblemUpdate,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key)
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with ID '{problem_id}' not found."
        )
    return crud.update_problem(db, problem_id, problem_update)

@router.delete("/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_problem(
    problem_id: str,
    db: Session = Depends(get_db),
    admin_key: str = Depends(security.verify_admin_key)
):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with ID '{problem_id}' not found."
        )
    crud.delete_problem(db, problem_id)
    return None
