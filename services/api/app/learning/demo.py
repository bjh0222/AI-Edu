"""演示生成器：未配置模型时的确定性结构化内容。

原则（v2.0 §7.1）：演示数据与真实输出 schema 一致、绝不伪装为真实模型结果；
反馈与评估类内容明确标注「演示模式仅做结构检查」。
"""
from __future__ import annotations

from .disciplines import DisciplineProfile


def _goal_title(goal) -> str:
    return getattr(goal, "title", "当前目标")


def diagnose(goal, discipline: DisciplineProfile) -> dict:
    title = _goal_title(goal)
    app = getattr(goal, "application_context", "") or "完成一个真实可交付的小任务"
    level = getattr(goal, "current_level", "") or "入门"
    return {
        "benefits": (
            f"1. 「{title}」直接服务于你的应用场景：{app}；\n"
            f"2. 掌握后可迁移到同类任务，减少重复求助；\n"
            f"3. 学习过程本身形成可复用的验收与复盘方法。"
        ),
        "prerequisites": (
            f"按「{discipline.display_name}」的常见路径，建议先确认基础概念与工具环境可用；"
            "若已有入门基础，可压缩第一段学习。"
        ),
        "alternatives": (
            "1. 使用现成课程/文档按目录学习（覆盖面广但缺少针对你目标的裁剪）；\n"
            "2. 直接向通用 AI 提问（即时但缺少验收与持续性）；\n"
            "3. 本方案：以目标为起点、以验收标准与真实实践为主线的闭环学习。"
        ),
        "assumptions": (
            f"假设你的当前水平为「{level}」，可投入时间见目标设定；"
            "若实际基础差异较大，计划与教程需要相应调整。"
        ),
        "uncertainties": (
            "尚未确认：目标的最小交付物边界、可投入时间的稳定性、"
            "以及是否需要前置工具环境（这些将在诊断与计划阶段确认）。"
        ),
        "recommendation": (
            "建议推进，但先把范围收窄到「能完成一个最小可运行任务」，"
            "再按验收标准逐步扩展；不建议一开始覆盖完整领域。"
        ),
    }


def plan(goal, discipline: DisciplineProfile) -> dict:
    title = _goal_title(goal)
    return {
        "steps": [
            {
                "title": "明确目标边界与环境准备",
                "objective": f"写下「{title}」的最小交付物定义，并确认工具/环境可用。",
                "estimated_effort": "30–60 分钟",
            },
            {
                "title": "建立领域地图与先修关系",
                "objective": "列出必学、后学、暂时跳过的分支，标出先修依赖。",
                "estimated_effort": "40–60 分钟",
            },
            {
                "title": "核心概念与最小示例",
                "objective": f"理解「{discipline.display_name}」中与目标直接相关的核心概念与边界。",
                "estimated_effort": "1–2 小时",
            },
            {
                "title": "完成第一个真实任务",
                "objective": "按验收标准执行实践任务，记录产物、错误与证据。",
                "estimated_effort": "1–2 小时",
            },
            {
                "title": "变式任务与迁移检验",
                "objective": "在未直接演示过的情境中完成变式任务，解释可迁移的规律。",
                "estimated_effort": "1 小时",
            },
            {
                "title": "复盘与下一步计划",
                "objective": "整理能力证据、薄弱点与后续学习顺序。",
                "estimated_effort": "30 分钟",
            },
        ]
    }


def criteria(goal, discipline: DisciplineProfile) -> list[dict]:
    title = _goal_title(goal)
    return [
        {
            "statement": f"能够用自己的话解释「{title}」涉及的核心概念及其适用边界",
            "conditions": "不照读教程原文；能举出一个边界情况或反例",
            "evidence_type": "explanation",
            "pass_rule": "能连续复述机制并给出一个正确边界示例/反例",
            "rationale": "解释能力是后续应用与迁移的前提",
        },
        {
            "statement": f"能够在给定约束下完成「{title}」的一个最小可运行任务并提交产物",
            "conditions": "使用教程给出的工具/环境；独立完成关键步骤",
            "evidence_type": "product",
            "pass_rule": "产物存在且按验证方式检查通过（如可运行、可复算、可演示）",
            "rationale": "产物是掌握程度的主要证据",
        },
        {
            "statement": "能够复现并定位一个常见错误，说明原因并验证修复",
            "conditions": "从错误信息/现象出发，给出最小验证动作",
            "evidence_type": "debug_log",
            "pass_rule": "记录复现步骤、原因判断与修复后的验证结果",
            "rationale": "错误诊断能力直接对应独立解决问题的目标",
        },
        {
            "statement": "能够独立完成一个与教程示例不同的变式任务",
            "conditions": "不能照抄教程步骤；允许少量提示但需记录",
            "evidence_type": "transfer",
            "pass_rule": "变式任务成功完成，且能解释哪条规律起了作用",
            "rationale": "迁移是真正理解的标志",
        },
    ]


