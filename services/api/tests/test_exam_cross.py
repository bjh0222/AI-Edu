# -*- coding: utf-8 -*-
"""E013 留白 / E017 母题重复 / E018 同母题不同答案 的测试。

这些判据是被真实卷子逼出来的，每条测试都对应一次实测踩坑，不是凑覆盖率：
- E017 用「共享定义式」而非题干 Jaccard 相似度（否则同母题不同问法会被拆开，漏报）；
- E018 比「答案内容」而非选项字母，且只比客观短答案（否则主观题证明文本会误报）；
- E018 必须跨题型可比（选择题答 e^2 / 填空题答 e^-1 是真错误）。
"""
from __future__ import annotations

from app.services import exam_check as ec


def _two_papers(body_a: str, body_b: str):
    doc = f"# 卷\n\n## 一、第一套\n\n{body_a}\n\n## 二、第二套\n\n{body_b}\n"
    return [(n, ec.parse_paper(b, n)) for n, b in ec.split_papers(doc)]


FN_A = """
### 选择题

**1.**（4 分）设 $f_n(x)=x^n+2nx-2$ 的正根为 $a_n$，则 $\\lim_{n\\to+\\infty}(1+a_n)^n=$（　　）

A. $1$　　B. $e$　　C. $e^2$　　D. $+\\infty$

### 参考答案

**1.** C
"""

FN_B = """
### 填空题

**1.**（4 分）设 $f_n(x)=x^n+2nx-2$ 的正根为 $a_n$，则 $\\lim_{n\\to\\infty}(1+a_n)^n=$ ______。

### 参考答案

**1.** $e^{-1}$
"""

FN_C = """
### 填空题

**1.**（4 分）设 $f_n(x)=x^n+2nx-2$ 的正根为 $a_n$，则 $\\lim_{n\\to\\infty}(1+a_n)^n=$ ______。

### 参考答案

**1.** $e$
"""


def test_same_motif_different_answer_reported():
    """实测真错误：同一母题，选择题答 e^2、填空题答 e^-1。"""
    parsed = _two_papers(FN_A, FN_B)
    codes = [v.code for v in ec.check_cross_paper(parsed)]
    assert "E017" in codes and "E018" in codes
    e018 = next(v for v in ec.check_cross_paper(parsed) if v.code == "E018")
    assert "e^2" in e018.detail and "e^{-1}" in e018.detail
    assert not e018.auto_fixable


def test_same_motif_same_answer_not_reported_as_e018():
    """同一母题、不同问法但答案一致（都是 e）：报 E017，不报 E018。"""
    parsed = _two_papers(FN_A.replace("**1.** C", "**1.** B"), FN_C)
    vs = ec.check_cross_paper(parsed)
    assert "E017" in [v.code for v in vs]
    assert "E018" not in [v.code for v in vs]


def test_choice_letter_alone_is_not_evidence():
    """两卷都答 C 但选项内容不同 => 不是「答案一致」，也不是简单字母相等。

    只比字母会双向出错。这里两卷 C 指向不同内容，必须报 E018。
    """
    b = FN_A.replace("A. $1$　　B. $e$　　C. $e^2$　　D. $+\\infty$",
                     "A. $1$　　B. $e$　　C. $e^{-1}$　　D. $+\\infty$")
    parsed = _two_papers(FN_A, b)
    assert "E018" in [v.code for v in ec.check_cross_paper(parsed)]


def test_judge_and_choice_answers_are_not_mixed():
    """判断题的 T/F 与选择题的 A-D 不可互比（实测误报来源）。"""
    judge = FN_A.replace("### 选择题", "### 判断题").replace("**1.** C", "**1.** 正确")
    parsed = _two_papers(FN_A, judge)
    assert "E018" not in [v.code for v in ec.check_cross_paper(parsed)]


def test_long_subjective_answers_are_not_compared():
    """主观题的成段证明文本不参与 E018（措辞略异但都正确会被误判）。"""
    long_a = FN_A.replace("**1.** C", "**1.** (1) 由零点定理知存在正根，又 f'(x)>0 故唯一；" * 3)
    long_b = FN_B.replace("**1.** $e^{-1}$", "**1.** (1) 由零点定理可知存在正根，且 f'(x)>0 所以唯一；" * 3)
    parsed = _two_papers(long_a, long_b)
    assert "E018" not in [v.code for v in ec.check_cross_paper(parsed)]


