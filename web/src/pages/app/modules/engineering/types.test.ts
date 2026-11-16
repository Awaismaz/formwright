import { describe, expect, it } from "vitest";
import { type CalcSchema, type Param, exampleKeys, initialForm } from "./types";

const param = (p: Partial<Param>): Param => ({
  key: "x", label: "x", kind: "length", default: null, unit: "mm", min: null, max: null, exclusive_min: false, help: "",
  group: "Inputs", optional: false, options: null, columns: null, show_if: null, prefill: null, ...p,
});

const calc: CalcSchema = {
  id: "shaft_fatigue", name: "Shaft", category: "", summary: "", version: "1", keywords: [], references: [], assumptions: [],
  verified_against: [], safety_factor: true, prefill: [], level: "preliminary_estimate",
  inputs: [
    param({ key: "d", kind: "length", default: 25 }),
    param({ key: "Ma", kind: "moment", default: 70000, unit: "N*m", units: [{ unit: "N*m", label: "N·m" }, { unit: "N*mm", label: "N·mm" }] }),
    param({ key: "Mm", kind: "moment", default: 0, unit: "N*m" }),
    param({ key: "Tm", kind: "moment", default: 45000, unit: "N*m" }),
  ],
};

describe("example load values (MAKE-19)", () => {
  it("flags non-zero textbook loads until they are edited", () => {
    const f = initialForm(calc);
    expect(exampleKeys(calc, f)).toEqual(["Ma", "Tm"]);   // d is geometry, Mm = 0 means "no load"
    expect(exampleKeys(calc, { ...f, Ma: { value: "80", unit: "N*m" } })).toEqual(["Tm"]);
  });
});
