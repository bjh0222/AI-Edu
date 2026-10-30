# PROJECT_CLEANUP.md — 整理明细

> 时间：2026-10-30　基线：`main` @ `3740070`
> 原则：**先确认依赖关系，再动手**；只清理「确认废弃且不再被使用」的对象；用户数据一律**移动/保留**而非删除；不改变产品定位、核心业务规则与用户可观察行为。

---

## 0. 前置：Git 工作区保护

审计开始时执行 `git status --porcelain=v1` → **工作区干净**（`main` @ `59c4241`）。

审计过程中用户提交了 `3740070`（「排版」），把 6 个功能文件**和 23 个我的审计脚本**一并纳入。处理方式：

- 用户提交的 6 个功能文件（`app/llm/prompts.py`、`app/services/format_specs.py`、`app/services/tutorials.py`、`app/services/utils.py`、`tests/test_format_specs.py`、`tests/test_tutorial_v2.py`）**全程未被修改**——本次所有代码改动都落在互不重叠的文件上，不存在覆盖或冲突。
- 我的 23 个审计脚本用 `git rm --cached` **取消跟踪**（文件保留在磁盘），并加进 `.gitignore`。

改动前后 `git status` 对比见 §6。

---

## 1. 代码修复（6 个文件）

| 文件 | 改动 | 对应问题 | 行为影响 |
|---|---|---|---|
| `services/api/app/models.py` | `TrainingRecord.created_at`、`ModelCallLog.created_at` 加 `index=True` | A | 无（纯索引，查询语义不变，分页变快） |
| `services/api/app/db.py` | 新增 `_migrate_sqlite_indexes()`，在 `init_db()` 里为已存在的表补建索引；用 `CreateIndex(index, if_not_exists=True)` 编译 DDL | A | 无（幂等、失败只记日志不阻塞启动） |
| `services/api/app/model_settings.py` | `config_path()` 相对路径锚定到 `BACKEND_ROOT` | B | 从仓库根启动不再「丢失」已保存的模型配置与用户画像 |
| `services/api/app/services/export.py` | `_backup_path()` 改用 `settings.backup_dir` | C | 导入前的兜底备份落到正确目录，与 `purge_goal` 一致 |
| `services/api/app/api/model_settings.py` | `target_type` 改从 `context_json` 读取（复用 `services.utils.jload`） | D | 「用户画像建议」在完成第 10 个目标后不再 500 |
| `apps/web/app/page.tsx` | 移除挂载阶段对 `user-profile-suggestion` 的请求；`loadSuggestion()` 补 try/catch | E | 首页不再白烧模型调用；建议失败时有提示而非静默 |

**关键取舍：为什么用 `CreateIndex` 而不是手拼 SQL**

`format_specs.uq_format_specs_default` 是**部分唯一索引**：

```sql
CREATE UNIQUE INDEX uq_format_specs_default ON format_specs (is_default) WHERE is_default = 1
```

手拼 `CREATE {UNIQUE}INDEX ... ON {table} ({cols})` 会**丢掉 `WHERE is_default = 1`**，把「只能有一个默认规范」悄悄放宽成全表唯一——第二条 `is_default=0` 的规范就再也插不进去了。这个坑在实现过程中被识别，改为让 SQLAlchemy 自己编译 DDL，并补了专门的回归测试 `test_index_migration_keeps_partial_unique_predicate`。

**关键取舍：为什么用索引而不是 `PRAGMA temp_store=MEMORY`**

`temp_store=MEMORY` 也能修好（实测通过），但：
- 它把排序溢出挪进内存，`training_records` 已有 7.3 MB 文本，继续增长会吃内存；
- 它**治标**：查询仍然全表排序，只是换了个地方溢出；
- 索引**治本**：`EXPLAIN QUERY PLAN` 里 `USE TEMP B-TREE FOR ORDER BY` 直接消失，分页从「全表排序」降到 `O(limit)`，实测 50 行分页 **0.009s**，且对临时目录是否可写完全免疫。

---

## 2. 配置修复（2 个文件）

