"""审计回归测试：修复「训练数据接口 500」与三处 CWD 相对路径 / 缺列缺陷。

对应 PROJECT_AUDIT.md 的问题 A–F。每条都先证明「缺陷可被触发」，再证明「已修复」，
避免测试只是重述实现。
"""

import os
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------- 索引与排序

def _indexes(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)
    )]


def test_created_at_index_exists_on_sort_heavy_tables(client):
    """training_records / model_call_logs 的排序键必须有索引。

    没有索引时 SQLite 走磁盘 TEMP B-TREE 排序，临时目录不可写就整条查询
    报 "unable to open database file"（线上表现为 /api/training/records 500）。
    """
    from app.db import engine

    with engine.connect() as conn:
        dbapi = conn.connection.driver_connection
        assert "ix_training_records_created_at" in _indexes(dbapi, "training_records")
        assert "ix_model_call_logs_created_at" in _indexes(dbapi, "model_call_logs")


def test_records_sort_query_plan_avoids_temp_btree(client):
    """排序计划必须走索引，不能出现 USE TEMP B-TREE FOR ORDER BY。"""
    from app.db import engine
    from app.models import TrainingRecord

    for i in range(5):
        client.post("/api/training/feedback", json={"rating": 1, "comment": f"c{i}"})
    cols = ", ".join(c.name for c in TrainingRecord.__table__.columns)
    sql = f"SELECT {cols} FROM training_records ORDER BY created_at DESC LIMIT 50 OFFSET 0"

    with engine.connect() as conn:
        plan = [row[3] for row in conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {sql}")]
    assert plan, "查询计划为空"
    assert not any("TEMP B-TREE" in step for step in plan), plan
    assert any("ix_training_records_created_at" in step for step in plan), plan


def test_init_db_backfills_missing_index_on_existing_table(client):
    """init_db 必须为「表已存在但缺索引」的老库补上索引。

    create_all 只建缺失的表，对已存在的表不补索引——这正是线上那份 22MB 老库
    拿不到新索引、/api/training/records 一直 500 的原因。
    """
    from app.db import engine, init_db

    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_training_records_created_at")

    def _has_index() -> bool:
        with engine.connect() as conn:
            return conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='index' "
                "AND name='ix_training_records_created_at'"
            ).fetchone() is not None

    assert not _has_index(), "前置条件：索引应已被删除"
    init_db()  # 幂等：可重复执行，第二次不能报错
    init_db()
    assert _has_index(), "init_db 未为已存在的表补建索引"


def test_index_migration_keeps_partial_unique_predicate(client):
    """补索引不得把部分唯一索引的 WHERE 谓词丢掉。

    uq_format_specs_default 是 UNIQUE ... WHERE is_default = 1；若被重建成全表唯一，
    「只能有一个默认规范」就会退化：第二条 is_default=0 的记录直接插不进去。
    """
    from app.db import _migrate_sqlite_indexes, engine

    _migrate_sqlite_indexes()
    _migrate_sqlite_indexes()  # 第二次不能报错

    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_format_specs_default'"
        ).fetchone()
    assert row is not None, "默认规范唯一索引丢失"
    sql = row[0] or ""
    assert "WHERE" in sql.upper(), f"部分索引谓词丢失：{sql}"


def test_format_specs_allow_multiple_non_default(client):
    """部分唯一索引仍生效：可存在多个 is_default=0，但默认规范只能有一个。"""
    specs = client.get("/api/format-specs").json()
    assert specs, "内置规范未就绪"
    assert sum(1 for s in specs if s["is_default"]) == 1
    assert sum(1 for s in specs if not s["is_default"]) >= 1


