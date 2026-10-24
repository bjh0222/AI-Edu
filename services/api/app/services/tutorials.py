"""教程服务：大纲 → 分节生成 → 质量检查 → 版本管理。"""
from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..model_settings import runtime_settings
from ..learning.disciplines import get_profile
from ..learning.engine import check_structure
from ..learning.generation_tiers import normalize_tier
from ..learning.levels import normalize_level
from ..learning.teaching_profile import normalize_teaching_plan
from ..llm.service import AIService, AIServiceError
from ..models import GenerationJob, ModelCallLog, Tutorial, TutorialVersion
from . import goals as goals_service
from . import knowledge as knowledge_service
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

MAX_SECTIONS_HINT = 8  # 安全上限：防止异常输出撑爆成本；正常章节数由目标范围决定
# 章节并发生成上限：3 路是「模型限流 / SQLite 写锁 / 墙钟收益」的折中（8 节串行约 8 次往返）
MAX_SECTION_WORKERS = 3

VALID_CONTENT_TYPES = {"concept", "method", "tool", "fact", "application", "mixed"}


def _normalize_content_type(value) -> str:
    """模型返回的非法教学类型归一化为 mixed（不因非法枚举判定生成失败）。"""
    text = str(value or "").strip().lower()
    return text if text in VALID_CONTENT_TYPES else "mixed"


def _normalize_outline_items(raw_sections: list) -> list[dict]:
    """大纲条目归一化：补 purpose / content_type，非法枚举回退 mixed；非对象条目跳过。"""
    items = []
    for raw in raw_sections:
        if not isinstance(raw, dict):
            continue
        items.append({
            "id": uuid.uuid4().hex[:8],
            "title": str(raw.get("title", "未命名章节"))[:120],
            "purpose": str(raw.get("purpose", "") or raw.get("summary", "")),
            "content_type": _normalize_content_type(raw.get("content_type")),
            "summary": str(raw.get("summary", "")),
            "criteria_ids": _as_str_list(raw.get("criteria_ids")),
        })
    return items


def _as_str_list(value) -> list[str]:
    """把模型输出安全转成字符串列表：非列表（如字符串）整体丢弃，不按字符展开。"""
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _normalize_section_raw(raw: dict) -> dict:
    """章节输出归一化：非法内容块类型回退 text；空 body 块丢弃；缺失可选字段置空。"""
    raw_blocks = raw.get("content")
    content_blocks = []
    for block in raw_blocks if isinstance(raw_blocks, list) else []:
        if not isinstance(block, dict):
            continue
        body = str(block.get("body", "") or "").strip()
        if not body:
            continue
        btype = str(block.get("type", "text") or "text").strip().lower()
        if btype not in {
            "text", "key_point", "formula", "steps", "table", "example",
            "comparison", "method_summary", "diagram", "memory", "note",
        }:
            btype = "text"
        content_blocks.append({"type": btype, "title": str(block.get("title", "") or ""), "body": body})
    raw_errors = raw.get("common_errors")
    common_errors = []
    for e in raw_errors if isinstance(raw_errors, list) else []:
        if not isinstance(e, dict):
            continue
        error = str(e.get("error", "") or "").strip()
        if not error:
            continue
        common_errors.append({
            "error": error,
            "cause": str(e.get("cause", "") or ""),
            "diagnose": str(e.get("diagnose", "") or ""),
        })
    raw_sources = raw.get("sources")
    sources = []
    for s in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "") or "").strip()
        if not title:
            continue
        sources.append({
            "title": title,
            "url": str(s.get("url", "") or ""),
            "note": str(s.get("note", "") or ""),
        })
    return {
        "title": str(raw.get("title", "") or "")[:120],
        "purpose": str(raw.get("purpose", "") or ""),
        "content_type": _normalize_content_type(raw.get("content_type")),
        "content": content_blocks,
        "key_takeaways": _as_str_list(raw.get("key_takeaways")),
        "common_errors": common_errors,
        "prerequisite_refs": _as_str_list(raw.get("prerequisite_refs")),
        "exercises": _as_str_list(raw.get("exercises")),
        "sources": sources,
        "mapping_criteria": [str(x) for x in raw.get("mapping_criteria", [])] if isinstance(raw.get("mapping_criteria"), list) else [],
    }


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
        "delivery_status": getattr(tutorial, "delivery_status", "") or "",
        "delivery_path": getattr(tutorial, "delivery_path", "") or "",
        "delivery_version": int(getattr(tutorial, "delivery_version", 0) or 0),
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
        raw_sections = data.get("sections")
        if not isinstance(raw_sections, list):
            raise AIServiceError("模型输出的章节大纲不是列表，请重试")
        outline = _normalize_outline_items(raw_sections[:MAX_SECTIONS_HINT])
        if not outline:
            raise AIServiceError("模型输出缺少有效章节大纲，请重试")
        teaching_plan = normalize_teaching_plan(data.get("teaching_plan"))
        content = {"teaching_plan": teaching_plan, "outline": outline, "sections": []}
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
        # 教程生成即更新知识网络：大纲阶段先写入概念级结构（失败不阻断教程）
        _update_job(db, job_id=job.id, progress=92, stage="更新知识网络")
        db.commit()
        try:
            knowledge_service.extract_from_tutorial(db, goal, tutorial, version, ai)
        except Exception as exc:  # noqa: BLE001  知识提取失败只记录，不影响教程交付
            job = db.get(GenerationJob, job.id)
            if job is not None:
                job.stage = f"大纲完成（知识网络更新失败：{str(exc)[:80]}）"
        job = db.get(GenerationJob, job.id)
        if job is not None:
            job.status = "done"
            job.progress = 100
            job.stage = "大纲完成，知识网络已更新"
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


