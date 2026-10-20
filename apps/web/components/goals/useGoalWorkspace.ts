"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type {
  Assessment,
  Attempt,
  Criterion,
  Goal,
  GoalAssessment,
  GoalUsage,
  Knowledge,
  Material,
  Plan,
  Proposal,
  Reflection,
  Task,
  Tutorial,
} from "@/lib/types";

/** 各阶段页面只加载自己需要的数据切片（避免每个子页都拉全量）。 */
export interface WorkspaceSlices {
  diagnosis?: boolean;
  plan?: boolean;
  criteria?: boolean;
  tutorials?: boolean;
  tasks?: boolean;
  attempts?: boolean;
  assessments?: boolean;
  reflections?: boolean;
  proposals?: boolean;
  materials?: boolean;
  usage?: boolean;
}

export interface GoalWorkspaceData {
  goal: Goal | null;
  diagnosis: GoalAssessment | null;
  plan: Plan | null;
  criteria: Criterion[];
  tutorials: Tutorial[];
  tasks: Task[];
  attempts: Record<string, Attempt[]>;
  assessments: Assessment[];
  reflections: Reflection[];
  proposals: Proposal[];
  materials: Material[];
  usage: GoalUsage | null;
}

const EMPTY: GoalWorkspaceData = {
  goal: null,
  diagnosis: null,
  plan: null,
  criteria: [],
  tutorials: [],
  tasks: [],
  attempts: {},
  assessments: [],
  reflections: [],
  proposals: [],
  materials: [],
  usage: null,
};

export function emptyWorkspace(): GoalWorkspaceData {
  return { ...EMPTY, criteria: [], tutorials: [], tasks: [], assessments: [], reflections: [], proposals: [], materials: [], attempts: {} };
}

export function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export interface GoalWorkspaceState {
  goalId: string;
  data: GoalWorkspaceData;
  loading: boolean;
  busy: string;
  error: string;
  notice: string;
  setError: (message: string) => void;
  setNotice: (message: string) => void;
  setBusy: (key: string) => void;
  /** 重新拉取（按当前切片） */
  reload: () => Promise<void>;
  /** 统一的操作包装：置忙 → 执行 → 重载 → 提示，失败落到 error */
  run: (key: string, fn: () => Promise<void>, message?: string) => Promise<void>;
}

export function useGoalWorkspace(goalId: string, slices: WorkspaceSlices): GoalWorkspaceState {
  const [data, setData] = useState<GoalWorkspaceData>(emptyWorkspace);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    if (!goalId) return;
    const goalData = await api.get<Goal>(`/api/goals/${goalId}`);

    const [
      diagnosis,
      plan,
      criteria,
      tutorials,
      tasks,
      assessments,
      reflections,
      materials,
      usage,
    ] = await Promise.all([
      slices.diagnosis
        ? api.get<GoalAssessment | null>(`/api/goals/${goalId}/diagnose`).catch(() => null)
        : Promise.resolve(null),
      slices.plan
        ? api.get<Plan | null>(`/api/goals/${goalId}/plan`).catch(() => null)
        : Promise.resolve(null),
      slices.criteria
        ? api.get<Criterion[]>(`/api/goals/${goalId}/criteria`).catch(() => [])
        : Promise.resolve([] as Criterion[]),
      slices.tutorials
        ? api.get<Tutorial[]>(`/api/goals/${goalId}/tutorials`).catch(() => [])
        : Promise.resolve([] as Tutorial[]),
      slices.tasks
        ? api.get<Task[]>(`/api/goals/${goalId}/tasks`).catch(() => [])
        : Promise.resolve([] as Task[]),
      slices.assessments
        ? api.get<Assessment[]>(`/api/goals/${goalId}/assessments`).catch(() => [])
        : Promise.resolve([] as Assessment[]),
      slices.reflections
        ? api.get<Reflection[]>(`/api/goals/${goalId}/reflections`).catch(() => [])
        : Promise.resolve([] as Reflection[]),
      slices.materials
        ? api.get<Material[]>(`/api/goals/${goalId}/materials`).catch(() => [])
        : Promise.resolve([] as Material[]),
      slices.usage
        ? api.get<GoalUsage>(`/api/goals/${goalId}/usage`).catch(() => null)
        : Promise.resolve(null),
    ]);

    let proposals: Proposal[] = [];
    if (slices.proposals) {
      const knowledge = await api
        .get<Knowledge>("/api/knowledge")
        .catch(() => ({ concepts: [], relations: [], proposals: [] }) as Knowledge);
      proposals = knowledge.proposals.filter((item) => item.status === "pending");
    }

    const attempts: Record<string, Attempt[]> = {};
    if (slices.tasks && slices.attempts) {
      const pairs = await Promise.all(
        tasks.map(
          async (task) =>
            [task.id, await api.get<Attempt[]>(`/api/tasks/${task.id}/attempts`).catch(() => [])] as const
        )
      );
      Object.assign(attempts, Object.fromEntries(pairs));
    }

    setData({
      goal: goalData,
      diagnosis,
      plan,
      criteria,
      tutorials,
      tasks,
      attempts,
      assessments,
      reflections,
      proposals,
      materials,
      usage,
    });
    setLoading(false);
  }, [goalId, slices]);

  useEffect(() => {
    // 挂载时按 URL 拉取工作区数据；该规则对异步 setState 误报
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load().catch((e) => {
      setError(errMsg(e));
      setLoading(false);
    });
  }, [load]);

  const reload = useCallback(async () => {
    await load();
  }, [load]);

  const run = useCallback(
    async (key: string, fn: () => Promise<void>, message = "完成") => {
      setBusy(key);
      setError("");
      setNotice("");
      try {
        await fn();
        await load();
        setNotice(message);
      } catch (e) {
        setError(errMsg(e));
      } finally {
        setBusy("");
      }
    },
    [load]
  );

  return {
    goalId,
    data,
    loading,
    busy,
    error,
    notice,
    setError,
    setNotice,
    setBusy,
    reload,
    run,
  };
}
