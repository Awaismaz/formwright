import { describe, expect, it } from "vitest";
import { filletCorner, offsetEntities, trim, type P2 } from "@/sketch/tools";
import {
  applySketch, chamferCorner, closedLoops, DEFAULT_SNAPS, dimText, findSnap, hatchAt, hatchRegionAt, measure, moveBy, parsePointInput,
  pointMap, prune, rotateAbout, sketchOf, track, transformSelection, type DEnt, type Dim, type DraftDoc,
} from "./geom";
import { contentPrims, textWidth, type Prim } from "./prims";

/** 100 x 60 rectangle (corner A at the origin), a Ø20 hole at (30, 30), a centre line through it. */
function base(): DraftDoc {
  const pts: Record<string, P2> = { A: [0, 0], B: [100, 0], C: [100, 60], D: [0, 60], H: [30, 30], K1: [10, 30], K2: [90, 30] };
  const L = (id: string, p1: string, p2: string, layer: DEnt["layer"] = "visible"): DEnt => ({ id, type: "line", p1, p2, layer });
  return {
    schema: 1,
    sheet: { size: "A3", orientation: "landscape", scale: [1, 1], projection: "first", units: "mm", origin: [200, 150] },
    title: { title: "T", drawing_no: "", material: "", company: "", drawn_by: "", checked_by: "", date: "", tolerance: "" },
    geom: {
      points: Object.entries(pts).map(([id, [x, y]]) => ({ id, x, y })),
      entities: [L("AB", "A", "B"), L("BC", "B", "C"), L("CD", "C", "D"), L("DA", "D", "A"), { id: "h", type: "circle", c: "H", r: 10, layer: "visible" }, L("cl", "K1", "K2", "center")],
      constraints: [],
    },
    dims: [], annos: [], notes: [], revisions: [],
  };
}
const near = (a: P2, b: P2, tol = 1e-9) => Math.hypot(a[0] - b[0], a[1] - b[1]) < tol;
const loopPoly = () => null;

describe("dimension values (associative, measured)", () => {
  it("linear h / v / aligned, radius, diameter, angle and ordinate", () => {
    const d = base();
    const P = pointMap(d);
    const dims: Dim[] = [
      { id: "1", type: "linear", orient: "h", a: "A", b: "C", pos: [50, -10] },
      { id: "2", type: "linear", orient: "v", a: "A", b: "C", pos: [-10, 30] },
      { id: "3", type: "linear", orient: "aligned", a: "A", b: "C", pos: [40, 40] },
      { id: "4", type: "diameter", ent: "h", pos: [50, 50] },
      { id: "5", type: "radius", ent: "h", pos: [50, 50] },
      { id: "6", type: "angle", l1: "AB", l2: "DA", pos: [5, 5] },
      { id: "7", type: "ordinate", axis: "y", origin: "A", pt: "H", pos: [-20, 30] },
    ];
    expect(dims.map(x => measure(d, x, P))).toEqual([100, 60, Math.hypot(100, 60), 20, 10, 90, 30]);
    // the value follows the geometry
    d.geom.points.find(p => p.id === "C")!.x = 120;
    expect(measure(d, dims[0]!)).toBe(120);
  });
  it("prints prefix, Ø / R, tolerances, limits and fits like the server", () => {
    const d = base();
    const t = (x: Dim) => { const r = dimText(d, x, measure(d, x)!); return [r.main, ...r.stack].join(" ").trim(); };
    expect(t({ id: "1", type: "diameter", ent: "h", pos: [0, 0], prefix: "4X", tol: { kind: "fit", fit: "H7" } })).toBe("4X Ø20 H7");
    expect(t({ id: "2", type: "linear", orient: "h", a: "A", b: "B", pos: [0, 0], tol: { kind: "sym", up: 0.1 } })).toBe("100 ±0.1");
    expect(t({ id: "3", type: "linear", orient: "h", a: "A", b: "B", pos: [0, 0], tol: { kind: "dev", up: 0, lo: -0.05 } })).toBe("100 0 -0.05");
    expect(t({ id: "4", type: "linear", orient: "v", a: "A", b: "D", pos: [0, 0], tol: { kind: "limits", up: 0.02, lo: -0.01 } })).toBe("60.02 59.99");
    expect(t({ id: "5", type: "radius", ent: "h", pos: [0, 0] })).toBe("R10");
  });
  it("draws the value centred above its dimension line with arrows on the extension lines", () => {
    const d = base();
    d.dims = [{ id: "L", type: "linear", orient: "h", a: "A", b: "B", pos: [50, -15] }];
    const prims = contentPrims(d, { loopPoly });
    const txt = prims.find((p): p is Extract<Prim, { t: "text" }> => p.t === "text" && p.dim === "L")!;
    expect(txt.txt).toBe("100");
    // origin (200, 150) at 1:1: the line sits at paper y = 150 + 15, text 1 mm above it
    expect(txt.x).toBeCloseTo(250, 9); expect(txt.y).toBeCloseTo(164, 9);
    const tips = prims.filter(p => p.t === "fill" && p.dim === "L").map(p => (p as { p: P2[] }).p[0]!);
    expect(tips.some(q => near(q, [200, 165]))).toBe(true); expect(tips.some(q => near(q, [300, 165]))).toBe(true);
    expect(textWidth("100", 3.5)).toBeCloseTo(3 * 0.556 * 3.5, 9);
  });
});

