# -*- coding: utf-8 -*-
"""独立质量评估的关闭/缺 Key/成功调用契约。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import model_settings as store
from app.db import SessionLocal
from app.models import ModelCallLog, Tutorial, TutorialVersion
from app.services.evaluation import EvaluationError, evaluate_version


class FakeProvider:
    model = "eval-model"

    def __init__(self, data=None, exc=None):
        self.data = data or {
            "knowledge_quality": {"score": 4, "summary": "结构清楚", "issues": []},
            "teaching_quality": {"score": 3, "summary": "映射完整", "issues": ["例证不足"]},
            "overall_recommendation": "补充一个可运行例题",
        }
        self.exc = exc
        self.calls = 0

    def complete_json(self, system: str, user: str):
        self.calls += 1
        self.system = system
        self.user = user
        if self.exc:
            raise self.exc("model unavailable")
        return self.data, 123, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "usage_source": "provider"}


@pytest.fixture()
def version(client):
    db = SessionLocal()
    try:
        tutorial = Tutorial(title="评估测试")
        db.add(tutorial)
        db.flush()
        version = TutorialVersion(
            tutorial_id=tutorial.id,
            content_json=json.dumps({"outline": [{"title": "第 1 章"}], "sections": []}, ensure_ascii=False),
            quality_report=json.dumps({"passed": True, "checks": []}, ensure_ascii=False),
        )
        db.add(version)
        db.commit()
        return version.id
    finally:
        db.close()


def test_disabled_skips_without_model_call(client, version):
    provider = FakeProvider()
    result = evaluate_version(SessionLocal(), version, provider=provider)
    assert result == {"status": "skipped", "reason": "independent_eval_disabled", "demo": False}
    assert provider.calls == 0
    db = SessionLocal()
    try:
        assert db.query(ModelCallLog).count() == 0
        assert "independent_eval" not in json.loads(db.get(TutorialVersion, version).quality_report)
    finally:
        db.close()


def test_missing_key_skips_without_model_call(client, version):
    store.save_independent_eval(True, None)
    provider = FakeProvider()
    result = evaluate_version(SessionLocal(), version, provider=provider)
    assert result["status"] == "skipped"
    assert result["reason"] == "evaluation_key_missing"
    assert provider.calls == 0


def test_enabled_with_key_calls_once_and_persists(client, version):
    store.save_profile(store.ModelProfile(
        id="eval-active", name="评估主模型", base_url="https://api.example.com/v1",
        model="main-model", api_key="main-key", timeout=30, temperature=0.2, json_mode=True,
    ))
    store.save_independent_eval(True, "eval-key-123456")
    provider = FakeProvider()
    db = SessionLocal()
    try:
        result = evaluate_version(db, version, provider=provider)
        assert provider.calls == 1
        assert result["status"] == "ok"
        assert result["demo"] is False
        assert result["result"]["knowledge_quality"]["score"] == 4
        stored = db.get(TutorialVersion, version)
        report = json.loads(stored.quality_report)
        assert report["independent_eval"]["status"] == "ok"
        assert report["independent_eval"]["model"] == "eval-model"
        assert db.query(ModelCallLog).filter(ModelCallLog.feature == "independent_eval").count() == 1
    finally:
        db.close()


def test_failure_logs_but_does_not_touch_report(client, version):
    store.save_independent_eval(True, "eval-key-123456")
    provider = FakeProvider(exc=RuntimeError)
    db = SessionLocal()
    try:
        with pytest.raises(EvaluationError):
            evaluate_version(db, version, provider=provider)
        assert provider.calls == 1
        assert db.get(TutorialVersion, version).quality_report == json.dumps({"passed": True, "checks": []}, ensure_ascii=False)
        assert db.query(ModelCallLog).filter(ModelCallLog.status == "error").count() == 1
    finally:
        db.close()


def test_api_does_not_return_full_key(client, version):
    resp = client.put("/api/settings/models/evaluation", json={"enabled": True, "api_key": "secret-key-value"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_key"] is True
    assert "secret-key-value" not in resp.text
    assert data["masked_key"].endswith("alue")
