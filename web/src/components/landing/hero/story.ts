/**
 * The hero's scripted Design Office run for the planetary gearbox PG-5: one deterministic timeline (seconds) from the
 * brief to the running gearbox. Everything on screen is a pure function of the story time, so it can loop, scrub
 * and jump between chapters.
 */

export const CHAPTERS = [
  { id: "brief", label: "Brief", start: 0 },
  { id: "plan", label: "Plan", start: 7.6 },
  { id: "board", label: "Board", start: 15.4 },
  { id: "build", label: "Build", start: 24.6 },
  { id: "assemble", label: "Assemble", start: 31.4 },
  { id: "run", label: "Run", start: 39.2 },
] as const;
export type ChapterId = (typeof CHAPTERS)[number]["id"];
export const LOOP = 52;

export function chapterAt(t: number): number {
  let i = 0;
  CHAPTERS.forEach((c, k) => { if (t >= c.start) i = k; });
  return i;
}
export const chapterStart = (id: ChapterId) => CHAPTERS.find(c => c.id === id)!.start;
export const chapterEnd = (i: number) => (i + 1 < CHAPTERS.length ? CHAPTERS[i + 1]!.start : LOOP);

/** 0..1 progress of t through [a, b], clamped. */
export const span = (t: number, a: number, b: number) => (t <= a ? 0 : t >= b ? 1 : (t - a) / (b - a));
export const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const easeOut = (x: number) => 1 - Math.pow(1 - x, 3);

// ------------------------------------------------------------------ a. brief
export const BRIEF =
  "Design a planetary gearbox, 5:1, for a NEMA 23 motor (Ø6.35 shaft), 12 Nm at the output. Ring fixed, sun in, " +
  "carrier out: sun 18T, 3 × planet 27T, internal ring 72T, module 1.5, 20° pressure angle, face width 12. " +
  "Two-part aluminium housing with a square flange mount, 2 × 6204-2RS on the output shaft, 6000 bearings in the " +
  "planets, M5 cap screws and Ø5 dowels. Keep the output flange ready for a second stage.";
const TYPE_AT = 0.5;
const TYPE_END = 6.3;
export const SEND_AT = 6.8;
export const typedChars = (t: number) => Math.round(BRIEF.length * span(t, TYPE_AT, TYPE_END));

