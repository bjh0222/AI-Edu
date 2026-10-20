"""教程服务：大纲 → 分节生成 → 质量检查 → 版本管理。"""
from __future__ import annotations

import threading
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..learning.disciplines import get_profile
from ..learning.engine import check_structure
from ..llm.service import AIService, AIServiceError
from ..models import GenerationJob, ModelCallLog, PracticeTask, Tutorial, TutorialVersion
from . import goals as goals_service
from . import materials as materials_service
from .utils import (
    add_usage,
    criterion_dict,
    jdump,
    jload,
    set_status_at_least,
    token_usage_dict,
    tutorial_version_dict,
)

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


def tutorial_tokens(db: Session, tutorial: Tutorial) -> dict:
    """教程累计 token：优先按调用日志汇总，旧数据回退到版本字段。"""
    usage = token_usage_dict()
    source = ""
    rows = db.query(ModelCallLog).filter(ModelCallLog.tutorial_id == tutorial.id).all()
    for row in rows:
        add_usage(usage, row.prompt_tokens, row.completion_tokens, row.total_tokens)
        if row.usage_source == "provider":
            source = "provider"
        elif row.usage_source == "estimated" and source != "provider":
            source = "estimated"
    if usage["calls"] == 0:
        versions = db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).all()
        for version in versions:
            add_usage(usage, version.prompt_tokens, version.completion_tokens, version.total_tokens)
            if version.usage_source == "provider":
                source = "provider"
            elif version.usage_source == "estimated" and source != "provider":
                source = "estimated"
    usage["usage_source"] = source
    return usage


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
        "tokens": tutorial_tokens(db, tutorial),
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
    db.commit()  # 先提交，避免在等待模型返回期间持有写锁

    tutorial = Tutorial(goal_id=goal.id, title=f"{goal.title} · 学习教程", status="outline")
    db.add(tutorial)
    db.commit()  # 先落库，让本次调用的 token / 训练样本能关联到 tutorial_id
    ai.tutorial_id = tutorial.id
    materials_text = materials_service.materials_context(db, goal.id)
    try:
        data = ai.outline(
            goal, profile, [{"id": c["id"], "statement": c["statement"]} for c in criteria], materials_text
        )
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
        usage = dict(ai.usage_last)

        version = TutorialVersion(
            tutorial_id=tutorial.id,
            version=1,
            content_json=jdump(content),
            prompt_version="v1",
            model_provider="demo" if ai.is_demo else "openai-compatible",
            model_name="demo" if ai.is_demo else "configured",
            quality_report=jdump({}),
            source_refs=jdump(materials_service.materials_source_refs(db, goal.id)),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            usage_source=usage.get("usage_source", ""),
        )
        db.add(version)
        db.flush()
        tutorial.current_version_id = version.id
        set_status_at_least(goal, "learning")
        job.status = "done"
        job.progress = 100
        job.stage = "大纲完成"
        job.prompt_tokens = usage.get("prompt_tokens", 0)
        job.completion_tokens = usage.get("completion_tokens", 0)
        job.total_tokens = usage.get("total_tokens", 0)
        job.usage_source = usage.get("usage_source", "")
        db.commit()
        return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo}
    except AIServiceError as exc:
        job.status = "failed"
        job.error_code = "llm_error"
        db.commit()
        # 清理本次未产出任何版本的「空壳教程」，避免列表出现空教程
        try:
            has_version = (
                db.query(TutorialVersion).filter(TutorialVersion.tutorial_id == tutorial.id).count() > 0
            )
            if not has_version:
                db.delete(tutorial)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc


