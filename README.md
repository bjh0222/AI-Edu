# AI Edu — 个人 AI 学习工具

> **当前执行基线：** [AI-Edu-最终执行方案-Agent版-v2.0.md](AI-Edu-最终执行方案-Agent版-v2.0.md)（仓库根目录）
> 本仓库按该方案实现：以学习目标为起点、以可执行教程和真实实践为载体、以证据反馈和独立能力验证为闭环的 AI 辅助学习系统。

## 目录结构

```
ai-edu/
├─ apps/web/                # Next.js 前端（App Router + TypeScript + Tailwind）
├─ services/api/            # FastAPI 后端（SQLite + SQLAlchemy + Pydantic）
│  └─ app/
│     ├─ services/          # 业务层：tutorials · materials · knowledge · format_specs
│     │                     #   质量校验：exam_check · exam_verify · tool_verify
│     │                     #              quote_check · practice_check · spec_check
│     │                     #   命题知识库：proposition
│     ├─ llm/               # prompts（提示词）· service（AIService）· context_layers（层级×维度装配 + EXPLAIN 观测）
│     ├─ api/               # 路由：goals · tutorials · knowledge · proposition · ...
│     └─ learning/          # disciplines（学科画像）· engine · levels · teaching_profile
├─ docs/                    # architecture.md · decisions.md · user-guide.md
├─ scripts/                 # 开发辅助脚本
├─ legacy/phase0/           # 阶段 0（Markdown 教程流水线）资产存档，仅参考
├─ obsidian-plugin/         # Obsidian 教程投递插件
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
pnpm install
pnpm dev
```

打开 http://127.0.0.1:3001

> 前端实际用 **pnpm** 安装（仓库里 `apps/web/pnpm-lock.yaml` 为准，`node_modules` 也是 pnpm 结构）。
> 仓库同时保留了 `package-lock.json`，两者当前都与 `package.json` 同步；
> 但不要在同一份 `node_modules` 上混用 `npm install` 与 `pnpm install`——
> 两种管理器的目录布局不同，混用会得到一棵彼此「invalid」的依赖树。
> 若要用 npm，先删掉 `node_modules` 再 `npm install`。

### 3. 模型配置

推荐打开网页的 **偏好设置 → 模型接入**，填写 API 根地址、密钥和模型 ID，点击「测试并启用」。支持保存多组 Chat Completions 兼容配置、获取模型列表、切换模型，以及调整超时、温度与 JSON 输出。配置立即对新请求生效，无需重启。

密钥仅保存在本机 `services/api/data/model-settings.json`，不会回传给网页，该文件不提交到 Git，也不包含在学习数据备份中。更换 API 地址需要重新填写密钥。尚未保存网页配置时，也可以通过 `.env` 提供初始配置：

```
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=glm-4.5
```

未配置时后端进入**演示模式**：结构化生成结果由确定性演示生成器产生，并在响应中明确标记 `demo: true`，绝不伪造为真实模型输出。

### 外观与学习辅助

- 偏好设置支持亮色、暗色、跟随系统、自定义主题色，以及教程阅读字号。
- 学习目标支持搜索、阶段筛选和创建草稿自动恢复。
- 章节支持自动保存笔记、已读标记和 Markdown 笔记下载；首页可以继续上次学习。
- 主题、草稿、笔记及阅读进度保存在当前浏览器，不包含在服务端 JSON 备份中；重要笔记请下载备份。
- 如果 8000 端口被占用，可将后端改为 8001，并在 `apps/web/.env.local` 设置 `API_BACKEND_URL=http://127.0.0.1:8001`。

### 4. 测试

```powershell
cd services/api
.\.venv\Scripts\python.exe -m pytest -q
```

并行跑测试时用 `AIEDU_TEST_SUFFIX` 给每个进程一套独立的库 / 材料 / 备份路径，避免
fixture 的 `drop_all` 互相删表：

```powershell
$env:AIEDU_TEST_SUFFIX="_A"; .\.venv\Scripts\python.exe -m pytest tests/test_exam_check.py -q
```

这些隔离产物已被 `.gitignore` 覆盖，不会进仓库。

### 5. 故障排查

**后端一启动就报 `ImportError: DLL load failed while importing _row_cy`（或每个请求 500）**
Windows 11 的「智能应用控制」(Smart App Control) 会拦截没有信誉的本地编译扩展（Win32 错误码 4551「应用程序控制策略已阻止此文件」），SQLAlchemy 的 C 扩展首当其冲。让 Python 回退到内置的纯 Python 实现即可（功能不变，略慢）：

```powershell
cd services/api
.\.venv\Scripts\python.exe scripts\disable_blocked_native_extensions.py
```

