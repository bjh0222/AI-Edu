# PROJECT_AUDIT.md — AI Edu 全面审计

> 审计时间：2026-10-30　基线：`main` @ `3740070`
> 审计方式：**实际运行验证优先**。所有结论都附带可复现的证据（命令、接口响应、浏览器行为、数据库查询）。
> 未做实际验证的部分在 §6「未验证事项」中明确列出，不宣称通过。

---

## 1. 架构与实现现状总评

| 维度 | 评价 |
|---|---|
| 架构清晰度 | **良好**。三层解耦（Next 前端 / FastAPI 后端 / Obsidian 交付端），同源代理避免跨源；后端 api→services→learning/llm 分层职责明确 |
| 代码质量 | **良好**。注释解释「为什么」而非「是什么」（大量记录踩坑原因与取舍）；18 条 ADR 留存决策依据 |
| 健壮性 | **良好**。幂等、重试、竞态保护、僵尸任务清理、数据安全阀都有实现且经测试覆盖 |
| 测试覆盖 | **中等偏好**。后端 129 个用例（审计前），前端**零单元测试**，Obsidian 插件有 7 项行为测试 |
| 文档一致性 | **差（已修复）**。`docs/architecture.md` 与 `docs/user-guide.md` 描述的是旧的 10 阶段流程，与实际 5 阶段实现严重不符 |
| 数据卫生 | **差（已修复）**。仓库里有误提交的 SQLite WAL/SHM 二进制、20 个 pip 临时目录、调试库、孤儿数据目录 |

**总体结论**：这是一个**真实可用、工程完成度较高**的个人学习工具，不是原型。核心业务链路（创建目标 → 诊断 → 计划 → 验收标准 → 大纲 → 章节 → 导出 → 知识网络 → 训练数据）全部实测打通，真实模型链路也已验证。但存在 1 个**线上正在发生的 500 故障**和 4 个潜在缺陷，均已修复。

---

## 2. 发现的问题（含证据、影响、修复状态）

### 问题 A【严重 · 已修复】训练数据接口线上 500：`unable to open database file`

**现象**：`GET /api/training/records` 与 `GET /api/training/export` 在**线上运行的服务上返回 500**，网页「测试数据」页直接渲染出原始 SQL 错误文本，「最近记录」显示「共 0 条 / 当前筛选下还没有记录」，而同一页的统计卡片却显示「生成材料 445 条」——**自相矛盾**。

**证据链**：

1. 线上接口实测（审计开始时，用户真实数据）：
   ```
   /api/training/stats                          200  len=757
   /api/training/records?limit=50               500
   /api/training/export?fmt=jsonl               500
   /api/training/export?fmt=json                500
   ```
2. 用户自己的 `services/api/data/errors.log` 里**已有同一异常的完整堆栈**。审计开始时该文件 732 行 / 6 次异常，仅做只读探测期间就增长到 854 行（说明线上仍在持续触发）；审计结束时为 157 KB / **16 次异常**，构成如下（全部同源）：
   ```
   最终异常类型：16 × sqlalchemy.exc.OperationalError（100%）
   涉及代码位置：13 × api/training.py:list_records
                  3 × api/training.py:export_training_data
   'unable to open database file' 出现 32 次 = 16 次异常 × 2（sqlite3 原始 + sqlalchemy 包装）
   ```
   即：**该日志里的每一次异常都是这一个问题**，涉及文件只有 `api/training.py` 与 `services/training.py`。典型堆栈：
   ```
   File "...\app\api\training.py", line 29, in list_records
   File "...\app\services\training.py", line 127, in list_records
   sqlite3.OperationalError: unable to open database file
   [SQL: SELECT training_records.id, ..., training_records.created_at
        FROM training_records ORDER BY training_records.created_at DESC LIMIT ? OFFSET ?]
   [parameters: (50, 0)]
   ```
3. 浏览器实测（Chrome + Playwright，真实前端 `/training` 页）：
   ```
   500 http://127.0.0.1:3001/api/training/records?limit=50&offset=0   （连续两次）
   CONSOLE: Failed to load resource: the server responded with a status of 500
   页面文本含：服务内部错误：OperationalError: (sqlite3.OperationalError) unable to open database file [SQL: SELECT ...
   ```

**根因（不是 SQL 写错，也不是权限配错）**：

