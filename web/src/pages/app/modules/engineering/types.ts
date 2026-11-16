/* Engineering Advisor: API types and small helpers (units, formatting, advice levels). */

export type Kind = string;
export interface UnitOpt { unit: string; label: string }
export interface Column { key: string; label: string; kind: Kind; unit: string; default: unknown; options?: { value: string; label: string }[] | null; min?: number | null; units?: UnitOpt[] }
export interface Param {
  key: string; label: string; kind: Kind; default: unknown; unit: string; unit_label?: string; units?: UnitOpt[];
  min: number | null; max: number | null; exclusive_min: boolean; help: string; group: string; optional: boolean;
  options: { value: string; label: string }[] | null; columns: Column[] | null; show_if: Record<string, unknown[]> | null; prefill: string | null;
}
export interface CalcSchema {
  id: string; name: string; category: string; summary: string; version: string; keywords: string[];
  inputs: Param[]; references: string[]; assumptions: string[]; verified_against: string[]; safety_factor: boolean; prefill: string[]; level: string;
}
export interface Step { label: string; equation: string; substitution: string; value: number | string | null; unit: string; ref: string }
export interface Output { key: string; label: string; value: number | string | null; kind: Kind; unit: string; primary: boolean }
export interface Check { label: string; achieved: number | string | null; required: number | null; source: string; passed: boolean | null; basis: string }
export interface CalcResult {
  calc_id: string; calc_name: string; calc_version: string; engine: string; inputs: Record<string, unknown>;
  steps: Step[]; outputs: Output[]; checks: Check[]; warnings: string[]; notes: string[]; references: string[];
  assumptions: string[]; verified_against: string[]; level: string; safety_factor: { required: number | null; source: string } | null;
}
export interface Catalog {
  calculators: CalcSchema[]; units: Record<string, { canonical: string; label: string; units: UnitOpt[] }>;
  levels: Record<string, { label: string; meaning: string }>; engine: string; can_edit: boolean;
  library: { standards_version: string; tables: { table: string; source: string; rows: number }[]; materials_version: string; materials_note: string; materials: Material[] };
}
export interface Material { code: string; name: string; condition: string; basis: string; Sut_MPa: number | null; Sy_MPa: number | null; E_GPa: number; nu: number; fatigue_MPa?: number; fatigue_note?: string; source: string; version: string; note: string; brittle?: boolean }
export interface Who { id: string; name: string }
export interface Suggestion { calc_id: string; title: string; inputs: Record<string, unknown>; provenance: Record<string, string> }
export interface Hint { id: string; kind: string; severity: "high" | "medium" | "low"; title: string; detail: string; location: number[] | null; suggestion: string; calc?: string; prefill?: Record<string, number> }
export interface ModelInfo {
  available: boolean; reason?: string; project?: { id: string; name: string }; ok?: boolean; part?: string; bbox?: number[];
  params?: Record<string, unknown>; features?: string[]; material?: { code: string; name: string; density_g_cm3: number; group: string } | null; material_source?: string;
  mechanical?: Material | null;
  mass?: { volume_mm3: number; mass_kg: number | null; com_mm: number[] | null; inertia_kg_mm2: number[][] | null; weight_N: number | null; density_source: string };
  recognition?: { summary?: string[]; stock?: { kind: string } }; hints?: Hint[]; suggestions?: Suggestion[]; geometry_error?: string | null;
}
export interface SetItem { id: string; calc_id: string; calc_version: string; title: string; raw_inputs: Record<string, unknown>; result: CalcResult; source: Record<string, string> | null; added_by: Who; added_at: string; edited_by?: Who; edited_at?: string }
export interface Signoff { user_id: string; name: string; email: string; role: string; at: string; hash: string; statement: string; self_check: boolean; items: number }
export interface CalcSet {
  id: string; name: string; notes: string; conclusion: string; load_case_ids: string[]; items: SetItem[]; signoff: Signoff | null;
  created_at: string; created_by: Who; updated_at: string; updated_by: Who; history: { at: string; by: Who; event: string; detail: string }[];
  status: { state: "signed" | "invalidated" | "unsigned"; hash: string; label: string; for_release: boolean }; level: string;
}
export interface Load { name: string; type: string; value: number; unit: string; direction: string; location: string; basis: string; source: string; value_canonical?: number; unit_canonical?: string }
export interface Support { type: string; location: string; note: string }
export interface LoadCase { id: string; name: string; kind: string; description: string; loads: Load[]; supports: Support[]; cycles: number | null; temperature_c: number | null; environment: string; source: string; updated_at: string; updated_by: Who }
export interface StackRow { name: string; dir: "+" | "-"; nominal: number; plus: number; minus: number; sens: number; source?: string }
export interface Stackup { id: string; name: string; description: string; unit: "mm" | "in"; rows: StackRow[]; spec_min: number | null; spec_max: number | null; result: CalcResult & { contributions: { name: string; pct_wc: number; pct_rss: number }[] }; updated_at: string; updated_by: Who }
export interface ReviewItem { id: string; mode: string; title: string; why: string; calculators: string[]; analyses: { what: string; why: string }[]; features: string[]; level: string; state: { status: string; note?: string; by?: Who; at?: string } }
export interface Review { available: boolean; reason?: string; items: ReviewItem[]; hints: Hint[]; analyses: { what: string; why: string; for: string[] }[]; heuristic_note?: string }

