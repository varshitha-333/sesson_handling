from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app import crud, schemas, security
from app.database import get_db

router = APIRouter(
    prefix="/api/problems",
    tags=["problems"],
    dependencies=[Depends(security.verify_api_key)]
)

@router.get("/", response_model=List[schemas.ProblemResponse])
def read_problems(db: Session = Depends(get_db)):
    problems = crud.get_problems(db)
    return problems

@router.get("/{problem_id}", response_model=schemas.ProblemResponse)
def read_problem(problem_id: str, db: Session = Depends(get_db)):
    problem = crud.get_problem(db, problem_id)
    if not problem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with ID '{problem_id}' not found."
        )
    return problem