def _companions_missing(content: dict, goal) -> dict:
    """配套文件缺口：知识速查总是需要；额外练习只在目标开启时需要。"""
    return {
        "cheatsheet": not content.get("cheatsheet"),
        "extra_exercises": bool(goal.generate_extra_exercises) and not content.get("extra_exercises"),
    }


def companions_missing(db: Session, tutorial_id: str) -> dict:
    """只读检查（不调模型）：供「一键生成」判断要不要提交后台配套任务。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    content = jload(version.content_json, {}) if version is not None else {}
    if not (content.get("sections") or []):
        return {"cheatsheet": False, "extra_exercises": False}
    return _companions_missing(content, goal)


_COMPANION_LABELS = {"cheatsheet": "知识速查", "extra_exercises": "额外练习"}


def _companion_task(
    kind: str,
    *,
    tutorial_id: str,
    goal_id: str,
    job_id: str,
    outline: list,
    materials_text: str,
) -> tuple[str, dict, dict]:
    """单个配套文件的生成任务：独立 Session + 独立 AIService（并发安全）。"""
    from ..db import SessionLocal

    from ..models import LearningGoal

    db = SessionLocal()
    try:
        goal = db.get(LearningGoal, goal_id)
        if goal is None:
            raise AIServiceError("学习目标不存在")
        profile = get_profile(goal.domain_key)
        ai = AIService(db, goal_id=goal_id, tutorial_id=tutorial_id, job_id=job_id)
        if kind == "cheatsheet":
            payload = ai.cheatsheet(goal, profile, outline, materials_text)
        else:
            payload = ai.extra_exercises(goal, profile, outline, materials_text)
        usage = dict(ai.usage_last)
        db.commit()  # 短事务：调用日志 / 训练样本尽快落库并释放写锁
        return kind, payload, usage
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _generate_companions(
    *,
    tutorial_id: str,
    goal_id: str,
    goal_title: str,
    job_id: str,
    outline: list,
    materials_text: str,
    want_cheatsheet: bool,
    want_extra: bool,
) -> dict:
    """知识速查与额外练习互不依赖 → 并行生成；单个失败只留痕，不拖垮另一个。"""
    wanted = [kind for kind, flag in (("cheatsheet", want_cheatsheet), ("extra_exercises", want_extra)) if flag]
    result: dict = {
        "cheatsheet": None,
        "extra_exercises": None,
        "usage": token_usage_dict(),
        "errors": [],
    }
    if not wanted:
        return result

    payloads: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(wanted), thread_name_prefix="companion") as pool:
        futures = {
            pool.submit(
                _companion_task,
                kind,
                tutorial_id=tutorial_id,
                goal_id=goal_id,
                job_id=job_id,
                outline=outline,
                materials_text=materials_text,
            ): kind
            for kind in wanted
        }
        for future in as_completed(futures):
            kind = futures[future]
            try:
                _, payload, usage = future.result()
            except Exception as exc:  # noqa: BLE001  单文件失败不影响另一个
                result["errors"].append(f"{_COMPANION_LABELS[kind]}生成失败：{str(exc)[:80]}")
                continue
            payloads[kind] = payload
            add_usage(
                result["usage"],
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
            if usage.get("usage_source") == "provider":
                result["usage"]["usage_source"] = "provider"
            elif usage.get("usage_source") == "estimated" and result["usage"]["usage_source"] != "provider":
                result["usage"]["usage_source"] = "estimated"

    if "cheatsheet" in payloads:
        result["cheatsheet"] = {
            "filename": f"{_safe_filename(goal_title)}-知识速查",
            **payloads["cheatsheet"],
        }
    if "extra_exercises" in payloads:
        result["extra_exercises"] = {
            "filename": f"{_safe_filename(goal_title)}-额外练习",
            **payloads["extra_exercises"],
        }
    return result


def ensure_companions(db: Session, tutorial_id: str, ai: AIService, *, strict: bool = True) -> dict:
    """为已有章节的教程补齐配套文件：知识速查（总是）+ 独立额外练习（用户开启时）。

    用于「先有教程、后开启选项」或旧版本缺配套的场景；不重复生成已存在的文件。
    生成成功会落一个新版本（内容 = 原内容 + 配套文件）。
    strict=True 时任一文件失败抛 AIServiceError（同步调用方）；strict=False 只回传 errors。
    """
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    sections = content.get("sections") or []
    if not sections:
        return {
            "changed": False,
            "cheatsheet": False,
            "extra_exercises": False,
            "errors": [],
            "tutorial": tutorial_dict(db, tutorial),
        }

    outline = content.get("outline", [])
    missing = _companions_missing(content, goal)
    if not any(missing.values()):
        return {
            "changed": False,
            "cheatsheet": False,
            "extra_exercises": False,
            "errors": [],
            "tutorial": tutorial_dict(db, tutorial),
        }

    materials_text = materials_service.materials_context(db, goal.id)
    ai.tutorial_id = tutorial.id
    result = _generate_companions(
        tutorial_id=tutorial.id,
        goal_id=goal.id,
        goal_title=goal.title,
        job_id=ai.job_id or "",
        outline=outline,
        materials_text=materials_text,
        want_cheatsheet=missing["cheatsheet"],
        want_extra=missing["extra_exercises"],
    )
    if strict and result["errors"]:
        raise AIServiceError("；".join(result["errors"]))

    changed = {
        "cheatsheet": result["cheatsheet"] is not None,
        "extra_exercises": result["extra_exercises"] is not None,
    }
    if not any(changed.values()):
        return {
            "changed": False,
            "cheatsheet": False,
            "extra_exercises": False,
            "errors": result["errors"],
            "tutorial": tutorial_dict(db, tutorial),
        }
    if result["cheatsheet"] is not None:
        content["cheatsheet"] = result["cheatsheet"]
    if result["extra_exercises"] is not None:
        content["extra_exercises"] = result["extra_exercises"]

    usage = result["usage"]
    new_version = TutorialVersion(
        tutorial_id=tutorial.id,
        version=version.version + 1,
        content_json=jdump(content),
        prompt_version="v1",
        model_provider="demo" if ai.is_demo else "openai-compatible",
        model_name="demo" if ai.is_demo else "configured",
        quality_report=version.quality_report,
        source_refs=version.source_refs,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"],
        usage_source=usage.get("usage_source", "") or ("estimated" if usage["total_tokens"] else ""),
    )
    db.add(new_version)
    db.flush()
    tutorial.current_version_id = new_version.id
    db.commit()
    return {
        "changed": True,
        "cheatsheet": changed["cheatsheet"],
        "extra_exercises": changed["extra_exercises"],
        "errors": result["errors"],
        "tutorial": tutorial_dict(db, tutorial),
    }


def start_companions(db: Session, tutorial_id: str, ai: AIService) -> dict:
    """后台补齐配套文件并立即返回 job（前端轮询 /generation-jobs/{id}）。

    「一键生成」在章节已存在时补齐配套文件，此前同步调用会让请求卡 1-2 分钟；
    这里改成与章节生成同构的后台任务，接口响应结构不变（仍返回 job_id）。
    """
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    if not (content.get("sections") or []):
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无章节内容"})

    active = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.goal_id == goal.id,
            GenerationJob.job_type == "tutorial_companions",
            GenerationJob.status.in_(("queued", "running")),
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    if active is not None:
        # 幂等：已有后台任务在跑就复用，避免连点产生重复生成与重复计费
        return {"tutorial": tutorial_dict(db, tutorial), "job": active, "demo": ai.is_demo, "reused": True}

    job = GenerationJob(
        goal_id=goal.id, job_type="tutorial_companions", status="queued", progress=0, stage="排队"
    )
    db.add(job)
    db.commit()  # 释放写锁后再启动后台线程

    thread = threading.Thread(target=_companions_worker, args=(tutorial.id, job.id), daemon=True)
    thread.start()
    return {"tutorial": tutorial_dict(db, tutorial), "job": job, "demo": ai.is_demo, "reused": False}


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


def _fail_job(db: Session, job_id: str, code: str, message: str = "") -> None:
    try:
        db.rollback()
        job = db.get(GenerationJob, job_id)
        if job:
            job.status = "failed"
            job.error_code = code
            job.error_message = (message or "")[:2000]
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


SECTION_RETRY_DELAYS = (3, 8)


def _section_with_retry(
    db: Session,
    job_id: str,
    ai: AIService,
    goal,
    profile,
    item: dict,
    criteria: list[dict],
    prior_titles: list[str],
    materials_text: str,
    companion_names: list[str] | None = None,
) -> dict:
    """单节生成带重试。

    模型偶发超时 / 限流 / 输出被截断时自动重试，避免「一键生成」在最后一节整体失败。
    每次重试前把原因写进 job.stage 与 job.retry_count，失败后仍可从 error_message 看到根因。
    """
    attempts = len(SECTION_RETRY_DELAYS) + 1
    for attempt in range(1, attempts + 1):
        try:
            return ai.section(
                goal, profile, item, criteria, prior_titles, materials_text, companion_names
            )
        except AIServiceError as exc:
            if attempt >= attempts:
                raise
            job = db.get(GenerationJob, job_id)
            if job is not None:
                job.retry_count = (job.retry_count or 0) + 1
                job.stage = f"第 {attempt} 次重试（{str(exc)[:60]}）"
            db.commit()
            time.sleep(SECTION_RETRY_DELAYS[attempt - 1])
    raise AIServiceError("章节生成重试次数已用完")


def _merge_section_usage(results: dict[int, dict]) -> dict:
    """按大纲顺序汇总各节 usage（真实 provider usage 优先于估算）。"""
    usage = token_usage_dict()
    source = ""
    for idx in sorted(results):
        last = results[idx]["usage"]
        add_usage(
            usage,
            last.get("prompt_tokens"),
            last.get("completion_tokens"),
            last.get("total_tokens"),
        )
        if last.get("usage_source") == "provider":
            source = "provider"
        elif last.get("usage_source") == "estimated" and source != "provider":
            source = "estimated"
    usage["usage_source"] = source
    return usage


def _generate_section_task(
    *,
    tutorial_id: str,
    goal_id: str,
    job_id: str,
    index: int,
    item: dict,
    criteria_dicts: list[dict],
    prior_titles: list[str],
    materials_text: str,
) -> dict:
    """并发生成的单节任务：独立 Session + 独立 AIService。

    SQLite 只允许单写者：每次调用只在「读上下文 → 写日志」这两处开短事务，
    等模型返回的整段时间不持有写锁。
    """
    from ..db import SessionLocal
    from ..models import LearningGoal

    db = SessionLocal()
    try:
        goal = db.get(LearningGoal, goal_id)
        if goal is None:
            raise AIServiceError("学习目标不存在")
        profile = get_profile(goal.domain_key)
        ai = AIService(db, goal_id=goal_id, tutorial_id=tutorial_id, job_id=job_id)
        section_id = uuid.uuid4().hex[:8]
        ai.section_id = section_id
        criteria_by_id = {c["id"]: c for c in criteria_dicts}
        mapped = [criteria_by_id[cid] for cid in item.get("criteria_ids", []) if cid in criteria_by_id]
        # 配套文件名在生成章节时已确定（见 _generate_companions），提前注入，避免模型猜错双链目标
        companion_names = [f"{_safe_filename(goal.title)}-知识速查"]
        if bool(getattr(goal, "generate_extra_exercises", False)):
            companion_names.append(f"{_safe_filename(goal.title)}-额外练习")
        raw = _section_with_retry(
            db, job_id, ai, goal, profile, item, mapped or criteria_dicts, prior_titles,
            materials_text, companion_names,
        )
        usage = dict(ai.usage_last)
        db.commit()  # 短事务：调用日志 / 训练样本立即落库，尽快释放写锁
        section_data = _normalize_section_raw(raw)
        section_data["title"] = section_data["title"] or item.get("title", "")
        section_data.update(
            {
                "id": section_id,
                "mapping_criteria": list(item.get("criteria_ids", [])),
                "token_usage": usage,
            }
        )
        return {"index": index, "section": section_data, "usage": usage}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _sections_worker(tutorial_id: str, job_id: str) -> None:
    """后台线程：最多 3 路并发生成章节，结果按大纲顺序合并。

    每节使用独立 Session / AIService（互不共享 ORM 与 usage_last），完成一节即按大纲
    顺序提交草稿；任一节最终失败仍使整个 job 失败，但已完成内容已落库不丢。
    """
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
        materials_text = materials_service.materials_context(db, goal.id)
        criteria_dicts = goals_service.confirmed_criteria(db, goal.id)
        version = db.get(TutorialVersion, tutorial.current_version_id) if tutorial.current_version_id else None
        content = jload(version.content_json, {"outline": [], "sections": []}) if version else {}
        outline = content.get("outline", [])
        teaching_plan = content.get("teaching_plan") or normalize_teaching_plan({})
        if not outline:
            _fail_job(db, job_id, "no_outline")
            return

        model_snapshot = runtime_settings()
        # 草稿版本：每完成一节即写入，避免中断丢失已完成章节
        base_version = version.version if version else 0
        draft = TutorialVersion(
            tutorial_id=tutorial.id,
            version=base_version + 1,
            content_json=jdump({"teaching_plan": teaching_plan, "outline": outline, "sections": []}),
            prompt_version="v1",
            model_provider="demo" if not model_snapshot.llm_configured else "openai-compatible",
            model_name=model_snapshot.llm_model or "demo",
            quality_report=jdump({}),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            usage_source="",
        )
        db.add(draft)
        db.commit()

        outline_titles = [str(o.get("title", "")) for o in outline]
        total = len(outline)
        results: dict[int, dict] = {}
        failures: list[tuple[int, Exception]] = []
        _update_job(
            db,
            job_id,
            progress=5,
            stage=f"并发生成 {total} 节（最多 {MAX_SECTION_WORKERS} 路）",
            status="running",
        )
        db.commit()

        done = 0
        with ThreadPoolExecutor(
            max_workers=min(MAX_SECTION_WORKERS, total), thread_name_prefix="section"
        ) as pool:
            futures = {
                pool.submit(
                    _generate_section_task,
                    tutorial_id=tutorial.id,
                    goal_id=goal.id,
                    job_id=job_id,
                    index=idx,
                    item={**item, "_teaching_plan": teaching_plan},
                    criteria_dicts=criteria_dicts,
                    # 并发下「前置章节标题」取大纲静态切片，避免依赖完成顺序
                    prior_titles=outline_titles[:idx],
                    materials_text=materials_text,
                ): idx
                for idx, item in enumerate(outline)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:  # noqa: BLE001  先收齐其余节再统一判定失败
                    failures.append((idx, exc))
                done += 1
                # 每完成一节：按大纲顺序合并 + 短事务提交（中断也不丢已完成内容）
                sections = [results[i]["section"] for i in sorted(results)]
                usage = _merge_section_usage(results)
                draft.prompt_tokens = usage["prompt_tokens"]
                draft.completion_tokens = usage["completion_tokens"]
                draft.total_tokens = usage["total_tokens"]
                draft.usage_source = usage["usage_source"]
                draft.content_json = jdump({"outline": outline, "sections": sections})
                job = db.get(GenerationJob, job_id)
                if job is not None:
                    job.progress = min(85, 5 + int(80 * done / total))
                    job.prompt_tokens = usage["prompt_tokens"]
                    job.completion_tokens = usage["completion_tokens"]
                    job.total_tokens = usage["total_tokens"]
                    job.usage_source = usage["usage_source"]
                    if results:
                        last_title = results[max(results)]["section"].get("title", "")
                        job.stage = f"已完成 {len(results)}/{total} 节：{last_title}"[:200]
                db.commit()

        if failures:
            db.commit()  # 保住已完成草稿，再判定整体失败
            idx, exc = failures[0]
            message = (
                f"第 {idx + 1}/{total} 节生成失败（已完成 {len(results)}/{total} 节，"
                f"已完成内容已保留）：{str(exc)[:160]}"
            )
            if isinstance(exc, AIServiceError):
                raise AIServiceError(message)
            raise RuntimeError(message)

        _update_job(db, job_id, progress=90, stage="质量检查")
        db.commit()
        sections = [results[i]["section"] for i in sorted(results)]
        new_content = {"teaching_plan": teaching_plan, "outline": outline, "sections": sections}
        quality = check_structure(new_content, criteria_dicts)
        draft.quality_report = jdump(quality)
        tutorial.status = "drafted" if quality.get("passed") else "drafted_with_issues"

        # 配套文件：知识速查与额外练习互不依赖 → 并行生成；失败只留痕，不阻断正文交付
        _update_job(db, job_id, progress=92, stage="并行生成配套文件（知识速查 / 额外练习）")
        db.commit()
        companions = _generate_companions(
            tutorial_id=tutorial.id,
            goal_id=goal.id,
            goal_title=goal.title,
            job_id=job_id,
            outline=outline,
            materials_text=materials_text,
            want_cheatsheet=True,
            want_extra=bool(goal.generate_extra_exercises),
        )
        new_content["cheatsheet"] = companions["cheatsheet"]
        if bool(goal.generate_extra_exercises):
            new_content["extra_exercises"] = companions["extra_exercises"]
        if companions["errors"]:
            _update_job(db, job_id, stage="；".join(companions["errors"])[:200])
            db.commit()
        draft.content_json = jdump(new_content)
        tutorial.current_version_id = draft.id

        # 实践任务与「实践」环节已移除：教程内的必要练习即练习载体
        # （配套文件已在上面写入 new_content）
        # 全部章节完成：提取概念与关系写入知识网络（失败不阻断教程交付，job.stage 留痕）
        _update_job(db, job_id, progress=94, stage="更新知识网络")
        db.commit()
        extraction_error = ""
        # 提取阶段已退出线程池，回到单线程：用一个绑定主会话的 AIService 记账即可
        ai = AIService(db, goal_id=goal.id, tutorial_id=tutorial.id, job_id=job_id)
        try:
            knowledge_service.extract_from_tutorial(db, goal, tutorial, draft, ai)
        except Exception as exc:  # noqa: BLE001
            extraction_error = f"{exc.__class__.__name__}: {str(exc)[:120]}"
        _update_job(
            db,
            job_id,
            status="done",
            progress=100,
            stage="完成，知识网络已更新" if not extraction_error else f"完成（知识网络更新失败：{extraction_error[:80]}）",
        )
        db.commit()
    except AIServiceError as exc:
        _fail_job(db, job_id, "llm_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail_job(db, job_id, "internal_error", f"{exc.__class__.__name__}: {exc}")
    finally:
        db.close()


def _companions_worker(tutorial_id: str, job_id: str) -> None:
    """后台线程：为已有章节的教程补齐配套文件（独立会话，失败只影响本 job）。"""
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
        _update_job(db, job_id, status="running", progress=15, stage="生成配套文件（知识速查 / 额外练习）")
        db.commit()
        ai = AIService(db, goal_id=goal.id, tutorial_id=tutorial.id, job_id=job_id)
        result = ensure_companions(db, tutorial.id, ai, strict=False)
        errors = result.get("errors") or []
        if not result.get("changed") and errors:
            _fail_job(db, job_id, "llm_error", "；".join(errors))
            return
        _update_job(
            db,
            job_id,
            status="done",
            progress=100,
            stage="配套文件已生成" if not errors else f"配套文件已生成（部分失败：{errors[0][:80]}）",
        )
        db.commit()
    except AIServiceError as exc:
        _fail_job(db, job_id, "llm_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail_job(db, job_id, "internal_error", f"{exc.__class__.__name__}: {exc}")
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
    item = {**item, "_teaching_plan": content.get("teaching_plan") or normalize_teaching_plan({})}
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
    section_data = _normalize_section_raw(raw)
    section_data.update(
        {
            "id": section_id,
            "title": section_data["title"] or item.get("title", sections[target_idx].get("title", "")),
            "mapping_criteria": list(item.get("criteria_ids", [])),
            "token_usage": usage,
        }
    )
    sections[target_idx] = section_data
    new_content = {**content, "outline": outline, "sections": sections}
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
    # 含 Obsidian 不允许/易冲突的字符（# ^ [ ] |）一并清理，保证双链文件名可用
    cleaned = re.sub(r'[\\/:*?"<>|#^\[\]\r\n]+', " ", name).strip()
    return cleaned or "tutorial"


# 双链与标签的导出归一化：模型可能写出 [[...]]、[[笔记名]] 这类占位链接，
# 也可能在正文里写 #标签。交付到 Vault 前统一处理：
# - 指向本次配套文件的 [[文件名]] 原样保留（这些文件由插件同时写入）；
# - 其余 [[...]] 与行内 #标签 包进行内代码，既保留原文又不会生成断链/真标签；
# - 围栏代码块与已有行内代码不处理，避免破坏命令、代码和语法示例。
WIKILINK_RE = re.compile(r"!?\[\[[^\[\]\n]{0,200}\]\]")
INLINE_TAG_RE = re.compile(r"(?<![\w#])#([A-Za-z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)")


def _wikilink_target(token: str) -> str:
    inner = token[3:-2] if token.startswith("![[") else token[2:-2]
    return inner.split("|", 1)[0].split("#", 1)[0].strip()


def normalize_obsidian_syntax(markdown: str, allowed_links: set[str]) -> str:
    """把不该生效的双链 / 标签降级为行内代码，保证导出文件只有指向真实文件的链接。"""
    allowed = {name.strip().removesuffix(".md") for name in allowed_links if name}
    lines: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            lines.append(line)
            continue
        if fence is not None:
            lines.append(line)
            continue

        def fix_links(part: str) -> str:
            def repl(match: re.Match) -> str:
                target = _wikilink_target(match.group(0))
                if not target or target in allowed:
                    return match.group(0)
                return f"`{match.group(0)}`"

            return WIKILINK_RE.sub(repl, part)

        def fix_tags(part: str) -> str:
            if stripped.startswith("#"):
                return part  # 标题行
            return INLINE_TAG_RE.sub(lambda m: f"`{m.group(0)}`", part)

        pieces = re.split(r"(`[^`\n]*`)", line)
        for idx, piece in enumerate(pieces):
            if idx % 2 == 1:
                continue
            pieces[idx] = fix_links(fix_tags(piece))
        lines.append("".join(pieces))
    return "\n".join(lines)


# 内容块类型的默认标题（模型未给 title 时使用）
_BLOCK_HEADINGS = {
    "text": "讲解",
    "key_point": "关键结论",
    "formula": "公式与推导",
    "steps": "操作步骤",
    "table": "表格",
    "example": "示例",
    "comparison": "对比分析",
    "method_summary": "方法归纳",
    "diagram": "概念关系图",
    "memory": "记忆材料",
    "note": "注意事项",
}

_LEVEL_LABELS = {"L1": "基础理解", "L2": "独立应用", "L3": "深入掌握与迁移"}


def _render_block(block: dict, lines: list[str]) -> None:
    btype = str(block.get("type", "text") or "text")
    title = str(block.get("title", "") or "").strip()
    heading = title or _BLOCK_HEADINGS.get(btype, "讲解")
    body = str(block.get("body", "") or "").strip()
    if btype == "key_point":
        lines.append(f"### {heading}")
        lines.append("")
        lines.append(f"> {body}")
        lines.append("")
        return
    if btype == "note":
        lines.append(f"### {heading}")
        lines.append("")
        lines.append(f"> ⚠️ {body}")
        lines.append("")
        return
    lines.append(f"### {heading}")
    lines.append("")
    lines.append(body)
    lines.append("")


def _render_section_v2(s: dict, crit_by_id: dict, lines: list[str]) -> None:
    if s.get("purpose"):
        lines.append(f"> {s['purpose']}")
        lines.append("")
    for block in s.get("content", []):
        if isinstance(block, dict):
            _render_block(block, lines)
    if s.get("key_takeaways"):
        lines.append("### 核心结论")
        lines.append("")
        for item in s["key_takeaways"]:
            lines.append(f"- {item}")
        lines.append("")
    if s.get("common_errors"):
        lines.append("### 常见错误")
        lines.append("")
        for e in s["common_errors"]:
            lines.append(f"- **{e.get('error', '')}** — 原因：{e.get('cause', '')}；排查：{e.get('diagnose', '')}")
        lines.append("")
    if s.get("prerequisite_refs"):
        lines.append("### 前置知识")
        lines.append("")
        for p in s["prerequisite_refs"]:
            lines.append(f"- {p}")
        lines.append("")
    if s.get("exercises"):
        lines.append("### 必要练习")
        lines.append("")
        for e in s["exercises"]:
            lines.append(f"- [ ] {e}")
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
        lines.append("### 来源")
        lines.append("")
        for src in sources:
            url = f"（{src.get('url', '')}）" if src.get("url") else ""
            note = f" — {src.get('note', '')}" if src.get("note") else ""
            lines.append(f"- {src.get('title', '')}{url}{note}")
        lines.append("")


def _render_section_v1(s: dict, crit_by_id: dict, lines: list[str]) -> None:
    """旧结构（explanation/steps/examples/...）渲染，保持历史版本可导出。"""
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


def _tutorial_base_name(goal) -> str:
    return f"{_safe_filename(goal.title)}-教程"


def export_markdown(db: Session, tutorial_id: str) -> tuple[str, str]:
    """导出聚焦学习的 Markdown；任务元数据放 YAML，内部验收与质量报告不进正文。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {"outline": [], "sections": []})
    profile = get_profile(goal.domain_key)
    crit_by_id = {}
    cheatsheet = content.get("cheatsheet") or {}
    exercises_file = content.get("extra_exercises") or {}

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {tutorial.title}")
    lines.append("ai_edu:")
    lines.append(f"  tutorial_id: {tutorial.id}")
    lines.append(f"  goal_id: {goal.id}")
    lines.append(f"  version: {version.version}")
    lines.append(f"  generation_tier: {normalize_tier(getattr(goal, 'generation_tier', None))}")
    lines.append(f"  generated_at: {version.created_at or ''}")
    lines.append(f"  discipline: {profile.display_name}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {tutorial.title}")
    lines.append("")

    # 配套文件是学习内容的直接延伸，保留 Obsidian 双链；验收与质量报告另行在 AI Edu 查看。
    companion = []
    if cheatsheet.get("sections"):
        companion.append(f"[[{cheatsheet.get('filename') or _safe_filename(goal.title) + '-知识速查'}]]（知识速查）")
    if exercises_file.get("exercises"):
        companion.append(
            f"[[{exercises_file.get('filename') or _safe_filename(goal.title) + '-额外练习'}]]（额外练习，含参考答案）"
        )
    if companion:
        lines.append("## 配套文件")
        lines.append("")
        for item in companion:
            lines.append(f"- {item}")
        lines.append("")

    outline = content.get("outline", [])
    sections = content.get("sections", [])
    if outline:
        lines.append("## 目录")
        lines.append("")
        for idx, item in enumerate(outline, 1):
            lines.append(f"{idx}. {item.get('title', '')}")
        lines.append("")

    for idx, section in enumerate(sections, 1):
        lines.append(f"## 第 {idx} 节：{section.get('title', '')}")
        lines.append("")
        if section.get("content"):
            _render_section_v2(section, crit_by_id, lines)
        else:
            _render_section_v1(section, crit_by_id, lines)

    allowed_links = {_tutorial_base_name(goal)}
    if cheatsheet.get("sections"):
        allowed_links.add(cheatsheet.get("filename") or f"{_safe_filename(goal.title)}-知识速查")
    if exercises_file.get("exercises"):
        allowed_links.add(exercises_file.get("filename") or f"{_safe_filename(goal.title)}-额外练习")
    filename = f"{_tutorial_base_name(goal)}.md"
    return filename, normalize_obsidian_syntax("\n".join(lines), allowed_links)
