import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Circle, Coins, FileDown, FlaskConical, Gauge, Lock, MoreHorizontal, PartyPopper, Pause, Play, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx, num, PAGE } from "@/lib/format";
import { useTitle } from "@/lib/title";
import { Badge, Button, Card, EmptyState, Menu, MenuContent, MenuItem, MenuTrigger, Modal, PageLoader, Progress, Stat, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { STATUS_LABEL } from "./Home";
import { BASE, useProgram, useProgramEvents } from "./api";
import AssemblyView from "./AssemblyView";
import Board from "./Board";
import Deliverables from "./Deliverables";
import Interfaces from "./Interfaces";
import PlanReview, { Planning } from "./PlanReview";
import TicketDrawer, { ActorBadge } from "./TicketDrawer";
import TimelineView from "./TimelineView";
import ArchieChat, { TalkToArchieButton } from "./ArchieChat";
import SpeedPanel from "./SpeedPanel";
import Tree from "./Tree";
import { saveNative } from "@/components/NativeExport";
import { budgetTone, fmtEta, fmtMinutes, orchestratorLabel, recentHandoffs } from "./model";
import type { OfficeEvent, Program, Ticket } from "./types";

function Gates({ p }: { p: Program }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {p.gates.map((g, i) => (
        <span key={g.code} className="flex items-center gap-2">
          {i > 0 && <span className="h-px w-4 bg-border" />}
          <span title={g.note ?? (g.by ? `Approved by ${g.by}` : undefined)}
            className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px]",
              g.status === "approved" ? "border-success/30 bg-success/10 text-success" : g.status === "pending" ? "border-warning/30 bg-warning/10 text-warning" : "border-border text-muted")}>
            {g.status === "approved" ? <CheckCircle2 className="h-3.5 w-3.5" /> : g.status === "pending" ? <Circle className="h-3.5 w-3.5" /> : <Lock className="h-3 w-3" />}
            {g.name}{g.status === "later" && <span className="text-[10.5px]">· not on this program</span>}
            {g.code === "icd" && p.icd && g.status !== "locked" && <span className="text-[10.5px]">· ICD v{p.icd.version}</span>}
            {g.code === "release" && p.released && <span className="text-[10.5px]">· rev {p.released.rev}</span>}
          </span>
        </span>))}
    </div>
  );
}

function Activity({ program }: { program: Program }) {
  const q = useQuery({ queryKey: ["office-activity", program.id], queryFn: () => api.get<{ items: OfficeEvent[] }>(`${BASE}/programs/${program.id}/activity?limit=300`) });
  if (q.isLoading) return <PageLoader />;
  return (
    <Card className="divide-y divide-border">
      {(q.data?.items ?? []).map(e => (
        <div key={e.seq} className="flex items-start gap-3 px-4 py-2.5">
          <ActorBadge e={e} size={28} />
          <div className="min-w-0 flex-1 text-[13px]">{e.text}<div className="text-[11px] text-muted">{e.actor.name} · {ago(e.t)}</div></div>
        </div>))}
    </Card>
  );
}

function LiveStrip({ recent, live }: { recent: OfficeEvent[]; live: boolean }) {
  const e = recent[0];
  return (
    <div className="flex min-w-0 items-center gap-2 text-[12px] text-muted" aria-live="polite">
      <span className={cx("h-2 w-2 shrink-0 rounded-full", live ? "bg-success shadow-[0_0_0_3px_rgb(47_158_68/.18)]" : "bg-text/25")} title={live ? "Live updates on" : "Reconnecting: updates every few seconds"} />
      {live ? "Live" : "Polling"}
      {e && <span key={e.seq} className="min-w-0 animate-fade-in truncate">· {e.text}</span>}
    </div>
  );
}

const TONE_CLS: Record<string, string> = {
  neutral: "border-border bg-panel2 text-muted", primary: "border-primary/30 bg-primary-soft text-primary",
  warning: "border-warning/40 bg-warning/10 text-warning", danger: "border-danger/40 bg-danger/10 text-danger",
  success: "border-success/30 bg-success/10 text-success",
};

