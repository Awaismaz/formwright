import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical, GitPullRequest, Route, TrendingDown } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Card, EmptyState, PageLoader, Tip } from "@/components/ui";
import { AGENT, AgentAvatar } from "./Avatars";
import { BASE } from "./api";
import { fmtMinutes } from "./model";
import { errorTone, explainUpdate, fmtClock, fmtError, rateLine, rowBreakdown, segmentTip, sparkline, ticks } from "./timeline";
import type { Calibration, Program, Ticket, Timeline, TimelineMarker, TimelineSegment } from "./types";

const TONE_TEXT = { neutral: "text-muted", success: "text-success", warning: "text-warning", danger: "text-danger" } as const;
const pct = (x: number, span: number) => `${Math.max(0, Math.min(100, (100 * x) / span))}%`;

function Seg({ s, span, tall }: { s: TimelineSegment; span: number; tall?: boolean }) {
  const colour = s.agent ? AGENT[s.agent]?.colour ?? "#495057" : undefined;
  return (
    <Tip side="top" content={segmentTip(s)}>
      <span className={cx("absolute rounded-sm", tall ? "top-1 h-5" : "top-[13px] h-3",
        s.kind === "capacity" && "fw-tl-wait", s.kind === "blocked" && "fw-tl-blocked", s.open && "animate-pulse")}
        style={{ left: pct(s.start, span), width: `max(3px, ${pct(Math.max(0, s.end - s.start), span)})`,
          background: s.kind === "work" ? colour : undefined }} data-kind={s.kind} />
    </Tip>
  );
}

function Markers({ markers, span, now, running }: { markers: TimelineMarker[]; span: number; now: number; running: boolean }) {
  return (
    <>
      {markers.map((m, i) => (
        <Tip key={i} side="top" content={m.text}>
          <span className={cx("absolute bottom-0 top-0 z-10 w-0.5 cursor-help", m.type === "cr.accepted" ? "bg-success/70" : m.type === "cr.rejected" ? "bg-danger/60" : "bg-warning/80")}
            style={{ left: pct(m.t, span) }} data-marker={m.type}><GitPullRequest className="absolute -left-1.5 -top-0.5 h-3 w-3 text-warning" /></span>
        </Tip>))}
      {running && <span className="pointer-events-none absolute bottom-0 top-0 z-10 w-px bg-primary" style={{ left: pct(now, span) }} title="Now" />}
    </>
  );
}

