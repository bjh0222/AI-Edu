"""长期用户画像到教学规则的结构化解析（分类 / 按阶段选择 / 可核验约束 / 交付契约）。

用户画像仍然以自然语言保存。生成前只做四件确定性的事（不调用模型、不改写原文）：

1. 分类：每行判断成 禁止 / 必须 / 条件 / 默认偏好，并计算「作用域」标签；
2. 选择：按生成阶段只挑出本阶段真正用得到的规则，避免把整份画像无差别注入；
3. 核验：对少数可机器判断的禁止性硬约束（按日历分配时间、Obsidian 标签）检查输出；
4. 交付契约：把「只包括…」这类对交付物组成的硬规定抽出来，交给教程结构强制执行。

设计取舍：
- 硬约束（禁止 / 必须）永远注入，不因阶段作用域不匹配被丢弃——约束一旦消失，
  「注入即约束」就不成立；只对默认偏好与条件规则做作用域与预算裁剪。
- 条件规则先按目标求值：条件不成立就不注入。规则的适用范围由目标决定，
  不能把「当出现输出试卷时只交付试卷」当成对每个目标都生效的通用禁令。
- 组成型约束必须落到结构上：模型会把「不要输出答案」理解成「可以写讲解」，
  所以「只包括 A/B/C」由代码直接决定章节，而不是只写进提示词。
- 选择规则用关键词作用域而非向量相似度：可解释、零成本、结果稳定可测。
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

# 作用域：命中哪些关键词，决定这条规则影响哪些生成阶段
SCOPE_PATTERNS: dict[str, str] = {
    "schedule": r"日程|时间表|日历|第\s*[一二三四五六七八九十\d]+\s*[天周]|每天|每日|每周",
    "depth": r"前置|推导|原理|推理|跳过|深入|底层|机制|基础|直觉|为什么|证明",
    "example": r"例子|示例|例题|案例|类比|举例",
    "exercise": r"练习|习题|题目|作业|自测|刷题|考核",
    "format": r"格式|模板|表格|标题|层级|标签|双链|代码块|公式|排版|Markdown|markdown",
    "tone": r"语气|口吻|口语|简洁|冗长|啰嗦|篇幅|简短|详细|细致|直白|废话",
    "language": r"中文|英文|术语|翻译|英文名|中英",
}

GENERAL_SCOPE = "general"

# 每个生成阶段只需要对应作用域的规则；None 表示不按作用域过滤
STAGE_SCOPES: dict[str, frozenset[str]] = {
    "outline": frozenset({"schedule", "depth", "language", GENERAL_SCOPE}),
    "section": frozenset({"depth", "example", "exercise", "format", "tone", "language", GENERAL_SCOPE}),
    "cheatsheet": frozenset({"format", "tone", "language", GENERAL_SCOPE}),
    "extra_exercises": frozenset({"exercise", "depth", "format", "tone", "language", GENERAL_SCOPE}),
}

# 导向类规则的注入预算（字符）。硬约束不参与预算裁剪。
DEFAULT_SOFT_BUDGET = 1200


def _clean_line(line: str) -> str:
    line = line.strip()
    return re.sub(r"^(?:[-*•]|\d+[.、)]|（\d+）|\(\d+\))\s*", "", line)


def rule_scopes(text: str) -> list[str]:
    """规则作用域标签：没有命中任何关键词时归为 general（通识教学偏好）。"""
    scopes = {name for name, pattern in SCOPE_PATTERNS.items() if re.search(pattern, text)}
    return sorted(scopes) or [GENERAL_SCOPE]


# 条件从句的判定：只认完整句式，避免「当前 / 适当」这类词被当成「当」
_CONDITIONAL_PATTERNS = (
    re.compile(r"如果|假如|倘若|若是|若"),
    re.compile(r"当[^。；\n]{0,40}?(?:的时候|时)"),
    re.compile(r"遇到|时，|时:|时："),
)


def parse_teaching_profile(raw: str | None = None, context_text: str | None = None) -> dict:
    """把画像自述拆成可执行规则；空画像返回空规则集。

    `context_text` 给出本次目标文本时，条件规则会先求值：条件不成立的规则被剔除，
    并记录在 `inactive` 里（方便排查「为什么这条规则没生效」）。
    """
    if raw is None:
        raw = str(read_config().get("user_profile", ""))

    rules: list[dict] = []
    for index, source_line in enumerate(raw.splitlines(), start=1):
        text = _clean_line(source_line)
        if not text:
            continue

        # 条件从句的判定要看完整句式：单个「当」会命中「理解当前知识」这类普通词
        conditional = any(pattern.search(text) for pattern in _CONDITIONAL_PATTERNS)
        forbidden = bool(re.search(r"(?:不要|不能|不得|禁止|别再|别用|避免)", text))
        # 只认显式的情态表达。「先…再…」「尽量…」这类顺序与风格偏好属于导向，
        # 若判成硬约束，会把「违反即不合格」的清单稀释成噪声。
        required = bool(re.search(r"(?:必须|务必|一定要|始终|总是|只能|每.*都要)", text))
        # 条件从句优先：带「当…的时候」的规则是一条「条件满足才生效」的规则，
        # 它的强度由条件里的情态词决定（务必/不要 → 硬），不能被拆成无条件的硬约束。
        # 否则「当出现输出试卷时只交付试卷」会变成对每个目标都生效的通用禁令。
        if conditional:
            rule_type = "conditional"
            hard = bool(forbidden or required)
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
                "scopes": rule_scopes(text),
            }
        )

    inactive: list[str] = []
    if context_text is not None:
        active_rules = []
        for rule in rules:
            if rule_is_active(rule, context_text):
                active_rules.append(rule)
            else:
                inactive.append(rule["text"])
        rules = active_rules

    return {"rules": rules, "inactive": inactive, "source": "long_term_user_profile"}


# 「学完想能做什么」等字段名只用于指明「看哪个字段」，本身不是触发词
FIELD_LABELS = frozenset(
    {
        "学完想能做什么",
        "学习目标",
        "目标",
        "应用场景",
        "动机",
        "当前基础",
        "可投入时间",
        "具体学习目标",
    }
)

_QUOTED = re.compile(r"[“”\"「」『』]([^“”\"「」『』]{1,20})[“”\"「」『』]")
_OBLIQUE_TRIGGER = re.compile(r"(?:出现|包含|含有|带|是)\s*([^，。；、\s“”\"「」『』]{2,20})")
# 匹配前抹掉标点与虚词，容忍「输出去试卷」「输出的试卷」这类插入
_MATCH_NOISE = re.compile(r"[\s，。、；：,.;:的了我你您请帮给下一]")


def goal_context_text(goal) -> str:
    """把目标里「学完想能做什么」等字段拼成一段文本，供条件规则匹配。"""
    if goal is None:
        return ""
    parts: list[str] = []
    for name in (
        "title",
        "motivation",
        "application_context",
        "current_level",
        "time_budget",
        "user_notes",
    ):
        value = getattr(goal, name, "")
        if value:
            parts.append(str(value))
    return "\n".join(parts)


def task_requirement_text(goal) -> str:
    """本次任务文本：目标上下文 + 用户填写的「硬性约束」。

    硬性约束是用户对本次交付结构最直接的表述（例如「为每一个章节生成一套检测卷」），
    规范快照的模式判定与任务覆盖项必须看到它；否则交付结构只能交给模型猜，
    用户重复生成多少次都得不到按章拆分的结果。
    """
    if goal is None:
        return ""
    parts = [goal_context_text(goal)]
    hard = str(getattr(goal, "hard_constraints", "") or "").strip()
    if hard:
        parts.append(hard)
    return "\n".join(part for part in parts if part.strip())


def _match_form(text: str) -> str:
    return _MATCH_NOISE.sub("", str(text or "")).lower()


def condition_triggers(rule: dict) -> list[str]:
    """从条件从句里抽触发词：优先引号内词（排除字段名），其次「出现 X」里的 X。"""
    condition = str(rule.get("condition") or "")
    if not condition:
        return []
    quoted = [item.strip() for item in _QUOTED.findall(condition)]
    triggers = [item for item in quoted if item and item not in FIELD_LABELS]
    if triggers:
        return triggers
    oblique = _OBLIQUE_TRIGGER.search(condition)
    return [oblique.group(1).strip()] if oblique else []


def rule_is_active(rule: dict, context_text: str) -> bool:
    """条件规则是否对本次目标生效。

    条件里抽不出可判定的触发词时按「生效」处理：宁可多给一条约束，也不静默丢约束。
    """
    if not rule.get("condition"):
        return True
    triggers = condition_triggers(rule)
    if not triggers:
        return True
    haystack = _match_form(context_text)
    return any(_match_form(trigger) and _match_form(trigger) in haystack for trigger in triggers)


_EXCLUSIVE = re.compile(r"只(?:包括|包含|输出|保留|交付)")
_EXCLUSIVE_TAIL = re.compile(r"[，,；;]?\s*(?:不要|不得|禁止|不含|不输出|不附|且不)")
_ANSWERS_BAN = re.compile(r"(?:不要|不得|禁止|不|别)[^。；\n]{0,12}答案")
_ITEM_SPLIT = re.compile(r"[、，,]|以及|和|与|及")


def delivery_contract(rules: list[dict], context_text: str = "") -> dict | None:
    """从生效的硬性约束里取出「交付契约」：这次允许交付哪几项、是否禁用答案。

    只认「只包括 / 只输出 …」这种穷举式写法：它是对交付物组成的硬性规定，
    与「讲得好不好」的导向无关，所以必须影响教程结构，而不只是提示词里的一句话。
    """
    for rule in rules or []:
        if not rule.get("hard") or not rule_is_active(rule, context_text):
            continue
        text = str(rule.get("text", ""))
        match = _EXCLUSIVE.search(text)
        if not match:
            continue
        tail = _EXCLUSIVE_TAIL.split(text[match.end():])[0]
        items = [item.strip(" ，,。；;、") for item in _ITEM_SPLIT.split(tail)]
        items = [item for item in items if len(item) >= 2]
        if not items:
            continue
        return {
            "items": items,
            "forbid_answers": bool(_ANSWERS_BAN.search(text)),
            "exclusive": True,
            # 「只包括…不要其它内容」把配套文件也排除在外
            "suppress_companions": True,
            "rule": text,
        }
    return None


def delivery_contract_for(goal) -> dict | None:
    """当前目标应遵守的交付契约；没有穷举式约束时返回 None。"""
    context = goal_context_text(goal)
    profile = parse_teaching_profile(context_text=context)
    return delivery_contract(profile["rules"], context)


def select_rules(rules: list[dict], stage: str, *, budget_chars: int = DEFAULT_SOFT_BUDGET) -> dict:
    """按阶段挑选规则：硬约束全保留，导向类只保留与本阶段相关且不超预算的部分。

    返回 {"rules": [...], "hard_count": int, "soft_count": int, "dropped": [str]}
    便于测试与排查「为什么这条规则没出现在提示词里」。
    """
    stage_scopes = STAGE_SCOPES.get(stage)
    hard: list[dict] = []
    soft: list[dict] = []
    dropped: list[str] = []

    for rule in rules:
        scopes = set(rule.get("scopes") or rule_scopes(str(rule.get("text", ""))))
        relevant = stage_scopes is None or bool(scopes & stage_scopes)
        if rule.get("hard"):
            # 硬约束与阶段无关也必须保留，否则约束会被静默丢出提示词。
            hard.append(rule)
        elif relevant:
            soft.append(rule)
        else:
            dropped.append(str(rule.get("text", "")))

    used = 0
    kept_soft: list[dict] = []
    for rule in soft:
        cost = len(str(rule.get("text", "")))
        if used + cost > budget_chars:
            dropped.append(str(rule.get("text", "")))
            continue
        used += cost
        kept_soft.append(rule)

    return {
        "rules": hard + kept_soft,
        "hard_count": len(hard),
        "soft_count": len(kept_soft),
        "dropped": dropped,
    }


# 可机器核验的禁止性约束：规则文本命中 match，且输出命中 pattern 即视为违规。
COMPLIANCE_GUARDS: tuple[dict, ...] = (
    {
        "match": re.compile(r"日程|时间表|日历|第\s*[一二三四五六七八九十\d]+\s*[天周]|每天|每日|每周"),
        "pattern": re.compile(
            r"(?:第\s*[一二三四五六七八九十\d]+\s*[天周])|每天|每日"
            r"|每周[一二三四五六日天\d]?\s*(?:投入|安排|学习|复习|完成)"
        ),
        "reason": "出现按日历 / 天次分配时间的表述",
    },
    {
        "match": re.compile(r"标签|tag|Tag"),
        "pattern": re.compile(r"(?<![\w#`])#[\w\u4e00-\u9fff][\w\u4e00-\u9fff/-]*"),
        "reason": "出现会生效的 Obsidian 标签",
    },
)


def check_rule_compliance(text: str, rules: list[dict]) -> list[dict]:
    """核对禁止性硬约束是否被输出违反；只做能确定性判断的少数项。

    返回 [{"rule": 规则原文, "reason": 违规说明}]；无违规返回 []。
    """
    content = text or ""
    if not content.strip():
        return []

    violations: list[dict] = []
    for rule in rules or []:
        if not rule.get("hard") or rule.get("rule_type") != "forbidden":
            continue
        rule_text = str(rule.get("text", ""))
        if not rule_text:
            continue
        for guard in COMPLIANCE_GUARDS:
            if guard["match"].search(rule_text) and guard["pattern"].search(content):
                violations.append({"rule": rule_text, "reason": guard["reason"]})
                break
    return violations


def normalize_teaching_plan(value, profile_data: dict | None = None) -> dict:
    """固化本次教程生效的规则与决策；硬约束不会被模型输出静默丢弃。

    rules_applied 只记录「本次实际采用的规则」= 硬约束 + 模型自报采用的规则。
    不再把全部画像规则回填进来：那样会让去重后的教学决策失去收敛作用
    （章节阶段同时注入宪章与教学决策时，同一批规则会出现两遍）。
    """
    profile_data = profile_data or parse_teaching_profile()
    raw_plan = value if isinstance(value, dict) else {}

    def _str_list(key: str) -> list[str]:
        values = raw_plan.get(key)
        return [str(item).strip() for item in values if str(item).strip()] if isinstance(values, list) else []

    hard_rules = [rule["text"] for rule in profile_data["rules"] if rule["hard"]]
    rules_applied: list[str] = []
    for text in hard_rules + _str_list("rules_applied"):
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