| 文件 | 改动 | 对应问题 |
|---|---|---|
| `.gitignore` | 补 `*.db-shm` `*.db-wal` `*.db-journal`（`*.db` 匹配不到这些后缀，这正是二进制能溜进仓库的原因）、`services/api/pip-*/`、`services/api/debug_*.db*`、`services/api/tests/test_aiedu.db*`、`services/api/tests/test_model_settings.json`、`apps/web/tsconfig.tsbuildinfo`、`.audit/` | G |
| `apps/web/pnpm-workspace.yaml` | `unrs-resolver: set this to true or false`（未填写的模板占位符）→ `unrs-resolver: false` + 理由注释 | H |

`pnpm-workspace.yaml` 选 `false` 的依据：`unrs-resolver` 是 eslint 的原生模块解析器，pnpm 默认就跳过依赖的 build script，而 `eslint` / `tsc --noEmit` / `next build` 全部正常通过 → `false` 是**保持既有行为**的取值，同时消掉每次 install 都报的 `ERR_PNPM_IGNORED_BUILDS`。用 `--dry-run` 验证过 lockfile 无变化。

---

## 3. 文档修复（5 个文件）

| 文件 | 改动 |
|---|---|
| `docs/architecture.md` | ① 分层图按**真实目录结构**重写（前端 `app/`+`components/`+`lib/`；后端 `models.py`/`schemas.py` 是单文件；明确「没有 repositories/ 层」；`prompts.py` 在 `llm/` 下）② 状态机从 10 阶段改为**实际的 5 阶段**，指明单一事实来源（`engine.py:PHASES` ↔ `goal-phases.ts:GOAL_PHASES`），并说明旧 5 个阶段「已从用户流程移除但后端能力保留」③ 删除不存在的「PromptVersion 表」说法 |
| `docs/user-guide.md` | ① §二 整节重写为五阶段流程，逐阶段对齐真实界面（含「创建并自动生成教程 / 仅创建目标」两个按钮的真实文案、暂停时的三个选项、单节重生成的互斥禁用、历史版本数）② 补「学习反馈」「上下文答疑」两块**仍在界面上**的能力 ③ 用引用块明确标注「旧版说明」，列出已移除的 4 个环节及其仍可用的后端接口 ④ 前端命令 `npm` → `pnpm` ⑤ FAQ 新增两条（训练数据页 SQL 报错的成因与修复、换目录启动后配置「消失」的说明） |
| `工作区文件功能说明.md` | 核心链路图从「… → 实践/答疑/反馈 → 能力评估 → 复盘 → 知识网络」改为五阶段 + 两条支线（教程学习页内的反馈/答疑、后台自动提取的知识网络），并注明旧环节的去向 |
| `README.md` | 前端 `npm install/npm run dev` → `pnpm install/pnpm dev`，并加引用块说明：仓库以 `pnpm-lock.yaml` 为准、`package-lock.json` 当前也同步、**但不要在同一份 `node_modules` 上混用两个管理器**（布局不同会得到彼此 invalid 的依赖树；要用 npm 先删 `node_modules`） |
| `scripts/start-dev.ps1` | 依赖缺失提示 `npm install` → `pnpm install（本仓库前端用 pnpm，勿与 npm 混用）`。**保留 UTF-8 BOM**（Windows PowerShell 5.1 靠 BOM 才能正确解码文件里的中文提示），改完用 `Parser::ParseFile` 验证语法无误 |

> 启动脚本仍用 `npm run dev` 拉起前端——这**没有改**：`npm run` 只是脚本执行器，在 pnpm 装出来的树上跑 `next dev` 是正常的（实测前端服务正常）。只有 `npm install` 会破坏依赖树，所以只改了提示文案。

### 3.1 代码内注释/可访问性文案修复

