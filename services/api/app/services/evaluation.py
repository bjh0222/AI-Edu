"""独立 LLM 教程质量评估。

设计约束：默认关闭；未启用或未填专用评估 Key 时完全不调用模型、不写报告。
评估结果只作为独立参考，不参与 check_structure 的通过判定，也不影响教程状态。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings, settings
from ..llm.provider import LLMError, OpenAICompatibleProvider
from ..llm.service import estimate_usage
from ..model_settings import profile_settings, read_config
from ..models import ModelCallLog, TutorialVersion
from ..services.utils import jdump, jload

logger = logging.getLogger("aiedu")

FEATURE = "independent_eval"


class EvaluationError(Exception):
    """独立评估失败；调用方只记日志，不得影响教程状态。"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _estimated_usage(prompt_text: str, output_text: str) -> dict[str, Any]:
    return estimate_usage(prompt_text, output_text)


def _required(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("knowledge_quality", "teaching_quality"):
        value = data.get(key)
        if not isinstance(value, dict) or not str(value.get("summary", "")).strip():
            raise EvaluationError(f"评估输出缺少有效字段：{key}.summary")
        try:
            score = int(value.get("score"))
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"评估输出缺少有效字段：{key}.score") from exc
        if not 1 <= score <= 5:
            raise EvaluationError(f"{key}.score 必须在 1~5 之间")
        value["score"] = score
    if not str(data.get("overall_recommendation", "")).strip():
        raise EvaluationError("评估输出缺少有效字段：overall_recommendation")
    return data


def _compact_content(content: dict[str, Any]) -> dict[str, Any]:
    """保留评估需要的全部语义内容，去掉仅导出/交付用的附件。

    这里不静默截断正文：独立评估本来就是按教程整体语义打分，丢正文会造成假评分。
    """
    sections = []
    for section in content.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sections.append({
            "title": section.get("title", ""),
            "mapping_criteria": section.get("mapping_criteria", []),
            "content": section.get("content", section.get("explanation", "")),
            "steps": section.get("steps", []),
        })
    return {
        "outline": content.get("outline", []),
        "sections": sections,
    }


def _provider_for_version(version: TutorialVersion) -> OpenAICompatibleProvider:
    """评估端点/模型沿用当前启用 profile，但 API Key 必须是评估专用 Key。"""
    config = read_config()
    eval_cfg = config.get("independent_eval") or {}
    key = str(eval_cfg.get("api_key") or "").strip()
    if not key:
        raise EvaluationError("缺少独立评估 API Key")
    active = next(
        (p for p in config.get("profiles") or [] if p.get("id") == config.get("active_id")),
        None,
    )
    if not active:
        raise EvaluationError("请先启用一个模型配置，提供评估用的 API 根地址与模型 ID")
    snapshot: Settings = profile_settings(active)
    snapshot.llm_api_key = key
    return OpenAICompatibleProvider(snapshot)


def evaluation_prompt(content: dict[str, Any], checks: list[dict[str, Any]]) -> tuple[str, str]:
    """自包含双量规提示词；刻意不 import prompts.py。"""
    system = (
        "你是独立的教程质量评审员。你只能依据提供的教程内容与确定性检查结果评分，"
        "不得改写教程，不得虚构未提供的内容。只输出严格 JSON 对象，不输出 Markdown 围栏。"
    )
    payload = {
        "content": _compact_content(content),
        "deterministic_checks": checks,
        "rubrics": {
            "knowledge_quality": "知识梳理质量：概念边界、层级结构、必要关联、去重与整体脉络是否清晰准确。",
            "teaching_quality": "教学质量：学习目标衔接、验收标准映射、内容可验证性、讲解与例证是否支撑学习。",
        },
        "output_schema": {
            "knowledge_quality": {
                "score": "1~5 整数",
                "summary": "50 字以内的核心判断",
                "issues": ["最多 5 条具体问题"],
            },
            "teaching_quality": {
                "score": "1~5 整数",
                "summary": "50 字以内的核心判断",
                "issues": ["最多 5 条具体问题"],
            },
            "overall_recommendation": "60 字以内，说明最优先的 1~2 个改进点",
        },
    }
    user = json.dumps(payload, ensure_ascii=False)
    return system, user


def evaluate_version(
    db: Session,
    version_id: str,
    *,
    provider: OpenAICompatibleProvider | None = None,
) -> dict[str, Any]:
    """评估指定教程版本；返回结果并在成功时写入 quality_report.independent_eval。"""
    version = db.get(TutorialVersion, version_id)
    if not version:
        raise EvaluationError("教程版本不存在")

    config = read_config()
    eval_cfg = config.get("independent_eval") or {}
    effective_enabled = bool(
        eval_cfg.get("enabled", settings.independent_eval_enabled)
    )
    has_key = bool(str(eval_cfg.get("api_key") or "").strip())
    if not effective_enabled:
        return {"status": "skipped", "reason": "independent_eval_disabled", "demo": False}
    if not has_key:
        return {"status": "skipped", "reason": "evaluation_key_missing", "demo": False}

    content = jload(version.content_json, {"outline": [], "sections": []})
    checks = jload(version.quality_report, {}).get("checks", [])
    system, user = evaluation_prompt(content, checks if isinstance(checks, list) else [])
    actual_provider = provider or _provider_for_version(version)
    started_at = _now()
    try:
        data, latency_ms, usage = actual_provider.complete_json(system, user)
        result = _required(data if isinstance(data, dict) else {})
    except (Exception, LLMError) as exc:  # noqa: BLE001  失败只记日志，不碰教程状态
        error = str(exc)[:500]
        try:
            db.add(ModelCallLog(
                feature=FEATURE,
                provider="openai-compatible",
                model=actual_provider.model,
                tutorial_id=version.tutorial_id,
                latency_ms=0,
                status="error",
                error_category=exc.__class__.__name__,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                usage_source="",
            ))
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        logger.warning("独立评估失败：%s", error)
        raise EvaluationError(error) from exc

    real_usage = usage or _estimated_usage(f"{system}\n{user}", json.dumps(result, ensure_ascii=False))
    report: dict[str, Any] = {
        "status": "ok",
        "demo": False,
        "evaluated_at": started_at,
        "model": actual_provider.model,
        "result": result,
        "usage": real_usage,
    }
    stored = jload(version.quality_report, {})
    stored["independent_eval"] = report
    version.quality_report = jdump(stored)

    try:
        db.add(ModelCallLog(
            feature=FEATURE,
            provider="openai-compatible",
            model=actual_provider.model,
            tutorial_id=version.tutorial_id,
            latency_ms=int(latency_ms or 0),
            status="ok",
            prompt_tokens=int(real_usage.get("prompt_tokens") or 0),
            completion_tokens=int(real_usage.get("completion_tokens") or 0),
            total_tokens=int(real_usage.get("total_tokens") or 0),
            usage_source=str(real_usage.get("usage_source") or ""),
        ))
        db.commit()
    except Exception:  # noqa: BLE001  评估报告保留；日志失败不改变结果
        db.rollback()
    return report