def outline(goal, discipline: DisciplineProfile, criterion_ids: list[str]) -> list[dict]:
    title = _goal_title(goal)
    c = (criterion_ids + ["", "", "", ""])[:4]
    return [
        {
            "title": "准备与核心概念",
            "summary": f"明确「{title}」的范围，建立必要概念与工具环境。",
            "criteria_ids": [x for x in [c[0]] if x],
        },
        {
            "title": "最小可运行任务（分步）",
            "summary": "按步骤完成第一个真实任务，每一步都有预期结果与验证方式。",
            "criteria_ids": [x for x in [c[1]] if x],
        },
        {
            "title": "常见错误与排查",
            "summary": "复现典型错误、定位原因并验证修复。",
            "criteria_ids": [x for x in [c[2]] if x],
        },
        {
            "title": "练习、变式任务与复盘",
            "summary": "完成练习与变式任务，检查迁移能力并复盘。",
            "criteria_ids": [x for x in [c[3], c[1]] if x],
        },
    ]


def section(goal, discipline: DisciplineProfile, item: dict, criteria_by_id: dict) -> dict:
    title = item.get("title", "")
    summary = item.get("summary", "")
    cids = item.get("criteria_ids", [])
    crit_text = "；".join(criteria_by_id.get(cid, {}).get("statement", "（验收标准）") for cid in cids) or "本章目标"
    is_cli = discipline.key == "computer_cli"

    explanation = [
        {
            "heading": "这一节在解决什么问题",
            "body": f"{summary}\n本章对应的验收标准：{crit_text}。",
        },
        {
            "heading": "核心概念与边界",
            "body": (
                ("以命令行为例：一个命令由「程序名 + 参数 + 输入/输出」组成；理解每一步的输入与输出，"
                 "比记住具体写法更重要。注意区分「演示环境」与「你的环境」的差异（版本、权限、路径）。")
                if is_cli else
                ("以数据分析为例：一个方法由「定义 + 前提假设 + 计算过程 + 结论解释」组成；"
                 "使用前先检查假设是否满足，结论要说明适用范围，避免把相关当因果。")
            ),
        },
    ]

    steps = [
        {
            "text": "第 1 步：确认前提条件（环境/数据/基础）。",
            "expected_result": "能看到与教程一致的版本信息或环境状态。",
            "verification": "运行版本检查命令（或核对数据字段），与教程描述比对。",
        },
        {
            "text": "第 2 步：执行本章核心操作的最小示例。",
            "expected_result": "得到与预期一致的输出/结果。",
            "verification": "按教程给出的验证方式逐项检查；把实际输出与预期输出对照。",
        },
        {
            "text": "第 3 步：把示例改造成你自己的任务版本。",
            "expected_result": "产物可运行/可复算，且与示例有明确差异。",
            "verification": "重新执行验证；记录差异点与原因。",
        },
    ]

    examples = [
        f"示例：{summary}（演示模式生成的示例框架；配置真实模型后内容会针对「{_goal_title(goal)}」细化）",
    ]
    exercises = [
        "练习 1：按本章步骤复现最小示例，并把实际输出与预期对照。",
        "练习 2：故意制造一个错误，按排查方法定位并修复。",
        f"练习 3：把本章方法应用到你自己的场景：{getattr(goal, 'application_context', '你的真实任务')}。",
    ]
    variation = (
        "变式任务：在不看本章步骤的情况下，完成一个结构相似但内容不同的任务（例如换一个目录/数据集），"
        "完成后解释你依据了哪条规律。"
    )
    common_errors = [
        {"error": e, "cause": "常见原因见学科清单", "diagnose": "按「复现 → 定位 → 最小验证」三步排查"}
        for e in discipline.common_errors[:3]
    ]
    sources = [
        {
            "title": "演示模式生成内容",
            "url": "",
            "note": "本教程由演示生成器产生，关键事实与命令需人工核验；配置真实模型后可获得针对性内容与来源。",
        }
    ]

    return {
        "title": title,
        "goal_statement": f"完成本章后，你应能：{crit_text}",
        "prerequisites": ["完成上一章内容", "工具/环境可用"],
        "explanation": explanation,
        "steps": steps,
        "examples": examples,
        "exercises": exercises,
        "variation_task": variation,
        "common_errors": common_errors,
        "sources": sources,
        "mapping_criteria": cids,
    }