| 文件 | 改动 |
|---|---|
| `apps/web/components/goals/GoalPhaseView.tsx` | 注释「十步导航」「十步阶段条」→「阶段导航」「阶段条」；`aria-label="学习目标十项流程"` → ``aria-label={`学习目标流程（共 ${GOAL_PHASES.length} 个阶段）`}``。**改为从数组派生而非写死数字**，这样流程再调整时不会又一次与文案脱节。`aria-label` 是读屏软件可观察文案，写「十项」而实际五项属于事实错误 |
| `apps/web/app/tutorials/[tid]/page.tsx`<br>`apps/web/components/goals/useGoalWorkspace.ts` | 移除失效的 `// eslint-disable-next-line react-hooks/set-state-in-effect`（该指令已不再抑制任何东西：`setState` 在异步 `load()` 内部，不在 effect 同步体里），并把旁边「该规则对异步 setState 误报」的注释改成准确描述，避免留下指向已删除指令的悬空注释。**纯注释级改动，行为不变**；移除前实证确认「移除后 lint 仍 0 error」 |

全仓库复查：`git grep -e 十步 -e 十项 -e 十阶段` → **零残留**。

结果：`npm run lint` 从 **0 errors / 3 warnings** 变为 **0 errors / 0 warnings**（完全干净），`tsc --noEmit` exit 0，`next build` 16 条路由全部成功，UI 回归 16 项全绿。

---

## 4. 文件与目录清理

### 4.1 用户数据：只移动，不删除

| 对象 | 处理 | 结果 |
|---|---|---|
| 仓库根 `data/backups/*.json`（20 份） | **移动**到 `services/api/data/backups/` | 正式备份 **373 → 393 份**，零丢失 |

移动前先做了安全检查：
- 逐份 `json.load` 验证可解析（不可解析的一律 SKIP 保留原样）；
- 逐份算 SHA-256 与正式目录 373 份比对 → **20 份全部唯一，无一重复**，都是 `full-export`（20 张表的完整备份），属于真实的数据安全网；
- 同名冲突时先比内容：相同则删源，不同则加 `recovered-from-repo-root-` 前缀保留（本次未触发）。

### 4.2 确认废弃后删除（29 项）

| 对象 | 数量 | 确认方式 |
|---|---|---|
| 仓库根 `data/aiedu.db` | 1（0 字节） | 空壳库，路径未锚定时期遗留；正式库在 `services/api/data/aiedu.db`（22.7 MB） |
| `services/api/debug_contract.db`<br>`debug_format.db`<br>`debug_format2.db`(+`-shm`,`-wal`) | 5 | `git grep` 全仓库搜索 `debug_contract` / `debug_format` / `debug_format2` → **零引用** |
| `services/api/pip-build-tracker-*`<br>`pip-install-*`<br>`pip-ephem-wheel-cache-*`<br>`pip-download-*` | 20 目录 | pip 中断遗留；递归统计**内含 0 个文件** |
| `services/api/data/e2e_check.db`(+`-shm`,`-wal`) | 3 | `git grep e2e_check` → **零引用** |
| 清空的 `data/backups/`、`data/` 目录 | 2 | 备份移走后为空 |

### 4.3 取消 git 跟踪（文件保留在磁盘）

| 对象 | 数量 | 原因 |
|---|---|---|
| `services/api/debug_format2.db-shm`（32 KB）<br>`services/api/debug_format2.db-wal`（800 KB） | 2 | **被误提交进仓库的二进制**。SQLite WAL/SHM 是运行时边车文件，每次启动都变，属于纯噪音。`.gitignore` 的 `*.db` 匹配不到 `.db-shm`/`.db-wal` 后缀——这就是它们能溜进去的根因，已补规则 |
| `.audit/**` | 23 | 我的审计脚本被用户的 `3740070` 提交误纳入；已加 `.gitignore` |

合计从索引移除 25 个文件、1488 行。

### 4.4 审计自身残留清理

| 对象 | 处理 |
|---|---|
| `services/api/aieduprobe_wwvxcqx6/`（21.6 MB）、`spilltest_283mbzjr/`（2.0 MB） | 我的探针在 `services/api` 下用 `tempfile.mkdtemp` 建的数据库副本目录 → 删除。`services/api` 现只剩 `.venv app data scripts tests pytest.ini requirements.txt` |
| `services/api/pytest-of-BJH/`、`.pytest_cache/` | 测试运行产物 → 删除（会自动重建） |
| 用户真实库里的 2 条测试记录 | 见 §5 |

---

## 5. 用户真实数据的完整性保障

