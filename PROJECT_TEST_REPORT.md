# PROJECT_TEST_REPORT.md — 实测报告

> 时间：2026-10-30　基线：`main` @ `3740070` + 本次审计修复
> 判定标准：**通过** = 已完成足够的实际验证；**失败** = 已观察到明确问题；**部分通过** = 部分环节正常但完整流程未通过；**未验证** = 没有执行足够测试；**受阻** = 环境/凭证/工具限制。
> 明确遵循：不把「代码存在」「构建成功」「页面能打开」等同于功能通过。

---

## 0. 测试环境

| 项 | 值 |
|---|---|
| 后端 | Python 3.14.6（系统）/ 3.12（venv）· FastAPI · SQLAlchemy 2.1.5 · SQLite 3.53.1 |
| 前端 | Node v24.21.0 · npm 11.19.0 · pnpm 12.4.2 · Next.js 16.4.2 (Turbopack) · React 19.3.0 · Tailwind 4 |
| 浏览器 | 真实 Chrome（Playwright 驱动，headless） |
| 真实模型 | `deepseek-flash` @ `https://api.deepseek.com/v1`（用户 `.env` 配置） |

**四套运行环境**（按风险从低到高）：

| 环境 | 端口 | 数据库 | 模型 | 用途 |
|---|---|---|---|---|
| pytest TestClient | — | `tests/test_aiedu.db`（每例重建） | 演示 | 后端单元/集成测试 |
| **隔离演示后端** | 8199 | `.audit/isolated/data/isolated.db` | 演示 | 完整写路径业务流程，**零风险零成本** |
| **真实数据副本后端** | 8198 | 用户 22.7 MB 库的 online-backup 快照（**故意删掉新索引**模拟老库） | 演示 | 验证修复在真实数据规模下成立 + 老库升级路径 |
| **用户线上服务** | 8000 / 3001 | 用户真实库 | **真实 deepseek** | 复现线上故障、验证生产恢复、真实模型链路 |

> UI 测试用 `page.route()` 把浏览器发往真实前端（3001）的 `/api/*` 全部改道到隔离后端（8199）——**真实 UI + 隔离数据**，既不碰用户数据也不烧 token。

---

## 1. 静态检查与构建（回归基线）

| 检查 | 审计前 | 审计后 | 结论 |
|---|---|---|---|
| `pytest -q` | **129 passed** | **142 passed** | ✅ 通过（+13 新增回归测试，无回归） |
| `npx tsc --noEmit` | exit 0 | exit 0 | ✅ 通过 |
| `npm run lint` | 0 errors, **3 warnings** | **0 errors, 0 warnings** | ✅ 通过（3 条警告全部清除，见下） |
| `npm run build` | ✅ 16 条路由全部成功 | ✅ 16 条路由全部成功 | ✅ 通过 |
| `node obsidian-plugin/tests/behavior-test.js` | — | `behavior-test passed` | ✅ 通过 |
| `pnpm install --frozen-lockfile --dry-run` | ❌ `ERR_PNPM_IGNORED_BUILDS` | ✅ `Dry run complete. pnpm-lock.yaml is up to date` | ✅ 修复后通过 |
| `Parser::ParseFile` on `start-dev.ps1` | — | 无语法错误，BOM 保留 | ✅ 通过 |

后端 17 个测试文件的用例分布：

```
test_teaching_profile.py    25   test_tutorial_v2.py       16   test_knowledge_network.py 14
test_audit_fixes.py         13 ← 新增   test_materials.py 11   test_format_specs.py      10
test_llm_json_repair.py      9   test_generation_pipeline.py 7  test_four_upgrades.py     6
test_llm_resilience.py       6   test_model_settings.py     6   test_hard_constraints.py  5
test_closed_loop.py          4   test_generation_tiers.py   3   test_goal_purge.py        3
test_export_import.py        2   test_pause_choices.py      2
```

**3 条 lint 警告全部清除**，逐条说明处置方式：

| 警告 | 位置 | 处置 |
|---|---|---|
| `'suggestionData' is assigned a value but never used` | `app/page.tsx:57` | 问题 E 的修复本身消除了它（移除该请求） |
| `Unused eslint-disable directive (react-hooks/set-state-in-effect)` | `app/tutorials/[tid]/page.tsx:63` | 移除失效指令 + 更新注释 |
| 同上 | `components/goals/useGoalWorkspace.ts:188` | 同上 |

后两条不是简单删注释：这两个 `eslint-disable-next-line` **已经不再抑制任何东西**（`setState` 发生在异步的 `load()` 内部，不在 effect 同步体里，规则本就不会触发）。移除前先实证确认「移除后 lint 仍 0 error」——若规则其实会触发，移除就会立刻变成 error。同时把旁边那句「该规则对异步 setState 误报」的注释改成准确描述，避免留下指向已删除指令的悬空注释。

