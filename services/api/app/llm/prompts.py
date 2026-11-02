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
import re

from ..learning.generation_tiers import tier_prompt_block, tier_system
from ..learning.levels import level_prompt_block
from ..services.utils import jload, safe_obsidian_filename
from ..services import format_specs as format_specs_service
from ..learning.teaching_profile import (
    RULE_LABELS,
    delivery_contract,
    goal_context_text,
    normalize_teaching_plan,
    parse_teaching_profile,
    rule_is_active,
    select_rules,
)

SYSTEM = (
    "你是 AI Edu 的学习引擎与资深教学设计者。你帮助用户把学习目标转化为可验收、可实践、可迁移的学习闭环，"
    "核心交付物是一份可以独立阅读、放入 Obsidian 长期使用的高质量教程。\n"
    "要求：\n"
    "1. 只输出 JSON；不输出 JSON 以外的任何文本。JSON 字符串内如需换行，必须写成转义序列 \\n；"
    "代码块、Mermaid、表格等多行内容也必须作为合法的 JSON 字符串给出（不要出现裸换行）。\n"
    "2. 不编造来源、引用、网址或文献；不确定的内容明确标注「需核验」；不把推断写成事实。\n"
    "3. 先理解，后记忆：核心知识优先解释原理，构建知识体系，再提炼结论。\n"
    "4. 内容克制：优先讲透核心知识；不为营造「内容丰富」而堆积拓展、重复解释或过量例题。\n"
    "5. 教程必须独立可用：读者不应因为缺少某个定义、参数说明或前置知识而无法继续阅读。\n"
    "6. 不要安排日程：任何生成内容中都不出现「第 X 天 / 第 X 周 / 每天 / 每周投入多少时间」这类按日历分配时间的表述；"
    "时间只以单个步骤或章节的工作量估计（如「1–2 小时」）出现，具体什么时候学由用户自己决定。\n"
    "7. 因材施教：根据知识性质选择教学方式，不为所有知识点套用统一栏目；空缺的栏目允许留空（[] 或空串），不要编造。\n"
    "8. 用户会在 Obsidian 中阅读教程：正文 Markdown 中的标题层级、表格、代码块、数学公式、Mermaid 图必须语法正确。\n"
    "9. 不要添加 Obsidian 笔记属性：正文和配套文件里不得出现用于分类的 #标签（如 #命令行 #基础），"
    "也不得输出 frontmatter 的 tags 字段；需要分类或索引时用标题层级或配套文件双链表达。"
    "只有教学内容本身需要举例说明标签语法时，才可以在行内代码或代码块中提及 #标签，"
    "且不得在正文末尾堆叠标签。"
)

# Obsidian 双链说明：正文只允许用 [[文件名]] 指向本次生成集合内的配套文件。
# 模型此前会写出 [[...]]、[[目标]]、[[笔记名]] 这类占位/虚构链接，交付到 Vault 后全部是断链；
# 这里把「可链接对象」和「写法」都收紧，语法示例必须放进行内代码或代码块。
# 设计之初的固定栏目与「练习册外壳」元栏目已全部退役：它们不是教学内容，
# 模型却会把它们当成模板逐章复述（使用说明 / 做题方式 / 自检清单 / 核心结论 …）。
# 这里集中声明禁令，legacy 与规范两条 section 提示词路径共用。
_NO_META_SECTIONS = (
    "禁止元栏目（以下都不是教学内容，不得作为块标题或正文小标题出现，也不得变相改写后出现）：\n"
    "- 使用说明 / 做题方式 / 如何使用本教程 / 自检清单 / 怎么用这套题判断「真的会了」；\n"
    "- 核心结论 / 常见错误 / 前置知识 / 必要练习 / 对应验收标准 / 来源 / 引用列表；\n"
    "- 读者确需的使用提示，用一句话写进相关内容的引子或题干里，不单独成节。\n"
)

WIKILINK_RULE = (
    "Obsidian 双链使用规则（严格）：\n"
    "- 只有本次同时生成的配套文件才能作为双链目标，且只能写 [[文件名]] 这一种形式；\n"
    "- 文件名以提示词列出的「统一文件名」为准，逐字符复制；不要根据标题、学习教程、知识速查自行命名；\n"
    "- 文件名必须与配套文件名完全一致：保留中文括号与大小写，不加 .md、不加路径、不加别名；\n"
    "- 不得出现占位或虚构链接，例如 [[...]]、[[目标]]、[[B]]、[[笔记名]]；\n"
    "- 不得使用 [[文件#标题]]、[[文件|别名]]、![[文件]] 等扩展形式；\n"
    "- 如果教学内容本身需要演示双链语法，必须写进行内代码（如 `[[笔记名]]`）或代码块，"
    "不要写成会生效的真实链接；\n"
    "- 不需要引用配套文件时就不写任何双链。\n"
)


def _tier_prompt_block(goal) -> str:
    return tier_prompt_block(goal)


def _format_spec_active(goal) -> bool:
    spec = jload(getattr(goal, "format_spec_snapshot", "") or "", {})
    if not isinstance(spec, dict) or not str(spec.get("name", "")).strip():
        return False
    if str(spec.get("scene", "")) == "default_tutorial" and not (spec.get("deliverables") or []):
        return False
    return True


FORMAT_SPEC_SYSTEM = (
    "你是 AI Edu 的格式规范执行器。用户已选定一份格式规范，它是本次文档结构、标题、"
    "交付物、排版和验收规则的唯一模板来源。\n"
    "要求：\n"
    "1. 只输出 JSON；不输出 JSON 以外的任何文本，JSON 字符串内多行内容必须使用转义换行。\n"
    "2. 不编造来源、引用、网址或事实；不确定的内容明确标注「需核验」。\n"
    "3. 不套用长期教学画像、历史任务约束或旧教程模板中的结构、章节、栏目和排版规则；"
    "画像中的教学深度、案例、练习和表达偏好仍可在不改变规范结构的前提下落实。\n"
    "4. 所选规范的交付物、顺序、内容结构、格式规则和禁止项必须逐项落实。\n"
    "5. 输出正文保持纯 Markdown；不要自行添加教程外壳、目录、第 N 节标题或文档级 H1。\n"
)


