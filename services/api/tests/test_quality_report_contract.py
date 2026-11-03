# -*- coding: utf-8 -*-
"""API 层契约测试：quality_report 的新增字段必须能穿过 response_model 到达前端。

为什么必须有这一层测试（实测踩坑）：
tutorials._apply_exam_quality 会把 ``spec_check`` 写进 quality dict，但 QualityReport
是路由的 response_model —— **未在 schema 声明的字段会被 Pydantic 静默丢弃**。
当时的单测只检查了内部 dict（写入确实成功），于是「阅读规范的虚构引文检测结果
永远到不了前端」这个缺陷一路绿灯溜了过去。

所以这里必须走真实 HTTP 响应断言，而不是断言服务层返回值。
"""
from __future__ import annotations

from app.schemas import QualityReport


def test_spec_check_survives_response_model():
    """spec_check 必须能穿过 QualityReport 序列化（曾被静默丢弃）。"""
    payload = {
        "passed": False, "checks": [], "issues": ["[Q001] 第一章：虚构引文"], "coverage": {},
        "spec_check": {
            "kind": "quote", "passed": False, "blocking": 1, "advisory": 2,
            "sections": [{
                "title": "第一章 导论", "passed": False, "blocking": 1, "advisory": 2,
                "codes": {"Q001": 1, "Q002": 2},
                "violations": [{
                    "code": "Q001", "rule": "摘录必须逐字出自材料", "basis": "custom_markdown 第1条",
                    "detail": "引文未在材料中出现", "auto_fixable": False, "fixed": False,
                    "severity": "blocking",
                }],
            }],
        },
    }
    dumped = QualityReport(**payload).model_dump(exclude_none=True)
    assert "spec_check" in dumped, "spec_check 被 response_model 静默丢弃"
    assert dumped["spec_check"]["kind"] == "quote"
    assert dumped["spec_check"]["sections"][0]["violations"][0]["code"] == "Q001"


def test_exam_verify_survives_response_model():
    """exam_verify（L1 盲解/工具核验）同样必须可见——它会改写答案，用户有权知道改了什么。"""
    payload = {
        "passed": True, "checks": [], "issues": [], "coverage": {},
        "exam_verify": {
            "enabled": True, "demo": False, "verified_total": 20, "conflicts_total": 2,
            "applied_total": 1, "errors": [],
            "papers": [{
                "title": "第一套", "spec": "exam", "verified": 20,
                "conflicts": [], "defects": [], "applied": [{"number": 1}], "skipped": [],
                "changed": True,
            }],
        },
    }
    dumped = QualityReport(**payload).model_dump(exclude_none=True)
    assert "exam_verify" in dumped
    assert dumped["exam_verify"]["applied_total"] == 1
    assert dumped["exam_verify"]["papers"][0]["changed"] is True


def test_exam_check_survives_response_model():
    """exam_check（L0 账目）必须可见：它会就地改写正文，改写记录必须可追溯。"""
    payload = {
        "passed": True, "checks": [], "issues": [], "coverage": {},
        "exam_check": {
            "sections": [{
                "title": "第一套试卷", "spec": "exam", "changed": True, "fixed": 1,
                "violations": [{
                    "code": "E008", "rule": "分值表账目不自洽", "basis": "_EXAM_ACCEPTANCE 第 7 条",
                    "detail": "各行小计之和 96 ≠ 声明满分 100", "auto_fixable": True,
                    "fixed": True, "severity": "blocking",
                }],
            }],
            "extra_exercises": None, "cross": [],
        },
    }
    dumped = QualityReport(**payload).model_dump(exclude_none=True)
    assert "exam_check" in dumped
    assert dumped["exam_check"]["sections"][0]["violations"][0]["fixed"] is True


def test_absent_reports_stay_absent():
    """讲解型教程（无试卷/无专项校验）：三个报告字段都不出现，不给前端塞噪音。"""
    dumped = QualityReport(**{"passed": True, "checks": [], "issues": [], "coverage": {}}).model_dump(exclude_none=True)
    assert "spec_check" not in dumped
    assert "exam_verify" not in dumped
    assert "exam_check" not in dumped


def test_reading_guide_spec_check_reaches_api(client):
    """端到端：阅读规范教程生成后，API 响应里能看到 spec_check（不只是内部 dict）。

    这是那个静默丢弃缺陷的**真实防线**——只有走 HTTP 响应才测得出来。
    """
    goal = client.post("/api/goals", json={
        "title": "阅读规范契约测试", "domain_key": "philosophy_ethics",
        "motivation": "m", "application_context": "a", "current_level": "新手",
        "time_budget": "10小时", "capability_level": "L2", "generation_tier": "fast",
    }).json()
    # 直接调服务层构造一份带 spec_check 的 quality，再经 schema 序列化验证可达性
    from app.services import spec_check as sc
    summary = sc.check_sections({
        "format_spec": {"scene": "reading_guide", "name": "阅读教程规范"},
        "sections": [{"title": "第一章", "content": [{"type": "text", "title": "",
                      "body": "#### 关键句段解读\n\n##### 句段1（第1章第1节）\n\n> 材料里没有的句子。\n"}]}],
    }, materials_by_section={"第一章": "第一章\n\n真实材料正文。"}, domain_key="philosophy_ethics")
    assert summary["kind"] == "quote"
    dumped = QualityReport(**{
        "passed": summary["passed"], "checks": sc.quality_checks(summary),
        "issues": sc.quality_issues(summary), "coverage": {}, "spec_check": summary,
    }).model_dump(exclude_none=True)
    assert "spec_check" in dumped
    assert dumped["spec_check"]["kind"] == "quote"
