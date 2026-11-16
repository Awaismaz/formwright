import { describe, expect, it } from "vitest";
import { profiles, solve, type CircleProfile, type Profile, type SEntity, type Sketch } from "./model";
import {
  addPolygon, addSlot, angleBetween, extend, filletCorner, geomOf, intersect, mirrorEntities, offsetEntities, ptOf, trim, type P2,
} from "./tools";

/** Sketch builder: points by name, entities referencing them. */
function sk(points: Record<string, P2>, entities: SEntity[], fixed: string[] = []): Sketch {
  return { points: Object.entries(points).map(([id, [x, y]]) => ({ id, x, y, ...(fixed.includes(id) ? { fixed: true } : {}) })), entities, constraints: [] };
}
const L = (id: string, p1: string, p2: string, construction = false): SEntity => ({ id, type: "line", p1, p2, ...(construction ? { construction } : {}) });
const C = (id: string, c: string, r: number): SEntity => ({ id, type: "circle", c, r });
const A = (id: string, c: string, p1: string, p2: string): SEntity => ({ id, type: "arc", c, p1, p2 });
const near = (a: P2, b: P2, tol = 1e-9) => Math.hypot(a[0] - b[0], a[1] - b[1]) < tol;
const has = (pts: P2[], p: P2, tol = 1e-9) => pts.some(q => near(q, p, tol));
const ent = (s: Sketch, id: string) => s.entities.find(e => e.id === id)!;
const ends = (s: Sketch, id: string): P2[] => { const e = ent(s, id) as { p1: string; p2: string }; return [ptOf(s, e.p1), ptOf(s, e.p2)]; };

/** Area of a profile loop: shoelace over the segments, plus each arc's circular-segment bulge. */
function loopArea(segs: Profile["segs"]): number {
  let a2 = 0;
  for (const g of segs) {
    if (g.type === "line") { a2 += g.a[0] * g.b[1] - g.b[0] * g.a[1]; continue; }
    // arc through a, m, b: sample it finely
    const [ax, ay] = g.a, [mx, my] = g.m!, [bx, by] = g.b;
    const d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my));
    const ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d;
    const uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d;
    const r = Math.hypot(ax - ux, ay - uy);
    const t0 = Math.atan2(ay - uy, ax - ux), tm = Math.atan2(my - uy, mx - ux), t1 = Math.atan2(by - uy, bx - ux);
    const norm = (t: number) => ((t % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    const ccw = norm(tm - t0) < norm(t1 - t0);
    const sweep = ccw ? norm(t1 - t0) || 2 * Math.PI : -(norm(t0 - t1) || 2 * Math.PI);
    const n = 4000; let px = ax, py = ay;
    for (let i = 1; i <= n; i++) { const t = t0 + (sweep * i) / n; const qx = ux + r * Math.cos(t), qy = uy + r * Math.sin(t); a2 += px * qy - qx * py; px = qx; py = qy; }
  }
  return Math.abs(a2) / 2;
}

const area = (l: Profile | CircleProfile) => (l.kind === "circle" ? Math.PI * l.r * l.r : loopArea(l.segs));

describe("intersections", () => {
  it("line/line, line/circle, line/arc and circle/circle", () => {
    const s = sk({ a: [0, 0], b: [10, 0], c: [5, -5], d: [5, 5], o: [0, 0], e: [-20, 3], f: [20, 3], g: [0, -20], h: [0, 20], p: [10, 0], q: [-10, 0], o2: [8, 0] },
      [L("h1", "a", "b"), L("v1", "c", "d"), C("c1", "o", 10), L("h2", "e", "f"), L("v2", "g", "h"), A("arc", "o", "p", "q"), C("c5", "o", 5), C("c6", "o2", 5)]);
    const G = (id: string) => geomOf(s, ent(s, id));
    expect(intersect(G("h1"), G("v1"))).toEqual([[5, 0]]);
    const lc = intersect(G("h2"), G("c1")); // y = 3 on R10: x = ±√91
    expect(lc).toHaveLength(2); expect(has(lc, [Math.sqrt(91), 3])).toBe(true); expect(has(lc, [-Math.sqrt(91), 3])).toBe(true);
    expect(intersect(G("v2"), G("arc"))).toEqual([[0, 10]]); // the upper half only, not (0, -10)
    const cc = intersect(G("c5"), G("c6"));
    expect(has(cc, [4, 3])).toBe(true); expect(has(cc, [4, -3])).toBe(true);
    expect(intersect(G("h1"), { kind: "line", a: [0, 1], b: [10, 1] })).toEqual([]); // parallel
  });
});

