"""数据导出 / 导入（版本化 JSON）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AcceptanceCriterion,
    Assessment,
    Attempt,
    ChatMessage,
    Concept,
    ConceptRelation,
    FormatSpec,
    GenerationJob,
    GoalAssessment,
    GoalMaterial,
    KnowledgeProposal,
    LearningGoal,
    LearningPlan,
    ModelCallLog,
    PlanStep,
    PracticeTask,
    Reflection,
    Source,
    TrainingRecord,
    Tutorial,
    TutorialVersion,
)

EXPORT_VERSION = 1

# 插入顺序（父表在前）；删除时倒序
TABLES = [
    ("format_specs", FormatSpec),
    ("learning_goals", LearningGoal),
    ("goal_assessments", GoalAssessment),
    ("goal_materials", GoalMaterial),
    ("learning_plans", LearningPlan),
    ("plan_steps", PlanStep),
    ("acceptance_criteria", AcceptanceCriterion),
    ("tutorials", Tutorial),
    ("tutorial_versions", TutorialVersion),
    ("practice_tasks", PracticeTask),
    ("attempts", Attempt),
    ("assessments", Assessment),
    ("reflections", Reflection),
    ("concepts", Concept),
    ("concept_relations", ConceptRelation),
    ("sources", Source),
    ("knowledge_proposals", KnowledgeProposal),
    ("chat_messages", ChatMessage),
    ("generation_jobs", GenerationJob),
    ("model_call_logs", ModelCallLog),
    ("training_records", TrainingRecord),
]


def _row_dict(model, row) -> dict:
    return {col.name: getattr(row, col.name) for col in model.__table__.columns}


def export_data(db: Session) -> dict:
    data = {}
    for name, model in TABLES:
        rows = db.query(model).all()
        data[name] = [_row_dict(model, r) for r in rows]
    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def _backup_path() -> Path:
    """导入前的兜底备份路径。

    必须用 settings.backup_dir：它已锚定到后端目录。此前这里写的是相对 CWD 的
    Path("data") / "backups"，从仓库根启动就把备份写到仓库根的 data/backups，
    与 goals_service.purge_goal 用的 settings.backup_dir 分家（仓库根那个 data/
    目录里躺着一个 0 字节 aiedu.db 和 20 份孤儿备份，就是这么来的）。
    """
    base = Path(settings.backup_dir)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return base / f"aiedu-backup-{stamp}.json"


def import_data(db: Session, payload: dict, force: bool = False) -> dict:
    if payload.get("version") != EXPORT_VERSION:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_version", "message": f"仅支持导入 version={EXPORT_VERSION} 的文件"},
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail={"code": "bad_payload", "message": "导入文件缺少 data 字段"})

    # 校验：每个已知表存在且为列表；未知表忽略
    for name, model in TABLES:
        rows = data.get(name, [])
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail={"code": "bad_payload", "message": f"表 {name} 数据格式错误"})
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                raise HTTPException(status_code=400, detail={"code": "bad_payload", "message": f"表 {name} 存在非法记录"})

    # 安全阀：导入会用备份完全覆盖当前数据。若当前有知识节点而备份里没有，
    # 多半是拿旧备份恢复——必须先明确确认，避免静默清空知识网络。
    incoming_concepts = data.get("concepts", [])
    current_concepts = db.query(Concept).count()
    current_relations = db.query(ConceptRelation).count()
    incoming_relations = data.get("concept_relations", [])
    if not force and (current_concepts or current_relations) and not (incoming_concepts or incoming_relations):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "knowledge_would_be_cleared",
                "message": (
                    f"该备份不含知识网络数据（0 概念），导入会清空现有的 "
                    f"{current_concepts} 个概念 / {current_relations} 条关系。"
                    "如确认要覆盖，请再次确认导入（force=true）。"
                ),
            },
        )

    # 先备份当前数据
    backup_file = _backup_path()
    backup_file.write_text(json.dumps(export_data(db), ensure_ascii=False), encoding="utf-8")

    try:
        for name, model in reversed(TABLES):
            db.query(model).delete()
        counts = {}
        for name, model in TABLES:
            rows = data.get(name, [])
            columns = {c.name for c in model.__table__.columns}
            for row in rows:
                values = {k: v for k, v in row.items() if k in columns}
                db.execute(model.__table__.insert().values(**values))
            counts[name] = len(rows)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail={"code": "import_failed", "message": f"导入失败，已回滚：{exc}"},
        ) from exc

    return {"ok": True, "counts": counts, "backup": str(backup_file)}
