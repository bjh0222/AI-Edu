"""通用学习引擎：阶段机、质量分级检查（L1 结构检查）。"""
from __future__ import annotations

from typing import Any

PHASES = [
    "goal_definition",
    "diagnosis",
    "planning",
    "acceptance_design",
    "learning",
    "practice",
    "feedback",
    "assessment",
    "reflection",
    "knowledge_update",
]

PHASE_LABELS = {
    "goal_definition": "目标定义",
    "diagnosis": "诊断与价值分析",
    "planning": "学习计划",
    "acceptance_design": "验收标准",
    "learning": "教程学习",
    "practice": "实践",
    "feedback": "反馈",
    "assessment": "能力评估",
    "reflection": "复盘",
    "knowledge_update": "知识记录",
}

HELP_LEVELS = {"A0": "引导", "A1": "协作", "A2": "提示", "A3": "独立验证"}


def next_phase(current: str) -> str:
    try:
        idx = PHASES.index(current)
    except ValueError:
        return "goal_definition"
    return PHASES[min(idx + 1, len(PHASES) - 1)]


def check_structure(content: dict[str, Any], criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """L1 结构检查：必需字段、预期结果、验收映射、双向覆盖、练习与变式。"""
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

    # 4. 每个操作步骤有预期结果与验证方式
    bad_steps = 0
    total_steps = 0
    for s in sections:
        for step in s.get("steps", []):
            total_steps += 1
            if not (step.get("expected_result") and step.get("verification")):
                bad_steps += 1
    checks.append({
        "name": "步骤含预期结果与验证",
        "passed": bad_steps == 0 and total_steps > 0,
        "detail": f"{total_steps} 个步骤中 {bad_steps} 个缺预期结果/验证",
    })
    if bad_steps:
        issues.append(f"{bad_steps} 个步骤缺少预期结果或验证方式")

    # 5. 练习与变式任务
    practice_ok = all(bool(s.get("exercises")) and bool(s.get("variation_task")) for s in sections)
    checks.append({
        "name": "练习与变式任务齐备",
        "passed": practice_ok,
        "detail": "每个章节须含练习与变式任务",
    })
    if not practice_ok:
        issues.append("部分章节缺少练习或变式任务")

    # 6. 来源与不确定性说明
    source_ok = all(bool(s.get("sources")) for s in sections)
    checks.append({
        "name": "关键内容有来源或不确定性标注",
        "passed": source_ok,
        "detail": "每个章节须列出至少一条来源或标注不确定性",
    })
    if not source_ok:
        issues.append("部分章节缺少来源或不确定性说明")

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
