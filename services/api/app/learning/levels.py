"""能力层级（L1/L2/L3）：定义、标签与提示词注入文本。

层级决定教程的讲解深度、练习设计与验收难度，而不只是描述文字。
每个层级都必须保证理解核心概念所必需的知识解释完整；层级之间的差异
体现在学习成果（能做什么）上，而不是简单增减字数。
"""
from __future__ import annotations

# 默认层级：现有目标没有该字段时回退到 L2（独立应用）
DEFAULT_LEVEL = "L2"
VALID_LEVELS = ("L1", "L2", "L3")


def normalize_level(level: str | None) -> str:
    """非法 / 缺失层级回退默认值，避免模型或旧数据把层级写坏。"""
    value = (level or "").strip().upper()
    return value if value in VALID_LEVELS else DEFAULT_LEVEL


CAPABILITY_LEVELS: dict[str, dict[str, str]] = {
    "L1": {
        "key": "L1",
        "name": "基础理解",
        "description": "快速建立知识基础，理解基本概念。",
        # 提示词注入：学习成果要求
        "requirements": (
            "- 能解释核心概念及其基本含义；\n"
            "- 能识别重要术语、公式、功能或操作；\n"
            "- 能理解具有代表性的简单示例；\n"
            "- 不要求系统掌握所有技巧或复杂应用。"
        ),
        # 验收难度：可观察的最低成果
        "assessment_hint": (
            "验收以「解释与识别」为主：解释核心概念、识别术语/功能、"
            "复现简单示例即可；不要求独立处理变式或复杂任务。"
        ),
    },
    "L2": {
        "key": "L2",
        "name": "独立应用",
        "description": "在理解基础上，能独立完成典型任务。",
        "requirements": (
            "- 在 L1 基础上，能够独立使用主要知识和方法；\n"
            "- 能完成典型题目、操作或实践任务；\n"
            "- 能识别常见错误，理解方法的适用条件；\n"
            "- 能够根据常见情境选择适当的方法。"
        ),
        "assessment_hint": (
            "验收以「独立完成」为主：独立完成典型任务、识别常见错误并说明"
            "方法适用条件；变式任务限于常见情境。"
        ),
    },
    "L3": {
        "key": "L3",
        "name": "深入掌握与迁移",
        "description": "建立较系统的理解，能解决变化情境下的问题。",
        "requirements": (
            "- 在 L2 基础上，深入理解重要原理及概念间的关系；\n"
            "- 能够比较不同方法，分析其适用条件与局限；\n"
            "- 能处理综合问题、变式任务或新的应用情境；\n"
            "- 能解释关键决策的依据，而不只是模仿已有示例。"
        ),
        "assessment_hint": (
            "验收以「迁移与论证」为主：比较方法优劣、处理综合或变式任务、"
            "解释关键决策依据；不满足于复述已有示例。"
        ),
    },
}


def get_level(level: str | None) -> dict[str, str]:
    return CAPABILITY_LEVELS[normalize_level(level)]


def level_prompt_block(level: str | None) -> str:
    """生成注入提示词的能力层级说明块。"""
    info = get_level(level)
    return (
        f"用户选择的能力层级：{info['key']}（{info['name']}）——{info['description']}\n"
        f"该层级要求的学习成果：\n{info['requirements']}\n"
        f"验收提示：{info['assessment_hint']}\n"
        "注意：无论哪个层级，理解核心概念所必需的知识解释都不能省略；"
        "层级差异体现在学习成果与验收难度上，不是靠堆砌或删减内容来体现。"
    )
