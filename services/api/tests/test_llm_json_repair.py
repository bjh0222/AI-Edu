"""模型输出解析容错测试：字面换行 / 围栏 / 尾逗号 / 非对象输出。"""

import pytest

from app.llm.provider import LLMError, extract_json
from app.llm.service import AIService, AIServiceError


def test_extract_json_accepts_literal_newlines_in_strings():
    # 模型把 Mermaid 代码块以字面换行写进 JSON 字符串（真实故障样本：
    # 引号已转义，但 \n 是裸换行；直接 json.loads 会失败）
    text = (
        '{"title": "管道", "content": [{"type": "diagram", "title": "数据流", '
        '"body": "```mermaid\nflowchart LR\n    A[\\"你输入的一行文本<br/>命中模式\\"] --> B[\\"匹配行\\"]\n```"}]}'
    )
    data = extract_json(text)
    assert data["title"] == "管道"
    body = data["content"][0]["body"]
    assert "\nflowchart LR" in body
    assert "命" in body


def test_extract_json_tolerates_unescaped_quotes_in_body():
    # 模型忘转义引号：引号后紧跟文字时按内容处理
    text = '{"body": "他说"你好"世界", "ok": true}'
    data = extract_json(text)
    assert data["ok"] is True
    assert "你好" in data["body"]


def test_extract_json_strips_fence_and_surrounding_text():
    text = '以下是结果：\n```json\n{"a": 1}\n```\n以上。'
    assert extract_json(text) == {"a": 1}


def test_extract_json_repairs_trailing_commas():
    text = '{"a": [1, 2, 3,], "b": {"c": 1,},}'
    assert extract_json(text) == {"a": [1, 2, 3], "b": {"c": 1}}


def test_extract_json_returns_non_dict_for_arrays():
    # 顶层数组不是合法任务输出，但解析器不崩溃，由上层转成可读错误
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_json_raises_readable_error():
    with pytest.raises(LLMError) as exc:
        extract_json('{"unclosed": "x"')
    assert "无法解析为 JSON" in str(exc.value)


class _FakeProvider:
    """返回非对象 JSON 的假 provider。"""

    def complete_json(self, system, user):  # noqa: ANN001
        return ["not", "an", "object"], 0, None


def test_real_json_rejects_non_object_output():
    ai = AIService()
    ai.provider = _FakeProvider()  # type: ignore[assignment]
    with pytest.raises(AIServiceError) as exc:
        ai._real_json("section", "s", "u", ("title",))  # noqa: SLF001
    assert "不是 JSON 对象" in str(exc.value)


class _MockProvider:
    """返回缺字段对象。"""

    def complete_json(self, system, user):  # noqa: ANN001
        return {"sections": []}, 0, None


def test_real_json_requires_fields():
    ai = AIService()
    ai.provider = _MockProvider()  # type: ignore[assignment]
    with pytest.raises(AIServiceError) as exc:
        ai._real_json("section", "s", "u", ("title",))  # noqa: SLF001
    assert "缺少字段" in str(exc.value)


def test_unhandled_error_returns_readable_json(client, monkeypatch):
    """未捕获异常不再只给前端一个裸 500，而是返回可读的 detail。"""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import goals as goals_service

    def boom(*args, **kwargs):  # noqa: ANN002,ANN003
        raise RuntimeError("测试注入异常")

    monkeypatch.setattr(goals_service, "list_goals", boom)
    # 默认 TestClient 会重新抛出异常；这里用非抛出模式验证异常处理器
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/goals")
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail["code"] == "internal_error"
    assert "RuntimeError" in detail["message"]


def test_extract_json_repairs_invalid_latex_escapes():
    """模型把集合差 H\\K、\\underline 等原样写进字符串：完整输出也应能解析。"""
    text = (
        '{"title": "参考答案", "content": [{"type": "note", "title": "", '
        '"body": "设 G=H\\\\K、k\\\\in K；\\\\underline{x} 与 \\\\frac{1}{2} 均保留"}]}'
    )
    data = extract_json(text)
    body = data["content"][0]["body"]
    assert "H\\K" in body  # 字面反斜杠保留，语义不变
    assert "\\underline{x}" in body
    assert "\\frac{1}{2}" in body


def test_extract_json_keeps_valid_escapes_untouched():
    text = '{"body": "换行\\n制表\\t引号\\\"反斜杠\\\\结束"}'
    data = extract_json(text)
    assert data["body"] == '换行\n制表\t引号"反斜杠\\结束'


def test_extract_json_error_shows_tail_and_finish_reason():
    with pytest.raises(LLMError) as excinfo:
        extract_json('{"a": "未闭合……训练版式：**n.*', finish_reason="stop")
    message = str(excinfo.value)
    assert "训练版式" in message
    assert "finish_reason=stop" in message
