/** Design Office API shapes (src/aicad/platform/routers/office.py, src/aicad/office/service.py). */

export type AgentState = "idle" | "working" | "review" | "blocked" | "done";
export type Column = "backlog" | "ready" | "in_design" | "in_review" | "changes_requested" | "approved" | "integrated";
export type Family = "machined" | "turned" | "gear" | "sheet" | "plastic" | "standard" | "integration";
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
export type RunStatus = "queued" | "searching" | "designing" | "reviewing" | "integrating" | "fitting" | "waiting_capacity"
  | "retry" | "blocked" | "done" | "manual" | "paused";
export interface TicketRun {
  status?: RunStatus; next?: string; agent?: string; agent_label?: string; line?: string; attempt?: number;
  review_round?: number; next_try_at?: number; blocked?: string; started_at?: string;
}
export interface Reuse { source: "toolbox" | "project"; title: string; found: string; code?: string; project_id?: string }

export interface Ticket {
  id: string; key: string; item_id: string; kind: "part" | "standard" | "integration"; title: string; brief: string;
  family: Family; specialist: string; complexity: number; estimate_min: number; qty: number; column: Column;
  milestones: string[]; progress: number; project_id: string | null; assembly_id: string | null;
  depends_on: string[]; comments: Comment[]; checks: { ok: boolean } | null; tokens: number;
  agent_state: AgentState; updated_at: string;
  /** Phase 3: who holds the ticket now, its live status line, and the engineer's controls. */
  agent?: string; agent_label?: string | null; line?: string | null; run_status?: RunStatus | null; run?: TicketRun | null;
  paused?: boolean; taken_over?: boolean; priority?: "high" | "normal" | "low"; review_tokens?: number; spent?: number;
  reuse?: Reuse | null; integration?: { summary?: string; clashes?: unknown[] } | null;
  /** Phase 4: Gage's interface conformance measurement of the latest build, and whether Fitz swapped it in. */
  icd_check?: IcdCheck | null; fitted?: boolean;
}

// ------------------------------------------------------------------ Phase 4: skeleton, ICD, change requests
export type InterfaceKind = "hole_pattern" | "shaft_bore" | "face" | "gear_mesh";
export interface CheckRow { feature: string; spec: string; measured: string; ok: boolean; delta_mm?: number; d_mm?: number }
export interface IcdCheck {
  version: number; ok: boolean; at?: string; envelope: CheckRow;
  interfaces: { interface: string; name: string; ok: boolean; rows: CheckRow[] }[];
}
export interface IcdFeature { type: "face" | "hole" | "boss" | "gear"; label: string; c?: [number, number]; z?: number; n?: number; d?: number; fit?: string; module?: number; teeth?: number; tol?: number }
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
  d?: number; bore?: number; module?: number; teeth?: number;
}
export interface Skeleton {
  units: "mm"; base: string | null; csys: string; envelope: { min: number[]; max: number[]; size: number[] };
  datums: { id: string; kind: string; name: string; origin: number[]; normal: number[] }[];
  axes: { id: string; name: string; item: string; origin: number[]; dir: number[] }[];
  items: Record<string, SkeletonItem>; notes: string[];
  standard: { item: string; name: string; qty: number; sub: string }[];
}
export interface Icd {
  version: number; status: "draft" | "approved"; interfaces: Interface[]; history: IcdHistory[]; problems: string[];
  skeleton: Skeleton; fits: string[]; fasteners: string[];
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
  active?: number; simulated?: boolean;
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
}

export interface ProgramSummary {
  id: string; name: string; key: string; status: ProgramStatus; planner: string; created_at: string; updated_at: string;
  rollup: Rollup | null; eta: Eta | null; counts: Record<Column, number>; budget: Program["budget"]; gates: Gate[];
  concurrency: number; tickets: number; brief: string; orchestrator?: Orchestrator;
}

export interface RosterAgent {
  code: string; name: string; role: string; colour: string; pun: string; phase: number; idle_line: string;
  state: AgentState; line: string; assigned: number; delivered: number; program_id: string | null;
}

export interface InboxItem {
  kind: "brief" | "ticket" | "blocked" | "icd"; reason?: string | null; program_id: string; program: string; at: string; title: string;
  ticket_id?: string; key?: string; specialist?: string; checks?: { ok: boolean } | null; source?: string;
}

export interface Home { programs: ProgramSummary[]; roster: RosterAgent[]; inbox: InboxItem[]; budget: { tokens: number; spent: number }; can_edit: boolean }

export interface OfficeEvent {
  seq: number; t: string; type: string; program_id: string; ticket_id: string | null; actor: Actor; text: string;
  data: Record<string, unknown>;
}
