"""路由聚合。"""
from __future__ import annotations

from fastapi import APIRouter

from . import chat, goals, health, io, knowledge, materials, practice, training, tutorials, model_settings

api_router = APIRouter(prefix="/api")

api_router.include_router(health.router)
api_router.include_router(model_settings.router)
api_router.include_router(goals.router)
api_router.include_router(materials.router)
api_router.include_router(tutorials.router)
api_router.include_router(practice.router)
api_router.include_router(knowledge.router)
api_router.include_router(chat.router)
api_router.include_router(training.router)
api_router.include_router(io.router)
