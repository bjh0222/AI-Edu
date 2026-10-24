"""服务层公共工具。"""
from __future__ import annotations

import json
from typing import Any

from ..learning.disciplines import get_profile
from ..learning.engine import PHASES
from ..learning.generation_tiers import normalize_tier
from ..learning.levels import normalize_level


def jload(text: str | None, default: Any = None) -> Any:
    if not text:
        return default if default is not None else []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def jdump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def set_status_at_least(goal, phase: str) -> None:
    # 已删除的阶段（practice/feedback/…）直接忽略，旧数据状态保持原值
    if phase not in PHASES:
        return
    try:
        cur = PHASES.index(goal.status)
    except ValueError:
        cur = -1  # 旧数据可能停留在已删除的阶段，视为最前
    new = PHASES.index(phase)
    if new > cur:
        goal.status = phase


def goal_dict(goal) -> dict:
    profile = get_profile(goal.domain_key)
    return {
        "id": goal.id,
        "title": goal.title,
        "domain_key": goal.domain_key,
        "domain_name": profile.display_name,
        "motivation": goal.motivation or "",
        "application_context": goal.application_context or "",
        "current_level": goal.current_level or "",
        "time_budget": goal.time_budget or "",
        # 旧数据该字段为 NULL → 归一化默认层级
        "capability_level": normalize_level(getattr(goal, "capability_level", None)),
        "generate_extra_exercises": bool(getattr(goal, "generate_extra_exercises", False)),
        "generation_tier": normalize_tier(getattr(goal, "generation_tier", None)),
        "status": goal.status,
        "user_notes": goal.user_notes or "",
        "archived": bool(goal.archived),
        "completed": bool(getattr(goal, "completed", False)),
        "completed_at": getattr(goal, "completed_at", "") or "",
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


def criterion_dict(c) -> dict:
    return {
        "id": c.id,
        "goal_id": c.goal_id,
        "plan_step_id": c.plan_step_id,
        "statement": c.statement,
        "conditions": c.conditions or "",
        "evidence_type": c.evidence_type or "product",
        "pass_rule": c.pass_rule or "",
        "status": c.status,
        "rationale": c.rationale or "",
    }


def step_dict(s) -> dict:
    return {
        "id": s.id,
        "plan_id": s.plan_id,
        "order_index": s.order_index,
        "title": s.title,
        "objective": s.objective or "",
        "status": s.status,
        "dependencies": jload(s.dependencies, []),
        "estimated_effort": s.estimated_effort or "",
        "completion_evidence_refs": jload(s.completion_evidence_refs, []),
    }


def task_dict(t) -> dict:
    return {
        "id": t.id,
        "goal_id": t.goal_id,
        "plan_step_id": t.plan_step_id,
        "tutorial_id": t.tutorial_id,
        "title": t.title,
        "instructions": t.instructions or "",
        "task_type": t.task_type or "practice",
        "expected_artifact": t.expected_artifact or "",
        "validation_rule": t.validation_rule or "",
        "status": t.status,
        "created_at": t.created_at,
    }


def token_usage_dict(
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    usage_source: str = "",
    calls: int = 0,
) -> dict:
    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    total = int(total_tokens or 0)
    if total == 0 and (prompt or completion):
        total = prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "usage_source": usage_source or "",
        "calls": int(calls or 0),
    }


def add_usage(target: dict, prompt: int | None, completion: int | None, total: int | None) -> dict:
    """把一次调用累加进 usage 字典（就地修改并返回）。"""
    target["prompt_tokens"] = int(target.get("prompt_tokens") or 0) + int(prompt or 0)
    target["completion_tokens"] = int(target.get("completion_tokens") or 0) + int(completion or 0)
    target["total_tokens"] = int(target.get("total_tokens") or 0) + int(total or 0)
    target["calls"] = int(target.get("calls") or 0) + 1
    return target


def tutorial_version_dict(v) -> dict:
    return {
        "id": v.id,
        "tutorial_id": v.tutorial_id,
        "version": v.version,
        "content": jload(v.content_json, {"outline": [], "sections": []}),
        "prompt_version": v.prompt_version or "v1",
        "model_provider": v.model_provider or "demo",
        "model_name": v.model_name or "demo",
        "quality_report": jload(v.quality_report, {}),
        "source_refs": jload(v.source_refs, []),
        "token_usage": token_usage_dict(
            v.prompt_tokens,
            v.completion_tokens,
            v.total_tokens,
            v.usage_source or "",
            calls=1 if (v.total_tokens or 0) > 0 else 0,
        ),
        "created_at": v.created_at,
    }