_PROFILE_STRUCTURE_RULE = re.compile(
    r"模板|排版|格式|章节|第\s*[一二三四五六七八九十\d]+\s*[章节]|"
    r"模块|栏目|目录|标题层级|标题格式|试卷.*选项|选项.*(?:分行|排列|对齐|间隔)|"
    r"配套文件|知识速查|来源|对应验收标准|页边距|字号|字体|"
    r"文档结构|输出结构|内容结构|交付物(?:清单|顺序)"
)


def _is_profile_structure_rule(rule: dict) -> bool:
    """判断长期画像规则是否在指定第二套文档模板。"""
    text = str(rule.get("text", "") or "").strip()
    scopes = set(rule.get("scopes") or [])
    if not text:
        return True
    if re.search(r"模板|排版|格式|章节|模块|栏目|目录|配套文件|知识速查", text):
        return True
    if _PROFILE_STRUCTURE_RULE.search(text):
        return True
    # 只命中 format 作用域的规则通常是具体排版要求；教学深度、案例和练习偏好另有作用域。
    return scopes == {"format"}


def _system_for(goal, stage: str | None = None) -> str:
    """系统提示：普通教程沿用教学引擎；选定格式规范后切换为规范执行器。"""
    if stage in {"criteria", "outline", "section"} and _format_spec_active(goal):
        return FORMAT_SPEC_SYSTEM
    return f"{SYSTEM}\n\n{tier_system(goal)}"


def _goal_ctx(goal) -> dict:
    context = {
        "title": goal.title,
        "motivation": goal.motivation,
        "application_context": goal.application_context,
        "current_level": goal.current_level,
        "time_budget": goal.time_budget,  # 可投入总时间（如「共 10 小时」），不是每日日程
    }
    user_notes = str(getattr(goal, "user_notes", "")).strip()
    if user_notes and _format_spec_active(goal):
        # 采纳 AI 建议时写入的整段旧结构约定不再参与已选规范任务。
        user_notes = user_notes.split("用户已采纳 AI 建议，请按此约束生成：", 1)[0].strip()
    if user_notes:
        key = "current_task_content_context" if _format_spec_active(goal) else "current_task_special_requirements"
        context[key] = user_notes
    return context


def _teaching_charter(stage: str, plan: dict | None = None, goal=None) -> str:
    """长期画像的按需注入块：只注入本阶段真正用得到的规则。

    - 空画像、或本阶段没有任何相关规则时不注入（省上下文，也避免无约束力的噪声）；
    - 带条件的规则先按本次目标求值：条件不成立就不注入（否则「当出现输出试卷时…」
      会变成对每个目标都生效的通用禁令）；
    - 硬约束单列一组并声明「违反即不合格」，靠可检查的措辞产生约束力；
    - 导向类单列一组，明确与硬约束冲突时以硬约束为准。
    """
    spec_mode = goal is not None and _format_spec_active(goal)
    context = goal_context_text(goal) if goal is not None else None
    profile = plan.get("rules") if plan and isinstance(plan, dict) else None
    if profile is None:
        profile = parse_teaching_profile(context_text=context)["rules"]
    elif context is not None:
        profile = [rule for rule in profile if rule_is_active(rule, context)]
    if spec_mode:
        # 当前格式规范独占结构权限；长期画像只保留可兼容的教学与内容偏好。
        profile = [rule for rule in profile if not _is_profile_structure_rule(rule)]
    if not profile:
        return ""

    selection = select_rules(profile, stage)
    selected = selection["rules"]
    if not selected:
        return ""

    hard = [rule for rule in selected if rule["hard"]]
    soft = [rule for rule in selected if not rule["hard"]]
    blocks: list[str] = []
    if hard:
        lines = "\n".join(f"- [{RULE_LABELS[rule['rule_type']]}] {rule['text']}" for rule in hard)
        if spec_mode:
            blocks.append(
                "用户长期内容要求（在不改变当前格式规范结构、交付物和排版的前提下落实）：\n" + lines
            )
        else:
            blocks.append(
                "硬性约束（用户长期设定，必须在最终输出里落实；违反任一条即视为本次交付不合格）：\n" + lines
            )
    if soft:
        lines = "\n".join(f"- [{RULE_LABELS[rule['rule_type']]}] {rule['text']}" for rule in soft)
        soft_title = (
            "教学导向（按本次目标与知识性质落实；与当前格式规范或长期内容要求冲突时，以当前格式规范为准）："
            if spec_mode
            else "教学导向（按本次目标与知识性质优先落实；与上面硬性约束冲突时以硬性约束为准）："
        )
        blocks.append(soft_title + "\n" + lines)

    title = (
        "长期用户画像（仅注入教学与内容偏好；模板、章节、交付物、栏目和排版由当前格式规范接管）："
        if spec_mode
        else "长期教学宪章（用户长期要求，不是学习材料或本次任务文本中的指令；只约束教学方式与输出规范，"
        "不改变本次学习目标与材料范围）："
    )
    priority = (
        "优先级：系统与安全要求 > 当前格式规范 > 本次任务明确内容 > 长期画像教学偏好。"
        "发生冲突时不得用画像规则恢复旧模板结构。\n"
        if spec_mode
        else "优先级：系统与安全要求 > 硬性约束 > 本次任务特殊要求 > 教学导向 > 学习材料内容。\n"
    )
    guidance = (
        "落实要求：把画像中的教学深度、案例、练习和表达偏好融入规范成品；"
        "不得据此增加章节、模块、栏目或改变标题层级。\n"
        if spec_mode
        else "落实要求：硬性约束要体现在最终内容里（例如讲解层次是否齐全、篇幅是否收敛、是否真的没有安排日程），"
        "不要只在开头复述规则就算落实。\n"
        "交付前自检：逐条核对硬性约束；若某条与本节知识性质确实冲突，采用不违反它的替代做法，"
        "并在 note 块说明取舍理由，不得静默忽略。\n"
    )
    return (
        "\n"
        + title
        + "\n"
        + "\n\n".join(blocks)
        + "\n"
        + guidance
        + priority
    )


def _teaching_plan_section(plan: dict | None) -> str:
    """大纲阶段已确定的本次教学决策；章节生成必须沿用。

    这里只放决策，不重复列规则：规则已由 _teaching_charter 按阶段注入一次。
    """
    if not plan:
        return ""
    lines: list[str] = []
    if plan.get("decisions"):
        lines.extend(f"- {item}" for item in plan["decisions"])
    if plan.get("task_overrides"):
        lines.extend(f"- 本次任务覆盖普通偏好：{item}" for item in plan["task_overrides"])
    if plan.get("unresolved_conflicts"):
        lines.extend(f"- 未消解的硬约束冲突（不得静默忽略）：{item}" for item in plan["unresolved_conflicts"])
    decisions = "\n".join(lines) if lines else "大纲阶段未记录额外决策：按长期教学宪章的硬性约束与本节知识性质组织内容。"
    return f"\n本次教程教学决策（落实到本节的知识组织、讲解、案例与练习）：\n{decisions}\n"


