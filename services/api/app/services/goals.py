"""目标服务：创建 / 诊断 / 计划 / 验收标准。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..learning.disciplines import get_profile
from ..learning.engine import PHASES
from ..llm.service import AIService
from ..models import AcceptanceCriterion, GoalAssessment, LearningGoal, LearningPlan, PlanStep
from .utils import criterion_dict, goal_dict, jdump, set_status_at_least, step_dict


def _get_goal(db: Session, goal_id: str) -> LearningGoal:
    goal = db.get(LearningGoal, goal_id)
    if goal is None or goal.archived:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    return goal


def create_goal(db: Session, payload) -> dict:
    goal = LearningGoal(
        title=payload.title,
        domain_key=payload.domain_key or "computer_cli",
        motivation=payload.motivation,
        application_context=payload.application_context,
        current_level=payload.current_level,
        time_budget=payload.time_budget,
    )
    db.add(goal)
    db.commit()
    return goal_dict(goal)


def list_goals(db: Session) -> list[dict]:
    goals = (
        db.query(LearningGoal)
        .filter(LearningGoal.archived.is_(False))
        .order_by(LearningGoal.created_at.desc())
        .all()
    )
    return [goal_dict(g) for g in goals]


def get_goal(db: Session, goal_id: str) -> dict:
    goal = _get_goal(db, goal_id)
    return goal_dict(goal)


def patch_goal(db: Session, goal_id: str, payload) -> dict:
    goal = _get_goal(db, goal_id)
    for field in ("title", "motivation", "application_context", "current_level", "time_budget", "status", "user_notes"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(goal, field, value)
    db.commit()
    return goal_dict(goal)


def archive_goal(db: Session, goal_id: str) -> dict:
    goal = _get_goal(db, goal_id)
    goal.archived = True
    db.commit()
    return {"ok": True}


def diagnose_goal(db: Session, goal_id: str, ai: AIService) -> dict:
    goal = _get_goal(db, goal_id)
    profile = get_profile(goal.domain_key)
    data = ai.diagnose(goal, profile)

    assessment = (
        db.query(GoalAssessment)
        .filter(GoalAssessment.goal_id == goal.id)
        .order_by(GoalAssessment.created_at.desc())
        .first()
    )
    if assessment is None:
        assessment = GoalAssessment(goal_id=goal.id)
        db.add(assessment)
    assessment.benefits = data.get("benefits", "")
    assessment.prerequisites = data.get("prerequisites", "")
    assessment.alternatives = data.get("alternatives", "")
    assessment.assumptions = data.get("assumptions", "")
    assessment.uncertainties = data.get("uncertainties", "")
    assessment.recommendation = data.get("recommendation", "")
    set_status_at_least(goal, "diagnosis")
    db.commit()
    return {
        "id": assessment.id,
        "goal_id": goal.id,
        "benefits": assessment.benefits,
        "prerequisites": assessment.prerequisites,
        "alternatives": assessment.alternatives,
        "assumptions": assessment.assumptions,
        "uncertainties": assessment.uncertainties,
        "recommendation": assessment.recommendation,
        "user_decision": assessment.user_decision,
        "decision_reason": assessment.decision_reason,
        "demo": ai.is_demo,
    }


def get_assessment(db: Session, goal_id: str) -> dict | None:
    _get_goal(db, goal_id)
    assessment = (
        db.query(GoalAssessment)
        .filter(GoalAssessment.goal_id == goal_id)
        .order_by(GoalAssessment.created_at.desc())
        .first()
    )
    if assessment is None:
        return None
    return {
        "id": assessment.id,
        "goal_id": assessment.goal_id,
        "benefits": assessment.benefits,
        "prerequisites": assessment.prerequisites,
        "alternatives": assessment.alternatives,
        "assumptions": assessment.assumptions,
        "uncertainties": assessment.uncertainties,
        "recommendation": assessment.recommendation,
        "user_decision": assessment.user_decision,
        "decision_reason": assessment.decision_reason,
        "demo": False,
    }


def set_decision(db: Session, goal_id: str, decision: str, reason: str) -> dict:
    goal = _get_goal(db, goal_id)
    assessment = (
        db.query(GoalAssessment)
        .filter(GoalAssessment.goal_id == goal.id)
        .order_by(GoalAssessment.created_at.desc())
        .first()
    )
    if assessment is None:
        raise HTTPException(status_code=409, detail={"code": "no_diagnosis", "message": "请先执行目标诊断"})
    assessment.user_decision = decision
    assessment.decision_reason = reason
    db.commit()
    return {"ok": True}


def get_plan(db: Session, goal_id: str) -> dict | None:
    _get_goal(db, goal_id)
    plan = (
        db.query(LearningPlan)
        .filter(LearningPlan.goal_id == goal_id)
        .order_by(LearningPlan.version.desc())
        .first()
    )
    if plan is None:
        return None
    steps = (
        db.query(PlanStep)
        .filter(PlanStep.plan_id == plan.id)
        .order_by(PlanStep.order_index.asc())
        .all()
    )
    return {
        "id": plan.id,
        "goal_id": plan.goal_id,
        "version": plan.version,
        "status": plan.status,
        "steps": [step_dict(s) for s in steps],
        "demo": False,
    }


def generate_plan(db: Session, goal_id: str, ai: AIService) -> dict:
    goal = _get_goal(db, goal_id)
    profile = get_profile(goal.domain_key)
    data = ai.plan(goal, profile)

    last = (
        db.query(LearningPlan)
        .filter(LearningPlan.goal_id == goal.id)
        .order_by(LearningPlan.version.desc())
        .first()
    )
    version = (last.version + 1) if last else 1
    plan = LearningPlan(goal_id=goal.id, version=version, status="active", generated_at="")
    db.add(plan)
    db.flush()
    steps = []
    for idx, raw in enumerate(data.get("steps", [])):
        step = PlanStep(
            plan_id=plan.id,
            order_index=idx,
            title=str(raw.get("title", f"第 {idx + 1} 步"))[:200],
            objective=str(raw.get("objective", "")),
            estimated_effort=str(raw.get("estimated_effort", "")),
        )
        db.add(step)
        steps.append(step)
    set_status_at_least(goal, "planning")
    db.commit()
    return {
        "id": plan.id,
        "goal_id": goal.id,
        "version": plan.version,
        "status": plan.status,
        "steps": [step_dict(s) for s in steps],
        "demo": ai.is_demo,
    }


def patch_plan(db: Session, plan_id: str, payload: dict) -> dict:
    plan = db.get(LearningPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail={"code": "plan_not_found", "message": "学习计划不存在"})
    goal = db.get(LearningGoal, plan.goal_id)
    for step_payload in payload.get("steps", []):
        step = db.get(PlanStep, step_payload.get("id", ""))
        if step is None or step.plan_id != plan.id:
            continue
        for field in ("title", "objective", "status", "estimated_effort"):
            if field in step_payload and step_payload[field] is not None:
                setattr(step, field, step_payload[field])
    if goal:
        set_status_at_least(goal, "planning")
    db.commit()
    return get_plan(db, plan.goal_id)


def list_criteria(db: Session, goal_id: str) -> list[dict]:
    _get_goal(db, goal_id)
    rows = (
        db.query(AcceptanceCriterion)
        .filter(AcceptanceCriterion.goal_id == goal_id)
        .order_by(AcceptanceCriterion.created_at.asc())
        .all()
    )
    return [criterion_dict(c) for c in rows]


def generate_criteria(db: Session, goal_id: str, ai: AIService) -> list[dict]:
    goal = _get_goal(db, goal_id)
    profile = get_profile(goal.domain_key)
    data = ai.criteria(goal, profile)
    created = []
    for raw in data.get("criteria", []):
        statement = str(raw.get("statement", "")).strip()
        if not statement:
            continue
        c = AcceptanceCriterion(
            goal_id=goal.id,
            statement=statement,
            conditions=str(raw.get("conditions", "")),
            evidence_type=str(raw.get("evidence_type", "product")),
            pass_rule=str(raw.get("pass_rule", "")),
            rationale=str(raw.get("rationale", "")),
            status="pending",
        )
        db.add(c)
        created.append(c)
    set_status_at_least(goal, "acceptance_design")
    db.commit()
    return [criterion_dict(c) for c in created]


def create_criterion(db: Session, goal_id: str, payload) -> dict:
    goal = _get_goal(db, goal_id)
    c = AcceptanceCriterion(
        goal_id=goal.id,
        plan_step_id=payload.plan_step_id,
        statement=payload.statement,
        conditions=payload.conditions,
        evidence_type=payload.evidence_type,
        pass_rule=payload.pass_rule,
        rationale=payload.rationale,
        status="pending",
    )
    db.add(c)
    set_status_at_least(goal, "acceptance_design")
    db.commit()
    return criterion_dict(c)


def patch_criterion(db: Session, criterion_id: str, payload) -> dict:
    c = db.get(AcceptanceCriterion, criterion_id)
    if c is None:
        raise HTTPException(status_code=404, detail={"code": "criterion_not_found", "message": "验收标准不存在"})
    for field in ("statement", "conditions", "evidence_type", "pass_rule", "status", "rationale"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(c, field, value)
    db.commit()
    return criterion_dict(c)


def delete_criterion(db: Session, criterion_id: str) -> dict:
    c = db.get(AcceptanceCriterion, criterion_id)
    if c is None:
        raise HTTPException(status_code=404, detail={"code": "criterion_not_found", "message": "验收标准不存在"})
    db.delete(c)
    db.commit()
    return {"ok": True}


def confirmed_criteria(db: Session, goal_id: str) -> list[dict]:
    rows = (
        db.query(AcceptanceCriterion)
        .filter(AcceptanceCriterion.goal_id == goal_id, AcceptanceCriterion.status == "confirmed")
        .order_by(AcceptanceCriterion.created_at.asc())
        .all()
    )
    return [criterion_dict(c) for c in rows]


def confirm_all_criteria(db: Session, goal_id: str, criterion_ids: list[str] | None = None) -> dict:
    """一键同意：把待确认的验收标准批量置为 confirmed。

    - 不覆盖用户已显式「拒绝」的标准（rejected 保持不变）；
    - 可传入 criterion_ids 只确认指定项，否则确认该目标下全部待确认项。
    """
    goal = _get_goal(db, goal_id)
    query = db.query(AcceptanceCriterion).filter(AcceptanceCriterion.goal_id == goal.id)
    if criterion_ids:
        query = query.filter(AcceptanceCriterion.id.in_(criterion_ids))
    rows = query.order_by(AcceptanceCriterion.created_at.asc()).all()
    confirmed = 0
    changed = 0
    for row in rows:
        if row.status == "confirmed":
            confirmed += 1
        elif row.status == "pending":
            row.status = "confirmed"
            confirmed += 1
            changed += 1
    set_status_at_least(goal, "acceptance_design")
    db.commit()
    return {
        "goal_id": goal.id,
        "confirmed": confirmed,
        "changed": changed,
        "criteria": [criterion_dict(c) for c in rows],
    }
