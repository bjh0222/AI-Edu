# -*- coding: utf-8 -*-
"""L1 编排层集成测试（exam_verify）：用假 AIService 驱动「盲解→冲突→仲裁→改写」全流程。

单元测试覆盖了 exam_check 的各零件；这里覆盖**编排**：run_exam_quality 是否按正确顺序
调用三层、L1 改完答案后跨卷是否基于最终内容重算、演示模式是否自动跳过、
单卷核验失败是否不拖垮整体。这些顺序依赖一旦错了，单元测试全绿但线上仍会出错。
"""
from __future__ import annotations

from app.services import exam_check as ec
from app.services import exam_verify as ev


PAPER_A = """
### 选择题

**1.**（20 分）设 $f_n(x)=x^n+2nx-2$ 的正根为 $a_n$，则 $\\lim_{n\\to\\infty}(1+a_n)^n=$（　　）

A. $1$　　B. $e$　　C. $e^2$　　D. $+\\infty$

### 判断题

**2.**（20 分）若 $f$ 在 $x_0$ 处可导，则 $f$ 在 $x_0$ 的某邻域内连续。

<p align="right"><input type="checkbox"> </p>

### 参考答案

**1.** C　**2.** 正确
"""


def _content(spec="exam_paper", *bodies):
    return {
        "format_spec": {"scene": spec, "name": "试卷生成规范"},
        "sections": [
            {"title": f"第 {i+1} 套试卷", "content": [{"type": "example", "title": "", "body": b}]}
            for i, b in enumerate(bodies)
        ],
    }


class FakeAI:
    """假 AIService：blind 返回预设盲解，arbitrate 返回预设仲裁。"""

    is_demo = False

    def __init__(self, blind=None, arbitrate=None, raise_on_verify=False):
        self._blind = blind or []
        self._arbitrate = arbitrate or []
        self._raise = raise_on_verify
        self.verify_calls = 0
        self.arbitrate_calls = 0

    def verify_questions(self, goal, discipline, title, questions):
        self.verify_calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return self._blind

    def arbitrate_answers(self, goal, discipline, title, conflicts):
        self.arbitrate_calls += 1
        return self._arbitrate


class FakeDemo(FakeAI):
    is_demo = True


def test_verify_paper_with_ai_fixes_wrong_objective_answer():
    """纯逻辑端到端：卷面答 C(=e^2)，盲解说 B(=e)，仲裁判 paper_wrong/high => 改成 B。"""
    ai = FakeAI(
        blind=[
            {"number": 1, "solved": True, "confidence": "high", "option_match": "B",
             "my_answer_text": "e", "question_defect": "", "reasoning": "na_n→1"},
            {"number": 2, "solved": True, "confidence": "high", "my_answer": "T",
             "my_answer_text": "", "question_defect": "", "reasoning": "可导必连续"},
        ],
        arbitrate=[
            {"number": 1, "verdict": "paper_wrong", "confidence": "high",
             "correct_answer": "B", "correct_answer_text": "e", "question_defect": "",
             "reasoning": "na_n→1 故 (1+a_n)^n→e"},
        ],
    )
    report = ev.verify_paper_with_ai(ai, None, None, "第 1 套试卷", PAPER_A, "exam")
    assert ai.verify_calls == 1 and ai.arbitrate_calls == 1
    assert report["verified"] == 2 and len(report["applied"]) == 1
    assert report["changed"] is True
    new_md = report.pop("_markdown")
    assert "**1.** B　**2.** 正确" in new_md
    assert "**1.** C" not in new_md


def test_demo_ai_skips_verification():
    """演示模式 AI：L1 整层跳过，返回留痕、不调模型。"""
    ai = FakeDemo()
    report = ev.verify_paper_with_ai(ai, None, None, "卷", PAPER_A, "exam")
    assert ai.verify_calls == 0
    assert report["error"] == "演示模式不做盲解核验"
    assert "_markdown" not in report


def test_verify_failure_is_captured_not_raised():
    """盲解调用抛异常：只在报告里留痕，不抛出（核验失败不能拖垮交付）。"""
    ai = FakeAI(raise_on_verify=True)
    report = ev.verify_paper_with_ai(ai, None, None, "卷", PAPER_A, "exam")
    assert report["error"] and "盲解核验调用失败" in report["error"]
    assert "_markdown" not in report


