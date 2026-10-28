"""硬性约束（hard_constraints）：目标创建持久化 + 注入所有生成阶段 prompt。

用户在「创建并生成教程」表单填写硬性约束后，必须满足两条验收：
1. 约束随目标落库，创建 / 修改 / 一键生成三条路径都不丢；
2. 价值判断、学习计划、验收标准、大纲、章节、知识速查、额外练习与评估的
   提示词全部注入约束块，且未填写时不产生噪声块。
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.learning.disciplines import get_profile
from app.llm import prompts

CONSTRAINT = "不安排任何日程"


def _goal(hard_constraints: str = CONSTRAINT) -> SimpleNamespace:
    return SimpleNamespace(
        title="掌握 grep 日志筛选",
        motivation="处理日志",
        application_context="能独立完成日志筛选",
        current_level="会基础命令行",
        time_budget="共 5 小时",
        hard_constraints=hard_constraints,
        user_notes="",
        capability_level="L2",
        generation_tier="standard",
    )


def test_create_and_patch_goal_persists_hard_constraints(client: TestClient):
    created = client.post("/api/goals", json={"title": "测试目标", "hard_constraints": CONSTRAINT})
    assert created.status_code == 200
    body = created.json()
    assert body["hard_constraints"] == CONSTRAINT

    goal_id = body["id"]
    patched = client.patch(f"/api/goals/{goal_id}", json={"hard_constraints": "每章不超过 800 字"})
    assert patched.status_code == 200
    assert patched.json()["hard_constraints"] == "每章不超过 800 字"

    fetched = client.get(f"/api/goals/{goal_id}")
    assert fetched.status_code == 200
    assert fetched.json()["hard_constraints"] == "每章不超过 800 字"


def test_quickstart_carries_hard_constraints(client: TestClient):
    response = client.post(
        "/api/goals/quickstart",
        json={
            "title": "硬性约束目标",
            "requirement": "学会用 grep 筛选日志",
            "hard_constraints": CONSTRAINT,
        },
    )
    assert response.status_code == 200
    assert response.json()["goal"]["hard_constraints"] == CONSTRAINT


def test_hard_constraints_injected_into_all_generation_prompts():
    goal = _goal()
    discipline = get_profile("cs_it")
    user_prompts = {
        "diagnose": prompts.diagnose(goal, discipline)[1],
        "plan": prompts.plan(goal, discipline)[1],
        "criteria": prompts.criteria(goal, discipline)[1],
        "outline": prompts.outline(goal, discipline, [{"id": "c1", "statement": "能够使用 grep"}])[1],
        "section": prompts.section(goal, discipline, {"title": "grep 基础"}, [], [])[1],
        "cheatsheet": prompts.cheatsheet(goal, discipline, [])[1],
        "extra_exercises": prompts.extra_exercises(goal, discipline, [])[1],
        "assessment": prompts.assessment(goal, discipline)[1],
    }
    for name, text in user_prompts.items():
        assert "本次硬性约束" in text, f"{name} 未注入硬性约束"
        assert CONSTRAINT in text, f"{name} 注入的约束内容不完整"


def test_hard_constraints_respect_line_breaks():
    goal = _goal(hard_constraints="不安排任何日程\n全部示例使用 Python 3")
    _, text = prompts.section(goal, get_profile("cs_it"), {"title": "基础"}, [], [])
    assert "- 不安排任何日程" in text
    assert "- 全部示例使用 Python 3" in text


def test_no_constraints_block_when_empty():
    goal = _goal(hard_constraints="   \n  ")
    _, text = prompts.diagnose(goal, get_profile("cs_it"))
    assert "本次硬性约束" not in text
