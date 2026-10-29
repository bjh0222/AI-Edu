"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card, inputCls } from "@/components/ui";
import type { FormatSpec, FormatSpecDeliverable } from "@/lib/types";

type Draft = Omit<FormatSpec, "id" | "version" | "created_at" | "updated_at">;

const EMPTY: Draft = {
  name: "",
  description: "",
  scene: "",
  is_builtin: false,
  is_default: false,
  applicable_tasks: "",
  applicable_intents: [],
  excluded_scenarios: [],
  excluded_intents: [],
  trigger_keywords: [],
  excluded_keywords: [],
  allow_keyword_trigger: true,
  allow_semantic_recommendation: true,
  allow_explicit_selection: true,
  target_reader: "",
  output_goal: "",
  deliverables: [],
  content_structure: "",
  format_rules: "",
  required_rules: "",
  forbidden_rules: "",
  suggested_rules: "",
  flexible_rules: "",
  acceptance_criteria: "",
  reference_examples: "",
  custom_markdown: "",
};

function errorText(e: unknown) {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}

const lines = (value: string[]) => value.join("\n");
const list = (value: string) =>
  value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);

function previewMarkdown(spec: Draft) {
  const deliverables = spec.deliverables.length
    ? spec.deliverables.map((item) => `- ${item.name}（${item.status}）`).join("\n")
    : "- 未配置结构化交付物";
  const triggers = spec.trigger_keywords.length ? spec.trigger_keywords.join("、") : "未启用";
  return [
    `# ${spec.name}`,
    "",
    spec.description,
    "",
    "## 输出目标",
    spec.output_goal || spec.description || "未填写",
    "",
    "## 交付物",
    deliverables,
    "",
    "## 结构与规则",
    spec.content_structure,
    spec.format_rules,
    spec.required_rules,
    spec.forbidden_rules,
    "",
    "## 触发设置",
    `触发关键词：${triggers}`,
    "",
    "## 自定义补充规则",
    spec.custom_markdown || "无",
  ].join("\n");
}

