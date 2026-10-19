"""实践 / 反馈 / 能力评估服务。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..learning.disciplines import get_profile
from ..llm.service import AIService, AIServiceError
from ..models import Assessment, Attempt, LearningGoal, PracticeTask, Reflection
from . import goals as goals_service
from .utils import jdump, jload, set_status_at_least, task_dict


def _goal(db: Session, goal_id: str) -> LearningGoal:
    goal = db.get(LearningGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    return goal


def _get_task(db: Session, task_id: str) -> PracticeTask:
    task = db.get(PracticeTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "实践任务不存在"})
    return task


def create_task(db: Session, goal_id: str, payload) -> dict:
    goal = _goal(db, goal_id)
    task = PracticeTask(
        goal_id=goal.id,
        plan_step_id=payload.plan_step_id,
        tutorial_id=payload.tutorial_id,
        title=payload.title,
        instructions=payload.instructions,
        task_type=payload.task_type,
        expected_artifact=payload.expected_artifact,
        validation_rule=payload.validation_rule,
    )
    db.add(task)
    db.commit()
    return task_dict(task)


def list_tasks(db: Session, goal_id: str) -> list[dict]:
    _goal(db, goal_id)
    rows = (
        db.query(PracticeTask)
        .filter(PracticeTask.goal_id == goal_id)
        .order_by(PracticeTask.created_at.asc())
        .all()
    )
    return [task_dict(t) for t in rows]


def patch_task(db: Session, task_id: str, payload) -> dict:
    task = _get_task(db, task_id)
    for field in ("title", "instructions", "expected_artifact", "validation_rule", "status"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(task, field, value)
    db.commit()
    return task_dict(task)


def submit_attempt(db: Session, task_id: str, payload, ai: AIService) -> dict:
    task = _get_task(db, task_id)
    goal = _goal(db, task.goal_id)
    criteria = goals_service.confirmed_criteria(db, goal.id)

    attempt = Attempt(
        task_id=task.id,
        artifact=payload.artifact,
        artifact_type=payload.artifact_type,
        result=payload.result,
        errors=payload.errors,
        help_level=payload.help_level,
        user_explanation=payload.user_explanation,
    )
    db.add(attempt)
    db.flush()
    set_status_at_least(goal, "practice")

    feedback: dict = {}
    if criteria:
        try:
            feedback = ai.feedback(goal, criteria, task, attempt)
        except AIServiceError as exc:
            db.rollback()
            raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
        attempt.feedback = jdump(feedback)
        task.status = "doing" if task.status == "todo" else task.status
        set_status_at_least(goal, "feedback")
    else:
        feedback = {"items": [], "summary": "尚无已确认验收标准，无法生成逐项反馈。", "weak_points": ""}
        attempt.feedback = jdump(feedback)

    db.commit()
    return {
        "id": attempt.id,
        "task_id": task.id,
        "artifact": attempt.artifact,
        "artifact_type": attempt.artifact_type,
        "result": attempt.result,
        "errors": attempt.errors,
        "help_level": attempt.help_level,
        "user_explanation": attempt.user_explanation,
        "feedback": feedback,
        "created_at": attempt.created_at,
        "demo": ai.is_demo,
    }


def list_attempts(db: Session, task_id: str) -> list[dict]:
    _get_task(db, task_id)
    rows = (
        db.query(Attempt)
        .filter(Attempt.task_id == task_id)
        .order_by(Attempt.created_at.asc())
        .all()
    )
    return [
        {
            "id": a.id,
            "task_id": a.task_id,
            "artifact": a.artifact,
            "artifact_type": a.artifact_type,
            "result": a.result,
            "errors": a.errors,
            "help_level": a.help_level,
            "user_explanation": a.user_explanation,
            "feedback": jload(a.feedback, {}),
            "created_at": a.created_at,
            "demo": False,
        }
        for a in rows
    ]


# ---------------------------------------------------------------- assessment


def create_assessment(db: Session, goal_id: str, payload, ai: AIService) -> dict:
    goal = _goal(db, goal_id)
    profile = get_profile(goal.domain_key)
    try:
        data = ai.assessment(goal, profile)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
    assessment = Assessment(
        goal_id=goal.id,
        task_id=payload.task_id,
        assessment_type=payload.assessment_type,
        rubric=jdump(data.get("rubric", [])),
        result="",
        weak_points="",
    )
    db.add(assessment)
    set_status_at_least(goal, "assessment")
    db.commit()
    out = {
        "id": assessment.id,
        "goal_id": goal.id,
        "task_id": assessment.task_id,
        "assessment_type": assessment.assessment_type,
        "rubric": jload(assessment.rubric, []),
        "result": assessment.result,
        "confidence": assessment.confidence,
        "evidence_refs": jload(assessment.evidence_refs, []),
        "weak_points": assessment.weak_points,
        "created_at": assessment.created_at,
        "demo": ai.is_demo,
    }
    out["independent_task"] = data.get("independent_task", {})
    out["variant_task"] = data.get("variant_task", {})
    out["evidence_hint"] = data.get("evidence_hint", "")
    return out


def list_assessments(db: Session, goal_id: str) -> list[dict]:
    _goal(db, goal_id)
    rows = (
        db.query(Assessment)
        .filter(Assessment.goal_id == goal_id)
        .order_by(Assessment.created_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "goal_id": a.goal_id,
            "task_id": a.task_id,
            "assessment_type": a.assessment_type,
            "rubric": jload(a.rubric, []),
            "result": a.result,
            "confidence": a.confidence,
            "evidence_refs": jload(a.evidence_refs, []),
            "weak_points": a.weak_points,
            "created_at": a.created_at,
            "demo": False,
        }
        for a in rows
    ]


def patch_assessment(db: Session, assessment_id: str, payload) -> dict:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail={"code": "assessment_not_found", "message": "评估不存在"})
    for field in ("result", "weak_points", "confidence"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(assessment, field, value)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- reflection


def create_reflection(db: Session, goal_id: str, payload, ai: AIService) -> dict:
    goal = _goal(db, goal_id)
    attempts = (
        db.query(Attempt)
        .join(PracticeTask, Attempt.task_id == PracticeTask.id)
        .filter(PracticeTask.goal_id == goal.id)
        .order_by(Attempt.created_at.desc())
        .limit(10)
        .all()
    )
    tasks_done = (
        db.query(PracticeTask)
        .filter(PracticeTask.goal_id == goal.id, PracticeTask.status == "done")
        .count()
    )
    context = {
        "attempt_count": len(attempts),
        "tasks_done": tasks_done,
        "attempts": [
            {"help_level": a.help_level, "artifact_len": len(a.artifact or ""), "errors": (a.errors or "")[:200]}
            for a in attempts
        ],
    }
    try:
        data = ai.reflection(goal, context)
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
    reflection = Reflection(
        goal_id=goal.id,
        summary=payload.summary or str(data.get("summary", "")),
        learned_capabilities=payload.learned_capabilities or str(data.get("learned_capabilities", "")),
        unresolved_gaps=payload.unresolved_gaps or str(data.get("unresolved_gaps", "")),
        next_actions=payload.next_actions or str(data.get("next_actions", "")),
        evidence_refs=jdump([a.id for a in attempts]),
    )
    db.add(reflection)
    set_status_at_least(goal, "reflection")
    db.commit()
    return {
        "id": reflection.id,
        "goal_id": goal.id,
        "summary": reflection.summary,
        "learned_capabilities": reflection.learned_capabilities,
        "unresolved_gaps": reflection.unresolved_gaps,
        "next_actions": reflection.next_actions,
        "evidence_refs": jload(reflection.evidence_refs, []),
        "created_at": reflection.created_at,
        "demo": ai.is_demo,
        "candidate_concepts": data.get("candidate_concepts", []),
    }


def list_reflections(db: Session, goal_id: str) -> list[dict]:
    _goal(db, goal_id)
    rows = (
        db.query(Reflection)
        .filter(Reflection.goal_id == goal_id)
        .order_by(Reflection.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "goal_id": r.goal_id,
            "summary": r.summary,
            "learned_capabilities": r.learned_capabilities,
            "unresolved_gaps": r.unresolved_gaps,
            "next_actions": r.next_actions,
            "evidence_refs": jload(r.evidence_refs, []),
            "created_at": r.created_at,
            "demo": False,
        }
        for r in rows
    ]


def patch_reflection(db: Session, reflection_id: str, payload) -> dict:
    reflection = db.get(Reflection, reflection_id)
    if reflection is None:
        raise HTTPException(status_code=404, detail={"code": "reflection_not_found", "message": "复盘不存在"})
    for field in ("summary", "learned_capabilities", "unresolved_gaps", "next_actions"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(reflection, field, value)
    db.commit()
    return {"ok": True}
