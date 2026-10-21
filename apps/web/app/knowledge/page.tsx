"use client";

/**
 * 知识网络：图谱即页面。
 *
 * 信息架构（按 UI 规格）：
 * - 顶部 56px 工具栏：范围下拉 + 统计 + 搜索 + 筛选 + 全屏 + 数据管理；
 * - 筛选条 44px：视图预设（聚焦/全部）+ 关系类型 chips + 折叠开关 + 已隐藏；
 * - 图谱铺满剩余视口；详情为右侧覆盖抽屉，不挤压画布；
 * - 全屏为 fixed 覆盖层（同一画布实例，保留位置 / 选中 / 缩放）；
 * - 隐藏 = 本机视图偏好（localStorage）；删除节点 / 清空图谱 = 后端不可逆操作。
 */

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { ConceptDetail, GraphData, GraphNode, NavData } from "@/lib/types";
import { Badge, DemoNotice } from "@/components/ui";
import GraphCanvas, { RELATION_TYPE_META } from "@/components/knowledge/GraphCanvas";

const HIDDEN_KEY = "aiedu.knowledge.hidden";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

const MASTERY_META: Record<string, { label: string; tone: "done" | "warn" | "neutral" }> = {
  mastered: { label: "有掌握证据", tone: "done" },
  practicing: { label: "练习中", tone: "warn" },
  no_evidence: { label: "缺学习证据", tone: "neutral" },
};

const STATUS_META: Record<string, { label: string; tone: "done" | "warn" | "neutral" | "demo" }> = {
  proposed: { label: "待核实", tone: "warn" },
  confirmed: { label: "已确认", tone: "done" },
  conflict: { label: "存在冲突", tone: "demo" },
  rejected: { label: "已驳回", tone: "neutral" },
  revoked: { label: "已撤销", tone: "neutral" },
};

type Preset = "focus" | "all" | "custom";

