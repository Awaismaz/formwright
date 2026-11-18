import type { AirSettings } from "./prompt";

export interface Integration {
  has_key: boolean; key_hint: string | null; key_added_at: string | null; key_added_by: string | null;
  key_checked_at: string | null; model: string; can_manage: boolean; fake: boolean;
  consent: { given: boolean; at: string | null; by: string | null; text: string; version: number };
}

export interface Choice { id: string; label: string; reliable?: boolean; eta_s?: number }

export interface Options {
  scenes: Choice[]; lighting: Choice[]; cameras: Choice[]; backgrounds: Choice[]; styles: Choice[];
  sizes: Choice[]; qualities: Choice[]; max_variants: number; defaults: AirSettings; caption: string; model: string;
}

export interface Reference { id: string; kind: "mesh_final" | "mesh_preview" | "model"; label: string; detail: string; at: string | null; url: string }

export interface AirJob {
  id: string; state: "queued" | "running" | "done" | "failed"; created_at: string; started_at: string | null;
  finished_at: string | null; seconds: number | null; settings: AirSettings; prompt: string; sent_prompt: string | null;
  negative: string[]; engine: string; reference: Omit<Reference, "url"> | null; model: string;
  usage: { input_tokens?: number; output_tokens?: number; total_tokens?: number } | null;
  error: string | null; error_code: string | null; variation_of: { job: string; index: number } | null;
  eta_s: number | null; images: { index: number; url: string; thumb: string }[]; caption: string; reference_url: string | null;
}

export interface ProjectInfo {
  project: { id: string; name: string; thumbnail: string | null };
  facts: { name: string; material: string | null; size_mm: number[] | null; features: string[]; build_id: number | null };
  finish: string; references: Reference[]; can_make_reference: boolean; jobs: AirJob[]; caption: string;
}

export interface Refined { prompt: string; negative: string[]; engine: "ai" | "template"; note: string | null; tokens?: number }
