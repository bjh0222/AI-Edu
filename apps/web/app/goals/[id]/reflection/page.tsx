"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Reflection } from "@/lib/types";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, Empty, inputCls } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import { errMsg, type WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("reflection");
const SLICES: WorkspaceSlices = { reflections: true };

export default function ReflectionPage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy, reload, setError }) => (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Card
            title="⑧ 学习复盘"
            desc="记录完成了什么、仍依赖 AI 的地方、下一步最值得做的事"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">{data.reflections.length} 条</Badge>
                <Button
                  variant="secondary"
                  onClick={() =>
                    run(
                      "reflection",
                      async () => {
                        await api.post(`/api/goals/${goalId}/reflections`, {});
                      },
                      "复盘草稿已生成"
                    )
                  }
                  disabled={busy === "reflection"}
                >
                  {busy === "reflection" ? "生成中…" : "生成复盘草稿"}
                </Button>
              </div>
            }
          >
            {data.reflections.length === 0 ? (
              <Empty>尚无复盘记录。点击右上角「生成复盘草稿」。</Empty>
            ) : (
              <div className="grid gap-2.5">
                {data.reflections.map((reflection) => (
                  <ReflectionItem
                    key={reflection.id}
                    reflection={reflection}
                    onSaved={reload}
                    onError={(message) => setError(message)}
                  />
                ))}
              </div>
            )}
          </Card>

          <div className="grid gap-4">
            <Card title="复盘写什么" desc="复盘的目标是「下一次更独立」，不是写总结作文">
              <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                <li>· 已形成的能力：能重复做出来的事，附证据。</li>
                <li>· 仍依赖 AI 的地方：哪一步还需要提示。</li>
                <li>· 下一步：一条最小的、可验证的行动。</li>
              </ul>
            </Card>
            <Card title="下一环节" desc="把本轮沉淀的概念与关系提交到知识网络">
              <div className="grid gap-2 text-[12px]">
                <Link
                  href={`/goals/${data.goal?.id}/knowledge-update`}
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                >
                  去知识记录 →
                </Link>
              </div>
            </Card>
          </div>
        </div>
      )}
    </GoalPhaseView>
  );
}

function ReflectionItem({
  reflection,
  onSaved,
  onError,
}: {
  reflection: Reflection;
  onSaved: () => Promise<void> | void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState({
    summary: reflection.summary ?? "",
    learned_capabilities: reflection.learned_capabilities ?? "",
    unresolved_gaps: reflection.unresolved_gaps ?? "",
    next_actions: reflection.next_actions ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setBusy(true);
    setSaved(false);
    try {
      await api.patch(`/api/reflections/${reflection.id}`, form);
      await onSaved();
      setSaved(true);
    } catch (e) {
      onError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-line p-3 text-[12px] leading-relaxed">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] text-muted">{reflection.created_at}</span>
        {reflection.demo && <Badge tone="demo">演示生成</Badge>}
      </div>
      <textarea
        className={`${inputCls} mt-1.5`}
        rows={2}
        value={form.summary}
        onChange={(event) => setForm({ ...form, summary: event.target.value })}
        aria-label="复盘总结"
      />
      <div className="mt-1.5 grid gap-1.5">
        <label className="grid gap-1">
          <span className="text-[10px] font-bold text-[#5a6a86]">已形成的能力</span>
          <textarea
            className={inputCls}
            rows={2}
            value={form.learned_capabilities}
            onChange={(event) => setForm({ ...form, learned_capabilities: event.target.value })}
          />
        </label>
        <label className="grid gap-1">
          <span className="text-[10px] font-bold text-[#5a6a86]">仍依赖 AI / 待解决</span>
          <textarea
            className={inputCls}
            rows={2}
            value={form.unresolved_gaps}
            onChange={(event) => setForm({ ...form, unresolved_gaps: event.target.value })}
          />
        </label>
        <label className="grid gap-1">
          <span className="text-[10px] font-bold text-[#5a6a86]">下一步最值得做的事</span>
          <textarea
            className={inputCls}
            rows={2}
            value={form.next_actions}
            onChange={(event) => setForm({ ...form, next_actions: event.target.value })}
          />
        </label>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={save} disabled={busy}>
          {busy ? "保存中…" : "保存复盘"}
        </Button>
        {saved && <span className="text-[11px] text-[#128b78]">已保存</span>}
        {reflection.candidate_concepts && reflection.candidate_concepts.length > 0 && (
          <span className="text-[10px] text-muted">
            候选概念：{reflection.candidate_concepts.map((item) => item.title).join("、")}
          </span>
        )}
      </div>
    </div>
  );
}
