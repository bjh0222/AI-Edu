# -*- coding: utf-8 -*-
"""context_layers 接入测试：EXPLAIN 对真实 prompt 有效、能抓违例、且真的落库。

必须测「落库」而不是只测函数返回：spec_check 那次就是内部 dict 写入成功、
但 Pydantic response_model 静默丢弃字段，单测一路绿灯而功能半残。
所以这里除了 EXPLAIN 的正确性，还要验证它随 TrainingRecord.context_json 持久化。
"""
from __future__ import annotations

import json

import pytest

from app.llm import prompts
from app.llm.context_layers import analyze_prompt
from app.llm.service import _explain_prompt


# ------------------------------------------------------------------ 真实 prompt

class _Goal:
    title = "线性代数"; motivation = "备考"; application_context = "期末"; current_level = "大二"
    time_budget = "20h"; user_notes = ""; domain_key = "math_logic"; capability_level = "L2"
    generation_tier = "standard"; hard_constraints = "只出试卷，不要讲解"
    format_spec_id = "x"
    format_spec_snapshot = json.dumps({
        "name": "试卷生成规范", "scene": "exam_paper", "content_structure": "# 试卷\n\n### 选择题",
        "format_rules": "- 题号加粗", "required_rules": "- 一节一卷", "forbidden_rules": "- 禁止答案散落",
        "target_reader": "学生", "output_goal": "输出试卷", "acceptance_criteria": "- 题号连续",
        "reference_examples": "✅ 正确", "custom_markdown": "**排版**",
        "suggested_rules": "", "flexible_rules": "", "deliverables": [],
    }, ensure_ascii=False)


class _Discipline:
    display_name = "数学"


def _real_section_prompt(proposition_hints: str = "") -> str:
    item = {"title": "第1章 单元检测卷", "_deliverable": "第1章 单元检测卷",
            "_teaching_plan": {"decisions": ["重讲解"]}}
    _, user = prompts.section(
        _Goal(), _Discipline(), item, [], [], "材料：线性方程组的解法。" * 600,
        None, None, False, proposition_hints,
    )
    return user


def test_explain_recognizes_real_prompt_blocks():
    """对真实 section prompt：大部分字符被识别，未识别的只是骨架行。"""
    user = _real_section_prompt()
    ex = analyze_prompt(user, stage="section")
    assert ex.total_chars == len(user)
    assert len(ex.blocks) >= 4
    # 未识别字符应远小于总量（骨架：学科行、任务说明、输出 schema）
    assert ex.unrecognized_chars < ex.total_chars * 0.15, (
        f"未识别 {ex.unrecognized_chars}/{ex.total_chars}，块标记可能已失效"
    )


def test_explain_finds_key_blocks_with_correct_layers():
    user = _real_section_prompt()
    ex = analyze_prompt(user, stage="section")
    by_title = {b.title: b for b in ex.blocks}
    assert "本次硬性约束" in by_title or "本次内容补充" in by_title
    assert by_title.get("用户上传材料").layer == "materials"
    assert by_title.get("格式规范").layer == "format_spec"
    assert by_title.get("格式规范").dimension == "structure"


def test_explain_no_violation_on_current_layout():
    """现状布局（硬约束→材料→规范→画像）不报违例：顺序与声明的优先级一致。"""
    ex = analyze_prompt(_real_section_prompt(), stage="section")
    assert ex.order_violations == []


def test_explain_detects_same_dimension_inversion():
    """同维度内倒置必须被抓到（材料 content 层跑到了硬约束 content 层之前）。"""
    bad = (
        "学科：数学\n"
        "用户上传的参考资料 / 例题来源（范围约束与依据；文本类文件为原始全文）：\n材料\n"
        "本次硬性约束（用户针对当前目标填写，必须逐条落实）：\n- 只出试卷\n"
    )
    ex = analyze_prompt(bad, stage="section")
    assert len(ex.order_violations) == 1
    assert "hard_constraints" in ex.order_violations[0]


def test_explain_does_not_flag_cross_dimension():
    """跨维度不算冲突：硬约束(content) 与格式规范(structure) 各管一段（ADR-018）。"""
    ok = (
        "本次格式规范（冻结快照，结构、排版和交付物唯一依据）：试卷生成规范\n"
        "本次硬性约束（用户针对当前目标填写，必须逐条落实）：\n- 只出试卷\n"
    )
    assert analyze_prompt(ok, stage="section").order_violations == []


def test_explain_exempts_trailing_restatements():
    """末尾的重申块（重试指令、禁止元栏目）不得被判为顺序违例。

    它们刻意放在 prompt 末尾（末尾重申对抗 lost-in-the-middle），layer 数字小
    但位置靠后是**设计意图**，不是 bug。这条豁免若失效，每次重试生成都会误报。
    """
    ok = (
        "本次硬性约束（用户针对当前目标填写，必须逐条落实）：\n- 只出试卷\n"
        "用户上传的参考资料 / 例题来源（范围约束与依据；文本类文件为原始全文）：\n材料\n"
        "上一稿违反了以下用户硬性约束，本次必须修正后重新输出完整 JSON：\n- 漏了范围\n"
        "禁止元栏目（以下都不是教学内容）：\n- 使用说明\n"
    )
    ex = analyze_prompt(ok, stage="section")
    assert ex.order_violations == []
    titles = [b.title for b in ex.blocks]
    assert "上一稿违规修正" in titles and "禁止元栏目" in titles


