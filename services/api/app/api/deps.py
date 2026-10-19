"""路由公共依赖。"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService


def get_ai(db: Session = Depends(get_db)) -> AIService:
    return AIService(db)
