"""知识管线：正文证据、关系分级、动态上限与大纲后全局阶段。"""
from __future__ import annotations

import json

from app.llm import prompts
from app.llm.service import AIService
from app.models import ConceptRelation, LearningGoal, Tutorial, TutorialVersion
from app.services import synthesis as synthesis_service
from app.services import tutorials as tutorials_service
from app.services.knowledge import (
    _tutorial_context,
    context_fingerprint,
    extract_from_tutorial,
)
from app.services.utils import jdump


def _client_goal(client) -> dict:
    resp = client.post(
        "/api/goals",
        json={
            "title": "知识管线测试目标",
            "domain_key": "cs_it",
            "motivation": "验证管线",
            "application_context": "日志处理",
            "current_level": "基础",
            "time_budget": "5 小时",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _client_goal_no_constraints(client) -> dict:
    return _client_goal(client)


def _tutorial_with_v2_body():
    tutorial = Tutorial(goal_id="g", title="正文上下文教程")
    content = {
        "outline": [{"id": "s1", "title": "管道", "summary": "管道定义"}],
        "sections": [{
            "id": "s1",
            "title": "管道",
            "content": [
                {"type": "text", "title": "核心定义", "body": "管道把前一个命令的输出交给后一个命令作为输入。"},
                {"type": "example", "title": "示例", "body": "cat access.log | grep 500。"},
            ],
        }],
    }
    version = TutorialVersion(tutorial_id=tutorial.id, version=1, content_json=jdump(content))
    return tutorial, version, content


def test_tutorial_context_injects_v2_body_and_fingerprint_changes(client):
    """F1：知识提取必须看到 v2 content[] 正文，正文变化必须改变指纹。"""
    tutorial, version, content = _tutorial_with_v2_body()
    context = _tutorial_context(tutorial, version)
    assert "管道把前一个命令的输出" in context["sections"][0]["body"]
    assert "cat access.log | grep 500" in context["sections"][0]["body"]
    before = context_fingerprint(context)
    content["sections"][0]["content"][0]["body"] = "正文发生了实质变化。"
    changed_version = TutorialVersion(
        tutorial_id=tutorial.id, version=2, content_json=jdump(content)
    )
    assert context_fingerprint(_tutorial_context(tutorial, changed_version)) != before


def test_section_body_context_limit_is_bounded(client):
    """正文注入有预算，避免长教程把提取提示词撑爆。"""
    tutorial, version, _ = _tutorial_with_v2_body()
    long_body = "字" * 5000
    content = {
        "outline": [{"id": "s1", "title": "长正文"}],
        "sections": [{"id": "s1", "title": "长正文", "content": [{"type": "text", "title": "", "body": long_body}]}],
    }
    version.content_json = jdump(content)
    context = _tutorial_context(tutorial, version)
    assert len(context["sections"][0]["body"]) < 5000
    assert context["sections"][0]["body"].endswith("…（正文已截断）")


def test_dynamic_concept_limit_follows_section_count(client):
    """A5：概念上限按章节数伸缩，而不是固定 12。"""
    assert prompts.dynamic_concept_limit(3) == 8
    assert prompts.dynamic_concept_limit(6) == 12
    assert prompts.dynamic_concept_limit(15) == 30
    assert prompts.dynamic_concept_limit(40) == 30


def test_knowledge_relations_use_three_condition_confirmation(client, monkeypatch):
    """F2：锚点、依据、置信度三者齐备才自动确认，否则保持 proposed。"""
    goal = LearningGoal(title="关系分级", domain_key="cs_it")
    tutorial = Tutorial(goal_id=goal.id, title="关系分级教程")
    content = {
        "outline": [{"id": "s1", "title": "管道"}],
        "sections": [{"id": "s1", "title": "管道", "content": []}],
    }
    version = TutorialVersion(tutorial_id=tutorial.id, version=1, content_json=jdump(content))
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        db.add_all([goal, tutorial])
        db.flush()
        version.tutorial_id = tutorial.id
        db.add(version)
        db.commit()

        class FakeAI:
            is_demo = False

            def knowledge_extract(self, goal_arg, tutorial_arg, context, existing):
                return {
                    "concepts": [
                        {"title": "管道", "definition": "连接命令的机制", "section_id": "s1"},
                        {"title": "重定向", "definition": "改变输出去向", "section_id": "s1"},
                    ],
                    "relations": [
                        {
                            "from_title": "管道", "to_title": "重定向",
                            "relation_type": "prerequisite_of", "section_id": "s1",
                            "rationale": "教程正文先解释管道，再说明重定向如何复用管道输出。",
                            "confidence": 0.85,
                        },
                        {
                            "from_title": "重定向", "to_title": "管道",
                            "relation_type": "related", "section_id": "s1",
                            "rationale": "依据不足但字数达到阈值。",
                            "confidence": 0.5,
                        },
                        {
                            "from_title": "管道", "to_title": "重定向",
                            "relation_type": "related", "section_id": "s1",
                            "rationale": "太短", "confidence": 0.9,
                        },
                    ],
                }

        result = extract_from_tutorial(db, goal, tutorial, version, FakeAI(), force=True)
        assert result["concepts"] == 2
        assert result["relations"] == 3
        relations = db.query(ConceptRelation).all()
        by_confidence = {round(r.confidence, 2): r for r in relations}
        assert by_confidence[0.85].status == "confirmed"
        assert by_confidence[0.5].status == "proposed"
        assert by_confidence[0.9].status == "proposed"
    finally:
        db.close()


def test_knowledge_extract_prompt_puts_constraints_first(client):
    """A4：知识提取提示词先声明硬性约束，再给上下文。"""
    goal = _client_goal_no_constraints(client)
    goal_obj = LearningGoal(
        id=goal["id"], title=goal["title"], domain_key=goal["domain_key"],
        hard_constraints="只使用教程正文已有依据；不编造来源。",
    )
    tutorial = Tutorial(goal_id=goal["id"], title="提示词")
    _, user = prompts.knowledge_extract(goal_obj, tutorial, {"sections": []}, [])
    assert user.index("硬性约束") < user.index("学习目标：")


def test_synthesis_prompt_limits_depth_to_structure_and_links(client):
    """新增 Synthesis 阶段：明确不做思想脉络级综合。"""
    goal_obj = LearningGoal(title="梳理深度", domain_key="cs_it")
    _, user = prompts.synthesis(goal_obj, [{"id": "s1", "title": "第一节"}])
    assert "跨章节联系与体系结构" in user
    assert "不做思想脉络" in user


def test_blueprint_prompt_respects_delivery_contract(client):
    """教学蓝图在契约模式下只影响内容取向，不改结构。"""
    goal_obj = LearningGoal(title="契约蓝图", domain_key="cs_it")
    _, user = prompts.blueprint(
        goal_obj,
        [{"id": "s1", "title": "试卷"}],
        {"sections": [{"section_id": "s1"}]},
        {},
        {"items": ["单元检测卷"]},
    )
    assert "不得增加/合并/改写交付物" in user
    assert "只影响每个交付物内部" in user


def test_attach_to_outline_injects_only_relevant_fragments(client):
    """章节 worker 只拿自己的全局片段，不无差别复制全局产物。"""
    outline = [
        {"id": "s1", "title": "第一节"},
        {"id": "s2", "title": "第二节"},
    ]
    synthesis = {
        "sections": [
            {"section_id": "s1", "global_position": "入口", "dependencies": []},
            {"section_id": "s2", "global_position": "应用", "dependencies": []},
        ],
        "global_structure": [
            {"block": "基础", "section_ids": ["s1"]},
            {"block": "应用", "section_ids": ["s2"]},
        ],
    }
    blueprint = {
        "sections": [
            {"section_id": "s1", "depth": "直觉"},
            {"section_id": "s2", "depth": "原理"},
        ]
    }
    attached = synthesis_service.attach_to_outline(outline, synthesis, blueprint)
    assert attached[0]["_synthesis"]["global_blocks"][0]["block"] == "基础"
    assert attached[1]["_synthesis"]["global_blocks"][0]["block"] == "应用"
    assert attached[0]["_synthesis"]["global_blocks"] != attached[1]["_synthesis"]["global_blocks"]
    assert attached[1]["_blueprint"]["depth"] == "原理"


def test_generation_pipeline_calls_synthesis_and_blueprint(client, monkeypatch):
    """生成主流程在并行章节前调用两个全局阶段，并把片段注入章节任务。"""
    goal = _client_goal(client)
    body = client.post(f"/api/goals/{goal['id']}/tutorials/quickstart").json()
    job_id = body["job_id"]
    for _ in range(300):
        job = client.get(f"/api/generation-jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job
            break
        import time
        time.sleep(0.05)
    tutorial_id = body["tutorial"]["id"]

    calls = {"prepare": 0, "sections": []}
    def fake_prepare(goal_arg, outline, teaching_plan, contract, ai):
        calls["prepare"] += 1
        synthesis = {
            "sections": [
                {"section_id": item["id"], "global_position": f"{item['title']} 定位", "dependencies": []}
                for item in outline
            ],
            "global_structure": [{"block": "主路径", "purpose": "顺序依赖", "section_ids": [item["id"] for item in outline]}],
        }
        blueprint = {
            "sections": [
                {"section_id": item["id"], "depth": "核心原理", "method": "示例驱动",
                 "practice_focus": "覆盖本节验收标准", "bridges": [f"衔接{item['title']}"]}
                for item in outline
            ]
        }
        return synthesis, blueprint

    original_section = AIService.section
    def fake_section(self, goal_arg, discipline, item, criteria_list, prior_titles, materials_text="", companion_names=None):
        calls["sections"].append(item)
        return original_section(self, goal_arg, discipline, item, criteria_list, prior_titles, materials_text, companion_names)

    monkeypatch.setattr(synthesis_service, "prepare", fake_prepare)
    monkeypatch.setattr(AIService, "section", fake_section)
    resp = client.post(f"/api/tutorials/{tutorial_id}/sections/generate")
    assert resp.status_code == 200, resp.text
    section_job_id = resp.json()["job_id"]
    for _ in range(300):
        job = client.get(f"/api/generation-jobs/{section_job_id}").json()
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job
            break
        import time
        time.sleep(0.05)

    assert calls["prepare"] == 1
    assert calls["sections"]
    assert all("_synthesis" in item and "_blueprint" in item for item in calls["sections"])
    assert any(item["_blueprint"].get("depth") == "核心原理" for item in calls["sections"])
    finished = client.get(f"/api/tutorials/{tutorial_id}").json()["current_version"]["content"]
    assert all("_synthesis" not in item and "_blueprint" not in item for item in finished["outline"])
