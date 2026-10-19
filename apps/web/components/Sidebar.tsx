"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "学习工作台", icon: "▦" },
  { href: "/goals", label: "学习目标", icon: "◎" },
  { href: "/knowledge", label: "知识网络", icon: "◉" },
  { href: "/settings", label: "偏好设置", icon: "⚙" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

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
        {items.map((it) => (
          <Link
            key={it.href}
            href={it.href}
            className={`flex items-center gap-3 rounded-[10px] px-3 py-3 text-left text-[13px] transition-colors ${
              isActive(it.href)
                ? "bg-[#6d5dfc36] text-white shadow-[inset_3px_0_#a99dff]"
                : "text-[#acbad0] hover:bg-white/5 hover:text-white"
            }`}
          >
            <span className="w-[18px] text-center">{it.icon}</span>
            {it.label}
          </Link>
        ))}
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
