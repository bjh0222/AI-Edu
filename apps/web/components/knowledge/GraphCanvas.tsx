"use client";

/**
 * 知识网络图谱画布：自研轻量力导向布局（纯 SVG + requestAnimationFrame）。
 *
 * 不引入第三方图库的理由：当前依赖里没有任何图可视化库；本组件只需要
 * 力导向布局 + 平移缩放 + 节点拖拽 + 点击选中，约 300 行即可稳定实现，
 * 避免为一个模块引入重量级依赖。数据全部来自后端持久化结果。
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
  onSelect,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  highlight: string[]; // 搜索命中的节点 id；非空时其余节点弱化
  onSelect: (id: string | null) => void;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 900, h: 560 });
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  // 仿真数据保存在 ref（只在 effect / 事件中修改），渲染用 positions state
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const simRef = useRef<SimNode[]>([]);
  const alphaRef = useRef(1);
  const edgesRef = useRef<GraphEdge[]>(edges);
  const sizeRef = useRef(size);
  const dragRef = useRef<{ kind: "node" | "pan"; id?: string; sx: number; sy: number; ox: number; oy: number } | null>(null);
  const highlightSet = useMemo(() => new Set(highlight), [highlight]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    sizeRef.current = size;
  }, [size]);

  // 尺寸自适应
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setSize({ w: Math.max(320, rect.width), h: Math.max(360, rect.height) });
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
        x: old?.x ?? cx + Math.cos(angle) * (120 + (i % 5) * 28),
        y: old?.y ?? cy + Math.sin(angle) * (120 + (i % 5) * 28),
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
      };
    });
    alphaRef.current = 1;
    setPositions(Object.fromEntries(simRef.current.map((n) => [n.id, { x: n.x, y: n.y }])));
  }, [nodes]);

  // 力导向仿真：常驻 rAF 循环；alpha 衰减到阈值后只做廉价检查，不再重绘
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
        // 斥力（按领域聚簇：同域弱斥力，异域强斥力，形成领域板块）
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
        // 边弹簧：先修关系用略硬的弹簧，保持先修链可读
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
        // 向心 + 阻尼 + 积分
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
    // 唤醒物理循环（循环常驻，只需抬升 alpha）
    alphaRef.current = Math.max(alphaRef.current, 0.5);
  }, []);

  // ------------------------------------------------------------ interactions
  const toGraph = useCallback(
    (clientX: number, clientY: number) => {
      const rect = wrapRef.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      return {
        x: (clientX - rect.left - transform.x) / transform.k,
        y: (clientY - rect.top - transform.y) / transform.k,
      };
    },
    [transform]
  );

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
        const p = {
          x: (e.clientX - rect.left - transform.x) / transform.k,
          y: (e.clientY - rect.top - transform.y) / transform.k,
        };
        const n = simRef.current.find((s) => s.id === d.id);
        if (n) {
          n.fx = p.x;
          n.fy = p.y;
          alphaRef.current = Math.max(alphaRef.current, 0.3);
        }
      }
    };
    const up = () => {
      const d = dragRef.current;
      if (d?.kind === "node" && d.id) {
        const n = simRef.current.find((s) => s.id === d.id);
        if (n) {
          n.fx = null; // 松手后节点自由，与 Obsidian 一致
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
      const k = Math.min(3, Math.max(0.25, t.k * (e.deltaY < 0 ? 1.12 : 0.89)));
      return { k, x: mx - ((mx - t.x) * k) / t.k, y: my - ((my - t.y) * k) / t.k };
    });
  };

  const resetView = () => setTransform({ x: 0, y: 0, k: 1 });

  // ------------------------------------------------------------ rendering
  const radius = (n: GraphNode) =>
    n.type === "goal" ? 13 : Math.min(16, 7 + Math.sqrt(n.degree) * 2.6);
  const posOf = (id: string) => positions[id] ?? { x: size.w / 2, y: size.h / 2 };

  const domainKeys = useMemo(
    () => Array.from(new Set(nodes.map((n) => n.domain_key).filter(Boolean))),
    [nodes]
  );
  const domainColor = (key: string) => {
    const idx = domainKeys.indexOf(key);
    return DOMAIN_COLORS[(idx < 0 ? 0 : idx) % DOMAIN_COLORS.length];
  };

  const dimmed = (id: string) => highlightSet.size > 0 && !highlightSet.has(id);
  const isSelected = (id: string) => selectedId === id;

  return (
    <div
      ref={wrapRef}
      className="relative h-[560px] w-full cursor-grab overflow-hidden rounded-xl border border-line bg-[#f8f9fd] active:cursor-grabbing"
      onMouseDown={onPaneMouseDown}
      onWheel={onWheel}
      onDoubleClick={resetView}
    >
      <svg width={size.w} height={size.h}>
        <defs>
          {Object.entries(RELATION_TYPE_META).map(([key, meta]) => (
            <marker
              key={key}
              id={`arrow-${key}`}
              viewBox="0 -4 8 8"
              refX={7}
              refY={0}
              markerWidth={6}
              markerHeight={6}
              orient="auto"
            >
              <path d="M0,-4L8,0L0,4" fill={meta.color} opacity={key === "goal_covers" ? 0.45 : 0.85} />
            </marker>
          ))}
        </defs>
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {edges.map((e) => {
            const a = posOf(e.source);
            const b = posOf(e.target);
            if (!positions[e.source] || !positions[e.target]) return null;
            const sourceNode = nodes.find((n) => n.id === e.source);
            const targetNode = nodes.find((n) => n.id === e.target);
            if (!sourceNode || !targetNode) return null;
            const meta = RELATION_TYPE_META[e.relation_type] ?? RELATION_TYPE_META.related;
            const dim = dimmed(e.source) || dimmed(e.target);
            const active = isSelected(e.source) || isSelected(e.target);
            // 边不再穿过节点圆心：按半径裁剪端点
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
                strokeWidth={active ? 2.2 : 1.2}
                strokeDasharray={e.status === "proposed" ? "5 4" : undefined}
                opacity={dim ? 0.08 : e.status === "proposed" ? 0.5 : 0.75}
                markerEnd={`url(#arrow-${markerKey})`}
              />
            );
          })}
          {nodes.map((n) => {
            const p = posOf(n.id);
            const dim = dimmed(n.id);
            const fill = n.type === "goal" ? "#39455d" : domainColor(n.domain_key);
            const stroke = n.type === "concept" ? MASTERY_STROKE[n.mastery] ?? "#c9d2e3" : "#1c2940";
            return (
              <g
                key={n.id}
                transform={`translate(${p.x},${p.y})`}
                opacity={dim ? 0.12 : 1}
                style={{ cursor: "pointer" }}
                onMouseDown={(e) => onNodeMouseDown(e, n.id)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(isSelected(n.id) ? null : n.id);
                }}
              >
                {isSelected(n.id) && <circle r={radius(n) + 5} fill="none" stroke="#6d5dfc" strokeWidth={1.6} />}
                <circle
                  r={radius(n)}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={n.type === "goal" ? 2.5 : 2.2}
                  strokeDasharray={n.type === "goal" && n.status === "archived" ? "3 3" : undefined}
                  fillOpacity={n.type === "goal" ? (n.status === "archived" ? 0.45 : 0.9) : 0.85}
                />
                <text
                  y={radius(n) + 13}
                  textAnchor="middle"
                  fontSize={11}
                  fill="#39455d"
                  style={{ pointerEvents: "none", userSelect: "none" }}
                >
                  {n.title.length > 12 ? `${n.title.slice(0, 12)}…` : n.title}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <button
        type="button"
        onClick={resetView}
        className="absolute bottom-3 right-3 rounded-lg border border-line bg-white/90 px-2.5 py-1.5 text-[11px] font-semibold text-[#39455d] shadow-sm hover:border-[#c9c3ff]"
      >
        重置视图
      </button>
      <div className="absolute bottom-3 left-3 rounded-lg bg-white/85 px-2.5 py-1 text-[10px] text-muted">
        拖动节点查看关联 · 滚轮缩放 · 空白处拖动平移 · 双击复位
      </div>
    </div>
  );
}