`training_records.created_at` **没有索引**，而该表每行的 `system_prompt` / `user_prompt` / `output_text` 动辄上万字符（真实库合计 7.3 MB）。`ORDER BY created_at` 时 SQLite 必须把**整表连同大字段**写进磁盘 TEMP B-TREE 再排序；而该进程的临时目录不可写，于是创建 `etilqs_*` 溢出文件失败 → 报 `unable to open database file`（这个错误信息极具误导性，看起来像数据库文件打不开，实际是**临时排序文件**打不开）。

三步定位证据：

| 实验 | 结果 |
|---|---|
| 同样的表，只 SELECT 小字段 + `ORDER BY created_at` | ✅ OK（50 行） |
| SELECT 全部字段（含大文本）+ `ORDER BY created_at` | ❌ FAIL |
| SELECT 全部字段，**不加** `ORDER BY` | ✅ OK（448 行） |
| 加 `PRAGMA temp_store=MEMORY` 后同一条失败查询 | ✅ OK |
| `EXPLAIN QUERY PLAN` | `SCAN training_records` + **`USE TEMP B-TREE FOR ORDER BY`** |
| 建 `ix_training_records_created_at` 后 | ✅ OK **0.009s**，计划变为 `SCAN ... USING INDEX ix_training_records_created_at`，**TEMP B-TREE 消失** |

规模阈值实测：400 行 × 5000 字符（1.9 MB）可以过；1000 行 × 5000 字符（4.8 MB）开始失败。57 MB 表排序默认失败、`temp_store=MEMORY` 通过 —— 确认是溢出文件问题。

> 补充：临时目录不可写在**本机环境**成立（Python 写 `%TEMP%` 报 `PermissionError: [Errno 13]`，而 cmd/node 可写）。但**修复不应依赖这一点**——索引方案对临时目录是否可写完全免疫，且顺带把分页从「全表排序」降到 `O(limit)`，所以选择索引而不是 `temp_store=MEMORY`。

**影响**：严重。「测试数据」页是产品四大功能之一（README 明确宣传「测试数据采集」与 JSONL 导出），列表与导出**完全不可用**，且错误信息把内部 SQL 直接暴露到界面。用户看不到任何生成材料记录，也无法导出预训练数据。

**修复**（两处，缺一不可）：

1. `app/models.py`：`TrainingRecord.created_at` 与 `ModelCallLog.created_at` 加 `index=True`（后者同理被 `usage.py:goal_usage()` 按 `created_at` 聚合）。
2. `app/db.py`：新增 `_migrate_sqlite_indexes()`，在 `init_db()` 里为**已存在的表**补建索引。

   > 为什么必须有第 2 步：`Base.metadata.create_all()` 只建缺失的**表**，对已存在的表既不补列也不补索引。用户那份 22 MB 老库单靠改 `models.py` **永远拿不到新索引**。

   实现要点：**用 SQLAlchemy 自己的 `CreateIndex(index, if_not_exists=True)` 编译 DDL，不手拼 SQL 字符串**。因为 `format_specs.uq_format_specs_default` 是**部分唯一索引**（`UNIQUE ... WHERE is_default = 1`），手拼会丢掉 `WHERE` 谓词，把「只能有一个默认规范」悄悄放宽成全表唯一——第二条 `is_default=0` 的记录就插不进去了。这个坑在审计过程中被识别并规避。

**验证**：见 `PROJECT_TEST_REPORT.md` §2.2 / §4。线上服务在**未重启**的情况下（索引是 DB 级变更，SQLite 在计划期即时选用）已从 500 恢复为 200，浏览器页面显示「共 449 条」，零控制台错误。

---

### 问题 B【中 · 已修复】模型配置路径未锚定，换目录启动会「丢失」已保存配置

**现象**：`app/model_settings.py:config_path()` 返回 `Path(os.getenv("MODEL_SETTINGS_FILE", "data/model-settings.json"))` —— **相对进程工作目录**。

**证据**（模拟从仓库根启动）：
```
CWD: D:\桌面\dsh\ai-edu
model config_path(): data\model-settings.json   exists: False      ← 找不到
db url (anchored)  : sqlite:///D:/.../services/api/data/aiedu.db   ← 正确锚定
backup_dir         : D:\...\services\api\data\backups              ← 正确锚定
materials_dir      : D:\...\services\api\data\materials            ← 正确锚定
profiles seen      : ['environment']     ← 用户配的 zhipu 配置消失了
```
用户 `data/model-settings.json` 里实际有两组配置（`zhipu` / `environment`）和一段用户画像；从仓库根启动只能看到 `environment`（回落 `.env`）。

