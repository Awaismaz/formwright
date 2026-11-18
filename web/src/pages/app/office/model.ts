/** Pure Design Office helpers: formatting, board lanes, and the plan-review estimate preview.
 * The preview mirrors src/aicad/office/estimates.py exactly (same constants, sent by the server). */
import type { AgentState, ChangeRequest, Column, Constants, Family, Interface, Item, LiveInstance, OfficeEvent, Orchestrator, Plan, Ticket } from "./types";

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
  return Math.round(clampComplexity(complexity, k) * per * 100) / 100;
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

// ------------------------------------------------------------------ Phase 3: the running office
export type Tone = "neutral" | "primary" | "warning" | "danger" | "success";

/** A chip for a ticket the office is holding back (null when the card's avatar and line say enough). */
export function runChip(t: Pick<Ticket, "run_status" | "paused" | "taken_over" | "run">): { label: string; tone: Tone } | null {
  if (t.paused) return { label: "Paused", tone: "neutral" };
  if (t.taken_over || t.run_status === "manual") return { label: "You took over", tone: "primary" };
  switch (t.run_status) {
    case "waiting_capacity": return { label: "Waiting for capacity", tone: "warning" };
    case "retry": return { label: `Retry ${t.run?.attempt ?? 1}`, tone: "warning" };
    case "blocked": return { label: "Needs you", tone: "danger" };
    case "awaiting_review": return { label: "Your review", tone: "warning" };
    default: return null;
  }
}

/** The program's run state in one line: "Running · 3 working", "Stopped: budget reached", ... */
export function orchestratorLabel(o: Orchestrator | undefined, concurrency: number): { label: string; tone: Tone } {
  if (!o || o.state === "idle") return { label: "Not running", tone: "neutral" };
  switch (o.state) {
    case "running": {
      const waiting = (o.capacity_until ?? 0) * 1000 > Date.now();
      if (waiting) return { label: "Waiting for capacity", tone: "warning" };
      const bits = [`${o.working} of ${concurrency} working`];
      if (o.blocked) bits.push(`${o.blocked} need${o.blocked === 1 ? "s" : ""} you`);
      if (o.review) bits.push(`${o.review} waiting for your review`);
      return { label: `Running · ${bits.join(" · ")}`, tone: "primary" };
    }
    case "paused": return { label: o.working ? `Pausing · ${o.working} finishing` : "Paused", tone: "neutral" };
    case "stopped": return { label: o.reason === "balance" ? "Stopped: out of tokens" : "Stopped: budget reached", tone: "danger" };
    case "complete": return { label: "Complete", tone: "success" };
    default: return { label: o.state, tone: "neutral" };
  }
}

/** Budget meter tone: warn at 80 %, stop at 100 % (the server's CD-016 thresholds). */
export function budgetTone(spent: number, tokens: number): { pct: number; tone: "primary" | "warning" | "danger" } {
  const pct = tokens > 0 ? (100 * spent) / tokens : 0;
  return { pct, tone: pct >= 100 ? "danger" : pct >= 80 ? "warning" : "primary" };
}

export interface Handoff { from: string; to: string; seq: number }

/** The latest hand-off per ticket from the live events, for the avatar slide (only fresh ones animate). */
export function recentHandoffs(events: OfficeEvent[], now: number, windowMs = 4000): Map<string, Handoff> {
  const out = new Map<string, Handoff>();
  for (const e of events) {
    if (e.type !== "ticket.handoff" || !e.ticket_id) continue;
    if (now - Date.parse(e.t) > windowMs) continue;
    const d = e.data as { from?: string; to?: string };
    const cur = out.get(e.ticket_id);
    if (d.from && d.to && (!cur || cur.seq < e.seq)) out.set(e.ticket_id, { from: d.from, to: d.to, seq: e.seq });
  }
  return out;
}

/** Which specialists a ticket may be given (Gage never designs: no self-approval; Fitz only assembles). */
export function assignable(kind: Ticket["kind"], deliverable?: Ticket["deliverable"]): string[] {
  if (kind === "deliverable") return [deliverable === "dfm" ? "smithy" : "ortho"];
  return kind === "integration" ? ["fitz"] : ["mill", "chuck", "axel", "benny", "molly", "hex"];
}


// ------------------------------------------------------------------ Phase 4: interfaces and the live assembly
const n = (v: unknown) => (typeof v === "number" ? (Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000)) : String(v ?? "—"));

/** The program axis an interface runs along (Phase 6: gearbox shafts along Y); "z" when not stated. */
export function ifaceAxis(data: Record<string, unknown>): "x" | "y" | "z" {
  const a = data?.ax;
  return a === "x" || a === "y" ? a : "z";
}

/** A field label written for Z interfaces, re-worded for an interface along X or Y: "(X, Y)" -> "(X, Z)",
 *  "Along Z" / "face Z" -> "Along Y" / "face Y". */
export function axisLabel(label: string, ax: "x" | "y" | "z"): string {
  if (ax === "z") return label;
  const across = ax === "y" ? "(X, Z)" : "(Y, Z)";
  return label.replace("(X, Y)", across).replace(/\bZ\b(?![,)])/g, ax.toUpperCase());
}

/** A skeleton axis in words: "at (X, Y) (-54, 0)" for a vertical shaft, "along Y at (X, Z) (-54, -62)" for a
 *  gearbox shaft in the side walls. */
