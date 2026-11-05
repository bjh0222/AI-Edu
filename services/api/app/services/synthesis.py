"""大纲后的全局知识梳理与教学蓝图。

两个阶段都是生成流程内的临时中间产物：只通过内存传给章节 worker，
不建新数据库表，也不做知识图谱持久化。综合深度限定为跨章节联系与体系结构，
第一期明确不做思想脉络级综合。
"""
from __future__ import annotations

from ..llm.prompts import blueprint as blueprint_prompt
from ..llm.prompts import synthesis as synthesis_prompt
from ..llm.service import AIService, AIServiceError


def _outline_for_prompt(outline: list[dict]) -> list[dict]:
    return [
        {
            "id": str(item.get("id", "")),
            "title": str(item.get("title", "")),
            "purpose": str(item.get("purpose", "")),
            "content_type": str(item.get("content_type", "")),
            "summary": str(item.get("summary", "")),
        }
        for item in outline
        if isinstance(item, dict)
    ]


def _demo_synthesis(outline: list[dict]) -> dict:
    sections = []
    for item in outline:
        previous = outline[outline.index(item) - 1] if outline.index(item) > 0 else None
        dependencies = []
        if previous and previous.get("id"):
            dependencies.append({
                "dependency_id": str(previous["id"]),
                "relation_type": "prerequisite_of",
                "rationale": "教程大纲顺序声明前节先修（演示模式按结构派生）。",
            })
        sections.append({
            "section_id": str(item.get("id", "")),
            "dependencies": dependencies,
            "global_position": f"「{item.get('title', '')}」属于本次教程的顺序学习单元。",
        })
    return {
        "sections": sections,
        "global_structure": [{
            "block": "主学习路径",
            "purpose": "按大纲顺序建立操作与概念的依赖关系。",
            "section_ids": [str(item.get("id", "")) for item in outline],
        }],
    }


def _demo_blueprint(outline: list[dict], synthesis_data: dict) -> dict:
    position = {
        str(row.get("section_id", "")): row for row in synthesis_data.get("sections", []) if isinstance(row, dict)
    }
    sections = []
    for item in outline:
        sid = str(item.get("id", ""))
        sections.append({
            "section_id": sid,
            "depth": "按该节 content_type 选择核心原理与可操作结论。",
            "method": "概念节先解释问题与定义；方法/工具节先演示关键步骤。",
            "practice_focus": "围绕本节验收标准和全局定位选择一个最小练习。",
            "bridges": [position.get(sid, {}).get("global_position", "")] if position.get(sid) else [],
        })
    return {"sections": sections}


def run_synthesis(
    goal, outline: list[dict], teaching_plan: dict | None, ai: AIService
) -> dict:
    """大纲后调用一次；demo 使用确定性产物，绝不伪装成真实模型调用。"""
    sections = _outline_for_prompt(outline)
    if not sections:
        raise AIServiceError("大纲为空，无法生成全局知识梳理")
    if ai.is_demo:
        # 走 AIService 的 demo 记账路径：显式记录演示产物，不伪装成真实模型调用。
        return ai._demo("synthesis", _demo_synthesis(sections), goal)
    system, user = synthesis_prompt(goal, sections, teaching_plan)
    data = ai._real_json("synthesis", system, user, ("sections", "global_structure"), goal)
    if not isinstance(data.get("sections"), list) or not isinstance(data.get("global_structure"), list):
        raise AIServiceError("模型输出缺少有效的全局梳理")
    return data


def run_blueprint(
    goal, outline: list[dict], synthesis_data: dict, teaching_plan: dict | None,
    delivery_contract: dict | None, ai: AIService,
) -> dict:
    """以梳理结果为输入生成教学蓝图；交付契约保持结构硬边界。"""
    sections = _outline_for_prompt(outline)
    if not sections:
        raise AIServiceError("大纲为空，无法生成教学蓝图")
    if ai.is_demo:
        # 同上：demo 蓝图显式记账，避免观测时把它当作真实模型输出。
        return ai._demo(
            "teaching_blueprint", _demo_blueprint(sections, synthesis_data), goal
        )
    system, user = blueprint_prompt(
        goal, sections, synthesis_data, teaching_plan, delivery_contract
    )
    data = ai._real_json("teaching_blueprint", system, user, ("sections",), goal)
    if not isinstance(data.get("sections"), list):
        raise AIServiceError("模型输出缺少教学蓝图片段")
    return data


def prepare(
    goal, outline: list[dict], teaching_plan: dict | None, delivery_contract: dict | None,
    ai: AIService,
) -> tuple[dict, dict]:
    """顺序执行 Synthesis → Blueprint，返回两个内部中间产物。"""
    synthesis_data = run_synthesis(goal, outline, teaching_plan, ai)
    blueprint_data = run_blueprint(
        goal, outline, synthesis_data, teaching_plan, delivery_contract, ai
    )
    return synthesis_data, blueprint_data


def attach_to_outline(outline: list[dict], synthesis_data: dict, blueprint_data: dict) -> list[dict]:
    """把全局结果裁成每节专属片段。

    只注入：本节依赖/定位 + 包含本节的全局分块 + 本节蓝图片段。
    禁止把完整 synthesis / blueprint 无差别复制到每个章节提示词。
    """
    synthesis_rows: dict[str, dict] = {}
    for index, row in enumerate(synthesis_data.get("sections", [])):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("section_id", ""))
        synthesis_rows[sid or str(outline[index].get("id", "") if index < len(outline) else "")] = row
    blueprint_rows: dict[str, dict] = {}
    for index, row in enumerate(blueprint_data.get("sections", [])):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("section_id", ""))
        blueprint_rows[sid or str(outline[index].get("id", "") if index < len(outline) else "")] = row
    attached = []
    for index, item in enumerate(outline):
        sid = str(item.get("id", ""))
        synthesis = dict(synthesis_rows.get(sid, {}))
        relevant_blocks = [
            block for block in synthesis_data.get("global_structure", [])
            if isinstance(block, dict) and sid in [str(x) for x in (block.get("section_ids") or [])]
        ]
        if relevant_blocks:
            synthesis["global_blocks"] = relevant_blocks
        blueprint = blueprint_rows.get(sid, {})
        attached.append({
            **item,
            "_synthesis": synthesis,
            "_blueprint": blueprint,
        })
    return attached
