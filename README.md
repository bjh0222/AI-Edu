# AI Edu — 个人 AI 学习工具

> **当前执行基线：** [AI-Edu-最终执行方案-Agent版-v2.0.md](../AI-Edu-最终执行方案-Agent版-v2.0.md)（工作区根目录）
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

双击仓库根目录的 **「启动 AI Edu.cmd」**：

- 自动打开两个窗口：「AI Edu 后端」（8000）与「AI Edu 前端」（3000）
- 自动等待就绪并打开浏览器 http://127.0.0.1:3000
- 停止：关闭这两个黑窗口即可

手动方式见下方「快速开始」。

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

打开 http://127.0.0.1:3000

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

**目标 → 诊断/价值分析 → 领域地图与计划 → 验收标准 → 教程（分节 + 质量检查）→ 实践尝试 → 逐项反馈 → 独立/迁移评估 → 复盘 → 知识记录**

计算机/命令行 与 数学/数据分析 两种学科配置共用同一学习引擎，通过 DisciplineProfile 体现差异。

## 阶段 0 存档

`legacy/phase0/` 保存了早期「教程生产流水线」实验（学习者画像、验收模板、质量清单、真实命令行教程素材）。它们是产品种子数据的来源，也是「先标准后教程」理念的原始实践。
