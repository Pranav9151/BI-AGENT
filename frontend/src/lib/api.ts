/**
 * Smart BI Agent — API Client
 *
 * Thin fetch wrapper with:
 *   - Automatic Bearer token injection from auth store
 *   - 401 interception → attempt token refresh → retry once
 *   - Typed error extraction from the standard error envelope
 *   - No external HTTP library dependency (fetch is sufficient)
 */

import type { ApiError } from "@/types/auth";

const API_BASE = "/api/v1";

// ─── Error Class ─────────────────────────────────────────────────────────────

export class ApiRequestError extends Error {
  code: string;
  status: number;
  requestId?: string;
  fields?: Array<{ field: string; issue: string }>;

  constructor(status: number, body: ApiError["error"]) {
    super(body.message);
    this.name = "ApiRequestError";
    this.code = body.code;
    this.status = status;
    this.requestId = body.request_id;
    this.fields = body.fields;
  }
}

// ─── Token Access (late-bound to avoid circular imports) ─────────────────────

let _getToken: (() => string | null) | null = null;
let _getPreTotpToken: (() => string | null) | null = null;
let _refreshFn: (() => Promise<boolean>) | null = null;
let _logoutFn: (() => void) | null = null;

/**
 * Called once from auth store initialization to wire up token access.
 * This avoids circular dependency between api.ts and auth-store.ts.
 */
export function bindAuthFunctions(fns: {
  getToken: () => string | null;
  getPreTotpToken: () => string | null;
  refresh: () => Promise<boolean>;
  logout: () => void;
}) {
  _getToken = fns.getToken;
  _getPreTotpToken = fns.getPreTotpToken;
  _refreshFn = fns.refresh;
  _logoutFn = fns.logout;
}

// ─── Core Request ────────────────────────────────────────────────────────────

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Use pre_totp token instead of access token (for TOTP endpoints) */
  usePreTotp?: boolean;
  /** Skip automatic 401 retry (used during refresh itself) */
  skipRetry?: boolean;
}

async function parseErrorBody(res: Response): Promise<ApiError["error"]> {
  try {
    const json = await res.json();
    if (json?.error?.code && json?.error?.message) {
      return json.error;
    }
  } catch {
    // Response body wasn't valid JSON
  }
  return {
    code: "UNKNOWN_ERROR",
    message: `Request failed with status ${res.status}`,
  };
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, usePreTotp = false, skipRetry = false } = opts;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };

  // Inject the right token
  const token = usePreTotp
    ? _getPreTotpToken?.() ?? null
    : _getToken?.() ?? null;

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include", // Always send cookies (refresh_token)
  });

  // ── 401 interception: try refresh once ──────────────────────────────────
  if (res.status === 401 && !skipRetry && !usePreTotp && _refreshFn) {
    const refreshed = await _refreshFn();
    if (refreshed) {
      // Retry the original request with the new token
      return request<T>(path, { ...opts, skipRetry: true });
    }
    // Refresh failed → force logout
    _logoutFn?.();
    const errBody = await parseErrorBody(res);
    throw new ApiRequestError(res.status, errBody);
  }

  // ── Error responses ─────────────────────────────────────────────────────
  if (!res.ok) {
    const errBody = await parseErrorBody(res);
    throw new ApiRequestError(res.status, errBody);
  }

  // ── 200/204 with no content ─────────────────────────────────────────────
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ─── Binary Download ────────────────────────────────────────────────────────

interface DownloadResult {
  blob: Blob;
  filename: string;
}

async function downloadBlob(
  path: string,
  body?: unknown,
  skipRetry = false,
): Promise<DownloadResult> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "*/*",
  };

  const token = _getToken?.() ?? null;
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
  });

  // 401 interception — same retry logic as request()
  if (res.status === 401 && !skipRetry && _refreshFn) {
    const refreshed = await _refreshFn();
    if (refreshed) {
      return downloadBlob(path, body, true);
    }
    _logoutFn?.();
    const errBody = await parseErrorBody(res);
    throw new ApiRequestError(res.status, errBody);
  }

  if (!res.ok) {
    const errBody = await parseErrorBody(res);
    throw new ApiRequestError(res.status, errBody);
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^";\n]+)"?/);
  const filename = match?.[1] ?? "export";

  return { blob, filename };
}

/**
 * Trigger a browser file download from a Blob.
 * Creates a temporary <a> element, clicks it, and cleans up.
 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── Convenience Methods ─────────────────────────────────────────────────────

export const api = {
  get: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "GET" }),

  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "POST", body }),

  patch: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "PATCH", body }),

  put: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "PUT", body }),

  delete: <T>(path: string, opts?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...opts, method: "DELETE" }),

  /** POST a JSON body, receive a binary blob response (for file exports). */
  downloadBlob: (path: string, body?: unknown) => downloadBlob(path, body),
};