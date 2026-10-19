# AI Edu 架构说明（v2.0 基线实现）

> 对应执行方案 v2.0 §3–§9。本文是实现的权威参考；与 v2.0 冲突时以 v2.0 为准并修订本文。

## 1. 系统分层

```
apps/web (Next.js App Router)
   └─ features/* ── lib/api.ts ──► REST /api/*
services/api (FastAPI)
   ├─ api/        路由：请求校验、响应格式、错误语义
   ├─ services/   业务：目标诊断、计划、验收、教程生成、反馈、评估、复盘、知识提议、答疑
   ├─ learning/   通用学习引擎 + 学科配置（discipline profiles）
   ├─ llm/        LLMProvider 抽象（真实调用 / 演示生成器）
   ├─ models/     SQLAlchemy 实体
   ├─ schemas/    Pydantic 请求/响应模型
   ├─ repositories/ 数据访问（可选：v1 直接在 service 中使用 Session，保持简单）
   └─ prompts/    提示词模板（按功能组织，版本化字段存在 PromptVersion 表或常量中）
```

原则：UI 不直接调模型；密钥只在服务端；错误响应不含堆栈/密钥/内部提示词；关键写入可幂等重试。

## 2. 数据模型（v1 范围）

| 实体 | 关键字段 | 说明 |
|---|---|---|
| LearningGoal | title, domain_key, motivation, application_context, current_level, time_budget, status, user_notes | 学习目标 |
| GoalAssessment | goal_id, benefits, prerequisites, alternatives, assumptions, uncertainties, recommendation, user_decision, decision_reason | 目标诊断/价值分析 |
| LearningPlan | goal_id, version, status, generated_at, user_edits | 学习计划 |
| PlanStep | plan_id, order_index, title, objective, status, dependencies, estimated_effort, completion_evidence_refs | 计划步骤 |
| AcceptanceCriterion | goal_id, plan_step_id, statement, conditions, evidence_type, pass_rule, status, rationale | 验收标准 |
| Tutorial | goal_id, plan_step_id, title, status, current_version_id | 教程 |
| TutorialVersion | tutorial_id, version, content_json, prompt_version, model_provider, model_name, quality_report, source_refs | 教程版本（内容为结构化 JSON，含章节） |
| PracticeTask | goal_id, plan_step_id, tutorial_id, title, instructions, task_type, expected_artifact, validation_rule, status | 实践任务 |
| Attempt | task_id, artifact, artifact_type, result, errors, help_level, user_explanation, feedback, created_at | 尝试与证据 |
| Assessment | goal_id, task_id, assessment_type, rubric, result, confidence, evidence_refs, weak_points, created_at | 能力评估 |
| Reflection | goal_id, summary, learned_capabilities, unresolved_gaps, next_actions, evidence_refs, created_at | 复盘 |
| Concept | domain_key, title, definition, status, source_refs, last_reviewed_at | 概念 |
| ConceptRelation | from_concept_id, to_concept_id, relation_type, status(proposed/confirmed/rejected), rationale, source_refs, evidence_refs, confidence | 概念关系 |
| Source | title, url, source_type, publisher, reliability_note, accessed_at | 来源 |
| KnowledgeProposal | proposal_type, payload, rationale, evidence_refs, status, created_at, reviewed_at | 知识提议 |
| ChatMessage | goal_id, tutorial_id, section_id, task_id, role, content, created_at | 上下文答疑记录 |

辅助等级：A0 引导 / A1 协作 / A2 提示 / A3 独立验证（记录在 Attempt.help_level）。

## 3. 学习状态机（v2.0 §5.1）

`goal_definition → diagnosis → planning → acceptance_design → learning → practice → feedback → assessment → reflection → knowledge_update`

阶段存储在 `LearningGoal.status` 或计算得出；用户可回退；修改验收标准后标记受影响教程/评估「可能过期」。

## 4. 学科配置（v2.0 §5.4/5.5）

`DisciplineProfile` 数据结构（代码中 `learning/disciplines.py`）：

- key / display_name
- goal_types：目标类型枚举
- artifact_types：产物类型（命令行任务=command/session/code/tests；数学=derivation/data_table/plot/analysis）
- practice_templates：实践任务模板
- assessment_rubrics：能力评估维度
- common_errors：常见错误清单
- source_requirements：来源要求
- tutorial_requirements：教程结构要求

v1 内置两套：`computer_cli`（计算机/命令行/编程）与 `math_data`（数学/数据分析）；其余学科通过新增配置扩展。

## 5. 教程生成流水线与质量分级（v2.0 §6）

1. 校验目标 + 学科配置 + 验收标准齐全；
2. 生成大纲与验收标准双向映射；
3. 结构校验（L1）→ 用户确认大纲；
4. 分章节生成；
5. 每章结构检查（L1）+ 内容审查（L2，模型辅助）；
6. 关键事实来源/不确定性检查；
7. 生成理解检查、练习与变式任务；
8. 双向映射覆盖检查；
9. 保存版本 + 质量报告 + 模型调用记录；
10. 支持章节重生成与回滚。

- **L1 结构检查**：必需字段、验收映射、章节顺序、预期结果字段齐全。
- **L2 内容审查**：模型按 rubric 审查一致性/完整度/无依据断言，结果存入 quality_report。
- **L3 外部核验**：命令/代码可运行、来源可追溯；v1 由用户人工核验并在质量报告中标注。

## 6. API 概览（v2.0 §8.1）

见 `services/api/app/api/` 下各路由；统一前缀 `/api`。错误响应：`{code, message}`（message 为中文可读，不含敏感信息）。

## 7. 前端信息架构（v2.0 §9.1）

- `/` 工作台（当前目标、下一步、近期实践、待处理反馈）
- `/goals` 目标列表 / `/goals/new` 新建 / `/goals/[id]` 目标详情（诊断、计划、验收标准、阶段状态、地图缩略）
- `/goals/[id]/tutorials/[tid]` 教程阅读（章节、答疑、质量报告）
- `/goals/[id]/practice` 实践任务与提交
- `/goals/[id]/assessment` 能力评估
- `/goals/[id]/reflection` 复盘
- `/knowledge` 知识网络（概念、关系、提议）
- `/settings` 模型配置状态、导入导出

视觉基线来自阶段 0 HTML 原型（`D:\BJH\AI%20Edu%E5%8E%9F%E5%9E%8B.html`），Tailwind 令牌对齐原型 CSS 变量。

## 8. 演示模式

未配置 `LLM_API_KEY` 时，`llm/provider.py` 返回 `DemoProvider`：输出确定性结构化内容（与真实输出 schema 完全一致），所有响应带 `demo: true` 标记；不得写入长期真实学习记录时冒充真实模型结果。

## 9. 安全

- 密钥仅存服务端 `.env`；不得写入前端、仓库、日志。
- 导出/导入为版本化 JSON；导入前校验 schema 并先备份。
- 单用户本地运行；公网部署必须加访问保护（v1 不宣称多用户安全）。