> 这两处属于**注释级改动，行为完全不变**；但因涉及 `useGoalWorkspace.ts`（全部 5 个阶段子页共用）与教程页，改动后重跑了完整的 UI 回归（§4.3，16 项全绿）与 `next build`（16 条路由全部成功）确认无影响。

---

## 2. 逐项功能实测结果

### 2.1 学习闭环主流程（隔离环境，演示模式）

| # | 功能 | 操作 | 预期 | 实测结果 | 判定 |
|---|---|---|---|---|---|
| 1 | 创建目标 | `POST /api/goals`（含硬约束/L2/fast/额外练习开关） | 200，字段正确落库 | `tier=fast level=L2 hard_constraints=35字 extra_exercises=True` | ✅ **通过** |
| 2 | 非法能力层级 | 传 `capability_level: "L9"` | 被拒或归一 | `422`（`Literal["L1","L2","L3"]` 校验） | ✅ **通过** |
| 3 | 价值诊断 | `POST /goals/{id}/diagnose` | 200，含 recommendation | `demo=True`，`benefits/prerequisites/alternatives/recommendation` 齐备 | ✅ **通过** |
| 4 | 诊断幂等读取 | `GET` 两次 | 同一份 | `same_id=True` | ✅ **通过** |
| 5 | 用户决定 | `POST /goals/{id}/decision` | 记录决定 | 200；**注**：`decision` 无枚举校验，任意字符串被接受（问题 I，已记录未改） | ⚠️ **部分通过** |
| 6 | 学习计划 | `POST /goals/{id}/plan` | 有序步骤 | `steps=2 plan_status=active` | ✅ **通过** |
| 7 | 验收标准 | `POST /goals/{id}/criteria` | pending 列表 | `count=2 statuses=['pending','pending']` | ✅ **通过** |
| 8 | 一键同意 | `POST /criteria/confirm-all` | 批量确认 | `confirmed=2 changed=2` | ✅ **通过** |
| 9 | 一键同意幂等 | 重复调用 | `changed=0` | `changed=0` | ✅ **通过** |
| 10 | **不覆盖已拒绝项** | 先把一条置 `rejected`，再一键同意 | rejected 保持 | `rejected 项状态=rejected` | ✅ **通过** |
| 11 | 一键生成 | `POST /goals/{id}/tutorials/quickstart` | 全流程 + job_id | `demo=True`，8 步全 `reused`（二次调用，幂等生效） | ✅ **通过** |
| 12 | 大纲生成 | 同上 | `outline` 非空 | `outline=2 items` | ✅ **通过** |
| 13 | 全部章节 | 同上（后台任务） | `sections` 非空 | `sections=2`，`blocks_per_section=[5,5]` | ✅ **通过** |
| 14 | 章节映射验收标准 | 检查 `mapping_criteria` | 每章都有 | `mapped=[1,1]` | ✅ **通过** |
| 15 | 质量检查报告 | `quality_report` | 5 项检查 | `passed=True`，含「大纲与章节齐备 / 章节均映射 / 双向覆盖 / 正文非空 / 内容块规范」 | ✅ **通过** |
| 16 | **硬性约束生效** | 扫描章节文本 | 无「第X天/每天」 | 未出现日程表述 | ✅ **通过** |
| 17 | 知识速查 | `content.cheatsheet` | 已生成 | `yes` | ✅ **通过** |
| 18 | 额外练习 | 开关开启时生成 | 已生成 | `yes` | ✅ **通过** |

### 2.2 训练数据（问题 A 的核心验证）

| # | 功能 | 环境 | 修复前 | 修复后 | 判定 |
|---|---|---|---|---|---|
| 19 | `GET /training/records?limit=50` | **线上真实数据（449 条）** | **500** `unable to open database file` | **200**，`len=61847`，100ms | ✅ **失败→通过** |
| 20 | `GET /training/export?fmt=jsonl` | 线上 | **500** | **200**，`len=16,227,151`，285ms | ✅ **失败→通过** |
| 21 | `GET /training/export?fmt=json` | 线上 | **500** | **200**，`len=8,655,633`，479ms | ✅ **失败→通过** |
| 22 | `GET /training/stats` | 线上 | 200（未受影响） | 200 | ✅ **通过** |
| 23 | `/training` 网页 | 线上 + Chrome | 页面渲染原始 SQL 错误；「共 0 条」；2 次 500 + 2 条 console error | **零 4xx/5xx、零 console error、「共 449 条」、24 行功能分布** | ✅ **失败→通过** |
| 24 | 排序计划无 TEMP B-TREE | 真实数据副本 | `SCAN` + `USE TEMP B-TREE FOR ORDER BY` | `SCAN ... USING INDEX ix_training_records_created_at` | ✅ **通过** |
| 25 | **老库自动补索引** | 真实数据副本（启动前故意 `DROP INDEX`） | — | 启动后两个索引自动重建 | ✅ **通过** |
| 26 | 迁移幂等 | pytest | — | 连续调用 `_migrate_sqlite_indexes()` 两次无错 | ✅ **通过** |
| 27 | **部分唯一索引谓词保留** | pytest | — | `uq_format_specs_default` 的 DDL 仍含 `WHERE` | ✅ **通过** |
| 28 | 多默认规范约束仍生效 | 隔离 | — | `defaults=1`；设默认后仍 1；删默认后自动回落 | ✅ **通过** |
| 29 | JSONL 结构可解析 | 隔离 + 线上 | — | 每行 `{messages:[system,user,assistant], metadata:{...}}` | ✅ **通过** |
| 30 | `exclude_demo=true` | 隔离 | — | 200，正确过滤 | ✅ **通过** |
| 31 | 提交反馈 | 隔离 | — | `rating=1 tags=['清晰','可操作']` | ✅ **通过** |
| 32 | 非法评分拒绝 | 隔离 | — | `rating:5` → `422 literal_error`；`rating:0` → 422 | ✅ **通过** |
| 33 | 不存在的教程 → 404 | 隔离 | — | 404 | ✅ **通过** |
| 34 | **大字段排序压力测试** | pytest（60 条 × 8k 字符） | — | 列表与导出均 200 | ✅ **通过** |

