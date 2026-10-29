"""格式规范：管理、匹配、任务快照与交付契约。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.format_specs import check_snapshot_delivery, delivery_contract_for_snapshot


def _payload(name: str = "速查表规范", **overrides) -> dict:
    data = {
        "name": name,
        "description": "整理考前速查材料。",
        "scene": "cheatsheet",
        "applicable_tasks": "整理速查材料",
        "applicable_intents": ["整理速查材料"],
        "excluded_intents": ["讲解知识点"],
        "trigger_keywords": ["速查材料"],
        "excluded_keywords": ["解释"],
        "target_reader": "学生",
        "output_goal": "输出高密度速查材料。",
        "deliverables": [
            {"name": "知识速查", "status": "required", "order": 1, "allow_override": True},
        ],
        "content_structure": "# 速查\n\n## 分类",
        "format_rules": "使用短列表和表格。",
        "forbidden_rules": "不输出长篇教程。",
        "acceptance_criteria": "- 分类完整\n- 无无关内容",
        "custom_markdown": "# 只属于本规范的自定义规则",
    }
    data.update(overrides)
    return data


def test_builtin_specs_initialize_once_and_stay_editable(client: TestClient):
    first = client.get("/api/format-specs")
    assert first.status_code == 200
    specs = first.json()
    assert {item["scene"] for item in specs} >= {"default_tutorial", "exam_paper"}
    assert sum(bool(item["is_default"]) for item in specs) == 1

    exam = next(item for item in specs if item["scene"] == "exam_paper")
    changed = client.put(
        f"/api/format-specs/{exam['id']}",
        json={**exam, "forbidden_rules": exam["forbidden_rules"] + "\n- 测试新增规则"},
    )
    assert changed.status_code == 200
    assert "测试新增规则" in changed.json()["forbidden_rules"]
    assert changed.json()["version"] == exam["version"] + 1

    restarted = client.get("/api/format-specs")
    assert restarted.status_code == 200
    assert restarted.json() == changed_context_specs(changed.json(), restarted.json())


def changed_context_specs(updated: dict, specs: list[dict]) -> list[dict]:
    return [
        updated if item["id"] == updated["id"] else item
        for item in specs
    ]


def test_format_spec_crud_default_uniqueness_and_custom_markdown(client: TestClient):
    created = client.post("/api/format-specs", json=_payload())
    assert created.status_code == 200
    spec = created.json()
    assert spec["custom_markdown"] == "# 只属于本规范的自定义规则"

    copied = client.post(f"/api/format-specs/{spec['id']}/duplicate")
    assert copied.status_code == 200
    assert copied.json()["custom_markdown"] == spec["custom_markdown"]

    updated = client.put(
        f"/api/format-specs/{spec['id']}",
        json={**spec, "format_rules": "更新后的格式规则。"},
    )
    assert updated.status_code == 200
    assert updated.json()["format_rules"] == "更新后的格式规则。"
    assert updated.json()["custom_markdown"] == spec["custom_markdown"]

    default = client.post(f"/api/format-specs/{spec['id']}/default")
    assert default.status_code == 200
    assert all(
        (item["id"] == spec["id"]) == item["is_default"]
        for item in client.get("/api/format-specs").json()
    )

    deleted = client.delete(f"/api/format-specs/{spec['id']}")
    assert deleted.status_code == 200
    specs = client.get("/api/format-specs").json()
    assert specs
    assert sum(bool(item["is_default"]) for item in specs) == 1


def test_matching_explicit_keyword_and_exclusion(client: TestClient):
    specs = client.get("/api/format-specs").json()
    exam = next(item for item in specs if item["scene"] == "exam_paper")
    default = next(item for item in specs if item["is_default"])

    matched = client.post("/api/format-specs/match", json={"requirement": "生成一份模拟试卷"})
    assert matched.status_code == 200
    assert matched.json()["source"] == "keyword"
    assert matched.json()["spec"]["id"] == exam["id"]

    explicit = client.post("/api/format-specs/match", json={"requirement": "使用试卷生成规范出题"})
    assert explicit.status_code == 200
    assert explicit.json()["spec"]["id"] == exam["id"]

    excluded = client.post(
        "/api/format-specs/match", json={"requirement": "解释一道模拟试题的解法"}
    )
    assert excluded.status_code == 200
    assert excluded.json()["spec"]["id"] == default["id"]
    assert excluded.json()["source"] == "default"

    manual = client.post(
        "/api/format-specs/match",
        json={"requirement": "生成一份模拟试卷", "manual_spec_id": default["id"]},
    )
    assert manual.status_code == 200
    assert manual.json()["source"] == "manual"
    assert manual.json()["spec"]["id"] == default["id"]


def test_snapshot_delivery_contract_and_check():
    snapshot = {
        "id": "spec",
        "snapshot_version": "v1",
        "deliverables": [
            {"name": "考向分析", "status": "on_request", "order": 1},
            {"name": "模拟试卷", "status": "required", "order": 2},
            {"name": "参考答案", "status": "forbidden", "order": 3},
        ],
    }
    contract = delivery_contract_for_snapshot(snapshot)
    assert contract is not None
    assert contract["items"] == ["考向分析", "模拟试卷"]
    assert contract["forbidden_deliverables"] == ["参考答案"]

    issues = check_snapshot_delivery(snapshot, {"outline": [{"title": "考向分析"}]})
    assert "必需交付物未出现在结构中：模拟试卷" in issues


def test_quickstart_exam_spec_binds_snapshot_and_contract_before_outline(client: TestClient):
    requirement = (
        "使用试卷生成规范，只输出考向分析和模拟试卷。不要答案，不要解析，"
        "不要学习教程或泛泛的复习建议。"
    )
    response = client.post("/api/goals/quickstart", json={
        "title": "线性代数模拟试卷",
        "requirement": requirement,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["goal"]["format_spec_source"] == "explicit"
    assert body["goal"]["format_spec_snapshot"]["scene"] == "exam_paper"

    content = body["tutorial"]["current_version"]["content"]
    assert content["delivery_contract"]["source"] == "format_spec"
    assert content["delivery_contract"]["forbid_answers"] is True
    titles = [item["title"] for item in content["outline"]]
    assert "考向分析" in titles
    assert "模拟试卷" in titles
    assert "参考答案" not in titles
    assert "难题解析" not in titles
    assert "参考答案" in content["delivery_contract"]["forbidden_deliverables"]
    assert "本次只生成：考向分析" in content["delivery_contract"]["task_overrides"]

    fetched = client.get(f"/api/goals/{body['goal']['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["format_spec_snapshot"]["snapshot_version"]
