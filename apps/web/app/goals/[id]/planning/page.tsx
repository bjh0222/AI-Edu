"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, DemoNotice, Empty } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import type { WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("planning");
const SLICES: WorkspaceSlices = { plan: true };

export default function PlanningPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy }) => {
        const plan = data.plan;
        return (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <Card
              title="② 学习计划"
              desc="把目标拆成有顺序的阶段与步骤；生成时会参考已上传的参考材料"
              actions={
                <Button
                  variant="secondary"
                  onClick={() =>
                    run(
                      "plan",
                      async () => {
                        await api.post(`/api/goals/${goalId}/plan`);
                      },
                      "学习计划已生成"
                    )
                  }
                  disabled={busy === "plan"}
                >
                  {busy === "plan" ? "生成中…" : plan ? "重新生成计划" : "生成学习计划"}
                </Button>
              }
            >
              {!plan ? (
                <Empty>尚未生成学习计划。点击右上角「生成学习计划」。</Empty>
              ) : (
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
                    <Badge tone="active">v{plan.version}</Badge>
                    <span>{plan.steps.length} 个阶段 · 状态 {plan.status}</span>
                  </div>
                  <DemoNotice show={plan.demo}>当前为演示生成器输出，配置真实模型后自动切换。</DemoNotice>
                  <ol className="grid gap-2">
                    {plan.steps.map((step, index) => (
                      <li key={step.id} className="flex gap-3 rounded-xl border border-line p-3">
                        <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[11px] font-bold text-brand">
                          {index + 1}
                        </span>
                        <div>
                          <b className="text-[12px]">{step.title}</b>
                          <div className="mt-0.5 text-[11px] leading-relaxed text-muted">{step.objective}</div>
                          {step.estimated_effort && (
                            <div className="mt-1 text-[10px] text-[#99a2b3]">预计：{step.estimated_effort}</div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </Card>

            <div className="grid gap-4">
              <Card title="计划为什么这样拆" desc="计划服务于验收：先能复述概念，再能独立完成，最后能迁移">
                <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                  <li>· 第一步通常是范围收窄与环境确认，避免一上手就陷进细节。</li>
                  <li>· 每个阶段都应有可观察的产物，而不是「看完了」。</li>
                  <li>· 生成时会把上传的参考资料与例题来源作为依据，题型风格会沿用。</li>
                </ul>
              </Card>
              <Card title="下一步" desc="计划之后先定义「学会的证据」，再生成教程">
                <div className="grid gap-2 text-[12px]">
                  <Link
                    href={`/goals/${data.goal?.id}/acceptance-design`}
                    className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                  >
                    去设计验收标准 →
                  </Link>
                  <Link
                    href={`/goals/${data.goal?.id}`}
                    className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-[#39455d] hover:border-[#c9c3ff]"
                  >
                    返回目标总览
                  </Link>
                </div>
              </Card>
            </div>
          </div>
        );
      }}
    </GoalPhaseView>
  );
}
