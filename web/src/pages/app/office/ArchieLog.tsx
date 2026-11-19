import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, MessageSquare, RotateCcw, ScanSearch, ShieldAlert, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, Button, Card, EmptyState } from "@/components/ui";
import { AgentAvatar } from "./Avatars";
import { BASE } from "./api";
import type { ArchieChat as Chat, ArchieQuestion, Program, RuleOverride, SupervisorEntry } from "./types";

type Resp = Chat & { supervisor: Program["supervisor"]; program: Program; result?: { ran: boolean; why?: string; done?: string[]; asked?: string[] } };

const CAUSE: Record<string, string> = {
  part: "the part", measurement: "the measurement", spec: "the specification", rule: "a procedural rule",
  plan: "the plan", interfaces: "the interfaces", budget: "the budget", capacity: "capacity", none: "nothing",
};
const STATUS: Record<SupervisorEntry["status"], { label: string; tone: "success" | "warning" | "neutral" | "danger" | "primary" }> = {
  applied: { label: "Done", tone: "success" }, asking: { label: "Waiting for you", tone: "warning" },
  declined: { label: "Declined", tone: "neutral" }, failed: { label: "Not done", tone: "danger" },
  lapsed: { label: "No longer applied", tone: "neutral" }, undone: { label: "Undone", tone: "neutral" },
};

/** Shared by the log and the chat: one call, both caches updated. */
function useSupervisorCall(program: Program) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const call = async (key: string, path: string, body?: unknown, ok?: (r: Resp) => string | null) => {
    setBusy(key);
    try {
      const r = await api.post<Resp>(`${BASE}/programs/${program.id}/supervisor${path}`, body);
      qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...r.program, can_edit: old?.can_edit }));
      qc.setQueryData(["office-archie", program.id], { messages: r.messages, ai: r.ai, can_edit: r.can_edit });
      const msg = ok?.(r);
      if (msg) toast.success(msg);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
    finally { setBusy(null); }
  };
  return { busy, call };
}

/** A major change Archie proposed, as clickable choices (in the chat and on the Archie tab). */
export function SupervisorQuestion({ program, q, canEdit }: { program: Program; q: ArchieQuestion; canEdit: boolean }) {
  const { busy, call } = useSupervisorCall(program);
  const live = !q.answered && canEdit;
  return (
    <div className="mt-1.5 rounded-lg border border-primary/30 bg-primary-soft/40 px-3 py-2.5" data-archie-question={q.action}>
      <div className="mb-1 text-[12.5px] font-medium">{q.question}</div>
      {q.why && <div className="mb-1.5 text-[11.5px] text-muted">{q.why}</div>}
      <div className="flex flex-wrap gap-1.5">
        {q.options.map(o => {
          const key = `${o.id}:${o.action ?? q.action}`;
          const on = q.answered === o.id && (o.id === "decline" || !q.actions || q.chosen === (o.action ?? q.action));
          return <button key={key} disabled={!live || !!busy} data-choice={o.id} data-option-action={o.action ?? q.action}
            onClick={() => void call(key, `/actions/${o.action ?? q.action}/decide`, { choice: o.id }, () => o.id === "approve" ? "Done: Archie applied it" : "Archie leaves it as it is")}
            className={cx("rounded-full border px-2.5 py-1 text-[12px] transition", on ? "border-primary bg-primary text-white" : "border-border bg-panel hover:border-primary hover:text-primary", !live && !on && "opacity-50")}>
            {busy === key ? "…" : o.label}</button>;
        })}
        {q.answered && <span className="self-center text-[11px] text-muted">{q.answered === "approve" ? "Approved" : "Declined"}{q.by ? ` by ${q.by.name}` : ""}{q.at ? ` ${ago(q.at)}` : ""}</span>}
      </div>
    </div>
  );
}

