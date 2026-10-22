# AI Edu — 个人 AI 学习工具

> **当前执行基线：** [AI-Edu-最终执行方案-Agent版-v2.0.md](AI-Edu-最终执行方案-Agent版-v2.0.md)（仓库根目录）
> 本仓库按该方案实现：以学习目标为起点、以可执行教程和真实实践为载体、以证据反馈和独立能力验证为闭环的 AI 辅助学习系统。

## 目录结构

```
ai-edu/
├─ apps/web/                # Next.js 前端（App Router + TypeScript + Tailwind）
├─ services/api/            # FastAPI 后端（SQLite + SQLAlchemy + Pydantic）
├─ docs/                    # architecture.md · decisions.md · user-guide.md
├─ scripts/                 # 开发辅助脚本
├─ legacy/phase0/           # 阶段 0（Markdown 教程流水线）资产存档，仅参考
├─ .env.example
├─ .gitignore
└─ README.md
```

## 一键启动（推荐）

- **方法一（保留智能应用控制，最稳妥）**：打开「Windows PowerShell」，输入 **`aiedu`** 回车。
- **方法二（双击）**：双击仓库根目录的 **「启动 AI Edu.cmd」**（需先关闭 Windows「智能应用控制」，否则会被系统拦截）。

两种方式都会打开「AI Edu 后端」（8000）与「AI Edu 前端」（3001）两个窗口，并自动打开浏览器 http://127.0.0.1:3001。停止 = 关闭这两个窗口。

> **为什么 .cmd 会被拦？** Windows 11「智能应用控制」会拦截直接双击运行的 `.cmd/.bat/.lnk`（提示「智能应用控制已阻止不安全文件」）。`aiedu` 走已签名的 PowerShell 并以 `-ExecutionPolicy Bypass` 加载脚本，不受影响。若想双击启动，可在「设置 → 隐私和安全性 → Windows 安全中心 → 应用和浏览器控制 → 智能应用控制」中关闭——注意：**关闭后无法再开启**（需重装系统才能恢复），请自行权衡。

等价命令行：`powershell -NoProfile -ExecutionPolicy Bypass -File "D:\桌面\dsh\ai-edu\scripts\start-dev.ps1"`

## 快速开始

### 1. 后端（services/api）

```powershell
cd services/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy ..\..\.env.example ..\..\.env   # 可选：配置真实模型
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

API 文档：http://127.0.0.1:8000/docs　健康检查：`GET /api/health`

### 2. 前端（apps/web）

```powershell
cd apps/web
npm install
npm run dev
```

打开 http://127.0.0.1:3001

### 3. 模型配置

在 `.env` 中配置任意 OpenAI 兼容接口即可接入真实模型：

```
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=glm-4.5
```

未配置时后端进入**演示模式**：结构化生成结果由确定性演示生成器产生，并在响应中明确标记 `demo: true`，绝不伪造为真实模型输出。

### 4. 测试

```powershell
cd services/api
.\.venv\Scripts\python.exe -m pytest -q
```

## 核心闭环

**目标定义 → 价值诊断 → 学习计划 → 验收标准 → 教程学习（终点）**

学习目标详情页按此阶段流组织（阶段条 + 「上一步/下一步」导航），前后端共用同一阶段顺序：后端 `app/learning/engine.py` 的 `PHASES`，前端 `apps/web/lib/goal-phases.ts` 的单一事实来源。先定验收标准、再生成教程：确认后的验收标准会进入教程验收，教程生成为流程终点。

计算机/命令行 与 数学/数据分析 两种学科配置共用同一学习引擎，通过 DisciplineProfile 体现差异。

## 测试版新增能力

- **列表 → 详情**：学习目标列表每项提供「查看」，经前端路由进入目标详情；教程大纲的每一步、每个章节都可点进独立详情页（`/tutorials/[tid]`、`/tutorials/[tid]/sections/[sid]`）。
- **一键生成 / 一键同意**：目标详情页可一次完成「诊断 → 计划 → 验收标准（批量同意）→ 大纲 → 全部章节」，幂等可重复执行；验收标准支持「一键同意全部」（不覆盖已拒绝项）。
- **token 统计**：优先使用模型返回的 usage；无 usage 时按字符估算并标注。生成界面显示本次 / 教程累计 / 目标累计，`GET /api/goals/{id}/usage` 可按功能与教程汇总。
- **测试数据采集**：每次生成的材料（prompt + 输出 + 模型/token 元数据）与用户反馈持久化到 `training_records`，在 `/training` 页面统计并导出 JSONL / JSON，供后续预训练与效果分析（导出可选排除演示数据）。

详见 [`docs/交付说明-四项改造.md`](docs/交付说明-四项改造.md) 与 [`docs/architecture.md`](docs/architecture.md)。

## 近期更新

- **流程重构（提示词优化）**：目标详情页收敛为「目标定义 → 价值诊断 → 学习计划 → 验收标准 → 教程学习」五阶段单一流程，移除独立的评估/反馈/实践/知识更新子页；教程 v2 生成管线重写（章节生成、等级难度、LLM JSON 修复，见 `services/api/app/services/tutorials.py`、`app/learning/levels.py`、`app/llm/`）。
- **统一生成任务轮询**：`apps/web/lib/job-poll.ts` 收拢「一键生成 / 章节生成 / 配套文件补齐」的轮询逻辑，修复重复轮询、页面卸载后泄漏、任务卡死无限轮询三类问题（默认约 20 分钟上限）。
- **稳定性与性能（加速）**：数据加载加请求序号竞态保护，旧响应不再覆盖新数据；教程页在章节后台生成期间自动刷新（约 4 分钟上限）；单节重生成期间互斥禁用，避免并发生成互相覆盖版本。
- **数据安全**：支持彻底删除学习目标（含 JSON 备份，见 `services/api/tests/test_goal_purge.py`）；导入恢复增加知识数据安全阀，防止静默清空知识网络；知识网络展示保留归档目标节点。

## 阶段 0 存档

`legacy/phase0/` 保存了早期「教程生产流水线」实验（学习者画像、验收模板、质量清单、真实命令行教程素材）。它们是产品种子数据的来源，也是「先标准后教程」理念的原始实践。
