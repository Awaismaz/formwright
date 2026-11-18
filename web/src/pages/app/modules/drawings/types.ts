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
  /** DRW-011: circles on a view (view coordinates, mm) redrawn larger */
  details?: DetailReq[];
  /** DRW-013: datum symbols and feature control frames, only as entered */
  gdt?: { datums: DatumIn[]; frames: FrameIn[] };
}

export interface DetailReq { view: string; u: number; v: number; r: number; scale: string | null }
export type GdtTarget = { kind: "dim" | "callout"; id: string } | { kind: "point"; view: string; u: number; v: number };
export interface DatumIn { letter: string; target: GdtTarget }
export interface FrameIn { char: string; tol: number; dia?: boolean; mod?: "M" | "L" | null; datums: string[]; target: GdtTarget; id?: string }
export interface GdtRecord {
  datums: { letter: string; source: "user" | "icd"; ref?: string | null; label?: string | null; view: string }[];
  frames: (FrameIn & { id: string; source: "user" | "icd"; ref?: string | null; label?: string | null; view: string; text: string })[];
  unresolved: { type: string; letter?: string; char?: string; label?: string | null; ref?: string | null }[];
  missing: { type: string; ref: string | null }[];
  icd_version?: number | null; icd_interfaces: string[];
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
  /** sheet metal (CAD-026): the flat-pattern sheet (outline, bend lines, bend table), null for other parts */
  flat_pattern?: { scale: string; size: [number, number]; bends: number; thickness: number; k_factor: number; files: string[];
    table: { n: number; name: string; direction: "UP" | "DOWN"; angle: number; radius: number; k: number; ba: number; span: number }[] } | null;
  sheet: { size: string; w: number; h: number; scale: string; iso_scale: number; projection: string; iso_dropped?: boolean;
    views?: Record<string, { rect: number[]; scale: number; origin: number[] }> };
  details?: { drawn: { letter: string; parent: string; scale: string; u: number; v: number; r: number }[]; skipped: string[] };
  gdt?: GdtRecord;
  threads?: { designation: string; internal: boolean; depth: number | null; feature: string | null; dia: number }[];
  threads_unmatched?: number;
  imported?: { inferred_only: boolean; component: string | null; unrecognised_faces: number } | null;
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
