"""演示生成器：未配置模型时的确定性结构化内容。

原则（v2.0 §7.1）：演示数据与真实输出 schema 一致、绝不伪装为真实模型结果；
反馈与评估类内容明确标注「演示模式仅做结构检查」。
"""
from __future__ import annotations

from .disciplines import DisciplineProfile


def _goal_title(goal) -> str:
    return getattr(goal, "title", "当前目标")


def _is_cli(discipline: DisciplineProfile) -> bool:
    """计算机类学科（含新目录 cs_it 与旧 key computer_cli）走命令行示例分支。"""
    return discipline.key in ("computer_cli", "cs_it")


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
    level = str(getattr(goal, "capability_level", "") or "L2").upper()
    base = [
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
    if level == "L1":
        # L1 不要求迁移；保留概念解释、最小任务与错误识别，并显式放宽范围
        kept = base[:3]
        kept[0]["rationale"] += "（L1：以解释与识别为主）"
        kept[1]["conditions"] = "允许对照教程步骤完成；关键输出需自验"
        return kept
    if level == "L3":
        base[3]["conditions"] = "换一个教程未覆盖的情境；不允许提示；需解释关键决策依据"
        base[3]["pass_rule"] = "变式任务成功完成，能解释依据的规律，并说明方法的适用条件与局限"
        base[3]["rationale"] += "（L3：以迁移与决策论证为主）"
        return base
    return base


def outline(goal, discipline: DisciplineProfile, criterion_ids: list[str]) -> list[dict]:
    title = _goal_title(goal)
    c = (criterion_ids + ["", "", "", ""])[:4]
    return [
        {
            "title": "准备与核心概念",
            "purpose": f"明确「{title}」的范围，建立必要概念与工具环境。",
            "content_type": "concept",
            "summary": f"明确「{title}」的范围，建立必要概念与工具环境。",
            "criteria_ids": [x for x in [c[0]] if x],
        },
        {
            "title": "最小可运行任务（分步）",
            "purpose": "通过完成第一个真实任务掌握核心操作。",
            "content_type": "tool",
            "summary": "按步骤完成第一个真实任务，每一步都有预期结果与验证方式。",
            "criteria_ids": [x for x in [c[1]] if x],
        },
        {
            "title": "常见错误与排查",
            "purpose": "建立错误诊断能力，理解方法适用条件。",
            "content_type": "method",
            "summary": "复现典型错误、定位原因并验证修复。",
            "criteria_ids": [x for x in [c[2]] if x],
        },
        {
            "title": "练习、变式任务与复盘",
            "purpose": "巩固所学，检验迁移能力并整理方法总结。",
            "content_type": "application",
            "summary": "完成练习与变式任务，检查迁移能力并复盘。",
            "criteria_ids": [x for x in [c[3], c[1]] if x],
        },
    ]


def section(goal, discipline: DisciplineProfile, item: dict, criteria_by_id: dict) -> dict:
    """演示版章节：与 v2 提示词输出结构一致（content 内容块）。"""
    title = item.get("title", "")
    summary = item.get("summary", "")
    cids = item.get("criteria_ids", [])
    crit_text = "；".join(criteria_by_id.get(cid, {}).get("statement", "（验收标准）") for cid in cids) or "本章目标"
    is_cli = _is_cli(discipline)

    concept_body = (
        (
            "以命令行为例：一个命令由「程序名 + 参数 + 输入/输出」组成。它要解决的问题是："
            "把重复的手工操作交给可复现、可验证的指令。理解每一步的输入与输出，比记住具体写法更重要。"
        )
        if is_cli
        else (
            "以数据分析为例：一个方法由「定义 + 前提假设 + 计算过程 + 结论解释」组成。"
            "它要解决的问题是：在不满足理想条件的数据上做出可靠判断。"
            "使用前先检查假设是否满足，结论要说明适用范围，避免把相关当因果。"
        )
    )
    content = [
        {
            "type": "text",
            "title": "这一节在解决什么问题",
            "body": f"{summary}\n本章对应的验收标准：{crit_text}。{concept_body}",
        },
        {
            "type": "key_point",
            "title": "核心结论",
            "body": (
                "先理解机制，再记忆写法：每一步操作都应能回答「输入是什么、输出是什么、如何验证结果正确」。"
            ),
        },
        {
            "type": "steps",
            "title": "操作步骤",
            "body": (
                "1. 确认前提条件（环境/数据/基础）——预期：能看到与教程一致的版本信息或环境状态；"
                "验证：运行版本检查命令（或核对数据字段）并与教程描述比对。\n"
                "2. 执行本章核心操作的最小示例——预期：得到与预期一致的输出/结果；"
                "验证：按教程给出的验证方式逐项检查，把实际输出与预期输出对照。\n"
                "3. 把示例改造成你自己的任务版本——预期：产物可运行/可复算，且与示例有明确差异；"
                "验证：重新执行验证；记录差异点与原因。"
            ),
        },
        {
            "type": "example",
            "title": "示例",
            "body": (
                f"{summary}（演示模式生成的示例框架；配置真实模型后内容会针对「{_goal_title(goal)}」细化）"
            ),
        },
        {
            "type": "note",
            "title": "注意事项",
            "body": (
                "注意区分「演示环境」与「你的环境」的差异（版本、权限、路径）；"
                "示例中的关键事实与命令需人工核验。"
            ),
        },
    ]

    exercises = [
        "练习 1：按本章步骤复现最小示例，并把实际输出与预期对照。",
        "练习 2：故意制造一个错误，按排查方法定位并修复。",
        f"练习 3：把本章方法应用到你自己的场景：{getattr(goal, 'application_context', '你的真实任务')}。",
    ]
    common_errors = [
        {"error": e, "cause": "常见原因见学科清单", "diagnose": "按「复现 → 定位 → 最小验证」三步排查"}
        for e in discipline.common_errors[:3]
    ]

    return {
        "title": title,
        "purpose": str(item.get("purpose", "") or summary),
        "content_type": str(item.get("content_type", "") or "mixed"),
        "content": content,
        "key_takeaways": [
            "每一步操作都要能回答：输入是什么、输出是什么、如何验证。",
            "遇到错误先复现，再定位，最后最小验证修复。",
        ],
        "common_errors": common_errors,
        "prerequisite_refs": ["完成上一章内容", "工具/环境可用"],
        "exercises": exercises,
        "sources": [
            {
                "title": "演示模式生成内容",
                "url": "",
                "note": "本教程由演示生成器产生，关键事实与命令需人工核验；配置真实模型后可获得针对性内容与来源。",
            }
        ],
        "mapping_criteria": cids,
    }


def cheatsheet(goal, discipline: DisciplineProfile, outline_items: list[dict]) -> dict:
    """演示版知识速查：从大纲确定性派生集中查阅材料。"""
    title = _goal_title(goal)
    is_cli = _is_cli(discipline)
    rows = (
        "| 功能/命令 | 入口/写法 | 用途 | 结果检查 |\n| --- | --- | --- | --- |\n"
        "| 环境确认 | `--version` / 帮助命令 | 确认工具可用与版本 | 输出版本号与教程一致 |\n"
        "| 最小示例 | 教程第 2 节命令 | 完成一次核心操作 | 输出与预期一致 |\n"
        "| 排错入口 | 报错信息 + 复现命令 | 定位失败原因 | 能指出哪一步偏离预期 |"
        if is_cli
        else "| 方法/概念 | 定义出处 | 用途 | 结果检查 |\n| --- | --- | --- | --- |\n"
        "| 核心方法 | 教程第 2 节 | 完成一次典型分析 | 结论可复算且适用条件满足 |\n"
        "| 前提假设 | 教程第 1 节 | 判断方法是否适用 | 使用前已逐项核对 |\n"
        "| 常见混淆 | 教程第 3 节 | 区分易混概念 | 能各举一个正反例 |"
    )
    return {
        "title": f"{title} · 知识速查",
        "sections": [
            {"heading": "核心速查表", "body": rows},
            {
                "heading": "使用说明",
                "body": (
                    f"本速查文件是「{title}」教程的配套材料，只用于快速查阅，不能替代正文讲解。"
                    "演示模式下内容为结构框架，配置真实模型后按教程正文细化。"
                ),
            },
        ],
    }


def extra_exercises(goal, discipline: DisciplineProfile, outline_items: list[dict]) -> dict:
    """演示版额外练习：与教程正文例题区分，答案集中放在文件后部。"""
    title = _goal_title(goal)
    app = getattr(goal, "application_context", "") or "你的真实任务"
    return {
        "title": f"{title} · 额外练习",
        "intro": (
            f"本文件是「{title}」教程的独立练习集，用于强化、巩固、检验和迁移。"
            "题目与教程正文中的必要练习不重复；参考答案集中在本文件末尾，建议先完成再看。"
        ),
        "exercises": [
            {
                "number": 1,
                "task": "在不看教程步骤的情况下，复现教程第 2 节的最小任务（换一组数据或目录）。",
                "requirements": "只允许查阅速查文件；记录每一步的实际输出。",
                "hint": "按「前提 → 操作 → 验证」的顺序执行；卡住时先确认输入是否符合预期。",
                "solution": "输出与预期一致、且能解释每步输入输出即为通过。",
            },
            {
                "number": 2,
                "task": "构造一个会触发常见错误的场景，复现、定位并修复它。",
                "requirements": "记录错误信息、原因判断与修复后的验证结果。",
                "hint": f"可从常见错误清单中选择：{('路径/权限/参数拼写' if _is_cli(discipline) else '概念混淆/假设不满足/计算错误')}。",
                "solution": "错误可复现、原因解释正确、修复后验证通过即为通过。",
            },
            {
                "number": 3,
                "task": f"把教程方法应用到一个教程未覆盖的情境：{app}。",
                "requirements": "完成后解释你依据了哪条规律，哪些地方需要调整。",
                "hint": "先识别情境与教程示例的相同点与不同点，再决定沿用或调整哪些步骤。",
                "solution": "任务完成且能说明关键决策依据即为通过；说不清依据说明迁移尚未形成。",
            },
        ],
        "answers_note": "参考答案与自检标准如上各题 solution 所示；先独立完成，再逐条对照。",
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
    is_cli = _is_cli(discipline)
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


def knowledge_extract(goal, tutorial, context: dict, existing: list) -> dict:
    """演示版知识提取：从大纲 / 章节结构确定性地派生概念与关系。

    规则（与分级策略一致，只写有结构依据的内容）：
    - 概念：每个大纲条目一个概念，定义取章节摘要，锚点指向该章节；
    - 关系：相邻章节构成先修链（第 i 章 先修于 第 i+1 章，教程顺序即依据）；
    - 跨章关键词关联：标题中共享关键词的章节建立 related（待核实）。
    """
    outline = context.get("outline", []) or []
    concepts = []
    for item in outline:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        concepts.append(
            {
                "title": title,
                "definition": str(item.get("summary", "") or f"「{_goal_title(goal)}」教程中的学习单元。"),
                "domain_key": getattr(goal, "domain_key", "general"),
                "section_id": str(item.get("section_id", "") or ""),
                "section_title": title,
                "aliases": [],
            }
        )
    relations = []
    for a, b in zip(outline, outline[1:]):
        if a.get("title") and b.get("title"):
            relations.append(
                {
                    "from_title": str(a["title"]),
                    "to_title": str(b["title"]),
                    "relation_type": "prerequisite_of",
                    "rationale": "教程章节顺序：前一章是后一章的学习前提（演示模式按大纲结构派生）。",
                    "section_id": str(a.get("section_id", "") or ""),
                    "confidence": 0.6,
                }
            )
    # 共享关键词的章节建立「相关联」（无章节锚点 → 待核实，不自动确认）
    def _keywords(text: str) -> set[str]:
        text = str(text or "")
        return {w for w in ("概念", "错误", "排查", "练习", "任务", "复盘", "工具", "环境", "数据", "验证") if w in text}

    for i, a in enumerate(outline):
        for b in outline[i + 2:]:
            shared = _keywords(a.get("title", "")) & _keywords(b.get("title", ""))
            if shared:
                relations.append(
                    {
                        "from_title": str(a.get("title", "")),
                        "to_title": str(b.get("title", "")),
                        "relation_type": "related",
                        "rationale": f"章节主题共享关键词（{'、'.join(sorted(shared))}），推测相关，待核实。",
                        "section_id": "",
                        "confidence": 0.35,
                    }
                )
    return {"concepts": concepts, "relations": relations}
