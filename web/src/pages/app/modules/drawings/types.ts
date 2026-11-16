export type Tag = "spec" | "inferred";

/** `views` null: chosen from the part type. `section` "auto": chosen from the part type, null: off. */
export interface DrawingOptions {
  sheet: "A3" | "A4";
  projection: "first" | "third";
  views: string[] | null;
  section: "auto" | "x" | "y" | "z" | "axial" | "cross" | null;
  hidden: boolean;
  tolerance: { mode: "none" | "iso2768" | "custom"; class: "f" | "m" | "c" | "v" | null; text: string | null };
}

/** The user's edits, keyed by dimension / callout id and re-applied on every regeneration. */
export interface DrawingEdits {
  dims: Record<string, { hidden?: boolean; tol?: string }>;
  title: Partial<Record<"title" | "drawing_no" | "company" | "checked_by", string>>;
  notes: string[];
}

export interface CheckResult {
  id: string; name: string; passed: boolean; gating: boolean; problems: string[];
  detail: {
    tags: { dimensions: number; callout_lines: number; untagged: string[] };
    spec_once: { spec_on_sheet: Record<string, number>; missing: string[]; duplicates: string[]; not_placed: string[]; unmapped_params: string[]; hidden_by_user?: string[] };
    extents: Record<string, { got: number[]; expected: number[]; max_err_mm: number; passed: boolean }>;
    overlap: { texts: number; text_overlaps: string[][]; text_over_geometry: string[][]; outside_frame: string[] };
    placement?: { checked: number; misplaced: { text: string; why: string }[] };
    holes: { census: Record<string, number>; called_out: Record<string, number>; mismatch: Record<string, unknown> };
  };
}

export interface DimRow { id: string; text: string; tag: Tag; param: string | null; kind: string; view: string; aux: boolean; value: number; tol?: string | null; hidden?: boolean }
export interface CalloutRow { id: string; type?: "hole" | "radius" | "chamfer"; view: string; qty: number; dia: number | null; thru: boolean | null; tol?: string | null; hidden?: boolean; lines: { text: string; tag: Tag; param: string | null; params?: string[] }[] }

export interface DrawingRecord {
  version: string; build_id: string; model_rev: string | null; sheet_rev?: string; issued?: boolean;
  options: DrawingOptions; edits?: DrawingEdits;
  sheet: { size: string; w: number; h: number; scale: string; iso_scale: number; projection: string; iso_dropped?: boolean };
  plan?: { turned: boolean; hollow: boolean; views: string[]; section: string | null; front_section: boolean; note: string | null };
  title: { title: string; drawing_no: string; material: string; drawn_by: string; date: string; rev: string; tolerance: string; company?: string; checked_by?: string };
  check: CheckResult;
  dimensions: DimRow[];
  callouts: CalloutRow[];
  mapping: { mapped: Record<string, number>; unmapped: string[] };
  param_labels?: Record<string, string>;
  revisions?: { rev: string; date: string; change: string; by: string }[];
  census: { bbox: number[]; holes: number; unsupported_holes: number };
  history: { rev: string; date: string; by: string; change: string; build_id: string }[];
  files: Record<string, number>;
  timings: { geometry_s: number; layout_s: number; total_s: number };
}

export interface DrawingProject {
  id: string; name: string; thumbnail: string | null; updated_at: string; verified: boolean;
  part: string | null; material: string | null;
  drawing: { model_rev: string | null; sheet_rev?: string | null; scale: string; sheet: string; chk12: boolean; stale: boolean } | null;
}

export interface DrawingState {
  project: DrawingProject; drawing: DrawingRecord | null; can_edit: boolean; stale: boolean;
  current_rev: string | null; made_from_rev?: string | null; elapsed_s?: number;
  edits?: DrawingEdits;
  release?: { rev: string; date: string; by: string; current: boolean } | null;
}

export const DEFAULT_OPTIONS: DrawingOptions = {
  sheet: "A3", projection: "first", views: null, section: "auto", hidden: true,
  tolerance: { mode: "none", class: null, text: null },
};

export const EMPTY_EDITS: DrawingEdits = { dims: {}, title: {}, notes: [] };

/** The user's own calendar date and zone, so the title block carries their day (not the server's UTC day). */
export function localStamp(): { local_date: string; tz: string | undefined } {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  let tz: string | undefined;
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { tz = undefined; }
  return { local_date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`, tz };
}
