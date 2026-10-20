"""token 用量统计：按目标 / 特性 / 教程聚合模型调用日志。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import LearningGoal, ModelCallLog, Tutorial
from .utils import add_usage, token_usage_dict


def goal_usage(db: Session, goal_id: str) -> dict:
    goal = db.get(LearningGoal, goal_id)
    if goal is None or goal.archived:
        raise HTTPException(status_code=404, detail={"code": "goal_not_found", "message": "学习目标不存在"})

    rows = (
        db.query(ModelCallLog)
        .filter(ModelCallLog.goal_id == goal_id)
        .order_by(ModelCallLog.created_at.asc())
        .all()
    )
    totals = token_usage_dict()
    by_feature: dict[str, dict] = {}
    by_tutorial: dict[str, dict] = {}
    provider_calls = 0
    estimated_calls = 0

    for row in rows:
        add_usage(totals, row.prompt_tokens, row.completion_tokens, row.total_tokens)
        if row.usage_source == "provider":
            provider_calls += 1
        elif row.usage_source == "estimated":
            estimated_calls += 1
        feature_key = row.feature or "unknown"
        feature = by_feature.setdefault(feature_key, token_usage_dict() | {"feature": feature_key})
        add_usage(feature, row.prompt_tokens, row.completion_tokens, row.total_tokens)
        if row.tutorial_id:
            item = by_tutorial.setdefault(
                row.tutorial_id, token_usage_dict() | {"tutorial_id": row.tutorial_id}
            )
            add_usage(item, row.prompt_tokens, row.completion_tokens, row.total_tokens)

    titles: dict[str, str] = {}
    if by_tutorial:
        for tutorial in db.query(Tutorial).filter(Tutorial.id.in_(list(by_tutorial))).all():
            titles[tutorial.id] = tutorial.title
    for tutorial_id, item in by_tutorial.items():
        item["tutorial_title"] = titles.get(tutorial_id, "")

    totals["usage_source"] = "provider" if provider_calls and not estimated_calls else (
        "estimated" if estimated_calls else ""
    )
    return {
        "goal_id": goal_id,
        "totals": totals,
        "provider_calls": provider_calls,
        "estimated_calls": estimated_calls,
        "by_feature": sorted(by_feature.values(), key=lambda x: x["total_tokens"], reverse=True),
        "by_tutorial": sorted(by_tutorial.values(), key=lambda x: x["total_tokens"], reverse=True),
    }
