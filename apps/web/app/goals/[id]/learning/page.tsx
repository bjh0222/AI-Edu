"use client";

import Link from "next/link";
import { useState } from "react";
import { api, downloadFile } from "@/lib/api";
import type {
  ChatResponse,
  GenerationJob,
  QuickStartResult,
  QuickStartStep,
  TokenUsage,
  Tutorial,
} from "@/lib/types";
import { fmtTokens, usageSourceLabel } from "@/lib/format";
import { phase } from "@/lib/goal-phases";
import { OutlineList, SectionContent, TokenLine } from "@/components/tutorial";
import { FeedbackForm } from "@/components/FeedbackForm";
import { Badge, Button, Card, DemoNotice, Empty, inputCls } from "@/components/ui";
import { GoalPhaseView } from "@/components/goals/GoalPhaseView";
import { errMsg, type WorkspaceSlices } from "@/components/goals/useGoalWorkspace";

const PHASE = phase("learning");
const SLICES: WorkspaceSlices = { tutorials: true, criteria: true, usage: true, materials: true };

const QUICK_STATUS: Record<string, { label: string; cls: string }> = {
  created: { label: "已生成", cls: "text-[#128b78]" },
  reused: { label: "沿用", cls: "text-muted" },
  running: { label: "生成中", cls: "text-brand" },
};

