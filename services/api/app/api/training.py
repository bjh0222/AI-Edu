"""测试版训练数据路由：用户反馈、记录列表、统计与导出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import TrainingFeedbackIn, TrainingListOut, TrainingRecordOut, TrainingStatsOut
from ..services import training as training_service

router = APIRouter()


@router.post("/training/feedback", response_model=TrainingRecordOut, tags=["training"])
def submit_feedback(payload: TrainingFeedbackIn, db: Session = Depends(get_db)):
    """收集用户对生成材料 / 教程 / 章节 / 整体流程的反馈（持久化，供后续预训练）。"""
    return training_service.submit_feedback(db, payload)


@router.get("/training/records", response_model=TrainingListOut, tags=["training"])
def list_records(
    source_type: str | None = Query(default=None),
    goal_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return training_service.list_records(
        db, source_type=source_type, goal_id=goal_id, limit=limit, offset=offset
    )


@router.get("/training/stats", response_model=TrainingStatsOut, tags=["training"])
def training_stats(db: Session = Depends(get_db)):
    return training_service.stats(db)


@router.get("/training/export", tags=["training"])
def export_training_data(
    source_type: str | None = Query(default=None),
    goal_id: str | None = Query(default=None),
    exclude_demo: bool = Query(default=False),
    fmt: str = Query(default="jsonl", pattern="^(jsonl|json)$"),
    db: Session = Depends(get_db),
):
    """导出训练数据（默认 JSONL，一行一个样本）。"""
    filename, content, media_type = training_service.export_dataset(
        db, source_type=source_type, goal_id=goal_id, exclude_demo=exclude_demo, fmt=fmt
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": training_service.export_disposition(filename)},
    )
