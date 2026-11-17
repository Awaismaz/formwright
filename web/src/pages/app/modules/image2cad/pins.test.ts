import { describe, expect, it } from "vitest";
import { spreadPins } from "./pins";

describe("spreadPins", () => {
  it("leaves separate pins where they are", () => {
    const off = spreadPins([{ id: "a", x: 0.1, y: 0.1 }, { id: "b", x: 0.5, y: 0.5 }], 1000, 800, 1);
    expect(off).toEqual({ a: 0, b: 0 });
  });

  it("steps overlapping pins sideways until clear, in reading order", () => {
    // 1000 px wide image at 50 % zoom: 0.01 apart = 5 screen px, well inside a 22 px pin
    const pins = [{ id: "p6", x: 0.41, y: 0.3 }, { id: "p5", x: 0.40, y: 0.3 }, { id: "p7", x: 0.42, y: 0.3 }];
    const off = spreadPins(pins, 1000, 800, 0.5);
    expect(off.p5).toBe(0);
    const xs = ["p5", "p6", "p7"].map(id => (pins.find(p => p.id === id)!.x * 1000 * 0.5) + off[id]!);
    for (let i = 1; i < xs.length; i++) expect(Math.abs(xs[i]! - xs[i - 1]!)).toBeGreaterThanOrEqual(22);
  });

  it("needs no offset once zoomed in far enough", () => {
    const off = spreadPins([{ id: "a", x: 0.40, y: 0.3 }, { id: "b", x: 0.41, y: 0.3 }], 1000, 800, 4);
    expect(off).toEqual({ a: 0, b: 0 });
  });
});