function Override({ o, program, canEdit }: { o: RuleOverride; program: Program; canEdit: boolean }) {
  const { busy, call } = useSupervisorCall(program);
  const entry = program.supervisor?.log.find(e => e.id === o.action);
  return (
    <div className="flex flex-wrap items-start gap-3 px-4 py-3" data-override={o.id}>
      <ShieldAlert className={cx("mt-0.5 h-4 w-4 shrink-0", o.status === "active" ? "text-warning" : "text-muted")} />
      <div className="min-w-[240px] flex-1 text-[13px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium first-letter:uppercase">{o.label}{o.feature_text ? ` for ${o.feature_text}` : ""}</span>
          <Badge tone={o.status === "active" ? "warning" : "neutral"}>{o.status === "active" ? (o.measures ? "Relaxed, not passed" : "Relaxed") : o.status === "expired" ? "Expired" : "Undone"}</Badge>
          {o.measures && <Badge tone="neutral">measures geometry</Badge>}
        </div>
        <div className="text-[12px] text-muted">On {o.scope_text}, {o.expiry_text}{o.approved_by ? ` · approved by ${o.approved_by}` : " · procedural, by Archie"} · {ago(o.at)}{o.uses?.length ? ` · used ${o.uses.length}×` : ""}</div>
        <div className="mt-0.5">Relaxed by Archie: {o.reason}</div>
        {o.ended && <div className="text-[12px] text-muted">Ended {ago(o.ended.at)}: {o.ended.why}</div>}
      </div>
      {canEdit && entry?.undoable && <Button size="sm" variant="secondary" loading={busy === "undo"} icon={<RotateCcw className="h-3.5 w-3.5" />}
        onClick={() => void call("undo", `/actions/${entry.id}/undo`, undefined, () => "Undone: the rule applies again")} data-undo={entry.id}>Undo</Button>}
    </div>
  );
}

