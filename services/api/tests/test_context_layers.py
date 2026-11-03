# -*- coding: utf-8 -*-
"""context_layers 单元测试：装配顺序、维度冲突检测、末尾锚点、EXPLAIN、位置不变量。

本模块是「层级 × 维度」上下文装配层（架构调研 Phase 3）。它已就绪但尚未接入
prompts.py 的 8 个调用点——全面接入需先用 A/B 测量确认「规范块前移换缓存」不会
降低遵从度（Lost-in-the-Middle 与缓存优化方向相反）。这些测试保证：接入前它就是
正确的，接入时不会引入装配层自身的 bug。
"""
from __future__ import annotations

import pytest

from app.llm.context_layers import (
    AUTHORITATIVE_LAYERS, DIMENSIONS, LAYERS, Assembled, Block, assemble,
)


def _b(layer, text, **kw):
    return Block(layer, text, **kw)


# ------------------------------------------------------------------ 装配顺序

def test_assemble_sorts_by_layer():
    """块按 layer 升序拼接，与传入顺序无关（把优先级从散文变成结构事实）。"""
    a = assemble([
        _b("profile", "画像偏好"),
        _b("system", "全局铁律"),
        _b("format_spec", "格式规范"),
    ])
    order = [r.layer for r in a.explain]
    assert order == ["system", "format_spec", "profile"]
    # prompt 里也是这个顺序
    assert a.prompt.index("全局铁律") < a.prompt.index("格式规范") < a.prompt.index("画像偏好")


def test_empty_blocks_skipped():
    """空块不注入、不进 explain（避免噪音）。"""
    a = assemble([_b("system", "铁律"), _b("materials", ""), _b("profile", "   ")])
    assert [r.layer for r in a.explain] == ["system"]


def test_unknown_layer_rejected():
    with pytest.raises(ValueError):
        _b("nonexistent_layer", "x")


def test_unknown_dimension_rejected():
    with pytest.raises(ValueError):
        _b("system", "x", dimension="bogus")


# ------------------------------------------------------------------ 标签与锚点

def test_labels_injected_with_rank_and_dimension():
    a = assemble([_b("format_spec", "规范内容", title="格式规范")])
    assert "[层级 1/1 · 结构维度 · 格式规范]" in a.prompt


def test_labels_can_be_disabled():
    a = assemble([_b("format_spec", "规范内容")], include_labels=False)
    assert "[层级" not in a.prompt
    assert "规范内容" in a.prompt


def test_tail_anchor_appended_at_end():
    """标记 tail_anchor 的块在末尾追加一行重申（对抗 lost-in-the-middle）。"""
    a = assemble([
        _b("system", "LaTeX 只用 $...$", tail_anchor=True),
        _b("materials", "很长的材料" * 100),
        _b("format_spec", "排版规范"),
    ])
    # 锚点在 prompt 最末尾
    assert a.prompt.rstrip().endswith("LaTeX 只用 $...$")
    # 锚点是「重申」形式，且只取首行前 60 字（不整块复制，避免膨胀与缓存漂移）
    assert "（重申 ·" in a.prompt


def test_tail_anchor_disabled():
    a = assemble([_b("system", "铁律", tail_anchor=True)], tail_anchors=False)
    assert "重申" not in a.prompt


# ------------------------------------------------------------------ 维度冲突检测

def test_same_dimension_overlap_detected():
    """同维度、不同 layer 都非空 → 记为潜在静默裁决点。"""
    a = assemble([_b("hard_constraints", "只出试卷"), _b("profile", "多讲原理")])
    # 两者都主张 content 维度
    assert any(o["higher"] == "hard_constraints" and o["lower"] == "profile"
               for o in a.overlaps)


def test_cross_dimension_no_overlap():
    """跨维度（content vs structure）不算冲突——这是「层级×维度」相对线性层级的价值。

    ADR-018 的核心教训：硬约束要「内容」、规范要「结构」，本就该各管一段，
    不是需要裁决的冲突。
    """
    a = assemble([_b("hard_constraints", "只出试卷"), _b("format_spec", "排版按规范")])
    # hard_constraints=content, format_spec=structure → 无 overlap
    assert not any(o["higher"] == "hard_constraints" and o["lower"] == "format_spec"
                   for o in a.overlaps)


def test_system_and_materials_not_authoritative():
    """system（全局铁律）与 materials（事实来源）不参与冲突检测。

    否则 system 的 dimension=both 会与**每个**块报 overlap，把真正的冲突信号淹没
    （这是实测踩过的噪音）。
    """
    a = assemble([
        _b("system", "铁律"),
        _b("materials", "材料原文"),
        _b("profile", "偏好"),
    ])
    layers_in_overlaps = {o["higher"] for o in a.overlaps} | {o["lower"] for o in a.overlaps}
    assert "system" not in layers_in_overlaps
    assert "materials" not in layers_in_overlaps


def test_authoritative_layers_set():
    assert "hard_constraints" in AUTHORITATIVE_LAYERS
    assert "format_spec" in AUTHORITATIVE_LAYERS
    assert "system" not in AUTHORITATIVE_LAYERS
    assert "materials" not in AUTHORITATIVE_LAYERS


# ------------------------------------------------------------------ EXPLAIN

def test_explain_records_chars_and_layers():
    a = assemble([_b("system", "12345"), _b("profile", "abc")])
    by_layer = {r.layer: r for r in a.explain}
    assert by_layer["system"].chars == 5
    assert by_layer["profile"].chars == 3
    assert a.total_chars == 8


def test_explain_to_dict_shape():
    a = assemble([_b("system", "x", title="系统")])
    d = a.to_dict()
    assert d["total_chars"] == 1
    assert d["blocks"][0]["layer"] == "system"
    assert d["blocks"][0]["dimension"] == "both"
    assert "overlaps" in d


def test_position_invariant_hard_constraints_before_profile():
    """位置不变量：用户硬约束必须排在画像偏好之前（与声明的优先级一致）。

    实测当前 prompts.py 布局中硬约束在 0.7%、画像在 98.5%——位置顺序恰好与优先级
    一致。这个不变量把它固化，防止将来改拼装顺序时无意打破（Epistemic Parity 证明
    位置会影响模型裁决）。
    """
    a = assemble([_b("profile", "偏好"), _b("hard_constraints", "硬约束")])
    layers = [r.layer for r in a.explain]
    assert layers.index("hard_constraints") < layers.index("profile")


def test_all_dimensions_valid():
    for _, name in LAYERS:
        blk = _b(name, "x")
        assert blk.effective_dimension in DIMENSIONS or blk.effective_dimension == "both"
