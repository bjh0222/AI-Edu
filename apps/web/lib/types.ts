export interface Goal {
  id: string;
  title: string;
  domain_key: string;
  domain_name: string;
  motivation: string;
  application_context: string;
  current_level: string;
  time_budget: string;
  status: string;
  user_notes: string;
  archived: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface GoalAssessment {
  id: string;
  goal_id: string;
  benefits: string;
  prerequisites: string;
  alternatives: string;
  assumptions: string;
  uncertainties: string;
  recommendation: string;
  user_decision: string;
  decision_reason: string;
  demo: boolean;
}

export interface PlanStep {
  id: string;
  plan_id: string;
  order_index: number;
  title: string;
  objective: string;
  status: string;
  dependencies: string[];
  estimated_effort: string;
  completion_evidence_refs: string[];
}

export interface Plan {
  id: string;
  goal_id: string;
  version: number;
  status: string;
  steps: PlanStep[];
  demo: boolean;
}

export interface Criterion {
  id: string;
  goal_id: string;
  plan_step_id?: string | null;
  statement: string;
  conditions: string;
  evidence_type: string;
  pass_rule: string;
  status: string;
  rationale: string;
}

export interface OutlineItem {
  id: string;
  title: string;
  summary: string;
  criteria_ids: string[];
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  usage_source: string;
  calls?: number;
}

export interface StepBlock {
  text: string;
  expected_result: string;
  verification: string;
}

export interface Section {
  id: string;
  title: string;
  goal_statement: string;
  prerequisites: string[];
  explanation: { heading: string; body: string }[];
  steps: StepBlock[];
  examples: string[];
  exercises: string[];
  variation_task: string;
  common_errors: { error: string; cause: string; diagnose: string }[];
  sources: { title: string; url: string; note: string }[];
  mapping_criteria: string[];
  token_usage?: TokenUsage;
}

export interface SectionDetail extends Section {
  goal_id: string;
  goal_title: string;
  tutorial_id: string;
  tutorial_title: string;
  index: number;
  total: number;
  version: number;
  prev_section_id?: string | null;
  next_section_id?: string | null;
}

export interface QualityCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface QualityReport {
  passed?: boolean;
  checks?: QualityCheck[];
  issues?: string[];
  coverage?: Record<string, number>;
}

export interface TutorialVersion {
  id: string;
  tutorial_id: string;
  version: number;
  content: { outline: OutlineItem[]; sections: Section[] };
  prompt_version: string;
  model_provider: string;
  model_name: string;
  quality_report: QualityReport;
  source_refs: string[];
  token_usage?: TokenUsage;
  created_at?: string;
}

export interface Tutorial {
  id: string;
  goal_id: string;
  plan_step_id?: string | null;
  title: string;
  status: string;
  current_version?: TutorialVersion | null;
  history_count: number;
  tokens?: TokenUsage;
}

export interface QuickStartStep {
  key: string;
  label: string;
  status: string;
  detail: string;
}

export interface QuickStartResult {
  goal_id: string;
  steps: QuickStartStep[];
  tutorial: Tutorial;
  job_id?: string | null;
  demo: boolean;
}

export interface ConfirmAllResult {
  goal_id: string;
  confirmed: number;
  changed: number;
  criteria: Criterion[];
}

export interface FeatureUsage extends TokenUsage {
  feature: string;
}

export interface TutorialUsage extends TokenUsage {
  tutorial_id: string;
  tutorial_title: string;
}

export interface GoalUsage {
  goal_id: string;
  totals: TokenUsage;
  provider_calls: number;
  estimated_calls: number;
  by_feature: FeatureUsage[];
  by_tutorial: TutorialUsage[];
}

export interface GenerationJob {
  id: string;
  goal_id: string;
  job_type: string;
  status: string;
  progress: number;
  stage: string;
  error_code: string;
  error_message?: string;
  token_usage?: TokenUsage;
}

export interface TrainingRecord {
  id: string;
  source_type: string;
  feature: string;
  goal_id?: string | null;
  tutorial_id?: string | null;
  section_id?: string | null;
  rating?: number | null;
  tags: string[];
  comment: string;
  created_at?: string;
  model_provider: string;
  model_name: string;
  token_usage: TokenUsage;
  context: Record<string, unknown>;
  prompt_preview: string;
  output_preview: string;
  prompt_chars: number;
  output_chars: number;
}

export interface TrainingList {
  total: number;
  limit: number;
  offset: number;
  items: TrainingRecord[];
}

export interface TrainingStats {
  totals: Record<string, number>;
  by_feature: { feature: string; records: number; total_tokens: number }[];
  tokens: TokenUsage;
  feedback: { positive: number; negative: number; with_comment: number };
}

export interface Material {
  id: string;
  goal_id: string;
  kind: string; // reference / example_source
  filename: string;
  ext: string;
  content_type: string;
  size: number;
  status: string;
  error_message: string;
  extract_status: string; // ok / empty / unsupported / failed / pending
  char_count: number;
  note: string;
  created_at?: string;
  excerpt_preview: string;
}

export interface MaterialLimits {
  max_bytes: number;
  allowed_extensions: string[];
  kinds: { key: string; label: string }[];
}

export interface Task {
  id: string;
  goal_id: string;
  plan_step_id?: string | null;
  tutorial_id?: string | null;
  title: string;
  instructions: string;
  task_type: string;
  expected_artifact: string;
  validation_rule: string;
  status: string;
  created_at?: string;
}

export interface FeedbackItem {
  criterion_id: string;
  statement: string;
  status: string;
  evidence: string;
  reason: string;
  next_action: string;
}

export interface Attempt {
  id: string;
  task_id: string;
  artifact: string;
  artifact_type: string;
  result: string;
  errors: string;
  help_level: string;
  user_explanation: string;
  feedback: {
    items?: FeedbackItem[];
    summary?: string;
    weak_points?: string;
  };
  created_at?: string;
  demo: boolean;
}

export interface Assessment {
  id: string;
  goal_id: string;
  task_id?: string | null;
  assessment_type: string;
  rubric: { dimension: string; weight: number; note: string }[];
  result: string;
  confidence: string;
  evidence_refs: string[];
  weak_points: string;
  created_at?: string;
  demo: boolean;
  independent_task?: { title?: string; description?: string; expected_artifact?: string };
  variant_task?: { title?: string; description?: string };
  evidence_hint?: string;
}

export interface Reflection {
  id: string;
  goal_id: string;
  summary: string;
  learned_capabilities: string;
  unresolved_gaps: string;
  next_actions: string;
  evidence_refs: string[];
  created_at?: string;
  demo: boolean;
  candidate_concepts?: { title: string; definition: string }[];
}

export interface SourceRef {
  type: string;
  tutorial_id?: string;
  section_id?: string;
  title?: string;
}

export interface Concept {
  id: string;
  domain_key: string;
  domain_keys: string[];
  title: string;
  definition: string;
  status: string;
  aliases: string[];
  goal_ids: string[];
  source_refs: SourceRef[];
  created_at?: string;
  updated_at?: string;
}

export interface Relation {
  id: string;
  from_concept_id: string;
  to_concept_id: string;
  relation_type: string;
  status: string;
  rationale: string;
  source_refs: SourceRef[];
  evidence_refs: unknown[];
  confidence: number;
  origin: string;
  history: { action: string; note?: string; at?: string }[];
  created_at?: string;
  updated_at?: string;
}

export interface Proposal {
  id: string;
  proposal_type: string;
  payload: Record<string, unknown>;
  rationale: string;
  evidence_refs: string[];
  status: string;
  reviewed_at: string;
  created_at?: string;
}

export interface Knowledge {
  concepts: Concept[];
  relations: Relation[];
  proposals: Proposal[];
}

// ---------------- 知识网络图谱（重构版） ----------------

export interface GraphNode {
  id: string;
  type: "concept" | "goal";
  title: string;
  domain_key: string;
  domain_name: string;
  definition: string;
  mastery: string; // mastered / practicing / no_evidence（goal 节点为空）
  degree: number;
  status: string;
  ref_id: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  status: string;
  rationale: string;
  confidence: number;
}

export interface GraphData {
  scope: { domain: string; goal_id: string };
  nodes: GraphNode[];
  edges: GraphEdge[];
  goal_edges: GraphEdge[];
  stats: { concepts: number; goals: number; relations: number };
  relation_types: Record<string, string>;
}

export interface NavGoal {
  id: string;
  title: string;
  status: string;
  concept_count: number;
}

export interface NavDomain {
  key: string;
  name: string;
  concept_count: number;
  goals: NavGoal[];
}

export interface NavData {
  domains: NavDomain[];
  totals: { concepts: number; goals: number; relations: number };
}

export interface Mastery {
  status: string;
  basis: string;
}

export interface ConceptAnchor {
  tutorial_id: string;
  tutorial_title: string;
  goal_id: string;
  goal_title: string;
  section_id: string;
  section_title: string;
}

export interface RelationItem extends Relation {
  direction: "in" | "out";
  other_concept_id: string;
  other_title: string;
}

export interface ConceptDetail extends Concept {
  relations: RelationItem[];
  tutorial_anchors: ConceptAnchor[];
  goals: { id: string; title: string; status: string }[];
  mastery: Mastery;
}

export interface Health {
  status: string;
  app: string;
  demo: boolean;
  llm_configured: boolean;
}

export interface ChatResponse {
  user: { id: string; role: string; content: string; created_at?: string };
  assistant: { id: string; role: string; content: string; created_at?: string };
  demo: boolean;
}