def _delivery_contract_section(contract: dict | None) -> str:
    """交付契约块：把「只包括…」这类硬性约束翻译成对交付物组成的硬规定。

    只靠「违反即不合格」的措辞约束不了交付物组成：模型会认为「写一整章讲解」不算
    违反「不要输出答案」，于是照样交付一份教程。这里把它写成可执行的结构要求。
    """
    items = (contract or {}).get("items") or []
    if not items:
        return ""
    listed = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
    ban = (
        "不写答案、解析、讲评或其它内容；题面只给题目与作答区。"
        if contract.get("forbid_answers")
        else "不写清单以外的内容。"
    )
    return (
        "\n本次交付契约（来自用户硬性约束，优先级高于常规教程结构；任一条不满足即本次交付不合格）：\n"
        f"交付物只包括以下 {len(items)} 项，顺序固定：\n{listed}\n"
        f"- 章节数必须严格等于 {len(items)}，第 i 章只交付第 i 项；不得增加讲解、复习、总结、导论或附录章节；\n"
        "- 每一项的成品就是最终交付物，不是「关于它的教程」：不要写教学原理、方法归纳或学习路径；\n"
        f"- {ban}\n"
    )


def _capability(goal) -> str:
    return level_prompt_block(getattr(goal, "capability_level", None))


_CLAUSE_SPLIT = re.compile(r"[，,；;。]")
_CLAUSE_PREFIX = re.compile(r"^\s*(?:\d+\s*[、.．)]\s*)?")


def _content_clauses(text: str, legacy_structure: "re.Pattern[str]") -> list[str]:
    """按小句（而不是整行）过滤旧结构约定，保留同一行里的内容要求。

    用户常把结构要求与内容要求写在同一句里，例如：
    「按参考材料的分章，为每一个章节生成单元检测卷，题量不限，要求知识点全覆盖」。
    整行丢弃会连带丢掉「题量不限 / 知识点全覆盖 / 难度拔高」这些真正约束内容的部分，
    模型于是只知道要出一份卷子，不知道要覆盖到什么程度。
    结构要求本身不再靠提示词表达：它已由规范快照的交付物清单（含按章拆分）确定性落实。
    """
    kept: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if not legacy_structure.search(line) and not re.search(
            r"只(?:输出|包括).*(?:试卷|答案|解析|章节)", line
        ):
            kept.append(line)
            continue
        clauses = [
            _CLAUSE_PREFIX.sub("", piece).strip()
            for piece in _CLAUSE_SPLIT.split(line)
        ]
        for clause in clauses:
            if len(clause) < 2:
                continue
            if legacy_structure.search(clause):
                continue
            if re.search(r"只(?:输出|包括).*(?:试卷|答案|解析|章节)", clause):
                continue
            kept.append(clause)
    return kept


def _hard_constraints_section(goal) -> str:
    """本次目标用户填写的「硬性约束」注入块：所有生成阶段共用。

    与长期教学画像里的硬约束（_teaching_charter）相互独立、并行生效：
    这里是用户创建目标时针对本次任务填写的强制要求，逐条满足，违反即交付不合格。
    """
    text = str(getattr(goal, "hard_constraints", "") or "").strip()
    if not text:
        return ""
    lines = "\n".join(f"- {line.strip()}" for line in text.splitlines() if line.strip())
    if not lines:
        return ""
    if _format_spec_active(goal):
        legacy_structure = re.compile(
            r"模板|排版|章节|第\s*[一二三四五六七八九十\d]+\s*章|模块|栏目|目录|"
            r"标题|格式|易错辨析|知识概要|知识速查|附加|附带|不要.*(?:教学|建议|信息)"
        )
        # 按小句过滤：同一行里的内容要求（题量、覆盖范围、难度）不能因为夹带
        # 「章节」等结构字样就整行丢弃，否则模型只知道要出卷、不知道要出到什么程度。
        content_lines = _content_clauses(text, legacy_structure)
        if not content_lines:
            return ""
        content_block = "\n".join(f"- {line}" for line in content_lines)
        return (
            "\n本次任务的内容补充（旧模板规则已停用，不是格式依据）：\n"
            f"{content_block}\n"
            "以上只用于确定内容主题、范围或事实；标题、章节、交付物、栏目、顺序和排版只能服从当前格式规范。\n"
        )
    return (
        "\n本次硬性约束（用户针对当前目标填写，必须逐条落实到最终交付内容；"
        "优先级高于常规内容组织方式，任一条不满足即本次交付不合格）：\n"
        f"{lines}\n"
        "自检要求：输出前逐条核对上述约束是否已在内容中落实；若某条与本节知识性质确实冲突，"
        "采用不违反它的替代做法，并在 note 块说明取舍理由，不得静默忽略。\n"
    )


def _materials_section(materials_text: str) -> str:
    """用户上传材料（参考资料 / 例题来源）的注入块；无材料时返回空串，保持原 prompt 不变。"""
    text = (materials_text or "").strip()
    if not text:
        return ""
    return (
        "\n用户上传的参考资料 / 例题来源（范围约束与依据；文本类文件为原始全文，"
        "PDF/DOCX 为文本抽取，图片仅登记来源）：\n"
        f"{text}\n"
        "材料使用规则：优先沿用材料中明确要求的内容、术语、任务与例题风格；"
        "不把材料未覆盖的内容伪装成材料原有结论；材料存在缺口时可以合理补充，"
        "但当用户明确要求遵循指定材料范围时不得擅自扩展到明显偏离目标的领域。"
        "若材料块明确标注「材料内容未完整注入」，必须把它视为部分材料，"
        "不得声称已审阅该文件的全部内容；可以在 uncertainties 中说明该限制。\n"
    )


def _is_guidance_goal(goal) -> bool:
    """目标绑定的快照是否是指导型规范（教程族）。"""
    from ..services.utils import is_guidance_snapshot

    return is_guidance_snapshot(jload(getattr(goal, "format_spec_snapshot", "") or "", {}))


