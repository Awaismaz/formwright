import type { QuickFinding, VisualRecord, VisualVerdict } from "@/components/VisualCheck";
/** Design Office API shapes (src/aicad/platform/routers/office.py, src/aicad/office/service.py). */

export type AgentState = "idle" | "working" | "review" | "blocked" | "done";
export type Column = "backlog" | "ready" | "in_design" | "in_review" | "changes_requested" | "approved" | "integrated";
export type Family = "machined" | "turned" | "gear" | "sheet" | "plastic" | "standard" | "integration" | "drawings" | "dfm";
export type ProgramStatus = "planning" | "plan_review" | "active" | "complete";

export interface Actor { kind: "user" | "agent" | "studio"; id?: string | null; code?: string; name: string }

export interface PlanPart { id: string; name: string; family: Family; complexity: number; qty: number; description: string; toolbox?: string | null }
export interface PlanSub { id: string; name: string; description: string; parts: PlanPart[] }
export interface Plan {
  source: "archie" | "standard"; summary: string; assumptions: string[]; subassemblies: PlanSub[];
  narrative?: string; note?: string | null; edited?: boolean;
}

export interface Eta { remaining_min: number; critical_path_min: number; concurrency: number; low_min: number; high_min: number }
export interface Rollup { estimate_min: number; done_min: number; remaining_min: number; progress: number }

export interface Item {
  id: string; parent_id: string | null; kind: "program" | "subassembly" | "part"; name: string;
  family?: Family; qty?: number; description?: string; toolbox?: string | null;
  rollup: Rollup; eta: Eta | null;
}

export interface Comment { id: string; by: Actor; text: string; t: string; delivery?: "queued" | "delivered" | "stored" }

/** What the orchestrator is doing with a ticket (server: office/orchestrator.py). */
export type RunStatus = "queued" | "searching" | "designing" | "reviewing" | "integrating" | "fitting" | "drafting"
  | "screening" | "waiting_capacity" | "retry" | "blocked" | "done" | "manual" | "paused" | "awaiting_review";
export interface TicketRun {
  status?: RunStatus; next?: string; agent?: string; agent_label?: string; line?: string; attempt?: number;
  review_round?: number; next_try_at?: number; blocked?: string; started_at?: string;
}
export interface Reuse { source: "toolbox" | "project"; title: string; found: string; code?: string; project_id?: string }
/** How the part was designed: built from the approved interfaces without AI, or by the design agent (and why). */
export interface DesignPath {
  path: "direct" | "agent"; label?: string; summary?: string; material?: string; seconds?: number; icd_version?: number;
  reasons?: string[]; seeded?: boolean; superseded?: boolean; fallback?: boolean;
}

export interface Ticket {
  id: string; key: string; item_id: string; kind: "part" | "standard" | "integration" | "deliverable"; title: string; brief: string;
  family: Family; specialist: string; complexity: number; estimate_min: number; qty: number; column: Column;
  milestones: string[]; progress: number; project_id: string | null; assembly_id: string | null;
  depends_on: string[]; comments: Comment[]; checks: { ok: boolean } | null; tokens: number;
  agent_state: AgentState; updated_at: string;
  /** Phase 3: who holds the ticket now, its live status line, and the engineer's controls. */
  agent?: string; agent_label?: string | null; line?: string | null; run_status?: RunStatus | null; run?: TicketRun | null;
  paused?: boolean; taken_over?: boolean; priority?: "high" | "normal" | "low"; review_tokens?: number; spent?: number;
  reuse?: Reuse | null; direct?: DesignPath | null; integration?: { summary?: string; clashes?: unknown[] } | null;
  /** Phase 4: Gage's interface conformance measurement of the latest build, and whether Fitz swapped it in. */
  icd_check?: IcdCheck | null; fitted?: boolean;
  /** Phase 5: deliverables (Ortho's drawings, Smithy's DFM), actual agent time and what it taught the estimates. */
  deliverable?: "drawings" | "dfm"; actual_min?: number; error_pct?: number | null; rounds?: Record<string, number>;
  calibrated?: { actual_min: number; learned: boolean; error_pct?: number | null; before?: number; after?: number;
    observed?: number; why?: string; profile?: string } | null;
  /** Phase 6: the engineer's decision at the per-part review gate; the change notice that reopened it. */
  reviewed?: { by: string; at: string; decision: "approved" | "changes"; note: string | null } | null; ecn?: string;
}

