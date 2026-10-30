"use client";

import { ReactNode, Suspense } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { Goal } from "@/lib/types";
import { fmtTokens } from "@/lib/format";
import {
  GOAL_PHASES,
  type GoalPhase,
  goalHref,
  isPhaseReached,
  neighborPhases,
  phaseHref,
  phaseIndex,
} from "@/lib/goal-phases";
import { Badge, Button } from "@/components/ui";
import { useGoalWorkspace, type GoalWorkspaceState, type WorkspaceSlices } from "./useGoalWorkspace";

/** 单阶段页面的统一外壳：面包屑 / 标题 / 阶段导航 / 提示条 / 上一步下一步。 */
export function GoalPhaseView({
  phase,
  slices,
  actions,
  children,
}: {
  phase: GoalPhase;
  slices: WorkspaceSlices;
  actions?: ReactNode;
  children: (workspace: GoalWorkspaceState) => ReactNode;
}) {
  return (
    <Suspense fallback={<PhaseFallback />}>
      <GoalPhaseInner phase={phase} slices={slices} actions={actions}>
        {children}
      </GoalPhaseInner>
    </Suspense>
  );
}

function PhaseFallback() {
  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10">
      <div className="text-[13px] text-muted">加载中…</div>
    </div>
  );
}

function GoalPhaseInner({
  phase,
  slices,
  actions,
  children,
}: {
  phase: GoalPhase;
  slices: WorkspaceSlices;
  actions?: ReactNode;
  children: (workspace: GoalWorkspaceState) => ReactNode;
}) {
  const params = useParams<{ id: string }>();
  const goalId = typeof params?.id === "string" ? params.id : "";
  const workspace = useGoalWorkspace(goalId, slices);
  const { data, loading, error, notice } = workspace;

  if (!data.goal) {
    if (error) {
      return (
        <div className="mx-auto max-w-[900px] px-6 py-10">
          <div className="mb-3 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
            {error}
          </div>
          <div className="flex flex-wrap gap-3 text-[12px] font-semibold text-brand">
            <Link href="/goals" className="hover:underline">
              ← 返回学习目标列表
            </Link>
          </div>
        </div>
      );
    }
    return (
      <div className="mx-auto max-w-[900px] px-6 py-10">
        <div className="text-[13px] text-muted">{loading ? "加载中…" : "目标不存在或已归档。"}</div>
      </div>
    );
  }

  const goal = data.goal;
  const { prev, next } = neighborPhases(phase.slug);

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <Breadcrumb goal={goal} phase={phase} />

      <header className="mt-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-bold tracking-tight">{goal.title}</h1>
          <GoalStatusBadge goal={goal} currentPhaseKey={phase.key} />
          <Badge>{goal.domain_name}</Badge>
          {data.usage && (
            <Badge tone="neutral">累计 {fmtTokens(data.usage.totals.total_tokens)} tokens</Badge>
          )}
        </div>
        {goal.motivation && <p className="mt-1 text-[12px] text-muted">为什么学：{goal.motivation}</p>}
        <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-[17px] font-bold text-ink">{phase.title}</h2>
            <p className="mt-0.5 max-w-[760px] text-[12px] leading-relaxed text-muted">{phase.desc}</p>
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      </header>

      <PhaseStepper goalId={goalId} currentSlug={phase.slug} goalStatus={goal.status} />

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-xl border border-[#c6eee4] bg-[#f0fbf8] px-4 py-2.5 text-[12px] text-[#128b78]">
          {notice}
        </div>
      )}

      {children(workspace)}

      <nav
        aria-label="流程导航"
        className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4"
      >
        <Link
          href={goalHref(goalId)}
          className="rounded-[10px] border border-line bg-white px-3.5 py-2 text-[12px] font-semibold text-[#39455d] hover:border-[#c9c3ff]"
        >
          ← 返回目标总览
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          {prev ? (
            <Link
              href={phaseHref(goalId, prev)}
              className="rounded-[10px] border border-line bg-white px-3.5 py-2 text-[12px] font-semibold text-[#39455d] hover:border-[#c9c3ff]"
            >
              ← 上一步：{prev.label}
            </Link>
          ) : (
            <span className="text-[11px] text-muted">已是第一步</span>
          )}
          {next ? (
            <Link
              href={phaseHref(goalId, next)}
              className="rounded-[10px] bg-brand px-3.5 py-2 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
            >
              下一步：{next.label} →
            </Link>
          ) : (
            <Link
              href={goalHref(goalId)}
              className="rounded-[10px] bg-brand px-3.5 py-2 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
            >
              完成闭环，回到总览 →
            </Link>
          )}
        </div>
      </nav>
    </div>
  );
}