**影响**：中。`config.py` 的注释已经明确记录过同类踩坑（「以前是相对进程工作目录的：从仓库根启动后端就会打开/新建另一份空库」），并锚定了 database/materials/backup 三个路径，**唯独漏了模型配置**。后果：
- 读不到 → 网页上配的其它 profile 与用户画像凭空消失；
- 更糟的是 `write_config()` 会把新文件**写到仓库根**，配置就此分裂成两份，用户以为「保存成功了」但下次从另一个目录启动又看不见。

当前被掩盖：`scripts/start-dev.ps1` 用 `-WorkingDirectory $backendDir` 启动，恰好 CWD 正确。

**修复**：`config_path()` 相对路径锚定到 `BACKEND_ROOT`（绝对路径原样返回，保证 `conftest.py` 注入的测试路径不受影响）。
**验证**：修复后从仓库根启动 `exists: True`、`profiles seen: ['83a47640-...', 'environment']`、用户画像保留。回归测试 3 个（含「换 CWD 后配置仍在」用**相对路径**才测得出锚定效果）。

---

### 问题 C【中 · 已修复】导入备份写到错误目录，已经产生了孤儿数据

**现象**：`app/services/export.py:_backup_path()` 用 `Path("data") / "backups"` —— 同样相对 CWD，而 `goals.py:purge_goal()` 用的是**已锚定**的 `settings.backup_dir`。两处备份目录分家。

**证据**：
```
settings.backup_dir (anchored, correct) : D:\...\services\api\data\backups
export._backup_path()  (CWD-relative)   : data\backups\aiedu-backup-20261030-092310.json

仓库根 data/ 目录实际存在：
  data/aiedu.db            0 字节      ← 空壳库（相对 DATABASE_URL 时期遗留）
  data/backups/            20 份 JSON  ← 孤儿备份
services/api/data/backups/ 373 份 JSON ← 正式备份
```
20 份孤儿备份经哈希比对**全部唯一、无一与正式目录重复**，都是 `full-export`（20 张表的完整备份），属于用户真实的数据安全网。

**影响**：中。用户在「偏好设置 → 导入备份」时，兜底备份被写到仓库根，**与他以为的备份位置不同**；正式备份目录里找不到这份「导入前快照」，出事时无从恢复。

**修复**：`_backup_path()` 改用 `Path(settings.backup_dir)`。
**数据处理**：20 份孤儿备份**移动**（不是删除）到 `services/api/data/backups/`，正式目录从 373 → 393 份，零丢失；0 字节空壳库与空目录删除。详见 `PROJECT_CLEANUP.md`。

---

### 问题 D【中 · 已修复】`TrainingRecord.target_type` 属性不存在，会让「用户画像建议」整块 500

**现象**：`app/api/model_settings.py:126` 读取 `r.target_type`，但 `TrainingRecord` **没有这一列**。

**证据**：
```python
>>> hasattr(TrainingRecord, "target_type")
False
>>> [c.name for c in TrainingRecord.__table__.columns]
['id','source_type','feature','goal_id','tutorial_id','section_id','system_prompt',
 'user_prompt','output_text','model_provider','model_name','prompt_tokens',
 'completion_tokens','total_tokens','usage_source','rating','tags','comment',
 'context_json','created_at']            ← 无 target_type
>>> TrainingRecord().target_type
AttributeError: 'TrainingRecord' object has no attribute 'target_type'
```
该值实际存在 `context_json` 里（`services/training.py:submit_feedback` 写 `context = {"target_type": ..., "client_context": ...}`，`_feedback_sample()` 也是从 `context_json` 读的）。同一份数据两种读法，其中一种是错的。

**影响**：中（潜伏）。触发条件是 `completed_count >= 10 and completed_count % 10 == 0`——用户当前只有 **1 个**已完成目标，所以还没撞上。一旦完成第 10 个目标，`GET /api/settings/models/user-profile-suggestion` 会因 `AttributeError` 抛 500，「用户画像建议」功能整块不可用。