// ------------------------------------------------------------------ Phase 4: skeleton, ICD, change requests
export type InterfaceKind = "hole_pattern" | "shaft_bore" | "face" | "gear_mesh" | "bearing_seat" | "key" | "dowel" | "bearing_journal";
export interface CheckRow { feature: string; spec: string; measured: string; ok: boolean; delta_mm?: number; d_mm?: number }
/** The part's own frame as Gage matched it to the ICD part frame (identity: modelled in the ICD frame). */
export interface PartFrame { R: number[][]; t: number[]; identity: boolean; label: string }
export interface IcdCheck {
  version: number; ok: boolean; at?: string; envelope: CheckRow; frame?: PartFrame;
  interfaces: { interface: string; name: string; ok: boolean; rows: CheckRow[] }[];
}
export interface IcdFeature {
  type: "face" | "hole" | "boss" | "gear" | "seat" | "keyway"; label: string; c?: [number, number]; z?: number; n?: number; d?: number;
  fit?: string; module?: number; teeth?: number; tol?: number; z0?: number; z1?: number; b?: number; depth?: number; on?: "shaft" | "hub";
}
export interface IcdSide {
  item: string; copy: number; name: string; ticket_id?: string | null; key?: string | null; column?: Column | null;
  features: IcdFeature[]; check: { ok: boolean; rows: CheckRow[]; version?: number } | null;
}
export interface Interface {
  id: string; kind: InterfaceKind; name: string; label: string; datums: string[]; data: Record<string, unknown>;
  a: { item: string; copy: number; name: string }; b: { item: string; copy: number; name: string };
  sides: { a: IcdSide; b: IcdSide }; crs: string[]; editable: string[]; edited?: string[];
  limits?: { hole: [number, number] | null; shaft: [number, number] | null };
}
export interface IcdHistory {
  version: number; at: string | null; by: string | null; kind: "created" | "edited" | "approved" | "cr_accepted";
  text: string; interface?: string; cr?: string; reason?: string;
  changes: { interface: string; name?: string; field: string; before: unknown; after: unknown }[];
}
export interface SkeletonItem {
  name: string; role: "block" | "shaft" | "hub" | "gear"; shape: "box" | "cylinder"; size: [number, number, number];
  sub: string; parent: string | null; copies: [number, number, number][]; qty: number; source: string;
  d?: number; bore?: number; module?: number; teeth?: number; rot?: number;
  bearing?: { designation: number; item: string; journal: number; seats: number };
}
export interface Skeleton {
  units: "mm"; base: string | null; csys: string;
  /** How the program is laid out: on a block, in a gearbox housing, as a shaft line (no housing) or a row (nothing to mount on). */
  layout?: "block" | "gearbox" | "shaft_line" | "row"; envelope: { min: number[]; max: number[]; size: number[] };
  datums: { id: string; kind: string; name: string; origin: number[]; normal: number[] }[];
  axes: { id: string; name: string; item: string; origin: number[]; dir: number[] }[];
  items: Record<string, SkeletonItem>; notes: string[];
  standard: { item: string; name: string; qty: number; sub: string }[];
}
export interface Icd {
  version: number; status: "draft" | "approved"; interfaces: Interface[]; history: IcdHistory[]; problems: string[];
  /** Layout warnings shown at the gate, not blocking (e.g. bearings no seat or journal takes). */
  warnings?: string[];
  /** The problems with a stable code and the items / interfaces they name. */
  issues?: { code: string; severity: "error" | "warning"; text: string; items: string[]; interfaces: string[] }[];
  skeleton: Skeleton; fits: string[]; fasteners: string[]; bearings?: string[]; housing_fits?: string[];
  /** PD-73: Archie's look at the drafted layout. */
  look?: { at: string; verdict: VisualVerdict | null; quick: QuickFinding[]; image: boolean; line: string } | null;
}
export interface ChangeRequest {
  id: string; interface: string; interface_name: string; values: Record<string, unknown>; before: Record<string, unknown>;
  reason: string; by: Actor; ticket_id: string | null; status: "open" | "accepted" | "rejected"; created_at: string;
  icd_version: number; version_after?: number; affected?: string[];
  decision: { by: string; at: string; reason: string; ai_note?: string | null; tokens?: number } | null;
  delta?: { interface: string; field: string; before: unknown; after: unknown }[];
}
export interface AssemblyState {
  status: "building" | "ready" | "failed" | "unavailable"; final?: string; subs?: Record<string, string>;
  parts?: Record<string, { key: string; kind: "placeholder" | "real"; icd_version: number }>;
  summary?: string; clashes?: { a: string; b: string; a_name?: string; b_name?: string; volume_mm3: number }[];
  mates?: number; at?: string; solve?: string | null; problems?: string[];
}
/** The live program assembly (GET /programs/{pid}/assembly). */
export interface LiveInstance {
  id: string; name: string; part: string; T: number[]; item: string | null; copy: number | null;
  kind: "placeholder" | "real" | "toolbox"; fastener: boolean; bin: boolean; sub: string | null;
}
export interface LiveAssembly {
  status: AssemblyState["status"] | null; summary?: string | null; at?: string | null;
  /** PD-73: the visual checks (layout, each integrated level), advisory. */
  looks?: (VisualRecord & { image: string | null; name: string; level: string })[];
  /** PD-71: the whole-program clash check after the final assembly (advisory, never blocks). */
  check?: { status: "running" | "done" | "failed" | "skipped"; text?: string; at?: string; count?: number } | null;
  clashes: { a: string; b: string; a_name?: string; b_name?: string; volume_mm3: number }[];
  view: null | {
    assembly_id: string; rev: number; instances: LiveInstance[];
    parts: Record<string, { key: string; topo_url: string; bbox: number[]; kind: string }>;
    explode: Record<string, [number, number, number]>; solve: string | null;
    clashes: { a: string; b: string; a_name?: string; b_name?: string; volume_mm3: number; mesh: { pos: number[]; idx: number[] } | null }[];
    envelope: Skeleton["envelope"]; subs: { id: string; name: string; assembly_id: string }[];
  };
  items: Record<string, { ticket_id: string; key: string; title: string; column: Column; specialist: string; line?: string | null;
    state: "placeholder" | "real" | "toolbox" | null; progress: number }>;
  can_edit: boolean;
}

