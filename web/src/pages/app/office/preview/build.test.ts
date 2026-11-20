import { describe, expect, it } from "vitest";
import { apply, bodyGeo, box, itemOfRow, lathe, segmentsFor, sig, toResolved, visibleDims, worldBounds } from "./build";
import type { PreviewBody, PreviewDim } from "./types";

// canonical frame of an item along +Y (office/frames.CANON["y"]): part Z -> program +Y, part Y -> program -Z
const ALONG_Y = (t: [number, number, number]) => [1, 0, 0, t[0], 0, 0, 1, t[1], 0, -1, 0, t[2]];
const ID = (t: [number, number, number]) => [1, 0, 0, t[0], 0, 1, 0, t[1], 0, 0, 1, t[2]];
const round6 = (xs: number[]) => xs.map(x => Math.round(x * 1e6) / 1e6 + 0);

/** The keyed gear golden case as the server lays it out (tests/test_plan_preview.py checks the same numbers). */
const KEYED: PreviewBody[] = [
  { id: "i_s1_p1#0", item: "i_s1_p1", copy: 0, name: "Stepped shaft", kind: "shaft", path: "spec", T: ALONG_Y([0, 18, 0]),
    g: { segs: [[-40, -18, 20], [-18, 40, 26]] } },
  { id: "i_s1_p2#0", item: "i_s1_p2", copy: 0, name: "Spur gear", kind: "gear", path: "spec", T: ALONG_Y([0, -10, 0]),
    g: { tip: 64, pitch: 60, width: 20, bore: 20, m: 2, z: 30 } },
  // key frame: X along the shaft (+Y), Z out along the keyway (+X); centre 6.5 + 6 / 2 = 9.5 off the axis
  { id: "i_s1_p3#0", item: "i_s1_p3", copy: 0, name: "Parallel key", kind: "key", path: "toolbox", standard: true,
    T: [0, 0, 1, 9.5, 1, 0, 0, -10, 0, 1, 0, 0], g: { s: [18, 6, 6] } },
];

describe("primitives", () => {
  it("a box has six flat faces and twelve edges", () => {
    const g = box(10, 20, 30);
    expect(g.pos.length / 3).toBe(24);
    expect(g.idx.length / 3).toBe(12);
    expect(g.edges.length / 6).toBe(12);
    expect(Math.min(...g.pos.filter((_, i) => i % 3 === 0))).toBe(-5);
    expect(Math.max(...g.pos.filter((_, i) => i % 3 === 2))).toBe(15);
  });

  it("a lathe profile gives one band per segment and a circle per corner off the axis", () => {
    const g = lathe([[0, 0], [5, 0], [5, 10], [0, 10]], false, 8);
    expect(g.pos.length / 3).toBe(3 * 9 * 2);          // three bands of 2 x (8 + 1) vertices
    expect(g.idx.length / 3).toBe(8 + 16 + 8);         // fan, quads, fan
    expect(g.edges.length / 6).toBe(2 * 8);            // circles at (5, 0) and (5, 10)
  });

  it("segment counts are multiples of four so the quadrant points are exact", () => {
    for (const r of [1, 3, 10, 22, 62, 600]) expect(segmentsFor(r) % 4).toBe(0);
  });

  it("a gear blank is its tip circle and face width, with the pitch circle and a tick per tooth on both faces", () => {
    const g = bodyGeo(KEYED[1]!);
    const n = segmentsFor(32);
    const rs: number[] = [];
    for (let i = 0; i + 2 < g.pos.length; i += 3) rs.push(Math.hypot(g.pos[i]!, g.pos[i + 1]!));
    expect(Math.max(...rs)).toBeCloseTo(32, 6);
    expect(Math.min(...rs)).toBeCloseTo(10, 6);        // the Ø20 bore
    // edges: 4 corner circles of the bored disc, 2 pitch circles, 2 x 30 tooth ticks
    expect(g.edges.length / 6).toBe(4 * n + 2 * n + 2 * 30);
  });

  it("a screw is a shank and a head along its own Z", () => {
    const g = bodyGeo({ kind: "screw", g: { d: 6, L: 30, head_d: 9, head_h: 6 } });
    const zs = g.pos.filter((_, i) => i % 3 === 2);
    expect(Math.min(...zs)).toBe(0);
    expect(Math.max(...zs)).toBe(36);
  });

  it("a bearing is a ring from its bore to its outer diameter, B wide", () => {
    const g = bodyGeo({ kind: "bearing", g: { d: 20, D: 47, B: 14 } });
    const rs: number[] = [];
    for (let i = 0; i + 2 < g.pos.length; i += 3) rs.push(Math.hypot(g.pos[i]!, g.pos[i + 1]!));
    expect(Math.min(...rs)).toBeCloseTo(10, 6);
    expect(Math.max(...rs)).toBeCloseTo(23.5, 6);
  });
});

