"use client";

import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button, Card, inputCls } from "@/components/ui";

import AppearanceSettings from "@/components/AppearanceSettings";
import ModelSettings from "@/components/ModelSettings";
import FormatSpecs from "@/components/FormatSpecs";
import IndependentEvalSettings from "@/components/IndependentEvalSettings";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function SettingsPage() {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);


  const exportData = async () => {
    setBusy("export");
    setError("");
    try {
      const data = await api.get<Record<string, unknown>>("/api/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aiedu-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setNotice("已导出学习数据备份。");
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const importFile = async (file: File) => {
    setBusy("import");
    setError("");
    setNotice("");
    try {
      const text = await file.text();
      const payload = JSON.parse(text) as { version?: number; data?: Record<string, unknown> };
      const body = { version: payload.version ?? 1, data: payload.data ?? {} };
      try {
        const resp = await api.post<{ ok: boolean; backup: string; counts: Record<string, number> }>(
          "/api/import",
          body
        );
        setNotice(`导入完成。导入前备份已保存到 ${resp.backup}。`);
      } catch (e) {
        // 安全阀：备份不含知识网络数据时会先拦截，用户明确确认后再强制覆盖
        if (e instanceof ApiError && e.code === "knowledge_would_be_cleared") {
          if (!window.confirm(`${e.message}\n\n仍要覆盖导入吗？`)) {
            setNotice("已取消导入，现有数据未改动。");
            return;
          }
          const resp = await api.post<{ ok: boolean; backup: string }>("/api/import?force=true", body);
          setNotice(`已按确认覆盖导入。导入前备份已保存到 ${resp.backup}。`);
          return;
        }
        throw e;
      }
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy("");
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="mx-auto max-w-[1100px] px-6 py-8 md:px-10">
      <div className="mb-6">
        <div className="mb-2 text-[11px] font-bold tracking-[1.5px] text-brand">PREFERENCES</div>
        <h1 className="mb-2 text-[27px] font-bold tracking-tight">偏好设置</h1>
        <p className="max-w-[700px] text-[13px] leading-relaxed text-muted">
          让学习环境适合你：外观、模型接入与学习数据备份。
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

      <div className="grid gap-4 lg:grid-cols-2">
        <AppearanceSettings />
        <div className="lg:row-span-2"><ModelSettings /></div>
        <div className="lg:col-span-2"><FormatSpecs /></div>
        <IndependentEvalSettings />

        <Card title="数据备份" desc="导出 / 导入版本化 JSON；导入前自动备份当前数据">
          <div className="grid gap-3 text-[12px]">
            <div className="rounded-lg border border-line p-3">
              <div className="mb-1.5 font-semibold">导出全部学习数据</div>
              <div className="mb-2 text-[11px] text-muted">包含目标、计划、验收标准、教程版本、尝试与证据、复盘、知识网络。</div>
              <Button onClick={exportData} disabled={busy === "export"}>
                {busy === "export" ? "导出中…" : "下载 JSON 备份"}
              </Button>
            </div>
            <div className="rounded-lg border border-line p-3">
              <div className="mb-1.5 font-semibold">从备份恢复（覆盖当前数据）</div>
              <div className="mb-2 text-[11px] text-muted">
                导入前会自动在当前数据库旁生成一份备份文件。
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="application/json,.json"
                className={inputCls}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void importFile(f);
                }}
                disabled={busy === "import"}
              />
            </div>
          </div>
        </Card>


      </div>
    </div>
  );
}