/** Planned against actual, by ticket or by agent lane (Gantt-lite). */
function Chart({ tl, program, mode, onOpen }: { tl: Timeline; program: Program; mode: "tickets" | "agents"; onOpen: (t: Ticket) => void }) {
  const span = Math.max(tl.span, tl.now, 1 / 60) * 1.04;
  const running = program.orchestrator?.state === "running";
  const axis = ticks(span, 8).filter(x => x <= span);
  const head = (
    <div className="relative h-6 border-b border-border text-[10.5px] text-muted">
      {axis.map(x => <span key={x} className="absolute -translate-x-1/2 whitespace-nowrap tabular-nums" style={{ left: pct(x, span) }}>{fmtClock(x)}</span>)}
    </div>
  );
  const grid = (
    <div className="pointer-events-none absolute inset-0">
      {axis.map(x => <span key={x} className="absolute bottom-0 top-0 w-px bg-border/60" style={{ left: pct(x, span) }} />)}
    </div>
  );
  if (mode === "agents") {
    return (
      <div className="min-w-[760px]">
        <div className="grid grid-cols-[200px_1fr] gap-3"><div className="text-[11px] font-medium text-muted">Agent</div>{head}</div>
        {tl.lanes.length === 0 && <div className="py-6 text-center text-[12.5px] text-muted">No agent has worked on this program yet. Press Run.</div>}
        {tl.lanes.map(l => (
          <div key={l.label} className="grid grid-cols-[200px_1fr] items-center gap-3 border-b border-border/50 py-1" data-lane={l.label}>
            <div className="flex min-w-0 items-center gap-2"><AgentAvatar code={l.agent} size={24} still />
              <div className="min-w-0"><div className="truncate text-[12.5px] font-medium">{l.label}</div>
                <div className="text-[10.5px] text-muted">{l.bars.length} spell{l.bars.length !== 1 ? "s" : ""} · {fmtMinutes(l.bars.reduce((a, b) => a + (b.end - b.start), 0))}</div></div></div>
            <div className="relative h-7">
              {grid}
              {l.bars.map((b, i) => <Tip key={i} side="top" content={`${b.key} ${b.title}: ${segmentTip(b)}`}>
                <span className={cx("absolute top-1 flex h-5 items-center overflow-hidden rounded-sm px-1 text-[9.5px] font-medium text-white",
                  b.critical && "ring-2 ring-danger/70")} style={{ left: pct(b.start, span), width: `max(3px, ${pct(b.end - b.start, span)})`,
                    background: AGENT[l.agent]?.colour ?? "#495057" }}>{b.key}</span></Tip>)}
              <Markers markers={tl.markers} span={span} now={tl.now} running={running} />
            </div>
          </div>))}
      </div>
    );
  }
  return (
    <div className="min-w-[860px]">
      <div className="grid grid-cols-[250px_1fr_150px] gap-3"><div className="text-[11px] font-medium text-muted">Ticket</div>{head}
        <div className="text-right text-[11px] font-medium text-muted">Estimate → actual</div></div>
      {tl.rows.map(r => {
        const t = program.tickets.find(x => x.id === r.id);
        const tone = errorTone(r.error_pct);
        const br = rowBreakdown(r);
        return (
          <div key={r.id} className={cx("grid grid-cols-[250px_1fr_150px] items-center gap-3 border-b border-border/50 py-0.5", r.critical && "bg-danger/[0.03]")}
            data-row={r.key} data-critical={r.critical || undefined}>
            <button type="button" className="flex min-w-0 items-center gap-2 text-left" onClick={() => t && onOpen(t)}>
              <AgentAvatar code={r.specialist} size={22} still />
              <span className="min-w-0"><span className="block truncate text-[12.5px] font-medium hover:text-primary">{r.title}</span>
                <span className="flex items-center gap-1 text-[10.5px] text-muted"><span className="font-mono">{r.key}</span>
                  {r.critical && <span className="inline-flex items-center gap-0.5 font-medium text-danger"><Route className="h-3 w-3" />critical path</span>}</span></span>
            </button>
            <div className="relative h-8">
              {grid}
              {r.planned && <Tip side="top" content={`Planned: ${fmtClock(r.planned.start)} → ${fmtClock(r.planned.end)} (${fmtMinutes(r.estimate_min)} estimated, agent slot ${r.planned.slot + 1})`}>
                <span className={cx("absolute top-1 h-2.5 rounded-sm border border-dashed", r.critical ? "border-danger bg-danger/10" : "border-text/40 bg-text/[0.04]")}
                  style={{ left: pct(r.planned.start, span), width: `max(3px, ${pct(r.planned.end - r.planned.start, span)})` }} data-planned /></Tip>}
              {r.segments.map((s, i) => <Seg key={i} s={s} span={span} />)}
              <Markers markers={tl.markers.filter(m => !m.ticket || m.ticket === r.id)} span={span} now={tl.now} running={running} />
            </div>
            <div className="text-right text-[11px] tabular-nums leading-tight">
              <div><span className="text-muted">{fmtMinutes(r.estimate_min)}</span> → <b>{r.actual_min ? fmtMinutes(r.actual_min) : "—"}</b></div>
              <div className={TONE_TEXT[tone]}>{r.error_pct !== null ? fmtError(r.error_pct) : br.waitCapacity > 0 || br.blocked > 0
                ? <span className="text-warning">{br.blocked > 0 ? "waited for you" : "waited for capacity"}</span> : r.actual_min ? "in progress" : ""}</div>
            </div>
          </div>);
      })}
    </div>
  );
}

function CalibrationPanel({ cal }: { cal: Calibration }) {
  const pts = sparkline(cal.trend, 180, 36);
  const last = cal.trend[cal.trend.length - 1];
  const learned = cal.families.filter(f => f.n > 0 || Math.abs(f.rate - f.default) > 1e-9);
  return (
    <Card className="p-4" data-calibration>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <TrendingDown className="h-4 w-4 text-primary" /><h3 className="text-[14px] font-semibold">Estimates learn from finished tickets</h3>
        {cal.profile === "simulated" && <Badge tone="warning"><FlaskConical className="mr-1 inline h-3 w-3" />Simulated runs (kept apart from live estimates)</Badge>}
      </div>
      <p className="mb-3 max-w-[900px] text-[12px] text-muted">Each finished ticket moves its specialist's minutes per complexity unit towards what it really took:
        the observation counts at most ×{cal.rule.step[1]} or ÷{1 / cal.rule.step[0]} of the current rate, the rate moves {Math.round(cal.rule.alpha * 100)} % of the way,
        and stays between {cal.rule.bounds[0]} and {cal.rule.bounds[1]} min. New plans take the current rates; estimates already on tickets stay as promised.</p>
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr className="text-left text-[11px] text-muted"><th className="py-1 font-medium">Specialist</th><th className="font-medium">Work</th>
              <th className="text-right font-medium">Starting rate</th><th className="text-right font-medium">Now</th><th className="text-right font-medium">Tickets</th></tr></thead>
            <tbody>{cal.families.map(f => (
              <tr key={f.family} className={cx("border-t border-border/60", !learned.includes(f) && "text-muted")}>
                <td className="py-1"><span className="flex items-center gap-1.5"><AgentAvatar code={f.specialist} size={20} still />{AGENT[f.specialist]?.name}</span></td>
                <td>{f.label}</td><td className="text-right tabular-nums">{f.default} min</td>
                <td className="text-right font-semibold tabular-nums">{Math.round(f.rate * 100) / 100} min</td><td className="text-right tabular-nums">{f.n}</td>
              </tr>))}</tbody>
          </table>
        </div>
        <div>
          <div className="label mb-1">Estimate error, rolling over {cal.rule.window} tickets</div>
          {cal.trend.length ? <div className="flex items-end gap-3">
            <svg width={180} height={36} className="overflow-visible" role="img" aria-label={`Mean absolute error ${last?.mape} %`}>
              <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.6} className="text-primary" /></svg>
            <div className="text-[12px]"><b className="text-[16px] tabular-nums">{last?.mape} %</b><div className="text-muted">after {last?.n} ticket{last?.n !== 1 ? "s" : ""}</div></div>
          </div> : <div className="text-[12px] text-muted">No finished ticket yet.</div>}
        </div>
      </div>
      {cal.history.length > 0 && <div className="mt-3">
        <div className="label mb-1">Latest updates</div>
        <ul className="space-y-1 text-[12px]">{cal.history.slice(0, 6).map((u, i) => (
          <li key={i} className="flex items-start gap-2"><AgentAvatar code={u.specialist} size={18} still />
            <span className="min-w-0 flex-1"><b className="tabular-nums">{rateLine(u.before, u.after)}</b> <span className="text-muted">({u.program}) {explainUpdate(u, cal.rule.alpha)}</span></span></li>))}</ul>
      </div>}
    </Card>
  );
}

