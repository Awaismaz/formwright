import { describe, expect, it } from "vitest";
import { stepScene } from "./MotionPanel";
import type { MotionResult } from "./types";

const m = {
  driver: "j1", driver_name: "Arm", unit: "°", start: 0, end: 360, worst: 1, colliding_steps: [1], summary: "", note: "",
  elapsed_s: 1, pairs_per_step: 1, joints: [],
  steps: [
    { i: 0, value: 0, values: { j1: 0 }, T: { a: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] }, collisions: [], total_mm3: 0 },
    { i: 1, value: 90, values: { j1: 90 }, T: { a: [0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0] }, total_mm3: 5,
      collisions: [{ a: "a", b: "p", a_name: "Arm<1>", b_name: "Pin<1>", volume_mm3: 5, center: [0, 70, 5], mesh: { pos: [0, 0, 0], idx: [0, 0, 0] } }] },
  ],
} as MotionResult;

describe("motion step scene", () => {
  it("places the moving parts and marks the colliding ones", () => {
    expect(stepScene(m, 0)).toEqual({ poses: m.steps[0].T, hot: [], meshes: [] });
    const s = stepScene(m, 1);
    expect(s.hot).toEqual(["a", "p"]);
    expect(s.meshes).toHaveLength(1);
    expect(s.poses?.a[1]).toBe(-1);
  });
  it("is empty without a result", () => {
    expect(stepScene(null, 0)).toEqual({ poses: null, hot: [], meshes: [] });
  });
});