这是本次整理**最需要谨慎**的部分。审计在用户真实库（22.7 MB）上做过一次真实模型链路验证，产生的数据已精确清除：

**做了什么**：创建 1 个临时目标 → 真实 `diagnose` → `purge` 删除。

**发现的残留**：`purge_goal()` **按设计**保留训练样本与调用日志供审计（`goals.py:201-206`：「训练样本 / 调用日志保留（历史审计），仅去除目标关联」），只把 `goal_id` 置空。所以我的测试留下了：
- 1 条 `training_records`（`goal_id=NULL`，但 `context_json.goal_id` 仍是那个临时目标）
- 1 条 `model_call_logs`（同样 `goal_id=NULL`）

**如何精确定位并删除**（绝不用时间范围粗暴删）：
```python
# 双重校验：context_json 里的 goal_id == 我的临时目标 AND user_prompt 含目标标题标记
SELECT ... FROM training_records WHERE context_json LIKE '%6323498b...%'
# → 命中 1 条，校验通过才删；model_call_logs 按精确到 0.1 秒的时间窗 + feature 锁定 → 命中 1 条
```
删除前后计数：`training_records 449 → 448`、`model_call_logs 513 → 512`，与审计开始前完全一致。

**顺带发现并澄清的一件事**：库里共有 **61 条** `goal_id IS NULL` 的训练记录。核查后确认这**不是缺陷**，而是 `purge_goal` 的刻意设计（保留历史审计），且 `context_json` 里仍留着原 `goal_id` 可追溯。审计只删了自己产生的 2 条，用户的 61 条历史记录一条未动。

**最终完整性核对**：

| 对象 | 审计前 | 审计后 |
|---|---|---|
| `learning_goals` | 26 | 26 |
| `training_records` | 448 | 448 |
| `model_call_logs` | 512 | 512 |
| `concepts` / `concept_relations` | 389 / 611 | 389 / 611 |
| `data/backups`（正式） | 373 | **393**（+20 从孤儿目录回收） |
| `data/materials` | 13 个目标目录 | 13 |
| `aiedu.db` 大小 | 22,695,936 B | 22,695,936 B |
| `PRAGMA integrity_check` | ok | **ok** |
| 用户 `model-settings.json` | 2 组配置 + 用户画像 | 未改动 |

**额外保险**：在对真实库执行 `CREATE INDEX` 之前，先用 SQLite 官方 online backup API 做了一份 22.6 MB 一致性快照（`integrity_check: ok`），存于 `.audit/aiedu-premigrate-*.db`。该目录已被 `.gitignore` 排除，可在确认无误后删除。

---

## 6. 整理前后对比

### 6.1 Git 索引

```
整理前（3740070 提交后）：
  跟踪 .audit/**                      23 个文件（80 KB）  ← 不该在仓库里
  跟踪 debug_format2.db-shm/-wal      2 个二进制（832 KB）← 不该在仓库里
  .gitignore 覆盖不到 *.db-shm/*.db-wal

整理后：
  上述 25 个文件全部取消跟踪（磁盘文件保留），并补齐 ignore 规则
  git status 只剩：6 个代码/配置修复 + 5 个文档修复 + 1 个新增测试文件
```

### 6.2 目录

```
services/api/  整理前：app data scripts tests + 3 个 debug_*.db(+2 边车)
                        + 20 个 pip-* 目录 + .pytest_cache + pytest-of-BJH
                        + aieduprobe_* + spilltest_*          ← 后两个是审计探针
               整理后：app data scripts tests pytest.ini requirements.txt .venv

仓库根 data/   整理前：aiedu.db(0 B) + backups/(20 份孤儿备份)
               整理后：不存在（备份已并入正式目录，空壳库与空目录已删）
```

### 6.3 体积

| 位置 | 整理前 | 整理后 |
|---|---|---|
| `services/` | 99.5 MB | 125.2 MB（审计中一度更高，含探针副本；探针清理后回落）|
| 仓库（不含 `node_modules`/`.venv`/`.git`/`.pnpm-store`） | — | 100.4 MB |
| 从 git 索引移除 | — | 25 文件 / 1488 行 / 约 912 KB 二进制 |