def test_explain_locates_proposition_after_materials():
    """命题规律必须排在材料**之后**：CRE 实测中部区域 76% 的错误与填充文本匹配。

    断言的是**相对顺序**而非绝对百分比——位置百分比取决于材料长度（材料越长，
    同一块的位置越靠后），用绝对阈值会让这条测试随材料体量漂移而假失败。
    真正要保证的性质是：命题块不被埋进材料海洋里。
    """
    user = _real_section_prompt(proposition_hints="- 母题重复时应改变提问角度。")
    ex = analyze_prompt(user, stage="section")
    prop = [b for b in ex.blocks if b.layer == "proposition"]
    mats = [b for b in ex.blocks if b.layer == "materials"]
    assert prop, "命题注入块未被识别"
    assert mats, "材料块未被识别（测试前提不成立）"
    assert prop[0].position > mats[0].position, (
        f"命题块 {prop[0].position:.1%} 未排在材料块 {mats[0].position:.1%} 之后"
    )


def test_proposition_stays_in_tail_regardless_of_material_size():
    """材料变大时命题块只会更靠后，不会漂进中部（相对顺序的稳健性）。"""
    small = analyze_prompt(_real_section_prompt("- 规律A。"), stage="section")
    big_material = "材料：线性方程组的解法与秩的讨论，含大量例题与推导。" * 4000
    item = {"title": "第1章 单元检测卷", "_deliverable": "第1章 单元检测卷",
            "_teaching_plan": {"decisions": ["重讲解"]}}
    _, big_user = prompts.section(_Goal(), _Discipline(), item, [], [], big_material,
                                  None, None, False, "- 规律A。")
    big = analyze_prompt(big_user, stage="section")
    for ex in (small, big):
        prop = [b for b in ex.blocks if b.layer == "proposition"]
        mats = [b for b in ex.blocks if b.layer == "materials"]
        assert prop and mats
        assert prop[0].position > mats[0].position


def test_explain_helper_is_compact_and_safe():
    """_explain_prompt 返回可 JSON 序列化的紧凑 dict；异常不抛出。"""
    data = _explain_prompt("本次硬性约束（用户针对当前目标填写，必须逐条落实）：\n- x\n", stage="section")
    json.dumps(data)  # 必须可序列化（要进 context_json）
    assert data["stage"] == "section"
    assert data["blocks"][0]["layer"] == "hard_constraints"
    # 空输入不炸
    assert _explain_prompt("", stage="outline")["total_chars"] == 0


def test_explain_persists_into_training_record(client):
    """**落库验证**：EXPLAIN 必须随 TrainingRecord.context_json 持久化。

    这是本文件最重要的一条——只测函数返回值测不出「写进了 dict 但没落库」，
    spec_check 那次就是这样漏掉的。
    """
    from app.db import SessionLocal
    from app.models import TrainingRecord

    goal = client.post("/api/goals", json={
        "title": "EXPLAIN 落库测试", "domain_key": "math_logic", "motivation": "m",
        "application_context": "a", "current_level": "新手", "time_budget": "10小时",
        "capability_level": "L2", "generation_tier": "fast",
    }).json()
    client.post(f"/api/goals/{goal['id']}/criteria")
    for c in client.get(f"/api/goals/{goal['id']}/criteria").json():
        client.patch(f"/api/criteria/{c['id']}", json={"status": "confirmed"})

    db = SessionLocal()
    try:
        # 演示模式下 _record 仍会写 TrainingRecord（demo=True），EXPLAIN 应一并落库
        from app.llm.service import AIService
        ai = AIService(db, goal_id=goal["id"])
        sysp, userp = prompts.diagnose(
            type("G", (), {"title": "t", "motivation": "m", "application_context": "a",
                           "current_level": "新手", "time_budget": "1h", "user_notes": "",
                           "domain_key": "math_logic", "hard_constraints": "只出试卷",
                           "format_spec_snapshot": "", "capability_level": "L2",
                           "generation_tier": "fast"})(),
            type("D", (), {"display_name": "数学"})(), "",
        )
        ai._record("diagnose", system=sysp, user=userp, output={"recommendation": "推进"},
                   usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                          "usage_source": "estimated"})
        db.commit()
        rec = (db.query(TrainingRecord)
                 .filter(TrainingRecord.feature == "diagnose")
                 .order_by(TrainingRecord.created_at.desc()).first())
        assert rec is not None, "TrainingRecord 未写入"
        ctx = json.loads(rec.context_json or "{}")
        assert "prompt_explain" in ctx, "EXPLAIN 未落库到 context_json"
        assert ctx["prompt_explain"]["total_chars"] > 0
        json.dumps(ctx["prompt_explain"])
    finally:
        db.close()