def _is_reading_guide_goal(goal) -> bool:
    """目标绑定的快照是否是阅读教程规范（scene == reading_guide）。

    与「教程族」并列但**刻意独立**：阅读规范不进 utils.GUIDANCE_SCENES（进了会让
    authoritative_spec_dict 对无交付物的它返回 {}，节标题就不再被强制对齐成大纲章名，
    而按章注入依赖可靠的章名）。它只在这里、章节范围声明、两阶段生成三处被单独放行。
    """
    return format_specs_service.is_reading_guide(
        jload(getattr(goal, "format_spec_snapshot", "") or "", {})
    )


def _format_spec_block(stage: str, goal, deliverable: str | None = None) -> str:
    """按阶段注入格式规范；不把自由 Markdown 和全部模板重复塞进每次调用。"""
    spec = jload(getattr(goal, "format_spec_snapshot", "") or "", {})
    if not isinstance(spec, dict) or not spec.get("name"):
        return ""

    from ..services.utils import is_guidance_snapshot

    guidance = is_guidance_snapshot(spec)
    if guidance:
        # 指导型规范（教程族）：只约束写法与质量，不接管章节数与章节标题；
        # 章节结构由大纲模型按知识逻辑决定（否则会把教程写成固定模板）。
        lines = [
            f"本次格式规范（写法与质量的唯一依据，不决定章节数与章节标题）：{spec.get('name', '')}",
            "优先级：本规范 > 旧任务约定中的格式要求 > 长期画像中的教学偏好。",
        ]
    else:
        lines = [
            f"本次格式规范（冻结快照，结构、排版和交付物唯一依据）：{spec.get('name', '')}",
            "优先级：本规范 > 旧任务约定中的格式要求 > 长期画像中的教学偏好。"
            "不得把旧模板的标题、章节、栏目或排版与当前规范拼接使用。",
        ]
    if stage in {"plan", "outline", "criteria"}:
        if spec.get("output_goal"):
            lines.append(f"输出目标：{spec['output_goal']}")
        if spec.get("deliverables"):
            rows = []
            for item in spec["deliverables"]:
                status = {
                    "required": "必须",
                    "on_request": "用户明确要求时",
                    "optional": "可选",
                    "forbidden": "禁止",
                }.get(item.get("status"), item.get("status"))
                rows.append(f"- {item.get('name', '')}（{status}）")
            lines.append("交付物清单（结构性边界）：\n" + "\n".join(rows))
        if spec.get("task_overrides"):
            lines.append("本次任务覆盖项：\n- " + "\n- ".join(spec["task_overrides"]))
    if stage == "criteria" and spec.get("acceptance_criteria"):
        lines.append(f"规范验收条件：\n{spec['acceptance_criteria']}")
    if stage in {"outline", "section"} and spec.get("content_structure"):
        # content_structure 是结构模板的唯一来源；reference_examples 只作排版对照示例，
        # 不参与结构，避免两个模板字段同时生效时模型不知道听谁的。
        cs = str(spec["content_structure"])
        if guidance and stage == "outline":
            # 指导型规范：outline 只要「章级规则」（分章与章节顺序），不要节内模板，
            # 否则大纲模型会把「本章导入 / 核心概念」当成章名。
            cs = cs.split("【节内结构")[0].rstrip()
        lines.append(f"内容结构：\n{cs}")
        if (not guidance or stage == "section") and str(spec.get("reference_examples", "") or "").strip():
            lines.append(f"排版正反例（只约束写法，不改变上面的结构）：\n{spec['reference_examples']}")
    if stage in {"outline", "section"} and spec.get("forbidden_rules"):
        lines.append(f"禁止内容：\n{spec['forbidden_rules']}")
    if stage == "outline" and spec.get("custom_markdown"):
        lines.append(f"自定义补充规则：\n{spec['custom_markdown']}")
    if stage in {"section", "cheatsheet", "extra_exercises"}:
        if spec.get("target_reader"):
            lines.append(f"目标受众：{spec['target_reader']}")
        for key in ("format_rules", "required_rules", "suggested_rules", "flexible_rules"):
            if spec.get(key):
                lines.append(f"{key}：\n{str(spec[key]).strip()}")
        if spec.get("custom_markdown"):
            lines.append(f"自定义补充规则：\n{spec['custom_markdown']}")
        if stage == "section" and spec.get("acceptance_criteria"):
            lines.append(f"局部验收参照：\n{spec['acceptance_criteria']}")
    if stage == "section":
        if deliverable:
            lines.append(f"当前唯一交付物：{deliverable}")
        lines.append(
            "输出约束：\n"
            "- title 必须严格使用当前交付物名称，不得改写成教程章节标题；\n"
            "- 不要在 content 的 body 中重复输出当前交付物标题、文档级 H1、目录、“第 N 节”或教程外壳；\n"
            "- body 直接写该交付物的 Markdown 成品；内部小标题从 ### 开始；\n"
            "- 不要为了套用旧教学模板而增加总览、核心结论、前置知识、必要练习、来源或验收标准栏目；\n"
            "- 不要输出使用说明、做题方式、自检清单一类元栏目；使用提示一句话并入相关引子。"
        )
    return "\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 目标阶段

def diagnose(goal, discipline, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n"
        f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"{_tier_prompt_block(goal)}"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        "请输出 JSON：{\"benefits\": str, \"prerequisites\": str, \"alternatives\": str, "
        "\"assumptions\": str, \"uncertainties\": str, \"recommendation\": str}。\n"
        "benefits/alternatives 用编号列表；recommendation 给出明确建议（推进/缩小范围/暂缓）。"
    )
    return _system_for(goal), user


def plan(goal, discipline, materials_text: str = "") -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"该学科的常见实践形式：{discipline.practice_templates}\n"
        f"{_tier_prompt_block(goal)}"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        "输出 JSON：{\"steps\": [{\"title\": str, \"objective\": str, \"estimated_effort\": str}]}。"
        "步骤按依赖顺序，第一步必须是范围收窄与环境确认；步骤数量由目标范围决定，不固定。"
        "time_budget 是可投入总时间；estimated_effort 只表示完成该步骤所需的工作量估计（如「1–2 小时」），"
        "不要把步骤映射到具体日期或天次，不要出现「第 X 天」「每天」的表述。"
    )
    return _system_for(goal), user


