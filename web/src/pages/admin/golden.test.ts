import { describe, expect, it } from "vitest";
import { caseSummaries, expectationGrid, fmt, rollingPassRate, sparkPath, suiteSummary, type GoldenCase, type GoldenRun } from "./golden";

const run = (o: Partial<GoldenRun>): GoldenRun => ({
  run_id: Math.random().toString(36).slice(2), suite_id: "s1", at: "2026-11-20T10:00:00Z", sha: "abc", mode: "simulated",
  case: "a", title: "Case A", letter: "a", passed: true, status: "complete", metrics: { wall_s: 10, tokens: 0 },
  expectations: [], ...o,
});

const cases: GoldenCase[] = [{ id: "a", title: "Case A", letter: "a", fast: true }, { id: "b", title: "Case B", letter: "b", fast: false }];

describe("golden suite dashboard shaping", () => {
  it("rolls the pass rate over a window", () => {
    const rs = [true, false, true, true].map((p, i) => run({ passed: p, at: `2026-11-20T10:0${i}:00Z` }));
    expect(rollingPassRate(rs, 2)).toEqual([1, 0.5, 0.5, 1]);
    expect(rollingPassRate(rs, 5)).toEqual([1, 0.5, 2 / 3, 0.75]);
  });

  it("summarises each case in its mode, latest last, with what fails and whether it changed", () => {
    const rs = [
      run({ at: "2026-11-20T10:00:00Z", passed: true, metrics: { wall_s: 20, tokens: 0 } }),
      run({ at: "2026-11-20T11:00:00Z", passed: false, metrics: { wall_s: 25, tokens: 0 },
        expectations: [{ id: "clashes", label: "Clashes", ok: false, got: 2, want: 0 }, { id: "parts", label: "Parts", ok: true, got: 3, want: 3 }] }),
      run({ at: "2026-11-20T10:30:00Z", mode: "live", passed: true, metrics: { wall_s: 120, tokens: 34 } }),
    ];
    const [a, b] = caseSummaries(cases, rs, "simulated");
    expect(a!.runs).toBe(2);
    expect(a!.latest!.at).toBe("2026-11-20T11:00:00Z");
    expect(a!.wall).toEqual([20, 25]);
    expect(a!.failing.map(f => f.id)).toEqual(["clashes"]);
    expect(a!.changed).toBe("worse");
    expect(b!.latest).toBeNull();
    const live = caseSummaries(cases, rs, "live");
    expect(live[0]!.tokens).toEqual([34]);
    expect(live[0]!.changed).toBeNull();
  });

  it("keeps cases that are only in the history", () => {
    const rows = caseSummaries(cases, [run({ case: "old", title: "Retired case" })], "simulated");
    expect(rows.map(r => r.id)).toEqual(["a", "b", "old"]);
  });

  it("builds the summary row per suite run", () => {
    const rs = [
      run({ suite_id: "s1", case: "a", passed: true, at: "2026-11-20T10:00:00Z", metrics: { wall_s: 10, tokens: 0 } }),
      run({ suite_id: "s1", case: "b", passed: false, at: "2026-11-20T10:01:00Z", metrics: { wall_s: 30, tokens: 5 } }),
      run({ suite_id: "s2", case: "a", passed: true, at: "2026-11-20T12:00:00Z", metrics: { wall_s: 12, tokens: 0 } }),
      run({ suite_id: "s2", case: "b", passed: true, at: "2026-11-20T12:01:00Z", sha: "def", metrics: { wall_s: 28, tokens: 0 } }),
    ];
    const s = suiteSummary(caseSummaries(cases, rs, "simulated"), rs, "simulated");
    expect([s.cases, s.withRuns, s.passing, s.failing, s.notRun]).toEqual([2, 2, 2, 0, 0]);
    expect(s.passRate).toEqual([0.5, 1]);
    expect(s.wall).toEqual([40, 40]);
    expect(s.tokens).toEqual([5, 0]);
    expect(s.wallTotal).toBe(40);
    expect([s.lastAt, s.sha]).toEqual(["2026-11-20T12:01:00Z", "def"]);
  });

  it("draws sparklines with gaps and flat series", () => {
    expect(sparkPath([], 100, 20)).toBe("");
    expect(sparkPath([5], 100, 20)).toBe("M50.0,10.0");
    expect(sparkPath([1, 1], 100, 20)).toBe("M2.0,10.0L98.0,10.0");
    expect(sparkPath([0, null, 10], 100, 20)).toBe("M2.0,18.0M98.0,2.0");
  });

  it("formats measured values plainly", () => {
    expect(fmt(null)).toBe("n/a");
    expect(fmt(true)).toBe("yes");
    expect(fmt(6.50001)).toBe("6.5");
    expect(fmt([[6.5, -10, 0]])).toBe("[[6.5, -10, 0]]");
    expect(fmt({ shaft: 1, gear: 1 })).toBe("shaft 1, gear 1");
    expect(fmt({})).toBe("none");
  });

  it("lays out the expectation grid over the last runs", () => {
    const rs = [
      run({ at: "2026-11-20T10:00:00Z", expectations: [{ id: "parts", label: "Parts", ok: true, got: 3, want: 3 }] }),
      run({ at: "2026-11-20T11:00:00Z", expectations: [{ id: "parts", label: "Parts", ok: true, got: 3, want: 3 }, { id: "clashes", label: "Clashes", ok: false, got: 1, want: 0 }] }),
    ];
    const g = expectationGrid(rs, 8);
    expect(g.ids.map(i => i.id)).toEqual(["parts", "clashes"]);
    expect(g.cols.map(c => c.at)).toEqual(["2026-11-20T10:00:00Z", "2026-11-20T11:00:00Z"]);
  });
});
