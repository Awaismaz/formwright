/** Pure Design Office helpers: formatting, board lanes, and the plan-review estimate preview.
 * The preview mirrors src/aicad/office/estimates.py exactly (same constants, sent by the server). */
import type { AgentState, Column, Constants, Family, Plan, Ticket, Item } from "./types";

export const COLUMN_STATE: Record<Column, AgentState> = {
  backlog: "idle", ready: "idle", in_design: "working", in_review: "review", changes_requested: "blocked",
  approved: "done", integrated: "done",
};

/** "45 s", "12 min", "1 h 05 min", "2 d 3 h" (agent working time). */
export function fmtMinutes(min: number): string {
  if (!Number.isFinite(min) || min <= 0) return "0 min";
  if (min < 1) return `${Math.max(1, Math.round(min * 60))} s`;
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60), m = Math.round(min - h * 60);
  if (h < 24) return m ? `${h} h ${String(m).padStart(2, "0")} min` : `${h} h`;
  const d = Math.floor(h / 24), hh = h - d * 24;
  return hh ? `${d} d ${hh} h` : `${d} d`;
}

/** An ETA range, never a single promise: "20–46 min", or "done" when nothing remains. */
export function fmtEta(e: { low_min: number; high_min: number } | null | undefined): string {
  if (!e) return "—";
  if (e.high_min <= 0) return "done";
  const lo = fmtMinutes(e.low_min), hi = fmtMinutes(e.high_min);
  if (lo === hi) return `≈ ${hi}`;
  const m = /^(\d+) min$/.exec(lo);
  return m && hi.endsWith(" min") && !hi.includes(" h ") ? `${m[1]}–${hi}` : `${lo}–${hi}`;
}

export function clampComplexity(c: number, k: Constants): number {
  return Math.max(k.complexity[0], Math.min(k.complexity[1], Math.round(Number.isFinite(c) ? c : 2)));
}

export function estimateMinutes(family: Family, complexity: number, k: Constants): number {
  const per = k.minutes_per_unit[family] ?? k.minutes_per_unit.machined;
  return Math.round(clampComplexity(complexity, k) * per * 10) / 10;
}

export function integrationComplexity(children: number, k: Constants): number {
  return clampComplexity(Math.max(1, Math.ceil(children / 3)), k);
}

/** What approving this plan creates: ticket count, total estimate, and the ETA range (nothing done yet). */
export function planPreview(plan: Plan, k: Constants, concurrency: number) {
  let total = 0, cpMax = 0, tickets = 0;
  for (const s of plan.subassemblies) {
    let sub = 0, longest = 0;
    for (const p of s.parts) {
      const est = p.family === "standard" ? estimateMinutes("standard", 1, k) : estimateMinutes(p.family, p.complexity, k);
      sub += est; longest = Math.max(longest, est); tickets += 1;
    }
    const integ = estimateMinutes("integration", integrationComplexity(s.parts.length, k), k);
    total += sub + integ; tickets += 1;
    cpMax = Math.max(cpMax, integ + longest);
  }
  const final = estimateMinutes("integration", integrationComplexity(plan.subassemblies.length, k), k);
  total += final; tickets += 1;
  const cp = final + cpMax;
  const n = Math.max(1, concurrency || k.default_concurrency);
  const [lf, hf] = k.eta_factors;
  return {
    tickets, estimate_min: Math.round(total * 10) / 10,
    eta: { low_min: Math.round(lf * Math.max(cp, total / n) * 10) / 10, high_min: Math.round(hf * (cp + total / n) * 10) / 10 },
  };
}

export interface Lane { item: Item | null; id: string; name: string; tickets: Ticket[] }

/** Swimlanes: one per sub-assembly (its parts + its integration ticket), then the program's final assembly. */
export function boardLanes(items: Item[], tickets: Ticket[]): Lane[] {
  const parent = new Map(items.map(i => [i.id, i.parent_id]));
  const laneOf = (itemId: string): string => {
    let cur: string | null | undefined = itemId;
    while (cur) {
      const p = parent.get(cur);
      if (p === "root" || p === null || p === undefined) return cur;
      cur = p;
    }
    return "root";
  };
  const subs = items.filter(i => i.kind === "subassembly" && i.parent_id === "root");
  const lanes: Lane[] = subs.map(s => ({ item: s, id: s.id, name: s.name, tickets: [] }));
  const root = items.find(i => i.id === "root") ?? null;
  const final: Lane = { item: root, id: "root", name: "Final assembly", tickets: [] };
  const byId = new Map(lanes.map(l => [l.id, l]));
  for (const t of tickets) (byId.get(laneOf(t.item_id)) ?? final).tickets.push(t);
  return final.tickets.length ? [...lanes, final] : lanes;
}

/** Can a card be dropped on a column? Dropping on its own column does nothing. */
export function canDrop(t: Ticket | undefined, column: Column): boolean {
  return !!t && t.column !== column;
}

/** Milestone weights the server would give after a column move (for an optimistic card update). */
export function progressAfterMove(t: Ticket, column: Column, k: Constants): number {
  const ms = new Set(t.milestones);
  if (column === "approved" || column === "integrated") ms.add("approved"); else ms.delete("approved");
  if (column === "changes_requested") ms.delete("self_review");
  return Math.max(0, ...k.milestones.filter(m => ms.has(m.code)).map(m => m.weight));
}
