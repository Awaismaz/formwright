/** The scripted hero replay: a brief is typed, the agent plans, builds three features, runs the gating checks. */

export const PROMPT = "6061 flange Ø150 × 16, Ø60 bore, 6 × Ø14 on PCD 120";
export const LOOP = 14;

const TYPE_START = 0.5;
const PER_CHAR = 0.038;
export const SENT_AT = TYPE_START + PROMPT.length * PER_CHAR + 0.35;

export const FEATURES = [
  { name: "Base disc Ø150 × 16", at: SENT_AT + 1.7 },
  { name: "Bore Ø60 through", at: SENT_AT + 2.7 },
  { name: "6 × Ø14 on PCD 120", at: SENT_AT + 3.7 },
] as const;

/** The real gating check names and the values this flange produces (volume = π/4·(150² − 60² − 6·14²)·16). */
export const CHECKS = [
  ["Valid solid", "1 solid"],
  ["Bounding box", "150 × 150 × 16"],
  ["Volume", "Δ 0.000%"],
  ["STEP round-trip", "identical"],
  ["Deterministic", "byte-equal"],
] as const;
const CHECKS_AT = SENT_AT + 4.3;
const CHECK_GAP = 0.4;
export const DONE_AT = CHECKS_AT + CHECKS.length * CHECK_GAP + 0.3;

export type HeroPhase = "typing" | "plan" | "build" | "inspect" | "done";
export type HeroFrame = {
  typed: string; sent: boolean; interpreted: boolean; phase: HeroPhase;
  features: number; checks: number; done: boolean; step: boolean; progress: number;
};

export function heroFrame(t: number): HeroFrame {
  const chars = Math.max(0, Math.min(PROMPT.length, Math.floor((t - TYPE_START) / PER_CHAR)));
  const sent = t >= SENT_AT;
  const features = FEATURES.filter(f => t >= f.at).length;
  const checks = t < CHECKS_AT ? 0 : Math.min(CHECKS.length, Math.floor((t - CHECKS_AT) / CHECK_GAP) + 1);
  const done = t >= DONE_AT;
  const phase: HeroPhase = !sent ? "typing" : done ? "done" : t >= CHECKS_AT - 0.3 ? "inspect" : t >= FEATURES[0].at - 0.6 ? "build" : "plan";
  return {
    typed: PROMPT.slice(0, chars), sent, interpreted: t >= SENT_AT + 1.0, phase, features, checks, done,
    step: t >= DONE_AT + 0.5, progress: Math.min(1, t / LOOP),
  };
}

/** The settled end state, shown when motion is reduced. */
export const FINAL = heroFrame(LOOP - 0.01);