脚本只改名、不删除，且只处理「加载失败且存在同名 .py 回退实现」的文件；重新安装/升级依赖会带回 `.pyd`，届时重跑一次即可。要根治可在「Windows 安全中心 → 应用和浏览器控制 → 智能应用控制」关闭（注意：关闭后无法再直接开启）。

**报 `sqlite3.OperationalError: unable to open database file`**
数据库、材料、备份目录现在都锚定到 `services/api/`（不再依赖启动时的工作目录），所以从仓库根或任何目录启动都指向同一份数据。启动日志会打印实际使用的库路径：

```
INFO:     [aiedu] 数据库：sqlite:///D:/.../services/api/data/aiedu.db
```

若该路径不符合预期，用 `DATABASE_URL` 显式指定（绝对路径）。

## 核心闭环

**目标定义 → 价值诊断 → 学习计划 → 验收标准 → 教程学习（终点）**

学习目标详情页按此阶段流组织（阶段条 + 「上一步/下一步」导航），前后端共用同一阶段顺序：后端 `app/learning/engine.py` 的 `PHASES`，前端 `apps/web/lib/goal-phases.ts` 的单一事实来源。先定验收标准、再生成教程：确认后的验收标准会进入教程验收，教程生成为流程终点。

学科配置（DisciplineProfile）决定练习类型、验收方法、常见错误与**工具验证能力**（`verify_capability`）。已定制四个：计算机 / 命令行（`executable`，静态检查 + 命令存在性）、数学 / 数据分析（`symbolic`，sympy 符号验算）、化学与材料（`symbolic_partial`，仅配平与电荷守恒）、生物与生命科学（`none`，回落模型核验与人工）；其余一级领域共用通用画像。

## 测试版新增能力

- **列表 → 详情**：学习目标列表每项提供「查看」，经前端路由进入目标详情；教程大纲的每一步、每个章节都可点进独立详情页（`/tutorials/[tid]`、`/tutorials/[tid]/sections/[sid]`）。
- **一键生成 / 一键同意**：目标详情页可一次完成「诊断 → 计划 → 验收标准（批量同意）→ 大纲 → 全部章节」，幂等可重复执行；验收标准支持「一键同意全部」（不覆盖已拒绝项）。
- **token 统计**：优先使用模型返回的 usage；无 usage 时按字符估算并标注。生成界面显示本次 / 教程累计 / 目标累计，`GET /api/goals/{id}/usage` 可按功能与教程汇总。
- **测试数据采集**：每次生成的材料（prompt + 输出 + 模型/token 元数据）与用户反馈持久化到 `training_records`，在 `/training` 页面统计并导出 JSONL / JSON，供后续预训练与效果分析（导出可选排除演示数据）。

详见 [`docs/交付说明-四项改造.md`](docs/交付说明-四项改造.md) 与 [`docs/architecture.md`](docs/architecture.md)。

## 生成质量保障体系

生成内容的质量不靠「提示词里写要求 + 模型自觉」，而是分层校验：**能用代码判定的绝不交给模型**。
这条分工来自项目既有裁决（ADR-015 / ADR-018：确定性规则 + 代码定结构），实测也反复印证——
一份 5 套卷的试卷，账目类错误（声明 20 题实际 25 题、题号按题型重置、满分各行之和 96 ≠ 100）
提示词约束不住，代码一次判定即可。

### 分层（按验证的确定性从高到低）

| 层 | 模块 | 管什么 | 成本 |
|---|---|---|---|
| **Tier-0 账目** | `services/exam_check.py` | 题号连续、分值表账目、答案题号集合、题型枚举、答案小节名、占位文字、跨卷母题重复与答案冲突 | 纯代码，零 token |
| **Tier-0 规范专项** | `services/quote_check.py`<br>`services/practice_check.py` | 阅读规范：摘录是否逐字出自材料（虚构引文）、章节定位、页码可核实<br>实践规范：步骤三要素、代码块语法、命令是否存在 | 纯代码，零 token |
| **Tier-1 工具验证** | `services/tool_verify.py` | 数学题用 **sympy 独立验算**答案；化学查配平与电荷守恒；计算机做静态检查与命令存在性 | 本地子进程，零 token |
| **Tier-2 模型核验** | `services/exam_verify.py` | 盲解（不给模型看答案）→ 与卷面答案比对 → 冲突仲裁 | 每卷 1~2 次模型往返 |
| **Tier-3 人工** | 前端质量报告 | 上述各层只标记不改写的问题 | 用户复核 |

`services/spec_check.py` 是**分派器**：按规范 scene 把内容路由到对应校验器
（`exam_paper`/`exercise` → 账目，`reading_guide` → 摘录溯源，`practical_tutorial` → 步骤与代码），
避免把试卷的判据套到导读上。

### 自动修复：只改一次，且改了什么必须可见

Tier-0 会**就地改写**章节正文，但严格受限：

