"""实践 / 评估 / 复盘路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..schemas import (
    AssessmentCreate,
    AssessmentOut,
    AssessmentPatch,
    AttemptCreate,
    AttemptOut,
    ReflectionCreate,
    ReflectionOut,
    ReflectionPatch,
    TaskCreate,
    TaskOut,
    TaskPatch,
)
from ..services import practice as practice_service
from .deps import get_ai

router = APIRouter()


@router.get("/goals/{goal_id}/tasks", response_model=list[TaskOut], tags=["practice"])
def list_tasks(goal_id: str, db: Session = Depends(get_db)):
    return practice_service.list_tasks(db, goal_id)


@router.post("/goals/{goal_id}/tasks", response_model=TaskOut, tags=["practice"])
def create_task(goal_id: str, payload: TaskCreate, db: Session = Depends(get_db)):
    return practice_service.create_task(db, goal_id, payload)


@router.patch("/tasks/{task_id}", response_model=TaskOut, tags=["practice"])
def patch_task(task_id: str, payload: TaskPatch, db: Session = Depends(get_db)):
    return practice_service.patch_task(db, task_id, payload)


@router.post("/tasks/{task_id}/attempts", response_model=AttemptOut, tags=["practice"])
def submit_attempt(task_id: str, payload: AttemptCreate, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return practice_service.submit_attempt(db, task_id, payload, ai)


@router.get("/tasks/{task_id}/attempts", response_model=list[AttemptOut], tags=["practice"])
def list_attempts(task_id: str, db: Session = Depends(get_db)):
    return practice_service.list_attempts(db, task_id)


@router.post("/goals/{goal_id}/assessments", response_model=AssessmentOut, tags=["practice"])
def create_assessment(goal_id: str, payload: AssessmentCreate, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return practice_service.create_assessment(db, goal_id, payload, ai)


@router.get("/goals/{goal_id}/assessments", response_model=list[AssessmentOut], tags=["practice"])
def list_assessments(goal_id: str, db: Session = Depends(get_db)):
    return practice_service.list_assessments(db, goal_id)


@router.patch("/assessments/{assessment_id}", tags=["practice"])
def patch_assessment(assessment_id: str, payload: AssessmentPatch, db: Session = Depends(get_db)):
    return practice_service.patch_assessment(db, assessment_id, payload)


@router.post("/goals/{goal_id}/reflections", response_model=ReflectionOut, tags=["practice"])
def create_reflection(goal_id: str, payload: ReflectionCreate, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return practice_service.create_reflection(db, goal_id, payload, ai)


@router.get("/goals/{goal_id}/reflections", response_model=list[ReflectionOut], tags=["practice"])
def list_reflections(goal_id: str, db: Session = Depends(get_db)):
    return practice_service.list_reflections(db, goal_id)


@router.patch("/reflections/{reflection_id}", tags=["practice"])
def patch_reflection(reflection_id: str, payload: ReflectionPatch, db: Session = Depends(get_db)):
    return practice_service.patch_reflection(db, reflection_id, payload)
