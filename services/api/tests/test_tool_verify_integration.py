# -*- coding: utf-8 -*-
"""块3 集成测试：工具验证（sympy）优先于盲解，并驱动答案改写。

这是 exam_verify._tool_verify_paper + tool_verify 全链路的验证。现有 FakeAI 测试因
domain 非数学、无 transcribe_for_tools 而**短路了工具验证路径**，所以必须专门测：
1. 数学卷走 sympy 工具验证，refuted 的客观题答案被自动改对；
2. 工具已判定的题**不再走盲解**（省一次模型往返，且工具是确定性、更可信）；
3. 工具判不了（undecidable）的题回落到盲解；
4. 非数学学科（化学/生物）不做工具转写，直接盲解。
"""
from __future__ import annotations

import pytest

from app.services import exam_check as ec
from app.services import exam_verify as ev


# 一份数学卷：第1题答案错（真值 e^{-1/2}，卷面写 e^{1/2}），第2题答案对
MATH_PAPER = """
> 本卷满分 100 分，考试时间 120 分钟，共 2 题。

### 填空题

**1.**（50 分）$\\displaystyle\\lim_{x\\to0}(\\cos x)^{\\csc^2 x}=$ ______。

**2.**（50 分）$\\dfrac{d^5}{dx^5}\\arcsin x\\big|_{x=0}=$ ______。

### 参考答案

**1.** $e^{1/2}$

**2.** $9$
"""


class FakeToolAI:
    """假 AIService：transcribe 返回真实 sympy 代码；verify_questions 记录被调用的题号。"""

    is_demo = False

    def __init__(self, transcriptions=None):
        self._transcriptions = transcriptions or {}
        self.blind_called_for = []      # 记录盲解被问了哪些题号
        self.arbitrate_called = 0
        self.transcribe_calls = 0

    def transcribe_for_tools(self, goal, discipline, title, items):
        self.transcribe_calls += 1
        return {it["number"]: self._transcriptions[it["number"]]
                for it in items if it["number"] in self._transcriptions}

    def verify_questions(self, goal, discipline, title, questions):
        self.blind_called_for.extend(q["number"] for q in questions)
        # 盲解：认为都跟卷面一致（不产生冲突），聚焦验证「工具已判定的题不进盲解」
        return [{"number": q["number"], "solved": True, "confidence": "high",
                 "my_answer_text": "同卷面", "my_answer": "", "option_match": "",
                 "question_defect": "", "reasoning": "r"} for q in questions]

    def arbitrate_answers(self, goal, discipline, title, conflicts):
        self.arbitrate_called += 1
        return []


class FakeGoal:
    def __init__(self, domain_key):
        self.domain_key = domain_key
        self.id = "g1"
        self.title = "t"


# 真实 sympy 断言代码（判定权在 sympy，不在模型）
TRANS_W1 = "RESULT = limit((cos(x))**(1/sin(x)**2), x, 0)"      # 真值 exp(-1/2)
TRANS_W2 = "RESULT = diff(asin(x), x, 5).subs(x, 0)"            # 真值 9


def test_math_paper_tool_refutes_and_fixes_wrong_answer():
    """第1题卷面答 e^{1/2}，sympy 算出 e^{-1/2} → refuted → 自动改对。"""
    ai = FakeToolAI({1: TRANS_W1, 2: TRANS_W2})
    report = ev.verify_paper_with_ai(ai, FakeGoal("math_data"), None, "数学卷", MATH_PAPER, "exam")
    assert ai.transcribe_calls == 1
    assert report.get("tool_verified") == 2
    assert report.get("tool_refuted") >= 1
    assert report["changed"] is True
    new_md = report.pop("_markdown")
    # 第1题被改成 sympy 算出的真值（e^{-1/2} 的某种 LaTeX/sympy 形态），不再是 e^{1/2}
    assert "$e^{1/2}$" not in new_md
    # 第2题答案对，保持不变
    assert "**2.** $9$" in new_md


def test_tool_settled_questions_skip_blind_solve():
    """工具已判定（confirmed/refuted）的题不再进盲解——省一次往返且工具更可信。"""
    ai = FakeToolAI({1: TRANS_W1, 2: TRANS_W2})
    ev.verify_paper_with_ai(ai, FakeGoal("math_data"), None, "数学卷", MATH_PAPER, "exam")
    # 两题都被 sympy 判定，盲解不应被调用（残差为空）
    assert ai.blind_called_for == []


def test_tool_undecidable_falls_back_to_blind():
    """工具判不了的题（转写返回 UNFORMALIZABLE）回落盲解。"""
    # 只转写第1题；第2题不转写 → 工具判不了 → 进盲解残差
    ai = FakeToolAI({1: TRANS_W1})
    report = ev.verify_paper_with_ai(ai, FakeGoal("math_data"), None, "数学卷", MATH_PAPER, "exam")
    assert 2 in ai.blind_called_for
    assert 1 not in ai.blind_called_for   # 第1题被工具判定，不进盲解


def test_non_math_domain_skips_tool_verification():
    """化学（symbolic_partial）/ 生物（none）不做 sympy 转写，直接盲解。"""
    for domain in ("chemistry_materials", "biology_life", "computer_cli"):
        ai = FakeToolAI({1: TRANS_W1, 2: TRANS_W2})
        ev.verify_paper_with_ai(ai, FakeGoal(domain), None, "卷", MATH_PAPER, "exam")
        assert ai.transcribe_calls == 0, f"{domain} 不应触发 sympy 转写"
        # 全部题目走盲解
        assert set(ai.blind_called_for) == {1, 2}


def test_unknown_domain_does_not_run_tool():
    """未知/空学科不得触发工具验证（resolve_capability 只认真实存在的 key）。"""
    ai = FakeToolAI({1: TRANS_W1})
    ev.verify_paper_with_ai(ai, FakeGoal(""), None, "卷", MATH_PAPER, "exam")
    assert ai.transcribe_calls == 0


def test_tool_confirm_keeps_correct_answer_unchanged():
    """工具 confirmed 的题：卷面答案正确，不改写。"""
    # 两题都转写成真值断言，且卷面答案本就对（构造一份答案正确的卷）
    correct_paper = MATH_PAPER.replace("$e^{1/2}$", "$e^{-1/2}$")
    ai = FakeToolAI({1: TRANS_W1, 2: TRANS_W2})
    report = ev.verify_paper_with_ai(ai, FakeGoal("math_data"), None, "卷", correct_paper, "exam")
    assert report.get("tool_refuted") == 0
    # 无改写（答案本就对）
    new_md = report.pop("_markdown", None)
    if new_md is not None:
        assert "$e^{-1/2}$" in new_md
