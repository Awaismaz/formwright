// WORKLIST 46: golden mechanism suite dashboard (admin console, God mode only). Plain numbers, no agent internals.
import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Check, ChevronDown, ChevronRight, Minus, X } from "lucide-react";
import { api } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, Card, EmptyState, PageLoader, Stat } from "@/components/ui";
import { caseSummaries, expectationGrid, fmt, sparkPath, suiteSummary, trackLabel, trackOf, tracks, type GoldenCase, type GoldenRun } from "./golden";

function Spark({ values, tone = "primary", w = 96, h = 22, title }: { values: (number | null)[]; tone?: "primary" | "success" | "accent"; w?: number; h?: number; title?: string }) {
  const d = sparkPath(values, w, h);
  const one = values.filter(v => v !== null).length === 1 ? /M([\d.]+),([\d.]+)/.exec(d) : null;
  const color = tone === "success" ? "text-success" : tone === "accent" ? "text-accent" : "text-primary";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className={cx("shrink-0", color)} role="img" aria-label={title}>
      {title && <title>{title}</title>}
      {one ? <circle cx={Number(one[1])} cy={Number(one[2])} r={2.5} fill="currentColor" />
        : d ? <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
        : <line x1={2} x2={w - 2} y1={h / 2} y2={h / 2} className="text-border" stroke="currentColor" strokeDasharray="2 3" />}
    </svg>
  );
}

const last = <T,>(xs: T[]) => (xs.length ? xs[xs.length - 1] : undefined);

function Result({ run, changed }: { run: GoldenRun | null; changed: "better" | "worse" | null }) {
  if (!run) return <Badge>not run</Badge>;
  return (
    <span className="inline-flex items-center gap-1">
      <Badge tone={run.passed ? "success" : "danger"}>{run.passed ? "PASS" : "FAIL"}</Badge>
      {changed === "better" && <ArrowUpRight className="h-3.5 w-3.5 text-success" aria-label="better than the run before" />}
      {changed === "worse" && <ArrowDownRight className="h-3.5 w-3.5 text-danger" aria-label="worse than the run before" />}
    </span>
  );
}