describe("snaps and tracking", () => {
  it("endpoint, midpoint, centre, intersection, perpendicular and grid", () => {
    const d = base();
    expect(findSnap(d, [100.4, 0.3], 1, DEFAULT_SNAPS)).toMatchObject({ kind: "endpoint", pt: "B", p: [100, 0] });
    expect(findSnap(d, [50.2, 0.4], 1, DEFAULT_SNAPS)).toMatchObject({ kind: "midpoint", p: [50, 0] });
    expect(findSnap(d, [30.3, 29.8], 1, DEFAULT_SNAPS)).toMatchObject({ kind: "center", pt: "H" });
    const x = findSnap(d, [20.2, 30.1], 1, DEFAULT_SNAPS)!; // centre line meets the hole at (20, 30)
    expect(x.kind).toBe("intersection"); expect(near(x.p, [20, 30])).toBe(true);
    const perp = findSnap(d, [70.3, 59.6], 1, DEFAULT_SNAPS, [70, 10])!;
    expect(perp.kind).toBe("perpendicular"); expect(near(perp.p, [70, 60])).toBe(true);
    expect(findSnap(d, [61.2, 43.9], 1, { ...DEFAULT_SNAPS, grid: true, gridStep: 5 })).toMatchObject({ kind: "grid", p: [60, 45] });
  });
  it("ortho, polar and typed input", () => {
    expect(track([0, 0], [10, 2], "ortho")).toEqual([10, 0]);
    const p = track([0, 0], [10, 9], "polar", 15); expect(near(p, [Math.hypot(10, 9) * Math.SQRT1_2, Math.hypot(10, 9) * Math.SQRT1_2])).toBe(true);
    expect(parsePointInput("25,40", null, null)).toEqual([25, 40]);
    expect(parsePointInput("@10,-5", [1, 1], null)).toEqual([11, -4]);
    const polar = parsePointInput("@20<90", [0, 0], null)!; expect(near(polar, [0, 20])).toBe(true);
    expect(parsePointInput("30", [0, 0], [5, 0])).toEqual([30, 0]);
    expect(parsePointInput("abc", [0, 0], null)).toBeNull();
  });
});

