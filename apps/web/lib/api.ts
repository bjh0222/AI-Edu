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

async function errorFrom(status: number, bodyText: string): Promise<ApiError> {
  let code = "error";
  let message = `请求失败（${status}）`;
  try {
    const body = JSON.parse(bodyText);
    if (body?.detail?.message) {
      code = body.detail.code ?? code;
      message = body.detail.message;
    } else if (typeof body?.detail === "string") {
      message = body.detail;
    } else if (Array.isArray(body?.detail)) {
      message = body.detail.map((item: { loc?: string[]; msg?: string }) => `${item.loc?.slice(1).join(".")}: ${item.msg}`).join("；");
    } else if (body?.message) {
      code = body.code ?? code;
      message = body.message;
    }
  } catch {
    /* ignore */
  }
  return new ApiError(status, code, message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    throw await errorFrom(res.status, await res.text());
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/**
 * 上传文件（multipart）。用 XHR 而不是 fetch：fetch 没有上传进度事件，
 * 而材料上传需要展示逐文件的百分比进度。Content-Type 交给浏览器设置（含 boundary）。
 */
export function uploadFile<T>(
  path: string,
  form: FormData,
  onProgress?: (percent: number) => void
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}${path}`);
    xhr.responseType = "text";
    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T);
        } catch {
          reject(new ApiError(xhr.status, "bad_response", "上传响应无法解析"));
        }
        return;
      }
      void errorFrom(xhr.status, xhr.responseText).then(reject);
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "上传失败：网络错误或服务未启动"));
    xhr.ontimeout = () => reject(new ApiError(0, "timeout", "上传超时，请重试"));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "上传已取消"));
    xhr.send(form);
  });
}

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
