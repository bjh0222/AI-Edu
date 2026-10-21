"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { phase } from "@/lib/goal-phases";
import type { Criterion } from "@/lib/types";
import { Badge, Button, Card, Empty } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import type { WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("acceptance_design");
const SLICES: WorkspaceSlices = { criteria: true, plan: true };

const EVIDENCE_LABEL: Record<string, string> = {
  product: "产物",
  artifact: "产物",
  process: "过程记录",
  explanation: "解释",
  performance: "现场演示",
  transfer: "迁移任务",
};

export default function AcceptanceDesignPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy }) => {
        const criteria = data.criteria;
        const confirmedCount = criteria.filter((item) => item.status === "confirmed").length;
        const pendingCount = criteria.filter((item) => item.status === "pending").length;
        const stepTitle = (stepId?: string | null) =>
          data.plan?.steps.find((step) => step.id === stepId)?.title ?? "";

        return (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Card
              title="③ 验收标准"
              desc="先定义「学会的证据」，再生成教程。确认后的标准才会进入教程验收"
              actions={
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={confirmedCount === criteria.length && criteria.length > 0 ? "done" : "warn"}>
                    {confirmedCount}/{criteria.length} 已确认
                  </Badge>
                  {pendingCount > 0 && (
                    <Button
                      variant="secondary"
                      onClick={() =>
                        run(
                          "confirm-all",
                          async () => {
                            await api.post(`/api/goals/${goalId}/criteria/confirm-all`);
                          },
                          "已一键同意全部待确认验收标准"
                        )
                      }
                      disabled={busy === "confirm-all"}
                    >
                      {busy === "confirm-all" ? "确认中…" : `一键同意全部（${pendingCount}）`}
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    onClick={() =>
                      run(
                        "criteria",
                        async () => {
                          await api.post(`/api/goals/${goalId}/criteria`);
                        },
                        "验收标准已生成"
                      )
                    }
                    disabled={busy === "criteria"}
                  >
                    {busy === "criteria" ? "生成中…" : "生成验收标准"}
                  </Button>
                </div>
              }
            >
              {criteria.length === 0 ? (
                <Empty>尚未设计验收标准。点击右上角「生成验收标准」。</Empty>
              ) : (
                <div className="grid gap-2">
                  {criteria.map((criterion) => (
                    <CriterionRow
                      key={criterion.id}
                      criterion={criterion}
                      planStepTitle={stepTitle(criterion.plan_step_id)}
                      busy={busy}
                      onToggle={() =>
                        run(
                          `crit-${criterion.id}`,
                          async () => {
                            await api.patch(`/api/criteria/${criterion.id}`, {
                              status: criterion.status === "confirmed" ? "pending" : "confirmed",
                            });
                          },
                          criterion.status === "confirmed" ? "已取消确认" : "已确认该标准"
                        )
                      }
                      onDelete={() =>
                        run(
                          `del-${criterion.id}`,
                          async () => {
                            await api.del(`/api/criteria/${criterion.id}`);
                          },
                          "已删除该标准"
                        )
                      }
                    />
                  ))}
                </div>
              )}
            </Card>

            <div className="grid gap-4">
              <Card title="写作规范" desc="验收标准必须可判定，否则教程无法验收">
                <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                  <li>· 以「能够 + 可观察动词」开头；避免「理解 / 掌握 / 熟悉 / 了解 / 学会」。</li>
                  <li>· 每条都要有通过条件（怎样算通过），并说明证据类型。</li>
                  <li>· 覆盖概念解释、应用、错误诊断、独立完成、迁移五个维度中的至少四个。</li>
                </ul>
              </Card>
              <Card title="下一步" desc="至少确认一条标准后才能生成教程">
                <div className="grid gap-2 text-[12px]">
                  <Link
                    href={`/goals/${data.goal?.id}/learning`}
                    className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                  >
                    去生成教程 →
                  </Link>
                  <span className="text-[11px] text-muted">
                    当前已确认 {confirmedCount} 条
                    {confirmedCount === 0 ? "：生成教程前请先确认标准，或使用总览页「一键生成」自动同意。" : "。"}
                  </span>
                </div>
              </Card>
            </div>
          </div>
        );
      }}
    </GoalPhaseView>
  );
}

function CriterionRow({
  criterion,
  planStepTitle,
  busy,
  onToggle,
  onDelete,
}: {
  criterion: Criterion;
  planStepTitle: string;
  busy: string;
  onToggle: () => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  return (
    <div className="rounded-xl border border-line p-3">
      <div className="flex items-start justify-between gap-2">
        <b className="text-[12px] leading-relaxed">{criterion.statement}</b>
        <Badge
          tone={criterion.status === "confirmed" ? "done" : criterion.status === "rejected" ? "warn" : "neutral"}
        >
          {criterion.status === "confirmed" ? "已确认" : criterion.status === "rejected" ? "已拒绝" : "待确认"}
        </Badge>
      </div>
      {criterion.conditions && <div className="mt-1 text-[11px] text-muted">条件：{criterion.conditions}</div>}
      {criterion.pass_rule && <div className="mt-0.5 text-[11px] text-muted">通过条件：{criterion.pass_rule}</div>}
      {criterion.rationale && <div className="mt-0.5 text-[11px] text-muted">依据：{criterion.rationale}</div>}
      {planStepTitle && <div className="mt-0.5 text-[10px] text-[#99a2b3]">对应计划阶段：{planStepTitle}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px]">
        <button
          className="font-semibold text-brand hover:underline disabled:opacity-40"
          disabled={busy === `crit-${criterion.id}`}
          onClick={() => void onToggle()}
        >
          {criterion.status === "confirmed" ? "取消确认" : "确认标准"}
        </button>
        <button
          className="text-muted hover:text-[#c33] disabled:opacity-40"
          disabled={busy === `del-${criterion.id}`}
          onClick={() => void onDelete()}
        >
          删除
        </button>
        <span className="ml-auto text-[10px] text-[#99a2b3]">
          证据类型：{EVIDENCE_LABEL[criterion.evidence_type] ?? criterion.evidence_type}
        </span>
      </div>
    </div>
  );
}