/** Run / Pause for the whole program, the office's state, and an honest note on what running means. */
function RunBar({ p, onSpeed }: { p: Program; onSpeed: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const o = p.orchestrator;
  const st = orchestratorLabel(o, p.concurrency);
  const running = o?.state === "running";
  const canEdit = p.can_edit !== false;
  const act = async (what: "run" | "pause") => {
    setBusy(true);
    try {
      const v = await api.post<Program>(`${BASE}/programs/${p.id}/${what}`);
      qc.setQueryData(["office-program", p.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
      toast.success(what === "run" ? "The office is working the tickets" : "Paused: agents finish the step they are on");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Failed");
      if (e instanceof ApiError && e.cta) nav(e.cta);
    } finally { setBusy(false); }
  };
  return (
    <Card className="mb-4 flex flex-wrap items-center gap-3 p-3">
      {canEdit && p.status !== "complete" && p.icd?.status !== "draft" && (running
        ? <Button variant="secondary" loading={busy} icon={<Pause className="h-4 w-4" />} onClick={() => act("pause")}>Pause</Button>
        : <Button loading={busy} icon={<Play className="h-4 w-4" />} onClick={() => act("run")}>{o?.state && o.state !== "idle" ? "Resume" : "Run"}</Button>)}
      <span className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium", TONE_CLS[st.tone])} aria-live="polite">
        {running && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}{st.label}</span>
      {canEdit && <Button variant="ghost" size="sm" icon={<Gauge className="h-4 w-4" />} onClick={onSpeed} data-speed-open>
        {p.concurrency} agents{p.threads ? ` · ${Object.entries(p.threads).filter(([, n]) => n > 1).map(([c, n]) => `${c[0]!.toUpperCase()}${c.slice(1)} ×${n}`).join(", ")}` .replace(/ · $/, "") : ""} · {num(p.budget.tokens)} tokens</Button>}
      {o?.simulated && <span title="Development mode: agents are simulated and no AI is called"><Badge tone="warning"><FlaskConical className="mr-1 inline h-3 w-3" />Simulated agents</Badge></span>}
      {o?.bypass && <span title="God mode: the token budget is not enforced"><Badge tone="neutral">Budget bypass</Badge></span>}
      <p className="min-w-[260px] flex-1 text-[12px] text-muted">
        {running || o?.state === "complete" || o?.state === "paused"
          ? <>Agents pick tickets by critical path, {p.concurrency} at a time. Hex tries the Toolbox and your parts first; each part is designed in its own Design Studio project; <b>Gage</b> checks every part before it is approved{p.review_gate ? <> and then <b>you</b> approve it (review gate on)</> : ""}; <b>Fitz</b> assembles each level{p.deliverables_auto !== false ? <>; then <b>Ortho</b> draws every part and the assembly with its BOM and <b>Smithy</b> reviews every part for manufacture</> : ""}. Comment, pause, reassign or take over any ticket.</>
          : o?.state === "stopped"
            ? <>{o.reason === "balance" ? "The workspace ran out of tokens." : `The program reached its ${num(p.budget.tokens)}-token budget.`} Work already running finished; nothing new starts until you {o.reason === "balance" ? "top up" : "raise the budget (program menu)"} and press Resume.</>
            : p.icd?.status === "draft" ? (p.icd.problems.length > 0
              ? <><b>Next: the Interfaces tab.</b> {p.icd.problems.length} interface problem{p.icd.problems.length === 1 ? "" : "s"} must be cleared (press <b>Fix with Archie</b> there), then approve the ICD and press Run.</>
              : <><b>Next: approve the interfaces (ICD)</b> on the Interfaces tab. Part work starts at that gate, against the numbers you approved; then press Run.</>)
              : <>Press <b>Run</b> and the office works the tickets: up to {p.concurrency} agents at a time, by critical path, inside the program's token budget. Each part is built to its interfaces and swapped into the program assembly when Gage approves it. You can still move tickets and open parts by hand.</>}
      </p>
    </Card>
  );
}

function BudgetDialog({ p, open, onOpenChange }: { p: Program; open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const [tokens, setTokens] = useState(p.budget.tokens);
  const [conc, setConc] = useState(p.concurrency);
  const [deliv, setDeliv] = useState(p.deliverables_auto !== false);
  const [gate, setGate] = useState(!!p.review_gate);
  const save = async () => {
    try {
      const v = await api.patch<Program>(`${BASE}/programs/${p.id}`, { budget_tokens: tokens, concurrency: conc, deliverables: deliv, review_gate: gate });
      qc.setQueryData(["office-program", p.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
      onOpenChange(false);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Budget, agents and reviews" description="The office warns at 80 % of the budget and starts no new work at 100 %."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={save}>Save</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block"><span className="label">Token budget</span>
          <input className="input mt-1" type="number" min={0} step={100} value={tokens} onChange={e => setTokens(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label className="block"><span className="label">Agents at a time</span>
          <input className="input mt-1" type="number" min={1} max={12} value={conc} onChange={e => setConc(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} /></label>
      </div>
      <p className="mt-2 text-[12px] text-muted">More agents finish sooner but share one AI subscription: above 3 at a time, expect waits for capacity.</p>
      <label className="mt-3 flex items-start gap-2 text-[12.5px]"><input type="checkbox" className="mt-0.5" checked={deliv} onChange={e => setDeliv(e.target.checked)} />
        <span>Make the deliverables after integration: Ortho's drawings (parts and the assembly with its BOM) and Smithy's manufacturing review. They cost no tokens.</span></label>
      <label className="mt-2 flex items-start gap-2 text-[12.5px]"><input type="checkbox" className="mt-0.5" checked={gate} onChange={e => setGate(e.target.checked)} data-review-gate-option />
        <span>Review every part myself: after Gage passes a part it waits in In review for your approval or your requested changes. Switching this off lets waiting parts go on.</span></label>
    </Modal>
  );
}

export default function ProgramPage() {
  const { pid } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = useProgram(pid);
  const { recent, live } = useProgramEvents(pid);
  const [open, setOpen] = useState<Ticket | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [speedOpen, setSpeedOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i); }, []);
  const handoffs = recentHandoffs(recent, now);
  const p = q.data;
  useTitle(p?.name ?? "Design Office");
  const icdPending = p?.icd?.status === "draft" && p.gates.some(g => g.code === "icd" && g.status === "pending");
  const tab = params.get("tab") ?? (icdPending ? "interfaces" : "board");
  useEffect(() => {  // deep link from the reviews inbox: ?ticket=<id>
    const tid = params.get("ticket");
    if (tid && p) { const t = p.tickets.find(x => x.id === tid); if (t) setOpen(t); params.delete("ticket"); setParams(params, { replace: true }); }
  }, [p, params, setParams]);
  useEffect(() => {
    const m = recent[0];
    if (m?.type === "program.milestone" || m?.type === "program.done" || m?.type === "program.released") toast.success(m.text, { icon: <PartyPopper className="h-4 w-4" /> });
    else if (m?.type === "deliverable.done") toast.success(m.text);
    else if (m?.type === "cr.accepted") toast.info(m.text);
    else if (m?.type === "cr.rejected") toast.warning(m.text);
    else if (m?.type === "budget.warn") toast.warning(m.text);
    else if (m?.type === "budget.stop") toast.error(m.text);
  }, [recent]);

  if (q.isLoading) return <PageLoader />;
  if (q.error || !p) return <div className={PAGE}><EmptyState icon={<Circle />} title="Program not found" body={q.error instanceof ApiError ? q.error.message : undefined}
    action={<Button onClick={() => nav("/app/office")}>Back to the Design Office</Button>} /></div>;

  const done = (p.counts?.approved ?? 0) + (p.counts?.integrated ?? 0);
  const canEdit = p.can_edit !== false;
  const del = async () => {
    try { await api.del(`${BASE}/programs/${p.id}`); qc.invalidateQueries({ queryKey: ["office-home"] }); toast.success("Program deleted"); nav("/app/office"); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not delete"); }
  };
  const bt = budgetTone(p.budget.spent, p.budget.tokens);

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-6">
      <Link to="/app/office" className="mb-2 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-3.5 w-3.5" />Design Office</Link>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[22px] font-semibold tracking-tight">{p.name}</h1>
            <span className="kbd">{p.key}</span>
            <Badge tone={p.status === "plan_review" ? "warning" : p.status === "complete" ? "success" : p.status === "planning" ? "primary" : "neutral"}>{p.released ? `Released · rev ${p.released.rev}` : STATUS_LABEL[p.status]}</Badge>
            <Badge tone="preview">Preview</Badge>
          </div>
          <div className="mt-2"><Gates p={p} /></div>
        </div>
        <div className="flex items-center gap-3">
          <LiveStrip recent={recent} live={live} />
          <TalkToArchieButton onClick={() => setChatOpen(true)} programId={p.id} />
          {canEdit && <Menu><MenuTrigger asChild><Button variant="ghost" size="sm" aria-label="Program actions"><MoreHorizontal className="h-4 w-4" /></Button></MenuTrigger>
            <MenuContent><MenuItem icon={<FileDown />} onSelect={() => { void saveNative(`/api/native/programs/${p.id}/export`, `${p.name}.fwprog`, "fwprog"); }}>Save as file (.fwprog)</MenuItem>
            <MenuItem icon={<Coins />} onSelect={() => setBudgetOpen(true)}>Program settings…</MenuItem>
              <MenuItem danger icon={<Trash2 />} onSelect={() => setConfirm(true)}>Delete program</MenuItem></MenuContent></Menu>}
        </div>
      </div>

      {p.status === "planning" && <Planning program={p} />}
      {p.status === "plan_review" && p.plan && <PlanReview program={p} />}
      {(p.status === "active" || p.status === "complete") && <>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Progress" value={`${Math.round(p.rollup?.progress ?? 0)} %`} sub={<Progress className="mt-1" value={p.rollup?.progress ?? 0} tone={p.status === "complete" ? "success" : "primary"} />} />
          <Stat label="Tickets done" value={`${done} / ${p.tickets.length}`} sub={`${p.counts.in_design} in design · ${p.counts.in_review} in review`} />
          <Stat label="ETA (remaining)" value={fmtEta(p.eta)} sub={`of ${fmtMinutes(p.rollup?.estimate_min ?? 0)} estimated · ${p.concurrency} in parallel`} />
          <Stat label="Tokens" value={num(p.budget.spent)} sub={<div>
            <span className={cx(bt.tone === "warning" && "text-warning", bt.tone === "danger" && "text-danger")}>of {num(p.budget.tokens)} budget · {Math.round(bt.pct)} %</span>
            {p.budget.tokens > 0 && <Progress className="mt-1" value={Math.min(100, bt.pct)} tone={bt.tone} />}</div>} />
        </div>
        {icdPending && tab !== "interfaces" && <Card className="mb-4 flex flex-wrap items-center gap-3 border-warning/40 bg-warning/5 p-3" data-icd-banner>
          <ShieldCheck className="h-5 w-5 text-warning" />
          <div className="min-w-[240px] flex-1 text-[13px]"><b>Review the interfaces before part work starts.</b> Archie named {p.icd!.interfaces.length} interfaces between the parts. Approve them on the Interfaces tab: the office can't run until then.</div>
          <Button variant="secondary" onClick={() => { params.set("tab", "interfaces"); setParams(params, { replace: true }); }}>Review interfaces</Button>
        </Card>}
        <RunBar p={p} onSpeed={() => setSpeedOpen(true)} />
        <Tabs value={tab} onValueChange={v => { params.set("tab", v); setParams(params, { replace: true }); }}>
          <TabList className="mb-3"><Tab value="board">Board</Tab><Tab value="interfaces">Interfaces{icdPending ? " ·" : ""}</Tab><Tab value="assembly">Assembly</Tab><Tab value="deliverables">Deliverables{p.gates.some(g => g.code === "release" && g.status === "pending") ? " ·" : ""}</Tab><Tab value="timeline">Timeline</Tab><Tab value="tree">Tree</Tab><Tab value="activity">Activity</Tab><Tab value="brief">Brief</Tab></TabList>
          <TabPanel value="board"><Board program={p} onOpen={setOpen} handoffs={handoffs} /></TabPanel>
          <TabPanel value="interfaces"><Interfaces program={p} /></TabPanel>
          <TabPanel value="assembly"><AssemblyView program={p} recent={recent} /></TabPanel>
          <TabPanel value="deliverables"><Deliverables program={p} /></TabPanel>
          <TabPanel value="timeline"><TimelineView program={p} onOpen={setOpen} /></TabPanel>
          <TabPanel value="tree"><Tree program={p} onOpen={setOpen} /></TabPanel>
          <TabPanel value="activity"><Activity program={p} /></TabPanel>
          <TabPanel value="brief">
            <Card className="space-y-3 p-5 text-[13px]">
              <div><div className="label mb-1">Brief</div><p className="whitespace-pre-line">{p.brief}</p></div>
              {p.plan && <div><div className="label mb-1">Plan</div>
                <p>{p.plan.source === "archie" ? "Planned by Archie (AI)" : "Standard breakdown (no AI)"}{p.plan.edited ? ", edited at approval" : ""}. {p.plan.summary}</p>
                {p.plan.assumptions.length > 0 && <ul className="mt-1 list-disc pl-5 text-muted">{p.plan.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>}</div>}
            </Card>
          </TabPanel>
        </Tabs>
      </>}
      <TicketDrawer program={p} ticket={open} onClose={() => setOpen(null)} />
      {budgetOpen && <BudgetDialog p={p} open={budgetOpen} onOpenChange={setBudgetOpen} />}
      <Modal open={speedOpen} onOpenChange={setSpeedOpen} title="Speed and budget" description="Change them any time; the office picks the new numbers up with its next ticket.">
        <SpeedPanel program={p} />
      </Modal>
      <ArchieChat program={p} open={chatOpen} onOpenChange={setChatOpen} />
      <Modal open={confirm} onOpenChange={setConfirm} title={`Delete ${p.name}?`}
        description="The program, its board and its history are removed. Design Studio parts and assemblies opened from tickets stay in Projects."
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="danger" onClick={del}>Delete program</Button></>} />
    </div>
  );
}
