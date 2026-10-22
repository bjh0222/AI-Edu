"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ApiError, downloadFile } from "@/lib/api";
import { startJobPolling, jobDoneMessage } from "@/lib/job-poll";
import type {
  ChatResponse,
  Criterion,
  Goal,
  GoalAssessment,
  GoalUsage,
  Plan,
  QuickStartResult,
  QuickStartStep,
  Tutorial,
} from "@/lib/types";
import { fmtTokens, usageSourceLabel } from "@/lib/format";
import { OutlineList, SectionContent, TokenLine } from "@/components/tutorial";
import { FeedbackForm } from "@/components/FeedbackForm";
import { Badge, Button, Card, DemoNotice, Empty, inputCls } from "@/components/ui";
import { GOAL_PHASES } from "@/lib/goal-phases";
import { GoalMaterialsCard } from "@/components/goals/GoalMaterialsCard";

const PHASES: { key: string; label: string }[] = [
  { key: "goal_definition", label: "目标定义" },
  { key: "diagnosis", label: "价值诊断" },
  { key: "planning", label: "学习计划" },
  { key: "acceptance_design", label: "验收标准" },
  { key: "learning", label: "教程学习" },
];

const STATUS_LABEL: Record<string, string> = Object.fromEntries(PHASES.map((p) => [p.key, p.label]));

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function GoalPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-[900px] px-6 py-10 text-[13px] text-muted">加载中…</div>
      }
    >
      <GoalWorkspace />
    </Suspense>
  );
}

