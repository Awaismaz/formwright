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
export type RunStatus = "queued" | "searching" | "designing" | "reviewing" | "integrating" | "waiting_capacity" | "retry"
  | "blocked" | "done" | "manual" | "paused";
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
  kind: "brief" | "ticket" | "blocked"; reason?: string | null; program_id: string; program: string; at: string; title: string;
  ticket_id?: string; key?: string; specialist?: string; checks?: { ok: boolean } | null; source?: string;
}

export interface Home { programs: ProgramSummary[]; roster: RosterAgent[]; inbox: InboxItem[]; budget: { tokens: number; spent: number }; can_edit: boolean }

export interface OfficeEvent {
  seq: number; t: string; type: string; program_id: string; ticket_id: string | null; actor: Actor; text: string;
  data: Record<string, unknown>;
}
