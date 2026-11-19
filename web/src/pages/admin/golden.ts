// WORKLIST 46: data shaping for the golden suite dashboard (admin, God mode only). Pure functions, vitest-covered.

export type Mode = "simulated" | "live";

export interface GoldenRow { id: string; label: string; ok: boolean | null; got: unknown; want: unknown; note?: string }

export interface GoldenMetrics {
  wall_s?: number; phases?: Record<string, number>; tokens?: number; light?: boolean; parts?: number; pieces?: number;
  instances?: number; clashes?: number | null; binned?: number; loose?: number; blocked?: number; supervisor?: number;
  conformance?: { ok: number; total: number }; direct?: number;
}

export interface GoldenRun {
  run_id: string; suite_id?: string | null; at: string; sha: string; dirty?: boolean; mode: Mode; case: string;
  title: string; letter?: string | null; passed: boolean; status: string; stopped?: string | null;
  metrics: GoldenMetrics | null; expectations: GoldenRow[] | null; routing_id?: string | null; error?: string | null;
  flags?: Record<string, string> | null;
}

export interface GoldenCase { id: string; title: string; letter?: string | null; source?: string | null; fast: boolean; tokens?: number | null }

export interface CaseSummary {
  id: string; title: string; letter: string; source: string; fast: boolean;
  latest: GoldenRun | null; runs: number; passes: number;
  wall: (number | null)[]; tokens: (number | null)[]; passRate: number[];
  failing: GoldenRow[]; changed: "better" | "worse" | null;
}

export interface SuiteSummary {
  cases: number; withRuns: number; passing: number; failing: number; notRun: number;
  wallTotal: number; tokensTotal: number; lastAt: string | null; sha: string | null;
  passRate: number[]; wall: number[]; tokens: number[];
}

const byTime = (a: GoldenRun, b: GoldenRun) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0);

/** Rolling pass rate (0..1) over the last ``window`` runs at each run. */
export function rollingPassRate(runs: GoldenRun[], window = 5): number[] {
  return runs.map((_, i) => {
    const w = runs.slice(Math.max(0, i - window + 1), i + 1);
    return w.filter(r => r.passed).length / w.length;
  });
}

/** One row per case: the latest run in this mode, its failing expectations and the trends across runs. */
export function caseSummaries(cases: GoldenCase[], runs: GoldenRun[], mode: Mode, window = 5): CaseSummary[] {
  const known = new Map(cases.map(c => [c.id, c]));
  for (const r of runs) if (!known.has(r.case)) known.set(r.case, { id: r.case, title: r.title, letter: r.letter, fast: false });
  return [...known.values()].map(c => {
    const rs = runs.filter(r => r.case === c.id && r.mode === mode).sort(byTime);
    const latest = rs.length ? rs[rs.length - 1]! : null;
    const prev = rs.length > 1 ? rs[rs.length - 2]! : null;
    return {
      id: c.id, title: c.title, letter: c.letter ?? "", source: c.source ?? "", fast: c.fast,
      latest, runs: rs.length, passes: rs.filter(r => r.passed).length,
      wall: rs.map(r => r.metrics?.wall_s ?? null), tokens: rs.map(r => r.metrics?.tokens ?? null),
      passRate: rollingPassRate(rs, window),
      failing: latest ? (latest.expectations ?? []).filter(e => e.ok === false) : [],
      changed: latest && prev && latest.passed !== prev.passed ? (latest.passed ? "better" : "worse") : null,
    };
  });
}

/** The summary row: the latest results across cases and, per suite run, the share of cases passing, wall and tokens. */
export function suiteSummary(rows: CaseSummary[], runs: GoldenRun[], mode: Mode): SuiteSummary {
  const latest = rows.map(r => r.latest).filter((r): r is GoldenRun => !!r);
  const newest = latest.slice().sort(byTime).pop() ?? null;
  const suites = new Map<string, GoldenRun[]>();
  for (const r of runs.filter(r => r.mode === mode).sort(byTime)) {
    const k = r.suite_id || r.run_id;
    suites.set(k, [...(suites.get(k) ?? []), r]);
  }
  const groups = [...suites.values()];
  return {
    cases: rows.length, withRuns: latest.length, passing: latest.filter(r => r.passed).length,
    failing: latest.filter(r => !r.passed).length, notRun: rows.length - latest.length,
    wallTotal: round1(latest.reduce((s, r) => s + (r.metrics?.wall_s ?? 0), 0)),
    tokensTotal: latest.reduce((s, r) => s + (r.metrics?.tokens ?? 0), 0),
    lastAt: newest?.at ?? null, sha: newest?.sha ?? null,
    passRate: groups.map(g => g.filter(r => r.passed).length / g.length),
    wall: groups.map(g => round1(g.reduce((s, r) => s + (r.metrics?.wall_s ?? 0), 0))),
    tokens: groups.map(g => g.reduce((s, r) => s + (r.metrics?.tokens ?? 0), 0)),
  };
}

const round1 = (n: number) => Math.round(n * 10) / 10;

/** An SVG polyline path for a sparkline; gaps (null) break the line. Flat series sit mid-height. */
export function sparkPath(values: (number | null)[], w: number, h: number, pad = 2): string {
  const nums = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (!nums.length) return "";
  const lo = Math.min(...nums), hi = Math.max(...nums);
  const n = values.length;
  const x = (i: number) => (n === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (n - 1));
  const y = (v: number) => (hi === lo ? h / 2 : h - pad - ((v - lo) * (h - 2 * pad)) / (hi - lo));
  let d = "", pen = false;
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) { pen = false; return; }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

/** A measured value as short plain text for a table cell. */
export function fmt(v: unknown): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return `[${v.map(fmt).join(", ")}]`;
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k} ${fmt(x)}`).join(", ") || "none";
  return String(v);
}

/** Every expectation id seen in the case's runs (latest first order), for the pass/fail grid. */
export function expectationGrid(runs: GoldenRun[], last = 8): { ids: { id: string; label: string }[]; cols: GoldenRun[] } {
  const cols = runs.slice().sort(byTime).slice(-last);
  const seen = new Map<string, string>();
  for (const r of cols.slice().reverse()) for (const e of r.expectations ?? []) if (!seen.has(e.id)) seen.set(e.id, e.label);
  return { ids: [...seen.entries()].map(([id, label]) => ({ id, label })), cols };
}
