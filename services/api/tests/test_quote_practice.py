# -*- coding: utf-8 -*-
"""quote_check / practice_check（阅读 + 实践教程规范 Tier-0 校验）单元测试。

覆盖两类东西：

1. **正向检出**：规范要求的事实（摘录逐字、代码可运行、步骤含预期与验证）不满足时必须报出来。
2. **防误报闸门**：这些闸门全部是用**真实产物**校准出来的，不是假想的边界情况。
   实测语料：库内 99 个 tutorial_versions / 328 个章节，以及 42 节、156 个摘录块的
   「毛选第二卷导读 · 阅读教程规范」。宽松规则下的误报率：
     - Q001 不加作用域与归一化防护 → 把模板引导句、编者注编号、句读差异判成「虚构引文」（blocking！）
     - Q002 卡死「第X章第Y节」→ 59 条 advisory，全是「第一篇 · 开篇总纲」这类可回查定位
     - Q004 判所有含「待核实」的行 → 178 处命中，绝大多数是正常论述句
     - P001 逐行判三要素 → 785 个步骤行里 243 行「缺项」，实为子项与合并写法
     - P002 朴素围栏正则 → 4 反引号嵌套示例吞掉后文散文，报「invalid character '。'」
     - P003 对 powershell 做 which → 86 个围栏首词全是 Cmdlet，which 100% 为 None
     - P004 把 / → > 当菜单分隔符 → 137/318 = 42% 误报
   每条闸门都有对应测试，改代码前先看测试名。
"""
from __future__ import annotations

import shutil
import sys

import pytest

from app.services import practice_check as pc
from app.services import quote_check as q

# 全角字符集中定义，避免各测试里散落易被输入法弄混的形近字符
_FULL_PLUS = "\uff0b"     # 全角 ＋
_ARROW = "\u2192"         # →


def _sec(blocks, title="第一章 基础操作"):
    """构造一个 v2 结构的 section dict。"""
    return {"title": title, "content": blocks}


def _codes(violations):
    return [v.code for v in violations]


# ------------------------------------------------------------------ 共用材料
#
# 材料文本取自《毛选》第一卷开篇（真实材料形态：含编者注编号、含句读）。
MATERIAL = (
    "谁是我们的敌人？谁是我们的朋友？这个问题是革命的首要问题〔1〕。"
    "中国过去一切革命斗争成效甚少，其基本原因就是因为不能团结真正的朋友，以攻击真正的敌人。"
    "我们要分辨真正的敌友，不可不将中国社会各阶级的经济地位及其对于革命的态度，"
    "作一个大概的分析。\n\n以斗争求团结则团结存，以退让求团结则团结亡，这一真理，"
    "已经逐渐为党内同志们所了解。\n"
)
# 「关键句段解读」小节标题：Q001 只在这个作用域内比对（见 test_q001_template_lead_quote_is_not_flagged）
_HEAD = "#### 关键句段解读\n\n"


# ==========================================================================
# quote_check · Q001 逐字比对
# ==========================================================================

def test_q001_confirmed_verbatim_quote_is_clean():
    """摘录逐字来自材料 → 无违规。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 谁是我们的敌人？谁是我们的朋友？这个问题是革命的首要问题。\n"
    assert q.check_quotes(md, MATERIAL) == []


def test_q001_refuted_fabricated_quote_is_blocking():
    """摘录是编造的（材料里没有）→ 报 Q001 且 severity=blocking。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 革命的根本问题是政权问题，必须依靠群众。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert _codes(vs) == ["Q001"]
    assert vs[0].severity == "blocking"
    assert vs[0].blocking is True
    assert vs[0].auto_fixable is False    # 引文错误没有唯一正确的修法，不自动改


def test_q001_rewritten_quote_is_detected():
    """「润色」过的引文（只改一个词）也必须抓出来——这正是规范禁止的改写。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的核心问题。\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == ["Q001"]


def test_q001_ellipsis_segments_all_present_passes():
    """省略号分段：每段都在材料里 → 通过。"""
    md = _HEAD + "##### 句段二（第1章第1节）\n\n> 谁是我们的敌人？谁是我们的朋友？……作一个大概的分析。\n"
    assert q.check_quotes(md, MATERIAL) == []


def test_q001_ellipsis_with_fabricated_segment_is_reported():
    """省略号分段：有一段不在材料里 → 报 Q001（拼接式伪造）。"""
    md = _HEAD + "##### 句段三（第1章第1节）\n\n> 谁是我们的敌人？谁是我们的朋友？……这句话材料里根本没有出现过。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert _codes(vs) == ["Q001"]
    assert vs[0].severity == "blocking"
    assert "拼接式引用" in vs[0].detail
    assert "分成 2 段" in vs[0].detail


def test_q001_fabricated_middle_segment_is_reported():
    """三段拼接、只有中间一段是编造的 → 也要抓出来。"""
    md = (_HEAD + "##### 句段四（第1章第1节）\n\n"
          "> 这个问题是革命的首要问题。……编造的中间句在这里。……作一个大概的分析。\n")
    vs = q.check_quotes(md, MATERIAL)
    assert _codes(vs) == ["Q001"]
    assert "分成 3 段" in vs[0].detail and "1 段未在材料中出现" in vs[0].detail


def test_q001_ascii_ellipsis_also_splits():
    """规范要求 ``……``，但实测也出现 ASCII ``...``，同样必须分段比对。"""
    md = _HEAD + "##### 句段五（第1章第1节）\n\n> 谁是我们的敌人？...这句话材料里根本没有出现过。\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == ["Q001"]


def test_q001_multi_line_quote_block_is_joined():
    """材料按行抽取，摘录连成一行；引用块跨多行时也要能比对上。"""
    md = _HEAD + "##### 句段六（第1章第1节）\n\n> 谁是我们的敌人？谁是我们的朋友？\n> 这个问题是革命的首要问题。\n"
    assert q.check_quotes(md, MATERIAL) == []


def test_q001_accepts_material_given_as_slice_list():
    """材料可以是 ``materials.slice_chapter`` 产出的**列表**（按章切片）。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n"
    assert q.check_quotes(md, [MATERIAL[:60], MATERIAL[60:]]) == []


def test_q001_empty_material_is_not_judged():
    """**防误报闸门**：材料为空 → 不判 Q001。没有比对基准就报 blocking 等于凭空指控。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 革命的根本问题是政权问题。\n"
    assert q.check_quotes(md, "") == []
    assert q.check_quotes(md, None) == []


def test_q001_editor_annotation_is_stripped():
    """**防误报闸门（实测）**：材料带编者注编号「〔1〕」，摘录自然省略 → 不得判成编造。

    实测原文「为了声讨卖国贼汪精卫〔1〕，又是为了…」，宽松前 Q001 报 blocking 假阳性。
    """
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 谁是我们的敌人？谁是我们的朋友？这个问题是革命的首要问题。\n"
    assert q.check_quotes(md, MATERIAL) == []          # MATERIAL 含〔1〕
    assert q.check_quotes(md, MATERIAL.replace("〔1〕", "[1]")) == []
    assert q.check_quotes(md, MATERIAL.replace("〔1〕", "\u2460")) == []


def test_q001_content_level_parenthesis_is_not_stripped():
    """「（一）」是**内容级**枚举，不是注释编号，剥掉它会掩盖真实差异。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题（一）。\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == ["Q001"]


