import { describe, expect, it } from "vitest";
import { EXAMPLES, FALLBACK_PACKS, FALLBACK_PLANS, defaultInputs, exampleCost, heroStats, hireYearOne, packTokenPrice, planYear, roi, topupCost } from "./roi";

const team = FALLBACK_PLANS.find(p => p.code === "team")!;

describe("top-up packs", () => {
  it("buys the cheapest combination that covers the shortfall", () => {
    expect(topupCost(0, FALLBACK_PACKS)).toBe(0);
    expect(topupCost(1, FALLBACK_PACKS)).toBe(1000);           // one 500 pack
    expect(topupCost(3000, FALLBACK_PACKS)).toBe(5500);        // 2,000 + 2 × 500 = $35 + $20
    expect(topupCost(9000, FALLBACK_PACKS)).toBe(15000);       // one 10,000 pack beats 4 × 2,000 + 2 × 500 ($160)
    expect(topupCost(10500, FALLBACK_PACKS)).toBe(16000);      // 10,000 + 500
  });
  it("prices example tokens at the smallest pack ($10 / 500 = $0.02)", () => {
    expect(packTokenPrice(FALLBACK_PACKS)).toBeCloseTo(0.02, 10);
  });
});

describe("ROI model", () => {
  it("default scenario: 10 medium parts, US$70/h, 25% review, Pro", () => {
    const r = roi(defaultInputs());
    expect(r.convHours).toBe(100);
    expect(r.convCost).toBe(7000);
    expect(r.fwHours).toBeCloseTo(27.5, 10);                  // 10 × (2.5 h review + 0.25 h brief)
    expect(r.fwLabour).toBeCloseTo(1925, 6);
    expect(r.tokens).toBe(4500);
    expect(r.extraTokens).toBe(3000);
    expect(r.topups).toBe(55);
    expect(r.subscription).toBe(49);
    expect(r.fwCost).toBeCloseTo(2029, 6);
    expect(r.monthlySaving).toBeCloseTo(4971, 6);
    expect(r.yearlySaving).toBeCloseTo(59652, 6);
    expect(r.costReduction).toBeCloseTo(4971 / 7000, 10);
    expect(r.speedUp).toBeCloseTo(100 / 27.5, 10);
    expect(r.firstModelSpeedUp).toBeCloseTo(28, 10);           // 10 h × 0.7 × 60 / 15 min
    expect(r.paybackDays).toBeCloseTo(104 / (5075 / 21), 10);  // under half a working day
  });

  it("20 simple parts offshore at 50% review on Team stays inside the pooled tokens", () => {
    const r = roi({ parts: 20, complexity: "simple", rate: 35, review: 0.5, plan: team, packs: FALLBACK_PACKS });
    expect(r.convCost).toBe(2450);
    expect(r.fwHours).toBeCloseTo(37, 10);
    expect(r.topups).toBe(0);
    expect(r.fwCost).toBeCloseTo(1295 + 199, 6);
    expect(r.monthlySaving).toBeCloseTo(956, 6);
    expect(r.speedUp).toBeCloseTo(70 / 37, 10);
  });

  it("reports no payback when review takes longer than doing the work by hand", () => {
    const r = roi({ ...defaultInputs(), review: 1.2 });
    expect(r.paybackDays).toBeNull();
    expect(r.monthlySaving).toBeLessThan(0);
  });

  it("zero parts costs only the subscription", () => {
    const r = roi({ ...defaultInputs(), parts: 0 });
    expect(r.fwCost).toBe(49);
    expect(r.costReduction).toBe(0);
  });

  it("hero stats come from the default scenario", () => {
    const h = heroStats(defaultInputs());
    expect(h.firstModel).toBeCloseTo(28, 10);
    expect(Math.round(h.costReduction * 100)).toBe(71);
    expect(h.throughput).toBeCloseTo(3.636, 3);
    expect(Math.round(h.yearly)).toBe(59652);
  });
});

describe("worked examples", () => {
  it("mounting plate: 3 to 4 h × $70 vs 150 to 250 tokens × $0.02 + 25% review", () => {
    const c = exampleCost(EXAMPLES.find(e => e.key === "plate")!, 70, 0.02, 0.25);
    expect(c.conv).toEqual([210, 280]);
    expect(c.tokensCost[0]).toBeCloseTo(3, 10);
    expect(c.tokensCost[1]).toBeCloseTo(5, 10);
    expect(c.reviewHours).toEqual([0.75, 1]);
    expect(c.fw[0]).toBeCloseTo(55.5, 10);
    expect(c.fw[1]).toBeCloseTo(75, 10);
  });
  it("planetary gearbox: 4,000 to 8,000 tokens ≈ $80 to 160", () => {
    const c = exampleCost(EXAMPLES.find(e => e.key === "gearbox")!, 70, 0.02, 0.25);
    expect(c.conv).toEqual([4200, 7000]);
    expect(c.tokensCost[0]).toBeCloseTo(80, 10);
    expect(c.tokensCost[1]).toBeCloseTo(160, 10);
  });
});

describe("hire vs buy", () => {
  it("loads the BLS median salary by 1.4 and adds a CAD seat and recruiting", () => {
    const h = hireYearOne();
    expect(h.loaded).toBeCloseTo(139314, 6);
    expect(h.hourly).toBeCloseTo(66.98, 2);
    expect(h.total).toBeCloseTo(150014, 6);
  });
  it("prices a Team year with monthly top-ups", () => {
    expect(planYear(team, 0, FALLBACK_PACKS)).toBe(2388);
    expect(planYear(team, 2000, FALLBACK_PACKS)).toBe(12 * (199 + 35));
  });
});

describe("formatting", () => {
  it("prints one currency prefix and collapses equal ends", async () => {
    const { range, usdRange } = await import("./roi");
    expect(usdRange([210, 280])).toBe("US$210 to 280");
    expect(range([73.2, 73.4], n => `${Math.round(n)}`)).toBe("73");
  });
});