export default function FormatSpecs() {
  const [specs, setSpecs] = useState<FormatSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [mode, setMode] = useState<"form" | "markdown">("form");
  const [showPreview, setShowPreview] = useState(false);
  const [draft, setDraft] = useState<Draft>(EMPTY);

  const load = async () => {
    try {
      const data = await api.get<FormatSpec[]>("/api/format-specs");
      setSpecs(data);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Initial fetch synchronizes React state with the backend.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  const startCreate = () => {
    setEditingId("new");
    setDraft({ ...EMPTY });
    setMode("form");
    setShowPreview(false);
  };

  const startEdit = (spec: FormatSpec) => {
    const rest: Draft = { ...spec };
    setEditingId(spec.id);
    setDraft(rest);
    setMode("form");
    setShowPreview(false);
  };

  const patch = (key: keyof Draft, value: unknown) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const patchDeliverable = (index: number, key: keyof FormatSpecDeliverable, value: unknown) => {
    setDraft((current) => {
      const deliverables = [...current.deliverables];
      deliverables[index] = { ...deliverables[index], [key]: value };
      return { ...current, deliverables };
    });
  };

  const addDeliverable = () => {
    patch("deliverables", [
      ...draft.deliverables,
      { name: "", description: "", status: "required", primary: true, order: draft.deliverables.length + 1, allow_override: true },
    ]);
  };

  const removeDeliverable = (index: number) => {
    patch("deliverables", draft.deliverables.filter((_, idx) => idx !== index));
  };

  const save = async () => {
    if (!draft.name.trim()) {
      setError("请填写规范名称");
      return;
    }
    if (!draft.output_goal.trim() && !draft.description.trim()) {
      setError("请填写用途描述或输出目标");
      return;
    }
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const body = { ...draft };
      const saved = editingId === "new"
        ? await api.post<FormatSpec>("/api/format-specs", body)
        : await api.put<FormatSpec>(`/api/format-specs/${editingId}`, body);
      setSpecs((current) => [
        saved,
        ...current.filter((item) => item.id !== saved.id),
      ]);
      setEditingId(saved.id);
      setDraft(saved);
      setNotice("规范已保存。");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };

  const duplicate = async (spec: FormatSpec) => {
    setBusy(spec.id);
    try {
      const saved = await api.post<FormatSpec>(`/api/format-specs/${spec.id}/duplicate`);
      await load();
      setNotice(`已复制为「${saved.name}」。`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };

  const makeDefault = async (spec: FormatSpec) => {
    setBusy(spec.id);
    try {
      const saved = await api.post<FormatSpec>(`/api/format-specs/${spec.id}/default`);
      await load();
      setNotice(`「${saved.name}」已设为默认规范。`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };

  const remove = async (spec: FormatSpec) => {
    if (!window.confirm(`删除「${spec.name}」？历史任务的规范快照仍会保留。`)) return;
    setBusy(spec.id);
    try {
      await api.del(`/api/format-specs/${spec.id}`);
      if (editingId === spec.id) setEditingId(null);
      await load();
      setNotice("规范已删除。");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Card title="格式规范" desc="保存可复用的交付结构、边界和验收条件，生成任务可自动或手动调用。">
      <div className="grid gap-4">
        {error && <div className="rounded-lg border border-[#f3c4c4] bg-[#fff5f5] px-3 py-2 text-[12px] text-[#a33]">{error}</div>}
        {notice && <div className="rounded-lg border border-[#c6eee4] bg-[#f0fbf8] px-3 py-2 text-[12px] text-[#128b78]">{notice}</div>}

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={startCreate}>新建规范</Button>
          {editingId && (
            <>
              <Button variant="secondary" onClick={() => setEditingId(null)}>关闭编辑</Button>
              <Button onClick={() => void save()} disabled={busy === "save"}>
                {busy === "save" ? "保存中…" : "保存"}
              </Button>
            </>
          )}
        </div>

        {loading ? (
          <div className="text-[12px] text-muted">加载中…</div>
        ) : (
          <div className="grid gap-3">
            {specs.map((spec) => (
              <div key={spec.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-[180px]">
                    <div className="flex items-center gap-2 text-[13px] font-bold">
                      {spec.name}
                      {spec.is_default && <Badge tone="done">默认</Badge>}
                      {spec.is_builtin && <Badge tone="active">内置</Badge>}
                    </div>
                    <div className="mt-1 text-[11px] text-muted">{spec.description || "未填写说明"}</div>
                    <div className="mt-1 text-[11px] text-muted">
                      适用场景：{spec.applicable_tasks || "未填写"} · 关键词：{spec.trigger_keywords.join("、") || "无"}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => startEdit(spec)}>编辑</Button>
                    <Button variant="secondary" onClick={() => void duplicate(spec)} disabled={busy === spec.id}>复制</Button>
                    {!spec.is_default && (
                      <Button variant="secondary" onClick={() => void makeDefault(spec)} disabled={busy === spec.id}>设为默认</Button>
                    )}
                    <Button variant="secondary" onClick={() => void remove(spec)} disabled={busy === spec.id}>删除</Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {editingId && (
          <div className="grid gap-3 rounded-lg border border-line p-3">
            <div className="flex items-center gap-2">
              <select aria-label="编辑模式" className={inputCls} value={mode} onChange={(e) => setMode(e.target.value as "form" | "markdown")}>
                <option value="form">表单模式</option>
                <option value="markdown">Markdown 模式</option>
              </select>
              <Button variant="secondary" onClick={() => setShowPreview((v) => !v)}>{showPreview ? "隐藏预览" : "预览"}</Button>
            </div>

            {mode === "form" ? (
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-[12px]">名称<input className={inputCls} value={draft.name} onChange={(e) => patch("name", e.target.value)} /></label>
                <label className="text-[12px]">场景标识<input className={inputCls} value={draft.scene} onChange={(e) => patch("scene", e.target.value)} /></label>
                <label className="text-[12px] md:col-span-2">用途描述<textarea className={inputCls} rows={2} value={draft.description} onChange={(e) => patch("description", e.target.value)} /></label>
                <label className="text-[12px]">适用任务<textarea className={inputCls} rows={2} value={draft.applicable_tasks} onChange={(e) => patch("applicable_tasks", e.target.value)} /></label>
                <label className="text-[12px]">输出目标<textarea className={inputCls} rows={2} value={draft.output_goal} onChange={(e) => patch("output_goal", e.target.value)} /></label>
                <label className="text-[12px]">触发关键词（每行一个）<textarea className={inputCls} rows={4} value={lines(draft.trigger_keywords)} onChange={(e) => patch("trigger_keywords", list(e.target.value))} /></label>
                <label className="text-[12px]">排除关键词（每行一个）<textarea className={inputCls} rows={4} value={lines(draft.excluded_keywords)} onChange={(e) => patch("excluded_keywords", list(e.target.value))} /></label>
                <div className="text-[12px] md:col-span-2">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="font-semibold text-ink">交付物清单</span>
                    <Button variant="secondary" onClick={addDeliverable}>新增交付物</Button>
                  </div>
                  {draft.deliverables.map((item, index) => (
                    <div key={index} className="mb-2 grid gap-2 rounded-lg border border-line p-2 md:grid-cols-[2fr_1fr_80px_auto]">
                      <input className={inputCls} placeholder="交付物名称" value={item.name} onChange={(e) => patchDeliverable(index, "name", e.target.value)} />
                      <select aria-label={`交付物状态：${item.name || index + 1}`} className={inputCls} value={item.status} onChange={(e) => patchDeliverable(index, "status", e.target.value)}>
                        <option value="required">必须</option>
                        <option value="on_request">用户要求时</option>
                        <option value="optional">可选</option>
                        <option value="forbidden">禁止</option>
                      </select>
                      <input className={inputCls} type="number" min={1} value={item.order} onChange={(e) => patchDeliverable(index, "order", Number(e.target.value))} />
                      <Button variant="secondary" onClick={() => removeDeliverable(index)}>移除</Button>
                      <label className="flex items-center gap-2 text-[11px]"><input type="checkbox" checked={item.primary} onChange={(e) => patchDeliverable(index, "primary", e.target.checked)} />主交付物</label>
                      <label className="flex items-center gap-2 text-[11px]"><input type="checkbox" checked={item.allow_override} onChange={(e) => patchDeliverable(index, "allow_override", e.target.checked)} />允许本次覆盖</label>
                    </div>
                  ))}
                </div>
                <label className="text-[12px]">内容结构<textarea className={inputCls} rows={6} value={draft.content_structure} onChange={(e) => patch("content_structure", e.target.value)} /></label>
                <label className="text-[12px]">格式与表达<textarea className={inputCls} rows={4} value={draft.format_rules} onChange={(e) => patch("format_rules", e.target.value)} /></label>
                <label className="text-[12px]">必须遵守<textarea className={inputCls} rows={4} value={draft.required_rules} onChange={(e) => patch("required_rules", e.target.value)} /></label>
                <label className="text-[12px]">禁止出现<textarea className={inputCls} rows={4} value={draft.forbidden_rules} onChange={(e) => patch("forbidden_rules", e.target.value)} /></label>
                <label className="text-[12px]">验收标准<textarea className={inputCls} rows={4} value={draft.acceptance_criteria} onChange={(e) => patch("acceptance_criteria", e.target.value)} /></label>
                <label className="text-[12px]">自定义补充规则（独立保存，切换模式不覆盖）<textarea className={inputCls} rows={5} value={draft.custom_markdown} onChange={(e) => patch("custom_markdown", e.target.value)} /></label>
                <div className="flex flex-wrap gap-3 text-[12px]">
                  <label className="flex items-center gap-2"><input type="checkbox" checked={draft.allow_keyword_trigger} onChange={(e) => patch("allow_keyword_trigger", e.target.checked)} />允许关键词触发</label>
                  <label className="flex items-center gap-2"><input type="checkbox" checked={draft.allow_semantic_recommendation} onChange={(e) => patch("allow_semantic_recommendation", e.target.checked)} />允许语义推荐</label>
                  <label className="flex items-center gap-2"><input type="checkbox" checked={draft.allow_explicit_selection} onChange={(e) => patch("allow_explicit_selection", e.target.checked)} />允许明确指定</label>
                  <label className="flex items-center gap-2"><input type="checkbox" checked={draft.is_default} onChange={(e) => patch("is_default", e.target.checked)} />设为默认规范</label>
                </div>
              </div>
            ) : (
              <label className="text-[12px]">
                Markdown 补充规则
                <textarea className={`${inputCls} min-h-[320px] font-mono`} value={draft.custom_markdown} onChange={(e) => patch("custom_markdown", e.target.value)} />
              </label>
            )}

            {showPreview && (
              <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg bg-[#f7f8fb] p-3 text-[12px]">{previewMarkdown(draft)}</pre>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
