import { describe, expect, it } from "vitest";
import { CHECKS, DONE_AT, FEATURES, FINAL, LOOP, PROMPT, SENT_AT, heroFrame } from "./heroTimeline";

describe("hero replay timeline", () => {
  it("types the brief, then plans, builds, inspects and finishes in order", () => {
    expect(heroFrame(0).typed).toBe("");
    expect(heroFrame(SENT_AT - 0.01).typed).toBe(PROMPT);
    expect(heroFrame(SENT_AT - 0.01).phase).toBe("typing");
    const order = ["typing", "plan", "build", "inspect", "done"];
    let last = 0;
    for (let t = 0; t < LOOP; t += 0.05) {
      const i = order.indexOf(heroFrame(t).phase);
      expect(i).toBeGreaterThanOrEqual(last);
      last = i;
    }
    expect(last).toBe(4);
  });

  it("adds features before any check runs, and every check passes before done", () => {
    expect(heroFrame(FEATURES[2].at).features).toBe(3);
    expect(heroFrame(FEATURES[2].at).checks).toBe(0);
    expect(heroFrame(DONE_AT).checks).toBe(CHECKS.length);
    expect(DONE_AT).toBeLessThan(LOOP - 2); // the finished state holds on screen before the loop restarts
  });

  it("settles to the complete state for reduced motion", () => {
    expect(FINAL).toMatchObject({ typed: PROMPT, features: 3, checks: CHECKS.length, done: true, step: true });
  });
});
