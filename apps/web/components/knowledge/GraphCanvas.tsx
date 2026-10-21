"use client";

/**
 * 知识网络图谱画布：自研轻量力导向布局（纯 SVG + requestAnimationFrame）。
 * 不引入第三方图库：只需要力导向 + 平移缩放 + 拖拽选中，数百行即可稳定实现。
 *
 * 可读性策略：
 * - 标签「语义缩放」：按缩放级别与优先级（选中 > 悬停 > 搜索命中 > 高度数）限量显示；
 * - 标签屏幕空间字号恒定（12px），白色描边避免被连线压字；
 * - 连线非缩放描边（缩放后仍清晰），待核实关系虚线；
 * - 适应画布按钮 + 缩放百分比，全屏下放宽缩放上限。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/lib/types";

export const RELATION_TYPE_META: Record<string, { label: string; color: string }> = {
  prerequisite_of: { label: "先修于", color: "#6d5dfc" },
  part_of: { label: "属于", color: "#128b78" },
  explains: { label: "解释", color: "#c47b12" },
  applied_in: { label: "应用于", color: "#0f7ac4" },
  contrasts_with: { label: "对比", color: "#b1568a" },
  related: { label: "相关联", color: "#9aa7bd" },
  goal_covers: { label: "目标覆盖", color: "#c9c3ff" },
};

const DOMAIN_COLORS = ["#6d5dfc", "#128b78", "#0f7ac4", "#c47b12", "#b1568a", "#5a6a86", "#2f9e6e", "#8a63d2"];
const MASTERY_STROKE: Record<string, string> = {
  mastered: "#128b78",
  practicing: "#c47b12",
  no_evidence: "#c9d2e3",
};

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx?: number | null;
  fy?: number | null;
}

export default function GraphCanvas({
  nodes,
  edges,
  selectedId,
  highlight,
  fullscreen = false,
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  highlight: string[];
  fullscreen?: boolean;
  onSelect: (id: string | null) => void;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 900, h: 560 });
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [hovered, setHovered] = useState<string | null>(null);
  const simRef = useRef<SimNode[]>([]);
  const alphaRef = useRef(1);
  const edgesRef = useRef<GraphEdge[]>(edges);
  const sizeRef = useRef(size);
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});
  const transformRef = useRef(transform);
  const dragRef = useRef<{ kind: "node" | "pan"; id?: string; sx: number; sy: number; ox: number; oy: number } | null>(null);
  const highlightSet = useMemo(() => new Set(highlight), [highlight]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    sizeRef.current = size;
  }, [size]);

  useEffect(() => {
    positionsRef.current = positions;
  }, [positions]);

  useEffect(() => {
    transformRef.current = transform;
  }, [transform]);

  // 尺寸自适应
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setSize({ w: Math.max(320, rect.width), h: Math.max(300, rect.height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // 数据变化：重建仿真节点（跨渲染保留位置），唤醒物理循环并同步初始位置
  useEffect(() => {
    const prev = new Map(simRef.current.map((n) => [n.id, n]));
    const cx = sizeRef.current.w / 2;
    const cy = sizeRef.current.h / 2;
    simRef.current = nodes.map((n, i) => {
      const old = prev.get(n.id);
      const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
      return {
        ...n,
        x: old?.x ?? cx + Math.cos(angle) * (110 + (i % 5) * 26),
        y: old?.y ?? cy + Math.sin(angle) * (110 + (i % 5) * 26),
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
      };
    });
    alphaRef.current = 1;
    setPositions(Object.fromEntries(simRef.current.map((n) => [n.id, { x: n.x, y: n.y }])));
  }, [nodes]);

  // 力导向仿真：常驻 rAF 循环；alpha 衰减后只做廉价检查，不再重绘
  useEffect(() => {
    let raf = 0;
    const step = () => {
      const sim = simRef.current;
      const alpha = alphaRef.current;
      if (alpha > 0.015 && sim.length) {
        const curEdges = edgesRef.current;
        const size = sizeRef.current;
        const byId = new Map(sim.map((n) => [n.id, n]));
        const cx = size.w / 2;
        const cy = size.h / 2;
        for (let i = 0; i < sim.length; i++) {
          const a = sim[i];
          for (let j = i + 1; j < sim.length; j++) {
            const b = sim[j];
            let dx = b.x - a.x;
            let dy = b.y - a.y;
            let dist2 = dx * dx + dy * dy;
            if (dist2 < 1) {
              dx = (Math.random() - 0.5) * 2;
              dy = (Math.random() - 0.5) * 2;
              dist2 = 4;
            }
            const sameDomain = a.type === b.type && a.domain_key === b.domain_key;
            const dist = Math.sqrt(dist2);
            const strength = ((sameDomain ? 1800 : 3200) * alpha) / dist2;
            const fx = (dx / dist) * strength;
            const fy = (dy / dist) * strength;
            a.vx -= fx;
            a.vy -= fy;
            b.vx += fx;
            b.vy += fy;
          }
        }
        const REP = 110;
        for (const e of curEdges) {
          const a = byId.get(e.source);
          const b = byId.get(e.target);
          if (!a || !b) continue;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.max(1, Math.hypot(dx, dy));
          const target = e.relation_type === "prerequisite_of" ? REP * 0.85 : REP;
          const f = ((dist - target) / dist) * 0.06 * alpha * 8;
          a.vx += dx * f;
          a.vy += dy * f;
          b.vx -= dx * f;
          b.vy -= dy * f;
        }
        for (const n of sim) {
          n.vx += (cx - n.x) * 0.003 * alpha * 10;
          n.vy += (cy - n.y) * 0.003 * alpha * 10;
          if (n.fx != null) {
            n.x = n.fx;
            n.y = n.fy ?? n.y;
            n.vx = 0;
            n.vy = 0;
          } else {
            n.vx *= 0.82;
            n.vy *= 0.82;
            n.x += Math.max(-24, Math.min(24, n.vx));
            n.y += Math.max(-24, Math.min(24, n.vy));
          }
        }
        alphaRef.current = alpha * 0.985;
        setPositions(Object.fromEntries(sim.map((n) => [n.id, { x: n.x, y: n.y }])));
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);

  const restart = useCallback(() => {
    alphaRef.current = Math.max(alphaRef.current, 0.5);
  }, []);

  // ------------------------------------------------------------ fit / zoom
  const fitView = useCallback(() => {
    const pos = positionsRef.current;
    const ids = Object.keys(pos);
    if (!ids.length) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const id of ids) {
      const p = pos[id];
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    }
    const w = sizeRef.current.w;
    const h = sizeRef.current.h;
    const pad = 64;
    const k = Math.max(
      0.35,
      Math.min(fullscreen ? 4 : 3, (w - pad * 2) / Math.max(1, maxX - minX), (h - pad * 2) / Math.max(1, maxY - minY))
    );
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setTransform({ k, x: w / 2 - cx * k, y: h / 2 - cy * k });
  }, [fullscreen]);

  // 首次有位置、切换全屏时自动适应画布
  const fittedRef = useRef(false);
  useEffect(() => {
    if (!fittedRef.current && Object.keys(positions).length > 0) {
      fittedRef.current = true;
      fitView();
    }
  }, [positions, fitView]);

  useEffect(() => {
    if (fittedRef.current) fitView();
  }, [fullscreen, fitView]);

  const zoomBy = (factor: number) => {
    setTransform((t) => {
      const maxK = fullscreen ? 4 : 3;
      const k = Math.min(maxK, Math.max(0.5, t.k * factor));
      const cx = sizeRef.current.w / 2;
      const cy = sizeRef.current.h / 2;
      return { k, x: cx - ((cx - t.x) * k) / t.k, y: cy - ((cy - t.y) * k) / t.k };
    });
  };

  // ------------------------------------------------------------ interactions
  const toGraph = (clientX: number, clientY: number) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    const t = transformRef.current;
    return { x: (clientX - rect.left - t.x) / t.k, y: (clientY - rect.top - t.y) / t.k };
  };

  const onNodeMouseDown = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    const n = simRef.current.find((s) => s.id === id);
    if (!n) return;
    const p = toGraph(e.clientX, e.clientY);
    dragRef.current = { kind: "node", id, sx: p.x, sy: p.y, ox: n.x, oy: n.y };
    n.fx = n.x;
    n.fy = n.y;
    restart();
  };

  const onPaneMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { kind: "pan", sx: e.clientX, sy: e.clientY, ox: transform.x, oy: transform.y };
  };

  useEffect(() => {
    const move = (e: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      if (d.kind === "pan") {
        setTransform((t) => ({ ...t, x: d.ox + (e.clientX - d.sx), y: d.oy + (e.clientY - d.sy) }));
      } else if (d.id) {
        const rect = wrapRef.current?.getBoundingClientRect();
        if (!rect) return;
        const t = transformRef.current;
        const n = simRef.current.find((s) => s.id === d.id);
        if (n) {
          n.fx = (e.clientX - rect.left - t.x) / t.k;
          n.fy = (e.clientY - rect.top - t.y) / t.k;
          alphaRef.current = Math.max(alphaRef.current, 0.3);
        }
      }
    };
    const up = () => {
      const d = dragRef.current;
      if (d?.kind === "node" && d.id) {
        const n = simRef.current.find((s) => s.id === d.id);
        if (n) {
          n.fx = null;
          n.fy = null;
        }
        restart();
      }
      dragRef.current = null;
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [transform, restart]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    setTransform((t) => {
      const maxK = fullscreen ? 4 : 3;
      const k = Math.min(maxK, Math.max(0.5, t.k * (e.deltaY < 0 ? 1.12 : 0.89)));
      return { k, x: mx - ((mx - t.x) * k) / t.k, y: my - ((my - t.y) * k) / t.k };
    });
  };

  // ------------------------------------------------------------ rendering
  const radius = (n: GraphNode) =>
    n.type === "goal" ? 13 : Math.max(7, Math.min(17, 7 + Math.sqrt(Math.max(1, n.degree)) * 2.4));
  const posOf = (id: string) => positions[id] ?? { x: size.w / 2, y: size.h / 2 };
  const domainKeys = useMemo(
    () => Array.from(new Set(nodes.map((n) => n.domain_key).filter(Boolean))),
    [nodes]
  );
  const domainColor = (key: string) => {
    const idx = domainKeys.indexOf(key);
    return DOMAIN_COLORS[(idx < 0 ? 0 : idx) % DOMAIN_COLORS.length];
  };

  // 语义标签：按缩放级别限量 + 优先级排序
  const labelLimit = transform.k < 0.75 ? 12 : transform.k < 1.2 ? 24 : transform.k < 1.8 ? 40 : 999;
  const labelTargets = useMemo(() => {
    const score = (n: GraphNode) =>
      n.id === selectedId ? 4 : n.id === hovered ? 3 : highlightSet.has(n.id) ? 2 : n.degree >= 3 ? 1 : 0;
    return nodes
      .map((n) => ({ id: n.id, s: score(n) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, labelLimit)
      .map((x) => x.id);
  }, [nodes, selectedId, hovered, highlightSet, labelLimit]);
  const labelSet = useMemo(() => new Set(labelTargets), [labelTargets]);

  const dimmed = (id: string) => highlightSet.size > 0 && !highlightSet.has(id) && id !== selectedId;
  const isSelected = (id: string) => selectedId === id;
  const k = transform.k;
  const labelFont = (fullscreen ? 13 : 12) / k;

  return (
    <div
      ref={wrapRef}
      className="relative h-full w-full cursor-grab overflow-hidden bg-[#f7f9fd] active:cursor-grabbing"
      onMouseDown={onPaneMouseDown}
      onWheel={onWheel}
      onDoubleClick={fitView}
      onMouseLeave={() => setHovered(null)}
    >
      {/* 点阵背景（屏幕空间） */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: "radial-gradient(#e2e8f2 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />
      <svg width={size.w} height={size.h} className="relative">
        <defs>
          {Object.entries(RELATION_TYPE_META).map(([key, meta]) => (
            <marker
              key={key}
              id={`arrow-${key}`}
              viewBox="0 -4 8 8"
              refX={7}
              refY={0}
              markerWidth={5}
              markerHeight={5}
              orient="auto"
            >
              <path d="M0,-4L8,0L0,4" fill={meta.color} opacity={key === "goal_covers" ? 0.45 : 0.8} />
            </marker>
          ))}
        </defs>
        <g transform={`translate(${transform.x},${transform.y}) scale(${k})`}>
          {edges.map((e) => {
            if (!positions[e.source] || !positions[e.target]) return null;
            const a = posOf(e.source);
            const b = posOf(e.target);
            const sourceNode = nodes.find((n) => n.id === e.source);
            const targetNode = nodes.find((n) => n.id === e.target);
            if (!sourceNode || !targetNode) return null;
            const meta = RELATION_TYPE_META[e.relation_type] ?? RELATION_TYPE_META.related;
            const dim = dimmed(e.source) || dimmed(e.target);
            const active = isSelected(e.source) || isSelected(e.target);
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const dist = Math.max(1, Math.hypot(dx, dy));
            const r1 = radius(sourceNode) + 2;
            const r2 = radius(targetNode) + 7;
            const markerKey = e.relation_type in RELATION_TYPE_META ? e.relation_type : "related";
            return (
              <line
                key={e.id}
                x1={a.x + (dx / dist) * r1}
                y1={a.y + (dy / dist) * r1}
                x2={b.x - (dx / dist) * r2}
                y2={b.y - (dy / dist) * r2}
                stroke={meta.color}
                strokeWidth={active ? 2.4 : 1.2}
                vectorEffect="non-scaling-stroke"
                strokeDasharray={e.status === "proposed" ? "5 4" : undefined}
                opacity={dim ? 0.06 : e.status === "proposed" ? 0.45 : 0.7}
                markerEnd={`url(#arrow-${markerKey})`}
              />
            );
          })}
          {nodes.map((n) => {
            const p = posOf(n.id);
            const dim = dimmed(n.id);
            const fill = n.type === "goal" ? "#39455d" : domainColor(n.domain_key);
            const stroke = n.type === "concept" ? MASTERY_STROKE[n.mastery] ?? "#c9d2e3" : "#1c2940";
            const r = radius(n);
            const hit = Math.max(r + 6, 22); // 屏幕空间 ≥44px 命中区
            const showLabel = labelSet.has(n.id);
            const title = n.title.length > 11 ? `${n.title.slice(0, 11)}…` : n.title;
            return (
              <g
                key={n.id}
                transform={`translate(${p.x},${p.y})`}
                opacity={dim ? 0.12 : 1}
                style={{ cursor: "pointer" }}
                onMouseDown={(e) => onNodeMouseDown(e, n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(isSelected(n.id) ? null : n.id);
                }}
              >
                <title>{n.title}</title>
                <circle r={hit / k} fill="transparent" />
                {isSelected(n.id) && (
                  <circle r={r + 6 / k} fill="none" stroke="#6d5dfc" strokeWidth={1.6 / k} />
                )}
                {highlightSet.has(n.id) && !isSelected(n.id) && (
                  <circle r={r + 5 / k} fill="none" stroke="#c47b12" strokeWidth={1.4 / k} opacity={0.8} />
                )}
                <circle
                  r={r}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={(n.type === "goal" ? 2.5 : 2.2) / k}
                  strokeDasharray={n.type === "goal" && n.status === "archived" ? "3 3" : undefined}
                  fillOpacity={n.type === "goal" ? (n.status === "archived" ? 0.45 : 0.92) : 0.86}
                />
                {showLabel && (
                  <text
                    y={r + 12 / k}
                    textAnchor="middle"
                    fontSize={labelFont}
                    fontWeight={n.id === selectedId ? 600 : 500}
                    fill="#24324a"
                    style={{
                      pointerEvents: "none",
                      userSelect: "none",
                      paintOrder: "stroke",
                      stroke: "#ffffff",
                      strokeWidth: 3 / k,
                      strokeLinejoin: "round",
                    }}
                  >
                    {title}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* 图例 */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-2 rounded-lg bg-white/85 px-2.5 py-1.5 text-[10px] text-[#5a6a86] shadow-sm">
        {Object.entries(MASTERY_STROKE).map(([key, color]) => (
          <span key={key} className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: color }} />
            {key === "mastered" ? "有证据" : key === "practicing" ? "练习中" : "缺证据"}
          </span>
        ))}
        <span className="text-[#9aa7bd]">｜ 拖动节点 · 滚轮缩放 · 双击适应</span>
      </div>

      {/* 缩放控件 */}
      <div className="absolute bottom-3 right-3 flex items-center gap-1 rounded-lg border border-line bg-white/95 px-1 py-1 shadow-sm">
        <button
          type="button"
          aria-label="缩小"
          onClick={() => zoomBy(0.85)}
          className="grid h-7 w-7 place-items-center rounded-md text-[13px] text-[#39455d] hover:bg-[#f0edff]"
        >
          −
        </button>
        <button
          type="button"
          onClick={() => setTransform({ x: 0, y: 0, k: 1 })}
          className="min-w-[42px] text-[11px] font-semibold text-[#39455d] hover:text-brand"
          title="回到 100%"
        >
          {Math.round(k * 100)}%
        </button>
        <button
          type="button"
          aria-label="放大"
          onClick={() => zoomBy(1.18)}
          className="grid h-7 w-7 place-items-center rounded-md text-[13px] text-[#39455d] hover:bg-[#f0edff]"
        >
          +
        </button>
        <span className="mx-0.5 h-4 w-px bg-line" />
        <button
          type="button"
          onClick={fitView}
          className="rounded-md px-2 py-1 text-[11px] font-semibold text-[#39455d] hover:bg-[#f0edff]"
        >
          适应
        </button>
      </div>
    </div>
  );
}