// ------------------------------------------------------------------ b. plan
export type PlanNode = { name: string; detail?: string; agent: string; children?: PlanNode[] };
export const PLAN: PlanNode = {
  name: "PG-5 Planetary gearbox 5:1", agent: "archie", children: [
    { name: "Housing", agent: "mill", children: [
      { name: "Input cover", detail: "6001 seat · 6 × M5", agent: "mill" },
      { name: "Output cover", detail: "140 □ flange · 2 × 6204 seats", agent: "mill" },
      { name: "Motor flange", detail: "NEMA 23 · 47.14 □ · Ø38.1 pilot", agent: "mill" },
    ] },
    { name: "Planet carrier", agent: "mill", children: [
      { name: "Carrier plates A + B", detail: "pins on PCD 67.5", agent: "mill" },
      { name: "Planet pins × 3", detail: "Ø10 × 24", agent: "chuck" },
      { name: "Output shaft", detail: "Ø20 / Ø16 · key 5 × 5", agent: "chuck" },
    ] },
    { name: "Gear set", agent: "axel", children: [
      { name: "Sun 18T", detail: "m1.5 · on input shaft", agent: "axel" },
      { name: "Planet 27T × 3", detail: "m1.5 · 6000 inside", agent: "axel" },
      { name: "Ring 72T internal", detail: "fixed · 6 × M5 · 2 dowels", agent: "axel" },
    ] },
    { name: "Input shaft", detail: "Ø6.35 motor socket", agent: "chuck" },
    { name: "Standard parts", detail: "6204-2RS × 2 · 6001 · 6000 × 3 · M5 × 35 × 6 · Ø5 × 16 × 2", agent: "hex" },
  ],
};
/** Flattened plan rows with their reveal time. */
export const PLAN_ROWS = (() => {
  const rows: { node: PlanNode; depth: number; at: number }[] = [];
  const walk = (n: PlanNode, d: number) => { rows.push({ node: n, depth: d, at: 0 }); n.children?.forEach(c => walk(c, d + 1)); };
  walk(PLAN, 0);
  rows.forEach((r, i) => { r.at = 8.6 + i * 0.32; });
  return rows;
})();
export const PLAN_CHECKS = [
  { label: "Ratio", calc: "1 + 72/18", value: "5.00 : 1" },
  { label: "Coaxial", calc: "18 + 2 × 27", value: "72 ✓" },
  { label: "Assembly", calc: "(18 + 72) / 3", value: "30 ✓" },
  { label: "Centre distance", calc: "1.5 × (18 + 27) / 2", value: "33.75" },
].map((c, i) => ({ ...c, at: 10.2 + i * 0.45 }));
export const INTERFACES = [
  "Sun ↔ input shaft Ø12 press fit",
  "Planet bore Ø26 ↔ 6000 bearing",
  "Pin Ø10 ↔ carrier PCD 67.5",
  "Output Ø20 ↔ 2 × 6204-2RS",
  "Ring ↔ covers: 6 × M5, PCD 122",
].map((s, i) => ({ text: s, at: 11.4 + i * 0.32 }));
export const ESTIMATE_AT = 13.2;
export const APPROVED_AT = 14.4;
export const ARCHIE_LINES = [
  { at: 7.6, text: "Archie is reading the brief…" },
  { at: 9.6, text: "Archie is checking the gear set…" },
  { at: 11.3, text: "Archie is freezing the interfaces…" },
  { at: 13.0, text: "Archie is estimating 11 tickets…" },
  { at: 14.4, text: "Plan approved. Opening the board." },
  { at: 15.4, text: "Archie assigned 11 tickets to 5 specialists" },
  { at: 17.4, text: "Hex filled 14 standard parts from the Toolbox · 0 tokens" },
  { at: 20.0, text: "Gage is checking every part before it is fitted" },
  { at: 23.0, text: "All parts pass. Fitz is planning the mates." },
];
export function archieLine(t: number): string {
  let s = ARCHIE_LINES[0]!.text;
  for (const l of ARCHIE_LINES) if (t >= l.at) s = l.text;
  return s;
}

// ------------------------------------------------------------------ c. board
export type Ticket = {
  key: string; title: string; agent: string; start: number; dur: number; status: string; review?: number;
};
const B = CHAPTERS[2].start;
export const TICKETS: Ticket[] = [
  { key: "PG-1", title: "Sun 18T", agent: "axel", start: B + 1.2, dur: 1.8, status: "Axel is generating 18 involute teeth, m1.5…" },
  { key: "PG-2", title: "Planet 27T × 3", agent: "axel", start: B + 3.0, dur: 1.9, status: "Axel is cutting 27 teeth, three planets…" },
  { key: "PG-3", title: "Ring 72T internal", agent: "axel", start: B + 4.9, dur: 2.3, status: "Axel is shaping 72 internal teeth…" },
  { key: "PG-4", title: "Input shaft", agent: "chuck", start: B + 1.4, dur: 1.6, status: "Chuck is boring the Ø6.35 motor socket…" },
  { key: "PG-5", title: "Planet pins × 3", agent: "chuck", start: B + 3.0, dur: 1.3, status: "Chuck is turning three Ø10 pins…" },
  { key: "PG-6", title: "Output shaft", agent: "chuck", start: B + 4.3, dur: 1.9, status: "Chuck is cutting the 5 × 5 keyway…" },
  { key: "PG-7", title: "Carrier plates", agent: "mill", start: B + 1.6, dur: 2.1, status: "Mill is drilling pin holes on PCD 67.5…" },
  { key: "PG-8", title: "Housing covers", agent: "mill", start: B + 3.7, dur: 2.5, status: "Mill is boring the 6204 seats…" },
  { key: "PG-9", title: "Motor flange", agent: "mill", start: B + 6.2, dur: 1.1, status: "Mill is drilling the NEMA 23 pattern…" },
  { key: "PG-10", title: "Standard parts (14)", agent: "hex", start: B + 1.0, dur: 0.5, status: "Hex found 6204-2RS, 6001, 6000, M5, dowels in the Toolbox · 0 tokens" },
  { key: "PG-11", title: "Assembly", agent: "fitz", start: B + 7.9, dur: 9, status: "Fitz is planning the assembly of 29 parts…" },
];
const REVIEW = 0.7;
export const DEAL_AT = B + 0.1;
export type TicketState = { col: 0 | 1 | 2 | 3; progress: number; visible: boolean };
/** Column 0 backlog, 1 in design, 2 review (Gage), 3 done. */
export function ticketState(tk: Ticket, i: number, t: number): TicketState {
  const visible = t >= DEAL_AT + i * 0.08;
  if (t < tk.start) return { col: 0, progress: 0, visible };
  const end = tk.start + tk.dur;
  if (t < end) return { col: 1, progress: span(t, tk.start, end), visible };
  if (tk.agent !== "hex" && t < end + REVIEW) return { col: 2, progress: 1, visible };
  return { col: 3, progress: 1, visible };
}

