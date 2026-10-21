"""AIService：任务级模型调用（真实模型 / 演示生成器统一入口）。

除生成内容外，本服务还负责两件与「测试版数据」相关的记账工作：

1. token 用量：优先使用提供方返回的 usage；没有 usage 时按字符估算并标记 estimated；
   每次调用写入 ModelCallLog（含 goal / tutorial / job 关联），供接口累计与展示。
2. 训练样本：把「输入 prompt + 生成输出 + 元数据」写入 TrainingRecord，供测试版导出
   后做后续预训练；用户反馈同样写入该表（source_type=feedback）。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..learning import demo
from ..models import ModelCallLog, TrainingRecord
from . import prompts
from .provider import LLMError, OpenAICompatibleProvider


class AIServiceError(Exception):
    """生成失败（模型不可用 / 输出不合法），由路由转为 502。"""


EMPTY_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "usage_source": ""}


def _require(obj: dict, *keys: str) -> dict:
    missing = [k for k in keys if k not in obj or obj[k] in (None, "")]
    if missing:
        raise AIServiceError(f"模型输出缺少字段：{', '.join(missing)}")
    return obj


def estimate_tokens(text: str) -> int:
    """粗估 token 数：CJK 约 1 字 1 token，其余字符约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def estimate_usage(prompt_text: str, output_text: str) -> dict[str, Any]:
    prompt = estimate_tokens(prompt_text)
    completion = estimate_tokens(output_text)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "usage_source": "estimated",
    }


