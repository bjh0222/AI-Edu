"""学科配置：跨学科学习引擎的学科差异层（v2.0 §5.4/§5.5）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DisciplineProfile:
    key: str
    display_name: str
    goal_types: list[str] = field(default_factory=list)
    artifact_types: list[str] = field(default_factory=list)
    practice_templates: list[str] = field(default_factory=list)
    assessment_rubrics: list[str] = field(default_factory=list)
    common_errors: list[str] = field(default_factory=list)
    source_requirements: list[str] = field(default_factory=list)
    tutorial_requirements: list[str] = field(default_factory=list)


COMPUTER_CLI = DisciplineProfile(
    key="computer_cli",
    display_name="计算机 / 命令行 / 编程",
    goal_types=["入门一个工具", "掌握工作流", "完成一个真实项目", "排错与调试"],
    artifact_types=["command_session", "code", "test_output", "debug_log", "repo_commit"],
    practice_templates=[
        "在给定约束下完成一个小任务并提交产物",
        "复现一个错误、定位原因并修复",
        "为关键步骤补充验证或测试",
        "完成一个与教程示例不同的变式任务",
    ],
    assessment_rubrics=[
        "概念解释：能用自己的话说明核心机制与边界",
        "实际应用：能独立完成同类任务",
        "错误诊断：能定位并解释错误原因",
        "独立完成：辅助等级 ≤ 提示模式下完成任务",
        "迁移：能在新情境中应用知识",
    ],
    common_errors=[
        "路径/目录错位", "权限问题", "参数拼写错误", "环境或依赖缺失",
        "命令输出被截断", "把命令示例当作文本复制而非理解", "边界条件遗漏",
    ],
    source_requirements=[
        "命令行为以官方文档或实际运行为准",
        "版本敏感的行为需标注版本号",
        "危险命令必须标注风险与回退方式",
    ],
    tutorial_requirements=[
        "每个命令给出前置条件、预期输出与验证方式",
        "示例可复制执行，并说明执行环境",
        "包含失败示例与排查步骤",
    ],
)

MATH_DATA = DisciplineProfile(
    key="math_data",
    display_name="数学 / 数据分析",
    goal_types=["理解一组方法", "完成一次数据分析", "掌握推导与证明", "形成统计判断"],
    artifact_types=["derivation", "computation", "data_table", "plot", "analysis_report"],
    practice_templates=[
        "用给定数据完成一次分析并解释结论",
        "推导关键结论并说明每一步依据",
        "检查一个分析方法的前提假设是否成立",
        "完成一个变式数据上的迁移任务",
    ],
    assessment_rubrics=[
        "概念解释：能说明定义、直觉与适用条件",
        "实际应用：能对真实数据完成分析",
        "错误诊断：能识别假设不满足或计算错误",
        "独立完成：不依赖逐步提示完成推导或分析",
        "迁移：能在变式数据或新情境中正确应用",
    ],
    common_errors=[
        "概念混淆（如相关与因果）", "前提假设不满足", "计算或单位错误",
        "过度解读结果", "样本选择偏差", "把结论推广到不适用的范围",
    ],
    source_requirements=[
        "方法与公式需给出出处或标准教材依据",
        "数据结果需可复算",
        "区分事实、推论与待验证假设",
    ],
    tutorial_requirements=[
        "定义与适用条件先于方法使用",
        "推导过程逐步给出，不跳步",
        "提供可复算示例与反例/边界条件",
        "明确结论的限制",
    ],
)

PROFILES: dict[str, DisciplineProfile] = {
    COMPUTER_CLI.key: COMPUTER_CLI,
    MATH_DATA.key: MATH_DATA,
}


def get_profile(key: str | None) -> DisciplineProfile:
    return PROFILES.get(key or "computer_cli", COMPUTER_CLI)


def list_profiles() -> list[dict]:
    return [
        {
            "key": p.key,
            "display_name": p.display_name,
            "goal_types": p.goal_types,
            "artifact_types": p.artifact_types,
        }
        for p in PROFILES.values()
    ]