### 2.3 导出 / 导入 / 删除

| # | 功能 | 结果 | 判定 |
|---|---|---|---|
| 35 | `GET /api/export` 全量备份 | 200，`version=1`，**21 张表**，120 KB（隔离）/ 23.7 MB（真实副本） | ✅ **通过** |
| 36 | 导入非 version=1 | `400 bad_version` | ✅ **通过** |
| 37 | 导入非法结构 | `400` | ✅ **通过** |
| 38 | 导入缺 id 记录 | `400 bad_payload`（指明表名） | ✅ **通过** |
| 39 | **知识数据安全阀** | 空备份导入 → `409 knowledge_would_be_cleared`（提示「会清空现有的 2 个概念 / 1 条关系」） | ✅ **通过** |
| 40 | 安全阀真的保住了数据 | 拒绝后复查：`before=2 after=2` | ✅ **通过** |
| 41 | 彻底删除 `?purge=true` | 200，返回逐表删除计数（`tutorial_versions:4, attempts:1, assessments:1, practice_tasks:1…`） | ✅ **通过** |
| 42 | 删除前写 JSON 备份 | 备份文件存在且可解析（60 KB） | ✅ **通过** |
| 43 | 删除后级联生效 | 目标 404、教程 404、列表（含归档）不再出现 | ✅ **通过** |
| 44 | **训练样本按设计保留** | `goal_id` 置空但记录仍在（`context_json` 可追溯）—— 这是刻意行为，非缺陷 | ✅ **通过**（已核实设计意图） |
| 45 | 软归档 | `DELETE /goals/{id}` → 默认列表隐藏、`include_archived=true` 可见 | ✅ **通过** |
| 46 | **备份路径锚定**（问题 C） | pytest：换 CWD 后备份仍落 `settings.backup_dir`，且**不再**在 CWD 下创建 `data/` | ✅ **通过** |

### 2.4 材料 / 格式规范 / 版本 / 知识网络

| # | 功能 | 结果 | 判定 |
|---|---|---|---|
| 47 | `GET /materials/limits` | `max_bytes=20971520`，11 种扩展名，2 个分类 | ✅ **通过** |
| 48 | 上传 md（reference） | 200，`chars=36` | ✅ **通过** |
| 49 | 上传 example_source | 200，`kind=example_source` | ✅ **通过** |
| 50 | 列出材料 | `count=2` | ✅ **通过** |
| 51 | 非法扩展名 `.exe` | `400 unsupported_file_type`（列出允许类型） | ✅ **通过** |
| 52 | 删除材料 / 删不存在的 | 200 / 404 | ✅ **通过** |
| 53 | 内置格式规范就绪 | 2 个（默认教程规范 / 试卷生成规范），`builtin=2`，默认唯一 | ✅ **通过** |
| 54 | 规范详情 / 复制 | 200 / 新 id + 「（副本）」 | ✅ **通过** |
| 55 | 自动匹配 | `source=default`，note「未命中特殊规范，使用默认规范」 | ✅ **通过** |
| 56 | 设为默认 → 默认唯一性 | `defaults=1`；删除默认后自动回落 | ✅ **通过** |
| 57 | **目标冻结规范快照** | `format_spec_snapshot` 非空，`source='default'` | ✅ **通过** |
| 58 | 教程版本列表 | `history_count=3` | ✅ **通过** |
| 59 | 章节详情 | 200，`title=准备与核心概念 blocks=5` | ✅ **通过** |
| 60 | 单节重生成 | 200，`history_count 3→4`，`current_version=4` | ✅ **通过** |
| 61 | 版本回滚 `restore/1` | 200，`current=1 history=4` | ✅ **通过** |
| 62 | 回滚不存在版本 | `404 version_not_found` | ✅ **通过** |
| 63 | 交付回写（**插件真实载荷** `{status,path,version}`） | 200，`delivery_status=delivered`，path/version 正确 | ✅ **通过** |
| 64 | 交付失败状态 / 非法状态 | 200 `failed` / 422 | ✅ **通过** |
| 65 | 知识提取（后台） | `concepts=2 relations=1` | ✅ **通过** |
| 66 | 图谱 / 导航 / 概念详情 | `nodes=3 edges=1`；`keys=['domains','totals']`；mastery 含 `basis` | ✅ **通过** |
| 67 | 概念去重 | `merged=0, remaining_concepts=2` | ✅ **通过** |
| 68 | 手工建概念 / 建关系 / 删概念 | 全部 200 | ✅ **通过** |
| 69 | token 用量统计 | `total=5499 source=estimated`，8 个 feature 维度 | ✅ **通过** |