describe("trim", () => {
  it("line/line: trims to the crossing and both pieces share the new point", () => {
    let s = sk({ a: [0, 0], b: [10, 0], c: [5, -5], d: [5, 5] }, [L("h", "a", "b"), L("v", "c", "d")]);
    s = trim(s, "h", [8, 0]);
    expect(ends(s, "h")).toEqual([[0, 0], [5, 0]]);
    expect(s.constraints.some(k => k.type === "onLine" && k.line === "v")).toBe(true);
    s = trim(s, "v", [5, 4]);
    expect(ends(s, "v")).toEqual([[5, -5], [5, 0]]);
    const h = ent(s, "h") as { p2: string }, v = ent(s, "v") as { p2: string };
    expect(h.p2).toBe(v.p2); // reused, so the corner chains
    expect(s.points).toHaveLength(3);
    expect(solve(s).ok).toBe(true);
  });

  it("an entity with no intersections is deleted", () => {
    const s = trim(sk({ a: [0, 0], b: [10, 0] }, [L("h", "a", "b")]), "h", [3, 0]);
    expect(s.entities).toHaveLength(0); expect(s.points).toHaveLength(0);
  });

  it("splitting a line in the middle keeps its horizontal relation on both pieces", () => {
    let s = sk({ a: [0, 0], b: [30, 0], c: [10, -5], d: [10, 5], e: [20, -5], f: [20, 5] }, [L("h", "a", "b"), L("v1", "c", "d"), L("v2", "e", "f")]);
    s.constraints.push({ id: "k1", type: "horizontal", line: "h" }, { id: "k2", type: "length", line: "h", value: 30 });
    s = trim(s, "h", [15, 0]);
    const lines = s.entities.filter(e => e.type === "line" && !["v1", "v2"].includes(e.id));
    expect(lines).toHaveLength(2);
    expect(lines.map(l => ends(s, l.id))).toEqual([[[0, 0], [10, 0]], [[20, 0], [30, 0]]]);
    expect(s.constraints.filter(k => k.type === "horizontal")).toHaveLength(2);
    expect(s.constraints.some(k => k.type === "length")).toBe(false);
  });

  it("circle/line: a circle cut by a diameter becomes a semicircle, then the line is trimmed to a closed D", () => {
    let s = sk({ o: [0, 0], a: [-20, 0], b: [20, 0] }, [C("c", "o", 10), L("d", "a", "b")]);
    s = trim(s, "c", [0, -10]); // remove the lower half
    const g = geomOf(s, ent(s, "c"));
    expect(g.kind).toBe("arc");
    if (g.kind === "arc") { expect(g.sweep).toBeCloseTo(Math.PI, 12); expect(near(ptOf(s, (ent(s, "c") as { p1: string }).p1), [10, 0])).toBe(true); }
    s = trim(s, "d", [15, 0]); s = trim(s, "d", [-15, 0]);
    expect(ends(s, "d")).toEqual([[-10, 0], [10, 0]]);
    const pr = profiles(s);
    expect(pr.loops).toHaveLength(1); expect(pr.open).toBe(0);
    expect(area(pr.loops[0]!)).toBeCloseTo((Math.PI * 100) / 2, 4);
  });

  it("circle/circle: trimming the overlap of two R5 circles leaves their union outline", () => {
    let s = sk({ o1: [0, 0], o2: [8, 0] }, [C("c1", "o1", 5), C("c2", "o2", 5)]);
    s = trim(s, "c1", [5, 0]); s = trim(s, "c2", [3, 0]);
    const g1 = geomOf(s, ent(s, "c1"));
    if (g1.kind !== "arc") throw new Error("expected an arc");
    expect(g1.sweep).toBeCloseTo(2 * Math.PI - 2 * Math.atan2(3, 4), 10); // cusps at (4, ±3)
    const pr = profiles(s); expect(pr.loops).toHaveLength(1);
    const lens = 2 * 25 * Math.acos(8 / 10) - 4 * Math.sqrt(100 - 64);
    expect(area(pr.loops[0]!)).toBeCloseTo(2 * Math.PI * 25 - lens, 3);
  });

  it("line/arc: an arc is shortened at the line", () => {
    let s = sk({ o: [0, 0], p: [10, 0], q: [-10, 0], a: [0, -20], b: [0, 20] }, [A("arc", "o", "p", "q"), L("v", "a", "b")]);
    s = trim(s, "arc", [-7.07, 7.07]);
    const g = geomOf(s, ent(s, "arc"));
    if (g.kind !== "arc") throw new Error("expected an arc");
    expect(g.sweep).toBeCloseTo(Math.PI / 2, 12);
    expect(near(ends(s, "arc")[1], [0, 10])).toBe(true);
  });
});

