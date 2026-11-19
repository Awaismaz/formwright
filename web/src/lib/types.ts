export type Role = "owner" | "admin" | "engineer" | "viewer";

export interface User {
  id: string; email: string; name: string; email_verified: boolean; is_superadmin: boolean;
  onboarding: Record<string, unknown>; onboarding_completed: boolean; tour_completed: boolean;
  preferences: { units?: "mm" | "in"; theme?: "light" | "dark" | "system"; notifications_email?: boolean; confirm_brief?: boolean };
  created_at: string;
  /** set while the email is unconfirmed: the end of the first-day grace */
  verify_by?: string | null;
}

export interface Org {
  id: string; name: string; role: Role; plan_code: string; plan_name: string;
  plan_status: "trialing" | "active" | "past_due" | "canceled"; token_balance: number; plan_tokens: number;
  current_period_end: string | null; seats_used: number; seat_limit: number; modules: string[];
  god_unlock: boolean; on_trial: boolean; trial_ends_at?: string; days_left?: number; expired?: boolean;
}

export interface GodFlags {
  available?: boolean; enabled?: boolean; bypass_paywall?: boolean; bypass_tokens?: boolean;
  skip_verification?: boolean; skip_onboarding?: boolean;
}

export interface Me {
  user: User | null;
  org?: Org | null;
  orgs?: { id: string; name: string; role: Role; plan_code: string }[];
  next_step?: "verify_email" | "onboarding" | "app";
  god?: GodFlags;
  impersonating?: { actor_email: string; actor_name: string } | null;
  system: { stripe_mode: "simulated" | "test" | "live"; env: string; god_mode_enabled: boolean };
}

export interface Product {
  code: string; kind: "plan" | "addon" | "topup" | "seat"; name: string; tagline: string; description: string;
  price_cents: number; interval: "month" | "year" | null; tokens: number; seats: number; modules: string[];
  features: string[]; highlight: boolean; contact_sales: boolean; purchasable: boolean; active: boolean; sort: number;
}

export interface Module {
  code: string; name: string; status: "live" | "preview"; icon: string; summary: string; bullets: string[];
  /** Live but still in beta, with honest tags such as "Uses your OpenAI key". */
  beta?: boolean; tags?: string[];
}

export interface RunRange { typical: number; low: number; high: number }

export interface Catalog {
  plans: Product[]; addons: Product[]; topups: Product[]; seats?: Product[]; modules: Module[];
  token_costs: Record<string, number>; stripe_mode: string;
  /** measured tokens per design run: a new part, a change to an existing part */
  typical_run?: { new: RunRange; change: RunRange }; trial_tokens?: number;
}

export interface RunEstimate extends RunRange {
  kind: "new" | "change"; basis: "typical" | "workspace"; samples: number;
  budget: number | null; default_budget: number; budget_min: number; budget_max: number;
}

export interface CheckResult { id: string; name: string; passed: boolean; gating: boolean; detail: Record<string, unknown> }

export interface BuildStatus {
  ok?: boolean; part?: string; material?: string; error?: string; error_plain?: string; build_id?: number;
  fingerprint?: { volume: number; bbox: number[]; faces: number; edges: number; solids: number };
  params?: Record<string, unknown>; checks?: CheckResult[]; expected?: Record<string, unknown>;
  /** parameters a user may change without the AI (declared, plain literal) and their current values */
  editable_params?: Record<string, number>;
  timings_s?: Record<string, number>; traceback?: string;
  param_meta?: Record<string, { min?: number; max?: number; step?: number; unit?: string; group?: string; label?: string; help?: string }>;
  mass?: { volume_mm3: number; area_mm2: number; com_mm: [number, number, number]; inertia_com_mm5: number[][]; principal_mm5: number[] };
  features?: { name: string; kind: string; params: Record<string, unknown>; chain?: boolean; suppressed?: boolean; error?: string }[];
  manual_features?: number; manual_errors?: RepairItem[];
  /** sheet metal (CAD-026): parameters, flat pattern size and the bend table; null for other parts */
  sheet_metal?: SheetMetalInfo | null;
}

export interface SheetBend {
  n: number; name: string; kind: "flange" | "hem" | "jog"; direction: "UP" | "DOWN"; angle: number; radius: number; k: number;
  ba: number; span: number; straight: number; length: number; length_ref: "outer" | "tangent"; position: string; outer_length: number | null;
}
export interface SheetMetalInfo {
  thickness: number; radius: number; k_factor: number; relief?: { type: "rect" | "obround" | "none"; ratio: number };
  corner?: { type: "closed" | "open"; gap: number };
  flat?: { size: [number, number]; bbox: number[]; area_mm2: number; perimeter_mm: number };
  bend_count: number; bends?: SheetBend[]; notes?: string[]; flat_error?: string;
}

