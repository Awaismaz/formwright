import { describe, expect, it } from "vitest";
import { briefPrompt } from "./AgentCards";

describe("briefPrompt", () => {
  const b = { title: "Plate", requirements: ["80 × 50 × 6 mm"], assumptions: ["6061-T6"], questions: [{ question: "Edge break?", default: "0.5 mm" }, { question: "Finish?", default: null }] };
  it("composes the approved brief the server recognises", () => {
    const t = briefPrompt(b, { 1: "anodised" });
    expect(t.startsWith("Approved design brief")).toBe(true);
    expect(t).toContain("- 80 × 50 × 6 mm");
    expect(t).toContain("- Edge break? 0.5 mm");
    expect(t).toContain("- Finish? anodised");
  });
  it("leaves unanswered questions to the agent, labelled", () => {
    expect(briefPrompt({ ...b, assumptions: [] }, {})).toContain("- Finish? your call; state the assumption");
  });
});
