import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, ClipboardCheck, Coins, Inbox, Info, Plus, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx, num, PAGE } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Modal, PageHeader, PageLoader, Progress } from "@/components/ui";
import { FileButtons } from "@/components/NativeExport";
import { AgentAvatar, AGENT, AGENTS, STATE_LABEL } from "./Avatars";
import { BASE, useHome } from "./api";
import { fmtEta } from "./model";
import type { InboxItem, ProgramSummary, RosterAgent } from "./types";

export const STATUS_LABEL: Record<string, string> = {
  planning: "Archie is planning", plan_review: "Plan waiting for approval", active: "In work", complete: "Integrated",
};

export function AutoRunNote({ className }: { className?: string }) {
  return (
    <div className={cx("flex items-start gap-2 rounded-lg border border-primary/20 bg-primary-soft/50 px-3 py-2 text-[12.5px] text-text", className)}>
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <span>Archie plans the program; press <b>Run</b> on a program and the office works its tickets: Hex reuses Toolbox and
        company parts, specialists design each part in its own Design Studio project, Gage checks every part, Fitz assembles.
        The Design Office is in Preview: estimates are estimates, and drawings, interfaces (ICD) and release come later.</span>
    </div>
  );
}

function ProgramCard({ p }: { p: ProgramSummary }) {
  const done = (p.counts?.approved ?? 0) + (p.counts?.integrated ?? 0);
  return (
    <Link to={`/app/office/programs/${p.id}`} className="card group block p-4 transition hover:border-primary/40 hover:shadow-pop">
      <div className="flex flex-wrap items-start gap-3 max-sm:gap-y-1.5">
        <AgentAvatar code="archie" size={38} state={p.status === "planning" ? "working" : p.status === "plan_review" ? "review" : p.status === "complete" ? "done" : "idle"} />
        <div className="min-w-0 flex-1 max-sm:basis-[calc(100%-50px)]">
          <div className="flex items-center gap-2">
            <span className="truncate text-[15px] font-semibold group-hover:text-primary">{p.name}</span>
            <span className="kbd">{p.key}</span>
          </div>
          <div className="mt-0.5 line-clamp-1 text-[12.5px] text-muted">{p.brief}</div>
        </div>
        <Badge className="max-sm:ml-[50px]" tone={p.status === "plan_review" ? "warning" : p.status === "complete" ? "success" : p.status === "planning" ? "primary" : "neutral"}>
          {STATUS_LABEL[p.status]}</Badge>
      </div>
      {p.rollup ? (
        <div className="mt-3">
          <div className="mb-1 flex items-baseline justify-between text-[12px] text-muted">
            <span><b className="text-text tabular-nums">{Math.round(p.rollup.progress)} %</b> · {done} of {p.tickets} tickets done</span>
            <span title="Estimated remaining agent time, at the program's concurrency">ETA {fmtEta(p.eta)}</span>
          </div>
          <Progress value={p.rollup.progress} tone={p.status === "complete" ? "success" : "primary"} />
        </div>
      ) : <div className="mt-3 text-[12px] text-muted">{p.status === "planning" ? "Archie is breaking the product down…" : "Review and approve the plan to open tickets."}</div>}
      <div className="mt-2 text-[11px] text-muted">Updated {ago(p.updated_at)}</div>
    </Link>
  );
}

