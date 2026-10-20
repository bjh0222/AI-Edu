"""LLM Provider：OpenAI 兼容接口封装。仅服务端调用。"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..config import Settings


class LLMError(Exception):
    """模型调用失败（网络 / 认证 / 解析）。"""


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（容忍 ```json 围栏与前后缀）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError(f"模型输出无法解析为 JSON：{text[:200]}")


def parse_usage(data: dict[str, Any]) -> dict[str, Any] | None:
    """解析 OpenAI 兼容响应中的 usage；不同提供方字段名略有差异。

    返回 None 表示响应未提供 usage（由上层按字符估算并标记 estimated）。
    """
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if prompt is None and completion is None and total is None:
        return None

    def _int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    prompt_i, completion_i, total_i = _int(prompt), _int(completion), _int(total)
    if total_i is None:
        total_i = (prompt_i or 0) + (completion_i or 0)
    return {
        "prompt_tokens": prompt_i or 0,
        "completion_tokens": completion_i or 0,
        "total_tokens": total_i or 0,
        "usage_source": "provider",
    }


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings):
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout

    def _post(self, messages: list[dict], json_mode: bool) -> tuple[str, int, dict[str, Any] | None]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMError("模型请求超时") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"模型请求失败：{exc.__class__.__name__}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code == 401:
            raise LLMError("模型认证失败（检查 API Key）")
        if resp.status_code == 429:
            raise LLMError("模型限流（稍后重试）")
        if resp.status_code >= 500:
            raise LLMError(f"模型服务错误（{resp.status_code}）")
        if resp.status_code >= 400:
            raise LLMError(f"模型请求被拒绝（{resp.status_code}）")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError("模型响应格式异常") from exc
        usage = parse_usage(data) if isinstance(data, dict) else None
        return content, latency_ms, usage

    def complete_json(self, system: str, user: str) -> tuple[dict, int, dict[str, Any] | None]:
        content, latency, usage = self._post(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True
        )
        return extract_json(content), latency, usage

    def complete_text(self, system: str, user: str) -> tuple[str, int, dict[str, Any] | None]:
        content, latency, usage = self._post(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=False
        )
        return content.strip(), latency, usage