**修复**：改从 `context_json` 读取（复用 `services.utils.jload`）。
**验证**：在**真实数据副本**上把已完成目标精确设为 10 个触发达标分支 → `200`，`eligible: true`，并正确生成建议文本，其中包含反馈里的 `target_type` 内容（探针评论「审计探针：验证 target_type 读取」出现在建议的 `profile_text` 里，证明读取路径真的走通了）。

---

### 问题 E【低 · 已修复】首页每次加载都可能白烧一次真实模型调用

**现象**：`apps/web/app/page.tsx:57` 在挂载阶段的 `Promise.all` 里请求 `/api/settings/models/user-profile-suggestion`，把结果解构成 `suggestionData`，然后**从未使用**（没有 `setSuggestion`）。ESLint 已报警：
```
app/page.tsx  57:34  warning  'suggestionData' is assigned a value but never used
```

**为什么是「烧钱」而不只是「多余请求」**：该端点在达标时会**真的调用模型**生成画像建议（`AIService(db).user_profile_suggestion(context)`）。所以每次打开首页都可能触发一次真实 LLM 调用，然后把结果丢掉。建议实际只在「用户画像」弹窗里展示，而弹窗打开时已经会调 `loadSuggestion()`——**功能上完全冗余**。

**次生问题**：`loadSuggestion()` 自身没有 try/catch，而调用方是 `void loadSuggestion()`，模型失败时会产生**未处理的 Promise rejection**，弹窗既不显示建议也不提示原因。

**修复**：从挂载阶段移除该请求；`loadSuggestion()` 补 try/catch，失败落到 `profileError`（用文件内既有的 `e instanceof Error ? e.message : String(e)` 写法，不引入跨层依赖）。
**验证**：浏览器实测首页挂载**不再发出**该请求（抓到 5 个 `/api` 请求，无 `user-profile-suggestion`）；点开「用户画像」弹窗后才发出（1 次）。ESLint 该警告消失，其余警告从 3 → 2。

---

### 问题 F【低 · 已修复】文档与实现严重不符（10 阶段 vs 5 阶段）

| 文件 | 过时内容 | 实际实现 |
|---|---|---|
| `docs/architecture.md` §1 | 画了 `features/*`、`models/`、`schemas/`、`repositories/`、`prompts/` 目录 | 前端是 `app/`+`components/`+`lib/`；后端 `models.py`/`schemas.py` 是**单文件**；**没有** `repositories/`；`prompts.py` 在 `llm/` 下 |
| `docs/architecture.md` §3 | `goal_definition → … → learning → practice → feedback → assessment → reflection → knowledge_update`（10 阶段） | `engine.py:PHASES` 只有 **5 阶段**，`learning` 是终点 |
| `docs/architecture.md` §2 | 提到「PromptVersion 表」 | 无此表；提示词版本记在 `TutorialVersion.prompt_version` |
| `docs/user-guide.md` §二 | 详述「⑤实践任务 ⑥能力评估 ⑦复盘 ⑨知识提议」的界面操作步骤 | 这些**界面已移除**（`learning/page.tsx` 里 grep 不到任何相关 UI） |
| `docs/user-guide.md` §一 | 前端 `npm install` | 实际是 pnpm（`pnpm-lock.yaml`，`node_modules` 为 pnpm 结构） |
| `工作区文件功能说明.md` §一 | 核心链路含「实践/答疑/反馈 → 能力评估 → 复盘」 | 同上 |
| `GoalPhaseView.tsx` | 注释「十步导航」「十步阶段条」；`aria-label="学习目标十项流程"` | 只有 5 项。`aria-label` 是**读屏软件可观察文案**，属于事实错误 |
| `README.md` | 前端 `npm install` | 同上；且 `npm ls` 在 pnpm 树上会报大量 `invalid` |

**影响**：低（不影响运行），但**误导性强**：新接手的人（或 AI agent）按文档去找 `practice` 子页、`repositories/` 目录会一无所获；按 `user-guide` 操作会找不到「⑤⑥⑦」按钮。

**修复**：`architecture.md`（分层图 + 状态机）、`user-guide.md`（五阶段流程 + 明确标注「旧版说明」+ FAQ 两条新增）、`工作区文件功能说明.md`（链路图）、`README.md`（pnpm + 混用警告）、`scripts/start-dev.ps1`（提示文案）、`GoalPhaseView.tsx`（注释与 `aria-label` 改为**由 `GOAL_PHASES.length` 派生**，避免流程再调整时又一次与文案脱节）。

