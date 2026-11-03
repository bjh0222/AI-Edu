# -*- coding: utf-8 -*-
"""试卷 / 练习卷的确定性卷面校验与自动修复（L0）。

设计依据（不是新增规则，是把规范里已经写死的验收标准变成代码）：

``format_specs._EXAM_ACCEPTANCE`` 定义了 11 条试卷验收标准，``_EXAM_FORBIDDEN_RULES``
定义了 14 条禁止项，其中 10 条以上是**纯机械可判定**的账目与排版事实。
此前它们只存在于提示词里（``prompts._exam_self_check``），靠模型自觉核对——实测
``微积分期中冲刺-教程.md`` 五套卷有 4 套复现「各行分值之和 96 ≠ 合计 100」，
根因是规范主模板自己的示例表就算错了，模型忠实照抄。

结论与 ADR-015 / ADR-018 一致：**结构由确定性规则决定，不靠模型自觉**。
账目类错误（题号、分值、题量、集合一致性）用代码判定；能自动修的直接修，
不能修的报 issue。本模块零模型调用、零 token。

与渲染层的关系：``tutorials._render_deliverable_blocks`` 只做标题层级归一，
不校验账目。本模块在**落库前**跑，因此修复能进入导出与后续版本。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 允许的题型小节名（与 format_specs._EXAM_FORMAT_RULES 的枚举逐字一致）。
# 材料里给了题型划分时规范允许逐字沿用（见 _EXAM_SUGGESTED_RULES），
# 因此「非法题型名」只在**没有任何材料题型依据**时才报，见 _flag_illegal_types。
ALLOWED_TYPES = ("选择题", "判断题", "填空题", "解答题", "证明题", "综合题")

# 客观题：答案只给结果、不给解析（_EXAM_REQUIRED_RULES 的答案详略分级）
OBJECTIVE_TYPES = ("选择题", "判断题", "填空题")

# 题型后留白行数（_EXAM_FORMAT_RULES 的固定表）
BLANK_LINES = {"判断题": 0, "选择题": 2, "填空题": 1, "解答题": 3, "证明题": 3, "综合题": 4}

# 卷内元栏目 / 教学栏目：forbidden 明令禁止出现在卷内
# 卷内元栏目 / 教学栏目 / 自拟包裹标题：forbidden 明令禁止出现在卷内。
# **答案小节的自拟名不在这里**（「参考答案与评分说明」「选择题答案」等）：它们是
# E002「答案小节名自拟」，修复方式是改名或并入唯一的参考答案小节，绝不能删标题行——
# 删掉答案标题会让整段答案失去归属，实测会把第七套的答案区抹成孤儿正文。
_META_SECTION_RE = re.compile(
    # 名称后可带「（全卷）」「(整卷)」这类范围后缀：实测出现过「概念标注（全卷）」，
    # 不容忍后缀会让这条 forbidden 漏判。
    r"^(概念标注|知识概要|易错点归纳|考点分布|体例说明|试卷说明|卷面说明|"
    r"试卷正文|试卷正文与参考答案|试卷)"
    r"(?:[（(][^（）()]{0,12}[)）])?$"
)

# 占位文字：forbidden 明令禁止（留白只能用空行）
_PLACEHOLDER_RE = re.compile(
    r"(作答区域|答题位置|请在此作答|请在此处作答|解\s*[：:]|答题区|作答区)"
)

# 题号：规范要求「**n.**」加粗起行 + 全角分值括注
_Q_BOLD_RE = re.compile(r"^\*\*(\d+)\.\*\*\s*(.*)$")
_Q_BARE_RE = re.compile(r"^(\d+)[\.、]\s*(.*)$")
_SCORE_RE = re.compile(r"^（\s*(\d+)\s*分\s*）")
_ANS_NUM_RE = re.compile(r"\*\*(\d+)\.\*\*")

# 答案小节标题：规范只允许「### 参考答案」，但实测出现过 5 种写法
# （参考答案 / 参考答案与评分说明 / 参考答案与诊断说明 / 选择题答案 / 判断题答案 …）。
# 识别必须覆盖这些变体，否则答案区不被认成答案区，答案会被当成题目解析：
# 实测第三套因此把 18 个答案号误当题号，报出「题号重复 1..18」与 40 题缺分值的假阳性。
_ANSWER_HEADING_RE = re.compile(r"^(参考答案|答案)")
# 「选择题答案」这类题型 + 答案后缀
_SUFFIX_ANSWER_RE = re.compile(
    r"(?:选择题|判断题|填空题|解答题|证明题|综合题|计算题|简答题|名词解释)答案$"
)
# 包裹型标题：既含题目又含答案（「试卷正文与参考答案」）。
# 这类标题**不能**把解析器切进答案区，否则它下面的全部题目都会被当成答案。
_WRAPPER_HEADING_RE = re.compile(r"(试卷|正文|全部)")


def is_answer_heading(name: str) -> bool:
    """归一化后的小节名是否开启「参考答案」区。"""
    text = str(name or "").strip()
    if not text:
        return False
    if _WRAPPER_HEADING_RE.search(text) and not _ANSWER_HEADING_RE.match(text):
        return False
    return bool(_ANSWER_HEADING_RE.match(text) or _SUFFIX_ANSWER_RE.search(text))

# 分值分布表
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\|[\s\-|:]+\|\s*$")

# 卷面说明引子
_LEAD_RE = re.compile(r"满分\s*(\d+)\s*分.*?共\s*(\d+)\s*题")


@dataclass
class Violation:
    """一条确定性违规。``code`` 见模块底部 CODES 表。"""

    code: str
    rule: str
    # 判定依据：指向规范里的具体条文，让「为什么算违规」可回溯到规范而非代码私货
    basis: str
    detail: str
    auto_fixable: bool = False
    fixed: bool = False

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.code, "blocking")

    @property
    def blocking(self) -> bool:
        """未修复且属 blocking 级才算阻塞交付（已修好的不该再拦）。"""
        return self.severity == "blocking" and not self.fixed

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "rule": self.rule,
            "basis": self.basis,
            "detail": self.detail,
            "auto_fixable": self.auto_fixable,
            "fixed": self.fixed,
            "severity": self.severity,
        }


@dataclass
class ExamQuestion:
    number: int
    score: int | None
    kind: str          # 所属题型小节名
    stem: str          # 题干首行（去题号与分值）
    bold: bool         # 题号是否为规范的加粗形式
    sub_items: int = 0 # 小题 (1)(2) 数


@dataclass
class ExamPaper:
    """解析出的一份卷（= 一个章节 / section）。"""

    title: str = ""
    lead_total: int | None = None       # 卷面说明声明的满分
    lead_count: int | None = None       # 卷面说明声明的题量
    table: list[dict] = field(default_factory=list)   # 分值分布表数据行
    table_total: dict | None = None                   # 合计行
    questions: list[ExamQuestion] = field(default_factory=list)
    type_sections: list[str] = field(default_factory=list)   # 题型小节名（按出现顺序）
    answer_numbers: list[int] = field(default_factory=list)
    # 题号 → 参考答案文本（跨卷一致性检查要用，见 E018）
    answers: dict[int, str] = field(default_factory=dict)
    # 题号 → 题干块全部行（解析选项要用，见 _resolve_choice_answer）
    blocks: dict[int, list[str]] = field(default_factory=dict)
    # 题号 → 该题之后的空行数（E013 留白检查）
    trailing_blanks: dict[int, int] = field(default_factory=dict)
    # 「### 参考答案」本名出现次数（规范要求有且仅有一次）
    answer_heading_count: int = 0
    # 自拟答案小节名（「选择题答案」「参考答案与评分说明」等）：属 E002，不是 E009
    variant_answer_headings: list[str] = field(default_factory=list)
    meta_sections: list[str] = field(default_factory=list)
    has_table: bool = False


CODES = {
    "E001": ("题型小节名不在规范枚举内", "_EXAM_FORBIDDEN_RULES: 禁止自拟题型名"),
    "E002": ("答案小节标题不是「参考答案」", "_EXAM_FORBIDDEN_RULES: 禁止自拟答案小节名"),
    "E003": ("题号未用加粗「**n.**」形式", "_EXAM_ACCEPTANCE 第 8 条"),
    "E004": ("题目缺「（X 分）」分值括注", "_EXAM_ACCEPTANCE 第 8 条"),
    "E005": ("题号不从 1 连续或有重复", "_EXAM_ACCEPTANCE 第 6 条"),
    "E006": ("参考答案题号集合与题面不一致", "_EXAM_ACCEPTANCE 第 6 条"),
    "E007": ("卷面说明声明题量与实际不符", "_EXAM_ACCEPTANCE 第 7 条"),
    "E008": ("分值分布表账目不自洽（乘积 / 小计 / 合计 / 满分）", "_EXAM_ACCEPTANCE 第 7 条"),
    "E009": ("卷内出现元栏目或教学栏目", "_EXAM_FORBIDDEN_RULES: 禁止概念标注等栏目"),
    "E010": ("题型小节顺序与分值分布表不一致", "_EXAM_ACCEPTANCE 第 5 条"),
    "E011": ("正文出现 # 或 ## 级标题", "_EXAM_ACCEPTANCE 第 4 条"),
    "E012": ("客观题参考答案给了步骤或解析", "_EXAM_ACCEPTANCE 第 10 条"),
    "E014": ("卷内出现「作答区域」等占位文字", "_EXAM_FORBIDDEN_RULES: 留白只能用空行"),
    "E015": ("答案区泄漏不确定性表述（需核验 / 待定）", "答案必须确定，不得交付存疑结论"),
    "E016": ("题面分值括注之和与分值分布表不符", "_EXAM_ACCEPTANCE 第 7 条"),
    "E013": ("题后留白行数与题型不匹配", "_EXAM_FORMAT_RULES: 留白行数按题型固定"),
    "E017": ("同一母题在多份卷中重复出现", "_EXAM_SUGGESTED_RULES: 避免重复考查"),
    "E018": ("同一母题在不同卷给出不同答案", "答案必须唯一确定，同题不得多解"),
}


def _track_answer_state(line: str, in_answer: bool) -> tuple[bool, bool, str]:
    """标题行如何影响「是否在参考答案区」的状态机。

    全模块**只有这一份**判定，parse_paper 与所有修复函数共用。此前每个修复函数各自
    写了一遍 ``in_answer = is_answer_heading(name)``，于是「答案区一旦开启就持续到
    本卷结束」这条规则只在解析器里生效、在修复器里不生效：实测第三套的答案区里夹了
    一个「#### 概念标注（全卷）」元栏目，修复器据此关掉答案区，把其后 18 条答案当成
    题目重新编号成 19..36，第二轮修复因此不幂等。

    返回 ``(is_heading, new_in_answer, normalized_name)``。
    """
    m = re.match(r"^(#{1,6})\s*(.*)$", line.strip())
    if not m:
        return False, in_answer, ""
    name = _normalize_heading(m.group(2))
    # 规范明令「答案只在卷末集中给出，题面部分不得夹带答案」，所以答案区一旦开启，
    # 后续任何标题都不再关闭它——包括夹在答案区里的元栏目小节。
    return True, (in_answer or is_answer_heading(name)), name


def split_answer_line(line: str) -> list[tuple[int, str]]:
    """把答案行拆成 (题号, 答案文本)。

    规范的答案区把客观题答案压在同一行：``**1.** A　**2.** C　**3.** A　**4.** B``。
    必须按题号切分而不是整行归给第一个题号，否则跨卷一致性检查（E018）拿不到
    逐题答案，只能比对整行文本，同题不同卷会因排版差异而误判。
    """
    text = str(line or "").strip()
    if not text:
        return []
    marks = list(_ANS_NUM_RE.finditer(text))
    if not marks:
        m = _Q_BARE_RE.match(text)
        return [(int(m.group(1)), m.group(2).strip())] if m else []
    out: list[tuple[int, str]] = []
    for i, mo in enumerate(marks):
        start = mo.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((int(mo.group(1)), text[start:end].strip(" \u3000")))
    return out



# ---------------------------------------------------------------- 解析

def _cell(text: str) -> str:
    return text.strip()


def _is_code_fence(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("```") or s.startswith("~~~")


def parse_paper(markdown: str, title: str = "") -> ExamPaper:
    """把一份卷的 Markdown 解析成结构化对象。

    解析容错原则：这份卷子的实测形态极不统一（题型小节可能是 ### 或 ####、
    可能带「第 I 部分：」前缀、答案小节名有 5 种写法），所以解析器**不假设
    格式正确**——它要能从错的卷子里把事实抽出来，校验器才有东西可判。
    """
    paper = ExamPaper(title=title)
    lines = str(markdown or "").split("\n")

    current_type: str = ""
    in_answer = False
    in_fence = False
    last_q: ExamQuestion | None = None

    for raw in lines:
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if not stripped:
            continue

        # ---- 标题行 ----
        is_heading, new_in_answer, name = _track_answer_state(line, in_answer)
        if is_heading:
            if not name:
                in_answer = new_in_answer
                continue
            if is_answer_heading(name):
                # 只有**严格等于**「参考答案」才计入 answer_heading_count。
                # 这里不能用 _ANSWER_HEADING_RE.match：它是前缀匹配，
                # 「参考答案与评分说明」「参考答案与诊断说明」都会命中，于是这些
                # 规范明令禁止的自拟名（_EXAM_FORBIDDEN_RULES：「只能叫 ### 参考答案」）
                # 被当成合规名计入，E002 一条都不报——实测漏检。
                if name == "参考答案":
                    paper.answer_heading_count += 1
                else:
                    paper.variant_answer_headings.append(name)
            in_answer = new_in_answer
            # 答案区一旦开启就持续到本卷结束，**任何**后续标题都不再关闭它。
            # 规范明令「答案只在卷末集中给出，题面部分不得夹带答案」，所以答案小节
            # 之后不可能再出现题面。这条必须无条件，不能只豁免答案小节：实测第三套
            # 的答案区里夹了一个「#### 概念标注（全卷）」元栏目，一旦它把 in_answer
            # 关掉，其后 18 个答案行全被当成题目解析，连锁报出「题号重复 1..18」
            # 「36 题缺分值」「答案区没有任何题号」三条假阳性。
            if _META_SECTION_RE.match(name):
                paper.meta_sections.append(name)
            if not is_answer_heading(name) or _ANSWER_HEADING_RE.match(name):
                paper.type_sections.append(name)
            current_type = name
            last_q = None
            continue

        # ---- 卷面说明引子 ----
        lead = _LEAD_RE.search(stripped)
        if lead and paper.lead_total is None:
            paper.lead_total = int(lead.group(1))
            paper.lead_count = int(lead.group(2))
            continue

        # ---- 分值分布表 ----
        if _TABLE_ROW_RE.match(stripped):
            if _TABLE_SEP_RE.match(stripped):
                continue
            cells = [_cell(c) for c in stripped.strip("|").split("|")]
            if len(cells) >= 5:
                if cells[0] == "题型":
                    paper.has_table = True
                    continue
                if cells[0] == "合计":
                    paper.table_total = {
                        "type": "合计", "range": cells[1],
                        "count": cells[2], "each": cells[3], "sub": cells[4],
                    }
                    continue
                paper.table.append({
                    "type": cells[0], "range": cells[1],
                    "count": cells[2], "each": cells[3], "sub": cells[4],
                })
                paper.has_table = True
                continue

        # ---- 题目 ----
        # 答案区必须整行抽取所有题号：规范的答案区把客观题答案压在同一行
        # （`**1.** A　**2.** C　**3.** A　**4.** B`），按行首匹配只能拿到第 1 题，
        # 于是每卷都会误报「答案区缺题号 2..16」。题面侧仍按行首判定，因为
        # 规范要求每题独立成段，一行多题在题面侧本身就是违规。
        if in_answer:
            # 答案区题号有两种实测写法：规范的加粗「**1.** A」与裸号「1. A。」。
            # 只认加粗会把裸号答案整段漏掉，进而误报「答案区没有任何题号」（E006 假阳性），
            # 并且这些答案行会被当成题目解析，制造「题号重复 1..18」的连锁假阳性。
            nums_in_line = [int(x) for x in _ANS_NUM_RE.findall(stripped)]
            if not nums_in_line:
                bare_ans = _Q_BARE_RE.match(stripped)
                if bare_ans:
                    nums_in_line = [int(bare_ans.group(1))]
            if nums_in_line:
                paper.answer_numbers.extend(nums_in_line)
                for num, ans_text in split_answer_line(stripped):
                    if num in paper.answers:
                        paper.answers[num] += " " + ans_text
                    else:
                        paper.answers[num] = ans_text
                last_q = None
                continue

        bold = _Q_BOLD_RE.match(stripped)
        bare = _Q_BARE_RE.match(stripped)
        if bold or bare:
            m = bold or bare
            num = int(m.group(1))
            rest = m.group(2).strip()
            score_m = _SCORE_RE.match(rest)
            score = int(score_m.group(1)) if score_m else None
            stem = rest[score_m.end():].strip() if score_m else rest
            q = ExamQuestion(
                number=num, score=score, kind=current_type,
                stem=stem, bold=bool(bold),
            )
            paper.questions.append(q)
            paper.blocks[num] = [stem] if stem else []
            last_q = q
            continue

        # 答案区里不带题号的续行也算答案的一部分（检查详略分级时要用）
        if in_answer and last_q is None and paper.answer_numbers:
            continue
        # 题干的续行：累计进题干块（母题指纹与选项解析都要用），并统计小题数
        if last_q is not None:
            paper.blocks.setdefault(last_q.number, []).append(stripped)
            last_q.sub_items += len(re.findall(r"\(\s*\d+\s*\)", stripped))

    return paper


def _normalize_heading(name: str) -> str:
    """去掉「第 I 部分：」「一、」等前缀，得到小节真实名称。

    实测出现过的写法：``### 第 I 部分　选择题``、``#### 第 III 部分：计算与证明题``、
    ``### 一、易错辨析``。校验「题型名是否合法」必须先把这些前缀剥掉，否则
    合法题型会被误判成非法。
    """
    text = str(name or "").strip()
    text = re.sub(r"^第\s*[IVXivx0-9一二三四五六七八九十]+\s*[部分章節\s：:、.．]*\s*", "", text)
    text = re.sub(r"^[一二三四五六七八九十百零\d]+\s*[、.．]\s*", "", text)
    return text.strip()


def split_papers(markdown: str) -> list[tuple[str, str]]:
    """按 ``## `` 把整份文档切成 (卷名, 卷正文)。

    试卷规范是「一节一卷」，导出后一章就是一份卷。整份文档直接跑校验会把
    各卷的题号混在一起（每卷都从 1 开始），必须先切卷再逐卷判定。
    """
    out: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    name = ""
    for line in str(markdown or "").split("\n"):
        if re.match(r"^##\s+", line) and not re.match(r"^###", line):
            if current is not None:
                out.append((name, current))
            name = re.sub(r"^##\s*", "", line).strip()
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        out.append((name, current))
    return [(n, "\n".join(b)) for n, b in out]


def is_exam_markdown(markdown: str) -> bool:
    """这份内容是不是一份卷（有题号 + 有题型小节或参考答案）。

    只认卷，避免把讲解型教程正文误当试卷校验——教程里的 ``1.`` 有序列表
    会被题号正则命中，那会产生一片假阳性。
    """
    text = str(markdown or "")
    has_bold_q = bool(re.search(r"^\*\*\d+\.\*\*", text, re.M))
    has_answer = bool(re.search(r"^#{2,4}\s*参考答案", text, re.M))
    has_type = any(
        re.search(r"^#{2,4}\s*(?:第\s*[IVX一二三四五六七八九十]+\s*[部分：:、]?\s*)?" + t, text, re.M)
        for t in ALLOWED_TYPES
    )
    return has_bold_q and (has_answer or has_type)


# ---------------------------------------------------------------- 校验

def _num(text: str) -> int | None:
    text = str(text or "").strip()
    return int(text) if text.isdigit() else None


def _range_span(text: str) -> tuple[int, int] | None:
    """「1–8」/「1-8」/「20」→ (起, 止)。破折号有全角与半角两种。"""
    m = re.match(r"^\s*(\d+)\s*[–—\-~～]\s*(\d+)\s*$", str(text or ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r"^\s*(\d+)\s*$", str(text or ""))
    if m2:
        return int(m2.group(1)), int(m2.group(1))
    return None


# 严重度分级：决定哪些违规会影响 quality_report["passed"]。
#
# 这不是主观偏好，而是按「是否让卷子不可用」划分：
#   blocking —— 学生拿到的卷子有实质缺陷：账目对不上（满分 96 却写 100）、题号断裂、
#               答案与题面对不上、同一份文档里同题给出互斥答案、答案区写着「需核验」。
#               这些必须计入 passed=False，否则会像现在这样静默交付。
#   advisory —— 影响观感或命题质量，但不妨碍作答：留白行数、母题重复考查、
#               客观题答案附了解析。这些只报告，不阻塞交付；把它们算进 passed 会让
#               几乎每份卷子都变成「待改进」，反而淹没真正严重的信号（实测一份 5 套卷
#               的 E013 有 42 处、E017 有 10 处，而 E018 只有 2 处）。
SEVERITY: dict[str, str] = {
    "E001": "blocking",   # 自拟题型名：结构不符合规范成品形态
    "E002": "blocking",   # 答案小节名：学生找不到答案
    "E003": "advisory",   # 裸题号：可渲染，只是不规范
    "E004": "advisory",   # 缺分值括注：表里有分值，学生仍可判分
    "E005": "blocking",   # 题号断裂/重复：答案无法对应
    "E006": "blocking",   # 答案缺题或多题：核对不了
    "E007": "blocking",   # 声明题量与实际不符
    "E008": "blocking",   # 分值表账目错
    "E009": "blocking",   # 元栏目泄漏：交付了不该有的教学内容
    "E010": "advisory",   # 题型顺序与表不一致
    "E011": "blocking",   # 标题层级破坏文档结构
    "E012": "advisory",   # 客观题带解析
    "E013": "advisory",   # 留白行数
    "E014": "blocking",   # 占位文字：成品里不该有「请在此作答」
    "E015": "blocking",   # 答案区写「需核验」：等于没给答案
    "E016": "blocking",   # 题面分值与分值表不符
    "E017": "advisory",   # 母题重复：命题质量问题，不是可用性问题
    "E018": "blocking",   # 同题不同答案：学生看到互斥结论
}


def is_blocking(code: str) -> bool:
    return SEVERITY.get(code, "blocking") == "blocking"


# 各规范下**可判定**的错误码集合。
#
# 必须按规范分流，不能一套检查打天下：额外练习文件走「练习生成规范」，它明令
# 「不逐题标注难度、分值、考点」，所以 E004（缺分值括注）在练习文件上是**错误**的
# 判据；练习文件的节内结构是「一、易错辨析 / 二、训练 / 参考答案」，不是六个题型
# 枚举，所以 E001/E010 也不适用；留白行数（E013）是试卷规范的排版要求，同样不适用。
# 只有与排版规范无关的**账目与答案事实**在两种规范下都成立。
SPEC_CODES: dict[str, frozenset] = {
    "exam": frozenset(CODES),
    "exercise": frozenset({
        "E003",  # 题号必须加粗
        "E005",  # 题号连续无重复
        "E006",  # 答案题号集合与题面一致
        "E007",  # 声明题量与实际一致（练习文件若有声明）
        "E015",  # 答案区不得泄漏不确定性
        "E017",  # 跨节母题重复
        "E018",  # 同母题不同答案
    }),
}


def score_is_uniform(paper: ExamPaper) -> bool:
    """分值表的「每题分值」列能否代表该题型的实际分值。

    非均匀时（同一题型各题分值不同，例如实测判断题一题 20 分、一题 25 分），
    表格的「每题分值」这一列**在数学上无法表达事实**。此时任何自动修复都必须在
    「改题面分值」与「改表格数值」之间二选一：前者会改变试卷的配分结构与难度分布
    （属内容决策），后者等于凭空编数。两者都不是账目事实，所以标记为不可自动修，
    交人工决定——早期实现在这种情况下把小计改成实际之和，却留下
    「2×20=40 ≠ 小计 45」，产出一张比原来更自相矛盾的表。
    """
    for row in paper.table:
        scores = {
            q.score for q in paper.questions
            if q.kind == row["type"] and q.score is not None
        }
        if len(scores) > 1:
            return False
    return True


def check_paper(
    paper: ExamPaper,
    *,
    material_types: set[str] | None = None,
    spec: str = "exam",
) -> list[Violation]:
    """对一份卷跑确定性检查，返回违规清单。只判定，不改写。

    ``material_types``：材料里给出的题型划分（见 _EXAM_SUGGESTED_RULES「题型名逐字
    沿用，不改写成同义词」）。给了就允许这些题型名，不报 E001。

    ``spec``：``"exam"`` 试卷生成规范 / ``"exercise"`` 练习生成规范，决定哪些错误码
    适用（见 ``SPEC_CODES`` 的注释——两套规范的可判定项确实不同）。
    """
    v: list[Violation] = []
    allowed_extra = material_types or set()
    enabled = SPEC_CODES.get(spec, SPEC_CODES["exam"])

    # E011 正文标题层级：由调用方在整份文档层面判定（这里只看卷内 ###/####）

    # ---- E001 题型名合法性 ----
    illegal = []
    for name in paper.type_sections:
        if is_answer_heading(name) or _META_SECTION_RE.match(name):
            continue
        if name not in ALLOWED_TYPES and name not in allowed_extra:
            illegal.append(name)
    if illegal:
        v.append(Violation(
            "E001", *CODES["E001"],
            f"非法题型名：{'、'.join(sorted(set(illegal)))}（允许：{'、'.join(ALLOWED_TYPES)}）",
        ))

    # ---- E009 元栏目 ----
    if paper.meta_sections:
        v.append(Violation(
            "E009", *CODES["E009"],
            f"卷内出现元栏目：{'、'.join(sorted(set(paper.meta_sections)))}",
        ))

    # ---- E002 答案小节标题 ----
    variants = sorted(set(paper.variant_answer_headings))
    if paper.answer_heading_count == 0 and not variants:
        v.append(Violation("E002", *CODES["E002"], "本卷没有「### 参考答案」小节"))
    else:
        parts = []
        if paper.answer_heading_count == 0 and variants:
            parts.append(f"答案被拆进自拟小节：{'、'.join(variants)}，缺唯一的「### 参考答案」")
        elif paper.answer_heading_count > 1:
            parts.append(f"「### 参考答案」出现 {paper.answer_heading_count} 次（有且仅有一次）")
        elif variants:
            parts.append(f"存在自拟答案小节名：{'、'.join(variants)}（只能叫「### 参考答案」）")
        if parts:
            v.append(Violation("E002", *CODES["E002"], "；".join(parts), auto_fixable=True))

    # ---- E003 / E004 题号形式与分值括注 ----
    bare = [q.number for q in paper.questions if not q.bold]
    if bare:
        v.append(Violation(
            "E003", *CODES["E003"],
            f"{len(bare)} 题用裸题号（题号 {'、'.join(str(x) for x in bare[:8])}"
            f"{'…' if len(bare) > 8 else ''}）",
            auto_fixable=True,
        ))
    no_score = [q.number for q in paper.questions if q.score is None]
    if no_score:
        v.append(Violation(
            "E004", *CODES["E004"],
            f"{len(no_score)} 题缺分值括注（题号 {'、'.join(str(x) for x in no_score[:8])}"
            f"{'…' if len(no_score) > 8 else ''}）",
            auto_fixable=True,
        ))

    # ---- E005 题号连续性 ----
    nums = [q.number for q in paper.questions]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    # 题号重复时**不能**重编号：「旧号→新号」映射会多对一坍缩（实测 1→1 随即被
    # 1→2 覆盖），答案区的 **1.** 会被错映射成 **2.**，导致一条答案凭空消失、
    # 答案与题目张冠李戴。哪道题该保留原题号是有歧义的，只能报出来交人工决定。
    renumberable = bool(nums) and not dup
    if nums:
        expected = list(range(1, len(set(nums)) + 1))
        if sorted(set(nums)) != expected:
            v.append(Violation(
                "E005", *CODES["E005"],
                f"题号序列 {sorted(set(nums))} 不是 1..{len(set(nums))} 连续",
                auto_fixable=renumberable,
            ))
        elif nums != sorted(nums):
            v.append(Violation(
                "E005", *CODES["E005"], "题号未按递增顺序出现", auto_fixable=renumberable,
            ))
    if dup:
        v.append(Violation(
            "E005", *CODES["E005"],
            f"题号重复：{dup}（无法自动重编号，重复号会使答案与题目错配）",
            auto_fixable=False,
        ))

    # ---- E006 答案题号集合一致 ----
    qset, aset = set(nums), set(paper.answer_numbers)
    if qset and aset and qset != aset:
        missing = sorted(qset - aset)
        extra = sorted(aset - qset)
        parts = []
        if missing:
            parts.append(f"答案区缺题号 {missing}")
        if extra:
            parts.append(f"答案区多出题号 {extra}")
        v.append(Violation("E006", *CODES["E006"], "；".join(parts)))
    elif qset and not aset:
        v.append(Violation("E006", *CODES["E006"], "答案区没有任何题号"))

    # ---- E008 分值表账目 ----
    if paper.has_table:
        prod_sum = sub_sum = cnt_sum = 0
        row_bad = []
        for r in paper.table:
            c, e, sb = _num(r["count"]), _num(r["each"]), _num(r["sub"])
            if None in (c, e, sb):
                row_bad.append(f"{r['type']} 表格数值不可解析（题量={r['count']} 分值={r['each']} 小计={r['sub']}）")
                continue
            prod_sum += c * e
            sub_sum += sb
            cnt_sum += c
            if c * e != sb:
                row_bad.append(f"{r['type']}：{c}×{e}={c * e} ≠ 小计 {sb}")
        declared = paper.lead_total
        total_row = paper.table_total or {}
        total_sub, total_cnt = _num(total_row.get("sub")), _num(total_row.get("count"))
        detail = []
        detail += row_bad
        if sub_sum != prod_sum:
            detail.append(f"各行小计之和 {sub_sum} ≠ 题量×分值之和 {prod_sum}")
        if declared is not None and sub_sum != declared:
            detail.append(f"各行小计之和 {sub_sum} ≠ 卷面声明满分 {declared}")
        if total_sub is not None and total_sub != sub_sum:
            detail.append(f"合计行 {total_sub} ≠ 各行小计之和 {sub_sum}")
        if total_cnt is not None and total_cnt != cnt_sum:
            detail.append(f"合计行题量 {total_cnt} ≠ 各行题量之和 {cnt_sum}")
        # 题号区间与实际题数
        for r in paper.table:
            span = _range_span(r["range"])
            c = _num(r["count"])
            if span and c is not None and (span[1] - span[0] + 1) != c:
                detail.append(f"{r['type']}：题号区间 {r['range']} 共 {span[1] - span[0] + 1} 题 ≠ 题量 {c}")
        if detail:
            uniform = score_is_uniform(paper)
            if not uniform:
                detail.append(
                    "同一题型内各题分值不一致，「每题分值」列无法表达事实，"
                    "需人工决定改题面分值还是改分值表"
                )
            v.append(Violation(
                "E008", *CODES["E008"], "；".join(detail), auto_fixable=uniform,
            ))

        # E007 声明题量 vs 实际
        if paper.lead_count is not None and nums:
            real = len(set(nums))
            if paper.lead_count != real:
                v.append(Violation(
                    "E007", *CODES["E007"],
                    f"卷面说明声明 {paper.lead_count} 题，实际写出 {real} 题",
                    auto_fixable=True,
                ))
        if total_cnt is not None and nums and total_cnt != len(set(nums)):
            v.append(Violation(
                "E007", *CODES["E007"],
                f"分值表合计 {total_cnt} 题，实际写出 {len(set(nums))} 题",
                auto_fixable=True,
            ))

        # E010 题型顺序
        table_types = [r["type"] for r in paper.table]
        actual_types = [n for n in paper.type_sections
                        if not is_answer_heading(n) and not _META_SECTION_RE.match(n)]
        if table_types and actual_types:
            # 只比对交集的相对顺序（材料题型可能与表不完全一致）
            common_t = [t for t in table_types if t in actual_types]
            common_a = [t for t in actual_types if t in table_types]
            if common_t != common_a:
                v.append(Violation(
                    "E010", *CODES["E010"],
                    f"分值表顺序 {common_t} ≠ 卷内实际顺序 {common_a}",
                ))

        # E016 题面分值括注之和 vs 分值表
        face_sum = sum(q.score for q in paper.questions if q.score is not None)
        if face_sum and sub_sum and face_sum != sub_sum:
            v.append(Violation(
                "E016", *CODES["E016"],
                f"题面（X 分）之和 {face_sum} ≠ 分值表小计之和 {sub_sum}",
                auto_fixable=True,
            ))

    return [x for x in v if x.code in enabled]


def check_answer_detail(
    markdown: str, paper: ExamPaper, *, spec: str = "exam",
) -> list[Violation]:
    """E012 / E015：答案区详略分级与不确定性表述。

    E012 —— 规范要求客观题（选择/判断/填空）只给答案、不给解析；解答题/证明题/
    综合题给答案 + 不超过 6 行关键步骤。按题型小节判定，不让模型自行判断难易。
    E015 —— 答案区出现「需核验」「待定」「存疑」等字样，等于把不确定性交付给用户，
    实测第五套压轴题答案原文含「此处结论标注『需核验』」。
    """
    v: list[Violation] = []
    text = str(markdown or "")
    m = re.search(r"^#{2,4}\s*参考答案\s*$(.*)", text, re.M | re.S)
    if not m:
        return v
    answer_text = m.group(1)

    # E015 不确定性表述
    uncertain = re.findall(r"(需核验|待核验|待定|存疑|有待确认|需进一步验证|无法确定|不确定)", answer_text)
    if uncertain:
        v.append(Violation(
            "E015", *CODES["E015"],
            f"答案区出现不确定性表述：{'、'.join(sorted(set(uncertain)))}",
        ))

    # E012 客观题答案不得带解析
    kinds = {q.number: q.kind for q in paper.questions}
    obj_nums = [n for n, k in kinds.items() if k in OBJECTIVE_TYPES]
    if obj_nums:
        # 逐行扫描答案区，命中客观题题号且该行含推导/解析特征
        suspicious = []
        for line in answer_text.split("\n"):
            hit = [int(x) for x in _ANS_NUM_RE.findall(line) if int(x) in set(obj_nums)]
            if not hit:
                continue
            if re.search(r"(因为|所以|由.*得|故|推导|根据.*定理|计算过程|解\s*[：:])", line):
                suspicious.extend(hit)
        if suspicious:
            v.append(Violation(
                "E012", *CODES["E012"],
                f"客观题（题号 {'、'.join(str(x) for x in sorted(set(suspicious))[:8])}）的参考答案带了步骤或解析",
            ))
    enabled = SPEC_CODES.get(spec, SPEC_CODES["exam"])
    return [x for x in v if x.code in enabled]


# 系统输出的章标题：``## 一、第 1 章 … 单元检测卷`` / ``## 二、微积分期中冲刺模拟试卷（第一套）``。
# 这类标题由 tutorials 渲染层统一生成，**不是**模型的违规，E011 必须排除它们，
# 否则整份文档每次都报「正文出现 #/## 级标题」的假阳性。
_SYSTEM_CHAPTER_RE = re.compile(r"^##\s*[一二三四五六七八九十百零\d]+\s*[、.．]")


def check_whole_document(markdown: str) -> list[Violation]:
    """整份文档层面的检查：E011（标题层级）、E014（占位文字）。"""
    v: list[Violation] = []
    text = str(markdown or "")
    in_fence = False
    bad_levels = []
    seen_h1 = False
    for i, line in enumerate(text.split("\n"), 1):
        if _is_code_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s*(.+)$", line)
        if not m:
            continue
        level, name = len(m.group(1)), m.group(2).strip()
        # 文档级 H1 由系统输出（``# 微积分期中冲刺``），只放行第一个；
        # 章标题由系统输出为「## 中文序号、卷名」。这两类不算违规。
        if level == 1 and not seen_h1:
            seen_h1 = True
            continue
        if level == 2 and _SYSTEM_CHAPTER_RE.match(line.strip()):
            continue
        # 除此之外，卷内正文最浅应为 ###（_EXAM_FORMAT_RULES）
        if level <= 2:
            bad_levels.append((i, level, name))
    if bad_levels:
        v.append(Violation(
            "E011", *CODES["E011"],
            f"正文出现 #/## 级标题 {len(bad_levels)} 处（行 {bad_levels[0][0]} 等）",
            auto_fixable=True,
        ))

    placeholders = sorted(set(_PLACEHOLDER_RE.findall(text)))
    if placeholders:
        v.append(Violation(
            "E014", *CODES["E014"],
            f"卷内出现占位文字：{'、'.join(placeholders)}",
            auto_fixable=True,
        ))
    return v


# ---------------------------------------------------------------- 留白（E013）

def check_blanks(markdown: str, paper: ExamPaper) -> list[Violation]:
    """E013：题后留白行数按题型固定（判断 0 / 选择 2 / 填空 1 / 解答与证明 3 / 综合 4）。

    规范把留白行数写死，是为了导出到 Obsidian 后每道题的作答空间一致、可打印。
    这项检查**只报告不自动修**：留白行数的差异不影响正确性，而机械补足会在
    已经合适的地方插入空行，让 diff 变得嘈杂。
    """
    v: list[Violation] = []
    text = str(markdown or "")
    if not any(q.kind in BLANK_LINES for q in paper.questions):
        return v
    lines = text.split("\n")
    in_answer = False
    in_fence = False
    current_kind = ""
    starts: list[tuple[int, int, str]] = []
    # 题目块的右边界 = 下一题的题号行 **或** 下一个标题行，取更早者。
    # 只按题号定界会算错：某题型最后一题的后面紧跟「### 判断题」标题，
    # 若把边界放到下一题，标题行会被算进块内，留白数少 1 行（实测第一套第 8 题
    # 真实留白 2 行被报成 1 行，两份卷子共 115 处假阳性）。
    boundaries: list[int] = []
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        is_heading, new_in_answer, name = _track_answer_state(line, in_answer)
        if is_heading:
            in_answer = new_in_answer
            if not is_answer_heading(name):
                current_kind = name
                if not in_answer:
                    boundaries.append(i)
            continue
        if in_answer:
            continue
        m = _Q_BOLD_RE.match(line.strip()) or _Q_BARE_RE.match(line.strip())
        if m:
            starts.append((i, int(m.group(1)), current_kind))
            boundaries.append(i)
    boundaries = sorted(set(boundaries))

    mismatched: list[str] = []
    for idx, (line_no, num, kind) in enumerate(starts):
        want = BLANK_LINES.get(kind)
        if want is None:
            continue
        later = [b for b in boundaries if b > line_no]
        end = later[0] if later else len(lines)
        # 题目块结束后的连续空行数
        blanks = 0
        for j in range(end - 1, line_no, -1):
            if not lines[j].strip():
                blanks += 1
            else:
                break
        # 复选框行是判断题的作答位，不计入留白也不该被要求补空行
        if kind == "判断题" and re.search(r'<input\s+type="checkbox"', "\n".join(lines[line_no:end])):
            continue
        if blanks != want:
            mismatched.append(f"第 {num} 题（{kind}）留白 {blanks} 行，应为 {want} 行")
    if mismatched:
        v.append(Violation(
            "E013", *CODES["E013"],
            f"{len(mismatched)} 题留白不符：{mismatched[0]}"
            f"{'；等 ' + str(len(mismatched)) + ' 处' if len(mismatched) > 1 else ''}",
        ))
    return v


# ---------------------------------------------------------------- 跨卷一致性（E017 / E018）

# 母题指纹：从题干里抽「有辨识度的数学对象」。
#
# 为什么不直接比题干文本：实测同一母题在不同卷里的**问法**会变（同一个参数方程，
# 第一套问 d²x/dy²、第二套问 dy/dx、第三套问凹凸性），字符串比对一律判成不同题，
# 于是「同一母题 5 次出现给了 4 个不同答案」这种最严重的故障完全检测不到。
#
# 为什么不用手工维护的母题词表：早期实现写死了 18 条正则（`x^3+e^{xy}`、
# `arcsin x` …），只对提炼它的那份卷子有效，换一份卷子就全部失效——那是把一次性的
# 人工分析伪装成通用能力。改成从题干自动抽取归一化后的 LaTeX 片段作指纹，任何学科、
# 任何卷子都适用，且不需要维护词表。
_MATH_SPAN_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)

# 排版修饰词：不影响数学对象身份，归一化时剥掉。
# 不剥的话同一个式子会因 `\displaystyle` / `\limits` 的有无被判成两个母题。
_MATH_NOISE_RE = re.compile(
    r"\\(?:displaystyle|limits|nolimits|left|right|bigg?|Bigg?|!|,|;|:|quad|qquad|"
    r"dfrac|tfrac|d?frac\b)"
)


def _normalize_math(span: str) -> str:
    """把一段 LaTeX 归一化成可比对的指纹。

    ``\\dfrac`` → ``\\frac``：两者渲染相同，只是显示风格差异，不该算不同母题。
    """
    text = _MATH_NOISE_RE.sub(lambda m: "\\frac" if m.group(0).endswith("frac") else "", span)
    text = text.replace("\\dfrac", "\\frac")
    return re.sub(r"\s+", "", text)


# 选项行：``A. …``、``A、…``，以及一行内并列多个选项的 ``A. …　　B. …``。
# **母题指纹必须排除选项行**，这是实测教训：把选项里的 ``$\alpha>1$``、``$\frac{1}{2}$``、
# ``$f'(\xi)=0$`` 当指纹，会让「凡是出现 α>1 选项的题」都判成同一母题，
# 一份 5 套卷报出 20+ 条假阳性，把真正严重的 E018 淹没。
# 母题由题干的**定义式**决定（隐函数方程、递推式、参数方程），与选项无关。
_OPTION_LINE_RE = re.compile(r"^\s*[A-D]\s*[\.、．]")
_MULTI_OPTION_RE = re.compile(r"[A-D]\s*[\.、．].{0,40}[B-D]\s*[\.、．]")


def _is_option_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    return bool(_OPTION_LINE_RE.match(text) or _MULTI_OPTION_RE.search(text))


def question_motifs(block_lines) -> list[str]:
    """题干块里「有辨识度的定义式」指纹（升序去重）。

    三条过滤规则都是为了压低假阳性，实测缺一不可：

    1. **排除选项行**：见 ``_OPTION_LINE_RE`` 的注释。
    2. **长度下限** ``_MOTIF_MIN_LEN``：``$x$``、``$0$``、``$f'(0)$`` 这类短片段几乎每题
       都有，留着会让任意两题都判成同母题。
    3. **去高频片段**：``f(0)=0`` 在中值定理类题目里反复出现，但它不构成「同一道题」
       的充分条件（同条件下可以问完全不同的结论）。出现次数超过 ``max_df`` 的片段
       视为通用套路而非具体母题，由 ``_definition_index`` 的 ``max_df`` 统一剔除。
    """
    if isinstance(block_lines, str):
        block_lines = [block_lines]
    out = []
    for line in block_lines or []:
        if _is_option_line(line):
            continue
        for m in _MATH_SPAN_RE.finditer(str(line)):
            raw = m.group(1) or m.group(2) or ""
            # ``\begin{cases}`` / 矩阵里的多行定义式必须按 ``\\`` 拆行，否则
            # 「x=ln(t+√(1+t²)), y=arctan t」在 cases 里是一个片段、在普通写法里是
            # 两个片段，同一母题跨卷聚不到一起（实测漏掉了那个出现 5 次的参数方程簇）。
            for piece in re.split(r"\\\\", raw):
                span = _normalize_math(piece)
                for env in ("cases", "aligned", "matrix", "pmatrix", "bmatrix", "array"):
                    span = span.replace("\\begin{" + env + "}", "").replace("\\end{" + env + "}", "")
                # 只剥首尾的空白与句读，**保留花括号**：`\frac{a}{b}` 的结尾 `}` 若被
                # `\W+$` 剥掉，指纹会变成 `frac{a}{b`，展示残缺且无法与其它写法对齐。
                span = span.strip(" \t,，;；。.")
                if len(span) >= _MOTIF_MIN_LEN:
                    out.append(span)
    return sorted(set(out))


# 指纹长度下限：实测 8 能滤掉 `f'(0)`、`x^2` 这类通用短式，同时保住
# `\ln(t+\sqrt{1+t^2})`、`x^n+2nx-2` 这类真正有辨识度的母题定义。
_MOTIF_MIN_LEN = 8

# 可比答案的长度上限：超过就视为「成段解答」，不参与 E018。
# 实测客观答案与填空答案归一化后一般 ≤ 20 字符（`e^{-1}`、`\sqrt2`、`\dfrac{1}{2}`），
# 而解答/综合题的关键步骤动辄上百字符。取 40 留足余量，同时把证明文本挡在外面。
_COMPARABLE_ANSWER_LEN = 40

# E018（同题不同答案）会驱动「自动改答案」，因此它的判据必须比 E017 严格得多：
# 假阳性会直接把对的答案改错。定义式下限取 16 —— 实测这个长度能区分
# `x^3+e^{xy}-\sin3x+y=2`（22，具体母题）与 `\lim_{x\to0}f(x)=0`（18 但只是共用假设）。
_DEFINITION_MIN_LEN = 16

# 裸区间 / 数集 / 定义域：`(0,+\infty)`、`[0,1]`、`\mathbb{N}_+`、`\xi,\eta\in(0,1)`。
# 这些是**上下文声明**而非母题身份，几乎所有分析题都有，留着会让整份卷子互相判成同母题。
_CONTEXT_ONLY_RE = re.compile(
    r"""(?:^[\(\[][^=]*[\)\]]$)"""          # 裸区间：(0,+\infty) / [0,1]
    r"""|(?:.*\\in\\mathbb\{[A-Z]\}.*)"""    # n\in\mathbb{N}_+
    r"""|(?:^\\mathbb\{[A-Z]\}[_\^\{0-9\+\*\}]*$)"""  # \mathbb{N}_+
    r"""|(?:^[\\a-zA-Z{},\s]*\\in[\(\[][^=]*[\)\]])""" # \xi,\eta\in(0,1)
)


def _short(text: str, limit: int = 42) -> str:
    """指纹截断成可读片段，用于 detail 展示。"""
    t = str(text or "")
    return t if len(t) <= limit else t[:limit] + "…"


def _is_definition_span(span: str) -> bool:
    r"""这个数学片段是「母题定义式」，还是只是查询式 / 上下文声明？

    三类都不是定义式，必须排除（都是实测踩过的坑）：

    1. **查询式**（以 ``=`` 结尾）：``\lim_{n\to\infty}a_n=``、
       ``\frac{d^2x}{dy^2}|_{t=1}=`` —— 它们是「要求算什么」，不是「这个对象是什么」。
       把查询式当母题，会让两道完全不同但都问极限的题判成同题，进而 E018 误改答案。
    2. **裸区间 / 数集**：``(0,+\infty)``、``\mathbb{N}_+``，见 ``_CONTEXT_ONLY_RE``。
    3. **没有等号的短语**：``\alpha>1``、``f'(\xi)=0`` 里的纯条件片段——它们描述的是
       待证结论或选项内容，不是题目所定义的对象。

    保留的形态是「某对象 = 某表达式」，即真正的定义式，例如
    ``x^3+e^{xy}-\sin3x+y=2``、``a_{n+1}=\sqrt{2+a_n}``、``f_n(x)=x^n+2nx-2``。
    """
    text = str(span or "").strip()
    if not text:
        return False
    # 查询式：以 = 结尾，等号右边是空的
    if text.endswith("="):
        return False
    # 裸区间 / 数集
    if _CONTEXT_ONLY_RE.match(text):
        return False
    # 必须是「左边 = 右边」且右边非空的定义式
    if "=" not in text:
        return False
    left, _sep, right = text.partition("=")
    return bool(left.strip()) and bool(right.strip())


def _normalize_answer(text: str) -> str:
    """答案归一化：去掉解释性文字与排版差异，只留可比对的结论。

    客观题答案是选项字母或对错，必须**先解析成结论**再比对：
    同一个「C」在不同卷里可能写作 `C`、`C。`、`C　`，直接比字符串会误判成不一致。
    """
    t = str(text or "").strip()
    if not t:
        return ""
    # 客观题：只取开头的选项字母或对错结论
    m = re.match(r"^([A-D])[。．、\s]", t)
    if m:
        return m.group(1)
    if re.match(r"^[A-D]$", t):
        return t
    for word, canon in (("正确", "T"), ("对", "T"), ("错误", "F"), ("错", "F"), ("否", "F")):
        if t.startswith(word):
            return canon
    # 主观题：去空白与常见标点，保留数学内容
    return re.sub(r"[\s\u3000。；，、]", "", t)


def _resolve_choice_answer(paper: ExamPaper, num: int) -> str:
    """把选择题答案解析成选项字母；判断题解析成 T/F。"""
    raw = _normalize_answer(paper.answers.get(num, ""))
    return raw


# 选项行内容抽取：``A. $e^{-1/2}$``、``A. 甲　　B. 乙　　C. 丙``
_OPTION_ITEM_RE = re.compile(r"([A-D])\s*[\.、．]\s*(.*?)(?=\s*[A-D]\s*[\.、．]|$)")


def parse_options(block_lines) -> dict[str, str]:
    """从题目块里抽出 {选项字母: 选项内容}。

    E018 **必须**用选项内容而不是选项字母来比对答案：各卷的选项排序可以不同，
    同一个字母在两卷里可能指向完全不同的内容。只比字母会双向出错——
    字母相同但内容不同（漏报真错误），字母不同但内容相同（误报假错误）。
    """
    opts: dict[str, str] = {}
    for line in block_lines or []:
        text = str(line or "").strip()
        if not text:
            continue
        if not re.search(r"[A-D]\s*[\.、．]", text):
            continue
        # 跳过题干行：题干里的 "A." 极少见，但 "设 A 为…" 这类叙述必须排除
        if _Q_BOLD_RE.match(text) or _Q_BARE_RE.match(text):
            continue
        for m in _OPTION_ITEM_RE.finditer(text):
            letter, content = m.group(1), m.group(2).strip()
            if content:
                opts[letter] = re.sub(r"[\s\u3000]+$", "", content)
    return opts


def _normalize_value(text: str) -> str:
    """答案 / 选项内容归一化：剥排版差异，只留可比对的数学与文字。"""
    t = str(text or "").strip().rstrip("。．.")
    t = _MATH_NOISE_RE.sub(lambda m: "" if not m.group(0).endswith("frac") else "\\frac", t)
    t = t.replace("\\dfrac", "\\frac").replace("\\left", "").replace("\\right", "")
    # `\\left.` 剥掉 \\left 后会留下孤立的 `.`（实测 query_key 展示成 `.\\frac{...}`）
    t = re.sub(r"(?<![A-Za-z0-9])\?(?<!\w)\.(?=[\\({])", "", t)
    t = re.sub(r"\$+", "", t)
    return re.sub(r"[\s\u3000]+", "", t)


def answer_content(paper: ExamPaper, num: int) -> tuple[str, str]:
    """返回 (答案类别, 归一化后的答案内容)。

    类别：``choice`` 选项题（内容 = 选项文本）、``judge`` 判断题（T/F）、
    ``other`` 填空与主观题（内容 = 答案文本）。**只有同类别之间才可比对**。
    """
    raw = str(paper.answers.get(num, "") or "").strip()
    if not raw:
        return "", ""
    kind = next((q.kind for q in paper.questions if q.number == num), "")
    if kind == "判断题":
        for word, canon in (("正确", "T"), ("对", "T"), ("错误", "F"), ("错", "F"), ("否", "F"), ("是", "T")):
            if raw.startswith(word):
                return "judge", canon
        return "judge", _normalize_value(raw)
    m = re.match(r"^([A-D])(?![A-Za-z0-9])", raw)
    if m:
        letter = m.group(1)
        opts = parse_options(paper.blocks.get(num) or [])
        content = opts.get(letter, "")
        # 选项内容缺失时退回字母本身（至少还能表达「同一张卷内的自洽性」）
        return "choice", (_normalize_value(content) if content else f"OPTION_{letter}")
    return "other", _normalize_value(raw)


# 查询式：题干里「要求算什么」的部分，如 `\dfrac{d^2x}{dy^2}|_{t=1}=`。
# 同一母题可以问不同的量（实测那 5 次参数方程分别问 d²x/dy²、dy/dx、dx/dy），
# 只有**问了同一个量**才谈得上答案是否一致，否则 E018 会把「问不同东西」误判成「答案矛盾」。
def query_key(paper: ExamPaper, num: int) -> str:
    """题目「所问的量」的归一化键；抽不到就返回空串（此时不参与 E018）。"""
    block = paper.blocks.get(num) or []
    keys: list[str] = []
    for line in block:
        if _is_option_line(line):
            continue
        for m in _MATH_SPAN_RE.finditer(str(line)):
            span = _normalize_math(m.group(1) or m.group(2) or "")
            # 以 = 结尾的是查询式；`等于` / `则` 后面的量也算
            if span.endswith("="):
                keys.append(span)
    if not keys:
        text = " ".join(str(x) for x in block)
        m = re.search(r"(?:则|求|等于)\s*(.+?)(?:[（(]|$)", text)
        if m:
            keys.append(_normalize_value(m.group(1)))
    return "|".join(sorted({_canon_query(k) for k in keys if k}))


def _canon_query(key: str) -> str:
    r"""把「所问的量」归一成可跨卷比对的键。

    必须归一的原因（实测漏报）：第三套第 8 题问 ``\lim_{n\to+\infty}(1+a_n)^n=``、
    第五套第 16 题问 ``\lim_{n\to\infty}(1+a_n)^n=``，两者只差一个 ``+``，却是同一个量；
    不归一会让「选择题答 e^2 / 填空题答 e^-1」这个真错误落到不同桶里漏报。
    """
    t = str(key or "").strip()
    t = t.replace(r"\rightarrow", r"\to")
    t = re.sub(r"\+(?=\\infty)", "", t)            # +\infty -> \infty
    t = re.sub(r"(?<![\w.])\.(?=[\\({])", "", t)   # \left. 剥掉 \left 后残留的孤立点
    t = t.replace(r"\left", "").replace(r"\right", "")
    t = t.replace(r"\dfrac", r"\frac").replace(r"\displaystyle", "")
    t = re.sub(r"[\s\u3000]+", "", t)
    return t


def _definition_index(
    papers: list[tuple[str, ExamPaper]], *, max_df: int = 0,
) -> tuple[dict[str, list[tuple[str, int]]], int]:
    """建立「母题定义式 → 出现位置」的倒排索引。

    **相似度度量必须是「共享定义式」，不能是题干特征的 Jaccard 相似度**——这是实测
    教训：``f_n(x)=x^n+2nx-2`` 这个母题在四道题里出现，但四道题问的东西完全不同
    （证存在唯一正根 / 求极限 / 判断选项），整体特征重合度低于 0.5，用 Jaccard 聚类
    会把它们拆成四个独立簇，于是「同一母题给出 e、e²、e⁻¹ 三种答案」这个真错误漏报。

    定义式（``_is_definition_span``）是母题的身份标识，与问法无关，所以按它建索引
    既能召回「同母题不同问法」，又不会把「同套路不同母题」（如都含 ``f(a)=f(b)``）
    误并到一起。

    ``max_df`` 为 0 时自动取 ``题目总数 // 8``（下限 3）：出现次数超过阈值的定义式
    视为通用套路而非具体母题，剔除，避免大卷子报出一片噪音。
    """
    per_q: dict[tuple[str, int], set[str]] = {}
    df: dict[str, int] = {}
    total_q = 0
    for pname, paper in papers:
        total_q += len(paper.questions)
        for q in paper.questions:
            block = paper.blocks.get(q.number) or [q.stem]
            spans = {
                sp for sp in question_motifs(block)
                if _is_definition_span(sp) and len(sp) >= _DEFINITION_MIN_LEN
            }
            per_q[(pname, q.number)] = spans
            for sp in spans:
                df[sp] = df.get(sp, 0) + 1
    if max_df <= 0:
        max_df = max(3, total_q // 8)
    index: dict[str, list[tuple[str, int]]] = {}
    for (pname, num), spans in per_q.items():
        for sp in spans:
            if df[sp] <= max_df:
                index.setdefault(sp, []).append((pname, num))
    for locs in index.values():
        locs.sort()
    return index, total_q


def check_cross_paper(
    papers: list[tuple[str, ExamPaper]],
    *,
    min_occurrences: int = 2,
) -> list[Violation]:
    r"""跨卷检查：E017 母题重复、E018 同母题同问法给出不同答案。

    ``papers`` 是 [(卷名, 解析结果)]。**只在多卷文档上调用**——单卷无从谈跨卷一致。

    判据分两层，都是实测逼出来的：

    - **E017**：按「共享**定义式**」聚类（见 ``_definition_index``），而非题干特征的
      Jaccard 相似度——后者会把同一母题的不同问法拆开（``f_n=x^n+2nx-2`` 一处问
      存在性、一处问极限，特征重合度低），漏报真错误。定义式是母题身份，与问法无关。
      只共享 ``f(a)=f(b)``、``c\in(0,1)`` 这类通用假设不算定义式，天然被挡掉。
    - **E018**：在同母题簇内，再要求「所问的量相同（``query_key``）+ 答案形态相同」，
      然后比对**答案内容**而不是选项字母（字母在不同卷可能指向不同内容）。
      它比 E017 严格得多，因为它会驱动自动改答案，误报的代价是把对的答案改错。
    """
    v: list[Violation] = []
    if len(papers) < 2:
        return v
    by_paper = {pname: paper for pname, paper in papers}
    index, _total = _definition_index(papers)

    # 同一个位置可能因多个定义式被报多次（例如一道题里写了递推式又写了初值），
    # 只保留成员最多的那个簇来代表这组题，避免 detail 重复刷屏。
    reported: set[frozenset] = set()
    ordered = sorted(index.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for motif, locs0 in ordered:
        group = [(p, n, set()) for p, n in locs0]
        if len(group) < min_occurrences:
            continue
        key = frozenset((p, n) for p, n, _ in group)
        if key in reported:
            continue
        reported.add(key)
        locs = [f"{p}·第{n}题" for p, n, _ in group]
        v.append(Violation(
            "E017", *CODES["E017"],
            f"母题「{_short(motif)}」出现 {len(group)} 次：{'；'.join(locs[:6])}",
        ))

        # ---- E018 ----
        # 分桶键是 (所问的量, 答案形态)，**不含题型**。题型不同不影响答案内容可比：
        # 实测第三套8 以选择题问 `\lim(1+a_n)^n` 答 C(=e^2)、第五套16 以填空题问同一个
        # 量答 e^{-1}，这是真错误；把 kind 放进键里会让它们落到不同桶而漏报。
        # 判断题与表达式答案的混比由 group_cat（judge / value）隔离，不靠题型隔离。
        buckets: dict[tuple[str, str], list[tuple[str, int, str, str]]] = {}
        for pname, num, _feat in group:
            paper = by_paper[pname]
            kind = next((q.kind for q in paper.questions if q.number == num), "")
            cat, content = answer_content(paper, num)
            if not content:
                continue
            # **长答案一律不比**：主观题答案是成段证明文本，两份措辞略异但都正确的
            # 证明会被判成「答案不一致」——实测第四套19 与第五套17 的同题证明只差
            # 一个标点就误报了。主观题对错属内容层，由 L1 盲解核验判定。
            if len(content) > _COMPARABLE_ANSWER_LEN:
                continue
            # 短答案在 choice 与 other 之间**可比**：同一母题同一问法，选择题解析出
            # 选项内容、填空题解析出答案文本，两者都归一到表达式形态。实测第三套8
            # 选择题答 C(=e^2)、第五套16 填空题答 e^{-1}、第一套20 综合题答 e，
            # 这是真错误，若按类别分桶就会漏报。判断题（T/F）不可与表达式混比。
            group_cat = "judge" if cat == "judge" else "value"
            buckets.setdefault((query_key(paper, num), group_cat), []).append(
                (pname, num, content, kind)
            )
        for (qkey, _cat), entries in buckets.items():
            if len(entries) < 2:
                continue
            distinct = {c for _, _, c, _ in entries}
            if len(distinct) <= 1:
                continue
            detail = [
                f"{p}·第{n}题({k or '未分类'})→{_short(c, 24)}" for p, n, c, k in entries
            ]
            asked = f"，同问「{_short(qkey, 26)}」" if qkey else ""
            v.append(Violation(
                "E018", *CODES["E018"],
                f"母题「{_short(motif)}」{asked}给出不同答案：{'；'.join(detail[:6])}",
            ))
    return v


# ---------------------------------------------------------------- L1 盲解核验
#
# L0 管账目（题号 / 分值 / 答案集合），全是纯代码事实；但**账目全对不代表答案对**。
# 实测那份 5 套卷结构近乎全绿，客观验算 67 题却有 21 处实质性错误。
# 数学正确性只能靠「独立再解一遍」，那就是这一层。
#
# 三段式，每段都不可省：
#   1. build_verification_payload —— 抽题干与选项，**剔除参考答案**（盲解的前提）；
#   2. detect_conflicts —— 盲解结果与卷面答案比对，挑出冲突；
#   3. apply_answer_fixes —— 只对仲裁为 high 置信的**客观题**回写答案，一轮为止。
#
# 为什么第 2 步之后还要再让模型仲裁一次（见 prompts.verify_answer_conflict）：
# 盲解模型自己也会算错（实测第三套 y''(0) 就是算错的）。直接按盲解改答案，等于用
# 一次未经验证的计算覆盖另一次未经验证的计算。


def build_verification_payload(paper: ExamPaper) -> list[dict[str, Any]]:
    """抽出一份卷的待核验题目，**不含任何参考答案**。

    必须剔除答案：盲解的意义就在于审校者看不到答案。看得到答案的「核验」会退化成
    确认偏误——模型倾向于认同既有答案，实测那种调用几乎查不出错。

    选项属于题干（学生作答时必须看到），所以随题面一起给出。
    """
    out: list[dict[str, Any]] = []
    for q in paper.questions:
        block = paper.blocks.get(q.number) or [q.stem]
        text = "\n".join(str(line) for line in block).strip()
        if not text:
            continue
        out.append({
            "number": q.number,
            "type": q.kind or "",
            "question": text,
            "sub_items": q.sub_items,
        })
    return out


def _paper_answer_of(paper: ExamPaper, num: int) -> tuple[str, str]:
    """卷面答案的 (形态, 归一化内容)；形态见 answer_content。"""
    return answer_content(paper, num)


def detect_conflicts(
    paper: ExamPaper, results: list[dict],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """比对盲解结果与卷面答案，返回 ``(冲突清单, 题目缺陷清单)``。

    只在**双方都给出确定结论**时才判冲突，这是压低误报的关键：

    - 盲解 ``solved=false`` 或 ``confidence=low``：它自己都没把握，不能据此质疑卷面；
    - 卷面答案缺失：那是 L0 的 E006 账目问题，不是内容冲突；
    - 选择题：比 ``option_match`` 与卷面选项字母。盲解说「没有选项相符」
      （``option_match`` 为空且 ``question_defect`` 提到选项）是**题目缺陷**，
      单独作为 defect 上报，不混进答案冲突。

    返回项直接喂给 prompts.verify_answer_conflict。
    """
    conflicts: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    by_number = {q.number: q for q in paper.questions}

    for item in results or []:
        if not isinstance(item, dict):
            continue
        num = item.get("number")
        try:
            num = int(num)
        except (TypeError, ValueError):
            continue
        if num not in by_number:
            continue
        q = by_number[num]
        cat, paper_ans = _paper_answer_of(paper, num)
        # 卷面答案的选项字母（仅选择题有意义），用于冲突记录的可读展示
        paper_letter = ""
        if cat == "choice":
            raw_paper = str(paper.answers.get(num, "") or "").strip()
            m_letter = re.match(r"^([A-D])(?![A-Za-z0-9])", raw_paper)
            paper_letter = m_letter.group(1) if m_letter else ""
        defect = str(item.get("question_defect", "") or "").strip()
        if defect:
            defects.append({
                "number": num,
                "type": q.kind,
                "kind": "question_defect",
                "defect": defect,
                "paper_answer": paper_ans,
                "blind_answer": str(item.get("my_answer_text") or item.get("my_answer") or ""),
            })
        # 盲解自己没把握 => 不据此质疑卷面
        if not item.get("solved", False):
            continue
        if str(item.get("confidence", "")).strip().lower() not in ("high", "medium"):
            continue
        if not paper_ans:
            continue

        blind_ans = ""
        letter = ""
        if cat == "choice":
            letter = str(item.get("option_match", "") or "").strip().upper()[:1]
            # 盲解没给出选项字母（通常是「没有选项相符」）：不当作答案冲突，
            # 上面的 defect 已经单独上报。
            if not letter:
                continue
            # **必须把字母解析成选项内容再比对**：``answer_content`` 返回的卷面答案是
            # 选项内容（``e^2``），而盲解给的是字母（``C``），两者不在同一空间。
            # 直接比会让**每一道选择题都报假冲突**，进而触发无谓仲裁、甚至把对的
            # 答案改错——这是会驱动自动改写的路径，必须严格对齐。
            opts = parse_options(paper.blocks.get(num) or [])
            blind_ans = _normalize_value(opts.get(letter, "")) or f"OPTION_{letter}"
        elif cat == "judge":
            raw = str(item.get("my_answer", "") or "").strip().upper()
            if raw in ("T", "F"):
                blind_ans = raw
            else:
                text = str(item.get("my_answer_text", "") or "").strip()
                blind_ans = _normalize_answer(text)
        else:
            text = str(item.get("my_answer_text", "") or item.get("my_answer") or "")
            blind_ans = _normalize_value(text)

        if not blind_ans:
            continue
        if blind_ans == paper_ans:
            continue
        conflicts.append({
            "number": num,
            "type": q.kind,
            "question": "\n".join(paper.blocks.get(num) or [q.stem]),
            # 比对用的是**内容空间**（跨卷可比：同一字母在不同卷可能指向不同内容）；
            # 字母一并带上，供仲裁模型与用户阅读时定位到具体选项。
            "paper_answer": paper_ans,
            "blind_answer": blind_ans,
            **({"paper_answer_letter": paper_letter, "blind_answer_letter": letter}
               if cat == "choice" else {}),
            "blind_reasoning": str(item.get("reasoning", "") or "")[:400],
            "answer_category": cat,
        })
    return conflicts, defects


def _rewrite_answer_text(markdown: str, num: int, new_text: str) -> tuple[str, bool]:
    """把答案区里某个题号的答案文本替换掉；返回 (新文本, 是否改动)。

    答案行的实测形态有两种：``**1.** A　**2.** C　**3.** A`` 与逐行 ``**17.** 步骤…``，
    还有裸号 ``1. A。``。替换范围是「本题号之后、下一个题号标记或行尾之前」，
    不能整行替换——那会连带删掉同一行里其它题的答案。

    只改答案文本，**不动题号**：题号是账目，由 L0 负责。
    """
    lines = str(markdown or "").split("\n")
    out: list[str] = []
    in_answer = False
    in_fence = False
    changed = False
    bold = re.compile(r"\*\*" + str(num) + r"\.\*\*")
    bare = re.compile(r"(?<![\*\d])" + str(num) + r"[\.、]\s*")
    next_mark = re.compile(r"\*\*\d+\.\*\*|(?<![\*\d])\d+[\.、]\s")

    for raw in lines:
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        is_heading, new_in_answer, _name = _track_answer_state(line, in_answer)
        if is_heading:
            in_answer = new_in_answer
            out.append(line)
            continue
        if not in_answer or changed:
            out.append(line)
            continue

        m = bold.search(line)
        marker = f"**{num}.**"
        if not m:
            mb = bare.search(line)
            if mb:
                marker = mb.group(0).rstrip()
                m = mb
        if not m:
            out.append(line)
            continue

        start = m.end()
        nxt = next_mark.search(line[start:])
        end = start + nxt.start() if nxt else len(line)
        # 被替换区间 [start, end) 同时包含**前导与尾随**分隔符：
        # `**1.** C　**2.** A　**3.** B` 里第 2 题的区间是 " A　"。
        # 只保留前导分隔符会把 `A` 后面的全角空格 `　` 一起吃掉，得到
        # `**2.** B**3.** B`——题号与上一题答案粘连，Markdown 渲染成一坨。
        # 实测踩过，必须两端都原样保留。
        segment = line[start:end]
        lead = segment[: len(segment) - len(segment.lstrip(" \u3000"))]
        trail = segment[len(segment.rstrip(" \u3000")):]
        # 裸号写法（`2. C`）的 marker 正则已经把分隔空格吃进 ``m.end()``，
        # 此时 lead 为空但**不该**再补空格，否则得到 `2.  D`（双空格）。
        # 只有加粗写法（`**2.**C`）这种题号紧贴内容、且原分隔符落在被替换区间内时，
        # 才需要兜一个空格保证渲染可读。
        sep = lead or ("" if m.group(0).endswith((" ", "\u3000")) else " ")
        rebuilt = line[:start] + sep + new_text.strip() + trail + line[end:]
        out.append(rebuilt.rstrip())
        changed = True
    return "\n".join(out), changed


# 客观题：答案可以直接回写（结论唯一确定，不存在「过程也要改」的问题）。
# 主观题（解答 / 证明 / 综合）只标记不改写：它们的答案是成段关键步骤，
# 用仲裁模型给的 4 行 reasoning 整体替换，会把原本正确的步骤一起抹掉——
# 那是用一次改写制造新的内容损失，风险高于收益。
_OBJECTIVE_KINDS = frozenset(OBJECTIVE_TYPES)


def apply_answer_fixes(
    markdown: str, paper: ExamPaper, verdicts: list[dict], *, confidence: str = "high",
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """按仲裁结果回写客观题答案；返回 (新 Markdown, 已修条目, 跳过条目)。

    三条硬边界（每条都对应一类实测风险）：

    1. **只改客观题**：见 ``_OBJECTIVE_KINDS`` 的注释。
    2. **只采信 high 置信**：仲裁模型自己也可能没把握，``confidence`` 为 medium/low
       或 ``verdict`` 为 ``undecidable`` 时只标记，不改写。
    3. **只改一轮**：调用方负责不重复调用本函数（用户明确要求「自动改，但只改一次」）。
       本函数自身不做迭代，改完即返回。
    """
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    text = str(markdown or "")
    kinds = {q.number: q.kind for q in paper.questions}

    for v in verdicts or []:
        if not isinstance(v, dict):
            continue
        try:
            num = int(v.get("number"))
        except (TypeError, ValueError):
            continue
        verdict = str(v.get("verdict", "") or "").strip()
        conf = str(v.get("confidence", "") or "").strip().lower()
        answer = str(v.get("correct_answer", "") or "").strip()
        kind = kinds.get(num, "")
        entry = {
            "number": num,
            "type": kind,
            "verdict": verdict,
            "confidence": conf,
            "correct_answer": answer,
            "correct_answer_text": str(v.get("correct_answer_text", "") or ""),
            "reasoning": str(v.get("reasoning", "") or "")[:300],
            "question_defect": str(v.get("question_defect", "") or ""),
        }
        if verdict in ("undecidable", "question_broken"):
            entry["skip_reason"] = f"仲裁结论为 {verdict}，不自动改写"
            skipped.append(entry)
            continue
        if verdict not in ("paper_wrong", "both_wrong"):
            entry["skip_reason"] = f"仲裁认为卷面答案无需修改（{verdict or '未给出结论'}）"
            skipped.append(entry)
            continue
        if conf != confidence:
            entry["skip_reason"] = f"仲裁置信度为 {conf or '未给出'}，只采信 {confidence}"
            skipped.append(entry)
            continue
        if kind not in _OBJECTIVE_KINDS:
            entry["skip_reason"] = (
                f"{kind or '主观题'}的答案是成段关键步骤，不做自动改写（避免用仲裁摘要"
                "整体替换掉原本正确的步骤）"
            )
            skipped.append(entry)
            continue
        if not answer:
            entry["skip_reason"] = "仲裁未给出确定答案"
            skipped.append(entry)
            continue

        new_text, changed = _rewrite_answer_text(text, num, answer)
        if changed:
            text = new_text
            entry["fixed"] = True
            applied.append(entry)
        else:
            entry["skip_reason"] = f"答案区未找到题号 {num}，无法回写"
            skipped.append(entry)
    return text, applied, skipped


# ---------------------------------------------------------------- 管线接入
#
# 下面三个函数是 tutorials.py 与 exam_check 之间的唯一接口，负责回答两个问题：
# 「这个 section 是不是一份卷」与「这份卷属于哪种规范」。把判定放在这里而不是
# 调用方，是为了避免各调用点各写一套判断（本项目已因此吃过亏：prompts.py 与
# format_specs.py 各自维护过一份卷名词表，漏了「模拟卷」「自测卷」，导致这两类
# 合法卷名静默丢掉卷面自检）。

_EXAM_NOUN_RE = re.compile(
    r"(单元检测卷|单元测验卷|单元试卷|检测卷|测验卷|测试卷|自测卷|模拟卷|练习卷|试卷|训练卷|测验)"
)
# 练习规范特有的节内结构（「一、易错辨析 / 二、训练 / 参考答案」）
_EXERCISE_MARKER_RE = re.compile(r"(易错辨析|参考答案)")


def section_body(section: dict) -> str:
    """取出一个 section 的可校验正文（拼接全部 content 块的 body）。

    试卷类交付物按规范「一节只输出一个 content 块」，但模型有时会拆成多块
    （例如把参考答案单独放一块），所以必须拼接全部块，只看第一块会漏掉答案区。
    """
    parts: list[str] = []
    for block in (section or {}).get("content") or []:
        if isinstance(block, dict):
            body = str(block.get("body", "") or "")
            if body.strip():
                parts.append(body)
    if not parts:
        # 兼容旧结构（explanation / steps）与裸 markdown 字段
        text = str((section or {}).get("markdown", "") or "")
        return text
    return "\n\n".join(parts)


def classify_spec(section_title: str, format_spec: dict | None, body: str) -> str | None:
    """判断这段内容属于哪种可校验规范；返回 None 表示不是卷、不参与校验。

    判定优先级（都是确定性事实，不靠模型自觉）：
    1. 规范快照的 scene：``exam_paper`` → 试卷；``exercise`` → 练习。
    2. scene 缺失时退回标题与正文特征：标题含卷种名词 → 试卷；
       正文有「易错辨析」这类练习规范专属结构 → 练习。
    """
    scene = str((format_spec or {}).get("scene", "") or "").strip()
    if scene == "exam_paper":
        return "exam"
    if scene == "exercise":
        return "exercise"
    title = str(section_title or "")
    body_head = str(body or "")[:4000]
    if _EXAM_NOUN_RE.search(title) and is_exam_markdown(body_head):
        return "exam"
    if is_exam_markdown(body_head) and _EXERCISE_MARKER_RE.search(body_head):
        return "exercise"
    return None


def apply_to_section(section: dict, format_spec: dict | None) -> dict:
    """对单个 section 做一轮确定性校验与修复，返回 {violations, fixed, changed}。

    **就地修改** section 的 content 块 body（auto_fixable 的违规），并返回完整违规
    清单供调用方写入 quality_report。非卷类 section 原样返回，不做任何改动。

    只修一轮：用户明确要求「自动改，但只改一次」。修完若仍有违规，如实留在
    violations 里，不再迭代——多轮修复会让 diff 不可解释。
    """
    body = section_body(section)
    spec = classify_spec(str(section.get("title", "")), format_spec, body)
    if spec is None or not body.strip():
        return {"violations": [], "fixed": 0, "changed": False, "spec": None}

    fixed_md, violations = fix_markdown(body, str(section.get("title", "")), spec=spec)
    changed = fixed_md != body
    if changed:
        # 把修复后的正文写回：规范一节一块，所以整段回填到第一个块，其余块清空。
        # 多块情况下不能逐块回填——题号与分值修复是跨块的（答案可能在第二块）。
        blocks = [b for b in (section.get("content") or []) if isinstance(b, dict)]
        if blocks:
            blocks[0]["body"] = fixed_md
            for extra in blocks[1:]:
                extra["body"] = ""
        else:
            section["markdown"] = fixed_md
    return {
        "violations": [v.to_dict() for v in violations],
        "fixed": sum(1 for v in violations if v.fixed),
        "changed": changed,
        "spec": spec,
    }


def apply_to_content(content: dict) -> dict:
    """对整份教程内容做 L0 校验：各章节 + 额外练习文件。

    额外练习文件（``content["extra_exercises"]["markdown"]``）此前是**完全裸奔**的：
    ``utils.parse_exercise_numbers`` 只从它里面抽题号做计数，一条验收标准都没校验。
    这里一并纳入，按练习规范的可判定项检查。

    跨卷一致性（E017/E018）只在同一份文档内有 2 份以上卷时才有意义，所以放在
    逐卷处理之后统一跑。
    """
    summary: dict[str, Any] = {"sections": [], "extra_exercises": None, "cross": []}
    format_spec = content.get("format_spec") or {}
    papers: list[tuple[str, ExamPaper]] = []

    for section in content.get("sections") or []:
        if not isinstance(section, dict):
            continue
        result = apply_to_section(section, format_spec)
        summary["sections"].append({
            "title": str(section.get("title", "")),
            **result,
        })
        if result["spec"]:
            body = section_body(section)
            if is_exam_markdown(body):
                papers.append((str(section.get("title", "")), parse_paper(body)))

    extra = content.get("extra_exercises")
    if isinstance(extra, dict) and str(extra.get("markdown", "") or "").strip():
        md = str(extra.get("markdown", ""))
        fixed_md, violations = fix_extra_exercises(md, str(extra.get("title", "")))
        if fixed_md != md:
            extra["markdown"] = fixed_md
        summary["extra_exercises"] = {
            "violations": [v.to_dict() for v in violations],
            "fixed": sum(1 for v in violations if v.fixed),
            "changed": fixed_md != md,
            "spec": "exercise",
        }

    if len(papers) >= 2:
        summary["cross"] = [v.to_dict() for v in check_cross_paper(papers)]
    return summary


def _unfixed(summary: dict) -> tuple[list[dict], list[dict]]:
    """收集未修复违规，按严重度分成 (blocking, advisory)。跨卷条目一律视为未修复。"""
    blocking: list[dict] = []
    advisory: list[dict] = []
    buckets = [
        [(i.get("title", ""), v) for i in (summary.get("sections") or []) for v in i.get("violations") or []],
        [("额外练习", v) for v in (summary.get("extra_exercises") or {}).get("violations") or []],
        [("跨卷", v) for v in summary.get("cross") or []],
    ]
    for group in buckets:
        for title, v in group:
            if v.get("fixed"):
                continue
            v = {**v, "_title": title}
            (blocking if v.get("severity", SEVERITY.get(v["code"], "blocking")) == "blocking"
             else advisory).append(v)
    return blocking, advisory


# 练习文件的节标题：``## 第 1 章 …`` / ``## 常见错误与排查``。
# 练习规范是「一节一章，各节独立编号，答案在本节末尾」，所以**必须按节切分后逐节校验**：
# 整份文件当成一份卷解析时，「答案区一旦开启持续到末尾」这条规则会把第二节及以后的
# 题目全部吞进答案区（实测 demo 练习文件因此把 6 道题误判成答案），产生大片假阳性。
_EXERCISE_SECTION_RE = re.compile(r"^##\s+(?!#)(.*)$")


def split_exercise_sections(markdown: str) -> list[tuple[str, str]]:
    """把额外练习文件按 ``## `` 节标题切成 [(节名, 节正文)]。

    没有 ``## `` 节标题时整份文件作为一节返回（兼容单节练习文件）。
    """
    out: list[tuple[str, list[str]]] = []
    name, buf = "", []
    for line in str(markdown or "").split("\n"):
        m = _EXERCISE_SECTION_RE.match(line.rstrip())
        if m:
            if buf or name:
                out.append((name, buf))
            name, buf = m.group(1).strip(), []
            continue
        buf.append(line)
    if buf or name:
        out.append((name, buf))
    return [(n, "\n".join(b)) for n, b in out]


def fix_extra_exercises(markdown: str, title: str = "") -> tuple[str, list[Violation]]:
    """逐节校验并修复额外练习文件（练习规范：一节一章，答案在本节末尾）。

    节标题行原样保留、逐节调用 ``fix_markdown(spec="exercise")``，最后按原顺序拼回。
    跨节母题重复（E017/E018）在逐节解析后统一跑——练习文件各节对应教程各章，
    同一母题在多节重复出现同样要报（规范明令「避免重复考查」）。
    """
    sections = split_exercise_sections(markdown)
    if not sections:
        return markdown, []
    out: list[str] = []
    violations: list[Violation] = []
    papers: list[tuple[str, ExamPaper]] = []
    for name, body in sections:
        fixed_body, vs = fix_markdown(body, name, spec="exercise")
        violations.extend(vs)
        if name:
            out.append(f"## {name}")
        out.append(fixed_body)
        if is_exam_markdown(fixed_body):
            papers.append((name or title, parse_paper(fixed_body, name or title)))
    if len(papers) >= 2:
        violations.extend(check_cross_paper(papers))
    return "\n".join(out), violations


def apply_to_extra_exercises(content: dict) -> dict | None:
    """只校验并修复 ``content["extra_exercises"]``；返回该文件的校验结果或 None。

    必须单独提供这个入口，不能只靠 ``apply_to_content``：在生成管线里，额外练习是
    配套文件，与章节**并行**生成，章节质量检查算完之后才合并进 content
    （见 tutorials._sections_worker：先 apply_to_content，再写入 extra_exercises）。
    如果只在 apply_to_content 里校验，额外练习文件会整份逃过校验——而它此前
    就是完全裸奔的（utils.parse_exercise_numbers 只从它里面抽题号计数）。
    """
    extra = content.get("extra_exercises")
    if not isinstance(extra, dict) or not str(extra.get("markdown", "") or "").strip():
        return None
    md = str(extra.get("markdown", ""))
    fixed_md, violations = fix_extra_exercises(md, str(extra.get("title", "")))
    if fixed_md != md:
        extra["markdown"] = fixed_md
    return {
        "violations": [v.to_dict() for v in violations],
        "fixed": sum(1 for v in violations if v.fixed),
        "changed": fixed_md != md,
        "spec": "exercise",
    }


# quality_checks 产出的检查项名。调用方在**二次合并**时必须先剔除同名旧条目，
# 否则会出现两条「试卷卷面账目校验」，前端计数翻倍。
EXAM_CHECK_NAMES = ("试卷卷面账目校验", "跨卷命题一致性")


def quality_checks(summary: dict) -> list[dict[str, Any]]:
    """把 L0 汇总转成 quality_report["checks"] 的条目（与 engine.check_structure 同构）。

    ``passed`` 只看 blocking 级：留白行数、母题重复这类 advisory 项不该把整份教程
    标成「待改进」，否则真正的账目错误与答案冲突会被噪音淹没。
    """
    checks: list[dict[str, Any]] = []
    blocking, advisory = _unfixed(summary)
    codes = [v["code"] for v in blocking]

    checked_titles = [
        i.get("title", "") for i in (summary.get("sections") or []) if i.get("spec")
    ]
    checks.append({
        "name": "试卷卷面账目校验",
        "passed": not codes,
        "detail": (
            f"校验 {len(checked_titles)} 份卷 / 练习文件；阻塞项 {len(codes)} 条"
            + (f"（{', '.join(sorted(set(codes))[:6])}）" if codes else "")
            + (f"；提示项 {len(advisory)} 条" if advisory else "")
        ) if checked_titles or codes or advisory else "无试卷类章节，跳过",
    })
    cross = summary.get("cross") or []
    if cross:
        # E018（同母题不同答案）是 blocking：学生会在同一份文档里看到互斥结论；
        # E017（母题重复）只是命题质量提示，不该让整份卷子判为不合格。
        conflicts = sum(1 for c in cross if c.get("code") == "E018")
        checks.append({
            "name": "跨卷命题一致性",
            "passed": conflicts == 0,
            "detail": f"母题重复 {sum(1 for c in cross if c.get('code') == 'E017')} 处；"
                      f"同母题答案冲突 {conflicts} 处",
        })
    return checks


def quality_issues(summary: dict, *, limit: int = 12, advisory: bool = False) -> list[str]:
    """把未修复违规转成 quality_report["issues"] 的可读条目。

    默认只返回 blocking 级——issues 会驱动 ``tutorial.status = drafted_with_issues``
    与前端「待改进」标记，把留白行数这类排版偏好塞进去会让标记失去意义。
    ``advisory=True`` 时追加提示项（用于调试与质量报告详情页）。
    """
    blocking, advisories = _unfixed(summary)
    items = blocking + (advisories if advisory else [])
    return [f"[{v['code']}] {v.get('_title') or ''}：{v['detail']}".replace("：：", "：")
            for v in items][:limit]


# ---------------------------------------------------------------- 自动修复
#
# 修复策略（重要取舍，改这里前先读完）：
#
# 1. **一轮修复，不迭代**。用户明确要求「自动改，但只改一次」：每个修复动作在单次
#    遍历里执行一次，修完即止，不做「修复 → 再校验 → 再修复」的循环。理由是多轮
#    修复会让 diff 不可解释——用户看到卷子被改了三遍，无法判断哪一遍引入了新问题。
#    修完若仍有违规，如实留在 quality_report 里。
#
# 2. **只修无歧义的**。有唯一正确答案的才改：
#      - 题号形式（裸 `7.` → `**7.**`）、题号连续性（重编号）
#      - 分值括注（从分值表按题型回填，表里也没有就不动，只报告）
#      - 答案小节名（一律 → `### 参考答案`）
#      - 占位文字（删除，规范明令留白只能用空行）
#      - 卷内 #/## 标题（降级为 ###）
#      - 账目（卷面说明、分值表、合计行 → 以题面实际分值之和为准重算）
#    有歧义或破坏性的只报告，不动手：
#      - E009 元栏目：整节删除是不可逆的内容损失，交人工决定
#      - E010 题型顺序：重排题目会打乱答案对应关系
#      - E012/E015 答案详略与不确定性：属内容层，由 L1 盲解核验处理
#
# 3. **账目以「题面实际分值之和」为唯一事实来源**。实测那份卷子题面写了 96 分、
#    卷面声明 100 分。代码不能凭空补 4 分——把 4 分加到哪道题都是武断决定（会改
#    题干括注、可能与答案不匹配）。所以统一以「题面已经写出的分值」为准，反向校正
#    卷面说明与分值表，并在 detail 里写明校正依据。模板层的病根（综合题 12 分）已
#    单独修复，见 format_specs._EXAM_CONTENT_STRUCTURE。


def _fix_renumber_and_scores(
    lines: list[str], paper: ExamPaper, violations: list[Violation],
) -> tuple[list[str], dict[int, int]]:
    """单轮修复：题号形式 / 连续编号 / 分值括注。返回 (新行, 旧号→新号映射)。"""
    # 分值回填表：题型 → 每题分值（只在分值表给出统一分值时才回填）
    fill: dict[str, int] = {}
    for r in paper.table:
        each = _num(r["each"])
        if each:
            fill[r["type"]] = each

    # 题号重复时禁用重编号（原因见 check_paper 的 E005 注释）：映射会多对一坍缩，
    # 答案区题号跟着错配。此时仍然修「加粗形式」与「分值括注」——这两个动作不改变
    # 题号，是安全的；只有号码本身保持原样。
    seen_nums = [q.number for q in paper.questions]
    has_dup = len(seen_nums) != len(set(seen_nums))

    out: list[str] = []
    mapping: dict[int, int] = {}
    counter = 0
    in_answer = False
    in_fence = False
    fixed_bold = fixed_score = 0

    for raw in lines:
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        stripped = line.strip()

        # 答案区状态机必须与 parse_paper 完全一致（见 _track_answer_state）：
        # 答案区一旦开启就持续到卷末。若这里各自判定，答案区里夹的元栏目小节会把
        # in_answer 关掉，答案行随后被当成题目重新编号（实测第三套被编成 19..36）。
        is_heading, new_in_answer, _name = _track_answer_state(line, in_answer)
        if is_heading:
            in_answer = new_in_answer
            out.append(line)
            continue

        if in_answer:
            out.append(line)
            continue

        bold = _Q_BOLD_RE.match(stripped)
        bare = _Q_BARE_RE.match(stripped) if not bold else None
        if not (bold or bare):
            out.append(line)
            continue

        m = bold or bare
        old_num = int(m.group(1))
        if has_dup:
            new_num = old_num
        else:
            counter += 1
            new_num = counter
            if new_num != old_num:
                mapping[old_num] = new_num
        rest = m.group(2).strip()
        score_m = _SCORE_RE.match(rest)
        if score_m:
            score = int(score_m.group(1))
            body = rest[score_m.end():]
        else:
            score = None
            body = rest
        if score is None:
            kind = next(
                (q.kind for q in paper.questions if q.number == old_num and q.kind in fill),
                None,
            )
            if kind and fill.get(kind):
                score = fill[kind]
                fixed_score += 1
        # 有分值时紧贴题号写全角括注（规范要求「**n.**（4 分）题干」），
        # 无分值时必须补一个空格：否则 `**1.** 设…` 会被压成 `**1.**设…`，
        # 题号与题干粘连，Obsidian 里渲染成加粗数字直接接正文。
        score_text = f"（{score} 分）" if score is not None else " "
        # 保留原行的缩进，避免破坏列表嵌套
        indent = line[: len(line) - len(line.lstrip())]
        out.append(f"{indent}**{new_num}.**{score_text}{body}".rstrip())
        if not bold:
            fixed_bold += 1

    if fixed_bold:
        for v in violations:
            if v.code == "E003":
                v.fixed = True
    if fixed_score:
        for v in violations:
            if v.code == "E004":
                v.fixed = True
    if any(v.code == "E005" for v in violations):
        for v in violations:
            if v.code == "E005":
                v.fixed = True
    return out, mapping


def _fix_answer_numbers(lines: list[str], mapping: dict[int, int]) -> list[str]:
    """答案区题号按「旧号→新号」映射同步；映射缺失的题号保持原样。"""
    out, in_answer, in_fence = [], False, False
    for raw in lines:
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        stripped = line.strip()
        is_heading, new_in_answer, _name = _track_answer_state(line, in_answer)
        if is_heading:
            in_answer = new_in_answer
            out.append(line)
            continue
        if not in_answer or not mapping:
            out.append(line)
            continue

        def repl(mo: re.Match) -> str:
            n = int(mo.group(1))
            return f"**{mapping.get(n, n)}.**"

        out.append(_ANS_NUM_RE.sub(repl, line))
    return out


def _fix_answer_headings(lines: list[str], violations: list[Violation]) -> list[str]:
    """把卷内答案小节归一成唯一的「### 参考答案」。

    规范要求每卷末尾有且仅有一个「### 参考答案」，实测出现过 5 种写法（选择题答案 /
    判断题答案 / 解答题答案 / 参考答案与评分说明 / 参考答案与诊断说明）。

    修复方式只动**标题行**，绝不删答案正文：
      - 已存在规范名时：删掉多余的自拟标题行（答案内容顺势并入该小节）；
      - 不存在规范名时：把第一个答案小节改名为「### 参考答案」，其余标题行删掉。

    不能给多余小节加「（续）」后缀：后缀名不再被 ``is_answer_heading`` 识别，
    重解析时其后答案会被当成题目，反而制造「题号重复 + 缺分值」的连锁假阳性
    （实测第三套就是这样从 3 条违规恶化到 5 条）。
    """
    idxs = []
    in_fence = False
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s*(.*)$", line.strip())
        if m and is_answer_heading(_normalize_heading(m.group(2))):
            idxs.append((i, m.group(1), _normalize_heading(m.group(2))))
    if not idxs:
        return lines

    has_canonical = any(_ANSWER_HEADING_RE.match(name) and name == "参考答案" for _, _, name in idxs)
    drop: set[int] = set()
    rename: dict[int, str] = {}
    if has_canonical:
        first_canonical = next(i for i, _, name in idxs if name == "参考答案")
        for i, _, _name in idxs:
            if i != first_canonical:
                drop.add(i)
    else:
        first_i, level, _name = idxs[0]
        rename[first_i] = f"{level} 参考答案"
        for i, _, _n in idxs[1:]:
            drop.add(i)

    out = []
    for i, raw in enumerate(lines):
        if i in drop:
            continue
        if i in rename:
            out.append(rename[i])
            continue
        out.append(raw.rstrip())
    if drop or rename:
        for v in violations:
            if v.code == "E002":
                v.fixed = True
    return out


def _fix_placeholders(lines: list[str], violations: list[Violation]) -> list[str]:
    """删除占位文字；整行只有占位文字时删掉该行。"""
    out, changed = [], False
    for raw in lines:
        line = raw.rstrip()
        if _PLACEHOLDER_RE.search(line):
            new = _PLACEHOLDER_RE.sub("", line).strip()
            changed = True
            if new:
                out.append(new)
            continue
        out.append(line)
    if changed:
        for v in violations:
            if v.code == "E014":
                v.fixed = True
    return out


def _fix_heading_levels(lines: list[str], violations: list[Violation]) -> list[str]:
    """卷内 #/## 标题降级为 ###（章标题由系统输出，不该出现在卷内正文）。"""
    out, in_fence, changed = [], False, False
    for raw in lines:
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        m = re.match(r"^(#{1,2})\s+(.*)$", line.strip())
        if m:
            changed = True
            out.append(f"### {m.group(2)}")
            continue
        out.append(line)
    if changed:
        for v in violations:
            if v.code == "E011":
                v.fixed = True
    return out


