/** Projects that hold related parts, the "agent knows" view of a part, and personal design memory. */
import type { Project } from "./types";

export interface ProjectRef { id: string; name: string }

export interface DesignProjectSummary {
  id: string; name: string; purpose: string; archived: boolean; program_id: string | null;
  parts: number; hidden_parts: number; thumbnails: (string | null)[]; can_edit: boolean;
  updated_at: string; created_at: string;
}

export interface PartFacts { size: number[] | null; material: string | null; revision: number | null; interfaces: string[]; built: boolean }

export interface Decision {
  id: string; text: string; category: string; source: "manual" | "chat" | "memory" | "program"; source_label: string;
  status: "active" | "dismissed"; created_by: string | null; created_at: string;
}

export interface ActivityItem {
  kind: "revision" | "decision"; at: string; what: string; by?: string | null; source?: string | null;
  part?: ProjectRef; revision?: number; status?: string;
}

export interface DesignProjectDetail extends DesignProjectSummary {
  notes: string; created_by: string | null; items: (Project & { facts: PartFacts })[]; decisions: Decision[];
  program: ProjectRef | null; activity: ActivityItem[]; can_delete: boolean;
}

export interface AgentContextView {
  project: ProjectRef | null; parts: { id: string; name: string; summary: string }[]; decisions: string[];
  preferences: string[]; in_use: boolean; learning: boolean; use: boolean;
}

export interface MemoryFact {
  id: string; kind: string; text: string; source: string; evidence: number; confidence: number;
  origin: "learned" | "said" | "user"; pinned: boolean; updated_at: string; used?: boolean;
}

export interface MemoryState {
  learning: boolean; use: boolean; workspace: string; facts: MemoryFact[]; observations: number;
  limits: { facts_used: number; observations_kept: number };
}

export const ORIGIN_LABEL: Record<MemoryFact["origin"], string> = { learned: "Learned", said: "You said", user: "Yours" };

/** "3 of 4" style confidence words (no percentages that suggest more precision than counting has). */
export function strength(f: MemoryFact): string {
  if (f.origin !== "learned") return f.pinned ? "Pinned" : "";
  if (f.confidence >= 0.85) return "Strong";
  if (f.confidence >= 0.6) return "Likely";
  return "Emerging";
}