describe("extend", () => {
  it("a line's free end runs to the next line", () => {
    let s = sk({ a: [0, 0], b: [5, 0], c: [10, -5], d: [10, 5], e: [14, -5], f: [14, 5] }, [L("h", "a", "b"), L("v", "c", "d"), L("w", "e", "f")]);
    s = extend(s, "h", [4, 0]);
    expect(ends(s, "h")).toEqual([[0, 0], [10, 0]]);
    expect(s.constraints.some(k => k.type === "onLine" && k.pt === "b" && k.line === "v")).toBe(true);
    expect(() => extend(s, "h", [0.5, 0])).toThrow(/Nothing to extend/);
  });

  it("an arc end runs round its circle to a line", () => {
    let s = sk({ o: [0, 0], p: [10, 0], q: [0, 10], a: [-5, -20], b: [-5, 20] }, [A("arc", "o", "p", "q"), L("v", "a", "b")]);
    s = extend(s, "arc", [1, 10]);
    expect(near(ends(s, "arc")[1], [-5, Math.sqrt(75)], 1e-9)).toBe(true); // 120°
  });

  it("a connected end is refused", () => {
    const s = sk({ a: [0, 0], b: [5, 0], c: [5, 5], d: [10, -5], e: [10, 5] }, [L("h", "a", "b"), L("u", "b", "c"), L("v", "d", "e")]);
    expect(() => extend(s, "h", [4, 0])).toThrow(/free end/);
  });
});