---

### 问题 G【低 · 已修复】数据卫生：误提交的二进制与临时产物

| 对象 | 问题 | 处理 |
|---|---|---|
| `services/api/debug_format2.db-shm` (32 KB)<br>`services/api/debug_format2.db-wal` (800 KB) | **被 git 跟踪**。SQLite 的 WAL/SHM 边车文件是运行时产物，每次启动都变，提交进仓库纯属噪音；`.gitignore` 的 `*.db` **匹配不到** `.db-shm`/`.db-wal` 后缀，这就是它们能溜进去的原因 | `git rm --cached` 取消跟踪 + 补 `.gitignore` 规则 |
| `debug_contract.db` `debug_format.db` `debug_format2.db` | 调试遗留库，全仓库 grep **零引用** | 删除 |
| 20 个 `pip-build-tracker-*` / `pip-install-*` / `pip-ephem-wheel-cache-*` / `pip-download-*` | pip 中断遗留，**内含 0 个文件** | 删除 |
| `services/api/data/e2e_check.db*` (3 个文件，2.1 MB) | 早期 e2e 验证遗留，零引用 | 删除 |
| 仓库根 `data/`（0 字节 `aiedu.db` + `backups/`） | 问题 C 造成的孤儿目录 | 备份移走后删除目录 |
| `.audit/`（23 个文件，80 KB） | **审计过程中被用户的 `3740070` 提交误纳入仓库** | `git rm --cached` 取消跟踪 + 加入 `.gitignore` |

`.gitignore` 补充规则：`*.db-shm` `*.db-wal` `*.db-journal`、`services/api/pip-*/`、`services/api/debug_*.db*`、`services/api/tests/test_aiedu.db*`、`services/api/tests/test_model_settings.json`、`apps/web/tsconfig.tsbuildinfo`、`.audit/`。

---

### 问题 H【低 · 已修复】`pnpm-workspace.yaml` 是未填写的占位符，导致 pnpm install 直接失败

**现象**：文件内容字面就是模板提示语：
```yaml
allowBuilds:
  unrs-resolver: set this to true or false
```
**证据**：
```
$ pnpm install --frozen-lockfile --offline --ignore-scripts
Error: ERR_PNPM_IGNORED_BUILDS
  × installing dependencies
  ╰─▶ Ignored build scripts: unrs-resolver@1.12.2
```
`allowBuilds` **是合法的 pnpm 配置键**（`pnpm config list` 能读到它），问题在于值是一句英文占位符而非布尔值。

**影响**：低但确定。任何人按 README 用 pnpm 装依赖都会**直接失败**；且这个文件会误导读者以为需要手工改。

**修复**：显式设为 `false` 并写明理由（`unrs-resolver` 是 eslint 的原生模块解析器，其安装脚本在本项目一直被 pnpm 默认跳过，而 lint / tsc / next build 全部正常通过 → 保持既有行为）。
**验证**：`pnpm install --frozen-lockfile --dry-run --offline` → `Dry run complete. pnpm-lock.yaml is up to date; a real install would make no changes.`，`ERR_PNPM_IGNORED_BUILDS` 消失，lockfile 无变化。

---

### 问题 I【低 · 仅记录，未改动】`decision` 字段无枚举校验

`app/schemas.py:DecisionIn.decision: str` 是自由字符串，而 `pipeline.py:210-227` 靠**中文字面量**匹配：
```python
explicit_continue = assessment.user_decision in {"坚决执行", "采纳建议继续"}
paused = not explicit_continue and (assessment.user_decision == "暂停" or ...)
```
实测 `POST /api/goals/{id}/decision {"decision":"nonsense"}` → `200 {"ok": true}`，任意字符串都被接受。

**为什么没改**：网页与 Obsidian 插件**都不直接调这个端点**（前端走 `quickstart` 的 `pause_action: Literal["proceed","adopt"]`，由后端自己写入正确的中文值），所以现实中不会被写坏。改成 `Literal[...]` 会让「继续」等后端内部写入值需要一并纳入枚举，属于**行为变更**，超出「低风险修复」范围。

**建议**（保留原状，记录备查）：若要收紧，应把 `decision` 改为 `Literal["坚决执行","采纳建议继续","暂停","继续"]`，并同步检查 `pipeline.py` 的三处字面量；或引入英文枚举 + 中文标签映射表，彻底摆脱中文字面量匹配。

