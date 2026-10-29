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

from ..model_settings import runtime_settings
from ..learning import demo
from ..learning.teaching_profile import check_rule_compliance, parse_teaching_profile
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


def _section_check_text(data: dict) -> str:
    """抽取章节输出里可核验的正文文本（不含 sources 的 url/note）。"""
    parts: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict):
            parts.append(str(block.get("title", "")))
            parts.append(str(block.get("body", "")))
    for key in ("key_takeaways", "exercises", "prerequisite_refs"):
        for item in data.get(key) or []:
            parts.append(str(item))
    for item in data.get("common_errors") or []:
        if isinstance(item, dict):
            parts.extend(str(item.get(field, "")) for field in ("error", "cause", "diagnose"))
    return "\n".join(parts)


def _sections_check_text(data: dict) -> str:
    """抽取「小节列表」型输出（知识速查）的可核验文本。"""
    parts: list[str] = []
    for item in data.get("sections") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("heading", "")))
            parts.append(str(item.get("body", "")))
    return "\n".join(parts)


def _exercises_check_text(data: dict) -> str:
    """抽取「练习列表」型输出（额外练习）的可核验文本。"""
    parts: list[str] = [str(data.get("intro", "")), str(data.get("answers_note", ""))]
    for item in data.get("exercises") or []:
        if isinstance(item, dict):
            parts.extend(
                str(item.get(field, ""))
                for field in ("task", "requirements", "hint", "solution")
            )
    return "\n".join(parts)


