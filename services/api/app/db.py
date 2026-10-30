"""数据库：引擎 / 会话 / 初始化。"""
from __future__ import annotations

import logging
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
    _migrate_sqlite_indexes()


def _migrate_sqlite_indexes() -> None:
    """轻量迁移：为已存在的 SQLite 表补上模型里声明的索引。

    create_all 只建缺失的表，对已存在的表既不补列也不补索引，所以老库拿不到后来
    新增的 index=True。缺索引不只是慢：按未建索引的 created_at 排序时，SQLite 要把
    整表（含 system_prompt / output_text 这类几万字的大字段）写进磁盘 TEMP B-TREE，
    临时目录不可写就整条查询报 "unable to open database file" 并 500。

    用 SQLAlchemy 自己的 CreateIndex 编译 DDL，而不是手拼字符串：部分索引
    （format_specs 的 uq_format_specs_default 带 WHERE is_default = 1）手拼会丢掉
    WHERE 谓词，把「只能有一个默认规范」的唯一约束悄悄放宽成全表唯一。

    CREATE INDEX IF NOT EXISTS 只读原表、不排序溢出，可重复执行。单个索引失败只记日志
    （例如老库里已有违反唯一谓词的脏数据），不阻塞启动。
    """
    if not _is_sqlite:
        return
    from sqlalchemy.schema import CreateIndex

    logger = logging.getLogger("aiedu")
    with engine.begin() as conn:
        existing_tables = {
            row[0]
            for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            for index in table.indexes:
                if not index.columns:
                    continue
                try:
                    conn.execute(CreateIndex(index, if_not_exists=True))
                except Exception as exc:  # noqa: BLE001  补索引失败不阻塞启动
                    logger.warning("补建索引失败：%s.%s：%s", table.name, index.name, exc)


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
