"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { ConceptDetail, GraphData, GraphNode, NavData } from "@/lib/types";
import { Badge, Button, Card, Empty, DemoNotice } from "@/components/ui";
import GraphCanvas, { RELATION_TYPE_META } from "@/components/knowledge/GraphCanvas";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

const MASTERY_META: Record<string, { label: string; tone: "done" | "warn" | "neutral"; hint: string }> = {
  mastered: { label: "有掌握证据", tone: "done", hint: "存在低辅助独立完成的实践尝试" },
  practicing: { label: "练习中", tone: "warn", hint: "已有实践尝试，尚无低辅助独立完成记录" },
  no_evidence: { label: "缺学习证据", tone: "neutral", hint: "尚无实践 / 评估证据，教程生成 ≠ 掌握" },
};

const STATUS_META: Record<string, { label: string; tone: "done" | "warn" | "neutral" | "demo" }> = {
  proposed: { label: "待核实", tone: "warn" },
  confirmed: { label: "已确认", tone: "done" },
  conflict: { label: "存在冲突", tone: "demo" },
  rejected: { label: "已驳回", tone: "neutral" },
  revoked: { label: "已撤销", tone: "neutral" },
};

function KnowledgePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const scopeDomain = searchParams.get("domain") ?? "";
  const scopeGoal = searchParams.get("goal") ?? "";

  const [nav, setNav] = useState<NavData | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [detail, setDetail] = useState<ConceptDetail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [query, setQuery] = useState("");
  const [hideProposed, setHideProposed] = useState(false);
  const [showGoals, setShowGoals] = useState(true);
  const [editingRel, setEditingRel] = useState<{ id: string; type: string; rationale: string } | null>(null);
  const [demo, setDemo] = useState(false);

  const setScope = (domain: string, goal: string) => {
    const params = new URLSearchParams();
    if (domain) params.set("domain", domain);
    if (goal) params.set("goal", goal);
    router.push(`/knowledge${params.toString() ? `?${params.toString()}` : ""}`);
  };

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (scopeDomain) params.set("domain", scopeDomain);
      if (scopeGoal) params.set("goal_id", scopeGoal);
      const qs = params.toString();
      setGraph(await api.get<GraphData>(`/api/knowledge/graph${qs ? `?${qs}` : ""}`));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, [scopeDomain, scopeGoal]);

  const loadNav = useCallback(async () => {
    try {
      setNav(await api.get<NavData>("/api/knowledge/nav"));
    } catch (e) {
      setError(errMsg(e));
    }
    try {
      const health = await api.get<{ demo: boolean }>("/api/health");
      setDemo(health.demo);
    } catch {
      /* 健康检查失败不阻塞页面 */
    }
  }, []);

  useEffect(() => {
    // 挂载 / 范围变化时加载图谱与导航（对异步 setState 误报的规则豁免）
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadNav();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadGraph();
    setSelected(null);
    setDetail(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeDomain, scopeGoal]);

  const loadDetail = useCallback(async (nodeId: string) => {
    setBusy("detail");
    try {
      if (nodeId.startsWith("goal:")) {
        setDetail(null);
        return;
      }
      setDetail(await api.get<ConceptDetail>(`/api/knowledge/concepts/${nodeId}`));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  }, []);

  const onSelect = (id: string | null) => {
    setSelected(id);
    if (id && !id.startsWith("goal:")) void loadDetail(id);
    if (!id) setDetail(null);
  };

  // ------------------------------------------------------------ derived
  const visibleEdges = useMemo(() => {
    if (!graph) return [];
    let edges = [...graph.edges, ...(showGoals ? graph.goal_edges : [])];
    if (hideProposed) edges = edges.filter((e) => e.status !== "proposed");
    return edges;
  }, [graph, hideProposed, showGoals]);

  const canvasNodes = useMemo(() => {
    if (!graph) return [];
    const kept = new Set<string>();
    for (const e of visibleEdges) {
      kept.add(e.source);
      kept.add(e.target);
    }
    return graph.nodes.filter((n) => (n.type === "goal" ? showGoals && kept.has(n.id) : kept.has(n.id)));
  }, [graph, visibleEdges, showGoals]);

  const highlight = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return canvasNodes.filter((n) => n.title.toLowerCase().includes(q)).map((n) => n.id);
  }, [canvasNodes, query]);

  const selectedNode: GraphNode | null = useMemo(
    () => graph?.nodes.find((n) => n.id === selected) ?? null,
    [graph, selected]
  );

  const relationAction = async (relationId: string, status: string) => {
    setBusy(relationId);
    setError("");
    try {
      await api.patch(`/api/knowledge/relations/${relationId}`, { status });
      if (selected) await loadDetail(selected);
      await loadGraph();
      await loadNav();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const relationEdit = async (relationId: string, relationType: string, rationale: string) => {
    setBusy(relationId);
    setError("");
    try {
      await api.patch(`/api/knowledge/relations/${relationId}`, { relation_type: relationType, rationale });
      setEditingRel(null);
      if (selected) await loadDetail(selected);
      await loadGraph();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const scopeName = scopeGoal
    ? nav?.domains.flatMap((d) => d.goals).find((g) => g.id === scopeGoal)?.title ?? "学习目标图谱"
    : scopeDomain
      ? nav?.domains.find((d) => d.key === scopeDomain)?.name ?? "领域图谱"
      : "全局知识网络";

  const emptyGraph = graph && graph.nodes.length === 0 && !loading;

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">KNOWLEDGE NETWORK</div>
          <h1 className="text-[26px] font-bold tracking-tight">{scopeName}</h1>
          <p className="mt-1 max-w-[720px] text-[12px] leading-relaxed text-muted">
            图谱来自真实持久化的概念与关系：教程生成后自动更新；实线为已确认关系，虚线为待核实关系；
            节点描边表示掌握证据状态。关系可信度与掌握状态是两个独立维度。
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted">
          {graph && (
            <>
              <Badge tone="active">{graph.stats.concepts} 概念</Badge>
              <Badge tone="neutral">{graph.stats.relations} 关系</Badge>
              <Badge tone="neutral">{graph.stats.goals} 目标</Badge>
            </>
          )}
          {(scopeDomain || scopeGoal) && (
            <Button variant="secondary" onClick={() => setScope("", "")}>
              返回全局视图
            </Button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}
      <DemoNotice show={demo}>当前为演示模式数据，配置真实模型后内容更完整。</DemoNotice>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="grid gap-4">
          <Card
            title="图谱"
            desc={loading ? "加载中…" : `${canvasNodes.length} 个节点 · ${visibleEdges.length} 条边`}
            actions={
              <input
                className="w-[180px] rounded-[10px] border border-line bg-[#fbfcff] px-3 py-1.5 text-[12px] outline-none focus:border-[#a69dff]"
                placeholder="搜索节点…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            }
          >
            <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={hideProposed} onChange={(e) => setHideProposed(e.target.checked)} />
                只看已确认关系
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={showGoals} onChange={(e) => setShowGoals(e.target.checked)} />
                显示学习目标节点
              </label>
              <span className="ml-2 flex items-center gap-2">
                {Object.entries(MASTERY_META).map(([k, m]) => (
                  <span key={k} className="flex items-center gap-1">
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-full"
                      style={{
                        background: k === "mastered" ? "#128b78" : k === "practicing" ? "#c47b12" : "#c9d2e3",
                      }}
                    />
                    {m.label}
                  </span>
                ))}
              </span>
            </div>
            {loading ? (
              <Empty>图谱加载中…</Empty>
            ) : emptyGraph ? (
              <Empty>
                这个范围还没有知识节点。创建学习目标并生成教程后，知识网络会自动生长。
              </Empty>
            ) : (
              <GraphCanvas
                nodes={canvasNodes}
                edges={visibleEdges}
                selectedId={selected}
                highlight={highlight}
                onSelect={onSelect}
              />
            )}
          </Card>

          <Card title="关系类型与筛选" desc="关系有明确语义与方向；点击图例可在当前视图中筛选">
            <div className="flex flex-wrap gap-2">
              {graph &&
                Object.entries(graph.relation_types)
                  .filter(([k]) => k !== "goal_covers")
                  .map(([key, label]) => {
                    const count = visibleEdges.filter((e) => e.relation_type === key).length;
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] ${
                          count
                            ? "border-line bg-white text-[#39455d]"
                            : "border-line bg-[#f6f7fb] text-[#aab4c6]"
                        }`}
                        title={label}
                      >
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ background: RELATION_TYPE_META[key]?.color ?? "#9aa7bd" }}
                        />
                        {label} · {count}
                      </button>
                    );
                  })}
            </div>
          </Card>
        </div>

        {/* ---------------- 详情面板 ---------------- */}
        <div className="grid content-start gap-4">
          <Card title="范围导航" desc="目录来自你的学习目标与领域，动态生成">
            <div className="grid gap-1.5 text-[12px]">
              <button
                type="button"
                onClick={() => setScope("", "")}
                className={`rounded-lg px-2.5 py-1.5 text-left ${
                  !scopeDomain && !scopeGoal ? "bg-[#f0edff] font-semibold text-brand" : "hover:bg-[#f6f7fb]"
                }`}
              >
                全局网络（含跨领域联系）{nav ? ` · ${nav.totals.concepts}` : ""}
              </button>
              {(nav?.domains ?? []).map((d) => (
                <div key={d.key}>
                  <button
                    type="button"
                    onClick={() => setScope(d.key, "")}
                    className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left ${
                      scopeDomain === d.key && !scopeGoal
                        ? "bg-[#f0edff] font-semibold text-brand"
                        : "hover:bg-[#f6f7fb]"
                    }`}
                  >
                    <span>
                      {d.name}
                    </span>
                    <span className="text-[10px] text-muted">{d.concept_count} 概念</span>
                  </button>
                  {d.goals.length > 0 && (
                    <div className="ml-3 mt-1 grid gap-1 border-l border-line pl-2">
                      {d.goals.map((g) => (
                        <button
                          key={g.id}
                          type="button"
                          onClick={() => setScope(d.key, g.id)}
                          className={`rounded-lg px-2 py-1 text-left text-[11px] ${
                            scopeGoal === g.id ? "bg-[#f0edff] font-semibold text-brand" : "text-muted hover:bg-[#f6f7fb]"
                          }`}
                        >
                          {g.title}
                          <span className="ml-1 text-[10px] text-[#aab4c6]">{g.concept_count}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {nav && nav.domains.length === 0 && <Empty>还没有学习目标。先创建一个目标并生成教程。</Empty>}
            </div>
          </Card>

          {selectedNode?.type === "goal" && (
            <Card title="学习目标" desc="图谱中的目标节点">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-[14px] font-bold">{selectedNode.title}</div>
                {selectedNode.status === "archived" && <Badge tone="neutral">已归档</Badge>}
              </div>
              <div className="mt-1 text-[11px] text-muted">
                领域：{selectedNode.domain_name} ｜ 关联概念 {selectedNode.degree} 个
                {selectedNode.status === "archived" && " ｜ 该目标已归档，其知识仍保留在学习记录中"}
              </div>
              <div className="mt-3">
                <Link
                  href={`/goals/${selectedNode.ref_id}`}
                  className="text-[12px] font-semibold text-brand hover:underline"
                >
                  进入目标工作台 →
                </Link>
              </div>
            </Card>
          )}

          {selectedNode?.type === "concept" && (
            <Card
              title={selectedNode.title}
              desc={busy === "detail" ? "加载详情…" : `${selectedNode.domain_name}${detail?.aliases.length ? ` · 别名：${detail.aliases.join("、")}` : ""}`}
              actions={
                <Button variant="ghost" onClick={() => onSelect(null)}>
                  关闭
                </Button>
              }
            >
              {detail ? (
                <div className="grid gap-3 text-[12px]">
                  {detail.definition && (
                    <p className="rounded-xl bg-[#f8f9fd] p-3 leading-relaxed text-[#39455d]">{detail.definition}</p>
                  )}

                  <div>
                    <div className="mb-1 font-bold">掌握状态（证据驱动）</div>
                    <div className="flex items-center gap-2">
                      <Badge tone={MASTERY_META[detail.mastery.status]?.tone ?? "neutral"}>
                        {MASTERY_META[detail.mastery.status]?.label ?? detail.mastery.status}
                      </Badge>
                      <span className="text-[11px] text-muted">{detail.mastery.basis}</span>
                    </div>
                  </div>

                  {detail.goals.length > 0 && (
                    <div>
                      <div className="mb-1 font-bold">服务的学习目标</div>
                      <div className="grid gap-1">
                        {detail.goals.map((g) => (
                          <Link
                            key={g.id}
                            href={`/goals/${g.id}`}
                            className="rounded-lg border border-line px-2.5 py-1.5 text-[11px] hover:border-[#c9c3ff]"
                          >
                            {g.title} →
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}

                  {detail.tutorial_anchors.length > 0 && (
                    <div>
                      <div className="mb-1 font-bold">教程与章节（点击直达）</div>
                      <div className="grid gap-1">
                        {detail.tutorial_anchors.map((a, i) => (
                          <a
                            key={`${a.tutorial_id}-${a.section_id}-${i}`}
                            href={
                              a.section_id
                                ? `/tutorials/${a.tutorial_id}/sections/${a.section_id}`
                                : `/tutorials/${a.tutorial_id}`
                            }
                            className="rounded-lg border border-line px-2.5 py-1.5 text-[11px] hover:border-[#c9c3ff]"
                          >
                            {a.section_title || a.tutorial_title}
                            <span className="ml-1 text-[10px] text-muted">（{a.goal_title}）</span>
                          </a>
                        ))}
                      </div>
                    </div>
                  )}

                  <div>
                    <div className="mb-1 font-bold">关联关系（含待核实 / 已撤销）</div>
                    {detail.relations.length === 0 ? (
                      <Empty>暂无关系。</Empty>
                    ) : (
                      <div className="grid gap-1.5">
                        {detail.relations.map((r) => {
                          const meta = RELATION_TYPE_META[r.relation_type] ?? RELATION_TYPE_META.related;
                          const st = STATUS_META[r.status] ?? { label: r.status, tone: "neutral" as const };
                          const anchor = r.source_refs.find((s) => s.type === "tutorial_section");
                          return (
                            <div key={r.id} className="rounded-xl border border-line p-2.5">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-[11px]">
                                  {r.direction === "out" ? "本概念" : r.other_title}
                                </span>
                                <span
                                  className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
                                  style={{ background: meta.color }}
                                >
                                  {r.direction === "out" ? `${meta.label}→` : `←${meta.label}`}
                                </span>
                                <span className="text-[11px]">
                                  {r.direction === "out" ? r.other_title : "本概念"}
                                </span>
                                <Badge tone={st.tone}>{st.label}</Badge>
                                <span className="ml-auto text-[10px] text-muted">
                                  {r.origin === "tutorial" ? "来自教程" : r.origin === "ai_proposal" ? "AI 提议" : "手动"}
                                </span>
                              </div>
                              {r.rationale && <div className="mt-1 text-[11px] leading-relaxed text-muted">依据：{r.rationale}</div>}
                              {editingRel?.id === r.id ? (
                                <div className="mt-2 grid gap-1.5 rounded-lg bg-[#f8f9fd] p-2">
                                  <select
                                    className="rounded-lg border border-line bg-white px-2 py-1 text-[11px]"
                                    value={editingRel.type}
                                    onChange={(e) => setEditingRel({ ...editingRel, type: e.target.value })}
                                  >
                                    {Object.entries(RELATION_TYPE_META)
                                      .filter(([k]) => k !== "goal_covers")
                                      .map(([k, m]) => (
                                        <option key={k} value={k}>{m.label}</option>
                                      ))}
                                  </select>
                                  <textarea
                                    className="rounded-lg border border-line bg-white px-2 py-1 text-[11px]"
                                    rows={2}
                                    placeholder="关系依据（为什么成立）"
                                    value={editingRel.rationale}
                                    onChange={(e) => setEditingRel({ ...editingRel, rationale: e.target.value })}
                                  />
                                  <div className="flex gap-1.5">
                                    <Button
                                      variant="secondary"
                                      disabled={busy === r.id}
                                      onClick={() => relationEdit(r.id, editingRel.type, editingRel.rationale)}
                                    >
                                      保存
                                    </Button>
                                    <Button variant="ghost" onClick={() => setEditingRel(null)}>
                                      取消
                                    </Button>
                                  </div>
                                </div>
                              ) : (
                                <>
                              {anchor?.section_id && (
                                <a
                                  href={`/tutorials/${anchor.tutorial_id}/sections/${anchor.section_id}`}
                                  className="mt-1 inline-block text-[11px] font-semibold text-brand hover:underline"
                                >
                                  查看依据章节 →
                                </a>
                              )}
                              <div className="mt-1.5 flex flex-wrap gap-1.5">
                                <Button variant="ghost" disabled={busy === r.id} onClick={() => setEditingRel({ id: r.id, type: r.relation_type, rationale: r.rationale })}>
                                  编辑
                                </Button>
                                {r.status === "proposed" && (
                                  <>
                                    <Button variant="secondary" disabled={busy === r.id} onClick={() => relationAction(r.id, "confirmed")}>
                                      确认
                                    </Button>
                                    <Button variant="ghost" disabled={busy === r.id} onClick={() => relationAction(r.id, "rejected")}>
                                      驳回
                                    </Button>
                                  </>
                                )}
                                {(r.status === "confirmed" || r.status === "conflict") && (
                                  <Button variant="ghost" disabled={busy === r.id} onClick={() => relationAction(r.id, "revoked")}>
                                    撤销
                                  </Button>
                                )}
                                {r.status === "confirmed" && (
                                  <Button variant="ghost" disabled={busy === r.id} onClick={() => relationAction(r.id, "conflict")}>
                                    标记冲突
                                  </Button>
                                )}
                                {(r.status === "revoked" || r.status === "rejected") && (
                                  <Button variant="ghost" disabled={busy === r.id} onClick={() => relationAction(r.id, "proposed")}>
                                    重新核实
                                  </Button>
                                )}
                              </div>
                                </>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <Empty>{busy === "detail" ? "加载中…" : "选择节点查看详情"}</Empty>
              )}
            </Card>
          )}

          {!selectedNode && (
            <Card title="节点详情" desc="点击图谱中的节点查看">
              <Empty>
                点击任意概念节点：查看定义、掌握状态依据、教程章节直达入口、前置 / 后续关系，并确认或撤销关系。
              </Empty>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

export default function KnowledgePage() {
  return (
    <Suspense fallback={<div className="px-10 py-8 text-[12px] text-muted">知识网络加载中…</div>}>
      <KnowledgePageInner />
    </Suspense>
  );
}
