"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, Field, inputCls } from "./ui";

type EvalSettings = {
  enabled: boolean;
  has_key: boolean;
  masked_key: string;
  active_model: string;
};

type RubricResult = {
  score?: number;
  summary?: string;
  issues?: string[];
};

type EvalResult = {
  status: string;
  reason?: string;
  demo?: boolean;
  model?: string;
  result?: {
    knowledge_quality?: RubricResult;
    teaching_quality?: RubricResult;
    overall_recommendation?: string;
  };
  usage?: { total_tokens?: number; usage_source?: string };
};

export default function IndependentEvalSettings() {
  const [settings, setSettings] = useState<EvalSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [versionId, setVersionId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<EvalResult | null>(null);

  useEffect(() => {
    api.get<EvalSettings>("/api/settings/models/evaluation").then((data) => {
      setSettings(data);
    }).catch((e: Error) => setError(e.message));
  }, []);

  const save = async () => {
    if (!settings) return;
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const next = await api.put<EvalSettings>("/api/settings/models/evaluation", {
        enabled: settings.enabled,
        api_key: clearKey ? "" : apiKey ? apiKey : null,
      });
      setSettings(next);
      setApiKey("");
      setClearKey(false);
      setNotice(next.enabled && !next.has_key ? "已保存；未填评估 Key 前不会调用模型。" : "评估设置已保存。");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const runEvaluation = async () => {
    if (!versionId.trim()) return;
    setBusy("evaluate");
    setError("");
    setNotice("");
    setResult(null);
    try {
      const data = await api.post<EvalResult>(`/api/settings/models/evaluate/${encodeURIComponent(versionId.trim())}`);
      setResult(data);
      if (data.status === "skipped") {
        setNotice(data.reason === "independent_eval_disabled" ? "评估未启用，已跳过。" : "缺少评估 Key，已跳过。");
      } else {
        setNotice("独立评估完成，结果已写入该版本质量报告。");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Card title="独立质量评估" desc="可选功能：用独立模型按知识梳理与教学质量两个量规评估指定教程版本">
      {!settings ? (
        <p className="text-xs text-muted">加载中…</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={settings.enabled ? "done" : "neutral"}>{settings.enabled ? "已启用" : "未启用"}</Badge>
            <Badge tone={settings.has_key ? "done" : "warn"}>{settings.has_key ? `Key ${settings.masked_key}` : "未填 Key"}</Badge>
          </div>
          <p className="mb-3 text-xs text-muted">
            评估端点和模型沿用当前启用的模型配置；API Key 独立保存。未启用或未填 Key 时完全跳过，不产生调用。
          </p>
          <label className="mb-3 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={settings.enabled}
              onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })}
            />
            启用独立 LLM 质量评估
          </label>
          <Field label="评估专用 API Key">
            <input
              type="password"
              autoComplete="new-password"
              className={inputCls}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={settings.has_key ? "已保存密钥；留空保持不变" : "输入评估专用密钥"}
              disabled={clearKey}
            />
          </Field>
          {settings.has_key && (
            <label className="mb-3 flex gap-1 text-xs text-muted">
              <input type="checkbox" checked={clearKey} onChange={(e) => setClearKey(e.target.checked)} />
              清除已保存密钥
            </label>
          )}
          <div className="flex flex-wrap items-end gap-2">
            <Button variant="secondary" onClick={() => void save()} disabled={busy !== ""}>
              {busy === "save" ? "保存中…" : "保存评估设置"}
            </Button>
          </div>
          <div className="mt-4 border-t border-line pt-4">
            <Field label="教程版本 ID">
              <input
                className={inputCls}
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
                placeholder="从教程详情复制 version id"
              />
            </Field>
            <Button onClick={() => void runEvaluation()} disabled={busy !== "" || !versionId.trim()}>
              {busy === "evaluate" ? "评估中…" : "运行评估"}
            </Button>
            {settings.enabled && !settings.has_key && (
              <p className="mt-2 text-xs text-amber">已启用但未填 Key：运行时仍会跳过。</p>
            )}
          </div>
          {error && <div role="alert" className="mt-3 rounded-xl border border-red-400/40 bg-red-500/10 p-3 text-sm">{error}</div>}
          {notice && <p role="status" className="mt-3 text-sm text-teal">{notice}</p>}
          {result?.result && (
            <div className="mt-4 grid gap-3 text-xs">
              {[
                { label: "知识梳理质量", data: result.result.knowledge_quality },
                { label: "教学质量", data: result.result.teaching_quality },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-line p-3">
                  <div className="font-semibold">{item.label}{typeof item.data?.score === "number" ? ` · ${item.data.score}/5` : ""}</div>
                  <p className="mt-1 text-muted">{item.data?.summary}</p>
                  {item.data?.issues?.length ? <ul className="mt-2 list-disc pl-4">{item.data.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul> : null}
                </div>
              ))}
              {result.result.overall_recommendation && <p className="text-muted">建议：{result.result.overall_recommendation}</p>}
            </div>
          )}
          {result && result.status === "skipped" && <p className="mt-3 text-xs text-muted">状态：已跳过（{result.reason}）。</p>}
        </>
      )}
    </Card>
  );
}
