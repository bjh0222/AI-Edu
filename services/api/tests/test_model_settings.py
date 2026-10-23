import httpx


def profile(**patch):
    return dict(id="test", name="Test", base_url="https://model.example/v1", model="tutor", api_key="secret-test-key", **patch)


def test_saved_key_redacted_retained_and_not_sent_to_changed_host(client):
    from app.model_settings import read_config
    response = client.post("/api/settings/models", json=profile())
    assert response.status_code == 200
    assert "secret-test-key" not in response.text
    assert response.json()["profiles"][0]["has_key"] is True
    changed = profile(); changed["api_key"] = None; changed["model"] = "tutor2"
    client.post("/api/settings/models", json=changed)
    assert read_config()["profiles"][0]["api_key"] == "secret-test-key"
    changed["base_url"] = "https://other.example/v1"
    client.post("/api/settings/models", json=changed)
    assert read_config()["profiles"][0]["api_key"] == ""


def test_activation_applies_to_service_and_survives_reload(client):
    from app.llm.service import AIService
    from app.model_settings import runtime_settings
    client.post("/api/settings/models", json=profile())
    assert client.get("/api/health").json()["demo"] is True
    client.post("/api/settings/models/activate", json={"active_id": "test"})
    service = AIService()
    assert service.provider.model == "tutor"
    assert runtime_settings().llm_model == "tutor"
    assert client.get("/api/health").json()["demo"] is False
    assert client.delete("/api/settings/models/test").status_code == 409
    client.post("/api/settings/models/activate", json={"active_id": None})
    assert AIService().is_demo
    # Existing jobs keep their original provider snapshot.
    assert service.provider.model == "tutor"
    assert client.delete("/api/settings/models/test").status_code == 200


def test_probe_uses_real_protocol_and_never_activates(client, monkeypatch):
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true,"reply":"OK"}'}, "finish_reason": "stop"}], "usage": {"total_tokens": 12}})
    monkeypatch.setattr("app.llm.provider.httpx.post", post)
    response = client.post("/api/settings/models/test", json=profile())
    assert response.status_code == 200 and response.json()["demo"] is False
    assert response.json()["usage"]["total_tokens"] == 12
    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert client.get("/api/settings/models").json()["profiles"] == []


def test_probe_failure_is_redacted_and_no_demo_fallback(client, monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.post", lambda *a, **kw: httpx.Response(401, json={"error": {"message": "Invalid secret-test-key"}}))
    response = client.post("/api/settings/models/test", json=profile())
    assert response.status_code == 502
    assert "secret-test-key" not in response.text
    assert "认证失败" in response.text


def test_local_no_key_compatibility_and_validation(client, monkeypatch):
    def post(url, **kw):
        assert "Authorization" not in kw["headers"]
        assert "temperature" not in kw["json"] and "response_format" not in kw["json"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true,"reply":"OK"}'}}]})
    monkeypatch.setattr("app.llm.provider.httpx.post", post)
    p = profile(); p.update(api_key="", temperature=None, json_mode=False, base_url="http://127.0.0.1:11434/v1/chat/completions")
    assert client.post("/api/settings/models/test", json=p).status_code == 200
    client.post("/api/settings/models", json=p)
    client.post("/api/settings/models/activate", json={"active_id": "test"})
    assert client.get("/api/health").json()["demo"] is False
    p["base_url"] = "file:///test"
    assert client.post("/api/settings/models", json=p).status_code == 422
    assert client.post("/api/settings/models", json=profile(), headers={"Origin": "https://evil.example"}).status_code == 403


def test_discovery_and_malformed_probe(client, monkeypatch):
    monkeypatch.setattr("app.llm.provider.httpx.get", lambda *a, **kw: httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}, {"id": "b"}]}))
    assert client.post("/api/settings/models/discover", json=profile()).json()["models"] == ["a", "b"]
    monkeypatch.setattr("app.llm.provider.httpx.post", lambda *a, **kw: httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":false}'}}]}))
    assert client.post("/api/settings/models/test", json=profile()).status_code == 502
