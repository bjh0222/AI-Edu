"""提示词模板（真实模型模式）。要求输出严格 JSON。

设计原则（与产品定位一致）：
- 教程是核心交付物：独立可用、解释充分、内容克制，而不是对话式课程的提纲；
- 目标驱动：内容、深度、结构与例题由学习目标 + 能力层级 + 材料约束决定；
- 先理解后记忆：核心知识按「直觉 → 原理 → 结论」分层讲解；
- 因材施教：按知识性质（概念/方法/工具/事实/综合）选择教学方式，不强制统一模板；
- 后端用严格 JSON，最终面向用户的是渲染后的 Markdown，不暴露 JSON 结构。
"""
from __future__ import annotations

import json

from ..learning.levels import level_prompt_block
from ..model_settings import read_config

SYSTEM = (
    "你是 AI Edu 的学习引擎与资深教学设计者。你帮助用户把学习目标转化为可验收、可实践、可迁移的学习闭环，"
    "核心交付物是一份可以独立阅读、放入 Obsidian 长期使用的高质量教程。\n"
    "要求：\n"
    "1. 只输出 JSON；不输出 JSON 以外的任何文本。JSON 字符串内如需换行，必须写成转义序列 \\n；"
    "代码块、Mermaid、表格等多行内容也必须作为合法的 JSON 字符串给出（不要出现裸换行）。\n"
    "2. 不编造来源、引用、网址或文献；不确定的内容明确标注「需核验」；不把推断写成事实。\n"
    "3. 先理解，后记忆：核心知识优先建立直觉、解释原理，再提炼结论。\n"
    "4. 内容克制：优先讲透核心知识；不为营造「内容丰富」而堆积拓展、重复解释或过量例题。\n"
    "5. 教程必须独立可用：读者不应因为缺少某个定义、参数说明或前置知识而无法继续阅读。\n"
    "6. 不要安排日程：任何生成内容中都不出现「第 X 天 / 第 X 周 / 每天 / 每周投入多少时间」这类按日历分配时间的表述；"
    "时间只以单个步骤或章节的工作量估计（如「1–2 小时」）出现，具体什么时候学由用户自己决定。\n"
    "7. 因材施教：根据知识性质选择教学方式，不为所有知识点套用统一栏目；空缺的栏目允许留空（[] 或空串），不要编造。\n"
    "8. 用户会在 Obsidian 中阅读教程：正文 Markdown 中的标题层级、表格、代码块、数学公式、Mermaid 图必须语法正确。"
)

# Obsidian 双链说明：正文允许使用 [[链接]] 指向本次生成集合内的配套文件
WIKILINK_RULE = (
    "允许在正文使用 Obsidian 双链 [[文件名]] 引用本次同时生成的配套文件；"
    "禁止指向本次生成集合之外或不存在的文件。\n"
)


def _goal_ctx(goal) -> dict:
    context = {
        "title": goal.title,
        "motivation": goal.motivation,
        "application_context": goal.application_context,
        "current_level": goal.current_level,
        "time_budget": goal.time_budget,  # 可投入总时间（如「共 10 小时」），不是每日日程
    }
    user_profile = str(read_config().get("user_profile", "")).strip()
    if user_profile:
        context["user_profile"] = user_profile
    return context


def _capability(goal) -> str:
    return level_prompt_block(getattr(goal, "capability_level", None))


def _materials_section(materials_text: str) -> str:
    """用户上传材料（参考资料 / 例题来源）的注入块；无材料时返回空串，保持原 prompt 不变。"""
    text = (materials_text or "").strip()
    if not text:
        return ""
    return (
        "\n用户上传的参考资料 / 例题来源（范围约束与依据）：\n"
        f"{text}\n"
        "材料使用规则：优先沿用材料中明确要求的内容、术语、任务与例题风格；"
        "不把材料未覆盖的内容伪装成材料原有结论；材料存在缺口时可以合理补充，"
        "但当用户明确要求遵循指定材料范围时不得擅自扩展到明显偏离目标的领域。\n"
    )


# ---------------------------------------------------------------- 目标阶段