---

### 问题 J【低 · 仅记录，未改动】`by_feature[].usage_source` 恒为空字符串

`services/usage.py:goal_usage()` 用 `add_usage(feature, ...)` 累加，但 `utils.add_usage()` 只累加 `prompt/completion/total/calls`，**不传递 `usage_source`**。实测：
```json
{"totals": {..., "usage_source": "provider"},
 "by_feature": [{"feature":"diagnose", ..., "usage_source": ""}]}
```
`totals` 的 `usage_source` 是单独算的（正确），只有 `by_feature` / `by_tutorial` 里是空串。

**为什么没改**：前端**不消费**这个字段——`tutorials/[tid]/page.tsx:387-392` 只渲染 `item.feature` 与 `item.total_tokens`；来源标签走的是 `usage.provider_calls` / `usage.estimated_calls`（这两个是对的）。改它会变动 API 输出契约，而无人受益。

**建议**：要么让 `add_usage` 接受并合并 `usage_source`（与 `training.py:stats()` 里的写法保持一致），要么把该字段从 `by_feature` 的输出里去掉，避免「看起来有值其实永远为空」的误导。

---

### 问题 K【低 · 仅记录，未改动】4 条路由前端与插件都不引用

用「路由特征串在 web/plugin/tests 源码里做子串匹配」精确扫描 86 条路由，得到 4 条孤儿候选：

| 端点 | 测试覆盖 | 判断 |
|---|---|---|
| `PATCH /api/plans/{plan_id}` | ❌ 无任何测试 | **真孤儿**：前端只能改步骤（`goals/[id]/page.tsx` 无调用），后端 `patch_plan` 也无测试 |
| `POST /api/tutorials/{id}/restore/{version}` | ✅ | 后端能力完整（实测回滚到 v1 成功、404 兜底正确），前端只显示「历史 N 个版本」而没有回滚按钮 |
| `POST /api/goals/{id}/criteria/manual` | ✅ | 手工添加单条验收标准，前端只提供了「一键同意全部」 |
| `POST /api/goals/{id}/knowledge-proposals`<br>`POST /api/knowledge/proposals/{id}/review` | ✅ | 知识提议生成与审核，界面已随 10 阶段一起移除 |

**为什么没删**：删除公开 API 属于**改变可观察行为**，超出本次「明确、安全、有实际收益」的整理边界；且其中 3 条有测试覆盖，说明是刻意保留的后端能力。

**建议**：
- `PATCH /api/plans/{plan_id}`：要么补测试并在前端接上（计划步骤编辑目前是只读的），要么删除。这是唯一一条**既无调用方又无测试**的路由。
- `restore/{version}`：功能完整且有测试，**建议在前端补一个版本回滚入口**——教程页已经显示「历史 N 个版本」，用户能看到却用不了。

---

## 3. 未发现问题的方面（正面确认）

审计中重点检查过、**确认没有发现问题**的方面：