describe("offset entities", () => {
  const rect = () => sk({ a: [0, 0], b: [20, 0], c: [20, 10], d: [0, 10] }, [L("l1", "a", "b"), L("l2", "b", "c"), L("l3", "c", "d"), L("l4", "d", "a")]);
  const newPts = (s0: Sketch, s: Sketch) => s.points.filter(p => !s0.points.some(q => q.id === p.id)).map(p => [p.x, p.y] as P2);
  it("a closed rectangle grows outwards by default and shrinks when flipped", () => {
    const s0 = rect();
    const out = newPts(s0, offsetEntities(s0, ["l1", "l2", "l3", "l4"], 2));
    for (const p of [[-2, -2], [22, -2], [22, 12], [-2, 12]] as P2[]) expect(has(out, p)).toBe(true);
    const inn = newPts(s0, offsetEntities(s0, ["l1", "l2", "l3", "l4"], 2, true));
    for (const p of [[2, 2], [18, 2], [18, 8], [2, 8]] as P2[]) expect(has(inn, p)).toBe(true);
    const s = offsetEntities(s0, ["l1", "l2", "l3", "l4"], 2);
    expect(s.constraints.filter(k => k.type === "parallel")).toHaveLength(4);
    expect(profiles(s).loops).toHaveLength(2);
    expect(solve(s).ok).toBe(true);
  });

  it("a slot outline offsets to concentric arcs and parallel lines", () => {
    const s0 = addSlot(sk({ c1: [0, 0], c2: [20, 0] }, []), "c1", "c2", 5);
    const ids = s0.entities.filter(e => !e.construction).map(e => e.id);
    const s = offsetEntities(s0, ids, 2);
    const arcs = s.entities.filter(e => e.type === "arc" && !s0.entities.some(o => o.id === e.id));
    expect(arcs).toHaveLength(2);
    for (const a of arcs) { const g = geomOf(s, a); expect(g.kind === "arc" && g.r).toBeCloseTo(7, 9); }
    const pr = profiles(s); expect(pr.loops).toHaveLength(2);
    const areas = pr.loops.map(l => area(l)).sort((x, y) => x - y);
    expect(areas[0]).toBeCloseTo(20 * 10 + Math.PI * 25, 3);
    expect(areas[1]).toBeCloseTo(20 * 14 + Math.PI * 49, 3);
  });

  it("an open chain offsets to the left of its direction and circles change radius", () => {
    const s0 = sk({ a: [0, 0], b: [10, 0], c: [10, 10], o: [30, 0] }, [L("l1", "a", "b"), L("l2", "b", "c"), C("k", "o", 4)]);
    const s = offsetEntities(s0, ["l1", "l2", "k"], 1);
    const pts = newPts(s0, s);
    for (const p of [[0, 1], [9, 1], [9, 10]] as P2[]) expect(has(pts, p)).toBe(true);
    expect(s.entities.filter(e => e.type === "circle").map(e => (e as { r: number }).r).sort()).toEqual([4, 5]);
    expect(() => offsetEntities(s0, ["k"], 5, true)).toThrow(/radius/);
  });
});

