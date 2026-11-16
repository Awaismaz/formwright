export type Role = "owner" | "admin" | "engineer" | "viewer";

export interface User {
  id: string; email: string; name: string; email_verified: boolean; is_superadmin: boolean;
  onboarding: Record<string, unknown>; onboarding_completed: boolean; tour_completed: boolean;
  preferences: { units?: "mm" | "in"; theme?: "light" | "dark" | "system"; notifications_email?: boolean };
  created_at: string;
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
  code: string; kind: "plan" | "addon" | "topup"; name: string; tagline: string; description: string;
  price_cents: number; interval: "month" | "year" | null; tokens: number; seats: number; modules: string[];
  features: string[]; highlight: boolean; contact_sales: boolean; purchasable: boolean; active: boolean; sort: number;
}

export interface Module {
  code: string; name: string; status: "live" | "preview"; icon: string; summary: string; bullets: string[];
}

export interface Catalog {
  plans: Product[]; addons: Product[]; topups: Product[]; modules: Module[];
  token_costs: Record<string, number>; stripe_mode: string;
}

export interface CheckResult { id: string; name: string; passed: boolean; gating: boolean; detail: Record<string, unknown> }

export interface BuildStatus {
  ok?: boolean; part?: string; material?: string; error?: string; build_id?: number;
  fingerprint?: { volume: number; bbox: number[]; faces: number; edges: number; solids: number };
  params?: Record<string, unknown>; checks?: CheckResult[]; expected?: Record<string, unknown>;
  timings_s?: Record<string, number>; traceback?: string;
  param_meta?: Record<string, { min?: number; max?: number; step?: number; unit?: string; group?: string; label?: string; help?: string }>;
  mass?: { volume_mm3: number; area_mm2: number; com_mm: [number, number, number]; inertia_com_mm5: number[][]; principal_mm5: number[] };
  features?: { name: string; kind: string; params: Record<string, unknown> }[];
  manual_features?: number;
}

export interface ManualFeature {
  id: string; op: "fillet" | "chamfer" | "hole" | "extrude" | "shell" | "mirror" | "sketch" | "revolve" | "pattern"; name: string; suppressed: boolean;
  end?: "blind" | "mid" | "through"; reverse?: boolean;
  axis?: { a: [number, number]; b: [number, number] } | { origin: [number, number, number]; dir: [number, number, number] }; angle?: number;
  source?: string[]; kind?: "linear" | "circular";
  faces?: { point: [number, number, number]; normal: [number, number, number] }[]; t?: number;
  pattern?: "circular"; center?: [number, number, number];
  edges?: [number, number, number][]; r?: number; d?: number;
  point?: [number, number, number]; normal?: [number, number, number]; depth?: number | null; count?: number; step?: [number, number, number];
  plane?: { origin: [number, number, number]; normal: [number, number, number]; x_dir?: [number, number, number] };
  sketch?: { kind: "rect" | "circle" | "poly"; w?: number; h?: number; r?: number; cx?: number; cy?: number };
  distance?: number; mode?: "add" | "cut";
  profiles?: unknown[]; editor?: unknown;
}

export interface Project {
  id: string; name: string; description: string; template: string | null; created_at: string; updated_at: string;
  archived: boolean; builds: number; last_status: BuildStatus; thumbnail: string | null; created_by?: string | null;
  agent?: { busy: boolean; allowed: boolean; reason: string | null; cta: string | null; has_history: boolean };
  starter_prompt?: string | null;
}

export interface Template { code: string; name: string; icon: string; prompt: string }

export interface AgentQuestion { id: string; question: string; options: string[]; multi: boolean; other: boolean; default: string | null }

export type AgentEvent =
  | { type: "hello"; busy: boolean }
  | { type: "user"; text: string; t: number }
  | { type: "text"; text: string; t: number }
  | { type: "system"; model: string; auth: string }
  | { type: "tool"; id: string; name: string; brief: string }
  | { type: "tool_result"; id: string; is_error: boolean; brief: string; revision?: number }
  | { type: "result"; subtype: string; turns: number; duration_s: number; cost_est_usd: number | null;
      auth: string | null; tokens_charged?: number; token_balance?: number }
  | { type: "error"; text: string }
  | { type: "busy"; value: boolean }
  | { type: "questions"; questions: AgentQuestion[] }
  | { type: "recognition"; component: string | null }
  | { type: "reset" };