function loadHidden(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HIDDEN_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function KnowledgeInner() {
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
  const [fullscreen, setFullscreen] = useState(false);
  const [showFilters, setShowFilters] = useState(true);
  const [demo, setDemo] = useState(false);
  const [toast, setToast] = useState<{ msg: string; undo?: () => void } | null>(null);

  // 视图预设：默认「聚焦」，显著降低默认密度
  const [preset, setPreset] = useState<Preset>("focus");
  const [showGoals, setShowGoals] = useState(false);
  const [showProposed, setShowProposed] = useState(false);
  const [showLeaves, setShowLeaves] = useState(false);
  const [relationFilter, setRelationFilter] = useState<string[]>(
    // 「聚焦」默认：隐藏 related 这种弱语义关系
    Object.keys(RELATION_TYPE_META).filter((k) => k !== "goal_covers" && k !== "related")
  );
  const [hidden, setHidden] = useState<string[]>(() => (typeof window === "undefined" ? [] : loadHidden()));
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const [relExpanded, setRelExpanded] = useState<Set<string>>(new Set());

  // 弹层状态
  const [moreOpen, setMoreOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<GraphNode | null>(null);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearInput, setClearInput] = useState("");
  const [editingRel, setEditingRel] = useState<{ id: string; type: string; rationale: string } | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const setScope = (domain: string, goal: string) => {
    const params = new URLSearchParams();
    if (domain) params.set("domain", domain);
    if (goal) params.set("goal", goal);
    router.push(`/knowledge${params.toString() ? `?${params.toString()}` : ""}`);
  };

  const notify = (msg: string, undo?: () => void) => {
    setToast({ msg, undo });
    window.setTimeout(() => setToast((t) => (t?.msg === msg ? null : t)), 6000);
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

  const persistHidden = (next: string[]) => {
    setHidden(next);
    try {
      window.localStorage.setItem(HIDDEN_KEY, JSON.stringify(next));
    } catch {
      /* 隐私模式下忽略 */
    }
  };

  const loadDetail = useCallback(async (nodeId: string) => {
    if (nodeId.startsWith("goal:")) {
      setDetail(null);
      return;
    }
    setBusy("detail");
    try {
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
    else setDetail(null);
  };

  const applyPreset = (next: Preset) => {
    setPreset(next);
    if (next === "focus") {
      setShowGoals(false);
      setShowProposed(false);
      setShowLeaves(false);
      setRelationFilter(
        Object.keys(RELATION_TYPE_META).filter((k) => k !== "goal_covers" && k !== "related")
      );
      setShowFilters(true);
    } else if (next === "all") {
      setShowGoals(true);
      setShowProposed(true);
      setShowLeaves(true);
      setRelationFilter([]);
    }
  };
  const markCustom = () => {
    if (preset !== "custom") setPreset("custom");
  };

  // Esc 关闭浮层；F 全屏；/ 搜索
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (e.key === "Escape") {
        if (moreOpen) setMoreOpen(false);
        else if (clearOpen) setClearOpen(false);
        else if (deleteTarget) setDeleteTarget(null);
        else if (fullscreen) setFullscreen(false);
        else if (selected) onSelect(null);
      } else if (!typing && (e.key === "f" || e.key === "F")) {
        setFullscreen((v) => !v);
      } else if (!typing && e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ------------------------------------------------------------ derived
  const allNodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const hiddenSet = useMemo(() => new Set(hidden), [hidden]);

  const baseEdges = useMemo(() => {
    if (!graph) return [];
    return [...graph.edges, ...(showGoals ? graph.goal_edges : [])].filter((e) => {
      if (!(showProposed || e.status !== "proposed")) return false;
      if (relationFilter.length > 0 && !relationFilter.includes(e.relation_type)) return false;
      if (e.relation_type === "goal_covers" && !showGoals) return false;
      return true;
    });
  }, [graph, showGoals, showProposed, relationFilter]);

  const searchMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return new Set<string>();
    return new Set(allNodes.filter((n) => n.title.toLowerCase().includes(q)).map((n) => n.id));
  }, [allNodes, query]);

  // 搜索时：命中节点 + 一跳邻居临时进入画布（绕过预设，但仍尊重隐藏）
  const { canvasNodes, canvasEdges } = useMemo(() => {
    let edgeList = baseEdges;
    let nodeIds: Set<string>;
    if (searchMatches.size > 0) {
      const keep = new Set(searchMatches);
      for (const e of edgeList) {
        if (searchMatches.has(e.source)) keep.add(e.target);
        if (searchMatches.has(e.target)) keep.add(e.source);
      }
      edgeList = edgeList.filter((e) => keep.has(e.source) && keep.has(e.target));
      nodeIds = keep;
    } else {
      const degree = new Map<string, number>();
      for (const e of edgeList) {
        degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
        degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
      }
      nodeIds = new Set(
        allNodes
          .filter((n) => {
            if (n.type === "goal" && !showGoals) return false;
            if (!degree.has(n.id) && n.type === "concept" && !showLeaves) return false; // 孤立节点默认隐藏
            if (!showLeaves && (degree.get(n.id) ?? 0) <= 1) return false; // 叶节点折叠
            return true;
          })
          .map((n) => n.id)
      );
      edgeList = edgeList.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
    }
    const nodes = allNodes.filter((n) => nodeIds.has(n.id) && !hiddenSet.has(n.id));
    const ids = new Set(nodes.map((n) => n.id));
    return {
      canvasNodes: nodes,
      canvasEdges: edgeList.filter((e) => ids.has(e.source) && ids.has(e.target)),
    };
  }, [allNodes, baseEdges, searchMatches, showGoals, showLeaves, hiddenSet]);

  const selectedNode: GraphNode | null = useMemo(
    () => allNodes.find((n) => n.id === selected) ?? null,
    [allNodes, selected]
  );

  const hiddenNodes = allNodes.filter((n) => hiddenSet.has(n.id));

  // ------------------------------------------------------------ actions
  const relationAction = async (relationId: string, status: string) => {
    setBusy(relationId);
    setError("");
    try {
      await api.patch(`/api/knowledge/relations/${relationId}`, { status });
      if (selected) await loadDetail(selected);
      await loadGraph();
      await loadNav();
    } catch (e) {
      notify(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const relationEdit = async (relationId: string, relationType: string, rationale: string) => {
    setBusy(relationId);
    try {
      await api.patch(`/api/knowledge/relations/${relationId}`, { relation_type: relationType, rationale });
      setEditingRel(null);
      if (selected) await loadDetail(selected);
      await loadGraph();
    } catch (e) {
      notify(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const hideNode = (node: GraphNode) => {
    const next = Array.from(new Set([...hidden, node.id]));
    persistHidden(next);
    onSelect(null);
    notify(`已隐藏「${node.title}」`, () => persistHidden(hidden.filter((x) => x !== node.id)));
  };

  const unhideNode = (id: string) => persistHidden(hidden.filter((x) => x !== id));

  const deleteConcept = async () => {
    if (!deleteTarget) return;
    setBusy("delete");
    try {
      const res = await api.del<{ deleted_relations: number }>(`/api/knowledge/concepts/${deleteTarget.id}`);
      setDeleteTarget(null);
      onSelect(null);
      persistHidden(hidden.filter((x) => x !== deleteTarget.id));
      await loadGraph();
      await loadNav();
      notify(`已删除概念（同时删除 ${res.deleted_relations} 条关系）`);
    } catch (e) {
      notify(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const clearAll = async () => {
    if (clearInput.trim() !== "清空") return;
    setBusy("clear");
    try {
      const res = await api.del<{ deleted_concepts: number; deleted_relations: number; deleted_proposals: number }>(
        "/api/knowledge/graph"
      );
      setClearOpen(false);
      setClearInput("");
      persistHidden([]);
      onSelect(null);
      await loadGraph();
      await loadNav();
      notify(`已清空知识网络（${res.deleted_concepts} 概念 / ${res.deleted_relations} 关系 / ${res.deleted_proposals} 提议）`);
    } catch (e) {
      notify(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const relationTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of graph?.edges ?? []) counts[e.relation_type] = (counts[e.relation_type] ?? 0) + 1;
    return counts;
  }, [graph]);

  // ------------------------------------------------------------ rendering
  const shell = (
    <div className={fullscreen ? "fixed inset-0 z-50 flex flex-col bg-white" : "flex h-[100dvh] flex-col bg-white"}>
      {/* 顶部工具栏 */}
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-[11px] font-bold tracking-[1.2px] text-brand">知识网络</span>
          <select
            className="max-w-[220px] truncate rounded-lg border border-line bg-[#fbfcff] px-2 py-1.5 text-[12px] font-semibold text-[#24324a] outline-none focus:border-[#a69dff]"
            value={scopeGoal ? `goal:${scopeGoal}` : scopeDomain ? `domain:${scopeDomain}` : "global"}
            onChange={(e) => {
              const v = e.target.value;
              if (v === "global") setScope("", "");
              else if (v.startsWith("domain:")) setScope(v.slice(7), "");
              else if (v.startsWith("goal:")) {
                const goalId = v.slice(5);
                const domain = nav?.domains.find((d) => d.goals.some((g) => g.id === goalId))?.key ?? "";
                setScope(domain, goalId);
              }
            }}
          >
            <option value="global">全局网络</option>
            {(nav?.domains ?? []).map((d) => (
              <optgroup key={d.key} label={d.name}>
                <option value={`domain:${d.key}`}>{d.name}（领域）</option>
                {d.goals.map((g) => (
                  <option key={g.id} value={`goal:${g.id}`}>
                    {g.title}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <span className="hidden shrink-0 items-center gap-1.5 text-[10px] text-muted sm:flex">
          <span>
            显示 <b className="text-[#39455d]">{canvasNodes.length}</b>/{allNodes.length} 节点
          </span>
          <span>
            · <b className="text-[#39455d]">{canvasEdges.length}</b>/{graph ? graph.edges.length + (showGoals ? graph.goal_edges.length : 0) : 0} 关系
          </span>
          {hidden.length > 0 && <span className="text-[#c47b12]">· 已隐藏 {hidden.length}</span>}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <input
            ref={searchRef}
            className="w-[130px] rounded-lg border border-line bg-[#fbfcff] px-2.5 py-1.5 text-[12px] outline-none transition-all focus:w-[210px] focus:border-[#a69dff]"
            placeholder="搜索节点…（/）"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className={`hidden rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold md:block ${
              showFilters ? "border-[#c9c3ff] bg-[#f0edff] text-brand" : "border-line text-[#39455d] hover:border-[#c9c3ff]"
            }`}
          >
            筛选
          </button>
          <button
            type="button"
            onClick={() => setFullscreen((v) => !v)}
            title={fullscreen ? "退出全屏（Esc）" : "放大图谱（F）"}
            aria-label={fullscreen ? "退出全屏" : "放大图谱"}
            className="grid h-8 w-8 place-items-center rounded-lg border border-line text-[14px] text-[#39455d] hover:border-[#c9c3ff]"
          >
            {fullscreen ? "⤡" : "⤢"}
          </button>
          <div className="relative">
            <button
              type="button"
              onClick={() => setMoreOpen((v) => !v)}
              aria-label="更多操作"
              className="grid h-8 w-8 place-items-center rounded-lg border border-line text-[14px] text-[#39455d] hover:border-[#c9c3ff]"
            >
              ⋯
            </button>
            {moreOpen && (
              <div className="absolute right-0 top-9 z-30 w-[190px] rounded-xl border border-line bg-white py-1 shadow-lg">
                <button
                  type="button"
                  className="block w-full px-3 py-2 text-left text-[11px] hover:bg-[#f6f7fb]"
                  onClick={async () => {
                    setMoreOpen(false);
                    try {
                      const r = await api.post<{ merged: number }>("/api/knowledge/dedupe");
                      await loadGraph();
                      await loadNav();
                      notify(`去重完成：合并 ${r.merged} 个相似概念`);
                    } catch (e) {
                      notify(errMsg(e));
                    }
                  }}
                >
                  合并相似概念
                </button>
                <button
                  type="button"
                  className="block w-full px-3 py-2 text-left text-[11px] text-[#a33] hover:bg-[#fff5f5]"
                  onClick={() => {
                    setMoreOpen(false);
                    setClearOpen(true);
                  }}
                >
                  清空全部图谱…
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 筛选条 */}
      {showFilters && (
        <div className="flex h-11 shrink-0 items-center gap-1.5 overflow-x-auto border-b border-line px-3 text-[11px]">
          <div className="flex shrink-0 items-center gap-1">
            {(
              [
                ["focus", "聚焦"],
                ["all", "全部"],
                ["custom", "自定义"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => key !== "custom" && applyPreset(key)}
                className={`rounded-md px-2 py-1 font-semibold ${
                  preset === key ? "bg-brand text-white" : "text-[#5a6a86] hover:bg-[#f0edff]"
                } ${key === "custom" && preset !== "custom" ? "cursor-default opacity-40" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="mx-1 h-4 w-px shrink-0 bg-line" />
          {Object.entries(RELATION_TYPE_META)
            .filter(([key]) => key !== "goal_covers")
            .map(([key, meta]) => {
              const count = relationTypeCounts[key] ?? 0;
              const on = relationFilter.length === 0 || relationFilter.includes(key);
              const allTypes = Object.keys(RELATION_TYPE_META).filter((k) => k !== "goal_covers");
              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => {
                    let next: string[];
                    if (relationFilter.length === 0) next = allTypes.filter((k) => k !== key);
                    else if (relationFilter.includes(key)) next = relationFilter.filter((k) => k !== key);
                    else next = [...relationFilter, key];
                    setRelationFilter(next.length === allTypes.length ? [] : next);
                    markCustom();
                  }}
                  className={`shrink-0 rounded-md border px-2 py-1 ${
                    on
                      ? "border-[#d9d5ff] bg-white text-[#39455d]"
                      : "border-dashed border-line bg-[#f6f7fb] text-[#aab4c6]"
                  }`}
                >
                  <span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: meta.color }} />
                  {meta.label} {count}
                </button>
              );
            })}
          <span className="mx-1 h-4 w-px shrink-0 bg-line" />
          <label className="flex shrink-0 items-center gap-1">
            <input type="checkbox" checked={showGoals} onChange={(e) => { setShowGoals(e.target.checked); markCustom(); }} />
            目标节点
          </label>
          <label className="flex shrink-0 items-center gap-1">
            <input type="checkbox" checked={showProposed} onChange={(e) => { setShowProposed(e.target.checked); markCustom(); }} />
            待核实
          </label>
          <label className="flex shrink-0 items-center gap-1">
            <input type="checkbox" checked={showLeaves} onChange={(e) => { setShowLeaves(e.target.checked); markCustom(); }} />
            叶节点
          </label>
          {hidden.length > 0 && (
            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => setHiddenOpen((v) => !v)}
                className="rounded-md px-2 py-1 text-[#c47b12] hover:bg-[#fff3e4]"
              >
                已隐藏 {hidden.length}
              </button>
              {hiddenOpen && (
                <div className="absolute left-0 top-8 z-30 w-[220px] rounded-xl border border-line bg-white p-2 shadow-lg">
                  <div className="mb-1 text-[10px] text-muted">仅本机视图隐藏，可随时恢复</div>
                  <div className="grid max-h-[180px] gap-1 overflow-y-auto">
                    {hiddenNodes.map((n) => (
                      <button
                        key={n.id}
                        type="button"
                        onClick={() => unhideNode(n.id)}
                        className="flex items-center justify-between rounded-md px-2 py-1 text-left text-[11px] hover:bg-[#f6f7fb]"
                      >
                        <span className="truncate">{n.title}</span>
                        <span className="text-brand">恢复</span>
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={() => persistHidden([])}
                    className="mt-1 w-full rounded-md bg-[#f6f7fb] px-2 py-1 text-[11px] font-semibold text-[#39455d]"
                  >
                    全部恢复
                  </button>
                </div>
              )}
            </div>
          )}
          <button type="button" onClick={() => applyPreset("focus")} className="shrink-0 rounded-md px-2 py-1 text-[#5a6a86] hover:bg-[#f0edff]">
            重置
          </button>
        </div>
      )}

      {/* 图谱区域 */}
      <div className="relative min-h-0 flex-1">
        {error && (
          <div className="absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-xl border border-[#f3c4c4] bg-white px-4 py-2 text-[11px] text-[#a33] shadow">
            {error}
            <button type="button" className="ml-2 font-semibold text-brand" onClick={() => setError("")}>
              知道了
            </button>
          </div>
        )}
        {demo && (
          <div className="absolute left-3 top-2 z-10">
            <DemoNotice show>演示模式数据</DemoNotice>
          </div>
        )}

        {loading ? (
          <div className="grid h-full place-items-center text-[12px] text-muted">图谱加载中…</div>
        ) : canvasNodes.length === 0 ? (
          <div className="grid h-full place-items-center px-6">
            <div className="max-w-[420px] text-center">
              <div className="mb-2 text-[15px] font-bold">
                {allNodes.length === 0 ? "知识网络还是空的" : "当前筛选下没有可显示的节点"}
              </div>
              <div className="mb-4 text-[12px] leading-relaxed text-muted">
                {allNodes.length === 0
                  ? "创建学习目标并生成教程后，概念与关系会自动生长到图谱里；也可以从「学习目标」打开已有目标再回到这里。"
                  : "试试「全部」预设、打开「叶节点 / 待核实 / 目标节点」，或清空搜索词。"}
              </div>
              <div className="flex justify-center gap-2">
                {allNodes.length === 0 ? (
                  <Link href="/goals" className="rounded-lg bg-brand px-3 py-2 text-[12px] font-semibold text-white">
                    去创建学习目标 →
                  </Link>
                ) : (
                  <button
                    type="button"
                    onClick={() => applyPreset("all")}
                    className="rounded-lg bg-brand px-3 py-2 text-[12px] font-semibold text-white"
                  >
                    显示全部
                  </button>
                )}
              </div>
            </div>
          </div>
        ) : (
          <GraphCanvas
            nodes={canvasNodes}
            edges={canvasEdges}
            selectedId={selected}
            highlight={Array.from(searchMatches)}
            fullscreen={fullscreen}
            onSelect={onSelect}
          />
        )}

        {/* 详情抽屉（覆盖层，不挤压画布；点击节点仍可切换） */}
        {selectedNode && (
          <aside className="absolute inset-y-0 right-0 z-30 flex w-[min(400px,92vw)] flex-col border-l border-line bg-white shadow-[-16px_0_40px_#19254224]">
              <div className="flex items-start gap-2 border-b border-line px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[15px] font-bold text-[#1c2940]">{selectedNode.title}</span>
                    {selectedNode.type === "concept" && (
                      <Badge tone={MASTERY_META[detail?.mastery.status ?? "no_evidence"]?.tone ?? "neutral"}>
                        {MASTERY_META[detail?.mastery.status ?? "no_evidence"]?.label}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 text-[10px] text-muted">
                    {selectedNode.type === "goal" ? "学习目标节点" : selectedNode.domain_name}
                    {selectedNode.type === "concept" && detail?.aliases.length
                      ? ` · 别名：${detail.aliases.join("、")}`
                      : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onSelect(null)}
                  aria-label="关闭"
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-[14px] text-[#5a6a86] hover:bg-[#f6f7fb]"
                >
                  ×
                </button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 text-[12px]">
                {selectedNode.type === "goal" ? (
                  <div className="grid gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-bold">{selectedNode.title}</span>
                      {selectedNode.status === "archived" && <Badge tone="neutral">已归档</Badge>}
                    </div>
                    <p className="text-[12px] leading-relaxed text-[#39455d]">
                      该学习目标在知识网络中关联 {selectedNode.degree} 个概念。图谱中的目标节点只表达「目标覆盖」关系，不表达掌握程度。
                      {selectedNode.status === "archived" && " 该目标已归档，其知识仍保留在学习记录中。"}
                    </p>
                    <Link
                      href={`/goals/${selectedNode.ref_id}`}
                      className="rounded-lg border border-line px-2.5 py-2 text-[12px] font-semibold text-brand hover:border-[#c9c3ff]"
                    >
                      进入目标工作台 →
                    </Link>
                  </div>
                ) : detail ? (
                  <div className="grid gap-3">
                    {detail.definition && (
                      <p className="rounded-xl bg-[#f8f9fd] p-3 leading-relaxed text-[#39455d]">{detail.definition}</p>
                    )}

                    <div>
                      <div className="mb-1 font-bold">掌握状态（证据驱动）</div>
                      <div className="flex items-start gap-2">
                        <Badge tone={MASTERY_META[detail.mastery.status]?.tone ?? "neutral"}>
                          {MASTERY_META[detail.mastery.status]?.label ?? detail.mastery.status}
                        </Badge>
                        <span className="text-[11px] leading-relaxed text-muted">{detail.mastery.basis}</span>
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
                        <div className="py-4 text-center text-[11px] text-muted">暂无关系。</div>
                      ) : (
                        <div className="grid gap-1.5">
                          {(() => {
                            const rels = detail.relations;
                            const expanded = relExpanded.has(detail.id);
                            const shown = expanded ? rels : rels.slice(0, 5);
                            return (
                              <>
                                {shown.map((r) => {
                                  const meta = RELATION_TYPE_META[r.relation_type] ?? RELATION_TYPE_META.related;
                                  const st = STATUS_META[r.status] ?? { label: r.status, tone: "neutral" as const };
                                  const anchor = r.source_refs.find((s) => s.type === "tutorial_section");
                                  return (
                                    <div key={r.id} className="rounded-xl border border-line p-2.5">
                                      <div className="flex flex-wrap items-center gap-1.5">
                                        <span className="text-[11px]">{r.direction === "out" ? "本概念" : r.other_title}</span>
                                        <span
                                          className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
                                          style={{ background: meta.color }}
                                        >
                                          {r.direction === "out" ? `${meta.label}→` : `←${meta.label}`}
                                        </span>
                                        <span className="text-[11px]">{r.direction === "out" ? r.other_title : "本概念"}</span>
                                        <Badge tone={st.tone}>{st.label}</Badge>
                                        <span className="ml-auto text-[10px] text-muted">
                                          {r.origin === "tutorial" ? "来自教程" : r.origin === "ai_proposal" ? "AI 提议" : "手动"}
                                        </span>
                                      </div>
                                      {r.rationale && (
                                        <div className="mt-1 text-[11px] leading-relaxed text-muted">依据：{r.rationale}</div>
                                      )}
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
                                                <option key={k} value={k}>
                                                  {m.label}
                                                </option>
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
                                            <button
                                              type="button"
                                              disabled={busy === r.id}
                                              onClick={() => relationEdit(r.id, editingRel.type, editingRel.rationale)}
                                              className="rounded-md bg-brand px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
                                            >
                                              保存
                                            </button>
                                            <button
                                              type="button"
                                              onClick={() => setEditingRel(null)}
                                              className="rounded-md px-2 py-1 text-[11px] font-semibold text-brand hover:bg-[#f0edff]"
                                            >
                                              取消
                                            </button>
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
                                          <div className="mt-1.5 flex flex-wrap gap-1">
                                            <button
                                              type="button"
                                              onClick={() => setEditingRel({ id: r.id, type: r.relation_type, rationale: r.rationale })}
                                              className="rounded-md px-1.5 py-0.5 text-[10px] font-semibold text-brand hover:bg-[#f0edff]"
                                            >
                                              编辑
                                            </button>
                                            {r.status === "proposed" && (
                                              <>
                                                <button
                                                  type="button"
                                                  disabled={busy === r.id}
                                                  onClick={() => relationAction(r.id, "confirmed")}
                                                  className="rounded-md border border-line px-1.5 py-0.5 text-[10px] font-semibold disabled:opacity-40"
                                                >
                                                  确认
                                                </button>
                                                <button
                                                  type="button"
                                                  disabled={busy === r.id}
                                                  onClick={() => relationAction(r.id, "rejected")}
                                                  className="rounded-md px-1.5 py-0.5 text-[10px] text-[#a33] hover:bg-[#fff5f5] disabled:opacity-40"
                                                >
                                                  驳回
                                                </button>
                                              </>
                                            )}
                                            {(r.status === "confirmed" || r.status === "conflict") && (
                                              <button
                                                type="button"
                                                disabled={busy === r.id}
                                                onClick={() => relationAction(r.id, "revoked")}
                                                className="rounded-md px-1.5 py-0.5 text-[10px] text-[#a33] hover:bg-[#fff5f5] disabled:opacity-40"
                                              >
                                                撤销
                                              </button>
                                            )}
                                            {r.status === "confirmed" && (
                                              <button
                                                type="button"
                                                disabled={busy === r.id}
                                                onClick={() => relationAction(r.id, "conflict")}
                                                className="rounded-md px-1.5 py-0.5 text-[10px] text-[#c47b12] hover:bg-[#fff3e4] disabled:opacity-40"
                                              >
                                                标记冲突
                                              </button>
                                            )}
                                            {(r.status === "revoked" || r.status === "rejected") && (
                                              <button
                                                type="button"
                                                disabled={busy === r.id}
                                                onClick={() => relationAction(r.id, "proposed")}
                                                className="rounded-md px-1.5 py-0.5 text-[10px] text-brand hover:bg-[#f0edff] disabled:opacity-40"
                                              >
                                                重新核实
                                              </button>
                                            )}
                                          </div>
                                        </>
                                      )}
                                    </div>
                                  );
                                })}
                                {rels.length > 5 && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      const next = new Set(relExpanded);
                                      if (next.has(detail.id)) next.delete(detail.id);
                                      else next.add(detail.id);
                                      setRelExpanded(next);
                                    }}
                                    className="rounded-lg border border-dashed border-line px-2 py-1 text-[11px] text-[#5a6a86] hover:border-[#c9c3ff]"
                                  >
                                    {expanded ? "收起" : `展开其余 ${rels.length - 5} 条`}
                                  </button>
                                )}
                              </>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="py-8 text-center text-[11px] text-muted">{busy === "detail" ? "加载中…" : "暂无详情"}</div>
                )}
              </div>

              {/* 底部操作栏 */}
              <div className="flex shrink-0 items-center gap-2 border-t border-line px-4 py-2.5">
                {selectedNode.type === "goal" ? (
                  <Link
                    href={`/goals/${selectedNode.ref_id}`}
                    className="rounded-lg bg-brand px-3 py-1.5 text-[11px] font-semibold text-white"
                  >
                    打开目标工作台
                  </Link>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => hideNode(selectedNode)}
                      className="rounded-lg border border-line px-2.5 py-1.5 text-[11px] font-semibold text-[#39455d] hover:border-[#c9c3ff]"
                    >
                      隐藏节点
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(selectedNode)}
                      className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-[#a33] hover:bg-[#fff5f5]"
                    >
                      删除节点…
                    </button>
                  </>
                )}
                <span className="ml-auto text-[10px] text-muted">Esc 关闭</span>
              </div>
            </aside>
        )}

        {/* Toast */}
        {toast && (
          <div className="absolute bottom-16 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-xl bg-[#1c2940] px-4 py-2 text-[11px] text-white shadow-lg">
            {toast.msg}
            {toast.undo && (
              <button
                type="button"
                className="font-semibold text-[#a99dff] hover:underline"
                onClick={() => {
                  toast.undo?.();
                  setToast(null);
                }}
              >
                撤销
              </button>
            )}
          </div>
        )}
      </div>

      {/* 删除确认 */}
      {deleteTarget && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-[#19254266] p-4">
          <div className="w-[min(420px,94vw)] rounded-2xl bg-white p-5">
            <div className="text-[15px] font-bold">删除这个概念？</div>
            <div className="mt-2 text-[12px] leading-relaxed text-[#39455d]">
              「{deleteTarget.title}」及其全部关系将被永久删除（如需保留请改用「隐藏」）。
            </div>
            <ul className="mt-2 grid gap-1 rounded-xl bg-[#fff5f5] p-3 text-[11px] text-[#8a3b3b]">
              <li>· 将删除 {detail?.relations.length ?? 0} 条关系</li>
              {detail?.goals.length ? <li>· 该概念同时服务 {detail.goals.length} 个学习目标，其他图谱中的该节点也会消失</li> : null}
              <li>· 教程、学习目标、练习记录不受影响；重新生成教程时可能再次提取同名概念</li>
            </ul>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="rounded-lg border border-line px-3 py-1.5 text-[12px] font-semibold text-[#39455d]"
              >
                取消
              </button>
              <button
                type="button"
                disabled={busy === "delete"}
                onClick={deleteConcept}
                className="rounded-lg bg-[#c0392b] px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-40"
              >
                {busy === "delete" ? "删除中…" : "永久删除"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 清空确认 */}
      {clearOpen && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-[#19254266] p-4">
          <div className="w-[min(440px,94vw)] rounded-2xl bg-white p-5">
            <div className="text-[15px] font-bold">清空全部图谱数据？</div>
            <div className="mt-2 text-[12px] leading-relaxed text-[#39455d]">
              将删除 <b>{nav?.totals.concepts ?? 0}</b> 个概念、<b>{nav?.totals.relations ?? 0}</b> 条关系，以及全部待处理的
              知识提议。学习目标、教程、练习记录会保留。
            </div>
            <div className="mt-3 rounded-xl bg-[#fff5f5] p-3 text-[11px] leading-relaxed text-[#8a3b3b]">
              不可撤销；重新生成教程时可能再次提取同名概念。请输入「清空」确认：
            </div>
            <input
              className="mt-2 w-full rounded-[10px] border border-line bg-[#fbfcff] px-3 py-2 text-[13px] outline-none focus:border-[#a69dff]"
              value={clearInput}
              onChange={(e) => setClearInput(e.target.value)}
              placeholder="输入 清空"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setClearOpen(false);
                  setClearInput("");
                }}
                className="rounded-lg border border-line px-3 py-1.5 text-[12px] font-semibold text-[#39455d]"
              >
                取消
              </button>
              <button
                type="button"
                disabled={clearInput.trim() !== "清空" || busy === "clear"}
                onClick={clearAll}
                className="rounded-lg bg-[#c0392b] px-3 py-1.5 text-[12px] font-semibold text-white disabled:opacity-40"
              >
                {busy === "clear" ? "清空中…" : "清空全部"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  return shell;
}

export default function KnowledgePage() {
  return (
    <Suspense fallback={<div className="px-10 py-8 text-[12px] text-muted">知识网络加载中…</div>}>
      <KnowledgeInner />
    </Suspense>
  );
}