def criteria(goal, discipline) -> tuple[str, str]:
    spec_mode = _format_spec_active(goal)
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"{'' if spec_mode else _tier_prompt_block(goal)}"
        f"{'' if spec_mode else _capability(goal) + chr(10)}"
        f"{_format_spec_block('criteria', goal)}"
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
    return _system_for(goal, "criteria"), user


# ---------------------------------------------------------------- 教程规划

def outline(goal, discipline, criteria_list, materials_text: str = "") -> tuple[str, str]:
    context = goal_context_text(goal)
    profile_data = parse_teaching_profile(context_text=context)
    spec_mode = _format_spec_active(goal)
    contract = None if spec_mode else delivery_contract(profile_data["rules"], context)
    if spec_mode:
        task = (
            "\n任务：严格按当前格式规范生成内部交付结构。每个允许交付物对应一个 section，"
            "title 必须逐字使用该交付物名称；不得生成教程导学、知识讲解、复习总结、附录或其它章节。\n"
            + (
                "若规范没有交付物清单，则按规范的分章规则与知识自身逻辑拆分 section（教程类规范："
                "一章一节，章名即 section 标题）；每节只产出本节自己的内容，禁止提前写入其它节的内容。\n"
                if (_is_guidance_goal(goal) or _is_reading_guide_goal(goal))
                else "若规范没有交付物清单，则按用户本次明确要求的交付单元拆分 section（例如每章试卷、"
                "答案、判断题各一节）；每节只产出本节自己的内容，禁止提前写入其它节的内容。\n"
            )
            + "输出 JSON：{\"teaching_plan\": {\"rules_applied\": [], \"decisions\": [], "
            "\"task_overrides\": [], \"unresolved_conflicts\": []}, "
            "\"sections\": [{\"title\": str, \"purpose\": str, \"content_type\": \"application\", "
            "\"summary\": str, \"criteria_ids\": [str]}]}。\n"
            "purpose 只说明该交付物用途；criteria_ids 使用给定验收标准 id。\n"
            "篇幅纪律：rules_applied / decisions 每条不超过 60 字、合计不超过 8 条；"
            "purpose / summary 各不超过 40 字；整份 JSON 控制在 1500 字以内，"
            "确保单次输出不被截断（截断会导致整份 JSON 无法解析、本次生成作废）。\n"
        )
    else:
        task = ""
    if spec_mode:
        user = (
            f"学科：{discipline.display_name}\n"
            f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
            f"已确认的验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
            f"{_hard_constraints_section(goal)}"
            f"{_materials_section(materials_text)}\n"
            f"{_format_spec_block('outline', goal)}"
            f"{_teaching_charter('outline', {'rules': profile_data['rules']}, goal)}"
            f"{task}"
        )
        return _system_for(goal, "outline"), user
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"已确认的验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"{_tier_prompt_block(goal)}"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        f"{_format_spec_block('outline', goal)}"
        f"{_teaching_charter('outline', {'rules': profile_data['rules']}, goal)}"
        f"{_delivery_contract_section(contract)}"
        "\n任务：为教程设计章节大纲。这是一次内部教学规划，请先在心里完成以下判断再输出：\n"
        "1. 达成目标必须包含哪些核心知识？哪些基础知识是理解核心内容所必需的（支撑知识）？\n"
        "2. 哪些内容只需简要介绍、放入速查清单或不讲（扩展知识按需取舍）？\n"
        "3. 各个核心知识点适合什么教学方式（概念原理 / 方法技巧 / 工具操作 / 事实记忆 / 综合应用）？\n"
        "4. 支撑知识安排在读者真正需要它的位置，避免重复讲解。\n\n"
        "输出 JSON：{\"teaching_plan\": {\"rules_applied\": [str], \"decisions\": [str], "
        "\"task_overrides\": [str], \"unresolved_conflicts\": [str]}, "
        "\"sections\": [{\"title\": str, \"purpose\": str, \"content_type\": str, "
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
        "- 不强制规定必须有变式章节或复盘章节：归纳、总结与练习按知识特点安排在最合适的位置；\n"
        "- teaching_plan 必须把画像规则转化为本次可执行的教学决策；rules_applied 只列本教程实际采用的规则；"
        "本次任务的明确特殊要求可覆盖普通偏好，写入 task_overrides；"
        "硬约束冲突无法合理消解时写入 unresolved_conflicts，并采用不违反任一已知硬约束的可行方案。"
    )
    return _system_for(goal, "outline"), user


def _companion_names_section(companion_names: list[str] | None) -> str:
    """列出本次确定会交付的配套文件名，模型只能按这些名字写双链。"""
    names = [str(name).strip() for name in (companion_names or []) if str(name).strip()]
    if not names:
        return ""
    lines = "\n".join(f"- [[{name}]]" for name in names)
    return (
        "\n本次同时生成的配套文件（统一文件名；双链目标只能是下列文件名，不引用就留空）：\n"
        f"{lines}\n"
    )


def _tutorial_file_name(goal) -> str:
    return f"{safe_obsidian_filename(goal.title)}-教程"


def _retry_violation_block(retry_violations: list[str] | None) -> str:
    """上一稿违反硬性约束时的定向修正指令；只改被违反的部分，不重写整章。"""
    texts = [str(item).strip() for item in (retry_violations or []) if str(item).strip()]
    if not texts:
        return ""
    lines = "\n".join(f"- {text}" for text in texts)
    return (
        "\n上一稿违反了以下用户硬性约束，本次必须修正后重新输出完整 JSON：\n"
        f"{lines}\n"
        "修正要求：只调整违反约束的地方，保留其余内容的教学价值与结构；"
        "输出格式与字段要求不变。\n"
    )


def _truncation_block(truncated: bool) -> str:
    """上一稿因超出单次输出上限被截断：明确要求压缩篇幅，否则原样重发必然再被截断。"""
    if not truncated:
        return ""
    return (
        "\n上一稿因超出单次输出长度上限被截断，JSON 不完整、无法解析。本次必须在保证字段"
        "结构完整的前提下压缩篇幅：\n"
        "- 正文（content 各块 body）合计控制在 12000 字以内，只留讲解主线；\n"
        "- 不逐字照抄材料原文，不复述前面已讲过的内容；\n"
        "- 宁可少放例题、少给表格，也要保证输出被完整生成。\n"
    )