export type OrchestratorState = "idle" | "running" | "paused" | "stopped" | "complete";
export interface Orchestrator {
  state: OrchestratorState; reason?: "budget" | "balance" | null; by?: string | null; started_at?: string | null;
  capacity_until?: number | null; bypass?: boolean; working: number; waiting: number; blocked: number;
  active?: number; simulated?: boolean; review?: number;
}

export interface Gate { code: string; name: string; mandatory: boolean; status: string; note?: string; by?: string; at?: string }

export interface Constants {
  minutes_per_unit: Record<Family, number>; complexity: [number, number];
  milestones: { code: string; label: string; weight: number }[]; default_concurrency: number; eta_factors: [number, number];
}

export interface Program {
  id: string; name: string; brief: string; key: string; status: ProgramStatus; planner: "archie" | "standard";
  planning: { started_at: string; notes: string } | null; plan: Plan | null;
  plan_estimate?: { tickets: number; estimate_min: number; eta: Eta };
  gates: Gate[]; items: Item[]; tickets: Ticket[]; columns: { code: Column; label: string }[];
  counts: Record<Column, number>; rollup: Rollup | null; eta: Eta | null; concurrency: number;
  budget: { tokens: number; planning_tokens: number; spent: number; pct?: number; level?: "ok" | "warn" | "stop" };
  orchestrator?: Orchestrator;
  icd?: Icd | null; change_requests?: ChangeRequest[]; assembly?: AssemblyState | null;
  constants: Constants; families: { code: Family; label: string; specialist: string }[];
  created_at: string; updated_at: string; can_edit?: boolean;
  /** Phase 5 */
  released?: { rev: string; date: string; by: string; issued_at: string } | null; deliverables_auto?: boolean;
  calibration?: { profile: "live" | "simulated"; rates: Record<string, number>; at: string } | null;
  /** Phase 6 */
  review_gate?: boolean; ecns?: Ecn[];
  /** Per-agent threads (CD-027): parallel sub-agents of one designer; null on programs from before (shared pool). */
  threads?: Record<string, number> | null;
}