export interface ManualFeature {
  id: string; op: "fillet" | "chamfer" | "hole" | "extrude" | "shell" | "mirror" | "sketch" | "revolve" | "pattern" | "plane" | "draft" | "rib" | "sketch2d" | "sweep" | "loft" | "thread" | "sm_base" | "sm_flange" | "sm_hem" | "sm_jog"; name: string; suppressed: boolean;
  /** below the rollback bar: kept in the tree, not built */
  rolled_back?: boolean;
  end?: "blind" | "mid" | "through"; reverse?: boolean;
  axis?: { a: [number, number]; b: [number, number] } | { origin: [number, number, number]; dir: [number, number, number] }; angle?: number;
  source?: string[]; kind?: "linear" | "circular";
  faces?: { point: [number, number, number]; normal?: [number, number, number] }[]; t?: number;
  /** draft: neutral plane face; rib: open profile chains and material side */
  neutral?: { point: [number, number, number]; normal: [number, number, number] }; chains?: unknown[]; flip?: boolean;
  pattern?: "circular"; center?: [number, number, number];
  edges?: [number, number, number][]; r?: number; d?: number;
  point?: [number, number, number]; normal?: [number, number, number]; depth?: number | null; count?: number; step?: [number, number, number];
  plane?: { origin: [number, number, number]; normal: [number, number, number]; x_dir?: [number, number, number] };
  sketch?: { kind: "rect" | "circle" | "poly"; w?: number; h?: number; r?: number; cx?: number; cy?: number };
  distance?: number; mode?: "add" | "cut";
  profiles?: unknown[]; editor?: unknown;
  /** reference plane: base plane, offset, angle about the base X/Y axis; `plane` holds the resolved placement */
  base?: { origin: [number, number, number]; normal: [number, number, number]; x_dir: [number, number, number] }; base_name?: string;
  offset?: number; rot_axis?: "x" | "y";
  /** sketch attached to a reference plane feature (follows it when the plane is edited) */
  plane_ref?: string;
  /** sweep: profile and path sketch node ids; loft: section sketch node ids in order */
  profile?: string; path?: string; sections?: string[]; ruled?: boolean;
  /** fillet/chamfer: kind and direction of each picked edge; body box when picked (picks follow size changes) */
  edge_refs?: { kind: "line" | "circle" | "other"; dir?: [number, number, number] }[]; ref_bbox?: number[];
  /** Hole Wizard: ISO fastener hole and its placement on a face by edge distance */
  spec?: { type: "clearance" | "tapped" | "cbore" | "csk"; size: number; fit?: string; pitch?: number; label?: string };
  cbore?: { d: number; depth: number }; csk?: { d: number; angle: number };
  place?: { mode: "corners" | "points"; face: { point: [number, number, number]; normal?: [number, number, number] }; x_dir?: [number, number, number]; dx?: number; dy?: number; pts?: [number, number][] };
  /** cosmetic thread (CAD-027) on a hole feature, or the thread of a Cosmetic Thread feature on a picked cylinder */
  thread?: { size: number; pitch: number; cls?: string; depth?: number | null; designation?: string; internal?: boolean };
  face?: { point: [number, number, number] };
  /** sheet metal (CAD-026). Base flange: thickness `t`, default inside radius `r`, K-factor and relief. Edge flange /
   * hem: the picked sheet edge, length (outer = from the outer virtual sharp), position, end offsets, hem gap */
  k?: number; relief?: { type: "rect" | "obround" | "none"; ratio: number }; corner?: { type: "closed" | "open"; gap: number };
  edge?: [number, number, number]; edge_ref?: { kind: "line" | "circle" | "other"; dir?: [number, number, number] };
  length?: number; position?: "inside" | "outside" | "bend_outside"; length_ref?: "outer" | "tangent"; inset?: [number, number]; gap?: number | null;
}

/** A manual feature that no longer rebuilds (kept in the tree, flagged for repair). */
export interface RepairItem { id: string; name: string; op: string; error: string }

