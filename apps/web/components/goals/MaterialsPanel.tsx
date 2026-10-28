"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, uploadFile } from "@/lib/api";
import type { Material, MaterialLimits } from "@/lib/types";
import { Badge, Button, Empty } from "@/components/ui";
import { errMsg } from "@/components/goals/useGoalWorkspace";

const FALLBACK_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".gif",
];

const FALLBACK_LIMITS: MaterialLimits = {
  max_bytes: 20 * 1024 * 1024,
  allowed_extensions: FALLBACK_EXTENSIONS,
  kinds: [
    { key: "reference", label: "参考资料" },
    { key: "example_source", label: "例题来源" },
  ],
};

const EXTRACT_LABEL: Record<string, { label: string; tone: "done" | "warn" | "neutral" }> = {
  ok: { label: "已抽取正文", tone: "done" },
  empty: { label: "未抽取到正文", tone: "warn" },
  unsupported: { label: "仅登记来源", tone: "neutral" },
  failed: { label: "抽取失败", tone: "warn" },
  pending: { label: "待抽取", tone: "neutral" },
};

export function formatSize(bytes: number): string {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

type UploadStatus = "queued" | "uploading" | "done" | "error";

interface QueueItem {
  key: string;
  file: File;
  kind: string;
  progress: number;
  status: UploadStatus;
  error: string;
}

/** 拉取上传限制（扩展名 / 单文件上限 / 分类），失败时退回内置默认值。 */
export function useMaterialLimits(): MaterialLimits {
  const [limits, setLimits] = useState<MaterialLimits>(FALLBACK_LIMITS);
  useEffect(() => {
    api
      .get<MaterialLimits>("/api/materials/limits")
      .then((data) => setLimits(data))
      .catch(() => setLimits(FALLBACK_LIMITS));
  }, []);
  return limits;
}

export function materialExtensionsText(limits: MaterialLimits): string {
  return limits.allowed_extensions.map((ext) => ext.replace(".", "")).join(" / ");
}

/** 与后端 save_upload 同规则的客户端预校验；返回错误文案，空串表示通过。 */
export function validateMaterialFile(file: File, limits: MaterialLimits): string {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!limits.allowed_extensions.includes(ext)) {
    return `不支持的类型「${ext || "无扩展名"}」，仅支持 ${materialExtensionsText(limits)}`;
  }
  if (file.size > limits.max_bytes) {
    return `文件过大（${formatSize(file.size)}），单文件上限 ${formatSize(limits.max_bytes)}`;
  }
  if (file.size === 0) return "文件为空";
  return "";
}

export const KIND_FALLBACK_LABELS: Record<string, string> = {
  reference: "参考资料",
  example_source: "例题来源",
};

/**
 * 参考资料 / 例题来源上传区：
 * 多文件选择或拖拽、类型与大小校验、逐文件进度、删除、失败重试。
 * 上传成功后由父组件重新拉取材料列表（onChanged）。
 */
