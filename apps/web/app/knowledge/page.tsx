"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { Knowledge, Proposal, Relation } from "@/lib/types";
import { Badge, Button, Card, Empty, Field, inputCls } from "@/components/ui";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function KnowledgePage() {
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [title, setTitle] = useState("");
  const [definition, setDefinition] = useState("");
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [relType, setRelType] = useState("prerequisite_of");

  const load = useCallback(async () => {
    try {
      setKnowledge(await api.get<Knowledge>("/api/knowledge"));
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => {
    // 挂载时加载知识网络（与后端 API 同步）；该规则对异步 setState 误报
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const concepts = knowledge?.concepts ?? [];
  const relations = knowledge?.relations ?? [];
  const proposals = (knowledge?.proposals ?? []).filter((p) => p.status === "pending");
  const nameOf = (id: string) => concepts.find((c) => c.id === id)?.title ?? id.slice(0, 6);

  const createConcept = () =>
    run("concept", async () => {
      if (!title.trim()) throw new Error("请填写概念名称");
      await api.post("/api/knowledge/concepts", { title: title.trim(), definition });
      setTitle("");
      setDefinition("");
    });

  const createRelation = () =>
    run("relation", async () => {
      if (!fromId || !toId) throw new Error("请选择起始与目标概念");
      await api.post("/api/knowledge/relations", {
        from_concept_id: fromId,
        to_concept_id: toId,
        relation_type: relType,
      });
    });

  const review = (p: Proposal, action: "confirm" | "reject") =>
    run(`p-${p.id}`, async () => {
      await api.post(`/api/knowledge/proposals/${p.id}/review`, { action });
    });

  const relationTypeLabel: Record<string, string> = {
    prerequisite_of: "先修于",
    part_of: "属于",
    applied_in: "应用于",
    contrasts_with: "对比",
    related: "相关",
  };

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-6">
        <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">KNOWLEDGE NETWORK</div>
        <h1 className="mb-2 text-[27px] font-bold tracking-tight">知识网络</h1>
        <p className="max-w-[700px] text-[13px] leading-relaxed text-muted">
          关系来自实际学习证据；AI 只能提议，确认后才入长期网络。不追求节点数量，追求能帮助复习、定位先修知识与迁移。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="grid gap-4">
          <Card title="概念" desc={`${concepts.length} 个概念`}>
            {concepts.length === 0 ? (
              <Empty>还没有概念。可从目标页生成知识提议，或手动添加。</Empty>
            ) : (
              <div className="grid gap-2">
                {concepts.map((c) => (
                  <div key={c.id} className="rounded-xl border border-line p-3">
                    <div className="flex items-center justify-between gap-2">
                      <b className="text-[12px]">{c.title}</b>
                      <Badge>{c.domain_key === "math_data" ? "数学/数据" : "计算机"}</Badge>
                    </div>
                    {c.definition && <div className="mt-1 text-[11px] leading-relaxed text-muted">{c.definition}</div>}
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 border-t border-line pt-3">
              <div className="mb-2 text-[11px] font-bold text-[#5a6a86]">手动添加概念</div>
              <Field label="概念名称">
                <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
              </Field>
              <Field label="简明定义（可选）">
                <input className={inputCls} value={definition} onChange={(e) => setDefinition(e.target.value)} />
              </Field>
              <Button onClick={createConcept} disabled={busy === "concept"}>
                添加
              </Button>
            </div>
          </Card>

          <Card title="关系" desc={`${relations.length} 条关系`}>
            {relations.length === 0 ? (
              <Empty>还没有关系。</Empty>
            ) : (
              <div className="grid gap-1.5">
                {relations.map((r: Relation) => (
                  <div key={r.id} className="flex items-center gap-2 rounded-lg border border-line p-2.5 text-[11px]">
                    <span>{nameOf(r.from_concept_id)}</span>
                    <span className="rounded bg-[#f0edff] px-1.5 py-0.5 text-[10px] font-semibold text-brand">
                      {relationTypeLabel[r.relation_type] ?? r.relation_type}
                    </span>
                    <span>{nameOf(r.to_concept_id)}</span>
                    <span className="ml-auto">
                      <Badge tone={r.status === "confirmed" ? "done" : r.status === "rejected" ? "warn" : "neutral"}>
                        {r.status === "confirmed" ? "已确认" : r.status === "rejected" ? "已拒绝" : "待确认"}
                      </Badge>
                    </span>
                  </div>
                ))}
              </div>
            )}
            {concepts.length >= 2 && (
              <div className="mt-3 border-t border-line pt-3">
                <div className="mb-2 text-[11px] font-bold text-[#5a6a86]">手动添加关系</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <select className={inputCls} value={fromId} onChange={(e) => setFromId(e.target.value)}>
                    <option value="">起始概念…</option>
                    {concepts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                  <select className={inputCls} value={toId} onChange={(e) => setToId(e.target.value)}>
                    <option value="">目标概念…</option>
                    {concepts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="mt-2 flex gap-2">
                  <select className={inputCls} value={relType} onChange={(e) => setRelType(e.target.value)}>
                    {Object.entries(relationTypeLabel).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                  <Button onClick={createRelation} disabled={busy === "relation"}>
                    添加关系
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>

        <Card title="待确认提议" desc="AI 提议的关系与概念，确认后才成为确定知识">
          {proposals.length === 0 ? (
            <Empty>没有待处理提议。可在目标页的「知识提议」中生成。</Empty>
          ) : (
            <div className="grid gap-2">
              {proposals.map((p) => {
                const payload = p.payload as Record<string, unknown>;
                return (
                  <div key={p.id} className="rounded-xl border border-[#f3e3c4] bg-[#fffaf0] p-3 text-[11px] leading-relaxed">
                    <div className="font-semibold">
                      {payload.title
                        ? `新概念：${String(payload.title)}`
                        : payload.from_title && payload.to_title
                          ? `新关系：${String(payload.from_title)} → ${String(payload.to_title)}（${String(
                              payload.relation_type ?? "related"
                            )}）`
                          : JSON.stringify(payload)}
                    </div>
                    {p.rationale && <div className="mt-1 text-[#8a6411]">依据：{p.rationale}</div>}
                    <div className="mt-2 flex gap-2">
                      <Button variant="secondary" disabled={busy === `p-${p.id}`} onClick={() => review(p, "confirm")}>
                        确认
                      </Button>
                      <Button variant="ghost" disabled={busy === `p-${p.id}`} onClick={() => review(p, "reject")}>
                        拒绝
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          <div className="mt-3 border-t border-line pt-3 text-[11px]">
            <Link href="/" className="font-semibold text-brand hover:underline">
              ← 返回工作台
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
