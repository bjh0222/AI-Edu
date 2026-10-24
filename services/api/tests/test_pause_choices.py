"""AI 暂停后的三选项续跑行为。"""

import time

from app.llm.service import AIService


def _create_goal(client) -> dict:
    resp = client.post("/api/goals", json={"title": "学习目标", "domain_key": "cs_it"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pause_diagnose(self, goal, discipline, materials_text=""):
    return {
        "benefits": "收益不足",
        "prerequisites": "无",
        "alternatives": "先缩小范围",
        "assumptions": "无",
        "uncertainties": "无",
        "recommendation": "暂缓：当前需求收益不足，先缩小到最小可交付任务。",
    }


def _poll_job(client, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("续跑任务未在预期时间内结束")


def test_paused_generation_offers_three_choices_and_proceed(client, monkeypatch):
    monkeypatch.setattr(AIService, "diagnose", _pause_diagnose)
    goal = _create_goal(client)

    first = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart")
    assert first.status_code == 409
    detail = first.json()["detail"]
    assert detail["code"] == "generation_paused"
    assert detail["goal_id"] == goal["id"]
    assert [c["label"] for c in detail["choices"]] == [
        "坚决执行",
        "采纳AI建议后立即执行",
        "修改计划",
    ]

    # 不带用户决定重复请求时，不能静默绕过暂停。
    repeated = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart")
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "generation_paused"

    resumed = client.post(
        f"/api/goals/{goal['id']}/tutorials/quickstart",
        json={"pause_action": "proceed"},
    )
    assert resumed.status_code == 200, resumed.text
    job = _poll_job(client, resumed.json()["job_id"])
    assert job["status"] == "done", job


def test_paused_generation_can_adopt_ai_advice(client, monkeypatch):
    monkeypatch.setattr(AIService, "diagnose", _pause_diagnose)
    goal = _create_goal(client)

    paused = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart")
    assert paused.status_code == 409

    resumed = client.post(
        f"/api/goals/{goal['id']}/tutorials/quickstart",
        json={"pause_action": "adopt"},
    )
    assert resumed.status_code == 200, resumed.text
    _poll_job(client, resumed.json()["job_id"])

    updated = client.get(f"/api/goals/{goal['id']}").json()
    assert "用户已采纳 AI 建议" in updated["user_notes"]
    assert "先缩小到最小可交付任务" in updated["user_notes"]
