"""彻底删除学习目标：级联清理、备份、共享概念保护、归档目标列表。"""

import json
import shutil
import time
from pathlib import Path


def _create_goal(client, title: str, domain_key: str = "cs_it") -> dict:
    resp = client.post(
        "/api/goals",
        json={
            "title": title,
            "domain_key": domain_key,
            "motivation": "测试",
            "application_context": "测试场景",
            "current_level": "基础",
            "time_budget": "共 3 小时",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _generate_tutorial(client, goal_id: str) -> str:
    client.post(f"/api/goals/{goal_id}/diagnose")
    client.post(f"/api/goals/{goal_id}/decision", json={"decision": "继续", "reason": "测试"})
    client.post(f"/api/goals/{goal_id}/plan")
    crit = client.post(f"/api/goals/{goal_id}/criteria").json()
    for c in crit:
        client.patch(f"/api/criteria/{c['id']}", json={"status": "confirmed"})
    resp = client.post(f"/api/goals/{goal_id}/tutorials/generate")
    tutorial_id = resp.json()["tutorial"]["id"]
    resp = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
    job_id = resp.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job
            return tutorial_id
        time.sleep(0.05)
    raise AssertionError("章节生成超时")


def test_purge_goal_cascades_and_backs_up(client):
    """彻底删除目标：连带教程 / 标准 / 任务 / 概念，并写 JSON 备份；之后 404。"""
    goal = _create_goal(client, "待删除目标")
    tutorial_id = _generate_tutorial(client, goal["id"])
    assert client.get("/api/knowledge/graph", params={"goal_id": goal["id"]}).json()["stats"]["concepts"] > 0

    resp = client.delete(f"/api/goals/{goal['id']}", params={"purge": "true"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted"]["tutorials"] == 1
    assert body["deleted"]["tutorial_versions"] >= 1
    assert body["deleted"]["concepts"] > 0
    assert body["deleted"]["criteria"] > 0
    # 实践环节已删除：不再产生实践任务
    assert body["deleted"]["practice_tasks"] == 0

    backup = Path(body["backup_path"])
    assert backup.exists(), "删除前必须写 JSON 备份"
    data = json.loads(backup.read_text(encoding="utf-8"))
    assert data["goal"]["id"] == goal["id"]
    assert data["tutorial_versions"], "备份应包含教程版本内容"
    assert client.get(f"/api/goals/{goal['id']}").status_code == 404
    assert client.get(f"/api/tutorials/{tutorial_id}").status_code == 404

    kb = client.get("/api/knowledge").json()
    assert all(goal["id"] not in c["goal_ids"] for c in kb["concepts"])
    # 该目标的概念不再出现在任何范围的图谱
    assert client.get("/api/knowledge/graph", params={"goal_id": goal["id"]}).status_code == 404


def test_purge_keeps_shared_concepts_for_other_goals(client):
    """一个概念服务多个目标时：删除其中一个目标，概念保留并解除关联。"""
    from app.db import SessionLocal
    from app.models import Concept

    a = _create_goal(client, "共享概念-A")
    b = _create_goal(client, "共享概念-B")
    db = SessionLocal()
    try:
        concept = Concept(
            title="共享概念",
            domain_key="cs_it",
            title_norm="共享概念",
            goal_ids=json.dumps([a["id"], b["id"]], ensure_ascii=False),
            domain_keys=json.dumps(["cs_it"], ensure_ascii=False),
        )
        db.add(concept)
        db.commit()
        concept_id = concept.id
    finally:
        db.close()

    resp = client.delete(f"/api/goals/{a['id']}", params={"purge": "true"})
    assert resp.status_code == 200
    detail = client.get(f"/api/knowledge/concepts/{concept_id}")
    assert detail.status_code == 200, "服务其他目标的概念必须保留"
    assert detail.json()["goal_ids"] == [b["id"]]

    shutil.rmtree(Path(__file__).resolve().parent / "test_backups", ignore_errors=True)


def test_archived_goal_listed_and_purge_allowed(client):
    """归档目标不出现在默认列表，include_archived 可查看，且允许彻底删除。"""
    goal = _create_goal(client, "归档后删除")
    assert client.delete(f"/api/goals/{goal['id']}").status_code == 200  # 归档
    default_ids = [g["id"] for g in client.get("/api/goals").json()]
    assert goal["id"] not in default_ids
    all_ids = [g["id"] for g in client.get("/api/goals", params={"include_archived": "true"}).json()]
    assert goal["id"] in all_ids
    assert all(g["archived"] is False for g in client.get("/api/goals").json())
    # 归档目标也可以彻底删除
    assert client.delete(f"/api/goals/{goal['id']}", params={"purge": "true"}).status_code == 200
    assert client.get(f"/api/goals/{goal['id']}").status_code == 404
