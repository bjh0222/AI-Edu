"""提示词模板（真实模型模式）。要求输出严格 JSON。"""
from __future__ import annotations

import json

SYSTEM = (
    "你是 AI Edu 的学习引擎。你帮助用户把学习目标转化为可验收、可实践、可迁移的学习闭环。"
    "要求：只输出 JSON；不编造来源；不确定的内容明确标注；不把推断写成事实。"
    "不要安排日程：任何生成内容中都不出现「第 X 天 / 第 X 周 / 每天 / 每周投入多少时间」这类按日历分配时间的表述；"
    "时间只以单个步骤或章节的工作量估计（如「1–2 小时」）出现，具体什么时候学由用户自己决定。"
)


def _goal_ctx(goal) -> dict:
    return {
        "title": goal.title,
        "motivation": goal.motivation,
        "application_context": goal.application_context,
        "current_level": goal.current_level,
        "time_budget": goal.time_budget,  # 可投入总时间（如「共 10 小时」），不是每日日程
    }


def _materials_section(materials_text: str) -> str:
    """用户上传材料（参考资料 / 例题来源）的注入块；无材料时返回空串，保持原 prompt 不变。"""
    text = (materials_text or "").strip()
    if not text:
        return ""
    return (
        "\n用户上传的参考资料 / 例题来源（仅作依据，不得编造材料中没有的内容）：\n"
        f"{text}\n"
        "要求：引用材料内容时标注「来自材料 N（文件名）」；例题来源里的题型风格优先沿用；"
        "材料未覆盖的部分明确标注为推断或需核验。\n"
    )


def diagnose(goal, discipline, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n"
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"{_materials_section(materials_text)}\n"
        "请输出 JSON：{\"benefits\": str, \"prerequisites\": str, \"alternatives\": str, "
        "\"assumptions\": str, \"uncertainties\": str, \"recommendation\": str}。\n"
        "benefits/alternatives 用编号列表；recommendation 给出明确建议（推进/缩小范围/暂缓）。"
    )
    return SYSTEM, user


def plan(goal, discipline, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"该学科的常见实践形式：{discipline.practice_templates}\n"
        f"{_materials_section(materials_text)}\n"
        "输出 JSON：{\"steps\": [{\"title\": str, \"objective\": str, \"estimated_effort\": str}]}。"
        "步骤 4–6 个，按依赖顺序，第一步必须是范围收窄与环境确认。"
        "time_budget 是可投入总时间；estimated_effort 只表示完成该步骤所需的工作量估计（如「1–2 小时」），"
        "不要把步骤映射到具体日期或天次，不要出现「第 X 天」「每天」的表述。"
    )
    return SYSTEM, user


def criteria(goal, discipline) -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n\n"
        "输出 JSON：{\"criteria\": [{\"statement\": str, \"conditions\": str, \"evidence_type\": str, "
        "\"pass_rule\": str, \"rationale\": str}]}。\n"
        "要求：4–5 条，覆盖 概念解释/应用/错误诊断/独立完成/迁移 五个维度中的至少四个。"
        "statement 必须以「能够 + 可观察动词」开头，禁止使用「理解/掌握/熟悉/了解/学会」；"
        "每条必须给出可判定的 pass_rule。"
    )
    return SYSTEM, user


def outline(goal, discipline, criteria_list, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"已确认的验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
        f"{_materials_section(materials_text)}\n"
        "输出 JSON：{\"sections\": [{\"title\": str, \"summary\": str, \"criteria_ids\": [str]}]}。"
        "章节 4–6 个；每章至少映射一条验收标准；所有验收标准都必须被至少一个章节覆盖；"
        "最后一章必须包含变式任务与复盘。"
    )
    return SYSTEM, user