export interface Project {
  id: string; name: string; description: string; template: string | null; created_at: string; updated_at: string;
  archived: boolean; builds: number; last_status: BuildStatus; thumbnail: string | null; created_by?: string | null;
  agent?: { busy: boolean; allowed: boolean; reason: string | null; cta: string | null; has_history: boolean };
  starter_prompt?: string | null;
  access?: import("./collab").Access; branch?: string; workspace?: string | null;
}

export interface Template { code: string; name: string; icon: string; prompt: string }

export interface AgentQuestion { id: string; question: string; options: string[]; multi: boolean; other: boolean; default: string | null }
/** CAD-028: the agent's reading of a new design, approved (and edited) by the user before anything is built. */
export interface AgentBrief { title: string | null; requirements: string[]; assumptions: string[]; questions: { question: string; default: string | null }[] }
/** AGT-006: the agent's structured self-review; `gates` comes from the checks, never from the agent. */
export interface AgentReview { items: { text: string; basis: string; kind: "observed" | "uncertain" | "overridden" }[]; gates: { ok: boolean | null; failed: string[]; build_id?: string | null } }

/** DS-035: a small edit the agent hands to the PropertyManager (validated and resolved on the server). */
export interface AgentEdit {
  op: "fillet" | "chamfer" | "shell" | "hole" | "params" | "extrude" | "pattern" | "multi"; summary: string; build_id?: string | number | null;
  feature_id: string | null; feature: Partial<ManualFeature> & Record<string, unknown> | null;
  targets: { kind: "edge" | "face"; picks: { id: number; point: [number, number, number] }[] } | null;
  params: Record<string, { from: number; to: number; label: string; unit: string }> | null;
  values: { size?: number; hole?: { type?: "simple" | "clearance" | "tapped" | "cbore" | "csk"; size?: number; d?: number; mode?: "corners"; dx?: number; dy?: number };
    /** extrude / cut depth edits */ distance?: number | null; end?: "blind" | "mid" | "through";
    /** pattern edits */ count?: number; spacing?: number; angle?: number };
  /** several edits proposed together: one PropertyManager step each, in order */
  steps?: AgentEdit[];
}

/** ASM-018: what a pending Studio change would do to the assemblies using the part (nothing committed). */
export interface ImpactAssembly {
  id: string; name: string; instances: number; behind: number; program?: string | null; error?: string;
  mates: { id: string; type: string; status: "breaks" | "follows"; text: string }[];
  moved: { id: string; name: string; mm: number; deg: number }[];
  refit: { id: string; name: string; why: string }[];
  clashes: { a: string; b: string; a_name: string; b_name: string; volume_mm3: number; was_mm3: number }[];
  resolved: { a_name: string; b_name: string; volume_mm3: number }[];
  breaks: number;
}
export interface Impact {
  assemblies: ImpactAssembly[]; headline: string; checked: boolean; issues?: number;
  programs: { id: string; name: string; tickets: string[] }[]; datasheet: { shots: number };
}
export type ImpactChange = { kind: "feature"; feature: Record<string, unknown> } | { kind: "edit"; id: string; feature: Record<string, unknown> } | { kind: "params"; values: Record<string, number> }
  | { kind: "suppress"; id: string; suppressed: boolean } | { kind: "delete"; id: string } | { kind: "reorder"; ids: string[] }
  | { kind: "design_suppress"; name: string; suppressed: boolean } | { kind: "design_delete"; name: string }
  | { kind: "sequence"; changes: ImpactChange[] };

export type AgentEvent =
  | { type: "hello"; busy: boolean; backlog?: number }
  | { type: "user"; text: string; t: number; mode?: "build" | "discuss" | "brief" }
  | { type: "text"; text: string; t: number }
  | { type: "system"; model: string; auth: string }
  | { type: "tool"; id: string; name: string; brief: string }
  | { type: "tool_result"; id: string; is_error: boolean; brief: string; revision?: number }
  | { type: "result"; mode?: "build" | "discuss"; subtype: string; turns: number | null; duration_s: number; cost_est_usd: number | null;
      auth: string | null; tokens_charged?: number; token_balance?: number; budget_stopped?: boolean; budget_tokens?: number | null }
  | { type: "meter"; tokens: number; budget_tokens: number | null }
  | { type: "error"; text: string }
  | { type: "busy"; value: boolean }
  | { type: "questions"; questions: AgentQuestion[] }
  | { type: "brief"; brief: AgentBrief }
  | ({ type: "review" } & AgentReview)
  | { type: "recognition"; component: string | null }
  | { type: "edit"; edit: AgentEdit; t?: number }
  | { type: "reset" };