_TEACHING_TASK = (
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
    "例题（克制原则）：\n"
    "- 数量由知识难度、教学需要与能力层级决定，不设固定数量；没有教学价值就不加；\n"
    "- 例题优先选有代表性、信息密度高的；篇幅与其教学价值相称，不得挤占核心讲解；\n"
    "- 方法性例题体现方法选择与关键决策，不只要计算过程；工具操作用简短真实可执行的示例；\n"
    "- 巩固练习由独立的额外练习文件承载（不由本章生成）；正文不设练习栏目。\n"
    "不要把完整教学规划过程写进输出；输出即教程正文本身。\n\n"
    + _NO_META_SECTIONS + "\n"
)


_CHAPTER_DELIVERABLE_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十]+\s*章)"        # 章号
    r"\s*([^（(]*?)"                                        # 章名
    r"\s*(?:单元检测卷|单元测验卷|单元试卷|检测卷|测验卷|测试卷|自测卷|模拟卷|练习卷|试卷)?$"
)


def _chapter_scope_block(deliverable: str, reading_guide: bool = False) -> str:
    """按章交付时的范围声明：只覆盖本章、只取材本章。

    交付物名形如「第 3 章 矩阵 单元检测卷」；范围里只保留章号与章名，
    否则模型会把「单元检测卷」当成要覆盖的知识点。

    ``reading_guide`` 为真时用导读版措辞。**这不是文风偏好，是语义相反**：
    试卷 / 练习要「不得跨章综合」（每章自成一卷，跨章就泄题）；
    而阅读导读的规范明确要求「思想关联：与其他章节的关联」「识别不同章节之间的
    思想联系，尤其是跨章节的概念和论证」—— 直接照搬「不得跨章综合」会把规范
    自己定义的核心能力禁掉。
    """
    match = _CHAPTER_DELIVERABLE_RE.match(str(deliverable or "").strip())
    if not match:
        return ""
    chapter = f"{match.group(1)} {match.group(2)}".strip()
    if not match.group(2).strip():
        chapter = match.group(1).strip()
    if reading_guide:
        return (
            f"本次范围：只导读「{chapter}」这一章。\n"
            f"- 原文摘录、概念详解、论证分析与难点辨析只能取材于材料中该章的正文；\n"
            "- 需要指出与其它章节的思想联系时，只写「与第 N 章的 X 概念相关」这类定位性提示，\n"
            "  不展开讲解其它章的内容，也不替其它章下结论（那是那一节自己的任务）；\n"
            "- 全书层面的评价（思想史地位、学界争鸣、总体贡献）留给全书层章节，本节不写。\n"
        )
    return (
        f"本次范围：只覆盖「{chapter}」这一章。"
        "命题只能取材于材料中该章（含其各节习题）涉及的知识点；"
        "其它章节的内容一律不得出现在本节，也不得跨章综合。\n"
    )


# 试卷类交付物的名词判据：直接复用 format_specs._UNIT_NOUN_RE，只有一处词表。
# 卷面自检、按章「自成一卷」、_deliverable_task 三处都靠它识别「这一节是不是一份卷」。
# 曾在本文件另写一份「试卷|练习卷|训练卷|测验|检测卷」，漏了「模拟卷」「自测卷」，
# 于是这两类合法卷名会静默丢掉卷面自检（题号重置、声明题量与实际不符无人管）。
# 追加「训练卷」「测验」是为了兼容旧卷名；「单元卷」这类裸词不在词表里，规范不得允许。
_EXAM_NOUN_RE = re.compile(format_specs_service._UNIT_NOUN_RE.pattern + r"|训练卷|测验")


def _exam_self_check() -> str:
    """试卷类交付物的确定性自检要求（两条提示词路径共用）。

    实测发现模型会在「试卷说明」里声明 20 题却写出 25 题，或每个题型都从 1 重新
    编号，导致答案区题号与题面对不上。这类错误无法靠渲染层修复，只能在出题时约束。
    """
    return (
        "卷面自检（必须满足，否则本卷不可用）：\n"
        "1. 题号在全卷内连续递增，从 1 开始；不得在每个题型重新从 1 开始编号；\n"
        "2. 卷面说明里声明的总题数、各题型题数与分值之和，必须与实际写出的题目数量和分值完全一致；\n"
        "3. 先确定题量与分值再落笔，写完逐条核对上述两项，不要出现「声明 20 题、实际 25 题」的情况；\n"
        "4. 参考答案按题号一一对应，不缺题、不串号；\n"
        "5. 分值之和必须等于卷面声明的满分；\n"
        r"6. 数学表达式一律使用 LaTeX，且分隔符只用 $...$（行内）与 $$...$$（独立成行）；"
        r"禁止使用 \(...\) 与 \[...\] 这两种反斜杠分隔符（Obsidian 会把反斜杠当转义吃掉，公式无法渲染）。"
        "禁止用 Unicode 数学字符代替公式（如 ℝ、ℕ、ⁿ、ᵀ、⁻¹、∈、∪、∩、⊆、×、≤、≠、∅），"
        "矩阵用 \\begin{pmatrix}…\\end{pmatrix}，分式用 \\dfrac{…}{…}；\n"
        "7. 全卷数学风格必须一致：不得一部分章节用 LaTeX、另一部分用 Unicode 字符。"
    )


def _self_contained_paper_block() -> str:
    """按章交付的单元卷是「自成一卷」的成品：卷末必须自带参考答案。

    与交付物清单里单列「参考答案」的试卷规范不同：按章拆分后每章就是一份独立可自测的
    卷子，没有配套的答案交付物。实测 7 章里有 6 章自带答案、1 章不带，同一份文档内
    形态不一致，所以这里明确要求统一形态，而不是留给模型逐章随机决定。
    """
    return (
        "本卷是自成一卷的成品（没有单独的答案交付物），因此卷末必须附「参考答案」小节：\n"
        "- 覆盖全部题号，选择题给出正确项，判断题给出对错，解答/计算/综合题给出关键步骤与结论；\n"
        "- 答案区不得遗漏任何一题，题号与题面一一对应；\n"
        "- 答案只在卷末集中给出，题面部分不得夹带答案、提示或解题过程。\n"
    )


