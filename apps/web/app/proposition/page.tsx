"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  PropositionItemModel,
  PropositionItemModelList,
  PropositionItemModelPatch,
  PropositionPrinciple,
  PropositionPrincipleList,
} from "@/lib/types";
import { Badge, Button, Card, Empty, Field, inputCls } from "@/components/ui";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

/** 母题编辑表单的本地草稿：展开时从当前值初始化，保存时整体 PATCH。 */
interface ItemDraft {
  title: string;
  chapter: string;
  solution_template: string;
  answer_expr: string;
  unknown: string;
  answer_select: string;
  difficulty: string;
  status: string;
}

function draftOf(item: PropositionItemModel): ItemDraft {
  return {
    title: item.title,
    chapter: item.chapter,
    solution_template: item.solution_template,
    answer_expr: item.answer_expr,
    unknown: item.unknown,
    answer_select: item.answer_select,
    difficulty: item.difficulty,
    status: item.status,
  };
}

const ANSWER_SELECTS: { value: string; label: string }[] = [
  { value: "", label: "单解（不选）" },
  { value: "positive", label: "取正解" },
  { value: "negative", label: "取负解" },
  { value: "nonnegative", label: "取非负解" },
  { value: "max", label: "取最大解" },
  { value: "min", label: "取最小解" },
];

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  confirmed: "已确认",
  archived: "已归档",
  proposed: "候选",
  rejected: "已驳回",
};

const PRINCIPLE_FILTERS: { value: string; label: string }[] = [
  { value: "proposed", label: "待处理" },
  { value: "confirmed", label: "已确认" },
  { value: "rejected", label: "已驳回" },
  { value: "", label: "全部" },
];