def feedback(goal, discipline: DisciplineProfile, task, attempt, criteria: list[dict]) -> dict:
    art_len = len(attempt.artifact or "")
    items = []
    for c in criteria:
        items.append({
            "criterion_id": c.get("id", ""),
            "statement": c.get("statement", ""),
            "status": "unclear",
            "evidence": f"收到产物：{art_len} 字符（辅助等级 {attempt.help_level}，帮助程度 {attempt.help_level}）",
            "reason": "演示模式仅做结构检查，未对产物做语义核验。",
            "next_action": "配置真实模型后可获得逐项评价；当前请按该条验收标准自评并记录依据。",
        })
    return {
        "items": items,
        "summary": "已收到你的尝试并记录为证据。演示模式下无法评价内容质量。",
        "weak_points": "未评估（演示模式）",
        "demo": True,
    }


def assessment(goal, discipline: DisciplineProfile) -> dict:
    title = _goal_title(goal)
    is_cli = discipline.key == "computer_cli"
    return {
        "rubric": [
            {"dimension": d, "weight": round(1 / len(discipline.assessment_rubrics), 2), "note": ""}
            for d in discipline.assessment_rubrics
        ],
        "independent_task": {
            "title": f"独立任务：完成「{title}」的一个真实小任务",
            "description": (
                "在仅有目标说明、没有教程步骤的情况下完成一个最小任务，并提交产物。"
                if is_cli else
                "在仅有目标说明、没有推导步骤的情况下完成一次分析或推导，并提交产物。"
            ),
            "expected_artifact": "产物 + 你的解释（为什么这样做）",
        },
        "variant_task": {
            "title": "变式任务：迁移到新情境",
            "description": "把已学方法应用到一个教程未覆盖的情境，完成后解释所依据的规律。",
        },
        "evidence_hint": "记录辅助等级、提示次数、是否独立完成，作为评估依据。",
        "demo": True,
    }


def reflection(goal, context: dict) -> dict:
    title = _goal_title(goal)
    attempts = context.get("attempt_count", 0)
    tasks_done = context.get("tasks_done", 0)
    return {
        "summary": (
            f"本轮围绕「{title}」完成了 {tasks_done} 个实践任务、提交 {attempts} 次尝试。"
            "核心证据来自任务产物与你的解释；演示模式下能力判断由你确认。"
        ),
        "learned_capabilities": "已形成部分概念理解与操作经验，具体证据见实践记录。",
        "unresolved_gaps": "演示模式无法判断语义薄弱点，请结合验收标准自评。",
        "next_actions": "1. 对照验收标准逐条确认；2. 完成变式任务；3. 把本次概念与关系加入知识记录（待你确认）。",
        "candidate_concepts": [],
    }


def propose(goal, concepts: list, attempts: list) -> list[dict]:
    title = _goal_title(goal)
    return [
        {
            "proposal_type": "concept",
            "payload": {
                "title": f"{title} 的最小可运行任务",
                "definition": "用最小产物验证理解的实践单元：可运行、可验证、可解释。",
                "domain_key": getattr(goal, "domain_key", "computer_cli"),
            },
            "rationale": "来自本轮实践任务的证据类型（产物 + 解释）。演示提议，待你确认。",
        },
        {
            "proposal_type": "relation",
            "payload": {
                "from_title": "验收标准",
                "to_title": "教程范围",
                "relation_type": "prerequisite_of",
            },
            "rationale": "先定义学会的证据，再决定教程讲什么；原型与迁移实验都支持这一顺序。演示提议，待你确认。",
        },
    ]


def chat(goal, question: str, context: dict) -> str:
    title = _goal_title(goal)
    section = context.get("section_title", "")
    where = f"当前章节「{section}」" if section else "你的当前目标"
    return (
        f"[演示模式] 关于「{question}」：根据{where}「{title}」，建议先定位问题所在（复现/前提条件），"
        "再给出一个最小验证动作，而不是直接重写全部内容。配置真实模型后，这里会基于你的教程上下文给出针对性答疑。"
    )
