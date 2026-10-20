"""一键生成教材：把「诊断 → 计划 → 验收标准（批量同意）→ 大纲 → 全部章节」串成一次点击。

设计要点：
- 幂等：已完成的阶段跳过并标记为 reused，已有章节时不再重复生成；
- 每一步都复用既有服务，单步失败会保留此前已完成的数据（服务内部各自提交）；
- 章节生成仍是后台任务，返回 job_id 供前端轮询进度与 token 消耗。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..llm.service import AIService
from ..models import GenerationJob, GoalAssessment, LearningGoal
from . import goals as goals_service
from . import tutorials as tutorials_service


def _step(key: str, label: str, status: str, detail: str = "") -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _active_sections_job(db: Session, goal_id: str) -> GenerationJob | None:
    return (
        db.query(GenerationJob)
        .filter(
            GenerationJob.goal_id == goal_id,
            GenerationJob.job_type == "tutorial_sections",
            GenerationJob.status.in_(("queued", "running")),
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )


def _usable_tutorial(tutorials: list[dict]) -> dict | None:
    for item in tutorials:
        content = (item.get("current_version") or {}).get("content") or {}
        if content.get("outline"):
            return item
    return None


def quickstart(db: Session, goal_id: str, ai: AIService) -> dict:
    goal = db.get(LearningGoal, goal_id)
    if goal is None or goal.archived:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})

    steps: list[dict] = []

    # ① 价值诊断
    assessment = (
        db.query(GoalAssessment)
        .filter(GoalAssessment.goal_id == goal.id)
        .order_by(GoalAssessment.created_at.desc())
        .first()
    )
    if assessment is None:
        goals_service.diagnose_goal(db, goal.id, ai)
        assessment = (
            db.query(GoalAssessment)
            .filter(GoalAssessment.goal_id == goal.id)
            .order_by(GoalAssessment.created_at.desc())
            .first()
        )
        steps.append(_step("diagnose", "价值诊断", "created", "已生成诊断与建议"))
    else:
        steps.append(_step("diagnose", "价值诊断", "reused", "沿用已有诊断"))

    # ② 用户决定（一键同意 = 按建议继续）
    if assessment is not None and not assessment.user_decision:
        goals_service.set_decision(db, goal.id, "继续", "一键同意：按诊断建议推进")
        steps.append(_step("decision", "你的决定", "created", "已按建议选择「继续」"))
    else:
        steps.append(_step("decision", "你的决定", "reused", assessment.user_decision if assessment else ""))

    # ③ 学习计划
    plan = goals_service.get_plan(db, goal.id)
    if plan is None:
        plan = goals_service.generate_plan(db, goal.id, ai)
        steps.append(_step("plan", "学习计划", "created", f"{len(plan.get('steps', []))} 个阶段"))
    else:
        steps.append(_step("plan", "学习计划", "reused", f"沿用 v{plan.get('version', 1)}"))

    # ④ 验收标准 + 一键同意
    criteria = goals_service.list_criteria(db, goal.id)
    if not criteria:
        criteria = goals_service.generate_criteria(db, goal.id, ai)
        generated_note = f"新生成 {len(criteria)} 条"
    else:
        generated_note = f"沿用 {len(criteria)} 条"
    result = goals_service.confirm_all_criteria(db, goal.id)
    criteria = result["criteria"]
    steps.append(
        _step(
            "criteria",
            "验收标准（一键同意）",
            "created" if result["changed"] else "reused",
            f"{generated_note}，本次新确认 {result['changed']} 条，共 {result['confirmed']} 条已确认",
        )
    )

    # ⑤ 教程大纲
    tutorials = tutorials_service.list_tutorials(db, goal.id)
    tutorial = _usable_tutorial(tutorials)
    if tutorial is None:
        outline_result = tutorials_service.generate_outline(db, goal.id, ai)
        tutorial = outline_result["tutorial"]
        outline_note = f"{len(tutorial['current_version']['content']['outline'])} 节大纲"
        steps.append(_step("outline", "教程大纲", "created", outline_note))
    else:
        outline_note = f"{len(tutorial['current_version']['content']['outline'])} 节大纲"
        steps.append(_step("outline", "教程大纲", "reused", outline_note))

    # ⑥ 全部章节
    content = (tutorial.get("current_version") or {}).get("content") or {}
    sections = content.get("sections") or []
    job_id: str | None = None
    if sections:
        steps.append(_step("sections", "全部章节", "reused", f"已生成 {len(sections)} 节"))
    else:
        active = _active_sections_job(db, goal.id)
        if active is not None:
            job_id = active.id
            steps.append(_step("sections", "全部章节", "running", f"后台生成中（{active.progress}%）"))
        else:
            started = tutorials_service.start_sections(db, tutorial["id"], ai)
            job_id = started["job"].id
            steps.append(_step("sections", "全部章节", "created", "已提交后台生成任务"))

    tutorial = tutorials_service.get_tutorial(db, tutorial["id"])
    return {
        "goal_id": goal.id,
        "steps": steps,
        "tutorial": tutorial,
        "job_id": job_id,
        "demo": ai.is_demo,
    }