def _rule_checked(produce, text_of) -> dict:
    """生成 → 核验硬性禁止类约束 → 命中则定向重写一次 → 如实标注。

    `produce(violations)` 用给定违规清单重新生成（violations 为 None 表示首稿），
    `text_of(data)` 从输出里抽出可核验文本。所有注入画像的阶段都走同一条流水线，
    避免「某些阶段的硬约束只停留在提示词里、没人核验」。
    """
    rules = parse_teaching_profile()["rules"]
    data = produce(None)
    violations = check_rule_compliance(text_of(data), rules)
    if not violations:
        return data
    retry = produce([violation["rule"] for violation in violations])
    if not check_rule_compliance(text_of(retry), rules):
        # 定向重写后通过：交付重写稿，并记录「修过」
        retry["rule_check"] = {
            "repaired": True,
            "violations": [violation["reason"] for violation in violations],
        }
        return retry
    # 仍未通过：保留原稿（不交付可能更差的稿），如实标注违规
    data["rule_check"] = {
        "repaired": False,
        "violations": [f"{v['rule']}（{v['reason']}）" for v in violations],
    }
    return data


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
        ("硬性约束", str(getattr(goal, "hard_constraints", "") or "").replace("\n", "；")),
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
        snapshot = runtime_settings()
        self.provider = OpenAICompatibleProvider(snapshot) if snapshot.llm_configured else None
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
        model_name = self.provider.model if self.provider else "demo"
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
        if not isinstance(data, dict):
            self._log_error(feature, LLMError("模型输出不是 JSON 对象"))
            raise AIServiceError(f"模型输出不是 JSON 对象（实际为 {type(data).__name__}）")
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

    def _section_payload(
        self, goal, discipline, item, criteria_list, prior_titles, materials_text: str,
        companion_names: list[str] | None, retry_violations: list[str] | None = None,
        truncated: bool = False,
    ) -> dict:
        system, user = prompts.section(
            goal, discipline, item, criteria_list, prior_titles, materials_text, companion_names,
            retry_violations, truncated=truncated,
        )
        data = self._real_json(
            "section", system, user,
            # mapping_criteria 不作必填：章节里这一项落库时一律由大纲已声明的 criteria_ids
            # 覆盖（见 tutorials.py 的章节写入处），而章节提示词本身并不要求模型输出它。
            # 若把它列为必填，模型严格按提示词输出时必然「缺字段」→ 整章重试 → 白烧 N 次
            # 完整模型往返（每次上万 token），却仍然失败。
            ("title", "content"),
            goal,
        )
        # 可选内容块允许缺失/非法：归一化，不因没有例题或易错点而判定生成失败
        for key in (
            "content", "key_takeaways", "common_errors", "prerequisite_refs",
            "exercises", "sources", "mapping_criteria",
        ):
            if not isinstance(data.get(key), list):
                data[key] = []
        # 模型没给映射就退回大纲里已经声明好的验收标准 id，语义等价且不丢覆盖关系
        if not data["mapping_criteria"] and isinstance(item, dict):
            data["mapping_criteria"] = [str(cid) for cid in (item.get("criteria_ids") or [])]
        return data

    def section(
        self, goal, discipline, item, criteria_list, prior_titles, materials_text: str = "",
        companion_names: list[str] | None = None,
    ) -> dict:
        if self.is_demo:
            by_id = {c["id"]: c for c in criteria_list}
            return self._demo(
                "section", demo.section(goal, discipline, item, by_id), goal, materials_text
            )
        # 硬性禁止类约束做一次确定性核验：命中即定向重写一次，避免规则只停留在提示词里。
        def produce(violations, truncated: bool = False):
            return self._section_payload(
                goal, discipline, item, criteria_list, prior_titles, materials_text,
                companion_names, violations, truncated,
            )

        try:
            return _rule_checked(lambda violations: produce(violations), _section_check_text)
        except AIServiceError as exc:
            if "截断" not in str(exc):
                raise
            # 输出超长被截断（finish_reason=length）：JSON 不完整、原样重发几乎必然再截断，
            # 所以要带「压缩篇幅、保证字段完整」的要求重试一次，而不是白烧一次完整往返。
            return _rule_checked(
                lambda violations: produce(violations, truncated=True), _section_check_text
            )

    def cheatsheet(self, goal, discipline, outline_items, materials_text: str = "") -> dict:
        """知识速查文件（教程配套，总是生成）。失败抛 AIServiceError，由调用方兜底。"""
        if self.is_demo:
            return self._demo("cheatsheet", demo.cheatsheet(goal, discipline, outline_items), goal)

        def produce(violations):
            system, user = prompts.cheatsheet(
                goal, discipline, outline_items, materials_text, violations
            )
            data = self._real_json("cheatsheet", system, user, ("sections",), goal)
            data["sections"] = [
                {"heading": str(s.get("heading", "") or ""), "body": str(s.get("body", "") or "")}
                for s in data.get("sections", []) or []
                if isinstance(s, dict) and str(s.get("body", "")).strip()
            ]
            return data

        return _rule_checked(produce, _sections_check_text)

    def extra_exercises(self, goal, discipline, outline_items, materials_text: str = "") -> dict:
        """独立额外练习文件（仅在用户开启选项时生成）。失败抛 AIServiceError，由调用方兜底。"""
        if self.is_demo:
            return self._demo("extra_exercises", demo.extra_exercises(goal, discipline, outline_items), goal)

        def produce(violations):
            system, user = prompts.extra_exercises(
                goal, discipline, outline_items, materials_text, violations
            )
            data = self._real_json("extra_exercises", system, user, ("exercises",), goal)
            data["exercises"] = [
                {
                    "number": int(e.get("number") or idx + 1),
                    "task": str(e.get("task", "") or ""),
                    "requirements": str(e.get("requirements", "") or ""),
                    "hint": str(e.get("hint", "") or ""),
                    "solution": str(e.get("solution", "") or ""),
                }
                for idx, e in enumerate(data.get("exercises", []) or [])
                if isinstance(e, dict) and str(e.get("task", "")).strip()
            ]
            return data

        return _rule_checked(produce, _exercises_check_text)

    def format_spec_match(self, requirement: str, candidates: list[dict]) -> dict:
        """少量候选规范的语义匹配；失败由 format_specs 服务回退默认规范。"""
        if self.is_demo:
            return {"format_spec_id": "", "confidence": 0, "reason": "演示模式不提供语义识别"}
        system, user = prompts.format_spec_match(requirement, candidates)
        return self._real_json("format_spec_match", system, user, (), None)

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

    def knowledge_extract(self, goal, tutorial, context: dict, existing: list) -> dict:
        """教程生成后的结构化知识提取（概念 + 关系）。失败抛 AIServiceError，由调用方兜底。"""
        if self.is_demo:
            data = demo.knowledge_extract(goal, tutorial, context, existing)
            return self._demo("knowledge_extract", data, goal)
        system, user = prompts.knowledge_extract(goal, tutorial, context, existing)
        data = self._real_json("knowledge_extract", system, user, ("concepts", "relations"), goal)
        if not isinstance(data.get("concepts"), list):
            raise AIServiceError("模型输出缺少概念列表")
        if not isinstance(data.get("relations"), list):
            data["relations"] = []
        return data

    def chat(self, goal, question: str, context: dict) -> dict:
        if self.is_demo:
            return self._demo("chat", {"answer": demo.chat(goal, question, context)}, goal)
        system, user = prompts.chat(goal, question, context)
        return self._real_json("chat", system, user, ("answer",), goal)

    def user_profile_suggestion(self, context: dict) -> dict:
        """每 N 次完整学习后的候选画像；必须由用户确认后才可保存。"""
        if self.is_demo:
            goals = context.get("completed_goals", [])
            feedback = context.get("recent_feedback", [])
            notes = [str(item.get("comment", "")).strip() for item in feedback if str(item.get("comment", "")).strip()]
            text = "\n".join(
                [
                    "重视从真实任务出发组织教程。",
                    "练习和结果检查要围绕已完成目标中的关键操作。",
                    *(f"反馈中反复关注：{note}" for note in notes[:3]),
                ]
            ) or "现有证据不足，暂不提出画像修改建议。"
            output = {
                "summary": "根据最近完整学习记录整理的候选教学画像。",
                "profile_text": text,
                "evidence": "；".join(str(item.get("title", "")) for item in goals[:5]),
                "notes": "演示建议，仅用于测试流程，不自动保存。",
            }
            return self._demo("user_profile_suggestion", output, None)
        system, user = prompts.user_profile_suggestion(context)
        data = self._real_json(
            "user_profile_suggestion", system, user,
            ("summary", "profile_text", "evidence", "notes"),
            None,
        )
        if not isinstance(data.get("profile_text"), str) or not data["profile_text"].strip():
            raise AIServiceError("画像建议缺少候选画像文本")
        return data
