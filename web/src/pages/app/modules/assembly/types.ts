export type V3 = [number, number, number];

export interface AsmSummary {
  id: string; name: string; project_id: string | null; updated_at: string; instances: number; mates: number;
  fasteners: number; status: SolveStatus | null; thumbnail: string | null; dof: number | null; free_spins: number | null;
  own_thumbnail: boolean;
}

export type SolveStatus = "fully_defined" | "under_defined" | "over_defined";

export interface InstDof { dof: number; rot: number; trans: number; spin: boolean; fixed: boolean; over: boolean }

export interface Instance {
  id: string; name: string; display: string; part: string; T: number[]; fixed: boolean; visible: boolean;
  group: string | null; stale: boolean; source_missing: boolean; dof: InstDof | null;
  source: { kind: "project"; project_id: string; build_id: string; rev: string | null }
    | { kind: "toolbox"; code: string; params: Record<string, number>; version: number };
}

export interface Hole { id: number; d: number; axis: V3; center: V3; depth: number; through: boolean; faces: number[] }
export interface HolePattern { kind: string; d: number; count: number; holes: number[] }

export interface PartView {
  key: string; name: string; kind: "project" | "toolbox"; material: string | null; standard: string | null;
  code: string | null; params: Record<string, number> | null; bbox: number[]; center: V3; volume: number;
  holes: Hole[]; patterns: HolePattern[]; topo_url: string;
}

export type MateType = "coincident" | "flush" | "distance" | "angle" | "concentric";
export type MateStatus = "ok" | "conflict" | "suppressed" | "broken" | "unsatisfied";
export interface Sel { inst: string; kind: "face" | "edge"; id: number }

export interface Mate {
  id: string; type: MateType; label: string; value: number | null; flip: boolean; suppressed: boolean;
  group: string | null; a: Sel; b: Sel; a_name: string; b_name: string; status: MateStatus;
  residual_mm: number | null; residual_deg: number | null;
}

export interface Group {
  id: string; kind: "fastener"; name: string; pattern: string | null; hole: { inst: string; hole: number };
  spec: { summary: string; designation: string; size: number; kind: string; grip: number; rule: string;
    length: LengthCalc; warnings: string[]; sources: string[]; clearance: { text: string } };
}

export interface Solve {
  status: SolveStatus; dof: number; redundant: number; conflicts: string[]; free_spins: number;
  suppressed: number; broken: number; no_fixed: boolean;
}

export interface InterferencePair {
  a: string; b: string; a_name: string; b_name: string; volume_mm3: number; kind: "interference" | "thread";
  center: V3; bbox: number[]; mesh: { pos: number[]; idx: number[] } | null;
}
export interface ClearanceRow {
  a: string; b: string; a_name: string; b_name: string; distance_mm: number; pa: V3; pb: V3; why: string[];
  status: "interference" | "thread" | "contact" | "clear"; mates: string[];
}
export interface Analysis {
  signature: string; at: string; stale: boolean; note: string;
  interference: { pairs: InterferencePair[]; checked_pairs: number; count: number; total_mm3: number };
  clearance: { rows: ClearanceRow[]; near_mm: number; min_clear_mm: number | null };
}

export interface BomRow {
  item: number; qty: number; part: string; kind: "project" | "toolbox"; description: string; standard: string | null;
  designation: string | null; material: string | null; mass_each_g: number | null; mass_total_g: number | null;
  instances: string[];
}
export interface Bom { rows: BomRow[]; total_qty: number; total_mass_g: number; mass_unknown_qty: number; note: string }

export interface ExportInfo {
  ok: boolean; instances: number; reimported: number; groups: number; placement_dev_mm: number; bytes: number;
  at: string; stale: boolean; url: string;
}

export interface AsmView {
  assembly: { id: string; name: string; project_id: string | null; rev: number; created_at: string; updated_at: string };
  home_project: { id: string; name: string } | null;
  instances: Instance[]; parts: Record<string, PartView>; mates: Mate[]; groups: Group[]; solve: Solve | null;
  explode: Record<string, V3>; analysis: Analysis | null; export: ExportInfo | null; bom: Bom; can_edit: boolean; thumb_rev: number | null;
  result?: Record<string, unknown>;
}

export interface SourceProject { id: string; name: string; thumbnail: string | null; material: string | null; verified: boolean }
export interface ToolboxParam {
  name: string; label: string; default: number; unit: string; min: number | null; max: number | null;
  options: number[] | null; help: string; integer: boolean;
}
export interface ToolboxComp { code: string; name: string; category: string; standard: string; material: string; params: ToolboxParam[] }
export interface Sources { projects: SourceProject[]; toolbox: ToolboxComp[] }

export interface LengthCalc {
  L: number | null; L_min: number; L_max?: number; terms: { label: string; mm: number }[]; rule: string;
  protrusion?: number; protrusion_threads?: number; engagement?: number; protrudes?: number; usable_thread?: number;
}
export interface Proposal {
  ok: boolean; verify: boolean; error?: string; warnings: string[]; sources: string[]; kind: "through" | "tapped" | "blocked";
  grip: number; members: { inst: string; name: string; t: number }[]; size?: number; designation?: string; pitch?: number;
  clearance?: { class: string | null; nominal: number | null; text: string }; length?: LengthCalc; rule?: string;
  items?: { role: string; code: string; params: Record<string, number>; title: string; standard: string; material: string }[];
  summary?: string;
}
export interface Probe {
  kind: "through" | "tapped" | "blocked"; hole_d: number; grip: number; reason?: string;
  members: { inst: string; name: string; t: number }[];
  tapped: { name: string; d: number; depth: number; blind: boolean } | null;
}
export interface FitPlan {
  holes: { inst: string; inst_name: string; hole: number; probe: Probe; proposal: Proposal }[];
  ok: number; failed: number; stacks: { summary: string; count: number }[];
  style: "hex_bolt" | "shcs"; washers: "both" | "head" | "none"; flip: boolean;
}
