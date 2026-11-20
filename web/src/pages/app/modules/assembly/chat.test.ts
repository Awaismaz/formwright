import { describe, expect, it } from "vitest";
import { answerText, liveQuestions, replyMeta, sayBody, stateTone, type ChatMessage } from "./chat";

describe("assembly chat helpers", () => {
  it("sends the question with the chosen chip", () => {
    const q = { id: "q1", question: "Which shaft does the gear go on?", options: ["A", "B"], default: null, multi: false, other: true };
    expect(answerText(q, "B")).toBe("Which shaft does the gear go on? B");
  });
  it("states time and tokens honestly", () => {
    expect(replyMeta({ seconds: 3.24, tokens: 4, offline: false })).toBe("3.2 s · 4 tokens");
    expect(replyMeta({ seconds: 42.6, tokens: 1, offline: false })).toBe("43 s · 1 token");
    expect(replyMeta({ seconds: 0.5, tokens: 0, offline: true })).toBe("0.5 s · no AI used");
  });
  it("colours the state by what the solver and the checks say", () => {
    const base = { parts: 3, mates: 6, ok: 6, bad: 0, unplaced: 0, unplaced_names: [], clashes: 0 };
    expect(stateTone(base)).toBe("success");
    expect(stateTone({ ...base, unplaced: 1 })).toBe("warning");
    expect(stateTone({ ...base, clashes: 2 })).toBe("danger");
    expect(stateTone({ ...base, bad: 1 })).toBe("danger");
    expect(stateTone(null)).toBe("neutral");
  });
  it("keeps chips live until the engineer answers", () => {
    const m = (role: "user" | "agent"): ChatMessage => ({ id: role, role, text: "", at: "" });
    const msgs = [m("user"), m("agent")];
    expect(liveQuestions(msgs, 1, false)).toBe(true);
    expect(liveQuestions(msgs, 1, true)).toBe(false);
    expect(liveQuestions([...msgs, m("user")], 1, false)).toBe(false);
  });
});

describe("ASM-OW: answers to a design job's question", () => {
  it("go to that job, anything else is a normal turn", () => {
    expect(sayBody("Spline gear: Hub length? 20 mm", "j12")).toEqual({ text: "Spline gear: Hub length? 20 mm", job: "j12" });
    expect(sayBody("check for clashes")).toEqual({ text: "check for clashes" });
    expect(sayBody("x", null)).toEqual({ text: "x" });
  });
});
