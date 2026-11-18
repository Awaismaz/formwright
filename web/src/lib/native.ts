/** Formwright native files (.fwpart / .fwasm / .fwdrw / .fwprog, projects archive): client helpers.
 *  Uploads go as raw bytes (no base64), downloads as blobs so the workspace header and error messages work. */
import { ApiError, apiHeaders, errorFrom } from "./api";

export type NativeFormat = "fwpart" | "fwasm" | "fwdrw" | "fwprog" | "zip";
export type NativeKind = "part" | "assembly" | "drawing" | "program" | "projects";
export type VerifyState = "identical" | "mismatch" | "fallback";

export const NATIVE_EXT = /\.(fwpart|fwasm|fwdrw|fwprog)$/i;
export const NATIVE_ACCEPT = ".fwpart,.fwasm,.fwdrw,.fwprog";
export const MAX_NATIVE_BYTES = 200 * 1024 * 1024;

export const FORMAT_LABEL: Record<NativeFormat, string> = {
  fwpart: "Formwright part", fwasm: "Formwright assembly", fwdrw: "Formwright drawing", fwprog: "Formwright program",
  zip: "Formwright projects archive",
};

export interface Verification {
  state: VerifyState; label: string; diffs: string[]; step_identical?: boolean; reason?: string | null;
  checks_ok?: boolean;
}
export interface NativeSummary {
  kind: NativeKind; title: string; description?: string; material?: string; parameters?: number; features?: number;
  revisions?: number; refs?: number; chat?: boolean; imported?: boolean; created_at?: string; app_version?: string;
  instances?: number; mates?: number; tickets?: number; sheet?: string; scale?: string; model?: boolean; part?: string;
  parts?: (string | { ref: string; kind: string; name: string })[]; assemblies?: string[];
}
export interface Inspection {
  kind: NativeKind; format: NativeFormat; filename: string; size: number; trust: "workspace" | "foreign";
  trust_note: string | null; needs_confirm: boolean; summary: NativeSummary; warnings: string[];
  format_version: number; migrated_from: number | null;
}
export interface PartResult { kind: "part"; action: "imported" | "linked"; project: { id: string; name: string }; verification: Verification }
export interface ImportResult {
  kind: NativeKind; trust: string; format: NativeFormat; warnings: string[];
  project?: { id: string; name: string }; verification?: Verification; action?: string;
  assembly?: { id: string; name: string }; program?: { id: string; name: string };
  parts?: PartResult[]; mates?: number; mates_dropped?: number; drawing_note?: string | null;
}

/** True for a file the native import handles: a Formwright extension, or a .zip that may be a projects archive. */
export function isNativeFile(name: string): boolean {
  return NATIVE_EXT.test(name) || /\.zip$/i.test(name);
}

export function formatOf(name: string): NativeFormat | null {
  const m = /\.(fwpart|fwasm|fwdrw|fwprog|zip)$/i.exec(name);
  return m ? (m[1]!.toLowerCase() as NativeFormat) : null;
}

/** Where to open the result of an import. */
export function resultLink(r: ImportResult): string {
  if (r.kind === "assembly" && r.assembly) return `/app/modules/assembly?assembly=${r.assembly.id}`;
  if (r.kind === "drawing" && r.project) return `/app/modules/drawings?project=${r.project.id}`;
  if (r.kind === "program" && r.program) return `/app/office/programs/${r.program.id}`;
  if (r.kind === "projects") return "/app/projects";
  return r.project ? `/app/projects/${r.project.id}` : "/app/projects";
}

/** The worst verification over a set of part results (an assembly is identical only if every part is). */
export function overallState(parts: { verification: Verification }[]): VerifyState {
  if (parts.some(p => p.verification.state === "fallback")) return "fallback";
  if (parts.some(p => p.verification.state === "mismatch")) return "mismatch";
  return "identical";
}

export const STATE_TONE: Record<VerifyState, "success" | "warning" | "danger"> = {
  identical: "success", mismatch: "warning", fallback: "warning",
};

/** One plain line describing what the file holds. */
export function describe(s: NativeSummary): string {
  const bits: string[] = [];
  if (s.kind === "part") {
    if (s.material) bits.push(s.material);
    if (s.parameters) bits.push(`${s.parameters} parameter${s.parameters === 1 ? "" : "s"}`);
    if (s.features) bits.push(`${s.features} feature${s.features === 1 ? "" : "s"}`);
    if (s.revisions) bits.push(`${s.revisions} revision${s.revisions === 1 ? "" : "s"}`);
    if (s.chat) bits.push("design conversation");
  } else if (s.kind === "assembly") {
    bits.push(`${s.instances ?? 0} instance${s.instances === 1 ? "" : "s"}`, `${s.mates ?? 0} mate${s.mates === 1 ? "" : "s"}`,
      `${s.parts?.length ?? 0} distinct part${s.parts?.length === 1 ? "" : "s"}`);
  } else if (s.kind === "drawing") {
    bits.push(s.model ? `drawing of ${s.part}` : "2D drawing");
    if (s.sheet) bits.push(`${s.sheet}${s.scale ? `, ${s.scale}` : ""}`);
  } else if (s.kind === "program") {
    bits.push(`${s.tickets ?? 0} ticket${s.tickets === 1 ? "" : "s"}`, `${s.parts?.length ?? 0} part${s.parts?.length === 1 ? "" : "s"}`,
      `${s.assemblies?.length ?? 0} assembl${s.assemblies?.length === 1 ? "y" : "ies"}`);
  } else bits.push(`${s.parts?.length ?? 0} part${s.parts?.length === 1 ? "" : "s"}`);
  return bits.join(" · ");
}

export function fileSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

async function upload<T>(path: string, file: File, params: Record<string, string> = {}): Promise<T> {
  if (file.size > MAX_NATIVE_BYTES) throw new ApiError(413, "Formwright files up to 200 MB can be imported.");
  const q = new URLSearchParams({ filename: file.name, ...params });
  const headers = { ...apiHeaders("POST"), "Content-Type": "application/octet-stream" };
  const res = await fetch(`${path}?${q}`, { method: "POST", headers, credentials: "same-origin", body: file });
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw errorFrom(res.status, data);
  return data as T;
}

export const inspectNative = (file: File) => upload<Inspection>("/api/native/inspect", file);
export const importNative = (file: File, confirm: boolean) =>
  upload<ImportResult>("/api/native/import", file, confirm ? { confirm: "1" } : {});

/** The filename from a Content-Disposition header. */
export function dispositionName(h: string | null, fallback: string): string {
  const m = h ? /filename="([^"]+)"/.exec(h) : null;
  return m?.[1] ?? fallback;
}

/** Download a native export through fetch (keeps the workspace header; shows the server's reason on failure). */
export async function downloadNative(url: string, fallbackName: string): Promise<string> {
  const res = await fetch(url, { headers: apiHeaders("GET"), credentials: "same-origin" });
  if (!res.ok) {
    let data: unknown = null;
    try { data = await res.json(); } catch { /* not JSON */ }
    throw errorFrom(res.status, data);
  }
  const name = dispositionName(res.headers.get("Content-Disposition"), fallbackName);
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
  return name;
}

/** Hand a native file to the import dialog (mounted once in the app shell). */
export const NATIVE_EVENT = "fw:native-import";
export function openNativeImport(file: File) {
  window.dispatchEvent(new CustomEvent<File>(NATIVE_EVENT, { detail: file }));
}
