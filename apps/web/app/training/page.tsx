"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, downloadFile } from "@/lib/api";
import type { TrainingList, TrainingRecord, TrainingStats } from "@/lib/types";
import { featureLabel, fmtTokens, usageSourceLabel } from "@/lib/format";
import { Badge, Button, Card, Empty } from "@/components/ui";

const PAGE_SIZE = 50;

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "全部记录" },
  { key: "material", label: "生成材料" },
  { key: "feedback", label: "用户反馈" },
];

export default function TrainingPage() {
  const [stats, setStats] = useState<TrainingStats | null>(null);
  const [records, setRecords] = useState<TrainingRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exporting, setExporting] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadStats = useCallback(async () => {
    const data = await api.get<TrainingStats>("/api/training/stats");
    setStats(data);
  }, []);

  const loadRecords = useCallback(
    async (sourceType: string, offset = 0) => {
      const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (sourceType) query.set("source_type", sourceType);
      const data = await api.get<TrainingList>(`/api/training/records?${query.toString()}`);
      setTotal(data.total);
      setRecords((prev) => (offset === 0 ? data.items : [...prev, ...data.items]));
    },
    []
  );

  useEffect(() => {
    (async () => {
      try {
        await Promise.all([loadStats(), loadRecords("", 0)]);
      } catch (e) {
        setError(errMsg(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [loadStats, loadRecords]);

  const changeFilter = async (key: string) => {
    setFilter(key);
    setLoading(true);
    setError("");
    try {
      await loadRecords(key, 0);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    setLoadingMore(true);
    setError("");
    try {
      await loadRecords(filter, records.length);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoadingMore(false);
    }
  };

  const exportData = async (key: string, path: string, filename: string, msg: string) => {
    setExporting(key);
    setError("");
    setNotice("");
    try {
      await downloadFile(path, filename);
      setNotice(msg);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setExporting("");
    }
  };

  const totals = stats?.totals ?? {};
  const feedbackStats = stats?.feedback ?? { positive: 0, negative: 0, with_comment: 0 };

  return (
    <div className="mx-auto max-w-[1450px] px-6 py-8 md:px-10">
      <div className="mb-6">
        <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">TEST DATA</div>
        <h1 className="mb-2 text-[27px] font-bold tracking-tight">测试版数据采集</h1>
        <p className="max-w-[760px] text-[13px] leading-relaxed text-muted">
          自动收集每次模型调用产生的「生成材料」（输入 prompt + 输出 + 模型与 token 元数据）以及用户主动提交的反馈，
          持久化到本地数据库，可导出 JSONL / JSON 供后续预训练与效果分析使用。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-[#f3c4c4] bg-[#fff5f5] px-4 py-3 text-[12px] text-[#a33]">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-xl border border-[#c6eee4] bg-[#f0fbf8] px-4 py-2.5 text-[12px] text-[#128b78]">
          {notice}
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">生成材料</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{totals.materials ?? 0}</div>
          <div className="mt-1 text-[11px] text-muted">
            其中演示数据 {totals.demo_materials ?? 0} 条
          </div>
        </div>
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">用户反馈</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{totals.feedback ?? 0}</div>
          <div className="mt-1 text-[11px] text-muted">
            👍 {feedbackStats.positive} · 👎 {feedbackStats.negative}
          </div>
        </div>
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">关联目标</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">{totals.goals ?? 0}</div>
          <div className="mt-1 text-[11px] text-muted">按目标聚合 token</div>
        </div>
        <div className="rounded-2xl border border-line bg-panel px-4 py-3.5 shadow-[0_8px_28px_#1925420b]">
          <div className="text-[12px] text-muted">材料 Token 总量</div>
          <div className="mt-2 text-[26px] font-bold tracking-tight">
            {fmtTokens(stats?.tokens.total_tokens)}
          </div>
          <div className="mt-1 text-[11px] text-muted">
            {usageSourceLabel(stats?.tokens.usage_source)} · {stats?.tokens.calls ?? 0} 次调用
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="grid gap-4">
          <Card title="导出训练数据" desc="JSONL 每行一个样本；material 为 messages 结构，feedback 含评分/标签/评论">
            <div className="grid gap-2">
              <Button
                onClick={() =>
                  exportData(
                    "all",
                    "/api/training/export?fmt=jsonl",
                    "aiedu-training-all.jsonl",
                    "已导出全部训练数据（JSONL）"
                  )
                }
                disabled={exporting !== ""}
              >
                {exporting === "all" ? "导出中…" : "导出全部（JSONL）"}
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  exportData(
                    "material",
                    "/api/training/export?source_type=material&fmt=jsonl",
                    "aiedu-training-material.jsonl",
                    "已导出生成材料"
                  )
                }
                disabled={exporting !== ""}
              >
                {exporting === "material" ? "导出中…" : "仅生成材料"}
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  exportData(
                    "feedback",
                    "/api/training/export?source_type=feedback&fmt=jsonl",
                    "aiedu-training-feedback.jsonl",
                    "已导出用户反馈"
                  )
                }
                disabled={exporting !== ""}
              >
                {exporting === "feedback" ? "导出中…" : "仅用户反馈"}
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  exportData(
                    "real",
                    "/api/training/export?exclude_demo=true&fmt=jsonl",
                    "aiedu-training-real-only.jsonl",
                    "已导出非演示材料 + 全部反馈"
                  )
                }
                disabled={exporting !== ""}
              >
                {exporting === "real" ? "导出中…" : "排除演示材料"}
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  exportData(
                    "json",
                    "/api/training/export?fmt=json",
                    "aiedu-training-all.json",
                    "已导出全部训练数据（JSON）"
                  )
                }
                disabled={exporting !== ""}
              >
                {exporting === "json" ? "导出中…" : "导出 JSON（便于查看）"}
              </Button>
            </div>
            <p className="mt-3 text-[10px] leading-relaxed text-muted">
              说明：演示模式下生成材料同样入库，但 metadata.demo=true；正式训练前可用「排除演示材料」过滤。
              数据同时包含在「偏好设置 → 导出备份」中，可整体迁移。
            </p>
          </Card>

          <Card title="按功能分布" desc="生成材料的 token 消耗">
            {!stats || stats.by_feature.length === 0 ? (
              <Empty>还没有生成材料。去学习目标页运行「一键生成教材」。</Empty>
            ) : (
              <div className="grid gap-1.5 text-[11px]">
                {stats.by_feature.map((item) => (
                  <div key={item.feature} className="flex items-center justify-between gap-2">
                    <span className="text-[#5a6a86]">{featureLabel(item.feature)}</span>
                    <span className="text-muted">{item.records} 条</span>
                    <b className="text-brand">{fmtTokens(item.total_tokens)}</b>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <Card
          title="最近记录"
          desc="生成材料与用户反馈按时间倒序；仅展示预览，完整内容见导出文件"
          actions={<Badge>共 {total} 条</Badge>}
        >
          <div className="mb-3 flex flex-wrap gap-1.5">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                onClick={() => changeFilter(item.key)}
                className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                  filter === item.key
                    ? "border-[#c9c2ff] bg-[#f0edff] text-brand"
                    : "border-line bg-white text-muted hover:border-[#c9c3ff]"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          {loading ? (
            <Empty>加载中…</Empty>
          ) : records.length === 0 ? (
            <Empty>当前筛选下还没有记录。</Empty>
          ) : (
            <div className="grid gap-2">
              {records.map((record) => (
                <div key={record.id} className="rounded-xl border border-line p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={record.source_type === "feedback" ? "warn" : "active"}>
                      {record.source_type === "feedback" ? "用户反馈" : "生成材料"}
                    </Badge>
                    <span className="text-[11px] font-semibold">{featureLabel(record.feature)}</span>
                    <span className="ml-auto text-[10px] text-muted">{record.created_at}</span>
                  </div>

                  {record.source_type === "feedback" ? (
                    <div className="mt-1.5 text-[11px] leading-relaxed">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={record.rating === 1 ? "text-[#128b78]" : "text-[#a33]"}>
                          {record.rating === 1 ? "👍 有帮助" : "👎 需改进"}
                        </span>
                        {record.tags.map((tag) => (
                          <span key={tag} className="rounded bg-[#f0f2f7] px-1.5 py-0.5 text-[10px] text-[#68748a]">
                            {tag}
                          </span>
                        ))}
                      </div>
                      {record.comment && <div className="mt-1 text-muted">{record.comment}</div>}
                    </div>
                  ) : (
                    <div className="mt-1.5 text-[11px] leading-relaxed text-muted">
                      <div className="line-clamp-2 whitespace-pre-wrap">{record.output_preview}</div>
                      <div className="mt-1 text-[10px] text-[#99a2b3]">
                        {record.model_provider} · {fmtTokens(record.token_usage.total_tokens)} tokens ·{" "}
                        {record.output_chars} 字符
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {records.length < total && (
                <div className="pt-1 text-center">
                  <Button variant="secondary" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? "加载中…" : `加载更多（还有 ${total - records.length} 条）`}
                  </Button>
                </div>
              )}
            </div>
          )}

          <p className="mt-3 text-[10px] leading-relaxed text-muted">
            数据仅保存在本机 `services/api/data/aiedu.db` 的 `training_records` 表；导出文件可直接用于后续训练或人工审阅。
          </p>
        </Card>
      </div>
    </div>
  );
}
