"""教程 / 生成任务 / token 用量路由。"""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..models import GenerationJob
from ..schemas import (
    GenerateOut,
    GoalUsageOut,
    JobOut,
    QuickStartOut,
    SectionDetailOut,
    TokenUsage,
    TutorialOut,
)
from ..services import pipeline as pipeline_service
from ..services import tutorials as tutorials_service
from ..services import usage as usage_service
from .deps import get_ai

router = APIRouter()


def _job_out(job: GenerationJob) -> JobOut:
    return JobOut(
        id=job.id,
        goal_id=job.goal_id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
        error_message=job.error_message or "",
        token_usage=TokenUsage(
            prompt_tokens=job.prompt_tokens or 0,
            completion_tokens=job.completion_tokens or 0,
            total_tokens=job.total_tokens or 0,
            usage_source=job.usage_source or ("estimated" if job.total_tokens else ""),
        ),
    )


@router.post("/goals/{goal_id}/tutorials/generate", response_model=GenerateOut, tags=["tutorials"])
def generate_tutorial(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    result = tutorials_service.generate_outline(db, goal_id, ai)
    job = result["job"]
    return GenerateOut(tutorial=result["tutorial"], job_id=job.id, demo=result["demo"])


@router.post("/goals/{goal_id}/tutorials/quickstart", response_model=QuickStartOut, tags=["tutorials"])
def quickstart_tutorial(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    """一键生成教材：诊断 → 计划 → 验收标准（一键同意）→ 大纲 → 全部章节。"""
    return pipeline_service.quickstart(db, goal_id, ai)


@router.get("/goals/{goal_id}/tutorials", response_model=list[TutorialOut], tags=["tutorials"])
def list_tutorials(goal_id: str, db: Session = Depends(get_db)):
    return tutorials_service.list_tutorials(db, goal_id)


@router.get("/tutorials/{tutorial_id}", response_model=TutorialOut, tags=["tutorials"])
def get_tutorial(tutorial_id: str, db: Session = Depends(get_db)):
    return tutorials_service.get_tutorial(db, tutorial_id)


@router.get("/tutorials/{tutorial_id}/sections/{section_id}", response_model=SectionDetailOut, tags=["tutorials"])
def get_section(tutorial_id: str, section_id: str, db: Session = Depends(get_db)):
    """章节详情：供「教程生成每一步都能点进详情」的深层链接使用。"""
    return tutorials_service.get_section(db, tutorial_id, section_id)


@router.post("/tutorials/{tutorial_id}/sections/generate", response_model=GenerateOut, tags=["tutorials"])
def generate_sections(tutorial_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    result = tutorials_service.start_sections(db, tutorial_id, ai)
    job = result["job"]
    return GenerateOut(tutorial=result["tutorial"], job_id=job.id, demo=result["demo"])


@router.post("/tutorials/{tutorial_id}/sections/{section_id}/regenerate", response_model=TutorialOut, tags=["tutorials"])
def regenerate_section(tutorial_id: str, section_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    result = tutorials_service.regenerate_section(db, tutorial_id, section_id, ai)
    return result["tutorial"]


@router.post("/tutorials/{tutorial_id}/restore/{version}", response_model=TutorialOut, tags=["tutorials"])
def restore_version(tutorial_id: str, version: int, db: Session = Depends(get_db)):
    return tutorials_service.restore_version(db, tutorial_id, version)


@router.get("/tutorials/{tutorial_id}/export", tags=["tutorials"])
def export_tutorial(tutorial_id: str, db: Session = Depends(get_db)):
    """导出当前教程版本为 Markdown 文件。"""
    filename, markdown = tutorials_service.export_markdown(db, tutorial_id)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return Response(content=markdown, media_type="text/markdown; charset=utf-8", headers=headers)


@router.get("/goals/{goal_id}/usage", response_model=GoalUsageOut, tags=["tutorials"])
def goal_usage(goal_id: str, db: Session = Depends(get_db)):
    """目标维度的 token 消耗：总用量、按功能、按教程。"""
    return usage_service.goal_usage(db, goal_id)


@router.get("/generation-jobs/{job_id}", response_model=JobOut, tags=["tutorials"])
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "生成任务不存在"})
    return _job_out(job)


@router.get("/generation-jobs/{job_id}/events", tags=["tutorials"])
def job_events(job_id: str, db: Session = Depends(get_db)):
    """SSE：回放生成任务状态（同步生成完成后的一次性快照 + 完成事件）。"""
    job = db.get(GenerationJob, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "生成任务不存在"})

    snapshot = {
        "id": job.id,
        "goal_id": job.goal_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error_code": job.error_code,
        "token_usage": {
            "prompt_tokens": job.prompt_tokens or 0,
            "completion_tokens": job.completion_tokens or 0,
            "total_tokens": job.total_tokens or 0,
        },
    }

    def event_stream():
        yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
