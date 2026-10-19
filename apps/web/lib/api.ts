// 默认使用同源 /api（由 Next 服务端反向代理到 FastAPI，见 next.config.ts rewrites）。
// 需要直连其他后端时可设置 NEXT_PUBLIC_API_BASE（如 http://127.0.0.1:8000）。
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    let code = "error";
    let message = `请求失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail?.message) {
        code = body.detail.code ?? code;
        message = body.detail.message;
      } else if (body?.message) {
        code = body.code ?? code;
        message = body.message;
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export const API_BASE = BASE;

/** 下载文件（如教程 Markdown 导出）：同源请求，返回 Blob 后触发浏览器下载。 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let message = `导出失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail?.message) message = body.detail.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, "download_failed", message);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fallbackName;
  a.click();
  URL.revokeObjectURL(url);
}
