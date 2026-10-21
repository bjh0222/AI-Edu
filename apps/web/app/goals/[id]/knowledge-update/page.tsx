"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, Empty } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import type { WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("knowledge_update");
const SLICES: WorkspaceSlices = { proposals: true };

function proposalText(proposal: Proposal): string {
  const payload = proposal.payload as Record<string, unknown>;
  if (payload.title) return `新概念：${String(payload.title)}`;
  if (payload.from_title && payload.to_title) {
    return `新关系：${String(payload.from_title)} —${String(payload.relation_type ?? "related")}→ ${String(
      payload.to_title
    )}`;
  }
  return JSON.stringify(payload);
}

export default function KnowledgeUpdatePage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy }) => (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Card
            title="⑨ 知识提议"
            desc="AI 只能提议，确认后才入长期知识网络"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">{data.proposals.length} 条待确认</Badge>
                <Button
                  variant="secondary"
                  onClick={() =>
                    run(
                      "proposals",
                      async () => {
                        await api.post(`/api/goals/${goalId}/knowledge-proposals`);
                      },
                      "知识提议已生成，请逐条确认"
                    )
                  }
                  disabled={busy === "proposals"}
                >
                  {busy === "proposals" ? "生成中…" : "生成知识提议"}
                </Button>
              </div>
            }
          >
            {data.proposals.length === 0 ? (
              <Empty>暂无待处理提议。完成实践与复盘后再生成，提议会更有依据。</Empty>
            ) : (
              <div className="grid gap-2">
                {data.proposals.map((proposal) => (
                  <div key={proposal.id} className="rounded-xl border border-line p-3 text-[11px] leading-relaxed">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge tone="warn">{proposal.proposal_type === "relation" ? "关系" : "概念"}</Badge>
                    </div>
                    <div className="font-semibold">{proposalText(proposal)}</div>
                    {proposal.rationale && <div className="mt-1 text-muted">依据：{proposal.rationale}</div>}
                    {proposal.evidence_refs && proposal.evidence_refs.length > 0 && (
                      <div className="mt-1 text-[10px] text-muted">证据：{proposal.evidence_refs.join("、")}</div>
                    )}
                    <div className="mt-2 flex gap-2">
                      <Button
                        variant="secondary"
                        disabled={busy === `p-${proposal.id}`}
                        onClick={() =>
                          run(
                            `p-${proposal.id}`,
                            async () => {
                              await api.post(`/api/knowledge/proposals/${proposal.id}/review`, { action: "confirm" });
                            },
                            "已确认该提议"
                          )
                        }
                      >
                        确认
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={busy === `p-${proposal.id}`}
                        onClick={() =>
                          run(
                            `p-${proposal.id}`,
                            async () => {
                              await api.post(`/api/knowledge/proposals/${proposal.id}/review`, { action: "reject" });
                            },
                            "已拒绝该提议"
                          )
                        }
                      >
                        拒绝
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 border-t border-line pt-3 text-[11px]">
              <Link href="/knowledge" className="font-semibold text-brand hover:underline">
                打开完整知识网络 →
              </Link>
            </div>
          </Card>

          <div className="grid gap-4">
            <Card title="为什么只提议不直接写入" desc="知识网络是长期资产，错误关系会污染后续所有生成">
              <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                <li>· 提议必须有依据（本轮实践、复盘或上传材料）。</li>
                <li>· 确认后才进入长期知识网络，并成为后续生成的概念基础。</li>
                <li>· 拒绝不会删除历史数据，只是不纳入网络。</li>
              </ul>
            </Card>
            <Card title="闭环完成" desc="十项流程走完后，可以开始下一轮目标">
              <div className="grid gap-2 text-[12px]">
                <Link
                  href={`/goals/${goalId}`}
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                >
                  ← 返回目标总览
                </Link>
                <Link
                  href="/knowledge"
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-[#39455d] hover:border-[#c9c3ff]"
                >
                  查看知识网络
                </Link>
              </div>
            </Card>
          </div>
        </div>
      )}
    </GoalPhaseView>
  );
}
