/**
 * 学习目标十项流程的单一事实来源。
 *
 * 后端 `app/learning/engine.py` 的 PHASES 顺序即学习闭环顺序，前端据此生成
 * 子路由 slug、阶段条、总览卡片与「上一步/下一步」导航；新增/调整阶段只改这里。
 */
export interface GoalPhase {
  /** 与后端 goal.status 一致的阶段 key */
  key: string;
  /** 子路由目录名：/goals/[id]/<slug> */
  slug: string;
  /** 阶段条上的短标签 */
  label: string;
  /** 子页标题 */
  title: string;
  /** 子页副标题 / 卡片说明 */
  desc: string;
  /** 总览卡片上的「产出物」提示 */
  output: string;
}

export const GOAL_PHASES: GoalPhase[] = [
  {
    key: "goal_definition",
    slug: "goal-definition",
    label: "目标定义",
    title: "目标定义",
    desc: "把模糊兴趣写成可验收的目标：要解决的问题、学完能做什么、当前基础与时间预算。",
    output: "目标描述与约束条件",
  },
  {
    key: "diagnosis",
    slug: "diagnosis",
    label: "价值诊断",
    title: "价值诊断",
    desc: "先判断是否值得学、范围是否合理——AI 给建议，你作决定；可上传参考资料与例题来源作为判断依据。",
    output: "收益 / 前置条件 / 你的决定",
  },
  {
    key: "planning",
    slug: "planning",
    label: "学习计划",
    title: "学习计划",
    desc: "把目标拆成有顺序、可执行的阶段与步骤。",
    output: "分阶段的学习计划",
  },
  {
    key: "acceptance_design",
    slug: "acceptance-design",
    label: "验收标准",
    title: "验收标准",
    desc: "先定义「学会的证据」，再生成教程。确认后的标准才会进入教程验收。",
    output: "可判定的验收标准",
  },
  {
    key: "learning",
    slug: "learning",
    label: "教程学习",
    title: "教程学习",
    desc: "按验收标准生成教程大纲与章节，可逐节打开详情、重新生成。",
    output: "教程大纲与章节",
  },
  {
    key: "practice",
    slug: "practice",
    label: "实践",
    title: "实践任务",
    desc: "每个任务都要有产物、验证方式与辅助等级记录；提交后获得逐条反馈。",
    output: "产物 + 尝试记录",
  },
  {
    key: "feedback",
    slug: "feedback",
    label: "反馈",
    title: "反馈",
    desc: "对照验收标准查看证据反馈，并把「哪里不清楚 / 哪里最有帮助」沉淀下来。",
    output: "逐条反馈与用户评价",
  },
  {
    key: "assessment",
    slug: "assessment",
    label: "能力评估",
    title: "能力评估",
    desc: "独立任务 + 变式任务，检查能否不依赖教程完成。",
    output: "评估方案与结果",
  },
  {
    key: "reflection",
    slug: "reflection",
    label: "复盘",
    title: "学习复盘",
    desc: "记录完成了什么、仍依赖 AI 的地方、下一步最值得做的事。",
    output: "复盘记录",
  },
  {
    key: "knowledge_update",
    slug: "knowledge-update",
    label: "知识记录",
    title: "知识记录",
    desc: "AI 只能提议概念与关系，确认后才进入长期知识网络。",
    output: "待确认的知识提议",
  },
];

export const PHASE_LABELS: Record<string, string> = Object.fromEntries(
  GOAL_PHASES.map((phase) => [phase.key, phase.label])
);

export const PHASE_SLUGS: string[] = GOAL_PHASES.map((phase) => phase.slug);

export function phaseBySlug(slug: string | string[] | undefined): GoalPhase | undefined {
  const value = Array.isArray(slug) ? slug[0] : slug;
  return GOAL_PHASES.find((phase) => phase.slug === value);
}

export function phaseByKey(key: string | undefined | null): GoalPhase | undefined {
  if (!key) return undefined;
  return GOAL_PHASES.find((phase) => phase.key === key);
}

export function phaseIndex(key: string | undefined | null): number {
  const index = GOAL_PHASES.findIndex((phase) => phase.key === key);
  return index < 0 ? 0 : index;
}

/** 子页地址；goalId 为空时返回目标列表，避免拼出 /goals//diagnosis 这类非法链接。 */
export function phaseHref(goalId: string | undefined, phase: GoalPhase): string {
  if (!goalId) return "/goals";
  return `/goals/${goalId}/${phase.slug}`;
}

export function goalHref(goalId: string | undefined): string {
  return goalId ? `/goals/${goalId}` : "/goals";
}

/** 上一步 / 下一步（跨阶段导航用，首尾返回 undefined）。 */
export function neighborPhases(slug: string): { prev?: GoalPhase; next?: GoalPhase } {
  const index = GOAL_PHASES.findIndex((phase) => phase.slug === slug);
  if (index < 0) return {};
  return {
    prev: index > 0 ? GOAL_PHASES[index - 1] : undefined,
    next: index + 1 < GOAL_PHASES.length ? GOAL_PHASES[index + 1] : undefined,
  };
}

/** 阶段是否已推进过（goal.status 是按顺序推进的，索引 <= 当前即算「已到达」）。 */
export function isPhaseReached(goalStatus: string | undefined, key: string): boolean {
  return phaseIndex(key) <= phaseIndex(goalStatus);
}
