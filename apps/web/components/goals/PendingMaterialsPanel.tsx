"use client";

import { useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui";
import {
  KIND_FALLBACK_LABELS,
  formatSize,
  materialExtensionsText,
  useMaterialLimits,
  validateMaterialFile,
} from "@/components/goals/MaterialsPanel";

export type PendingMaterialStatus = "pending" | "uploading" | "done" | "error";

/** 「创建并生成教程」里暂存的待上传材料：学习目标创建成功后才真正上传。 */
export interface PendingMaterial {
  key: string;
  file: File;
  kind: string;
  status: PendingMaterialStatus;
  progress: number;
  error: string;
}

/**
 * 创建页专用的「参考资料 / 例题来源」暂存区：
 * 此时目标尚未创建，材料接口挂在目标下（/api/goals/{goal_id}/materials），
 * 因此文件先留在浏览器里（校验规则与目标页上传一致），
 * 点击「创建并自动生成教程」或「仅创建目标」时随新目标一起上传。
 * 文件列表状态由父组件持有，提交逻辑负责推进 status / progress。
 */
export function PendingMaterialsPanel({
  files,
  busy,
  onAdd,
  onRemove,
}: {
  files: PendingMaterial[];
  busy: boolean;
  onAdd: (files: File[], kind: string) => void;
  onRemove: (key: string) => void;
}) {
  const limits = useMaterialLimits();
  const [kind, setKind] = useState("reference");
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const addFiles = useCallback(
    (list: FileList | File[]) => {
      if (busy) return;
      const selected = Array.from(list);
      if (selected.length === 0) return;
      const accepted: File[] = [];
      const rejected: string[] = [];
      selected.forEach((file) => {
        const problem = validateMaterialFile(file, limits);
        if (problem) rejected.push(`${file.name}：${problem}`);
        else accepted.push(file);
      });
      setMessage(rejected.join("；"));
      if (accepted.length > 0) onAdd(accepted, kind);
      if (inputRef.current) inputRef.current.value = "";
    },
    [busy, kind, limits, onAdd]
  );

  const kindLabel = (key: string) =>
    limits.kinds.find((item) => item.key === key)?.label ?? KIND_FALLBACK_LABELS[key] ?? key;

  return (
    <div className="grid gap-2.5">
      <div className="rounded-xl border border-line bg-[#fbfcff] p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold text-[#5a6a86]">上传分类</span>
            <div className="flex gap-1.5" role="radiogroup" aria-label="材料分类">
              {limits.kinds.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="radio"
                  aria-checked={kind === item.key}
                  onClick={() => setKind(item.key)}
                  className={`rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                    kind === item.key
                      ? "border-[#c9c2ff] bg-[#f0edff] text-brand"
                      : "border-line bg-white text-[#5a6a86] hover:border-[#c9c3ff]"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <Button variant="secondary" disabled={busy} onClick={() => inputRef.current?.click()}>
            选择文件（可多选）
          </Button>
        </div>

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            addFiles(event.dataTransfer.files);
          }}
          className={`rounded-xl border border-dashed px-3 py-4 text-center text-[11px] transition-colors ${
            dragging ? "border-brand bg-[#f0edff] text-brand" : "border-[#d5dbe8] bg-white text-muted"
          }`}
        >
          拖拽文件到这里，或点击右上角「选择文件」。
          <div className="mt-1 text-[10px] text-[#99a2b3]">
            支持 {materialExtensionsText(limits)}；单文件上限 {formatSize(limits.max_bytes)}；
            提交时先创建学习目标，再把这些文件上传到该目标并注入生成依据。
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          multiple
          className="sr-only"
          aria-label="选择参考资料或例题来源文件"
          accept={limits.allowed_extensions.join(",")}
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
          }}
        />

        {message && (
          <div aria-live="polite" className="mt-2 rounded-lg bg-[#fff5f5] px-2.5 py-1.5 text-[11px] text-[#a33]">
            {message}
          </div>
        )}

        {files.length > 0 && (
          <ul className="mt-2 grid gap-1.5">
            {files.map((row) => (
              <li key={row.key} className="rounded-lg border border-line bg-white px-2.5 py-2 text-[11px]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-[#f0f2f7] px-2 py-0.5 text-[10px] font-semibold text-[#68748a]">
                    {kindLabel(row.kind)}
                  </span>
                  <span className="truncate font-semibold text-[#33415c]">{row.file.name}</span>
                  <span className="text-[10px] text-muted">{formatSize(row.file.size)}</span>
                  <span className="ml-auto text-[10px] font-semibold">
                    {row.status === "done" && <span className="text-[#128b78]">已上传</span>}
                    {row.status === "uploading" && <span className="text-brand">上传中 {row.progress}%</span>}
                    {row.status === "pending" && <span className="text-muted">待上传</span>}
                    {row.status === "error" && <span className="text-[#a33]">失败</span>}
                  </span>
                  <button
                    type="button"
                    disabled={busy || row.status === "uploading"}
                    className="text-[10px] text-muted hover:text-[#c33] disabled:opacity-40"
                    onClick={() => onRemove(row.key)}
                  >
                    移除
                  </button>
                </div>
                {row.status === "uploading" && (
                  <div
                    className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[#eef0f7]"
                    role="progressbar"
                    aria-valuenow={row.progress}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${row.file.name} 上传进度`}
                  >
                    <div className="h-full rounded-full bg-brand transition-[width]" style={{ width: `${row.progress}%` }} />
                  </div>
                )}
                {row.status === "error" && <div className="mt-1 text-[10px] text-[#a33]">{row.error}</div>}
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="text-[10px] leading-relaxed text-[#99a2b3]">
        文件先暂存在浏览器里，点击下方按钮提交时才上传；刷新页面后需重新选择。
      </p>
    </div>
  );
}