| 检查项 | 结论 |
|---|---|
| 密钥泄露 | ✅ `public_config()` 只返回 `has_key` 布尔值，密钥永不回传前端；`write_config` 用 `0o600` 权限 + 临时文件 `os.replace` 原子写；`resolve_profile()` 在 base_url 变更时**不转发旧密钥**（`test_model_settings.py` 有覆盖）；错误响应经 `_log_unhandled` 落盘但返回给前端的消息截断到 300 字符且不含堆栈 |
| 并发安全 | ✅ 所有后台任务（并行初始三件套 / 章节 / 配套 / 知识提取）都是**独立 `SessionLocal()` + 独立 `AIService`**，不共享 Session；知识提取有全局串行锁 `_KNOWLEDGE_EXTRACTION_LOCK` 防「查-插」重复概念；SQLite 配 `busy_timeout=30000` + WAL |
| 幂等性 | ✅ `quickstart` 每步先查现状标 `reused`；`start_sections`/`start_companions` 复用进行中的 job；`confirm_all_criteria` 重复调用 `changed=0` 且**不覆盖 rejected**（实测验证） |
| 竞态保护 | ✅ 前端 `useGoalWorkspace` 用 `loadSeq` ref 做请求序号保护，旧响应不覆盖新数据；`job-poll.ts` 返回 cancel 函数，调用方在重新提交与卸载时都会调用；有 20 分钟轮询上限防僵尸轮询 |
| 数据安全阀 | ✅ 导入时若备份不含知识网络而当前有 → `409 knowledge_would_be_cleared`，需 `force=true`（实测：2 概念/1 关系未被清空）；`purge_goal` 删除前先写 JSON 备份（实测备份文件存在且可读） |
| 演示模式诚实性 | ✅ 未配置模型时 `demo: true` 显式标注；token 无 usage 时标 `usage_source: estimated`；`_demo()` 的 system prompt 直接写明「演示生成器…未配置真实模型」；失败调用只记 `ModelCallLog(status="error")`，**不产生训练样本**（避免污染数据集） |
| 训练数据隔离 | ✅ 用户真实库在审计前后完全一致（`training_records` 448 / `model_call_logs` 512 / `learning_goals` 26 / `concepts` 389 / `relations` 611），审计产生的 2 条记录已精确定位并删除 |
| 前后端契约一致 | ✅ `goal-phases.ts` 与 `engine.py:PHASES` 顺序一致；`phase()` 对写错的 key **立即抛错**而非静默上线；`materials/limits` 由后端提供上限，避免前后端校验不一致 |
| 错误语义 | ✅ 统一 `{code, message}` 结构；前端 `errorFrom()` 能解析 4 种 detail 形态；404/409/422/502 分工清晰（实测各异常路径返回码正确） |

---

## 4. 遗留风险与建议

### 4.1 需要用户操作的一项

⚠️ **线上后端进程仍在运行修复前的代码。**

```
线上后端 PID 17720 启动时间 : 2026-10-30 18:09:13
我的代码修改落盘时间        : 2026-10-30 18:25:24 ~ 18:25:30
=> 进程早于代码修改，内存里仍是旧代码
```

- **问题 A（训练数据 500）在当前线上服务上已经修好**——因为索引是**数据库级**变更，我已在用户真实库上执行过 `CREATE INDEX`（执行前先用 SQLite 官方 online backup API 做了 22.6 MB 一致性快照，`integrity_check: ok`），SQLite 在查询计划期即时选用新索引，无需重启。
- **问题 B/C/D/E 需要重启后端与前端才能生效**（都是 Python/TS 代码变更）。

**建议**：方便时关闭「AI Edu 后端」「AI Edu 前端」两个窗口，重新执行 `aiedu` 启动即可。重启后 `init_db()` 会自动跑 `_migrate_sqlite_indexes()`，即使换一台机器、拿一份没有索引的旧库也能自动补齐。

### 4.2 前端零自动化测试

后端 129 个用例（审计前）+ 13 个新增，但 `apps/web` **没有任何测试框架**（`package.json` 只有 `dev/build/start/lint`）。本次前端验证全靠 Playwright 手工驱动真实浏览器完成，无法纳入 CI。

**建议**（成本从低到高）：
1. 最低成本：把 `lib/goal-phases.ts`、`lib/job-poll.ts`、`lib/tutorial-continue.ts` 这三个**纯逻辑模块**纳入 vitest——它们承载了阶段顺序、轮询取消、自动续跑闸门等最容易回归的逻辑，且无需渲染。
2. 中等成本：用 Playwright 建 2-3 条冒烟流程（首页 → 创建目标 → 教程页），指向演示模式后端，即可零 token 成本跑 CI。

### 4.3 `legacy/phase0/` 与根方案文档的定位

`legacy/phase0/`（13 个文件）与 `AI-Edu-最终执行方案-Agent版-v2.0.md`（669 行）都**不参与运行**。README 已明确前者是「资产存档，仅参考」、是产品种子数据来源。方案文档描述的是 10 阶段完整愿景，与当前 5 阶段实现有差距。

**建议**：保留（有历史价值，且 README 已正确定位）。但 `architecture.md` 开头写着「与 v2.0 冲突时以 v2.0 为准并修订本文」——这句话现在**方向反了**：v2.0 是愿景，实现已按实际使用体验收敛。已在本次修复中把状态机一节改为「当前实现」并说明差异，但建议后续把这句优先级声明也一并调整，否则读者会以为 10 阶段才是权威。

### 4.4 单一 `services/api/data/errors.log` 无轮转

`errors.log` 已 157 KB / 16 次异常，只追加不轮转。长期运行会无限增长。

