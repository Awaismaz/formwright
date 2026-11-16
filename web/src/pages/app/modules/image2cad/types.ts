export const BASE = "/api/m/image2cad";

export type UploadStatus = "reading" | "review" | "failed" | "created";

export interface UploadSummary {
  id: string; name: string; type: "pdf" | "png" | "jpg" | "webp"; bytes: number; created_at: string;
  status: UploadStatus; error: string | null; project_id: string | null; method: "vector" | "vision" | null;
  pages?: number | null; step?: string | null; preview: string | null;
  counts?: { dims: number; open: number };
  roundtrip?: { matched: number; checked: number } | null;
}

/** Measured token estimates: typical run and the upper figure a run needs in the balance before it starts. */
export interface CostLine { tokens: number; high: number; runs: number; basis: "measured" | "seed" }
export interface Estimate { read: CostLine; build: CostLine; balance: number | null; unlimited: boolean }

export interface RoundTripRow {
  id: string; label: string; describes?: string | null; status: "match" | "count" | "missing" | "skipped";
  found: string | null; note: string | null;
}
export interface RoundTrip {
  rows: RoundTripRow[]; matched: number; checked: number; skipped: number; ok: boolean; at: string;
  build_id: string | null; stale?: boolean;
}

export interface Tol { plus: number; minus: number }

export interface Dim {
  id: string; text: string; label: string; read_text: string | null;
  kind: string; value: number | null; count: number | null; tol: Tol | null; fit: string | null;
  reference: boolean; through: boolean; depth: number | null; pitch?: number | null;
  x: number | null; y: number | null; box: number[] | null; dir: string | null;
  view: string | null; view_alt?: string | null; confidence: number; source: "text" | "vision" | "user";
  describes?: string | null; alternatives?: string[]; kind_unclear?: string[];
  edited: boolean; excluded: boolean; confirmed: boolean;
}

export interface View {
  id: string; name: string; label?: string | null; kind: "ortho" | "iso" | "section" | "detail";
  box: number[] | null; drawn_mm?: number[]; place?: string; suggest_front?: boolean; looks_like?: string;
}

export interface Opt { value: string; label: string; hint?: string; matched?: boolean }

export interface Need {
  id: string; kind: "reference" | "choice" | "confirm" | "unparsed" | "unreadable" | "missing";
  question: string; detail?: string | null; options: Opt[]; default: string | null; default_unit?: string | null;
  input?: "callout" | "text" | "value"; dim?: string; x?: number | null; y?: number | null;
  answer: Answer | RefAnswer | null; answered: boolean; blocking: boolean;
}

export interface Answer { choice?: string; text?: string; value?: number; unit?: string }
export interface RefAnswer { dim?: string | null; value?: number; unit?: string; describes?: string | null }

export interface Check {
  view: string; axis: "width" | "height"; drawn_mm: number; dim: string; value: number;
  match?: boolean; conflict?: boolean; units?: string; at_scale?: number; implied_scale?: number | null;
}

export interface Read {
  method: "vector" | "vision"; drawing_kind?: string; part?: string | null;
  dims: Dim[]; views: View[]; title: Record<string, string>; title_block: number[] | null;
  scale: { ratio: number[]; text: string; evidence: string } | null;
  units: { value: string; evidence: string; inferred?: boolean } | null;
  unparsed: { text: string; x: number | null; y: number | null }[];
  unreadable?: { note: string; x: number | null; y: number | null }[];
  checks: Check[]; pages?: number; paper_mm?: number[]; preview_px?: { w: number; h: number };
  projection?: { value: string; evidence: string } | null; title_text?: string | null;
}

export interface Review {
  dims: Record<string, { text?: string; excluded?: boolean; confirmed?: boolean; describes?: string }>;
  added: { id?: string; text: string; describes?: string | null; view?: string | null }[];
  answers: Record<string, Answer>;
  reference: RefAnswer | null;
  notes: string;
}

export interface ReviewState {
  dims: Dim[]; needs: Need[]; open: number; ready: boolean; assumptions: string[];
  documentation: { what: string; why?: string | null }[]; name: string | null; drawing_no: string | null;
  scale: {
    status: "undefined" | "confirmed" | "corrected"; summary: string; evidence: string[]; warning?: string;
    stated: Read["scale"]; units: Read["units"];
    reference: { dim: string | null; value: number; unit: string; describes: string } | null;
  };
}

export interface Full {
  upload: UploadSummary; read: Read | null; review: Review; state: ReviewState | null;
  project: { id: string; name: string; built: boolean; build_id: string | null } | null; can_edit: boolean;
  estimate: Estimate; roundtrip: RoundTrip | null;
}

export const KIND_LABEL: Record<string, string> = {
  linear: "Length", diameter: "Diameter", radius: "Radius", spherical_radius: "Sph. radius",
  spherical_diameter: "Sph. diameter", square: "Square", thread: "Thread", angle: "Angle", chamfer: "Chamfer",
};
