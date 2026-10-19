"""导出 / 导入测试。"""


def _mk_goal(client, title="导出测试目标"):
    return client.post(
        "/api/goals",
        json={"title": title, "domain_key": "computer_cli"},
    ).json()


def test_export_import_roundtrip(client):
    goal1 = _mk_goal(client, "目标 A")
    goal2 = _mk_goal(client, "目标 B")
    assert goal1["id"] != goal2["id"]

    exported = client.get("/api/export").json()
    assert exported["version"] == 1
    assert len(exported["data"]["learning_goals"]) == 2

    # 删除一个目标（归档后再导出，验证导入能恢复数据）
    client.delete(f"/api/goals/{goal1['id']}")
    goals_after_delete = client.get("/api/goals").json()
    assert len(goals_after_delete) == 1

    # 导入备份 → 两条目标恢复
    resp = client.post("/api/import", json={"version": 1, "data": exported["data"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["counts"]["learning_goals"] == 2

    goals = client.get("/api/goals").json()
    titles = sorted(g["title"] for g in goals)
    assert titles == ["目标 A", "目标 B"]


def test_import_rejects_bad_version(client):
    resp = client.post("/api/import", json={"version": 99, "data": {}})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "bad_version"
