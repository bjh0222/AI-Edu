<!-- 由 scripts/arch_map.py 从代码生成，禁止手改。
     更新：仓库根 services\api\.venv\Scripts\python.exe scripts\arch_map.py -->

# 架构事实（自动生成）


## 路由（101 条 = 路径 × 方法，18 组资源）

### assessments（1 条）

| 方法 | 路径 |
|---|---|
| PATCH | `/api/assessments/{assessment_id}` |

### chat（1 条）

| 方法 | 路径 |
|---|---|
| POST | `/api/chat` |

### criteria（1 条）

| 方法 | 路径 |
|---|---|
| DELETE/PATCH | `/api/criteria/{criterion_id}` |

### export（1 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/export` |

### format-specs（5 条）

| 方法 | 路径 |
|---|---|
| GET/POST | `/api/format-specs` |
| POST | `/api/format-specs/match` |
| DELETE/GET/PUT | `/api/format-specs/{spec_id}` |
| POST | `/api/format-specs/{spec_id}/default` |
| POST | `/api/format-specs/{spec_id}/duplicate` |

### generation-jobs（2 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/generation-jobs/{job_id}` |
| GET | `/api/generation-jobs/{job_id}/events` |

### goals（19 条）

| 方法 | 路径 |
|---|---|
| GET/POST | `/api/goals` |
| POST | `/api/goals/quickstart` |
| DELETE/GET/PATCH | `/api/goals/{goal_id}` |
| GET/POST | `/api/goals/{goal_id}/assessments` |
| GET/POST | `/api/goals/{goal_id}/criteria` |
| POST | `/api/goals/{goal_id}/criteria/confirm-all` |
| POST | `/api/goals/{goal_id}/criteria/manual` |
| POST | `/api/goals/{goal_id}/decision` |
| GET/POST | `/api/goals/{goal_id}/diagnose` |
| POST | `/api/goals/{goal_id}/knowledge-proposals` |
| GET/POST | `/api/goals/{goal_id}/materials` |
| GET/POST | `/api/goals/{goal_id}/plan` |
| GET/POST | `/api/goals/{goal_id}/reflections` |
| GET/POST | `/api/goals/{goal_id}/tasks` |
| GET | `/api/goals/{goal_id}/tutorials` |
| POST | `/api/goals/{goal_id}/tutorials/generate` |
| POST | `/api/goals/{goal_id}/tutorials/quickstart` |
| POST | `/api/goals/{goal_id}/unarchive` |
| GET | `/api/goals/{goal_id}/usage` |

### health（1 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/health` |

### import（1 条）

| 方法 | 路径 |
|---|---|
| POST | `/api/import` |

### knowledge（10 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/knowledge` |
| POST | `/api/knowledge/concepts` |
| DELETE/GET | `/api/knowledge/concepts/{concept_id}` |
| POST | `/api/knowledge/dedupe` |
| POST | `/api/knowledge/extract/{tutorial_id}` |
| DELETE/GET | `/api/knowledge/graph` |
| GET | `/api/knowledge/nav` |
| POST | `/api/knowledge/proposals/{proposal_id}/review` |
| POST | `/api/knowledge/relations` |
| PATCH | `/api/knowledge/relations/{relation_id}` |

### materials（2 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/materials/limits` |
| DELETE | `/api/materials/{material_id}` |

### plans（1 条）

| 方法 | 路径 |
|---|---|
| PATCH | `/api/plans/{plan_id}` |

### proposition（10 条）

| 方法 | 路径 |
|---|---|
| POST | `/api/proposition/distill` |
| GET | `/api/proposition/item-instances` |
| GET | `/api/proposition/item-models` |
| POST | `/api/proposition/item-models/extract` |
| GET/PATCH | `/api/proposition/item-models/{item_model_id}` |
| POST | `/api/proposition/item-models/{item_model_id}/variations` |
| GET | `/api/proposition/principles` |
| GET | `/api/proposition/principles/injection-preview` |
| POST | `/api/proposition/principles/{principle_id}/review` |
| GET | `/api/proposition/quality-records` |

