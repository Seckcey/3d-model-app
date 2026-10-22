/** Same-origin JSON client with Django CSRF handling and readable errors. */

export const CSRF_COOKIE = "bpcad_csrftoken";

export class ApiError extends Error {
  status: number;
  data: unknown;
  code?: string;

  constructor(status: number, message: string, data: unknown, code?: string) {
    super(message);
    this.status = status;
    this.data = data;
    this.code = code;
  }
}

export function getCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

let csrfRequest: Promise<void> | null = null;

export function ensureCsrf(): Promise<void> {
  if (getCookie(CSRF_COOKIE)) return Promise.resolve();
  if (!csrfRequest) {
    csrfRequest = fetch("/api/v1/csrf/", { credentials: "same-origin" })
      .then(() => undefined)
      .finally(() => {
        csrfRequest = null;
      });
  }
  return csrfRequest;
}

function firstMessage(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      const message = firstMessage(item);
      if (message) return message;
    }
  }
  return null;
}

/** Turn DRF and allauth error payloads into one sentence for the user. */
export function messageFrom(data: unknown, status: number): { message: string; code?: string } {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (Array.isArray(record.errors) && record.errors.length) {
      const first = record.errors[0] as { message?: string; code?: string };
      return { message: first.message ?? "Request failed.", code: first.code };
    }
    if (typeof record.detail === "string") {
      return { message: record.detail, code: typeof record.code === "string" ? record.code : undefined };
    }
    const code = firstMessage(record.code) ?? undefined;
    for (const [field, value] of Object.entries(record)) {
      if (field === "code") continue;
      const message = firstMessage(value);
      if (message) {
        const label = field === "non_field_errors" || field === "file" ? "" : `${field.replace(/_/g, " ")}: `;
        return { message: `${label}${message}`, code };
      }
    }
  }
  if (status === 403) return { message: "You do not have access to this." };
  if (status === 404) return { message: "Not found." };
  if (status === 429) return { message: "Too many requests. Wait a moment and try again." };
  if (status >= 500) return { message: "The server had a problem. Try again shortly." };
  return { message: `Request failed (${status}).` };
}

export interface RequestOptions {
  idempotencyKey?: string;
  okStatuses?: number[];
}

export async function request<T>(
  method: string,
  url: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<{ status: number; data: T }> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET" && method !== "HEAD") {
    await ensureCsrf();
    headers["X-CSRFToken"] = getCookie(CSRF_COOKIE) ?? "";
  }
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  const response = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok && !options.okStatuses?.includes(response.status)) {
    const { message, code } = messageFrom(data, response.status);
    throw new ApiError(response.status, message, data, code);
  }
  return { status: response.status, data: data as T };
}

export const api = {
  get: async <T>(url: string) => (await request<T>("GET", url)).data,
  post: async <T>(url: string, body?: unknown, options?: RequestOptions) =>
    (await request<T>("POST", url, body ?? {}, options)).data,
  patch: async <T>(url: string, body: unknown) => (await request<T>("PATCH", url, body)).data,
  del: async <T>(url: string) => (await request<T>("DELETE", url)).data,
};

/** Upload with progress (fetch cannot report upload progress). */
export function upload<T>(url: string, file: File, onProgress?: (fraction: number) => void): Promise<T> {
  return ensureCsrf().then(
    () =>
      new Promise<T>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", url);
        xhr.withCredentials = true;
        xhr.setRequestHeader("X-CSRFToken", getCookie(CSRF_COOKIE) ?? "");
        xhr.setRequestHeader("Accept", "application/json");
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
        };
        xhr.onload = () => {
          let data: unknown = null;
          try {
            data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
          } catch {
            data = xhr.responseText;
          }
          if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
          else {
            const { message, code } = messageFrom(data, xhr.status);
            reject(new ApiError(xhr.status, message, data, code));
          }
        };
        xhr.onerror = () => reject(new ApiError(0, "Network error during upload.", null));
        const form = new FormData();
        form.append("file", file);
        xhr.send(form);
      }),
  );
}

export function newIdempotencyKey(prefix: string): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${random}`;
}
