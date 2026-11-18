import { describe, expect, it } from "vitest";
import { assignable, boardLanes, budgetTone, canDrop, estimateMinutes, fmtEta, fmtMinutes, orchestratorLabel, planPreview, progressAfterMove, recentHandoffs, runChip } from "./model";
import type { Constants, Item, Plan, Ticket } from "./types";

// Same numbers as src/aicad/office/estimates.py (the server sends them as `constants`).
const K: Constants = {
  minutes_per_unit: { machined: 4, turned: 3.5, gear: 4, sheet: 4.5, plastic: 5, standard: 0.5, integration: 3, drawings: 0.5, dfm: 0.5 },
  complexity: [1, 5], default_concurrency: 3, eta_factors: [0.8, 1.3],
  milestones: [{ code: "brief_read", label: "Brief read", weight: 5 }, { code: "first_build", label: "First build", weight: 35 },
    { code: "gates_pass", label: "Gating checks pass", weight: 70 }, { code: "self_review", label: "Self-review", weight: 85 },
    { code: "approved", label: "Approved", weight: 100 }],
};

describe("formatting", () => {
  it("formats agent minutes", () => {
    expect(fmtMinutes(0)).toBe("0 min");
    expect(fmtMinutes(0.5)).toBe("30 s");
    expect(fmtMinutes(12.4)).toBe("12 min");
    expect(fmtMinutes(65)).toBe("1 h 05 min");
    expect(fmtMinutes(120)).toBe("2 h");
    expect(fmtMinutes(60 * 27)).toBe("1 d 3 h");
  });
  it("formats ETA ranges", () => {
    expect(fmtEta({ low_min: 20, high_min: 45.7 })).toBe("20–46 min");
    expect(fmtEta({ low_min: 0, high_min: 0 })).toBe("done");
    expect(fmtEta(null)).toBe("—");
  });
});

describe("plan preview mirrors the server", () => {
  it("estimates per ticket", () => {
    expect(estimateMinutes("machined", 3, K)).toBe(12);
    expect(estimateMinutes("turned", 2, K)).toBe(7);
    expect(estimateMinutes("machined", 9, K)).toBe(20);
  });
  it("matches service.plan_estimate on the same plan", () => {
    const plan: Plan = { source: "standard", summary: "", assumptions: [], subassemblies: [
      { id: "s1", name: "A", description: "", parts: [
        { id: "p1", name: "Plate", family: "machined", complexity: 3, qty: 1, description: "" },
        { id: "p2", name: "Bolt", family: "standard", complexity: 1, qty: 4, description: "" }] },
      { id: "s2", name: "B", description: "", parts: [{ id: "p3", name: "Shaft", family: "turned", complexity: 2, qty: 1, description: "" }] },
    ] };
    // server: {'tickets': 6, 'estimate_min': 28.5, 'eta': {'low_min': 14.4, 'high_min': 35.8}}
    expect(planPreview(plan, K, 3)).toEqual({ tickets: 6, estimate_min: 28.5, eta: { low_min: 14.4, high_min: 35.8 } });
  });
});

const T = (id: string, item: string, extra: Partial<Ticket> = {}): Ticket => ({
  id, key: `X-${id}`, item_id: item, kind: "part", title: id, brief: "", family: "machined", specialist: "mill", complexity: 2,
  estimate_min: 8, qty: 1, column: "ready", milestones: [], progress: 0, project_id: null, assembly_id: null, depends_on: [],
  comments: [], checks: null, tokens: 0, agent_state: "idle", updated_at: "", ...extra,
});
const I = (id: string, parent: string | null, kind: Item["kind"]): Item => ({
  id, parent_id: parent, kind, name: id, rollup: { estimate_min: 0, done_min: 0, remaining_min: 0, progress: 0 }, eta: null,
});

