"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Goal } from "@/lib/types";
import { Badge, Button, Card, Empty, Field, inputCls } from "@/components/ui";

const STATUS_LABEL: Record<string, string> = {
  goal_definition: "目标定义",
  diagnosis: "诊断",
  planning: "计划",
  acceptance_design: "验收标准",
  learning: "教程学习",
  practice: "实践",
  feedback: "反馈",
  assessment: "评估",
  reflection: "复盘",
  knowledge_update: "知识记录",
};

const DOMAINS = [
  { key: "computer_cli", label: "计算机 / 命令行 / 编程" },
  { key: "math_data", label: "数学 / 数据分析" },
];

export default function GoalsPage() {
  const router = useRouter();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    title: "",
    domain_key: "computer_cli",
    motivation: "",
    application_context: "",
    current_level: "",
    time_budget: "每天 30 分钟",
  });

  const load = async () => {
    try {
      setGoals(await api.get<Goal[]>("/api/goals"));
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
    if (!window.confirm("归档该目标？数据仍保留，可从导出备份中恢复。")) return;
    try {
      await api.del(`/api/goals/${id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
                    {g.domain_name} · {g.time_budget || "未设时间预算"}
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
          <Field label="可投入时间">
            <input
              className={inputCls}
              value={form.time_budget}
              onChange={(e) => setForm({ ...form, time_budget: e.target.value })}
            />
          </Field>
          <Button onClick={create} disabled={busy}>
            {busy ? "创建中…" : "创建目标"}
          </Button>
          <p className="mt-3 text-[11px] leading-relaxed text-muted">
            创建后仍需评估价值、学习范围与验收标准；这里不会自动生成教程。
          </p>
        </Card>
      </div>
    </div>
  );
}