> 说明：`services/api/data` 增长来自正式备份 373 → 393（回收的 20 份孤儿备份，约 700 KB）与 `errors.log` 增长，都是**用户数据**，不是垃圾。

---

## 7. 需要人工进一步判断的对象（保留原状）

以下对象**没有动**，因为无法确认「安全且有收益」，或涉及产品取舍：

| 对象 | 为什么保留 | 建议 |
|---|---|---|
| `legacy/phase0/`（13 文件） | README 明确定位为「阶段 0 资产存档，仅参考」「产品种子数据的来源」；`docs/decisions.md` 多处引用其理念 | 保留。若确认永不再参考，可移到独立存档仓库 |
| `AI-Edu-最终执行方案-Agent版-v2.0.md`（669 行） | 是 README 声明的「当前执行基线」，但描述的是 10 阶段完整愿景，与 5 阶段实现有差距 | 保留。建议把 `architecture.md` 开头「与 v2.0 冲突时以 v2.0 为准」这句优先级声明反过来——现在实现才是权威 |
| `apps/web/package-lock.json`（232 KB） | 与 `pnpm-lock.yaml` **并存**。经核对两者当前都与 `package.json` 同步，`node_modules` 是 pnpm 结构 | **需要你定夺**：若确定用 pnpm，删掉 `package-lock.json` 更干净；若保留双管理器兼容，README 已加「不要混用」警告。删除 lockfile 属于会影响他人工作流的选择，未擅自执行 |
| `PATCH /api/plans/{plan_id}` | 前端、插件、测试**都不引用**（唯一一条既无调用方又无测试的路由） | 补测试 + 前端接上（计划步骤目前只读），或删除 |
| `POST /api/tutorials/{id}/restore/{version}` | 后端能力完整且有测试（实测回滚成功），但前端只显示「历史 N 个版本」没有回滚按钮 | **建议在前端补入口**——用户能看到版本数却用不了 |
| `POST /api/goals/{id}/criteria/manual`<br>`POST /api/goals/{id}/knowledge-proposals`<br>`POST /api/knowledge/proposals/{id}/review` | 有测试覆盖，属于刻意保留的后端能力；界面随 10 阶段一起移除 | 保留。若将来恢复「知识提议审核」界面可直接复用 |
| `services/practice.py`、`services/chat.py` | 常被误判为废弃模块。实测证明：`chat` 仍被教程学习页「上下文答疑」使用；`practice` 的实践尝试记录仍被 `knowledge.py:639-651` 的**掌握度计算**读取 | **不可删除** |
| `DecisionIn.decision` 无枚举校验 | 现实中网页与插件都不直接调该端点，不会被写坏；收紧会改变 API 行为 | 见 `PROJECT_AUDIT.md` 问题 I |
| `by_feature[].usage_source` 恒为空 | 前端不消费该字段；改它会变动 API 输出契约 | 见 `PROJECT_AUDIT.md` 问题 J |
| `.audit/`（审计工作区，含 22.6 MB 迁移前库快照） | 已 `.gitignore` 排除。快照是本次改动的回滚保险 | 确认无误后可整目录删除 |

---

## 8. 本次整理**没有**做的事（边界声明）

- ❌ 没有升级任何依赖、没有替换框架、没有改数据库结构（只**加**索引，未删列/改类型）
- ❌ 没有引入新基础设施（没有加 Docker、CI、数据库迁移工具如 Alembic）
- ❌ 没有重构任何模块、没有合并任何 service、没有调整目录组织
- ❌ 没有改变核心业务规则（五阶段顺序、验收标准闸门、交付契约、演示模式语义全部原样）
- ❌ 没有改变任何用户可观察的功能行为（除修复 bug 本身：训练数据页恢复可用、首页不再白发请求、画像建议不再 500）
- ❌ 没有删除任何来源不明、用途不明或存在动态引用可能的文件
- ❌ 没有动用户提交的 6 个功能文件，没有覆盖或重置任何未提交修改
- ❌ 没有删除 `legacy/phase0/`、方案文档、`package-lock.json` 等需要产品判断的对象
