"""教程 / 生成任务路由。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm.service import AIService
from ..models import GenerationJob
from ..schemas import GenerateOut, JobOut, SectionGenerateRequest, TutorialOut
from ..services import tutorials as tutorials_service
from .deps import get_ai

router = APIRouter()


@router.post("/goals/{goal_id}/tutorials/generate", response_model=GenerateOut, tags=["tutorials"])
def generate_tutorial(goal_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    result = tutorials_service.generate_outline(db, goal_id, ai)
    job = result["job"]
    return GenerateOut(tutorial=result["tutorial"], job_id=job.id, demo=result["demo"])


@router.get("/goals/{goal_id}/tutorials", response_model=list[TutorialOut], tags=["tutorials"])
def list_tutorials(goal_id: str, db: Session = Depends(get_db)):
    return tutorials_service.list_tutorials(db, goal_id)


@router.get("/tutorials/{tutorial_id}", response_model=TutorialOut, tags=["tutorials"])
def get_tutorial(tutorial_id: str, db: Session = Depends(get_db)):
    return tutorials_service.get_tutorial(db, tutorial_id)


@router.post("/tutorials/{tutorial_id}/sections/generate", response_model=GenerateOut, tags=["tutorials"])
def generate_sections(tutorial_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    result = tutorials_service.generate_sections(db, tutorial_id, ai)
    job = result["job"]
    return GenerateOut(tutorial=result["tutorial"], job_id=job.id, demo=result["demo"])


@router.post("/tutorials/{tutorial_id}/sections/{section_id}/regenerate", response_model=TutorialOut, tags=["tutorials"])
def regenerate_section(tutorial_id: str, section_id: str, db: Session = Depends(get_db), ai: AIService = Depends(get_ai)):
    result = tutorials_service.regenerate_section(db, tutorial_id, section_id, ai)
    return result["tutorial"]


@router.post("/tutorials/{tutorial_id}/restore/{version}", response_model=TutorialOut, tags=["tutorials"])
def restore_version(tutorial_id: str, version: int, db: Session = Depends(get_db)):
    return tutorials_service.restore_version(db, tutorial_id, version)


@router.get("/generation-jobs/{job_id}", response_model=JobOut, tags=["tutorials"])
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "生成任务不存在"})
    return JobOut(
        id=job.id, goal_id=job.goal_id, job_type=job.job_type, status=job.status,
        progress=job.progress, stage=job.stage, error_code=job.error_code,
    )


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
    }

    def event_stream():
        yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