def _deliverable_task(deliverable: str) -> str:
    """交付物任务的写法：不写讲解章节，直接产出这一项成品。"""
    if re.search(r"参考答案|答案", deliverable):
        shape = (
            "只输出答案与必要依据，不重新粘贴整套试题；题号必须与对应试卷一一对应。"
            "若答案需要解析，只保留判分或核对所需的关键步骤。"
        )
    elif "解析" in deliverable:
        shape = "只输出规定范围内的难题解析，不写泛化复习建议，不扩写成教程。"
    elif "分析" in deliverable:
        shape = "只给简要分析（结构、考点分布、难度分布），不展开教学原理。"
    elif re.search(_EXAM_NOUN_RE, deliverable):
        shape = (
            "先给卷面说明（时长、满分、题型与分值分布），再给完整可做的题面与作答区；"
            "题目可独立判分；不写答案、解析或旧模板要求的其它栏目。\n"
            + _exam_self_check()
        )
    else:
        shape = "按这一项在真实场景里的形态直接组织成品，不写成关于它的教程。"
    return (
        f"任务：本次要交付的是成品「{deliverable}」，不是教学讲解章节。\n"
        f"{_chapter_scope_block(deliverable)}"
        f"{shape}\n"
        "禁止：写教学讲解、知识梳理、方法归纳、复习总结；写交付清单以外的内容。\n"
        "content 块只是渲染容器：用 text 写卷面说明、用 table 排分值分布或答题区、用 example 放题面，"
        "按交付物的真实形态组合，不要套教学栏目。\n"
        "purpose 写这一项交付物的用途；content_type 固定为 application。\n\n"
    )


def section(
    goal, discipline, outline_item, criteria_list, prior_titles, materials_text: str = "",
    companion_names: list[str] | None = None, retry_violations: list[str] | None = None,
    truncated: bool = False,
) -> tuple[str, str]:
    plan = outline_item.get("_teaching_plan") if isinstance(outline_item, dict) else None
    if not plan:
        plan = normalize_teaching_plan({}, parse_teaching_profile(context_text=goal_context_text(goal)))
    outline_for_prompt = (
        {key: value for key, value in outline_item.items() if key not in ("_teaching_plan", "_deliverable")}
        if isinstance(outline_item, dict)
        else outline_item
    )
    deliverable = outline_item.get("_deliverable") if isinstance(outline_item, dict) else None
    if _format_spec_active(goal):
        section_deliverable = str(
            deliverable or (outline_item.get("title", "") if isinstance(outline_item, dict) else "")
        ).strip()
        # 试卷类交付物追加卷面自检要求（规范模式的提示词路径不经过 _deliverable_task）
        is_exam_paper = bool(re.search(_EXAM_NOUN_RE, section_deliverable))
        exam_self_check_block = _exam_self_check() + "\n" if is_exam_paper else ""
        # 按章拆分时每章自成一卷（无单独的答案交付物）：卷末必须自带参考答案
        snapshot_spec = jload(getattr(goal, "format_spec_snapshot", "") or "", {})
        if is_exam_paper and isinstance(snapshot_spec, dict) and snapshot_spec.get("chapter_split"):
            exam_self_check_block += _self_contained_paper_block()
        user = (
            f"学科：{discipline.display_name}\n"
            f"学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
            f"当前交付物：{section_deliverable or '按格式规范生成'}\n"
            f"{_chapter_scope_block(section_deliverable, format_specs_service.is_reading_guide(snapshot_spec))}"
            f"本章大纲：{json.dumps(outline_for_prompt, ensure_ascii=False)}\n"
            f"相关验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
            f"{_hard_constraints_section(goal)}"
            f"{_materials_section(materials_text)}\n"
            f"{_format_spec_block('section', goal, section_deliverable)}"
            f"{_teaching_charter('section', plan, goal)}"
            f"{_retry_violation_block(retry_violations)}"
            f"{_truncation_block(truncated)}"
            "\n任务：直接生成当前交付物的成品，不得套用旧教程模板。\n"
            "只输出当前交付物自己的内容；其它章节/交付物的内容一律不写，也不得提前给出后文的答案或题目。\n"
            f"{exam_self_check_block}"
            "输出 JSON：{\"title\": str, \"purpose\": str, \"content_type\": \"application\", "
            "\"content\": [{\"type\": \"text|key_point|formula|steps|table|example|comparison|"
            "method_summary|diagram|memory|note\", \"title\": str, \"body\": str}]}。\n"
            "content 的每个 body 必须是可直接拼接的纯 Markdown；标题层级最高从 ### 开始；"
            "不得重复当前交付物名称、文档标题、目录、“第 N 节”或任何教程外壳。"
            "不要输出 key_takeaways/common_errors/prerequisite_refs/exercises 字段（固定栏目已退役）；"
            "规范确需的结论或易错提醒，直接写进 content 块正文。\n"
            + _NO_META_SECTIONS
        )
        return _system_for(goal, "section"), user
    task_block = _deliverable_task(str(deliverable)) if deliverable else _TEACHING_TASK
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"已学过章节：{prior_titles}\n"
        f"本章大纲：{json.dumps(outline_for_prompt, ensure_ascii=False)}\n"
        f"相关验收标准：{json.dumps(criteria_list, ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"{_tier_prompt_block(goal)}"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        f"{_format_spec_block('section', goal)}"
        f"{_teaching_charter('section', plan, goal)}\n"
        f"{_teaching_plan_section(plan)}\n"
        f"{_companion_names_section(companion_names)}"
        f"{_retry_violation_block(retry_violations)}"
        f"{_truncation_block(truncated)}"
        f"{WIKILINK_RULE}"
        f"{task_block}"
        "输出 JSON：\n"
        "{\"title\": str,\n"
        " \"purpose\": str,                                  # 本章在学习路径中的作用（沿用或细化大纲）\n"
        " \"content_type\": str,                             # concept / method / tool / fact / application / mixed\n"
        " \"content\": [                                     # 正文内容块，按合理教学顺序组合；块类型只能取：\n"
        "     {\"type\": \"text\"|\"key_point\"|\"formula\"|\"steps\"|\"table\"|\"example\"|\"comparison\""
        "|\"method_summary\"|\"diagram\"|\"memory\"|\"note\",\n"
        "       \"title\": str,                               # 块标题（可以是空串）\n"
        "       \"body\": str}],                              # Markdown 正文\n"
        " \"mapping_criteria\": []}                                # 验收映射由系统回填，输出空数组即可\n"
        "只输出上述字段；不要输出目录、来源、引用列表或其他元信息栏；\n"
        "不要输出 key_takeaways/common_errors/prerequisite_refs/exercises 字段（固定栏目已退役）。\n"
        + _NO_META_SECTIONS
        + "内容块规范：\n"
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
    return _system_for(goal, "section"), user


