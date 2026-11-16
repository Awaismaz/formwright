export type Status = "pass" | "warn" | "fail" | "info";
export type ProcessCode = "fdm" | "sla" | "sls";

export interface Check {
  id: string; name: string; status: Status; value: number | number[] | null; limit: number | number[] | null;
  unit: string; detail: string; level: string; limit_is_assumption: boolean;
  regions?: { min_mm: number; area_mm2: number; feature?: string; face?: number; at: number[] }[];
  items?: { kind?: string; diameter_mm?: number; size_mm?: number }[];
}

export interface Orientation {
  id: string; rank: number; kind: string; label: string; down: number[]; rotation: number[][];
  euler_xyz_deg: [number, number, number]; height_mm: number; footprint_mm: [number, number]; fits: boolean;
  contact_area_mm2: number; overhang_area_mm2: number; support_area_mm2: number; support_volume_mm3: number;
  support_on_part_mm2: number; layers: number; score: number; rationale: string[]; strength_note: string;
  bridges: { count: number; max_span_mm: number };
  estimate: { time_s: number; part_material_mm3: number; support_material_mm3: number; model: string;
    part_mass_g: number | null; support_mass_g: number | null; level: string };
  checks: Check[];
}

export interface ProcessSettings {
  code: ProcessCode; name: string; layer_mm: number; min_wall_mm: number; warn_wall_mm: number; min_hole_mm: number;
  min_pin_mm: number; min_gap_mm: number; overhang_deg: number; max_bridge_mm: number | null; supports: boolean;
  printer_mm: [number, number, number]; infill: number; flow_mm3_s: number | null; layer_overhead_s: number;
  nozzle_mm: number | null; materials: string[]; default_material: string; edited?: string[]; note?: string;
}

export interface Material { code: string; name: string; density_g_cm3: number; verify?: boolean; source?: string }

export interface Presets {
  processes: Record<ProcessCode, ProcessSettings>; materials: Record<string, Material>; editable: string[];
  source: string; units: string[]; max_upload_mb: number; tolerance_range: [number, number];
}

export interface RepairReport {
  before: Record<string, number>; after: Record<string, number>; actions: string[];
}

export interface ExportFile { name: string; bytes: number; format: string; modified?: string }

export interface Report {
  disclosure: string; units: "mm"; process: ProcessSettings; material: Material | null; checks: Check[];
  orientations: Orientation[];
  topology: Record<string, number>;
  estimates: { volume_mm3: number; area_mm2: number; bbox_mm: number[]; mass_solid_g: number | null; density_g_cm3: number | null; level: string };
  thickness: { min_mm: number | null; cap_mm: number; min_wall_mm: number; warn_wall_mm: number; below_min_mm2: number; below_warn_mm2: number; median?: number };
  overhang: { angle_deg: number; bed_eps_mm: number; rule: string };
  summary: { status: Status; fails: number; warnings: number };
  source: { kind: "project" | "upload"; id: string; name: string; triangles: number; vertices: number;
    tolerance_mm?: number; deviation?: { max_mm: number; samples: number } | null; exact_volume_mm3?: number;
    volume_rel_dev?: number; format?: string; units?: string; repaired?: boolean; repair?: RepairReport | null; revision?: number };
  mesh_query: string; notes: string; presets_source: string; exports: ExportFile[];
}

export interface UploadMeta {
  id: string; name: string; format: string; units: string; bytes: number; triangles: number; created_at: string;
  repaired: boolean; repair: RepairReport | null; revision: number;
}

export interface Settings {
  process: ProcessCode; material: string; tolerance: number; overhang_deg: number;
  printer_mm: [number, number, number]; load_dir: "" | "X" | "Y" | "Z"; overrides: Record<string, number>;
}
