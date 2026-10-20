"""测试版训练数据：生成材料与用户反馈的持久化、统计与导出（JSONL）。

导出格式刻意贴近常见指令微调样本：
- material：messages = [system, user, assistant]，metadata 保留来源/模型/token；
- feedback：feedback = {rating, tags, comment, target_type} + context 快照。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import LearningGoal, TrainingRecord, Tutorial, TutorialVersion
from .utils import jdump, jload, token_usage_dict

VALID_TARGETS = ("general", "generation", "tutorial", "section")


def _preview(text: str, limit: int = 240) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def record_dict(record: TrainingRecord) -> dict:
    return {
        "id": record.id,
        "source_type": record.source_type,
        "feature": record.feature,
        "goal_id": record.goal_id,
        "tutorial_id": record.tutorial_id,
        "section_id": record.section_id,
        "rating": record.rating,
        "tags": jload(record.tags, []),
        "comment": record.comment or "",
        "created_at": record.created_at,
        "model_provider": record.model_provider or "",
        "model_name": record.model_name or "",
        "token_usage": token_usage_dict(
            record.prompt_tokens,
            record.completion_tokens,
            record.total_tokens,
            record.usage_source or "",
            calls=1 if (record.total_tokens or 0) > 0 else 0,
        ),
        "context": jload(record.context_json, {}),
        "prompt_preview": _preview("\n".join(x for x in (record.system_prompt, record.user_prompt) if x)),
        "output_preview": _preview(record.output_text),
        "prompt_chars": len(record.system_prompt or "") + len(record.user_prompt or ""),
        "output_chars": len(record.output_text or ""),
    }


def _touch_targets(db: Session, goal_id: str | None, tutorial_id: str | None, section_id: str | None) -> None:
    if goal_id:
        goal = db.get(LearningGoal, goal_id)
        if goal is None:
            raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})
    if tutorial_id:
        tutorial = db.get(Tutorial, tutorial_id)
        if tutorial is None:
            raise HTTPException(
                status_code=404, detail={"code": "tutorial_not_found", "message": "教程不存在"}
            )
        if section_id:
            version = db.get(TutorialVersion, tutorial.current_version_id) if tutorial.current_version_id else None
            content = jload(version.content_json, {}) if version else {}
            if not any(s.get("id") == section_id for s in content.get("sections", [])):
                raise HTTPException(
                    status_code=404, detail={"code": "section_not_found", "message": "章节不存在"}
                )


def submit_feedback(db: Session, payload) -> dict:
    target_type = payload.target_type or "general"
    if target_type not in VALID_TARGETS:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_target_type", "message": f"target_type 需为 {', '.join(VALID_TARGETS)}"},
        )
    _touch_targets(db, payload.goal_id, payload.tutorial_id, payload.section_id)
    tags = [str(tag).strip()[:40] for tag in (payload.tags or []) if str(tag).strip()][:12]
    context = {
        "target_type": target_type,
        "client_context": payload.context or {},
    }
    record = TrainingRecord(
        source_type="feedback",
        feature="user_feedback",
        goal_id=payload.goal_id,
        tutorial_id=payload.tutorial_id,
        section_id=payload.section_id,
        rating=payload.rating,
        tags=jdump(tags),
        comment=(payload.comment or "").strip()[:2000],
        context_json=jdump(context),
        model_provider="user",
        model_name="feedback",
    )
    db.add(record)
    db.commit()
    return record_dict(record)


def list_records(
    db: Session,
    *,
    source_type: str | None = None,
    goal_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    query = db.query(TrainingRecord)
    if source_type:
        query = query.filter(TrainingRecord.source_type == source_type)
    if goal_id:
        query = query.filter(TrainingRecord.goal_id == goal_id)
    total = query.count()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows = (
        query.order_by(TrainingRecord.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [record_dict(r) for r in rows],
    }


def stats(db: Session) -> dict:
    rows = db.query(TrainingRecord).all()
    materials = [r for r in rows if r.source_type == "material"]
    feedback = [r for r in rows if r.source_type == "feedback"]
    demo_materials = sum(1 for r in materials if (jload(r.context_json, {}) or {}).get("demo"))
    tokens = token_usage_dict()
    by_feature: dict[str, dict] = {}
    for row in materials:
        tokens["prompt_tokens"] += int(row.prompt_tokens or 0)
        tokens["completion_tokens"] += int(row.completion_tokens or 0)
        tokens["total_tokens"] += int(row.total_tokens or 0)
        tokens["calls"] += 1
        item = by_feature.setdefault(row.feature or "unknown", {"feature": row.feature or "unknown", "records": 0, "total_tokens": 0})
        item["records"] += 1
        item["total_tokens"] += int(row.total_tokens or 0)
    if any(r.usage_source == "provider" for r in materials):
        tokens["usage_source"] = "provider"
    elif materials:
        tokens["usage_source"] = "estimated"

    positives = sum(1 for r in feedback if r.rating == 1)
    negatives = sum(1 for r in feedback if r.rating == -1)
    return {
        "totals": {
            "records": len(rows),
            "materials": len(materials),
            "feedback": len(feedback),
            "demo_materials": demo_materials,
            "goals": len({r.goal_id for r in rows if r.goal_id}),
        },
        "by_feature": sorted(by_feature.values(), key=lambda x: x["total_tokens"], reverse=True),
        "tokens": tokens,
        "feedback": {
            "positive": positives,
            "negative": negatives,
            "with_comment": sum(1 for r in feedback if (r.comment or "").strip()),
        },
    }


def _material_sample(record: TrainingRecord) -> dict:
    messages = []
    if record.system_prompt:
        messages.append({"role": "system", "content": record.system_prompt})
    if record.user_prompt:
        messages.append({"role": "user", "content": record.user_prompt})
    if record.output_text:
        messages.append({"role": "assistant", "content": record.output_text})
    context = jload(record.context_json, {})
    return {
        "id": record.id,
        "source_type": "material",
        "feature": record.feature,
        "created_at": record.created_at,
        "messages": messages,
        "metadata": {
            "goal_id": record.goal_id,
            "tutorial_id": record.tutorial_id,
            "section_id": record.section_id,
            "model_provider": record.model_provider,
            "model_name": record.model_name,
            "prompt_tokens": record.prompt_tokens,
            "completion_tokens": record.completion_tokens,
            "total_tokens": record.total_tokens,
            "usage_source": record.usage_source,
            "demo": bool(context.get("demo")),
            "context": context,
        },
    }


def _feedback_sample(record: TrainingRecord) -> dict:
    context = jload(record.context_json, {})
    return {
        "id": record.id,
        "source_type": "feedback",
        "feature": record.feature,
        "created_at": record.created_at,
        "feedback": {
            "rating": record.rating,
            "tags": jload(record.tags, []),
            "comment": record.comment,
            "target_type": context.get("target_type", "general"),
        },
        "target": {
            "goal_id": record.goal_id,
            "tutorial_id": record.tutorial_id,
            "section_id": record.section_id,
        },
        "context": context.get("client_context", {}),
    }


def export_dataset(
    db: Session,
    *,
    source_type: str | None = None,
    goal_id: str | None = None,
    exclude_demo: bool = False,
    fmt: str = "jsonl",
) -> tuple[str, str, str]:
    """导出训练数据，返回 (文件名, 内容, media_type)。"""
    if source_type and source_type not in ("material", "feedback"):
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_source_type", "message": "source_type 仅支持 material / feedback"},
        )
    query = db.query(TrainingRecord)
    if source_type:
        query = query.filter(TrainingRecord.source_type == source_type)
    if goal_id:
        query = query.filter(TrainingRecord.goal_id == goal_id)
    rows = query.order_by(TrainingRecord.created_at.asc()).all()

    samples = []
    for record in rows:
        if record.source_type == "feedback":
            samples.append(_feedback_sample(record))
        else:
            context = jload(record.context_json, {})
            if exclude_demo and context.get("demo"):
                continue
            samples.append(_material_sample(record))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = source_type or "all"
    if fmt == "json":
        content = json.dumps(samples, ensure_ascii=False, indent=2)
        filename = f"aiedu-training-{suffix}-{stamp}.json"
        media_type = "application/json; charset=utf-8"
    else:
        content = "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples)
        if content:
            content += "\n"
        filename = f"aiedu-training-{suffix}-{stamp}.jsonl"
        media_type = "application/x-ndjson; charset=utf-8"
    return filename, content, media_type


def export_disposition(filename: str) -> str:
    return f"attachment; filename*=UTF-8''{quote(filename)}"