**建议**：加简单的大小轮转（如超 5 MB 改名为 `.1` 并新建），或改用 `logging.handlers.RotatingFileHandler`。低优先级。

---

## 5. 审计方法说明（可复现）

本次审计**不使用「读代码即宣称正常」**的方式，具体手段：

| 手段 | 用途 |
|---|---|
| 直接调用**用户正在运行的线上服务**（8000） | 发现真实故障（问题 A 就是在线上抓到的，且与用户自己的 `errors.log` 交叉印证） |
| **隔离演示后端**（8199，独立 SQLite + 独立材料/备份目录 + `DEMO_MODE=1`） | 跑完整写路径业务流程，**零风险**不碰用户数据、**零成本**不烧 token |
| **真实数据副本后端**（8198，用 SQLite online backup API 取用户 22 MB 库的一致性快照，并**故意删掉新索引**模拟老库） | 验证修复在真实数据规模下成立，并验证老库自动补索引的升级路径 |
| **Playwright + 真实 Chrome** 驱动真实前端（3001） | UI 级验证；对写操作用 `page.route()` 把 `/api/*` 改道到隔离后端，做到「真实 UI + 隔离数据」 |
| **变异测试（mutation probe）** | 逐个把修复回退成缺陷版本，确认新测试**真的会失败**——5 处修复全部被捕获（详见 `PROJECT_TEST_REPORT.md` §5） |
| 数据库层直查 | `EXPLAIN QUERY PLAN`、`sqlite_master`、`PRAGMA integrity_check`、孤儿行检测 |
| 精确孤儿扫描 | 从运行中的 `openapi.json` 取 86 条路由，用路径特征串在 web/plugin/tests 源码里匹配（并修正了首轮宽松匹配的假阳性） |

**审计自身的数据卫生**：所有测试产生的数据都已清理。用户真实库在审计前后计数完全一致；我创建的 1 个临时目标已 `purge`，其残留的 1 条 `training_record` + 1 条 `model_call_log`（`purge` 按设计会保留训练样本仅置空 `goal_id`）已按 `context_json.goal_id` 精确定位删除；临时备份文件已删；探针临时目录（23.6 MB）已删。

---

## 6. 未验证事项（明确声明）

以下环节**没有做实际验证**，不宣称通过：

| 事项 | 原因 |
|---|---|
| 真实模型的**完整教程生成**（大纲 + 全部章节 + 配套文件） | 会产生真实 token 开销（用户历史数据显示单教程章节生成累计 5.35M tokens）。只验证了**真实模型的最小链路**：`POST /settings/models/test` 结构化 JSON 测试通过（905ms，103 tokens，`usage_source: provider`），以及一次真实 `diagnose`（10.0s，2395 tokens，`demo: false`，token 记账与训练样本落库均正确）。完整章节生成链路是在**演示模式**下验证的 |
| Obsidian 插件在**真实 Obsidian 运行时**内的行为 | 需要 Obsidian 应用与真实 Vault。只跑了它的独立行为测试（`node obsidian-plugin/tests/behavior-test.js` → passed，覆盖 7 类行为），以及核对了它调用的 5 组 API 路径与载荷形状（`/delivery` 的 `{status,path,version}` 与后端 schema 一致，已实测通过） |
| `zhipu` 模型配置（`https://<INTERNAL-GATEWAY-REDACTED>/v1`，`glm-5.3-flash`） | 未激活、未调用。只验证了当前激活的 `environment`（deepseek）配置 |
| Windows「智能应用控制」拦截场景 | README 记录的两类拦截（`.cmd` 双击、SQLAlchemy C 扩展 `_row_cy`）未复现验证；`scripts/disable_blocked_native_extensions.py` 未执行（当前环境无此问题） |
| 多用户 / 公网部署安全性 | 产品定位为单用户本地运行，`docs/user-guide.md` §五已声明「公网部署前必须增加访问保护」。未做安全渗透测试 |
| 生产构建产物的运行时行为 | `next build` 通过（16 条路由全部成功预渲染），但只验证了 dev 模式的运行时行为；`next start` 未启动验证 |
| 前端在 dev 模式下每个 `/api` 请求发两次 | 已确认是 React StrictMode 双调用 effect 的**开发期预期行为**（`next.config.ts` 未配 `reactStrictMode`，Next 16 dev 默认开启），生产构建不受影响。未启动生产构建复验 |
