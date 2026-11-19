/**
 * The "Why Formwright" cost model. Pure functions, no React: the hero stats, the worked examples, the ROI
 * calculator and the hire-vs-buy comparison all read from here, so every number on the page agrees.
 *
 * Everything below is a modelled estimate for illustration. Conventional hours are typical ranges for an
 * experienced engineer in a mainstream CAD tool (model + drawing + self-check); Formwright tokens follow the
 * measured typical run (a new part ~250 tokens, a change ~60) plus a few agent edits.
 */

export type Complexity = "simple" | "medium" | "complex";

export interface Profile {
  label: string;
  example: string;
  /** conventional engineer hours per part: model + drawing + self-check */
  convHours: number;
  /** share of `convHours` that is modelling (the rest is the drawing and checking) */
  modelShare: number;
  /** tokens per part including a few agent edits; drawings, checks and manual edits use none */
  tokens: number;
  /** engineer minutes from brief to first verified model (writing the brief, watching the run) */
  briefMinutes: number;
}

export const PROFILES: Record<Complexity, Profile> = {
  simple: { label: "Simple", example: "plates, brackets, spacers, shafts", convHours: 3.5, modelShare: 0.7, tokens: 200, briefMinutes: 6 },
  medium: { label: "Medium", example: "housings, enclosures, multi-feature parts", convHours: 10, modelShare: 0.7, tokens: 450, briefMinutes: 15 },
  complex: { label: "Complex", example: "castings, multi-body parts, small assemblies", convHours: 30, modelShare: 0.7, tokens: 1200, briefMinutes: 45 },
};

export interface PlanLike { code: string; name: string; price_cents: number; tokens: number; seats: number }
export interface PackLike { tokens: number; price_cents: number }

/** Mirrors `src/aicad/platform/catalog.py`; used until the live catalog loads (and in tests). */
export const FALLBACK_PLANS: PlanLike[] = [
  { code: "pro", name: "Pro", price_cents: 4900, tokens: 1500, seats: 1 },
  { code: "team", name: "Team", price_cents: 19900, tokens: 7500, seats: 5 },
];
export const FALLBACK_PACKS: PackLike[] = [
  { tokens: 500, price_cents: 1000 }, { tokens: 2000, price_cents: 3500 }, { tokens: 10000, price_cents: 15000 },
];

export const RATE_PRESETS = [
  { key: "us", label: "US employee", rate: 70, note: "BLS median pay × 1.4 overhead" },
  { key: "consultancy", label: "Consultancy", rate: 110, note: "typical US$75 to 150/h" },
  { key: "offshore", label: "Offshore", rate: 35, note: "typical US$25 to 50/h" },
] as const;

export const WORKDAYS_PER_MONTH = 21;

/** Cheapest combination of top-up packs that covers `extra` tokens, in cents. */
export function topupCost(extra: number, packs: PackLike[]): number {
  if (extra <= 0 || !packs.length) return 0;
  const ps = [...packs].sort((a, b) => b.tokens - a.tokens);
  const best = (i: number, rem: number): number => {
    if (rem <= 0) return 0;
    const p = ps[i]!;
    const max = Math.ceil(rem / p.tokens);
    if (i === ps.length - 1) return max * p.price_cents;
    let b = Infinity;
    for (let n = 0; n <= max; n++) b = Math.min(b, n * p.price_cents + best(i + 1, rem - n * p.tokens));
    return b;
  };
  return best(0, extra);
}

/** Highest per-token price among the packs (the smallest pack): the conservative price used in examples. */
export function packTokenPrice(packs: PackLike[]): number {
  return packs.length ? Math.max(...packs.map(p => p.price_cents / p.tokens)) / 100 : 0.02;
}

export interface Inputs {
  parts: number;
  complexity: Complexity;
  /** fully loaded engineer cost, US$/h */
  rate: number;
  /** share of conventional hours the engineer still spends reviewing and signing off (0 to 1) */
  review: number;
  plan: PlanLike;
  packs: PackLike[];
}

