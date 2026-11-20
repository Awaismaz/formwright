import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, LayoutTemplate, Plus, RotateCcw, Sparkles, Trash2, Zap } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Card, Input, Modal } from "@/components/ui";
import { AgentAvatar, AGENT } from "./Avatars";
import { BASE } from "./api";
import SpeedPanel from "./SpeedPanel";
import DesignGraphCard, { GraphQuestions } from "./DesignGraph";
import LayoutPathCard from "./MasterModel";
import { estimateRange, fmtEta, fmtRange, partPath, planPreview, type BuildPath } from "./model";

const PATH_WORD: Record<BuildPath, string> = { toolbox: "Toolbox", direct: "from the interfaces", template: "workspace template", agent: "AI designer" };
import type { Family, Plan, PlanPart, Program } from "./types";

const PLANNING_LINES = ["Reading the brief", "Finding the sub-assemblies", "Deciding what is bought out", "Choosing part families",
  "Sizing each part's complexity", "Checking what fits the Toolbox", "Laying out the work"];
const MASTER_LINES = ["Modelling every part in one coordinate system", "Placing each body against what carries it",
  "Lining up the screw holes across each joint", "Measuring the joints from the model", "Checking nothing overlaps or floats"];

/** Archie at work: shown while the planning turn runs (typically well under a minute). */
export function Planning({ program }: { program: Program }) {
  const [i, setI] = useState(0);
  const [, tick] = useState(0);
  const master = program.planning?.stage === "master";
  const lines = master ? MASTER_LINES : PLANNING_LINES;
  useEffect(() => { const t = setInterval(() => setI(x => (x + 1) % lines.length), 2400); return () => clearInterval(t); }, [lines.length]);
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t); }, []);
  const since = program.planning?.started_at ? Math.max(0, Math.round((Date.now() - new Date(program.planning.started_at).getTime()) / 1000)) : 0;
  return (
    <Card className="mx-auto flex max-w-xl flex-col items-center px-6 py-12 text-center">
      <AgentAvatar code="archie" state="working" size={112} />
      <div className="mt-5 text-[17px] font-semibold">{master ? `Archie is modelling a master of ${program.name}` : `Archie is planning ${program.name}`}</div>
      <div role="status" aria-live="polite" key={i} className="mt-1 animate-fade-in text-[14px] text-primary">{lines[i % lines.length]}…</div>
      <div className="mt-1 text-[12px] tabular-nums text-muted">{Math.floor(since / 60)}:{String(since % 60).padStart(2, "0")}</div>
      <p className="mt-5 max-w-sm text-[12.5px] text-muted">{master
        ? (program.plan?.layout_path?.reasons?.[0]?.text ?? "This structure has no known connection pattern.") + " The layout and the interfaces are measured from that one model. If it can't be made, the fast path lays the program out, clearly labelled."
        : "You'll review and edit the plan before any ticket opens. If Archie can't finish, you get the standard breakdown instead, clearly labelled."}</p>
    </Card>
  );
}

