"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ApiError, downloadFile } from "@/lib/api";
import type { Criterion, Goal, GoalUsage, Tutorial } from "@/lib/types";
import { featureLabel, fmtTokens, usageSourceLabel } from "@/lib/format";
import { OutlineList, SectionContent, TeachingPlanNotice, TokenLine } from "@/components/tutorial";
import { continueAllSections, clearOutlineOnlyGoal, outlineOnlyChosen, outlineOnlyRecently, markAutoResumeTried, autoResumeTried, clearAutoResumeTried } from "@/lib/tutorial-continue";
import { FeedbackForm } from "@/components/FeedbackForm";
import { Badge, Button, Card, DemoNotice, Empty } from "@/components/ui";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function TutorialPage() {
  return (
    <Suspense
      fallback={<div className="mx-auto max-w-[900px] px-6 py-10 text-[13px] text-muted">加载中…</div>}
    >
      <TutorialDetail />
    </Suspense>
  );
}

function TutorialDetail() {
  const params = useParams<{ tid: string }>();
  const tutorialId = params.tid;

  const [tutorial, setTutorial] = useState<Tutorial | null>(null);
  const [goal, setGoal] = useState<Goal | null>(null);
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [usage, setUsage] = useState<GoalUsage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState(false);

  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    const tutorialData = await api.get<Tutorial>(`/api/tutorials/${tutorialId}`);
    if (seq !== loadSeq.current) return; // 有更新的请求在飞，丢弃这次结果，避免旧数据覆盖新数据
    setTutorial(tutorialData);
    const [goalData, criteriaData, usageData] = await Promise.all([
      api.get<Goal>(`/api/goals/${tutorialData.goal_id}`).catch(() => null),
      api.get<Criterion[]>(`/api/goals/${tutorialData.goal_id}/criteria`).catch(() => []),
      api.get<GoalUsage>(`/api/goals/${tutorialData.goal_id}/usage`).catch(() => null),
    ]);
    if (seq !== loadSeq.current) return;
    setGoal(goalData);
    setCriteria(criteriaData);
    setUsage(usageData);
  }, [tutorialId]);

  useEffect(() => {
    // 首次进入按 URL 拉取教程。setState 在异步 load() 内部、不在 effect 同步体里，无需抑制规则。
    load().catch((e) => setError(errMsg(e)));
  }, [load]);

  // 章节还在后台生成时自动刷新：否则从「一键生成」直接跳进来会一直停在「0 节」，
  // 用户只能手动刷新（状态卡死）。刷新有上限，避免任务失败后无限请求。
  const outlineCount = tutorial?.current_version?.content?.outline?.length ?? 0;
  const sectionCount = tutorial?.current_version?.content?.sections?.length ?? 0;
  const sectionsPending = !!tutorial && outlineCount > sectionCount;

  useEffect(() => {
    if (!sectionsPending) return;
    let ticks = 0;
    const timer = setInterval(() => {
      ticks += 1;
      if (ticks > 60) {
        clearInterval(timer); // 约 4 分钟仍无进展就停手，由用户手动刷新
        return;
      }
      void load().catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [sectionsPending, sectionCount, load]);

  // 一键生成默认不停在大纲：新大纲还没有章节时，进入本页自动续跑全部章节
  // （每次挂载最多触发一次；后端对重复提交幂等——已有进行中的章节任务会直接复用）。
  const autoResumed = useRef(false);
  useEffect(() => {
    if (autoResumed.current || busy || !tutorial) return;
    if (!outlineOnlyRecently(tutorial)) return;
    // 用户主动选过「只生成大纲」时不自动续跑，尊重他的选择
    if (outlineOnlyChosen(tutorial.goal_id)) return;
    // 已经自动续跑过一次就不再重复：章节任务失败时本页仍只有大纲，无限重试会反复烧钱
    if (autoResumeTried(tutorial.goal_id)) return;
    // 推迟到本轮渲染结束后再改状态、提交任务，避免 effect 内同步 setState 触发级联渲染
    const timer = setTimeout(() => {
      autoResumed.current = true;
      setNotice("教程章节正在生成中，完成后本页会自动刷新…");
      continueAllSections(tutorialId)
        .then(() => load())
        .catch((e) => setError(errMsg(e)));
      markAutoResumeTried(tutorial.goal_id);
    }, 0);
    return () => clearTimeout(timer);
  }, [tutorial, busy, tutorialId, load]);

  // 空状态下的默认动作：不跳回学习目标页，直接在本页一键生成全部章节
  const startAllSections = () => {
    setBusy("sections");
    setError("");
    setNotice("");
    if (tutorial) {
      clearOutlineOnlyGoal(tutorial.goal_id); // 明确要全部章节
      clearAutoResumeTried(tutorial.goal_id); // 显式重试后重新允许自动续跑
    }
    continueAllSections(tutorialId)
      .then(() => {
        setNotice("已提交全部章节生成任务，生成完成后本页会自动刷新。");
        return load();
      })
      .catch((e) => setError(errMsg(e)))
      .finally(() => setBusy(""));
  };

  const run = async (key: string, fn: () => Promise<void>, msg = "完成") => {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await fn();
      await load();
      setNotice(msg);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  if (error && !tutorial) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-10">
        <div className="mb-3 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
        <Link href="/goals" className="text-[12px] font-semibold text-brand hover:underline">
          ← 返回学习目标
        </Link>
      </div>
    );
  }

  if (!tutorial) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-10">
        <div className="text-[13px] text-muted">加载中…</div>
      </div>
    );
  }

  const version = tutorial.current_version;
  const content = version?.content;
  const formatSpec = content?.format_spec;
  const outline = content?.outline ?? [];
  const sections = content?.sections ?? [];
  const cheatsheet = content?.cheatsheet ?? null;
  const extraExercises = content?.extra_exercises ?? null;
  const report = version?.quality_report ?? {};
  const isDemo = version?.model_provider === "demo";

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-5">
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
          <Link href="/goals" className="hover:text-brand">
            学习目标
          </Link>
          <span>/</span>
          {goal ? (
            <Link href={`/goals/${goal.id}`} className="hover:text-brand">
              {goal.title}
            </Link>
          ) : (
            <span>目标</span>
          )}
          <span>/</span>
          <span className="text-ink">教程详情</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-bold tracking-tight">{tutorial.title}</h1>
          <Badge tone="active">v{version?.version ?? 1}</Badge>
          {formatSpec?.name && (
            <Badge tone={formatSpec.scene === "exam_paper" ? "warn" : "neutral"}>
              {formatSpec.name} · {formatSpec.scene === "exam_paper" ? "试卷规范" : "格式规范"}
            </Badge>
          )}
          <Badge tone={report.passed ? "done" : "warn"}>
            质量{report.passed ? "通过" : "待改进"}
          </Badge>
          <Badge tone={tutorial.delivery_status === "delivered" ? "done" : "neutral"}>
            {tutorial.delivery_status === "delivered" ? "Obsidian 已交付" : "未交付"}
          </Badge>
          <Badge>累计 {fmtTokens(tutorial.tokens?.total_tokens)} tokens</Badge>
        </div>
        <p className="mt-1 text-[12px] text-muted">
          {sections.length} 节已生成 · 历史 {tutorial.history_count} 个版本 ·{" "}
          {usageSourceLabel(tutorial.tokens?.usage_source)}
        </p>
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

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="grid gap-4">
          <Card
            title="大纲与章节"
            desc="每一节都有独立详情页：可单独打开、重新生成，也可回到学习目标继续闭环"
            actions={
              <div className="flex flex-wrap items-center gap-2">
                {cheatsheet?.sections?.length ? (
                  <Button
                    variant="secondary"
                    disabled={exporting}
                    onClick={async () => {
                      setExporting(true);
                      setError("");
                      try {
                        await downloadFile(
                          `/api/tutorials/${tutorial.id}/export/cheatsheet`,
                          `${cheatsheet.filename ?? "知识速查"}.md`
                        );
                      } catch (e) {
                        setError(errMsg(e));
                      } finally {
                        setExporting(false);
                      }
                    }}
                  >
                    下载知识速查
                  </Button>
                ) : null}
                {extraExercises?.exercises?.length ? (
                  <Button
                    variant="secondary"
                    disabled={exporting}
                    onClick={async () => {
                      setExporting(true);
                      setError("");
                      try {
                        await downloadFile(
                          `/api/tutorials/${tutorial.id}/export/exercises`,
                          `${extraExercises.filename ?? "额外练习"}.md`
                        );
                      } catch (e) {
                        setError(errMsg(e));
                      } finally {
                        setExporting(false);
                      }
                    }}
                  >
                    下载额外练习
                  </Button>
                ) : null}
                <Button
                  variant="secondary"
                  disabled={exporting || !version}
                  onClick={async () => {
                    setExporting(true);
                    setError("");
                    try {
                      await downloadFile(
                        `/api/tutorials/${tutorial.id}/export`,
                        `${tutorial.title || "tutorial"}.md`
                      );
                    } catch (e) {
                      setError(errMsg(e));
                    } finally {
                      setExporting(false);
                    }
                  }}
                >
                  {exporting ? "导出中…" : "下载 Markdown"}
                </Button>
                {goal && (
                  <Link
                    href={`/goals/${goal.id}`}
                    className="text-[11px] font-semibold text-brand hover:underline"
                  >
                    返回学习目标 →
                  </Link>
                )}
              </div>
            }
          >
            <DemoNotice show={!!isDemo}>教程由演示生成器产生，关键事实与命令需人工核验。</DemoNotice>
            <TeachingPlanNotice plan={content?.teaching_plan} />

            <div className="mb-3">
              <div className="mb-1.5 text-[11px] font-bold text-[#5a6a86]">
                大纲（{outline.length} 节）· 点击进入每一步详情
              </div>
              <OutlineList tutorialId={tutorial.id} outline={outline} sections={sections} />
            </div>

            {sections.length === 0 ? (
              <div className="grid gap-2">
                <Empty>章节尚未生成。大纲已就绪，可直接一键生成全部章节。</Empty>
                <div>
                  <Button onClick={startAllSections} disabled={busy === "sections"}>
                    {busy === "sections" ? "生成中…" : "一键生成全部章节"}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="grid gap-3">
                {sections.map((section, index) => (
                  <div key={section.id} id={section.id} className="rounded-xl border border-line p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
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
                          单独打开 →
                        </Link>
                        <button
                          className="text-[10px] font-semibold text-brand hover:underline disabled:opacity-40"
                          // 单节重生成会各自落一个新版本：并发点两节会互相覆盖，任一任务在跑时全部禁用
                          disabled={!!busy}
                          onClick={() =>
                            run(
                              `regen-${section.id}`,
                              async () => {
                                await api.post(
                                  `/api/tutorials/${tutorial.id}/sections/${section.id}/regenerate`
                                );
                              },
                              "章节已重新生成"
                            )
                          }
                        >
                          {busy === `regen-${section.id}` ? "重生成中…" : "重新生成本节"}
                        </button>
                      </div>
                    </div>
                    <div className="mt-2">
                      <SectionContent section={section} criteria={criteria} />
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
          </Card>
        </div>

        <div className="grid gap-4">
          <Card title="Token 消耗" desc="优先使用模型返回的 usage；缺失时按字符估算并标注">
            <TokenLine
              versionTokens={version?.token_usage}
              tutorialTokens={tutorial.tokens}
              goalTokens={usage?.totals}
            />
            <div className="mt-3 grid gap-1 text-[11px]">
              {(usage?.by_feature ?? []).map((item) => (
                <div key={item.feature} className="flex items-center justify-between gap-2">
                  <span className="text-[#5a6a86]">{featureLabel(item.feature)}</span>
                  <b className="text-brand">{fmtTokens(item.total_tokens)}</b>
                </div>
              ))}
            </div>
            {usage && (
              <div className="mt-2 border-t border-line pt-2 text-[10px] text-muted">
                目标累计调用 {usage.totals.calls ?? 0} 次 · 实测 {usage.provider_calls} 次 · 估算{" "}
                {usage.estimated_calls} 次
              </div>
            )}
          </Card>

          {(cheatsheet?.sections?.length || extraExercises?.exercises?.length) && (
            <Card
              title="配套文件"
              desc="导出后与主教程放在同一文件夹，Obsidian 双链会自动生效"
            >
              <ul className="grid gap-1.5 text-[11px]">
                {cheatsheet?.sections?.length ? (
                  <li>
                    [[{cheatsheet.filename ?? "知识速查"}]] — 知识速查（{cheatsheet.sections.length} 个小节，
                    公式 / 命令 / 方法适用条件的集中查阅）
                  </li>
                ) : null}
                {extraExercises?.exercises?.length ? (
                  <li>
                    [[{extraExercises.filename ?? "额外练习"}]] — 额外练习（{extraExercises.exercises.length} 题，
                    参考答案集中放文件末尾）
                  </li>
                ) : null}
              </ul>
            </Card>
          )}

          {version && (
            <Card
              title="质量报告"
              desc={`v${version.version} · ${version.model_provider} / ${version.model_name}`}
              actions={<Badge tone={report.passed ? "done" : "warn"}>{report.passed ? "通过" : "待改进"}</Badge>}
            >
              <ul className="grid gap-0.5 text-[11px]">
                {(report.checks ?? []).map((check, index) => (
                  <li key={index} className={check.passed ? "text-[#128b78]" : "text-[#a33]"}>
                    {check.passed ? "✓" : "✗"} {check.name}
                    <span className="text-muted"> — {check.detail}</span>
                  </li>
                ))}
              </ul>
              {report.issues && report.issues.length > 0 && (
                <ul className="mt-1 grid gap-0.5 text-[11px] text-[#a33]">
                  {report.issues.map((issue, index) => (
                    <li key={index}>· {issue}</li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          <Card title="用户反馈" desc="测试版：反馈会持久化，并随训练数据一起导出">
            <FeedbackForm
              goalId={tutorial.goal_id}
              tutorialId={tutorial.id}
              targetType="tutorial"
              title="这套教程对你有帮助吗？"
            />
          </Card>
        </div>
      </div>
    </div>
  );
}
