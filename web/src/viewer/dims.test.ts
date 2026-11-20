import { describe, expect, it } from "vitest";
import { checkEdit, chooseOffsetDir, dimFaces, dimText, extreme, layout, layoutLinear, levels, perpBasis, placeLabels, resolveDims, viewKey, type DimSpec, type ViewCam } from "./dims";
import type { Topo, TopoEdge, TopoFace, V3 } from "./types";

// An 80 x 50 x 20 block (x -40..40, y -25..25, z 0..20) with one Ø6.6 hole along Z at (20, 0): enough topology for
// a length and a diameter. Plane faces carry their corner points as tessellation, like topo.json.
const plane = (id: number, normal: V3, pts: V3[]): TopoFace => ({
  id, solid: 0, type: "plane", area: 1, normal, center: pts.reduce((a, p) => [a[0] + p[0] / pts.length, a[1] + p[1] / pts.length, a[2] + p[2] / pts.length], [0, 0, 0] as V3),
  pos: pts.flat(), idx: [], edges: [],
});
const circle = (id: number, z: number): TopoEdge => ({ id, type: "circle", length: 0, pts: [], faces: [2], verts: [], center: [20, 0, z], radius: 3.3, axis: [0, 0, 1], full: true });
const topo: Topo = {
  units: "mm", up: "Z", bbox: [-40, -25, 0, 40, 25, 20], solids: [], vertices: [],
  faces: [
    plane(0, [-1, 0, 0], [[-40, -25, 0], [-40, 25, 0], [-40, 25, 20], [-40, -25, 20]]),
    plane(1, [1, 0, 0], [[40, -25, 0], [40, 25, 0], [40, 25, 20], [40, -25, 20]]),
    { id: 2, solid: 0, type: "cylinder", area: 1, center: [20, 0, 10], axis: [0, 0, 1], axis_point: [20, 0, -1], radius: 3.3, pos: [], idx: [], edges: [0, 1] },
  ],
  edges: [circle(0, 0), circle(1, 20)],
};
const L: DimSpec = { param: "L", kind: "linear", a: { face: 0, ref: "plane" }, b: { face: 1, ref: "plane" }, u: [1, 0, 0], s: 80 };
const D: DimSpec = { param: "D", kind: "diameter", faces: [2], count: 4 };

/** Orthographic Front view (looking along +Y), 2 px per mm, model origin at the screen centre. */
const front: ViewCam = { project: p => [400 + p[0] * 2, 300 - p[2] * 2], vd: [0, -1, 0], right: [1, 0, 0], up: [0, 0, 1], pxPerMm: 2, width: 800, height: 600 };

describe("resolveDims", () => {
  it("measures a length between two parallel faces and keeps it only while it equals the value", () => {
    const [r] = resolveDims([L], topo, { L: 80 });
    expect(r).toMatchObject({ kind: "linear", s: 80, faces: [0, 1] });
    expect(resolveDims([L], topo, { L: 81 })).toEqual([]); // a stale mapping never shows a wrong number
    expect(resolveDims([{ ...L, b: { face: 2, ref: "plane" } }], topo, { L: 80 })).toEqual([]); // not a plane any more
  });
  it("puts a diameter on the hole's circles and counts the pattern", () => {
    const [r] = resolveDims([D], topo, { D: 6.6 });
    expect(r).toMatchObject({ kind: "round", sym: "Ø", count: 4 });
    expect(r!.kind === "round" && r!.circles.map(c => c.c[2])).toEqual([0, 20]);
    expect(dimText(r!, 6.6, "mm")).toBe("4× Ø6.6");
    expect(resolveDims([D], topo, { D: 7 })).toEqual([]);
  });
  it("highlights the measured faces, else the faces a parameter moves", () => {
    expect(dimFaces(L)).toEqual([0, 1]);
    expect(dimFaces({ param: "CH", kind: "none", driven: [4, 5] })).toEqual([4, 5]);
  });
});

