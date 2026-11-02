"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, DemoNotice, Empty, inputCls } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import { MaterialsPanel } from "@/components/goals/MaterialsPanel";
import type { WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("diagnosis");
const SLICES: WorkspaceSlices = { diagnosis: true, materials: true };

export default function DiagnosisPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy, reload }) => {
        const diagnosis = data.diagnosis;
        return (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <Card
              title="① 价值诊断"
              desc="先判断是否值得学、范围是否合理——AI 给建议，你作决定"
              actions={
                <Button
                  variant="secondary"
                  onClick={() =>
                    run(
                      "diagnose",
                      async () => {
                        await api.post(`/api/goals/${goalId}/diagnose`);
                      },
                      "价值诊断已生成"
                    )
                  }
                  disabled={busy === "diagnose"}
                >
                  {busy === "diagnose" ? "诊断中…" : diagnosis ? "重新诊断" : "运行价值诊断"}
                </Button>
              }
            >
              {!diagnosis ? (
                <Empty>尚未诊断。点击右上角「运行价值诊断」；上传的参考资料会作为依据。</Empty>
              ) : (
                <div className="grid gap-2 text-[12px] leading-relaxed">
                  <DemoNotice show={diagnosis.demo}>
                    当前为演示生成器输出，配置真实模型后自动切换。
                  </DemoNotice>
                  <KV k="收益" v={diagnosis.benefits} />
                  <KV k="前置条件" v={diagnosis.prerequisites} />
                  <KV k="替代路径" v={diagnosis.alternatives} />
                  <KV k="假设" v={diagnosis.assumptions} />
                  <KV k="不确定项" v={diagnosis.uncertainties} />
                  <KV k="建议" v={diagnosis.recommendation} />
                  {diagnosis.user_decision ? (
                    <div className="rounded-lg bg-[#f0fbf8] px-3 py-2 text-[#128b78]">
                      你的决定：<b>{diagnosis.user_decision}</b>
                      {diagnosis.decision_reason && ` · 理由：${diagnosis.decision_reason}`}
                    </div>
                  ) : (
                    <DecisionBox
                      busy={busy === "decision"}
                      onDecide={(decision, reason) =>
                        run(
                          "decision",
                          async () => {
                            await api.post(`/api/goals/${goalId}/decision`, { decision, reason });
                          },
                          "已记录你的决定"
                        )
                      }
                    />
                  )}
                </div>
              )}
            </Card>

            <div className="grid gap-4">
              <Card
                title="参考资料 / 例题来源"
                desc="上传讲义、教材章节或往年例题：会作为价值诊断、学习计划与教程生成的依据"
                actions={<Badge tone="neutral">{data.materials.length} 份</Badge>}
              >
                <MaterialsPanel goalId={goalId} materials={data.materials} onChanged={reload} />
              </Card>

              <Card title="本次生成的来源标注" desc="注入 prompt 的材料（纯文本材料直接注入文件原文，超长才截断）">
                {data.materials.length === 0 ? (
                  <Empty>没有材料：诊断只基于目标描述本身。</Empty>
                ) : (
                  <ul className="grid gap-1 text-[11px]">
                    {data.materials.map((material, index) => (
                      <li key={material.id} className="flex flex-wrap items-center gap-1.5">
                        <span className="grid h-4 w-4 place-items-center rounded bg-[#f0edff] text-[9px] font-bold text-brand">
                          {index + 1}
                        </span>
                        <span className="font-semibold text-[#33415c]">{material.filename}</span>
                        <Badge tone={material.kind === "example_source" ? "warn" : "active"}>
                          {material.kind === "example_source" ? "例题来源" : "参考资料"}
                        </Badge>
                        <span className="text-[10px] text-muted">
                          {material.extract_status === "ok"
                            ? `${material.char_count.toLocaleString()} 字正文`
                            : material.extract_status === "truncated"
                              ? `仅载入 ${material.char_count.toLocaleString()} / ${material.source_char_count.toLocaleString()} 字（已截断）`
                              : "未抽取正文"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </div>
        );
      }}
    </GoalPhaseView>
  );
}

function DecisionBox({
  busy,
  onDecide,
}: {
  busy: boolean;
  onDecide: (decision: string, reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="mt-1 rounded-xl border border-line bg-[#fbfcff] p-3">
      <div className="mb-2 text-[11px] font-bold">你的决定（AI 不替你决定）</div>
      <input
        className={inputCls}
        placeholder="理由（可选）：为什么这样决定？"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {["继续", "调整", "暂缓"].map((decision) => (
          <Button
            key={decision}
            variant={decision === "继续" ? "primary" : "secondary"}
            disabled={busy}
            onClick={() => void onDecide(decision, reason)}
          >
            {decision}
          </Button>
        ))}
      </div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  if (!v) return null;
  return (
    <div>
      <div className="text-[11px] font-bold text-[#5a6a86]">{k}</div>
      <div className="whitespace-pre-wrap text-[12px] text-[#33415c]">{v}</div>
    </div>
  );
}
