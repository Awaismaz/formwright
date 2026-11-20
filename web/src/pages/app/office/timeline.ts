/** Pure helpers for the Timeline tab (Gantt-lite) and the calibration panel (CD-015). Times are minutes from the
 * program's first Run (server: src/aicad/office/timeline.py); rates are minutes per complexity unit
 * (src/aicad/office/calibration.py). */
import type { CalibrationUpdate, TimelineRow, TimelineSegment } from "./types";

const STEPS = [5 / 60, 10 / 60, 15 / 60, 30 / 60, 1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 1440];

/** The tick spacing (minutes) that gives at most ``maxTicks`` ticks over ``span``. */
export function niceStep(span: number, maxTicks = 8): number {
  const s = Math.max(span, 1e-6);
  return STEPS.find(x => s / x <= maxTicks) ?? Math.ceil(s / maxTicks / 1440) * 1440;
}

/** Tick positions (minutes) from 0 up to and including the first tick past ``span``. */
export function ticks(span: number, maxTicks = 8): number[] {
  const step = niceStep(span, maxTicks);
  const out: number[] = [];
  for (let k = 0; k * step <= span + step * 0.999 && out.length < 60; k++) out.push(Math.round(k * step * 1e6) / 1e6);
  return out;
}

/** An axis label: "0", "30 s", "2 min", "1 h 30", "1 d". */
export function fmtClock(min: number): string {
  if (min <= 0) return "0";
  if (min < 1) return `${Math.round(min * 60)} s`;
  if (min < 60) return `${Math.round(min * 10) / 10} min`;
  if (min < 1440) {
    const h = Math.floor(min / 60), m = Math.round(min - h * 60);
    return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
  }
  return `${Math.round((min / 1440) * 10) / 10} d`;
}

/** Pixels per minute so ``span`` fills ``width`` (a tiny span still draws). */
export function pxPerMin(span: number, width: number): number {
  return width / Math.max(span, 1 / 60);
}

/** A bar's box in pixels; very short spells stay visible (``minPx``). */
export function bar(start: number, end: number, ppm: number, minPx = 3): { left: number; width: number } {
  const left = Math.max(0, start) * ppm;
  return { left, width: Math.max(minPx, (Math.max(end, start) - Math.max(0, start)) * ppm) };
}

/** Estimate error for people: "on estimate" within 5 %, else "+25 %" / "−85 %". */
export function fmtError(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "-";
  if (Math.abs(pct) < 5) return "on estimate";
  return `${pct > 0 ? "+" : "−"}${Math.round(Math.abs(pct))} %`;
}

export function errorTone(pct: number | null | undefined): "neutral" | "success" | "warning" | "danger" {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "neutral";
  const a = Math.abs(pct);
  return a <= 25 ? "success" : a <= 100 ? "warning" : "danger";
}

/** An SVG polyline for the accuracy trend (rolling mean absolute error, %): x = finished ticket, y = error. */
export function sparkline(points: { n: number; mape: number }[], w: number, h: number, pad = 2): string {
  if (!points.length) return "";
  const maxY = Math.max(10, ...points.map(p => p.mape));
  const xs = points.length === 1 ? [w / 2] : points.map((_p, i) => pad + (i * (w - 2 * pad)) / (points.length - 1));
  return points.map((p, i) => `${Math.round(xs[i] * 10) / 10},${Math.round((h - pad - (p.mape / maxY) * (h - 2 * pad)) * 10) / 10}`).join(" ");
}

/** "4 → 3.4 min per unit" */
export function rateLine(before: number, after: number): string {
  const f = (x: number) => String(Math.round(x * 1000) / 1000);
  return before === after ? `${f(after)} min per unit` : `${f(before)} → ${f(after)} min per unit`;
}

/** Why a rate moved, in one sentence (the server's bounded EMA: observed, clamped to ×½…×2, then 30 % of the way). */
export function explainUpdate(u: Pick<CalibrationUpdate, "ticket" | "actual_min" | "estimate_min" | "complexity" | "observed" | "clamped" | "before" | "after">,
  alpha: number): string {
  const f = (x: number) => String(Math.round(x * 1000) / 1000);
  const took = u.actual_min < 1 ? `${Math.round(u.actual_min * 60)} s` : `${f(u.actual_min)} min`;
  const clamp = Math.abs(u.observed - u.clamped) > 1e-9 ? `, held to ${f(u.clamped)} (one ticket moves a rate at most ×2 or ÷2)` : "";
  return `${u.ticket} took ${took} at complexity ${u.complexity}: ${f(u.observed)} min per unit${clamp}; the rate moves `
    + `${Math.round(alpha * 100)} % of the way: ${f(u.before)} → ${f(u.after)}.`;
}

/** Work time per stage and the waits of a row, for the drawer and the row tooltip. */
export function rowBreakdown(r: Pick<TimelineRow, "segments">): { work: number; waitCapacity: number; blocked: number } {
  let work = 0, waitCapacity = 0, blocked = 0;
  for (const s of r.segments) {
    const d = Math.max(0, s.end - s.start);
    if (s.kind === "work") work += d; else if (s.kind === "capacity") waitCapacity += d; else blocked += d;
  }
  return { work, waitCapacity, blocked };
}

/** A segment's tooltip line. */
export function segmentTip(s: Pick<TimelineSegment, "what" | "label" | "start" | "end" | "open">): string {
  const who = s.label ? `${s.label}: ` : "";
  return `${who}${s.what} · ${fmtClock(s.start)} → ${s.open ? "now" : fmtClock(s.end)} (${fmtClock(Math.max(0, s.end - s.start)) || "0"})`;
}