/* ---- number formatting: engineering significant figures */
export function fmt(v: unknown, sig = 4): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string") return v;
  if (typeof v !== "number" || Number.isNaN(v)) return String(v);
  if (!Number.isFinite(v)) return "∞";
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e7 || a < 1e-4) return v.toExponential(sig - 1);
  const digits = Math.max(0, sig - 1 - Math.floor(Math.log10(a)));
  return Number(v.toFixed(digits)).toLocaleString(undefined, { maximumFractionDigits: digits });
}

/* ---- display units: SI (canonical) or US customary; factors = canonical units per display unit */
export type UnitSystem = "SI" | "US";
const US: Record<string, [string, number]> = {
  length: ["in", 25.4], force: ["lbf", 4.4482216152605], stress: ["ksi", 6.894757293168361], moment: ["lbf·in", 112.98482902],
  line_load: ["lbf/in", 0.17512683524647], stiffness: ["lbf/in", 0.17512683524647], area: ["in²", 645.16], section_modulus: ["in³", 16387.064],
  inertia_area: ["in⁴", 416231.42563], mass: ["lb", 0.45359237],
};
export function display(o: { value: unknown; kind: string; unit: string }, sys: UnitSystem, unitLabel: (k: string) => string): { value: string; unit: string } {
  if (typeof o.value === "number" && sys === "US" && US[o.kind]) {
    const [u, f] = US[o.kind]!;
    return { value: fmt(o.value / f), unit: u };
  }
  if (typeof o.value === "number" && o.kind === "moment") return { value: fmt(o.value / 1000), unit: "N·m" };  // engineers read torque in N·m
  if (typeof o.value === "number" && o.kind === "stiffness") return { value: fmt(o.value / 1000), unit: "kN/mm" };
  return { value: fmt(o.value), unit: unitLabel(o.kind) };
}

export const LEVEL_TONE: Record<string, "neutral" | "primary" | "success" | "warning" | "accent"> = {
  recommended_check: "neutral", preliminary_estimate: "warning", verified_calculation: "success", validated_simulation: "primary",
};
export const SEVERITY_TONE: Record<string, "danger" | "warning" | "neutral"> = { high: "danger", medium: "warning", low: "neutral" };

/* form values: numbers kept as strings while typing; unit-bearing fields as {value, unit} */
export type FormVal = string | boolean | { value: string; unit: string } | Record<string, unknown>[];
export type FormState = Record<string, FormVal>;

export const isUnitKind = (k: string) => !["enum", "bool", "text", "table"].includes(k);
export const UNITLESS = new Set(["ratio", "count", "megarev", "speed", "time", "angle"]);

export function initialForm(c: CalcSchema, raw?: Record<string, unknown>): FormState {
  const f: FormState = {};
  for (const p of c.inputs) {
    const v = raw && p.key in raw ? raw[p.key] : p.default;
    f[p.key] = toFormVal(p, v);
  }
  return f;
}

