"""目标服务：创建 / 诊断 / 计划 / 验收标准。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..learning.disciplines import get_profile
from ..learning.engine import PHASES
from ..llm.service import AIService
from ..models import AcceptanceCriterion, GoalAssessment, LearningGoal, LearningPlan, PlanStep
from . import materials as materials_service
from .utils import criterion_dict, goal_dict, jdump, jload, set_status_at_least, step_dict


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


def list_goals(db: Session, include_archived: bool = False) -> list[dict]:
    query = db.query(LearningGoal)
    if not include_archived:
        query = query.filter(LearningGoal.archived.is_(False))
    goals = query.order_by(LearningGoal.created_at.desc()).all()
    return [goal_dict(g) for g in goals]


def purge_goal(db: Session, goal_id: str) -> dict:
    """彻底删除学习目标及其全部数据（不可逆）。

    删除前把目标相关的全部记录写一份 JSON 备份到 BACKUP_DIR，便于事后找回。
    概念按「多目标共享」规则处理：仅解除该目标的关联；若概念不再服务任何目标
    且只被该目标的教程引用，则一并删除。
    """
    from pathlib import Path

    from ..config import settings
    from ..models import (
        Assessment,
        Attempt,
        ChatMessage,
        Concept,
        ConceptRelation,
        GenerationJob,
        GoalMaterial,
        KnowledgeProposal,
        ModelCallLog,
        PracticeTask,
        Reflection,
        TrainingRecord,
        Tutorial,
        TutorialVersion,
    )

    goal = db.get(LearningGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})

    tutorials = db.query(Tutorial).filter(Tutorial.goal_id == goal.id).all()
    tutorial_ids = [t.id for t in tutorials]
    tasks = db.query(PracticeTask).filter(PracticeTask.goal_id == goal.id).all()
    task_ids = [t.id for t in tasks]

    # ---- 备份（删除前）
    backup = {
        "goal": goal_dict(goal),
        "assessment": None,
        "plans": [],
        "steps": [],
        "criteria": [],
        "tutorials": [],
        "tutorial_versions": [],
        "practice_tasks": [],
        "attempts": [],
        "assessments": [],
        "reflections": [],
        "materials": [],
        "concepts": [],
    }
    assessment = db.query(GoalAssessment).filter(GoalAssessment.goal_id == goal.id).first()
    if assessment is not None:
        backup["assessment"] = {c.name: getattr(assessment, c.name) for c in assessment.__table__.columns}
    plans = db.query(LearningPlan).filter(LearningPlan.goal_id == goal.id).all()
    for plan in plans:
        backup["plans"].append({c.name: getattr(plan, c.name) for c in plan.__table__.columns})
        for step in db.query(PlanStep).filter(PlanStep.plan_id == plan.id).all():
            backup["steps"].append({c.name: getattr(step, c.name) for c in step.__table__.columns})
    for criterion in db.query(AcceptanceCriterion).filter(AcceptanceCriterion.goal_id == goal.id).all():
        backup["criteria"].append({c.name: getattr(criterion, c.name) for c in criterion.__table__.columns})
    for tutorial in tutorials:
        backup["tutorials"].append({c.name: getattr(tutorial, c.name) for c in tutorial.__table__.columns})
        for version in db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).all():
            backup["tutorial_versions"].append({c.name: getattr(version, c.name) for c in version.__table__.columns})
    for task in tasks:
        backup["practice_tasks"].append({c.name: getattr(task, c.name) for c in task.__table__.columns})
        for attempt in db.query(Attempt).filter(Attempt.task_id == task.id).all():
            backup["attempts"].append({c.name: getattr(attempt, c.name) for c in attempt.__table__.columns})
    for row in db.query(Assessment).filter(Assessment.goal_id == goal.id).all():
        backup["assessments"].append({c.name: getattr(row, c.name) for c in row.__table__.columns})
    for row in db.query(Reflection).filter(Reflection.goal_id == goal.id).all():
        backup["reflections"].append({c.name: getattr(row, c.name) for c in row.__table__.columns})
    materials = db.query(GoalMaterial).filter(GoalMaterial.goal_id == goal.id).all()
    for material in materials:
        backup["materials"].append({c.name: getattr(material, c.name) for c in material.__table__.columns})
    concepts = db.query(Concept).all()
    goal_concepts = [c for c in concepts if goal.id in jload(c.goal_ids, [])]
    for concept in goal_concepts:
        backup["concepts"].append(
            {
                "id": concept.id,
                "title": concept.title,
                "definition": concept.definition,
                "domain_key": concept.domain_key,
                "goal_ids": jload(concept.goal_ids, []),
                "source_refs": jload(concept.source_refs, []),
            }
        )

    import json as _json
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(getattr(settings, "backup_dir", "data/backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"goal-{goal.id}-{stamp}.json"
    backup_path.write_text(_json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 删除（显式级联，不依赖数据库外键）
    deletes = {
        "attempts": 0,
        "assessments": 0,
        "practice_tasks": 0,
        "tutorial_versions": 0,
        "tutorials": 0,
        "criteria": 0,
        "plans": 0,
        "steps": 0,
        "reflections": 0,
        "materials": 0,
        "chat_messages": 0,
        "generation_jobs": 0,
        "concepts": 0,
        "relations": 0,
    }
    for task in tasks:
        deletes["attempts"] += db.query(Attempt).filter(Attempt.task_id == task.id).delete(synchronize_session=False)
    deletes["assessments"] = db.query(Assessment).filter(Assessment.goal_id == goal.id).delete(synchronize_session=False)
    deletes["practice_tasks"] = db.query(PracticeTask).filter(PracticeTask.goal_id == goal.id).delete(
        synchronize_session=False
    )
    for tutorial in tutorials:
        deletes["tutorial_versions"] += db.query(TutorialVersion).filter(
            TutorialVersion.tutorial_id == tutorial.id
        ).delete(synchronize_session=False)
    deletes["tutorials"] = db.query(Tutorial).filter(Tutorial.goal_id == goal.id).delete(synchronize_session=False)
    deletes["criteria"] = db.query(AcceptanceCriterion).filter(AcceptanceCriterion.goal_id == goal.id).delete(
        synchronize_session=False
    )
    plan_ids = [p.id for p in plans]
    if plan_ids:
        deletes["steps"] = db.query(PlanStep).filter(PlanStep.plan_id.in_(plan_ids)).delete(synchronize_session=False)
    deletes["plans"] = db.query(LearningPlan).filter(LearningPlan.goal_id == goal.id).delete(synchronize_session=False)
    db.query(GoalAssessment).filter(GoalAssessment.goal_id == goal.id).delete(synchronize_session=False)
    deletes["reflections"] = db.query(Reflection).filter(Reflection.goal_id == goal.id).delete(
        synchronize_session=False
    )
    deletes["materials"] = db.query(GoalMaterial).filter(GoalMaterial.goal_id == goal.id).delete(
        synchronize_session=False
    )
    deletes["chat_messages"] = db.query(ChatMessage).filter(ChatMessage.goal_id == goal.id).delete(
        synchronize_session=False
    )
    deletes["generation_jobs"] = db.query(GenerationJob).filter(GenerationJob.goal_id == goal.id).delete(
        synchronize_session=False
    )
    # 训练样本 / 调用日志保留（历史审计），仅去除目标关联，避免导出时指向已删除目标
    db.query(TrainingRecord).filter(TrainingRecord.goal_id == goal.id).update(
        {TrainingRecord.goal_id: None}, synchronize_session=False
    )
    db.query(ModelCallLog).filter(ModelCallLog.goal_id == goal.id).update(
        {ModelCallLog.goal_id: None}, synchronize_session=False
    )

    # 概念：解除关联；不再服务任何目标且仅被该目标教程引用的概念一并删除
    for concept in concepts:
        goal_ids = jload(concept.goal_ids, [])
        if goal.id not in goal_ids:
            continue
        remaining_goals = [g for g in goal_ids if g != goal.id]
        refs = [
            r
            for r in jload(concept.source_refs, [])
            if not (r.get("type") == "tutorial_section" and str(r.get("tutorial_id", "")) in tutorial_ids)
        ]
        if not remaining_goals and not refs:
            deletes["relations"] += db.query(ConceptRelation).filter(
                (ConceptRelation.from_concept_id == concept.id)
                | (ConceptRelation.to_concept_id == concept.id)
            ).delete(synchronize_session=False)
            db.delete(concept)
            deletes["concepts"] += 1
        else:
            concept.goal_ids = jdump(remaining_goals)
            concept.source_refs = jdump(refs[:40])
    # 清理引用已删除概念的待处理提议
    for proposal in db.query(KnowledgeProposal).filter(KnowledgeProposal.status == "pending").all():
        payload = jload(proposal.payload, {})
        if payload.get("goal_id") == goal.id:
            db.delete(proposal)

    # 材料文件目录
    try:
        goal_dir = Path(settings.materials_dir) / goal.id
        if goal_dir.exists():
            import shutil

            shutil.rmtree(goal_dir, ignore_errors=True)
    except OSError:
        pass

    db.delete(goal)
    db.commit()
    return {
        "ok": True,
        "goal_id": goal_id,
        "title": goal.title,
        "deleted": deletes,
        "backup_path": str(backup_path),
    }


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
    materials_text = materials_service.materials_context(db, goal.id)
    data = ai.diagnose(goal, profile, materials_text)

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
    materials_text = materials_service.materials_context(db, goal.id)
    data = ai.plan(goal, profile, materials_text)

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
