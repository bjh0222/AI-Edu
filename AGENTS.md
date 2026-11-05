# AI Edu

个人使用的单用户 AI 学习工具：Next.js 前端（`apps/web`）+ FastAPI 后端（`services/api`）+ Obsidian 交付插件（`obsidian-plugin`）。所有后端相对路径锚定到 `services/api/`，与启动目录无关。

## 命令

| 用途 | 命令 |
|---|---|
| 后端测试（完成判据，必须全绿） | `cd services/api` 后 `.venv/Scripts/python.exe -m pytest -q` |
| 前端类型检查 / lint / 构建 | `cd apps/web` 后 `npx tsc --noEmit` / `npm run lint` / `npm run build` |
| 插件行为测试 | 仓库根 `node obsidian-plugin/tests/behavior-test.js` |
| 架构地图（脚本生成，勿手改） | 仓库根 `services\api\.venv\Scripts\python.exe scripts\arch_map.py` |
| 规范预览双端一致性 | 仓库根 `node scripts/verify_spec_preview_sync.mjs` |
| 启动 | 仓库根 `aiedu`，或 `scripts/start-dev.ps1`（后端 8000 + 前端 3001） |

## 环境事实

- 前端包管理器是 **pnpm**（`pnpm-lock.yaml` 为准，`node_modules` 是 pnpm 结构）。不要在同一份 `node_modules` 上混用 `npm install`。
- 后端 venv 在 `services/api/.venv`；系统里还有别的 Python，测试和脚本都用这个 venv 的解释器。
- pytest 用 `services/api/tests/test_aiedu*.db`（conftest.py 设定），**不碰真实库** `services/api/data/aiedu.db`。真实库是用户数据。
- `Base.metadata.create_all()` 只建缺失的表，**不会**给已存在的表补列或补索引。给老库加列/加索引必须走 `app/db.py` 的 `_migrate_sqlite_columns` / `_migrate_sqlite_indexes`，且建索引用 SQLAlchemy 的 `CreateIndex(index, if_not_exists=True)`，不要手拼 DDL（部分唯一索引的 WHERE 谓词会丢）。
- `scripts/start-dev.ps1` 带 UTF-8 BOM，编辑时必须保留，否则 PowerShell 5.1 会把中文读成乱码。

## 不可违反的约束

1. **章节是并行生成的。** `tutorials.py` 用 ThreadPoolExecutor，每节只拿到 `prior_titles`（前面章节的**标题**，不是正文）。任何「A 章与 B 章保持一致」的需求在提示词层面无法实现——改结构让它们落在同一次调用里，而不是加规则。
2. **相对路径必须锚定。** services/api 的新代码里写 `Path("data")/...` 会在从仓库根启动时静默写到别处。一律用 `config.py` 的 `settings.*` 或 `_resolve_path`。这个 bug 出现过三次（database_url、model-settings.json、导入备份目录）。
3. **排序键必须有索引。** training_records 等表的文本列很大，`ORDER BY` 无索引时 SQLite 溢出磁盘临时文件；临时目录不可写就报 `unable to open database file`（误导性错误：不是库打不开，是临时排序文件打不开）。
4. **purge_goal 保留训练样本是刻意的。** 删除目标时 `training_records` / `model_call_logs` 只置空 `goal_id`（历史审计），不是泄漏，不要"修"它。
5. **practice.py / chat.py 不是废弃代码。** 前端已无对应页面，但 `knowledge.py` 的掌握度计算读实践记录，教程学习页在用 `/api/chat`。删除前先确认调用方。
6. **跨语言副本必须同步。** `apps/web/lib/specs.ts` 与 `obsidian-plugin/ai-edu-tutorial-delivery/main.js` 是等价实现（插件不能 import 前端代码），改任一份跑 `node scripts/verify_spec_preview_sync.mjs`。
7. **改阶段要改两处。** 后端 `learning/engine.py:PHASES` 与前端 `lib/goal-phases.ts:GOAL_PHASES` 必须一致（`test_arch_invariants.py` 会拦），每个 slug 对应 `apps/web/app/goals/[id]/<slug>/` 路由目录。
8. **演示模式的诚实性是产品原则。** 未配置模型时 `demo: true` 显式标注；token 无 usage 时标 `usage_source: estimated`；失败调用只记 `ModelCallLog`，不产生训练样本。不要让任何路径把演示输出伪装成真实模型输出。

## 大规模改动后的收尾

1. `pytest -q` 全绿。
2. `services\api\.venv\Scripts\python.exe scripts\arch_map.py` 重新生成架构地图（新增路由/表/模块后必须跑，否则 `test_architecture_map_is_current` 会失败）。
3. `npx tsc --noEmit` + `npm run build` 通过。
4. 涉及提示词或导出排版时，跑 `node scripts/verify_spec_preview_sync.mjs`。

## 文档地图

- `docs/ARCHITECTURE.generated.md` — 脚本生成的当前事实（路由 / 表 / 模块 / 页面），**勿手改**
- `docs/decisions.md` — ADR；改架构决策先读这里，再追加
- `docs/tutorial-generation-flow.md` — 提示词注入链路的完整解剖
- `docs/项目全景与架构解析.md` — 2026-10-30 的深度解析；叙述仍有效，**其中的数字已过期**，以生成的地图为准
- `PROJECT_AUDIT.md` / `PROJECT_CLEANUP.md` / `PROJECT_TEST_REPORT.md` — 2026-10-30 全量审计
- `apps/web/AGENTS.md` — Next.js 自动生成的版本注意事项，勿删