def test_q001_edge_punctuation_difference_is_tolerated():
    """**防误报闸门（实测）**：截断关键句时补句号属正常排版，不得判成编造。

    实测材料「…以退让求团结则团结亡，这一真理…」，摘录截成「…团结亡。」，
    宽松前 Q001 报 blocking 假阳性。规范第 2 条本就允许「只截承担论证功能的关键句」。
    """
    md = _HEAD + "##### 句段二（第1章第2节）\n\n> 以斗争求团结则团结存，以退让求团结则团结亡。\n"
    assert q.check_quotes(md, MATERIAL) == []


def test_q001_inner_word_difference_is_still_caught():
    """边界标点容忍**不得**放宽到段内：改一个实词照样报。"""
    md = _HEAD + "##### 句段二（第1章第2节）\n\n> 以斗争求团结则团结存，以妥协求团结则团结亡。\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == ["Q001"]


def test_q001_too_short_segment_is_not_judged():
    """过短分段（<4 字符）不判：太短的子串在长材料里偶然命中概率高，不能当结论。"""
    md = _HEAD + "##### 句段五（第1章第1节）\n\n> 谁是我们的敌人？……的。\n"
    assert q.check_quotes(md, MATERIAL) == []


def test_q001_template_lead_quote_is_not_flagged():
    """**防误报闸门（实测）**：「本章概要」里的 ``> 本章在全书中的位置：…`` 是规范模板
    引导句，本来就不在材料里；不加作用域限制会把每份导读都判成虚构引文。
    """
    md = "### 本章概要\n\n> 本章在全书中的位置：一句话说明它承接什么、要解决什么。\n"
    assert q.check_quotes(md, MATERIAL) == []
    assert len(q.parse_quote_blocks(md)) == 1          # 解析得到，但不参与比对
    assert q.excerpt_blocks(md) == []