describe("board", () => {
  it("puts tickets in sub-assembly swimlanes with the final assembly last", () => {
    const items = [I("root", null, "program"), I("S1", "root", "subassembly"), I("A", "S1", "part"), I("S2", "root", "subassembly"), I("C", "S2", "part")];
    const lanes = boardLanes(items, [T("tA", "A"), T("tS1", "S1"), T("tC", "C"), T("tR", "root")]);
    expect(lanes.map(l => [l.id, l.tickets.map(t => t.id)])).toEqual([["S1", ["tA", "tS1"]], ["S2", ["tC"]], ["root", ["tR"]]]);
  });
  it("derives progress after a move like the server", () => {
    const t = T("a", "A", { milestones: ["brief_read", "first_build", "self_review"], progress: 85 });
    expect(progressAfterMove(t, "approved", K)).toBe(100);
    expect(progressAfterMove(t, "changes_requested", K)).toBe(35);
    expect(progressAfterMove({ ...t, milestones: ["approved"] }, "in_review", K)).toBe(0);
    expect(canDrop(t, "ready")).toBe(false);
    expect(canDrop(t, "in_review")).toBe(true);
  });
});

describe("the running office (Phase 3)", () => {
  it("labels held-back tickets", () => {
    expect(runChip({ run_status: "waiting_capacity" })).toEqual({ label: "Waiting for capacity", tone: "warning" });
    expect(runChip({ run_status: "retry", run: { attempt: 2 } })?.label).toBe("Retry 2");
    expect(runChip({ run_status: "blocked" })?.tone).toBe("danger");
    expect(runChip({ run_status: "designing", paused: true })?.label).toBe("Paused");
    expect(runChip({ run_status: "manual" })?.label).toBe("You took over");
    expect(runChip({ run_status: "designing" })).toBeNull();
  });
  it("summarises the run state", () => {
    const base = { working: 2, waiting: 0, blocked: 1 };
    expect(orchestratorLabel(undefined, 3).label).toBe("Not running");
    expect(orchestratorLabel({ ...base, state: "running" }, 3).label).toBe("Running · 2 of 3 working · 1 needs you");
    expect(orchestratorLabel({ ...base, state: "running", capacity_until: Date.now() / 1000 + 60 }, 3).label).toBe("Waiting for capacity");
    expect(orchestratorLabel({ ...base, state: "stopped", reason: "budget" }, 3)).toEqual({ label: "Stopped: budget reached", tone: "danger" });
    expect(orchestratorLabel({ ...base, state: "paused" }, 3).label).toBe("Pausing · 2 finishing");
    expect(orchestratorLabel({ ...base, working: 0, state: "paused" }, 3).label).toBe("Paused");
  });
  it("tones the budget at 80 and 100 %", () => {
    expect(budgetTone(79, 100).tone).toBe("primary");
    expect(budgetTone(80, 100).tone).toBe("warning");
    expect(budgetTone(100, 100)).toEqual({ pct: 100, tone: "danger" });
    expect(budgetTone(5, 0).pct).toBe(0);
  });
  it("finds fresh hand-offs per ticket", () => {
    const now = Date.parse("2026-11-18T10:00:10Z");
    const ev = (seq: number, t: string, tid: string, from: string, to: string) => ({ seq, t, type: "ticket.handoff", program_id: "p", ticket_id: tid,
      actor: { kind: "agent" as const, name: from }, text: "", data: { from, to } });
    const m = recentHandoffs([ev(1, "2026-11-18T10:00:08Z", "t1", "mill", "gage"), ev(2, "2026-11-18T10:00:09Z", "t1", "gage", "fitz"),
      ev(3, "2026-11-18T09:59:00Z", "t2", "hex", "mill")], now);
    expect(m.get("t1")).toEqual({ from: "gage", to: "fitz", seq: 2 });
    expect(m.has("t2")).toBe(false);
  });
  it("never lets Gage design", () => {
    expect(assignable("part")).not.toContain("gage");
    expect(assignable("integration")).toEqual(["fitz"]);
  });
});