def diagnose(goal, discipline, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n"
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"{_capability(goal)}\n"
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
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        "输出 JSON：{\"steps\": [{\"title\": str, \"objective\": str, \"estimated_effort\": str}]}。"
        "步骤按依赖顺序，第一步必须是范围收窄与环境确认；步骤数量由目标范围决定，不固定。"
        "time_budget 是可投入总时间；estimated_effort 只表示完成该步骤所需的工作量估计（如「1–2 小时」），"
        "不要把步骤映射到具体日期或天次，不要出现「第 X 天」「每天」的表述。"
    )
    return SYSTEM, user


def criteria(goal, discipline) -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"{_capability(goal)}\n"
        f"评估维度：{discipline.assessment_rubrics}\n\n"
        "输出 JSON：{\"criteria\": [{\"statement\": str, \"conditions\": str, \"evidence_type\": str, "
        "\"pass_rule\": str, \"rationale\": str}]}。\n"
        "要求：4–5 条，覆盖 概念解释/应用/错误诊断/独立完成/迁移 五个维度中的至少四个"
        "（低层级允许把「迁移」合并进「应用」，但必须覆盖概念解释与应用）。\n"
        "statement 必须以「能够 + 可观察动词」开头，禁止使用「理解/掌握/熟悉/了解/学会」；"
        "每条必须给出可判定的 pass_rule。"
        "验收难度必须与能力层级匹配：层级越高，对独立完成、变式迁移与决策解释的要求越高；"
        "不得要求用户展示教程没有提供必要基础的能力。"
    )
    return SYSTEM, user


# ---------------------------------------------------------------- 教程规划