describe("placement", () => {
  it("applies the 12-number transform (part Z laid along program +Y)", () => {
    expect(apply(ALONG_Y([0, 18, 0]), [0, 0, 40])).toEqual([0, 58, 0]);
    expect(round6(apply(ALONG_Y([0, 18, 0]), [0, 10, 0]))).toEqual([0, 18, -10]);
  });

  it("the keyed gear's drawn bodies span exactly the solved envelope", () => {
    // shaft Y -22 .. 58 (centre 18, 80 long), gear tip Ø64 at Y -20 .. 0: X and Z +-32
    expect(round6(worldBounds(KEYED))).toEqual([-32, -22, -32, 32, 58, 32]);
  });

  it("the stepped shaft keeps its Ø20 seat under the gear and its Ø26 step behind the shoulder", () => {
    const g = bodyGeo(KEYED[0]!);
    const radiusAt = (yWorld: number) => {
      let r = 0;
      for (let i = 0; i + 2 < g.pos.length; i += 3) {
        const w = apply(KEYED[0]!.T, [g.pos[i]!, g.pos[i + 1]!, g.pos[i + 2]!]);
        if (Math.abs(w[1] - yWorld) < 1e-6) r = Math.max(r, Math.hypot(w[0], w[2]));
      }
      return r;
    };
    expect(radiusAt(-22)).toBeCloseTo(10, 6);   // the seat's free end
    expect(radiusAt(58)).toBeCloseTo(13, 6);    // the far end of the Ø26 step
  });

  it("the key sits in the keyseat: underside 6.5 off the axis, top 12.5, along the hub", () => {
    expect(round6(worldBounds([KEYED[2]!]))).toEqual([6.5, -19, -3, 12.5, -1, 3]);
  });

  it("the gear pair: blanks 80 apart on parallel axes; the table: legs at their corners", () => {
    const pair: PreviewBody[] = [
      { id: "p#0", item: "p", copy: 0, name: "Pinion", kind: "gear", path: "spec", T: ALONG_Y([0, 0, 0]), g: { tip: 44, pitch: 40, width: 20, bore: 20, m: 2, z: 20 } },
      { id: "g#0", item: "g", copy: 0, name: "Gear", kind: "gear", path: "spec", T: ALONG_Y([80, 0, 0]), g: { tip: 124, pitch: 120, width: 20, bore: 20, m: 2, z: 60 } },
    ];
    expect(round6(worldBounds(pair))).toEqual([-22, -10, -62, 142, 10, 62]);
    const corners: [number, number][] = [[-540, -280], [540, -280], [-540, 280], [540, 280]];
    const legs: PreviewBody[] = corners.map(([x, y], c) => (
      { id: "leg#" + c, item: "leg", copy: c, name: "Leg", kind: "box", path: "spec", T: ID([x, y, -370]), g: { s: [40, 20, 700] } }));
    expect(worldBounds(legs)).toEqual([-560, -290, -720, 560, 290, -20]);
  });
});

describe("dimensions and rows", () => {
  const dims: PreviewDim[] = [
    { id: "cd:IF-07", kind: "linear", a: [0, 0, 0], b: [80, 0, 0], text: "80", label: "Centre distance", items: ["p", "g"], prio: 1, sources: [], value: 80 },
    { id: "dia:s:20", kind: "diameter", c: [0, -22, 0], axis: [0, 2, 0], r: 10, text: "Ø20 k6", label: "Journal", items: ["s"], prio: 1, sources: [] },
    { id: "size:p", kind: "label", at: [0, 0, 0], text: "m2 × 20", label: "Pinion size", items: ["p"], prio: 2, sources: [] },
  ];

  it("maps onto the viewport dimension layout (DS-038)", () => {
    const r = toResolved(dims);
    expect(r[0]).toMatchObject({ kind: "linear", s: 80, u: [1, 0, 0] });
    expect(r[1]).toMatchObject({ kind: "round", sym: "Ø", circles: [{ c: [0, -22, 0], axis: [0, 1, 0], r: 10 }] });
    expect(r[2]).toMatchObject({ kind: "tag", tag: "label", at: [[0, 0, 0]] });
  });

  it("shows key numbers always and a part's size when it is hot (or all sizes)", () => {
    expect(visibleDims(dims, null, false).map(d => d.id)).toEqual(["cd:IF-07", "dia:s:20"]);
    expect(visibleDims(dims, "p", false).map(d => d.id)).toEqual(["cd:IF-07", "dia:s:20", "size:p"]);
    expect(visibleDims(dims, null, true)).toHaveLength(3);
  });

  it("finds a plan row's item: by id, or by position and name after approval renumbers an edited plan", () => {
    const rows = { i_s1_p1: { name: "Shaft", at: [0, 0] as [number, number] }, i_s1_p2: { name: "Gear", at: [0, 1] as [number, number] } };
    expect(itemOfRow(rows, 0, 0, "Shaft", "s1", "p1")).toBe("i_s1_p1");
    expect(itemOfRow(rows, 0, 1, "Gear", "s1", "pnew7")).toBe("i_s1_p2");
    expect(itemOfRow(rows, 3, 3, "Gear", "sx", "py")).toBe("i_s1_p2");
    expect(itemOfRow(rows, 0, 2, "New part", "s1", "p9")).toBeNull();
  });

  it("signatures change with the plan", () => {
    expect(sig({ a: 1 })).toBe(sig({ a: 1 }));
    expect(sig({ a: 1 })).not.toBe(sig({ a: 2 }));
  });
});
