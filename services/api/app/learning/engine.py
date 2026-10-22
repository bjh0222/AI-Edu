"""通用学习引擎：阶段机、质量分级检查（L1 结构检查）。"""
from __future__ import annotations

from typing import Any

PHASES = [
    "goal_definition",
    "diagnosis",
    "planning",
    "acceptance_design",
    "learning",
]

PHASE_LABELS = {
    "goal_definition": "目标定义",
    "diagnosis": "诊断与价值分析",
    "planning": "学习计划",
    "acceptance_design": "验收标准",
    "learning": "教程学习",
}

HELP_LEVELS = {"A0": "引导", "A1": "协作", "A2": "提示", "A3": "独立验证"}


def next_phase(current: str) -> str:
    try:
        idx = PHASES.index(current)
    except ValueError:
        return "goal_definition"
    return PHASES[min(idx + 1, len(PHASES) - 1)]


VALID_BLOCK_TYPES = {
    "text", "key_point", "formula", "steps", "table", "example",
    "comparison", "method_summary", "diagram", "memory", "note",
}


def check_structure(content: dict[str, Any], criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """L1 结构检查：必需字段、正文齐备、验收映射、双向覆盖。

    兼容两种章节结构：
    - v1（旧）：explanation / steps / examples / variation_task / sources 等固定栏目；
    - v2（提示词重构后）：content 内容块 + key_takeaways / common_errors 等。
    练习、变式与来源为可选项，不再作为硬性失败条件（例题与练习按教学需要取舍）。
    """
    issues: list[str] = []
    checks: list[dict[str, Any]] = []

    outline = content.get("outline") or []
    sections = content.get("sections") or []

    # 1. 大纲与章节齐备
    checks.append({
        "name": "大纲与章节齐备",
        "passed": bool(outline) and bool(sections) and len(sections) >= len(outline),
        "detail": f"outline={len(outline)}, sections={len(sections)}",
    })
    if not checks[-1]["passed"]:
        issues.append("大纲或章节数量不足，无法形成完整教程")

    # 2. 每个章节映射到至少一条验收标准
    unmapped = [s.get("title", "?") for s in sections if not s.get("mapping_criteria")]
    checks.append({
        "name": "章节均映射验收标准",
        "passed": not unmapped,
        "detail": ("未映射章节: " + ", ".join(unmapped)) if unmapped else "全部章节已映射",
    })
    if unmapped:
        issues.append(f"{len(unmapped)} 个章节未映射到验收标准")

    # 3. 双向覆盖：每条验收标准至少被一个章节覆盖
    covered = {cid for s in sections for cid in s.get("mapping_criteria", [])}
    uncovered = [c.get("statement", c.get("id", "?")) for c in criteria if c.get("id") not in covered]
    checks.append({
        "name": "验收标准双向覆盖",
        "passed": not uncovered,
        "detail": ("未覆盖: " + "; ".join(uncovered)) if uncovered else "全部验收标准已被覆盖",
    })
    if uncovered:
        issues.append(f"{len(uncovered)} 条验收标准未被任何章节覆盖")

    # 4. 章节正文非空（v1: explanation；v2: content 内容块）
    empty_sections = [
        s.get("title", "?")
        for s in sections
        if not (s.get("content") or s.get("explanation"))
    ]
    checks.append({
        "name": "章节正文非空",
        "passed": not empty_sections,
        "detail": ("空章节: " + ", ".join(empty_sections)) if empty_sections else "全部章节均有正文",
    })
    if empty_sections:
        issues.append(f"{len(empty_sections)} 个章节没有正文内容")

    # 5. 内容块与操作步骤可验证
    bad_blocks = 0
    bad_steps = 0
    total_steps = 0
    for s in sections:
        for block in s.get("content", []):
            if not isinstance(block, dict) or not str(block.get("body", "")).strip():
                bad_blocks += 1
            elif block.get("type") not in VALID_BLOCK_TYPES:
                bad_blocks += 1
        for step in s.get("steps", []):  # v1 结构
            total_steps += 1
            if not (step.get("expected_result") and step.get("verification")):
                bad_steps += 1
    step_ok = bad_blocks == 0 and bad_steps == 0
    checks.append({
        "name": "内容块与步骤规范",
        "passed": step_ok and (total_steps > 0 or any(s.get("content") for s in sections)),
        "detail": (
            f"非法内容块 {bad_blocks} 个；v1 步骤 {total_steps} 个中 {bad_steps} 个缺预期结果/验证"
        ),
    })
    if bad_blocks:
        issues.append(f"{bad_blocks} 个内容块类型非法或正文为空")
    if bad_steps:
        issues.append(f"{bad_steps} 个步骤缺少预期结果或验证方式")

    passed = all(c["passed"] for c in checks)
    return {
        "passed": passed,
        "checks": checks,
        "issues": issues,
        "coverage": {
            "criteria_total": len(criteria),
            "criteria_covered": len([c for c in criteria if c.get("id") in covered]),
            "sections": len(sections),
        },
    }


def check_criterion_writing(statement: str, pass_rule: str) -> list[str]:
    """验收标准写法检查（v2.0 §2.1.4：动作、对象、条件、证据、通过条件）。"""
    problems: list[str] = []
    banned = ["理解", "掌握", "熟悉", "了解", "学会"]
    for word in banned:
        if word in statement:
            problems.append(f"包含不可观察动词「{word}」，请改为可观察行为")
    observable = ["能够", "创建", "拆分", "定位", "运行", "解释", "说明", "修复", "比较", "完成", "推导", "分析"]
    if not any(w in statement for w in observable):
        problems.append("主句建议以「能够 + 可观察动词」开头")
    if not pass_rule.strip():
        problems.append("缺少通过条件（怎样算通过）")
    return problems
