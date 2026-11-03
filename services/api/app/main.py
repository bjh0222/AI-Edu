"""FastAPI 应用入口。"""
from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.router import api_router
from .config import settings
from .db import init_db
from .llm.service import AIServiceError

logger = logging.getLogger("aiedu")
if not logger.handlers:
    # uvicorn 只配置自己的 logger，应用日志默认落到未配置的 root（INFO 会被丢弃）。
    # 显式挂一个 handler：启动时的库路径、后台线程失败原因才看得见。
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def _log_unhandled(exc: BaseException) -> None:
    """把未捕获异常写入 data/errors.log，便于事后定位 500 根因。"""
    try:
        log_dir = Path(getattr(settings, "backup_dir", "data/backups")).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "errors.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write("=" * 60 + "\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            fh.write("\n")
    except OSError:
        pass
    logger.exception("未捕获异常", exc_info=exc)


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


def _ensure_format_specs() -> None:
    from .db import SessionLocal
    from .services.format_specs import ensure_builtin_specs

    db = SessionLocal()
    try:
        ensure_builtin_specs(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _ensure_format_specs()
    # 把实际使用的库路径打进日志：从不同目录启动时不会再悄悄换库
    logger.info("数据库：%s", settings.database_url)
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
async def ai_error_handler(_: Request, exc: AIServiceError):
    # 模型调用失败（欠费 / 认证 / 限流 / 超时…）统一 502。此前这里静默返回，
    # errors.log 里查不到任何痕迹，用户只看到客户端一句通用报错——补一行日志。
    logger.warning("模型调用失败（502）：%s", exc)
    return JSONResponse(status_code=502, content={"code": "llm_error", "message": str(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    """未捕获异常：写完整堆栈到 data/errors.log，并返回可读错误（前端不再只显示 500）。"""
    _log_unhandled(exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": f"服务内部错误：{exc.__class__.__name__}: {str(exc)[:300]}",
            }
        },
    )