def start_sections(db: Session, tutorial_id: str, ai: AIService) -> dict:
    """启动后台章节生成任务并立即返回（前端轮询 /generation-jobs/{id} 获取进度）。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    _criteria_list(db, goal.id)  # 校验：必须先有已确认验收标准
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_outline", "message": "教程尚无大纲"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    if not content.get("outline"):
        raise HTTPException(status_code=409, detail={"code": "no_outline", "message": "教程尚无大纲"})

    job = GenerationJob(goal_id=goal.id, job_type="tutorial_sections", status="queued", progress=0, stage="排队")
    db.add(job)
    db.commit()  # 释放写锁后再启动后台线程

    thread = threading.Thread(target=_sections_worker, args=(tutorial.id, job.id), daemon=True)
    thread.start()
    return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo}


def _update_job(
    db: Session, job_id: str, *, progress: int | None = None, stage: str | None = None, status: str | None = None
) -> None:
    job = db.get(GenerationJob, job_id)
    if job is None:
        return
    if progress is not None:
        job.progress = progress
    if stage is not None:
        job.stage = stage
    if status is not None:
        job.status = status


def _fail_job(db: Session, job_id: str, code: str) -> None:
    try:
        db.rollback()
        job = db.get(GenerationJob, job_id)
        if job:
            job.status = "failed"
            job.error_code = code
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _sections_worker(tutorial_id: str, job_id: str) -> None:
    """后台线程：独立会话逐节生成；每节完成即提交，失败时保留已完成内容。"""
    from ..db import SessionLocal
    from ..models import LearningGoal

    db = SessionLocal()
    try:
        tutorial = db.get(Tutorial, tutorial_id)
        if tutorial is None:
            _fail_job(db, job_id, "tutorial_not_found")
            return
        goal = db.get(LearningGoal, tutorial.goal_id)
        if goal is None:
            _fail_job(db, job_id, "goal_not_found")
            return
        profile = get_profile(goal.domain_key)
        materials_text = materials_service.materials_context(db, goal.id)
        criteria_dicts = goals_service.confirmed_criteria(db, goal.id)
        criteria_by_id = {c["id"]: c for c in criteria_dicts}
        version = db.get(TutorialVersion, tutorial.current_version_id) if tutorial.current_version_id else None
        content = jload(version.content_json, {"outline": [], "sections": []}) if version else {}
        outline = content.get("outline", [])
        if not outline:
            _fail_job(db, job_id, "no_outline")
            return

        # 草稿版本：每完成一节即写入，避免中断丢失已完成章节
        base_version = version.version if version else 0
        draft = TutorialVersion(
            tutorial_id=tutorial.id,
            version=base_version + 1,
            content_json=jdump({"outline": outline, "sections": []}),
            prompt_version="v1",
            model_provider="demo" if not settings.llm_configured else "openai-compatible",
            model_name=settings.llm_model or "demo",
            quality_report=jdump({}),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            usage_source="",
        )
        db.add(draft)
        db.commit()

        sections: list[dict] = list(content.get("sections", []))
        prior_titles = [s.get("title", "") for s in sections]
        ai = AIService(db, goal_id=goal.id, tutorial_id=tutorial.id, job_id=job_id)
        draft_usage_source = ""

        for idx, item in enumerate(outline):
            title = item.get("title", "")
            _update_job(
                db,
                job_id,
                progress=min(85, 5 + idx * 15),
                stage=f"生成第 {idx + 1}/{len(outline)} 节：{title}",
                status="running",
            )
            db.commit()
            mapped = [criteria_by_id[cid] for cid in item.get("criteria_ids", []) if cid in criteria_by_id]
            section_id = uuid.uuid4().hex[:8]
            ai.section_id = section_id
            raw = ai.section(goal, profile, item, mapped or criteria_dicts, prior_titles, materials_text)
            usage = dict(ai.usage_last)
            sections.append(
                {
                    "id": section_id,
                    "title": title,
                    "goal_statement": str(raw.get("goal_statement", "")),
                    "prerequisites": [str(x) for x in raw.get("prerequisites", [])],
                    "explanation": raw.get("explanation", []),
                    "steps": raw.get("steps", []),
                    "examples": [str(x) for x in raw.get("examples", [])],
                    "exercises": [str(x) for x in raw.get("exercises", [])],
                    "variation_task": str(raw.get("variation_task", "")),
                    "common_errors": raw.get("common_errors", []),
                    "sources": raw.get("sources", []),
                    "mapping_criteria": [cid for cid in item.get("criteria_ids", [])],
                    "token_usage": usage,
                }
            )
            prior_titles.append(title)
            # 版本 / 任务级 token 累计（真实 usage 优先，缺失时为估算值）
            draft.prompt_tokens = (draft.prompt_tokens or 0) + int(usage.get("prompt_tokens") or 0)
            draft.completion_tokens = (draft.completion_tokens or 0) + int(usage.get("completion_tokens") or 0)
            draft.total_tokens = (draft.total_tokens or 0) + int(usage.get("total_tokens") or 0)
            if usage.get("usage_source") == "provider":
                draft_usage_source = "provider"
            elif usage.get("usage_source") == "estimated" and draft_usage_source != "provider":
                draft_usage_source = "estimated"
            draft.usage_source = draft_usage_source
            job = db.get(GenerationJob, job_id)
            if job is not None:
                job.prompt_tokens = (job.prompt_tokens or 0) + int(usage.get("prompt_tokens") or 0)
                job.completion_tokens = (job.completion_tokens or 0) + int(usage.get("completion_tokens") or 0)
                job.total_tokens = (job.total_tokens or 0) + int(usage.get("total_tokens") or 0)
                job.usage_source = draft_usage_source
            draft.content_json = jdump({"outline": outline, "sections": sections})
            db.commit()

        _update_job(db, job_id, progress=90, stage="质量检查")
        db.commit()
        new_content = {"outline": outline, "sections": sections}
        quality = check_structure(new_content, criteria_dicts)
        draft.quality_report = jdump(quality)
        draft.content_json = jdump(new_content)
        tutorial.current_version_id = draft.id
        tutorial.status = "drafted" if quality.get("passed") else "drafted_with_issues"
        last = sections[-1] if sections else {}
        exercises = last.get("exercises", [])
        db.add(
            PracticeTask(
                goal_id=goal.id,
                tutorial_id=tutorial.id,
                title=f"实践：完成「{goal.title}」的最小真实任务",
                instructions="\n".join(str(x) for x in exercises) or "按教程完成最小可运行任务。",
                task_type="practice",
                expected_artifact=last.get("variation_task") or "产物 + 你的解释",
                validation_rule="；".join(c["pass_rule"] for c in criteria_dicts if c.get("pass_rule")),
            )
        )
        set_status_at_least(goal, "practice")
        _update_job(db, job_id, status="done", progress=100, stage="完成")
        db.commit()
    except AIServiceError:
        _fail_job(db, job_id, "llm_error")
    except Exception:  # noqa: BLE001
        _fail_job(db, job_id, "internal_error")
    finally:
        db.close()


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
    ai.tutorial_id = tutorial.id
    ai.section_id = section_id
    materials_text = materials_service.materials_context(db, goal.id)
    try:
        raw = ai.section(
            goal, profile, item, mapped or criteria_dicts, [o.get("title", "") for o in outline[:target_idx]], materials_text
        )
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail={"code": "llm_error", "message": str(exc)}) from exc
    usage = dict(ai.usage_last)
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
        "token_usage": usage,
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
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        usage_source=usage.get("usage_source", ""),
    )
    db.add(new_version)
    db.flush()
    tutorial.current_version_id = new_version.id
    db.commit()
    return {"tutorial": tutorial_dict(db, tutorial), "demo": ai.is_demo}


def get_section(db: Session, tutorial_id: str, section_id: str) -> dict:
    """章节详情：单节内容 + 所属教程 / 目标 + 前后导航。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    sections = content.get("sections", [])
    index = next((i for i, s in enumerate(sections) if s.get("id") == section_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "章节不存在"})
    section = sections[index]
    return {
        **section,
        "id": section.get("id", section_id),
        "token_usage": section.get("token_usage") or token_usage_dict(),
        "goal_id": goal.id,
        "goal_title": goal.title,
        "tutorial_id": tutorial.id,
        "tutorial_title": tutorial.title,
        "index": index,
        "total": len(sections),
        "version": version.version,
        "prev_section_id": sections[index - 1].get("id") if index > 0 else None,
        "next_section_id": sections[index + 1].get("id") if index + 1 < len(sections) else None,
    }


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


