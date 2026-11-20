/** The instant layout preview served by GET/POST /api/office/programs/{pid}/preview (``graph/preview.py``). */
import type { V3 } from "@/viewer/types";

export type BuildPath = "spec" | "toolbox" | "template" | "ai";

export type BodyGeom =
  | { kind: "box"; g: { s: [number, number, number]; open?: boolean } }
  | { kind: "key"; g: { s: [number, number, number] } }
  | { kind: "cyl"; g: { d: number; L: number; bore?: number } }
  | { kind: "shaft"; g: { segs: [number, number, number][] } }
  | { kind: "gear"; g: { tip: number; pitch: number; width: number; bore: number; m: number; z: number } }
  | { kind: "bearing"; g: { d: number; D: number; B: number } }
  | { kind: "ring"; g: { d: number; D: number; s: number } }
  | { kind: "screw"; g: { d: number; L: number; head_d: number; head_h: number } };

export type PreviewBody = BodyGeom & {
  id: string; item: string; copy: number; name: string;
  /** part frame -> program frame, rows of a 3x4 matrix (rotation | translation), mm */
  T: number[];
  path: BuildPath; flag?: "error" | null; standard?: boolean; joint?: string;
};

export interface DimSource { what: string; value: unknown; source: string; word: string; note: string }
export type PreviewDim = {
  id: string; text: string; label: string; items: string[]; prio: 1 | 2; sources: DimSource[]; value?: number; envelope?: boolean;
} & ({ kind: "linear"; a: V3; b: V3 } | { kind: "diameter"; c: V3; axis: V3; r: number } | { kind: "label"; at: V3 });

export interface PreviewIssue { code: string; severity: "error" | "warning"; text: string; items: string[]; bodies: string[]; acknowledged: boolean }
export interface PreviewRow { name: string; path: BuildPath; why: string; qty: number; standard: boolean; placed?: number; at?: [number, number] }

export interface PreviewData {
  version: number; units: "mm"; state: "plan" | "edited" | "icd"; solver: string | null; layout: string | null; master: boolean;
  bodies: PreviewBody[]; dims: PreviewDim[]; issues: PreviewIssue[]; rows: Record<string, PreviewRow>; unplaced: string[];
  envelope: { min: V3; max: V3 } | null; notes: string[];
  counts: { bodies: number; screws: number; dims: number; errors: number; warnings: number };
  paths: Record<BuildPath, number>;
  ms: { scene: number; layout?: number; paths?: number; total?: number };
  icd_version?: number | null; icd_status?: string | null;
}

export interface PreviewCompare { title: string; before: PreviewData; after: PreviewData }
