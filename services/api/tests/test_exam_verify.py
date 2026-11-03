# -*- coding: utf-8 -*-
"""L1 盲解核验测试：载荷构造、冲突检测、答案回写。

回写（``_rewrite_answer_text``）是字符串手术，边界最多，因此测试最密：
同一行多题、行尾题、裸号答案、跨行主观答案、全角分隔符保留。
每条都对应一次实测踩坑。
"""
from __future__ import annotations

import pytest

from app.services import exam_check as ec


PAPER = """
> 本卷满分 100 分，考试时间 120 分钟，共 6 题。

### 选择题

**1.**（20 分）设 $f_n(x)=x^n+2nx-2$ 的正根为 $a_n$，则 $\\lim_{n\\to\\infty}(1+a_n)^n=$（　　）

A. $1$　　B. $e$　　C. $e^2$　　D. $+\\infty$

**2.**（20 分）设 $y=y(x)$ 由 $x^3+e^{xy}-\\sin3x+y=2$ 确定，则 $f''(0)=$（　　）

A. $-8$　　B. $-4$　　C. $4$　　D. $8$

### 判断题

**3.**（10 分）若 $f$ 在 $x_0$ 处可导，则 $f$ 在 $x_0$ 的某邻域内连续。

<p align="right"><input type="checkbox"> </p>

### 填空题

**4.**（10 分）$\\lim_{x\\to0}(\\cos x)^{\\csc^2x}=$ ______。

### 解答题

**5.**（20 分）证明：当 $x>0$ 时 $\\ln(1+x)<x$。

### 综合题

**6.**（20 分）设 $a_1=\\sqrt2$，$a_{n+1}=\\sqrt{2+a_n}$，求极限。

### 参考答案

**1.** C　**2.** A　**3.** 正确　**4.** $e^{-1/2}$

**5.** 令 $F(x)=x-\\ln(1+x)$，$F'(x)=\\dfrac{x}{1+x}>0$，故 $F(x)>0$。

**6.** 单调有界，极限为 $2$。
"""


def _paper(md: str = PAPER) -> ec.ExamPaper:
    return ec.parse_paper(md)


# ------------------------------------------------------------------ 盲解载荷


def test_payload_excludes_answers():
    """盲解的前提：载荷里绝不能出现参考答案。"""
    payload = ec.build_verification_payload(_paper())
    assert [q["number"] for q in payload] == [1, 2, 3, 4, 5, 6]
    blob = " ".join(str(q) for q in payload)
    assert "参考答案" not in blob
    assert "F'(x)" not in blob          # 第5题答案的步骤不得泄漏
    assert "e^{-1/2}" not in blob       # 第4题答案不得泄漏


def test_payload_keeps_options_and_type():
    """选项属于题干，必须随题面给出；题型也要带上（决定答案形态）。"""
    payload = ec.build_verification_payload(_paper())
    q1 = next(q for q in payload if q["number"] == 1)
    assert q1["type"] == "选择题"
    assert "A. $1$" in q1["question"]
    assert "D. $+\\infty$" in q1["question"]


# ------------------------------------------------------------------ 冲突检测


def _blind(num, *, solved=True, conf="high", option="", text="", my_answer="", defect=""):
    return {
        "number": num, "solved": solved, "confidence": conf,
        "option_match": option, "my_answer_text": text, "my_answer": my_answer,
        "question_defect": defect, "reasoning": "r",
    }


def test_conflict_detected_for_choice():
    """盲解选 B、卷面写 A => 冲突。

    比对在**内容空间**（B→$-4$、A→$-8$），因为同一字母在不同卷可能指向不同内容，
    只比字母会双向出错；字母作为附加字段带上，供仲裁与展示定位。
    """
    conflicts, _ = ec.detect_conflicts(_paper(), [_blind(2, option="B")])
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["number"] == 2
    assert c["answer_category"] == "choice"
    assert c["paper_answer_letter"] == "A" and c["blind_answer_letter"] == "B"
    assert c["paper_answer"] == "-8" and c["blind_answer"] == "-4"