- **只修无歧义的**：裸题号 `7.` → `**7.**`、答案小节名统一为 `### 参考答案`、分值括注按分值表回填、
  占位文字删除、账目以「题面实际分值之和」为准重算。
- **不修有歧义的**：题号重复时**不重编号**（旧号→新号映射会多对一坍缩，导致答案与题目错配）；
  同一题型各题分值不一致时**不改账目**（「每题分值」列在数学上无法表达事实，改哪边都是武断决定）。
- **一轮为限**：修完即止，不迭代。二次运行不产生任何改动（幂等，有测试锁定）。
- **可追溯**：每条违规带 `code` / `rule` / `basis`（指向规范具体条文）/ `fixed` / `severity`，
  写进 `quality_report.exam_check` 并暴露给前端。

Tier-1/Tier-2 改写答案时更保守：**只改客观题**（选择/判断/填空），且只采信
sympy 算出的确定值或 high 置信仲裁；解答题与证明题的答案是成段步骤，一律只标记不改写。

### 严重度分级：不让噪音淹没真信号

`blocking`（账目对不上、题号断裂、答案冲突、答案区写「需核验」、虚构引文、代码语法错）
会让教程标记为「待改进」；`advisory`（留白行数、母题重复、记法风格）只提示。
实测一份 5 套卷有 42 处留白偏差、10 处母题重复，而真正严重的答案冲突只有 2 处——
若都算进 `passed`，几乎每份卷子都「待改进」，真信号反而看不见。

### 提示词 EXPLAIN：让「注入了什么」可见

每次模型调用会反向解析它的 user prompt，记录**实际注入了哪些块、各占多少字符、
在 prompt 的什么位置、优先级顺序是否自洽**，随 `TrainingRecord.context_json` 落库
（`llm/context_layers.py` 的 `analyze_prompt`）。

这补上了 agent 运行时六职责（observation / context / control / action / state / verification）里
项目此前唯一薄弱的一项：过去只知道花了多少 token（`ModelCallLog`），不知道注入了什么。
ADR-018 那类故障（条件从句被误分类、约束静默失效）若有 EXPLAIN 当场就能看见，
不必事后写进 `decisions.md` 复盘。

注入块按「层级 × 维度」组织（借 CSS cascade 模型）：优先级不是一条全序，而是
**内容维度**（范围 / 题量 / 难度 / 事实）与**结构维度**（标题 / 栏目 / 排版 / 交付构成）
各自一条全序。只有两个块声称**同一维度**的权威时才构成潜在冲突——这正是 ADR-018 的
教训：硬约束要「内容」、格式规范要「结构」，本就该各管一段，不是需要裁决的矛盾。

位置不变量有测试保护：命题规律、格式规范等关键块必须排在长材料**之后**（落在末尾区）。
实测整本书场景（材料约 20 万字符）命题块在 99.6%、格式规范在 99.3%——依据是长上下文
的注意力分布（Lost in the Middle / CRE：中部区域利用率最低、易与填充文本混淆）。

## 命题知识库

让系统积累自己的命题经验，而不是每次出题都像第一次。四张表（`models.py`）：

| 表 | 作用 |
|---|---|
| `ItemModel` | **母题**：`radicals`（决定难度与认知要求的结构元素）/ `incidentals`（可变表面特征）/ `solution_template`（参数化解法） |
| `ItemInstance` | 母题代入一组具体参数后的**同构题**实例，答案由模板机械求解 |
| `DesignPrinciple` | 提炼出的命题规律，三态 `proposed` / `confirmed` / `rejected` |
| `QualityRecord` | Tier-0/1/2 发现的缺陷回流，是命题规律的冷启动素材 |

结构取自自动命题生成（AIG）的 **item model / radicals / isomorphs** 范式与**变式教学理论**
（概念性变式 / 过程性变式）。它解决的是一个实测缺陷：同一母题在一份文档里出现 5 次、
给出 4 个不同答案（`x=ln(t+√(1+t²)), y=arctan t` → √2 / √2⁄2 / −2 / √2），
根因是每次都独立重新生成。同构变式的答案改为**代入模板机械求解**后，同母题必然同答案结构。

闭环（`services/proposition.py` + `api/proposition.py`，10 条路由）：

```
生成 → Tier-0/1 发现缺陷 → 回流 QualityRecord
     → distill 确定性聚类（同学科同缺陷 ≥3 次）→ DesignPrinciple(proposed)
     → 人工 review → confirmed → 注入下次命题提示词（1200 字符预算裁剪）
```

三条硬约束：**只有 `confirmed` 才注入**（未经人核实的经验不得影响交付）；
提炼出的规律**必须绑定具体错误码、出现次数与母题指纹**（不许「要注意答案正确性」这类空话）；
被驳回的规律**不因再攒证据而复活**。