function Entry({ e, program, canEdit }: { e: SupervisorEntry; program: Program; canEdit: boolean }) {
  const { busy, call } = useSupervisorCall(program);
  const [open, setOpen] = useState(false);
  const st = STATUS[e.status];
  return (
    <div className="flex items-start gap-3 px-4 py-3" data-log-entry={e.id} data-log-status={e.status}>
      <AgentAvatar code="archie" size={28} still />
      <div className="min-w-0 flex-1 text-[13px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={st.tone}>{st.label}</Badge>
          <Badge tone={e.class === "minor" ? "neutral" : "primary"}>{e.class === "minor" ? "Minor: Archie did it" : "Major: asked you"}</Badge>
          {e.mode === "simulated" && <Badge tone="warning">Simulated</Badge>}
          <span className="text-[11.5px] text-muted">{ago(e.at)}{e.tokens ? ` · ${e.tokens} tokens` : ""}</span>
        </div>
        <div className="mt-1 font-medium">{e.title}</div>
        {e.why && <div className="text-muted">Why: {e.why}</div>}
        {e.outcome && e.status !== "asking" && <div>Outcome: {e.outcome}</div>}
        {e.decided && <div className="text-[12px] text-muted">{e.decided.choice === "approve" ? "Approved" : "Declined"} by {e.decided.by} {ago(e.decided.at)}</div>}
        {e.undone && <div className="text-[12px] text-muted">Undone by {e.undone.by} {ago(e.undone.at)}: {e.undone.outcome}</div>}
        {(e.diagnosis || e.evidence.length > 0) && <button className="mt-1 text-[12px] text-primary hover:underline" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} the diagnosis and evidence</button>}
        {open && <div className="mt-1 rounded-md border border-border bg-panel2 p-2 text-[12px]">
          {e.cause && <div><b>At fault:</b> {CAUSE[e.cause] ?? e.cause}</div>}
          {e.diagnosis && <div className="mt-0.5">{e.diagnosis}</div>}
          {e.evidence.length > 0 && <ul className="mt-1 list-disc pl-4 text-muted">{e.evidence.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          <div className="mt-1 text-muted">{e.class === "minor" ? "Minor" : "Major"} because {e.class_why}. Triggered by: {e.trigger.join(", ")}.</div>
        </div>}
        {e.status === "asking" && canEdit && <div className="mt-1.5 flex gap-2">
          <Button size="sm" loading={busy === "approve"} disabled={!!busy} icon={<Check className="h-3.5 w-3.5" />} data-approve={e.id}
            onClick={() => void call("approve", `/actions/${e.id}/decide`, { choice: "approve" }, () => "Done: Archie applied it")}>Yes, do it</Button>
          <Button size="sm" variant="ghost" disabled={!!busy} icon={<X className="h-3.5 w-3.5" />}
            onClick={() => void call("decline", `/actions/${e.id}/decide`, { choice: "decline" }, () => "Archie leaves it as it is")}>No, leave it</Button>
        </div>}
      </div>
      {canEdit && e.undoable && <Button size="sm" variant="secondary" loading={busy === "undo"} icon={<RotateCcw className="h-3.5 w-3.5" />}
        onClick={() => void call("undo", `/actions/${e.id}/undo`, undefined, () => "Undone")} data-undo={e.id}>Undo</Button>}
    </div>
  );
}

/** WORKLIST 49: everything Archie did or proposed while supervising the program, with undo. */
export default function ArchieLog({ program, onTalk }: { program: Program; onTalk: () => void }) {
  const s = program.supervisor;
  const canEdit = program.can_edit !== false;
  const { busy, call } = useSupervisorCall(program);
  const log = s?.log ?? [];
  const asking = log.filter(e => e.status === "asking");
  const rest = log.filter(e => e.status !== "asking");
  const overrides = s?.overrides ?? [];
  const look = () => void call("run", "/run", undefined, r => r.result?.ran ? "Archie looked at the program" : "Archie looked: nothing new needs him");
  return (
    <div className="space-y-4" data-archie-log>
      <Card className="flex flex-wrap items-start gap-3 p-4">
        <AgentAvatar code="archie" size={40} still />
        <div className="min-w-[260px] flex-1 text-[13px]">
          <div className="font-semibold">Archie supervises this program{s && !s.enabled ? " (off on this server)" : ""}</div>
          <p className="mt-0.5 text-muted">He watches every ticket and gate: blocked parts, a part that fails the same way twice, review rounds that stop moving the
            measurement, a gate that stays blocked, a stalled step, the budget and the visual checks. He diagnoses what is at fault (the part, the measurement,
            a rule, the plan or the interfaces) and acts. Minor steps (a retry, a reassignment, a better instruction, an approval when only advisory notes remain,
            a procedural rule) he does himself and tells you. Major ones (adding or removing parts, an approved interface, a bigger budget, relaxing a check
            that measures geometry) wait for your yes. A relaxed check is never shown as passed.</p>
          {s && <p className="mt-1 text-[11.5px] text-muted">AI looks this hour: {s.calls_hour} of {s.max_calls_hour}. When the limit is reached, or AI is off, he reads the known patterns without AI.</p>}
        </div>
        <div className="flex flex-col gap-2">
          {canEdit && <Button size="sm" loading={busy === "run"} icon={<ScanSearch className="h-4 w-4" />} onClick={look} data-archie-check>Ask Archie to check now</Button>}
          <Button size="sm" variant="ghost" icon={<MessageSquare className="h-4 w-4" />} onClick={onTalk}>Talk to Archie</Button>
        </div>
      </Card>

      {asking.length > 0 && <div>
        <div className="label mb-1.5">Waiting for your decision</div>
        <Card className="divide-y divide-border border-warning/40">{asking.map(e => <Entry key={e.id} e={e} program={program} canEdit={canEdit} />)}</Card>
      </div>}

      {overrides.length > 0 && <div>
        <div className="label mb-1.5">Rules relaxed by Archie</div>
        <Card className="divide-y divide-border" data-overrides>{overrides.map(o => <Override key={o.id} o={o} program={program} canEdit={canEdit} />)}</Card>
      </div>}

      <div>
        <div className="label mb-1.5">Archie's log</div>
        {rest.length === 0 && asking.length === 0
          ? <EmptyState icon={<ScanSearch />} title="Nothing yet" body="When a ticket gets stuck or fails, Archie diagnoses it and his actions appear here, with undo where they can be undone." />
          : <Card className="divide-y divide-border">{rest.map(e => <Entry key={e.id} e={e} program={program} canEdit={canEdit} />)}</Card>}
      </div>
    </div>
  );
}
