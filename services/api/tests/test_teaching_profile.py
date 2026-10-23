"""用户画像规则解析与教程教学决策的针对性测试。"""

from app.learning.teaching_profile import normalize_teaching_plan, parse_teaching_profile
from app.llm import prompts


def test_parse_teaching_profile_classifies_rule_strength():
    profile = parse_teaching_profile(
        "- 不要跳过理解当前知识所必需的推理步骤\n"
        "必须解释关键推理步骤\n"
        "如果遇到抽象概念，先给一个具体例子\n"
        "先看整体框架\n"
    )
    rules = profile["rules"]
    assert [rule["rule_type"] for rule in rules] == ["forbidden", "required", "conditional", "default"]
    assert [rule["hard"] for rule in rules] == [True, True, False, False]


def test_prompt_separates_charter_from_task_requirements(client):
    resp = client.put(
        "/api/settings/models/user-profile",
        json={"content": "不要跳过前置概念\n必须解释关键推理步骤\n先看整体框架\n"},
    )
    assert resp.status_code == 200, resp.text

    goal = type(
        "G",
        (),
        {
            "title": "查一个简单命令",
            "motivation": "",
            "application_context": "",
            "current_level": "",
            "time_budget": "",
            "capability_level": "L2",
            "user_notes": "本次只要速查式结果，不要展开整体框架",
        },
    )()
    _, user = prompts.outline(goal, type("D", (), {"display_name": "计算机/命令行"})(), [])
    assert "长期教学宪章" in user
    assert "[禁止]（硬约束） 不要跳过前置概念" in user
    assert "[必须]（硬约束） 必须解释关键推理步骤" in user
    assert "[默认偏好]（可按本次任务特点调整方法） 先看整体框架" in user
    assert "current_task_special_requirements" in user
    assert "本次只要速查式结果" in user
    assert "普通偏好，写入 task_overrides" in user


def test_quickstart_persists_teaching_plan(client):
    resp = client.put(
        "/api/settings/models/user-profile",
        json={"content": "不要跳过前置概念\n必须解释关键推理步骤\n先看整体框架\n"},
    )
    assert resp.status_code == 200, resp.text

    goal = client.post(
        "/api/goals",
        json={
            "title": "掌握命令行管道与重定向",
            "domain_key": "cs_it",
            "motivation": "处理日志",
            "application_context": "分析服务器日志",
            "current_level": "基础",
            "time_budget": "共 5 小时",
        },
    ).json()
    body = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart").json()
    job_id = body["job_id"]
    assert job_id
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
    assert job["status"] == "done", job

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    plan = tutorial["current_version"]["content"]["teaching_plan"]
    assert plan["source"] == "long_term_user_profile"
    assert any("不要跳过前置概念" in text for text in plan["rules_applied"])
    assert any("必须解释关键推理步骤" in text for text in plan["rules_applied"])
    assert any(rule["hard"] for rule in plan["rules"])


def test_normalize_teaching_plan_keeps_hard_rules_when_model_omits_them():
    profile = parse_teaching_profile("不要跳过前置概念\n先看整体框架\n")
    plan = normalize_teaching_plan(
        {"rules_applied": ["先看整体框架"], "decisions": ["按单命令速查组织"]},
        profile,
    )
    assert "不要跳过前置概念" in plan["rules_applied"]
    assert "先看整体框架" in plan["rules_applied"]
    assert plan["decisions"] == ["按单命令速查组织"]


def test_profile_suggestion_only_after_every_ten_completed_goals(client):
    goal_ids = []
    for index in range(10):
        goal = client.post(
            "/api/goals",
            json={"title": f"目标 {index + 1}", "domain_key": "cs_it"},
        ).json()
        resp = client.patch(f"/api/goals/{goal['id']}", json={"completed": True})
        assert resp.status_code == 200, resp.text
        goal_ids.append(goal["id"])

        state = client.get("/api/settings/models/user-profile-suggestion").json()
        if index < 9:
            assert state["eligible"] is False

    state = client.get("/api/settings/models/user-profile-suggestion").json()
    assert state["eligible"] is True
    assert state["suggestion"] is not None
    assert "演示建议" in state["suggestion"]["notes"]

    dismissed = client.post("/api/settings/models/user-profile-suggestion/dismiss").json()
    assert dismissed["eligible"] is False
    assert client.get("/api/settings/models/user-profile-suggestion").json()["eligible"] is False