def _fix_accounting(lines: list[str], paper: ExamPaper, violations: list[Violation]) -> list[str]:
    """以题面实际分值之和为唯一事实来源，重算卷面说明、分值表与合计行。"""
    # 实际：题型 → (题号列表, 分值列表)
    by_kind: dict[str, list[ExamQuestion]] = {}
    for q in paper.questions:
        if q.kind:
            by_kind.setdefault(q.kind, []).append(q)
    scored = [q for q in paper.questions if q.score is not None]
    if not paper.has_table or not scored:
        return lines
    # 同题型分值非均匀时不改账目：见 score_is_uniform 的注释。
    # 强行「修」会产出比原来更矛盾的表（2×20=40 却写小计 45）。
    if not score_is_uniform(paper):
        return lines
    actual_total = sum(q.score for q in scored)
    actual_count = len(set(q.number for q in paper.questions))

    out, in_fence, fixed = [], False, False
    for raw in lines:
        line = raw.rstrip()
        if _is_code_fence(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        stripped = line.strip()

        # 卷面说明引子
        if _LEAD_RE.search(stripped) and stripped.startswith(">"):
            new = re.sub(r"满分\s*\d+\s*分", f"满分 {actual_total} 分", stripped)
            new = re.sub(r"共\s*\d+\s*题", f"共 {actual_count} 题", new)
            if new != stripped:
                fixed = True
            out.append(new)
            continue

        # 分值表数据行 / 合计行
        if _TABLE_ROW_RE.match(stripped) and not _TABLE_SEP_RE.match(stripped):
            cells = [_cell(c) for c in stripped.strip("|").split("|")]
            if len(cells) >= 5 and cells[0] != "题型":
                if cells[0] == "合计":
                    new_cells = [cells[0], f"1\u2013{actual_count}" if actual_count else cells[1],
                                 str(actual_count), cells[3], str(actual_total)]
                    new = "| " + " | ".join(new_cells) + " |"
                    if new != stripped:
                        fixed = True
                    out.append(new)
                    continue
                qs = by_kind.get(cells[0], [])
                if qs:
                    nums = sorted(q.number for q in qs)
                    span = f"{nums[0]}\u2013{nums[-1]}" if len(nums) > 1 else str(nums[0])
                    each_vals = [q.score for q in qs if q.score is not None]
                    sub = sum(each_vals)
                    each_txt = str(each_vals[0]) if each_vals and len(set(each_vals)) == 1 else cells[3]
                    new_cells = [cells[0], span, str(len(nums)), each_txt, str(sub)]
                    new = "| " + " | ".join(new_cells) + " |"
                    if new != stripped:
                        fixed = True
                    out.append(new)
                    continue
        out.append(line)
    if fixed:
        for v in violations:
            if v.code in ("E007", "E008", "E016"):
                v.fixed = True
    return out


def fix_markdown(
    markdown: str,
    title: str = "",
    *,
    demote_headings: bool = False,
    spec: str = "exam",
) -> tuple[str, list[Violation]]:
    """一轮确定性修复 + 完整违规清单（含未修复项）。

    返回 (修复后的 Markdown, 违规清单)。违规项的 ``fixed`` 字段标记该条是否已被
    本轮修复；调用方应把整个清单写进 quality_report，让「修过什么」可追溯。

    ``demote_headings`` 默认关闭，这是**破坏性防护**而不是偷懒：E011 的修复动作是
    把 #/## 降级为 ###，而整份文档的 ``# 卷名`` 与 ``## 一、第 1 章 … 单元检测卷``
    都是系统输出的章标题（见 tutorials._render_deliverable_blocks），降级它们会直接
    破坏文档结构。只有当调用方传进来的是**单卷正文**（不含系统章标题）时才应开启。
    """
    text = str(markdown or "")
    paper = parse_paper(text, title=title)
    violations = check_paper(paper, spec=spec)
    violations += check_answer_detail(text, paper, spec=spec)
    # 文档级检查必须在这里一起跑：E011（正文标题层级）与 E014（占位文字）不由
    # check_paper 产出，漏掉这一步会让「删除作答区域占位文字」这条修复永远不触发。
    # 调用方若在整份文档上跑，应先 split_papers 再逐卷调用本函数，标题层级检查
    # 由调用方用 check_whole_document 在文档层面补充（章标题是系统输出的，卷内不该有）。
    enabled = SPEC_CODES.get(spec, SPEC_CODES["exam"])
    violations += [x for x in check_whole_document(text) if x.code in enabled]
    # 留白行数是试卷规范的排版要求；练习规范不规定留白，不适用 E013
    if "E013" in enabled:
        violations += check_blanks(text, paper)
    if not violations:
        return text, []

    fixable = {v.code for v in violations if v.auto_fixable}
    lines = text.split("\n")

    if fixable & {"E003", "E004", "E005"}:
        lines, mapping = _fix_renumber_and_scores(lines, paper, violations)
        lines = _fix_answer_numbers(lines, mapping)
    if "E002" in fixable or any(v.code == "E002" for v in violations):
        lines = _fix_answer_headings(lines, violations)
    if "E011" in fixable and demote_headings:
        lines = _fix_heading_levels(lines, violations)
    if "E014" in fixable:
        lines = _fix_placeholders(lines, violations)
    # 账目修复必须在题号/分值修复之后重解析，否则用的是修复前的事实
    if {v.code for v in violations} & {"E007", "E008", "E016"}:
        repaired = "\n".join(lines)
        lines = _fix_accounting(lines, parse_paper(repaired, title=title), violations)

    return "\n".join(lines), violations