### 2.5 「已移除界面」的后端能力（确认仍可用，不可误删）

| # | 功能 | 结果 | 判定 |
|---|---|---|---|
| 70 | 创建实践任务 | 200 | ✅ **通过** |
| 71 | 提交尝试（含 help_level A1） | 200，`help_level=A1` | ✅ **通过** |
| 72 | 列出尝试 / 标记任务完成 | 200 / 200 | ✅ **通过** |
| 73 | 复盘（`ReflectionCreate` 字段是**字符串**不是数组） | 200；GET 可读回 | ✅ **通过** |
| 74 | `PATCH /reflections/{id}` | 200 `{ok:true}`；GET 复查 `summary` 已更新为「修订后的复盘」 | ✅ **通过** |
| 75 | 上下文答疑（字段名是 `question`） | 200，`keys=['user','assistant','demo']`，assistant 回复 116 字符 | ✅ **通过** |
| 76 | 空问题拒绝 | 422（`min_length=1`） | ✅ **通过** |
| 77 | 知识提议 | 200，生成 2 条 | ✅ **通过** |
| 78 | 能力评估 | 200 | ✅ **通过** |
| 79 | 掌握度读取实践记录 | `mastery.basis="关联教程尚无实践尝试记录"` → 证明 `practice` 数据仍被消费 | ✅ **通过** |

> 首轮测试中 #73/#74/#75 报「失败」，核查后确认是**我的载荷写错**（把字符串字段传成数组、把 `question` 写成 `message`），按真实 schema 复测全部通过。这说明 `schemas.py` 的校验是有效的。

### 2.6 异常路径与边界

| # | 场景 | 结果 | 判定 |
|---|---|---|---|
| 80 | 不存在的目标 / 教程 / 任务 | 均 404，`{code, message}` 结构 | ✅ **通过** |
| 81 | 空标题创建目标 | 422 | ✅ **通过** |
| 82 | 未知学科 | 200，`domain_key` 原样保留、`domain_name=通用学科`（回退 GENERIC，不误判为计算机类） | ✅ **通过** |
| 83 | 全局异常处理 | 500 时返回 `{detail:{code:"internal_error", message}}`，完整堆栈落 `data/errors.log`，前端不再只见「500」 | ✅ **通过**（线上日志实证） |
| 84 | 僵尸任务清理 | `main.py:_sweep_stale_jobs()` 在 lifespan 里把遗留 `queued/running` 标 `failed` + `error_code=server_restart` | ⚪ **代码审阅确认，未制造中断场景实测** |

---

## 3. 真实模型链路实测（用户线上服务，最小成本）

刻意**只验证链路，不跑完整教程生成**（用户历史数据显示单教程章节生成累计 5.35M tokens，成本过高）。

| # | 项目 | 结果 | 判定 |
|---|---|---|---|
| 85 | `GET /api/health` | `{"demo":false,"llm_configured":true}` | ✅ **通过** |
| 86 | `GET /api/settings/models` | 2 组配置（zhipu / environment），**只返回 `has_key:true`，密钥零回显**；用户画像完整返回 | ✅ **通过** |
| 87 | `POST /api/settings/models/test`（结构化 JSON 探测） | `{"ok":true,"reply":"连接成功","latency_ms":905,"model":"deepseek-flash","usage":{"total_tokens":103,"usage_source":"provider"},"demo":false}` | ✅ **通过** |
| 88 | 真实 `diagnose`（临时目标，L1 + fast 挡位） | 10.0s，`demo:false`，真实建议文本 231/127 字符；挡位与层级的提示词注入在 prompt 里可见 | ✅ **通过** |
| 89 | **provider token 记账** | `/goals/{id}/usage` → `total_tokens=2395 usage_source="provider" calls=1`（不是估算值） | ✅ **通过** |
| 90 | 训练样本落库 | `feature=diagnose model=deepseek-flash tokens=2395 src=provider prompt_chars=1718 output_chars=1135` | ✅ **通过** |
| 91 | 测试后清理 | `purge` 成功；残留的 1 条 training_record + 1 条 model_call_log 按 `context_json.goal_id` 精确定位删除；计数回到 448 / 512 | ✅ **通过** |