def test_shared_assumption_alone_is_not_same_motif():
    """只共享 `f(a)=f(b)` 这类通用假设不算同母题（否则中值定理题全被判重复）。"""
    a = """
### 判断题

**1.**（3 分）若 $f$ 在 $[a,b]$ 上连续、在 $(a,b)$ 内可导且 $f(a)=f(b)$，则存在 $\\xi$ 使 $f'(\\xi)=0$。

<p align="right"><input type="checkbox"> </p>

### 参考答案

**1.** 正确
"""
    b = a.replace("则存在 $\\xi$ 使 $f'(\\xi)=0$", "则 $f$ 在 $[a,b]$ 上恒为常数")
    parsed = _two_papers(a, b)
    assert "E017" not in [v.code for v in ec.check_cross_paper(parsed)]


def test_query_key_normalization():
    r"""\to+\infty 与 \to\infty 是同一个量（实测漏报来源）。"""
    assert ec._canon_query(r"\lim_{n\to+\infty}(1+a_n)^n=") == ec._canon_query(
        r"\lim_{n\to\infty}(1+a_n)^n="
    )
    # \left. 剥掉 \left 后不得残留孤立点
    assert ec._canon_query(r".\frac{d^2x}{dy^2}|_{t=1}=") == r"\frac{d^2x}{dy^2}|_{t=1}="


def test_option_lines_excluded_from_motifs():
    r"""选项里的 $\alpha>1$、$\frac{1}{2}$ 不得成为母题指纹（实测噪音来源）。"""
    block = [
        r"**1.**（4 分）设 $f(x)=x^2e^{\sin^2\frac1x}$，则 $f'(0)=$（　　）",
        r"A. $\alpha>1$　　B. $\frac{1}{2}$　　C. $0$　　D. $\alpha>2$",
    ]
    motifs = ec.question_motifs(block)
    assert r"\alpha>1" not in motifs
    assert r"\frac{1}{2}" not in motifs
    assert any("x^2e^{" in m for m in motifs)


def test_cases_definition_is_split_per_line():
    r"""cases 里的多行定义式必须逐行成指纹（否则跨卷聚不到一起）。"""
    block = [r"$$\begin{cases}x=\ln\left(t+\sqrt{1+t^2}\right),\\ y=\arctan t,\end{cases}$$"]
    motifs = ec.question_motifs(block)
    assert any("x=\\ln(t+\\sqrt{1+t^2})" == m for m in motifs)
    assert any("y=\\arctant" == m for m in motifs)


def test_answer_content_resolves_choice_to_option_text():
    parsed = _two_papers(FN_A, FN_C)
    paper_a = parsed[0][1]
    cat, content = ec.answer_content(paper_a, 1)
    assert cat == "choice"
    assert content == "e^2"


def test_single_paper_skips_cross_checks():
    parsed = [(n, ec.parse_paper(b, n)) for n, b in ec.split_papers(f"# 卷\n\n## 一、第一套\n\n{FN_A}\n")]
    assert ec.check_cross_paper(parsed) == []


# ------------------------------------------------------------------ E013 留白

_BLANKS = """
> 本卷满分 100 分，考试时间 120 分钟，共 2 题。

### 选择题

**1.**（50 分）题干（　　）

A. 甲　　B. 乙


### 判断题

**2.**（50 分）判断题。

<p align="right"><input type="checkbox"> </p>

### 参考答案

**1.** A　**2.** 正确
"""


def test_blanks_ok_for_choice_and_judge():
    paper = ec.parse_paper(_BLANKS)
    assert ec.check_blanks(_BLANKS, paper) == []


def test_blanks_mismatch_reported_not_auto_fixed():
    bad = _BLANKS.replace("A. 甲　　B. 乙\n\n\n", "A. 甲　　B. 乙\n")
    paper = ec.parse_paper(bad)
    vs = ec.check_blanks(bad, paper)
    assert vs and vs[0].code == "E013"
    # 留白不影响正确性，机械补空行会让 diff 嘈杂 => 只报告不自动修
    assert not vs[0].auto_fixable


def test_blank_boundary_counts_heading():
    """题目块右边界要含标题行，否则题型最后一题的留白会少算 1 行（实测假阳性）。"""
    paper = ec.parse_paper(_BLANKS)
    # 第 1 题（选择题）块后紧跟 "### 判断题"：留白应为 2 行，且不得误报
    assert ec.check_blanks(_BLANKS, paper) == []