def test_no_conflict_when_blind_agrees():
    """盲解与卷面选同一项 => 内容一致，不报冲突（回归：曾因比对空间不一致而误报）。"""
    conflicts, _ = ec.detect_conflicts(_paper(), [_blind(1, option="C")])
    assert conflicts == []
    # 盲解选 C、卷面也是 C：内容都是 e^2，必须判定为一致
    paper = _paper()
    assert ec.answer_content(paper, 1)[1] == ec._normalize_value(
        ec.parse_options(paper.blocks.get(1) or [])["C"]
    )


def test_no_conflict_when_blind_unsolved_or_low_confidence():
    """盲解自己没把握时不得质疑卷面（否则一片假冲突）。"""
    assert ec.detect_conflicts(_paper(), [_blind(2, solved=False, option="B")])[0] == []
    assert ec.detect_conflicts(_paper(), [_blind(2, conf="low", option="B")])[0] == []


def test_choice_without_matching_option_is_defect_not_conflict():
    """盲解说「没有选项相符」是**题目缺陷**，不是答案冲突。

    实测第二套第1题真值 2√2-2≈0.828，四个选项 0/½/1/2 全错——这类必须报缺陷，
    因为改答案字母没有意义（正确答案根本不在选项里）。
    """
    conflicts, defects = ec.detect_conflicts(
        _paper(), [_blind(1, option="", defect="选项不完备：真值约 0.828，不在 A–D 中")],
    )
    assert conflicts == []
    assert len(defects) == 1 and defects[0]["kind"] == "question_defect"
    assert "不完备" in defects[0]["defect"]


def test_judge_conflict_detected():
    conflicts, _ = ec.detect_conflicts(_paper(), [_blind(3, my_answer="F")])
    assert conflicts and conflicts[0]["paper_answer"] == "T"
    assert conflicts[0]["blind_answer"] == "F"


def test_fill_in_conflict_uses_normalized_text():
    """填空题比归一化后的表达式：e^{-1/2} 与 e^{-0.5} 视为同值。"""
    assert ec.detect_conflicts(_paper(), [_blind(4, text="$e^{-1/2}$")])[0] == []
    conflicts, _ = ec.detect_conflicts(_paper(), [_blind(4, text="$e^{1/2}$")])
    assert conflicts and conflicts[0]["paper_answer"] == "e^{-1/2}"


def test_conflict_for_unknown_number_ignored():
    """模型漏题或串号（给了不存在的题号）不能炸掉流程。"""
    conflicts, _ = ec.detect_conflicts(_paper(), [_blind(99, option="A")])
    assert conflicts == []


# ------------------------------------------------------------------ 答案回写


def test_rewrite_keeps_fullwidth_separators():
    """回归：同一行多题时，替换一题不得吃掉它后面的全角空格。

    实测早期实现把 `**1.** C　**2.** A　**3.** 正确` 改成 `**2.** B**3.** 正确`，
    题号与上一题答案粘连，Markdown 渲染成一坨。
    """
    new, changed = ec._rewrite_answer_text(PAPER, 2, "B")
    assert changed
    assert "**1.** C　**2.** B　**3.** 正确" in new


def test_rewrite_only_touches_target_number():
    new, _ = ec._rewrite_answer_text(PAPER, 2, "B")
    assert "**1.** C" in new and "**3.** 正确" in new and "**4.** $e^{-1/2}$" in new
    # 其它题的答案一字未动
    assert new.count("**2.** B") == 1


def test_rewrite_last_item_in_line():
    """行尾题号：后面没有下一个题号标记，替换到行尾且不留多余空白。"""
    new, changed = ec._rewrite_answer_text(PAPER, 4, "$e^{1/2}$")
    assert changed
    assert "**4.** $e^{1/2}$" in new
    assert not new.rstrip().endswith("　")


def test_rewrite_multiline_subjective_answer():
    """跨行主观答案：只改首行，后续行（步骤）原样保留。"""
    new, changed = ec._rewrite_answer_text(PAPER, 5, "结论：不等式成立。")
    assert changed
    assert "**5.** 结论：不等式成立。" in new
    # 原答案的后续步骤行不应被吞掉（只替换到下一个题号标记前）
    assert "**6.**" in new


