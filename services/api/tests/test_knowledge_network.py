"""知识网络重构测试：教程生成联动、去重、图谱范围、关系状态与证据。"""

import time


def _create_goal(client, title="掌握命令行管道与重定向", domain_key="computer_cli") -> dict:
    resp = client.post(
        "/api/goals",
        json={
            "title": title,
            "domain_key": domain_key,
            "motivation": "测试目标",
            "application_context": "分析服务器日志",
            "current_level": "基础",
            "time_budget": "共 5 小时",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _generate_tutorial(client, goal_id: str) -> str:
    """演示模式一键补齐到教程完成，返回 tutorial_id。"""
    resp = client.post(f"/api/goals/{goal_id}/diagnose")
    assert resp.status_code == 200, resp.text
    client.post(f"/api/goals/{goal_id}/decision", json={"decision": "继续", "reason": "测试"})
    resp = client.post(f"/api/goals/{goal_id}/plan")
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/goals/{goal_id}/criteria")
    assert resp.status_code == 200, resp.text
    for c in resp.json():
        assert client.patch(f"/api/criteria/{c['id']}", json={"status": "confirmed"}).status_code == 200
    resp = client.post(f"/api/goals/{goal_id}/tutorials/generate")
    assert resp.status_code == 200, resp.text
    tutorial_id = resp.json()["tutorial"]["id"]
    resp = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job
            return tutorial_id
        time.sleep(0.05)
    raise AssertionError("章节生成超时")


def test_tutorial_generation_writes_knowledge(client):
    """验收 C：教程生成后知识网络自动更新，无需手动触发。"""
    goal = _create_goal(client)
    tutorial_id = _generate_tutorial(client, goal["id"])

    graph = client.get("/api/knowledge/graph").json()
    assert graph["stats"]["concepts"] > 0, "教程生成后应有概念节点"
    assert graph["stats"]["relations"] > 0, "教程生成后应有关系"
    concept_nodes = [n for n in graph["nodes"] if n["type"] == "concept"]
    assert all(n["goal_ids"] if "goal_ids" in n else True for n in concept_nodes)
    # 大纲章节 → 概念，先修链
    titles = {n["title"] for n in concept_nodes}
    assert "准备与核心概念" in titles

    # 数据可从数据库侧（/api/knowledge）查到，且带章节锚点
    kb = client.get("/api/knowledge").json()
    assert kb["concepts"]
    anchored = [c for c in kb["concepts"] if any(r.get("type") == "tutorial_section" for r in c["source_refs"])]
    assert anchored, "概念应携带教程章节锚点"
    rel_with_anchor = [r for r in kb["relations"] if r["source_refs"]]
    assert rel_with_anchor, "教程顺序推导的先修关系应带章节依据"
    confirmed = [r for r in rel_with_anchor if r["status"] == "confirmed"]
    assert confirmed, "有章节锚点的关系应自动确认"

    job_stage = client.get("/api/tutorials/" + tutorial_id).json()
    assert job_stage["id"] == tutorial_id


def test_repeated_generation_no_duplicate_nodes(client):
    """验收 C：重复提取不产生重复节点 / 关系。"""
    goal = _create_goal(client)
    tutorial_id = _generate_tutorial(client, goal["id"])
    before = client.get("/api/knowledge").json()
    n_concepts = len(before["concepts"])
    n_relations = len(before["relations"])
    assert n_concepts > 0

    # 手动再触发一次提取（等价于重新生成后的幂等写入）
    resp = client.post(f"/api/knowledge/extract/{tutorial_id}")
    assert resp.status_code == 200, resp.text
    after = client.get("/api/knowledge").json()
    assert len(after["concepts"]) == n_concepts, "重复提取不应新建概念"
    assert len(after["relations"]) == n_relations, "重复提取不应新建关系"


def test_revoked_relation_not_resurrected(client):
    """验收 E：已撤销的关系不会被重新生成自动恢复。"""
    goal = _create_goal(client)
    tutorial_id = _generate_tutorial(client, goal["id"])
    kb = client.get("/api/knowledge").json()
    target = next(r for r in kb["relations"] if r["relation_type"] == "prerequisite_of")
    resp = client.patch(f"/api/knowledge/relations/{target['id']}", json={"status": "revoked"})
    assert resp.status_code == 200, resp.text

    client.post(f"/api/knowledge/extract/{tutorial_id}")
    kb2 = client.get("/api/knowledge").json()
    same = [r for r in kb2["relations"] if r["id"] == target["id"]]
    assert same and same[0]["status"] == "revoked", "撤销状态必须保留"
    graph = client.get("/api/knowledge/graph").json()
    assert all(e["id"] != target["id"] for e in graph["edges"]), "已撤销关系不应出现在图谱中"

    # 历史留痕
    assert any(h.get("action") == "status" for h in same[0]["history"])


def test_graph_scopes(client):
    """验收 A/B：全局 / 领域 / 学习目标三种范围。"""
    goal = _create_goal(client)
    _generate_tutorial(client, goal["id"])

    g_global = client.get("/api/knowledge/graph").json()
    assert g_global["scope"]["goal_id"] == ""
    assert any(n["type"] == "goal" for n in g_global["nodes"]), "全局图谱应包含目标节点"

    g_domain = client.get("/api/knowledge/graph", params={"domain": "computer_cli"}).json()
    assert g_domain["stats"]["concepts"] > 0

    g_other = client.get("/api/knowledge/graph", params={"domain": "philosophy_ethics"}).json()
    assert g_other["stats"]["concepts"] == 0, "其他领域不应看到该目标的概念"

    g_goal = client.get("/api/knowledge/graph", params={"goal_id": goal["id"]}).json()
    assert g_goal["stats"]["concepts"] > 0
    assert g_goal["scope"]["goal_id"] == goal["id"]


def test_nav_dynamic_domains(client):
    """验收 A：子目录来源于真实学习目标。"""
    goal = _create_goal(client)
    _generate_tutorial(client, goal["id"])
    nav = client.get("/api/knowledge/nav").json()
    keys = [d["key"] for d in nav["domains"]]
    assert "computer_cli" in keys
    domain = next(d for d in nav["domains"] if d["key"] == "computer_cli")
    assert any(g["id"] == goal["id"] for g in domain["goals"])
    assert domain["goals"][0]["concept_count"] > 0
    assert nav["totals"]["concepts"] > 0


def test_concept_detail_and_mastery(client):
    """验收 D：概念详情含教程锚点、前置后续与证据驱动的掌握状态。"""
    goal = _create_goal(client)
    _generate_tutorial(client, goal["id"])
    kb = client.get("/api/knowledge").json()
    concept = kb["concepts"][0]
    detail = client.get(f"/api/knowledge/concepts/{concept['id']}").json()
    assert detail["id"] == concept["id"]
    assert any(g["id"] == goal["id"] for g in detail["goals"]), "概念应关联学习目标"
    assert detail["tutorial_anchors"], "详情应包含教程章节锚点"
    anchor = detail["tutorial_anchors"][0]
    assert anchor["tutorial_id"] and anchor["goal_id"] == goal["id"]
    # 掌握状态：未做任何实践 → 缺证据，不得伪装为已掌握
    assert detail["mastery"]["status"] in ("no_evidence", "practicing", "mastered")
    assert detail["mastery"]["status"] != "mastered" or detail["mastery"]["basis"]


def test_concept_dedup_by_title_and_alias(client):
    """验收 A：同一概念不因重复创建而分裂；别名命中同一节点。"""
    r1 = client.post("/api/knowledge/concepts", json={"title": "管道", "definition": "把前一个命令的输出作为后一个命令的输入", "domain_key": "computer_cli"})
    assert r1.status_code == 200
    r2 = client.post("/api/knowledge/concepts", json={"title": " 管道 ", "definition": ""})
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"], "空白差异不应产生重复概念"
    r3 = client.post("/api/knowledge/concepts", json={"title": "Pipeline", "definition": ""})
    assert r3.status_code == 200
    r4 = client.post("/api/knowledge/concepts", json={"title": "pipeline", "definition": ""})
    assert r4.status_code == 200
    assert r4.json()["id"] == r3.json()["id"], "大小写 / 规范化后同名应合并"
    # 别名合并：新标题 + 别名命中已有概念
    r5 = client.post("/api/knowledge/concepts", json={"title": "Pipes", "definition": "", "aliases": ["管道"]})
    assert r5.status_code == 200
    assert r5.json()["id"] == r1.json()["id"], "显式别名应命中同一概念"


def test_version_level_extraction_idempotent(client):
    """验收 C：同一教程版本只提取一次；force 重提也不产生重复（demo 确定性输出）。"""
    goal = _create_goal(client)
    tutorial_id = _generate_tutorial(client, goal["id"])
    r1 = client.post(f"/api/knowledge/extract/{tutorial_id}")
    assert r1.status_code == 200
    assert r1.json().get("skipped") == "already_extracted"
    count_1 = len(client.get("/api/knowledge").json()["concepts"])

    r2 = client.post(f"/api/knowledge/extract/{tutorial_id}?force=true")
    assert r2.status_code == 200
    count_2 = len(client.get("/api/knowledge").json()["concepts"])
    assert count_2 == count_1, "强制重提（确定性输出）不应新增概念"


def test_fuzzy_title_merge(client):
    """概念识别结合语义判断：措辞漂移的概念合并而非重复创建。"""
    c1 = client.post("/api/knowledge/concepts", json={"title": "CSV 的构成规则", "domain_key": "cs_it"}).json()
    c2 = client.post("/api/knowledge/concepts", json={"title": "CSV 构成规则"}).json()
    assert c2["id"] == c1["id"], "包含关系的相似标题应合并"
    c3 = client.post("/api/knowledge/concepts", json={"title": "HTTP 状态码", "domain_key": "cs_it"}).json()
    assert c3["id"] != c1["id"], "不同概念不得误合并"


def test_dedupe_endpoint_merges_similar(client):
    """模型措辞漂移兜底：dedupe 端点合并相似概念并重指关系。

    创建层已带 0.75 阈值的合并，因此这里直接构造「绕过创建层」的重复概念
    （模拟旧数据 / 真实模型漂移遗留），验证合并与关系重指向。
    """
    from app.db import SessionLocal
    from app.models import Concept
    from app.services.knowledge import dedupe_concepts

    c1 = client.post("/api/knowledge/concepts", json={"title": "标准输出流", "domain_key": "cs_it"}).json()
    c2 = client.post("/api/knowledge/concepts", json={"title": "标准错误流", "domain_key": "cs_it"}).json()
    rel = client.post(
        "/api/knowledge/relations",
        json={"from_concept_id": c1["id"], "to_concept_id": c2["id"], "relation_type": "related"},
    )
    assert rel.status_code == 200

    # 直接落库一条相似重复概念（模拟旧版模块 / 措辞漂移产生的数据）
    db = SessionLocal()
    try:
        dup = Concept(title="标准输出流（stdout）", domain_key="cs_it", title_norm="标准输出流stdout")
        db.add(dup)
        db.commit()
        dup_id = dup.id
    finally:
        db.close()
    client.post(
        "/api/knowledge/relations",
        json={"from_concept_id": dup_id, "to_concept_id": c2["id"], "relation_type": "contrasts_with"},
    )

    result = client.post("/api/knowledge/dedupe").json()
    assert result["merged"] >= 1
    kb = client.get("/api/knowledge").json()
    ids = {c["id"] for c in kb["concepts"]}
    assert dup_id not in ids, "重复概念应被合并删除"
    assert c1["id"] in ids and c2["id"] in ids
    pair = [
        r for r in kb["relations"]
        if r["from_concept_id"] == c1["id"] and r["to_concept_id"] == c2["id"] and r["relation_type"] == "contrasts_with"
    ]
    assert len(pair) == 1, "dup 上的 contrasts_with 边应重指向保留概念"
    assert all(
        dup_id not in (r["from_concept_id"], r["to_concept_id"]) for r in kb["relations"]
    ), "不应有任何边继续指向已删除概念"


def test_manual_relation_confirmed_and_editable(client):
    """验收 E：手动关系确认为已确认，可编辑 / 驳回 / 撤销。"""
    c1 = client.post("/api/knowledge/concepts", json={"title": "标准输出", "domain_key": "computer_cli"}).json()
    c2 = client.post("/api/knowledge/concepts", json={"title": "标准错误", "domain_key": "computer_cli"}).json()
    r = client.post(
        "/api/knowledge/relations",
        json={"from_concept_id": c1["id"], "to_concept_id": c2["id"], "relation_type": "contrasts_with", "rationale": "两者都是输出流"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["origin"] == "manual"

    p = client.patch(f"/api/knowledge/relations/{body['id']}", json={"status": "conflict"})
    assert p.status_code == 200 and p.json()["status"] == "conflict"
    p = client.patch(f"/api/knowledge/relations/{body['id']}", json={"status": "revoked"})
    assert p.status_code == 200 and p.json()["status"] == "revoked"
    bad = client.patch(f"/api/knowledge/relations/{body['id']}", json={"status": "bogus"})
    assert bad.status_code == 422


def test_delete_concept_removes_relations(client):
    """删除节点：概念与其全部关系一起删除，重复删除返回 404。"""
    goal = _create_goal(client)
    _generate_tutorial(client, goal["id"])
    kb = client.get("/api/knowledge").json()
    concept = kb["concepts"][0]
    resp = client.delete(f"/api/knowledge/concepts/{concept['id']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted_relations"] > 0

    kb2 = client.get("/api/knowledge").json()
    assert all(c["id"] != concept["id"] for c in kb2["concepts"])
    assert all(
        concept["id"] not in (r["from_concept_id"], r["to_concept_id"]) for r in kb2["relations"]
    ), "删除概念后不应有残留关系"
    assert client.delete(f"/api/knowledge/concepts/{concept['id']}").status_code == 404


def test_clear_graph_keeps_goals_and_tutorials(client):
    """清空图谱：概念 / 关系 / 提议归零，学习目标与教程保留；重复清空为 0。"""
    goal = _create_goal(client)
    tutorial_id = _generate_tutorial(client, goal["id"])
    assert any(c["goal_ids"] == [goal["id"]] or goal["id"] in c["goal_ids"] for c in client.get("/api/knowledge").json()["concepts"])

    resp = client.delete("/api/knowledge/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_concepts"] > 0 and body["deleted_relations"] > 0

    kb = client.get("/api/knowledge").json()
    assert kb["concepts"] == [] and kb["relations"] == []
    graph = client.get("/api/knowledge/graph").json()
    assert graph["nodes"] == []
    assert client.get(f"/api/goals/{goal['id']}").status_code == 200
    assert client.get(f"/api/tutorials/{tutorial_id}").status_code == 200

    again = client.delete("/api/knowledge/graph").json()
    assert again["deleted_concepts"] == 0