function RosterCard({ a }: { a: RosterAgent }) {
  const [hover, setHover] = useState(false);
  const preview = hover && a.state === "idle";
  return (
    <Card className="flex items-center gap-3 p-3" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <AgentAvatar code={a.code} state={preview ? "working" : a.state} size={52}
        label={`${a.name}, ${a.role}: ${STATE_LABEL[a.state]}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[14px] font-semibold" style={{ color: a.colour }}>{a.name}</span>
          {a.phase > 3 && <Badge className="ml-auto" tone="neutral">Later</Badge>}
          {a.code === "benny" && <span className="ml-auto" title="Sheet-metal tools are not in the app yet: Benny designs sheet parts as solids and says so"><Badge tone="neutral">Solids only</Badge></span>}
        </div>
        <div className="truncate text-[11.5px] text-muted">{a.role}</div>
        <div className="mt-1 truncate text-[12px]">{a.line}</div>
        {(a.assigned > 0 || a.delivered > 0) && <div className="mt-0.5 text-[11px] text-muted">{a.assigned} open · {a.delivered} {a.code === "archie" ? "plans approved" : "done"}</div>}
      </div>
    </Card>
  );
}

function InboxRow({ i, canEdit }: { i: InboxItem; canEdit: boolean }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const move = async (column: string) => {
    setBusy(true);
    try {
      await api.post(`${BASE}/programs/${i.program_id}/tickets/${i.ticket_id}/move`, { column });
      toast.success(column === "approved" ? `${i.key} approved` : `Changes requested on ${i.key}`);
      qc.invalidateQueries({ queryKey: ["office-home"] });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  if (i.kind === "blocked") return (
    <Link to={`/app/office/programs/${i.program_id}?ticket=${i.ticket_id}`} className="flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left last:border-0 hover:bg-panel2">
      <AgentAvatar code={i.specialist ?? "gage"} state="blocked" size={30} still />
      <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium"><span className="font-mono text-[11px] text-muted">{i.key}</span> {i.title}</div>
        <div className="line-clamp-2 text-[11.5px] text-warning">{i.reason ?? "Needs your decision"}</div></div>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted" />
    </Link>
  );
  if (i.kind === "brief") return (
    <button onClick={() => nav(`/app/office/programs/${i.program_id}`)} className="flex w-full items-center gap-3 border-b border-border px-3 py-2.5 text-left last:border-0 hover:bg-panel2">
      <AgentAvatar code="archie" state="review" size={30} />
      <div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium">{i.title}</div>
        <div className="text-[11.5px] text-muted">Brief gate · {i.source === "archie" ? "planned by Archie" : "standard breakdown"} · {ago(i.at)}</div></div>
      <ArrowRight className="h-4 w-4 text-muted" />
    </button>
  );
  return (
    <div className="flex items-center gap-3 border-b border-border px-3 py-2.5 last:border-0">
      <AgentAvatar code={i.specialist ?? "gage"} state="review" size={30} />
      <Link to={`/app/office/programs/${i.program_id}?ticket=${i.ticket_id}`} className="min-w-0 flex-1 hover:text-primary">
        <div className="truncate text-[13px] font-medium"><span className="font-mono text-[11px] text-muted">{i.key}</span> {i.title}</div>
        <div className="flex items-center gap-1 text-[11.5px] text-muted">{i.program} · {ago(i.at)}
          {i.checks && (i.checks.ok ? <span className="inline-flex items-center gap-0.5 text-success"><CheckCircle2 className="h-3 w-3" />checks pass</span>
            : <span className="inline-flex items-center gap-0.5 text-danger"><XCircle className="h-3 w-3" />a check fails</span>)}</div>
      </Link>
      {canEdit && <div className="flex shrink-0 gap-1">
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => move("changes_requested")}>Changes</Button>
        <Button size="sm" disabled={busy} onClick={() => move("approved")}>Approve</Button>
      </div>}
    </div>
  );
}

const STATES = ["idle", "working", "review", "blocked", "done"] as const;

/** Every agent in every state: how the board, roster and cards show who is doing what. */
function MeetTheTeam({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title="Meet the team" description="Each agent's avatar shows its state at a glance. Working plays the agent's own shop-floor animation.">
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead><tr className="text-muted">{["", ...STATES.map(s => STATE_LABEL[s])].map(h => <th key={h} className="pb-2 text-center font-medium">{h.charAt(0).toUpperCase() + h.slice(1)}</th>)}</tr></thead>
          <tbody>{AGENTS.map(a => (
            <tr key={a.code} className="border-t border-border">
              <td className="py-2 pr-3"><div className="font-semibold" style={{ color: a.colour }}>{a.name}</div><div className="text-[11px] text-muted">{a.role}</div></td>
              {STATES.map(s => <td key={s} className="py-2 text-center"><AgentAvatar code={a.code} state={s} size={56} progress={s === "working" ? 60 : null} /></td>)}
            </tr>))}</tbody>
        </table>
      </div>
    </Modal>
  );
}

export default function OfficeHome() {
  const q = useHome();
  const [team, setTeam] = useState(false);
  const nav = useNavigate();
  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) return <div className={PAGE}><EmptyState icon={<Inbox />} title="The Design Office could not load" body={q.error instanceof ApiError ? q.error.message : "Try again in a moment."} /></div>;
  const d = q.data;
  const pct = d.budget.tokens > 0 ? (100 * d.budget.spent) / d.budget.tokens : 0;
  return (
    <div className={PAGE}>
      <PageHeader eyebrow={<Badge tone="preview">Preview</Badge>} title="Design Office"
        subtitle="Run a product like a design company: Archie plans the program, named specialists own the parts, you approve at the gates."
        actions={d.can_edit && <><FileButtons ext="fwprog" openOnly size="md" />
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => nav("/app/office/new")}>New program</Button></>} />
      <AutoRunNote className="mb-6" />
      <div className="grid gap-6 lg:grid-cols-3">
        <section className="space-y-3 lg:col-span-2">
          <h2 className="label">Programs</h2>
          {d.programs.length === 0 ? (
            <EmptyState icon={<AgentAvatar code="archie" size={44} />} title="Hand Archie your first brief"
              body="Describe a product or machine. Archie breaks it into sub-assemblies and parts, estimates the work, and you approve the plan before any ticket opens."
              action={d.can_edit && <Button icon={<Plus className="h-4 w-4" />} onClick={() => nav("/app/office/new")}>New program</Button>} />
          ) : <div className="grid gap-3 md:grid-cols-2">{d.programs.map(p => <ProgramCard key={p.id} p={p} />)}</div>}
        </section>
        <aside className="space-y-6">
          <section>
            <h2 className="label mb-3 flex items-center gap-1.5"><ClipboardCheck className="h-3.5 w-3.5" />Reviews for you {d.inbox.length > 0 && <Badge tone="warning">{d.inbox.length}</Badge>}</h2>
            <Card className="overflow-hidden">
              {d.inbox.length === 0 ? <div className="px-4 py-8 text-center text-[13px] text-muted">Nothing waiting for you.</div>
                : d.inbox.slice(0, 8).map(i => <InboxRow key={`${i.kind}-${i.program_id}-${i.ticket_id ?? ""}`} i={i} canEdit={d.can_edit} />)}
            </Card>
          </section>
          <section>
            <h2 className="label mb-3 flex items-center gap-1.5"><Coins className="h-3.5 w-3.5" />Token spend vs budget</h2>
            <Card className="p-4">
              <div className="flex items-baseline justify-between"><span className="text-2xl font-semibold tabular-nums">{num(d.budget.spent)}</span>
                <span className="text-[12px] text-muted">of {num(d.budget.tokens)} budgeted</span></div>
              <Progress className="mt-2" value={pct} tone={pct >= 100 ? "danger" : pct >= 80 ? "warning" : "primary"} />
              <p className="mt-2 text-[11.5px] text-muted">Archie's planning, the part agents' Design Studio runs and Gage's reviews, across all programs.</p>
            </Card>
          </section>
        </aside>
      </div>
      <section className="mt-8">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="label">The team</h2>
          <span className="flex items-center gap-3 text-[11.5px] text-muted">Hover an idle agent to see them at work
            <Button size="sm" variant="secondary" onClick={() => setTeam(true)}>Meet the team</Button></span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {d.roster.map(a => <RosterCard key={a.code} a={{ ...a, colour: AGENT[a.code]?.colour ?? a.colour }} />)}
        </div>
      </section>
      <MeetTheTeam open={team} onOpenChange={setTeam} />
    </div>
  );
}