def test_rewrite_bare_number_answers():
    """裸号答案行（`1. A。`）也要能改——旧卷子实测存在这种写法。"""
    bare = PAPER.replace("**1.** C　**2.** A　**3.** 正确　**4.** $e^{-1/2}$", "1. A\n2. C")
    new, changed = ec._rewrite_answer_text(bare, 2, "D")
    assert changed
    assert "2. D" in new
    assert "1. A" in new


def test_rewrite_missing_number_is_noop():
    new, changed = ec._rewrite_answer_text(PAPER, 99, "A")
    assert not changed and new == PAPER


def test_rewrite_does_not_touch_question_body():
    """答案回写绝不能改题面：题面里也有 `**2.**` 与 A–D 选项。"""
    new, _ = ec._rewrite_answer_text(PAPER, 2, "B")
    assert "**2.**（20 分）设 $y=y(x)$" in new
    assert "A. $-8$　　B. $-4$" in new


# ------------------------------------------------------------------ 一轮修正的边界


def _verdict(num, verdict="paper_wrong", conf="high", answer="", text="", defect=""):
    return {
        "number": num, "verdict": verdict, "confidence": conf,
        "correct_answer": answer, "correct_answer_text": text,
        "question_defect": defect, "reasoning": "重解得分歧",
    }


def test_fix_applies_high_confidence_objective():
    new, applied, skipped = ec.apply_answer_fixes(
        PAPER, _paper(), [_verdict(2, answer="B")],
    )
    assert len(applied) == 1 and applied[0]["number"] == 2
    assert "**2.** B" in new
    assert skipped == []


def test_fix_skips_low_confidence():
    """仲裁自己没把握时只标记不改写（用户要求只改一次，改错代价更高）。"""
    new, applied, skipped = ec.apply_answer_fixes(
        PAPER, _paper(), [_verdict(2, conf="medium", answer="B")],
    )
    assert applied == [] and len(skipped) == 1
    assert "置信度" in skipped[0]["skip_reason"]
    assert new == PAPER


def test_fix_skips_undecidable_and_broken():
    for verdict in ("undecidable", "question_broken"):
        _new, applied, skipped = ec.apply_answer_fixes(
            PAPER, _paper(), [_verdict(2, verdict=verdict, answer="B")],
        )
        assert applied == [] and skipped and verdict in skipped[0]["skip_reason"]


def test_fix_skips_subjective_questions():
    """解答题/综合题的答案是成段步骤，不做自动改写（避免用摘要覆盖正确步骤）。"""
    new, applied, skipped = ec.apply_answer_fixes(
        PAPER, _paper(), [_verdict(5, answer="新结论")],
    )
    assert applied == [] and len(skipped) == 1
    assert "不做自动改写" in skipped[0]["skip_reason"]
    assert new == PAPER


def test_fix_skips_when_paper_is_right():
    """仲裁判 blind_wrong（卷面对）时不得改写。"""
    new, applied, skipped = ec.apply_answer_fixes(
        PAPER, _paper(), [_verdict(2, verdict="blind_wrong", answer="A")],
    )
    assert applied == [] and skipped
    assert new == PAPER


def test_fix_is_single_round_and_idempotent():
    """「只改一次」：改完再跑同样的 verdict 不得产生第二次改动。"""
    once, applied, _ = ec.apply_answer_fixes(PAPER, _paper(), [_verdict(2, answer="B")])
    assert applied
    twice, applied2, skipped2 = ec.apply_answer_fixes(
        once, _paper(once), [_verdict(2, answer="B")],
    )
    # 第二次时卷面已经是 B，与正确答案一致 => 没有可改的（rewrote to same text）
    assert twice == once
    assert all(not a.get("fixed") for a in applied2) or twice == once


def test_fix_multiple_verdicts_in_one_pass():
    """一轮内可以同时修多题（各自独立回写，互不影响）。"""
    new, applied, _skipped = ec.apply_answer_fixes(
        PAPER, _paper(), [_verdict(1, answer="B"), _verdict(2, answer="D")],
    )
    assert len(applied) == 2
    assert "**1.** B　**2.** D　**3.** 正确" in new
    assert "**4.** $e^{-1/2}$" in new
