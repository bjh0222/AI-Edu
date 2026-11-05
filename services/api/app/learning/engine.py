"""通用学习引擎：阶段机、质量分级检查（L1 结构检查）。"""
from __future__ import annotations

import re
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


_V2_STEP_RE = re.compile(r"^\s*(?:\d+[.、)]|[*-])\s+")
_V2_EXPECTED_RE = re.compile(r"预期|期望结果|应看到|结果[:：]")
_V2_VERIFY_RE = re.compile(r"验证|确认|校验|检查")


def _v2_unverifiable_steps(section: dict[str, Any]) -> list[str]:
    """粗判 v2 ``type=steps`` 块中顶层步骤是否缺「预期」与「验证」。

    这里与 practice_check 的 P001 互补：engine 用保守词法拦截明显裸步骤，
    后者的专项规则再处理实践教程的更细措辞。合并写在同一句的情况不算失败。
    """
    missing: list[str] = []
    for block in section.get("content") or []:
        if not isinstance(block, dict) or str(block.get("type", "")).lower() != "steps":
            continue
        current: list[str] = []
        number = 0
        in_fence = False

        def has_evidence(lines: list[str]) -> bool:
            text = "\n".join(lines)
            return bool(_V2_EXPECTED_RE.search(text) or _V2_VERIFY_RE.search(text))

        for raw in str(block.get("body", "") or "").splitlines():
            stripped = raw.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                if current:
                    current.append(stripped)
                continue
            if _V2_STEP_RE.match(raw) and not stripped.startswith(("-", "*")):
                if current and not has_evidence(current):
                    missing.append(str(number))
                number += 1
                current = [stripped]
                continue
            if current:
                current.append(stripped)
        if current and not has_evidence(current):
            missing.append(str(number))
    return missing


def check_structure(content: dict[str, Any], criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """L1 结构检查：知识组织与教学质量双量规分别汇总。

    兼容两种章节结构：
    - v1（旧）：explanation / steps / examples / variation_task / sources 等固定栏目；
    - v2（提示词重构后）：content 内容块 + key_takeaways / common_errors 等。
    练习、变式与来源为可选项，不再作为硬性失败条件（例题与练习按教学需要取舍）。

    ``checks[].group`` 与 ``summary`` 是新增输出；旧字段（passed/checks/issues/
    coverage）保留，避免破坏既有调用方与前端。
    """
    issues: list[str] = []
    checks: list[dict[str, Any]] = []

    outline = content.get("outline") or []
    sections = content.get("sections") or []

    def add(name: str, group: str, passed: bool, detail: str, issue: str | None = None) -> None:
        checks.append({"name": name, "group": group, "passed": bool(passed), "detail": detail})
        if not passed and issue:
            issues.append(issue)

    # 1. 大纲与章节齐备（知识组织）
    outline_ok = bool(outline) and bool(sections) and len(sections) >= len(outline)
    add(
        "大纲与章节齐备", "knowledge_quality", outline_ok,
        f"outline={len(outline)}, sections={len(sections)}",
        "大纲或章节数量不足，无法形成完整教程",
    )

    # 2. 每个章节映射到至少一条验收标准（教学质量）
    unmapped = [s.get("title", "?") for s in sections if not s.get("mapping_criteria")]
    add(
        "章节均映射验收标准", "teaching_quality", not unmapped,
        ("未映射章节: " + ", ".join(unmapped)) if unmapped else "全部章节已映射",
        f"{len(unmapped)} 个章节未映射到验收标准",
    )

    # 3. 双向覆盖：每条验收标准至少被一个章节覆盖（教学质量）
    covered = {cid for s in sections for cid in s.get("mapping_criteria", [])}
    uncovered = [c.get("statement", c.get("id", "?")) for c in criteria if c.get("id") not in covered]
    add(
        "验收标准双向覆盖", "teaching_quality", not uncovered,
        ("未覆盖: " + "; ".join(uncovered)) if uncovered else "全部验收标准已被覆盖",
        f"{len(uncovered)} 条验收标准未被任何章节覆盖",
    )

    # 4. 章节正文非空（v1: explanation；v2: content 内容块；知识组织）
    empty_sections = [
        s.get("title", "?")
        for s in sections
        if not (s.get("content") or s.get("explanation"))
    ]
    add(
        "章节正文非空", "knowledge_quality", not empty_sections,
        ("空章节: " + ", ".join(empty_sections)) if empty_sections else "全部章节均有正文",
        f"{len(empty_sections)} 个章节没有正文内容",
    )

    # 5. 内容块与操作步骤可验证（教学质量；v1/v2 都补齐）
    bad_blocks = 0
    bad_steps = 0
    total_steps = 0
    v2_missing: list[str] = []
    for s in sections:
        for block in s.get("content", []):
            if not isinstance(block, dict) or not str(block.get("body", "")).strip():
                bad_blocks += 1
            elif block.get("type") not in VALID_BLOCK_TYPES:
                bad_blocks += 1
        missing = _v2_unverifiable_steps(s)
        if missing:
            v2_missing.append(f"{s.get('title', '?')}: {', '.join(missing)}")
        for step in s.get("steps", []):  # v1 结构
            total_steps += 1
            if not (step.get("expected_result") and step.get("verification")):
                bad_steps += 1
    step_ok = bad_blocks == 0 and bad_steps == 0 and not v2_missing
    has_content = total_steps > 0 or any(s.get("content") for s in sections)
    detail = f"非法内容块 {bad_blocks} 个；v1 步骤 {total_steps} 个中 {bad_steps} 个缺预期结果/验证"
    if v2_missing:
        detail += f"；v2 裸步骤 {len(v2_missing)} 章节"
    add(
        "内容块与步骤规范", "teaching_quality", step_ok and has_content,
        detail,
        "内容块或操作步骤缺少可验证结果",
    )

    groups = ("knowledge_quality", "teaching_quality")
    summary = {}
    for group in groups:
        group_checks = [c for c in checks if c["group"] == group]
        summary[group] = {
            "passed": all(c["passed"] for c in group_checks),
            "passed_checks": sum(c["passed"] for c in group_checks),
            "total_checks": len(group_checks),
        }

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
        "summary": summary,
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
