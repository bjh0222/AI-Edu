# -*- coding: utf-8 -*-
"""阅读教程「原文摘录」的确定性忠实性校验（L0，零模型调用、零 token）。

设计依据（与 ``exam_check`` 同源：不是新增规则，是把规范里已经写死的铁律变成代码）：

``format_specs``（数据库 format_specs 表 name="阅读教程规范" scene="reading_guide"）
的 ``custom_markdown``「原文摘录与出处规则」写明：

1. 原文摘录一律用 Markdown 引用块，``>`` 起行，**逐字照录**；不得改写、缩写、合并或「润色」。
2. 摘录过长时只截承担论证功能的关键句，省略处用 ``……`` 标示。
3. 引用块前面的 ``#####`` 标题必须给出章节定位，格式固定为「句段N（第X章第Y节）」。
4. 页码只在材料本身带页码、且能确定对应关系时才写。
5. 材料里没有的内容一律不得补写。

``forbidden_rules`` 另有「禁止编造原文里没有的引文、术语或论证步骤」「禁止改写、扩写或
『润色』原文摘录」「禁止把 AI 自己的解释写成学界共识」。

为什么这一层必须是代码而不是提示词：**虚构引文是导读类交付物最致命的失效**——读者拿着
一段「原文」回查却找不到，整份导读的可信度归零；而它恰好是纯字符串匹配可判定的事实，
不需要模型自觉，也不需要再花一次往返。与 ADR-015 / ADR-018 的结论一致：结构由确定性
规则决定。

本模块**只判定不改写**：引文错误没有唯一正确的修法（补什么、删什么都要回到材料重读），
机械改写只会把「编造」变成「另一段编造」。因此全部违规 ``auto_fixable=False``。

误判防护（比漏判更重要，因为 Q001 是 blocking）。以下四条全部是**实测踩出来的**，
用真实产物「毛选第二卷导读 · 阅读教程规范」（42 节 / 156 个摘录块）逐条校准过：

1. **只校验「关键句段解读」作用域内的引用块**。「本章概要」里的
   ``> 本章在全书中的位置：…`` 是规范 content_structure 给的模板引导句，本来就不在材料里；
   不加作用域限制会把每份导读都判成虚构引文。
2. **剥掉注释标记**（``〔1]``、``[1]``、``①``）。材料原文是「为了声讨卖国贼汪精卫〔1〕，
   又是为了…」，摘录自然省略编者注编号，不剥就判成编造。
3. **容忍段首尾标点差异**。材料是「…以退让求团结则团结亡，这一真理…」，摘录截成
   「…以退让求团结则团结亡。」——规范第 2 条本就允许截关键句，截断处补句号是正常排版。
4. **材料为空时不判 Q001/Q003**。没有比对基准就报 blocking，等于凭空指控。
5. **Q002 用材料验证定位**：括号里写了材料真实存在的标题（「抗日战争的情况和教训」）
   就是有效定位，正则穷举不完材料的组织方式，但「材料里找不找得到」是可判定事实。

Q002/Q004 同样按实测放宽（见各自 docstring）：真实教程的定位写法与「材料未涉及」标注
形态远比规范举例丰富，卡死规范字面会报出几十条 advisory 噪音，反而淹没 Q001。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# ------------------------------------------------------------------ 规范条文
#
# basis 一律指向规范原文的具体条文，让「为什么算违规」可回溯到规范而非代码私货。
_BASIS_VERBATIM = (
    "阅读教程规范 custom_markdown「原文摘录与出处规则」第 1 条：原文摘录一律用引用块逐字照录，"
    "不得改写、缩写、合并或润色；forbidden_rules：禁止编造原文里没有的引文"
)
_BASIS_LOCATOR = (
    "阅读教程规范 custom_markdown「原文摘录与出处规则」第 3 条：引用块前面的 ##### 标题"
    "必须给出章节定位，格式固定为「句段N（第X章第Y节）」"
)
_BASIS_PAGE = (
    "阅读教程规范 custom_markdown「原文摘录与出处规则」第 4 条：页码只在材料本身带页码、"
    "且能确定对应关系时才写；不确定时一律用章节定位"
)
_BASIS_UNKNOWN = (
    "阅读教程规范 custom_markdown「材料不足时的标注格式」第 1 条：模块可写但材料无依据时，"
    "写一行「材料未涉及，待核实：（说明缺什么）」"
)
_BASIS_TRIPARTITE = (
    "阅读教程规范 custom_markdown「观点三方标记规则」：作者本人的观点 / 学界观点 / AI 的分析"
    "必须分区书写、可区分，不得混写；forbidden_rules：禁止把 AI 自己的解释写成学界共识"
)

CODES = {
    "Q001": ("摘录不是材料原文（逐字比对未命中）", _BASIS_VERBATIM),
    "Q002": ("摘录的定位标题没有给出可回查的章节定位", _BASIS_LOCATOR),
    "Q003": ("页码引用无法在材料中核实", _BASIS_PAGE),
    "Q004": ("「材料未涉及，待核实」标注格式不正确", _BASIS_UNKNOWN),
    "Q005": ("作者观点 / 学界观点 / AI 分析混写", _BASIS_TRIPARTITE),
}


@dataclass
class Violation:
    """一条确定性违规（结构与 ``exam_check.Violation`` 逐字同构，便于同一套报告消费）。"""

    code: str
    rule: str
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


# Q001 是唯一的 blocking：它判定的是「这段话在材料里根本不存在」，是纯字符串事实，
# 而后果是读者按图索骥找不到原文——比排版不规范严重得多。
# Q002~Q005 全是 advisory：标题格式、页码、标注措辞、观点分区都可能有规范未穷举的
# 合理写法，把它们算进 blocking 会让几乎每份导读都变成「待改进」，反而淹没 Q001。
SEVERITY: dict[str, str] = {
    "Q001": "blocking",   # 虚构 / 改写引文：交付物最致命的失效
    "Q002": "advisory",   # 定位标题格式
    "Q003": "advisory",   # 页码无法核实
    "Q004": "advisory",   # 「材料未涉及」标注格式
    "Q005": "advisory",   # 三方观点混写（保守启发式）
}


def is_blocking(code: str) -> bool:
    return SEVERITY.get(code, "blocking") == "blocking"


# ------------------------------------------------------------------ 文本归一化

_WS_RE = re.compile(r"\s+")
# 抽取与排版产生的不可见字符：PDF 换行、复制粘贴常带，留着会让真引文比对失败
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad]")
# 注释标记：材料（《毛选》《马克思恩格斯选集》这类政治文献、以及学术著作）在正文里
# 内嵌编者注编号，摘录时它们会被自然省略。**必须两侧一起剥掉**，否则实测把
# 「为了声讨卖国贼汪精卫〔1〕，又是为了团结一切抗日力量」判成虚构引文（Q001 blocking）——
# 那是抽取痕迹，不是编造，报出来就是最恶性的假阳性。
# 只剥这三种确定形态：「（一）（二）」这类**内容级**枚举绝不剥，剥了会掩盖真实差异。
_ANNOTATION_RE = re.compile(r"〔\s*\d{1,3}\s*〕|\[\s*\d{1,3}\s*\]|[\u2460-\u2473\u3251-\u32bf]")
# 引号体系统一：材料用「」/ “” 与教程用另一套时，字形不同但**逐字内容相同**。
# 这不是放宽忠实性要求，而是承认标点渲染差异（规范禁的是改写实词，不是换引号样式）。
_QUOTE_TABLE = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u300c": '"', "\u300d": '"', "\u300e": '"', "\u300f": '"',
    "\u301d": '"', "\u301e": '"',
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\uff02": '"', "\uff07": "'",
})
# 段首 / 段尾标点：见 _segment_hit 的说明（实测第 3 条误判防护）。
_EDGE_PUNCT = (
    "\u3002\uff0c\u3001\uff1b\uff1a\uff01\uff1f\u2026\u00b7\u301c~,.:;!?-_"
    "\u2014\u2015\u2013'`()（）[]〔〕【】《》<>「」『』" + '"'
)

# 省略号：规范要求用 ``……``，实测还出现单个 ``…``、ASCII ``...``、``。。。``
_ELLIPSIS_RE = re.compile(r"\u2026+|\.{3,}|\u00b7{3,}|\u30fb{3,}")

# 归一化后短于此长度的分段不参与比对：太短的子串在长材料里偶然命中的概率不可忽略，
# 判它「编造」就是拿偶然性当结论。宁可漏判不误判（Q001 是 blocking）。
_MIN_SEGMENT_CHARS = 4


def _canon(text: str) -> str:
    """比对用归一化：NFKC → 去不可见字符 → 统一引号 → 剥注释标记 → 去全部空白。

    去空白是必需的：材料按行抽取，一句话常被拆成多行；教程摘录把它连成一行。
    NFKC 顺带把全角括号 / 全角字母数字 / ``…`` 折成半角与 ``...``，吸收排版差异。
    """
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = _INVISIBLE_RE.sub("", t)
    t = t.translate(_QUOTE_TABLE)
    # 注释标记必须在 NFKC 之后剥：NFKC 会把 ``①`` 折成 ``(1)``、``〔〕`` 折成 ``[]``，
    # 顺序颠倒就漏剥了。
    t = _ANNOTATION_RE.sub("", t)
    return _WS_RE.sub("", t)


def _segment_hit(canon_seg: str, canon_material: str) -> bool:
    """这一段是否在材料里命中；**只**容忍段首尾的标点差异。

    实测误判：材料「…以退让求团结则团结亡，这一真理，已经逐渐为党内同志们所了解。」，
    摘录截成「…以退让求团结则团结亡。」。严格子串比对差一个句读就判成「虚构引文」，
    指控模型编造——而规范第 2 条本来就允许「只截承担论证功能的关键句」。
    所以先严格比对，失败后再剥掉**边界**标点比对一次；段内任何实词差异照样判未命中，
    不降低忠实性要求。
    """
    if not canon_seg:
        return True
    if canon_seg in canon_material:
        return True
    inner = canon_seg.strip(_EDGE_PUNCT)
    # 剥完变空或没有变短 → 差异不在边界标点，不再放宽
    if not inner or inner == canon_seg:
        return False
    return inner in canon_material


def segments(text: str) -> list[str]:
    """把一条摘录按省略号切成待比对分段（丢弃空段与过短段）。"""
    out: list[str] = []
    for part in _ELLIPSIS_RE.split(str(text or "")):
        canon = _canon(part)
        if len(canon) >= _MIN_SEGMENT_CHARS:
            out.append(part.strip())
    return out


def _join_material(material_text: Any) -> str:
    """材料正文可以是单个字符串，也可以是按章切片后的列表（``materials.slice_chapter``）。"""
    if material_text is None:
        return ""
    if isinstance(material_text, str):
        return material_text
    if isinstance(material_text, (bytes, bytearray)):
        return material_text.decode("utf-8", "ignore")
    if isinstance(material_text, Iterable):
        return "\n".join(str(x) for x in material_text if x)
    return str(material_text)


def _short(text: str, limit: int = 42) -> str:
    """截断成可读片段，用于 detail 展示。"""
    t = str(text or "")
    return t if len(t) <= limit else t[:limit] + "…"


# ------------------------------------------------------------------ 结构解析

_FENCE_MARKS = ("```", "~~~")
_HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$")
_QUOTE_LINE_RE = re.compile(r"^>\s?(.*)$")

# 「摘录作用域」小节名：只有这些小节里的 ``>`` 块才是**原文摘录**。
# 规范 content_structure 的章节层模板给的就是「#### 关键句段解读」，实测逐字沿用。
# 其它小节（本章概要 / 论证结构分析…）里的 ``>`` 是模板引导句或作者自己的话。
EXCERPT_SECTIONS = ("关键句段解读", "关键句段", "原文摘录", "句段解读", "关键句段分析")

# 模板引导句：规范 content_structure 自带、必然不在材料里的引用块。
# 即使调用方开了 all_quotes 也要排除，否则每份导读都报 blocking 假阳性。
_TEMPLATE_LEAD_RE = re.compile(
    r"^(本章在全书中的位置|本节在全书中的位置|本篇在全书中的位置|全节定位|"
    r"\u26a0|\u26a0\ufe0f|风险[:：]|注意[:：]|提示[:：])"
)

# 句段定位标题：「句段N（第X章第Y节）」。N/X/Y 允许阿拉伯或中文数字。
_SEGMENT_HEADING_RE = re.compile(
    r"^句段\s*([0-9一二三四五六七八九十百零两]+)\s*[（(](.*?)[)）]\s*$"
)
# 括号内是否给了**可回查的定位**。
#
# 这里必须取宽一档，是实测逼出来的：规范写的是「句段N（第X章第Y节）」，但真实材料
# 大量按「篇 / 讲 / 自然段 / 甲乙丙 / （一）」组织（《毛选》第二卷就是
# 「# 第二卷 → ## 时期 → ### 篇」，整卷没有章号）。实测 42 节、156 个摘录块的定位
# 写法有「第一篇 · 开篇总纲」「《中国工人》发刊词第1自然段」「本篇「干部政策」节」
# 「本篇谈话部分」「第二小节」「第（一）节」「（甲）」「相持阶段问题段」——它们
# 都能让读者回查原文。卡死「第X章第Y节」会报出 59 条 advisory 噪音，把真正致命的
# Q001 淹没。Q002 要抓的是「完全没有回查线索」（如「句段一（重要）」「句段一（精彩）」）。
_LOCATOR_RE = re.compile(
    # 第 N + 结构单位（含「第二小节」「第三自然段」这类带前缀的单位）
    r"第\s*[0-9一二三四五六七八九十百零两]+\s*(?:小|大|本)?\s*(?:章|篇|节|讲|回|卷|课|段|条|目|部分)"
    # 括号编号：（一）（甲）(3)。注意 _SEGMENT_HEADING_RE 已经把外层括号吃掉，
    # 所以括号内是**裸字**（「句段一（甲）」→ group(2)=="甲"），两种形态都要认。
    r"|[（(]?\s*(?:[0-9]{1,3}|[一二三四五六七八九十百零两]|[甲乙丙丁戊己庚辛])\s*[)）]?"
    # 篇名 / 书名（材料里的真实标题本身就是定位）
    r"|《[^》]{1,40}》"
    # 相对定位：本篇 / 本节 / 本卷（「本篇「干部政策」节」「本篇谈话部分」）
    r"|本篇|本节|本卷|本书|本条|上段|下段|前段|后段"
    # 位置词：开篇 / 首段 / 末段 / 篇末 / 结尾 / 一段
    r"|开篇|首段|末段|篇末|结尾|段末|段首|开头|收束|结语|结论部分|段$"
    # 页码类
    r"|[Pp]\.?\s*\d+|第\s*\d+\s*页"
)


def _norm_head(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "").strip())


@dataclass
class QuoteBlock:
    """一个 ``>`` 引用块及其上下文（标题、所属小节），Q001/Q002 的判定单位。"""

    text: str                 # 去掉 ``>`` 前缀后的摘录正文
    lineno: int               # 首行行号
    heading: str = ""         # 上方最近的 ##### 标题文本（已归一）
    heading_level: int = 0
    heading_lineno: int = 0
    section: str = ""         # 上方最近的 #### 小节名（如「关键句段解读」）
    section_lineno: int = 0

    @property
    def where(self) -> str:
        head = self.heading or "（无标题）"
        return f"第 {self.lineno} 行「{_short(head, 24)}」"

    @property
    def is_template_lead(self) -> bool:
        return bool(_TEMPLATE_LEAD_RE.match(self.text.strip()))


def _iter_lines(markdown: str):
    """逐行产出 (行号, 原行, 是否在代码围栏内)；围栏行本身也标记为围栏。"""
    fence: str | None = None
    for idx, raw in enumerate(str(markdown or "").split("\n"), 1):
        stripped = raw.lstrip()
        marker = next((m for m in _FENCE_MARKS if stripped.startswith(m)), None)
        if marker:
            if fence is None:
                fence = marker
                yield idx, raw, True
                continue
            if stripped.startswith(fence):
                fence = None
                yield idx, raw, True
                continue
        yield idx, raw, fence is not None


def parse_quote_blocks(markdown: str) -> list[QuoteBlock]:
    """解析出全部引用块，并记录它所属的 ``####`` 小节与上方最近的 ``#####`` 标题。

    代码围栏里的 ``>`` 不是引用块（那是代码），必须跳过——否则示例代码里的重定向
    ``ls > out.txt`` 会被当成摘录送去比对，报出虚构引文的假阳性。
    """
    blocks: list[QuoteBlock] = []
    section = ""
    section_lineno = 0
    heading = ""
    heading_level = 0
    heading_lineno = 0
    buf: list[str] = []
    start = 0

    def flush() -> None:
        nonlocal buf, start
        if buf:
            text = "\n".join(buf).strip()
            if text:
                blocks.append(QuoteBlock(
                    text=text, lineno=start, heading=heading, heading_level=heading_level,
                    heading_lineno=heading_lineno, section=section, section_lineno=section_lineno,
                ))
        buf = []
        start = 0

    for lineno, raw, fenced in _iter_lines(markdown):
        if fenced:
            flush()
            continue
        m = _QUOTE_LINE_RE.match(raw.lstrip())
        if m:
            if not buf:
                start = lineno
            buf.append(m.group(1))
            continue
        flush()
        stripped = raw.strip()
        if not stripped:
            continue
        hm = _HEADING_RE.match(stripped)
        if hm:
            level, name = len(hm.group(1)), _norm_head(hm.group(2))
            if level <= 4:
                section = name
                section_lineno = lineno
            if level == 5:
                heading, heading_level, heading_lineno = name, level, lineno
            else:
                # 其它级别标题会打断「句段标题 → 摘录」的紧邻关系
                heading, heading_level, heading_lineno = "", level, lineno
    flush()
    return blocks


def excerpt_blocks(markdown: str, *, all_quotes: bool = False) -> list[QuoteBlock]:
    """挑出需要与材料逐字比对的引用块。

    默认只取「关键句段解读」作用域内的块（见模块 docstring 的误判防护）。
    模板引导句无论何种模式都排除。
    """
    out: list[QuoteBlock] = []
    for b in parse_quote_blocks(markdown):
        if b.is_template_lead:
            continue
        if all_quotes or _norm_head(b.section) in EXCERPT_SECTIONS:
            out.append(b)
    return out


# ------------------------------------------------------------------ Q001 逐字比对

def check_verbatim(markdown: str, material_text: Any, *, all_quotes: bool = False) -> list[Violation]:
    """Q001：每条原文摘录的每一段都必须逐字命中材料。

    省略号切段后**每段都要命中**：拼接式伪造（前半真、后半编）会在这里露出来。
    """
    blocks = excerpt_blocks(markdown, all_quotes=all_quotes)
    if not blocks:
        return []
    canon_material = _canon(_join_material(material_text))
    if not canon_material:
        # 没有比对基准就报 blocking，等于凭空指控模型编造——绝对不行。
        return []

    v: list[Violation] = []
    for b in blocks:
        segs = segments(b.text)
        if not segs:
            continue
        missing = [s for s in segs if not _segment_hit(_canon(s), canon_material)]
        if not missing:
            continue
        if len(missing) == len(segs):
            detail = (
                f"{b.where}的摘录未在材料中出现（疑似编造或改写）："
                f"「{_short(missing[0])}」"
            )
        else:
            detail = (
                f"{b.where}的摘录按省略号分成 {len(segs)} 段，其中 {len(missing)} 段未在材料中出现："
                f"「{_short(missing[0])}」（拼接式引用：部分真、部分无据）"
            )
        v.append(Violation("Q001", *CODES["Q001"], detail))
    return v


# ------------------------------------------------------------------ Q002 定位标题

# 括号内定位的分隔符：「论政策·关于政权组织」「第一篇 · 开篇总纲」都要拆开逐段验
_LOCATOR_SPLIT_RE = re.compile(r"[·\u00b7、，,；;/｜|]+")
# 材料标题行（与 ``materials.heading_lines`` 同语义：跳过代码围栏内的 # 行）。
# 本地实现而不是 import materials：本模块是纯校验器（与 exam_check 一样零 app 依赖），
# 引 materials 会把 SQLAlchemy / models 一起拖进来，还会形成 services 内部的耦合。
_MATERIAL_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# 定位片段的两个长度门槛（实测校准，见 _locator_matches_material）
_MIN_HEADING_SEG = 3      # 命中标题：标题是稀有词，3 字即可
_MIN_LONG_SEG = 6         # 命中正文长片段：正文命中概率高，门槛必须抬高


def material_headings(material_text: Any) -> set[str]:
    """材料里的标题集合（归一化后），用于验证摘录定位是否指向材料真实标题。"""
    text = _join_material(material_text)
    if not text.strip():
        return set()
    heads: set[str] = set()
    fence: str | None = None
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif stripped.startswith(fence):
                fence = None
            continue
        if fence is not None:
            continue
        m = _MATERIAL_HEAD_RE.match(stripped)
        if m:
            name = _canon(m.group(2).strip().rstrip("*"))
            if len(name) >= _MIN_HEADING_SEG:
                heads.add(name)
    return heads


def _locator_parts(inner: str):
    """把括号内的定位拆成候选片段（按 · / 、 / 空格等分隔）。"""
    for part in _LOCATOR_SPLIT_RE.split(str(inner or "")):
        seg = part.strip().strip("「」『』\u201c\u201d《》()（） 　")
        if seg:
            yield seg


def _locator_matches_material(inner: str, canon_material: str, heads: set[str]) -> bool:
    """括号里的定位是否指向材料中真实存在的位置。

    这是 Q002 最重要的一道防误报闸门，**实测**逼出来的：
    「句段一（抗日战争的情况和教训）」在正则看来「没有章号 → 违规」，但材料里
    ``#### 抗日战争的情况和教训`` 是真实小节标题——它恰恰是**最好的**定位。
    正则永远穷举不完材料的组织方式（篇 / 讲 / 自然段 / 甲乙 / 小节标题…），
    但「能不能在材料里找到这个位置」是可判定的事实。

    两条通道，门槛不同（实测校准：只用正文匹配会让「有意思」「值得注意」这类泛词
    在 30 万字材料里偶然命中而漏判）：
    1. 片段是**材料标题**（≥3 字）→ 有效。标题是稀有词，偶然命中率低。
    2. 片段是**材料正文里的长片段**（归一化后 ≥6 字）→ 有效。门槛必须抬高，
       否则短泛词会在长材料里到处命中，等于把这道闸门废掉。
    """
    if not canon_material:
        return False
    for seg in _locator_parts(inner):
        canon = _canon(seg)
        if not canon:
            continue
        if len(canon) >= _MIN_HEADING_SEG and canon in heads:
            return True
        if len(canon) >= _MIN_LONG_SEG and canon in canon_material:
            return True
    return False


def check_locators(markdown: str, material_text: Any = None) -> list[Violation]:
    """Q002：摘录块前的 ``#####`` 标题是否给出可回查的章节定位。

    判三种确定情形，其余一律不报：
    1. 摘录块上方没有 ``#####`` 标题；
    2. 有标题但不是「句段N（…）」形态；
    3. 是「句段N（…）」，括号里既没有定位线索（``_LOCATOR_RE``），
       也**不是材料里真实存在的标题**（``_locator_matches_material``）。

    ``material_text`` 传了才启用第 3 条的材料验证；没传时退回纯正则判断。
    """
    v: list[Violation] = []
    canon_material = _canon(_join_material(material_text))
    heads = material_headings(material_text) if canon_material else set()
    for b in excerpt_blocks(markdown):
        if not b.heading:
            v.append(Violation(
                "Q002", *CODES["Q002"],
                f"{b.where}：摘录块前缺少 ##### 句段定位标题（应写「句段N（第X章第Y节）」）",
            ))
            continue
        m = _SEGMENT_HEADING_RE.match(b.heading)
        if not m:
            v.append(Violation(
                "Q002", *CODES["Q002"],
                f"第 {b.heading_lineno} 行标题「{_short(b.heading, 30)}」不是「句段N（第X章第Y节）」格式",
            ))
            continue
        if _LOCATOR_RE.search(m.group(2)):
            continue
        if _locator_matches_material(m.group(2), canon_material, heads):
            continue
        v.append(Violation(
            "Q002", *CODES["Q002"],
            f"第 {b.heading_lineno} 行「{_short(b.heading, 30)}」括号内未给章节定位"
            f"（应含「第X章第Y节」一类可回查定位；不确定页码时更要用章节定位）",
        ))
    return v


# ------------------------------------------------------------------ Q003 页码

_PAGE_REF_RE = re.compile(
    r"第\s*(\d{1,4})\s*[页頁]"
    r"|[（(]\s*[Pp]\.?\s*(\d{1,4})\s*[)）]"
    r"|(?<![A-Za-z0-9])[Pp]\.\s*(\d{1,4})(?![0-9])"
)
# 材料里的页码痕迹：「第 N 页」「P. N」，或 PDF 抽取常见的**整行只有页码**。
# 必须带 re.M：``^…$`` 要按行匹配，否则整份材料只有开头能命中独立页码行，
# 结果 material_page_numbers 返回空集 → check_page_refs 误判「材料不带页码」。
# 注意这会把材料里的其它独立数字行也算作页码，方向是**放宽**（少报 Q003），
# 对一个 advisory 检查来说是可接受的取舍：宁可漏报，不可凭空指控。
_MATERIAL_PAGE_RE = re.compile(
    r"第\s*(\d{1,4})\s*[页頁]|[Pp]\.?\s*(\d{1,4})(?![0-9])|^\s*(\d{1,4})\s*$",
    re.M,
)


def material_page_numbers(material_text: Any) -> set[int]:
    """材料里能确认存在的页码集合；空集合表示材料不带页码痕迹。"""
    text = _join_material(material_text)
    if not text.strip():
        return set()
    nums: set[int] = set()
    for m in _MATERIAL_PAGE_RE.finditer(text):
        raw = next((g for g in m.groups() if g), None)
        if raw:
            nums.add(int(raw))
    return nums


def check_page_refs(markdown: str, material_text: Any) -> list[Violation]:
    """Q003：正文里的页码引用必须能在材料中找到依据。

    材料完全没有页码痕迹时，任何页码引用都属「无法确定对应关系」——规范此时要求
    一律改用章节定位。这条只报 advisory：页码错不会让读者读错内容，但会让人回查失败。
    """
    refs: list[tuple[int, int]] = []
    for lineno, raw, fenced in _iter_lines(markdown):
        if fenced:
            continue
        for m in _PAGE_REF_RE.finditer(raw):
            num = next((int(g) for g in m.groups() if g), None)
            if num:
                refs.append((lineno, num))
    if not refs:
        return []

    known = material_page_numbers(material_text)
    if not known:
        shown = "、".join(f"第 {n} 页" for _, n in refs[:6])
        return [Violation(
            "Q003", *CODES["Q003"],
            f"材料本身未带页码，正文却引用了 {len(refs)} 处页码（{shown}"
            f"{' 等' if len(refs) > 6 else ''}）；应改用「第X章第Y节」章节定位",
        )]

    unknown = sorted({n for _, n in refs if n not in known})
    if not unknown:
        return []
    first_line = next(ln for ln, n in refs if n == unknown[0])
    return [Violation(
        "Q003", *CODES["Q003"],
        f"页码 {('、'.join(str(n) for n in unknown[:6]))} 未出现在材料中"
        f"（首见于第 {first_line} 行）；材料可确认的页码只有 {len(known)} 个",
    )]


# ------------------------------------------------------------------ Q004 材料未涉及标注

# 「材料未涉及」这类**独立标注行**的起首形态
_UNKNOWN_LEAD_RE = re.compile(r"^(材料未涉及|材料中未涉及|材料未提及|材料未说明|材料未提供)")
# 规范要求的完整形态：「材料未涉及，待核实：（说明缺什么）」
_UNKNOWN_FULL_RE = re.compile(r"^材料未涉及\s*[，,]\s*待核实\s*[:：]\s*(\S.*)$")
# 行首的列表 / 引用 / 标题符号，以及模板里的加粗字段引导词（「**严谨定义**：」）
_LIST_PREFIX_RE = re.compile(r"^(?:[-*>+]\s*|\d+[\.、)]\s*)+")
_FIELD_LABEL_RE = re.compile(r"^\**[^*：:]{1,24}\**\s*[：:]\s*")


def _strip_lead(line: str) -> str:
    """剥掉列表符号与加粗字段引导词，取出真正要判定的标注文本。

    必须剥字段引导词：模板是「- 严谨定义：材料未涉及，待核实：…」，不剥的话
    整行永远不匹配「^材料未涉及」，这条检查等于没生效。
    """
    text = str(line or "").strip()
    for _ in range(3):
        new = _LIST_PREFIX_RE.sub("", text)
        new = _FIELD_LABEL_RE.sub("", new, count=1)
        if new == text:
            break
        text = new.strip()
    return text


def check_unknown_marks(markdown: str) -> list[Violation]:
    """Q004：「材料未涉及，待核实：（说明缺什么）」标注的格式。

    规范要求材料不足时**这样标**，而不是编造填充。标注写得不完整（只写「材料未涉及」
    却不写待核实、或冒号后没有说明缺什么），读者就分不清「这是材料确实没有」还是
    「AI 漏写了」。

    **只判独立标注行**——即剥掉列表符号与字段引导词后，整行以「材料未涉及」起首，
    且行内没有「待核实」+ 说明。这是实测逼出来的收窄：真实教程（42 节）里有 178 处
    含「待核实 / 需核验」，绝大多数出现在正常论述句中（「材料未直接涉及与其他理论家的
    关系，待核实；从论证方式看…」），把它们一起判违规会报出上百条噪音，直接淹没 Q001。
    另外**带字段标签的行**（「- 与其他重要理论或思想的联系：材料未涉及，待核实。」）
    一律不报：模板字段名本身已经充当了「说明缺什么」，这是合规写法（实测 20 处全是这种）。
    """
    v: list[Violation] = []
    for lineno, raw, fenced in _iter_lines(markdown):
        if fenced:
            continue
        stripped = raw.strip()
        text = _strip_lead(stripped)
        if not text or not _UNKNOWN_LEAD_RE.match(text):
            continue
        if _UNKNOWN_FULL_RE.match(text):
            continue
        # 带字段引导词：字段名已经是「缺什么」的说明，不再要求冒号格式
        labeled = _FIELD_LABEL_RE.sub("", _LIST_PREFIX_RE.sub("", stripped), count=1).strip() != \
            _LIST_PREFIX_RE.sub("", stripped).strip()
        if labeled:
            continue
        v.append(Violation(
            "Q004", *CODES["Q004"],
            f"第 {lineno} 行「{_short(text, 36)}」不是规范格式；"
            f"应写「材料未涉及，待核实：（说明缺什么）」",
        ))
    return v


# ------------------------------------------------------------------ Q005 三方观点

_SCHOLAR_HEAD = "学界视角"
_AI_HEAD = "AI辅助分析"
# AI 分析的口吻标记（规范原文举例：「从论证看」「可以追问」）
_AI_TONE_RE = re.compile(
    r"从论证看|可以追问|我们不妨|笔者认为|从教学角度|作为\s*AI|由\s*AI\s*(分析|补充|给出)|"
    r"这里的解释是|以下是\s*AI|AI\s*(?:的)?(?:分析|解释|补充|理解)"
)
# 把 AI 解释包装成学界共识（forbidden_rules 明令禁止）
_SCHOLAR_CLAIM_RE = re.compile(
    r"学界认为|学界共识|学界公认|学界普遍|学术界一致|学术界公认|研究者普遍认为|研究者一致|公认的观点"
)
# 作者本人的观点（应写在概要 / 深度导读，不该混进「学界视角」）
_AUTHOR_CLAIM_RE = re.compile(r"作者认为|作者主张|作者指出|作者强调|作者明确表示|本书作者")
# 「写明是哪一派 / 哪类立场」的最低要求
_SCHOOL_MARKER_RE = re.compile(
    r"一派|某派|学派|派别|立场|学者|学界|研究者|批评者|支持者|反对者|质疑|反驳|争议|认为|主张|指出|评价"
)
# 规范认可的「无实质争议」写法：写了这句就整块跳过
_NO_DISPUTE_RE = re.compile(r"材料未显示存在实质争议|材料未涉及.*争议|无实质争议")


def _heading_positions(markdown: str) -> list[tuple[int, int, str]]:
    """全部标题的 (行号, 级别, 归一名)，跳过代码围栏内的 # 行。"""
    out: list[tuple[int, int, str]] = []
    for lineno, raw, fenced in _iter_lines(markdown):
        if fenced:
            continue
        hm = _HEADING_RE.match(raw.strip())
        if hm:
            out.append((lineno, len(hm.group(1)), _norm_head(hm.group(2))))
    return out


