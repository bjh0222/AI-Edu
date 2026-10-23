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


def _escape_control_chars_in_strings(text: str) -> str:
    """把 JSON 字符串内部的裸控制字符（换行/制表符）转义。

    模型经常把 Markdown 代码块、Mermaid 图等多行内容以字面换行写进 JSON 字符串，
    这是非法 JSON；转义后即可解析，内容语义不变。
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                out.append(ch)
                escaped = True
            elif ch == '"':
                out.append(ch)
                in_string = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ch == "\b":
                out.append("\\b")
            elif ch == "\f":
                out.append("\\f")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """去掉对象/数组末尾的多余逗号（模型常见的小毛病）。"""
    previous = None
    current = text
    while previous != current:
        previous = current
        current = re.sub(r",(\s*[}\]])", r"\1", current)
    return current


def _tolerant_loads(text: str) -> Any:
    """容错解析：把「字符串内部的未转义引号 / 裸换行」按内容处理后再解析。

    判定规则：字符串中的 `"` 只有在其后紧跟 `, : } ]`（允许空白）或文本结束时
    才视为字符串结束，否则视为内容引号并转义。该规则对 Markdown 代码块、
    Mermaid 节点标签里的引号很有效。
    """
    out: list[str] = []
    idx = 0
    total = len(text)
    in_string = False
    while idx < total:
        ch = text[idx]
        if in_string:
            if ch == "\\":
                if idx + 1 < total:
                    out.append(ch)
                    out.append(text[idx + 1])
                    idx += 2
                    continue
                out.append("\\\\")
                idx += 1
                continue
            if ch == '"':
                nxt = idx + 1
                while nxt < total and text[nxt] in " \t\r\n":
                    nxt += 1
                if nxt >= total or text[nxt] in ",:}]":
                    out.append('"')
                    in_string = False
                else:
                    out.append('\\"')
                idx += 1
                continue
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
            idx += 1
        else:
            out.append(ch)
            if ch == '"':
                in_string = True
            idx += 1
    return json.loads("".join(out))


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（容忍围栏、前后缀、裸换行与未转义引号）。

    注意：不能先用 ``` 正则剥围栏——教程正文本身可能包含 ```mermaid / ```python
    代码块，剥围栏会把合法 JSON 剪碎。因此先按原文解析（含首尾大括号截取），
    只有原文确实无法解析时，才尝试把整体包裹在 ```json 围栏里的情况。

    解析策略（逐级放宽）：
    1. 原文直接解析；
    2. 截取首个 { 到末个 } 再解析；
    3. 转义字符串内部的裸换行/制表符（Markdown / Mermaid 场景最常见）；
    4. 同时清理对象/数组末尾的多余逗号；
    5. 最后用容错扫描器处理未转义引号；
    6. 仍失败时，尝试剥离整体 ```json 围栏后重试以上步骤。
    """
    raw = text.strip()
    candidates = [raw]
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    # 整体被 ``` 围栏包裹（且围栏内只有一个对象）时的候选
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.S)
    if fence:
        inner = fence.group(1).strip()
        candidates.append(inner)
        inner_start, inner_end = inner.find("{"), inner.rfind("}")
        if inner_start >= 0 and inner_end > inner_start:
            candidates.append(inner[inner_start : inner_end + 1])

    for candidate in candidates:
        attempts = [
            candidate,
            _escape_control_chars_in_strings(candidate),
            _strip_trailing_commas(candidate),
            _strip_trailing_commas(_escape_control_chars_in_strings(candidate)),
        ]
        for attempt in attempts:
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
        try:
            return _tolerant_loads(_strip_trailing_commas(candidate))
        except json.JSONDecodeError:
            continue
    raise LLMError(f"模型输出无法解析为 JSON：{raw[:200]}")


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


def _error_detail(resp: httpx.Response) -> str:
    """从失败的响应里提取可读原因，便于前端直接展示与排查。"""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)[:200]
        if err:
            return str(err)[:200]
        return str(body.get("message") or body)[:200]
    return str(body)[:200]


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings):
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout
        self.temperature = getattr(settings, "llm_temperature", 0.3)
        self.json_mode = getattr(settings, "llm_json_mode", True)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _detail(self, resp: httpx.Response) -> str:
        detail = _error_detail(resp)
        if not self.api_key:
            return detail
        if len(self.api_key) < 6:
            return re.sub(r"(?<!\w)" + re.escape(self.api_key) + r"(?!\w)", "[REDACTED]", detail)
        return detail.replace(self.api_key, "[REDACTED]")

    def list_models(self) -> list[str]:
        try:
            resp = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMError(f"获取模型列表失败：{exc.__class__.__name__}") from exc
        if resp.status_code >= 300:
            raise LLMError(f"获取模型列表失败（HTTP {resp.status_code}）；可直接手填模型 ID")
        try:
            data = resp.json()["data"]
            if not isinstance(data, list):
                raise ValueError()
            return sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)})
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("模型列表格式不兼容，请手填模型 ID") from exc

    def _post(
        self, messages: list[dict], json_mode: bool
    ) -> tuple[str, int, dict[str, Any] | None, str]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if json_mode and self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            resp = httpx.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMError(f"模型请求超时（>{self.timeout}s）") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"模型请求失败：{exc.__class__.__name__}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code == 401:
            raise LLMError(f"模型认证失败（检查 API Key）：{self._detail(resp)}")
        if resp.status_code == 429:
            raise LLMError(f"模型限流（稍后重试）：{self._detail(resp)}")
        if resp.status_code >= 300:
            raise LLMError(f"模型请求被拒绝（HTTP {resp.status_code}）：{self._detail(resp)}")
        try:
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, ValueError, AttributeError, TypeError) as exc:
            raise LLMError("模型响应格式异常：需要兼容 Chat Completions 的接口") from exc
        if not isinstance(content, str):
            raise LLMError("模型响应 content 必须为文本")
        finish_reason = str(choice.get("finish_reason") or "")
        if not content.strip():
            raise LLMError(f"模型返回空内容（finish_reason={finish_reason or 'unknown'}）")
        if finish_reason == "length":
            raise LLMError("模型输出被截断（finish_reason=length）：单次输出超出上限，可重试或拆小章节")
        usage = parse_usage(data) if isinstance(data, dict) else None
        return content, latency_ms, usage, finish_reason

    def complete_json(self, system: str, user: str) -> tuple[dict, int, dict[str, Any] | None]:
        content, latency, usage, _finish_reason = self._post(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True
        )
        if len(self.api_key) >= 6:
            content = content.replace(self.api_key, "[REDACTED]")
        return extract_json(content), latency, usage

    def complete_text(self, system: str, user: str) -> tuple[str, int, dict[str, Any] | None]:
        content, latency, usage, _finish_reason = self._post(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=False
        )
        return content.strip(), latency, usage
