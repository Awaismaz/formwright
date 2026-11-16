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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-FW-CSRF"] = "1";
  if (currentOrg) headers["X-Org"] = currentOrg;
  const res = await fetch(path, { method, headers, credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const d = (data as { detail?: unknown } | null)?.detail;
    if (d && typeof d === "object" && "message" in (d as object)) {
      const o = d as { message: string; cta?: string };
      throw new ApiError(res.status, o.message, o.cta);
    }
    if (Array.isArray(d)) throw new ApiError(res.status, "Please check the form fields.");
    throw new ApiError(res.status, typeof d === "string" ? d : `Request failed (${res.status})`);
  }
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