def export_cheatsheet(db: Session, tutorial_id: str) -> tuple[str, str]:
    """导出配套知识速查文件。未生成时 404。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    cheatsheet = content.get("cheatsheet") or {}
    sections = cheatsheet.get("sections") or []
    if not sections:
        raise HTTPException(
            status_code=404,
            detail={"code": "cheatsheet_not_found", "message": "该教程没有可导出的知识速查文件"},
        )

    lines: list[str] = []
    lines.append(f"# {cheatsheet.get('title') or f'{goal.title} · 知识速查'}")
    lines.append("")
    lines.append(f"> 配套教程：[[{_tutorial_base_name(goal)}]]")
    lines.append(">")
    lines.append("> 本文件只用于快速查阅，不能替代教程正文讲解；核心概念以教程正文的解释为准。")
    lines.append("")
    for sec in sections:
        lines.append(f"## {sec.get('heading', '')}")
        lines.append("")
        lines.append(str(sec.get("body", "")))
        lines.append("")

    filename = f"{cheatsheet.get('filename') or _safe_filename(goal.title) + '-知识速查'}.md"
    return filename, normalize_obsidian_syntax("\n".join(lines), {_tutorial_base_name(goal)})


def export_extra_exercises(db: Session, tutorial_id: str) -> tuple[str, str]:
    """导出独立额外练习文件（用户开启选项时生成）。未生成时 404。"""
    tutorial = _get_tutorial(db, tutorial_id)
    goal = _goal_for(db, tutorial.goal_id)
    version = _current_version(db, tutorial)
    if version is None:
        raise HTTPException(status_code=409, detail={"code": "no_content", "message": "教程尚无内容"})
    content = jload(version.content_json, {})
    extra = content.get("extra_exercises") or {}
    exercises = extra.get("exercises") or []
    if not exercises:
        raise HTTPException(
            status_code=404,
            detail={"code": "exercises_not_found", "message": "该教程没有额外练习文件（可在学习目标中开启后重新生成）"},
        )

    lines: list[str] = []
    lines.append(f"# {extra.get('title') or f'{goal.title} · 额外练习'}")
    lines.append("")
    lines.append(f"> 配套教程：[[{_tutorial_base_name(goal)}]]")
    lines.append(">")
    if extra.get("intro"):
        for row in str(extra["intro"]).splitlines():
            lines.append(f"> {row}")
        lines.append(">")
    lines.append("> 参考答案集中在本文件末尾，建议先独立完成再对照。")
    lines.append("")

    level = _LEVEL_LABELS.get(normalize_level(goal.capability_level), "独立应用")
    lines.append(f"难度基准：{level}（{normalize_level(goal.capability_level)}）")
    lines.append("")
    lines.append("## 题目")
    lines.append("")
    for ex in exercises:
        num = ex.get("number") or ""
        lines.append(f"### 练习 {num}")
        lines.append("")
        lines.append(str(ex.get("task", "")))
        lines.append("")
        if ex.get("requirements"):
            lines.append(f"- 要求：{ex['requirements']}")
        if ex.get("hint"):
            lines.append(f"- 提示：{ex['hint']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 参考答案与自检标准")
    lines.append("")
    for ex in exercises:
        num = ex.get("number") or ""
        lines.append(f"### 练习 {num} 参考")
        lines.append("")
        lines.append(str(ex.get("solution", "")))
        lines.append("")
    if extra.get("answers_note"):
        lines.append(f"> {extra['answers_note']}")
        lines.append("")

    filename = f"{extra.get('filename') or _safe_filename(goal.title) + '-额外练习'}.md"
    return filename, normalize_obsidian_syntax("\n".join(lines), {_tutorial_base_name(goal)})


def mark_delivery(db: Session, tutorial_id: str, payload) -> dict:
    """插件写入 Vault 成功后回写交付状态；生成状态与交付状态独立。"""
    tutorial = _get_tutorial(db, tutorial_id)
    version = _current_version(db, tutorial)
    tutorial.delivery_status = "delivered" if payload.status == "delivered" else "failed"
    tutorial.delivery_path = str(payload.path or "")
    version_id = payload.version or (version.version if version else 0)
    tutorial.delivery_version = int(version_id or 0)
    db.commit()
    return tutorial_dict(db, tutorial)
