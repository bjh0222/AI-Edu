"""数据导入 / 导出路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ImportRequest
from ..services import export as export_service

router = APIRouter()


@router.get("/export", tags=["io"])
def export_data(db: Session = Depends(get_db)):
    return export_service.export_data(db)


@router.post("/import", tags=["io"])
def import_data(
    payload: ImportRequest,
    force: bool = Query(default=False, description="备份不含知识数据时仍需覆盖（用户明确确认）"),
    db: Session = Depends(get_db),
):
    return export_service.import_data(db, payload.model_dump(), force=force)
