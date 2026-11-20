import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Gauge, Minus, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx, num } from "@/lib/format";
import { Button } from "@/components/ui";
import { AGENT, AgentAvatar } from "./Avatars";
import { BASE } from "./api";
import { DESIGNER_CODES, etaRange, fmtEta, fmtMinutes, planPreview, workByAgent, type Threads } from "./model";
import type { Family, Plan, Program } from "./types";

function Stepper({ value, min, max, onChange, label, auto }: { value: number | null; min: number; max: number; onChange: (v: number) => void; label: string; auto?: boolean }) {
  const v = value ?? 0;
  return (
    <span className="inline-flex items-center rounded-md border border-border" role="group" aria-label={label}>
      <button type="button" className="px-1.5 py-1 text-muted hover:text-text disabled:opacity-40" disabled={value !== null && v <= min} aria-label={`Fewer: ${label}`}
        onClick={() => onChange(value === null ? min : Math.max(min, v - 1))}><Minus className="h-3 w-3" /></button>
      <span className="min-w-[38px] text-center text-[12.5px] font-semibold tabular-nums">{value === null && auto ? "Auto" : v}</span>
      <button type="button" className="px-1.5 py-1 text-muted hover:text-text disabled:opacity-40" disabled={value !== null && v >= max} aria-label={`More: ${label}`}
        onClick={() => onChange(value === null ? Math.min(max, 2) : Math.min(max, v + 1))}><Plus className="h-3 w-3" /></button>
    </span>
  );
}

/** Speed and budget at any stage (CD-027): agents at a time, threads per designer (parallel sub-agents), the token
 * budget, and what the change does to the ETA before you save it. In plan review it previews the edited plan. */
