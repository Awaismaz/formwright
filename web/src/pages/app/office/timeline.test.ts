import { describe, expect, it } from "vitest";
import { bar, errorTone, explainUpdate, fmtClock, fmtError, niceStep, pxPerMin, rateLine, rowBreakdown, segmentTip, sparkline, ticks } from "./timeline";

describe("timeline axis", () => {
  it("picks a nice step and ticks past the span", () => {
    expect(niceStep(29)).toBe(5);          // 29 / 5 = 5.8 ticks <= 8
    expect(niceStep(3)).toBe(0.5);         // 6 ticks of 30 s
    expect(niceStep(0.2)).toBeCloseTo(5 / 60);
    expect(ticks(29)).toEqual([0, 5, 10, 15, 20, 25, 30]);
    expect(ticks(2.5, 6)).toEqual([0, 0.5, 1, 1.5, 2, 2.5]);
  });
  it("formats clock labels", () => {
    expect([fmtClock(0), fmtClock(0.5), fmtClock(2), fmtClock(90), fmtClock(120), fmtClock(2880)]).toEqual(["0", "30 s", "2 min", "1 h 30", "2 h", "2 d"]);
  });
  it("places bars and keeps short spells visible", () => {
    const ppm = pxPerMin(29, 580);
    expect(ppm).toBe(20);
    expect(bar(10, 15, ppm)).toEqual({ left: 200, width: 100 });
    expect(bar(1, 1.01, ppm)).toEqual({ left: 20, width: 3 });
    expect(pxPerMin(0, 100)).toBe(6000); // a span shorter than a second still draws
  });
});

describe("estimate vs actual", () => {
  it("formats the error and its tone", () => {
    expect([fmtError(-85), fmtError(25.4), fmtError(3), fmtError(null)]).toEqual(["−85 %", "+25 %", "on estimate", "-"]);
    expect([errorTone(20), errorTone(-60), errorTone(150), errorTone(undefined)]).toEqual(["success", "warning", "danger", "neutral"]);
  });
  it("sums work and waits of a row", () => {
    const r = rowBreakdown({ segments: [
      { stage: "capacity", kind: "capacity", agent: null, label: null, start: 0.1667, end: 1, open: false, what: "Waiting for capacity" },
      { stage: "design", kind: "work", agent: "mill", label: "Mill", start: 1, end: 2, open: false, what: "Design" },
      { stage: "review", kind: "work", agent: "gage", label: "Gage", start: 2, end: 2.5, open: false, what: "Gage review" },
      { stage: "blocked", kind: "blocked", agent: null, label: null, start: 3, end: 4, open: true, what: "Needs the engineer" }] });
    expect(r.work).toBeCloseTo(1.5);
    expect(r.waitCapacity).toBeCloseTo(0.8333);
    expect(r.blocked).toBe(1);
    expect(segmentTip({ what: "Design", label: "Mill #2", start: 1, end: 2, open: false })).toBe("Mill #2: Design · 1 min → 2 min (1 min)");
    expect(segmentTip({ what: "Needs the engineer", label: null, start: 3, end: 4, open: true })).toBe("Needs the engineer · 3 min → now (1 min)");
  });
});

describe("calibration panel", () => {
  it("explains a bounded EMA update with the server's numbers", () => {
    // the hand-computed case of tests/test_office_phase5.py: 4.0, 2 min at complexity 2 -> observed 1.0, clamped 2.0, 3.4
    const u = { ticket: "TR-1", actual_min: 2, estimate_min: 8, complexity: 2, observed: 1, clamped: 2, before: 4, after: 3.4 };
    expect(explainUpdate(u, 0.3)).toBe("TR-1 took 2 min at complexity 2: 1 min per unit, held to 2 (one ticket moves a rate at most ×2 or ÷2); "
      + "the rate moves 30 % of the way: 4 → 3.4.");
    expect(explainUpdate({ ...u, actual_min: 0.5, observed: 3.5, clamped: 3.5, complexity: 1, after: 3.85 }, 0.3))
      .toBe("TR-1 took 30 s at complexity 1: 3.5 min per unit; the rate moves 30 % of the way: 4 → 3.85.");
    expect(rateLine(4, 3.4)).toBe("4 → 3.4 min per unit");
    expect(rateLine(0.5, 0.5)).toBe("0.5 min per unit");
  });
  it("draws the accuracy trend", () => {
    expect(sparkline([], 100, 20)).toBe("");
    expect(sparkline([{ n: 1, mape: 50 }], 100, 20)).toBe("50,2");
    expect(sparkline([{ n: 1, mape: 50 }, { n: 2, mape: 25 }, { n: 3, mape: 0 }], 100, 20)).toBe("2,2 50,10 98,18");
  });
});
