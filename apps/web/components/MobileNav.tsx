"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "工作台", icon: "▦" },
  { href: "/goals", label: "目标", icon: "◎" },
  { href: "/knowledge", label: "知识", icon: "◉" },
  { href: "/training", label: "数据", icon: "◈" },
  { href: "/settings", label: "设置", icon: "⚙" },
];

/**
 * 手机端底部标签栏（安卓 / iOS）。
 *
 * 为什么需要它：Sidebar 是 `hidden md:flex`，手机上侧栏整块不渲染 ——
 * 没有它，手机端进入任何页面后都无法切换页面（只能靠浏览器后退）。
 *
 * 要点：
 * - 用 body 上的 class 而不是媒体查询判定不可行（纯 CSS），这里用 Tailwind 的
 *   `md:hidden`，与 Sidebar 的 `md:flex` 严格互补，不会同时出现两个导航。
 * - `fixed` 吸底 + `pb-[env(safe-area-inset-bottom)]`：安卓全面屏手势条 / iOS home
 *   indicator 不会压住标签。
 * - 触控目标 ≥48px 高（安卓无障碍建议），5 个标签等分屏宽。
 * - 知识网络页的图谱是绝对核心，标签栏在该页仍保留（图谱自身有全屏按钮），
 *   保证手机上始终有出口。
 */
export default function MobileNav() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <nav
      aria-label="主导航（手机端）"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-[#2b3850] bg-navy pb-[env(safe-area-inset-bottom)] text-[#eaf0fa] md:hidden"
    >
      {items.map((it) => {
        const active = isActive(it.href);
        return (
          <Link
            key={it.href}
            href={it.href}
            aria-label={it.label}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[10px] transition-colors ${
              active ? "text-white" : "text-[#8a99b5]"
            }`}
          >
            <span
              aria-hidden="true"
              className={`grid h-7 w-7 place-items-center rounded-lg text-[16px] ${
                active ? "bg-brand/25" : ""
              }`}
            >
              {it.icon}
            </span>
            {it.label}
          </Link>
        );
      })}
    </nav>
  );
}