### reflections（1 条）

| 方法 | 路径 |
|---|---|
| PATCH | `/api/reflections/{reflection_id}` |

### settings（10 条）

| 方法 | 路径 |
|---|---|
| GET/POST | `/api/settings/models` |
| POST | `/api/settings/models/activate` |
| POST | `/api/settings/models/discover` |
| POST | `/api/settings/models/evaluate/{version_id}` |
| GET/PUT | `/api/settings/models/evaluation` |
| POST | `/api/settings/models/test` |
| PUT | `/api/settings/models/user-profile` |
| GET | `/api/settings/models/user-profile-suggestion` |
| POST | `/api/settings/models/user-profile-suggestion/dismiss` |
| DELETE | `/api/settings/models/{profile_id}` |

### tasks（2 条）

| 方法 | 路径 |
|---|---|
| PATCH | `/api/tasks/{task_id}` |
| GET/POST | `/api/tasks/{task_id}/attempts` |

### training（4 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/training/export` |
| POST | `/api/training/feedback` |
| GET | `/api/training/records` |
| GET | `/api/training/stats` |

### tutorials（9 条）

| 方法 | 路径 |
|---|---|
| GET | `/api/tutorials/{tutorial_id}` |
| POST | `/api/tutorials/{tutorial_id}/delivery` |
| GET | `/api/tutorials/{tutorial_id}/export` |
| GET | `/api/tutorials/{tutorial_id}/export/cheatsheet` |
| GET | `/api/tutorials/{tutorial_id}/export/exercises` |
| POST | `/api/tutorials/{tutorial_id}/restore/{version}` |
| POST | `/api/tutorials/{tutorial_id}/sections/generate` |
| GET | `/api/tutorials/{tutorial_id}/sections/{section_id}` |
| POST | `/api/tutorials/{tutorial_id}/sections/{section_id}/regenerate` |

## 数据表（25 张）

