import { describe, expect, it } from "vitest";
import { edgeMid, edgeRef } from "./measure";
import type { Topo } from "./types";

const topo = (pts: number[], type = "line"): Topo => ({ edges: [{ id: 0, type, pts, length: 0, faces: [], verts: [] }] } as unknown as Topo);

describe("edgeMid (STU-01)", () => {
  it("is the middle of a straight edge, never an end vertex", () => {
    expect(edgeMid(topo([-25, -10, 0, -25, -10, 10]), 0)).toEqual([-25, -10, 5]);
  });
  it("is halfway along a polyline by length", () => {
    // 0 → 10 along X, then 10 → 30 along Y: total 30, middle at 15 = 5 mm up the second segment
    expect(edgeMid(topo([0, 0, 0, 10, 0, 0, 10, 20, 0], "other"), 0)).toEqual([10, 5, 0]);
  });
  it("describes a straight edge by its direction", () => {
    expect(edgeRef(topo([1, 2, 0, 1, 2, 8]), 0)).toEqual({ kind: "line", dir: [0, 0, 1] });
  });
});
