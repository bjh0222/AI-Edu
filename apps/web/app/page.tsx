"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Goal, Health, Knowledge, ProfileSuggestionState } from "@/lib/types";
import { Badge, Card, DemoNotice, Empty } from "@/components/ui";
import { ContinueLearning } from "@/components/StudyNotes";
import { Button, inputCls } from "@/components/ui";

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

const DAY_MS = 24 * 60 * 60 * 1000;

function createdDays(goal: Goal) {
  const time = goal.created_at ? new Date(goal.created_at).getTime() : NaN;
  return Number.isFinite(time) ? Math.max(0, Math.floor((Date.now() - time) / DAY_MS)) : 0;
}

export default function Home() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");
  const [profile, setProfile] = useState("");
  const [profileDraft, setProfileDraft] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [suggestion, setSuggestion] = useState<ProfileSuggestionState | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [g, h, k, setting, suggestionData] = await Promise.all([
          api.get<Goal[]>("/api/goals"),
          api.get<Health>("/api/health"),
          api.get<Knowledge>("/api/knowledge"),
          api.get<{ user_profile: string }>("/api/settings/models"),
          api.get<ProfileSuggestionState>("/api/settings/models/user-profile-suggestion").catch(() => null),
        ]);
        setGoals(g);
        setHealth(h);
        setKnowledge(k);
        setProfile(setting.user_profile);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const inProgress = goals.filter((g) => PHASE_ORDER.indexOf(g.status) > 0).length;
  const done = goals.filter((g) => g.status === "learning").length;
  const sortedGoals = [...goals].sort((a, b) => {
    const at = a.created_at ?? "";
    const bt = b.created_at ?? "";
    return sortOrder === "desc" ? bt.localeCompare(at) : at.localeCompare(bt);
  });
  const activeGoals = sortedGoals.filter((g) => !g.completed);
  const completedGoals = sortedGoals.filter((g) => g.completed);


  const loadSuggestion = async () => {
    setSuggestion(await api.get<ProfileSuggestionState>("/api/settings/models/user-profile-suggestion"));
  };

  const dismissSuggestion = async () => {
    const next = await api.post<ProfileSuggestionState>("/api/settings/models/user-profile-suggestion/dismiss", {});
    setSuggestion(next);
  };

  const saveProfile = async () => {
    setProfileBusy(true);
    setProfileError("");
    try {
      const setting = await api.put<{ user_profile: string }>("/api/settings/models/user-profile", {
        content: profileDraft,
      });
      setProfile(setting.user_profile);
      setProfileOpen(false);
    } catch (e) {
      setProfileError(e instanceof Error ? e.message : String(e));
    } finally {
      setProfileBusy(false);
    }
  };

  const setCompletion = async (goal: Goal, completed: boolean) => {
    if (
      completed &&
      !window.confirm(`确认已完成「${goal.title}」？完成后会移入右栏，可随时恢复为未完成。`)
    ) {
      return;
    }
    setError("");
    try {
      await api.patch(`/api/goals/${goal.id}`, { completed });
      setGoals((items) => items.map((item) => (item.id === goal.id ? { ...item, completed } : item)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const renderGoal = (g: Goal, completed: boolean) => (
    <article
      key={g.id}
      className={`rounded-xl border p-4 transition-colors ${
        completed ? "border-[#c9e8de] bg-[#f7fbfa]" : "border-line hover:border-[#c9c2ff] hover:bg-[#faf9ff]"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <Link href={`/goals/${g.id}`} className="text-[13px] font-bold hover:text-brand">
          {g.title}
        </Link>
        <button
          type="button"
          onClick={() => void setCompletion(g, !completed)}
          className={`shrink-0 rounded-lg border px-2 py-1 text-[10px] font-semibold transition-colors ${
            completed
              ? "border-line bg-white text-muted hover:text-brand"
              : "border-[#b8e5d8] bg-[#eefaf6] text-[#128b78] hover:border-[#128b78]"
          }`}
        >
          {completed ? "恢复未完成" : "确认完成"}
        </button>
      </div>
      <div className="mt-1.5 text-[11px] text-muted">
        {g.domain_name}
        {g.application_context ? ` · ${g.application_context}` : ""}
      </div>
      {!completed && (
        <div className="mt-1.5 text-[11px] font-semibold text-[#a96a08]">
          已创建 {createdDays(g)} 天
        </div>
      )}
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
    </article>
  );

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setProfileDraft(profile);
              setProfileError("");
              setProfileOpen(true);
              void loadSuggestion();
            }}
            className="rounded-[10px] border border-line bg-white px-4 py-2.5 text-[12px] font-semibold text-[#39455d] transition-colors hover:border-[#c9c3ff] hover:text-brand"
          >
            用户画像
          </button>
          <Link
            href="/goals"
            className="rounded-[10px] bg-brand px-4 py-2.5 text-[12px] font-semibold text-white shadow-[0_5px_15px_#6d5dfc2a] hover:bg-brand-dark"
          >
            ＋ 创建学习目标
          </Link>
        </div>
      </div>

      <ContinueLearning />
      {profileOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-[#1118274d] p-4">
          <div className="w-full max-w-[620px] rounded-2xl border border-line bg-panel p-5 shadow-[0_20px_60px_#19254226]">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[16px] font-bold text-ink">用户画像</h2>
              <button
                type="button"
                onClick={() => setProfileOpen(false)}
                className="rounded-lg px-2 py-1 text-[12px] font-semibold text-muted hover:text-brand"
              >
                关闭
              </button>
            </div>
            {suggestion?.eligible && suggestion.suggestion && (
              <div className="mb-3 rounded-xl border border-[#e7e3ff] bg-[#f7f6ff] p-3">
                <b className="text-[11px]">完成 {suggestion.completed_count} 次学习后的画像建议</b>
                <p className="mt-1 text-[11px] text-muted">{suggestion.suggestion.summary}</p>
                <pre className="mt-2 whitespace-pre-wrap text-[11px] leading-relaxed text-[#33415c]">
{suggestion.suggestion.profile_text}
                </pre>
                <p className="mt-2 text-[10px] text-muted">
                  依据：{suggestion.suggestion.evidence || "无"} · {suggestion.suggestion.notes}
                </p>
                <div className="mt-2 flex gap-2">
                  <Button
                    onClick={() => setProfileDraft(suggestion.suggestion?.profile_text ?? profileDraft)}
                  >
                    填入草稿
                  </Button>
                  <Button variant="secondary" onClick={() => void dismissSuggestion()}>
                    忽略
                  </Button>
                </div>
              </div>
            )}
            <p className="mb-3 text-[11px] leading-relaxed text-muted">
              写长期教学要求：一次一行。以「不要 / 禁止」开头会视为禁区，含「必须 / 务必」会视为必须原则，
              「当 / 如果 / 遇到」开头的偏好会按条件处理。本次任务的特殊要求请写在具体学习目标里。
            </p>
            <textarea
              className={inputCls}
              rows={9}
              value={profileDraft}
              onChange={(event) => setProfileDraft(event.target.value)}
              placeholder="例如：非科班转行，必须解释关键推理步骤，遇到抽象概念先给一个可运行示例，不要跳过前置概念。"
            />
            {profileError && (
              <p role="alert" className="mt-2 text-[12px] text-[#a33]">{profileError}</p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setProfileOpen(false)}>
                取消
              </Button>
              <Button onClick={() => void saveProfile()} disabled={profileBusy}>
                {profileBusy ? "保存中…" : "保存画像"}
              </Button>
            </div>
          </div>
        </div>
      )}
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
          <div className="flex items-center gap-3">
            <select
              aria-label="按创建时间排序"
              className="rounded-lg border border-line bg-panel px-2 py-1 text-[11px]"
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value as "desc" | "asc")}
            >
              <option value="desc">创建时间：新→旧</option>
              <option value="asc">创建时间：旧→新</option>
            </select>
            <Link href="/goals" className="text-[12px] font-semibold text-brand hover:underline">
              全部目标 →
            </Link>
          </div>
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
          <div className="grid gap-4 lg:grid-cols-2">
            <section aria-label="未完成学习路径">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-[12px] font-bold text-ink">未完成</h3>
                <Badge tone="active">{activeGoals.length} 个</Badge>
              </div>
              <div className="grid gap-2.5">
                {activeGoals.length === 0 ? (
                  <Empty>没有未完成的学习路径。</Empty>
                ) : activeGoals.map((g) => renderGoal(g, false))}
              </div>
            </section>
            <section aria-label="已完成学习路径">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-[12px] font-bold text-ink">已完成</h3>
                <Badge tone="done">{completedGoals.length} 个</Badge>
              </div>
              <div className="grid gap-2.5">
                {completedGoals.length === 0 ? (
                  <Empty>确认完成的学习路径会显示在这里。</Empty>
                ) : completedGoals.map((g) => renderGoal(g, true))}
              </div>
            </section>
          </div>
        )}
      </Card>

      <div className="mt-6 text-center text-[10px] text-[#9aa3b3]">
        AI Edu · 本地开发版 · 生成内容需核验，证据比感觉更可靠
      </div>
    </div>
  );
}
