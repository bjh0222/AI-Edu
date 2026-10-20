"""数据库：引擎 / 会话 / 初始化。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
        if raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 连接级设置
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

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
    _migrate_sqlite_columns()


def _migrate_sqlite_columns() -> None:
    """轻量迁移：为已存在的 SQLite 表补上新增列（create_all 不会改旧表）。

    只处理「新增可空列 / 带常量默认值的列」；不处理删列、改类型等破坏性变更。
    """
    if not _is_sqlite:
        return
    with engine.begin() as conn:
        existing_tables = {
            row[0]
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            columns = {
                row[1]
                for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")').fetchall()
            }
            for column in table.columns:
                if column.name in columns:
                    continue
                ddl = (
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                    f"{column.type.compile(dialect=engine.dialect)}"
                )
                default = getattr(column, "default", None)
                arg = getattr(default, "arg", None)
                if arg is not None and not callable(arg):
                    if isinstance(arg, bool):
                        ddl += f" DEFAULT {1 if arg else 0}"
                    elif isinstance(arg, (int, float)):
                        ddl += f" DEFAULT {arg}"
                    elif isinstance(arg, str):
                        ddl += " DEFAULT '" + arg.replace("'", "''") + "'"
                conn.exec_driver_sql(ddl)
