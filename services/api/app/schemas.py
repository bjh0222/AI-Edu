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


class GoalPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    motivation: Optional[str] = None
    application_context: Optional[str] = None
    current_level: Optional[str] = None
    time_budget: Optional[str] = None
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
    status: str
    user_notes: str
    archived: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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
    extract_status: str = "pending"  # ok / empty / unsupported / failed
    char_count: int = 0
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


class SectionOut(BaseModel):
    id: str = ""
    title: str
    goal_statement: str = ""
    prerequisites: list[str] = []
    explanation: list[ExplanationBlock] = []
    steps: list[StepBlock] = []
    examples: list[str] = []
    exercises: list[str] = []
    variation_task: str = ""
    common_errors: list[CommonError] = []
    sources: list[SourceRef] = []
    mapping_criteria: list[str] = []
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class TutorialContent(BaseModel):
    outline: list[OutlineItem] = []
    sections: list[SectionOut] = []


class QualityReport(BaseModel):
    passed: bool = False
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    coverage: dict[str, Any] = {}


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