// ------------------------------------------------------------------ talking to Archie (CD-026)
export interface ArchieAction {
  id: string; type: string; label: string; status: "proposed" | "applied" | "dismissed"; ticket?: string;
  by?: Actor; at?: string;
}
export interface ArchieMessage {
  id: string; role: "user" | "archie"; text: string; t: string; by?: Actor;
  kind?: "status" | "ai" | "office" | "look"; tokens?: number; actions?: ArchieAction[];
  /** Archie spoke first (a look, a failure): founder 2026-11-19. */
  unprompted?: boolean;
  visual?: { level: string; image: string | null; verdict: VisualVerdict | null; quick: QuickFinding[] | null; tokens?: number };
}
export interface ArchieChat { messages: ArchieMessage[]; ai: boolean; can_edit: boolean }

export interface ProgramSummary {
  id: string; name: string; key: string; status: ProgramStatus; planner: string; created_at: string; updated_at: string;
  rollup: Rollup | null; eta: Eta | null; counts: Record<Column, number>; budget: Program["budget"]; gates: Gate[];
  concurrency: number; tickets: number; brief: string; orchestrator?: Orchestrator;
  released?: Program["released"];
}

export interface RosterAgent {
  code: string; name: string; role: string; colour: string; pun: string; phase: number; idle_line: string;
  state: AgentState; line: string; assigned: number; delivered: number; program_id: string | null;
}

export interface InboxItem {
  kind: "brief" | "ticket" | "blocked" | "icd" | "review"; reason?: string | null; program_id: string; program: string; at: string; title: string;
  ticket_id?: string; key?: string; specialist?: string; checks?: { ok: boolean } | null; source?: string;
}

export interface Home { programs: ProgramSummary[]; roster: RosterAgent[]; inbox: InboxItem[]; budget: { tokens: number; spent: number }; can_edit: boolean }

export interface OfficeEvent {
  seq: number; t: string; type: string; program_id: string; ticket_id: string | null; actor: Actor; text: string;
  data: Record<string, unknown>;
}

