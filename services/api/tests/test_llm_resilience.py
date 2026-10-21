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
