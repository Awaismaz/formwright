import { describe, expect, it } from "vitest";
import {
  assemblable, carrierSpeed, centreDistance, meshResiduals, planetPhase, planetSpin, pose, ratio, spinUp, type GearSet,
} from "./kinematics";
import manifest from "./gearbox.json";

const PG5: GearSet = { zs: 18, zp: 27, zr: 72, n: 3, m: 1.5 };

describe("planetary kinematics (hand-computed)", () => {
  it("PG-5: ratio 1 + 72/18 = 5, a = 1.5·45/2 = 33.75, assembly (18+72)/3 = 30", () => {
    expect(ratio(PG5)).toBe(5);
    expect(centreDistance(PG5)).toBeCloseTo(33.75, 12);
    expect(assemblable(PG5)).toBe(true);
    expect(assemblable({ ...PG5, n: 4 })).toBe(false); // 90/4 not whole
    expect(assemblable({ ...PG5, zr: 70 })).toBe(false); // not coaxial
  });

  it("carrier turns at 1/5 of the sun; planets spin backwards at -(5/3)·ωc", () => {
    expect(carrierSpeed(10, PG5)).toBeCloseTo(2, 12); // 10 · 18/90
    expect(planetSpin(10, PG5)).toBeCloseTo(-10 / 3, 12); // 2 · (1 − 72/27) = 2 · (−45/27)
    // 600 rpm motor -> 120 rpm output
    expect(carrierSpeed(600, PG5)).toBeCloseTo(120, 12);
  });

  it("Willis equations hold for both meshes", () => {
    const ws = 7, wc = carrierSpeed(ws, PG5), wp = planetSpin(ws, PG5);
    expect((ws - wc) / (wp - wc)).toBeCloseTo(-PG5.zp / PG5.zs, 12); // external sun/planet
    expect((0 - wc) / (wp - wc)).toBeCloseTo(PG5.zp / PG5.zr, 12); // internal ring/planet, ring fixed
  });

  it("PG-5 planet phases are all 0: θk(1 − Zr/Zp) = 120°·(−5/3) = −200° = −15 planet pitches", () => {
    for (const k of [0, 1, 2]) expect(planetPhase(k, PG5)).toBeCloseTo(0, 9);
  });

  it("a set with a half-pitch planet phase: 13/25/63 × 4 gives 0, π/25, 0, π/25", () => {
    const g: GearSet = { zs: 13, zp: 25, zr: 63, n: 4, m: 1 };
    expect(assemblable(g)).toBe(true);
    // k=1: 90°·(1 − 63/25) = −136.8° = −9.5 pitches of 14.4°
    expect(planetPhase(0, g)).toBeCloseTo(0, 9);
    expect(planetPhase(1, g)).toBeCloseTo(Math.PI / 25, 9);
    expect(planetPhase(2, g)).toBeCloseTo(0, 9);
    expect(planetPhase(3, g)).toBeCloseTo(Math.PI / 25, 9);
  });

  it("teeth stay meshed with the ring and the sun at every sun angle", () => {
    for (const g of [PG5, { zs: 13, zp: 25, zr: 63, n: 4, m: 1 }]) {
      for (const a of [0, 0.37, 1, 2.5, 12.3, -4]) {
        const p = pose(a, g);
        for (let k = 0; k < g.n; k++) {
          const r = meshResiduals(p, k, g);
          expect(r.ring).toBeLessThan(1e-9);
          expect(r.sun).toBeLessThan(1e-9);
        }
      }
    }
    // a planet turned by half a pitch is NOT meshed
    const p = pose(0, PG5);
    p.planets[0]!.spin += Math.PI / PG5.zp;
    expect(meshResiduals(p, 0, PG5).ring).toBeCloseTo(Math.PI, 9);
  });

  it("the carrier and planet centres move together; one sun turn = 1/5 carrier turn", () => {
    const p = pose(2 * Math.PI, PG5);
    expect(p.carrier).toBeCloseTo((2 * Math.PI) / 5, 12);
    expect(p.planets[1]!.centre).toBeCloseTo((2 * Math.PI) / 3 + (2 * Math.PI) / 5, 12);
  });

  it("spin-up starts at rest and approaches steady speed", () => {
    expect(spinUp(0, 3)).toBe(0);
    expect(spinUp(-1, 3)).toBe(0);
    const d = (spinUp(20.01, 3) - spinUp(20, 3)) / 0.01;
    expect(d).toBeCloseTo(3, 3);
  });

  it("the generated assets match this gear set", () => {
    expect(manifest.gear).toMatchObject({ zs: 18, zp: 27, zr: 72, n: 3, m: 1.5, a: 33.75 });
    expect(manifest.planetAngles).toEqual([0, 120, 240]);
  });
});
