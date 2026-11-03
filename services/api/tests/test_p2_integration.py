# -*- coding: utf-8 -*-
"""集成测试：tutorials._apply_exam_quality 把 spec_check（块1）与命题质量回流（块2）接进来。

单元测试证明了 quote_check / practice_check / proposition 各自正确，但没证明它们在
真实管线入口 _apply_exam_quality 里被**正确调用**（scene 分派对不对、材料基准传没传、
reflow 的 db.commit 时序会不会破坏 draft 落库）。这一层必须用真实 db session 验证。
"""
from __future__ import annotations

import pytest

from app.db import Base, engine, SessionLocal
from app.models import LearningGoal, QualityRecord
from app.services import tutorials as tut


@pytest.fixture()
def db_session():
    """独立 db fixture：显式建表，且每个测试用干净 schema。

    不用 conftest 的 client fixture（它建表但会拉起整个 FastAPI app），也不依赖
    陈旧 db 文件里已有的表——那样测试会顺序敏感、跨运行串味（distill 的聚类幂等
    会让第二个测试拿不到新 principle）。这里 create_all 保证表在，测试间互不干扰。
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_goal(db, domain_key="math_logic"):
    g = LearningGoal(title="测试目标", domain_key=domain_key, motivation="m",
                     application_context="a", current_level="新手", time_budget="10h",
                     capability_level="L2", generation_tier="standard")
    db.add(g); db.commit(); db.refresh(g)
    return g


# 阅读规范 content：含一条**虚构引文**（材料里没有），Q001 应报 blocking
READING_CONTENT = {
    "format_spec": {"scene": "reading_guide", "name": "阅读教程规范"},
    "sections": [{
        "title": "第一章 导论",
        "content": [{
            "type": "text", "title": "第一章 导论",
            "body": (
                "### 深度导读\n\n#### 关键句段解读\n\n"
                "##### 句段1（第1章第1节）\n\n"
                "> 这是一段材料里根本不存在的虚构引文。\n\n"
                "解读：blah blah。\n"
            ),
        }],
    }],
}
# 对应的材料原文（不含上面那句引文）
READING_MATERIAL = "第一章 导论\n\n真实材料的正文内容，讲的是别的东西。\n"


def test_spec_check_catches_fabricated_quote(db_session, monkeypatch):
    """阅读规范：虚构引文被 Q001 抓为 blocking，写进 quality_report.spec_check。"""
    goal = _make_goal(db_session)
    # 让 _reading_materials_by_section 拿到我们构造的材料
    monkeypatch.setattr(tut.materials_service, "materials_context",
                        lambda db, gid, **kw: READING_MATERIAL)
    quality = {"checks": [], "issues": [], "passed": True}
    content = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in READING_CONTENT.items()}
    tut._apply_exam_quality(
        db_session, content, quality, goal, "tid", "jid",
        verify_enabled=False, version=1,
    )
    spec = quality.get("spec_check")
    assert spec is not None and spec["kind"] == "quote"
    assert spec["blocking"] >= 1
    codes = {v["code"] for s in spec["sections"] for v in s.get("violations", [])}
    assert "Q001" in codes
    # blocking 违规必须让整体 passed=False，并进 issues
    assert quality["passed"] is False
    assert any("Q001" in i for i in quality["issues"])


def test_practical_scene_dispatches_to_practice_check(db_session):
    """实践规范：分派到 practice_check，代码语法错被 P002 抓为 blocking。"""
    goal = _make_goal(db_session, domain_key="cs_it")
    content = {
        "format_spec": {"scene": "practical_tutorial", "name": "实践性教程规范"},
        "sections": [{
            "title": "第一章 上手", "content": [{
                "type": "text", "title": "", "body": "```python\ndef f(:\n    pass\n```\n",
            }],
        }],
    }
    quality = {"checks": [], "issues": [], "passed": True}
    tut._apply_exam_quality(db_session, content, quality, goal, "tid", "jid",
                            verify_enabled=False, version=1)
    spec = quality.get("spec_check")
    assert spec is not None and spec["kind"] == "practice"
    codes = {v["code"] for s in spec["sections"] for v in s.get("violations", [])}
    assert "P002" in codes
    assert quality["passed"] is False


def test_exam_scene_does_not_double_check(db_session):
    """试卷 scene 由 run_exam_quality 处理，spec_check 不得重复校验（kind=exam 直接返回）。"""
    goal = _make_goal(db_session, domain_key="math_logic")
    content = {"format_spec": {"scene": "exam_paper", "name": "试卷生成规范"}, "sections": []}
    quality = {"checks": [], "issues": [], "passed": True}
    tut._apply_exam_quality(db_session, content, quality, goal, "tid", "jid",
                            verify_enabled=False, version=1)
    # exam scene 不产出 spec_check 块（避免与 exam_check 重复）
    assert quality.get("spec_check") is None


def test_reflow_writes_quality_records_for_cross_conflict(db_session):
    """块2：L0 跨卷 E018 冲突回流成 QualityRecord，供 distill 冷启动。"""
    goal = _make_goal(db_session, domain_key="math_logic")
    # 构造 summary：含一个 E018 跨卷冲突（reflow 只收 E017/E018/DEFECT）
    fake_l0 = {"cross": [{
        "code": "E018", "rule": "", "basis": "", "detail": "同母题不同答案",
        "auto_fixable": False, "fixed": False, "severity": "blocking",
    }], "sections": [], "extra_exercises": None}
    # 直接调 _apply_exam_quality 需要真实 content，这里改测 reflow 本身经管线可达：
    # 用一个空 exam content + monkeypatch run_exam_quality 返回带 E018 的 summary
    from app.services import exam_verify as ev
    orig = ev.run_exam_quality
    ev.run_exam_quality = lambda *a, **k: {"l0": fake_l0, "l1": {"enabled": False}, "cross": fake_l0["cross"]}
    try:
        content = {"format_spec": {"scene": "exam_paper"}, "sections": []}
        quality = {"checks": [], "issues": [], "passed": True}
        tut._apply_exam_quality(db_session, content, quality, goal, "tid_reflow", "jid",
                                verify_enabled=False, version=7)
    finally:
        ev.run_exam_quality = orig
    recs = db_session.query(QualityRecord).filter(
        QualityRecord.tutorial_id == "tid_reflow", QualityRecord.version == 7).all()
    assert len(recs) >= 1
    assert any(r.code == "E018" for r in recs)


def test_reflow_idempotent_on_rerun(db_session):
    """重跑同一 (tutorial,version) 不重复计数（去重键生效）——否则阈值会被同一次错误刷满。"""
    goal = _make_goal(db_session, domain_key="math_logic")
    from app.services import exam_verify as ev
    fake_l0 = {"cross": [{"code": "E018", "detail": "冲突", "severity": "blocking",
                          "rule": "", "basis": "", "auto_fixable": False, "fixed": False}],
               "sections": [], "extra_exercises": None}
    orig = ev.run_exam_quality
    ev.run_exam_quality = lambda *a, **k: {"l0": fake_l0, "l1": {"enabled": False}, "cross": fake_l0["cross"]}
    try:
        for _ in range(2):
            content = {"format_spec": {"scene": "exam_paper"}, "sections": []}
            quality = {"checks": [], "issues": [], "passed": True}
            tut._apply_exam_quality(db_session, content, quality, goal, "tid_idem", "jid",
                                    verify_enabled=False, version=3)
    finally:
        ev.run_exam_quality = orig
    recs = db_session.query(QualityRecord).filter(
        QualityRecord.tutorial_id == "tid_idem", QualityRecord.version == 3).all()
    # 跑两次，E018 仍只应有一条（去重）
    assert len([r for r in recs if r.code == "E018"]) == 1
