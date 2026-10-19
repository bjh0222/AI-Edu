"""健康检查。"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(demo=not settings.llm_configured, llm_configured=settings.llm_configured)
