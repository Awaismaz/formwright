import { describe, expect, it } from "vitest";
import type { AgentEdit, ManualFeature } from "@/lib/types";
import type { Topo } from "@/viewer/types";
import { agentSteps, impactChange, prefillPm, targetPicks, treeChange } from "./agentEdit";

/** A 60 × 40 × 10 box: two top edges (y = ±20 at z = 10) and the top face, enough for the mapping. */
const topo = {
  units: "mm", up: "Z", bbox: [-30, -20, 0, 30, 20, 10], solids: [], vertices: [],
  faces: [
    { id: 0, solid: 0, type: "plane", area: 2400, center: [0, 0, 10], normal: [0, 0, 1], pos: [], idx: [], edges: [0, 1] },
    { id: 1, solid: 0, type: "plane", area: 2400, center: [0, 0, 0], normal: [0, 0, -1], pos: [], idx: [], edges: [] },
  ],
  edges: [
    { id: 0, type: "line", length: 60, pts: [-30, -20, 10, 30, -20, 10], faces: [0], verts: [] },
    { id: 1, type: "line", length: 60, pts: [-30, 20, 10, 30, 20, 10], faces: [0], verts: [] },
  ],
} as unknown as Topo;

const chamfer: AgentEdit = {
  op: "chamfer", summary: "Chamfer the top edges 2 mm", build_id: "b1", feature_id: null, params: null, values: { size: 2 },
  feature: { op: "chamfer", name: "Chamfer", d: 2, edges: [[0, -20, 10], [0, 20, 10]] },
  targets: { kind: "edge", picks: [{ id: 0, point: [0, -20, 10] }, { id: 1, point: [0, 20, 10] }] },
};

describe("agent edit → PropertyManager (DS-035)", () => {
  it("opens a new chamfer with the size preset and the edges selected", () => {
    const r = prefillPm(chamfer, topo, [], "b1");
    expect(r).toEqual({ kind: "feature", op: "chamfer", editing: null, preset: { size: 2 }, note: undefined,
      selection: [{ kind: "edge", id: 0, point: [0, -20, 10] }, { kind: "edge", id: 1, point: [0, 20, 10] }] });
  });
  it("re-finds the targets by position when the model was rebuilt (ids renumbered)", () => {
    const moved = { ...chamfer, build_id: "old", targets: { kind: "edge" as const, picks: [{ id: 7, point: [0, 20, 10] as [number, number, number] }, { id: 8, point: [0, 99, 10] as [number, number, number] }] } };
    const { picks, lost } = targetPicks(moved, topo, "b2");
    expect(picks).toEqual([{ kind: "edge", id: 1, point: [0, 20, 10] }]);
    expect(lost).toBe(1);
    const r = prefillPm(moved, topo, [], "b2");
    expect(r.kind === "feature" && r.note).toMatch(/1 edge could not be found/);
  });
  it("edits an existing hand-made feature with the new value merged in", () => {
    const f: ManualFeature = { id: "f1", op: "fillet", name: "Top fillet", suppressed: false, r: 1, edges: [[0, -20, 10]] };
    const e: AgentEdit = { op: "fillet", summary: "Edit Fillet R3", feature_id: "f1", feature: { ...f, r: 3 }, targets: null, params: null, values: { size: 3 } };
    const r = prefillPm(e, topo, [f], "b1");
    expect(r).toMatchObject({ kind: "feature", op: "fillet", editing: { id: "f1", r: 3, edges: [[0, -20, 10]] }, selection: [] });
    expect(prefillPm(e, topo, [], "b1")).toEqual({ kind: "error", message: "That feature is no longer in the feature tree" });
    const h: ManualFeature = { id: "h1", op: "hole", name: "M6 Clearance Hole", suppressed: false, d: 6.6, spec: { type: "clearance", size: 6, fit: "medium" } };
    const he: AgentEdit = { op: "hole", summary: "", feature_id: "h1", feature: {}, targets: null, params: null, values: { hole: { type: "clearance", size: 8 } } };
    expect(prefillPm(he, topo, [h])).toMatchObject({ editing: { spec: { type: "clearance", size: 8, fit: "medium" } } });
  });
  it("hands parameter changes to the parameter PropertyManager and builds impact requests", () => {
    const p: AgentEdit = { op: "params", summary: "Change Thickness to 12 mm", feature_id: null, feature: null, targets: null, values: {},
      params: { T: { from: 10, to: 12, label: "Thickness", unit: "mm" } } };
    expect(prefillPm(p, topo, [])).toEqual({ kind: "params", rows: p.params });
    expect(impactChange(p)).toEqual({ kind: "params", values: { T: 12 } });
    expect(impactChange(chamfer)).toEqual({ kind: "feature", feature: chamfer.feature });
    expect(impactChange({ ...chamfer, feature_id: "f9" })).toEqual({ kind: "edit", id: "f9", feature: chamfer.feature });
  });
});