export interface Result {
  convHours: number; convCost: number;
  fwHours: number; fwLabour: number; tokens: number; extraTokens: number; topups: number; subscription: number;
  fwCost: number; monthlySaving: number; yearlySaving: number; costReduction: number;
  speedUp: number; firstModelSpeedUp: number;
  /** working days until the month's subscription and top-ups are paid back by labour saved; null if never */
  paybackDays: number | null;
}

export function roi(i: Inputs): Result {
  const p = PROFILES[i.complexity];
  const parts = Math.max(0, i.parts);
  const convHours = parts * p.convHours;
  const convCost = convHours * i.rate;
  const fwHours = parts * (i.review * p.convHours + p.briefMinutes / 60);
  const fwLabour = fwHours * i.rate;
  const tokens = parts * p.tokens;
  const extraTokens = Math.max(0, tokens - i.plan.tokens);
  const topups = topupCost(extraTokens, i.packs) / 100;
  const subscription = i.plan.price_cents / 100;
  const fwCost = fwLabour + subscription + topups;
  const monthlySaving = convCost - fwCost;
  const labourSaved = convCost - fwLabour;
  return {
    convHours, convCost, fwHours, fwLabour, tokens, extraTokens, topups, subscription, fwCost,
    monthlySaving, yearlySaving: monthlySaving * 12,
    costReduction: convCost > 0 ? monthlySaving / convCost : 0,
    speedUp: fwHours > 0 ? convHours / fwHours : 0,
    firstModelSpeedUp: (p.convHours * p.modelShare * 60) / p.briefMinutes,
    paybackDays: labourSaved > 0 ? (subscription + topups) / (labourSaved / WORKDAYS_PER_MONTH) : null,
  };
}

/** The calculator's opening scenario; the hero stats are computed from it. */
export function defaultInputs(plans: PlanLike[] = FALLBACK_PLANS, packs: PackLike[] = FALLBACK_PACKS): Inputs {
  return { parts: 10, complexity: "medium", rate: 70, review: 0.25, plan: plans.find(p => p.code === "pro") ?? plans[0]!, packs };
}

export interface HeroStats { firstModel: number; costReduction: number; throughput: number; yearly: number; parts: number; rate: number }

export function heroStats(inp: Inputs): HeroStats {
  const r = roi(inp);
  return { firstModel: r.firstModelSpeedUp, costReduction: r.costReduction, throughput: r.speedUp, yearly: r.yearlySaving, parts: inp.parts, rate: inp.rate };
}

/* ---------------------------------------------------------------- worked examples */

export interface Example {
  key: string; title: string; body: string;
  convHours: [number, number]; convCalendar: string; convSteps: string;
  tokens: [number, number]; fwTime: string; fwSteps: string;
}

export const EXAMPLES: Example[] = [
  { key: "plate", title: "Mounting plate", body: "120 × 80 × 10 mm plate, 4 × M6 hole pattern, 2 mm pocket, edge chamfers, A3 drawing.",
    convHours: [3, 4], convCalendar: "same day", convSteps: "Sketch, extrude, hole wizard, pocket, chamfers, drawing views, dimensions, self-check.",
    tokens: [150, 250], fwTime: "~5 min", fwSteps: "One-paragraph brief, agent builds and checks, drawing generated." },
  { key: "bracket", title: "L-bracket with gusset", body: "6 mm folded L-bracket, slotted holes, triangular gusset, inside fillets, drawing.",
    convHours: [3, 5], convCalendar: "same day", convSteps: "Base flange, wall, gusset rib, slots, fillets, drawing, self-check.",
    tokens: [180, 300], fwTime: "~6 min", fwSteps: "Brief, agent build, one dimension tweak by parameter edit (free)." },
  { key: "shaft", title: "Stepped shaft with keyway", body: "Ø20/25/30 mm stepped shaft, DIN 6885 keyway, circlip groove, chamfers, drawing.",
    convHours: [3, 4.5], convCalendar: "same day", convSteps: "Revolve profile, keyway cut, groove, chamfers, drawing with section.",
    tokens: [150, 300], fwTime: "~5 min", fwSteps: "Brief, agent build, keyway sized from the standard table." },
  { key: "enclosure", title: "Electronics enclosure", body: "Two-part ABS enclosure: shelled base and lid, screw bosses, lip and groove, vents, PCB standoffs.",
    convHours: [12, 18], convCalendar: "2 to 3 days", convSteps: "Base, shell, bosses, lip, lid, matching features, interference check, two drawings.",
    tokens: [600, 1000], fwTime: "~20 min", fwSteps: "Brief per part, agent edits, exact interference check in assembly." },
  { key: "gearbox", title: "Planetary gearbox", body: "Single-stage planetary, 15 to 20 parts: sun, planets, ring, carrier, housing, bearings, fasteners, BOM and drawings.",
    convHours: [60, 100], convCalendar: "2 to 3 weeks", convSteps: "Gear geometry, housing, carrier, standard parts, assembly mates, interference, BOM, drawing set.",
    tokens: [4000, 8000], fwTime: "a few hours", fwSteps: "Design Office plans the program; specialist agents model in parallel; Toolbox supplies bearings and fasteners." },
];

