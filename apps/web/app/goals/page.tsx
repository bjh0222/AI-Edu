"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError, uploadFile } from "@/lib/api";
import type { Goal, GenerationTier, OneShotGenerateResult, QuickStartResult } from "@/lib/types";
import { CAPABILITY_LEVELS, GENERATION_TIERS } from "@/lib/types";
import { PHASE_LABELS } from "@/lib/goal-phases";
import { Badge, Button, Card, Empty, Field, inputCls } from "@/components/ui";
import { GoalExamples } from "@/components/goals/GoalExamples";
import { PausedGenerationPanel, type PauseResumeAction } from "@/components/PausedGeneration";
import { PendingMaterialsPanel, type PendingMaterial } from "@/components/goals/PendingMaterialsPanel";

const STATUS_LABEL = PHASE_LABELS;

// 与后端 services/api/app/learning/disciplines.py 的 SUBJECTS 保持一致
// （依据《AI-Edu-教程分类体系规范》一级学科目录 S01–S21）
type PausedGenerationState = {
  goalId: string;
  recommendation: string;
  plan: string;
};

const DOMAINS = [
  { key: "math_logic", label: "数学、逻辑与统计" },
  { key: "cs_it", label: "计算机科学与信息技术" },
  { key: "physics_astronomy", label: "物理与天文学" },
  { key: "chemistry_materials", label: "化学与材料" },
  { key: "biology_life", label: "生物与生命科学" },
  { key: "earth_environment", label: "地球、环境与气候" },
  { key: "engineering_manufacturing", label: "工程与制造" },
  { key: "health_sport", label: "医学、健康与运动" },
  { key: "agriculture_food", label: "农业、食品与兽医" },
  { key: "psychology_cognition", label: "心理与认知科学" },
  { key: "society_politics", label: "社会、政治与人类学" },
  { key: "economics_business", label: "经济、商业与管理" },
  { key: "law_policy", label: "法律、政策与治理" },
  { key: "education_learning", label: "教育与学习科学" },
  { key: "language_communication", label: "语言、语言学与传播" },
  { key: "philosophy_ethics", label: "哲学、伦理与宗教研究" },
  { key: "history_culture", label: "历史、文化与考古" },
  { key: "arts_creativity", label: "文学、艺术与创意实践" },
  { key: "design_architecture", label: "设计与建筑环境" },
  { key: "geography_urban", label: "地理、空间与城市研究" },
  { key: "interdisciplinary", label: "跨学科与综合研究" },
];