describe("dimension layout", () => {
  it("offsets along world axes perpendicular to the measured direction", () => {
    const [a, b] = perpBasis([1, 0, 0]);
    expect(Math.abs(a[0]) + Math.abs(b[0])).toBeCloseTo(0);
    expect([a, b].map(v => Math.hypot(...v))).toEqual([1, 1]);
  });
  it("draws a length on the visible side, above the part in the Front view", () => {
    const [r] = resolveDims([L], topo, { L: 80 });
    const w = chooseOffsetDir(r!.kind === "linear" ? r!.u : [1, 0, 0], (r as { A: number[] }).A, (r as { B: number[] }).B, topo.bbox, front.vd, front.up, front.right);
    expect(w.map(c => Math.round(c) + 0)).toEqual([0, 0, 1]); // ±Y point at the camera; up wins over down
  });
  it("puts extension lines, the dimension line and arrows at a fixed screen gap beyond the faces", () => {
    const [r] = resolveDims([L], topo, { L: 80 });
    const d = layoutLinear(r as Extract<typeof r, { kind: "linear" }>, [0, 0, 1], 0, front, "80")!;
    // top of the faces z = 20 -> y = 260; the line sits 22 px above: y = 238, from x = 320 to 480
    const line = d.lines[2]!;
    expect([line.x1, line.y1, line.x2, line.y2]).toEqual([320, 238, 480, 238]);
    expect(d.lines[0]!.x1).toBe(320);
    expect(d.lines[0]!.y2).toBeCloseTo(233); // extension runs 5 px past the dimension line
    expect([d.lx, d.ly, d.angle]).toEqual([400, 238, 0]);
    expect(d.arrows.map(a => a.dx)).toEqual([-1, 1]); // arrows point out to the extension lines
    const deeper = layoutLinear(r as Extract<typeof r, { kind: "linear" }>, [0, 0, 1], 2, front, "80")!;
    expect(deeper.lines[2]!.y1).toBe(238 - 40); // stacked two levels further out, 20 px each
  });
  it("runs a dimension above a face along the edge nearest the viewer", () => {
    // top face corners at y = -25 (front, towards a camera at -Y) and y = +25
    const top = [[-40, 25, 20], [-40, -25, 20], [40, 25, 20], [40, -25, 20]].flat();
    expect(extreme(top, [0, 0, 1], [0.6, -0.6, 0.5])).toEqual([40, -25, 20]);
    expect(extreme(top, [0, 0, 1], [-0.6, 0.6, 0.5])).toEqual([-40, 25, 20]);
  });
  it("hides a length seen end-on", () => {
    const side: ViewCam = { ...front, project: p => [400 - p[1] * 2, 300 - p[2] * 2], vd: [1, 0, 0], right: [0, 1, 0] };
    const [r] = resolveDims([L], topo, { L: 80 });
    expect(layoutLinear(r as Extract<typeof r, { kind: "linear" }>, [0, 0, 1], 0, side, "80")).toBeNull();
  });
  it("lays out every kind and keeps the chosen side while the view stays on the same side", () => {
    const dirs = new Map<string, V3>();
    const out = layout(resolveDims([L, D], topo, { L: 80, D: 6.6 }), front, { bbox: topo.bbox, values: { L: 80, D: 6.6 }, units: { L: "mm", D: "mm" }, dirs });
    expect(out.map(d => d.text)).toEqual(["80", "4× Ø6.6"]);
    expect(viewKey([0.02, -0.99, 0.1])).toBe(viewKey(front.vd));
    expect(viewKey([0.7, -0.7, 0.2])).not.toBe(viewKey(front.vd));
  });
  it("nests dimensions measured the same way, shortest nearest the part", () => {
    expect(levels([{ key: "x", s: 80 }, { key: "x", s: 30 }, { key: "y", s: 50 }])).toEqual([1, 0, 0]);
  });
});

describe("labels and editing", () => {
  it("moves a label that would sit on another one, and keeps labels in the view", () => {
    const r = placeLabels([{ x: 100, y: 100, w: 40, h: 18 }, { x: 110, y: 102, w: 40, h: 18 }, { x: 300, y: 100, w: 40, h: 18 }, { x: 5, y: 100, w: 40, h: 18 }], { width: 800, height: 600 });
    expect(r[0]).toEqual({ x: 100, y: 100, moved: false });
    expect(r[1]!.moved).toBe(true);
    expect(Math.abs(r[1]!.x - 100) >= 40 || Math.abs(r[1]!.y - 100) >= 18).toBe(true);
    expect(r[2]!.moved).toBe(false);
    expect(r[3]!.x - 20).toBeGreaterThanOrEqual(0);
  });
  it("checks an on-screen edit like the panel does", () => {
    const m = { min: 60, max: 400, unit: "mm", label: "Length" };
    expect(checkEdit("150", false, m)).toEqual({ ok: true, value: 150 });
    expect(checkEdit(" 72,5 ", false, m)).toEqual({ ok: true, value: 72.5 });
    expect(checkEdit("500", false, m)).toEqual({ ok: false, error: "Length must be 60 to 400 mm" });
    expect(checkEdit("abc", false, m).ok).toBe(false);
    expect(checkEdit("4.5", true, { label: "Holes" })).toEqual({ ok: false, error: "Holes must be a whole number" });
  });
  it("writes values the way a drawing does", () => {
    const [r] = resolveDims([L], topo, { L: 80 });
    expect(dimText(r!, 80, "mm")).toBe("80");
    expect(dimText({ ...r!, circle: true } as typeof r & object, 120, "mm")).toBe("Ø120");
    expect(dimText({ param: "N", kind: "tag", tag: "count", at: [[0, 0, 0]], faces: [] }, 6, undefined)).toBe("6×");
    expect(dimText({ param: "A", kind: "tag", tag: "angle", at: [[0, 0, 0]], faces: [] }, 30, "deg")).toBe("30°");
  });
});