export interface ExampleCost {
  conv: [number, number];
  tokensCost: [number, number];
  reviewHours: [number, number];
  reviewCost: [number, number];
  fw: [number, number];
  saving: [number, number];
}

/** Conventional = hours × rate. Formwright = tokens × token price + review share of conventional hours × rate. */
export function exampleCost(e: Example, rate: number, tokenPrice: number, review: number): ExampleCost {
  const conv: [number, number] = [e.convHours[0] * rate, e.convHours[1] * rate];
  const tokensCost: [number, number] = [e.tokens[0] * tokenPrice, e.tokens[1] * tokenPrice];
  const reviewHours: [number, number] = [e.convHours[0] * review, e.convHours[1] * review];
  const reviewCost: [number, number] = [reviewHours[0] * rate, reviewHours[1] * rate];
  const fw: [number, number] = [tokensCost[0] + reviewCost[0], tokensCost[1] + reviewCost[1]];
  return { conv, tokensCost, reviewHours, reviewCost, fw, saving: [1 - fw[0] / conv[0], 1 - fw[1] / conv[1]] };
}

/* ---------------------------------------------------------------- hire vs buy */

export const HIRE = {
  salary: 99_510,     // BLS OOH, mechanical engineers, median pay May 2023
  overhead: 1.4,      // wages ≈ 70% of total compensation (BLS ECEC)
  cadSeat: 6_000,     // CAD + PDM seat, mid-point of US$4 to 8k/yr
  recruiting: 4_700,  // SHRM average cost per hire
  hoursPerYear: 2_080,
};

export function hireYearOne(h = HIRE) {
  const loaded = h.salary * h.overhead;
  return { loaded, hourly: loaded / h.hoursPerYear, total: loaded + h.cadSeat + h.recruiting };
}

export function planYear(plan: PlanLike, extraTokensPerMonth: number, packs: PackLike[]) {
  return 12 * (plan.price_cents / 100 + topupCost(extraTokensPerMonth, packs) / 100);
}

/* ---------------------------------------------------------------- formatting */

export const usd = (v: number, digits = 0) =>
  `${v < 0 ? "−" : ""}US$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;

/** "$1.2k" / "$59k" style for compact stat tiles. */
export function usdShort(v: number) {
  const a = Math.abs(v);
  const s = a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e4 ? `${Math.round(a / 1e3)}k` : a >= 1e3 ? `${(a / 1e3).toFixed(1)}k` : `${Math.round(a)}`;
  return `${v < 0 ? "−" : ""}$${s}`;
}

export function range(r: [number, number], f: (n: number) => string) {
  const a = f(r[0]), b = f(r[1]);
  return a === b ? a : `${a} to ${b}`;
}

/** "US$210 to 280": one currency prefix for a money range. */
export const usdRange = (r: [number, number]) => range(r, n => usd(n)).replace(" to US$", " to ");
