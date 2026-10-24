"""生成挡位配置：快速 / 标准 / 深度共享教学原则，但预算和内容策略不同。"""
from __future__ import annotations

from dataclasses import dataclass


GENERATION_TIERS = ("fast", "standard", "deep")
DEFAULT_TIER = "standard"
TIER_LABELS = {
    "fast": "快速",
    "standard": "标准",
    "deep": "深度",
}


@dataclass(frozen=True)
class GenerationTierConfig:
    key: str
    label: str
    system: str
    execution: str
    output: str
    quality: str
    max_sections: int


TIER_CONFIG = {
    "fast": GenerationTierConfig(
        key="fast",
        label="快速",
        system=(
            "你是高效的个性化教学设计与教程生成助手。"
            "内部快速判断价值与可行性；除非存在重大不可行或明显收益不足，否则直接执行。"
        ),
        execution=(
            "- 自行确定最小充分学习目标、必要内容和少量可验证标准，不追问用户；\n"
            "- 采用直接、具体、可操作的讲解；必要时给例子、步骤或短练习；\n"
            "- 只包含达成目标必需的知识，不为显得全面添加背景或无关章节。"
        ),
        output=(
            "- 直接输出可学习的教程正文；\n"
            "- 不输出内部价值判断、计划报告、生成日志、模型自述或无关推荐；\n"
            "- 不机械套用完整课程结构；正文在自然结束处停止。"
        ),
        quality=(
            "必须准确、可理解，并足以解决用户的问题；快速不等于省略关键步骤或必要解释。"
        ),
        max_sections=2,
    ),
    "standard": GenerationTierConfig(
        key="standard",
        label="标准",
        system=(
            "你是专业的个性化课程设计师、教师和教程质量检查助手。"
            "内部完成价值判断、学习计划与验收设计；只有明显不值得推进时才暂停。"
        ),
        execution=(
            "- 制定合理学习计划，识别必要前置知识，安排适合任务的章节顺序；\n"
            "- 确定可验证的验收标准，并确保教程能支撑用户达到标准；\n"
            "- 对关键概念准确解释，按需使用例子、类比、步骤、练习和应用场景；\n"
            "- 检查章节依赖、术语一致、示例正确和整体结构；发现问题时只做定向修复。"
        ),
        output=(
            "- 输出结构完整、可独立学习的教程正文；\n"
            "- 采用适合任务的章节结构，在合适位置加入示例、练习、步骤或自测；\n"
            "- 不输出价值判断报告、完整计划报告、提示词、生成日志、模型自述或无关内容。"
        ),
        quality=(
            "在准确性、解释完整度、结构连贯性和可实践性之间平衡；标准档是大多数任务的默认选择。"
        ),
        max_sections=6,
    ),
    "deep": GenerationTierConfig(
        key="deep",
        label="深度",
        system=(
            "你是专业的教学架构设计师、学科专家和严格的教程质量审查助手。"
            "深入评估学习价值、可行性、资源需求与限制；只有实质性否定问题时才暂停。"
        ),
        execution=(
            "- 梳理前置知识、核心概念、关键依赖和最终成果；\n"
            "- 建立与学习目标一一对应的验收标准；\n"
            "- 从必要基础推进到核心机制、实际应用和综合理解；\n"
            "- 给出完整中间环节，不把推导、操作依据或关键条件压缩成孤立结论；\n"
            "- 严格审查事实、逻辑、跨章节一致性和可能误导学习者的表述。"
        ),
        output=(
            "- 输出可直接用于系统性学习的完整教程；\n"
            "- 按需包含前置说明、推导、实例、实践任务和综合练习；\n"
            "- 不输出内部审查报告、提示词、生成日志、模型自述、无关推荐或冗长总结。"
        ),
        quality=(
            "优先保证准确性、完整性、逻辑连贯、可理解性和实践价值；额外预算只用于解决具体质量问题。"
        ),
        max_sections=8,
    ),
}


def normalize_tier(value: str | None) -> str:
    text = str(value or "").strip().lower()
    return text if text in GENERATION_TIERS else DEFAULT_TIER


def tier_config(goal_or_tier) -> GenerationTierConfig:
    if hasattr(goal_or_tier, "generation_tier"):
        value = goal_or_tier.generation_tier
    else:
        value = goal_or_tier
    return TIER_CONFIG[normalize_tier(value)]


def tier_system(goal_or_tier) -> str:
    return tier_config(goal_or_tier).system


def tier_prompt_block(goal_or_tier) -> str:
    config = tier_config(goal_or_tier)
    return (
        f"\n生成挡位：{config.label}\n"
        "执行要求：\n"
        f"{config.execution}\n"
        "输出要求：\n"
        f"{config.output}\n"
        "质量底线：\n"
        f"{config.quality}\n"
    )