function Grid({ runs }: { runs: GoldenRun[] }) {
  const { ids, cols } = expectationGrid(runs, 8);
  if (!cols.length) return null;
  const latest = cols[cols.length - 1]!;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted"><tr>
          <th className="px-3 py-1.5 text-left font-medium">Expectation</th>
          <th className="px-3 py-1.5 text-left font-medium">Latest: got / want</th>
          {cols.map(c => <th key={c.run_id} className="px-1 py-1.5 text-center font-mono font-normal" title={`${c.at} · ${c.sha}`}>{c.sha.slice(0, 5)}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-border">
          {ids.map(({ id, label }) => {
            const e = (latest.expectations ?? []).find(x => x.id === id);
            return (
              <tr key={id}>
                <td className="px-3 py-1.5">{label}</td>
                <td className={cx("px-3 py-1.5 font-mono text-[11px]", e?.ok === false ? "text-danger" : "text-muted")}>
                  {e ? `${fmt(e.got)} / ${fmt(e.want)}` : "n/a"}{e?.note ? <span className="ml-1 font-sans text-muted">({e.note})</span> : null}
                </td>
                {cols.map(c => {
                  const x = (c.expectations ?? []).find(y => y.id === id);
                  return (
                    <td key={c.run_id} className="px-1 py-1.5 text-center">
                      {!x ? <span className="text-muted">·</span> : x.ok === true ? <Check className="mx-auto h-3.5 w-3.5 text-success" aria-label="pass" />
                        : x.ok === false ? <X className="mx-auto h-3.5 w-3.5 text-danger" aria-label="fail" /> : <Minus className="mx-auto h-3.5 w-3.5 text-muted" aria-label="not measured" />}
                    </td>);
                })}
              </tr>);
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function GoldenSuite() {
  const q = useQuery({ queryKey: ["admin", "golden"], queryFn: () => api.get<{ cases: GoldenCase[]; runs: GoldenRun[] }>("/api/admin/golden") });
  const [track, setTrack] = useState("simulated");
  const [open, setOpen] = useState<string | null>(null);
  const mode = track.startsWith("live") ? "live" : "simulated";
  const rows = useMemo(() => (q.data ? caseSummaries(q.data.cases, q.data.runs, track) : []), [q.data, track]);
  const sum = useMemo(() => suiteSummary(rows, q.data?.runs ?? [], track), [rows, q.data, track]);
  const offered = useMemo(() => tracks(q.data?.runs ?? []), [q.data]);
  if (q.isError) return <Card className="p-5 text-sm text-muted">The golden suite is available in God mode only.</Card>;
  if (!q.data) return <PageLoader />;
  const runsOf = (id: string) => q.data.runs.filter(r => r.case === id && trackOf(r) === track);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-muted">Each case is a brief with hand-checked expectations, run through the Design Office end to end. Simulated runs use simulated agents and spend nothing; live runs use the real agents with a token cap per case.</p>
        <div className="inline-flex flex-wrap rounded-lg border border-border p-0.5 text-sm" role="tablist" aria-label="Runs">
          {offered.map(t => (
            <button key={t} role="tab" aria-selected={track === t} onClick={() => setTrack(t)}
              className={cx("rounded-md px-3 py-1", track === t ? "bg-primary text-white" : "text-muted hover:text-text")}>{trackLabel(t)}</button>))}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Cases passing" value={`${sum.passing} of ${sum.cases}`} sub={sum.notRun ? `${sum.notRun} not run on this track` : `${sum.failing} failing`} />
        <Stat label="Pass rate per suite run" value={sum.passRate.length ? `${Math.round((last(sum.passRate) ?? 0) * 100)}%` : "n/a"} sub={<Spark values={sum.passRate} tone="success" w={140} title="Share of cases passing, per suite run" />} />
        <Stat label="Wall time, latest runs" value={`${sum.wallTotal} s`} sub={<Spark values={sum.wall} w={140} title="Suite wall time per run (s)" />} />
        <Stat label={mode === "live" ? "Tokens, latest runs" : "Tokens (simulated metering)"} value={sum.tokensTotal} sub={sum.lastAt ? `Last run ${ago(sum.lastAt)} at ${sum.sha}` : "No runs yet"} />
      </div>
      {!q.data.runs.length ? (
        <EmptyState icon={<Check className="h-6 w-6" />} title="No golden runs yet" body="Run the golden suite on a development machine; each run adds one record per case here." />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-sm">
            <thead className="bg-panel2 text-left text-xs text-muted"><tr>
              {["Case", "Latest", "Failing expectations", "Wall time", "Tokens", "Pass rate", "Runs"].map(h => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-border">
              {rows.map(r => {
                const isOpen = open === r.id;
                return (
                  <Fragment key={r.id}>
                    <tr className="cursor-pointer hover:bg-text/[.03]" onClick={() => setOpen(isOpen ? null : r.id)}>
                      <td className="px-4 py-2.5">
                        <div className="flex items-start gap-1.5">
                          {isOpen ? <ChevronDown className="mt-0.5 h-4 w-4 text-muted" /> : <ChevronRight className="mt-0.5 h-4 w-4 text-muted" />}
                          <div><div className="font-medium">{r.letter && <span className="mr-1.5 font-mono text-xs text-muted">{r.letter}</span>}{r.title}{r.fast && <Badge className="ml-1.5">CI</Badge>}</div>
                            {r.source && <div className="text-xs text-muted">{r.source}</div>}</div>
                        </div>
                      </td>
                      <td className="px-4 py-2.5"><Result run={r.latest} changed={r.changed} />{r.latest && <div className="mt-0.5 text-[11px] text-muted" title={r.latest.dirty ? "Run with uncommitted changes on top of this commit" : undefined}>{ago(r.latest.at)} · {r.latest.sha}{r.latest.dirty ? "+" : ""}</div>}</td>
                      <td className="max-w-xs px-4 py-2.5 text-xs">
                        {r.latest?.error ? <span className="text-danger">{r.latest.error}</span>
                          : r.failing.length ? r.failing.slice(0, 3).map(f => <div key={f.id} className="truncate" title={`${f.label}: got ${fmt(f.got)}, want ${fmt(f.want)}`}><span className="text-danger">{f.label}</span> <span className="text-muted">got {fmt(f.got)}, want {fmt(f.want)}</span></div>)
                            : r.latest ? <span className="text-muted">none</span> : null}
                        {r.failing.length > 3 && <div className="text-muted">and {r.failing.length - 3} more</div>}
                        {r.latest?.stopped && <div className="truncate text-muted" title={r.latest.stopped}>Stopped: {r.latest.stopped}</div>}
                      </td>
                      <td className="px-4 py-2.5"><div className="flex items-center gap-2"><Spark values={r.wall} title="Wall time per run (s)" /><span className="whitespace-nowrap tabular-nums">{r.runs ? `${fmt(last(r.wall) ?? null)} s` : "n/a"}</span></div></td>
                      <td className="px-4 py-2.5"><div className="flex items-center gap-2"><Spark values={r.tokens} tone="accent" title="Tokens per run" /><span className="whitespace-nowrap tabular-nums">{fmt(last(r.tokens) ?? null)}</span></div></td>
                      <td className="px-4 py-2.5"><div className="flex items-center gap-2"><Spark values={r.passRate} tone="success" title="Pass rate, last 5 runs" /><span className="tabular-nums">{r.runs ? `${Math.round((last(r.passRate) ?? 0) * 100)}%` : "n/a"}</span></div></td>
                      <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-muted">{r.passes} / {r.runs}</td>
                    </tr>
                    {isOpen && (
                      <tr><td colSpan={7} className="bg-panel2/60 px-4 py-3">
                        {r.latest ? <>
                          <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
                            {Object.entries(r.latest.metrics?.phases ?? {}).map(([k, v]) => <span key={k}>{k} <b className="font-semibold text-text tabular-nums">{fmt(v)} s</b></span>)}
                            <span>parts <b className="font-semibold text-text">{fmt(r.latest.metrics?.parts)}</b></span>
                            <span>instances <b className="font-semibold text-text">{fmt(r.latest.metrics?.instances)}</b></span>
                            <span>built without AI <b className="font-semibold text-text">{fmt(r.latest.metrics?.direct)}</b></span>
                            <span>interface features conforming <b className="font-semibold text-text">{r.latest.metrics?.conformance ? `${r.latest.metrics.conformance.ok} of ${r.latest.metrics.conformance.total}` : "n/a"}</b></span>
                            <span>supervisor actions <b className="font-semibold text-text">{fmt(r.latest.metrics?.supervisor)}</b></span>
                            <span>routing <b className="font-mono font-semibold text-text">{r.latest.routing_id ?? "n/a"}</b></span>
                            {r.latest.flags && Object.keys(r.latest.flags).length > 0 && <span>switches <b className="font-mono font-semibold text-text">{Object.entries(r.latest.flags).map(([k, v]) => `${k}=${v}`).join(" ")}</b></span>}
                          </div>
                          <Grid runs={runsOf(r.id)} />
                        </> : <span className="text-xs text-muted">No run of this case on this track yet.</span>}
                      </td></tr>)}
                  </Fragment>);
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
