import { describe, expect, it } from "vitest";
import { etaSeconds, keepsGeometry, negativesToText, refineKey, sizeLabel, textToNegatives, wordCount, type AirSettings } from "./prompt";

const S: AirSettings = { scene: "studio", finish: "Brass", lighting: "softbox", camera: "match", background: "white",
  style: "photoreal", size: "1536x1024", quality: "medium", variants: 1 };
const CLAUSE = "Use the attached reference image as the exact geometry of the part.";

describe("airender prompt helpers", () => {
  it("round-trips negatives one per line, trimming bullets and duplicates", () => {
    expect(textToNegatives(negativesToText(["no text", "no people"]))).toEqual(["no text", "no people"]);
    expect(textToNegatives("- no text\n\n• no  people\nNo text\n")).toEqual(["no text", "no people"]);
    expect(textToNegatives(Array.from({ length: 20 }, (_, i) => `no ${i}`).join("\n"))).toHaveLength(12);
  });
  it("detects the geometry clause regardless of whitespace and case", () => {
    expect(keepsGeometry(`A part.\n${CLAUSE.toUpperCase()}`, CLAUSE)).toBe(true);
    expect(keepsGeometry("Use the attached  reference image as the exact\ngeometry of the part.", CLAUSE)).toBe(true);
    expect(keepsGeometry("A part on a table.", CLAUSE)).toBe(false);
  });
  it("marks the prompt stale only when prompt inputs change", () => {
    const k = refineKey(S, "warm");
    expect(refineKey({ ...S, size: "1024x1024", quality: "high", variants: 3 }, "warm ")).toBe(k);
    expect(refineKey({ ...S, scene: "workshop" }, "warm")).not.toBe(k);
    expect(refineKey(S, "cold")).not.toBe(k);
  });
  it("formats sizes, words and the wait", () => {
    expect(sizeLabel("1536x1024")).toBe("1536 × 1024");
    expect(wordCount("  a b\nc ")).toBe(3);
    expect(wordCount("")).toBe(0);
    expect(etaSeconds(45, 1)).toBe(45);
    expect(etaSeconds(20, 3)).toBe(34);
  });
});
