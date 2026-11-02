"""生成挡位 / 一次性入口 / 聚焦导出 / Obsidian 交付状态测试。"""

import time

from app.llm import prompts


def _fake_goal(tier: str):
    return type(
        "G",
        (),
        {
            "title": "掌握命令行管道",
            "motivation": "处理日志",
            "application_context": "分析服务器日志",
            "current_level": "基础",
            "time_budget": "共 5 小时",
            "capability_level": "L2",
            "user_notes": "",
            "generation_tier": tier,
        },
    )()


def _discipline():
    from app.learning.disciplines import get_profile

    return get_profile("cs_it")


def test_tier_prompts_are_independent_and_selectable(client):
    fast_system, fast_user = prompts.outline(_fake_goal("fast"), _discipline(), [])
    deep_system, deep_user = prompts.outline(_fake_goal("deep"), _discipline(), [])
    assert "高效的个性化教学设计与教程生成助手" in fast_system
    assert "教学架构设计师" in deep_system
    assert "生成挡位：快速" in fast_user
    assert "生成挡位：深度" in deep_user
    assert "最小充分学习目标" in fast_user
    assert "一一对应的验收标准" in deep_user


def _poll_job(client, job_id: str, tries: int = 300) -> dict:
    for _ in range(tries):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("一次性生成任务未在预期时间内结束")


def test_one_shot_fast_generation_and_focused_export(client):
    resp = client.post(
        "/api/goals/quickstart",
        json={
            "requirement": "学会用 grep 与 awk 从日志中统计错误，并能解释每个步骤",
            "generation_tier": "fast",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["goal"]["generation_tier"] == "fast"
    assert body["goal"]["domain_key"] == "cs_it"
    assert body["job_id"]
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job

    goal = client.get(f"/api/goals/{body['goal']['id']}").json()
    assert goal["generation_tier"] == "fast"

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    content = tutorial["current_version"]["content"]
    assert len(content["outline"]) <= 2
    assert len(content["sections"]) <= 2

    export = client.get(f"/api/tutorials/{tutorial['id']}/export")
    assert export.status_code == 200, export.text
    markdown = export.text
    assert markdown.startswith("#")
    assert "ai_edu:" not in markdown
    assert "## 一、" in markdown  # 规范渲染器：章标题带中文序号，不再输出「目录」块
    assert "## 验收标准" not in markdown
    assert "## 质量报告" not in markdown
    assert "由 AI Edu 生成" not in markdown


def test_delivery_state_is_separate_from_generation(client):
    resp = client.post(
        "/api/goals/quickstart",
        json={
            "title": "标准生成教程",
            "requirement": "学习 SQL 基础查询并完成一次数据筛选",
            "generation_tier": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["goal"]["generation_tier"] == "standard"
    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job

    tutorial_id = body["tutorial"]["id"]
    before = client.get(f"/api/tutorials/{tutorial_id}").json()
    assert before["delivery_status"] == ""
    assert before["delivery_version"] == 0

    delivered = client.post(
        f"/api/tutorials/{tutorial_id}/delivery",
        json={"status": "delivered", "path": "AI Edu/标准生成教程-教程.md", "version": before["current_version"]["version"]},
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["delivery_status"] == "delivered"
    assert delivered.json()["delivery_path"].endswith(".md")
    assert delivered.json()["delivery_version"] == before["current_version"]["version"]
