"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Criterion, GoalUsage, SectionDetail, Tutorial } from "@/lib/types";
import { fmtTokens, usageSourceLabel } from "@/lib/format";
import { SectionContent, TeachingPlanNotice, TokenLine } from "@/components/tutorial";
import { FeedbackForm } from "@/components/FeedbackForm";
import StudyNotes from "@/components/StudyNotes";
import { Badge, Button, Card, DemoNotice } from "@/components/ui";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function SectionPage() {
  return (
    <Suspense
      fallback={<div className="mx-auto max-w-[900px] px-6 py-10 text-[13px] text-muted">加载中…</div>}
    >
      <SectionDetailView />
    </Suspense>
  );
}

function SectionDetailView() {
  const params = useParams<{ tid: string; sid: string }>();
  const tutorialId = params.tid;
  const sectionId = params.sid;

  const [section, setSection] = useState<SectionDetail | null>(null);
  const [tutorial, setTutorial] = useState<Tutorial | null>(null);
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [usage, setUsage] = useState<GoalUsage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const detail = await api.get<SectionDetail>(
      `/api/tutorials/${tutorialId}/sections/${sectionId}`
    );
    setSection(detail);
    const [tutorialData, criteriaData, usageData] = await Promise.all([
      api.get<Tutorial>(`/api/tutorials/${tutorialId}`).catch(() => null),
      api.get<Criterion[]>(`/api/goals/${detail.goal_id}/criteria`).catch(() => []),
      api.get<GoalUsage>(`/api/goals/${detail.goal_id}/usage`).catch(() => null),
    ]);
    setTutorial(tutorialData);
    setCriteria(criteriaData);
    setUsage(usageData);
  }, [tutorialId, sectionId]);

  useEffect(() => {
    // 首次进入按 URL 拉取章节详情；该规则对异步 setState 误报
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load().catch((e) => setError(errMsg(e)));
  }, [load]);

  const regenerate = async () => {
    if (!section) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.post(`/api/tutorials/${tutorialId}/sections/${sectionId}/regenerate`);
      await load();
      setNotice("本节已重新生成（新版本已生效）");
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  if (error && !section) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-10">
        <div className="mb-3 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
        <div className="flex flex-wrap gap-3 text-[12px] font-semibold text-brand">
          <Link href={`/tutorials/${tutorialId}`} className="hover:underline">
            ← 返回教程
          </Link>
          <Link href="/goals" className="hover:underline">
            ← 返回学习目标
          </Link>
        </div>
      </div>
    );
  }

  if (!section) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-10">
        <div className="text-[13px] text-muted">加载中…</div>
      </div>
    );
  }

  const isDemo = tutorial?.current_version?.model_provider === "demo";

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-5">
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
          <Link href="/goals" className="hover:text-brand">
            学习目标
          </Link>
          <span>/</span>
          <Link href={`/goals/${section.goal_id}`} className="hover:text-brand">
            {section.goal_title}
          </Link>
          <span>/</span>
          <Link href={`/tutorials/${section.tutorial_id}`} className="hover:text-brand">
            教程
          </Link>
          <span>/</span>
          <span className="text-ink">
            第 {section.index + 1} / {section.total} 节
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-bold tracking-tight">{section.title}</h1>
          <Badge tone="active">
            {section.index + 1} / {section.total}
          </Badge>
          <Badge>本节 {fmtTokens(section.token_usage?.total_tokens)} tokens</Badge>
          <Badge tone="neutral">教程累计 {fmtTokens(tutorial?.tokens?.total_tokens)}</Badge>
        </div>
        <p className="mt-1 text-[12px] text-muted">
          {usageSourceLabel(section.token_usage?.usage_source)} · 教程版本 v{section.version}
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

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="grid gap-4">
          <Card
            title="本节内容"
            desc={`来自教程「${section.tutorial_title}」；可单独重新生成或提交反馈`}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={regenerate} disabled={busy}>
                  {busy ? "重生成中…" : "重新生成本节"}
                </Button>
                <Link
                  href={`/tutorials/${section.tutorial_id}`}
                  className="text-[11px] font-semibold text-brand hover:underline"
                >
                  返回教程 →
                </Link>
              </div>
            }
          >
            <DemoNotice show={!!isDemo}>演示生成内容，关键事实与命令需人工核验。</DemoNotice>
            <TeachingPlanNotice plan={tutorial?.current_version?.content.teaching_plan} />
            <div className="reading-content"><SectionContent section={section} criteria={criteria} /></div>
            <div className="mt-3">
              <TokenLine
                versionTokens={tutorial?.current_version?.token_usage}
                tutorialTokens={tutorial?.tokens}
                goalTokens={usage?.totals}
              />
            </div>
          </Card>

          <div className="flex flex-wrap items-center justify-between gap-2">
            {section.prev_section_id ? (
              <Link
                href={`/tutorials/${section.tutorial_id}/sections/${section.prev_section_id}`}
                className="rounded-[10px] border border-line bg-white px-3.5 py-2 text-[12px] font-semibold text-[#39455d] hover:border-[#c9c3ff]"
              >
                ← 上一节
              </Link>
            ) : (
              <span className="text-[11px] text-muted">已是第一节</span>
            )}
            {section.next_section_id ? (
              <Link
                href={`/tutorials/${section.tutorial_id}/sections/${section.next_section_id}`}
                className="rounded-[10px] bg-brand px-3.5 py-2 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
              >
                下一节 →
              </Link>
            ) : (
              <span className="text-[11px] text-muted">已是最后一节</span>
            )}
          </div>
        </div>

        <div className="grid gap-4">
          <Card title="学习闭环" desc="从这一节回到目标工作区，继续实践、评估与复盘">
            <div className="grid gap-2 text-[12px]">
              <Link
                href={`/goals/${section.goal_id}`}
                className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
              >
                ← 回到学习目标工作区
              </Link>
              <Link
                href={`/tutorials/${section.tutorial_id}`}
                className="rounded-lg border border-line bg-white px-3 py-2 font-semibold text-brand hover:border-[#c9c3ff]"
              >
                ← 查看完整教程
              </Link>
            </div>
          </Card>

          <StudyNotes key={section.id} sectionId={section.id} tutorialId={section.tutorial_id} title={section.title} goal={section.goal_title} />
          <Card title="用户反馈" desc="测试版：反馈会持久化，并随训练数据一起导出">
            <FeedbackForm
              goalId={section.goal_id}
              tutorialId={section.tutorial_id}
              sectionId={section.id}
              targetType="section"
              title="这一节对你有帮助吗？"
            />
          </Card>
        </div>
      </div>
    </div>
  );
}
