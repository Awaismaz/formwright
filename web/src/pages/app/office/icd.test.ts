import { describe, expect, it } from "vitest";
import { axisChip, axisLabel, changedValues, crDelta, crTone, ifaceAxis, ifaceStatus, ifaceSummary, liveCounts, sideStatus, swappedIn } from "./model";
import type { Interface, LiveInstance } from "./types";

// The hand-checked bolted joint of tests/test_office_icd.py (IF-01: bracket on the base plate).
const joint = {
  kind: "hole_pattern" as const, editable: ["fastener", "d", "count", "inset", "flatness", "position_tol"],
  data: { fastener: "M6", count: 4, d: 6.6, pattern: "grid", inset: 13.2, plane_z: 0, flatness: 0.05, position_tol: 0.1 },
};

describe("interface summaries", () => {
  it("reads like the ICD table", () => {
    expect(ifaceSummary(joint)).toBe("4 × Ø6.6 (M6) · face Z 0");
    expect(ifaceSummary({ kind: "hole_pattern", data: { ...joint.data, pattern: "circular", pcd: 13, count: 3, d: 3.4, fastener: "M3" } }))
      .toBe("3 × Ø3.4 (M3) on PCD 13 · face Z 0");
    expect(ifaceSummary({ kind: "shaft_bore", data: { d: 20, fit: "H7/h6", length: 28 } })).toBe("Ø20 H7/h6 · 28 long");
    expect(ifaceSummary({ kind: "gear_mesh", data: { module: 2, teeth_a: 18, teeth_b: 54, centre_distance: 72 } }))
      .toBe("m2 · 18 / 54 teeth · a = 72");
  });
});

describe("conformance status", () => {
  const side = (check: { ok: boolean } | null) => ({ check }) as unknown as Interface["sides"]["a"];
  it("passes only when both sides were measured and passed", () => {
    expect(sideStatus(null)).toBe("pending");
    expect(sideStatus({ ok: false })).toBe("fail");
    expect(ifaceStatus({ sides: { a: side({ ok: true }), b: side({ ok: true }) } })).toBe("pass");
    expect(ifaceStatus({ sides: { a: side({ ok: true }), b: side(null) } })).toBe("pending");
    expect(ifaceStatus({ sides: { a: side(null), b: side({ ok: false }) } })).toBe("fail");
  });
});

describe("edits and change requests", () => {
  it("sends only the numbers that changed", () => {
    const form = { fastener: "M6", d: "7", count: "4", inset: "13.2", flatness: "0.05", position_tol: "" };
    expect(changedValues(joint, form)).toEqual({ d: 7 });
    expect(changedValues(joint, { ...form, fastener: "M8", d: "6.6" })).toEqual({ fastener: "M8" });
    expect(changedValues(joint, { ...form, d: "6.6" })).toEqual({});
  });
  it("describes a change request and its state", () => {
    expect(crDelta({ values: { d: 7 }, before: { d: 6.6 } })).toBe("Diameter Ø 6.6 → 7");
    expect(crTone("accepted")).toBe("success");
    expect(crTone("rejected")).toBe("danger");
    expect(crTone("open")).toBe("warning");
  });
});

describe("live assembly", () => {
  const inst = (id: string, kind: LiveInstance["kind"], extra: Partial<LiveInstance> = {}): LiveInstance =>
    ({ id, name: id, part: `k_${id}`, T: [], item: id, copy: 0, kind, fastener: false, bin: false, sub: null, ...extra });
  it("finds the parts that just replaced their placeholder", () => {
    const prev = new Map<string, LiveInstance["kind"]>([["i1", "placeholder"], ["i2", "placeholder"], ["i3", "real"]]);
    expect(swappedIn(prev, [inst("i1", "real"), inst("i2", "placeholder"), inst("i3", "real"), inst("i4", "real")])).toEqual(["i1"]);
    expect(swappedIn(new Map(), [inst("i1", "real")])).toEqual([]);  // first load: nothing animates
  });
  it("counts placeholders, real parts and standard parts", () => {
    expect(liveCounts([inst("a", "placeholder"), inst("b", "real"), inst("c", "toolbox", { fastener: true }), inst("d", "toolbox", { bin: true })]))
      .toEqual({ placeholders: 1, real: 1, standard: 2 });
  });
});

describe("interfaces along Y (Phase 6 gearbox layout)", () => {
  it("re-words Z labels for a shaft along Y", () => {
    expect(axisLabel("Axis (X, Y)", "y")).toBe("Axis (X, Z)");
    expect(axisLabel("Along Z", "y")).toBe("Along Y");
    expect(axisLabel("Mounting face Z", "y")).toBe("Mounting face Y");
    expect(axisLabel("Positions (X, Y)", "x")).toBe("Positions (Y, Z)");
    expect(axisLabel("Along Z", "z")).toBe("Along Z");
  });
  it("summarises a tapped cap joint on a side wall", () => {
    const f = { kind: "hole_pattern" as const, data: { count: 4, d: 4.5, fastener: "M4", pattern: "circular", pcd: 58.5, ax: "y",
      plane_z: -41, tapped: { d: 3.3, depth: 13, thread: "M4" } } };
    expect(ifaceAxis(f.data)).toBe("y");
    expect(ifaceSummary(f as never)).toBe("4 × Ø4.5 (M4) on PCD 58.5 · tapped M4 in the housing · face Y -41");
  });
});

describe("skeleton axis chips", () => {
  it("names the axis direction for gearbox shafts", () => {
    expect(axisChip([-54, 0, 0], [0, 0, 1])).toBe("at (X, Y) (-54, 0)");
    expect(axisChip([-54, 0, -62], [0, 1, 0])).toBe("along Y at (X, Z) (-54, -62)");
  });
});
