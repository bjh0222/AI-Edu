"use client";

import { useMemo, useState } from "react";
import type { FormatSpec } from "@/lib/types";
import { groupSpecs, specGroupLabel, specPreviewMarkdown } from "@/lib/specs";
import { inputCls } from "@/components/ui";

/**
 * 「教程规范」一栏：分组下拉 + 就地展开规范正文。
 *
 * 选择语义与后端逐字一致，不改提交映射：
 * - "auto" → format_spec_id = null（自动匹配）
 * - ""     → format_spec_id = ""（本次不使用特殊规范）
 * - 其他   → 规范 id（手动选择，优先于自动匹配）
 *
 * 分组只是界面便利（避免把试卷/练习规范误选给教程任务），下拉的 value 仍是规范 id。
 * 手机上（安卓浏览器）这一栏的「查看规范」是不打开偏好设置页就能确认规范正文的唯一途径。
 * Obsidian 插件里有一份等价的界面实现（main.js createSpecField），改这里要同步改插件。
 */
export function SpecPicker({
  specs,
  value,
  onChange,
  disabled,
  label = "教程规范",
}: {
  specs: FormatSpec[];
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const groups = useMemo(() => groupSpecs(specs), [specs]);
  const selected = useMemo(
    () => (value && value !== "auto" ? specs.find((s) => s.id === value) ?? null : null),
    [specs, value]
  );
  const preview = useMemo(() => (selected ? specPreviewMarkdown(selected) : ""), [selected]);

  const meta = !selected
    ? value === "auto"
      ? "自动匹配：按需求文本的关键词与语义挑选规范，未命中时使用默认规范；手动选择优先于自动匹配。"
      : "本次不使用特殊规范：正文只受「硬性约束」与通用排版要求约束。"
    : `${specGroupLabel(selected)} · v${selected.version || 1}${selected.is_default ? " · 默认规范" : ""}${
        selected.is_builtin ? " · 内置" : ""
      }｜手动选择优先于自动匹配；规范会在大纲生成前冻结为本任务快照。`;

  return (
    <div className="grid gap-1.5">
      <span className="text-[12px] font-semibold text-ink">{label}</span>
      <div className="flex items-stretch gap-2">
        <select
          aria-label={label}
          className={`${inputCls} min-w-0 flex-1`}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="auto">自动匹配（未命中时使用默认规范）</option>
          <option value="">本次不使用特殊规范</option>
          {groups.map((group) => (
            <optgroup key={group.key} label={group.label}>
              {group.specs.map((spec) => (
                <option key={spec.id} value={spec.id}>
                  {spec.name}
                  {spec.is_default ? " · 默认" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <button
          type="button"
          disabled={!selected}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="shrink-0 rounded-[10px] border border-line bg-white px-3 py-2 text-[12px] font-semibold text-[#39455d] hover:border-[#c9c3ff] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {open ? "收起规范" : "查看规范"}
        </button>
      </div>
      <span className="text-[10px] leading-relaxed text-muted">{meta}</span>
      {open && selected && (
        <pre className="max-h-[45vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-line bg-[#fbfcff] p-3 font-mono text-[12px] leading-relaxed text-ink">
          {preview}
        </pre>
      )}
      {open && selected && (
        <span className="text-[10px] leading-relaxed text-muted">
          以上为规范全文预览，段落顺序与生成时注入提示词的顺序一致。修改请到「偏好设置 → 格式规范」。
        </span>
      )}
    </div>
  );
}
