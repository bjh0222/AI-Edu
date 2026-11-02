"""SQLAlchemy 数据模型（v2.0 §4 的子集，v1 闭环所需）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, String, Text, text

from .db import Base

# 能力层级默认值（learning.levels.DEFAULT_LEVEL），直接用字符串避免循环导入
CAPABILITY_DEFAULT = "L2"


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = Column(String(40), default=lambda: _now().isoformat())
    updated_at = Column(String(40), default=lambda: _now().isoformat(), onupdate=lambda: _now().isoformat())


class LearningGoal(Base, TimestampMixin):
    __tablename__ = "learning_goals"

    id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(String(200), nullable=False)
    domain_key = Column(String(50), nullable=False, default="computer_cli")
    motivation = Column(Text, default="")
    application_context = Column(Text, default="")
    current_level = Column(Text, default="")
    time_budget = Column(String(100), default="")
    # 用户针对本次目标填写的硬性约束：注入所有生成阶段 prompt，违反任一条即视为交付不合格
    hard_constraints = Column(Text, default="")
    # 能力层级：L1 基础理解 / L2 独立应用 / L3 深入掌握与迁移（旧数据回退 L2）
    capability_level = Column(String(10), default=CAPABILITY_DEFAULT)
    # 是否生成独立的额外练习文件（默认关闭；教程内的必要练习不受此开关影响）
    generate_extra_exercises = Column(Boolean, default=False)
    # 生成挡位：fast / standard / deep；旧数据回退 standard
    generation_tier = Column(String(20), default="standard")
    # 大纲前选定并冻结的格式规范；后台任务只读快照，不重读可变模板
    format_spec_id = Column(String(36), default="", index=True)
    format_spec_source = Column(String(30), default="")
    format_spec_match_note = Column(Text, default="")
    format_spec_snapshot = Column(Text, default="")
    status = Column(String(30), default="goal_definition")
    user_notes = Column(Text, default="")
    archived = Column(Boolean, default=False)
    completed = Column(Boolean, default=False)
    completed_at = Column(String(40), default="")


class FormatSpec(Base, TimestampMixin):
    """可复用交付规范：结构化字段与自由 Markdown 补充分开保存。"""

    __tablename__ = "format_specs"
    __table_args__ = (
        Index(
            "uq_format_specs_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    scene = Column(String(80), default="")
    is_builtin = Column(Boolean, default=False)
    is_default = Column(Boolean, default=False)
    version = Column(Integer, default=1)

    applicable_tasks = Column(Text, default="")
    applicable_intents = Column(Text, default="[]")
    excluded_scenarios = Column(Text, default="[]")
    excluded_intents = Column(Text, default="[]")
    trigger_keywords = Column(Text, default="[]")
    excluded_keywords = Column(Text, default="[]")
    allow_keyword_trigger = Column(Boolean, default=True)
    allow_semantic_recommendation = Column(Boolean, default=True)
    allow_explicit_selection = Column(Boolean, default=True)

    target_reader = Column(Text, default="")
    output_goal = Column(Text, default="")
    deliverables = Column(Text, default="[]")
    content_structure = Column(Text, default="")
    format_rules = Column(Text, default="")
    required_rules = Column(Text, default="")
    forbidden_rules = Column(Text, default="")
    suggested_rules = Column(Text, default="")
    flexible_rules = Column(Text, default="")
    acceptance_criteria = Column(Text, default="")
    reference_examples = Column(Text, default="")
    custom_markdown = Column(Text, default="")


class GoalAssessment(Base, TimestampMixin):
    __tablename__ = "goal_assessments"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    benefits = Column(Text, default="")
    prerequisites = Column(Text, default="")
    alternatives = Column(Text, default="")
    assumptions = Column(Text, default="")
    uncertainties = Column(Text, default="")
    recommendation = Column(Text, default="")
    user_decision = Column(String(30), default="")
    decision_reason = Column(Text, default="")


class LearningPlan(Base, TimestampMixin):
    __tablename__ = "learning_plans"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    version = Column(Integer, default=1)
    status = Column(String(30), default="draft")
    generated_at = Column(String(40), default="")
    user_edits = Column(Text, default="")


class PlanStep(Base, TimestampMixin):
    __tablename__ = "plan_steps"

    id = Column(String(36), primary_key=True, default=_uuid)
    plan_id = Column(String(36), ForeignKey("learning_plans.id"), index=True)
    order_index = Column(Integer, default=0)
    title = Column(String(200), default="")
    objective = Column(Text, default="")
    status = Column(String(30), default="pending")
    dependencies = Column(Text, default="[]")  # JSON list
    estimated_effort = Column(String(100), default="")
    completion_evidence_refs = Column(Text, default="[]")  # JSON list


class AcceptanceCriterion(Base, TimestampMixin):
    __tablename__ = "acceptance_criteria"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    plan_step_id = Column(String(36), ForeignKey("plan_steps.id"), nullable=True)
    statement = Column(Text, nullable=False)
    conditions = Column(Text, default="")
    evidence_type = Column(String(50), default="product")
    pass_rule = Column(Text, default="")
    status = Column(String(30), default="pending")  # pending / confirmed / rejected
    rationale = Column(Text, default="")


class Tutorial(Base, TimestampMixin):
    __tablename__ = "tutorials"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    plan_step_id = Column(String(36), ForeignKey("plan_steps.id"), nullable=True)
    title = Column(String(200), default="")
    status = Column(String(30), default="outline")  # outline / drafted / reviewed
    current_version_id = Column(String(36), nullable=True)
    # 生成状态在 Tutorial / TutorialVersion / GenerationJob；以下只记录单向交付结果
    delivery_status = Column(String(20), default="")
    delivery_path = Column(Text, default="")
    delivery_version = Column(Integer, default=0)


class TutorialVersion(Base):
    __tablename__ = "tutorial_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    tutorial_id = Column(String(36), ForeignKey("tutorials.id"), index=True)
    version = Column(Integer, default=1)
    content_json = Column(Text, default="{}")  # {outline:[], sections:[]}
    prompt_version = Column(String(30), default="v1")
    model_provider = Column(String(50), default="demo")
    model_name = Column(String(100), default="demo")
    quality_report = Column(Text, default="{}")  # JSON
    source_refs = Column(Text, default="[]")
    # 生成本版本消耗的 token（真实 usage 或按字符估算，见 usage_source）
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    usage_source = Column(String(20), default="")
    created_at = Column(String(40), default=lambda: _now().isoformat())


class PracticeTask(Base, TimestampMixin):
    __tablename__ = "practice_tasks"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    plan_step_id = Column(String(36), ForeignKey("plan_steps.id"), nullable=True)
    tutorial_id = Column(String(36), ForeignKey("tutorials.id"), nullable=True)
    title = Column(String(200), default="")
    instructions = Column(Text, default="")
    task_type = Column(String(50), default="practice")
    expected_artifact = Column(Text, default="")
    validation_rule = Column(Text, default="")
    status = Column(String(30), default="todo")  # todo / doing / done


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(String(36), primary_key=True, default=_uuid)
    task_id = Column(String(36), ForeignKey("practice_tasks.id"), index=True)
    artifact = Column(Text, default="")
    artifact_type = Column(String(50), default="text")
    result = Column(Text, default="")
    errors = Column(Text, default="")
    help_level = Column(String(10), default="A1")  # A0-A3
    user_explanation = Column(Text, default="")
    feedback = Column(Text, default="{}")  # JSON
    created_at = Column(String(40), default=lambda: _now().isoformat())


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    task_id = Column(String(36), ForeignKey("practice_tasks.id"), nullable=True)
    assessment_type = Column(String(30), default="mixed")  # independent / variant / mixed
    rubric = Column(Text, default="[]")  # JSON
    result = Column(Text, default="")
    confidence = Column(String(20), default="")
    evidence_refs = Column(Text, default="[]")
    weak_points = Column(Text, default="")
    created_at = Column(String(40), default=lambda: _now().isoformat())


class Reflection(Base):
    __tablename__ = "reflections"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    summary = Column(Text, default="")
    learned_capabilities = Column(Text, default="")
    unresolved_gaps = Column(Text, default="")
    next_actions = Column(Text, default="")
    evidence_refs = Column(Text, default="[]")
    created_at = Column(String(40), default=lambda: _now().isoformat())


class Concept(Base, TimestampMixin):
    __tablename__ = "concepts"

    id = Column(String(36), primary_key=True, default=_uuid)
    domain_key = Column(String(50), default="general")
    title = Column(String(200), nullable=False)
    # 去重键：规范化标题（小写、去空白与标点），同名/别名视为同一概念
    title_norm = Column(String(240), default="", index=True)
    # 别名 JSON list：跨学科概念在不同领域可能有不同叫法，检索/去重时合并
    aliases = Column(Text, default="[]")
    # 多对多领域：JSON list；domain_key 保留主领域（第一个），兼容旧数据
    domain_keys = Column(Text, default="[]")
    # 服务的学习目标 JSON list：一个概念可同时服务于多个目标
    goal_ids = Column(Text, default="[]")
    definition = Column(Text, default="")
    status = Column(String(20), default="active")  # active / archived
    source_refs = Column(Text, default="[]")
    last_reviewed_at = Column(String(40), default="")


class ConceptRelation(Base, TimestampMixin):
    __tablename__ = "concept_relations"

    id = Column(String(36), primary_key=True, default=_uuid)
    from_concept_id = Column(String(36), ForeignKey("concepts.id"), index=True)
    to_concept_id = Column(String(36), ForeignKey("concepts.id"), index=True)
    relation_type = Column(String(30), default="related")
    # proposed(待核实) / confirmed(已确认) / conflict(存在冲突) / rejected(已驳回) / revoked(已撤销)
    status = Column(String(20), default="proposed")
    rationale = Column(Text, default="")
    source_refs = Column(Text, default="[]")
    evidence_refs = Column(Text, default="[]")
    confidence = Column(Float, default=0.5)
    # manual / tutorial / ai_proposal：关系来源，决定默认可信状态
    origin = Column(String(20), default="manual")
    # 变更历史 JSON list：[{at, action, note}]，重要修改可追溯
    history = Column(Text, default="[]")


class GoalMaterial(Base, TimestampMixin):
    """学习目标下用户上传的参考资料 / 例题来源。

    文件本体落在 MATERIALS_DIR/{goal_id}/{id}{ext}，这里只存元数据与正文摘录，
    摘录供「价值诊断 / 学习计划 / 教程生成」的 prompt 注入使用。
    """

    __tablename__ = "goal_materials"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    kind = Column(String(20), default="reference")  # reference / example_source
    filename = Column(String(255), default="")
    stored_name = Column(String(255), default="")
    ext = Column(String(20), default="")
    content_type = Column(String(120), default="")
    size = Column(Integer, default=0)
    status = Column(String(20), default="ready")  # ready / failed
    error_message = Column(Text, default="")
    # ok / empty / unsupported / failed / truncated（truncated = 原文超过入库上限被截断）
    extract_status = Column(String(20), default="pending")
    text_excerpt = Column(Text, default="")
    # 实际入库 / 实际注入的字数（可能被 MAX_EXCERPT_CHARS 截断）
    char_count = Column(Integer, default=0)
    # 文件原文字数（未截断）。source_char_count > char_count 即为被截断，
    # 旧库由 _migrate_sqlite_columns 自动补列，默认 0 表示「未知 / 未截断」。
    source_char_count = Column(Integer, default=0)
    note = Column(Text, default="")


class Source(Base):
    __tablename__ = "sources"

    id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(String(200), default="")
    url = Column(String(500), default="")
    source_type = Column(String(50), default="web")
    publisher = Column(String(100), default="")
    reliability_note = Column(Text, default="")
    accessed_at = Column(String(40), default="")


class KnowledgeProposal(Base, TimestampMixin):
    __tablename__ = "knowledge_proposals"

    id = Column(String(36), primary_key=True, default=_uuid)
    proposal_type = Column(String(30), default="relation")  # concept / relation / status_update
    payload = Column(Text, default="{}")  # JSON
    rationale = Column(Text, default="")
    evidence_refs = Column(Text, default="[]")
    status = Column(String(20), default="pending")  # pending / confirmed / rejected / edited
    reviewed_at = Column(String(40), default="")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), nullable=True, index=True)
    tutorial_id = Column(String(36), nullable=True)
    section_id = Column(String(36), nullable=True)
    task_id = Column(String(36), nullable=True)
    role = Column(String(20), default="user")  # user / assistant
    content = Column(Text, default="")
    created_at = Column(String(40), default=lambda: _now().isoformat())


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    goal_id = Column(String(36), ForeignKey("learning_goals.id"), index=True)
    job_type = Column(String(50), default="tutorial")
    status = Column(String(20), default="queued")  # queued / running / done / failed
    progress = Column(Integer, default=0)
    stage = Column(String(200), default="")
    error_code = Column(String(50), default="")
    error_message = Column(Text, default="")
    retry_count = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    usage_source = Column(String(20), default="")
    created_at = Column(String(40), default=lambda: _now().isoformat())
    updated_at = Column(String(40), default=lambda: _now().isoformat(), onupdate=lambda: _now().isoformat())


class ModelCallLog(Base):
    __tablename__ = "model_call_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    feature = Column(String(50), default="")
    provider = Column(String(50), default="")
    model = Column(String(100), default="")
    goal_id = Column(String(36), nullable=True, index=True)
    tutorial_id = Column(String(36), nullable=True, index=True)
    job_id = Column(String(36), nullable=True)
    latency_ms = Column(Integer, default=0)
    status = Column(String(20), default="ok")
    error_category = Column(String(50), default="")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    usage_source = Column(String(20), default="")  # provider / estimated
    # 同 TrainingRecord：goal_usage 按 created_at 聚合，建索引避免磁盘 TEMP B-TREE
    created_at = Column(String(40), default=lambda: _now().isoformat(), index=True)


class TrainingRecord(Base):
    """测试版训练数据：生成材料（material）与用户反馈（feedback）。"""

    __tablename__ = "training_records"

    id = Column(String(36), primary_key=True, default=_uuid)
    source_type = Column(String(20), default="material", index=True)  # material / feedback
    feature = Column(String(50), default="")  # diagnose / plan / criteria / outline / section / ...
    goal_id = Column(String(36), nullable=True, index=True)
    tutorial_id = Column(String(36), nullable=True, index=True)
    section_id = Column(String(36), nullable=True)
    system_prompt = Column(Text, default="")
    user_prompt = Column(Text, default="")
    output_text = Column(Text, default="")
    model_provider = Column(String(50), default="")
    model_name = Column(String(100), default="")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    usage_source = Column(String(20), default="")
    rating = Column(Integer, nullable=True)  # feedback: 1 有帮助 / -1 需改进
    tags = Column(Text, default="[]")
    comment = Column(Text, default="")
    context_json = Column(Text, default="{}")
    # 排序键必须建索引：训练数据列表 / 导出都按 created_at 排序，而 system_prompt /
    # output_text 单行就有几万字。没有索引时 SQLite 会把整表连同大字段一起塞进
    # 磁盘 TEMP B-TREE 再排序，一旦临时文件目录不可写就整条查询 500
    # （sqlite3.OperationalError: unable to open database file）。有索引则走索引序，
    # 不产生临时文件，分页也从「全表排序」变成 O(limit)。
    created_at = Column(String(40), default=lambda: _now().isoformat(), index=True)