describe("agent edit follow-ups: depths, patterns, several steps; tree impact", () => {
  const pocket: ManualFeature = { id: "c1", op: "sketch", name: "Pocket", suppressed: false, mode: "cut", end: "blind", distance: 3,
    plane: { origin: [0, 0, 10], normal: [0, 0, 1] }, profiles: [] };
  const lpat: ManualFeature = { id: "p1", op: "pattern", name: "LPattern1", suppressed: false, source: ["c1"], count: 3, kind: "linear", step: [0, 15, 0] };
  const cpat: ManualFeature = { id: "p2", op: "pattern", name: "CirPattern1", suppressed: false, source: ["c1"], count: 6, kind: "circular", angle: 360 };
  const holes: ManualFeature = { id: "h1", op: "hole", name: "Holes", suppressed: false, d: 4, count: 2, step: [3, 4, 0] };
  const depth: AgentEdit = { op: "extrude", summary: "Cut depth of “Pocket” to 5 mm", feature_id: "c1", feature: { ...pocket, distance: 5 },
    targets: null, params: null, values: { distance: 5, end: "blind" } };
  const count: AgentEdit = { op: "pattern", summary: "“LPattern1”: 4 instances, spacing 12 mm", feature_id: "p1", feature: { ...lpat, count: 4, step: [0, 12, 0] },
    targets: null, params: null, values: { count: 4, spacing: 12 } };

  it("opens the extrude's own panel with the new depth (sketch editor for a sketched cut)", () => {
    expect(prefillPm(depth, topo, [pocket])).toEqual({ kind: "feature", op: "sketch", editing: { ...pocket, distance: 5, end: "blind" }, preset: {}, selection: [] });
    const through: AgentEdit = { ...depth, values: { distance: null, end: "through" } };
    expect(prefillPm(through, topo, [pocket])).toMatchObject({ editing: { end: "through", distance: 3 } });
    expect(prefillPm(depth, topo, [])).toEqual({ kind: "error", message: "That feature is no longer in the feature tree" });
  });
  it("scales a pattern's step to the new spacing along the same direction, and sets count / total angle", () => {
    expect(prefillPm(count, topo, [lpat])).toMatchObject({ kind: "feature", op: "pattern", editing: { id: "p1", count: 4, step: [0, 12, 0], source: ["c1"] } });
    const hs: AgentEdit = { ...count, feature_id: "h1", values: { spacing: 10 } };
    expect(prefillPm(hs, topo, [holes])).toMatchObject({ op: "hole", editing: { count: 2, step: [6, 8, 0] } });  // |(3,4)| = 5 -> 10
    const ang: AgentEdit = { ...count, feature_id: "p2", values: { angle: 180, count: 4 } };
    expect(prefillPm(ang, topo, [cpat])).toMatchObject({ editing: { angle: 180, count: 4, kind: "circular" } });
  });
  it("splits a multi-step edit into PropertyManager steps and previews their impact as one sequence", () => {
    const multi: AgentEdit = { op: "multi", summary: "Deeper pockets, four of them", feature_id: null, feature: null, targets: null, params: null, values: {},
      steps: [depth, count, chamfer] };
    expect(agentSteps(multi)).toEqual([depth, count, chamfer]);
    expect(agentSteps(chamfer)).toEqual([chamfer]);
    expect(prefillPm(multi, topo, [pocket, lpat], "b1")).toEqual(prefillPm(depth, topo, [pocket, lpat], "b1"));  // step 1 opens first
    expect(impactChange(multi)).toEqual({ kind: "sequence", changes: [
      { kind: "edit", id: "c1", feature: depth.feature }, { kind: "edit", id: "p1", feature: count.feature }, { kind: "feature", feature: chamfer.feature }] });
    expect(impactChange({ ...multi, steps: [] })).toBeNull();
  });
  it("maps tree actions and typed commands to impact requests", () => {
    expect(treeChange({ kind: "toggle", feature: lpat })).toEqual({ kind: "suppress", id: "p1", suppressed: true });
    expect(treeChange({ kind: "toggle", feature: { ...lpat, suppressed: true } })).toEqual({ kind: "suppress", id: "p1", suppressed: false });
    expect(treeChange({ kind: "delete", feature: pocket })).toEqual({ kind: "delete", id: "c1" });
    expect(treeChange({ kind: "move", ids: ["c1", "p1", "h1"], id: "h1", by: -1 })).toEqual({ kind: "reorder", ids: ["c1", "h1", "p1"] });
    expect(treeChange({ kind: "move", ids: ["c1", "p1"], id: "c1", by: -1 })).toBeNull();  // already first
    expect(treeChange({ kind: "design_suppress", name: "Boss", suppressed: true })).toEqual({ kind: "design_suppress", name: "Boss", suppressed: true });
    expect(treeChange({ kind: "design_delete", name: "Boss" })).toEqual({ kind: "design_delete", name: "Boss" });
  });
});