export function MaterialsPanel({
  goalId,
  materials,
  onChanged,
  hint = "已上传的材料会作为依据注入「价值诊断 / 学习计划 / 教程生成」的 prompt（超长自动截断）。",
}: {
  goalId: string;
  materials: Material[];
  onChanged: () => Promise<void> | void;
  hint?: string;
}) {
  const limits = useMaterialLimits();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [kind, setKind] = useState("reference");
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState("");
  const [deleting, setDeleting] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const queueRef = useRef<QueueItem[]>([]);
  const busyRef = useRef(false);

  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);

  const allowedText = useMemo(() => materialExtensionsText(limits), [limits]);

  const validate = useCallback((file: File) => validateMaterialFile(file, limits), [limits]);

  const setRow = useCallback((key: string, patch: Partial<QueueItem>) => {
    setQueue((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }, []);

  const uploadOne = useCallback(
    async (item: QueueItem) => {
      const form = new FormData();
      form.append("file", item.file, item.file.name);
      form.append("kind", item.kind);
      await uploadFile<Material>(`/api/goals/${goalId}/materials`, form, (percent) => {
        setQueue((prev) => prev.map((row) => (row.key === item.key ? { ...row, progress: percent } : row)));
      });
    },
    [goalId]
  );

  /** 串行消费队列：逐条上传，失败只影响该条，其余继续。 */
  const pump = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    try {
      for (;;) {
        const next = queueRef.current.find((row) => row.status === "queued");
        if (!next) break;
        const current: QueueItem = { ...next, status: "uploading", progress: 0, error: "" };
        queueRef.current = queueRef.current.map((row) => (row.key === next.key ? current : row));
        setRow(next.key, { status: "uploading", progress: 0, error: "" });
        try {
          await uploadOne(current);
          queueRef.current = queueRef.current.map((row) =>
            row.key === next.key ? { ...row, status: "done", progress: 100 } : row
          );
          setRow(next.key, { status: "done", progress: 100 });
          await onChanged();
        } catch (e) {
          const error = errMsg(e);
          queueRef.current = queueRef.current.map((row) =>
            row.key === next.key ? { ...row, status: "error", error } : row
          );
          setRow(next.key, { status: "error", error });
        }
      }
    } finally {
      busyRef.current = false;
    }
  }, [onChanged, setRow, uploadOne]);

  useEffect(() => {
    if (queue.some((row) => row.status === "queued")) void pump();
  }, [queue, pump]);

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const list = Array.from(files);
      if (list.length === 0) return;
      const rows: QueueItem[] = [];
      const rejected: string[] = [];
      list.forEach((file, index) => {
        const problem = validate(file);
        if (problem) {
          rejected.push(`${file.name}：${problem}`);
          return;
        }
        rows.push({
          key: `${Date.now()}-${index}-${file.name}`,
          file,
          kind,
          progress: 0,
          status: "queued",
          error: "",
        });
      });
      setMessage(rejected.join("；"));
      if (rows.length > 0) setQueue((prev) => [...prev, ...rows]);
      if (inputRef.current) inputRef.current.value = "";
    },
    [kind, validate]
  );

  const removeRow = (key: string) => {
    setQueue((prev) => prev.filter((row) => row.key !== key));
  };

  const removeMaterial = async (material: Material) => {
    if (!window.confirm(`删除材料「${material.filename}」？删除后不再注入生成 prompt。`)) return;
    setDeleting(material.id);
    setMessage("");
    try {
      await api.del(`/api/materials/${material.id}`);
      await onChanged();
      setMessage(`已删除「${material.filename}」`);
    } catch (e) {
      setMessage(errMsg(e));
    } finally {
      setDeleting("");
    }
  };

  const counts: Record<string, number> = { reference: 0, example_source: 0 };
  materials.forEach((material) => {
    counts[material.kind] = (counts[material.kind] ?? 0) + 1;
  });

  return (
    <div className="grid gap-3">
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
          <Button variant="secondary" onClick={() => inputRef.current?.click()}>
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
            支持 {allowedText}；单文件上限 {formatSize(limits.max_bytes)}；可反复追加，上传后立即参与生成。
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

        {queue.length > 0 && (
          <ul className="mt-2 grid gap-1.5">
            {queue.map((row) => (
              <li key={row.key} className="rounded-lg border border-line bg-white px-2.5 py-2 text-[11px]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-semibold text-[#33415c]">{row.file.name}</span>
                  <span className="text-[10px] text-muted">{formatSize(row.file.size)}</span>
                  <span className="ml-auto text-[10px] font-semibold">
                    {row.status === "done" && <span className="text-[#128b78]">上传完成</span>}
                    {row.status === "uploading" && <span className="text-brand">上传中 {row.progress}%</span>}
                    {row.status === "queued" && <span className="text-muted">排队中</span>}
                    {row.status === "error" && <span className="text-[#a33]">失败</span>}
                  </span>
                </div>
                {(row.status === "uploading" || row.status === "done") && (
                  <div
                    className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[#eef0f7]"
                    role="progressbar"
                    aria-valuenow={row.progress}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${row.file.name} 上传进度`}
                  >
                    <div
                      className={`h-full rounded-full transition-[width] ${
                        row.status === "done" ? "bg-teal" : "bg-brand"
                      }`}
                      style={{ width: `${row.progress}%` }}
                    />
                  </div>
                )}
                {(row.status === "error" || row.status === "done") && (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px]">
                    {row.status === "error" && <span className="text-[#a33]">{row.error}</span>}
                    {row.status === "error" && (
                      <button
                        type="button"
                        className="font-semibold text-brand hover:underline"
                        onClick={() => {
                          setMessage("");
                          setRow(row.key, { status: "queued", progress: 0, error: "" });
                        }}
                      >
                        重试
                      </button>
                    )}
                    <button
                      type="button"
                      className="text-muted hover:underline"
                      onClick={() => removeRow(row.key)}
                    >
                      移除
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] font-bold text-[#5a6a86]">
            已上传材料（{materials.length}）· 参考资料 {counts.reference ?? 0} 份 / 例题来源{" "}
            {counts.example_source ?? 0} 份
          </div>
          {materials.length > 0 && <Badge tone="active">已注入生成 prompt</Badge>}
        </div>
        {materials.length === 0 ? (
          <Empty>还没有上传材料。课程讲义、教材章节、往年例题都可以放进来。</Empty>
        ) : (
          <ul className="grid gap-1.5">
            {materials.map((material) => {
              const extract = EXTRACT_LABEL[material.extract_status] ?? EXTRACT_LABEL.pending;
              return (
                <li key={material.id} className="rounded-xl border border-line bg-white px-3 py-2 text-[11px]">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={material.kind === "example_source" ? "warn" : "active"}>
                      {material.kind === "example_source" ? "例题来源" : "参考资料"}
                    </Badge>
                    <span className="truncate font-semibold text-[#33415c]" title={material.filename}>
                      {material.filename}
                    </span>
                    <span className="text-[10px] text-muted">{formatSize(material.size)}</span>
                    <Badge tone={extract.tone}>{extract.label}</Badge>
                    <button
                      type="button"
                      onClick={() => void removeMaterial(material)}
                      disabled={deleting === material.id}
                      className="ml-auto text-[10px] font-semibold text-muted hover:text-[#c33] disabled:opacity-40"
                    >
                      {deleting === material.id ? "删除中…" : "删除"}
                    </button>
                  </div>
                  {material.excerpt_preview && (
                    <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-muted">
                      摘录：{material.excerpt_preview}
                    </div>
                  )}
                  {material.note && <div className="mt-0.5 text-[10px] text-muted">备注：{material.note}</div>}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <p className="text-[10px] leading-relaxed text-[#99a2b3]">{hint}</p>
    </div>
  );
}
