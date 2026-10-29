import { api } from "@/lib/api";
import type { Tutorial } from "@/lib/types";

/**
 * 「一键生成不停在大纲」的默认行为：
 * 一键生成的最后一步默认是「一键生成全部章节」。如果因为中断 / 刷新 / 响应丢失，
 * 教程停在了「只有大纲、没有章节」的状态，进入相关页面时自动续跑章节生成，
 * 不再要求用户手动点击「一键生成全部章节」。
 */

/** 大纲在此窗口期内生成过 → 视为「一键生成刚停在大纲」，自动续跑；更早的大纲视为用户的有意选择，只展示按钮。 */
export const OUTLINE_STALL_WINDOW_MS = 30 * 60 * 1000;

/** 大纲已就绪但还没有任何章节，且大纲是最近生成的。 */
export function outlineOnlyRecently(tutorial: Tutorial, now = Date.now()): boolean {
  const version = tutorial.current_version;
  const content = version?.content;
  if (!version || !content) return false;
  if (!(content.outline?.length)) return false;
  if ((content.sections?.length ?? 0) > 0) return false;
  const createdAt = version.created_at;
  if (!createdAt) return false;
  const time = new Date(createdAt).getTime();
  if (!Number.isFinite(time)) return false;
  return now - time <= OUTLINE_STALL_WINDOW_MS;
}

/** 续跑「一键生成全部章节」：提交后台任务并返回 job_id。后端对重复提交幂等（复用进行中的任务）。 */
export async function continueAllSections(tutorialId: string): Promise<string> {
  const resp = await api.post<{ job_id: string }>(`/api/tutorials/${tutorialId}/sections/generate`);
  return resp.job_id;
}

/**
 * 用户主动点了「只生成大纲」时记录下来（按目标、按标签页），自动续跑不再推翻这个选择：
 * 刻意只看大纲的场景不应该被自动花钱补齐全部章节。同标签页后续点「一键生成」或
 * 「生成全部章节」会清除记录，恢复默认行为。
 */
const OUTLINE_ONLY_PREFIX = "aiedu:outline-only-goal:";

export function markOutlineOnlyGoal(goalId: string): void {
  try {
    sessionStorage.setItem(OUTLINE_ONLY_PREFIX + goalId, "1");
  } catch {
    // 隐私模式等场景下 sessionStorage 不可用，退化为「不记忆」，不影响主流程
  }
}

export function clearOutlineOnlyGoal(goalId: string): void {
  try {
    sessionStorage.removeItem(OUTLINE_ONLY_PREFIX + goalId);
  } catch {
    // 同上
  }
}

export function outlineOnlyChosen(goalId: string): boolean {
  try {
    return sessionStorage.getItem(OUTLINE_ONLY_PREFIX + goalId) === "1";
  } catch {
    return false;
  }
}

/**
 * 自动续跑每个目标、每个标签页只做一次。
 * 章节任务失败后教程仍然只有大纲，如果每次刷新都自动续跑，就会在模型持续报错时
 * 反复提交一整轮章节生成（每次都是几十万 token 的真实开销）。留一次自动尝试，
 * 之后交给用户显式点按钮重试。
 */
const AUTO_RESUME_PREFIX = "aiedu:auto-resume-goal:";

export function markAutoResumeTried(goalId: string): void {
  try {
    sessionStorage.setItem(AUTO_RESUME_PREFIX + goalId, "1");
  } catch {
    // 隐私模式等场景下 sessionStorage 不可用，退化为「不记忆」，不影响主流程
  }
}

export function autoResumeTried(goalId: string): boolean {
  try {
    return sessionStorage.getItem(AUTO_RESUME_PREFIX + goalId) === "1";
  } catch {
    return false;
  }
}

/** 用户显式要求生成全部章节时重置闸门，让后续中断仍能自动续跑。 */
export function clearAutoResumeTried(goalId: string): void {
  try {
    sessionStorage.removeItem(AUTO_RESUME_PREFIX + goalId);
  } catch {
    // 同上
  }
}
