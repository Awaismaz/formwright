import { describe, expect, it } from "vitest";
import { paramLine, tokenLine } from "./smart";

describe("smart assembly helpers", () => {
  it("marks defaults the user did not write", () => {
    const meta = [{ name: "D", label: "Diameter", unit: "mm" }, { name: "L", label: "Length", unit: "mm" }] as never;
    expect(paramLine({ params: { D: 8, L: 20 }, read: ["D"] }, meta)).toBe("Diameter 8 mm · Length 20 mm (default)");
  });
  it("states token use honestly", () => {
    expect(tokenLine({ tokens: 0, ai_used: false })).toBe("0 tokens · read without AI");
    expect(tokenLine({ tokens: 120, ai_used: true })).toBe("AI reading: 120 tokens");
  });
});
