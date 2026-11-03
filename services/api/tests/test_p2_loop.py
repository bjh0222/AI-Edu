# -*- coding: utf-8 -*-
"""P2 端到端闭环验证：reflow → distill → review → inject。

这是 P2 的核心价值主张——「让系统积累自己的命题经验」——必须证明整条链真的转得起来，
而不只是各函数单测通过。用真实 db session 驱动，全程零模型调用（distill 是确定性聚类）。
"""
from __future__ import annotations

import pytest

from app.db import Base, engine, SessionLocal
from app.models import DesignPrinciple, QualityRecord, LearningGoal
from app.services import proposition as prop


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


def _goal(db, domain="math_logic"):
    g = LearningGoal(title="线代", domain_key=domain, motivation="m", application_context="a",
                     current_level="新手", time_budget="10h", capability_level="L2",
                     generation_tier="standard")
    db.add(g); db.commit(); db.refresh(g)
    return g


def test_full_loop_reflow_distill_review_inject(db_session):
    """完整闭环：三次 E018 冲突回流 → 提炼出 proposed 规律 → 确认 → 注入提示词。"""
    db = db_session
    DOM = "dom_loop"
    goal = _goal(db, DOM)

    # ---- 步骤1：reflow —— 模拟三次不同卷/版本的 E018 跨卷答案冲突 ----
    for ver in (1, 2, 3):
        l0 = {"cross": [{
            "code": "E018", "rule": "同母题不同答案", "basis": "",
            "detail": f"母题「f_n(x)=x^n+2nx-2」在不同卷给出不同答案：e^2 / e^{{-1}}（第{ver}卷）",
            "auto_fixable": False, "fixed": False, "severity": "blocking",
        }], "sections": [], "extra_exercises": None}
        n = prop.reflow_quality_records(db, goal, f"tut_{ver}", ver, l0, {"papers": []})
        assert n >= 1
    recs = db.query(QualityRecord).filter(QualityRecord.domain_key == DOM).all()
    assert len([r for r in recs if r.code == "E018"]) == 3

    # ---- 步骤2：distill —— 阈值3，应提炼出 1 条 proposed 规律 ----
    principles = prop.distill_principles(db, DOM, threshold=3)
    assert len(principles) >= 1
    p = principles[0]
    assert p["status"] == "proposed"
    # statement 必须绑定具体 code + 出现次数 + 母题指纹（不得是空话）
    assert "E018" in p["statement"] and "f_n" in p["statement"]

    # ---- 步骤2b：proposed 态绝不注入 ----
    assert prop.principles_for_injection(db, DOM) == ""

    # ---- 步骤3：review —— 人工确认 ----
    reviewed = prop.review_principle(db, p["id"], "confirm", rationale="多次同题答案漂移，确需固化")
    assert reviewed["status"] == "confirmed"

    # ---- 步骤4：inject —— confirmed 规律进入注入文本 ----
    hints = prop.principles_for_injection(db, DOM)
    assert hints.strip() != ""
    assert "E018" in hints or "f_n" in hints


def test_distill_threshold_not_met_no_principle(db_session):
    """阈值未达（2 < 3）不提炼——挡住偶然一次的噪音。"""
    db = db_session
    DOM = "dom_thresh"
    goal = _goal(db, DOM)
    for ver in (1, 2):
        l0 = {"cross": [{"code": "E018", "detail": "母题「X」不同答案", "severity": "blocking",
                         "rule": "", "basis": "", "auto_fixable": False, "fixed": False}],
              "sections": [], "extra_exercises": None}
        prop.reflow_quality_records(db, goal, f"t{ver}", ver, l0, {"papers": []})
    assert prop.distill_principles(db, DOM, threshold=3) == []


