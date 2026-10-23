"""Local model profiles. Secrets stay on the server; each call uses a snapshot."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from .config import settings

_lock = threading.RLock()


class ModelProfile(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(max_length=2048)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=8192)
    timeout: int = Field(default=120, ge=5, le=600)
    temperature: float | None = Field(default=0.3, ge=0, le=2)
    json_mode: bool = True

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        for suffix in ("/chat/completions", "/models"):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("请填写 http/https API 根地址，不含账号、查询参数或片段")
        return value

    @field_validator("name", "model", mode="before")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


def config_path() -> Path:
    return Path(os.getenv("MODEL_SETTINGS_FILE", "data/model-settings.json"))


def read_config() -> dict:
    with _lock:
        path = config_path()
        if path.exists():
            config = json.loads(path.read_text(encoding="utf-8"))
            config.setdefault("user_profile", "")
            return config
        profiles = []
        if settings.llm_configured:
            profiles.append(dict(id="environment", name="环境变量配置", base_url=settings.llm_base_url,
                                 model=settings.llm_model, api_key=settings.llm_api_key,
                                 timeout=settings.llm_timeout, temperature=0.3, json_mode=True))
        return {
            "active_id": "environment" if profiles else None,
            "profiles": profiles,
            "user_profile": "",
        }


def write_config(config: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with _lock:
        try:
            with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def public_config() -> dict:
    config = read_config()
    return {"active_id": config["active_id"], "user_profile": config.get("user_profile", ""), "profiles": [
        {**{k: v for k, v in p.items() if k != "api_key"}, "has_key": bool(p.get("api_key"))}
        for p in config["profiles"]
    ]}


def save_user_profile(content: str) -> dict:
    with _lock:
        config = read_config()
        config["user_profile"] = content.strip()[:4000]
        write_config(config)
    return public_config()


def resolve_profile(profile: ModelProfile) -> dict:
    result = profile.model_dump()
    previous = next((p for p in read_config()["profiles"] if p["id"] == profile.id), None)
    if profile.api_key is None:
        # Never forward a retained credential to a newly typed endpoint.
        result["api_key"] = previous.get("api_key", "") if previous and previous["base_url"] == profile.base_url else ""
    else:
        result["api_key"] = profile.api_key.strip()
    return result


def save_profile(profile: ModelProfile) -> dict:
    with _lock:
        config = read_config()
        resolved = resolve_profile(profile)
        config["profiles"] = [p for p in config["profiles"] if p["id"] != profile.id] + [resolved]
        write_config(config)
    return public_config()


def select_profile(profile_id: str | None) -> dict:
    with _lock:
        config = read_config()
        if profile_id is not None:
            profile = next((p for p in config["profiles"] if p["id"] == profile_id), None)
            if not profile or not profile["model"]:
                raise ValueError("请先保存配置并填写模型 ID")
        config["active_id"] = profile_id
        write_config(config)
    return public_config()


def delete_profile(profile_id: str) -> dict:
    with _lock:
        config = read_config()
        if config["active_id"] == profile_id:
            raise ValueError("请先切换到其他模型或演示模式，再删除当前模型")
        config["profiles"] = [p for p in config["profiles"] if p["id"] != profile_id]
        write_config(config)
    return public_config()


def profile_settings(profile: dict):
    snapshot = copy.copy(settings)
    snapshot.llm_base_url = profile["base_url"]
    snapshot.llm_api_key = profile.get("api_key", "")
    snapshot.llm_model = profile["model"]
    snapshot.llm_timeout = profile["timeout"]
    snapshot.llm_temperature = profile.get("temperature", 0.3)
    snapshot.llm_json_mode = profile.get("json_mode", True)
    snapshot.allow_no_key = True  # Local endpoints may not require authentication.
    return snapshot


def runtime_settings():
    config = read_config()
    active = next((p for p in config["profiles"] if p["id"] == config["active_id"]), None)
    if active:
        return profile_settings(active)
    snapshot = copy.copy(settings)
    snapshot.llm_base_url = snapshot.llm_api_key = snapshot.llm_model = ""
    return snapshot
