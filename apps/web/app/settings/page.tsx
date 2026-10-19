"use client";

import { useEffect, useRef, useState } from "react";
import { api, API_BASE, ApiError } from "@/lib/api";
import type { Health } from "@/lib/types";
import { Badge, Button, Card, inputCls } from "@/components/ui";

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function SettingsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .get<Health>("/api/health")
      .then(setHealth)
      .catch((e) => setError(errMsg(e)));
  }, []);

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
      const resp = await api.post<{ ok: boolean; backup: string; counts: Record<string, number> }>(
        "/api/import",
        { version: payload.version ?? 1, data: payload.data ?? {} }
      );
      setNotice(`导入完成。导入前备份已保存到 ${resp.backup}。`);
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
          模型配置状态、数据备份与恢复。密钥只保存在服务端 `.env`，不会进入浏览器。
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
        <Card title="模型服务" desc="当前后端连通状态">
          <div className="grid gap-2 text-[12px]">
            <div className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
              <span>后端地址</span>
              <span className="font-mono text-[11px] text-muted">
                {API_BASE || "同源 /api（Next 反向代理 → 127.0.0.1:8000）"}
              </span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
              <span>模型配置</span>
              {health?.llm_configured ? (
                <Badge tone="done">已配置</Badge>
              ) : (
                <Badge tone="warn">演示模式</Badge>
              )}
            </div>
            {health?.demo && (
              <div className="rounded-lg bg-[#fffaf0] p-3 text-[11px] leading-relaxed text-[#8a6411]">
                未检测到模型密钥：教程、诊断、反馈等内容由演示生成器产生并在界面标注。要接入真实模型，在仓库根目录
                `.env` 中填写 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`，然后重启后端。
              </div>
            )}
          </div>
        </Card>

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

        <Card title="开发环境说明" desc="本版本边界">
          <ul className="grid gap-1.5 text-[11px] leading-relaxed text-muted">
            <li>· 单用户本地运行：SQLite 数据库位于 `services/api/data/aiedu.db`。</li>
            <li>· 公网部署前必须增加访问保护，本版本不宣称多用户安全。</li>
            <li>· 演示模式内容仅用于体验流程，不代表真实模型输出。</li>
            <li>· 生成内容需核验：模型自评不能作为准确性保证。</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
