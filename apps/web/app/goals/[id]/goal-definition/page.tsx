"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Goal, GenerationTier } from "@/lib/types";
import { CAPABILITY_LEVELS, GENERATION_TIERS } from "@/lib/types";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, Field, inputCls } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import { GoalExamples } from "@/components/goals/GoalExamples";
import type { WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("goal_definition");
const SLICES: WorkspaceSlices = {};

const FIELDS = [
  { key: "motivation", label: "为什么要学", placeholder: "它和你的当前需求或长期目标有什么关系？", rows: 2 },
  { key: "application_context", label: "学完要能做什么", placeholder: "尽量描述一个可观察、可验收的任务。", rows: 3 },
  { key: "current_level", label: "当前基础", placeholder: "你已经会什么、卡在哪里？", rows: 2 },
  {
    key: "hard_constraints",
    label: "硬性约束（可选）",
    placeholder: "生成内容必须满足的强制要求，每行一条。例如：\n不安排任何日程\n所有命令示例同时给出 Linux 与 Windows 写法",
    rows: 2,
  },
] as const;

export default function GoalDefinitionPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ data, run, busy }) => (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <Card title="目标基础信息" desc="名称、动机、应用场景、当前基础、时间预算与硬性约束——这些会进入后续所有生成的 prompt">
            {data.goal && (
              <GoalForm
                // 服务端数据更新后换 key 重新挂载表单，避免用 effect 强行 setState
                key={data.goal.updated_at ?? data.goal.id}
                goal={data.goal}
                busy={busy === "save"}
                onSave={(payload) =>
                  run(
                    "save",
                    async () => {
                      await api.patch<Goal>(`/api/goals/${data.goal?.id}`, payload);
                    },
                    "目标信息已保存"
                  )
                }
              />
            )}
          </Card>

          <div className="grid gap-4">
            <Card title="目标完整性检查" desc="描述越具体，价值诊断与验收标准越可判定">
              {data.goal && <Completeness goal={data.goal} />}
            </Card>
            <Card title="下一步" desc="除非只是修改基础信息，否则默认回到总览页一键生成">
              <div className="grid gap-2 text-[12px]">
                <Link
                  href={`/goals/${data.goal?.id}`}
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                >
                  自动生成教程 →
                </Link>
                <p className="text-[11px] leading-relaxed text-muted">
                  总览页的一键生成会自动完成价值判断、学习计划、验收标准与教程；只有明显不值得推进时才暂停。
                </p>
              </div>
            </Card>
          </div>
        </div>
      )}
    </GoalPhaseView>
  );
}

function GoalForm({
  goal,
  busy,
  onSave,
}: {
  goal: Goal;
  busy: boolean;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [form, setForm] = useState({
    title: goal.title,
    motivation: goal.motivation,
    application_context: goal.application_context,
    current_level: goal.current_level,
    time_budget: goal.time_budget,
    hard_constraints: goal.hard_constraints || "",
    user_notes: goal.user_notes,
    capability_level: (goal.capability_level || "L2") as Goal["capability_level"],
    generate_extra_exercises: !!goal.generate_extra_exercises,
    generation_tier: (goal.generation_tier || "standard") as GenerationTier,
  });

  return (
    <div>
      <Field label="目标名称 *">
        <input
          className={inputCls}
          value={form.title}
          onChange={(event) => setForm({ ...form, title: event.target.value })}
        />
      </Field>
      {FIELDS.map((field) => (
        <Field key={field.key} label={field.label}>
          <textarea
            className={inputCls}
            rows={field.rows}
            placeholder={field.placeholder}
            value={form[field.key]}
            onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
          />
        </Field>
      ))}
      <Field label="可投入总时间">
        <input
          className={inputCls}
          value={form.time_budget}
          onChange={(event) => setForm({ ...form, time_budget: event.target.value })}
        />
        <span className="text-[10px] text-muted">
          填总时长（如「共 10 小时」），不用拆成每天的时间安排
        </span>
      </Field>
      <Field label="能力层级">
        <select
          className={inputCls}
          value={form.capability_level}
          onChange={(event) =>
            setForm({ ...form, capability_level: event.target.value as Goal["capability_level"] })
          }
        >
          {CAPABILITY_LEVELS.map((lv) => (
            <option key={lv.key} value={lv.key}>
              {lv.key} · {lv.name}
            </option>
          ))}
        </select>
        <span className="text-[10px] leading-relaxed text-muted">
          {CAPABILITY_LEVELS.find((lv) => lv.key === form.capability_level)?.description}
          层级决定教程深度、练习设计与验收难度；修改后重新生成教程才会生效。
        </span>
      </Field>
      <Field label="生成挡位">
        <select
          className={inputCls}
          value={form.generation_tier}
          onChange={(event) => setForm({ ...form, generation_tier: event.target.value as GenerationTier })}
        >
          {GENERATION_TIERS.map((tier) => (
            <option key={tier.key} value={tier.key}>
              {tier.name} · {tier.key}
            </option>
          ))}
        </select>
        <span className="text-[10px] leading-relaxed text-muted">
          {GENERATION_TIERS.find((tier) => tier.key === form.generation_tier)?.description}
          一键生成会按此挡位自动完成价值判断、计划、验收标准与教程。
        </span>
      </Field>
      <Field label="额外练习文件">
        <label className="flex cursor-pointer items-center gap-2 text-[12px]">
          <input
            type="checkbox"
            checked={form.generate_extra_exercises}
            onChange={(event) => setForm({ ...form, generate_extra_exercises: event.target.checked })}
          />
          生成独立的额外练习文件（含参考答案，与教程内必要练习分开）
        </label>
        <span className="text-[10px] text-muted">
          开启后重新生成教程时会附带一份 Markdown 练习集，并在教程中建立 Obsidian 双链
        </span>
      </Field>
      <Field label="自己的补充笔记">
        <textarea
          className={inputCls}
          rows={2}
          placeholder="例如：希望两周内能独立完成一次日志分析"
          value={form.user_notes}
          onChange={(event) => setForm({ ...form, user_notes: event.target.value })}
        />
      </Field>
      <GoalExamples />
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void onSave(form)} disabled={busy || !form.title.trim()}>
          {busy ? "保存中…" : "保存目标信息"}
        </Button>
        <span className="text-[10px] text-muted">学科：{goal.domain_name}（由创建时选择，暂不可修改）</span>
      </div>
    </div>
  );
}

function Completeness({ goal }: { goal: Goal }) {
  const items = [
    { label: "目标名称", done: goal.title.trim().length > 0 },
    { label: "为什么学", done: goal.motivation.trim().length > 0 },
    { label: "学完要能做什么", done: goal.application_context.trim().length > 0 },
    { label: "当前基础", done: goal.current_level.trim().length > 0 },
    { label: "可投入总时间", done: goal.time_budget.trim().length > 0 },
  ];
  const done = items.filter((item) => item.done).length;
  return (
    <div className="grid gap-2">
      <div className="flex items-center gap-2">
        <Badge tone={done === items.length ? "done" : "warn"}>
          {done}/{items.length} 项已填写
        </Badge>
        <span className="text-[11px] text-muted">缺项会让诊断与验收标准变得模糊</span>
      </div>
      <ul className="grid gap-1 text-[11px]">
        {items.map((item) => (
          <li key={item.label} className={item.done ? "text-[#128b78]" : "text-[#a33]"}>
            {item.done ? "✓" : "✗"} {item.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
