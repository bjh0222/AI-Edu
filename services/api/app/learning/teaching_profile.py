"""长期用户画像到教学规则的轻量结构化解析。

用户画像仍然以自然语言保存；生成前只做类型归一，让提示词能区分
禁止性约束、必须性原则、默认偏好和条件性规则。
"""
from __future__ import annotations

import re

from ..model_settings import read_config


RULE_LABELS = {
    "forbidden": "禁止",
    "required": "必须",
    "default": "默认偏好",
    "conditional": "条件规则",
}


def _clean_line(line: str) -> str:
    line = line.strip()
    return re.sub(r"^(?:[-*•]|\d+[.、)]|（\d+）|\(\d+\))\s*", "", line)


def parse_teaching_profile(raw: str | None = None) -> dict:
    """把画像自述拆成可执行规则；空画像返回空规则集。"""
    if raw is None:
        raw = str(read_config().get("user_profile", ""))

    rules: list[dict] = []
    for index, source_line in enumerate(raw.splitlines(), start=1):
        text = _clean_line(source_line)
        if not text:
            continue

        conditional = bool(re.search(r"(?:如果|当|遇到|时，|时:|时：)", text))
        forbidden = bool(re.search(r"(?:不要|不能|不得|禁止|别再|别用|避免)", text))
        required = bool(re.search(r"(?:必须|务必|一定|始终|总是|先.*再|每.*都要)", text))
        if conditional and not (forbidden or required):
            rule_type = "conditional"
            hard = False
        elif forbidden:
            rule_type = "forbidden"
            hard = True
        elif required:
            rule_type = "required"
            hard = True
        else:
            rule_type = "default"
            hard = False

        rules.append(
            {
                "id": f"rule-{index:02d}",
                "text": text,
                "rule_type": rule_type,
                "hard": hard,
                "condition": text if conditional else "",
            }
        )

    return {"rules": rules, "source": "long_term_user_profile"}


def normalize_teaching_plan(value, profile_data: dict | None = None) -> dict:
    """固化本次教程生效的规则与决策；硬约束不会被模型输出静默丢弃。"""
    profile_data = profile_data or parse_teaching_profile()
    raw_plan = value if isinstance(value, dict) else {}

    def _str_list(key: str) -> list[str]:
        values = raw_plan.get(key)
        return [str(item).strip() for item in values if str(item).strip()] if isinstance(values, list) else []

    hard_rules = [rule["text"] for rule in profile_data["rules"] if rule["hard"]]
    rules_applied: list[str] = []
    for text in hard_rules + _str_list("rules_applied") + [rule["text"] for rule in profile_data["rules"]]:
        if text and text not in rules_applied:
            rules_applied.append(text)

    return {
        "rules": profile_data["rules"],
        "rules_applied": rules_applied,
        "decisions": _str_list("decisions"),
        "task_overrides": _str_list("task_overrides"),
        "unresolved_conflicts": _str_list("unresolved_conflicts"),
        "source": "long_term_user_profile",
    }
