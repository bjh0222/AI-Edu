"""服务层公共工具。"""
from __future__ import annotations

import json
import re
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


def safe_obsidian_filename(name: str) -> str:
    """清理 Obsidian 文件名中不允许或易冲突的字符。"""
    cleaned = re.sub(r'[\\/:*?"<>|#^\[\]\r\n]+', " ", name).strip()
    return cleaned or "tutorial"


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
        "hard_constraints": getattr(goal, "hard_constraints", "") or "",
        # 旧数据该字段为 NULL → 归一化默认层级
        "capability_level": normalize_level(getattr(goal, "capability_level", None)),
        "generate_extra_exercises": bool(getattr(goal, "generate_extra_exercises", False)),
        "generation_tier": normalize_tier(getattr(goal, "generation_tier", None)),
        "format_spec_id": getattr(goal, "format_spec_id", "") or "",
        "format_spec_source": getattr(goal, "format_spec_source", "") or "",
        "format_spec_match_note": getattr(goal, "format_spec_match_note", "") or "",
        "format_spec_snapshot": jload(getattr(goal, "format_spec_snapshot", "") or "", {}),
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
    content = align_section_titles(
        prune_foreign_section_blocks(jload(v.content_json, {"outline": [], "sections": []}))
    )
    return {
        "id": v.id,
        "tutorial_id": v.tutorial_id,
        "version": v.version,
        "content": content,
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


def _norm_ws(text: str) -> str:
    """比较标题时忽略空格 / 全角空格差异（模型常把「　」写成「 」）。"""
    return re.sub(r"\s+", "", str(text or ""))


_CHAPTER_RE = re.compile(r"^第\s*([0-9一二三四五六七八九十]+)\s*[章节]")
_ANSWERISH = ("答案", "简析", "解析", "判断")


def _chapter_marker(text: str) -> str:
    match = _CHAPTER_RE.match(str(text or "").strip())
    return match.group(1) if match else ""


def _block_targets_other_chapter(block: dict, others: set) -> bool:
    """块标题或正文首行正好是其它大纲章节标题 → 模型把整篇文档写进了本节。"""
    title = _norm_ws(re.sub(r"^#{1,6}\s*", "", str(block.get("title", "") or "")))
    if title and title in others:
        return True
    first = next((ln.strip() for ln in str(block.get("body", "") or "").splitlines() if ln.strip()), "")
    first = _norm_ws(re.sub(r"^#{1,6}\s*", "", first))
    return bool(first) and first in others


def _block_from_other_chapter(block: dict, own_marker: str) -> bool:
    """非答案章节里，块标题以别的章节编号开头 → 属于其它章节的内容。"""
    if not own_marker:
        return False
    title = re.sub(r"^#{1,6}\s*", "", str(block.get("title", "") or "").strip()).strip()
    marker = _chapter_marker(title)
    return bool(marker) and marker != own_marker


def prune_foreign_section_blocks(content: dict) -> dict:
    """删除误写入当前章节的其它章节整块内容；只按标题精确匹配，避免误伤派生块标题。"""
    outline = content.get("outline") or []
    sections = content.get("sections") or []
    titles = [str(item.get("title", "")).strip() for item in outline if isinstance(item, dict)]
    if not titles or not sections:
        return content
    for idx, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        own = titles[idx] if idx < len(titles) else str(section.get("title", "")).strip()
        others = {_norm_ws(t) for t in titles if t and _norm_ws(t) != _norm_ws(own)}
        own_marker = "" if any(word in own for word in _ANSWERISH) else _chapter_marker(own)
        blocks = section.get("content")
        if not others or not isinstance(blocks, list):
            continue
        kept = [
            b
            for b in blocks
            if not (
                isinstance(b, dict)
                and (
                    _block_targets_other_chapter(b, others)
                    or _block_from_other_chapter(b, own_marker)
                )
            )
        ]
        if len(kept) != len(blocks):
            section["content"] = kept
    return content


def _spec_dict_is_authoritative(spec: dict) -> bool:
    if not isinstance(spec, dict) or not str(spec.get("name", "")).strip():
        return False
    if str(spec.get("scene", "")) == "default_tutorial" and not (spec.get("deliverables") or []):
        return False
    return True


def align_section_titles(content: dict) -> dict:
    """规范接管结构时，章节标题以大纲（交付单元）为准，避免模型自拟整篇标题。"""
    if not _spec_dict_is_authoritative(content.get("format_spec") or {}):
        return content
    titles = [
        str(item.get("title", "")).strip()
        for item in (content.get("outline") or [])
        if isinstance(item, dict)
    ]
    for idx, section in enumerate(content.get("sections") or []):
        if isinstance(section, dict) and idx < len(titles) and titles[idx]:
            section["title"] = titles[idx]
    return content


def prune_section_foreign_blocks(section: dict, outline_titles: list) -> dict:
    """单节版本：生成 / 重生成后立即剔除属于其它章节的整块内容。"""
    own = str(section.get("title", "")).strip()
    others = {_norm_ws(t) for t in outline_titles or [] if _norm_ws(t) and _norm_ws(t) != _norm_ws(own)}
    own_marker = "" if any(word in own for word in _ANSWERISH) else _chapter_marker(own)
    blocks = section.get("content")
    if not others or not isinstance(blocks, list):
        return section
    kept = [
        b
        for b in blocks
        if not (
            isinstance(b, dict)
            and (
                _block_targets_other_chapter(b, others)
                or _block_from_other_chapter(b, own_marker)
            )
        )
    ]
    if len(kept) != len(blocks):
        section["content"] = kept
    return section
