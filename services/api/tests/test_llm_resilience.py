"""LLM 失败可诊断性 / 章节重试的单元测试。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _mk_goal_and_job():
    from app.db import SessionLocal
    from app.models import GenerationJob, LearningGoal

    db = SessionLocal()
    goal = LearningGoal(title="测试目标", domain_key="computer_cli")
    db.add(goal)
    db.flush()
    job = GenerationJob(goal_id=goal.id, job_type="tutorial_sections", status="running")
    db.add(job)
    db.commit()
    return db, goal, job


def test_fail_job_keeps_error_message(client):
    from app.models import GenerationJob
    from app.services import tutorials

    db, _goal, job = _mk_goal_and_job()
    tutorials._fail_job(db, job.id, "llm_error", "模型请求超时（>180s）")
    db.expire_all()
    stored = db.get(GenerationJob, job.id)
    assert stored.status == "failed"
    assert stored.error_code == "llm_error"
    assert "超时" in stored.error_message
    db.close()


def test_section_retry_recovers_and_counts(client, monkeypatch):
    from app.services import tutorials

    monkeypatch.setattr(tutorials.time, "sleep", lambda _s: None)

    class FlakyAI:
        def __init__(self) -> None:
            self.calls = 0

        def section(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.calls += 1
            if self.calls < 3:
                raise tutorials.AIServiceError(f"模型限流（第 {self.calls} 次）")
            return {"title": "ok"}

    db, _goal, job = _mk_goal_and_job()
    ai = FlakyAI()
    raw = tutorials._section_with_retry(db, job.id, ai, None, None, {}, [], [], "")
    db.expire_all()
    from app.models import GenerationJob

    stored = db.get(GenerationJob, job.id)
    assert raw == {"title": "ok"}
    assert ai.calls == 3
    assert stored.retry_count == 2
    assert stored.status == "running"
    db.close()


def test_section_retry_gives_up_after_max_attempts(client, monkeypatch):
    from app.services import tutorials

    monkeypatch.setattr(tutorials.time, "sleep", lambda _s: None)

    class AlwaysFail:
        def section(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise tutorials.AIServiceError("模型服务错误（HTTP 500）")

    db, _goal, job = _mk_goal_and_job()
    with pytest.raises(tutorials.AIServiceError):
        tutorials._section_with_retry(db, job.id, AlwaysFail(), None, None, {}, [], [], "")
    db.close()


def _provider():
    from app.llm.provider import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        SimpleNamespace(llm_base_url="http://llm.local/v1", llm_api_key="k", llm_model="m", llm_timeout=10)
    )


class _Resp:
    def __init__(self, status: int, body: dict, text: str = "") -> None:
        self.status_code = status
        self._body = body
        self.text = text or str(body)

    def json(self) -> dict:
        return self._body


def test_provider_surfaces_rejection_reason(monkeypatch):
    from app.llm import provider as provider_mod

    resp = _Resp(400, {"error": {"message": "max_tokens too large（上限 8192）"}})
    monkeypatch.setattr(provider_mod.httpx, "post", lambda *a, **k: resp)
    with pytest.raises(provider_mod.LLMError) as excinfo:
        _provider().complete_json("system", "user")
    assert "max_tokens too large" in str(excinfo.value)


def test_provider_rejects_truncated_output(monkeypatch):
    from app.llm import provider as provider_mod

    resp = _Resp(200, {"choices": [{"message": {"content": '{"a": 1'}, "finish_reason": "length"}]})
    monkeypatch.setattr(provider_mod.httpx, "post", lambda *a, **k: resp)
    with pytest.raises(provider_mod.LLMError) as excinfo:
        _provider().complete_json("system", "user")
    assert "截断" in str(excinfo.value)


def test_provider_rejects_empty_content(monkeypatch):
    from app.llm import provider as provider_mod

    resp = _Resp(200, {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})
    monkeypatch.setattr(provider_mod.httpx, "post", lambda *a, **k: resp)
    with pytest.raises(provider_mod.LLMError) as excinfo:
        _provider().complete_json("system", "user")
    assert "空内容" in str(excinfo.value)


def test_parse_error_message_exposes_tail_and_length():
    """截断型失败的根因在「结尾」：只给开头 200 字会把最关键线索切掉。"""
    from app.llm.provider import LLMError, extract_json

    truncated = (
        '{"teaching_plan":{"rules_applied":["交付物清单：仅输出「易错辨析」「训练」'
        '「参考答案」三个 section，顺序固定，不增加任何其它章节","训练版式：**n.*'
    )
    with pytest.raises(LLMError) as excinfo:
        extract_json(truncated, finish_reason="stop")
    message = str(excinfo.value)
    assert "训练版式" in message  # 结尾必须出现在错误里
    assert "长度" in message
    assert "finish_reason=stop" in message


def _outline_goal():
    """prompts.outline 需要的最小目标字段（getattr 之外的直接属性访问）。"""
    return SimpleNamespace(
        title="测试目标", motivation="", application_context="", current_level="",
        time_budget="", hard_constraints="", user_notes="", capability_level=None,
        generation_tier="standard", format_spec_snapshot="", domain_key="cs_it",
    )


def _outline_discipline():
    from app.learning.disciplines import get_profile

    return get_profile("cs_it")


def test_outline_retries_then_succeeds(client, monkeypatch):
    """大纲偶发失败自动重试：第二次成功即交付，不报废整条管线。"""
    from app.llm.service import AIService, AIServiceError

    calls = {"n": 0}

    def fake_real_json(feature, system, user, required, goal=None):  # noqa: ANN001,ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise AIServiceError("模型输出无法解析为 JSON（长度 2400 字符）")
        return {"sections": [{"title": "第一章", "purpose": "p", "content_type": "application"}]}

    ai = AIService()
    ai.provider = SimpleNamespace()  # 退出演示模式，走真实链路（_real_json 已被替换）
    monkeypatch.setattr(ai, "_real_json", fake_real_json)
    data = ai.outline(_outline_goal(), _outline_discipline(), [], "")
    assert calls["n"] == 2
    assert data["sections"][0]["title"] == "第一章"


def test_outline_truncation_retry_adds_compact_hint(client, monkeypatch):
    """截断型失败重试时提示词必须带「压缩篇幅」要求，否则原样重发必然再截断。"""
    from app.llm.service import AIService, AIServiceError

    seen: list[str] = []

    def fake_real_json(feature, system, user, required, goal=None):  # noqa: ANN001,ANN202
        seen.append(user)
        if len(seen) == 1:
            raise AIServiceError("模型输出被截断（finish_reason=length）：单次输出超出上限")
        return {"sections": [{"title": "第一章"}]}

    ai = AIService()
    ai.provider = SimpleNamespace()
    monkeypatch.setattr(ai, "_real_json", fake_real_json)
    ai.outline(_outline_goal(), _outline_discipline(), [], "")
    assert len(seen) == 2
    assert "截断" in seen[1] and "压缩篇幅" in seen[1]


def _spec_goal_with_criteria(client):
    """带格式规范快照 + 已确认验收标准的目标（规范模式大纲兜底的前置条件）。"""
    from app.db import SessionLocal
    from app.models import AcceptanceCriterion, LearningGoal

    db = SessionLocal()
    goal = LearningGoal(title="概率大题练习", domain_key="math_logic")
    goal.format_spec_snapshot = (
        '{"id": "spec-1", "name": "练习册规范", "scene": "exercise_book", "snapshot_version": 1,'
        '"deliverables": ['
        '{"name": "易错辨析", "status": "required", "order": 1},'
        '{"name": "训练", "status": "required", "order": 2},'
        '{"name": "参考答案", "status": "required", "order": 3}]}'
    )
    db.add(goal)
    db.flush()
    criterion = AcceptanceCriterion(goal_id=goal.id, statement="能够独立完成大题", status="confirmed")
    db.add(criterion)
    db.commit()
    goal_id, criterion_id = goal.id, criterion.id
    db.close()
    return goal_id, criterion_id


def test_generate_outline_falls_back_to_contract_when_spec_mode_llm_fails(client, monkeypatch):
    """规范模式下大纲模型调用失败：回退交付契约结构，教程照常产出（不再整体报废）。"""
    from app.db import SessionLocal
    from app.llm.service import AIService, AIServiceError
    from app.services import tutorials as tutorials_service

    goal_id, _ = _spec_goal_with_criteria(client)

    class FailingAI(AIService):
        def outline(self, *args, **kwargs):  # noqa: ANN002,ANN003,ANN201
            raise AIServiceError("模型输出无法解析为 JSON（长度 2539 字符；结尾：训练版式：**n.*）")

    db = SessionLocal()
    try:
        result = tutorials_service.generate_outline(db, goal_id, FailingAI(db, goal_id=goal_id))
        content = result["tutorial"]["current_version"]["content"]
        titles = [item["title"] for item in content["outline"]]
        assert titles == ["易错辨析", "训练", "参考答案"]
        assert content["delivery_contract"]["source"] == "format_spec"
        # 画像硬约束兜底结构在（测试环境无长期画像，rules_applied 允许为空）
        assert content["teaching_plan"].get("source") == "long_term_user_profile"
        assert result["job"].status == "done"
    finally:
        db.close()


def test_generate_outline_still_fails_without_spec(client):
    """非规范模式下大纲是结构唯一来源：模型失败保持原有失败语义（502）。"""
    from fastapi import HTTPException

    from app.db import SessionLocal
    from app.llm.service import AIService, AIServiceError
    from app.services import tutorials as tutorials_service

    db = SessionLocal()
    from app.models import AcceptanceCriterion, LearningGoal

    goal = LearningGoal(title="无规范目标", domain_key="math_logic")
    db.add(goal)
    db.flush()
    db.add(AcceptanceCriterion(goal_id=goal.id, statement="能够独立完成", status="confirmed"))
    db.commit()
    goal_id = goal.id

    class FailingAI(AIService):
        def outline(self, *args, **kwargs):  # noqa: ANN002,ANN003,ANN201
            raise AIServiceError("模型输出无法解析为 JSON")

    try:
        with pytest.raises(HTTPException) as excinfo:
            tutorials_service.generate_outline(db, goal_id, FailingAI(db, goal_id=goal_id))
        assert excinfo.value.status_code == 502
    finally:
        db.close()