export default function TimelineView({ program, onOpen }: { program: Program; onOpen: (t: Ticket) => void }) {
  const [mode, setMode] = useState<"tickets" | "agents">("tickets");
  const running = program.orchestrator?.state === "running";
  const q = useQuery({ queryKey: ["office-timeline", program.id], queryFn: () => api.get<Timeline>(`${BASE}/programs/${program.id}/timeline`),
    refetchInterval: running ? 4000 : false });
  const cal = useQuery({ queryKey: ["office-calibration"], queryFn: () => api.get<Calibration>(`${BASE}/calibration`) });
  if (q.isLoading) return <PageLoader />;
  const tl = q.data;
  if (!tl) return <EmptyState icon={<Route />} title="No timeline yet" body="The timeline fills in when the office runs the tickets." />;
  const waits = tl.rows.reduce((a, r) => { const b = rowBreakdown(r); return { cap: a.cap + b.waitCapacity, blocked: a.blocked + b.blocked }; }, { cap: 0, blocked: 0 });
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
          <div><div className="label">Planned (estimates, {tl.concurrency} at a time)</div><b className="text-[15px] tabular-nums">{fmtMinutes(tl.planned_end)}</b></div>
          <div><div className="label">Elapsed since the first Run</div><b className="text-[15px] tabular-nums">{tl.origin ? fmtMinutes(tl.now) : "not run yet"}</b></div>
          <div><div className="label">Finished tickets: estimate → actual</div>
            <b className="text-[15px] tabular-nums">{fmtMinutes(tl.totals.estimate_min)} → {fmtMinutes(tl.totals.actual_min)}</b>
            <span className="ml-1 text-muted">({tl.totals.done} ticket{tl.totals.done !== 1 ? "s" : ""})</span></div>
          {(waits.cap > 0 || waits.blocked > 0) && <div className="flex items-center gap-1 text-warning"><AlertTriangle className="h-4 w-4" />
            {waits.cap > 0 && `${fmtMinutes(waits.cap)} waiting for capacity`}{waits.cap > 0 && waits.blocked > 0 && " · "}{waits.blocked > 0 && `${fmtMinutes(waits.blocked)} waiting for you`}</div>}
          <div className="ml-auto flex rounded-md border border-border p-0.5 text-[12px]" role="tablist" aria-label="Timeline view">
            {(["tickets", "agents"] as const).map(m => <button key={m} type="button" role="tab" aria-selected={mode === m}
              className={cx("rounded px-2.5 py-1", mode === m ? "bg-primary-soft font-medium text-primary" : "text-muted hover:text-text")}
              onClick={() => setMode(m)}>{m === "tickets" ? "By ticket" : "By agent"}</button>)}
          </div>
        </div>
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-6 rounded-sm border border-dashed border-text/40" />planned (estimate)</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-6 rounded-sm" style={{ background: AGENT.mill.colour }} />work (agent colour)</span>
          <span className="flex items-center gap-1"><span className="fw-tl-wait inline-block h-2.5 w-6 rounded-sm" />waiting for capacity</span>
          <span className="flex items-center gap-1"><span className="fw-tl-blocked inline-block h-2.5 w-6 rounded-sm" />waiting for you</span>
          <span className="flex items-center gap-1 text-danger"><Route className="h-3 w-3" />critical path</span>
          <span className="flex items-center gap-1"><GitPullRequest className="h-3 w-3 text-warning" />change request</span>
          <span>Times are agent working time from the first Run; estimates are labelled as estimates.</span>
        </div>
        <div className="overflow-x-auto"><Chart tl={tl} program={program} mode={mode} onOpen={onOpen} /></div>
      </Card>
      {cal.data && <CalibrationPanel cal={cal.data} />}
    </div>
  );
}
