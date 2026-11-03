# -*- coding: utf-8 -*-
"""规范校验分派器：按 format_spec 的 scene 把内容路由到对应的 Tier-0 校验器。

为什么需要这一层（而不是在 tutorials.py 里写 if/elif）：

项目有 5 份规范、4 种 scene，每种能机械判定的东西**完全不同**：
  exam_paper / exercise → 卷面账目（题号、分值、答案集合）      exam_check
  reading_guide         → 摘录溯源（引文必须逐字出自材料）      quote_check
  practical_tutorial    → 步骤三要素 + 代码语法 + 命令存在性    practice_check
  default_tutorial      → 结构齐备（已由 engine.check_structure 覆盖）

这些判据没有交集：把摘录校验套到试卷上是荒谬的，把分值校验套到导读上同样荒谬。
所以分派必须**以 scene 为唯一依据**，而不是靠正文特征猜——scene 是结构契约的一部分
（见 format_specs.is_reading_guide 的同款理由：用户可以改规范名，但 scene 不能改）。

三条设计约束：
1. **只判定，不改写**：quote_check / practice_check 全部 auto_fixable=False（虚构引文
   没有唯一正确的机械修法），所以本层不产出「修复后的内容」，只产出违规清单。
   这与 exam_check 会就地改写正文不同，调用方不要期望 content 被修改。
2. **passed 只看 blocking**：advisory 级（排版、记法风格）不该把整份教程标成
   「待改进」，否则 Q001/P002 这类真正致命的信号会被噪音淹没。
3. **缺材料就不指控**：阅读规范的 Q001 需要材料原文做基准，拿不到材料时跳过
   而不是报「全部引文都虚构」——那会产生一整片假阳性。
"""
from __future__ import annotations

import logging
from typing import Any

from . import exam_check as exam_check_service
from . import format_specs as format_specs_service
from . import practice_check as practice_check_service
from . import quote_check as quote_check_service

logger = logging.getLogger("aiedu")

# scene → 用哪个校验器。default_tutorial 不在此表：它的结构齐备性已由
# engine.check_structure 覆盖（大纲/章节齐备、验收映射、双向覆盖、内容块合法）。
SCENE_CHECKER = {
    "exam_paper": "exam",
    "exercise": "exam",
    "reading_guide": "quote",
    "practical_tutorial": "practice",
}


def checker_for_scene(format_spec: dict | None) -> str | None:
    """按 scene 决定用哪个校验器；None 表示本 scene 无 Tier-0 专项校验。"""
    scene = str((format_spec or {}).get("scene", "") or "").strip()
    return SCENE_CHECKER.get(scene)


def check_sections(
    content: dict,
    *,
    materials_by_section: dict[str, str] | None = None,
    domain_key: str = "",
) -> dict[str, Any]:
    """对整份内容的各章节跑 scene 对应的 Tier-0 校验，返回可并入 quality_report 的汇总。

    ``materials_by_section``：节标题 → 该节注入的材料原文。只有阅读规范需要
    （Q001 逐字比对要有基准）；其它 scene 忽略此参数。缺某节的材料时该节跳过 Q001，
    不报假阳性。

    返回 {"kind": str, "passed": bool, "sections": [...], "blocking": int, "advisory": int}。
    ``kind`` 为 None 时表示本次内容不适用任何专项校验（讲解型教程）。
    """
    format_spec = content.get("format_spec") or {}
    kind = checker_for_scene(format_spec)
    result: dict[str, Any] = {
        "kind": kind, "passed": True, "sections": [], "blocking": 0, "advisory": 0,
    }
    if kind is None:
        return result
    # exam_paper / exercise 已由 exam_check 在 run_exam_quality 里校验过（它会改写正文），
    # spec_check 不插手：返回 kind=None，让调用方的 `if spec_summary.get("kind")` 直接跳过，
    # 否则会把空的 spec_check 结果写进 quality_report，并被 quality_checks 误判成实践校验。
    if kind == "exam":
        result["kind"] = None
        return result

    materials_by_section = materials_by_section or {}
    for section in content.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "") or "")
        body = exam_check_service.section_body(section)
        if not body.strip():
            continue
        try:
            if kind == "quote":
                # 拿不到材料基准时 check_quotes 内部会跳过 Q001/Q003（不指控）
                violations = quote_check_service.check_quotes(
                    body, materials_by_section.get(title, "")
                )
                summary = quote_check_service.summarize(violations)
            else:  # practice
                violations = practice_check_service.check_practice_section(
                    section, domain_key=domain_key
                )
                summary = practice_check_service.summarize(violations)
        except Exception as exc:  # noqa: BLE001  校验失败不阻断交付
            logger.warning("规范校验失败（%s）：%s", title, exc)
            result["sections"].append({"title": title, "error": str(exc)[:120]})
            continue
        result["sections"].append({
            "title": title,
            "passed": summary["passed"],
            "blocking": summary["blocking"],
            "advisory": summary["advisory"],
            "codes": summary["codes"],
            "violations": summary["violations"],
        })
        result["blocking"] += summary["blocking"]
        result["advisory"] += summary["advisory"]
        if not summary["passed"]:
            result["passed"] = False
    return result


def quality_checks(spec_summary: dict) -> list[dict[str, Any]]:
    """转成 quality_report["checks"] 条目（与 exam_check.quality_checks 同构）。"""
    kind = (spec_summary or {}).get("kind")
    if kind == "quote":
        name = "原文摘录溯源校验"
    elif kind == "practice":
        name = "实践步骤与代码校验"
    else:
        # kind 为 None / exam / 未知值：spec_check 不产出检查项（exam 归 exam_check）
        return []
    checked = [s for s in (spec_summary.get("sections") or []) if "passed" in s]
    return [{
        "name": name,
        "passed": bool(spec_summary.get("passed", True)),
        "detail": (
            f"校验 {len(checked)} 节；阻塞项 {spec_summary.get('blocking', 0)} 条，"
            f"提示项 {spec_summary.get('advisory', 0)} 条"
        ) if checked else "无可校验章节，跳过",
    }]


def quality_issues(spec_summary: dict, *, limit: int = 8) -> list[str]:
    """只返回 blocking 级违规为 issues（驱动 drafted_with_issues 与前端「待改进」）。"""
    out: list[str] = []
    for section in (spec_summary or {}).get("sections") or []:
        title = section.get("title", "") or "（未命名）"
        for v in section.get("violations") or []:
            if v.get("severity") != "blocking" or v.get("fixed"):
                continue
            out.append(f"[{v.get('code', '')}] {title}：{str(v.get('detail', ''))[:120]}")
            if len(out) >= limit:
                return out
    return out


def is_reading_content(format_spec: dict | None) -> bool:
    """是否阅读教程规范（需要材料基准做摘录溯源）。"""
    return format_specs_service.is_reading_guide(format_spec)
