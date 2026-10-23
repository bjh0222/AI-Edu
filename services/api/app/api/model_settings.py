"""Model setup, discovery and real generation probes (no demo fallback)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import settings
from .. import model_settings as store
from ..llm.provider import LLMError, OpenAICompatibleProvider


def local_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        raise HTTPException(403, "不允许的来源")


router = APIRouter(prefix="/settings/models", tags=["model settings"], dependencies=[Depends(local_origin)])


@router.get("")
def get_models():
    return store.public_config()


@router.post("")
def save_model(profile: store.ModelProfile):
    if not profile.model:
        raise HTTPException(422, "请填写模型 ID")
    return store.save_profile(profile)


class Selection(BaseModel):
    active_id: str | None = None


class UserProfile(BaseModel):
    content: str = Field(default="", max_length=4000)


@router.put("/user-profile")
def update_user_profile(payload: UserProfile):
    return store.save_user_profile(payload.content)


@router.post("/activate")
def activate(selection: Selection):
    try:
        return store.select_profile(selection.active_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{profile_id}")
def delete_model(profile_id: str):
    try:
        return store.delete_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def provider_for(profile):
    resolved = store.resolve_profile(profile)
    resolved["timeout"] = min(resolved["timeout"], 60)
    return OpenAICompatibleProvider(store.profile_settings(resolved))


@router.post("/discover")
def discover(profile: store.ModelProfile):
    try:
        return {"models": provider_for(profile).list_models()}
    except LLMError as exc:
        raise HTTPException(502, {"code": "model_discovery_failed", "message": str(exc)}) from exc


@router.post("/test")
def test_connection(profile: store.ModelProfile):
    if not profile.model:
        raise HTTPException(422, "请填写模型 ID")
    try:
        provider = provider_for(profile)
        # Structured generation is what the learning pipeline actually requires.
        result, latency, usage = provider.complete_json(
            'You are a connection test. Return only a JSON object with ok=true and reply="连接成功".',
            'Return {"ok":true,"reply":"连接成功"}.',
        )
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("reply"), str):
            raise LLMError("接口已返回，但未通过教程生成所需的结构化 JSON 测试")
        return {"ok": True, "reply": result["reply"][:300], "latency_ms": latency,
                "model": provider.model, "usage": usage, "demo": False}
    except LLMError as exc:
        raise HTTPException(502, {"code": "model_test_failed", "message": str(exc)}) from exc