def _add_usage(total: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    merged = dict(total)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        merged[key] = int(merged.get(key) or 0) + int(usage.get(key) or 0)
    if usage.get("usage_source"):
        merged["usage_source"] = usage["usage_source"]
    return merged


def goal_context_text(goal) -> str:
    """把目标转成一段稳定文本，作为演示模式下的「输入」与训练样本上下文。"""
    if goal is None:
        return ""
    fields = [
        ("目标", getattr(goal, "title", "")),
        ("学科", getattr(goal, "domain_key", "")),
        ("动机", getattr(goal, "motivation", "")),
        ("应用场景", getattr(goal, "application_context", "")),
        ("当前基础", getattr(goal, "current_level", "")),
        ("可投入总时间", getattr(goal, "time_budget", "")),
    ]
    return "\n".join(f"{name}：{value}" for name, value in fields if value)


class AIService:
    def __init__(
        self,
        db: Session | None = None,
        *,
        goal_id: str | None = None,
        tutorial_id: str | None = None,
        section_id: str | None = None,
        job_id: str | None = None,
    ):
        self.db = db
        self.provider = OpenAICompatibleProvider(settings) if settings.llm_configured else None
        self.goal_id = goal_id
        self.tutorial_id = tutorial_id
        self.section_id = section_id
        self.job_id = job_id
        self.usage_last: dict[str, Any] = dict(EMPTY_USAGE)
        self.usage_total: dict[str, Any] = dict(EMPTY_USAGE)

    @property
    def is_demo(self) -> bool:
        return self.provider is None

    # ------------------------------------------------------------ accounting
    def _record(
        self,
        feature: str,
        *,
        system: str,
        user: str,
        output: Any,
        usage: dict[str, Any],
        goal=None,
        latency_ms: int = 0,
        status: str = "ok",
        error_category: str = "",
    ) -> None:
        self.usage_last = usage
        self.usage_total = _add_usage(self.usage_total, usage)
        if self.db is None:
            return
        goal_id = getattr(goal, "id", None) or self.goal_id
        provider = "demo" if self.is_demo else "openai-compatible"
        model_name = "demo" if self.is_demo else (settings.llm_model or "configured")
        try:
            self.db.add(
                ModelCallLog(
                    feature=feature,
                    provider=provider,
                    model=model_name,
                    goal_id=goal_id,
                    tutorial_id=self.tutorial_id,
                    job_id=self.job_id,
                    latency_ms=latency_ms,
                    status=status,
                    error_category=error_category,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    usage_source=usage.get("usage_source", ""),
                )
            )
            if status == "ok":
                context = {
                    "goal_id": goal_id,
                    "goal_title": getattr(goal, "title", ""),
                    "domain_key": getattr(goal, "domain_key", ""),
                    "tutorial_id": self.tutorial_id,
                    "section_id": self.section_id,
                    "demo": self.is_demo,
                }
                self.db.add(
                    TrainingRecord(
                        source_type="material",
                        feature=feature,
                        goal_id=goal_id,
                        tutorial_id=self.tutorial_id,
                        section_id=self.section_id,
                        system_prompt=system or "",
                        user_prompt=user or "",
                        output_text=output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
                        model_provider=provider,
                        model_name=model_name,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        total_tokens=usage.get("total_tokens", 0),
                        usage_source=usage.get("usage_source", ""),
                        context_json=json.dumps(context, ensure_ascii=False),
                    )
                )
        except Exception:  # noqa: BLE001  记账失败不影响主流程
            pass

    def _log_error(self, feature: str, exc: LLMError) -> None:
        """错误调用只记调用日志，不产生训练样本。"""
        self._record(
            feature,
            system="",
            user="",
            output="",
            usage=dict(EMPTY_USAGE),
            status="error",
            error_category=exc.__class__.__name__,
        )

    # ------------------------------------------------------------ internal
    def _real_json(self, feature: str, system: str, user: str, required: tuple[str, ...], goal=None) -> dict:
        try:
            data, latency, usage = self.provider.complete_json(system, user)  # type: ignore[union-attr]
        except LLMError as exc:
            self._log_error(feature, exc)
            raise AIServiceError(str(exc)) from exc
        if usage is None:
            usage = estimate_usage(f"{system}\n{user}", json.dumps(data, ensure_ascii=False))
        self._record(
            feature,
            system=system,
            user=user,
            output=data,
            usage=usage,
            goal=goal,
            latency_ms=latency,
        )
        return _require(data, *required)

    def _demo(self, feature: str, output: Any, goal=None, extra_user: str = "") -> Any:
        """演示模式：记录估算 token 与「合成输入」，训练样本标记 demo=true。"""
        system = f"（演示生成器：{feature}，未配置真实模型）"
        user = goal_context_text(goal)
        if (extra_user or "").strip():
            user = f"{user}\n{extra_user.strip()}"
        usage = estimate_usage(f"{system}\n{user}", json.dumps(output, ensure_ascii=False))
        self._record(feature, system=system, user=user, output=output, usage=usage, goal=goal)
        return output

    # ------------------------------------------------------------ features
    def diagnose(self, goal, discipline, materials_text: str = "") -> dict:
        if self.is_demo:
            return self._demo("diagnose", demo.diagnose(goal, discipline), goal, materials_text)
        system, user = prompts.diagnose(goal, discipline, materials_text)
        return self._real_json(
            "diagnose", system, user,
            ("benefits", "prerequisites", "alternatives", "assumptions", "uncertainties", "recommendation"),
            goal,
        )

    def plan(self, goal, discipline, materials_text: str = "") -> dict:
        if self.is_demo:
            return self._demo("plan", demo.plan(goal, discipline), goal, materials_text)
        system, user = prompts.plan(goal, discipline, materials_text)
        data = self._real_json("plan", system, user, ("steps",), goal)
        if not isinstance(data.get("steps"), list) or not data["steps"]:
            raise AIServiceError("模型输出缺少有效步骤列表")
        return data

    def criteria(self, goal, discipline) -> dict:
        if self.is_demo:
            return self._demo("criteria", {"criteria": demo.criteria(goal, discipline)}, goal)
        system, user = prompts.criteria(goal, discipline)
        data = self._real_json("criteria", system, user, ("criteria",), goal)
        if not isinstance(data.get("criteria"), list) or not data["criteria"]:
            raise AIServiceError("模型输出缺少有效验收标准列表")
        return data

    def outline(self, goal, discipline, criteria_list, materials_text: str = "") -> dict:
        if self.is_demo:
            ids = [c["id"] for c in criteria_list]
            return self._demo(
                "outline", {"sections": demo.outline(goal, discipline, ids)}, goal, materials_text
            )
        system, user = prompts.outline(goal, discipline, criteria_list, materials_text)
        data = self._real_json("outline", system, user, ("sections",), goal)
        if not isinstance(data.get("sections"), list) or not data["sections"]:
            raise AIServiceError("模型输出缺少有效大纲")
        return data

    def section(
        self, goal, discipline, item, criteria_list, prior_titles, materials_text: str = ""
    ) -> dict:
        if self.is_demo:
            by_id = {c["id"]: c for c in criteria_list}
            return self._demo(
                "section", demo.section(goal, discipline, item, by_id), goal, materials_text
            )
        system, user = prompts.section(
            goal, discipline, item, criteria_list, prior_titles, materials_text
        )
        data = self._real_json(
            "section", system, user,
            ("title", "explanation", "steps", "exercises", "variation_task", "sources", "mapping_criteria"),
            goal,
        )
        return data

    def feedback(self, goal, criteria_list, task, attempt) -> dict:
        if self.is_demo:
            return self._demo("feedback", demo.feedback(goal, None, task, attempt, criteria_list), goal)
        system, user = prompts.feedback(goal, criteria_list, task, attempt)
        data = self._real_json("feedback", system, user, ("items", "summary"), goal)
        if not isinstance(data.get("items"), list):
            raise AIServiceError("模型输出缺少反馈条目")
        return data

    def assessment(self, goal, discipline) -> dict:
        if self.is_demo:
            return self._demo("assessment", demo.assessment(goal, discipline), goal)
        system, user = prompts.assessment(goal, discipline)
        data = self._real_json("assessment", system, user, ("rubric", "independent_task", "variant_task"), goal)
        return data

    def reflection(self, goal, context) -> dict:
        if self.is_demo:
            return self._demo("reflection", demo.reflection(goal, context), goal)
        system, user = prompts.reflection(goal, context)
        return self._real_json(
            "reflection", system, user,
            ("summary", "learned_capabilities", "unresolved_gaps", "next_actions"),
            goal,
        )

    def suggest_proposals(self, goal, concepts, relations_hint) -> dict:
        if self.is_demo:
            return self._demo("proposals", {"proposals": demo.propose(goal, concepts, relations_hint)}, goal)
        system, user = prompts.suggest_proposals(goal, concepts, relations_hint)
        return self._real_json("proposals", system, user, ("proposals",), goal)

    def chat(self, goal, question: str, context: dict) -> dict:
        if self.is_demo:
            return self._demo("chat", {"answer": demo.chat(goal, question, context)}, goal)
        system, user = prompts.chat(goal, question, context)
        return self._real_json("chat", system, user, ("answer",), goal)
