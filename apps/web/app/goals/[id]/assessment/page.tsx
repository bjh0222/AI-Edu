"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Assessment } from "@/lib/types";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, Empty, inputCls } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import { errMsg, type WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("assessment");
const SLICES: WorkspaceSlices = { assessments: true };

const TYPE_LABEL: Record<string, string> = {
  independent: "独立任务",
  variant: "变式任务",
  mixed: "独立 + 变式",
};

export default function AssessmentPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy, reload, setError }) => (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Card
            title="⑦ 能力评估"
            desc="独立任务 + 变式任务，检查能否不依赖教程完成；记录结果与薄弱点"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">{data.assessments.length} 份</Badge>
                <Button
                  variant="secondary"
                  onClick={() =>
                    run(
                      "assessment",
                      async () => {
                        await api.post(`/api/goals/${goalId}/assessments`, { assessment_type: "mixed" });
                      },
                      "评估方案已生成"
                    )
                  }
                  disabled={busy === "assessment"}
                >
                  {busy === "assessment" ? "生成中…" : "生成评估方案"}
                </Button>
              </div>
            }
          >
            {data.assessments.length === 0 ? (
              <Empty>尚未生成评估方案。点击右上角「生成评估方案」。</Empty>
            ) : (
              <div className="grid gap-2">
                {data.assessments.map((assessment) => (
                  <AssessmentItem
                    key={assessment.id}
                    assessment={assessment}
                    onSaved={reload}
                    onError={(message) => setError(message)}
                  />
                ))}
              </div>
            )}
          </Card>

          <div className="grid gap-4">
            <Card title="评估看什么" desc="不看「看完了没有」，看能否在无教程条件下完成">
              <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                <li>· 独立任务：不照抄教程，能自己拆步骤并完成。</li>
                <li>· 变式任务：换一个情境，仍能迁移同一套方法。</li>
                <li>· 记录结果时写清证据（产物、命令输出、关键判断），而不是感受。</li>
              </ul>
            </Card>
            <Card title="下一环节" desc="评估之后做复盘，把经验沉淀成方法">
              <div className="grid gap-2 text-[12px]">
                <Link
                  href={`/goals/${data.goal?.id}/reflection`}
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                >
                  去复盘 →
                </Link>
              </div>
            </Card>
          </div>
        </div>
      )}
    </GoalPhaseView>
  );
}

function AssessmentItem({
  assessment,
  onSaved,
  onError,
}: {
  assessment: Assessment;
  onSaved: () => Promise<void> | void;
  onError: (message: string) => void;
}) {
  const [result, setResult] = useState(assessment.result ?? "");
  const [weak, setWeak] = useState(assessment.weak_points ?? "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await api.patch(`/api/assessments/${assessment.id}`, { result, weak_points: weak });
      await onSaved();
    } catch (e) {
      onError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-line p-3 text-[11px] leading-relaxed">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="active">{TYPE_LABEL[assessment.assessment_type] ?? assessment.assessment_type}</Badge>
        <span className="text-[10px] text-muted">{assessment.created_at}</span>
      </div>
      {assessment.rubric.length > 0 && (
        <div className="mt-1.5 grid gap-0.5">
          {assessment.rubric.map((item, index) => (
            <div key={index} className="text-muted">
              · {item.dimension}（权重 {item.weight}）{item.note ? ` — ${item.note}` : ""}
            </div>
          ))}
        </div>
      )}
      {assessment.independent_task?.title && (
        <div className="mt-1.5 rounded-lg bg-[#fafbfc] p-2">
          <b className="text-[#4f45a6]">独立任务：</b>
          {assessment.independent_task.title}
          {assessment.independent_task.description && (
            <div className="text-muted">{assessment.independent_task.description}</div>
          )}
          {assessment.independent_task.expected_artifact && (
            <div className="text-[10px] text-[#99a2b3]">
              预期产物：{assessment.independent_task.expected_artifact}
            </div>
          )}
        </div>
      )}
      {assessment.variant_task?.title && (
        <div className="mt-1.5 rounded-lg bg-[#fafbfc] p-2">
          <b className="text-[#4f45a6]">变式任务：</b>
          {assessment.variant_task.title}
          {assessment.variant_task.description && (
            <div className="text-muted">{assessment.variant_task.description}</div>
          )}
        </div>
      )}
      {assessment.evidence_hint && (
        <div className="mt-1.5 text-[10px] text-muted">证据提示：{assessment.evidence_hint}</div>
      )}
      <div className="mt-2 grid gap-1.5">
        <input
          className={inputCls}
          placeholder="评估结果（如：独立完成 3/4 项，迁移任务未通过）"
          value={result}
          onChange={(event) => setResult(event.target.value)}
        />
        <input
          className={inputCls}
          placeholder="薄弱点"
          value={weak}
          onChange={(event) => setWeak(event.target.value)}
        />
        <div>
          <Button variant="secondary" onClick={save} disabled={busy}>
            {busy ? "保存中…" : "保存评估结果"}
          </Button>
        </div>
      </div>
    </div>
  );
}
