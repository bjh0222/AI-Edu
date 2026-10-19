"""数据库：引擎 / 会话 / 初始化。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
        if raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册

    Base.metadata.create_all(bind=engine)
