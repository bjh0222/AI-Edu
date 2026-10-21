"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Attempt, Task } from "@/lib/types";
import { phase } from "@/lib/goal-phases";
import { Badge, Button, Card, Empty, inputCls } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import { errMsg, type WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("practice");
const SLICES: WorkspaceSlices = { tasks: true, attempts: true };

export default function PracticePage() {
  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ data, reload, setError }) => (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Card
            title="⑤ 实践任务"
            desc="每个任务都要有产物、验证方式与辅助等级记录；提交后按验收标准给出逐条反馈"
            actions={<Badge tone="neutral">{data.tasks.length} 个任务</Badge>}
          >
            {data.tasks.length === 0 ? (
              <Empty>暂无任务。生成教程章节后会自动创建一个实践任务。</Empty>
            ) : (
              <div className="grid gap-2.5">
                {data.tasks.map((task) => (
                  <TaskItem
                    key={task.id}
                    task={task}
                    attempts={data.attempts[task.id] ?? []}
                    onSubmitted={reload}
                    onError={(message) => setError(message)}
                  />
                ))}
              </div>
            )}
          </Card>

          <div className="grid gap-4">
            <Card title="辅助等级怎么填" desc="记录你实际用到的帮助程度，评估阶段会据此判断独立性">
              <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
                <li>
                  <b className="text-[#33415c]">A0 引导</b>：照着完整步骤做，还不能自己决定下一步。
                </li>
                <li>
                  <b className="text-[#33415c]">A1 协作</b>：和 AI 分工，关键判断由你做。
                </li>
                <li>
                  <b className="text-[#33415c]">A2 提示</b>：只需要少量提示就能完成。
                </li>
                <li>
                  <b className="text-[#33415c]">A3 独立验证</b>：独立完成，并能解释为什么这样做。
                </li>
              </ul>
              <p className="mt-2 text-[10px] text-[#99a2b3]">
                提交产物后无需等待：反馈会按验收标准逐项判断是否满足，并给出最小下一步。
              </p>
            </Card>
            <Card title="下一环节" desc="实践提交后进入反馈：看证据、补差距">
              <div className="grid gap-2 text-[12px]">
                <Link
                  href={`/goals/${data.goal?.id}/feedback`}
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
                >
                  去看反馈 →
                </Link>
                <Link
                  href={`/goals/${data.goal?.id}/learning`}
                  className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-[#39455d] hover:border-[#c9c3ff]"
                >
                  ← 回到教程学习
                </Link>
              </div>
            </Card>
          </div>
        </div>
      )}
    </GoalPhaseView>
  );
}

function TaskItem({
  task,
  attempts,
  onSubmitted,
  onError,
}: {
  task: Task;
  attempts: Attempt[];
  onSubmitted: () => Promise<void> | void;
  onError: (message: string) => void;
}) {
  const [artifact, setArtifact] = useState("");
  const [helpLevel, setHelpLevel] = useState("A1");
  const [errorsText, setErrorsText] = useState("");
  const [explanation, setExplanation] = useState("");
  const [busy, setBusy] = useState(false);
  const [localErr, setLocalErr] = useState("");

  const submit = async () => {
    if (!artifact.trim()) {
      setLocalErr("请填写产物（命令输出 / 代码 / 推导 / 证据）");
      return;
    }
    setBusy(true);
    setLocalErr("");
    try {
      await api.post(`/api/tasks/${task.id}/attempts`, {
        artifact,
        artifact_type: "text",
        errors: errorsText,
        help_level: helpLevel,
        user_explanation: explanation,
      });
      setArtifact("");
      setErrorsText("");
      setExplanation("");
      await onSubmitted();
    } catch (e) {
      setLocalErr(errMsg(e));
      onError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-line p-3">
      <div className="flex items-center justify-between gap-2">
        <b className="text-[12px]">{task.title}</b>
        <Badge tone={task.status === "done" ? "done" : task.status === "doing" ? "active" : "neutral"}>
          {task.status === "done" ? "已完成" : task.status === "doing" ? "进行中" : "待开始"}
        </Badge>
      </div>
      <div className="mt-1 whitespace-pre-wrap text-[11px] text-muted">{task.instructions}</div>
      {task.expected_artifact && (
        <div className="mt-1 text-[11px] text-muted">
          预期产物：<b>{task.expected_artifact}</b>
        </div>
      )}
      {task.validation_rule && <div className="text-[10px] text-[#99a2b3]">验收：{task.validation_rule}</div>}

      <div className="mt-2 grid gap-2 rounded-xl bg-[#fbfcff] p-3">
        <textarea
          className={inputCls}
          rows={3}
          placeholder="粘贴产物 / 命令输出 / 推导过程 / 结果…"
          value={artifact}
          onChange={(event) => setArtifact(event.target.value)}
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <select className={inputCls} value={helpLevel} onChange={(event) => setHelpLevel(event.target.value)}>
            <option value="A0">A0 引导（完整步骤）</option>
            <option value="A1">A1 协作</option>
            <option value="A2">A2 提示</option>
            <option value="A3">A3 独立验证</option>
          </select>
          <input
            className={inputCls}
            placeholder="遇到的错误（可选）"
            value={errorsText}
            onChange={(event) => setErrorsText(event.target.value)}
          />
        </div>
        <input
          className={inputCls}
          placeholder="你的解释：为什么这样做（可选）"
          value={explanation}
          onChange={(event) => setExplanation(event.target.value)}
        />
        <div className="flex items-center gap-2">
          <Button onClick={submit} disabled={busy}>
            {busy ? "提交中…" : "提交尝试并获取反馈"}
          </Button>
          {localErr && <span className="text-[11px] text-[#a33]">{localErr}</span>}
        </div>
      </div>

      {attempts.length > 0 && (
        <div className="mt-2 grid gap-2">
          {attempts.map((attempt) => (
            <div
              key={attempt.id}
              className="rounded-xl border border-[#e7e3ff] bg-[#faf9ff] p-3 text-[11px] leading-relaxed"
            >
              <div className="flex items-center gap-2">
                <Badge>尝试 · {attempt.help_level}</Badge>
                <span className="text-[10px] text-muted">{attempt.created_at}</span>
              </div>
              <div className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-[#33415c]">{attempt.artifact}</div>
              {attempt.feedback?.summary && <div className="mt-1 text-muted">反馈：{attempt.feedback.summary}</div>}
              {attempt.feedback?.items && attempt.feedback.items.length > 0 && (
                <ul className="mt-1 grid gap-1">
                  {attempt.feedback.items.map((item, index) => (
                    <li key={index} className="rounded-lg bg-white p-2">
                      <div className="flex items-center gap-1.5">
                        <Badge
                          tone={
                            item.status === "satisfied" ? "done" : item.status === "unclear" ? "warn" : "neutral"
                          }
                        >
                          {item.status === "satisfied" ? "满足" : item.status === "unsatisfied" ? "未满足" : "待确认"}
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
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