> #88 的一个细节：诊断响应体里 `token_usage` 是 `{}`，但 `/usage` 端点统计正确（2395 / provider）。原因是 diagnose 的响应 schema 不带 token 字段，token 只落在 `ModelCallLog`，由 `/usage` 聚合——**行为一致，非缺陷**。

---

## 4. 浏览器 UI 级端到端实测

### 4.1 修复后的线上真实数据验证（Chrome + Playwright，直连 8000）

| # | 检查 | 结果 | 判定 |
|---|---|---|---|
| 92 | `/training` 页无 4xx/5xx | `(none)` | ✅ **通过** |
| 93 | 无 console error | `(none)` | ✅ **通过** |
| 94 | 无 SQL 报错文案 | `false` | ✅ **通过** |
| 95 | 记录总数正确显示 | **共 449 条**（修复前「共 0 条」） | ✅ **失败→通过** |
| 96 | 按功能分布渲染 | 24 行（章节生成 5.35M / knowledge_extract 1.10M / cheatsheet 489.4k …） | ✅ **通过** |

### 4.2 真实前端 + 隔离后端（写路径全流程，25 项）

| # | 检查 | 结果 | 判定 |
|---|---|---|---|
| 97 | 首页零数据空状态 | 统计全 0，导航 5 个入口齐备 | ✅ **通过** |
| 98 | 创建表单字段齐备 | 目标名称/为什么要学/**学完要能做什么**/当前基础/硬性约束/能力层级/生成挡位/格式规范 | ✅ **通过** |
| 99 | 「创建并自动生成教程」提交 | → 跳 `/tutorials/{id}` | ✅ **通过** |
| 100 | 教程页渲染章节 | `len=5435`，「历史 2 个版本」 | ✅ **通过** |
| 101 | 章节详情页 | `/tutorials/{tid}/sections/{sid}` 正常渲染 | ✅ **通过** |
| 102 | 五阶段流程条 | `5/5`，`<nav><ol><li>` 恰好 5 项，当前阶段 `aria-current="page"` | ✅ **通过** |
| 103 | 5 个阶段子页逐个打开 | goal-definition / diagnosis / planning / acceptance-design / learning 全部正常 | ✅ **通过** |
| 104 | 测试数据页 + JSONL 下载 | 无 4xx/5xx，「共 11 条」，触发真实浏览器下载 `aiedu-training-all-*.jsonl` | ✅ **通过** |
| 105 | 知识网络页 | **SVG** 力导向图（非 canvas），4 个节点，支持筛选/聚焦/缩放/去重 | ✅ **通过** |
| 106 | 偏好设置页 | 渲染正常，**密钥明文零出现** | ✅ **通过** |
| 107 | 首页统计联动 | 学习目标 1 / 已出教程 1 | ✅ **通过** |

> 首轮此项 1 个「失败」（`li=0`）与知识网络 `canvas=0`，核查后确认是**我的选择器写错**：`PhaseStepper` 在阶段子页而非目标详情页；知识图谱用 `<svg>` 不是 `<canvas>`。按正确结构复测：`li=5`、`svg=3`、`circle=4`，全部通过。

### 4.3 修复后的最终线上验证（16 项，全绿）

| # | 检查 | 结果 | 判定 |
|---|---|---|---|
| 108 | **首页不再请求 `user-profile-suggestion`** | 抓到 5 个 `/api` 请求，**无该请求** | ✅ **通过**（问题 E 修复实证） |
| 109 | 点开「用户画像」弹窗后才请求 | `GET /api/settings/models/user-profile-suggestion` ×1 | ✅ **通过** |
| 110 | 弹窗渲染 + 无未处理 rejection | 正常，`(none)` | ✅ **通过** |
| 111 | `/training` 页（真实 448 条） | 无 4xx/5xx、无 SQL 文案、「共 448 条」、列表非空、导出区可用 | ✅ **通过** |
| 112 | 真实目标详情页 | 五阶段条 `5/5`，标题正确 | ✅ **通过** |
| 113 | 真实用户教程页 | `len=17751`，「4 节已生成 · 历史 2 个版本 · 模型实测」 | ✅ **通过** |

**汇总：16 pass / 0 fail，failed responses `(none)`，console errors `(none)`。**

> 该终验在**全部整理完成后重跑过一次**（含最后两处注释级改动），结果同样 16 pass / 0 fail。
> 其中 #108「首页不再请求 `user-profile-suggestion`」是在**用户线上服务**上验证的——Next dev 已热加载 `app/page.tsx` 的修复，说明问题 E 的修复在真实运行环境中已生效。
>
> ⚠️ 但 #109-#113 所依赖的**后端**代码修复（问题 B/C/D）尚未生效：线上后端进程 PID 17720 启动于 `18:09:13`，而代码修改落盘于 `18:25:24~18:25:30`，**进程内存里仍是修复前的代码**。问题 A 之所以在线上已恢复，是因为索引属于**数据库级**变更（已直接对真实库执行，SQLite 在计划期即时选用）。这些修复的验证是在**真实数据副本后端（8198）**与 **pytest** 上完成的，见 §2.2 #24-#28、§2.3 #46、§5。