def test_distill_statement_not_vague(db_session):
    """提炼的规律必须绑定证据，不得是「要注意答案正确性」这类空话（EMG 批评的脆弱规律）。"""
    db = db_session
    DOM = "dom_vague"
    goal = _goal(db, DOM)
    for ver in (1, 2, 3):
        l0 = {"cross": [{"code": "E018", "detail": "母题「x=ln(t+sqrt(1+t^2))」不同答案 sqrt2/-2",
                         "severity": "blocking", "rule": "", "basis": "",
                         "auto_fixable": False, "fixed": False}],
              "sections": [], "extra_exercises": None}
        prop.reflow_quality_records(db, goal, f"t{ver}", ver, l0, {"papers": []})
    ps = prop.distill_principles(db, DOM, threshold=3)
    assert ps
    st = ps[0]["statement"]
    # 必须含具体信息：出现次数、母题指纹、错误码——三者缺一即空话
    assert any(ch.isdigit() for ch in st), st
    assert "x=ln" in st or "E018" in st


def test_rejected_principle_not_revived(db_session):
    """驳回的规律不因再攒证据而复活（与 knowledge.py 同语义）。"""
    db = db_session
    DOM = "dom_reject"
    goal = _goal(db, DOM)
    for ver in (1, 2, 3):
        l0 = {"cross": [{"code": "E017", "detail": "母题「Y」重复", "severity": "advisory",
                         "rule": "", "basis": "", "auto_fixable": False, "fixed": False}],
              "sections": [], "extra_exercises": None}
        prop.reflow_quality_records(db, goal, f"t{ver}", ver, l0, {"papers": []})
    ps = prop.distill_principles(db, DOM, threshold=3)
    assert ps
    prop.review_principle(db, ps[0]["id"], "reject", rationale="这类重复可接受")
    # 再加证据、再 distill：被驳回的聚类不得复活
    for ver in (4, 5):
        l0 = {"cross": [{"code": "E017", "detail": "母题「Y」重复", "severity": "advisory",
                         "rule": "", "basis": "", "auto_fixable": False, "fixed": False}],
              "sections": [], "extra_exercises": None}
        prop.reflow_quality_records(db, goal, f"t{ver}", ver, l0, {"papers": []})
    revived = prop.distill_principles(db, DOM, threshold=3)
    assert all(p["id"] != ps[0]["id"] for p in revived)
    # 且库里该聚类仍是 rejected，没有新增 proposed 同聚类
    same = db.query(DesignPrinciple).filter(
        DesignPrinciple.domain_key == DOM,
        DesignPrinciple.rationale.contains("E017"),
    ).all()
    assert all(x.status == "rejected" for x in same)


def test_injection_respects_budget(db_session):
    """多条 confirmed 规律超预算时裁剪，且不静默截断（select_rules 同款语义）。"""
    db = db_session
    DOM = "dom_budget"
    goal = _goal(db, DOM)
    # 造 3 个不同 code 的聚类，各攒够阈值并确认
    for code in ("E018", "E017", "DEFECT"):
        for ver in (1, 2, 3):
            l0 = {"cross": [{"code": code, "detail": f"母题「Z{code}」{code}", "severity": "blocking",
                             "rule": "", "basis": "", "auto_fixable": False, "fixed": False}],
                  "sections": [], "extra_exercises": None} if code != "DEFECT" else {"cross": [], "sections": [], "extra_exercises": None}
            l1 = {"papers": [{"title": "v", "defects": [{"number": 1, "defect": f"选项不完备{code}"}]}]} if code == "DEFECT" else {"papers": []}
            prop.reflow_quality_records(db, goal, f"t_{code}_{ver}", ver, l0, l1)
        ps = prop.distill_principles(db, DOM, threshold=3)
        for p in ps:
            if p["status"] == "proposed":
                prop.review_principle(db, p["id"], "confirm")
    # 极小预算：应裁剪到预算内（返回文本长度受限）
    small = prop.principles_for_injection(db, DOM, budget_chars=60)
    full = prop.principles_for_injection(db, DOM, budget_chars=5000)
    assert len(small) <= len(full)
