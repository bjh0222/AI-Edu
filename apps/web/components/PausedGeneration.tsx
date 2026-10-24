"use client";

import { useState } from "react";
import { Button, inputCls } from "@/components/ui";

export type PauseResumeAction = "proceed" | "adopt";

export function PausedGenerationPanel({
  recommendation,
  initialPlan,
  busy,
  onResume,
  onRevise,
}: {
  recommendation: string;
  initialPlan: string;
  busy: boolean;
  onResume: (action: PauseResumeAction) => void;
  onRevise: (plan: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [plan, setPlan] = useState(initialPlan);

  return (
    <div className="rounded-xl border border-[#f3e3c4] bg-[#fffaf0] p-3">
      <b className="text-[12px] text-[#8a6411]">AI 已暂停生成</b>
      <p className="mt-1 text-[11px] leading-relaxed text-[#5a6a86]">{recommendation}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => onResume("proceed")} disabled={busy}>
          坚决执行
        </Button>
        <Button onClick={() => onResume("adopt")} disabled={busy}>
          采纳AI建议后立即执行
        </Button>
        <Button variant="secondary" onClick={() => setEditing((value) => !value)} disabled={busy}>
          {editing ? "收起修改" : "修改计划"}
        </Button>
      </div>
      {editing && (
        <div className="mt-3">
          <textarea
            className={inputCls}
            rows={4}
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            placeholder="修改学习目标、范围、成果或执行方式。"
          />
          <div className="mt-2">
            <Button onClick={() => onRevise(plan)} disabled={busy || !plan.trim()}>
              保存修改并执行
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
