"""上下文答疑路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..schemas import ChatRequest, ChatResponse
from ..services import chat as chat_service
from .deps import get_ai

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(payload: ChatRequest, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    return chat_service.chat(db, payload, ai)
