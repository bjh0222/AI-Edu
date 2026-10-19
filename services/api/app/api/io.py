"""数据导入 / 导出路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ImportRequest
from ..services import export as export_service

router = APIRouter()


@router.get("/export", tags=["io"])
def export_data(db: Session = Depends(get_db)):
    return export_service.export_data(db)


@router.post("/import", tags=["io"])
def import_data(payload: ImportRequest, db: Session = Depends(get_db)):
    return export_service.import_data(db, payload.model_dump())
