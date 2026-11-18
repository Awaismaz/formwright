import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Circle, FileDown, Lock, MoreHorizontal, PartyPopper, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx, num, PAGE } from "@/lib/format";
import { useTitle } from "@/lib/title";
import { Badge, Button, Card, EmptyState, Menu, MenuContent, MenuItem, MenuTrigger, Modal, PageLoader, Progress, Stat, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { AutoRunNote, STATUS_LABEL } from "./Home";
import { BASE, useProgram, useProgramEvents } from "./api";
import Board from "./Board";
import PlanReview, { Planning } from "./PlanReview";
import TicketDrawer, { ActorBadge } from "./TicketDrawer";
import Tree from "./Tree";
import { saveNative } from "@/components/NativeExport";
import { fmtEta, fmtMinutes } from "./model";
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
            {g.name}{g.status === "later" && <span className="text-[10.5px]">· later</span>}
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

export default function ProgramPage() {
  const { pid } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const q = useProgram(pid);
  const { recent, live } = useProgramEvents(pid);
  const [open, setOpen] = useState<Ticket | null>(null);
  const [confirm, setConfirm] = useState(false);
  const p = q.data;
  useTitle(p?.name ?? "Design Office");
  const tab = params.get("tab") ?? "board";
  useEffect(() => {  // deep link from the reviews inbox: ?ticket=<id>
    const tid = params.get("ticket");
    if (tid && p) { const t = p.tickets.find(x => x.id === tid); if (t) setOpen(t); params.delete("ticket"); setParams(params, { replace: true }); }
  }, [p, params, setParams]);
  useEffect(() => {
    const m = recent[0];
    if (m?.type === "program.milestone") toast.success(m.text, { icon: <PartyPopper className="h-4 w-4" /> });
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
  const budgetPct = p.budget.tokens ? (100 * p.budget.spent) / p.budget.tokens : 0;

  return (
    <div className="mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-6">
      <Link to="/app/office" className="mb-2 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-3.5 w-3.5" />Design Office</Link>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[22px] font-semibold tracking-tight">{p.name}</h1>
            <span className="kbd">{p.key}</span>
            <Badge tone={p.status === "plan_review" ? "warning" : p.status === "complete" ? "success" : p.status === "planning" ? "primary" : "neutral"}>{STATUS_LABEL[p.status]}</Badge>
            <Badge tone="preview">Preview</Badge>
          </div>
          <div className="mt-2"><Gates p={p} /></div>
        </div>
        <div className="flex items-center gap-3">
          <LiveStrip recent={recent} live={live} />
          {canEdit && <Menu><MenuTrigger asChild><Button variant="ghost" size="sm" aria-label="Program actions"><MoreHorizontal className="h-4 w-4" /></Button></MenuTrigger>
            <MenuContent><MenuItem icon={<FileDown />} onSelect={() => { void saveNative(`/api/native/programs/${p.id}/export`, `${p.name}.fwprog`, "fwprog"); }}>Save as file (.fwprog)</MenuItem>
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
          <Stat label="Tokens" value={num(p.budget.spent)} sub={<span className={cx(budgetPct >= 80 && "text-warning")}>of {num(p.budget.tokens)} budget{budgetPct >= 80 ? ` · ${Math.round(budgetPct)} %` : ""}</span>} />
        </div>
        <AutoRunNote className="mb-4" />
        <Tabs value={tab} onValueChange={v => { params.set("tab", v); setParams(params, { replace: true }); }}>
          <TabList className="mb-3"><Tab value="board">Board</Tab><Tab value="tree">Tree</Tab><Tab value="activity">Activity</Tab><Tab value="brief">Brief</Tab></TabList>
          <TabPanel value="board"><Board program={p} onOpen={setOpen} /></TabPanel>
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
      <Modal open={confirm} onOpenChange={setConfirm} title={`Delete ${p.name}?`}
        description="The program, its board and its history are removed. Design Studio parts and assemblies opened from tickets stay in Projects."
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="danger" onClick={del}>Delete program</Button></>} />
    </div>
  );
}