describe("slot, polygon, fillet, mirror, angle", () => {
  it("straight slot: closed profile of area 2r·L + πr², 5 degrees of freedom", () => {
    const s = addSlot(sk({ c1: [0, 0], c2: [30, 0] }, []), "c1", "c2", 4);
    const r = solve(s);
    expect(r.ok).toBe(true); expect(r.dof).toBe(5);
    const pr = profiles(r.sketch); expect(pr.loops).toHaveLength(1);
    expect(area(pr.loops[0]!)).toBeCloseTo(8 * 30 + Math.PI * 16, 3);
  });

  it("inscribed hexagon R10 has sides of 10; circumscribed about an apothem of 10 has sides 2·10·tan30°", () => {
    for (const [mode, side] of [["inscribed", 10], ["circumscribed", 20 * Math.tan(Math.PI / 6)]] as const) {
      const s = addPolygon(sk({ c: [0, 0] }, [], ["c"]), "c", [10, 0], 6, mode);
      const r = solve(s);
      expect(r.ok).toBe(true); expect(r.dof).toBe(2); // size and rotation
      const sides = r.sketch.entities.filter(e => e.type === "line").map(e => { const [a, b] = ends(r.sketch, e.id); return Math.hypot(b[0] - a[0], b[1] - a[1]); });
      expect(sides).toHaveLength(6); for (const x of sides) expect(x).toBeCloseTo(side, 9);
    }
    expect(() => addPolygon(sk({ c: [0, 0] }, []), "c", [10, 0], 2)).toThrow();
  });

  it("corner fillet R3 on a 20×10 rectangle removes 9 − 9π/4 of area and stays solved", () => {
    const s0 = sk({ a: [0, 0], b: [20, 0], c: [20, 10], d: [0, 10] }, [L("l1", "a", "b"), L("l2", "b", "c"), L("l3", "c", "d"), L("l4", "d", "a")]);
    const s = filletCorner(s0, "b", 3);
    expect(s.points.some(p => p.id === "b")).toBe(false);
    const arc = s.entities.find(e => e.type === "arc")!; const g = geomOf(s, arc);
    expect(g.kind === "arc" && near(g.c, [17, 3])).toBe(true);
    expect(g.kind === "arc" && g.sweep).toBeCloseTo(Math.PI / 2, 12);
    const r = solve(s); expect(r.ok).toBe(true); expect(r.dof).toBe(8); // 12 unknowns − (arc ends, 2 tangents, radius)
    const pr = profiles(r.sketch); expect(pr.loops).toHaveLength(1);
    expect(area(pr.loops[0]!)).toBeCloseTo(200 - (9 - (9 * Math.PI) / 4), 4);
    expect(() => filletCorner(s0, "d", 11)).toThrow(/too large/);
  });

  it("mirror about a centerline: copies follow the original through the symmetric relation", () => {
    const s0 = sk({ m1: [0, -10], m2: [0, 10], a: [2, 1], b: [5, 4], o: [6, -3], t: [0, 4] }, [L("ax", "m1", "m2", true), L("l", "a", "b"), C("c", "o", 2), L("u", "b", "t")], ["m1", "m2"]);
    const s = mirrorEntities(s0, ["l", "c", "u", "ax"], "ax");
    const mirrored = s.entities.filter(e => !s0.entities.some(o => o.id === e.id));
    expect(mirrored).toHaveLength(3);
    const pts = s.points.map(p => [p.x, p.y] as P2);
    for (const p of [[-2, 1], [-5, 4], [-6, -3]] as P2[]) expect(has(pts, p)).toBe(true);
    expect(s.points.filter(p => p.x === 0 && p.y === 4)).toHaveLength(1); // a point on the axis is shared
    // drag the original end point: its image follows
    s.points.find(p => p.id === "a")!.x = 3; s.points.find(p => p.id === "a")!.fixed = true;
    const r = solve(s); expect(r.ok).toBe(true);
    expect(has(r.sketch.points.map(p => [p.x, p.y] as P2), [-3, 1], 1e-6)).toBe(true);
  });

  it("angle dimension measures the corner angle and drives it", () => {
    const s0 = sk({ o: [0, 0], a: [10, 0], b: [5, 5 * Math.sqrt(3)] }, [L("l1", "o", "a"), L("l2", "b", "o")], ["o", "a"]);
    const k = angleBetween(s0, "l1", "l2");
    expect(k.value).toBeCloseTo(60, 9); expect(k.f2).toBe(true);
    const s = { ...s0, constraints: [{ ...k, id: "k", value: 45 }, { id: "k2", type: "length" as const, line: "l2", value: 10 }] };
    const r = solve(s); expect(r.ok).toBe(true); expect(r.dof).toBe(0);
    const b = ptOf(r.sketch, "b"); expect(Math.atan2(b[1], b[0]) * 180 / Math.PI).toBeCloseTo(45, 6);
    expect(() => angleBetween(sk({ a: [0, 0], b: [1, 0], c: [0, 1], d: [1, 1] }, [L("p", "a", "b"), L("q", "c", "d")]), "p", "q")).toThrow(/parallel/);
  });

  it("profiles chain coincident end points even with different ids", () => {
    const s = sk({ a: [0, 0], b: [10, 0], b2: [10, 0], c: [0, 10], c2: [0, 10], a2: [0, 0] }, [L("l1", "a", "b"), L("l2", "b2", "c"), L("l3", "c2", "a2")]);
    const pr = profiles(s); expect(pr.loops).toHaveLength(1); expect(pr.open).toBe(0);
    const open = profiles(sk({ a: [0, 0], b: [10, 0], c: [10, 10] }, [L("l2", "b", "c"), L("l1", "a", "b")]));
    expect(open.chains).toHaveLength(1); expect(open.chains[0]).toHaveLength(2);
  });
});
