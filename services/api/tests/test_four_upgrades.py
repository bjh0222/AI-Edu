"""四项改造测试：一键生成 / 一键同意 / token 累计 / 训练数据采集导出。"""

import json
import time


def _goal(client, title="掌握命令行管道与重定向") -> dict:
    resp = client.post(
        "/api/goals",
        json={
            "title": title,
            "domain_key": "computer_cli",
            "motivation": "能独立处理日志与数据流",
            "application_context": "分析服务器日志",
            "current_level": "会用 ls/cd 等基础命令",
            "time_budget": "每天 30 分钟",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _poll_job(client, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("生成任务未在预期时间内结束")


def _quickstart(client, goal_id: str) -> dict:
    resp = client.post(f"/api/goals/{goal_id}/tutorials/quickstart")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_quickstart_batch_confirm_and_idempotent(client):
    goal = _goal(client)
    goal_id = goal["id"]

    body = _quickstart(client, goal_id)
    assert body["demo"] is True
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["diagnose"]["status"] == "created"
    assert steps["plan"]["status"] == "created"
    assert steps["criteria"]["status"] == "created"
    assert "新确认" in steps["criteria"]["detail"]
    assert steps["outline"]["status"] == "created"
    assert steps["sections"]["status"] == "created"
    assert body["job_id"]

    # 一键同意：全部标准已确认
    criteria = client.get(f"/api/goals/{goal_id}/criteria").json()
    assert criteria and all(c["status"] == "confirmed" for c in criteria)

    job = _poll_job(client, body["job_id"])
    assert job["status"] == "done", job
    assert job["token_usage"]["total_tokens"] > 0
    assert job["token_usage"]["usage_source"] == "estimated"

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    assert tutorial["tokens"]["total_tokens"] > 0
    assert tutorial["tokens"]["usage_source"] == "estimated"
    assert tutorial["current_version"]["token_usage"]["total_tokens"] > 0
    sections = tutorial["current_version"]["content"]["sections"]
    assert len(sections) >= 3
    assert all(s["token_usage"]["total_tokens"] > 0 for s in sections)

    # 再次一键：幂等，不重复生成
    again = _quickstart(client, goal_id)
    assert again["job_id"] is None
    statuses = {s["key"]: s["status"] for s in again["steps"]}
    assert statuses["criteria"] == "reused"
    assert statuses["outline"] == "reused"
    assert statuses["sections"] == "reused"


def test_confirm_all_keeps_rejected_criteria(client):
    goal = _goal(client)
    goal_id = goal["id"]
    criteria = client.post(f"/api/goals/{goal_id}/criteria").json()
    assert len(criteria) >= 2
    rejected_id = criteria[0]["id"]
    client.patch(f"/api/criteria/{rejected_id}", json={"status": "rejected"})

    resp = client.post(f"/api/goals/{goal_id}/criteria/confirm-all")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] == len(criteria) - 1
    by_id = {c["id"]: c for c in body["criteria"]}
    assert by_id[rejected_id]["status"] == "rejected"
    assert all(c["status"] == "confirmed" for cid, c in by_id.items() if cid != rejected_id)
    assert client.get(f"/api/goals/{goal_id}").json()["status"] == "acceptance_design"


def test_section_detail_and_goal_usage(client):
    goal = _goal(client)
    goal_id = goal["id"]
    body = _quickstart(client, goal_id)
    assert body["job_id"]
    _poll_job(client, body["job_id"])

    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    sections = tutorial["current_version"]["content"]["sections"]
    target = sections[1]
    detail = client.get(f"/api/tutorials/{tutorial['id']}/sections/{target['id']}")
    assert detail.status_code == 200, detail.text
    section = detail.json()
    assert section["id"] == target["id"]
    assert section["tutorial_id"] == tutorial["id"]
    assert section["goal_id"] == goal_id
    assert section["index"] == 1
    assert section["total"] == len(sections)
    assert section["prev_section_id"] == sections[0]["id"]
    assert section["next_section_id"] == sections[2]["id"]
    assert section["token_usage"]["total_tokens"] > 0

    missing = client.get(f"/api/tutorials/{tutorial['id']}/sections/not-exist")
    assert missing.status_code == 404

    usage = client.get(f"/api/goals/{goal_id}/usage").json()
    assert usage["totals"]["total_tokens"] > 0
    assert usage["totals"]["calls"] > 0
    assert usage["estimated_calls"] > 0
    assert usage["provider_calls"] == 0
    assert any(item["feature"] == "section" for item in usage["by_feature"])
    assert usage["by_tutorial"] and usage["by_tutorial"][0]["tutorial_id"] == tutorial["id"]


def test_training_feedback_persist_and_export(client):
    goal = _goal(client)
    goal_id = goal["id"]
    body = _quickstart(client, goal_id)
    assert body["job_id"]
    _poll_job(client, body["job_id"])
    tutorial = client.get(f"/api/tutorials/{body['tutorial']['id']}").json()
    section_id = tutorial["current_version"]["content"]["sections"][0]["id"]

    resp = client.post(
        "/api/training/feedback",
        json={
            "goal_id": goal_id,
            "tutorial_id": tutorial["id"],
            "section_id": section_id,
            "target_type": "section",
            "rating": -1,
            "tags": ["步骤太抽象", "来源不足"],
            "comment": "希望第二节给出更具体的命令示例。",
            "context": {"version": tutorial["current_version"]["version"]},
        },
    )
    assert resp.status_code == 200, resp.text
    record = resp.json()
    assert record["source_type"] == "feedback"
    assert record["rating"] == -1
    assert record["tags"] == ["步骤太抽象", "来源不足"]

    stats = client.get("/api/training/stats").json()
    assert stats["totals"]["feedback"] == 1
    assert stats["totals"]["materials"] > 0
    assert stats["feedback"]["negative"] == 1
    assert stats["tokens"]["total_tokens"] > 0

    records = client.get("/api/training/records?source_type=material&limit=5").json()
    assert records["total"] > 0
    assert len(records["items"]) <= 5
    assert records["items"][0]["source_type"] == "material"

    exported = client.get("/api/training/export").text.strip().splitlines()
    samples = [json.loads(line) for line in exported]
    assert any(s["source_type"] == "feedback" for s in samples)
    material = next(s for s in samples if s["source_type"] == "material")
    assert material["messages"][-1]["role"] == "assistant"
    assert material["metadata"]["demo"] is True
    assert material["metadata"]["total_tokens"] > 0
    feedback = next(s for s in samples if s["source_type"] == "feedback")
    assert feedback["feedback"]["rating"] == -1
    assert feedback["target"]["section_id"] == section_id

    # 排除演示材料后：只剩真实用户反馈
    real_only = client.get("/api/training/export?exclude_demo=true").text.strip().splitlines()
    real_samples = [json.loads(line) for line in real_only]
    assert real_samples
    assert all(s["source_type"] == "feedback" for s in real_samples)

    # 备份 / 恢复包含训练数据
    backup = client.get("/api/export").json()
    assert "training_records" in backup["data"]
    assert len(backup["data"]["training_records"]) > 0
    imported = client.post("/api/import", json={"version": 1, "data": backup["data"]})
    assert imported.status_code == 200, imported.text
    assert client.get("/api/training/stats").json()["totals"]["feedback"] == 1


def test_training_feedback_validation(client):
    goal = _goal(client)
    missing_tutorial = client.post(
        "/api/training/feedback",
        json={"goal_id": goal["id"], "tutorial_id": "nope", "target_type": "tutorial", "rating": 1},
    )
    assert missing_tutorial.status_code == 404
    bad_rating = client.post(
        "/api/training/feedback",
        json={"goal_id": goal["id"], "target_type": "general", "rating": 0},
    )
    assert bad_rating.status_code == 422


def test_start_sections_reuses_active_job(client, monkeypatch):
    """章节任务幂等：已有排队 / 进行中的章节任务时再次提交，返回同一个 job。

    「一键生成自动续跑全部章节」与手动按钮并发提交时，不能开出两路重复生成任务。
    """
    import app.services.tutorials as tutorials_service

    goal = _goal(client)
    goal_id = goal["id"]
    client.post(f"/api/goals/{goal_id}/criteria")
    confirm = client.post(f"/api/goals/{goal_id}/criteria/confirm-all")
    assert confirm.status_code == 200, confirm.text
    outline = client.post(f"/api/goals/{goal_id}/tutorials/generate")
    assert outline.status_code == 200, outline.text
    tutorial_id = outline.json()["tutorial"]["id"]

    # 冻结后台线程：任务提交后停留在 queued，模拟「正在生成」
    class _FrozenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(tutorials_service.threading, "Thread", _FrozenThread)

    try:
        first = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
        assert first.status_code == 200, first.text
        second = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
        assert second.status_code == 200, second.text
        assert second.json()["job_id"] == first.json()["job_id"]

        # 队列里只有一个章节任务，不会重复生成
        jobs = [j for j in _all_jobs(client) if j["job_type"] == "tutorial_sections"]
        assert len(jobs) == 1
    finally:
        # 冻结线程永远不会自己跑完、也就永远不会从在途登记里摘除，留着会污染
        # pending_knowledge_extractions()（其它测试据此等待「后台提取已结束」）。
        # 只清理本次冻结出来的假线程，不碰真实在途线程。
        with tutorials_service._PENDING_EXTRACTIONS_LOCK:
            for thread in [t for t in tutorials_service._PENDING_EXTRACTIONS if isinstance(t, _FrozenThread)]:
                tutorials_service._PENDING_EXTRACTIONS.discard(thread)


def _all_jobs(client) -> list[dict]:
    """遍历最近的任务列表（测试辅助：演示数据量小，直接查库不可行，走 API）。"""
    from app.db import SessionLocal
    from app.models import GenerationJob

    db = SessionLocal()
    try:
        return [
            {"id": j.id, "job_type": j.job_type, "status": j.status}
            for j in db.query(GenerationJob).all()
        ]
    finally:
        db.close()