def section(
    goal, discipline, outline_item, criteria_list, prior_titles, materials_text: str = ""
) -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"已学过章节：{prior_titles}\n"
        f"本章大纲：{json.dumps(outline_item, ensure_ascii=False)}\n"
        f"相关验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
        f"{_materials_section(materials_text)}\n"
        "输出 JSON，字段如下：\n"
        "{\"title\": str, \"goal_statement\": str, \"prerequisites\": [str], "
        "\"explanation\": [{\"heading\": str, \"body\": str}], "
        "\"steps\": [{\"text\": str, \"expected_result\": str, \"verification\": str}], "
        "\"examples\": [str], \"exercises\": [str], \"variation_task\": str, "
        "\"common_errors\": [{\"error\": str, \"cause\": str, \"diagnose\": str}], "
        "\"sources\": [{\"title\": str, \"url\": str, \"note\": str}], "
        "\"mapping_criteria\": [str]}\n"
        "要求：步骤 3–6 个，每个步骤必须有 expected_result 与 verification；"
        "步骤必须可被用户逐步执行；sources 至少一条（真实可追溯，或标注「需核验」）；"
        "mapping_criteria 用给定的验收标准 id。"
    )
    return SYSTEM, user


def feedback(goal, criteria_list, task, attempt) -> tuple[str, str]:
    user = (
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
        f"任务：{task.title}｜要求：{task.instructions or task.expected_artifact}\n"
        f"用户产物：{attempt.artifact}\n用户解释：{attempt.user_explanation}\n"
        f"错误信息：{attempt.errors}\n辅助等级：{attempt.help_level}\n\n"
        "输出 JSON：{\"items\": [{\"criterion_id\": str, \"statement\": str, \"status\": \"satisfied|unsatisfied|unclear\", "
        "\"evidence\": str, \"reason\": str, \"next_action\": str}], \"summary\": str, \"weak_points\": str}。"
        "要求：按验收标准逐项判断；区分事实与推断；只基于用户提供的证据，不虚构测试结果；"
        "不一致处给出最小下一步排查动作。"
    )
    return SYSTEM, user


def assessment(goal, discipline) -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"评估维度：{discipline.assessment_rubrics}\n\n"
        "输出 JSON：{\"rubric\": [{\"dimension\": str, \"weight\": float, \"note\": str}], "
        "\"independent_task\": {\"title\": str, \"description\": str, \"expected_artifact\": str}, "
        "\"variant_task\": {\"title\": str, \"description\": str}, \"evidence_hint\": str}。"
        "independent_task 必须是不照抄教程的独立任务；variant_task 必须换一个情境。"
    )
    return SYSTEM, user


def reflection(goal, context) -> tuple[str, str]:
    user = (
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"本轮数据：{json.dumps(context, ensure_ascii=False)}\n\n"
        "输出 JSON：{\"summary\": str, \"learned_capabilities\": str, \"unresolved_gaps\": str, "
        "\"next_actions\": str, \"candidate_concepts\": [{\"title\": str, \"definition\": str}]}。"
        "要求：只基于提供的数据；区分「已形成的能力」与「仍需验证的内容」；"
        "candidate_concepts 最多 5 个，必须与本轮学习直接相关。"
    )
    return SYSTEM, user


def suggest_proposals(goal, concepts, relations_hint) -> tuple[str, str]:
    user = (
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"已有概念：{json.dumps(concepts, ensure_ascii=False)}\n"
        f"候选关系：{json.dumps(relations_hint, ensure_ascii=False)}\n\n"
        "输出 JSON：{\"proposals\": [{\"proposal_type\": \"concept|relation\", "
        "\"payload\": {...}, \"rationale\": str}]}。"
        "relation payload 含 from_title/to_title/relation_type；concept payload 含 title/definition。"
        "只提议有依据的关系，不编造；最多 6 条。"
    )
    return SYSTEM, user


def chat(goal, question, context) -> tuple[str, str]:
    user = (
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"当前上下文：{json.dumps(context, ensure_ascii=False)}\n"
        f"用户问题：{question}\n\n"
        "请以学习教练身份回答：先确认已知事实与缺失信息，再给出提示或最小下一步；"
        "不要直接给出完整答案或大段代码；如引用来源必须真实，不确定则说明。"
        "输出 JSON：{\"answer\": str}。"
    )
    return SYSTEM, user
