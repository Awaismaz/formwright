export type Tag = "spec" | "inferred";

export interface DrawingOptions {
  sheet: "A3" | "A4";
  projection: "first" | "third";
  views: string[];
  section: "x" | "y" | "z" | null;
  hidden: boolean;
  tolerance: { mode: "none" | "iso2768" | "custom"; class: "f" | "m" | "c" | "v" | null; text: string | null };
}

export interface CheckResult {
  id: string; name: string; passed: boolean; gating: boolean; problems: string[];
  detail: {
    tags: { dimensions: number; callout_lines: number; untagged: string[] };
    spec_once: { spec_on_sheet: Record<string, number>; missing: string[]; duplicates: string[]; not_placed: string[]; unmapped_params: string[] };
    extents: Record<string, { got: number[]; expected: number[]; max_err_mm: number; passed: boolean }>;
    overlap: { texts: number; text_overlaps: string[][]; text_over_geometry: string[][]; outside_frame: string[] };
    holes: { census: Record<string, number>; called_out: Record<string, number>; mismatch: Record<string, unknown> };
  };
}

export interface DrawingRecord {
  version: string; build_id: string; model_rev: string | null; options: DrawingOptions;
  sheet: { size: string; w: number; h: number; scale: string; iso_scale: number; projection: string };
  title: { title: string; drawing_no: string; material: string; drawn_by: string; date: string; rev: string; tolerance: string };
  check: CheckResult;
  dimensions: { id: string; text: string; tag: Tag; param: string | null; kind: string; view: string; aux: boolean; value: number }[];
  callouts: { id: string; view: string; qty: number; dia: number; thru: boolean; lines: { text: string; tag: Tag; param: string | null }[] }[];
  mapping: { mapped: Record<string, number>; unmapped: string[] };
  census: { bbox: number[]; holes: number; unsupported_holes: number };
  history: { rev: string; date: string; by: string; change: string; build_id: string }[];
  files: Record<string, number>;
  timings: { geometry_s: number; layout_s: number; total_s: number };
}

export interface DrawingProject {
  id: string; name: string; thumbnail: string | null; updated_at: string; verified: boolean;
  part: string | null; material: string | null;
  drawing: { model_rev: string | null; scale: string; sheet: string; chk12: boolean; stale: boolean } | null;
}

export interface DrawingState {
  project: DrawingProject; drawing: DrawingRecord | null; can_edit: boolean; stale: boolean;
  current_rev: string | null; elapsed_s?: number;
}

export const DEFAULT_OPTIONS: DrawingOptions = {
  sheet: "A3", projection: "first", views: ["front", "top", "right", "iso"], section: null, hidden: true,
  tolerance: { mode: "none", class: null, text: null },
};
