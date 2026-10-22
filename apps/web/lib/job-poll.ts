import { api } from "./api";
import type { GenerationJob } from "./types";
import { fmtTokens } from "./format";

/**
 * 生成任务轮询：把「一键生成 / 章节生成 / 配套文件补齐」共用的轮询逻辑收在一处。
 *
 * 修掉的三类前端问题（都来自页面里手写 setTimeout 循环）：
 * 1. 重复轮询：连点或再次提交会叠加多个计时器，同一 job 被多路轮询；这里先返回取消函数，
 *    调用方在启动新轮询前取消旧的（startJobPolling 返回 stop）。
 * 2. 卸载后仍在跑：页面跳走后计时器继续 setState；调用方在 useEffect 清理阶段 stop()。
 * 3. 无限轮询：job 卡在 queued/running 时永远刷下去；这里加上限（默认约 20 分钟）后停止并提示。
 */
export interface JobPollHandlers {
  /** 每次拿到最新状态（用于刷新进度条） */
  onUpdate?: (job: GenerationJob) => void;
  /** job 完成（可异步，例如 reload 数据） */
  onDone: (job: GenerationJob) => void | Promise<void>;
  /** job 失败（业务失败，非网络问题） */
  onFailed: (message: string) => void;
  /** 请求异常 / 轮询超时 */
  onError: (message: string) => void;
  intervalMs?: number;
  firstDelayMs?: number;
  /** 最大轮询次数，防止状态卡死时无限请求 */
  maxTicks?: number;
}

const JOB_LABELS: Record<string, string> = {
  tutorial_sections: "教程章节",
  tutorial_companions: "配套文件",
  tutorial_outline: "教程大纲",
};

export function jobLabel(job: GenerationJob): string {
  return JOB_LABELS[job.job_type] ?? "生成任务";
}

/** 完成提示按任务类型区分：章节 vs 配套文件（两者共用同一个进度面板）。 */
export function jobDoneMessage(job: GenerationJob): string {
  const tokens = job.token_usage?.total_tokens ?? 0;
  const suffix = tokens ? ` · 本次消耗 ${fmtTokens(tokens)} tokens` : "";
  if (job.job_type === "tutorial_companions") return `配套文件（知识速查 / 额外练习）已生成${suffix}`;
  if (job.job_type === "tutorial_sections") return `教程章节已生成，质量检查完成${suffix}`;
  return `${jobLabel(job)}已完成${suffix}`;
}

export function jobFailedMessage(job: GenerationJob): string {
  const label = jobLabel(job);
  return `${label}生成失败（${job.error_code || "unknown"}）${
    job.error_message ? `：${job.error_message}` : "，请检查模型配置后重试"
  }`;
}

/**
 * 开始轮询一个生成任务，返回取消函数。
 * 调用方必须在「再次提交任务」和「组件卸载」时调用 cancel，否则会留下僵尸计时器。
 */
export function startJobPolling(jobId: string, handlers: JobPollHandlers): () => void {
  const intervalMs = handlers.intervalMs ?? 2000;
  const firstDelayMs = handlers.firstDelayMs ?? 1200;
  const maxTicks = handlers.maxTicks ?? 600;

  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let ticks = 0;

  const clear = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const schedule = (delay: number) => {
    if (cancelled) return;
    clear();
    timer = setTimeout(() => {
      void tick();
    }, delay);
  };

  const tick = async () => {
    if (cancelled) return;
    ticks += 1;
    if (ticks > maxTicks) {
      handlers.onError("生成任务长时间未结束，已停止自动刷新；稍后刷新页面查看结果。");
      return;
    }
    try {
      const job = await api.get<GenerationJob>(`/api/generation-jobs/${jobId}`);
      if (cancelled) return;
      handlers.onUpdate?.(job);
      if (job.status === "done") {
        try {
          await handlers.onDone(job);
        } catch (e) {
          handlers.onError(e instanceof Error ? e.message : String(e));
        }
        return;
      }
      if (job.status === "failed") {
        handlers.onFailed(jobFailedMessage(job));
        return;
      }
      schedule(intervalMs);
    } catch (e) {
      if (cancelled) return;
      handlers.onError(e instanceof Error ? e.message : String(e));
    }
  };

  schedule(firstDelayMs);
  return () => {
    cancelled = true;
    clear();
  };
}