# ---------------------------------------------------------------- 配套文件

def cheatsheet(
    goal, discipline, outline_items, materials_text: str = "",
    retry_violations: list[str] | None = None,
) -> tuple[str, str]:
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"教程大纲：{json.dumps(outline_items, ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"{_tier_prompt_block(goal)}"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        f"{_format_spec_block('cheatsheet', goal)}"
        f"{_teaching_charter('cheatsheet', None, goal)}"
        f"{_retry_violation_block(retry_violations)}\n"
        f"统一文件名（反向双链只能使用）：[[{_tutorial_file_name(goal)}]]\n"
        f"{WIKILINK_RULE}"
        "\n任务：为教程生成配套的「知识速查」文件。只放适合集中查阅、有长期复用价值的材料，例如：\n"
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
    return _system_for(goal), user


def extra_exercises(
    goal, discipline, outline_items, materials_text: str = "",
    retry_violations: list[str] | None = None,
    exercise_spec: dict | None = None,
) -> tuple[str, str]:
    """额外练习配套文件：排版与结构完全交给「练习生成规范」，按教程大纲分节。

    exercise_spec 由调用方从 format_specs.get_exercise_spec_dict 传入；
    为空时退化为无规范生成（保持旧行为可运行）。
    """
    spec = exercise_spec if isinstance(exercise_spec, dict) and exercise_spec.get("name") else {}
    chapter_titles = [str(i.get("title", "")).strip() for i in outline_items or [] if isinstance(i, dict)]
    chapter_titles = [x for x in chapter_titles if x]
    spec_lines: list[str] = []
    if spec:
        spec_lines.append(f"排版与结构唯一依据：{spec.get('name', '')}（练习生成规范，逐字遵守）")
        for key, label in (
            ("content_structure", "内容结构"),
            ("format_rules", "format_rules"),
            ("required_rules", "required_rules"),
            ("forbidden_rules", "禁止内容"),
            ("reference_examples", "排版正反例"),
            ("custom_markdown", "自定义补充规则"),
        ):
            if str(spec.get(key, "") or "").strip():
                spec_lines.append(f"{label}：\n{str(spec[key]).strip()}")
    spec_block = ("\n".join(spec_lines) + "\n") if spec_lines else ""
    user = (
        f"学科：{discipline.display_name}\n学习目标：{json.dumps(_goal_ctx(goal), ensure_ascii=False)}\n"
        f"教程大纲（分节依据）：{json.dumps(chapter_titles, ensure_ascii=False)}\n"
        f"{_hard_constraints_section(goal)}"
        f"{_tier_prompt_block(goal)}"
        f"{_capability(goal)}\n"
        f"{_materials_section(materials_text)}\n"
        f"{spec_block}"
        f"{_retry_violation_block(retry_violations)}\n"
        f"统一文件名（反向双链只能使用）：[[{_tutorial_file_name(goal)}]]\n"
        f"{WIKILINK_RULE}"
        "\n任务：为教程生成独立的「额外练习」文件，用于强化、巩固、检验和迁移，"
        "不是简单复制教程正文中的例题。\n"
        "分节规则（覆盖练习规范里的「按材料分章」）：\n"
        "- 一节 = 教程大纲的一章，节数与顺序逐字等于上面给出的大纲；不得合并、增删或改名；\n"
        "- 节标题逐字使用大纲章名；章标题由系统输出，正文不写 # 或 ## 级标题；\n"
        "- 每节内部完全按练习规范的节内结构走（### 一、易错辨析 / ### 二、训练 / ### 参考答案，"
        "题型 ####，题号在本节内从 1 连续，各节独立编号）；\n"
        "- 每节只出一个 content 块，块 title 逐字等于本节章名。\n"
        "其它要求：\n"
        "- 题目数量克制：按知识难度与能力层级决定，避免无意义堆题；\n"
        "- 不逐题标注难度、分值、考点或验收标准（练习规范明令禁止）；\n"
        "- 不写「使用说明 / 做题方式 / 自检清单」一类元栏目。\n"
        "输出：直接输出整份 Markdown 成品（不要 JSON、不要代码围栏包裹）：\n"
        "第一行写 `# {教程名} · 额外练习` 形式的文档标题，随后按节输出；"
        "每节的正文从 `### 一、易错辨析` 开始。"
    )
    return _system_for(goal, "extra_exercises"), user
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
        f"{_hard_constraints_section(goal)}"
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


def format_spec_match(requirement: str, candidates: list[dict]) -> tuple[str, str]:
    system = (
        "你是 AI Edu 的格式规范匹配器。只输出 JSON；不输出 JSON 以外的任何文本。"
        "只判断用户当前任务最适合哪个候选规范；不要考虑候选之外的知识。"
        "如果没有任何候选显著改变交付物结构，返回空 ID。"
    )
    user = (
        f"用户任务：{requirement}\n"
        f"候选规范（只含摘要）：{json.dumps(candidates, ensure_ascii=False)}\n\n"
        "输出 JSON：{\"format_spec_id\": str, \"confidence\": float, \"reason\": str}。"
        "confidence 0-1；低于 0.6 或任务只是解释/复习且不是生成交付物时，format_spec_id 返回空串。"
    )
    return system, user


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


# ---------------------------------------------------------------- 画像建议

def user_profile_suggestion(context: dict) -> tuple[str, str]:
    system = (
        "你是 AI Edu 的教学画像整理助手。只输出 JSON；不输出 JSON 以外的任何文本。"
        "只基于用户提供的学习目标与反馈，不推断能力标签，不编造偏好。"
    )
    user = (
        f"学习记录：{json.dumps(context, ensure_ascii=False)}\n\n"
        "请把用户已确认完成的学习和反馈整理成一份候选长期画像。要求：\n"
        "- 只提取有重复证据、能指导未来教学的稳定要求；\n"
        "- 不给用户贴未经证实的能力标签；\n"
        "- 区分硬约束与偏好，但不擅自把普通偏好升级为硬约束；\n"
        "- profile_text 用用户能看懂的自然语言，一次一行；\n"
        "- evidence 说明依据；如果证据不足，就在 notes 里说明，不要硬凑规则。"
        "\n\n输出 JSON：{\"summary\": str, \"profile_text\": str, \"evidence\": str, \"notes\": str}。"
    )
    return system, user