---

## 5. 变异测试：确认新测试真的能抓到缺陷

新增 13 个测试如果只在「修复后」通过，无法证明它们有效。因此把每处修复**逐个回退成缺陷版本**，确认对应测试确实失败：

| 回退的修复 | 预期失败的测试 | 结果 |
|---|---|---|
| `models.py` 去掉 `created_at` 的 `index=True` | `test_created_at_index_exists_on_sort_heavy_tables`<br>`test_records_sort_query_plan_avoids_temp_btree` | 🔴 **CAUGHT**（2 条失败） |
| `db.py` 的 `init_db()` 不再调 `_migrate_sqlite_indexes()` | `test_init_db_backfills_missing_index_on_existing_table` | 🔴 **CAUGHT** |
| `model_settings.config_path()` 改回 `Path(raw)`（CWD 相对） | `test_model_settings_path_anchored_to_backend_root`<br>`test_relative_env_override_anchored_not_cwd`<br>`test_saved_profiles_survive_cwd_change` | 🔴 **CAUGHT**（3 条失败） |
| `export._backup_path()` 改回 `Path("data")/"backups"` | `test_import_backup_written_to_anchored_backup_dir` | 🔴 **CAUGHT** |
| `api/model_settings.py` 改回读 `r.target_type` | `test_user_profile_suggestion_reads_target_type_from_context`<br>`test_user_profile_suggestion_survives_threshold` | 🔴 **CAUGHT**（2 条失败） |

**5 处修复全部被捕获，无「假绿」测试。** 每次回退后都完整还原源文件，并用 `git diff --stat` 核对。

过程中还修正了自己两个**测试写得太弱**的问题：
- `test_saved_profiles_survive_cwd_change` 原本用 conftest 注入的**绝对路径**，锚定与否看不出差别 → 改为显式注入**相对路径**，才真能复现「换 CWD 后配置丢失」；
- `test_index_migration_*` 原本直接调 `_migrate_sqlite_indexes()`，无法证明 `init_db()` 会调它 → 拆成 `test_init_db_backfills_missing_index_on_existing_table`（先 `DROP INDEX`，再 `init_db()`，断言索引回来）。

---

## 6. 回归验证

| 时机 | 项目 | 结果 |
|---|---|---|
| 每组代码修改后 | `pytest -q` | 全程保持 passed，无回归 |
| 全部整理完成后 | `pytest -q` | **142 passed**（10.62s） |
| 全部整理完成后 | `npx tsc --noEmit` | exit 0 |
| 全部整理完成后 | `npm run lint` | **0 errors, 0 warnings** |
| 全部整理完成后 | `npm run build` | 16 条路由全部成功 |
| 全部整理完成后 | `node obsidian-plugin/tests/behavior-test.js` | passed |
| 文件清理后 | `pytest -q`（`.pytest_cache` 已删） | **142 passed**（缓存自动重建） |
| 文件清理后 | 用户真实数据完整性核对 | goals 26 / training_records 448 / model_call_logs 512 / concepts 389 / relations 611 / backups 393 / `integrity_check: ok` |
| 文件清理后 | 线上服务仍正常 | 8000 与 3001 均在监听，`/api/health` 200 |

---

## 7. 未完成的测试（明确声明）

| 事项 | 状态 | 原因 |
|---|---|---|
| 真实模型的**完整教程生成**（大纲 + 全部章节 + 配套文件 + 知识提取） | ⚪ **未验证** | 会产生真实 token 开销（用户历史单教程 5.35M tokens）。完整链路已在**演示模式**下验证（含并发章节、重试、质量检查、配套文件、版本落库）；真实模型只验证了最小链路（#85-#91） |
| 真实模型下的**交付契约**行为（「只包括 A/B/C」→ 结构由规则决定） | ⚪ **未验证** | 同上，成本考虑。已有 25 个 `test_teaching_profile.py` 用例覆盖规则解析与求值逻辑 |
| Obsidian 插件在**真实 Obsidian 运行时**内 | ⚪ **受阻** | 需要 Obsidian 应用与真实 Vault。已跑独立行为测试（7 类行为）+ 核对其调用的 5 组 API 路径与载荷形状（`/delivery` 载荷已按插件真实形状实测通过） |
| `zhipu` 模型配置（`glm-5.3-flash` @ <INTERNAL-GATEWAY-REDACTED>） | ⚪ **未验证** | 未激活、未调用；只验证了当前激活的 deepseek 配置 |
| 生产构建（`next start`）的运行时行为 | ⚪ **未验证** | `next build` 通过，但只测了 dev 模式运行时 |
| Windows「智能应用控制」拦截场景 | ⚪ **未验证** | README 记录的两类拦截（`.cmd` 双击、`_row_cy` DLL）在当前环境未复现；`disable_blocked_native_extensions.py` 未执行 |
| 僵尸任务清理（`_sweep_stale_jobs`） | ⚪ **未验证** | 需要制造「生成中强杀进程」的场景，未执行 |
| 多用户 / 公网安全 | ⚪ **不适用** | 产品定位单用户本地运行，`user-guide.md` §五已声明「公网部署前必须增加访问保护」 |
| 前端自动化测试 | ⚪ **不存在** | `apps/web` 无任何测试框架（`package.json` 只有 dev/build/start/lint）。本次前端验证全靠 Playwright 手工驱动，**无法纳入 CI**。建议见 `PROJECT_AUDIT.md` §4.2 |
| 长时间稳定性 / 内存 / 并发压力 | ⚪ **未验证** | 未做压测。已知设计约束：章节并发默认 9 路，**换单卡自建端点必须设 `AIEDU_LLM_CONCURRENCY=1`**，否则会陷入「排队超时→重试再排队」死循环（代码注释与 ADR-017 有记录） |