export default function GoalsPage() {
  const router = useRouter();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [archivedGoals, setArchivedGoals] = useState<Goal[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [paused, setPaused] = useState<PausedGenerationState | null>(null);
  const [pausedBusy, setPausedBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState("");
  const [draftStatus, setDraftStatus] = useState("");
  const [draftReady, setDraftReady] = useState(false);
  const [form, setForm] = useState({
    title: "",
    domain_key: "cs_it",
    motivation: "",
    application_context: "",
    current_level: "",
    time_budget: "共 10 小时",
    hard_constraints: "",
    capability_level: "L2" as Goal["capability_level"],
    generate_extra_exercises: false,
    generation_tier: "standard" as GenerationTier,
  });
  // 「创建并生成教程」里暂存的参考材料：目标创建成功后才真正上传
  const [pendingMaterials, setPendingMaterials] = useState<PendingMaterial[]>([]);
  // 同一次提交里已创建的目标（材料上传中途失败重试时复用，避免重复建目标）
  const createdGoalRef = useRef<Goal | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("aiedu-goal-draft");
      if (raw) {
        const draft = JSON.parse(raw);
        // Restore browser-only draft after hydration.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setForm(previous => {
          const next = { ...previous };
          for (const key of ["title", "motivation", "application_context", "current_level", "time_budget", "hard_constraints"] as const) {
            if (typeof draft[key] === "string") next[key] = draft[key];
          }
          if (DOMAINS.some(d => d.key === draft.domain_key)) next.domain_key = draft.domain_key;
          if (["L1", "L2", "L3"].includes(draft.capability_level)) next.capability_level = draft.capability_level;
          next.generate_extra_exercises = draft.generate_extra_exercises === true;
          if (GENERATION_TIERS.some(t => t.key === draft.generation_tier)) next.generation_tier = draft.generation_tier;
          return next;
        });
        setDraftStatus("已恢复上次未提交的草稿");
      }
    } catch { setDraftStatus("浏览器无法读取草稿"); }
    setDraftReady(true);
  }, []);

  useEffect(() => {
    if (!draftReady) return;
    const timer = setTimeout(() => {
      try {
        if (form.title || form.motivation || form.application_context || form.current_level || form.hard_constraints) {
          localStorage.setItem("aiedu-goal-draft", JSON.stringify(form));
          setDraftStatus("草稿已自动保存到此浏览器");
        } else { localStorage.removeItem("aiedu-goal-draft"); setDraftStatus(""); }
      } catch { setDraftStatus("草稿保存失败，请勿关闭页面"); }
    }, 300);
    return () => clearTimeout(timer);
  }, [form, draftReady]);

  const visibleGoals = goals.filter(g => (!phase || g.status === phase) &&
    `${g.title} ${g.domain_name} ${g.application_context}`.toLowerCase().includes(query.trim().toLowerCase()));

  const load = async () => {
    try {
      const [active, all] = await Promise.all([
        api.get<Goal[]>("/api/goals"),
        api.get<Goal[]>("/api/goals?include_archived=true"),
      ]);
      setGoals(active);
      setArchivedGoals(all.filter((g) => g.archived));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // 挂载时加载目标列表（与后端 API 同步）；该规则对异步 setState 误报
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const resetDraft = () => {
    setForm((previous) => ({
      ...previous,
      title: "",
      motivation: "",
      application_context: "",
      current_level: "",
      hard_constraints: "",
      generate_extra_exercises: false,
      generation_tier: "standard",
    }));
    try { localStorage.removeItem("aiedu-goal-draft"); } catch { /* Draft cleanup is best effort. */ }
  };

  const addPendingMaterials = useCallback((files: File[], kind: string) => {
    setPendingMaterials((prev) => [
      ...prev,
      ...files.map((file, index) => ({
        key: `${Date.now()}-${prev.length + index}-${file.name}`,
        file,
        kind,
        status: "pending" as PendingMaterial["status"],
        progress: 0,
        error: "",
      })),
    ]);
  }, []);

  const removePendingMaterial = (key: string) => {
    setPendingMaterials((prev) => prev.filter((row) => row.key !== key));
  };

  const patchPendingMaterial = (key: string, patch: Partial<PendingMaterial>) => {
    setPendingMaterials((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  };

  /** 逐个上传暂存材料：成功的行标记 done（重试时跳过），失败的保留错误信息并返回列表。 */
  const uploadPendingMaterials = async (goalId: string): Promise<string[]> => {
    const failed: string[] = [];
    for (const row of pendingMaterials) {
      if (row.status === "done") continue;
      patchPendingMaterial(row.key, { status: "uploading", progress: 0, error: "" });
      try {
        const upload = new FormData();
        upload.append("file", row.file, row.file.name);
        upload.append("kind", row.kind);
        await uploadFile(`/api/goals/${goalId}/materials`, upload, (percent) => {
          patchPendingMaterial(row.key, { progress: percent });
        });
        patchPendingMaterial(row.key, { status: "done", progress: 100, error: "" });
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        patchPendingMaterial(row.key, { status: "error", progress: 0, error: message });
        failed.push(`${row.file.name}：${message}`);
      }
    }
    return failed;
  };

  const resetAll = () => {
    resetDraft();
    setPendingMaterials([]);
    createdGoalRef.current = null;
  };

  const create = async (autoGenerate = true) => {
    if (!form.title.trim()) {
      setError("请填写目标名称");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const requirement = [
        form.application_context,
        form.motivation,
        form.current_level ? `当前基础：${form.current_level}` : "",
        form.time_budget ? `可投入时间：${form.time_budget}` : "",
      ].filter(Boolean).join("\n") || form.title;

      // 带参考材料的提交流程：材料接口挂在目标下（/api/goals/{goal_id}/materials），
      // 所以先创建目标 → 上传材料 → 再触发生成，AI 才能把这些材料注入 prompt。
      if (pendingMaterials.length > 0) {
        const goal = createdGoalRef.current ?? (await api.post<Goal>("/api/goals", autoGenerate
          ? {
              // 与后端 /api/goals/quickstart（create_and_quickstart）的字段处理保持一致
              title: form.title,
              domain_key: form.domain_key,
              motivation: form.motivation || "完成用户提出的学习需求",
              application_context: form.application_context || requirement,
              current_level: form.current_level,
              time_budget: form.time_budget,
              hard_constraints: form.hard_constraints,
              capability_level: form.capability_level,
              generate_extra_exercises: form.generate_extra_exercises,
              generation_tier: form.generation_tier,
              user_notes: requirement,
            }
          : { ...form, user_notes: requirement }));
        createdGoalRef.current = goal;
        const failed = await uploadPendingMaterials(goal.id);
        if (failed.length > 0) {
          await load();
          setError(
            `材料上传失败：${failed.join("；")}。目标「${goal.title}」已创建但尚未生成；` +
            "可移除失败文件后重新提交，不会重复创建目标。"
          );
          return;
        }
        if (!autoGenerate) {
          resetAll();
          await load();
          router.push(`/goals/${goal.id}`);
          return;
        }
        const result = await api.post<QuickStartResult>(`/api/goals/${goal.id}/tutorials/quickstart`, {});
        resetAll();
        setPaused(null);
        await load();
        router.push(`/tutorials/${result.tutorial.id}`);
        return;
      }

      if (!autoGenerate) {
        const goal = await api.post<Goal>("/api/goals", form);
        resetDraft();
        await load();
        router.push(`/goals/${goal.id}`);
        return;
      }

      const result = await api.post<OneShotGenerateResult>("/api/goals/quickstart", {
        title: form.title,
        requirement,
        domain_key: form.domain_key,
        motivation: form.motivation,
        application_context: form.application_context,
        current_level: form.current_level,
        time_budget: form.time_budget,
        hard_constraints: form.hard_constraints,
        capability_level: form.capability_level,
        generate_extra_exercises: form.generate_extra_exercises,
        generation_tier: form.generation_tier,
      });
      resetDraft();
      setPaused(null);
      await load();
      router.push(`/tutorials/${result.tutorial.id}`);
    } catch (e) {
      const detail = e instanceof ApiError ? e.data as { goal_id?: string; recommendation?: string } | null : null;
      if (e instanceof ApiError && e.code === "generation_paused" && detail?.goal_id) {
        setPaused({
          goalId: detail.goal_id,
          recommendation: detail.recommendation || e.message,
          plan: form.application_context || form.motivation || form.title,
        });
        return;
      }
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const resumePaused = async (action: PauseResumeAction) => {
    if (!paused) return;
    setPausedBusy(true);
    setError("");
    try {
      const result = await api.post<QuickStartResult>(
        `/api/goals/${paused.goalId}/tutorials/quickstart`,
        { pause_action: action }
      );
      setPaused(null);
      await load();
      router.push(`/tutorials/${result.tutorial.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPausedBusy(false);
    }
  };

  const revisePaused = async (plan: string) => {
    if (!paused || !plan.trim()) return;
    setPausedBusy(true);
    setError("");
    try {
      await api.patch(`/api/goals/${paused.goalId}`, {
        application_context: plan,
        user_notes: plan,
      });
      const result = await api.post<QuickStartResult>(
        `/api/goals/${paused.goalId}/tutorials/quickstart`,
        { pause_action: "proceed" }
      );
      setPaused(null);
      await load();
      router.push(`/tutorials/${result.tutorial.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPausedBusy(false);
    }
  };
  const archive = async (id: string) => {
    if (!window.confirm("归档该目标？归档后不在目标列表显示，可在「已归档目标」中彻底删除。")) return;
    try {
      await api.del(`/api/goals/${id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const purge = async (goal: Goal) => {
    if (
      !window.confirm(
        `彻底删除「${goal.title}」及其教程、验收标准、实践记录与知识网络数据？\n\n此操作不可撤销；删除前会自动生成一份 JSON 备份到 data/backups/。`
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await api.del(`/api/goals/${goal.id}?purge=true`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-6">
        <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">LEARNING GOALS</div>
        <h1 className="mb-2 text-[27px] font-bold tracking-tight">学习目标</h1>
        <p className="max-w-[700px] text-[13px] leading-relaxed text-muted">
          填写需求并选择挡位后，AI 会自动完成价值判断、学习计划、验收标准设计和教程生成。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}

      {paused && (
        <div className="mb-4">
          <Card title="生成已暂停" desc="请选择如何继续；三个选项都不会自动修改 AI 的原始判断记录。">
            <PausedGenerationPanel
              recommendation={paused.recommendation}
              initialPlan={paused.plan}
              busy={pausedBusy}
              onResume={(action) => void resumePaused(action)}
              onRevise={(plan) => void revisePaused(plan)}
            />
          </Card>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Card title="我的目标" desc="点击进入闭环工作区" actions={<Badge>{goals.length} 个</Badge>}>
          <div className="mb-4 flex flex-wrap gap-2">
            <input aria-label="搜索学习目标" className={`${inputCls} min-w-0 flex-1`} placeholder="搜索目标、学科或应用场景" value={query} onChange={e => setQuery(e.target.value)} />
            <select aria-label="按学习阶段筛选" className="rounded-xl border border-line bg-panel px-3 text-xs" value={phase} onChange={e => setPhase(e.target.value)}>
              <option value="">全部阶段</option>{Object.entries(STATUS_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </div>
          {loading ? (
            <Empty>加载中…</Empty>
          ) : visibleGoals.length === 0 ? (
            <Empty>{goals.length ? "没有匹配的目标，试试其他关键词或阶段。" : "还没有目标，右侧创建第一个。"}</Empty>
          ) : (
            <div className="grid gap-2.5">
              {visibleGoals.map((g) => (
                <div
                  key={g.id}
                  className="rounded-xl border border-line p-3.5 transition-colors hover:border-[#c9c2ff]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <Link href={`/goals/${g.id}`} className="text-[13px] font-bold hover:text-brand">
                      {g.title}
                    </Link>
                    <Badge tone="active">{STATUS_LABEL[g.status] ?? g.status}</Badge>
                  </div>
                  <div className="mt-1 text-[11px] text-muted">
                    {g.domain_name} · 层级 {g.capability_level || "L2"} ·{" "}
                    {g.time_budget || "未填可投入总时间"}
                    {g.application_context ? ` · ${g.application_context}` : ""}
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <Link
                      href={`/goals/${g.id}`}
                      className="rounded-lg border border-line bg-white px-2.5 py-1 text-[11px] font-semibold text-brand transition-colors hover:border-[#c9c3ff] hover:bg-[#f8f7ff]"
                    >
                      查看 →
                    </Link>
                    <button
                      onClick={() => archive(g.id)}
                      className="text-[11px] text-muted hover:text-[#c33]"
                    >
                      归档
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {archivedGoals.length > 0 && (
            <div className="mt-3 border-t border-line pt-3">
              <button
                type="button"
                onClick={() => setShowArchived((v) => !v)}
                className="text-[11px] font-semibold text-[#5a6a86] hover:text-brand"
              >
                已归档目标（{archivedGoals.length}）{showArchived ? "收起" : "展开"}
              </button>
              {showArchived && (
                <div className="mt-2 grid gap-1.5">
                  {archivedGoals.map((g) => (
                    <div
                      key={g.id}
                      className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[11px]"
                    >
                      <div className="min-w-0 flex-1 truncate text-[#39455d]">
                        {g.title}
                        <span className="ml-2 text-[10px] text-muted">{g.domain_name}</span>
                      </div>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => purge(g)}
                        className="shrink-0 text-[11px] font-semibold text-[#a33] hover:underline disabled:opacity-40"
                      >
                        彻底删除
                      </button>
                    </div>
                  ))}
                  <div className="text-[10px] leading-relaxed text-muted">
                    彻底删除会移除该目标的教程、实践与知识网络数据（不可撤销，删除前自动写入 JSON 备份）。
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card title="创建并生成教程" desc="默认一次生成：价值判断、学习计划、验收标准和教程自动完成">
          <p role="status" className="mb-3 text-xs text-muted">{draftStatus || "填写内容自动暂存，刷新页面也不会丢失。"}</p>
          <Field label="目标名称 *">
            <input
              className={inputCls}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="例如：掌握命令行管道与重定向"
            />
          </Field>
          <Field label="学科 / 领域">
            <select
              className={inputCls}
              value={form.domain_key}
              onChange={(e) => setForm({ ...form, domain_key: e.target.value })}
            >
              {DOMAINS.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="为什么要学">
            <textarea
              className={inputCls}
              rows={2}
              value={form.motivation}
              onChange={(e) => setForm({ ...form, motivation: e.target.value })}
              placeholder="它和你的当前需求或长期目标有什么关系？"
            />
          </Field>
          <Field label="学完要能做什么">
            <textarea
              className={inputCls}
              rows={2}
              value={form.application_context}
              onChange={(e) => setForm({ ...form, application_context: e.target.value })}
              placeholder="尽量描述一个可观察、可验收的任务。"
            />
          </Field>
          <Field label="当前基础">
            <textarea
              className={inputCls}
              rows={2}
              value={form.current_level}
              onChange={(e) => setForm({ ...form, current_level: e.target.value })}
              placeholder="你已经会什么、卡在哪里？"
            />
          </Field>
          <Field label="硬性约束（可选）">
            <textarea
              className={inputCls}
              rows={2}
              value={form.hard_constraints}
              onChange={(e) => setForm({ ...form, hard_constraints: e.target.value })}
              placeholder={"生成内容必须满足的强制要求，每行一条。例如：\n不安排任何日程\n所有命令示例同时给出 Linux 与 Windows 写法"}
            />
            <span className="text-[10px] leading-relaxed text-muted">
              填写后会注入价值判断、计划、验收标准、教程与配套文件的全部生成提示词；
              生成内容必须逐条满足，违反任一条即视为本次交付不合格
            </span>
          </Field>
          <Field label="可投入总时间">
            <input
              className={inputCls}
              value={form.time_budget}
              onChange={(e) => setForm({ ...form, time_budget: e.target.value })}
            />
            <span className="text-[10px] text-muted">
              填总时长（如「共 10 小时」），不用拆成每天的时间安排
            </span>
          </Field>
          <Field label="能力层级">
            <select
              className={inputCls}
              value={form.capability_level}
              onChange={(e) =>
                setForm({ ...form, capability_level: e.target.value as Goal["capability_level"] })
              }
            >
              {CAPABILITY_LEVELS.map((lv) => (
                <option key={lv.key} value={lv.key}>
                  {lv.key} · {lv.name}
                </option>
              ))}
            </select>
            <span className="text-[10px] leading-relaxed text-muted">
              {CAPABILITY_LEVELS.find((lv) => lv.key === form.capability_level)?.description}
            </span>
          </Field>
          <Field label="生成挡位">
            <select
              className={inputCls}
              value={form.generation_tier}
              onChange={(e) => setForm({ ...form, generation_tier: e.target.value as GenerationTier })}
            >
              {GENERATION_TIERS.map((tier) => (
                <option key={tier.key} value={tier.key}>
                  {tier.name} · {tier.key}
                </option>
              ))}
            </select>
            <span className="text-[10px] leading-relaxed text-muted">
              {GENERATION_TIERS.find((tier) => tier.key === form.generation_tier)?.description}
              一键生成会按此挡位自动完成价值判断、计划、验收标准与教程。
            </span>
          </Field>
          <Field label="额外练习文件">
            <label className="flex cursor-pointer items-center gap-2 text-[12px]">
              <input
                type="checkbox"
                checked={form.generate_extra_exercises}
                onChange={(e) => setForm({ ...form, generate_extra_exercises: e.target.checked })}
              />
              生成独立的额外练习文件（含参考答案，与教程内必要练习分开）
            </label>
            <span className="text-[10px] text-muted">
              开启后会随教程生成一份 Markdown 练习集并在教程中建立双链；教程内的必要练习不受影响
            </span>
          </Field>
          <div className="mb-3 grid gap-1.5">
            <span className="text-[12px] font-semibold text-ink">参考资料 / 例题来源（可选）</span>
            <PendingMaterialsPanel
              files={pendingMaterials}
              busy={busy}
              onAdd={addPendingMaterials}
              onRemove={removePendingMaterial}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void create(true)} disabled={busy}>
              {busy ? "自动生成中…" : "创建并自动生成教程"}
            </Button>
            <Button variant="secondary" onClick={() => void create(false)} disabled={busy}>
              仅创建目标
            </Button>
          </div>

          <GoalExamples />
          <p className="mt-3 text-[11px] leading-relaxed text-muted">
            默认路径会自动生成教程并跳转；仅当 AI 明确判断不值得推进时才暂停。
          </p>
        </Card>
      </div>
    </div>
  );
}
