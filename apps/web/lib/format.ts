/** 展示辅助：token 数字格式化与功能名中文映射。 */

export function fmtTokens(value?: number | null): string {
  const n = value ?? 0;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function usageSourceLabel(source?: string): string {
  if (source === "provider") return "模型实测";
  if (source === "estimated") return "按字符估算";
  return "暂无数据";
}

export const FEATURE_LABELS: Record<string, string> = {
  diagnose: "价值诊断",
  plan: "学习计划",
  criteria: "验收标准",
  outline: "教程大纲",
  section: "章节生成",
  feedback: "实践反馈",
  assessment: "能力评估",
  reflection: "复盘",
  proposals: "知识提议",
  chat: "上下文答疑",
  user_feedback: "用户反馈",
  unknown: "未知",
};

export function featureLabel(feature: string): string {
  return FEATURE_LABELS[feature] ?? feature;
}

/** 教程内某条大纲对应的已生成章节（按顺序对齐）。 */
export function sectionForOutline<T extends { id: string }>(
  sections: T[],
  outlineIndex: number
): T | undefined {
  return sections[outlineIndex];
}
