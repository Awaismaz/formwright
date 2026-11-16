export interface Colour { id: string; label: string; hex: string }
export interface Finish { id: string; label: string; group: string; colours: Colour[] | null; default_colour: string | null; swatch: string }
export interface Presets {
  finishes: Finish[];
  lighting: { id: string; label: string; hint: string; background: string }[];
  cameras: { id: string; label: string }[];
  aspects: string[];
  poses: { id: string; label: string }[];
  quality: Record<"preview" | "final" | "turntable", { label: string; res: [number, number]; frames: number | null }>;
  disclosure: string;
  renderer: { available: boolean; engine: string; device: "GPU" | "CPU" | null; gpu: string | null; reason?: string | null };
}

export interface Settings {
  finish: string; colour: string | null; lighting: string; camera: string; aspect: string;
  transparent: boolean; pose: string; soften_edges: boolean;
}

export type JobState = "queued" | "running" | "done" | "failed";
export interface Job {
  id: string; kind: "preview" | "final" | "turntable" | "export"; state: JobState;
  options: Partial<Settings> & { quality?: string }; label: string | null;
  created_at: string; started_at: string | null; finished_at: string | null;
  seconds: number | null; render_seconds: number | null; progress: number | null; phase: string | null;
  error: string | null; size: [number, number] | null; triangles: number | null; cached?: boolean;
  device: { engine: string; device: "GPU" | "CPU"; backend: string | null; gpu: string | null; samples: number } | null;
  files: Record<string, { url: string; bytes: number }>; queue_position?: number | null; disclosure: string;
}

export interface MeshCheck { id: string; name: string; status: "pass" | "warn" | "fail" | "info"; value: unknown; detail: string }
export interface ProjectInfo {
  project: { id: string; name: string; material: string | null; build_id: number | null };
  suggested: { finish: string; colour: string | null; matched: string | null };
  mesh: { triangles: number; vertices: number; tolerance_mm: number; bbox_mm: number[]; volume_mm3: number; checks: MeshCheck[] };
  disclosure: string; renders: Job[]; exports: Job[]; previews: Job[];
}