// ------------------------------------------------------------------ d. build flash
export type BuildItem = { part: string; label: string; agent: string; at: number; stock?: "cyl" | "box" };
const D0 = CHAPTERS[3].start;
const MADE: [string, string, string, "cyl" | "box"][] = [
  ["ring", "Ring 72T internal", "axel", "cyl"],
  ["planet", "Planet 27T", "axel", "cyl"],
  ["sun", "Sun 18T", "axel", "cyl"],
  ["carrier_a", "Carrier plate A", "mill", "cyl"],
  ["carrier_b", "Carrier plate B", "mill", "cyl"],
  ["input_cover", "Input cover", "mill", "cyl"],
  ["output_cover", "Output cover", "mill", "box"],
  ["motor_flange", "Motor flange", "mill", "box"],
  ["input_shaft", "Input shaft", "chuck", "cyl"],
  ["output_shaft", "Output shaft", "chuck", "cyl"],
  ["pin", "Planet pin", "chuck", "cyl"],
];
const STD: [string, string][] = [
  ["b6204", "6204-2RS"], ["b6001", "6001"], ["b6000", "6000"], ["shcs_m5", "M5 × 35"], ["dowel", "Dowel Ø5"],
];
export const BUILD_DUR = 0.95;
export const BUILD: BuildItem[] = [
  ...MADE.map(([part, label, agent, stock], i) => ({ part, label, agent, stock, at: D0 + 0.9 + i * 0.4 })),
  ...STD.map(([part, label], i) => ({ part, label, agent: "hex", at: D0 + 0.6 + i * 0.06 })),
];
export const BLANKS_AT = D0 + 0.1;

// ------------------------------------------------------------------ e. assembly
const E0 = CHAPTERS[4].start;
export const FLY = { start: E0 + 0.1, dur: 1.5, stagger: 0.03 };
/** Bottom-up assembly order; each group seats together. */
export const SEAT_ORDER: string[][] = [
  ["motor_flange", "input_cover"], ["b6001"], ["input_shaft"], ["carrier_a"], ["pin"], ["b6000"], ["planet"], ["sun"],
  ["ring"], ["dowel"], ["carrier_b"], ["output_shaft"], ["b6204"], ["output_cover"], ["shcs_m5"],
];
export const SEAT = { start: E0 + 1.9, gap: 0.36, dur: 0.55 };
export const seatAt = (part: string) => SEAT.start + SEAT.gap * SEAT_ORDER.findIndex(g => g.includes(part));
export const ASSEMBLED_AT = SEAT.start + SEAT.gap * (SEAT_ORDER.length - 1) + SEAT.dur;
/** Exploded-view axial offset (mm) per part, stacked bottom to top. */
export const EXPLODE_DZ: Record<string, number> = {
  motor_flange: -190, input_cover: -150, b6001: -120, input_shaft: -95, carrier_a: -70, pin: -45, b6000: -20, planet: 0,
  sun: 0, ring: 40, dowel: 62, carrier_b: 80, output_shaft: 110, b6204: 110, output_cover: 150, shcs_m5: 230,
};

// ------------------------------------------------------------------ f. running
export const RUN_AT = CHAPTERS[5].start;
/** On-screen sun speed (rad/s): shown slowed down; the readout gives the design-point speeds. */
export const SUN_SPEED = Math.PI * 2 * 0.42;
export const MOTOR_RPM = 600;
export const OUTPUT_TORQUE = 12;
export const CHIPS_AT = RUN_AT + 3.2;