def test_training_records_and_export_work_with_wide_rows(client):
    """端到端：写入带大字段的训练记录后，列表与导出都不再 500。

    这是线上真实故障的最小复现——system_prompt/output_text 撑到需要排序溢出。
    """
    goal = client.post("/api/goals", json={"title": "训练数据排序回归", "domain_key": "cs_it"}).json()
    client.post(f"/api/goals/{goal['id']}/tutorials/quickstart")

    blob = "内容" * 4000  # ~8k 字符，逼出真实排序成本
    from app.db import SessionLocal
    from app.models import TrainingRecord

    db = SessionLocal()
    try:
        for i in range(60):
            db.add(TrainingRecord(
                source_type="material", feature="section", goal_id=goal["id"],
                system_prompt=blob, user_prompt=blob, output_text=blob,
                model_name="test", total_tokens=1000,
            ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/training/records?limit=50&offset=0")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 60
    assert len(body["items"]) == 50

    exported = client.get("/api/training/export?fmt=jsonl")
    assert exported.status_code == 200, exported.text
    lines = [line for line in exported.text.splitlines() if line.strip()]
    assert len(lines) >= 60

    filtered = client.get(f"/api/training/records?source_type=feedback&limit=200")
    assert filtered.status_code == 200, filtered.text


# ------------------------------------------------- CWD 相对路径（模型配置）

def test_model_settings_path_anchored_to_backend_root(monkeypatch, tmp_path):
    """模型配置路径必须锚定后端目录，不随进程 CWD 漂移。

    从仓库根启动时此前会读不到已保存配置：网页上配的 profile 与用户画像凭空消失，
    并悄悄回落到 .env 那一组。
    """
    from app import model_settings as store
    from app.config import BACKEND_ROOT

    monkeypatch.delenv("MODEL_SETTINGS_FILE", raising=False)
    cwd = Path(os.getcwd())
    monkeypatch.chdir(tmp_path)
    try:
        assert store.config_path() == (BACKEND_ROOT / "data" / "model-settings.json").resolve()
    finally:
        monkeypatch.chdir(cwd)


def test_model_settings_env_override_still_absolute(tmp_path, monkeypatch):
    """显式绝对路径（含 conftest 注入的测试文件）不被改写。"""
    from app import model_settings as store

    target = tmp_path / "custom-settings.json"
    monkeypatch.setenv("MODEL_SETTINGS_FILE", str(target))
    assert store.config_path() == target


def test_relative_env_override_anchored_not_cwd(tmp_path, monkeypatch):
    """相对 MODEL_SETTINGS_FILE 也锚定后端目录，保持与其它路径一致。"""
    from app import model_settings as store
    from app.config import BACKEND_ROOT

    monkeypatch.setenv("MODEL_SETTINGS_FILE", "data/relative-probe.json")
    monkeypatch.chdir(tmp_path)
    assert store.config_path() == (BACKEND_ROOT / "data" / "relative-probe.json").resolve()


def test_saved_profiles_survive_cwd_change(client, monkeypatch, tmp_path):
    """相对配置路径下，保存后换 CWD 仍能读到同一份配置（不会分裂成两份）。

    conftest 注入的是绝对路径，锚定与否看不出差别；这里显式换成相对路径，
    才能复现「从仓库根启动 → 网页配的 profile 凭空消失」这一线上症状。
    """
    from app import model_settings as store

    monkeypatch.setenv("MODEL_SETTINGS_FILE", "data/cwd-probe-settings.json")
    monkeypatch.delenv("MODEL_SETTINGS_FILE_ABS", raising=False)
    saved = store.config_path()
    assert saved.is_absolute(), saved
    saved.unlink(missing_ok=True)
    try:
        client.post("/api/settings/models", json={
            "id": "cwdprobe", "name": "CWD 探针", "base_url": "https://model.example/v1",
            "model": "tutor", "api_key": "k", "timeout": 60,
        })
        assert saved.exists(), f"配置未写入锚定路径：{saved}"
        monkeypatch.chdir(tmp_path)
        assert store.config_path() == saved, "换 CWD 后配置路径发生漂移"
        ids = [p["id"] for p in store.read_config()["profiles"]]
        assert "cwdprobe" in ids, f"换 CWD 后配置丢失：{ids}（path={saved}）"
    finally:
        saved.unlink(missing_ok=True)


# ------------------------------------------------- CWD 相对路径（导入备份）

def test_import_backup_written_to_anchored_backup_dir(client, monkeypatch, tmp_path):
    """导入前的兜底备份必须落在 settings.backup_dir，而不是 CWD 下的 data/backups。"""
    from app.config import settings
    from app.services import export as export_service

    payload = client.get("/api/export").json()
    monkeypatch.chdir(tmp_path)
    resp = client.post("/api/import", json=payload)
    assert resp.status_code == 200, resp.text
    backup = Path(resp.json()["backup"])
    assert backup.parent == Path(settings.backup_dir).resolve()
    assert backup.exists(), f"备份未落盘：{backup}"
    assert not (tmp_path / "data").exists(), "又在 CWD 下创建了 data/ 目录"
    assert Path(export_service._backup_path()).parent == Path(settings.backup_dir).resolve()


# ------------------------------------------------------- 缺列（target_type）

def test_user_profile_suggestion_reads_target_type_from_context(client):
    """画像建议读取反馈时不得访问不存在的 TrainingRecord.target_type 列。

    该值存在 context_json 里。此前直接取属性 → AttributeError → 500，
    导致「用户画像建议」在完成第 10 个目标后整块不可用。
    """
    goal = client.post("/api/goals", json={"title": "画像建议回归", "domain_key": "cs_it"}).json()
    for rating, target in ((1, "section"), (-1, "tutorial")):
        resp = client.post("/api/training/feedback", json={
            "goal_id": goal["id"], "rating": rating, "target_type": target, "comment": "x",
        })
        assert resp.status_code == 200, resp.text

    # 未达标时不应触发模型调用，但代码路径必须能安全读反馈
    resp = client.get("/api/settings/models/user-profile-suggestion")
    assert resp.status_code == 200, resp.text
    assert resp.json()["eligible"] is False


def test_user_profile_suggestion_survives_threshold(client, monkeypatch):
    """达标（10 个完成目标）时走完整分支：读反馈 + 生成建议，不得 500。"""
    from app.db import SessionLocal
    from app.models import LearningGoal

    db = SessionLocal()
    try:
        for i in range(10):
            db.add(LearningGoal(title=f"已完成目标 {i}", domain_key="cs_it", completed=True))
        db.commit()
    finally:
        db.close()
    client.post("/api/training/feedback", json={"rating": 1, "target_type": "general"})

    # 不接真实模型：让建议生成本身失败，验证端点仍 200 并带 error 字段（而非 500）
    from app.llm import service as llm_service

    def boom(self, *args, **kwargs):
        raise llm_service.AIServiceError("模拟模型不可用")

    monkeypatch.setattr(llm_service.AIService, "user_profile_suggestion", boom, raising=True)
    resp = client.get("/api/settings/models/user-profile-suggestion")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["eligible"] is True
    assert body["completed_count"] == 10
    assert body["suggestion"] is None
    assert "error" in body

    dismissed = client.post("/api/settings/models/user-profile-suggestion/dismiss")
    assert dismissed.status_code == 200
    assert client.get("/api/settings/models/user-profile-suggestion").json()["eligible"] is False
