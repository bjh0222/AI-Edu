# -*- coding: utf-8 -*-
"""上下文装配层：把散落在 prompts.py 里的手写 f-string 拼接，收敛成「层级 × 维度」的结构化装配。

为什么需要它（实测 + 文献双重依据）：

现状是 prompts.py 用 1094 行手写 f-string 把 8 个指令源拼成一个 prompt，优先级只写在
一句散文里（``优先级：本规范 > 旧任务约定 > 长期画像``）。文献证明这靠不住：

- Epistemic Parity（arXiv 2610.33128，1383 次运行）：memory 与 skill 注入同一上下文、
  无定义优先级时，**89% 的运行对矛盾只字未提**（silent adjudication 是默认行为）；
  裁决追随 token 位置而非来源语义；显式「绝对优先」指令仍留 3-10% 残余不遵从。
- PRIME（arXiv 2606.22470）：**冲突类型比模型规模更显著**地影响行为，且不同冲突类别
  有不同失效模式——所以优先级不是一条全序，而是**按维度分**。
- 我们自己的 ADR-018 就是 silent adjudication 实例：模型把「只输出试卷」静默裁决成
  「写一整章讲解」，且一个字都没告诉我们。

本模块做两件事：
1. **层级 × 维度**：优先级不是一条线性层级，而是「内容维度」与「结构维度」各自一条全序
   （这正是 prompts.py 里「内容要求逐条落实；结构排版只能服从规范」已隐含的规则）。
   只有两个块声称**同一维度**的权威时才构成冲突，大幅减少假冲突。
2. **EXPLAIN**：装配结果附带每块的 layer/dimension/chars/dropped，让「实际注入了什么」
   可观测。select_rules 早已返回 dropped 但从未暴露给用户（Tokalator 称之为「隐形预算
   消耗者」）；ADR-018 那类根因若有 EXPLAIN 就能当场看见，而非事后写进 decisions.md 复盘。

本模块是**纯函数 + 数据类**，不调模型、不碰数据库、不 import prompts.py（避免循环导入），
因此可独立单测；prompts.py 后续逐个调用点切换过来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# ---------------------------------------------------------------- 维度与层级

# 两个维度：一条指令要么在管「写什么内容」，要么在管「怎么排版/交付结构」。
# 依据 PRIME「冲突类型比模型规模更显著」——不同类型冲突的裁决规则不同，不能混成一条全序。
#   content   内容维度：范围、题量、覆盖度、难度、事实
#   structure 结构维度：标题、栏目、排版、交付物构成
DIMENSIONS = ("content", "structure")

# 层级：数字越小优先级越高（与 CSS cascade 的 origin 顺序同构）。
# 顺序不是拍脑袋定的，是把项目里已有的、散落的优先级声明收敛成单一事实来源：
#   - system 全局铁律（LaTeX 分隔符、禁 Obsidian 标签等，跨维度生效）
#   - hard_constraints 用户硬约束：在**内容维度**最高（prompts.py:339「内容要求必须逐条落实」），
#     但在**结构维度**被显式忽略（ADR-018「结构排版已由规范接管，不作为格式依据」）
#   - delivery_contract 交付契约：结构维度由代码强制（ADR-018，比规范更高，因为它是代码定的事实）
#   - materials 材料：只提供内容事实，不决定结构
#   - format_spec 格式规范：结构维度的权威（prompts.py「结构、排版和交付物唯一依据」）
#   - proposition 命题规律（P2）：content 维度的软建议，走预算裁剪
#   - profile 教学画像：偏好，最低，可被预算裁剪
LAYERS: tuple[tuple[int, str], ...] = (
    (0, "system"),
    (1, "hard_constraints"),
    (2, "delivery_contract"),
    (3, "materials"),
    (4, "format_spec"),
    (5, "proposition"),
    (6, "profile"),
)

# 每个 layer 默认主张哪个维度的权威（用于冲突判定）。
# system 跨维度；hard_constraints 只在 content 维度是权威（结构维度让位给 format_spec）。
LAYER_DIMENSION: dict[str, str] = {
    "system": "both",
    "hard_constraints": "content",
    "delivery_contract": "structure",
    "materials": "content",
    "format_spec": "structure",
    "proposition": "content",
    "profile": "content",
}

_LAYER_ORDER = {name: idx for idx, name in LAYERS}

# 只有「主张某维度权威」的层才参与冲突检测。
#   system 是无条件全局铁律（LaTeX 分隔符、禁标签），凌驾一切、不存在裁决问题；
#   materials 是事实来源（只提供内容、不主张「该怎么排版/该出什么」的权威）。
# 二者若参与 overlap 检测，system 会因 dimension=both 与**每个**块报冲突（实测噪音），
# 把真正需要披露的冲突（如 ADR-018：硬约束要内容 vs 规范要结构）淹没。
AUTHORITATIVE_LAYERS = frozenset({
    "hard_constraints", "delivery_contract", "format_spec", "proposition", "profile",
})


# ---------------------------------------------------------------- 数据类

@dataclass
class Block:
    """一个待注入的上下文块。

    ``layer`` 决定优先级与拼装顺序；``dimension`` 声明它主张哪个维度的权威
    （None 表示用 LAYER_DIMENSION 的默认值）；``text`` 为空时该块被跳过。
    """

    layer: str
    text: str
    title: str = ""
    dimension: str | None = None       # content / structure / both / None(用默认)
    # 是否参与末尾锚点重复（见 tail_anchor）：关键约束在 prompt 末尾再出现一次，
    # 对抗 lost-in-the-middle。CRE（arXiv 2605.23170）实测：末尾复制一份目标任务，
    # 能把中部准确率拉回末位基线 ±4pp。
    tail_anchor: bool = False

    @property
    def order(self) -> int:
        return _LAYER_ORDER.get(self.layer, 99)

    @property
    def effective_dimension(self) -> str:
        return self.dimension or LAYER_DIMENSION.get(self.layer, "content")

    def __post_init__(self) -> None:
        if self.layer not in _LAYER_ORDER:
            raise ValueError(f"未知层级 {self.layer!r}，可用：{sorted(_LAYER_ORDER, key=_LAYER_ORDER.get)}")
        dim = self.effective_dimension
        if dim not in DIMENSIONS and dim != "both":
            raise ValueError(f"未知维度 {dim!r}，可用：{DIMENSIONS} 或 both")


@dataclass
class BlockRecord:
    """EXPLAIN 输出的一条记录：这一块实际注入了什么。"""

    layer: str
    dimension: str
    title: str
    chars: int
    dropped: bool = False
    drop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "dimension": self.dimension,
            "title": self.title,
            "chars": self.chars,
            "dropped": self.dropped,
            "drop_reason": self.drop_reason,
        }


@dataclass
class Assembled:
    """装配结果：最终 prompt + 可观测的 explain 记录 + 检测到的同维度冲突。"""

    prompt: str
    explain: list[BlockRecord] = field(default_factory=list)
    # 同一维度内，低优先级块声称的权威与高优先级块重叠时记录于此。
    # 不是「一定错了」，而是「这里有两个来源都想管同一维度，模型可能静默裁决」——
    # 交给上层决定是否要求模型在输出里披露（见 prompts 的 conflicts 字段）。
    overlaps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(r.chars for r in self.explain if not r.dropped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_chars": self.total_chars,
            "blocks": [r.to_dict() for r in self.explain],
            "overlaps": self.overlaps,
        }


# ---------------------------------------------------------------- 装配

def _layer_label(block: Block, rank: int, total: int) -> str:
    """块头部注入的层级标记：让模型看到的是「有序分层」，而非需要自行解释的散文声明。

    Epistemic Parity 实测「裁决追随 token 位置而非来源语义」，所以除了排序，还要把
    层级与维度**写进每个块的头部**，把隐式的位置信号变成显式的结构信号。
    """
    dim_cn = {"content": "内容维度", "structure": "结构维度", "both": "跨维度"}[block.effective_dimension]
    name = block.title or block.layer
    return f"[层级 {rank}/{total} · {dim_cn} · {name}]"


def assemble(
    blocks: Iterable[Block],
    *,
    tail_anchors: bool = True,
    include_labels: bool = True,
) -> Assembled:
    """把一组上下文块装配成最终 prompt，同时产出 EXPLAIN 与同维度冲突清单。

    装配规则（每条都有依据，改前先读）：

    1. **按 layer 升序拼接**（system 最先、profile 最后）。这把「优先级」从散文变成
       结构事实：模型看到的是有序分层，而不是一句需要它自己解释的「A > B > C」。
    2. **空块跳过**：text 为空的块不注入，也不进 explain（避免噪音）。
    3. **末尾锚点**（tail_anchors=True 时）：把标了 ``tail_anchor`` 的块在 prompt 末尾
       再追加一份精简标记。依据 CRE（arXiv 2605.23170）的 8K 探针实验——在末尾复制一份
       目标任务，可把中部位置的准确率拉回末位基线 ±4pp；以及 Classifier Context Rot
       （arXiv 2605.12366）的缓解手段「在整个上下文周期性插入提醒」。
       **注意**：只追加一行「提醒」而非整块复制，避免 prompt 膨胀与缓存前缀漂移。
    4. **同维度冲突检测**：只在**同一维度**内、两个不同 layer 的块都非空时记为 overlap。
       跨维度（一个管 content、一个管 structure）不算冲突——这正是「层级×维度」相对
       「线性层级」的价值：ADR-018 那类「硬约束要内容、规范要结构」根本不是冲突。

    本函数是纯函数：不调模型、不碰数据库、不 import prompts.py（避免循环导入）。
    """
    items = [b for b in blocks if b.text and b.text.strip()]
    items.sort(key=lambda b: b.order)
    total = len(items)

    explain: list[BlockRecord] = []
    parts: list[str] = []
    anchor_parts: list[str] = []

    for rank, block in enumerate(items, 1):
        dim = block.effective_dimension
        label = _layer_label(block, rank, total) if include_labels else ""
        head = f"{label}\n" if label else ""
        parts.append(f"{head}{block.text.strip()}")
        explain.append(BlockRecord(
            layer=block.layer, dimension=dim, title=block.title or block.layer,
            chars=len(block.text),
        ))
        if tail_anchors and block.tail_anchor:
            anchor_parts.append(f"（重申 · {block.title or block.layer}）{block.text.strip().splitlines()[0][:60]}")

    prompt = "\n\n".join(parts)
    if anchor_parts:
        prompt += "\n\n" + "\n".join(anchor_parts)
    return Assembled(prompt=prompt, explain=explain, overlaps=_collect_overlaps(items))



def _collect_overlaps(items: Sequence[Block]) -> list[dict[str, Any]]:
    """在所有非空块里，找出「同一维度、不同 layer」的重叠对（= 潜在静默裁决点）。

    跨维度不报：一个块管 content、另一个管 structure 时，它们本就该各管一段，
    不构成需要裁决的冲突（ADR-018 的核心教训）。
    """
    overlaps: list[dict[str, Any]] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a.layer == b.layer:
                continue
            # 只检测「主张权威」的层之间的冲突（见 AUTHORITATIVE_LAYERS 注释）
            if a.layer not in AUTHORITATIVE_LAYERS or b.layer not in AUTHORITATIVE_LAYERS:
                continue
            da, db = a.effective_dimension, b.effective_dimension
            same = (da == db) or da == "both" or db == "both"
            if not same:
                continue
            higher, lower = (a, b) if a.order < b.order else (b, a)
            overlaps.append({
                "dimension": da if da == db else "both",
                "higher": higher.layer, "lower": lower.layer,
                "note": f"{higher.layer} 与 {lower.layer} 在同一维度都声明了内容，模型可能静默裁决",
            })
    return overlaps


# ---------------------------------------------------------------- 反向解析（EXPLAIN）
#
# 为什么需要「反向解析已生成的 prompt」，而不是直接改用 assemble() 拼装：
#
# prompts.py 的现有拼装顺序**碰巧与 layer 升序一致**（hard_constraints → materials →
# format_spec → profile 恰是 layer 1 → 3 → 4 → 6），所以顺序上没有需要修的问题。
# 但直接把它改写成 assemble() 会改变 prompt 的**字节**：现有各块自带 \n 前后缀且紧邻
# 拼接，assemble 用 \n\n 连接，两者不等价。对一个已实测调优过的提示词系统，
# 「等价重写」的风险远大于收益——除非先有 A/B 测量证明改动无害。
#
# 所以这里先接入**观测能力**（EXPLAIN）：反向识别 prompt 里的块边界，回答
# 「这次到底注入了什么、各占多少字符、优先级顺序对不对」。这补的是 agent harness
# 六职责（observation / context / control / action / state / verification）里
# 项目唯一薄弱的一项——此前只知道花了多少 token（ModelCallLog），不知道注入了什么。
# ADR-018 那类故障（条件从句被丢进 forbidden 分支、约束静默失效）若有 EXPLAIN，
# 当场就能看见，不必事后写进 decisions.md 复盘。

# 块边界标记：每个注入块**首行的固定前缀** → (layer, 展示名, 维度)。
# 标记取自 prompts.py 里各块的 return 字面量，逐字对应，不是猜的。
# 新增注入块时必须在这里登记，否则 EXPLAIN 会把它算进「未识别」区域。
BLOCK_MARKERS: tuple[tuple[str, str, str, str], ...] = (
    # (首行前缀, layer, 展示名, 维度)
    ("本次硬性约束（用户针对当前目标填写", "hard_constraints", "本次硬性约束", "content"),
    ("本次任务的内容补充（旧模板规则已停用", "hard_constraints", "本次内容补充", "content"),
    ("本次范围：只覆盖「", "hard_constraints", "本章范围声明", "content"),
    ("本次范围：只导读「", "hard_constraints", "本章范围声明", "content"),
    ("用户上传的参考资料 / 例题来源（范围约束与依据", "materials", "用户上传材料", "content"),
    ("本次格式规范（", "format_spec", "格式规范", "structure"),
    ("长期用户画像（仅注入教学与内容偏好", "profile", "长期用户画像", "content"),
    ("长期教学宪章（用户长期要求", "profile", "长期教学宪章", "content"),
    ("本次教程教学决策（落实到本节的知识组织", "profile", "本次教学决策", "content"),
    ("本次命题可借鉴的已核实经验", "proposition", "命题知识库经验", "content"),
    ("上一稿违反了以下用户硬性约束", "hard_constraints", "上一稿违规修正", "content"),
    ("上一稿因超出单次输出长度上限被截断", "system", "截断压缩要求", "structure"),
    ("任务：本次要交付的是成品「", "delivery_contract", "交付物任务", "structure"),
    ("卷面自检（必须满足", "format_spec", "卷面自检要求", "structure"),
    ("禁止元栏目（", "system", "禁止元栏目", "structure"),
    ("Obsidian 双链使用规则（严格）", "system", "双链使用规则", "structure"),
)


# 参与「位置不变量」判定的层：**只有争夺权威的层**才需要检查顺序。
#
# 刻意排除的三类，每类都有实测理由：
# - ``system``：全局铁律**本来就设计成首尾都出现**（``_NO_META_SECTIONS``、
#   ``WIKILINK_RULE`` 放在 prompt 最末是「末尾重申」，对抗 lost-in-the-middle；
#   ``_truncation_block`` 放最后是因为它是本轮最新的指令）。按 layer 数字判定会误报。
# - ``hard_constraints`` 的重试块（``_retry_violation_block``）：同理，定向修正指令
#   必须在末尾最显眼处，不能因为它是 layer 1 就要求它排在 materials 之前。
# - ``proposition`` / ``profile``：两者都是**软建议**，不存在权威争夺，谁先谁后
#   不改变裁决结果（真正会冲突的 content/structure 权威分别是 hard_constraints 与
#   format_spec）。对软建议检查顺序只会产生噪音。
ORDER_CHECKED_LAYERS = frozenset({"hard_constraints", "materials", "format_spec", "delivery_contract"})

# 这些标题是「同一层的后续重申」，不是该层的首次权威声明，不参与顺序判定。
_RESTATEMENT_TITLES = frozenset({"上一稿违规修正", "截断压缩要求", "禁止元栏目", "双链使用规则"})


@dataclass
class PromptBlock:
    """从已生成 prompt 里反向识别出的一个注入块。"""

    layer: str
    title: str
    dimension: str
    chars: int
    # 在 prompt 中的相对位置（0.0~1.0）。用于验证「位置与声明的优先级一致」这个不变量。
    position: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer, "title": self.title, "dimension": self.dimension,
            "chars": self.chars, "position": round(self.position, 4),
        }


@dataclass
class PromptExplanation:
    """EXPLAIN 结果：这份 prompt 实际注入了什么。"""

    stage: str
    total_chars: int
    blocks: list[PromptBlock] = field(default_factory=list)
    # 未被任何标记识别的字符数（prompt 骨架：学科行、任务说明、输出 schema 等）。
    # 这个值异常增大通常意味着有人加了新注入块却没在 BLOCK_MARKERS 登记。
    unrecognized_chars: int = 0
    # 位置不变量违例：低优先级块出现在高优先级块之前。
    order_violations: list[str] = field(default_factory=list)

    @property
    def recognized_chars(self) -> int:
        return sum(b.chars for b in self.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "total_chars": self.total_chars,
            "recognized_chars": self.recognized_chars,
            "unrecognized_chars": self.unrecognized_chars,
            "blocks": [b.to_dict() for b in self.blocks],
            "order_violations": self.order_violations,
        }


def analyze_prompt(user_prompt: str, *, stage: str = "") -> PromptExplanation:
    """反向解析一份已生成的 user prompt，产出 EXPLAIN。

    做法：逐行扫描，命中 ``BLOCK_MARKERS`` 的前缀就开一个新块，块一直延伸到下一个
    标记（或 prompt 末尾）。因此块边界靠标记切分，不靠空行猜测——空行在各块内部
    本来就大量存在（材料原文、LaTeX、表格），用它切分会把一块拆成十几块。

    位置不变量：同一维度内，块的 layer 必须单调不减（高优先级在前）。违例会被记录
    而不是被修正——EXPLAIN 的职责是**让问题可见**，不是替人决定该怎么排。
    """
    text = str(user_prompt or "")
    total = len(text)
    if not total:
        return PromptExplanation(stage=stage, total_chars=0)

    lines = text.split("\n")
    # 先定位每个标记出现的行号
    hits: list[tuple[int, str, str, str]] = []
    for lineno, line in enumerate(lines):
        stripped = line.lstrip()
        for prefix, layer, title, dim in BLOCK_MARKERS:
            if stripped.startswith(prefix):
                hits.append((lineno, layer, title, dim))
                break   # 一行只归属一个块（取最先匹配的标记）

    blocks: list[PromptBlock] = []
    # 用字符偏移计算 chars 与 position：行号只能定位，字符数才是 EXPLAIN 关心的量
    offsets: list[int] = []
    acc = 0
    for line in lines:
        offsets.append(acc)
        acc += len(line) + 1   # +1 是 \n

    recognized = 0
    for i, (lineno, layer, title, dim) in enumerate(hits):
        start = offsets[lineno]
        end = offsets[hits[i + 1][0]] if i + 1 < len(hits) else total
        size = max(0, end - start)
        recognized += size
        blocks.append(PromptBlock(
            layer=layer, title=title, dimension=dim,
            chars=size, position=start / total,
        ))

    # 位置不变量检查：只看**权威层的首次出现**，同维度内 layer 必须单调不减。
    # 为什么只查首次出现、且只查权威层：见 ORDER_CHECKED_LAYERS 的注释——
    # system 与重试块刻意放末尾（末尾重申），软建议之间无权威争夺，查了全是噪音。
    violations: list[str] = []
    first_seen: dict[str, PromptBlock] = {}
    for b in blocks:
        if b.layer not in ORDER_CHECKED_LAYERS or b.title in _RESTATEMENT_TITLES:
            continue
        first_seen.setdefault(b.layer, b)
    last_order: dict[str, tuple[int, PromptBlock]] = {}
    for layer, b in sorted(first_seen.items(), key=lambda kv: kv[1].position):
        order = _LAYER_ORDER.get(layer, 99)
        for dim, (prev_order, prev_block) in last_order.items():
            if dim != b.dimension:
                continue
            if order < prev_order:
                violations.append(
                    f"{b.dimension} 维度：{b.title}（{layer}, 位置 {b.position:.1%}）"
                    f"出现在优先级更低的 {prev_block.title}（{prev_block.layer}, "
                    f"位置 {prev_block.position:.1%}）之后"
                )
        last_order[b.dimension] = (max(last_order.get(b.dimension, (0, b))[0], order), b)

    return PromptExplanation(
        stage=stage,
        total_chars=total,
        blocks=blocks,
        unrecognized_chars=max(0, total - recognized),
        order_violations=violations,
    )
