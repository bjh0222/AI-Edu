"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ApiError, downloadFile } from "@/lib/api";
import type {
  Assessment,
  Attempt,
  ChatResponse,
  Criterion,
  GenerationJob,
  Goal,
  GoalAssessment,
  GoalUsage,
  Knowledge,
  Plan,
  Proposal,
  QuickStartResult,
  QuickStartStep,
  Reflection,
  Task,
  Tutorial,
} from "@/lib/types";
import { fmtTokens, usageSourceLabel } from "@/lib/format";
import { OutlineList, SectionContent, TokenLine } from "@/components/tutorial";
import { FeedbackForm } from "@/components/FeedbackForm";
import { Badge, Button, Card, DemoNotice, Empty, inputCls } from "@/components/ui";

const PHASES: { key: string; label: string }[] = [
  { key: "goal_definition", label: "目标定义" },
  { key: "diagnosis", label: "价值诊断" },
  { key: "planning", label: "学习计划" },
  { key: "acceptance_design", label: "验收标准" },
  { key: "learning", label: "教程学习" },
  { key: "practice", label: "实践" },
  { key: "feedback", label: "反馈" },
  { key: "assessment", label: "能力评估" },
  { key: "reflection", label: "复盘" },
  { key: "knowledge_update", label: "知识记录" },
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
  const [tasks, setTasks] = useState<Task[]>([]);
  const [attempts, setAttempts] = useState<Record<string, Attempt[]>>({});
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [reflections, setReflections] = useState<Reflection[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
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

  const loadAll = useCallback(async () => {
    const [g, d, p, c, ts, tk, as, rf, kn, u] = await Promise.all([
      api.get<Goal>(`/api/goals/${goalId}`),
      api.get<GoalAssessment | null>(`/api/goals/${goalId}/diagnose`).catch(() => null),
      api.get<Plan | null>(`/api/goals/${goalId}/plan`).catch(() => null),
      api.get<Criterion[]>(`/api/goals/${goalId}/criteria`).catch(() => []),
      api.get<Tutorial[]>(`/api/goals/${goalId}/tutorials`).catch(() => []),
      api.get<Task[]>(`/api/goals/${goalId}/tasks`).catch(() => []),
      api.get<Assessment[]>(`/api/goals/${goalId}/assessments`).catch(() => []),
      api.get<Reflection[]>(`/api/goals/${goalId}/reflections`).catch(() => []),
      api.get<Knowledge>("/api/knowledge").catch(() => ({ concepts: [], relations: [], proposals: [] })),
      api.get<GoalUsage>(`/api/goals/${goalId}/usage`).catch(() => null),
    ]);
    setGoal(g);
    setDiagnosis(d);
    setPlan(p);
    setCriteria(c);
    setTutorials(ts);
    setTasks(tk);
    setAssessments(as);
    setReflections(rf);
    setProposals(kn.proposals.filter((x) => x.status === "pending"));
    setUsage(u);

    const pairs = await Promise.all(
      tk.map(async (t) => [t.id, await api.get<Attempt[]>(`/api/tasks/${t.id}/attempts`).catch(() => [])] as const)
    );
    setAttempts(Object.fromEntries(pairs));
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
    const tick = async () => {
      try {
        const job = await api.get<GenerationJob>(`/api/generation-jobs/${jobId}`);
        setGen({
          stage: job.stage,
          progress: job.progress,
          tokens: job.token_usage?.total_tokens ?? 0,
        });
        if (job.status === "done") {
          setGen(null);
          setBusy("");
          await loadAll();
          setNotice(
            `教程章节已生成，质量检查完成${job.token_usage?.total_tokens ? ` · 本次消耗 ${fmtTokens(job.token_usage.total_tokens)} tokens` : ""}`
          );
        } else if (job.status === "failed") {
          setGen(null);
          setBusy("");
          setError(`章节生成失败（${job.error_code || "unknown"}），请检查模型配置后重试`);
        } else {
          setTimeout(tick, 2000);
        }
      } catch (e) {
        setGen(null);
        setBusy("");
        setError(errMsg(e));
      }
    };
    setTimeout(tick, 1500);
  };

  const startSections = async () => {
    if (!tutorial) return;
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
        setGen({ stage: "一键生成已提交，正在生成全部章节…", progress: 0, tokens: 0 });
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
          <div
            key={p.key}
            className={`rounded-lg border px-2.5 py-1.5 text-[10px] ${
              i <= phaseIdx
                ? "border-[#c9c2ff] bg-[#f8f7ff] font-bold text-brand"
                : "border-line bg-white text-muted"
            }`}
          >
            {String(i + 1).padStart(2, "0")} {p.label}
          </div>
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

          {/* 5 实践任务 */}
          <Card title="⑤ 实践任务" desc="每个任务都要有产物、验证方式与辅助等级记录">
            {tasks.length === 0 ? (
              <Empty>暂无任务。生成教程章节后会自动创建一个实践任务。</Empty>
            ) : (
              <div className="grid gap-2.5">
                {tasks.map((t) => (
                  <TaskItem
                    key={t.id}
                    task={t}
                    attempts={attempts[t.id] ?? []}
                    onSubmitted={loadAll}
                    onError={(m) => setError(m)}
                  />
                ))}
              </div>
            )}
          </Card>

          {/* 6 能力评估 */}
          <Card
            title="⑥ 能力评估"
            desc="独立任务 + 变式任务，检查能否不依赖教程完成"
            actions={
              <Button
                variant="secondary"
                onClick={() =>
                  run(
                    "assessment",
                    async () => { await api.post(`/api/goals/${goalId}/assessments`, { assessment_type: "mixed" }); },
                    "评估方案已生成"
                  )
                }
                disabled={busy === "assessment"}
              >
                {busy === "assessment" ? "生成中…" : "生成评估方案"}
              </Button>
            }
          >
            {assessments.length === 0 ? (
              <Empty>尚未生成评估方案。</Empty>
            ) : (
              <div className="grid gap-2">
                {assessments.map((a) => (
                  <AssessmentItem key={a.id} assessment={a} onSaved={loadAll} onError={(m) => setError(m)} />
                ))}
              </div>
            )}
          </Card>

          {/* 7 复盘 */}
          <Card
            title="⑦ 学习复盘"
            desc="记录完成了什么、仍依赖 AI 的地方、下一步最值得做的事"
            actions={
              <Button
                variant="secondary"
                onClick={() => run("reflection", async () => { await api.post(`/api/goals/${goalId}/reflections`, {}); }, "复盘草稿已生成")}
                disabled={busy === "reflection"}
              >
                {busy === "reflection" ? "生成中…" : "生成复盘草稿"}
              </Button>
            }
          >
            {reflections.length === 0 ? (
              <Empty>尚无复盘记录。</Empty>
            ) : (
              <div className="grid gap-2">
                {reflections.map((r) => (
                  <div key={r.id} className="rounded-xl border border-line p-3 text-[12px] leading-relaxed">
                    <div className="mb-1 text-[10px] text-muted">{r.created_at}</div>
                    <div>{r.summary}</div>
                    <div className="mt-1.5 grid gap-1 text-[11px] text-muted">
                      <div>已形成的能力：{r.learned_capabilities}</div>
                      <div>待解决：{r.unresolved_gaps}</div>
                      <div>下一步：{r.next_actions}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* 右列 */}
        <div className="grid gap-4">
          <Card
            title="知识提议"
            desc="AI 只能提议，确认后才入长期知识网络"
            actions={
              <Button
                variant="secondary"
                onClick={() =>
                  run(
                    "proposals",
                    async () => { await api.post(`/api/goals/${goalId}/knowledge-proposals`); },
                    "知识提议已生成，请逐条确认"
                  )
                }
                disabled={busy === "proposals"}
              >
                {busy === "proposals" ? "生成中…" : "生成知识提议"}
              </Button>
            }
          >
            {proposals.length === 0 ? (
              <Empty>暂无待处理提议。</Empty>
            ) : (
              <div className="grid gap-2">
                {proposals.map((p) => (
                  <div key={p.id} className="rounded-xl border border-line p-3 text-[11px] leading-relaxed">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge tone="warn">{p.proposal_type === "relation" ? "关系" : "概念"}</Badge>
                    </div>
                    <div className="font-semibold">{proposalText(p)}</div>
                    {p.rationale && <div className="mt-1 text-muted">依据：{p.rationale}</div>}
                    <div className="mt-2 flex gap-2">
                      <Button
                        variant="secondary"
                        disabled={busy === `p-${p.id}`}
                        onClick={() =>
                          run(`p-${p.id}`, async () => { await api.post(`/api/knowledge/proposals/${p.id}/review`, { action: "confirm" }); }, "已确认该提议")
                        }
                      >
                        确认
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={busy === `p-${p.id}`}
                        onClick={() =>
                          run(`p-${p.id}`, async () => { await api.post(`/api/knowledge/proposals/${p.id}/review`, { action: "reject" }); }, "已拒绝该提议")
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

function proposalText(p: Proposal): string {
  const payload = p.payload as Record<string, unknown>;
  if (payload.title) {
    return `新概念：${String(payload.title)}`;
  }
  if (payload.from_title && payload.to_title) {
    return `新关系：${String(payload.from_title)} —${String(payload.relation_type ?? "related")}→ ${String(payload.to_title)}`;
  }
  return JSON.stringify(payload);
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

function TaskItem({
  task,
  attempts,
  onSubmitted,
  onError,
}: {
  task: Task;
  attempts: Attempt[];
  onSubmitted: () => Promise<void> | void;
  onError: (m: string) => void;
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
          onChange={(e) => setArtifact(e.target.value)}
        />
        <div className="grid gap-2 sm:grid-cols-2">
          <select className={inputCls} value={helpLevel} onChange={(e) => setHelpLevel(e.target.value)}>
            <option value="A0">A0 引导（完整步骤）</option>
            <option value="A1">A1 协作</option>
            <option value="A2">A2 提示</option>
            <option value="A3">A3 独立验证</option>
          </select>
          <input
            className={inputCls}
            placeholder="遇到的错误（可选）"
            value={errorsText}
            onChange={(e) => setErrorsText(e.target.value)}
          />
        </div>
        <input
          className={inputCls}
          placeholder="你的解释：为什么这样做（可选）"
          value={explanation}
          onChange={(e) => setExplanation(e.target.value)}
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
          {attempts.map((a) => (
            <div key={a.id} className="rounded-xl border border-[#e7e3ff] bg-[#faf9ff] p-3 text-[11px] leading-relaxed">
              <div className="flex items-center gap-2">
                <Badge>尝试 · {a.help_level}</Badge>
                <span className="text-[10px] text-muted">{a.created_at}</span>
              </div>
              <div className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-[#33415c]">{a.artifact}</div>
              {a.feedback?.summary && <div className="mt-1 text-muted">反馈：{a.feedback.summary}</div>}
              {a.feedback?.items && a.feedback.items.length > 0 && (
                <ul className="mt-1 grid gap-1">
                  {a.feedback.items.map((f, i) => (
                    <li key={i} className="rounded-lg bg-white p-2">
                      <div className="flex items-center gap-1.5">
                        <Badge tone={f.status === "satisfied" ? "done" : f.status === "unclear" ? "warn" : "neutral"}>
                          {f.status === "satisfied" ? "满足" : f.status === "unsatisfied" ? "未满足" : "待确认"}
                        </Badge>
                        <span className="font-semibold">{f.statement || "（标准）"}</span>
                      </div>
                      {f.evidence && <div className="mt-0.5 text-muted">证据：{f.evidence}</div>}
                      {f.reason && <div className="text-muted">判断：{f.reason}</div>}
                      {f.next_action && <div className="text-[#6255e8]">下一步：{f.next_action}</div>}
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

function AssessmentItem({
  assessment,
  onSaved,
  onError,
}: {
  assessment: Assessment;
  onSaved: () => Promise<void> | void;
  onError: (m: string) => void;
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
      <div className="flex items-center gap-2">
        <Badge tone="active">{assessment.assessment_type}</Badge>
        <span className="text-[10px] text-muted">{assessment.created_at}</span>
      </div>
      {assessment.rubric.length > 0 && (
        <div className="mt-1.5 grid gap-0.5">
          {assessment.rubric.map((r, i) => (
            <div key={i} className="text-muted">
              · {r.dimension}（权重 {r.weight}）
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
      <div className="mt-2 grid gap-1.5">
        <input
          className={inputCls}
          placeholder="评估结果（如：独立完成 3/4 项，迁移任务未通过）"
          value={result}
          onChange={(e) => setResult(e.target.value)}
        />
        <input
          className={inputCls}
          placeholder="薄弱点"
          value={weak}
          onChange={(e) => setWeak(e.target.value)}
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
