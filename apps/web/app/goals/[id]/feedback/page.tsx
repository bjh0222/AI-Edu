"use client";

import Link from "next/link";
import { phase } from "@/lib/goal-phases";
import { FeedbackForm } from "@/components/FeedbackForm";
import { Badge, Card, Empty } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import type { WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("feedback");
const SLICES: WorkspaceSlices = { tasks: true, attempts: true, criteria: true };

export default function FeedbackPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data }) => {
        const rows = data.tasks
          .flatMap((task) =>
            (data.attempts[task.id] ?? []).map((attempt) => ({ task, attempt }))
          )
          .sort((a, b) => String(b.attempt.created_at ?? "").localeCompare(String(a.attempt.created_at ?? "")));

        const items = rows.flatMap((row) => row.attempt.feedback?.items ?? []);
        const satisfied = items.filter((item) => item.status === "satisfied").length;
        const unsatisfied = items.filter((item) => item.status === "unsatisfied").length;
        const unclear = items.filter((item) => item.status === "unclear").length;

        return (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Card
              title="⑥ 逐条证据反馈"
              desc="每次实践提交都会按验收标准逐项判断；反馈只基于你提供的证据"
              actions={
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="done">满足 {satisfied}</Badge>
                  <Badge tone="neutral">未满足 {unsatisfied}</Badge>
                  <Badge tone="warn">待确认 {unclear}</Badge>
                </div>
              }
            >
              {rows.length === 0 ? (
                <Empty>
                  还没有实践提交。先到
                  <Link href={`/goals/${goalId}/practice`} className="mx-1 font-semibold text-brand hover:underline">
                    实践任务
                  </Link>
                  提交一次产物。
                </Empty>
              ) : (
                <div className="grid gap-2.5">
                  {rows.map(({ task, attempt }) => (
                    <div key={attempt.id} className="rounded-xl border border-line p-3 text-[11px] leading-relaxed">
                      <div className="flex flex-wrap items-center gap-2">
                        <b className="text-[12px]">{task.title}</b>
                        <Badge>尝试 · {attempt.help_level}</Badge>
                        <span className="text-[10px] text-muted">{attempt.created_at}</span>
                      </div>
                      <div className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-[#33415c]">
                        {attempt.artifact}
                      </div>
                      {attempt.feedback?.summary && (
                        <div className="mt-1 text-muted">总结：{attempt.feedback.summary}</div>
                      )}
                      {(attempt.feedback?.items ?? []).length > 0 && (
                        <ul className="mt-1.5 grid gap-1">
                          {(attempt.feedback?.items ?? []).map((item, index) => (
                            <li key={index} className="rounded-lg bg-[#fbfcff] p-2">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <Badge
                                  tone={
                                    item.status === "satisfied"
                                      ? "done"
                                      : item.status === "unclear"
                                        ? "warn"
                                        : "neutral"
                                  }
                                >
                                  {item.status === "satisfied"
                                    ? "满足"
                                    : item.status === "unsatisfied"
                                      ? "未满足"
                                      : "待确认"}
                                </Badge>
                                <span className="font-semibold">{item.statement || "（标准）"}</span>
                              </div>
                              {item.evidence && <div className="mt-0.5 text-muted">证据：{item.evidence}</div>}
                              {item.reason && <div className="text-muted">判断：{item.reason}</div>}
                              {item.next_action && <div className="text-[#6255e8]">下一步：{item.next_action}</div>}
                            </li>
                          ))}
                        </ul>
                      )}
                      {attempt.feedback?.weak_points && (
                        <div className="mt-1 text-[#a33]">薄弱点：{attempt.feedback.weak_points}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <div className="grid gap-4">
              <Card title="你的反馈" desc="测试版：反馈会持久化，并随训练数据一起导出">
                <FeedbackForm goalId={goalId} targetType="generation" title="这些反馈对你有帮助吗？" />
              </Card>
              <Card title="反馈怎么用" desc="先补证据，再谈「学会了」">
                <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                  <li>· 「未满足」不要急着改结论，先看它缺的是哪类证据。</li>
                  <li>· 「待确认」通常意味着产物不足以判断，补一次可观察的输出。</li>
                  <li>· 需要独立判断时，到能力评估页做独立任务与变式任务。</li>
                </ul>
                <div className="mt-2 grid gap-2 text-[12px]">
                  <Link
                    href={`/goals/${goalId}/assessment`}
                    className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                  >
                    去做能力评估 →
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
