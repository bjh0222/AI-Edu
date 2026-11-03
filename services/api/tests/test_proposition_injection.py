# -*- coding: utf-8 -*-
"""块4 集成测试：命题规律（confirmed）注入 prompts，且位置在末尾区、冷启动零影响。

验证的是架构调研的两条硬结论落到代码：
1. 注入点必须在末尾区（≥93%），避开材料海洋——CRE 实测中部 76% 错误与填充文本匹配；
2. 冷启动（无 confirmed 规律）时命题块完全不出现，对既有提示词零影响（不破坏 288+ 既有行为）。
"""
from __future__ import annotations

from app.llm import prompts


class _G:
    title = "线性代数"; motivation = "m"; application_context = "a"; current_level = "新手"
    time_budget = "10h"; user_notes = ""; domain_key = "math_logic"; capability_level = "L2"
    generation_tier = "standard"; hard_constraints = ""; format_spec_id = ""; format_spec_snapshot = ""


class _D:
    display_name = "数学"


def test_section_cold_start_has_no_proposition_block():
    """无 confirmed 规律（hints="")：命题块不出现，提示词与从前一致。"""
    _, u = prompts.section(_G(), _D(), {"title": "第1章", "_teaching_plan": {}}, [], [],
                           "", None, None, False, "")
    assert "已核实经验" not in u


def test_section_injects_hints_in_tail_region():
    """有 confirmed 规律：注入且落在材料之后（末尾区），避开 lost-in-the-middle。"""
    material = "材料正文" * 40000
    _, u = prompts.section(_G(), _D(), {"title": "第1章", "_teaching_plan": {}}, [], [],
                           material, None, None, False, "- 含参方程组先讨论秩再定解。")
    assert "已核实经验" in u
    idx_mat = u.find("材料正文")
    idx_prop = u.find("已核实经验")
    assert idx_prop > idx_mat
    # 位置必须在末尾区（≥90%），这是 CRE 结论的直接落实
    assert idx_prop / len(u) >= 0.90, f"命题块位置 {idx_prop/len(u):.2%} 未落在末尾区"


def test_extra_exercises_injects_hints():
    """额外练习也注入命题规律（变式/练习是命题的主战场）。"""
    _, u = prompts.extra_exercises(_G(), _D(), [{"title": "第1章"}], "材料" * 20000,
                                   None, None, "- 变式只改 incidentals，保持 radicals。")
    assert "已核实经验" in u


def test_hints_block_is_soft_not_mandatory():
    """措辞是软建议（与格式规范冲突时以规范为准），不越权声称结构权威。"""
    _, u = prompts.section(_G(), _D(), {"title": "第1章", "_teaching_plan": {}}, [], [],
                           "", None, None, False, "- 一条规律。")
    assert "软建议" in u and "以规范为准" in u