export function Breadcrumb({ goal, phase }: { goal: Goal; phase?: GoalPhase }) {
  return (
    <nav aria-label="面包屑" className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
      <Link href="/goals" className="hover:text-brand">
        学习目标
      </Link>
      <span aria-hidden>/</span>
      <Link href={goalHref(goal.id)} className="hover:text-brand">
        {goal.title}
      </Link>
      {phase && (
        <>
          <span aria-hidden>/</span>
          <span className="text-ink">{phase.title}</span>
        </>
      )}
    </nav>
  );
}

export function GoalStatusBadge({ goal, currentPhaseKey }: { goal: Goal; currentPhaseKey?: string }) {
  const current = GOAL_PHASES[phaseIndex(goal.status)];
  const onCurrentPhase = !currentPhaseKey || currentPhaseKey === current?.key;
  return (
    <Badge tone="active">
      {onCurrentPhase ? "当前阶段" : "阶段状态"}：{current?.label ?? goal.status}
    </Badge>
  );
}

/** 阶段条：可点击跳转，已到达的阶段高亮；当前阶段 aria-current="page"。
 *  阶段数由 GOAL_PHASES 决定（当前五阶段），不写死数字，避免流程调整后再次与注释不符。 */
export function PhaseStepper({
  goalId,
  currentSlug,
  goalStatus,
}: {
  goalId: string;
  currentSlug: string;
  goalStatus: string;
}) {
  return (
    <nav aria-label={`学习目标流程（共 ${GOAL_PHASES.length} 个阶段）`} className="mt-4 mb-5">
      <ol className="flex flex-wrap gap-1.5">
        {GOAL_PHASES.map((phase, index) => {
          const active = phase.slug === currentSlug;
          const reached = isPhaseReached(goalStatus, phase.key);
          return (
            <li key={phase.slug}>
              <Link
                href={phaseHref(goalId, phase)}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand ${
                  active
                    ? "border-brand bg-brand text-white shadow-[0_4px_12px_#6d5dfc33]"
                    : reached
                      ? "border-[#c9c2ff] bg-[#f8f7ff] font-bold text-brand hover:border-brand"
                      : "border-line bg-white text-muted hover:border-[#c9c3ff]"
                }`}
              >
                <span
                  className={`grid h-4 w-4 shrink-0 place-items-center rounded text-[9px] font-bold ${
                    active ? "bg-white/20 text-white" : reached ? "bg-[#f0edff] text-brand" : "bg-[#f0f2f7] text-[#68748a]"
                  }`}
                  aria-hidden
                >
                  {index + 1}
                </span>
                {phase.label}
                {reached && !active && <span aria-label="已到达">✓</span>}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** 阶段卡片上的「尚未开始 / 进行中 / 已到达」文案。 */
export function phaseStateLabel(goalStatus: string, phaseKey: string): { label: string; tone: "done" | "active" | "neutral" } {
  const currentIdx = phaseIndex(goalStatus);
  const idx = phaseIndex(phaseKey);
  if (idx < currentIdx) return { label: "已完成", tone: "done" };
  if (idx === currentIdx) return { label: "进行中", tone: "active" };
  return { label: "未开始", tone: "neutral" };
}

/** 小尺寸空状态 / 提示按钮，供子页复用。 */
export function InlineAction({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <Button variant="secondary" onClick={onClick} disabled={disabled}>
      {children}
    </Button>
  );
}