describe("editing tools on a drawing", () => {
  it("trim keeps layers and drops dimensions on removed geometry", () => {
    let d = base();
    d.dims = [{ id: "dcl", type: "linear", orient: "h", a: "K1", b: "K2", pos: [50, 40] }];
    d = applySketch(d, trim(sketchOf(d), "cl", [15, 30]), "visible"); // cut the centre line's left part off at the hole
    const cl = d.geom.entities.find(e => e.id === "cl")!;
    expect(cl.layer).toBe("center");
    expect(d.dims).toHaveLength(0); // K1 is gone, so its dimension is too
  });
  it("offset puts new geometry on the layer given (the source's); fillet and chamfer corners", () => {
    let d = base();
    d = applySketch(d, offsetEntities(sketchOf(d), ["AB", "BC", "CD", "DA"], 5), "visible");
    expect(d.geom.entities.find(e => e.id === "cl")!.layer).toBe("center");
    const outer = d.geom.entities.filter(e => e.type === "line" && !["AB", "BC", "CD", "DA", "cl"].includes(e.id));
    expect(outer).toHaveLength(4);
    expect(outer.every(e => e.layer === "visible")).toBe(true);
    const P = pointMap(d);
    const xs = outer.flatMap(e => e.type === "line" ? [P.get(e.p1)![0], P.get(e.p2)![0]] : []);
    expect(Math.min(...xs)).toBeCloseTo(-5, 9); expect(Math.max(...xs)).toBeCloseTo(105, 9);
    let f = applySketch(base(), filletCorner(sketchOf(base()), "B", 8), "visible");
    expect(f.geom.entities.filter(e => e.type === "arc")).toHaveLength(1);
    f = chamferCorner(base(), "D", 5);
    const cham = f.geom.entities.at(-1)!;
    expect(cham.type).toBe("line");
    const Q = pointMap(f); const c = cham as Extract<DEnt, { type: "line" }>;
    expect(Math.hypot(Q.get(c.p1)![0] - Q.get(c.p2)![0], Q.get(c.p1)![1] - Q.get(c.p2)![1])).toBeCloseTo(5 * Math.SQRT2, 9);
    expect(() => chamferCorner(base(), "H", 5)).toThrow();
  });
  it("move splits shared points; copy duplicates with its dimensions; rotate turns about a point", () => {
    const d = base();
    d.dims = [{ id: "dd", type: "diameter", ent: "h", pos: [45, 45] }];
    const moved = transformSelection(d, new Set(["h"]), moveBy(10, 0));
    expect(pointMap(moved).get("H")).toEqual([40, 30]);
    expect(moved.dims[0]!.pos).toEqual([55, 45]); // the dimension follows its circle
    const ab = transformSelection(d, new Set(["AB"]), moveBy(0, -5));
    const P = pointMap(ab);
    expect(P.get("A")).toEqual([0, 0]); // the side DA keeps its corner: AB got its own points
    const e = ab.geom.entities.find(x => x.id === "AB") as Extract<DEnt, { type: "line" }>;
    expect(P.get(e.p1)).toEqual([0, -5]);
    const copied = transformSelection(d, new Set(["h"]), moveBy(40, 0), { copy: true });
    expect(copied.geom.entities.filter(x => x.type === "circle")).toHaveLength(2);
    expect(copied.dims).toHaveLength(2);
    const r = transformSelection(d, new Set(["h"]), rotateAbout([0, 0], 90));
    const H = pointMap(r).get("H")!; expect(near(H, [-30, 30])).toBe(true);
  });
  it("hatch finds the region around a point, with the hole as an island", () => {
    const d = base();
    expect(closedLoops(d)).toHaveLength(2);
    expect(hatchRegionAt(d, [70, 10])).toEqual([["AB", "BC", "CD", "DA"], ["h"]]);
    expect(hatchRegionAt(d, [30, 30])).toEqual([["h"]]);
    expect(hatchRegionAt(d, [200, 200])).toBeNull();
    const h = hatchAt(d, [70, 10])!;
    expect(h.loops[0]!.sort()).toEqual(["AB", "BC", "CD", "DA"]); expect(h.loops[1]).toEqual(["h"]);
    expect(hatchAt(d, [30, 30])!.loops).toEqual([["h"]]);
  });
  it("hatch splits a T-junction boundary into whole pieces (wall between a dividing line and the outline)", () => {
    const d = base();
    d.geom.points.push({ id: "T1", x: 60, y: 0 }, { id: "T2", x: 60, y: 60 });
    d.geom.entities.push({ id: "div", type: "line", p1: "T1", p2: "T2", layer: "visible" });
    const r = hatchAt(d, [80, 30])!;
    expect(r).not.toBeNull();
    const P = pointMap(r.doc);
    const loop = r.loops[0]!.map(id => r.doc.geom.entities.find(e => e.id === id)!);
    // the right-hand cell: x 60..100, y 0..60, made of 4 whole lines
    const xs = loop.flatMap(e => e.type === "line" ? [P.get(e.p1)![0], P.get(e.p2)![0]] : []);
    expect(loop).toHaveLength(4); expect(Math.min(...xs)).toBeCloseTo(60, 9); expect(Math.max(...xs)).toBeCloseTo(100, 9);
    expect(r.doc.geom.entities.filter(e => e.type === "line" && e.layer === "visible")).toHaveLength(7); // AB and CD split at x = 60
    expect(hatchAt(d, [40, 10])!.loops).toHaveLength(2); // left cell keeps the hole as an island
    const pr = prune({ ...d, annos: [{ id: "x", type: "hatch", loops: [["gone"]], spacing: 3 }, { id: "c", type: "centermark", ent: "h" }] });
    expect(pr.annos.map(a => a.id)).toEqual(["c"]);
  });
});
