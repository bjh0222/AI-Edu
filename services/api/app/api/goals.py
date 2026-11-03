"""目标 / 诊断 / 计划 / 验收标准路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..schemas import (
    ConfirmAllIn,
    ConfirmAllOut,
    CriterionCreate,
    CriterionDraft,
    CriterionOut,
    CriterionPatch,
    DecisionIn,
    GenerateOut,  # noqa: F401
    GoalAssessmentOut,
    GoalCreate,
    GoalOut,
    GoalPatch,
    PlanOut,
)
from ..services import goals as goals_service
from .deps import get_ai

router = APIRouter()


@router.get("/goals", response_model=list[GoalOut], tags=["goals"])
def list_goals(include_archived: bool = Query(default=False), db: Session = Depends(get_db)):
    return goals_service.list_goals(db, include_archived=include_archived)


@router.post("/goals", response_model=GoalOut, tags=["goals"])
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)):
    return goals_service.create_goal(db, payload)


@router.get("/goals/{goal_id}", response_model=GoalOut, tags=["goals"])
def get_goal(goal_id: str, db: Session = Depends(get_db)):
    return goals_service.get_goal(db, goal_id)


@router.patch("/goals/{goal_id}", response_model=GoalOut, tags=["goals"])
def patch_goal(goal_id: str, payload: GoalPatch, db: Session = Depends(get_db)):
    return goals_service.patch_goal(db, goal_id, payload)


@router.delete("/goals/{goal_id}", tags=["goals"])
def archive_goal(
    goal_id: str,
    purge: bool = Query(default=False, description="true 时彻底删除目标及其全部数据（不可逆，先写 JSON 备份）"),
    db: Session = Depends(get_db),
):
    if purge:
        return goals_service.purge_goal(db, goal_id)
    return goals_service.archive_goal(db, goal_id)


@router.post("/goals/{goal_id}/unarchive", response_model=GoalOut, tags=["goals"])
def unarchive_goal(goal_id: str, db: Session = Depends(get_db)):
    return goals_service.unarchive_goal(db, goal_id)


@router.get("/goals/{goal_id}/diagnose", response_model=GoalAssessmentOut | None, tags=["goals"])
def get_diagnosis(goal_id: str, db: Session = Depends(get_db)):
    return goals_service.get_assessment(db, goal_id)


@router.post("/goals/{goal_id}/diagnose", response_model=GoalAssessmentOut, tags=["goals"])
def diagnose(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return goals_service.diagnose_goal(db, goal_id, ai)


@router.post("/goals/{goal_id}/decision", tags=["goals"])
def set_decision(goal_id: str, payload: DecisionIn, db: Session = Depends(get_db)):
    return goals_service.set_decision(db, goal_id, payload.decision, payload.reason)


@router.get("/goals/{goal_id}/plan", response_model=PlanOut | None, tags=["goals"])
def get_plan(goal_id: str, db: Session = Depends(get_db)):
    return goals_service.get_plan(db, goal_id)


@router.post("/goals/{goal_id}/plan", response_model=PlanOut, tags=["goals"])
def generate_plan(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return goals_service.generate_plan(db, goal_id, ai)


@router.patch("/plans/{plan_id}", response_model=PlanOut, tags=["goals"])
def patch_plan(plan_id: str, payload: dict, db: Session = Depends(get_db)):
    return goals_service.patch_plan(db, plan_id, payload)


@router.get("/goals/{goal_id}/criteria", response_model=list[CriterionOut], tags=["goals"])
def list_criteria(goal_id: str, db: Session = Depends(get_db)):
    return goals_service.list_criteria(db, goal_id)


@router.post("/goals/{goal_id}/criteria", response_model=list[CriterionOut], tags=["goals"])
def generate_criteria(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return goals_service.generate_criteria(db, goal_id, ai)


@router.post("/goals/{goal_id}/criteria/manual", response_model=CriterionOut, tags=["goals"])
def create_criterion(goal_id: str, payload: CriterionCreate, db: Session = Depends(get_db)):
    return goals_service.create_criterion(db, goal_id, payload)


@router.post("/goals/{goal_id}/criteria/confirm-all", response_model=ConfirmAllOut, tags=["goals"])
def confirm_all_criteria(goal_id: str, payload: ConfirmAllIn | None = None, db: Session = Depends(get_db)):
    """一键同意：批量确认该目标下待确认的验收标准。"""
    criterion_ids = payload.criterion_ids if payload else []
    return goals_service.confirm_all_criteria(db, goal_id, criterion_ids or None)


@router.patch("/criteria/{criterion_id}", response_model=CriterionOut, tags=["goals"])
def patch_criterion(criterion_id: str, payload: CriterionPatch, db: Session = Depends(get_db)):
    return goals_service.patch_criterion(db, criterion_id, payload)


@router.delete("/criteria/{criterion_id}", tags=["goals"])
def delete_criterion(criterion_id: str, db: Session = Depends(get_db)):
    return goals_service.delete_criterion(db, criterion_id)