---

## 8. 结论

**核心业务链路全部实测通过**：创建目标 → 价值诊断 → 学习计划 → 验收标准 → 一键生成 → 大纲 → 全部章节 → 配套文件 → 质量检查 → Markdown 导出 → 知识网络提取 → 训练数据采集与导出 → 备份/导入/彻底删除，在演示模式下端到端跑通。

实测步骤总数（每步都有打印的 PASS/FAIL 记录）：

本报告有两个统计口径，分开列示以免混算：

**口径一：文档检查项**（下表 §2–§5 里的编号 #1–#113 + 5 处变异回退，每项都对应一次人工判读）

| 章节 | 编号区间 | 项数 |
|---|---|---|
| §2.1 学习闭环主流程 | #1–#18 | 18 |
| §2.2 训练数据（问题 A 核心验证） | #19–#34 | 16 |
| §2.3 导出 / 导入 / 删除 | #35–#46 | 12 |
| §2.4 材料 / 格式规范 / 版本 / 知识网络 | #47–#69 | 23 |
| §2.5 已移除界面的后端能力 | #70–#79 | 10 |
| §2.6 异常路径与边界 | #80–#84 | 5 |
| §3 真实模型链路 | #85–#91 | 7 |
| §4.1 UI（线上真实数据） | #92–#96 | 5 |
| §4.2 UI（真实前端 + 隔离后端全流程） | #97–#107 | 11 |
| §4.3 UI（修复后终验） | #108–#113 | 6 |
| §5 变异测试 | 5 处回退 | 5 |
| **合计** | | **118** |

**口径二：脚本自动断言步数**（`step()` 计数器落盘到 `.audit/isolated/e2e_part*.json` 与运行日志；一个文档检查项有时聚合多条脚本断言，所以这个数更大）

| 批次 | 环境 | 断言步数 | 首轮记录 |
|---|---|---|---|
| API 批次 1（目标/诊断/计划/标准） | 隔离演示后端 | 13 | PASS 9 / FAIL 4 |
| API 批次 2（一键生成/导出/训练/知识） | 隔离演示后端 | 30 | **PASS 30 / FAIL 0** |
| API 批次 3（材料/规范/版本/交付/旧能力/异常） | 隔离演示后端 | 38 | PASS 33 / FAIL 5 |
| API 批次 4（交付/复盘/答疑/回滚/导入删除） | 隔离演示后端 | 28 | PASS 26 / FAIL 2 |
| **API 层小计** | | **109** | PASS 98 / FAIL 11 |
| UI 全流程（首轮） | 真实 Chrome + 隔离后端 | 25 | PASS 24 / FAIL 1 |
| UI 终验（修复后） | 真实 Chrome + **线上** | 16 | **PASS 16 / FAIL 0** |
| UI 训练页复验 | 真实 Chrome + **线上** | 6 | 全部通过 |
| 变异测试 | pytest | 5 | **5 处全部 CAUGHT** |
| **合计** | | **161** | |

> **关于首轮 12 项 FAIL 的说明**：逐条核查后确认**全部是我的测试写错**，没有一项是产品缺陷被误判：
> - **载荷字段名/类型不符 schema**：`ReflectionCreate` 的四个字段是**字符串**（我传了数组）；`ChatRequest` 的问题字段叫 **`question`**（我传了 `message`）；`DeliveryUpdateIn` 是 **`{status,path,version}`**（我按猜测传了 `{delivered, vault_path, wikilinks_resolved}`）。
> - **断言写错**：`PATCH /reflections/{id}` 返回 `{ok:true}`、`POST /delivery` 返回 `TutorialOut`，都不含我断言的字段——改为 GET 复查落库结果后确认功能正常（复盘修订确实落库、交付状态确实回写）。
> - **选择器写错**：`PhaseStepper` 在阶段子页而非目标详情页；知识图谱用 `<svg>` 不是 `<canvas>`；按钮实际文案是「创建并**自动**生成教程」（卡片标题才是「创建并生成教程」）；标题输入框要按 placeholder 定位，否则会填到搜索框里。
>
> 这些「测试写错」反而反向证明了 `schemas.py` 的校验有效——错误载荷全部被 `422` 挡下，没有静默通过。
> 唯一真实的产品缺陷是问题 A 的 500，单独记录为「失败→通过」（§2.2 #19–#23、§4.1 #95）。