export default function SpeedPanel({ program, plan, className }: { program: Program; plan?: Plan; className?: string }) {
  const qc = useQueryClient();
  const k = program.constants;
  const saved = useMemo(() => ({ conc: program.concurrency, threads: program.threads ?? null, tokens: program.budget.tokens }),
    [program.concurrency, program.threads, program.budget.tokens]);
  const [conc, setConc] = useState(saved.conc);
  const [threads, setThreads] = useState<Threads | null>(saved.threads);
  const [tokens, setTokens] = useState(saved.tokens);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setConc(saved.conc); setThreads(saved.threads); setTokens(saved.tokens); }, [saved]);
  const canEdit = program.can_edit !== false && program.status !== "planning";

  const spec = (f: Family) => program.families.find(x => x.code === f)?.specialist ?? "mill";
  const model = useMemo(() => {
    if (plan) {
      const p = (c: number, t: Threads | null) => planPreview(plan, k, c, t, spec, program.plan_estimate?.paths);
      const base = p(saved.conc, saved.threads), next = p(conc, threads);
      return { before: base.eta, after: next.eta, work: next.work, parts: next.parts };
    }
    const open = program.tickets.filter(t => t.progress < 100);
    const work = workByAgent(open);
    const parts: Record<string, number> = {};
    for (const t of open) if (t.kind === "part" || t.kind === "standard") parts[t.specialist] = (parts[t.specialist] ?? 0) + 1;
    const cp = program.eta?.critical_path_min ?? 0, total = program.eta?.remaining_min ?? 0;
    return { before: etaRange(cp, total, work, saved.conc, saved.threads, k), after: etaRange(cp, total, work, conc, threads, k), work, parts };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan, program.tickets, program.eta, k, conc, threads, saved]);

  const designers = DESIGNER_CODES.filter(c => (model.work[c] ?? 0) > 0 || threads?.[c] !== undefined && (model.parts[c] ?? 0) > 0);
  const shown = designers.length ? designers : DESIGNER_CODES.filter(c => (model.parts[c] ?? 0) > 0);
  const threadSum = shown.reduce((s, c) => s + (threads?.[c] ?? 0), 0);
  const dirty = conc !== saved.conc || tokens !== saved.tokens || JSON.stringify(threads ?? null) !== JSON.stringify(saved.threads ?? null);
  const saves = model.before.high_min - model.after.high_min;

  const setThread = (c: string, v: number) => {
    const next = { ...(threads ?? {}), [c]: v };
    setThreads(next);
    const sum = shown.reduce((s, x) => s + (next[x] ?? 0), 0);
    if (sum > conc) setConc(Math.min(12, sum));  // more sub-agents than the office runs at once: raise the cap with them
  };
  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = {};
      if (conc !== saved.conc) body.concurrency = conc;
      if (tokens !== saved.tokens) body.budget_tokens = tokens;
      if (JSON.stringify(threads ?? null) !== JSON.stringify(saved.threads ?? null) && threads) body.threads = threads;
      const v = await api.patch<Program>(`${BASE}/programs/${program.id}`, body);
      qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
      toast.success(program.orchestrator?.state === "running" ? "Saved: the office uses it from the next pick-up" : "Saved");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  };

  return (
    <div className={cx("text-[12.5px]", className)} data-speed-panel>
      <div className="label mb-2 flex items-center gap-1.5"><Gauge className="h-3.5 w-3.5" />Speed and budget</div>
      <div className="flex items-center justify-between gap-2 py-1">
        <span><b>Agents at a time</b><span className="block text-[11px] text-muted">All agents together</span></span>
        <Stepper value={conc} min={1} max={12} onChange={setConc} label="Agents at a time" />
      </div>
      {shown.length > 0 && <div className="mt-1 border-t border-border pt-2">
        <div className="mb-1 text-[11px] text-muted">Threads per designer: parallel sub-agents, each taking its own parts.</div>
        {shown.map(c => (
          <div key={c} className="flex items-center gap-2 py-1">
            <AgentAvatar code={c} size={24} still />
            <span className="min-w-0 flex-1"><b>{AGENT[c]?.name}</b>
              <span className="block text-[11px] text-muted">{model.parts[c] ?? 0} part{model.parts[c] === 1 ? "" : "s"} · {fmtMinutes(model.work[c] ?? 0)} of work</span></span>
            <Stepper value={threads?.[c] ?? null} min={1} max={12} auto onChange={v => setThread(c, v)} label={`${AGENT[c]?.name} threads`} />
          </div>))}
        {threads && threadSum > conc && <p className="mt-1 text-[11px] text-warning">Only {conc} agents work at once, so not every thread runs together.</p>}
        {!threads && <p className="mt-1 text-[11px] text-muted">Auto: designers share the {conc} agents as work comes up.</p>}
      </div>}
      <label className="mt-2 flex items-center justify-between gap-2 border-t border-border pt-2">
        <span><b>Token budget</b><span className="block text-[11px] text-muted">{num(program.budget.spent)} used so far</span></span>
        <input className="input h-8 w-28 text-right tabular-nums" type="number" min={0} step={500} value={tokens} disabled={!canEdit} aria-label="Token budget"
          onChange={e => setTokens(Math.max(0, Math.min(1_000_000, Number(e.target.value) || 0)))} />
      </label>
      <div className="mt-2 rounded-md bg-panel2 px-2.5 py-2" aria-live="polite">
        <div className="flex justify-between"><span className="text-muted">ETA now</span><b className="tabular-nums">{fmtEta(model.before)}</b></div>
        {dirty && <div className="flex justify-between"><span className="text-muted">With these changes</span>
          <b className={cx("tabular-nums", saves > 0.05 ? "text-success" : saves < -0.05 ? "text-warning" : "")}>{fmtEta(model.after)}</b></div>}
        {dirty && Math.abs(saves) > 0.05 && <div className="text-right text-[11px] text-muted">{saves > 0 ? `up to ${fmtMinutes(saves)} sooner` : `up to ${fmtMinutes(-saves)} later`}</div>}
      </div>
      {canEdit && dirty && <div className="mt-2 flex gap-2">
        <Button size="sm" className="flex-1" loading={busy} onClick={save}>Save</Button>
        <Button size="sm" variant="ghost" onClick={() => { setConc(saved.conc); setThreads(saved.threads); setTokens(saved.tokens); }}>Reset</Button>
      </div>}
      <p className="mt-2 text-[10.5px] text-muted">More agents finish sooner but share one AI subscription: above 3 at a time, expect waits for capacity. Estimates are ranges, not promises.</p>
    </div>
  );
}
