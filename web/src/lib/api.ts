export class ApiError extends Error {
  status: number;
  cta?: string;
  constructor(status: number, message: string, cta?: string) {
    super(message);
    this.status = status;
    this.cta = cta;
  }
}

let currentOrg: string | null = (() => {
  try { return localStorage.getItem("fw_org"); } catch { return null; }
})();

export function setCurrentOrg(id: string | null) {
  currentOrg = id;
  try { id ? localStorage.setItem("fw_org", id) : localStorage.removeItem("fw_org"); } catch { /* storage unavailable */ }
}

/** Workspace + CSRF headers for requests made outside `api` (raw uploads, blob downloads). */
export function apiHeaders(method: string): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-FW-CSRF"] = "1";
  if (currentOrg) headers["X-Org"] = currentOrg;
  return headers;
}

/** The API's error message from a failed response body (FastAPI `detail`, plain or {message}). */
export function errorFrom(status: number, data: unknown): ApiError {
  const d = (data as { detail?: unknown } | null)?.detail;
  if (d && typeof d === "object" && "message" in (d as object)) {
    const o = d as { message: string; cta?: string };
    return new ApiError(status, o.message, o.cta);
  }
  if (Array.isArray(d)) return new ApiError(status, "Please check the form fields.");
  return new ApiError(status, typeof d === "string" ? d : `Request failed (${status})`);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers = apiHeaders(method);
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw errorFrom(res.status, data);
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b: unknown = {}) => request<T>("POST", p, b),
  patch: <T,>(p: string, b: unknown) => request<T>("PATCH", p, b),
  del: <T,>(p: string) => request<T>("DELETE", p),
};

export function track(event: string, meta: Record<string, unknown> = {}) {
  api.post("/api/events", { event, meta }).catch(() => {});
}
