"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { NavData } from "@/lib/types";

const items = [
  { href: "/", label: "学习工作台", icon: "▦" },
  { href: "/goals", label: "学习目标", icon: "◎" },
  { href: "/knowledge", label: "知识网络", icon: "◉" },
  { href: "/training", label: "测试数据", icon: "◈" },
  { href: "/settings", label: "偏好设置", icon: "⚙" },
];

/**
 * 侧边栏：知识网络为一级导航，下方子目录由用户学习目标涉及的领域动态生成
 * （来自 GET /api/knowledge/nav），不依赖硬编码学科树。
 */
export default function Sidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [nav, setNav] = useState<NavData | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [expandedGoals, setExpandedGoals] = useState<Set<string>>(new Set());

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  const loadNav = useCallback(async () => {
    try {
      setNav(await api.get<NavData>("/api/knowledge/nav"));
    } catch {
      /* 后端未启动时静默：只显示一级导航 */
    }
  }, []);

  useEffect(() => {
    // 挂载时加载知识网络导航；路径变化时刷新计数（对异步 setState 误报的规则豁免）
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadNav();
  }, [loadNav, pathname, searchParams]);

  const currentDomain = pathname.startsWith("/knowledge") ? searchParams.get("domain") ?? "" : "";
  const currentGoal = pathname.startsWith("/knowledge") ? searchParams.get("goal") ?? "" : "";
  const knowledgeActive = isActive("/knowledge");

  const toggleDomain = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const toggleGoal = (id: string) =>
    setExpandedGoals((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <aside className="hidden w-[238px] shrink-0 flex-col gap-7 bg-navy px-3.5 py-6 text-[#eaf0fa] md:flex">
      <div className="flex items-center gap-2.5 px-2">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-[#a89cff] to-[#5c4bf0] text-[17px] font-extrabold">
          E
        </div>
        <div>
          <b className="text-[17px]">AI Edu</b>
          <small className="mt-0.5 block text-[11px] text-[#94a4be]">Learn by building</small>
        </div>
      </div>

      <nav className="grid gap-1.5">
        <div className="px-3 pb-2 text-[10px] tracking-[1.5px] text-[#7787a2]">工作空间</div>
        {items.map((it) => {
          const active = isActive(it.href);
          return (
            <div key={it.href}>
              <Link
                href={it.href}
                className={`flex items-center gap-3 rounded-[10px] px-3 py-3 text-left text-[13px] transition-colors ${
                  active
                    ? "bg-[#6d5dfc36] text-white shadow-[inset_3px_0_#a99dff]"
                    : "text-[#acbad0] hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="w-[18px] text-center">{it.icon}</span>
                {it.label}
              </Link>

              {it.href === "/knowledge" && knowledgeActive && nav && nav.domains.length > 0 && (
                <div className="ml-4 mt-1 grid gap-0.5 border-l border-[#2b3954] pl-2">
                  <Link
                    href="/knowledge"
                    className={`rounded-lg px-2 py-1.5 text-[11px] ${
                      !currentDomain && !currentGoal
                        ? "bg-[#6d5dfc36] font-semibold text-white"
                        : "text-[#94a4be] hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    全局网络
                    <span className="ml-1 text-[10px] text-[#7787a2]">{nav.totals.concepts}</span>
                  </Link>
                  {nav.domains.map((d) => {
                    const open = expanded.has(d.key) || currentDomain === d.key;
                    const domainActive = currentDomain === d.key && !currentGoal;
                    return (
                      <div key={d.key}>
                        <div className="flex items-center">
                          <button
                            type="button"
                            aria-label={open ? "折叠" : "展开"}
                            className="w-4 shrink-0 text-[9px] text-[#7787a2] hover:text-white"
                            onClick={() => toggleDomain(d.key)}
                          >
                            {open ? "▾" : "▸"}
                          </button>
                          <Link
                            href={`/knowledge?domain=${d.key}`}
                            title={d.name}
                            className={`flex-1 truncate rounded-lg px-1.5 py-1.5 text-[11px] ${
                              domainActive
                                ? "bg-[#6d5dfc36] font-semibold text-white"
                                : "text-[#94a4be] hover:bg-white/5 hover:text-white"
                            }`}
                          >
                            {d.name}
                            <span className="ml-1 text-[10px] text-[#7787a2]">{d.concept_count}</span>
                          </Link>
                        </div>
                        {open && d.goals.length > 0 && (
                          <div className="ml-4 grid gap-0.5 border-l border-[#2b3954] pl-2">
                            {d.goals.map((g) => {
                              const goalOpen = expandedGoals.has(g.id);
                              const goalActive = currentGoal === g.id;
                              return (
                                <div key={g.id}>
                                  <div className="flex items-center">
                                    <button
                                      type="button"
                                      aria-label={goalOpen ? "折叠" : "展开"}
                                      className="w-3.5 shrink-0 text-[9px] text-[#7787a2] hover:text-white"
                                      onClick={() => toggleGoal(g.id)}
                                    >
                                      {goalOpen ? "▾" : "▸"}
                                    </button>
                                    <Link
                                      href={`/knowledge?domain=${d.key}&goal=${g.id}`}
                                      title={g.archived ? `${g.title}（已归档）` : g.title}
                                      className={`flex-1 truncate rounded-lg px-1.5 py-1 text-[10.5px] ${
                                        goalActive
                                          ? "bg-[#6d5dfc36] font-semibold text-white"
                                          : g.archived
                                            ? "text-[#5f6d87] hover:bg-white/5 hover:text-[#94a4be]"
                                            : "text-[#8a99b5] hover:bg-white/5 hover:text-white"
                                      }`}
                                    >
                                      {g.title}
                                      <span className="ml-1 text-[9px] text-[#7787a2]">{g.concept_count}</span>
                                      {g.archived && <span className="ml-1 text-[9px] text-[#5f6d87]">已归档</span>}
                                    </Link>
                                  </div>
                                  {goalOpen && (
                                    <div className="ml-4 grid gap-0.5 pl-1.5">
                                      <Link
                                        href={`/goals/${g.id}`}
                                        className="rounded-lg px-1.5 py-1 text-[10px] text-[#7787a2] hover:bg-white/5 hover:text-white"
                                      >
                                        进入目标工作台 →
                                      </Link>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="mt-auto">
        <div className="mx-1 mb-3 rounded-xl border border-[#2b3954] bg-[#1c2940] p-3.5 text-[11px] leading-relaxed text-[#aebbd0]">
          <b className="text-[#e5eaff]">学习原则</b>
          <br />
          不是收集更多教程，而是逐步独立解决问题。
        </div>
        <div className="flex items-center gap-2.5 border-t border-[#2b3850] px-2 pt-3.5">
          <div className="grid h-8 w-8 place-items-center rounded-full bg-[#f3b59d] font-bold text-[#65382c]">
            我
          </div>
          <div>
            <b className="text-[12px]">个人学习空间</b>
            <small className="block text-[11px] text-[#8595af]">v0.1 · 本地开发版</small>
          </div>
        </div>
      </div>
    </aside>
  );
}