export function axisChip(origin: number[], dir: number[]): string {
  const k = [0, 1, 2].reduce((b, i) => (Math.abs(dir[i] ?? 0) > Math.abs(dir[b] ?? 0) ? i : b), 2);
  const [i, j, names] = k === 2 ? [0, 1, "(X, Y)"] as const : k === 1 ? [0, 2, "(X, Z)"] as const : [1, 2, "(Y, Z)"] as const;
  return `${k === 2 ? "" : `along ${"XYZ"[k]} `}at ${names} (${n(origin[i])}, ${n(origin[j])})`;
}

/** The interface's key numbers in one line, as an engineer reads them. */
export function ifaceSummary(f: Pick<Interface, "kind" | "data">): string {
  const d = f.data as Record<string, number & string & number[]>;
  const A = ifaceAxis(f.data as Record<string, unknown>).toUpperCase();
  const tapped = (f.data as { tapped?: { thread: string } }).tapped;
  switch (f.kind) {
    case "hole_pattern":
      return `${d.count} × Ø${n(d.d)} (${d.fastener})` + (d.pattern === "circular" ? ` on PCD ${n(d.pcd)}` : "")
        + (tapped ? ` · tapped ${tapped.thread} in the housing` : "") + ` · face ${A} ${n(d.plane_z)}`;
    case "shaft_bore": return `Ø${n(d.d)} ${d.fit} · ${n(d.length)} long`;
    case "face": return `plane ${A} ${n(d.plane_z)} · flatness ${n(d.flatness)}`;
    case "gear_mesh": return `m${n(d.module)} · ${d.teeth_a} / ${d.teeth_b} teeth · a = ${n(d.centre_distance)}`;
    case "bearing_seat": return `${d.count} × ${d.designation} · seat Ø${n(d.D)} ${d.housing_fit} × ${n(d.B)} · journal Ø${n(d.d)} ${d.shaft_fit}`
      + (A !== "Z" ? ` · shaft along ${A} (side walls)` : "");
    case "key": return `key ${n(d.b)} × ${n(d.h)} × ${n(d.length)} (DIN 6885) · shaft ${n(d.t1)} / hub ${n(d.t2)} deep`;
    case "dowel": return `${d.count} × Ø${n(d.d)} × ${n(d.length)} (ISO 8734) · holes ${String(d.fit).split("/")[0]}`;
    default: return "";
  }
}

export type SideStatus = "pass" | "fail" | "pending";
/** One side of an interface: measured on the real part (pass / fail) or not built yet (pending). */
export function sideStatus(check: { ok: boolean } | null | undefined): SideStatus {
  return !check ? "pending" : check.ok ? "pass" : "fail";
}

/** An interface is conforming when both sides were measured and passed. */
export function ifaceStatus(f: Pick<Interface, "sides">): SideStatus {
  const a = sideStatus(f.sides.a.check), b = sideStatus(f.sides.b.check);
  if (a === "fail" || b === "fail") return "fail";
  return a === "pass" && b === "pass" ? "pass" : "pending";
}

/** Human labels for the editable numbers of an interface. */
export const FIELD_LABEL: Record<string, string> = {
  fastener: "Fastener", d: "Diameter Ø (mm)", count: "Holes", inset: "Edge distance (mm)", flatness: "Flatness (mm)",
  position_tol: "Position tolerance ± (mm)", fit: "Fit (ISO 286)", module: "Module", teeth_a: "Teeth (first gear)",
  teeth_b: "Teeth (second gear)", designation: "Bearing (60xx / 62xx)", housing_fit: "Housing fit (ISO 286)",
  length: "Key length (mm)",
};

/** The current value of an editable field (the fastener is stored as "M6"). */
export function fieldValue(f: Pick<Interface, "data">, k: string): string {
  const v = (f.data as Record<string, unknown>)[k];
  return v === undefined || v === null ? "" : String(v);
}

/** Values the user changed (only fields whose text differs; numbers parsed, fastener / fit kept as text). */
export function changedValues(f: Pick<Interface, "data" | "editable">, form: Record<string, string>): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const k of f.editable) {
    const v = (form[k] ?? "").trim();
    if (v === "" || v === fieldValue(f, k)) continue;
    out[k] = k === "fit" || k === "fastener" || k === "housing_fit" ? v : Number(v);
  }
  return out;
}

export function crTone(s: ChangeRequest["status"]): Tone {
  return s === "accepted" ? "success" : s === "rejected" ? "danger" : "warning";
}

/** "Ø 6.6 → 7" lines of a change request. */
export function crDelta(c: Pick<ChangeRequest, "values" | "before">): string {
  return Object.entries(c.values).map(([k, v]) => `${FIELD_LABEL[k]?.replace(/ \(.*\)$/, "") ?? k} ${n(c.before[k])} → ${n(v)}`).join(", ");
}

/** Instances that just turned from a placeholder into the real part (for the "fitted" animation). */
export function swappedIn(prev: Map<string, LiveInstance["kind"]>, next: LiveInstance[]): string[] {
  return next.filter(i => prev.get(i.id) === "placeholder" && i.kind === "real").map(i => i.id);
}

/** Counts for the live assembly legend. */
export function liveCounts(insts: LiveInstance[]): { placeholders: number; real: number; standard: number } {
  let placeholders = 0, real = 0, standard = 0;
  for (const i of insts) {
    if (i.bin || i.fastener || i.kind === "toolbox") standard += 1; else if (i.kind === "placeholder") placeholders += 1; else real += 1;
  }
  return { placeholders, real, standard };
}