def _section_spans(markdown: str, names: tuple[str, ...]) -> dict[str, list[int]]:
    """返回 {归一小节名: [起行, …]}；小节止于下一个同级或更高级标题。"""
    heads = _heading_positions(markdown)
    last_line = len(str(markdown or "").split("\n")) + 1
    spans: dict[str, list[int]] = {n: [] for n in names}
    for pos, (lineno, level, name) in enumerate(heads):
        if name not in names:
            continue
        end = last_line
        for nxt_line, nxt_level, _nxt_name in heads[pos + 1:]:
            if nxt_level <= level:
                end = nxt_line
                break
        spans[name].append((lineno, end))
    return spans


def _lines_in(markdown: str, start: int, end: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, raw, fenced in _iter_lines(markdown):
        if lineno <= start or lineno >= end or fenced:
            continue
        if raw.strip():
            out.append((lineno, raw.strip()))
    return out


def check_viewpoint_separation(markdown: str) -> list[Violation]:
    """Q005：「#### 学界视角」与「#### AI 辅助分析」是否混写。

    **保守启发式**：只报三类确定信号，拿不准就不报（这条最容易被合理写法误伤）。
    1. 「学界视角」块里出现 AI 分析口吻（从论证看 / 可以追问 / 作为 AI …）；
    2. 「学界视角」块里直接陈述作者观点（作者认为…）；
    3. 「AI 辅助分析」块里出现「学界认为 / 学界共识 / 研究者普遍」——forbidden_rules
       明令「禁止把 AI 自己的解释写成学界共识」。

    「学界视角」写了「材料未显示存在实质争议」时整块跳过：那是规范明确认可的写法。
    """
    v: list[Violation] = []
    spans = _section_spans(markdown, (_SCHOLAR_HEAD, _AI_HEAD))

    for start, end in spans.get(_SCHOLAR_HEAD, []):
        body = _lines_in(markdown, start, end)
        text = "\n".join(t for _, t in body)
        if not text.strip() or _NO_DISPUTE_RE.search(text):
            continue
        hit = _AI_TONE_RE.search(text)
        if hit:
            lineno = next((ln for ln, t in body if _AI_TONE_RE.search(t)), start + 1)
            v.append(Violation(
                "Q005", *CODES["Q005"],
                f"第 {lineno} 行「#### 学界视角」里出现 AI 分析口吻「{hit.group(0)}」；"
                f"AI 的分析与解释应写在「#### AI 辅助分析」",
            ))
        hit = _AUTHOR_CLAIM_RE.search(text)
        if hit:
            lineno = next((ln for ln, t in body if _AUTHOR_CLAIM_RE.search(t)), start + 1)
            v.append(Violation(
                "Q005", *CODES["Q005"],
                f"第 {lineno} 行「#### 学界视角」里直接陈述作者观点「{hit.group(0)}…」；"
                f"作者本人的观点应写在章节概要 / 深度导读并指向原文出处",
            ))
        if not _SCHOOL_MARKER_RE.search(text):
            v.append(Violation(
                "Q005", *CODES["Q005"],
                f"第 {start} 行「#### 学界视角」未写明是哪一派 / 哪类立场"
                f"（规范要求「写明是哪一派/哪类立场，须有可靠依据」）",
            ))

    for start, end in spans.get(_AI_HEAD, []):
        for lineno, text in _lines_in(markdown, start, end):
            hit = _SCHOLAR_CLAIM_RE.search(text)
            if hit:
                v.append(Violation(
                    "Q005", *CODES["Q005"],
                    f"第 {lineno} 行「#### AI 辅助分析」把 AI 解释写成「{hit.group(0)}」；"
                    f"forbidden_rules 明令禁止把 AI 自己的解释写成学界共识",
                ))
                break
    return v


# ------------------------------------------------------------------ 对外入口

def check_quotes(
    markdown: str,
    material_text: Any,
    *,
    all_quotes: bool = False,
) -> list[Violation]:
    """阅读教程规范 Tier-0 校验入口：返回全部违规（**只判定，不改写**）。

    参数：
    - ``markdown``：一节（或整份）教程正文。
    - ``material_text``：该节注入的材料原文，字符串或按章切片后的字符串列表
      （``materials.slice_chapter`` / ``materials._material_body`` 的产物）。
      为空时 Q001/Q003 不做判定——没有基准就不指控。
    - ``all_quotes``：True 时把全部引用块都当作摘录比对（调试用；默认只比对
      「关键句段解读」作用域，避免把模板引导句判成虚构引文）。
    """
    v: list[Violation] = []
    v += check_verbatim(markdown, material_text, all_quotes=all_quotes)
    v += check_locators(markdown, material_text)
    v += check_page_refs(markdown, material_text)
    v += check_unknown_marks(markdown)
    v += check_viewpoint_separation(markdown)
    return v


def summarize(violations: list[Violation]) -> dict[str, Any]:
    """汇总成可写进 quality_report 的结构（与 exam_check.quality_checks 同构）。

    ``passed`` 只看 blocking：Q002~Q005 是排版与标注层面的提示，不该把整份导读
    标成「待改进」，否则 Q001 这个真正致命的信号会被噪音淹没。
    """
    codes = Counter(v.code for v in violations)
    blocking = [v for v in violations if v.blocking]
    return {
        "passed": not blocking,
        "codes": dict(codes),
        "blocking": len(blocking),
        "advisory": len(violations) - len(blocking),
        "violations": [v.to_dict() for v in violations],
    }