export default function PlanReview({ program }: { program: Program }) {
  const qc = useQueryClient();
  const [plan, setPlan] = useState<Plan>(() => structuredClone(program.plan!));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [askOpen, setAskOpen] = useState(false);
  const [notes, setNotes] = useState("");
  const canEdit = program.can_edit !== false;
  const k = program.constants;
  useEffect(() => { if (!dirty) setPlan(structuredClone(program.plan!)); }, [program.plan, dirty]);
  const paths = program.plan_estimate?.paths ?? null;
  const preview = useMemo(() => planPreview(plan, k, program.concurrency, program.threads ?? null,
    f => program.families.find(x => x.code === f)?.specialist ?? "mill", paths), [plan, k, program.concurrency, program.threads, program.families, paths]);
  const team = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of plan.subassemblies) for (const p of s.parts) {
      const sp = program.families.find(f => f.code === p.family)?.specialist ?? "mill";
      m.set(sp, (m.get(sp) ?? 0) + 1);
    }
    m.set("fitz", (m.get("fitz") ?? 0) + plan.subassemblies.length + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [plan, program.families]);

  const edit = (fn: (p: Plan) => void) => { setPlan(p => { const n = structuredClone(p); fn(n); return n; }); setDirty(true); };
  const nextId = (prefix: string) => `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
  const refresh = () => { qc.invalidateQueries({ queryKey: ["office-program", program.id] }); qc.invalidateQueries({ queryKey: ["office-home"] }); };

  const approve = async () => {
    setBusy("approve");
    try {
      await api.post(`${BASE}/programs/${program.id}/gates/brief/approve`, { plan: dirty ? plan : null });
      toast.success("Plan approved. Tickets are open on the board.");
      setDirty(false); refresh();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not approve"); } finally { setBusy(null); }
  };
  const express = async () => {
    setBusy("express");
    try {
      const v = await api.post<Program>(`${BASE}/programs/${program.id}/gates/express`, { plan: dirty ? plan : null });
      const ex = v.express;
      if (ex?.approved && ex.run) toast.success("Plan and interfaces approved: the office is building it");
      else if (ex?.approved) toast.success(`Plan and interfaces approved. ${ex.run_blocked ?? "Press Run to build it."}`);
      else toast.warning(`Plan approved. The interfaces have ${ex?.problems ?? 0} problem${ex?.problems === 1 ? "" : "s"}: review them on the Interfaces tab.`);
      setDirty(false); refresh();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not approve"); } finally { setBusy(null); }
  };
  const replan = async (kind: "archie" | "standard") => {
    setBusy(kind);
    try {
      await api.post(`${BASE}/programs/${program.id}/replan`, { planner: kind, notes: kind === "archie" ? notes : "" });
      setAskOpen(false); setNotes(""); setDirty(false); refresh();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not re-plan"); } finally { setBusy(null); }
  };

  const familyOptions = program.families.filter(f => f.code !== "integration");
  const partRow = (si: number, p: PlanPart, pi: number) => {
    const path = partPath(p, paths);
    const est = estimateRange(p.family, p.family === "standard" ? 1 : p.complexity, path, k);
    const sp = program.families.find(f => f.code === p.family)?.specialist ?? "mill";
    return (
      <tr key={p.id} className="border-t border-border align-top">
        <td className="py-1.5 pr-2"><AgentAvatar code={sp} size={26} still label={`${AGENT[sp]?.name}, ${AGENT[sp]?.role}`} /></td>
        <td className="py-1.5 pr-2">
          <Input aria-label="Part name" className="h-8" value={p.name} disabled={!canEdit} onChange={e => edit(n => { n.subassemblies[si]!.parts[pi]!.name = e.target.value; })} />
          {p.description && <div className="mt-1 line-clamp-2 text-[11.5px] text-muted" title={p.description}>{p.description}</div>}
        </td>
        <td className="py-1.5 pr-2">
          <select aria-label="Family" className="input h-8 py-0" value={p.family} disabled={!canEdit} onChange={e => edit(n => { n.subassemblies[si]!.parts[pi]!.family = e.target.value as Family; })}>
            {familyOptions.map(f => <option key={f.code} value={f.code}>{f.label}</option>)}
          </select>
        </td>
        <td className="py-1.5 pr-2">
          <select aria-label="Complexity" className="input h-8 w-16 py-0" value={p.family === "standard" ? 1 : p.complexity} disabled={!canEdit || p.family === "standard"}
            onChange={e => edit(n => { n.subassemblies[si]!.parts[pi]!.complexity = Number(e.target.value); })}>
            {[1, 2, 3, 4, 5].map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </td>
        <td className="py-1.5 pr-2"><Input aria-label="Quantity" className="h-8 w-16" type="number" min={1} value={p.qty} disabled={!canEdit}
          onChange={e => edit(n => { n.subassemblies[si]!.parts[pi]!.qty = Math.max(1, Number(e.target.value) || 1); })} /></td>
        <td className="py-1.5 pr-2 text-right text-[12.5px] tabular-nums text-muted" data-part-estimate={path}>
          <div className="whitespace-nowrap">{fmtRange(est[0], est[1])}</div>
          <div className={cx("text-[10.5px]", path === "agent" ? "text-muted" : "text-success")}>{PATH_WORD[path]}</div></td>
        <td className="py-1.5 text-right">{canEdit && <button className="rounded p-1.5 text-muted hover:bg-danger/10 hover:text-danger" aria-label={`Remove ${p.name}`}
          onClick={() => edit(n => { n.subassemblies[si]!.parts.splice(pi, 1); })}><Trash2 className="h-3.5 w-3.5" /></button>}</td>
      </tr>
    );
  };

  const asking = (program.plan?.graph?.questions?.length ?? 0) > 0;
  const empty = plan.subassemblies.some(s => s.parts.length === 0 || !s.name.trim()) || plan.subassemblies.length === 0;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <div className="min-w-0 space-y-4">
        <Card className="p-4">
          <div className="flex items-start gap-3">
            {plan.source === "archie" ? <AgentAvatar code="archie" size={44} state="review" />
              : <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-text/[.06] text-muted"><LayoutTemplate className="h-5 w-5" /></span>}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[15px] font-semibold">Gate 1 · Brief approval</span>
                <Badge tone={plan.source === "archie" ? "primary" : "neutral"}>{plan.source === "archie" ? "Planned by Archie (AI)" : "Standard breakdown (no AI)"}</Badge>
                {dirty && <Badge tone="warning">Edited</Badge>}
              </div>
              {program.plan?.narrative && <p className="mt-1.5 whitespace-pre-line text-[13px]">{program.plan.narrative}</p>}
              {plan.summary && <p className="mt-1 text-[13px] text-muted">{plan.summary}</p>}
            </div>
          </div>
          {program.plan?.note && <div className="mt-3 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-[12.5px]">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />{program.plan.note}</div>}
          {plan.assumptions.length > 0 && <div className="mt-3"><div className="label mb-1">Assumptions</div>
            <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-muted">{plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></div>}
          <details className="mt-3 text-[12.5px]"><summary className="cursor-pointer select-none font-medium text-muted">The brief</summary>
            <p className="mt-1 whitespace-pre-line">{program.brief}</p></details>
        </Card>

        {program.plan && <LayoutPathCard plan={program.plan} />}
        {program.plan?.graph && <GraphQuestions program={program} graph={program.plan.graph} />}
        {program.plan?.graph && <DesignGraphCard graph={program.plan.graph} />}

        {plan.subassemblies.map((s, si) => (
          <Card key={s.id} className="p-4">
            <div className="mb-2 flex items-center gap-2">
              <AgentAvatar code="fitz" size={28} still label="Fitz assembles this sub-assembly" />
              <Input aria-label="Sub-assembly name" className="h-8 max-w-xs font-semibold" value={s.name} disabled={!canEdit}
                onChange={e => edit(n => { n.subassemblies[si]!.name = e.target.value; })} />
              <span className="text-[12px] text-muted">{s.parts.length} part{s.parts.length === 1 ? "" : "s"}</span>
              {canEdit && <button className="ml-auto rounded p-1.5 text-muted hover:bg-danger/10 hover:text-danger" aria-label={`Remove ${s.name}`}
                onClick={() => edit(n => { n.subassemblies.splice(si, 1); })}><Trash2 className="h-4 w-4" /></button>}
            </div>
            {s.description && <p className="mb-2 text-[12px] text-muted">{s.description}</p>}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-[13px]">
                <thead><tr className="text-left text-[11px] uppercase tracking-wider text-muted">
                  <th className="w-9 pb-1" /><th className="pb-1">Part</th><th className="w-48 pb-1">Family</th><th className="w-20 pb-1" title="1 trivial … 5 very complex">Complexity</th>
                  <th className="w-20 pb-1">Qty</th><th className="w-28 pb-1 text-right" title="Each part on the way it will be built">Estimate</th><th className="w-8 pb-1" /></tr></thead>
                <tbody>{s.parts.map((p, pi) => partRow(si, p, pi))}</tbody>
              </table>
            </div>
            {canEdit && <Button size="sm" variant="ghost" className="mt-2" icon={<Plus className="h-3.5 w-3.5" />}
              onClick={() => edit(n => { n.subassemblies[si]!.parts.push({ id: nextId("p"), name: "New part", family: "machined", complexity: 2, qty: 1, description: "" }); })}>Add part</Button>}
          </Card>
        ))}
        {canEdit && <Button variant="secondary" icon={<Plus className="h-4 w-4" />}
          onClick={() => edit(n => { n.subassemblies.push({ id: nextId("s"), name: "New sub-assembly", description: "", parts: [{ id: nextId("p"), name: "New part", family: "machined", complexity: 2, qty: 1, description: "" }] }); })}>
          Add sub-assembly</Button>}
      </div>

      <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <Card className="p-4">
          <div className="label mb-2">Approving opens</div>
          <div className="text-2xl font-semibold tabular-nums">{preview.tickets} tickets</div>
          <div className="mt-2 space-y-1 text-[12.5px]">
            <div className="flex justify-between"><span className="text-muted">Total effort (estimate)</span><b className="tabular-nums" data-plan-effort>{fmtRange(preview.estimate_lo, preview.estimate_hi)}</b></div>
            <div className="flex justify-between"><span className="text-muted">ETA at {program.concurrency} in parallel</span><b className="tabular-nums">{fmtEta(preview.eta)}</b></div>
          </div>
          <div className="mt-3 border-t border-border pt-3">
            <div className="label mb-2">Team</div>
            <div className="flex flex-wrap gap-2">{team.map(([c, n]) => (
              <span key={c} className="inline-flex items-center gap-1.5 rounded-full border border-border py-0.5 pl-0.5 pr-2 text-[12px]">
                <AgentAvatar code={c} size={22} still /> {AGENT[c]?.name} <span className="text-muted">{n}</span></span>))}</div>
          </div>
          {canEdit && <div className="mt-4 space-y-2">
            {program.light && <div className="rounded-md border border-primary/30 bg-primary-soft/50 p-2.5" data-light-path>
              <div className="mb-1 flex items-center gap-1.5 text-[12.5px] font-semibold text-primary"><Zap className="h-3.5 w-3.5" />
                Small program · {program.light.parts} part{program.light.parts === 1 ? "" : "s"}</div>
              <p className="mb-2 text-[11.5px] text-muted">{program.light.text}</p>
              <Button className="w-full" loading={busy === "express"} disabled={!!busy || empty || asking} icon={<Zap className="h-4 w-4" />} onClick={express} data-express
                title="Approves the plan and, when they have no problems, the interfaces; then runs the office">
                Approve and build</Button>
            </div>}
            <Button className="w-full" variant={program.light ? "secondary" : "primary"} loading={busy === "approve"} disabled={!!busy || empty || asking} icon={<CheckCircle2 className="h-4 w-4" />} onClick={approve}>
              {program.light ? "Approve the plan only" : `Approve plan${dirty ? " with edits" : ""}`}</Button>
            {empty && <p className="text-[11.5px] text-danger">Every sub-assembly needs a name and at least one part.</p>}
            {asking && <p className="text-[11.5px] text-muted">Answer Archie's questions first (or take his defaults).</p>}
            <Button className="w-full" variant="secondary" disabled={!!busy} icon={<Sparkles className="h-4 w-4" />} onClick={() => setAskOpen(true)}>Ask Archie to revise</Button>
            <div className="flex gap-2">
              {plan.source !== "standard" && <Button className="flex-1" size="sm" variant="ghost" loading={busy === "standard"} disabled={!!busy} onClick={() => replan("standard")}>Standard breakdown</Button>}
              {dirty && <Button className="flex-1" size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => { setDirty(false); setPlan(structuredClone(program.plan!)); }}>Discard edits</Button>}
            </div>
          </div>}
          <p className={cx("mt-3 text-[11px] text-muted")} data-estimate-note>Each part is estimated on the way it will be built: Toolbox and parts built from the interfaces take seconds, a part for the AI designer about a minute or two per design turn. The interfaces settle the way at their approval. Ranges, not promises.</p>
        </Card>
        <Card className="p-4"><SpeedPanel program={program} plan={plan} /></Card>
      </aside>

      <Modal open={askOpen} onOpenChange={setAskOpen} title="Ask Archie to revise the plan"
        description="Say what to change. Archie plans again from the brief and your notes (uses tokens). Your unsaved edits are replaced."
        footer={<><Button variant="secondary" onClick={() => setAskOpen(false)}>Cancel</Button>
          <Button loading={busy === "archie"} disabled={!notes.trim()} onClick={() => replan("archie")}>Re-plan with Archie</Button></>}>
        <textarea className="input min-h-[110px] py-2" value={notes} onChange={e => setNotes(e.target.value)} maxLength={2000}
          placeholder="e.g. Split the housing into base and cover; the motor is bought out; add a guard over the belt." />
      </Modal>
    </div>
  );
}
