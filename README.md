# ai-edu — 第一阶段：教程生产流水线（方案 A）

> 目标：验证「验收标准先行 + 分节生成 + 质量门」能否显著改善教程质量与学习效果（假设 A1）
> 方式：零 API、零新代码——Git 仓库 + 网页模型（经 AI Hub）+ 人工执行质量门
> 上游文档：[Stage 1.md](D:\桌面\记录\Stage 1.md) ｜ [首轮交付物](D:\桌面\dsh\AI-Edu-Stage1-首轮交付物.md) ｜ [基线诊断](tutorials\cli\diagnosis-基线诊断.md)

## 目录

```
ai-edu/
├─ README.md                 本文件
├─ profile.md                学习者画像（每次生成前取摘要）
├─ templates/
│  ├─ acceptance.md          验收标准写法模板（P1 用）
│  ├─ generation-prompt.md   生成 prompt 组装模板（P3/P4 用）
│  └─ question.md            中途提问模板（学习中随时用）
├─ checklists/
│  └─ quality.md             教程质量 9 项清单（P5 审查用）
├─ tutorials/
│  └─ cli/                   命令行教程（素材与重构产物）
│     ├─ diagnosis-基线诊断.md
│     └─ source-原始教程.md   ← Phase 0 你手动复制进来
├─ evidence/                 执行记录、任务完成记录（T1–T5）
│  └─ baseline.md            Phase 0 基线测量（现在开始填）
├─ learning-log.md           追问与反馈台账（每次提问记一行）
└─ tutorial-log.md           成本台账（每教程记一行）
```

## 生产管线（P0–P7）

```
P0 画像 → P1 价值判断+验收标准 → P2 入门诊断 → P3 大纲
→ P4 分节生成 → P5 质量审查 → P6 实践验证 → P7 反馈与修订
        ↑门槛：G1 可判定性    ↑门槛：G2 双向映射  ↑G3 节结构  ↑G4 九项清单
```

三条铁律：
1. **先标准、后教程**——没有已确认的验收标准，不生成任何教程内容
2. **确认权在人**——AI 起草，你逐条确认；不确认不进下一阶段
3. **单节 ≤ 单次专注时长（40 分钟）且映射 ≥1 条验收标准**——防止重蹈 1455 行覆辙

## 阶段进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 0 | 基线测量 + 脚手架 | 🔄 进行中 |
| Phase 1 | 首模块「文件与目录导航」全流程 | ⏸ 等待 Phase 0 数据 |
| Phase 2 | 第二模块 + 修订回路验证 | ⏸ |
| Phase 3 | 决策点：是否进入方案 B（独立仓库、同栈 Next.js） | ⏸ |