def _safe_filename(name: str) -> str:
    import re

    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', " ", name).strip()
    return cleaned or "tutorial"


def export_markdown(db: Session, tutorial_id: str) -> tuple[str, str]:
    """把当前教程版本导出为 Markdown，返回 (文件名, 内容)。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    quality = jload(version.quality_report, {})
    profile = get_profile(goal.domain_key)
    criteria = goals_service.list_criteria(db, goal.id)
    crit_by_id = {c["id"]: c for c in criteria}

    lines: list[str] = []
    lines.append(f"# {tutorial.title}")
    lines.append("")
    lines.append(f"- 学习目标：{goal.title}")
    lines.append(f"- 学科：{profile.display_name}")
    if goal.application_context:
        lines.append(f"- 应用场景：{goal.application_context}")
    if goal.current_level:
        lines.append(f"- 当前基础：{goal.current_level}")
    lines.append(f"- 生成时间：{version.created_at or ''}")
    lines.append(f"- 模型：{version.model_provider} / {version.model_name}")
    quality_text = "通过" if quality.get("passed") else "待改进"
    lines.append(f"- 版本：v{version.version} ｜ 质量检查：{quality_text}")
    usage = tutorial_tokens(db, tutorial)
    if usage["total_tokens"]:
        usage_label = "实测" if usage["usage_source"] == "provider" else "估算"
        lines.append(f"- Token 消耗：{usage['total_tokens']}（{usage_label}）")
    lines.append("")

    lines.append("## 验收标准")
    lines.append("")
    if criteria:
        for idx, c in enumerate(criteria, 1):
            lines.append(f"{idx}. [ ] {c['statement']}")
            if c.get("conditions"):
                lines.append(f"   - 条件：{c['conditions']}")
            if c.get("pass_rule"):
                lines.append(f"   - 通过条件：{c['pass_rule']}")
    else:
        lines.append("（无验收标准）")
    lines.append("")

    outline = content.get("outline", [])
    sections = content.get("sections", [])
    if outline:
        lines.append("## 目录")
        lines.append("")
        for idx, o in enumerate(outline, 1):
            lines.append(f"{idx}. {o.get('title', '')}")
        lines.append("")

    for idx, s in enumerate(sections, 1):
        lines.append(f"## 第 {idx} 节：{s.get('title', '')}")
        lines.append("")
        if s.get("goal_statement"):
            lines.append(f"> {s['goal_statement']}")
            lines.append("")
        if s.get("prerequisites"):
            lines.append("**前置要求**")
            lines.append("")
            for p in s["prerequisites"]:
                lines.append(f"- {p}")
            lines.append("")
        for block in s.get("explanation", []):
            lines.append(f"### {block.get('heading', '')}")
            lines.append("")
            lines.append(str(block.get("body", "")))
            lines.append("")
        steps = s.get("steps", [])
        if steps:
            lines.append("### 操作步骤")
            lines.append("")
            for si, st in enumerate(steps, 1):
                lines.append(f"{si}. {st.get('text', '')}")
                if st.get("expected_result"):
                    lines.append(f"   - 预期结果：{st['expected_result']}")
                if st.get("verification"):
                    lines.append(f"   - 验证方式：{st['verification']}")
            lines.append("")
        if s.get("examples"):
            lines.append("### 示例")
            lines.append("")
            for e in s["examples"]:
                lines.append(f"- {e}")
            lines.append("")
        if s.get("exercises"):
            lines.append("### 练习")
            lines.append("")
            for e in s["exercises"]:
                lines.append(f"- [ ] {e}")
            lines.append("")
        if s.get("variation_task"):
            lines.append("### 变式任务（检查迁移）")
            lines.append("")
            lines.append(f"- {s['variation_task']}")
            lines.append("")
        if s.get("common_errors"):
            lines.append("### 常见错误")
            lines.append("")
            for e in s["common_errors"]:
                lines.append(f"- **{e.get('error', '')}** — 原因：{e.get('cause', '')}；排查：{e.get('diagnose', '')}")
            lines.append("")
        mapped = s.get("mapping_criteria", [])
        if mapped:
            lines.append("### 对应验收标准")
            lines.append("")
            for cid in mapped:
                stmt = crit_by_id.get(cid, {}).get("statement", cid)
                lines.append(f"- {stmt}")
            lines.append("")
        sources = s.get("sources", [])
        if sources:
            lines.append("### 来源与可信度")
            lines.append("")
            for src in sources:
                url = f"（{src['url']}）" if src.get("url") else ""
                note = f" — {src['note']}" if src.get("note") else ""
                lines.append(f"- {src.get('title', '')}{url}{note}")
            lines.append("")

    checks = quality.get("checks", [])
    if checks:
        lines.append("## 质量报告")
        lines.append("")
        for c in checks:
            mark = "✅" if c.get("passed") else "❌"
            lines.append(f"- {mark} {c.get('name', '')}：{c.get('detail', '')}")
        lines.append("")
    if quality.get("issues"):
        lines.append("### 待改进项")
        lines.append("")
        for issue in quality["issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> 由 AI Edu 生成。教程内容需结合实践核验；证据比感觉更可靠。")
    lines.append("")

    filename = f"{_safe_filename(goal.title)}-教程-v{version.version}.md"
    return filename, "\n".join(lines)
