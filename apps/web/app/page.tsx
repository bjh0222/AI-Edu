"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Goal, Health, Knowledge } from "@/lib/types";
import { Badge, Card, DemoNotice, Empty } from "@/components/ui";
import { ContinueLearning } from "@/components/StudyNotes";

const STATUS_LABEL: Record<string, string> = {
  goal_definition: "目标定义",
  diagnosis: "诊断",
  planning: "计划",
  acceptance_design: "验收标准",
  learning: "教程学习",
  // 旧数据可能停留在已删除的阶段，保留中文标签
  practice: "实践",
  feedback: "反馈",
  assessment: "评估",
  reflection: "复盘",
  knowledge_update: "知识记录",
};

const PHASE_ORDER = [
  "goal_definition",
  "diagnosis",
  "planning",
  "acceptance_design",
  "learning",
];

export default function Home() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [g, h, k] = await Promise.all([
          api.get<Goal[]>("/api/goals"),
          api.get<Health>("/api/health"),
          api.get<Knowledge>("/api/knowledge"),
        ]);
        setGoals(g);
        setHealth(h);
        setKnowledge(k);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const inProgress = goals.filter((g) => PHASE_ORDER.indexOf(g.status) > 0).length;
  const done = goals.filter((g) => g.status === "learning").length;

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      {/* 页头 */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">YOUR LEARNING OS</div>
          <h1 className="mb-2 text-[27px] font-bold tracking-tight">把好奇心，变成真正的能力。</h1>
          <p className="max-w-[700px] text-[13px] leading-relaxed text-muted">
            先明确要解决的问题，再学习真正需要的知识。每一次实践，都会成为下一次独立解决问题的起点。
          </p>
        </div>
        <Link
          href="/goals"
          className="rounded-[10px] bg-brand px-4 py-2.5 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
        >
          ＋ 创建学习目标
        </Link>
      </div>

      <ContinueLearning />
      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          无法连接后端：{error}。请确认 API 服务（services/api）已启动，或在
          <Link href="/settings" className="mx-1 underline">
            偏好设置
          </Link>
          中检查。
        </div>
      )}

      <DemoNotice show={!!health?.demo}>
        未配置模型密钥——教程、诊断等内容由演示生成器产生并已标注；配置 `.env` 中的 LLM 参数后自动切换为真实模型。
      </DemoNotice>

      {/* 统计卡 */}
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">学习目标</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{goals.length}</div>
          <div className="mt-1 text-[11px] text-muted">从真实需求出发</div>
        </div>
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">进行中</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{inProgress}</div>
          <div className="mt-1 text-[11px] text-muted">已进入学习闭环</div>
        </div>
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">已出教程</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{done}</div>
          <div className="mt-1 text-[11px] text-muted">教程已生成，可放入 Obsidian 学习</div>
        </div>
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">知识网络</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{knowledge?.concepts.length ?? 0}</div>
          <div className="mt-1 text-[11px] text-muted">
            {knowledge?.relations.length ?? 0} 条关系 ·{" "}
            {knowledge?.proposals.filter((p) => p.status === "pending").length ?? 0} 条待确认
          </div>
        </div>
      </div>

      {/* 目标列表 */}
      <Card
        title="当前学习路径"
        desc="以真实项目为牵引，逐步减少 AI 提示。点击目标进入闭环工作区。"
        actions={
          <Link href="/goals" className="text-[12px] font-semibold text-brand hover:underline">
            全部目标 →
          </Link>
        }
      >
        {loading ? (
          <Empty>加载中…</Empty>
        ) : goals.length === 0 ? (
          <div className="py-8 text-center">
            <div className="mb-2 text-[13px] text-muted">还没有学习目标。</div>
            <Link href="/goals" className="text-[12px] font-semibold text-brand hover:underline">
              创建第一个目标 →
            </Link>
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {goals.map((g) => (
              <Link
                key={g.id}
                href={`/goals/${g.id}`}
                className="block rounded-xl border border-line p-4 transition-colors hover:border-[#c9c2ff] hover:bg-[#faf9ff]"
              >
                <div className="flex items-center justify-between gap-2">
                  <b className="text-[13px]">{g.title}</b>
                  <Badge tone="active">{STATUS_LABEL[g.status] ?? g.status}</Badge>
                </div>
                <div className="mt-1.5 text-[11px] text-muted">
                  {g.domain_name}
                  {g.application_context ? ` · ${g.application_context}` : ""}
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {PHASE_ORDER.map((p, i) => (
                    <span
                      key={p}
                      title={STATUS_LABEL[p]}
                      className={`h-1 w-4 rounded-full ${
                        i <= PHASE_ORDER.indexOf(g.status) ? "bg-brand" : "bg-[#e7e9f3]"
                      }`}
                    />
                  ))}
                </div>
              </Link>
            ))}
          </div>
        )}
      </Card>

      <div className="mt-6 text-center text-[10px] text-[#9aa3b3]">
        AI Edu · 本地开发版 · 生成内容需核验，证据比感觉更可靠
      </div>
    </div>
  );
}