def outline(goal, discipline, criteria_list, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"已确认的验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n\n"
        "任务：为教程设计章节大纲。这是一次内部教学规划，请先在心里完成以下判断再输出：\n"
        "1. 达成目标必须包含哪些核心知识？哪些基础知识是理解核心内容所必需的（支撑知识）？\n"
        "2. 哪些内容只需简要介绍、放入速查清单或不讲（扩展知识按需取舍）？\n"
        "3. 各个核心知识点适合什么教学方式（概念原理 / 方法技巧 / 工具操作 / 事实记忆 / 综合应用）？\n"
        "4. 支撑知识安排在读者真正需要它的位置，避免重复讲解。\n\n"
        "输出 JSON：{\"sections\": [{\"title\": str, \"purpose\": str, \"content_type\": str, "
        "\"summary\": str, \"criteria_ids\": [str]}]}。\n"
        "字段说明：\n"
        "- purpose：本章在整体学习路径中的作用（一句话）；\n"
        "- content_type：本章主要教学类型，只能取 concept / method / tool / fact / application / mixed；\n"
        "- criteria_ids 必须使用给定验收标准的 id。\n"
        "章节规划要求：\n"
        "- 章节数量由目标范围与知识复杂度决定：目标较小允许只有 1–3 章；目标复杂可增加，但避免碎片化；\n"
        "- 覆盖全部核心知识，且所有验收标准都被至少一个章节覆盖；\n"
        "- 章节之间保持合理的依赖顺序；\n"
        "- 不为让大纲显得系统而塞入与目标关联较弱的内容；\n"
        "- 不强制规定必须有变式章节或复盘章节：归纳、总结与练习按知识特点安排在最合适的位置。"
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
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        f"{WIKILINK_RULE}"
        "任务：撰写本章教程正文。先做内部教学规划（不必输出）：\n"
        "1. 本章的核心知识（A 级：直接决定目标达成，必须讲透——直觉、原理、关键结论、适用条件、使用方式）；\n"
        "2. 支撑知识（B 级：理解或应用核心知识所必需的基础，用户可能不熟悉，必须在正文中给足解释，"
        "不能让读者因为缺一个基础知识而中断）；\n"
        "3. 扩展知识（C 级：只在有明确价值时纳入，否则省略或一句带过）；\n"
        "4. 按知识性质选择教学方式，不机械套用固定栏目。\n\n"
        "分层讲解原则（核心知识默认采用，但按内容自然组织标题，不生硬套三段式）：\n"
        "- 第一层 直觉与问题背景：解决什么问题、为什么需要它、简单例子建立初步认识；直觉有局限要指出；\n"
        "- 第二层 原理与关键推导：核心机制、关键定义与条件、重要推导或操作依据、易混淆概念的区别；\n"
        "- 第三层 结论与可用知识：公式、规则、操作流程、适用条件、注意事项，以及可直接复用的精炼总结。\n\n"
        "教学方式按知识性质选择：\n"
        "- 概念与原理：问题背景/直觉 → 严格定义与术语 → 推导或成立条件 → 正例反例与辨析 → 与相关概念的联系；\n"
        "- 方法与技巧：方法分类 → 各自适用条件 → 方法选择依据 → 关键步骤 → 易错环节 → 方法比较与决策规则"
        "（重点是帮读者判断什么时候用哪种方法，不是罗列方法）；\n"
        "- 工具与操作：要解决的问题 → 功能用途 → 入口/调用方式 → 语法参数与操作步骤 → 预期结果与验证 → "
        "常见失败原因与排查（形成「需求 → 功能 → 入口 → 使用方法 → 结果检查」的完整链路）；\n"
        "- 事实与记忆：区分「必须记住 / 理解后使用 / 知道在哪查 / 靠练习熟练」，不要都变成背诵任务；\n"
        "- 综合应用：真实任务 → 知识与方法组合 → 关键决策及依据 → 完整过程 → 结果检查与适用范围。\n\n"
        "例题与练习（克制原则）：\n"
        "- 数量由知识难度、教学需要与能力层级决定，不设固定数量；没有教学价值就不加；\n"
        "- 例题优先选有代表性、信息密度高的；篇幅与其教学价值相称，不得挤占核心讲解；\n"
        "- 方法性例题体现方法选择与关键决策，不只要计算过程；工具操作用简短真实可执行的示例；\n"
        "- exercises 只放验证核心方法所必需的必要练习；更大量的巩固练习由独立的额外练习文件承载（不由本章生成）。\n\n"
        "输出 JSON：\n"
        "{\"title\": str,\n"
        " \"purpose\": str,                                  # 本章在学习路径中的作用（沿用或细化大纲）\n"
        " \"content_type\": str,                             # concept / method / tool / fact / application / mixed\n"
        " \"content\": [                                     # 正文内容块，按合理教学顺序组合；块类型只能取：\n"
        "     {\"type\": \"text\"|\"key_point\"|\"formula\"|\"steps\"|\"table\"|\"example\"|\"comparison\""
        "|\"method_summary\"|\"diagram\"|\"memory\"|\"note\",\n"
        "       \"title\": str,                               # 块标题（可以是空串）\n"
        "       \"body\": str}],                              # Markdown 正文\n"
        " \"key_takeaways\": [str],                          # 核心结论；无则 []\n"
        " \"common_errors\": [{\"error\": str, \"cause\": str, \"diagnose\": str}],  # 与本章密切相关的典型错误；无则 []\n"
        " \"prerequisite_refs\": [str],                      # 正文涉及的必要前置知识或速查条目名称；无则 []\n"
        " \"exercises\": [str],                              # 必要练习；无则 []\n"
        " \"sources\": [{\"title\": str, \"url\": str, \"note\": str}],  # 仅在确有可靠来源时给出；无则 []\n"
        " \"mapping_criteria\": [str]}                       # 用给定的验收标准 id\n"
        "内容块规范：\n"
        "- text：普通解释正文；\n"
        "- key_point：关键结论（简短，用于强调真正重要的结论）；\n"
        "- formula：公式与推导，body 用 LaTeX（$...$ 或 $$...$$）；\n"
        "- steps：操作步骤，body 用有序 Markdown 列表，每步含操作、预期结果与验证方式；\n"
        "- table：表格，body 用 Markdown 表格；\n"
        "- example：示例；comparison：对比分析（用 Markdown 表格或逐项对比）；\n"
        "- method_summary：方法归纳（用途、适用条件、关键步骤、选择依据、陷阱）；\n"
        "- diagram：概念关系图，body 用 ```mermaid 代码块，只画有依据的关系；\n"
        "- memory：记忆材料（口诀、清单）；note：注意事项与易错提醒。\n"
        "- 按需组合，不要求每章包含所有类型；核心章节至少包含一层直觉解释与一层原理讲解；\n"
        "- Markdown 必须语法正确：表格、代码块、公式、Mermaid 都要能直接渲染。\n"
        "不要把完整教学规划过程写进输出；输出即教程正文本身。"
    )
    return SYSTEM, user


# ---------------------------------------------------------------- 配套文件

