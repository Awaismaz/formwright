export interface Colour { id: string; label: string; hex: string }
export interface Finish { id: string; label: string; group: string; colours: Colour[] | null; default_colour: string | null; swatch: string }
export interface Presets {
  finishes: Finish[];
  lighting: { id: string; label: string; hint: string; background: string }[];
  cameras: { id: string; label: string }[];
  aspects: string[];
  poses: { id: string; label: string }[];
  quality: Record<"preview" | "final" | "turntable" | "turntable_draft", { label: string; res: [number, number]; frames: number | null }>;
  disclosure: string;
  renderer: { available: boolean; engine: string; device: "GPU" | "CPU" | null; gpu: string | null; reason?: string | null;
    warm: boolean; warm_up_estimate_s: number };
}

export interface Settings {
  finish: string; colour: string | null; lighting: string; camera: string; aspect: string;
  transparent: boolean; pose: string; soften_edges: boolean;
  /** assemblies only: 0..1 of the full explode */
  explode?: number;
}

export type JobState = "queued" | "running" | "done" | "failed";
export interface Job {
  id: string; kind: "preview" | "final" | "turntable" | "export"; state: JobState;
  options: Partial<Settings> & { quality?: string }; label: string | null; explode?: number | null;
  created_at: string; started_at: string | null; finished_at: string | null;
  seconds: number | null; render_seconds: number | null; progress: number | null; phase: string | null;
  error: string | null; size: [number, number] | null; triangles: number | null; cached?: boolean;
  device: { engine: string; device: "GPU" | "CPU"; backend: string | null; gpu: string | null; samples: number } | null;
  files: Record<string, { url: string; bytes: number }>; queue_position?: number | null; disclosure: string;
  /** first GPU render on this server: preparing the GPU (no progress lines until it ends) */
  warming?: boolean | null; warm_estimate_s?: number; eta_s?: number | null; frames?: number | null;
  /** highlight protection: exposure change (EV) and the measured share of the part in the white shoulder */
  highlights?: { ev: number; blown: number | null; ok: boolean } | null;
  /** part revision the render shows; stale when the project has been rebuilt since */
  revision: number | null; stale: boolean; build_id: number | null;
}

export interface MeshCheck { id: string; name: string; status: "pass" | "warn" | "fail" | "info"; value: unknown; detail: string }
export interface AssemblyPart { key: string; name: string; material: string | null; finish: string; colour: string | null; count: number; visible: number }
export interface ProjectInfo {
  kind?: "assembly"; parts?: AssemblyPart[]; instances?: number; explode_steps?: number[];
  project: { id: string; name: string; material: string | null; build_id: number | null; revision: number | null };
  look: (Settings & { saved_by: string | null; saved_at: string | null }) | null;
  suggested: { finish: string; colour: string | null; matched: string | null };
  mesh: null | { triangles: number; vertices: number; tolerance_mm: number; bbox_mm: number[]; volume_mm3: number; checks: MeshCheck[] };
  disclosure: string; renders: Job[]; exports: Job[]; previews: Job[];
}
