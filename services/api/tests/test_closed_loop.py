"""核心闭环测试：目标 → 诊断 → 计划 → 验收 → 教程 → 实践 → 反馈 → 评估 → 复盘 → 知识。"""

import time


def _create_goal(client) -> dict:
    resp = client.post(
        "/api/goals",
        json={
            "title": "掌握命令行管道与重定向",
            "domain_key": "computer_cli",
            "motivation": "能独立处理日志与数据流",
            "application_context": "分析服务器日志",
            "current_level": "会用 ls/cd 等基础命令",
            "time_budget": "每天 30 分钟",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["demo"] is True  # 测试环境未配置模型
    assert body["llm_configured"] is False


def test_closed_loop_demo(client):
    goal = _create_goal(client)
    goal_id = goal["id"]
    assert goal["domain_name"] == "计算机 / 命令行 / 编程"
    assert goal["status"] == "goal_definition"

    # 诊断
    resp = client.post(f"/api/goals/{goal_id}/diagnose")
    assert resp.status_code == 200, resp.text
    diag = resp.json()
    assert diag["demo"] is True
    assert diag["benefits"]
    assert diag["recommendation"]

    resp = client.post(f"/api/goals/{goal_id}/decision", json={"decision": "继续", "reason": "范围收窄后值得做"})
    assert resp.status_code == 200

    # 计划
    resp = client.post(f"/api/goals/{goal_id}/plan")
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert len(plan["steps"]) >= 4
    assert plan["demo"] is True

    # 验收标准（生成 → 逐条确认）
    resp = client.post(f"/api/goals/{goal_id}/criteria")
    assert resp.status_code == 200, resp.text
    criteria = resp.json()
    assert len(criteria) >= 3
    for c in criteria:
        patch = client.patch(f"/api/criteria/{c['id']}", json={"status": "confirmed"})
        assert patch.status_code == 200

    # 教程：大纲
    resp = client.post(f"/api/goals/{goal_id}/tutorials/generate")
    assert resp.status_code == 200, resp.text
    gen = resp.json()
    assert gen["demo"] is True
    tutorial_id = gen["tutorial"]["id"]
    assert gen["tutorial"]["current_version"]["content"]["outline"]

    # 教程：分节生成（后台任务，轮询进度）+ 质量检查
    resp = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    status = ""
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        status = job["status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.05)
    assert status == "done", f"章节生成未完成：{status}"
    tut = client.get(f"/api/tutorials/{tutorial_id}").json()
    content = tut["current_version"]["content"]
    assert len(content["sections"]) >= 3
    report = tut["current_version"]["quality_report"]
    assert report["passed"] is True, report
    section_ids = [s["id"] for s in content["sections"]]

    # 章节重生成（版本递增）
    resp = client.post(f"/api/tutorials/{tutorial_id}/sections/{section_ids[0]}/regenerate")
    assert resp.status_code == 200, resp.text
    tut2 = resp.json()
    assert tut2["current_version"]["version"] == tut["current_version"]["version"] + 1

    # 自动生成实践任务
    tasks = client.get(f"/api/goals/{goal_id}/tasks").json()
    assert len(tasks) >= 1
    task_id = tasks[0]["id"]

    # 提交尝试 → 逐项反馈
    resp = client.post(
        f"/api/tasks/{task_id}/attempts",
        json={
            "artifact": "cat access.log | grep 500 | wc -l  → 42",
            "artifact_type": "command_session",
            "result": "统计出错请求数量成功",
            "errors": "第一次路径写错，报 No such file",
            "help_level": "A2",
            "user_explanation": "先确认日志路径，再逐段验证管道每一步输出",
        },
    )
    assert resp.status_code == 200, resp.text
    attempt = resp.json()
    assert attempt["demo"] is True
    assert len(attempt["feedback"]["items"]) == len(criteria)

    # 能力评估
    resp = client.post(f"/api/goals/{goal_id}/assessments", json={"assessment_type": "mixed"})
    assert resp.status_code == 200, resp.text
    assessment = resp.json()
    assert assessment["rubric"]
    assert assessment["independent_task"]

    # 复盘
    resp = client.post(f"/api/goals/{goal_id}/reflections", json={})
    assert resp.status_code == 200, resp.text
    reflection = resp.json()
    assert reflection["summary"]

    # 知识提议 → 确认
    resp = client.post(f"/api/goals/{goal_id}/knowledge-proposals")
    assert resp.status_code == 200, resp.text
    proposals = resp.json()
    assert len(proposals) >= 1
    confirm = client.post(
        f"/api/knowledge/proposals/{proposals[0]['id']}/review", json={"action": "confirm"}
    )
    assert confirm.status_code == 200, confirm.text

    # 目标阶段推进到最后
    goal_after = client.get(f"/api/goals/{goal_id}").json()
    assert goal_after["status"] == "reflection"

    # 刷新（重新请求）后数据仍在
    goals = client.get("/api/goals").json()
    assert any(g["id"] == goal_id for g in goals)
    knowledge = client.get("/api/knowledge").json()
    assert len(knowledge["concepts"]) >= 1


def test_tutorial_requires_confirmed_criteria(client):
    goal = _create_goal(client)
    goal_id = goal["id"]
    resp = client.post(f"/api/goals/{goal_id}/tutorials/generate")
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["code"] == "no_confirmed_criteria"


def test_math_discipline_pipeline(client):
    resp = client.post(
        "/api/goals",
        json={
            "title": "用统计假设检验分析一组真实数据",
            "domain_key": "math_data",
            "application_context": "论文数据分析章节",
        },
    )
    assert resp.status_code == 200, resp.text
    goal_id = resp.json()["id"]
    assert resp.json()["domain_name"] == "数学 / 数据分析"

    client.post(f"/api/goals/{goal_id}/diagnose")
    client.post(f"/api/goals/{goal_id}/plan")
    criteria = client.post(f"/api/goals/{goal_id}/criteria").json()
    for c in criteria:
        client.patch(f"/api/criteria/{c['id']}", json={"status": "confirmed"})
    gen = client.post(f"/api/goals/{goal_id}/tutorials/generate").json()
    tut_id = gen["tutorial"]["id"]
    resp = client.post(f"/api/tutorials/{tut_id}/sections/generate")
    assert resp.status_code == 200, resp.text