| 表 | 列 |
|---|---|
| `concepts` | id, domain_key, title, title_norm, aliases, domain_keys, goal_ids, definition, status, source_refs, last_reviewed_at, created_at, updated_at |
| `design_principles` | id, domain_key, statement, principle_type, scope_knowledge_points, positive_refs, negative_refs, evidence_count, status, rationale, reviewed_at, created_at, updated_at |
| `format_specs` | id, name, description, scene, is_builtin, is_default, version, applicable_tasks, applicable_intents, excluded_scenarios, excluded_intents, trigger_keywords, excluded_keywords, allow_keyword_trigger, allow_semantic_recommendation, allow_explicit_selection, target_reader, output_goal, deliverables, content_structure, format_rules, required_rules, forbidden_rules, suggested_rules, flexible_rules, acceptance_criteria, reference_examples, custom_markdown, created_at, updated_at |
| `item_models` | id, domain_key, title, chapter, knowledge_points, radicals, incidentals, solution_template, answer_expr, difficulty, provenance, status, source_ref, created_at, updated_at |
| `knowledge_proposals` | id, proposal_type, payload, rationale, evidence_refs, status, reviewed_at, created_at, updated_at |
| `learning_goals` | id, title, domain_key, motivation, application_context, current_level, time_budget, hard_constraints, capability_level, generate_extra_exercises, generation_tier, format_spec_id, format_spec_source, format_spec_match_note, format_spec_snapshot, status, user_notes, archived, completed, completed_at, created_at, updated_at |
| `model_call_logs` | id, feature, provider, model, goal_id, tutorial_id, job_id, latency_ms, status, error_category, prompt_tokens, completion_tokens, total_tokens, usage_source, created_at |
| `quality_records` | id, domain_key, goal_id, tutorial_id, version, source, code, paper_title, question_number, motif, detail, severity, question_text, created_at |
| `sources` | id, title, url, source_type, publisher, reliability_note, accessed_at |
| `training_records` | id, source_type, feature, goal_id, tutorial_id, section_id, system_prompt, user_prompt, output_text, model_provider, model_name, prompt_tokens, completion_tokens, total_tokens, usage_source, rating, tags, comment, context_json, created_at |
| `chat_messages` | id, goal_id, tutorial_id, section_id, task_id, role, content, created_at |
| `concept_relations` | id, from_concept_id, to_concept_id, relation_type, status, rationale, source_refs, evidence_refs, confidence, origin, history, created_at, updated_at |
| `generation_jobs` | id, goal_id, job_type, status, progress, stage, error_code, error_message, retry_count, prompt_tokens, completion_tokens, total_tokens, usage_source, created_at, updated_at |
| `goal_assessments` | id, goal_id, benefits, prerequisites, alternatives, assumptions, uncertainties, recommendation, user_decision, decision_reason, created_at, updated_at |
| `goal_materials` | id, goal_id, kind, filename, stored_name, ext, content_type, size, status, error_message, extract_status, text_excerpt, char_count, source_char_count, note, created_at, updated_at |
| `item_instances` | id, item_model_id, incidental_values, stem, answer, variation_type, verified_by, verified_at, source_tutorial_id, created_at, updated_at |
| `learning_plans` | id, goal_id, version, status, generated_at, user_edits, created_at, updated_at |
| `reflections` | id, goal_id, summary, learned_capabilities, unresolved_gaps, next_actions, evidence_refs, created_at |
| `plan_steps` | id, plan_id, order_index, title, objective, status, dependencies, estimated_effort, completion_evidence_refs, created_at, updated_at |
| `acceptance_criteria` | id, goal_id, plan_step_id, statement, conditions, evidence_type, pass_rule, status, rationale, created_at, updated_at |
| `tutorials` | id, goal_id, plan_step_id, title, status, current_version_id, delivery_status, delivery_path, delivery_version, created_at, updated_at |
| `practice_tasks` | id, goal_id, plan_step_id, tutorial_id, title, instructions, task_type, expected_artifact, validation_rule, status, created_at, updated_at |
| `tutorial_versions` | id, tutorial_id, version, content_json, prompt_version, model_provider, model_name, quality_report, source_refs, prompt_tokens, completion_tokens, total_tokens, usage_source, created_at |
| `assessments` | id, goal_id, task_id, assessment_type, rubric, result, confidence, evidence_refs, weak_points, created_at |
| `attempts` | id, task_id, artifact, artifact_type, result, errors, help_level, user_explanation, feedback, created_at |

### app/api/ — 路由层（14 个）

`chat`、`deps`、`format_specs`、`goals`、`health`、`io`、`knowledge`、`materials`、`model_settings`、`practice`、`proposition`、`router`、`training`、`tutorials`

### app/services/ — 业务层（21 个）

`chat`、`evaluation`、`exam_check`、`exam_verify`、`export`、`format_specs`、`goals`、`knowledge`、`materials`、`pipeline`、`practice`、`practice_check`、`proposition`、`quote_check`、`spec_check`、`synthesis`、`tool_verify`、`training`、`tutorials`、`usage`、`utils`

### app/learning/ — 学习引擎（6 个）

`demo`、`disciplines`、`engine`、`generation_tiers`、`levels`、`teaching_profile`

### app/llm/ — 模型调用（4 个）

`context_layers`、`prompts`、`provider`、`service`

## 前端页面（14 个）

- `/goals/[id]/acceptance-design`
- `/goals/[id]/diagnosis`
- `/goals/[id]/goal-definition`
- `/goals/[id]/learning`
- `/goals/[id]`
- `/goals/[id]/planning`
- `/goals`
- `/knowledge`
- `/`
- `/proposition`
- `/settings`
- `/training`
- `/tutorials/[tid]`
- `/tutorials/[tid]/sections/[sid]`
