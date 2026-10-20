"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { TrainingRecord } from "@/lib/types";
import { Button, inputCls } from "@/components/ui";

const PRESET_TAGS = [
  "内容有用",
  "步骤清晰",
  "例子不够",
  "来源需补充",
  "术语太多",
  "难度合适",
  "希望更具体",
];

/**
 * 测试版用户反馈：写入 /api/training/feedback，持久化后可随训练数据导出。
 * 复用现有卡片 / 按钮风格，不引入新依赖。
 */
export function FeedbackForm({
  goalId,
  tutorialId,
  sectionId,
  targetType = "general",
  title = "这份材料对你有帮助吗？",
}: {
  goalId?: string;
  tutorialId?: string;
  sectionId?: string;
  targetType?: "general" | "generation" | "tutorial" | "section";
  title?: string;
}) {
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const toggleTag = (tag: string) => {
    setTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  };

  const submit = async () => {
    if (rating === null) {
      setError("请先选择「有帮助」或「需改进」");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.post<TrainingRecord>("/api/training/feedback", {
        goal_id: goalId ?? null,
        tutorial_id: tutorialId ?? null,
        section_id: sectionId ?? null,
        target_type: targetType,
        rating,
        tags,
        comment,
        context: {
          page: typeof window !== "undefined" ? window.location.pathname : "",
        },
      });
      setDone(true);
      setTags([]);
      setComment("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const ratingBtn = (value: 1 | -1, label: string) => (
    <button
      type="button"
      onClick={() => {
        setRating(value);
        setDone(false);
        setError("");
      }}
      className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold transition-colors ${
        rating === value
          ? "border-[#c9c2ff] bg-[#f0edff] text-brand"
          : "border-line bg-white text-[#5a6a86] hover:border-[#c9c3ff]"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="rounded-xl border border-line bg-[#fbfcff] p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <b className="text-[11px]">{title}</b>
        <span className="text-[10px] text-muted">测试版反馈将用于改进与后续训练数据</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {ratingBtn(1, "👍 有帮助")}
        {ratingBtn(-1, "👎 需改进")}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {PRESET_TAGS.map((tag) => (
          <button
            key={tag}
            type="button"
            onClick={() => toggleTag(tag)}
            className={`rounded-full border px-2.5 py-1 text-[10px] transition-colors ${
              tags.includes(tag)
                ? "border-[#c9c2ff] bg-[#f0edff] font-semibold text-brand"
                : "border-line bg-white text-muted hover:border-[#c9c3ff]"
            }`}
          >
            {tag}
          </button>
        ))}
      </div>
      <textarea
        className={`${inputCls} mt-2`}
        rows={2}
        placeholder="补充说明（可选）：哪里不清楚、哪里最有帮助？"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button onClick={submit} disabled={busy || rating === null}>
          {busy ? "提交中…" : "提交反馈"}
        </Button>
        {done && <span className="text-[11px] text-[#128b78]">已记录，感谢反馈。</span>}
        {error && <span className="text-[11px] text-[#a33]">{error}</span>}
      </div>
    </div>
  );
}
