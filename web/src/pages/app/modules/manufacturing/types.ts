export type Severity = "critical" | "warning" | "info";
export type ProcessKey = "cnc_milling" | "cnc_turning" | "sheet_metal" | "moulding_casting";
export type Tolerance = "general" | "fine" | "precision";

export interface Finding {
  id: string; rule: string; process: ProcessKey; severity: Severity; title: string; measured: string; limit: string;
  value: number | null; rationale: string; fix: string; source: string; faces: number[]; features: string[];
  advice_level: string;
  /** Plain description of where the finding is (feature name or geometry), never face ids. */
  where?: string | null;
  /** Other process views this finding belongs to (a milled keyway on a turned part). */
  also?: ProcessKey[];
  note?: string | null;
  action?: FixAction | null;
}
export type FixAction =
  | { kind: "param"; param: string; param_label?: string | null; from: number; to: number; unit: string; why?: string | null; label: string }
  | { kind: "studio"; label: string; prompt: string }
  | { kind: "note"; label: string; text: string };
export interface Delta {
  critical: { before: number; after: number }; warning: { before: number; after: number }; info: { before: number; after: number };
  cost: { before: number | null; after: number | null; pct: number | null; process: string | null }; text: string;
}
export interface FixResult {
  applied: { param: string; label: string; from: number; to: number; revision: number | null; finding: string };
  delta: Delta; analysis: Analysis;
}
export interface RuleRow { rule: string; name: string; process: ProcessKey; status: "pass" | "flagged" | "not applicable"; findings: number; worst?: Severity | null }
export interface Ranked {
  process: string; name: string; score: number; fit: string; feasible: boolean; confidence: "low" | "medium";
  analysed?: boolean; critical?: number;
  pros: string[]; cons: string[]; unit_cost: number | null;
}
export interface CostProc {
  unit_cost: number; batch_cost: number; breakdown: { material: number; machine_time: number; setup_tooling: number };
  curve: { q: number; unit: number }[]; run_minutes: number; fixed: number; material: number; notes: string[];
  setups?: number; removed_frac?: number;
}
export interface Driver {
  title: string; rationale: string; faces: number[]; features: string[]; rule: string | null;
  saving_per_unit: number | null; saving_pct: number | null; advice_level: string;
}
export interface MatInfo {
  code: string; name: string; group: string; density_g_cm3: number; machining_class: string; processes: string[];
  price_per_kg: number; metal: boolean; provenance: Record<string, string>; version: string;
}
export interface Analysis {
  analyser: string; tables: string; generated_at: string; cache_key: string; stale?: boolean;
  build: { fingerprint?: { volume: number; bbox: number[] }; build_id?: string | number; part?: string; model_rev?: string | null };
  freshness?: { state: "current" | "stale" | "missing"; made_from_rev: string | null; current_rev: string | null };
  /** Severity counts across every process shown by default (never filtered by the process chip). */
  summary?: Record<Severity, number>;
  screens?: Record<ProcessKey, { shown: boolean; reason: string | null }>;
  project: { id: string; name: string };
  inputs: { quantity: number; material: string | null; tolerance: Tolerance };
  material: MatInfo & { how: string; library_version: string; price_used: number };
  shop: { name: string; fingerprint: string; currency: string };
  part: { bbox: number[]; volume_mm3: number; area_mm2: number; mass_kg: number; faces: number; solids: number };
  signals: {
    setups: string[]; setup_faces: Record<string, number[]>; undercut_faces: number[];
    turning: { turnable: boolean; axis: string | null; revolved_pct: number; max_diameter: number; length: number };
    sheet: { sheet_like: boolean; thickness: number | null; pct: number };
    holes: { d: number; depth: number; ld: number; through: boolean; faces: number[] }[];
    pockets: { depth: number; width: number; direction: string; faces: number[] }[];
    min_wall_mm: number | null; pull_direction: string;
  };
  findings: Finding[];
  chk13: { id: string; name: string; gate: boolean; counts: Record<Severity, number>; rules: RuleRow[]; advice_level: string };
  process: { advice_level: string; ranking: Ranked[]; assumptions: string[] };
  cost: { label: string; advice_level: string; currency: string; quantity: number; quantities: number[]; primary: string;
    processes: Record<string, CostProc> };
  drivers: Driver[];
  disclaimer: string;
}

export interface Machine {
  name: string; kind: "mill3" | "mill5" | "lathe" | "printer_fdm" | "printer_sla" | "printer_sls";
  travel_mm?: number[] | null; max_diameter_mm?: number | null; max_length_mm?: number | null; rate_per_hour: number;
}
export interface ShopProfile {
  name: string; currency: string; machines: Machine[];
  smallest_tool_d_mm: number; max_tool_reach_mm: number; max_flank_mm: number; max_drill_ld: number; deep_drill_ld: number;
  min_wall_metal_mm: number; min_wall_plastic_mm: number; min_draft_deg: number;
  setup_minutes: number; programming_minutes: number; mrr_cm3_min: Record<string, number>; turning_mrr_factor: number;
  finish_cm2_min: number; minutes_per_hole: number; material_price_per_kg: Record<string, number>;
  mould_tooling_cost: number; mould_cycle_s: number; moulding_rate_per_hour: number; casting_tooling_cost: number;
  casting_minutes_per_part: number; am_material_per_kg: Record<string, number>; am_rate_cm3_h: Record<string, number>;
  sheet_cut_mm_min: number; sheet_minutes_per_bend: number;
}
export interface ShopResp { profile: ShopProfile; is_default: boolean; can_edit: boolean; note: string; fingerprint: string }
export interface MfgProject {
  id: string; name: string; thumbnail: string | null; built: boolean; material: string | null; updated_at: string;
  analysed: boolean; counts: Record<Severity, number> | null; stale?: boolean;
}

export const PROCESS_LABEL: Record<ProcessKey, string> = {
  cnc_milling: "Milling & drilling", cnc_turning: "Turning", sheet_metal: "Sheet metal", moulding_casting: "Moulding & casting",
};
export const COST_NAMES: Record<string, string> = {
  cnc_milling: "CNC milling", cnc_turning: "CNC turning", sheet_metal: "Sheet metal", fdm: "3D print (FDM)",
  sla: "3D print (SLA)", sls: "3D print (SLS)", casting: "Casting", injection_moulding: "Injection moulding",
};
