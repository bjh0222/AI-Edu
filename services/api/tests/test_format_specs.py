"""格式规范：管理、匹配、任务快照与交付契约。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.learning.disciplines import get_profile
from app.llm import prompts
from app.services.format_specs import check_snapshot_delivery, delivery_contract_for_snapshot
from app.services.utils import align_section_titles, prune_foreign_section_blocks
from app.services.tutorials import _render_format_spec_document


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


def test_selected_spec_is_the_only_format_authority():
    snapshot = {
        "id": "spec",
        "name": "练习生成规范",
        "scene": "exercise",
        "snapshot_version": "v3",
        "deliverables": [
            {"name": "训练", "status": "required", "order": 1},
        ],
        "content_structure": "# 练习\n\n## 训练",
        "format_rules": "只使用当前模板。",
        "custom_markdown": "**当前模板专属规则**",
    }
    goal = SimpleNamespace(
        title="Python 冲刺",
        motivation="期中考试",
        application_context="完成训练",
        current_level="有基础",
        time_budget="共 10 小时",
        user_notes=(
            "覆盖基础语法与容器。\n"
            "用户已采纳 AI 建议，请按此约束生成：旧模板曾经要求先输出总览。"
        ),
        hard_constraints="1.练习题型只包括代码补全\n2.不要易错辨析，要知识概要\n3.第一章只输出两套试卷",
        capability_level="L2",
        generation_tier="standard",
        format_spec_snapshot=json.dumps(snapshot, ensure_ascii=False),
        generate_extra_exercises=False,
        domain_key="cs_it",
    )

    system, outline_user = prompts.outline(goal, get_profile("cs_it"), [])
    assert "唯一模板来源" in system
    assert "长期教学宪章" not in outline_user
    assert "不要易错辨析" not in outline_user
    assert "第一章只输出" not in outline_user
    assert "练习题型只包括代码补全" in outline_user
    assert "覆盖基础语法与容器" in outline_user
    assert "旧模板曾经要求先输出总览" not in outline_user
    assert "**当前模板专属规则**" in outline_user

    _, section_user = prompts.section(
        goal,
        get_profile("cs_it"),
        {"title": "训练", "_deliverable": "训练"},
        [],
        [],
    )
    assert "当前唯一交付物：训练" in section_user
    assert "不得套用旧教程模板" in section_user
    assert "分层讲解原则" not in section_user
    structural_only = prompts._teaching_charter(
        "section",
        {"rules": [{"text": "旧模板要求固定栏目", "hard": True, "rule_type": "required", "scopes": ["general"]}]},
        goal,
    )
    assert structural_only == ""

    profile_block = prompts._teaching_charter(
        "section",
        {
            "rules": [
                {
                    "text": "遇到实践性强的项目时，希望有更多操作实例",
                    "hard": False,
                    "rule_type": "conditional",
                    "scopes": ["example"],
                },
                {
                    "text": "生成试卷时四个选项分行输出，并保留旧版目录栏目",
                    "hard": True,
                    "rule_type": "conditional",
                    "scopes": ["format"],
                },
            ]
        },
        goal,
    )
    assert "长期用户画像" in profile_block
    assert "希望有更多操作实例" in profile_block
    assert "四个选项分行" not in profile_block
    assert "旧版目录栏目" not in profile_block
    assert "当前格式规范 > 本次任务明确内容 > 长期画像教学偏好" in profile_block


def test_format_spec_renderer_removes_tutorial_wrappers_and_duplicate_titles():
    goal = SimpleNamespace(title="Python 冲刺")
    sections = [
        {
            "title": "训练",
            "content": [
                {
                    "type": "text",
                    "title": "讲解",
                    "body": "# Python 冲刺\n\n## 第一部分\n\n完成题目。",
                }
            ],
            "key_takeaways": ["旧模板结论"],
            "exercises": ["旧模板练习"],
        }
    ]
    lines: list[str] = []
    _render_format_spec_document({}, goal, sections, lines)
    text = "\n".join(lines)

    assert text.count("# Python 冲刺") == 1
    assert "## 训练" in text
    assert "### 第一部分" in text
    assert "## 第 1 节" not in text
    assert "### 讲解" not in text
    assert "旧模板结论" not in text
    assert "旧模板练习" not in text


def test_manual_spec_replaces_legacy_hard_constraint_structure(client: TestClient):
    created = client.post(
        "/api/format-specs",
        json=_payload(
            name="当前练习模板",
            scene="exercise",
            trigger_keywords=[],
            deliverables=[
                {"name": "训练", "status": "required", "order": 1, "allow_override": True},
            ],
            content_structure="# 练习名称\n\n## 训练",
        ),
    )
    assert created.status_code == 200
    spec_id = created.json()["id"]

    response = client.post(
        "/api/goals/quickstart",
        json={
            "title": "模板冲突验证",
            "requirement": "完成练习",
            "hard_constraints": "第一章只输出两套试卷\n不要易错辨析，要知识概要",
            "format_spec_id": spec_id,
        },
    )
    assert response.status_code == 200
    body = response.json()
    content = body["tutorial"]["current_version"]["content"]
    assert [item["title"] for item in content["outline"]] == ["训练"]
    assert content["delivery_contract"]["items"] == ["训练"]
    assert body["tutorial"]["title"] == "模板冲突验证 · 当前练习模板"


def test_foreign_chapter_blocks_are_pruned_and_titles_aligned():
    content = {
        "format_spec": {"name": "试卷生成规范", "scene": "exam_paper", "deliverables": []},
        "outline": [
            {"title": "第一章　基础对标卷（一套）"},
            {"title": "第二章　高难进阶卷（两套）"},
            {"title": "第三章　试卷答案与难题简析"},
        ],
        "sections": [
            {
                "title": "线性代数期中冲刺（内容参考）",
                "content": [
                    {"type": "text", "title": "第一章　基础对标卷（一套）", "body": "第一章正文"},
                    {"type": "text", "title": "第二章　高难进阶卷（两套）", "body": "第二章正文"},
                    {"type": "text", "title": "## 第三章　试卷答案与难题简析", "body": "第三章正文"},
                    {"type": "text", "title": "第三章 答案与难题简析", "body": "编号启发式应剔除"},
                    {
                        "type": "text",
                        "title": "第一章　基础对标卷（一套）· 填空题答案",
                        "body": "派生块应保留",
                    },
                ],
            },
            {"title": "第二章　高难进阶卷（两套）", "content": [{"type": "text", "title": "第一套", "body": "x"}]},
            {"title": "第三章　试卷答案与难题简析", "content": [{"type": "text", "title": "对照方式", "body": "y"}]},
        ],
    }
    fixed = align_section_titles(prune_foreign_section_blocks(content))
    first = fixed["sections"][0]
    titles = [b.get("title") for b in first["content"]]
    assert first["title"] == "第一章　基础对标卷（一套）"
    assert titles == ["第一章　基础对标卷（一套）", "第一章　基础对标卷（一套）· 填空题答案"]
    # 答案章节保留跨章答案块
    answer_titles = [b.get("title") for b in fixed["sections"][2]["content"]]
    assert answer_titles == ["对照方式"]


def test_export_uses_spec_renderer_for_authoritative_spec(client: TestClient):
    import json as _json

    from app.db import SessionLocal
    from app.models import Tutorial, TutorialVersion
    from app.services.tutorials import export_markdown

    created = client.post(
        "/api/goals",
        json={"title": "导出渲染验证", "hard_constraints": "第一章只输出一套试卷"},
    )
    goal_id = created.json()["id"]
    db = SessionLocal()
    try:
        tutorial = Tutorial(goal_id=goal_id, title="导出渲染验证 · 试卷生成规范", status="drafted")
        db.add(tutorial)
        db.flush()
        content = {
            "format_spec": {"name": "试卷生成规范", "scene": "exam_paper", "deliverables": []},
            "delivery_contract": {"source": "format_spec", "items": ["第一章　基础对标卷（一套）"]},
            "outline": [
                {"title": "第一章　基础对标卷（一套）", "criteria_ids": []},
                {"title": "第二章　高难进阶卷（两套）", "criteria_ids": []},
            ],
            "sections": [
                {
                    "title": "导出渲染验证",
                    "content": [
                        {"type": "text", "title": "第一章　基础对标卷（一套）", "body": "卷面正文"},
                        {"type": "text", "title": "第二章　高难进阶卷（两套）", "body": "不该出现"},
                    ],
                    "key_takeaways": ["旧栏目"],
                }
            ],
        }
        version = TutorialVersion(
            tutorial_id=tutorial.id,
            version=1,
            content_json=_json.dumps(content, ensure_ascii=False),
            prompt_version="v1",
            model_provider="demo",
            model_name="demo",
            quality_report="{}",
            source_refs="[]",
        )
        db.add(version)
        db.flush()
        tutorial.current_version_id = version.id
        db.commit()
        name, md = export_markdown(db, tutorial.id)
    finally:
        db.close()

    assert "## 第 1 节" not in md
    assert "### 核心结论" not in md
    assert "## 第一章　基础对标卷（一套）" in md
    assert "不该出现" not in md
    assert "卷面正文" in md


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
