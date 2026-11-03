"""Pydantic 请求 / 响应模型。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- health


class HealthOut(BaseModel):
    status: str = "ok"
    app: str = "AI Edu"
    demo: bool
    llm_configured: bool


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usage_source: str = ""  # provider / estimated / ""
    calls: int = 0


# ---------------------------------------------------------------- goals


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    domain_key: str = "computer_cli"
    motivation: str = ""
    application_context: str = ""
    current_level: str = ""
    time_budget: str = ""
    # 用户针对本次目标填写的硬性约束：注入所有生成阶段 prompt，违反即交付不合格
    hard_constraints: str = ""
    # 能力层级：L1 基础理解 / L2 独立应用 / L3 深入掌握与迁移
    capability_level: Literal["L1", "L2", "L3"] = "L2"
    # 是否生成独立的额外练习文件（教程内的必要练习不受此开关影响）
    generate_extra_exercises: bool = False
    # 生成挡位：快速 / 标准 / 深度
    generation_tier: Literal["fast", "standard", "deep"] = "standard"
    user_notes: str = ""


class GoalPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    motivation: Optional[str] = None
    application_context: Optional[str] = None
    current_level: Optional[str] = None
    time_budget: Optional[str] = None
    hard_constraints: Optional[str] = None
    capability_level: Optional[Literal["L1", "L2", "L3"]] = None
    generate_extra_exercises: Optional[bool] = None
    generation_tier: Optional[Literal["fast", "standard", "deep"]] = None
    completed: Optional[bool] = None
    status: Optional[str] = None
    user_notes: Optional[str] = None


class GoalOut(BaseModel):
    id: str
    title: str
    domain_key: str
    domain_name: str = ""
    motivation: str
    application_context: str
    current_level: str
    time_budget: str
    hard_constraints: str = ""
    capability_level: str = "L2"
    generate_extra_exercises: bool = False
    format_spec_id: str = ""
    format_spec_source: str = ""
    format_spec_match_note: str = ""
    format_spec_snapshot: dict[str, Any] = {}
    # 生成挡位：快速 / 标准 / 深度
    generation_tier: Literal["fast", "standard", "deep"] = "standard"
    status: str
    user_notes: str
    archived: bool
    completed: bool = False
    completed_at: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FormatSpecDeliverable(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    status: Literal["required", "optional", "on_request", "forbidden"] = "optional"
    primary: bool = True
    order: int = 1
    allow_override: bool = True


class FormatSpecIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    scene: str = Field(default="", max_length=80)
    is_builtin: bool = False
    is_default: bool = False
    applicable_tasks: str = ""
    applicable_intents: list[str] = []
    excluded_scenarios: list[str] = []
    excluded_intents: list[str] = []
    trigger_keywords: list[str] = []
    excluded_keywords: list[str] = []
    allow_keyword_trigger: bool = True
    allow_semantic_recommendation: bool = True
    allow_explicit_selection: bool = True
    target_reader: str = ""
    output_goal: str = ""
    deliverables: list[FormatSpecDeliverable] = []
    content_structure: str = ""
    format_rules: str = ""
    required_rules: str = ""
    forbidden_rules: str = ""
    suggested_rules: str = ""
    flexible_rules: str = ""
    acceptance_criteria: str = ""
    reference_examples: str = ""
    custom_markdown: str = ""


class FormatSpecOut(FormatSpecIn):
    id: str
    version: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FormatSpecMatchIn(BaseModel):
    requirement: str = Field(min_length=1)
    manual_spec_id: Optional[str] = None


class FormatSpecMatchOut(BaseModel):
    source: str
    note: str
    spec: Optional[FormatSpecOut] = None
    snapshot: dict[str, Any] = {}


class GoalAssessmentOut(BaseModel):
    id: str
    goal_id: str
    benefits: str
    prerequisites: str
    alternatives: str
    assumptions: str
    uncertainties: str
    recommendation: str
    user_decision: str
    decision_reason: str
    demo: bool = False


class PlanStepOut(BaseModel):
    id: str
    plan_id: str
    order_index: int
    title: str
    objective: str
    status: str
    dependencies: list[str] = []
    estimated_effort: str
    completion_evidence_refs: list[str] = []


class PlanOut(BaseModel):
    id: str
    goal_id: str
    version: int
    status: str
    steps: list[PlanStepOut]
    demo: bool = False


class CriterionCreate(BaseModel):
    statement: str = Field(min_length=1)
    conditions: str = ""
    evidence_type: str = "product"
    pass_rule: str = ""
    plan_step_id: Optional[str] = None
    rationale: str = ""


class CriterionPatch(BaseModel):
    statement: Optional[str] = None
    conditions: Optional[str] = None
    evidence_type: Optional[str] = None
    pass_rule: Optional[str] = None
    status: Optional[Literal["pending", "confirmed", "rejected"]] = None
    rationale: Optional[str] = None


class ConfirmAllIn(BaseModel):
    criterion_ids: list[str] = []


class CriterionOut(BaseModel):
    id: str
    goal_id: str
    plan_step_id: Optional[str] = None
    statement: str
    conditions: str
    evidence_type: str
    pass_rule: str
    status: str
    rationale: str


class CriterionDraft(BaseModel):
    statement: str
    conditions: str = ""
    evidence_type: str = "product"
    pass_rule: str = ""
    rationale: str = ""


# ---------------------------------------------------------------- materials


class MaterialOut(BaseModel):
    id: str
    goal_id: str
    kind: str = "reference"  # reference / example_source
    filename: str = ""
    ext: str = ""
    content_type: str = ""
    size: int = 0
    status: str = "ready"
    error_message: str = ""
    extract_status: str = "pending"  # ok / empty / unsupported / failed / truncated
    char_count: int = 0
    source_char_count: int = 0  # 原文字数；大于 char_count 表示入库时被截断
    note: str = ""
    created_at: Optional[str] = None
    excerpt_preview: str = ""


class MaterialLimitsOut(BaseModel):
    """前端上传前的校验参数：允许的扩展名与单文件上限。"""

    max_bytes: int
    allowed_extensions: list[str] = []
    kinds: list[dict[str, str]] = []


# ---------------------------------------------------------------- tutorials


class OutlineItem(BaseModel):
    id: str = ""
    title: str
    summary: str = ""
    purpose: str = ""
    content_type: str = ""
    criteria_ids: list[str] = []


class ExplanationBlock(BaseModel):
    heading: str
    body: str


class StepBlock(BaseModel):
    text: str
    expected_result: str = ""
    verification: str = ""


class CommonError(BaseModel):
    error: str
    cause: str = ""
    diagnose: str = ""


class SourceRef(BaseModel):
    title: str
    url: str = ""
    note: str = ""


# 章节正文内容块类型（合法枚举；非法值在保存前被归一化为 text）
CONTENT_BLOCK_TYPES = {
    "text",  # 普通解释
    "key_point",  # 关键结论
    "formula",  # 公式与推导
    "steps",  # 操作步骤
    "table",  # 表格
    "example",  # 示例
    "comparison",  # 对比分析
    "method_summary",  # 方法归纳
    "diagram",  # 概念关系图（Mermaid 等）
    "memory",  # 记忆材料
    "note",  # 注意事项
}
# 章节主要教学类型（content_type 枚举；非法值归一化为 mixed）
SECTION_CONTENT_TYPES = {
    "concept",  # 概念原理
    "method",  # 方法技巧
    "tool",  # 工具操作
    "fact",  # 事实记忆
    "application",  # 综合应用
    "mixed",  # 组合
}


class ContentBlock(BaseModel):
    """章节正文内容块：type 决定渲染方式，body 为 Markdown 文本。

    - steps：body 用有序 Markdown 列表（每步一行，可含预期结果与验证）；
    - table / comparison：body 用 Markdown 表格；
    - diagram：body 为 Mermaid 代码块；
    - 其余：body 为正文 Markdown（可含公式、代码块、双链）。
    """

    type: str = "text"
    title: str = ""
    body: str = ""


class RuleCheck(BaseModel):
    """画像硬性约束的核验结果（只有注入画像的阶段才有）。

    repaired=True 表示首稿违规、定向重写后已通过；repaired=False 表示重写后仍违规，
    交付保留的原稿并如实列出违规项——让「违反即不合格」有可展示的落点。
    """

    repaired: bool = False
    violations: list[str] = []


class SectionOut(BaseModel):
    id: str = ""
    title: str
    # ---- v2 结构（提示词重构后）：教学组织随知识性质变化，固定栏目允许为空
    purpose: str = ""
    content_type: str = "mixed"
    content: list[ContentBlock] = []
    sources: list[SourceRef] = []
    mapping_criteria: list[str] = []
    rule_check: Optional[RuleCheck] = None
    # ---- v1 结构（兼容旧版本数据）
    goal_statement: str = ""
    prerequisites: list[str] = []
    explanation: list[ExplanationBlock] = []
    steps: list[StepBlock] = []
    examples: list[str] = []
    variation_task: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class CheatsheetSection(BaseModel):
    heading: str
    body: str


class CheatsheetOut(BaseModel):
    filename: str = ""  # 配套文件名（不含 .md），与主教程中的 Obsidian 双链一致
    title: str = ""
    sections: list[CheatsheetSection] = []
    rule_check: Optional[RuleCheck] = None


class ExtraExerciseItem(BaseModel):
    """额外练习的题号条目：正文在 markdown 里，这里只保留计数所需的题号。"""

    number: int = 0


class ExtraExercisesOut(BaseModel):
    filename: str = ""  # 配套文件名（不含 .md），与主教程中的 Obsidian 双链一致
    title: str = ""
    markdown: str = ""  # 练习生成规范排版的整份 Markdown 成品
    exercises: list[ExtraExerciseItem] = []
    rule_check: Optional[RuleCheck] = None


class DeliveryContract(BaseModel):
    """交付契约：画像硬性约束对「这次交付物由哪几项组成」的规定。

    例如「目标里出现输出试卷时，只交付试卷、分析与压轴拓展」——它决定教程结构，
    不只是提示词里的一句话，所以要在 API 里能看到。
    """

    items: list[str] = []
    forbid_answers: bool = False
    exclusive: bool = False
    suppress_companions: bool = False
    rule: str = ""
    source: str = ""
    format_spec_id: str = ""
    format_spec_version: str = ""
    forbidden_deliverables: list[str] = []
    task_overrides: list[str] = []


class TutorialContent(BaseModel):
    outline: list[OutlineItem] = []
    sections: list[SectionOut] = []
    teaching_plan: dict[str, Any] = Field(default_factory=dict)
    format_spec: Optional[dict[str, Any]] = None
    # 交付契约（仅当画像里存在「只包括…」这类组成约束时出现）
    delivery_contract: Optional[DeliveryContract] = None
    # 配套文件（可能为 None：速查未生成 / 用户未开启额外练习）
    cheatsheet: Optional[CheatsheetOut] = None
    extra_exercises: Optional[ExtraExercisesOut] = None


class ExamViolation(BaseModel):
    """exam_check 的一条违规（错误码见 services/exam_check.CODES）。"""

    code: str = ""
    rule: str = ""
    # 判定依据：指向规范里的具体条文，让「为什么算违规」可回溯到规范而非代码私货
    basis: str = ""
    detail: str = ""
    auto_fixable: bool = False
    # 本轮是否已被代码修好（用户要求「自动改，但只改一次」，改了什么必须可追溯）
    fixed: bool = False
    severity: str = "blocking"


class ExamSectionCheck(BaseModel):
    title: str = ""
    spec: Optional[str] = None      # exam / exercise / None（非卷类章节不校验）
    changed: bool = False           # 代码是否就地改写了这一节的正文
    fixed: int = 0                  # 已自动修复的违规条数
    violations: list[ExamViolation] = []


class ExamCheckReport(BaseModel):
    """L0 卷面账目校验结果。

    必须暴露给前端：本层会**就地改写**章节正文（题号、分值括注、答案小节名、账目），
    用户看不到改了什么就无法信任交付物，也无法在改错时回滚。
    """

    sections: list[ExamSectionCheck] = []
    extra_exercises: Optional[ExamSectionCheck] = None
    # 跨卷一致性（E017 母题重复 / E018 同母题不同答案），基于 L0+L1 之后的最终内容
    cross: list[ExamViolation] = []


class ExamVerifyPaper(BaseModel):
    """L1 盲解核验对单份卷的结果。"""

    title: str = ""
    spec: str = ""
    verified: int = 0                 # 盲解核验的题目数
    conflicts: list[dict[str, Any]] = []   # 盲解与卷面答案的冲突（已送仲裁）
    defects: list[dict[str, Any]] = []     # 题目本身缺陷（如选项不完备）
    applied: list[dict[str, Any]] = []     # 本轮已自动改正的客观题答案
    skipped: list[dict[str, Any]] = []     # 未改写的项及原因
    changed: bool = False
    error: str = ""


class ExamVerifyReport(BaseModel):
    """L1 盲解核验汇总（每份卷 1~2 次模型往返：盲解 + 冲突仲裁）。

    与 L0 的区别：L0 是纯代码账目校验，L1 用「独立再解一遍」核对**答案内容对不对**。
    必须暴露给用户：L1 会**改写客观题答案**（仅限 high 置信仲裁），用户要能看到
    改了哪几题、依据是什么，以及哪些被判为「不改」及原因。
    """

    enabled: bool = False
    demo: bool = False
    skipped: str = ""
    verified_total: int = 0
    conflicts_total: int = 0
    applied_total: int = 0
    errors: list[str] = []
    papers: list[ExamVerifyPaper] = []


class SpecSectionCheck(BaseModel):
    """单节的规范专项校验结果（阅读摘录溯源 / 实践步骤与代码）。"""

    title: str = ""
    passed: bool = True
    blocking: int = 0
    advisory: int = 0
    codes: dict[str, int] = {}
    violations: list[ExamViolation] = []
    error: str = ""


class SpecCheckReport(BaseModel):
    """按规范 scene 分派的专项校验结果（services/spec_check.py）。

    必须声明在 QualityReport 里：tutorials._apply_exam_quality 会写入
    ``quality["spec_check"]``，而 QualityReport 是路由的 response_model——
    未声明的字段会被 Pydantic **静默丢弃**，Q001（虚构引文）这类 blocking 结果
    就永远到不了前端。这是实测踩过的坑（写入成功、响应里没有）。
    """

    # quote = 阅读教程规范（摘录溯源）/ practice = 实践性教程规范（步骤与代码）
    # None = 本 scene 无专项校验（讲解型教程、试卷类走 exam_check）
    kind: Optional[str] = None
    passed: bool = True
    blocking: int = 0
    advisory: int = 0
    sections: list[SpecSectionCheck] = []


class QualityReport(BaseModel):
    passed: bool = False
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    coverage: dict[str, Any] = {}
    # 无试卷类章节时为 None（讲解型教程不参与卷面校验）
    exam_check: Optional[ExamCheckReport] = None
    # L1 盲解核验；未启用 / 演示模式 / 无试卷时为 None
    exam_verify: Optional[ExamVerifyReport] = None
    # 规范专项校验（阅读摘录溯源 / 实践步骤与代码）；不适用时为 None
    spec_check: Optional[SpecCheckReport] = None


class TutorialVersionOut(BaseModel):
    id: str
    tutorial_id: str
    version: int
    content: TutorialContent
    prompt_version: str
    model_provider: str
    model_name: str
    quality_report: QualityReport
    source_refs: list[str] = []
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    created_at: Optional[str] = None


class TutorialOut(BaseModel):
    id: str
    goal_id: str
    plan_step_id: Optional[str] = None
    title: str
    status: str
    current_version: Optional[TutorialVersionOut] = None
    delivery_status: str = ""
    delivery_path: str = ""
    delivery_version: int = 0
    history_count: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)


class SectionDetailOut(SectionOut):
    goal_id: str
    goal_title: str = ""
    tutorial_id: str
    tutorial_title: str = ""
    index: int = 0
    total: int = 0
    version: int = 1
    prev_section_id: Optional[str] = None
    next_section_id: Optional[str] = None


class SectionGenerateRequest(BaseModel):
    section_ids: list[str] = []


class GenerateResult(BaseModel):
    job_id: str
    demo: bool


class JobOut(BaseModel):
    id: str
    goal_id: str
    job_type: str
    status: str
    progress: int
    stage: str
    error_code: str
    error_message: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class QuickStartStep(BaseModel):
    key: str
    label: str
    status: str  # created / reused / confirmed / running
    detail: str = ""


class QuickStartOut(BaseModel):
    goal_id: str
    steps: list[QuickStartStep] = []
    tutorial: TutorialOut
    job_id: Optional[str] = None
    demo: bool = False


class ConfirmAllOut(BaseModel):
    goal_id: str
    confirmed: int = 0
    changed: int = 0
    criteria: list[CriterionOut] = []


class FeatureUsageOut(TokenUsage):
    feature: str


class TutorialUsageOut(TokenUsage):
    tutorial_id: str
    tutorial_title: str = ""


class GoalUsageOut(BaseModel):
    goal_id: str
    totals: TokenUsage = Field(default_factory=TokenUsage)
    provider_calls: int = 0
    estimated_calls: int = 0
    by_feature: list[FeatureUsageOut] = []
    by_tutorial: list[TutorialUsageOut] = []


# ---------------------------------------------------------------- training


class TrainingFeedbackIn(BaseModel):
    goal_id: Optional[str] = None
    tutorial_id: Optional[str] = None
    section_id: Optional[str] = None
    target_type: Literal["general", "generation", "tutorial", "section"] = "general"
    rating: Literal[-1, 1]
    tags: list[str] = []
    comment: str = ""
    context: dict[str, Any] = {}


class TrainingRecordOut(BaseModel):
    id: str
    source_type: str
    feature: str = ""
    goal_id: Optional[str] = None
    tutorial_id: Optional[str] = None
    section_id: Optional[str] = None
    rating: Optional[int] = None
    tags: list[str] = []
    comment: str = ""
    created_at: Optional[str] = None
    model_provider: str = ""
    model_name: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    context: dict[str, Any] = {}
    prompt_preview: str = ""
    output_preview: str = ""
    prompt_chars: int = 0
    output_chars: int = 0


class TrainingListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TrainingRecordOut] = []


class TrainingStatsOut(BaseModel):
    totals: dict[str, Any] = {}
    by_feature: list[dict[str, Any]] = []
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    feedback: dict[str, Any] = {}


# ---------------------------------------------------------------- practice


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    instructions: str = ""
    task_type: str = "practice"
    expected_artifact: str = ""
    validation_rule: str = ""
    plan_step_id: Optional[str] = None
    tutorial_id: Optional[str] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    instructions: Optional[str] = None
    expected_artifact: Optional[str] = None
    validation_rule: Optional[str] = None
    status: Optional[Literal["todo", "doing", "done"]] = None


class TaskOut(BaseModel):
    id: str
    goal_id: str
    plan_step_id: Optional[str] = None
    tutorial_id: Optional[str] = None
    title: str
    instructions: str
    task_type: str
    expected_artifact: str
    validation_rule: str
    status: str
    created_at: Optional[str] = None


class AttemptCreate(BaseModel):
    artifact: str = ""
    artifact_type: str = "text"
    result: str = ""
    errors: str = ""
    help_level: Literal["A0", "A1", "A2", "A3"] = "A1"
    user_explanation: str = ""


class FeedbackItem(BaseModel):
    criterion_id: str = ""
    statement: str = ""
    status: str = "unsatisfied"  # satisfied / unsatisfied / unclear
    evidence: str = ""
    reason: str = ""
    next_action: str = ""


class AttemptOut(BaseModel):
    id: str
    task_id: str
    artifact: str
    artifact_type: str
    result: str
    errors: str
    help_level: str
    user_explanation: str
    feedback: dict[str, Any] = {}
    created_at: Optional[str] = None
    demo: bool = False


# ---------------------------------------------------------------- assessment


class AssessmentCreate(BaseModel):
    assessment_type: Literal["independent", "variant", "mixed"] = "mixed"
    task_id: Optional[str] = None


class AssessmentPatch(BaseModel):
    result: Optional[str] = None
    weak_points: Optional[str] = None
    confidence: Optional[str] = None


class AssessmentOut(BaseModel):
    id: str
    goal_id: str
    task_id: Optional[str] = None
    assessment_type: str
    rubric: list[dict[str, Any]] = []
    result: str
    confidence: str
    evidence_refs: list[str] = []
    weak_points: str
    created_at: Optional[str] = None
    demo: bool = False
    independent_task: dict[str, Any] = {}
    variant_task: dict[str, Any] = {}
    evidence_hint: str = ""


# ---------------------------------------------------------------- reflection


class ReflectionCreate(BaseModel):
    summary: str = ""
    learned_capabilities: str = ""
    unresolved_gaps: str = ""
    next_actions: str = ""


class ReflectionPatch(BaseModel):
    summary: Optional[str] = None
    learned_capabilities: Optional[str] = None
    unresolved_gaps: Optional[str] = None
    next_actions: Optional[str] = None


class ReflectionOut(BaseModel):
    id: str
    goal_id: str
    summary: str
    learned_capabilities: str
    unresolved_gaps: str
    next_actions: str
    evidence_refs: list[str] = []
    created_at: Optional[str] = None
    demo: bool = False


# ---------------------------------------------------------------- knowledge


class ConceptCreate(BaseModel):
    title: str = Field(min_length=1)
    definition: str = ""
    domain_key: str = "general"
    aliases: list[str] = []
    source_refs: list[Any] = []


class ConceptOut(BaseModel):
    id: str
    domain_key: str
    domain_keys: list[str] = []
    title: str
    definition: str
    status: str
    aliases: list[str] = []
    goal_ids: list[str] = []
    source_refs: list[Any] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RelationCreate(BaseModel):
    from_concept_id: str
    to_concept_id: str
    relation_type: str = "related"
    rationale: str = ""


class RelationPatch(BaseModel):
    relation_type: Optional[str] = None
    rationale: Optional[str] = None
    status: Optional[Literal["proposed", "confirmed", "conflict", "rejected", "revoked"]] = None


class RelationOut(BaseModel):
    id: str
    from_concept_id: str
    to_concept_id: str
    relation_type: str
    status: str
    rationale: str
    source_refs: list[Any] = []
    evidence_refs: list[Any] = []
    confidence: float
    origin: str = "manual"
    history: list[Any] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProposalOut(BaseModel):
    id: str
    proposal_type: str
    payload: dict[str, Any]
    rationale: str
    evidence_refs: list[str] = []
    status: str
    reviewed_at: str = ""
    created_at: Optional[str] = None


class ProposalReview(BaseModel):
    action: Literal["confirm", "edit", "reject"]
    payload: Optional[dict[str, Any]] = None


class KnowledgeOut(BaseModel):
    concepts: list[ConceptOut] = []
    relations: list[RelationOut] = []
    proposals: list[ProposalOut] = []


class GraphNode(BaseModel):
    id: str
    type: str  # concept / goal
    title: str
    domain_key: str = ""
    domain_name: str = ""
    definition: str = ""
    mastery: str = ""
    degree: int = 0
    status: str = ""
    ref_id: str = ""


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation_type: str
    status: str
    rationale: str = ""
    confidence: float = 0.5


class GraphOut(BaseModel):
    scope: dict[str, str] = {}
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    goal_edges: list[GraphEdge] = []
    stats: dict[str, int] = {}
    relation_types: dict[str, str] = {}


class NavGoal(BaseModel):
    id: str
    title: str
    status: str
    archived: bool = False
    concept_count: int = 0


class NavDomain(BaseModel):
    key: str
    name: str
    concept_count: int = 0
    goals: list[NavGoal] = []


class NavOut(BaseModel):
    domains: list[NavDomain] = []
    totals: dict[str, int] = {}


class MasteryOut(BaseModel):
    status: str
    basis: str = ""


class ConceptAnchor(BaseModel):
    tutorial_id: str
    tutorial_title: str = ""
    goal_id: str = ""
    goal_title: str = ""
    section_id: str = ""
    section_title: str = ""


class ConceptDetailOut(BaseModel):
    id: str
    domain_key: str
    domain_keys: list[str] = []
    title: str
    definition: str
    status: str
    aliases: list[str] = []
    goal_ids: list[str] = []
    source_refs: list[Any] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    relations: list[dict[str, Any]] = []
    tutorial_anchors: list[ConceptAnchor] = []
    goals: list[dict[str, Any]] = []
    mastery: MasteryOut


class ExtractionResult(BaseModel):
    concepts: int = 0
    relations: int = 0
    tutorial_id: str = ""
    goal_id: str = ""
    skipped: str = ""
    error: str = ""


# ---------------------------------------------------------------- chat


class ChatRequest(BaseModel):
    goal_id: Optional[str] = None
    tutorial_id: Optional[str] = None
    section_id: Optional[str] = None
    question: str = Field(min_length=1)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: Optional[str] = None
    demo: bool = False


# ---------------------------------------------------------------- io


class ImportRequest(BaseModel):
    version: int = 1
    data: dict[str, Any]


class DecisionIn(BaseModel):
    decision: str
    reason: str = ""


class GenerateOut(BaseModel):
    tutorial: TutorialOut
    job_id: str
    demo: bool


class ChatResponse(BaseModel):
    user: ChatMessageOut
    assistant: ChatMessageOut
    demo: bool = False


# ---------------------------------------------------------------- one-shot generation & delivery




class QuickStartRequest(BaseModel):
    """一键生成续跑参数；仅在 AI 暂停后由用户选择是否继续。"""

    pause_action: Optional[Literal["proceed", "adopt"]] = None
    # None 自动匹配；空串表示不使用特殊规范；其他值为手动选择
    format_spec_id: Optional[str] = None

class OneShotGenerateIn(BaseModel):
    """统一生成入口：一段需求 + 一个挡位即可创建任务并自动规划。"""

    title: str = Field(default="", max_length=200)
    requirement: str = Field(min_length=1, max_length=8000)
    generation_tier: Literal["fast", "standard", "deep"] = "standard"
    domain_key: Optional[str] = None
    motivation: str = ""
    application_context: str = ""
    current_level: str = ""
    time_budget: str = ""
    hard_constraints: str = ""
    capability_level: Literal["L1", "L2", "L3"] = "L2"
    generate_extra_exercises: bool = False
    user_notes: str = ""
    format_spec_id: Optional[str] = None


class OneShotGenerateOut(BaseModel):
    goal: GoalOut
    steps: list[QuickStartStep] = []
    tutorial: TutorialOut
    job_id: Optional[str] = None
    demo: bool = False


class DeliveryUpdateIn(BaseModel):
    status: Literal["delivered", "failed"]
    path: str = ""
    version: Optional[int] = None


# ---------------------------------------------------------------- proposition（命题知识库 / 变式引擎）


class ItemModelOut(BaseModel):
    """母题（AIG item model）：radicals 决定难度与认知要求，incidentals 是可换的表面特征。"""

    id: str
    domain_key: str = ""
    title: str = ""
    chapter: str = ""
    knowledge_points: list[str] = []
    radicals: dict[str, Any] = {}
    incidentals: dict[str, Any] = {}
    solution_template: str = ""
    answer_expr: str = ""
    # 求解约定随 radicals 一起存（models.py 无独立列）：未知量符号名与多解选取规则
    unknown: str = ""
    answer_select: str = ""
    difficulty: str = ""
    provenance: str = "manual"   # manual / ai_constructed / material
    status: str = "draft"         # draft / confirmed / archived
    source_ref: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    instances: list["ItemInstanceOut"] = []


class ItemInstanceOut(BaseModel):
    """同构题实例：母题代入一组具体 incidentals 后的一道题。

    变式 ↔ 母题的对应关系**只由 item_model_id 表达**，绝不写进 stem：
    变式规范的 forbidden_rules 明令禁止标注原题编号 / 溯源括注。
    """

    id: str
    item_model_id: str = ""
    incidental_values: dict[str, Any] = {}
    stem: str = ""
    answer: str = ""
    variation_type: str = "isomorph"   # isomorph / procedural / conceptual
    verified_by: str = "none"          # tool_symbolic / tool_executable / model / human / none
    verified_at: str = ""
    source_tutorial_id: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # 仅本次响应附带的可读信息（不入库）
    answer_latex: str = ""
    numeric: str = ""
    needs_independent_verification: bool = False


class DesignPrincipleOut(BaseModel):
    """命题规律。三态语义与 KnowledgeProposal / ConceptRelation 一致：
    只有 confirmed 才会被注入提示词，proposed 绝不注入。"""

    id: str
    domain_key: str = ""
    domain_name: str = ""
    statement: str = ""
    principle_type: str = "discipline"   # general / discipline
    scope_knowledge_points: list[str] = []
    positive_refs: list[Any] = []
    negative_refs: list[Any] = []
    evidence_count: int = 0
    status: str = "proposed"             # proposed / confirmed / rejected
    rationale: str = ""
    reviewed_at: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class QualityRecordOut(BaseModel):
    """质量记录：L0（exam_check）/ L1（exam_verify）发现的缺陷回流，是命题规律的冷启动素材。"""

    id: str
    domain_key: str = ""
    goal_id: str = ""
    tutorial_id: str = ""
    version: int = 0
    source: str = ""     # l0_account / l0_cross / l1_defect / l1_fixed / tool_refuted / tool_undecidable
    code: str = ""       # E017 / E018 / DEFECT
    paper_title: str = ""
    question_number: int = 0
    motif: str = ""
    detail: str = ""
    severity: str = ""   # blocking / advisory
    question_text: str = ""
    created_at: Optional[str] = None


class ItemModelPatch(BaseModel):
    """补录母题的参数化解法与求解约定（让 isomorph 变式能机械求答案的唯一途径）。

    ``solution_template`` / ``answer_expr`` 会在入库前用 sympy 在受控环境里试解析，
    不合法直接 422——不把不可求解的模板存进去、等到生成变式时才失败。

    ``answer_select`` 只在方程有多个解时有意义：多解时**必须**显式声明选取规则，
    否则求解器拒绝任选其一（那正是「同题多解」的病根）。
    """

    title: Optional[str] = Field(default=None, max_length=200)
    chapter: Optional[str] = Field(default=None, max_length=200)
    knowledge_points: Optional[list[str]] = None
    incidentals: Optional[dict[str, Any]] = None
    solution_template: Optional[str] = Field(default=None, max_length=512)
    answer_expr: Optional[str] = Field(default=None, max_length=512)
    unknown: Optional[str] = Field(default=None, max_length=32)
    answer_select: Optional[Literal["", "positive", "negative", "nonnegative", "max", "min"]] = None
    difficulty: Optional[str] = Field(default=None, max_length=20)
    provenance: Optional[Literal["manual", "ai_constructed", "material"]] = None
    status: Optional[Literal["draft", "confirmed", "archived"]] = None
    source_ref: Optional[str] = Field(default=None, max_length=2000)


class VariationCreate(BaseModel):
    """生成一个变式实例。

    isomorph 的答案由母题的 solution_template 代入 incidental_values **机械求解**；
    求不出来直接 409，不会产出一个未经验证的答案。
    """

    incidental_values: dict[str, Any] = {}
    variation_type: Literal["isomorph", "procedural", "conceptual"] = "isomorph"


class PrincipleReview(BaseModel):
    action: Literal["confirm", "reject"]
    rationale: str = ""


class DistillRequest(BaseModel):
    """规则聚类（确定性、零 token）：同一缺陷在某学科出现 ≥ threshold 次 → 候选规律。"""

    domain_key: str = "general"
    threshold: int = 3


class ExtractItemModelsRequest(BaseModel):
    """从一份卷子 Markdown 抽母题；radicals 复用 exam_check 的定义式指纹。"""

    domain_key: str = "general"
    markdown: str = Field(min_length=1, max_length=400000)
    chapter: str = ""


class ItemModelListOut(BaseModel):
    total: int = 0
    items: list[ItemModelOut] = []
    conflicts: int = 0     # 存在「同母题不同答案」证据的母题数
    solvable: int = 0      # 已具备可机械求解模板的母题数


class PrincipleListOut(BaseModel):
    total: int = 0
    items: list[DesignPrincipleOut] = []
    confirmed: int = 0
    proposed: int = 0
    rejected: int = 0


class QualityRecordListOut(BaseModel):
    total: int = 0
    items: list[QualityRecordOut] = []
    by_code: dict[str, int] = {}


class InjectionPreviewOut(BaseModel):
    """命题规律注入预览：哪些会被注入、哪些被预算裁掉，都要看得见。"""

    text: str = ""
    chars: int = 0
    budget_chars: int = 0
    injected: int = 0
    confirmed_total: int = 0
    dropped: int = 0
