"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Goal } from "@/lib/types";
import { PHASE_LABELS } from "@/lib/goal-phases";
import { Badge, Button, Card, Empty, Field, inputCls } from "@/components/ui";
import { GoalExamples } from "@/components/goals/GoalExamples";

const STATUS_LABEL = PHASE_LABELS;

// 与后端 services/api/app/learning/disciplines.py 的 SUBJECTS 保持一致
// （依据《AI-Edu-教程分类体系规范》一级学科目录 S01–S21）
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
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    title: "",
    domain_key: "cs_it",
    motivation: "",
    application_context: "",
    current_level: "",
    time_budget: "共 10 小时",
  });

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

  const create = async () => {
    if (!form.title.trim()) {
      setError("请填写目标名称");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const goal = await api.post<Goal>("/api/goals", form);
      setForm({ ...form, title: "", motivation: "", application_context: "", current_level: "" });
      await load();
      router.push(`/goals/${goal.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
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
          把模糊兴趣转化为清晰、值得投入且可以验收的目标。创建后先做价值评估与验收标准设计，再生成教程。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Card title="我的目标" desc="点击进入闭环工作区" actions={<Badge>{goals.length} 个</Badge>}>
          {loading ? (
            <Empty>加载中…</Empty>
          ) : goals.length === 0 ? (
            <Empty>还没有目标，右侧创建第一个。</Empty>
          ) : (
            <div className="grid gap-2.5">
              {goals.map((g) => (
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
                    {g.domain_name} · {g.time_budget || "未填可投入总时间"}
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

        <Card title="创建学习目标" desc="先描述想解决的问题，创建后再评估价值、范围与验收标准">
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
          <Button onClick={create} disabled={busy}>
            {busy ? "创建中…" : "创建目标"}
          </Button>
          <GoalExamples />
          <p className="mt-3 text-[11px] leading-relaxed text-muted">
            创建后仍需评估价值、学习范围与验收标准；这里不会自动生成教程。
          </p>
        </Card>
      </div>
    </div>
  );
}