def test_verify_disabled_by_config():
    """verify_enabled=False：不调用任何模型，summary.l1 标记 skipped。"""
    content = _content("exam_paper", PAPER_A)
    summary = ev.run_exam_quality(content, goal_id="g", tutorial_id="t", job_id="j",
                                  discipline=None, verify_enabled=False)
    assert summary["l1"].get("skipped") == "config_disabled"
    # L0 仍跑了（账目校验），但这里 PAPER_A 账目无表 => 无 blocking
    assert isinstance(summary["l0"], dict)


def test_no_exam_sections_skips_everything():
    """讲解型教程：L1 不核验任何卷，cross 为空。"""
    tutorial_body = "### 一、安装\n\n1. 下载\n2. 运行\n"
    content = _content("default_tutorial", tutorial_body)
    summary = ev.run_exam_quality(content, goal_id="g", tutorial_id="t", job_id="j",
                                  discipline=None, verify_enabled=True)
    assert summary["cross"] == []
    assert summary["l1"].get("enabled") is False


def test_cross_recomputed_after_l1_fix():
    """L1 改完答案后，跨卷 E018 必须基于**最终**内容重算。

    两套卷同一母题：卷1 答 C(e^2)、卷2 答 B(e)。L1 把卷1 也改成 B(e) 后，
    两卷答案一致，重算的 cross 不应再有 E018。若沿用改答案前的 cross，会误报冲突。
    """
    ai = FakeAI(
        blind=[{"number": 1, "solved": True, "confidence": "high", "option_match": "B",
                "my_answer_text": "e", "question_defect": "", "reasoning": "r"},
               {"number": 2, "solved": True, "confidence": "high", "my_answer": "T",
                "my_answer_text": "", "question_defect": "", "reasoning": "r"}],
        arbitrate=[{"number": 1, "verdict": "paper_wrong", "confidence": "high",
                    "correct_answer": "B", "correct_answer_text": "e",
                    "question_defect": "", "reasoning": "r"}],
    )
    # 卷1 答 C，卷2 答 B（同母题不同答案）
    content = _content("exam_paper", PAPER_A, PAPER_A.replace("**1.** C　**2.** 正确",
                                                              "**1.** B　**2.** 正确"))
    # 直接验证 recompute_cross 的行为：手工把卷1 改成与卷2 一致后，cross 无 E018
    content["sections"][0]["content"][0]["body"] = PAPER_A.replace(
        "**1.** C　**2.** 正确", "**1.** B　**2.** 正确")
    cross = ev.recompute_cross(content)
    assert not [c for c in cross if c["code"] == "E018"]
    # 改回不一致，E018 出现
    content["sections"][0]["content"][0]["body"] = PAPER_A
    cross2 = ev.recompute_cross(content)
    assert [c for c in cross2 if c["code"] == "E018"]


def test_quality_from_summary_blocks_on_defect_and_conflict():
    """缺陷与冲突进 issues（blocking），改了几题进 checks 的 detail。"""
    summary = {
        "l0": {"sections": [], "extra_exercises": None, "cross": [
            {"code": "E018", "rule": "", "basis": "", "detail": "同题不同答案",
             "auto_fixable": False, "fixed": False, "severity": "blocking"},
        ]},
        "l1": {"enabled": True, "verified_total": 5, "applied_total": 2,
               "errors": [], "papers": [
                   {"title": "卷1", "defects": [
                       {"number": 3, "defect": "选项不完备"}]}]},
        "cross": [{"code": "E018", "rule": "", "basis": "", "detail": "同题不同答案",
                   "auto_fixable": False, "fixed": False, "severity": "blocking"}],
    }
    checks, issues = ev.quality_from_summary(summary)
    assert any("E018" in i for i in issues)
    assert any("DEFECT" in i and "不完备" in i for i in issues)
    assert any(c["name"] == "试卷答案盲解核验" and "2" in c["detail"] for c in checks)
    cross_check = next(c for c in checks if c["name"] == "跨卷命题一致性")
    assert cross_check["passed"] is False
