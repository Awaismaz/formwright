export type V3 = [number, number, number];

export interface AsmSummary {
  id: string; name: string; project_id: string | null; updated_at: string; instances: number; mates: number;
  fasteners: number; status: SolveStatus | null; thumbnail: string | null; dof: number | null; free_spins: number | null;
  own_thumbnail: boolean; broken_mates?: number; stale_parts?: number; stacks_to_check?: number;
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
  a_desc?: string; b_desc?: string; a_lost?: boolean; b_lost?: boolean;
  residual_mm: number | null; residual_deg: number | null;
}

export interface Group {
  id: string; kind: "fastener"; name: string; pattern: string | null; hole: { inst: string; hole: number };
  spec: { summary: string; designation: string; size: number; kind: string; grip: number; rule: string;
    length: LengthCalc; warnings: string[]; sources: string[]; clearance: { text: string } };
  check?: { text: string; summary: string | null };
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
  summary?: string; no_room?: boolean;
}
export interface Probe {
  kind: "through" | "tapped" | "blocked"; hole_d: number; grip: number; reason?: string;
  members: { inst: string; name: string; t: number }[];
  tapped: { name: string; d: number; depth: number; blind: boolean } | null;
  mismatch?: { inst: string; name: string; hole: number; d: number; size: number } | null;
}
export interface FitPlan {
  holes: { inst: string; inst_name: string; hole: number; probe: Probe; proposal: Proposal }[];
  ok: number; failed: number; stacks: { summary: string; count: number }[];
  style: "hex_bolt" | "shcs"; washers: "both" | "head" | "none"; flip: boolean;
}

export interface HoleFix { project_id: string; project: string; param: string; label: string; from: number; to: number; radius: boolean }
export interface HolePair {
  a_hole: number; b_hole: number; a_d: number; b_d: number; target: { inst: string; hole: number }; grip: number | null;
  mismatch: { inst: string; hole: number; d: number; to_d: number; size: number | null; name?: string; fix: HoleFix | null } | null;
  proposal: Proposal; point: V3;
}
export interface PairPlan { a: string; b: string; a_name: string; b_name: string; pairs: HolePair[]; ok: number }
export interface Clash { a: string; b: string; a_name: string; b_name: string; volume_mm3: number }
export interface RefreshResult {
  refreshed: number; references_kept: number; references_followed: number; references_lost: number;
  broken_mates: string[]; stacks_to_check: number;
}

/** Smart assembly (ASM-010 / ASM-019): one line of Hex's reading, with Fitz's intended placement. */
export type SmartAction = "base" | "mount" | "seat" | "dowel" | "fasten" | "place" | "design";
export interface SmartItem {
  id: string; text: string; qty: number; qty_explicit: boolean; enabled: boolean; order: number;
  source: "toolbox" | "project" | "new"; kind?: string; action: SmartAction; title: string;
  code?: string; params?: Record<string, number> | null; read?: string[]; standard?: string;
  fasten?: { style: "hex_bolt" | "shcs"; washers: "both" | "head" | "none"; size: number | null; length: number | null };
  project_id?: string; inst?: string; auto?: boolean; ai?: boolean;
  target?: { inst?: string; item?: string } | null; target_name?: string | null;
  confidence: "high" | "medium" | "low"; found: string; plan: string; reasons?: string[];
  alternatives?: { id: string; name: string; score: number }[];
}
export interface SmartPlan {
  items: SmartItem[]; unresolved: string[]; tokens: number; ai_used: boolean; ai_lines?: number; ai_read?: number;
  parts_in_assembly: { id: string; name: string }[];
}
export interface SmartLog { agent: "Hex" | "Fitz"; text: string; tone: "ok" | "warn" | "muted" }
export interface SmartResult {
  log: SmartLog[]; summary: string; clashes: Clash[]; inserted: number; mated: number; placed_loose: number;
  fastener_stacks: number; fastener_asked: number;
}