def test_q001_all_quotes_mode_includes_every_block():
    """``all_quotes=True`` 放开到全部引用块（调试用），模板引导句仍排除。"""
    md = ("### 本章概要\n\n> 编造的概要引文。\n\n" + _HEAD
          + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n")
    assert q.check_quotes(md, MATERIAL) == []                        # 默认只看摘录作用域
    assert _codes(q.check_quotes(md, MATERIAL, all_quotes=True)) == ["Q001"]


def test_q001_code_fence_redirect_is_not_a_quote():
    """**防误报闸门**：代码块里的 ``>`` 是重定向，不是引用块。"""
    md = _HEAD + "##### 句段七（第1章第1节）\n\n```bash\nls > out.txt\n```\n"
    assert q.parse_quote_blocks(md) == []
    assert q.check_quotes(md, MATERIAL) == []



# ==========================================================================
# quote_check · Q002 定位标题
# ==========================================================================

def test_q002_correct_locator_is_clean():
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == []


def test_q002_wrong_heading_shape_is_reported():
    md = _HEAD + "##### 精彩段落一\n\n> 这个问题是革命的首要问题。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert "Q002" in _codes(vs)
    v = next(x for x in vs if x.code == "Q002")
    assert v.severity == "advisory" and v.blocking is False
    assert "不是「句段N（第X章第Y节）」格式" in v.detail


def test_q002_missing_heading_is_reported():
    md = _HEAD + "> 这个问题是革命的首要问题。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert "Q002" in _codes(vs)
    assert "缺少 ##### 句段定位标题" in next(x for x in vs if x.code == "Q002").detail


def test_q002_heading_without_any_locator_is_reported():
    md = _HEAD + "##### 句段一（重要）\n\n> 这个问题是革命的首要问题。\n"
    assert "Q002" in _codes(q.check_quotes(md, MATERIAL))


def test_q002_real_world_locator_variants_are_accepted():
    """**防误报闸门（实测）**：材料按篇 / 讲 / 自然段 / 甲乙组织时，「第X章第Y节」并不存在。

    实测 156 个摘录块的定位写法包含以下全部形态；卡死规范字面会报 59 条 advisory 噪音。
    """
    variants = [
        "句段一（第一篇 · 开篇总纲）",
        "句段二（第二章第四节）",
        "句段三（第4章「军事问题」节）",
        "句段四（《中国工人》发刊词第1自然段）",
        "句段五（本篇「干部政策」节）",
        "句段一（甲）",
        "句段二（第（一）节）",
        "句段三（第二小节）",
        "句段四（相持阶段问题段）",
        "句段五（本篇谈话部分）",
        "句段一（P. 45）",
    ]
    for head in variants:
        md = _HEAD + "##### " + head + "\n\n> 这个问题是革命的首要问题。\n"
        got = [v for v in q.check_quotes(md, MATERIAL) if v.code == "Q002"]
        assert not got, "定位「" + head + "」被误判" + (": " + got[0].detail if got else "")


# 带标题结构的材料：Q002 的材料验证通道用它当基准
MATERIAL_WITH_HEADINGS = (
    "# 第二卷\n\n"
    "## 抗日战争时期（上）\n\n"
    "### 团结到底\n\n"
    "#### 抗日战争的情况和教训\n\n"
    "谁是我们的敌人？谁是我们的朋友？这个问题是革命的首要问题〔1〕。\n\n"
    "#### 民主制度和抗日战争\n\n"
    "以斗争求团结则团结存，以退让求团结则团结亡，这一真理。\n\n"
    "```bash\n# 这不是标题，是注释\n```\n"
)


def test_q002_locator_naming_a_real_material_heading_passes():
    """**防误报闸门（实测）**：括号里写了材料真实标题 → 是**最好的**定位，不得报。

    实测「句段一（抗日战争的情况和教训）」在正则看来「没有章号 → 违规」，但材料里
    ``#### 抗日战争的情况和教训`` 是真实小节标题。正则穷举不完材料的组织方式
    （篇 / 讲 / 自然段 / 甲乙 / 小节标题…），「材料里找不找得到」才是可判定事实。
    """
    for head in ("抗日战争的情况和教训", "民主制度和抗日战争", "团结到底"):
        md = _HEAD + "##### 句段一（" + head + "）\n\n> 这个问题是革命的首要问题。\n"
        got = [v for v in q.check_quotes(md, MATERIAL_WITH_HEADINGS) if v.code == "Q002"]
        assert not got, "材料真实标题「" + head + "」被误判为无定位"


def test_q002_vague_locator_is_still_reported_with_material():
    """闸门不得放宽到「泛泛形容词也放过」——这类词正是 Q002 要抓的。"""
    for head in ("重要", "精彩", "核心观点", "总结", "作者观点", "关键内容"):
        md = _HEAD + "##### 句段一（" + head + "）\n\n> 这个问题是革命的首要问题。\n"
        got = [v for v in q.check_quotes(md, MATERIAL_WITH_HEADINGS) if v.code == "Q002"]
        assert got, "泛泛定位「" + head + "」漏判"


def test_q002_short_body_phrase_is_not_a_valid_locator():
    """短片段只认标题、不认正文：否则 3~4 字的泛词会在长材料里到处偶然命中。

    「首要问题」确实在材料正文里出现，但它只有 4 字、又不是标题，
    不足以构成定位（实测 30 万字材料里「有意思」「值得注意」都能偶然命中）。
    """
    md = _HEAD + "##### 句段一（首要问题）\n\n> 这个问题是革命的首要问题。\n"
    assert "Q002" in _codes(q.check_quotes(md, MATERIAL_WITH_HEADINGS))


def test_q002_long_body_phrase_is_a_valid_locator():
    """归一化后 ≥6 字的**正文长片段**可作为定位（材料没有标题结构时的退化路径）。"""
    md = _HEAD + "##### 句段一（以斗争求团结则团结存）\n\n> 以斗争求团结则团结存。\n"
    assert "Q002" not in _codes(q.check_quotes(md, MATERIAL_WITH_HEADINGS))


def test_q002_locator_parts_are_split_and_checked_individually():
    """「论政策·关于政权组织」按分隔符拆开逐段验：任一段命中即有效。"""
    md = (_HEAD + "##### 句段三（论政策·抗日战争的情况和教训）\n\n"
          "> 这个问题是革命的首要问题。\n")
    assert "Q002" not in _codes(q.check_quotes(md, MATERIAL_WITH_HEADINGS))


def test_q002_without_material_falls_back_to_regex_only():
    """没传材料时退回纯正则判断（不猜）：有章号定位放行，无定位仍报。"""
    ok = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n"
    assert "Q002" not in _codes(q.check_locators(ok))
    vague = _HEAD + "##### 句段一（抗日战争的情况和教训）\n\n> 这个问题是革命的首要问题。\n"
    assert "Q002" in _codes(q.check_locators(vague))          # 无材料可验证 → 仍按正则报
    assert "Q002" not in _codes(q.check_locators(vague, MATERIAL_WITH_HEADINGS))


def test_material_headings_extraction():
    """标题提取要跳过代码围栏（与 ``materials.heading_lines`` 同语义）。"""
    heads = q.material_headings(MATERIAL_WITH_HEADINGS)
    assert q._canon("抗日战争的情况和教训") in heads
    assert q._canon("团结到底") in heads
    assert q._canon("# 这不是标题，是注释") not in heads
    assert "这不是标题" not in {h for h in heads}
    assert q.material_headings("") == set()
    assert q.material_headings(None) == set()


def test_q002_only_excerpt_scope_is_checked():
    """非摘录作用域的 ##### 标题（如「概念名（原文术语）」）不参与 Q002。"""
    md = "#### 核心概念详解\n\n##### 概念名（原文术语）\n\n- 严谨定义：……\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == []


# ==========================================================================
# quote_check · Q003 页码
# ==========================================================================

def test_q003_page_present_in_material_is_clean():
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n\n见第 12 页。\n"
    assert q.check_quotes(md, MATERIAL + "\n第 12 页\n") == []


def test_q003_page_absent_from_material_is_reported():
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n\n见第 99 页。\n"
    vs = q.check_quotes(md, MATERIAL + "\n第 12 页\n")
    assert "Q003" in _codes(vs)
    v = next(x for x in vs if x.code == "Q003")
    assert v.severity == "advisory"
    assert "99" in v.detail and "未出现在材料中" in v.detail


def test_q003_material_without_any_page_is_reported():
    """材料本身不带页码 → 规范第 4 条要求「一律用章节定位」。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n\n见第 99 页。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert "Q003" in _codes(vs)
    assert "材料本身未带页码" in next(x for x in vs if x.code == "Q003").detail


def test_q003_english_page_notation_is_detected():
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n\n（P. 88）\n"
    assert "Q003" in _codes(q.check_quotes(md, MATERIAL))
    assert q.check_quotes(md, MATERIAL + "\nP. 88\n") == []


def test_q003_page_inside_code_fence_is_ignored():
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 这个问题是革命的首要问题。\n\n```text\n第 99 页\n```\n"
    assert "Q003" not in _codes(q.check_quotes(md, MATERIAL))


def test_q003_bare_page_number_in_material_counts():
    """PDF 抽取常见形态：整行只有页码。"""
    assert 7 in q.material_page_numbers("正文\n7\n正文\n")
    assert q.material_page_numbers("") == set()


# ==========================================================================
# quote_check · Q004 材料未涉及标注
# ==========================================================================

def test_q004_correct_marker_is_clean():
    assert q.check_quotes("材料未涉及，待核实：缺作者生平与写作年代。\n", MATERIAL) == []


def test_q004_incomplete_marker_is_reported():
    vs = q.check_quotes("材料未涉及，作者生平不明。\n", MATERIAL)
    assert "Q004" in _codes(vs)
    v = next(x for x in vs if x.code == "Q004")
    assert v.severity == "advisory"
    assert "应写「材料未涉及，待核实：（说明缺什么）」" in v.detail


def test_q004_marker_with_field_label_is_accepted():
    """**防误报闸门（实测）**：``- 严谨定义：材料未涉及，待核实。`` 属合规写法。

    模板字段名本身已充当「说明缺什么」；实测真实教程 20 处命中全是这种形态。
    """
    md = ("- 严谨定义：材料未涉及，待核实。\n"
          "- 与其他重要理论或思想的联系：材料未涉及，待核实。\n")
    assert q.check_quotes(md, MATERIAL) == []


def test_q004_prose_containing_dai_heshi_is_not_reported():
    """**防误报闸门（实测）**：论述句里的「待核实」不是标注行。

    实测真实教程 4640 行里有 178 处含「待核实 / 需核验」，绝大多数在正常论述句中。
    """
    md = ("- 与其他章的联系：材料未直接涉及与其他理论家的关系，待核实；"
          "从论证方式看它是承上启下的。\n")
    assert q.check_quotes(md, MATERIAL) == []


def test_q004_list_marker_without_colon_is_reported():
    """裸列表项写了「材料未涉及」却没写「待核实：说明」→ 报。"""
    assert "Q004" in _codes(q.check_quotes("- 材料未涉及。\n", MATERIAL))


def test_q004_marker_inside_code_fence_is_ignored():
    md = "```text\n材料未涉及\n```\n"
    assert _codes(q.check_quotes(md, MATERIAL)) == []


# ==========================================================================
# quote_check · Q005 三方观点
# ==========================================================================

def test_q005_separated_views_are_clean():
    md = ("#### 学界视角\n\n一派学者认为该论断成立，另一派研究者提出质疑。\n\n"
          "#### AI 辅助分析\n\n从论证看，这里的前提并不自明。\n")
    assert q.check_quotes(md, MATERIAL) == []


def test_q005_ai_tone_inside_scholar_section_is_reported():
    md = "#### 学界视角\n\n从论证看，这里的前提并不自明。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert "Q005" in _codes(vs)
    assert "AI 分析口吻" in next(x for x in vs if x.code == "Q005").detail


def test_q005_author_view_inside_scholar_section_is_reported():
    md = "#### 学界视角\n\n作者认为这个结论是成立的。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert "Q005" in _codes(vs)
    assert "直接陈述作者观点" in next(x for x in vs if x.code == "Q005").detail


def test_q005_scholar_consensus_inside_ai_section_is_reported():
    """forbidden_rules 明令：禁止把 AI 自己的解释写成学界共识。"""
    md = "#### AI 辅助分析\n\n学界普遍认为这个结论成立。\n"
    vs = q.check_quotes(md, MATERIAL)
    assert "Q005" in _codes(vs)
    assert "写成学界共识" in next(x for x in vs if x.code == "Q005").detail


def test_q005_no_real_dispute_marker_is_skipped():
    """规范认可「材料未显示存在实质争议」这种写法，不得再要求写明学派。"""
    assert q.check_quotes("#### 学界视角\n\n材料未显示存在实质争议。\n", MATERIAL) == []


def test_q005_missing_school_marker_is_reported():
    """「学界视角」没写明哪一派 / 哪类立场 → 报（规范要求「写明是哪一派/哪类立场」）。"""
    md = "#### 学界视角\n\n这个结论影响深远，值得重视。\n"
    assert "Q005" in _codes(q.check_quotes(md, MATERIAL))


def test_q005_section_ends_at_next_same_level_heading():
    """小节作用域必须止于下一个同级标题，否则后面章节的内容会被算进来。"""
    md = ("#### 学界视角\n\n一派学者持肯定立场。\n\n"
          "#### 思想关联\n\n从论证看，它与另一章相关。\n")
    assert q.check_quotes(md, MATERIAL) == []


# ==========================================================================
# practice_check · P002 代码语法（唯一 blocking）
# ==========================================================================

def test_p002_valid_python_is_clean():
    sec = _sec([{"type": "steps", "title": "运行示例", "body": "```python\nprint('hi')\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_python_syntax_error_is_blocking():
    """``def f(:`` 语法错 → 报 P002 且 blocking（示例不可能运行）。"""
    sec = _sec([{"type": "steps", "title": "运行示例", "body": "```python\ndef f(:\n    pass\n```"}])
    vs = pc.check_practice_section(sec, domain_key="cs_it")
    assert _codes(vs) == ["P002"]
    assert vs[0].severity == "blocking" and vs[0].blocking is True
    assert vs[0].auto_fixable is False
    assert "语法错误" in vs[0].detail


def test_p002_unbalanced_bracket_is_reported():
    sec = _sec([{"type": "text", "title": "括号", "body": "```python\nprint('a'\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == ["P002"]


def test_p002_nested_four_backtick_fence_is_not_parsed_as_code():
    """**防误报闸门（实测）**：````markdown 里嵌 ```python 示例，后文散文不得被吞进 ast.parse。

    实测报出「invalid character '。'」——朴素正则把「## 小结 / 到这里结束。」当成代码。
    """
    body = "正确：\n\n````markdown\n```python\nprint('hello')\n```\n````\n\n## 小结\n\n到这里结束。"
    sec = _sec([{"type": "text", "title": "围栏写法", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_unclosed_fence_is_skipped():
    """未闭合围栏：整段可能是被吞掉的正文，不送语法检查。"""
    sec = _sec([{"type": "text", "title": "残缺", "body": "```python\ndef f(:\n    pass\n"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_exercise_blank_is_skipped():
    """**防误报闸门（实测）**：练习留白是刻意不完整，不是语法错。"""
    body = "```python\na, b = int(input()), int(input())\nwhile b != 0:\n    # 在此补全一行\n\nprint(a)\n```"
    sec = _sec([{"type": "steps", "title": "练习", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_indented_fragment_is_skipped():
    """**防误报闸门（实测）**：从更大程序里截出的缩进片段，单独 parse 必然报错。"""
    sec = _sec([{"type": "steps", "title": "片段", "body": "```python\n    a, b = b, a % b\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_placeholder_token_is_skipped():
    """``<命令>`` 这类占位符是教学设计，不是语法错。"""
    sec = _sec([{"type": "steps", "title": "占位", "body": "```python\nrun(<命令>)\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_todo_marker_is_skipped():
    sec = _sec([{"type": "steps", "title": "占位", "body": "```python\nx = 1  # TODO 补全\ny =\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_js_unbalanced_brackets_is_reported():
    """JS 不引入 node 依赖，只做确定性括号配平检查。"""
    sec = _sec([{"type": "text", "title": "js", "body": "```javascript\nfunction f() { return [1,2; }\n```"}])
    vs = pc.check_practice_section(sec, domain_key="cs_it")
    assert _codes(vs) == ["P002"]
    assert "括号不配平" in vs[0].detail


def test_p002_js_unclosed_brace_is_reported():
    sec = _sec([{"type": "text", "title": "js", "body": "```js\nfunction f() {\n  return 1;\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == ["P002"]


def test_p002_js_balanced_is_clean():
    """括号配平的正常 JS 不得报（深层语法校验对不完整片段必然假阳性）。"""
    sec = _sec([{"type": "text", "title": "js",
                "body": "```javascript\nconst f = (a) => { return [a, a + 1]; };\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_bracket_inside_js_string_or_comment_is_ignored():
    """字符串与注释里的括号不是结构：先去字面量与注释再配平。"""
    body = ('```javascript\nconst s = "}";\nconst t = "]";\n// 这里有个 { 不配对\n'
            '/* 块注释里也有 } */\n```')
    sec = _sec([{"type": "text", "title": "js", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_typescript_alias_is_checked():
    sec = _sec([{"type": "text", "title": "ts", "body": "```typescript\nlet x: number = [1;\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == ["P002"]


def test_p002_other_languages_are_not_checked():
    """cpp / css / mermaid 等没有零依赖的确定性检查手段，不猜（猜就产生假阳性）。"""
    body = "```cpp\nint main( {\n```\n\n```mermaid\ngraph TD\n  a-->\n```\n\n```css\ndiv { color: red;\n```"
    sec = _sec([{"type": "text", "title": "其它语言", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p002_checks_every_content_block_not_just_first():
    """模型有时把代码拆到第二块，只查第一块会漏检（与 exam_check.section_body 同理）。"""
    sec = _sec([
        {"type": "text", "title": "说明", "body": "先看示例。"},
        {"type": "example", "title": "示例", "body": "```python\ndef f(:\n```"},
    ])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == ["P002"]


def test_p002_reports_each_bad_block_once():
    """同一块的同一个错只报一条（seen 去重）。"""
    sec = _sec([{"type": "text", "title": "两块",
                "body": "```python\ndef a(:\n```\n\n```python\ndef b(:\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == ["P002", "P002"]


# ==========================================================================
# practice_check · P001 步骤三要素
# ==========================================================================

def test_p001_steps_with_expected_and_verify_are_clean():
    body = "1. 打开 `设置` 面板，勾选自动保存。预期：出现复选框被勾选。验证：重启后设置仍在。\n"
    sec = _sec([{"type": "steps", "title": "操作步骤", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_missing_both_elements_is_reported():
    body = ("1. 打开 `设置` 面板，勾选自动保存。\n"
            "2. 点击 `文件` 菜单里的保存。\n"
            "3. 关闭程序。\n")
    sec = _sec([{"type": "steps", "title": "操作步骤", "body": body}])
    vs = pc.check_practice_section(sec, domain_key="cs_it")
    assert _codes(vs) == ["P001"]
    assert vs[0].severity == "advisory" and vs[0].blocking is False
    assert "3 步" in vs[0].detail and "步骤 1、2、3" in vs[0].detail


def test_p001_elements_in_sub_items_are_counted():
    """**防误报闸门（实测）**：预期与验证常写在**子项**里，逐行判会大面积误报。

    实测 785 个步骤行里 243 行不含关键词，绝大多数是 ``- 预期：…`` / ``- 失败：…`` 子项。
    """
    body = ("1. **确认命令来源**：`Get-Command` 查一下。\n"
            "   - 预期：返回一条命令信息。\n"
            "   - 验证：CommandType 为 Cmdlet。\n")
    sec = _sec([{"type": "steps", "title": "探查", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_expected_plus_failure_branch_is_accepted():
    """**实测场景**：步骤写了「预期」与「失败分支」，没写「验证」字样。

    P001 只在**两者皆缺**时报：这类步骤已经让读者能自检（看到什么、失败长什么样），
    报它属于把措辞偏好当规范。实测「预期/失败」成对出现的步骤共 23 块。
    """
    body = ("1. **确认命令来源**：`Get-Command` 查一下。\n"
            "   - 预期：返回一条命令信息。\n"
            "   - 失败：报 CommandNotFoundException，说明命令不在 PATH。\n")
    sec = _sec([{"type": "steps", "title": "探查", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_merged_expected_and_verify_is_accepted():
    """**防误报闸门（实测）**：「预期与验证合并写一句」是合理写法，103 个步骤属此类。"""
    body = ("1. **只修这一处，重新编译**。验证：对比报错条数是否明显减少；"
            "如果一条都没少，说明你修的不是根因。\n")
    sec = _sec([{"type": "steps", "title": "修错", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_should_show_wording_counts_as_expected():
    """"应显示 / 会看到 / 屏幕上出现" 等同义措辞都算预期结果。"""
    body = ("1. 点击 `运行`。应显示进度条。\n"
            "2. 等待结束，屏幕上出现结果表。\n")
    sec = _sec([{"type": "steps", "title": "运行", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_non_operational_steps_are_skipped():
    """**防误报闸门（实测）**：数学推导 / 概念辨析不适用「预期结果 / 验证方式」。

    实测 71 个「两者皆缺」的步骤里 42 个属非操作性内容（逆矩阵验算、祛魅辨析）。
    加闸门后块级报告 67 → 18 条。
    """
    body = ("1. 任取 $A$ 的第 $i$ 行与 $A^{-1}$ 的第 $j$ 列作内积。\n"
            "2. 问意义来源：这个现象里，是不是「世界本身不再提供意义」在起作用？\n"
            "3. 写出结论与适用条件。\n")
    sec = _sec([{"type": "steps", "title": "推导", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_operational_marker_triggers_check():
    """含菜单 / 命令 / 代码块等操作性标记的块才判三要素。"""
    body = "1. 记下这一步的结论。\n2. 写下理由。\n"
    assert _codes(pc.check_practice_section(_sec([{"type": "steps", "title": "a", "body": body}]))) == []
    body2 = "1. 点击 `保存` 按钮。\n2. 关闭窗口。\n"
    assert _codes(pc.check_practice_section(_sec([{"type": "steps", "title": "b", "body": body2}]))) == ["P001"]


def test_p001_only_steps_blocks_are_checked():
    """``type != "steps"`` 的块不判三要素（text / table / example 各有形态）。"""
    sec = _sec([{"type": "text", "title": "说明", "body": "1. 打开 `设置`。\n2. 关闭。\n"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_one_violation_per_block():
    """一个块只报一条（缺失步骤号聚合进 detail），避免 quality_report 被同质条目淹掉。"""
    body = "1. 打开 `设置`。\n2. 点击保存。\n3. 关闭窗口。\n4. 重启程序。\n"
    sec = _sec([{"type": "steps", "title": "操作", "body": body}])
    assert len(pc.check_steps_elements(sec)) == 1


def test_p001_steps_inside_code_fence_are_not_parsed():
    body = ("1. 打开 `设置`。预期：面板出现。验证：勾选项存在。\n\n"
            "```bash\n1. 这不是步骤\n2. 也不是\n```\n")
    sec = _sec([{"type": "steps", "title": "操作", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_empty_body_is_skipped():
    sec = _sec([{"type": "steps", "title": "空", "body": "   "}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p001_v1_steps_structure_does_not_crash():
    """v1 结构（顶层 steps 列表）由 engine.check_structure 校验，本模块不重复判但也不崩。"""
    sec = {"title": "旧结构", "steps": [{"text": "打开设置。", "expected_result": "", "verification": ""}]}
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


# ==========================================================================
# practice_check · P003 命令存在性（只探测、绝不执行）
# ==========================================================================

# 测试环境里确实存在的命令；找不到就跳过（不拿环境差异当失败）
_REAL_CMD = next((c for c in ("python", "python3", "py") if shutil.which(c)), None)


def test_p003_existing_command_is_clean():
    """``shutil.which`` 能找到的命令（如 python）→ 通过。"""
    if _REAL_CMD is None:
        pytest.skip("测试环境未找到 python，无法验证 which 命中路径")
    sec = _sec([{"type": "steps", "title": "运行", "body": "```bash\n" + _REAL_CMD + " -V\n```"}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_fabricated_command_is_reported():
    """编造命令（``nonexistent_cmd_xyz``）→ 报 P003 advisory。"""
    assert shutil.which("nonexistent_cmd_xyz") is None    # 前提：确实不存在
    sec = _sec([{"type": "steps", "title": "运行",
                "body": "```bash\nnonexistent_cmd_xyz --flag\npython -V\n```"}])
    vs = pc.check_practice_section(sec, domain_key="computer_cli")
    assert _codes(vs) == ["P003"]
    assert vs[0].severity == "advisory" and vs[0].blocking is False
    assert "nonexistent_cmd_xyz" in vs[0].detail
    assert "PATH 中找不到" in vs[0].detail


def test_p003_several_fabricated_commands_are_deduped():
    """同一块里多个可疑命令都要列出（去重后）。"""
    sec = _sec([{"type": "steps", "title": "运行",
                "body": "```bash\nfake_cmd_a -x\nfake_cmd_a -y\nfake_cmd_b\n```"}])
    vs = pc.check_practice_section(sec, domain_key="computer_cli")
    assert _codes(vs) == ["P003"]
    assert "fake_cmd_a" in vs[0].detail and "fake_cmd_b" in vs[0].detail
    assert vs[0].detail.count("fake_cmd_a") == 1          # 去重


def test_p003_shell_builtins_are_not_reported():
    """**防误报闸门（实测）**：Shell 内建本来就不是可执行文件，which 不到属正常。

    实测本机 ``ls`` / ``cat`` / ``grep`` / ``echo`` / ``mkdir`` 全部 which=False。
    """
    body = "```bash\nls -la\ncat file.txt\ngrep -r foo .\nmkdir -p out\necho hi\n```"
    sec = _sec([{"type": "steps", "title": "命令", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_uninstalled_common_tools_are_not_reported():
    """**防误报闸门（实测）**：which 失败 ≠ 命令不存在，可能只是本机没装。

    实测本机 ``docker`` / ``g++`` which=False，但没人会说它们是编造的命令。
    """
    body = "```bash\ndocker ps\ng++ a.cpp -o a\nkubectl get pods\nnpm install\n```"
    sec = _sec([{"type": "steps", "title": "编译", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_shell_keywords_are_not_reported():
    """if / for / while / function / exit 是关键字，不是命令。"""
    body = "```bash\nif [ -f a ]; then echo yes; fi\nfor i in 1 2; do echo $i; done\nwhile true; do break; done\nexit 0\n```"
    sec = _sec([{"type": "steps", "title": "脚本", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_powershell_blocks_are_never_probed():
    """**防误报闸门（实测）**：PowerShell 首词是 Cmdlet，which 100% 为 None。

    实测库内 86 个 powershell 围栏（Get-ChildItem ×35、Select-Object ×13、
    Where-Object ×11…），不加这道闸一份教程会报上百条假阳性。
    """
    body = ("```powershell\n"
            "Get-ChildItem -Path 'C:/Data' | Where-Object { $_.Length -ge 10MB }\n"
            "  | Select-Object -First 5 | Sort-Object Length -Descending\n"
            "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned\n"
            "```")
    sec = _sec([{"type": "steps", "title": "ps", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_cmdlet_looking_token_is_skipped_even_in_bash():
    """Verb-Noun 形态的 token 是 PowerShell Cmdlet，在 bash 块里也不 which 探测。"""
    body = "```bash\nGet-ChildItem -Path .\nInvoke-WebRequest -Uri http://x\n```"
    sec = _sec([{"type": "steps", "title": "混合", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_unlanguaged_fence_is_not_probed():
    """实测 667 个围栏没有语言标记，内容可能是输出而非命令，一律不探测。"""
    sec = _sec([{"type": "steps", "title": "输出",
                "body": "```\nnonexistent_cmd_xyz: command not found\n```\n"}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_non_code_fence_languages_are_not_probed():
    """json / text / markdown 围栏里不是命令行。"""
    body = '```json\n{"cmd": "nonexistent_cmd_xyz"}\n```\n\n```text\nnonexistent_cmd_xyz 不存在\n```'
    sec = _sec([{"type": "steps", "title": "配置", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_only_computer_domains_are_probed():
    """非计算机类领域跳过：其它领域的「命令」多是领域记法，which 无意义。"""
    sec = _sec([{"type": "steps", "title": "运行", "body": "```bash\nnonexistent_cmd_xyz --flag\n```"}])
    for domain in ("math_data", "physics_astronomy", "arts_creativity", ""):
        assert _codes(pc.check_practice_section(sec, domain_key=domain)) == []
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == ["P003"]
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == ["P003"]


def test_p003_prompts_variables_and_paths_are_not_treated_as_commands():
    """提示符 / 变量 / 路径 / 选项都不是命令名（首词提取必须保守）。"""
    body = ("```bash\n"
            "$ python -V\n"
            "(venv) $ ls\n"
            "./script.sh\n"
            "-x --verbose\n"
            "SRC=1 make\n"
            "| sort\n"
            "> out.txt\n"
            "```")
    sec = _sec([{"type": "steps", "title": "命令", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="computer_cli")) == []


def test_p003_probe_never_executes_commands():
    """**安全边界**：探测只用 ``shutil.which``（路径查找），绝不启动进程。

    用副作用探针钉死边界：把 os.system / subprocess.* 换成会失败的桩，
    探测若真的执行了命令就会抛错。校验器执行教程里的命令 = 运行未知代码。
    """
    import os
    import subprocess

    calls = []

    def _boom(*a, **k):
        calls.append("executed")
        raise AssertionError("P003 探测执行了命令")

    orig = (os.system, subprocess.run, subprocess.Popen, subprocess.call)
    os.system, subprocess.run, subprocess.Popen, subprocess.call = _boom, _boom, _boom, _boom
    try:
        sec = _sec([{"type": "steps", "title": "运行",
                    "body": "```bash\nfake_cmd_zzz --danger\nrm -rf /\n```"}])
        pc.check_practice_section(sec, domain_key="computer_cli")
    finally:
        os.system, subprocess.run, subprocess.Popen, subprocess.call = orig
    assert calls == []


def test_p003_probe_commands_helper_is_pure():
    """``probe_commands`` 只做存在性判断，返回 (行号, 命令名)。"""
    got = pc.probe_commands("nonexistent_cmd_xyz -a\npython -V\nls -la\n")
    assert [t for _, t in got] == ["nonexistent_cmd_xyz"]
    assert got[0][0] == 1


# ==========================================================================
# practice_check · P004 记法一致性
# ==========================================================================

def test_p004_consistent_shortcuts_are_clean():
    sec = _sec([{"type": "text", "title": "快捷键",
                "body": "按 Ctrl+C 复制、Ctrl+V 粘贴、Ctrl+S 保存。\n"}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_mixed_shortcut_styles_are_reported():
    body = "按 Ctrl+C 复制，Ctrl + V 粘贴，或 Ctrl " + _FULL_PLUS + " S 保存。\n"
    sec = _sec([{"type": "text", "title": "快捷键", "body": body}])
    vs = pc.check_practice_section(sec, domain_key="cs_it")
    assert _codes(vs) == ["P004"]
    assert vs[0].severity == "advisory"
    assert "共 3 处" in vs[0].detail          # 去重后计数准确（不是 6）


def test_p004_combo_shortcuts_are_counted_once():
    """Ctrl+Alt+Del 这类组合键被两条正则都匹配，必须按 span 去重。"""
    body = "按 Ctrl+Alt+Del 打开、Ctrl + Alt + Del 重启、Ctrl＋Alt＋Del 结束。\n"
    sec = _sec([{"type": "text", "title": "组合键", "body": body}])
    vs = [v for v in pc.check_practice_section(sec, domain_key="cs_it") if v.code == "P004"]
    assert vs and "共 3 处" in vs[0].detail


def test_p004_mixed_menu_separators_are_reported():
    body = "走 文件 > 保存，再走 编辑 " + _ARROW + " 撤销，以及 视图 " + _ARROW + " 大纲。\n"
    sec = _sec([{"type": "text", "title": "菜单", "body": body}])
    vs = pc.check_practice_section(sec, domain_key="cs_it")
    assert _codes(vs) == ["P004"]
    assert "菜单路径分隔符" in vs[0].detail


def test_p004_consistent_menu_separators_are_clean():
    body = "走 文件 > 保存，再走 编辑 > 撤销，以及 视图 > 大纲。\n"
    sec = _sec([{"type": "text", "title": "菜单", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_process_arrows_are_not_menu_paths():
    """**防误报闸门（实测）**：``→`` 命中 786 处全是流程箭头，规范模板自己就写
    「目标 → 步骤 → 关键决策 → 结果检查」。左侧不是菜单词就不得当菜单路径。
    """
    body = "目标 → 步骤 → 关键决策 → 结果检查；流程是 取数 → 筛选 → 排序 → 导出。\n"
    sec = _sec([{"type": "text", "title": "流程", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_slash_juxtaposition_is_not_menu_path():
    """**防误报闸门（实测）**：``/`` 命中 1072 处全是并列词（「文件/目录」「大于 / 大于等于」）。"""
    body = "文件/目录项、隐藏/系统项、大于 / 大于等于、按大小/时间排序、筛选/排序依据。\n"
    sec = _sec([{"type": "text", "title": "并列", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_quote_marker_is_not_menu_separator():
    """**防误报闸门（实测）**：``>`` 大量是 Markdown 引用块符号，不是菜单分隔符。"""
    body = "警告块写法：\n\n> 标题\n> 正文内容\n\n> 这是另一个普通提示\n> 第二行同样以大于号开头。\n"
    sec = _sec([{"type": "text", "title": "引用块", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_operators_inside_code_are_ignored():
    """代码块里的 ``->`` / ``+`` / ``>`` 是语法，不参与记法统计。"""
    body = ("统一用 Ctrl+C 复制。\n\n"
            "```cpp\nfor (auto it = v.begin(); it != v.end(); ++it) {}\nif (a > b) {}\n```\n")
    sec = _sec([{"type": "text", "title": "代码", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_plain_phrases_are_not_shortcuts():
    """**防误报闸门（实测）**：宽松规则把「Windows 11」「Command Get」误当快捷键。

    连接符必须是显式的 + / ＋ / -> / →，否则不认为是快捷键。
    """
    body = "Windows 11 上用 Command Get 查命令，Option 3 是第三种做法，Shift 2 表示两步。\n"
    sec = _sec([{"type": "text", "title": "说明", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_two_occurrences_are_not_judged():
    """不足 3 处不判：无法区分「不统一」与「只用了一次」。"""
    body = "按 Ctrl+C 复制，或 Ctrl + V 粘贴。\n"
    sec = _sec([{"type": "text", "title": "快捷键", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


def test_p004_overwhelming_majority_style_is_not_reported():
    """主风格压倒性（25:1）时不报：一处笔误不值得让整个章节「待改进」。"""
    body = "用 Ctrl+A、Ctrl+C、Ctrl+V、Ctrl+S、Ctrl+Z、Ctrl+Y、Ctrl+F、Ctrl+P、Ctrl+N、Ctrl+O、Ctrl+W，只有 Ctrl + Q 例外。\n"
    sec = _sec([{"type": "text", "title": "快捷键", "body": body}])
    assert _codes(pc.check_practice_section(sec, domain_key="cs_it")) == []


# ==========================================================================
# 两个模块的公共契约
# ==========================================================================

def test_severity_tables_and_is_blocking():
    assert q.SEVERITY == {
        "Q001": "blocking", "Q002": "advisory", "Q003": "advisory",
        "Q004": "advisory", "Q005": "advisory",
    }
    assert pc.SEVERITY == {
        "P001": "advisory", "P002": "blocking", "P003": "advisory", "P004": "advisory",
    }
    assert q.is_blocking("Q001") and not q.is_blocking("Q002")
    assert pc.is_blocking("P002") and not pc.is_blocking("P001")
    # 未知码按 blocking 处理（与 exam_check 同构：宁可拦住不可漏过）
    assert q.is_blocking("Q999") and pc.is_blocking("P999")


def test_every_code_has_rule_and_basis():
    """basis 必须指向规范条文——让「为什么算违规」可回溯到规范而非代码私货。"""
    for mod, prefix in ((q, "Q"), (pc, "P")):
        for code, (rule, basis) in mod.CODES.items():
            assert code.startswith(prefix)
            assert rule and basis
            assert code in mod.SEVERITY
            assert "规范" in basis, code + " 的 basis 未指向规范条文：" + basis


def test_violation_to_dict_shape():
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 编造的引文内容在这里。\n"
    d = q.check_quotes(md, MATERIAL)[0].to_dict()
    assert set(d) == {"code", "rule", "basis", "detail", "auto_fixable", "fixed", "severity"}
    assert d["code"] == "Q001" and d["severity"] == "blocking" and d["fixed"] is False

    sec = _sec([{"type": "steps", "title": "x", "body": "```python\ndef f(:\n```"}])
    d2 = pc.check_practice_section(sec, domain_key="cs_it")[0].to_dict()
    assert set(d2) == set(d) and d2["severity"] == "blocking"


def test_blocking_property_ignores_fixed_violations():
    """已修好的不该再拦（与 exam_check.Violation.blocking 语义一致）。"""
    v = q.Violation("Q001", *q.CODES["Q001"], "detail")
    assert v.blocking is True
    v.fixed = True
    assert v.blocking is False
    a = pc.Violation("P001", *pc.CODES["P001"], "detail")
    assert a.blocking is False          # advisory 本来就不阻塞


def test_nothing_is_auto_fixable():
    """两个模块都**只判定不改写**：引文与命令都没有唯一正确的机械修法。"""
    md = _HEAD + "##### 句段一（重要）\n\n> 编造的引文内容在这里。\n\n材料未涉及，作者生平不明。\n"
    for v in q.check_quotes(md, MATERIAL):
        assert v.auto_fixable is False
    sec = _sec([{"type": "steps", "title": "x", "body": "```python\ndef f(:\n```\n"}])
    for v in pc.check_practice_section(sec, domain_key="cs_it"):
        assert v.auto_fixable is False


def test_summarize_passed_only_looks_at_blocking():
    """advisory 不该把交付物标成「待改进」，否则 blocking 信号被噪音淹没。"""
    md = _HEAD + "##### 句段一（重要）\n\n> 这个问题是革命的首要问题。\n"
    s = q.summarize(q.check_quotes(md, MATERIAL))
    assert s["passed"] is True and s["codes"] == {"Q002": 1} and s["advisory"] == 1

    md2 = _HEAD + "##### 句段一（第1章第1节）\n\n> 编造的引文内容在这里。\n"
    s2 = q.summarize(q.check_quotes(md2, MATERIAL))
    assert s2["passed"] is False and s2["blocking"] == 1

    sec = _sec([{"type": "steps", "title": "x", "body": "1. 点击 `保存`。\n"}])
    s3 = pc.summarize(pc.check_practice_section(sec, domain_key="cs_it"))
    assert s3["passed"] is True and s3["codes"] == {"P001": 1}

    sec2 = _sec([{"type": "text", "title": "x", "body": "```python\ndef f(:\n```"}])
    s4 = pc.summarize(pc.check_practice_section(sec2, domain_key="cs_it"))
    assert s4["passed"] is False and s4["blocking"] == 1


def test_empty_and_malformed_input_is_safe():
    """空输入 / 结构异常不得抛错（校验跑在生成链路里，崩了就整条链路失败）。"""
    assert q.check_quotes("", "") == []
    assert q.check_quotes(None, None) == []
    assert pc.check_practice_section({}, domain_key="cs_it") == []
    assert pc.check_practice_section({"content": None}, domain_key="cs_it") == []
    assert pc.check_practice_section({"content": ["not-a-dict", {"body": None}]},
                                     domain_key="cs_it") == []
    assert pc.section_body({"markdown": "# 兜底"}) == "# 兜底"
    assert pc.iter_blocks({"content": "not-a-list"}) == []
    assert pc.parse_steps("") == []
    assert pc.parse_code_fences("") == []


def test_parse_steps_aggregates_sub_items():
    """解析结构本身要可测：顶层步骤 + 子项 + 行号。"""
    body = ("1. 打开 `设置`。\n"
            "   - 预期：面板出现。\n"
            "   - 验证：勾选项存在。\n"
            "2. 点击保存。预期：出现提示。验证：文件已写入。\n")
    steps = pc.parse_steps(body)
    assert [s.number for s in steps] == [1, 2]
    assert steps[0].lineno == 1 and len(steps[0].sub) == 2
    assert steps[0].has_expected and steps[0].has_verify
    assert steps[1].lineno == 4 and steps[1].sub == []
    assert steps[1].has_expected and steps[1].has_verify


def test_parse_steps_keeps_only_expected_sub_item_separate():
    """只有「预期 / 失败」子项、且正文无验证措辞 → has_verify 为 False。

    注意判定单位是**整步**（顶层步骤文本 + 全部子项），不是单行。
    步骤文本里的动作动词若含「确认 / 检查」也会被计入验证措辞，那是**偏漏判**
    方向的宽松（advisory 检查宁可漏报不误报），见 practice_check._VERIFY_RE。
    """
    body = "1. **查命令来源**：`Get-Command`。\n   - 预期：返回一条命令信息。\n   - 失败：报 CommandNotFoundException。\n"
    steps = pc.parse_steps(body)
    assert len(steps) == 1
    assert steps[0].has_expected is True and steps[0].has_verify is False


def test_action_verb_counts_as_verify_wording_documented():
    """上面那条取舍的正向固化：步骤文本含「确认」即视为已给验证线索（漏判优于误报）。"""
    body = "1. **确认命令来源**：`Get-Command`。\n   - 预期：返回一条命令信息。\n"
    assert pc.parse_steps(body)[0].has_verify is True


def test_parse_steps_chinese_and_paren_numbering():
    """``1、`` 与 ``1)`` 也是合法编号（实测模型输出三种都有）。"""
    assert [s.number for s in pc.parse_steps("1、打开 `设置`。\n2）点击保存。")] == [1, 2]


def test_parse_code_fences_matches_by_length():
    """围栏按**长度配对**（CommonMark 语义），这是 P002 第一道防误报闸门。"""
    body = "````markdown\n```python\nprint('hello')\n```\n````\n\n```python\nx = 1\n```"
    fences = pc.parse_code_fences(body)
    assert [f.lang for f in fences] == ["markdown", "python"]
    assert all(f.closed for f in fences)
    assert "print('hello')" in fences[0].code
    # 行号：````markdown 在第 1 行，第 5 行收场，第 6 行空行，```python 起于第 7 行
    assert fences[0].lineno == 1 and fences[1].lineno == 7


def test_parse_code_fences_tilde_variant():
    fences = pc.parse_code_fences("~~~python\nx =\n~~~")
    assert len(fences) == 1 and fences[0].lang == "python" and fences[0].closed


def test_quote_block_parsing_records_scope():
    """QuoteBlock 要带上小节名与最近的 ##### 标题（Q001/Q002 都依赖它）。"""
    md = _HEAD + "##### 句段一（第1章第1节）\n\n> 摘录正文第一行。\n> 摘录正文第二行。\n"
    blocks = q.parse_quote_blocks(md)
    assert len(blocks) == 1
    b = blocks[0]
    assert b.section == "关键句段解读"
    assert b.heading == "句段一（第1章第1节）" and b.heading_level == 5
    assert b.lineno == 5 and b.heading_lineno == 3
    assert "摘录正文第一行" in b.text and "摘录正文第二行" in b.text
    assert "第 5 行" in b.where


def test_canon_normalizes_fullwidth_and_quotes():
    """归一化要吸收全角/半角与引号体系差异，但不吸收实词差异。"""
    assert q._canon("ＡＢＣ（1）「x」") == q._canon('ABC(1)"x"')
    assert q._canon("a\u200bb\ufeffc") == "abc"
    assert q._canon("多行\n文本 拼接") == "多行文本拼接"
    assert q._canon("敌人") != q._canon("朋友")


def test_segment_helper_splits_and_filters():
    segs = q.segments("第一段内容……第二段内容……的")
    assert len(segs) == 2          # 「的」过短被丢弃
    assert q.segments("") == []


def test_python_version_supports_ast_parse():
    """ast.parse 需要 py3.8+；本仓库 venv 是 3.12（探测用，防止环境退化）。"""
    assert sys.version_info >= (3, 8)
