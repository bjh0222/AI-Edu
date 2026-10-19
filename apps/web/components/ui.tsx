"use client";

import { ReactNode } from "react";

export function Card({
  title,
  desc,
  actions,
  children,
}: {
  title: ReactNode;
  desc?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_8px_28px_#1925420b]">
      <div className="flex items-start justify-between gap-4 px-5 pt-5 pb-3">
        <div>
          <div className="text-[15px] font-bold text-ink">{title}</div>
          {desc && <div className="mt-1 text-[11px] text-muted">{desc}</div>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="px-5 pb-5">{children}</div>
    </section>
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "active" | "done" | "warn" | "demo";
  children: ReactNode;
}) {
  const map: Record<string, string> = {
    neutral: "bg-[#f0f2f7] text-[#68748a]",
    active: "bg-[#f0edff] text-brand",
    done: "bg-[#e7f8f3] text-[#128b78]",
    warn: "bg-[#fff3e4] text-[#c47b12]",
    demo: "bg-[#fff3e4] text-[#c47b12]",
  };
  return (
    <span className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${map[tone]}`}>{children}</span>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
}) {
  const map: Record<string, string> = {
    primary:
      "bg-brand text-white hover:bg-brand-dark shadow-[0_5px_15px_#6d5dfc2a] disabled:opacity-40",
    secondary:
      "border border-line bg-white text-[#39455d] hover:border-[#c9c3ff] disabled:opacity-40",
    ghost: "text-brand hover:bg-[#f0edff] rounded-lg px-2 py-1",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-[10px] px-3.5 py-2 text-[12px] font-semibold disabled:cursor-not-allowed ${map[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="mb-3 grid gap-1.5">
      <span className="text-[12px] font-semibold text-ink">{label}</span>
      {children}
    </label>
  );
}

export const inputCls =
  "w-full rounded-[10px] border border-line bg-[#fbfcff] px-3 py-2.5 text-[13px] outline-none focus:border-[#a69dff]";

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-[12px] text-muted">{children}</div>;
}

export function DemoNotice({ show, children }: { show: boolean; children: ReactNode }) {
  if (!show) return null;
  return (
    <div className="mb-3 rounded-xl border border-[#f3e3c4] bg-[#fffaf0] px-3 py-2 text-[11px] leading-relaxed text-[#8a6411]">
      <span className="font-bold">演示模式：</span>
      {children}
    </div>
  );
}
