import { describe, expect, it } from "vitest";
import { parse } from "./commands";

describe("typed Studio commands (IDEA 5)", () => {
  it("reads feature verbs with sizes", () => {
    expect(parse("fillet 3")).toEqual({ kind: "fillet", size: 3 });
    expect(parse("Round R2.5")).toEqual({ kind: "fillet", size: 2.5 });
    expect(parse("chamfer 1 mm")).toEqual({ kind: "chamfer", size: 1 });
    expect(parse("fillet")).toBeNull();
  });
  it("reads Hole Wizard requests", () => {
    expect(parse("hole M6 x4 10 from edges")).toEqual({ kind: "hole", type: "clearance", size: 6, count: 4, edge: 10 });
    expect(parse("tapped hole m8")).toEqual({ kind: "hole", type: "tapped", size: 8 });
    expect(parse("cbore M5")).toEqual({ kind: "hole", type: "cbore", size: 5 });
    expect(parse("hole 6.6")).toEqual({ kind: "hole", type: "simple", d: 6.6 });
  });
  it("reads views and tree actions", () => {
    expect(parse("view top")).toEqual({ kind: "view", view: "Top" });
    expect(parse("iso")).toEqual({ kind: "view", view: "Iso" });
    expect(parse("zoom to fit")).toEqual({ kind: "fit" });
    expect(parse("suppress Centre pocket")).toEqual({ kind: "suppress", name: "Centre pocket" });
    expect(parse("make it nicer")).toBeNull();
  });
});