export default function PropositionPage() {
  const [models, setModels] = useState<PropositionItemModelList | null>(null);
  const [principles, setPrinciples] = useState<PropositionPrincipleList | null>(null);
  const [principleFilter, setPrincipleFilter] = useState("proposed");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [expandedId, setExpandedId] = useState("");
  const [drafts, setDrafts] = useState<Record<string, ItemDraft>>({});
  const [savingId, setSavingId] = useState("");
  const [reviewingId, setReviewingId] = useState("");

  const loadModels = useCallback(async () => {
    const data = await api.get<PropositionItemModelList>("/api/proposition/item-models?limit=200");
    setModels(data);
  }, []);

  const loadPrinciples = useCallback(async (status: string) => {
    const query = new URLSearchParams({ limit: "200" });
    if (status) query.set("status", status);
    const data = await api.get<PropositionPrincipleList>(`/api/proposition/principles?${query.toString()}`);
    setPrinciples(data);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        await Promise.all([loadModels(), loadPrinciples("proposed")]);
      } catch (e) {
        setError(errMsg(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [loadModels, loadPrinciples]);

  const changePrincipleFilter = async (status: string) => {
    setPrincipleFilter(status);
    setError("");
    try {
      await loadPrinciples(status);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const expand = (item: PropositionItemModel) => {
    setExpandedId((prev) => (prev === item.id ? "" : item.id));
    setDrafts((prev) => ({ ...prev, [item.id]: draftOf(item) }));
  };

  const patchDraft = (id: string, key: keyof ItemDraft, value: string) => {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], [key]: value } }));
  };

  const saveModel = async (id: string) => {
    const d = drafts[id];
    if (!d) return;
    setSavingId(id);
    setError("");
    setNotice("");
    const patch: PropositionItemModelPatch = {
      title: d.title,
      chapter: d.chapter,
      solution_template: d.solution_template,
      answer_expr: d.answer_expr,
      unknown: d.unknown,
      answer_select: d.answer_select as PropositionItemModelPatch["answer_select"],
      difficulty: d.difficulty,
      status: d.status as PropositionItemModelPatch["status"],
    };
    try {
      await api.patch<PropositionItemModel>(`/api/proposition/item-models/${id}`, patch);
      await loadModels();
      setNotice("母题已保存（模板已通过 sympy 试解析）。");
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSavingId("");
    }
  };

  const reviewPrinciple = async (p: PropositionPrinciple, action: "confirm" | "reject") => {
    let rationale = "";
    if (action === "reject") {
      const input = window.prompt(`驳回原因（可选）：\n${p.statement}`);
      if (input === null) return;
      rationale = input;
    }
    setReviewingId(p.id);
    setError("");
    setNotice("");
    try {
      await api.post(`/api/proposition/principles/${p.id}/review`, { action, rationale });
      await loadPrinciples(principleFilter);
      setNotice(action === "confirm" ? "规律已确认，之后会注入出题提示词。" : "规律已驳回（终态）。");
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setReviewingId("");
    }
  };

  const statusTone = (status: string) =>
    status === "confirmed" ? "done" : status === "rejected" || status === "archived" ? "warn" : "neutral";

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-6">
        <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">PROPOSITION KB</div>
        <h1 className="mb-2 text-[27px] font-bold tracking-tight">命题知识库</h1>
        <p className="max-w-[760px] text-[13px] leading-relaxed text-muted">
          母题补录参数化解法模板后，同构变式的答案由 sympy 机械求解，不再依赖模型重复推理；
          质量回流聚类出的命题规律经确认后注入出题提示词，提高典型性与模仿能力。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-xl border border-[#c8ecd9] bg-[#f2fcf7] px-4 py-3 text-[12px] text-[#128b78]">
          {notice}
        </div>
      )}

      {/* 母题 */}
      <Card
        title={`母题（${models?.total ?? 0}）`}
        desc={
          models
            ? `已具备可求解模板 ${models.solvable} · 存在同母题不同答案证据 ${models.conflicts}（排在最前，优先补录）`
            : "加载中…"
        }
      >
        {loading ? (
          <Empty>加载中…</Empty>
        ) : !models || models.items.length === 0 ? (
          <Empty>还没有母题。可先在生成试卷后通过 POST /api/proposition/item-models/extract 抽取，或等质量回流积累。</Empty>
        ) : (
          <div className="grid gap-3">
            {models.items.map((item) => {
              const hasTemplate = item.solution_template.trim() !== "";
              const expanded = expandedId === item.id;
              return (
                <div key={item.id} className="rounded-xl border border-line bg-[#fbfcff] px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => expand(item)}
                      className="min-w-0 flex-1 text-left text-[13px] font-semibold text-ink hover:text-brand"
                    >
                      {expanded ? "▾" : "▸"} {item.title || "（未命名母题）"}
                    </button>
                    <Badge tone="neutral">{item.domain_key || "general"}</Badge>
                    <Badge tone={statusTone(item.status)}>{STATUS_LABELS[item.status] ?? item.status}</Badge>
                    {hasTemplate ? (
                      <Badge tone="done">模板就绪</Badge>
                    ) : (
                      <Badge tone="warn">缺模板</Badge>
                    )}
                  </div>
                  {expanded && drafts[item.id] && (
                    <div className="mt-3 grid gap-x-4 md:grid-cols-2">
                      <Field label="标题">
                        <input
                          className={inputCls}
                          value={drafts[item.id].title}
                          onChange={(e) => patchDraft(item.id, "title", e.target.value)}
                        />
                      </Field>
                      <Field label="章节">
                        <input
                          className={inputCls}
                          value={drafts[item.id].chapter}
                          onChange={(e) => patchDraft(item.id, "chapter", e.target.value)}
                        />
                      </Field>
                      <Field label="参数化解法模板（sympy 可解析，必填才能产变式）">
                        <textarea
                          className={`${inputCls} min-h-[80px] font-mono text-[12px]`}
                          value={drafts[item.id].solution_template}
                          onChange={(e) => patchDraft(item.id, "solution_template", e.target.value)}
                        />
                      </Field>
                      <Field label="答案表达式（与模板变量一致）">
                        <textarea
                          className={`${inputCls} min-h-[80px] font-mono text-[12px]`}
                          value={drafts[item.id].answer_expr}
                          onChange={(e) => patchDraft(item.id, "answer_expr", e.target.value)}
                        />
                      </Field>
                      <Field label="未知量符号（多解时必填）">
                        <input
                          className={inputCls}
                          value={drafts[item.id].unknown}
                          onChange={(e) => patchDraft(item.id, "unknown", e.target.value)}
                        />
                      </Field>
                      <Field label="多解选取规则">
                        <select
                          className={inputCls}
                          value={drafts[item.id].answer_select}
                          onChange={(e) => patchDraft(item.id, "answer_select", e.target.value)}
                        >
                          {ANSWER_SELECTS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label="难度">
                        <input
                          className={inputCls}
                          value={drafts[item.id].difficulty}
                          onChange={(e) => patchDraft(item.id, "difficulty", e.target.value)}
                        />
                      </Field>
                      <Field label="状态">
                        <select
                          className={inputCls}
                          value={drafts[item.id].status}
                          onChange={(e) => patchDraft(item.id, "status", e.target.value)}
                        >
                          <option value="draft">草稿</option>
                          <option value="confirmed">已确认</option>
                          <option value="archived">已归档</option>
                        </select>
                      </Field>
                      <div className="md:col-span-2">
                        <Button onClick={() => saveModel(item.id)} disabled={savingId === item.id}>
                          {savingId === item.id ? "保存中…" : "保存（提交前 sympy 试解析）"}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* 命题规律 */}
      <div className="mt-6">
        <Card
          title="命题规律"
          desc={
            principles
              ? `confirmed ${principles.confirmed} · proposed ${principles.proposed} · rejected ${principles.rejected}（只有 confirmed 会注入提示词）`
              : "加载中…"
          }
          actions={
            <select
              className={`${inputCls} w-[130px] py-1.5 text-[12px]`}
              value={principleFilter}
              onChange={(e) => void changePrincipleFilter(e.target.value)}
            >
              {PRINCIPLE_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          }
        >
          {!principles || principles.items.length === 0 ? (
            <Empty>
              {principleFilter === "proposed"
                ? "没有待处理的规律。质量回流累计同类缺陷后，POST /api/proposition/distill 会聚类出候选规律。"
                : "该状态下没有规律。"}
            </Empty>
          ) : (
            <div className="grid gap-3">
              {principles.items.map((p) => (
                <div key={p.id} className="rounded-xl border border-line bg-[#fbfcff] px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="neutral">{p.domain_name || p.domain_key || "general"}</Badge>
                    <Badge tone={statusTone(p.status)}>{STATUS_LABELS[p.status] ?? p.status}</Badge>
                    <span className="text-[11px] text-muted">证据 {p.evidence_count} 次</span>
                    {p.principle_type === "discipline" && <Badge tone="active">学科</Badge>}
                  </div>
                  <p className="mt-2 text-[13px] leading-relaxed text-[#39455d]">{p.statement}</p>
                  {p.status === "proposed" && (
                    <div className="mt-3 flex gap-2">
                      <Button onClick={() => reviewPrinciple(p, "confirm")} disabled={reviewingId === p.id}>
                        {reviewingId === p.id ? "处理中…" : "确认"}
                      </Button>
                      <Button variant="secondary" onClick={() => reviewPrinciple(p, "reject")} disabled={reviewingId === p.id}>
                        驳回
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
