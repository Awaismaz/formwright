import { describe, expect, it } from "vitest";
import type { AgentEdit, ManualFeature } from "@/lib/types";
import type { Topo } from "@/viewer/types";
import { impactChange, prefillPm, targetPicks } from "./agentEdit";

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