function GoalWorkspace() {
  const params = useParams<{ id: string }>();
  const goalId = params.id;

  const [goal, setGoal] = useState<Goal | null>(null);
  const [diagnosis, setDiagnosis] = useState<GoalAssessment | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [tutorials, setTutorials] = useState<Tutorial[]>([]);
  const [chatLog, setChatLog] = useState<{ q: string; a: string; demo: boolean }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [gen, setGen] = useState<{ stage: string; progress: number; tokens: number } | null>(null);
  const [usage, setUsage] = useState<GoalUsage | null>(null);
  const [quickSteps, setQuickSteps] = useState<QuickStartStep[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const tutorial = tutorials[0] ?? null;
  const confirmedCount = criteria.filter((c) => c.status === "confirmed").length;
  const pendingCount = criteria.filter((c) => c.status === "pending").length;

  const pollCancel = useRef<(() => void) | null>(null);

  useEffect(() => {
    // 卸载时停掉轮询，避免页面跳走后继续请求 + setState
    return () => {
      pollCancel.current?.();
      pollCancel.current = null;
    };
  }, []);

  const loadAll = useCallback(async () => {
    const [g, d, p, c, ts, u] = await Promise.all([
      api.get<Goal>(`/api/goals/${goalId}`),
      api.get<GoalAssessment | null>(`/api/goals/${goalId}/diagnose`).catch(() => null),
      api.get<Plan | null>(`/api/goals/${goalId}/plan`).catch(() => null),
      api.get<Criterion[]>(`/api/goals/${goalId}/criteria`).catch(() => []),
      api.get<Tutorial[]>(`/api/goals/${goalId}/tutorials`).catch(() => []),
      api.get<GoalUsage>(`/api/goals/${goalId}/usage`).catch(() => null),
    ]);
    setGoal(g);
    setDiagnosis(d);
    setPlan(p);
    setCriteria(c);
    setTutorials(ts);
    setUsage(u);
  }, [goalId]);

  useEffect(() => {
    // 挂载时加载工作区数据（与后端 API 同步）；该规则对异步 setState 误报
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadAll().catch((e) => setError(errMsg(e)));
  }, [loadAll]);

  const run = async (key: string, fn: () => Promise<void>, msg = "完成") => {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await fn();
      await loadAll();
      setNotice(msg);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const pollJob = (jobId: string) => {
    // 先取消上一次轮询：连点「一键生成」不应产生两路计时器同时刷同一个 job
    pollCancel.current?.();
    pollCancel.current = startJobPolling(jobId, {
      onUpdate: (job) =>
        setGen({
          stage: job.stage,
          progress: job.progress,
          tokens: job.token_usage?.total_tokens ?? 0,
        }),
      onDone: async (job) => {
        setGen(null);
        setBusy("");
        await loadAll();
        setNotice(jobDoneMessage(job));
      },
      onFailed: (message) => {
        setGen(null);
        setBusy("");
        setError(message);
      },
      onError: (message) => {
        setGen(null);
        setBusy("");
        setError(message);
      },
    });
  };

  const startSections = async () => {
    if (!tutorial || busy) return;
    setBusy("sections");
    setError("");
    setNotice("");
    try {
      const resp = await api.post<{ job_id: string }>(`/api/tutorials/${tutorial.id}/sections/generate`);
      setGen({ stage: "已提交，等待模型返回…", progress: 0, tokens: 0 });
      pollJob(resp.job_id);
    } catch (e) {
      setBusy("");
      setError(errMsg(e));
    }
  };

  const startQuickstart = async () => {
    if (busy) return;
    setBusy("quickstart");
    setError("");
    setNotice("");
    setQuickSteps([]);
    try {
      const resp = await api.post<QuickStartResult>(`/api/goals/${goalId}/tutorials/quickstart`);
      setQuickSteps(resp.steps);
      await loadAll();
      if (resp.job_id) {
        // 可能是章节任务，也可能是「只差配套文件」的后台任务，进度文案交给 job.stage
        setGen({ stage: "任务已提交，等待模型返回…", progress: 0, tokens: 0 });
        pollJob(resp.job_id);
      } else {
        setBusy("");
        setNotice("教材已是最新状态：没有重复生成。");
      }
    } catch (e) {
      setBusy("");
      setError(errMsg(e));
    }
  };

  const confirmAllCriteria = () =>
    run(
      "confirm-all",
      async () => {
        await api.post(`/api/goals/${goalId}/criteria/confirm-all`);
      },
      "已一键同意全部待确认验收标准"
    );

  if (!goal) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-10">
        <div className="text-[13px] text-muted">加载中…</div>
      </div>
    );
  }

  const phaseIdx = Math.max(0, PHASES.findIndex((p) => p.key === goal.status));

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      {/* 顶部 */}
      <div className="mb-5">
        <Link href="/goals" className="text-[12px] text-muted hover:text-brand">
          ← 返回目标列表
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-bold tracking-tight">{goal.title}</h1>
          <Badge tone="active">{STATUS_LABEL[goal.status] ?? goal.status}</Badge>
          <Badge>{goal.domain_name}</Badge>
        </div>
        {goal.motivation && <p className="mt-1 text-[12px] text-muted">为什么学：{goal.motivation}</p>}
      </div>

      {/* 阶段条 */}
      <div className="mb-5 flex flex-wrap gap-1.5">
        {PHASES.map((p, i) => (
          <Link
            key={p.key}
            href={`/goals/${goalId}/${GOAL_PHASES.find((g) => g.key === p.key)?.slug ?? p.key}`}
            title={`打开「${p.label}」详情页`}
            className={`rounded-lg border px-2.5 py-1.5 text-[10px] transition hover:border-[#c9c2ff] hover:text-brand ${
              i <= phaseIdx
                ? "border-[#c9c2ff] bg-[#f8f7ff] font-bold text-brand"
                : "border-line bg-white text-muted"
            }`}
          >
            {String(i + 1).padStart(2, "0")} {p.label}
          </Link>
        ))}
      </div>

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

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="grid gap-4">
          {/* 1 价值诊断 */}
          <Card
            title="① 价值诊断"
            desc="先判断是否值得学、范围是否合理——AI 给建议，你作决定"
            actions={
              <Button
                variant="secondary"
                onClick={() => run("diagnose", async () => { await api.post(`/api/goals/${goalId}/diagnose`); }, "价值诊断已生成")}
                disabled={busy === "diagnose"}
              >
                {busy === "diagnose" ? "诊断中…" : diagnosis ? "重新诊断" : "运行价值诊断"}
              </Button>
            }
          >
            {!diagnosis ? (
              <Empty>尚未诊断。点击右上角「运行价值诊断」。</Empty>
            ) : (
              <div className="grid gap-2 text-[12px] leading-relaxed">
                <DemoNotice show={diagnosis.demo}>当前为演示生成器输出，配置真实模型后自动切换。</DemoNotice>
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
                  <div className="mt-1 rounded-xl border border-line bg-[#fbfcff] p-3">
                    <div className="mb-2 text-[11px] font-bold">你的决定（AI 不替你决定）</div>
                    <input
                      className={inputCls}
                      placeholder="理由（可选）：为什么这样决定？"
                      value={decisionReason}
                      onChange={(e) => setDecisionReason(e.target.value)}
                    />
                    <div className="mt-2 flex flex-wrap gap-2">
                      {["继续", "调整", "暂缓"].map((d) => (
                        <Button
                          key={d}
                          variant={d === "继续" ? "primary" : "secondary"}
                          disabled={busy === "decision"}
                          onClick={() =>
                            run(
                              "decision",
                              async () => {
                                await api.post(`/api/goals/${goalId}/decision`, {
                                  decision: d,
                                  reason: decisionReason,
                                });
                              },
                              "已记录你的决定"
                            )
                          }
                        >
                          {d}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* 2 学习计划 */}
          <Card
            title="② 学习计划"
            desc="把目标拆成有顺序的阶段与步骤"
            actions={
              <Button
                variant="secondary"
                onClick={() => run("plan", async () => { await api.post(`/api/goals/${goalId}/plan`); }, "学习计划已生成")}
                disabled={busy === "plan"}
              >
                {busy === "plan" ? "生成中…" : plan ? "重新生成计划" : "生成学习计划"}
              </Button>
            }
          >
            {!plan ? (
              <Empty>尚未生成学习计划。</Empty>
            ) : (
              <ol className="grid gap-2">
                {plan.steps.map((s, i) => (
                  <li key={s.id} className="flex gap-3 rounded-xl border border-line p-3">
                    <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[11px] font-bold text-brand">
                      {i + 1}
                    </span>
                    <div>
                      <b className="text-[12px]">{s.title}</b>
                      <div className="mt-0.5 text-[11px] leading-relaxed text-muted">{s.objective}</div>
                      {s.estimated_effort && (
                        <div className="mt-1 text-[10px] text-[#99a2b3]">预计：{s.estimated_effort}</div>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          {/* 3 验收标准 */}
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
                    onClick={confirmAllCriteria}
                    disabled={busy === "confirm-all"}
                  >
                    {busy === "confirm-all" ? "确认中…" : `一键同意全部（${pendingCount}）`}
                  </Button>
                )}
                <Button
                  variant="secondary"
                  onClick={() => run("criteria", async () => { await api.post(`/api/goals/${goalId}/criteria`); }, "验收标准已生成")}
                  disabled={busy === "criteria"}
                >
                  {busy === "criteria" ? "生成中…" : "生成验收标准"}
                </Button>
              </div>
            }
          >
            {criteria.length === 0 ? (
              <Empty>尚未设计验收标准。</Empty>
            ) : (
              <div className="grid gap-2">
                {criteria.map((c) => (
                  <div key={c.id} className="rounded-xl border border-line p-3">
                    <div className="flex items-start justify-between gap-2">
                      <b className="text-[12px] leading-relaxed">{c.statement}</b>
                      <Badge tone={c.status === "confirmed" ? "done" : c.status === "rejected" ? "warn" : "neutral"}>
                        {c.status === "confirmed" ? "已确认" : c.status === "rejected" ? "已拒绝" : "待确认"}
                      </Badge>
                    </div>
                    {c.conditions && <div className="mt-1 text-[11px] text-muted">条件：{c.conditions}</div>}
                    {c.pass_rule && <div className="mt-0.5 text-[11px] text-muted">通过条件：{c.pass_rule}</div>}
                    <div className="mt-2 flex items-center gap-3 text-[11px]">
                      <button
                        className="font-semibold text-brand hover:underline disabled:opacity-40"
                        disabled={busy === `crit-${c.id}`}
                        onClick={() =>
                          run(
                            `crit-${c.id}`,
                            async () => {
                              await api.patch(`/api/criteria/${c.id}`, {
                                status: c.status === "confirmed" ? "pending" : "confirmed",
                              });
                            },
                            c.status === "confirmed" ? "已取消确认" : "已确认该标准"
                          )
                        }
                      >
                        {c.status === "confirmed" ? "取消确认" : "确认标准"}
                      </button>
                      <button
                        className="text-muted hover:text-[#c33]"
                        onClick={() => run(`del-${c.id}`, async () => { await api.del(`/api/criteria/${c.id}`); }, "已删除")}
                      >
                        删除
                      </button>
                      <span className="ml-auto text-[10px] text-[#99a2b3]">证据类型：{c.evidence_type}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* 4 教程 */}
          <Card
            title="④ 教程与资料"
            desc="一键生成会按顺序补齐：诊断 → 计划 → 验收标准（一键同意）→ 大纲 → 全部章节；每一步都可点进详情"
            actions={
              <div className="flex flex-wrap items-center justify-end gap-2">
                {usage && (
                  <Badge tone="neutral">累计 {fmtTokens(usage.totals.total_tokens)} tokens</Badge>
                )}
                {tutorial && (
                  <Badge tone={tutorial.current_version?.quality_report?.passed ? "done" : "warn"}>
                    v{tutorial.current_version?.version ?? 1} · 质量
                    {tutorial.current_version?.quality_report?.passed ? "通过" : "待改进"}
                  </Badge>
                )}
              </div>
            }
          >
            {quickSteps.length > 0 && <QuickStepsPanel steps={quickSteps} />}

            {!tutorial ? (
              <div className="grid gap-2">
                <div className="text-[12px] text-muted">
                  一键生成会自动生成并同意验收标准，不需要逐条点击。当前已确认 {confirmedCount} 条。
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={startQuickstart} disabled={busy === "quickstart" || !!gen}>
                    {busy === "quickstart" ? "一键生成中…" : "一键生成教材（推荐）"}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => run("outline", async () => { await api.post(`/api/goals/${goalId}/tutorials/generate`); }, "教程大纲已生成")}
                    disabled={busy === "outline" || confirmedCount === 0}
                  >
                    {busy === "outline" ? "生成中…" : "只生成大纲"}
                  </Button>
                  {confirmedCount === 0 && (
                    <span className="text-[11px] text-[#c47b12]">「只生成大纲」需先确认至少一条验收标准</span>
                  )}
                </div>
              </div>
            ) : (
              <div className="grid gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/tutorials/${tutorial.id}`}
                    className="rounded-[10px] bg-brand px-3.5 py-2 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
                  >
                    打开教程详情 →
                  </Link>
                  <Link
                    href={`/knowledge?goal=${goalId}`}
                    className="rounded-[10px] border border-line bg-white px-3.5 py-2 text-[12px] font-semibold text-[#39455d] hover:border-[#c9c3ff]"
                  >
                    在知识网络中查看本目标 →
                  </Link>
                  <Button
                    variant="secondary"
                    onClick={startQuickstart}
                    disabled={busy === "quickstart" || !!gen}
                  >
                    {busy === "quickstart" ? "补齐中…" : tutorial.current_version?.content.sections.length ? "一键补齐流程" : "一键生成全部章节"}
                  </Button>
                  {gen && (
                    <span className="text-[11px] text-brand">
                      {gen.stage}（{gen.progress}%）· 已用 {fmtTokens(gen.tokens)} tokens
                    </span>
                  )}
                </div>
                <TutorialView
                  tutorial={tutorial}
                  criteria={criteria}
                  usage={usage}
                  busy={busy}
                  gen={gen}
                  onGenerateSections={startSections}
                  onRegenerateSection={(sid) =>
                    run(
                      `regen-${sid}`,
                      async () => { await api.post(`/api/tutorials/${tutorial.id}/sections/${sid}/regenerate`); },
                      "章节已重新生成"
                    )
                  }
                />
              </div>
            )}
          </Card>
        </div>

        {/* 右列 */}
        <div className="grid gap-4">
          <GoalMaterialsCard goalId={goalId} />

          {/* 答疑 */}
          <Card title="上下文答疑" desc="基于当前目标与教程上下文的提问；优先提示，不直接代做">
            <div className="grid gap-2">
              {chatLog.length === 0 ? (
                <Empty>还没有提问。可以先问：「这一节的步骤为什么要这样拆？」</Empty>
              ) : (
                chatLog.map((m, i) => (
                  <div key={i} className="rounded-xl bg-[#f7f6ff] p-3 text-[11px] leading-relaxed">
                    <div className="font-semibold text-[#6255e8]">问：{m.q}</div>
                    <div className="mt-1 whitespace-pre-wrap">{m.a}</div>
                    {m.demo && <div className="mt-1 text-[10px] text-[#8a6411]">（演示模式）</div>}
                  </div>
                ))
              )}
              <div className="flex gap-2">
                <input
                  className={inputCls}
                  placeholder="针对当前目标提问…"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void ask();
                    }
                  }}
                />
                <Button
                  onClick={() => void ask()}
                  disabled={busy === "chat" || !chatInput.trim()}
                >
                  {busy === "chat" ? "…" : "提问"}
                </Button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );

  async function ask() {
    if (!chatInput.trim()) return;
    setBusy("chat");
    setError("");
    try {
      const resp = await api.post<ChatResponse>("/api/chat", {
        goal_id: goalId,
        tutorial_id: tutorial?.id,
        question: chatInput,
      });
      setChatLog([...chatLog, { q: chatInput, a: resp.assistant.content, demo: resp.demo }]);
      setChatInput("");
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  }
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

const QUICK_STATUS: Record<string, { label: string; cls: string }> = {
  created: { label: "已生成", cls: "text-[#128b78]" },
  reused: { label: "沿用", cls: "text-muted" },
  running: { label: "生成中", cls: "text-brand" },
};

function QuickStepsPanel({ steps }: { steps: QuickStartStep[] }) {
  return (
    <div className="mb-3 rounded-xl border border-line bg-[#fbfcff] p-3">
      <div className="mb-1.5 text-[11px] font-bold">一键生成流程</div>
      <ol className="grid gap-1">
        {steps.map((step, index) => {
          const status = QUICK_STATUS[step.status] ?? { label: step.status, cls: "text-muted" };
          return (
            <li key={step.key} className="flex flex-wrap items-start gap-x-2 text-[11px]">
              <span className="grid h-4 w-4 shrink-0 place-items-center rounded-full bg-[#f0edff] text-[9px] font-bold text-brand">
                {index + 1}
              </span>
              <span className="font-semibold text-[#33415c]">{step.label}</span>
              <span className={status.cls}>· {status.label}</span>
              {step.detail && <span className="text-muted">{step.detail}</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function TutorialView({
  tutorial,
  criteria,
  usage,
  busy,
  gen,
  onGenerateSections,
  onRegenerateSection,
}: {
  tutorial: Tutorial;
  criteria: Criterion[];
  usage: GoalUsage | null;
  busy: string;
  gen: { stage: string; progress: number; tokens: number } | null;
  onGenerateSections: () => void;
  onRegenerateSection: (sectionId: string) => void;
}) {
  const [exporting, setExporting] = useState(false);
  const [exportErr, setExportErr] = useState("");
  const version = tutorial.current_version;
  const content = version?.content;
  const outline = content?.outline ?? [];
  const sections = content?.sections ?? [];
  const report = version?.quality_report ?? {};
  const isDemo = version?.model_provider === "demo";

  return (
    <div className="grid gap-3">
      <DemoNotice show={!!isDemo}>教程由演示生成器产生，关键事实与命令需人工核验。</DemoNotice>

      {gen && (
        <div className="rounded-xl border border-[#c9c2ff] bg-[#f8f7ff] px-3 py-2 text-[11px] text-brand">
          生成中：{gen.stage}（{gen.progress}%）
          {gen.tokens ? ` · 已消耗 ${fmtTokens(gen.tokens)} tokens` : ""}
        </div>
      )}

      <TokenLine
        versionTokens={version?.token_usage}
        tutorialTokens={tutorial.tokens}
        goalTokens={usage?.totals}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          disabled={exporting || !version}
          onClick={async () => {
            setExporting(true);
            setExportErr("");
            try {
              await downloadFile(`/api/tutorials/${tutorial.id}/export`, `${tutorial.title || "tutorial"}.md`);
            } catch (e) {
              setExportErr(errMsg(e));
            } finally {
              setExporting(false);
            }
          }}
        >
          {exporting ? "导出中…" : "下载 Markdown 教程"}
        </Button>
        <Link href={`/tutorials/${tutorial.id}`} className="text-[11px] font-semibold text-brand hover:underline">
          完整教程详情 →
        </Link>
        {exportErr && <span className="text-[11px] text-[#a33]">{exportErr}</span>}
      </div>

      {/* 配套文件：知识速查 + 可选额外练习（与主教程用 Obsidian 双链关联） */}
      {((version?.content.cheatsheet?.sections?.length ?? 0) > 0 ||
        (version?.content.extra_exercises?.exercises?.length ?? 0) > 0) && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-[#f7f6ff] px-3 py-2 text-[11px]">
          <span className="font-bold text-[#5a6a86]">配套文件：</span>
          {version?.content.cheatsheet?.sections?.length ? (
            <button
              className="font-semibold text-brand hover:underline disabled:opacity-40"
              disabled={exporting}
              onClick={async () => {
                setExporting(true);
                setExportErr("");
                try {
                  const name = version.content.cheatsheet!.filename ?? "知识速查";
                  await downloadFile(`/api/tutorials/${tutorial.id}/export/cheatsheet`, `${name}.md`);
                } catch (e) {
                  setExportErr(errMsg(e));
                } finally {
                  setExporting(false);
                }
              }}
            >
              下载知识速查（{version.content.cheatsheet.sections.length} 节）
            </button>
          ) : null}
          {version?.content.extra_exercises?.exercises?.length ? (
            <button
              className="font-semibold text-brand hover:underline disabled:opacity-40"
              disabled={exporting}
              onClick={async () => {
                setExporting(true);
                setExportErr("");
                try {
                  const name = version.content.extra_exercises!.filename ?? "额外练习";
                  await downloadFile(`/api/tutorials/${tutorial.id}/export/exercises`, `${name}.md`);
                } catch (e) {
                  setExportErr(errMsg(e));
                } finally {
                  setExporting(false);
                }
              }}
            >
              下载额外练习（{version.content.extra_exercises.exercises.length} 题，含参考答案）
            </button>
          ) : null}
          <span className="text-[10px] text-muted">导出后与主教程放同一文件夹，双链自动生效</span>
        </div>
      )}

      <div>
        <div className="mb-1.5 text-[11px] font-bold text-[#5a6a86]">
          大纲（{outline.length} 节）· 点击任意一步进入详情
        </div>
        <OutlineList tutorialId={tutorial.id} outline={outline} sections={sections} />
      </div>

      {sections.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={onGenerateSections} disabled={busy === "sections"}>
            {busy === "sections" ? "生成中…" : "生成全部章节并执行质量检查"}
          </Button>
          <span className="text-[11px] text-muted">
            如需连同诊断 / 计划 / 标准一起补齐，请使用上方「一键生成」。
          </span>
        </div>
      ) : (
        <div className="grid gap-3">
          {sections.map((s, i) => (
            <div key={s.id} className="rounded-xl border border-line p-3">
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/tutorials/${tutorial.id}/sections/${s.id}`}
                  className="text-[13px] font-bold hover:text-brand"
                >
                  {i + 1}. {s.title}
                </Link>
                <div className="flex shrink-0 items-center gap-3">
                  <Link
                    href={`/tutorials/${tutorial.id}/sections/${s.id}`}
                    className="text-[10px] font-semibold text-brand hover:underline"
                  >
                    查看详情 →
                  </Link>
                  <button
                    className="text-[10px] font-semibold text-brand hover:underline disabled:opacity-40"
                    disabled={busy === `regen-${s.id}`}
                    onClick={() => onRegenerateSection(s.id)}
                  >
                    {busy === `regen-${s.id}` ? "重生成中…" : "重新生成本节"}
                  </button>
                </div>
              </div>
              <div className="mt-2">
                <SectionContent section={s} criteria={criteria} />
              </div>
              {s.token_usage && (
                <div className="mt-2 text-[10px] text-[#99a2b3]">
                  本节 token：{fmtTokens(s.token_usage.total_tokens)}（
                  {usageSourceLabel(s.token_usage.usage_source)}）
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {version && (
        <div className="rounded-xl border border-line bg-[#fafbfc] p-3 text-[11px]">
          <div className="mb-1 font-bold">
            质量报告
            <Badge tone={report.passed ? "done" : "warn"}>{report.passed ? "通过" : "待改进"}</Badge>
            <span className="ml-2 text-[10px] font-normal text-muted">
              v{version.version} · {version.model_provider} · {version.created_at}
            </span>
          </div>
          <ul className="grid gap-0.5">
            {(report.checks ?? []).map((c, i) => (
              <li key={i} className={c.passed ? "text-[#128b78]" : "text-[#a33]"}>
                {c.passed ? "✓" : "✗"} {c.name}
                <span className="text-muted"> — {c.detail}</span>
              </li>
            ))}
          </ul>
          {report.issues && report.issues.length > 0 && (
            <ul className="mt-1 grid gap-0.5 text-[#a33]">
              {report.issues.map((x, i) => (
                <li key={i}>· {x}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <FeedbackForm
        goalId={tutorial.goal_id}
        tutorialId={tutorial.id}
        targetType="tutorial"
        title="这套教程对你有帮助吗？"
      />
    </div>
  );
}
