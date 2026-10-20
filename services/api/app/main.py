"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.router import api_router
from .config import settings
from .db import init_db
from .llm.service import AIServiceError


def _sweep_stale_jobs() -> None:
    """启动时把上次进程中断遗留的排队/运行中任务标记为失败，避免界面永久转圈。"""
    from .db import SessionLocal
    from .models import GenerationJob

    db = SessionLocal()
    try:
        stale = (
            db.query(GenerationJob)
            .filter(GenerationJob.status.in_(["queued", "running"]))
            .all()
        )
        for job in stale:
            job.status = "failed"
            job.error_code = "server_restart"
        if stale:
            db.commit()
    except Exception:  # noqa: BLE001  清理失败不阻塞启动
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _sweep_stale_jobs()
    yield


app = FastAPI(title="AI Edu API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(AIServiceError)
async def ai_error_handler(_, exc: AIServiceError):
    return JSONResponse(status_code=502, content={"code": "llm_error", "message": str(exc)})