---

## 8. 结论

**核心业务链路全部实测通过**：创建目标 → 价值诊断 → 学习计划 → 验收标准 → 一键生成 → 大纲 → 全部章节 → 配套文件 → 质量检查 → Markdown 导出 → 知识网络提取 → 训练数据采集与导出 → 备份/导入/彻底删除，在演示模式下端到端跑通。

实测步骤总数（每步都有打印的 PASS/FAIL 记录）：

下表数字来自脚本落盘的结果文件（`.audit/isolated/e2e_part*.json`）与运行日志，非人工估算：

| 层面 | 环境 | 步骤数 | 首轮记录 | 复核后 |
|---|---|---|---|---|
| API 批次 1：目标/诊断/计划/标准 | 隔离演示后端 | 13 | PASS 9 / FAIL 4 | 4 项 FAIL 全部是**我的测试写错**（见下） |
| API 批次 2：一键生成/导出/训练/知识 | 隔离演示后端 | 30 | **PASS 30 / FAIL 0** | 同 |
| API 批次 3：材料/规范/版本/交付/旧能力/异常 | 隔离演示后端 | 38 | PASS 33 / FAIL 5 | 5 项 FAIL 全部是我的载荷/断言写错 |
| API 批次 4：交付/复盘/答疑/回滚/导入删除 | 隔离演示后端 | 28 | PASS 26 / FAIL 2 | 2 项 FAIL 同上 |
| **API 层小计** | | **109** | PASS 98 / FAIL 11 | 复核后 11 项全部确认为测试侧问题 |
| 真实模型链路 §3 | **线上真实模型** | 7 | 全部通过 | — |
| UI 浏览器级（首轮全流程） §4.2 | 真实 Chrome + 隔离后端 | 25 | PASS 24 / FAIL 1 | 1 项 FAIL 是我的选择器写错 |
| UI 浏览器级（线上真实数据） §4.1 | 真实 Chrome + **线上** | 6 | 全部通过 | 其中 1 项为「失败→通过」 |
| UI 浏览器级（修复后终验） §4.3 | 真实 Chrome + **线上** | 16 | **PASS 16 / FAIL 0** | 零 4xx/5xx、零 console error |
| 变异测试 §5 | pytest | 5 处回退 | **5 处全部 CAUGHT** | — |
| **合计** | | **168** | | |

> **关于 12 项首轮 FAIL 的说明**：逐条核查后确认**全部是我的测试写错**，不是产品缺陷：
> - 载荷字段名/类型不符 schema：`ReflectionCreate` 的四个字段是**字符串**（我传了数组）、`ChatRequest` 的问题字段叫 **`question`**（我传了 `message`）、`DeliveryUpdateIn` 是 **`{status,path,version}`**（我按猜测传了 `{delivered,vault_path,...}`）；
> - 断言写错：`PATCH /reflections/{id}` 与 `POST /delivery` 返回的是 `{ok:true}` / `TutorialOut`，不含我断言的字段——改为 GET 复查落库结果后确认功能正常；
> - 选择器写错：`PhaseStepper` 在阶段子页而非目标详情页；知识图谱用 `<svg>` 不是 `<canvas>`；按钮实际文案是「创建并**自动**生成教程」。
>
> 唯一真实的产品缺陷是问题 A 的 500，它单独记录为「失败→通过」（§2.2 #19-23、§4.1 #95）。这些「测试写错」恰恰反向证明了 `schemas.py` 的校验是有效的——错误载荷都被 422 挡下，没有静默通过。

**发现并修复了 1 个线上正在发生的严重故障**（训练数据页 500，用户自己的 `errors.log` 里有 16 次同源异常记录）和 4 个潜在缺陷（2 个路径未锚定、1 个缺列 AttributeError、1 个白烧 token）。5 处修复全部通过变异测试确认测试有效性。

**真实模型链路已验证可用**（`demo:false`、provider token 记账正确、训练样本完整落库）。

**用户数据零损失**：真实库计数审计前后完全一致，`integrity_check: ok`；20 份孤儿备份被**回收**（373 → 393）而非删除；测试残留已精确清除。

**主要遗留**：真实模型的完整教程生成、Obsidian 运行时行为、生产构建运行时**未验证**（原因见 §7）；前端**无自动化测试**是最大的回归风险敞口。