> 冷启动状态：抽出的母题 `solution_template` 为空，需人工补录后才能产出同构变式
> （`PATCH /api/proposition/item-models/{id}`）。模板不自动生成——让模型「看着题写个解法模板」
> 等于把答案正确性交回模型，正是要消除的漂移源。

### 已知限制（当前状态，非缺陷）

- **Tier-1 只覆盖可符号化的题目**：数学（sympy）与化学配平能确定性判定；几何证明、
  概念辨析、文字题无法形式化，一律回落 Tier-2 模型核验与 Tier-3 人工。
  转写失败（题目翻不成 sympy）也回落，**绝不把「转写不出来」当成「题目错了」**。
- **Tier-2 的模型自评可信度有限**：同一模型多次调用的独立信息增益接近于零
  （多裁判面板实测 9 个前沿模型仅相当于 2.18 张有效独立票）。所以 Tier-2 的结论
  **不单独驱动答案改写**，只有 Tier-1 的确定性结果或 high 置信仲裁才改。
- **`context_layers.py` 的 EXPLAIN 已接入，装配（assemble）待 A/B 后接入**：EXPLAIN（反向解析
  每次调用实际注入了哪些块、各占多少、优先级顺序是否自洽）已挂进 `AIService._record`，随
  `TrainingRecord.context_json` 落库，补上了 harness 六职责里唯一薄弱的 observation。但把
  `prompts.py` 的 f-string 拼装改写成 `assemble()` 会改变 prompt 字节（现有各块紧邻拼接 vs
  assemble 用空行连接），需先做 A/B 测量——静态规范块前移能命中提示词缓存（约 8,300 token ×
  每章），而靠后更符合长上下文的注意力分布，两个方向相反，不能靠推理定案。
- **命题知识库处于冷启动**：母题的 `solution_template` 需人工补录后才能产出同构变式；
  `procedural` / `conceptual` 两类变式的答案留空（`verified_by="none"`），需独立验证链路。
- **演示模式（未配置模型）下 Tier-1/Tier-2 跳过**：Tier-0 账目与规范校验始终生效（纯代码）。

## 近期更新

- **生成质量保障体系（本次）**：新增 Tier-0 账目校验（`exam_check`，18 个错误码）、规范专项校验（`quote_check` 摘录溯源 / `practice_check` 步骤与代码，经 `spec_check` 按 scene 分派）、Tier-1 工具验证（`tool_verify`，数学走 sympy 独立验算）、Tier-2 盲解核验（`exam_verify`，工具优先于模型）。修复了规范主模板自身的账目错误（示例分值表各行之和 96 却写满分 100，模型忠实照抄导致 4/5 卷满分对不上）。后端测试 680 项。
- **命题知识库（本次）**：新增 `ItemModel` / `ItemInstance` / `DesignPrinciple` / `QualityRecord` 四表与 `services/proposition.py`、`api/proposition.py`（10 条路由），按 AIG 的 item model（radicals / incidentals / isomorphs）与变式教学理论组织；质量缺陷自动回流并可提炼成命题规律，确认后注入后续命题。
- **学科配置扩展（本次）**：新增化学与材料（`symbolic_partial`）、生物与生命科学（`none`）两个定制画像，并为所有学科增加 `verify_capability` 字段作为工具验证的分派依据。
- **流程重构（提示词优化）**：目标详情页收敛为「目标定义 → 价值诊断 → 学习计划 → 验收标准 → 教程学习」五阶段单一流程，移除独立的评估/反馈/实践/知识更新子页；教程 v2 生成管线重写（章节生成、等级难度、LLM JSON 修复，见 `services/api/app/services/tutorials.py`、`app/learning/levels.py`、`app/llm/`）。
- **统一生成任务轮询**：`apps/web/lib/job-poll.ts` 收拢「一键生成 / 章节生成 / 配套文件补齐」的轮询逻辑，修复重复轮询、页面卸载后泄漏、任务卡死无限轮询三类问题（默认约 20 分钟上限）。
- **稳定性与性能（加速）**：数据加载加请求序号竞态保护，旧响应不再覆盖新数据；教程页在章节后台生成期间自动刷新（约 4 分钟上限）；单节重生成期间互斥禁用，避免并发生成互相覆盖版本。
- **数据安全**：支持彻底删除学习目标（含 JSON 备份，见 `services/api/tests/test_goal_purge.py`）；导入恢复增加知识数据安全阀，防止静默清空知识网络；知识网络展示保留归档目标节点。

## 阶段 0 存档

`legacy/phase0/` 保存了早期「教程生产流水线」实验（学习者画像、验收模板、质量清单、真实命令行教程素材）。它们是产品种子数据的来源，也是「先标准后教程」理念的原始实践。