function canonicalToUnit(v: number, unit: string, canonical: string): number {
  // defaults from the schema are canonical (mm, N, MPa, N·mm). Convert to the param's default display unit.
  const F: Record<string, number> = { GPa: 1000, kN: 1000, "N*m": 1000, "kN*m": 1e6, m: 1000, cm: 10 };
  if (unit === canonical || !F[unit]) return v;
  return v / F[unit]!;
}

export function toFormVal(p: Param, v: unknown): FormVal {
  if (p.kind === "bool") return Boolean(v);
  if (p.kind === "enum" || p.kind === "text") return v === null || v === undefined ? "" : String(v);
  if (p.kind === "table") {
    const rows = Array.isArray(v) ? v as Record<string, unknown>[] : [];
    return rows.map(r => Object.fromEntries((p.columns ?? []).map(c => [c.key, colVal(c, r[c.key] ?? c.default)])));
  }
  if (UNITLESS.has(p.kind) && (p.units?.length ?? 0) <= 1) {
    if (v && typeof v === "object" && "value" in (v as object)) return String((v as { value: unknown }).value ?? "");
    return v === null || v === undefined ? "" : String(v);
  }
  if (v && typeof v === "object" && "value" in (v as object)) {
    const o = v as { value: unknown; unit?: string };
    return { value: o.value === null || o.value === undefined ? "" : String(o.value), unit: o.unit || p.unit };
  }
  if (v === null || v === undefined || v === "") return { value: "", unit: p.unit };
  return { value: String(+canonicalToUnit(Number(v), p.unit, p.units?.[0]?.unit ?? p.unit).toPrecision(10)), unit: p.unit };
}

function colVal(c: Column, v: unknown): unknown {
  if (c.kind === "text" || c.kind === "enum") return v ?? "";
  if (v && typeof v === "object" && "value" in (v as object)) {
    const o = v as { value: unknown; unit?: string };
    return { value: String(o.value ?? ""), unit: o.unit || c.unit };
  }
  if (c.kind === "ratio" || c.kind === "count") return v === null || v === undefined ? "" : String(v);
  return { value: v === null || v === undefined ? "" : String(+canonicalToUnit(Number(v), c.unit, c.units?.[0]?.unit ?? c.unit).toPrecision(10)), unit: c.unit };
}

export function visible(p: Param, f: FormState): boolean {
  if (!p.show_if) return true;
  return Object.entries(p.show_if).every(([k, allowed]) => {
    const v = f[k];
    const raw = v && typeof v === "object" && !Array.isArray(v) && "value" in v ? (v as { value: string }).value : v;
    return allowed.includes(raw as never);
  });
}

/** Form → API inputs (numbers parsed; empty optional fields omitted). */
const num = (s: string): number | string => { const n = Number(s.trim()); return Number.isFinite(n) ? n : s; };

export function toInputs(c: CalcSchema, f: FormState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const p of c.inputs) {
    if (!visible(p, f)) continue;
    const v = f[p.key];
    if (p.kind === "bool") { out[p.key] = Boolean(v); continue; }
    if (p.kind === "enum" || p.kind === "text") { if (v !== "") out[p.key] = v; continue; }
    if (p.kind === "table") {
      out[p.key] = (v as Record<string, unknown>[]).map(r => Object.fromEntries(Object.entries(r).map(([k, x]) => {
        if (x && typeof x === "object" && "value" in (x as object)) { const o = x as { value: string; unit: string }; return [k, o.value === "" ? null : { value: num(o.value), unit: o.unit }]; }
        const col = p.columns?.find(cc => cc.key === k);
        if (col && (col.kind === "ratio" || col.kind === "count")) return [k, x === "" ? null : num(String(x))];
        return [k, x];
      })));
      continue;
    }
    if (typeof v === "string") { if (v.trim() !== "") out[p.key] = num(v); continue; }
    const o = v as { value: string; unit: string };
    if (o && o.value.trim() !== "") out[p.key] = { value: num(o.value), unit: o.unit };
  }
  return out;
}

/** Merge a pre-fill suggestion (API values) into a form. */
export function applyPrefill(c: CalcSchema, f: FormState, inputs: Record<string, unknown>): FormState {
  const next = { ...f };
  for (const p of c.inputs) if (p.key in inputs) next[p.key] = toFormVal(p, inputs[p.key]);
  return next;
}