// ------------------------------------------------------------------ Phase 5: timeline, calibration, deliverables
export interface TimelineSegment {
  stage: string; kind: "work" | "capacity" | "blocked"; agent: string | null; label: string | null;
  start: number; end: number; open: boolean; what: string;
}
export interface TimelineRow {
  id: string; key: string; title: string; kind: Ticket["kind"]; specialist: string; column: Column; estimate_min: number;
  planned: { start: number; end: number; slot: number } | null; segments: TimelineSegment[]; actual_min: number;
  error_pct: number | null; critical: boolean; rounds: Record<string, number>;
}
export interface TimelineBar extends TimelineSegment { ticket: string; key: string; title: string; critical: boolean }
export interface TimelineMarker { t: number; type: "cr.raised" | "cr.accepted" | "cr.rejected"; text: string; cr?: string | null; ticket?: string | null }
export interface Timeline {
  origin: number | null; now: number; concurrency: number; rows: TimelineRow[];
  lanes: { label: string; agent: string; bars: TimelineBar[] }[]; critical: string[]; markers: TimelineMarker[];
  planned_end: number; actual_end: number; span: number; totals: { estimate_min: number; actual_min: number; done: number };
}
export interface CalibrationUpdate {
  at: string; family: string; specialist: string; ticket: string; title: string; program: string; complexity: number;
  estimate_min: number; actual_min: number; error_pct: number | null; before: number; observed: number; clamped: number; after: number;
}
export interface Calibration {
  profile: "live" | "simulated";
  families: { family: string; label: string; specialist: string; default: number; rate: number; n: number }[];
  history: CalibrationUpdate[]; accuracy: { at: string; family: string; ticket: string; estimate_min: number; actual_min: number; error_pct: number | null }[];
  trend: { n: number; mape: number }[]; rule: { alpha: number; step: [number, number]; bounds: [number, number]; window: number };
}
export interface BomRow {
  item: number; qty: number; part: string; make_buy: "make" | "buy"; kind: string; designation: string | null; standard: string | null;
  material: string | null; mass_each_g: number | null; mass_total_g: number | null; description: string; ticket: string | null; key: string | null;
}
export interface Bom { rows: BomRow[]; total_qty: number; make: number; buy: number; total_mass_g: number; mass_unknown: number; note: string }
export interface DfmLine {
  ticket: string; key: string; title: string; qty: number; ok: boolean; error?: string; process?: string; process_name?: string;
  critical?: number; warning?: number; info?: number; unit_cost?: number | null; currency?: string | null; relative_cost?: number | null;
  cost_share_pct?: number | null; material?: string; mass_kg?: number; kept?: boolean;
  findings?: { rule: string; severity: string; title: string; measured: string; limit: string; fix: string }[];
}
export interface DfmSummary {
  parts: DfmLine[]; analysed: number; critical: number; warning: number; attention: string[]; program_cost: number;
  currency: string | null; label: string; note: string; at?: string;
}
export interface DrawingSheet {
  ticket: string; key: string; title: string; project_id: string; ok: boolean; error?: string; check_passed?: boolean;
  problems?: string[]; scale?: string; size?: string; spec_dims?: number; inferred_dims?: number; icd_dims?: number; icd_offered?: number;
  kept?: boolean;
}
/** Phase 6: an engineering change notice on a released program. */
export interface Ecn {
  id: string; reason: string; by: Actor; created_at: string; items: string[]; tickets: string[]; titles: string[];
  from_rev: string; to_rev: string | null; interface: string | null; values: Record<string, unknown> | null;
  icd_changes: string[]; cr_id: string | null; status: "open" | "in_work" | "ready" | "released";
  history: { status: string; at: string; by: string | null; text: string }[];
}
export interface ReleaseDiff {
  from: string; ecn: { id: string; reason: string } | null; changed: number; unchanged: number; summary: string;
  parts: { ticket: string; key: string; title: string; before: string | null; after: string; changed: boolean }[];
  bom: { added: { part: string; designation: string | null; qty: number }[]; removed: { part: string; designation: string | null; qty: number }[];
    qty_changed: { part: string; designation: string | null; before: number; after: number }[]; unchanged: number };
  icd: { before: number | null; after: number | null; changes: string[] };
}
export interface ProgramRelease {
  rev: string; date: string; by: string; note: string; issued_at: string; pack_sha256?: string; pack_bytes?: number; files?: string[];
  ecn?: string | null; diff?: ReleaseDiff;
  parts: { ticket: string; key: string; title: string; project_id: string; rev: string; reused: boolean; model_rev: number | null; tag: string }[];
}
export interface Deliverables {
  bom: Bom; dfm: DfmSummary | null;
  drawings: { sheets: DrawingSheet[]; at: string; assembly: { ok: boolean; error?: string; scale?: string; balloons?: { item: number }[];
    rows?: number; urls?: Record<string, string> } } | null;
  tickets: Ticket[]; auto: boolean; can_edit: boolean;
  gate: { ready: boolean; blocking: string[]; next_rev: string | null; releases: ProgramRelease[]; released: Program["released"];
    ecn?: Ecn | null; ecns?: Ecn[] };
}