export default function LearningPage() {
  // 局部状态放在页面组件里（而不是渲染回调内），避免在 render prop 里调用 Hook
  const [steps, setSteps] = useState<QuickStartStep[]>([]);
  const [gen, setGen] = useState<{ stage: string; progress: number; tokens: number } | null>(null);

  return (
    <GoalPhaseView phase={PHASE} slices={SLICES}>
      {({ goalId, data, run, busy, setBusy, setError, setNotice, reload }) => {
        const tutorial = data.tutorials[0] ?? null;
        const confirmedCount = data.criteria.filter((item) => item.status === "confirmed").length;

        const pollJob = (jobId: string) => {
          const tick = async () => {
            try {
              const job = await api.get<GenerationJob>(`/api/generation-jobs/${jobId}`);
              setGen({ stage: job.stage, progress: job.progress, tokens: job.token_usage?.total_tokens ?? 0 });
              if (job.status === "done") {
                setGen(null);
                setBusy("");
                await reload();
                setNotice(
                  `教程章节已生成，质量检查完成${
                    job.token_usage?.total_tokens
                      ? ` · 本次消耗 ${fmtTokens(job.token_usage.total_tokens)} tokens`
                      : ""
                  }`
                );
              } else if (job.status === "failed") {
                setGen(null);
                setBusy("");
                setError(
                  `章节生成失败（${job.error_code || "unknown"}）${job.error_message ? `：${job.error_message}` : "，请检查模型配置后重试"}`
                );
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

        const startQuickstart = async () => {
          if (busy) return;
          setBusy("quickstart");
          setError("");
          setNotice("");
          setSteps([]);
          try {
            const resp = await api.post<QuickStartResult>(`/api/goals/${goalId}/tutorials/quickstart`);
            setSteps(resp.steps);
            await reload();
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

        const startSections = async (target: Tutorial) => {
          setBusy("sections");
          setError("");
          setNotice("");
          try {
            const resp = await api.post<{ job_id: string }>(`/api/tutorials/${target.id}/sections/generate`);
            setGen({ stage: "已提交，等待模型返回…", progress: 0, tokens: 0 });
            pollJob(resp.job_id);
          } catch (e) {
            setBusy("");
            setError(errMsg(e));
          }
        };

        return (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <div className="grid gap-4">
              <Card
                title="④ 教程与资料"
                desc="一键生成会按顺序补齐：诊断 → 计划 → 验收标准（一键同意）→ 大纲 → 全部章节"
                actions={
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {data.usage && (
                      <Badge tone="neutral">累计 {fmtTokens(data.usage.totals.total_tokens)} tokens</Badge>
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
                {steps.length > 0 && <QuickStepsPanel steps={steps} />}
                {gen && (
                  <div className="mb-3 rounded-xl border border-[#c9c2ff] bg-[#f8f7ff] px-3 py-2 text-[11px] text-brand">
                    生成中：{gen.stage}（{gen.progress}%）
                    {gen.tokens ? ` · 已消耗 ${fmtTokens(gen.tokens)} tokens` : ""}
                  </div>
                )}

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
                        onClick={() =>
                          run(
                            "outline",
                            async () => {
                              await api.post(`/api/goals/${goalId}/tutorials/generate`);
                            },
                            "教程大纲已生成"
                          )
                        }
                        disabled={busy === "outline" || confirmedCount === 0}
                      >
                        {busy === "outline" ? "生成中…" : "只生成大纲"}
                      </Button>
                      {confirmedCount === 0 && (
                        <span className="text-[11px] text-[#c47b12]">
                          「只生成大纲」需先确认至少一条验收标准
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <TutorialPanel
                    tutorial={tutorial}
                    goalTokens={data.usage?.totals}
                    busy={busy}
                    knowledgeHref={`/knowledge?goal=${goalId}`}
                    onStartSections={() => startSections(tutorial)}
                    onRegenerate={(sectionId) =>
                      run(
                        `regen-${sectionId}`,
                        async () => {
                          await api.post(`/api/tutorials/${tutorial.id}/sections/${sectionId}/regenerate`);
                        },
                        "章节已重新生成"
                      )
                    }
                    onQuickstart={startQuickstart}
                  />
                )}
              </Card>

              <ChatPanel goalId={goalId} tutorialId={tutorial?.id} />
            </div>

            <div className="grid gap-4">
              <Card title="注入生成的材料" desc="教程大纲与每一节都会带上这些材料的摘录作为依据">
                {data.materials.length === 0 ? (
                  <Empty>没有上传材料。到「价值诊断」页上传讲义或例题来源。</Empty>
                ) : (
                  <ul className="grid gap-1.5 text-[11px]">
                    {data.materials.map((material) => (
                      <li key={material.id} className="flex flex-wrap items-center gap-1.5">
                        <Badge tone={material.kind === "example_source" ? "warn" : "active"}>
                          {material.kind === "example_source" ? "例题来源" : "参考资料"}
                        </Badge>
                        <span className="truncate font-semibold text-[#33415c]">{material.filename}</span>
                        <span className="text-[10px] text-muted">
                          {material.extract_status === "ok" ? `${material.char_count} 字摘录` : "未抽取正文"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-2 border-t border-line pt-2 text-[10px] text-muted">
                  <Link href={`/goals/${goalId}/diagnosis`} className="font-semibold text-brand hover:underline">
                    去上传 / 管理材料 →
                  </Link>
                </div>
              </Card>

              <Card title="学习反馈" desc="测试版：反馈会持久化，并随训练数据一起导出">
                {tutorial ? (
                  <FeedbackForm
                    goalId={tutorial.goal_id}
                    tutorialId={tutorial.id}
                    targetType="tutorial"
                    title="这套教程对你有帮助吗？"
                  />
                ) : (
                  <Empty>生成教程后可以提交反馈。</Empty>
                )}
              </Card>
            </div>
          </div>
        );
      }}
    </GoalPhaseView>
  );
}

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

function TutorialPanel({
  tutorial,
  goalTokens,
  busy,
  knowledgeHref,
  onStartSections,
  onRegenerate,
  onQuickstart,
}: {
  tutorial: Tutorial;
  goalTokens?: TokenUsage;
  busy: string;
  knowledgeHref?: string;
  onStartSections: () => void;
  onRegenerate: (sectionId: string) => void;
  onQuickstart: () => void;
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

      <TokenLine versionTokens={version?.token_usage} tutorialTokens={tutorial.tokens} goalTokens={goalTokens} />

      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/tutorials/${tutorial.id}`}
          className="rounded-[10px] bg-brand px-3.5 py-2 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
        >
          打开教程详情 →
        </Link>
        {knowledgeHref && (
          <Link
            href={knowledgeHref}
            className="rounded-[10px] border border-line bg-white px-3.5 py-2 text-[12px] font-semibold text-[#39455d] hover:border-[#c9c3ff]"
          >
            在知识网络中查看 →
          </Link>
        )}
        <Button variant="secondary" onClick={onQuickstart} disabled={busy === "quickstart"}>
          {sections.length > 0 ? "一键补齐流程" : "一键生成全部章节"}
        </Button>
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
          <Button onClick={onStartSections} disabled={busy === "sections"}>
            {busy === "sections" ? "生成中…" : "生成全部章节并执行质量检查"}
          </Button>
          <span className="text-[11px] text-muted">
            如需连同诊断 / 计划 / 标准一起补齐，请使用上方「一键生成」。
          </span>
        </div>
      ) : (
        <div className="grid gap-3">
          {sections.map((section, index) => (
            <div key={section.id} className="rounded-xl border border-line p-3">
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/tutorials/${tutorial.id}/sections/${section.id}`}
                  className="text-[13px] font-bold hover:text-brand"
                >
                  {index + 1}. {section.title}
                </Link>
                <div className="flex shrink-0 items-center gap-3">
                  <Link
                    href={`/tutorials/${tutorial.id}/sections/${section.id}`}
                    className="text-[10px] font-semibold text-brand hover:underline"
                  >
                    查看详情 →
                  </Link>
                  <button
                    className="text-[10px] font-semibold text-brand hover:underline disabled:opacity-40"
                    disabled={busy === `regen-${section.id}`}
                    onClick={() => onRegenerate(section.id)}
                  >
                    {busy === `regen-${section.id}` ? "重生成中…" : "重新生成本节"}
                  </button>
                </div>
              </div>
              <div className="mt-2">
                <SectionContent section={section} criteria={[]} />
              </div>
              {section.token_usage && (
                <div className="mt-2 text-[10px] text-[#99a2b3]">
                  本节 token：{fmtTokens(section.token_usage.total_tokens)}（
                  {usageSourceLabel(section.token_usage.usage_source)}）
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
            {(report.checks ?? []).map((check, index) => (
              <li key={index} className={check.passed ? "text-[#128b78]" : "text-[#a33]"}>
                {check.passed ? "✓" : "✗"} {check.name}
                <span className="text-muted"> — {check.detail}</span>
              </li>
            ))}
          </ul>
          {report.issues && report.issues.length > 0 && (
            <ul className="mt-1 grid gap-0.5 text-[#a33]">
              {report.issues.map((issue, index) => (
                <li key={index}>· {issue}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ChatPanel({ goalId, tutorialId }: { goalId: string; tutorialId?: string }) {
  const [log, setLog] = useState<{ q: string; a: string; demo: boolean }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const ask = async () => {
    if (!input.trim()) return;
    setBusy(true);
    setError("");
    try {
      const resp = await api.post<ChatResponse>("/api/chat", {
        goal_id: goalId,
        tutorial_id: tutorialId,
        question: input,
      });
      setLog([...log, { q: input, a: resp.assistant.content, demo: resp.demo }]);
      setInput("");
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="上下文答疑" desc="基于当前目标与教程上下文的提问；优先提示，不直接代做">
      <div className="grid gap-2">
        {log.length === 0 ? (
          <Empty>还没有提问。可以先问：「这一节的步骤为什么要这样拆？」</Empty>
        ) : (
          log.map((message, index) => (
            <div key={index} className="rounded-xl bg-[#f7f6ff] p-3 text-[11px] leading-relaxed">
              <div className="font-semibold text-[#6255e8]">问：{message.q}</div>
              <div className="mt-1 whitespace-pre-wrap">{message.a}</div>
              {message.demo && <div className="mt-1 text-[10px] text-[#8a6411]">（演示模式）</div>}
            </div>
          ))
        )}
        <div className="flex gap-2">
          <input
            className={inputCls}
            placeholder="针对当前目标提问…"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void ask();
              }
            }}
          />
          <Button onClick={() => void ask()} disabled={busy || !input.trim()}>
            {busy ? "…" : "提问"}
          </Button>
        </div>
        {error && <span className="text-[11px] text-[#a33]">{error}</span>}
      </div>
    </Card>
  );
}
