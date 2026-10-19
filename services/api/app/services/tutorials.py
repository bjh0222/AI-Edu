"""教程服务：大纲 → 分节生成 → 质量检查 → 版本管理。"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..learning.disciplines import get_profile
from ..learning.engine import check_structure
from ..llm.service import AIService, AIServiceError
from ..models import GenerationJob, PracticeTask, Tutorial, TutorialVersion
from . import goals as goals_service
from .utils import criterion_dict, jdump, jload, set_status_at_least, tutorial_version_dict

MAX_SECTIONS_HINT = 8


def _get_tutorial(db: Session, tutorial_id: str) -> Tutorial:
    tutorial = db.get(Tutorial, tutorial_id)
    if tutorial is None:
        raise HTTPException(status_code=404, detail={"code": "tutorial_not_found", "message": "教程不存在"})
    return tutorial


def _goal_for(db: Session, goal_id: str):
    from ..models import LearningGoal

    goal = db.get(LearningGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    return goal


def _current_version(db: Session, tutorial: Tutorial) -> TutorialVersion | None:
    if not tutorial.current_version_id:
        return None
    return db.get(TutorialVersion, tutorial.current_version_id)


def tutorial_dict(db: Session, tutorial: Tutorial) -> dict:
    version = _current_version(db, tutorial)
    count = db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).count()
    return {
        "id": tutorial.id,
        "goal_id": tutorial.goal_id,
        "plan_step_id": tutorial.plan_step_id,
        "title": tutorial.title,
        "status": tutorial.status,
        "current_version": tutorial_version_dict(version) if version else None,
        "history_count": count,
    }


def list_tutorials(db: Session, goal_id: str) -> list[dict]:
    rows = (
        db.query(Tutorial)
        .filter(Tutorial.goal_id == goal_id)
        .order_by(Tutorial.created_at.desc())
        .all()
    )
    return [tutorial_dict(db, t) for t in rows]


def get_tutorial(db: Session, tutorial_id: str) -> dict:
    return tutorial_dict(db, _get_tutorial(db, tutorial_id))


def _criteria_list(db: Session, goal_id: str) -> list[dict]:
    confirmed = goals_service.confirmed_criteria(db, goal_id)
    if not confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "no_confirmed_criteria",
                "message": "尚无已确认的验收标准：请先设计并确认验收标准，再生成教程（先标准、后教程）。",
            },
        )
    return confirmed


def generate_outline(db: Session, goal_id: str, ai: AIService) -> dict:
    goal = _goal_for(db, goal_id)
    criteria = _criteria_list(db, goal.id)
    profile = get_profile(goal.domain_key)

    job = GenerationJob(goal_id=goal.id, job_type="tutorial_outline", status="running", progress=10, stage="生成大纲")
    db.add(job)
    db.flush()
    try:
        data = ai.outline(goal, profile, [{"id": c["id"], "statement": c["statement"]} for c in criteria])
        raw_sections = data.get("sections", [])[:MAX_SECTIONS_HINT]
        outline = []
        for raw in raw_sections:
            outline.append({
                "id": uuid.uuid4().hex[:8],
                "title": str(raw.get("title", "未命名章节"))[:120],
                "summary": str(raw.get("summary", "")),
                "criteria_ids": [str(x) for x in raw.get("criteria_ids", []) if str(x)],
            })
        content = {"outline": outline, "sections": []}

        tutorial = Tutorial(
            goal_id=goal.id,
            title=f"{goal.title} · 学习教程",
            status="outline",
        )
        db.add(tutorial)
        db.flush()
        version = TutorialVersion(
            tutorial_id=tutorial.id,
            version=1,
            content_json=jdump(content),
            prompt_version="v1",
            model_provider="demo" if ai.is_demo else "openai-compatible",
            model_name="demo" if ai.is_demo else "configured",
            quality_report=jdump({}),
        )
        db.add(version)
        db.flush()
        tutorial.current_version_id = version.id
        set_status_at_least(goal, "learning")
        job.status = "done"
        job.progress = 100
        job.stage = "大纲完成"
        db.commit()
        return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo}
    except AIServiceError as exc:
        job.status = "failed"
        job.error_code = "llm_error"
        db.commit()
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc


def generate_sections(db: Session, tutorial_id: str, ai: AIService) -> dict:
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    profile = get_profile(goal.domain_key)
    criteria_dicts = goals_service.confirmed_criteria(db, goal.id)
    criteria_by_id = {c["id"]: c for c in criteria_dicts}
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_outline", "message": "教程尚无大纲"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    outline = content.get("outline", [])
    if not outline:
        raise HTTPException(status_code=409, detail={"code": "no_outline", "message": "教程尚无大纲"})

    job = GenerationJob(goal_id=goal.id, job_type="tutorial_sections", status="running", progress=5, stage="分节生成")
    db.add(job)
    db.flush()
    try:
        sections = []
        prior_titles: list[str] = []
        for idx, item in enumerate(outline):
            job.progress = min(85, 10 + idx * 12)
            job.stage = f"生成第 {idx + 1}/{len(outline)} 节：{item.get('title', '')}"
            db.flush()
            mapped = [criteria_by_id[cid] for cid in item.get("criteria_ids", []) if cid in criteria_by_id]
            raw = ai.section(goal, profile, item, mapped or criteria_dicts, prior_titles)
            section = {
                "id": uuid.uuid4().hex[:8],
                "title": item.get("title", ""),
                "goal_statement": str(raw.get("goal_statement", "")),
                "prerequisites": [str(x) for x in raw.get("prerequisites", [])],
                "explanation": raw.get("explanation", []),
                "steps": raw.get("steps", []),
                "examples": [str(x) for x in raw.get("examples", [])],
                "exercises": [str(x) for x in raw.get("exercises", [])],
                "variation_task": str(raw.get("variation_task", "")),
                "common_errors": raw.get("common_errors", []),
                "sources": raw.get("sources", []),
                # 以大纲映射为准，保证双向覆盖
                "mapping_criteria": [cid for cid in item.get("criteria_ids", [])],
            }
            sections.append(section)
            prior_titles.append(item.get("title", ""))

        new_content = {"outline": outline, "sections": sections}
        quality = check_structure(new_content, criteria_dicts)

        prev = _current_version(db, tutorial)
        base_version = prev.version if prev else 1
        new_version = TutorialVersion(
            tutorial_id=tutorial.id,
            version=base_version + 1,
            content_json=jdump(new_content),
            prompt_version="v1",
            model_provider="demo" if ai.is_demo else "openai-compatible",
            model_name="demo" if ai.is_demo else "configured",
            quality_report=jdump(quality),
        )
        db.add(new_version)
        db.flush()
        tutorial.current_version_id = new_version.id
        tutorial.status = "drafted" if quality.get("passed") else "drafted_with_issues"

        # 自动生成一个实践任务（来源于最后一节的练习与变式任务）
        last = sections[-1] if sections else {}
        exercises = last.get("exercises", [])
        practice_task = PracticeTask(
            goal_id=goal.id,
            tutorial_id=tutorial.id,
            title=f"实践：完成「{goal.title}」的最小真实任务",
            instructions="\n".join(str(x) for x in exercises) or "按教程完成最小可运行任务。",
            task_type="practice",
            expected_artifact=last.get("variation_task") or "产物 + 你的解释",
            validation_rule="；".join(c["pass_rule"] for c in criteria_dicts if c.get("pass_rule")),
        )
        db.add(practice_task)
        set_status_at_least(goal, "practice")
        job.status = "done"
        job.progress = 100
        job.stage = "完成"
        db.commit()
        return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo}
    except AIServiceError as exc:
        job.status = "failed"
        job.error_code = "llm_error"
        db.commit()
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc


def regenerate_section(db: Session, tutorial_id: str, section_id: str, ai: AIService) -> dict:
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    profile = get_profile(goal.domain_key)
    criteria_dicts = goals_service.confirmed_criteria(db, goal.id)
    criteria_by_id = {c["id"]: c for c in criteria_dicts}
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    outline = content.get("outline", [])
    sections = content.get("sections", [])
    target_idx = next((i for i, s in enumerate(sections) if s.get("id") == section_id), None)
    if target_idx is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "章节不存在"})
    item = outline[target_idx] if target_idx < len(outline) else {"title": sections[target_idx].get("title", ""), "criteria_ids": sections[target_idx].get("mapping_criteria", [])}
    mapped = [criteria_by_id[cid] for cid in item.get("criteria_ids", []) if cid in criteria_by_id]
    try:
        raw = ai.section(goal, profile, item, mapped or criteria_dicts, [o.get("title", "") for o in outline[:target_idx]])
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
    sections[target_idx] = {
        "id": section_id,
        "title": item.get("title", sections[target_idx].get("title", "")),
        "goal_statement": str(raw.get("goal_statement", "")),
        "prerequisites": [str(x) for x in raw.get("prerequisites", [])],
        "explanation": raw.get("explanation", []),
        "steps": raw.get("steps", []),
        "examples": [str(x) for x in raw.get("examples", [])],
        "exercises": [str(x) for x in raw.get("exercises", [])],
        "variation_task": str(raw.get("variation_task", "")),
        "common_errors": raw.get("common_errors", []),
        "sources": raw.get("sources", []),
        "mapping_criteria": list(item.get("criteria_ids", [])),
    }
    new_content = {"outline": outline, "sections": sections}
    quality = check_structure(new_content, criteria_dicts)
    new_version = TutorialVersion(
        tutorial_id=tutorial.id,
        version=version.version + 1,
        content_json=jdump(new_content),
        prompt_version="v1",
        model_provider="demo" if ai.is_demo else "openai-compatible",
        model_name="demo" if ai.is_demo else "configured",
        quality_report=jdump(quality),
    )
    db.add(new_version)
    db.flush()
    tutorial.current_version_id = new_version.id
    db.commit()
    return {"tutorial": tutorial_dict(db, tutorial), "demo": ai.is_demo}


def restore_version(db: Session, tutorial_id: str, version_number: int) -> dict:
    tutorial = _get_tutorial(db, tutorial_id)
    version = (
        db.query(TutorialVersion)
        .filter(TutorialVersion.tutorial_id == tutorial.id, TutorialVersion.version == version_number)
        .first()
    )
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "version_not_found", "message": "版本不存在"})
    tutorial.current_version_id = version.id
    db.commit()
    return tutorial_dict(db, tutorial)