def cheatsheet(goal, discipline, outline_items, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"教程大纲：{json.dumps(outline_items, ensure_ascii=False)}\n"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n\n"
        "任务：为教程生成配套的「知识速查」文件。只放适合集中查阅、有长期复用价值的材料，例如：\n"
        "- 重要公式、定义和规则；\n"
        "- 命令行参数及其用途；\n"
        "- 工具功能名称、入口、用途和常见用法；\n"
        "- 常用函数、操作流程和快捷方式；\n"
        "- 方法分类及其适用条件；\n"
        "- 容易混淆的概念对比。\n"
        "要求：优先使用表格、短列表、简洁分类与必要示例，便于快速定位；"
        "速查文件是教程的补充，不能替代正文讲解；只收录教程大纲涉及的知识，不要扩展新主题。"
        "输出 JSON：{\"title\": str, \"sections\": [{\"heading\": str, \"body\": str}]}，"
        "body 为 Markdown（表格 / 列表 / 代码块），heading 是速查文件内的小节标题。"
    )
    return SYSTEM, user


def extra_exercises(goal, discipline, outline_items, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"教程大纲：{json.dumps(outline_items, ensure_ascii=False)}\n"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n\n"
        "任务：为教程生成独立的「额外练习」文件，用于强化、巩固、检验和迁移，"
        "不是简单复制教程正文中的例题。\n"
        "要求：\n"
        "- 题目数量克制：按知识难度与能力层级决定，避免无意义堆题；\n"
        "- 题目难度与用户能力层级匹配；\n"
        "- 每题包含清晰的任务说明和必要条件；\n"
        "- 根据学科特点提供解题思路或提示（hint）；\n"
        "- 提供参考答案或自我检查标准（solution）；\n"
        "- 题目编号连续。\n"
        "输出 JSON：{\"title\": str, \"intro\": str, "
        "\"exercises\": [{\"number\": int, \"task\": str, \"requirements\": str, \"hint\": str, \"solution\": str}], "
        "\"answers_note\": str}。"
        "answers_note 是说明参考答案位置的提示语（答案会集中渲染在文件后部）。"
    )
    return SYSTEM, user


# ---------------------------------------------------------------- 闭环阶段

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
        f"评估维度：{discipline.assessment_rubrics}\n"
        f"{_capability(goal)}\n\n"
        "输出 JSON：{\"rubric\": [{\"dimension\": str, \"weight\": float, \"note\": str}], "
        "\"independent_task\": {\"title\": str, \"description\": str, \"expected_artifact\": str}, "
        "\"variant_task\": {\"title\": str, \"description\": str}, \"evidence_hint\": str}。"
        "independent_task 必须是不照抄教程的独立任务；variant_task 必须换一个情境。"
        "任务难度与能力层级匹配：若教程包含实践任务优先用实际成果作证据；"
        "若以概念学习为主，用解释、辨析、推导或应用任务作证据。"
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


def knowledge_extract(goal, tutorial, context: dict, existing: list) -> tuple[str, str]:
    user = (
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"教程：{tutorial.title}\n"
        f"教程结构（outline 与 sections 均含 section_id）：{json.dumps(context, ensure_ascii=False)}\n"
        f"已有概念（用于去重，勿重复输出）：{json.dumps(existing, ensure_ascii=False)}\n\n"
        "从教程结构中提取结构化知识。要求：\n"
        "- concepts：只提取教程结构直接体现的概念 / 学习单元；title 简明稳定；definition 一句话；"
        "section_id 指向最直接解释该概念的章节；已有概念（按名称）不要重复输出；最多 12 个。\n"
        "- relations：只写有依据的关系；from_title/to_title 必须能在 concepts 或已有概念中找到；"
        "relation_type 只能取 prerequisite_of / part_of / explains / applied_in / contrasts_with / related；"
        "带 section_id 表示教程明确解释（会自动确认），纯推测则留空 section_id 并降低 confidence；"
        "不为图谱美观添加无依据的边；最多 20 条。\n"
        "- domain_key 只能使用规范学科 key（例如 math_logic / cs_it / philosophy_ethics / "
        "psychology_cognition / economics_business），跨学科概念填写它主要服务的规范学科；"
        "不要自造新 key。\n"
        "输出 JSON：{\"concepts\": [{\"title\": str, \"definition\": str, \"domain_key\": str, "
        "\"section_id\": str, \"aliases\": [str]}], "
        "\"relations\": [{\"from_title\": str, \"to_title\": str, \"relation_type\": str, "
        "\"rationale\": str, \"section_id\": str, \"confidence\": float}]}。"
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
