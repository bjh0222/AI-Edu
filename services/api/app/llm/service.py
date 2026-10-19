"""AIService：任务级模型调用（真实模型 / 演示生成器统一入口）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..learning import demo
from ..models import ModelCallLog
from . import prompts
from .provider import LLMError, OpenAICompatibleProvider


class AIServiceError(Exception):
    """生成失败（模型不可用 / 输出不合法），由路由转为 502。"""


def _require(obj: dict, *keys: str) -> dict:
    missing = [k for k in keys if k not in obj or obj[k] in (None, "")]
    if missing:
        raise AIServiceError(f"模型输出缺少字段：{', '.join(missing)}")
    return obj


class AIService:
    def __init__(self, db: Session | None = None):
        self.db = db
        self.provider = OpenAICompatibleProvider(settings) if settings.llm_configured else None

    @property
    def is_demo(self) -> bool:
        return self.provider is None

    # ------------------------------------------------------------ internal
    def _log(self, feature: str, status: str, latency_ms: int = 0, error_category: str = "") -> None:
        """模型调用日志：使用独立短事务写入，避免与请求事务互相持锁。"""
        if self.db is None:
            return
        from ..db import SessionLocal

        try:
            with SessionLocal() as log_db:
                log_db.add(
                    ModelCallLog(
                        feature=feature,
                        provider="demo" if self.is_demo else "openai-compatible",
                        model=settings.llm_model or "demo",
                        latency_ms=latency_ms,
                        status=status,
                        error_category=error_category,
                    )
                )
                log_db.commit()
        except Exception:  # noqa: BLE001  日志失败不影响主流程
            pass

    def _real_json(self, feature: str, system: str, user: str, required: tuple[str, ...]) -> dict:
        try:
            data, latency = self.provider.complete_json(system, user)  # type: ignore[union-attr]
        except LLMError as exc:
            self._log(feature, "error", error_category=exc.__class__.__name__)
            raise AIServiceError(str(exc)) from exc
        self._log(feature, "ok", latency_ms=latency)
        return _require(data, *required)

    # ------------------------------------------------------------ features
    def diagnose(self, goal, discipline) -> dict:
        if self.is_demo:
            return demo.diagnose(goal, discipline)
        system, user = prompts.diagnose(goal, discipline)
        return self._real_json(
            "diagnose", system, user,
            ("benefits", "prerequisites", "alternatives", "assumptions", "uncertainties", "recommendation"),
        )

    def plan(self, goal, discipline) -> dict:
        if self.is_demo:
            return demo.plan(goal, discipline)
        system, user = prompts.plan(goal, discipline)
        data = self._real_json("plan", system, user, ("steps",))
        if not isinstance(data.get("steps"), list) or not data["steps"]:
            raise AIServiceError("模型输出缺少有效步骤列表")
        return data

    def criteria(self, goal, discipline) -> dict:
        if self.is_demo:
            return {"criteria": demo.criteria(goal, discipline)}
        system, user = prompts.criteria(goal, discipline)
        data = self._real_json("criteria", system, user, ("criteria",))
        if not isinstance(data.get("criteria"), list) or not data["criteria"]:
            raise AIServiceError("模型输出缺少有效验收标准列表")
        return data

    def outline(self, goal, discipline, criteria_list) -> dict:
        if self.is_demo:
            ids = [c["id"] for c in criteria_list]
            return {"sections": demo.outline(goal, discipline, ids)}
        system, user = prompts.outline(goal, discipline, criteria_list)
        data = self._real_json("outline", system, user, ("sections",))
        if not isinstance(data.get("sections"), list) or not data["sections"]:
            raise AIServiceError("模型输出缺少有效大纲")
        return data

    def section(self, goal, discipline, item, criteria_list, prior_titles) -> dict:
        if self.is_demo:
            by_id = {c["id"]: c for c in criteria_list}
            return demo.section(goal, discipline, item, by_id)
        system, user = prompts.section(goal, discipline, item, criteria_list, prior_titles)
        data = self._real_json(
            "section", system, user,
            ("title", "explanation", "steps", "exercises", "variation_task", "sources", "mapping_criteria"),
        )
        return data

    def feedback(self, goal, criteria_list, task, attempt) -> dict:
        if self.is_demo:
            return demo.feedback(goal, None, task, attempt, criteria_list)
        system, user = prompts.feedback(goal, criteria_list, task, attempt)
        data = self._real_json("feedback", system, user, ("items", "summary"))
        if not isinstance(data.get("items"), list):
            raise AIServiceError("模型输出缺少反馈条目")
        return data

    def assessment(self, goal, discipline) -> dict:
        if self.is_demo:
            return demo.assessment(goal, discipline)
        system, user = prompts.assessment(goal, discipline)
        data = self._real_json("assessment", system, user, ("rubric", "independent_task", "variant_task"))
        return data

    def reflection(self, goal, context) -> dict:
        if self.is_demo:
            return demo.reflection(goal, context)
        system, user = prompts.reflection(goal, context)
        return self._real_json(
            "reflection", system, user,
            ("summary", "learned_capabilities", "unresolved_gaps", "next_actions"),
        )

    def suggest_proposals(self, goal, concepts, relations_hint) -> dict:
        if self.is_demo:
            return {"proposals": demo.propose(goal, concepts, relations_hint)}
        system, user = prompts.suggest_proposals(goal, concepts, relations_hint)
        return self._real_json("proposals", system, user, ("proposals",))

    def chat(self, goal, question: str, context: dict) -> dict:
        if self.is_demo:
            return {"answer": demo.chat(goal, question, context)}
        system, user = prompts.chat(goal, question, context)
        return self._real_json("chat", system, user, ("answer",))
