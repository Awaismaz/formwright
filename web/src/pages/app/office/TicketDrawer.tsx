import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, ExternalLink, FileWarning, Hand, LayoutTemplate, Library, MessageSquareWarning, Pause, Play, Puzzle, RotateCcw, Ruler, Send, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Avatar, Badge, Button, Modal } from "@/components/ui";
import { AgentAvatar, AGENT, AGENTS, STATE_LABEL } from "./Avatars";
import { BASE } from "./api";
import { useMoveTicket } from "./Board";
import { assignable, fmtMinutes, runChip } from "./model";
import PartPreview from "./PartPreview";
import { errorTone, fmtError } from "./timeline";
import type { Column, DesignPath, OfficeEvent, Program, Ticket } from "./types";

export function ActorBadge({ e, size = 24 }: { e: Pick<OfficeEvent, "actor">; size?: number }) {
  if (e.actor.kind === "agent" && e.actor.code) return <AgentAvatar code={e.actor.code} size={size} still />;
  if (e.actor.kind === "studio") return <span className="flex shrink-0 items-center justify-center rounded-full bg-primary-soft text-[10px] font-bold text-primary" style={{ width: size, height: size }}>DS</span>;
  return <Avatar name={e.actor.name} size={size} />;
}

export default function TicketDrawer({ program, ticket, onClose }: { program: Program; ticket: Ticket | null; onClose: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const move = useMoveTicket(program);
  const [comment, setComment] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const canEdit = program.can_edit !== false;
  const t = ticket ? program.tickets.find(x => x.id === ticket.id) ?? ticket : null;
  const acts = useQuery({ queryKey: ["office-activity", program.id], enabled: !!t,
    queryFn: () => api.get<{ items: OfficeEvent[] }>(`${BASE}/programs/${program.id}/activity?limit=300`) });
  if (!t) return null;
  const a = AGENT[t.specialist];
  const set = (v: Program) => qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
  const call = async (what: string, fn: () => Promise<Program>) => {
    setBusy(what);
    try { set(await fn()); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(null); }
  };
  const start = async () => {
    setBusy("start");
    try {
      const r = await api.post<{ project_id: string | null; assembly_id: string | null; starter_prompt: string | null; program: Program }>(
        `${BASE}/programs/${program.id}/tickets/${t.id}/start`);
      set(r.program);
      if (r.project_id) {
        if (r.starter_prompt) try { sessionStorage.setItem(`fw_starter_${r.project_id}`, r.starter_prompt); } catch { /* ignore */ }
        nav(`/app/projects/${r.project_id}`);
      } else if (r.assembly_id) nav(`/app/modules/assembly?assembly=${r.assembly_id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not open the ticket");
      if (e instanceof ApiError && e.cta) nav(e.cta);
    } finally { setBusy(null); }
  };
  const review = (decision: "approve" | "changes") => call(decision, () => api.post<Program>(
    `${BASE}/programs/${program.id}/tickets/${t.id}/review`, { decision, note })).then(() => setNote(""));
  const keepTemplate = async () => {
    setBusy("template");
    try {
      const r = await api.post<{ name: string; mapped: number; params: number }>(`${BASE}/programs/${program.id}/tickets/${t.id}/template`);
      toast.success(`Kept as the template ${r.name}: ${r.mapped} of ${r.params} sizes follow the interfaces`);
      qc.invalidateQueries({ queryKey: ["office-program", program.id] });
      qc.invalidateQueries({ queryKey: ["office-templates"] });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not keep the template"); } finally { setBusy(null); }
  };
  const control = (action: string) => call(action, () => api.post<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}/control`, { action }));
  const who = t.agent ?? t.specialist;
  const holder = AGENT[who];
  const busyRun = ["searching", "designing", "reviewing", "integrating", "fitting", "drafting", "screening"].includes(t.run_status ?? "");
  const deliverable = t.kind === "deliverable";
  const chip = runChip(t);
  const done = t.column === "approved" || t.column === "integrated";
  const spec = AGENT[t.specialist]?.name ?? "the agent";
  const deps = t.depends_on.map(id => program.tickets.find(x => x.id === id)).filter(Boolean) as Ticket[];
  const history = (acts.data?.items ?? []).filter(e => e.ticket_id === t.id).slice(0, 12);
  const linked = t.project_id || t.assembly_id;
  return (
    <Modal open onOpenChange={o => { if (!o) onClose(); }} wide
      title={<span className="flex items-center gap-2"><span className="font-mono text-[13px] text-muted">{t.key}</span>{t.title}{t.qty > 1 && <Badge>×{t.qty}</Badge>}</span>}
      description={`${program.name} · ${t.kind === "integration" ? "assembly integration" : t.kind === "standard" ? "standard part" : t.kind === "deliverable" ? "program deliverable (after integration)" : `${program.families.find(f => f.code === t.family)?.label.toLowerCase()} part`}`}>
      <div className="grid gap-5 md:grid-cols-[1fr_220px]">
        <div className="min-w-0 space-y-4">
          <div className="flex items-center gap-3 rounded-lg border border-border p-3">
            <AgentAvatar code={who} state={t.agent_state} size={56} progress={t.agent_state === "working" ? t.progress : null} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[14px] font-semibold" style={{ color: holder?.colour }}>{t.agent_label ?? holder?.name}</span>
                {chip && <Badge tone={chip.tone === "danger" ? "danger" : chip.tone === "warning" ? "warning" : chip.tone === "primary" ? "primary" : "neutral"}>{chip.label}</Badge>}
              </div>
              <div className="text-[12px] text-muted">{holder?.role} · {STATE_LABEL[t.agent_state]}{who !== t.specialist && <> · assigned to <b style={{ color: a?.colour }}>{a?.name}</b></>}</div>
              {t.line && <div className="mt-1 text-[12.5px]" aria-live="polite">{t.line}</div>}
              {!t.run && !done && <div className="mt-1 text-[11.5px] text-muted">Waiting for the office: press Run on the program, or start it by hand.</div>}
            </div>
          </div>
          {t.project_id && (t.kind === "part" || t.kind === "standard") && t.milestones.includes("first_build") &&
            <PartPreview projectId={t.project_id} version={t.updated_at} done={done} onOpen={() => nav(`/app/projects/${t.project_id}`)} />}
          {t.run_status === "awaiting_review" && <div className="rounded-md border border-warning/40 bg-warning/5 p-3" data-review-gate>
            <div className="flex items-center gap-1.5 text-[13px] font-semibold"><MessageSquareWarning className="h-4 w-4 text-warning" />Waiting for your review</div>
            <p className="mt-0.5 text-[12px] text-muted">Gage passed this part. The program's review gate holds it here until you approve it for assembly or send it back to {spec} with a note.</p>
            {canEdit && <>
              <textarea className="input mt-2 min-h-[64px] w-full py-1.5 text-[12.5px]" value={note} onChange={e => setNote(e.target.value)} maxLength={2000}
                placeholder="Note (required to request changes, optional with an approval)" aria-label="Review note" />
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button size="sm" loading={busy === "approve"} icon={<CheckCircle2 className="h-3.5 w-3.5" />} onClick={() => review("approve")}>Approve for assembly</Button>
                <Button size="sm" variant="secondary" loading={busy === "changes"} disabled={!note.trim()} icon={<FileWarning className="h-3.5 w-3.5" />}
                  onClick={() => review("changes")} title={note.trim() ? undefined : "Write what should change first"}>Request changes</Button>
              </div></>}
          </div>}
          {t.reviewed && t.run_status !== "awaiting_review" && <div className="text-[11.5px] text-muted" data-reviewed>
            Last review: {t.reviewed.decision === "approved" ? "approved" : "changes requested"} by {t.reviewed.by} {ago(t.reviewed.at)}{t.reviewed.note ? `: ${t.reviewed.note}` : ""}</div>}
          {t.ecn && <div className="text-[11.5px] text-muted">Reopened by change notice <b>{t.ecn}</b>.</div>}
          {t.reuse && <div className="flex items-start gap-2 rounded-md border border-success/30 bg-success/5 p-2.5 text-[12.5px]">
            <Library className="mt-0.5 h-4 w-4 shrink-0 text-success" /><span>{t.reuse.found}. Reused, so no design run and 0 tokens.</span></div>}
          {t.direct && !t.reuse && <DesignPathNote d={t.direct} />}
          {t.kind === "part" && t.direct?.path === "agent" && ["approved", "integrated", "done"].includes(t.column) && <div
            className="flex items-start gap-2 rounded-md border border-border bg-panel2 p-2.5 text-[12.5px]" data-template-offer>
            <LayoutTemplate className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            {t.template_kept ? <span>Kept as a workspace template {ago(t.template_kept.at)}: the next part of this kind starts from it.</span>
              : <span className="flex-1">The designer made this part with AI. Keep it as a workspace template, and the next part of the same kind starts from it, or is built from it without AI when every size maps onto its interfaces.
                {canEdit && <span className="mt-1.5 block"><Button size="sm" variant="secondary" loading={busy === "template"}
                  icon={<LayoutTemplate className="h-3.5 w-3.5" />} onClick={keepTemplate}>Keep as a template</Button></span>}</span>}
          </div>}
          {(t.relaxed ?? []).length > 0 && <div className="rounded-md border border-warning/40 bg-warning/5 p-2.5 text-[12.5px]" data-relaxed>
            <div className="font-medium text-warning">Checks relaxed by Archie: relaxed, not passed</div>
            <ul className="mt-1 space-y-1">{(t.relaxed ?? []).map((r, i) => <li key={i}>
              <span className="font-medium first-letter:uppercase">{r.label}{r.feature_text ? ` for ${r.feature_text}` : ""}</span>{r.undone ? " · the relaxation was undone after integration: reopen the part so Gage measures it again" : ""}
              <div className="text-muted">{r.text}</div><div>Relaxed by Archie: {r.reason}</div></li>)}</ul>
          </div>}
          {t.icd_check && <div className={cx("rounded-md border p-2.5 text-[12.5px]", t.icd_check.ok ? "border-success/30 bg-success/5" : "border-danger/30 bg-danger/5")} data-icd-check>
            <div className="font-medium">{t.icd_check.ok ? `Interfaces conform to ICD v${t.icd_check.version}` : `Interfaces off ICD v${t.icd_check.version}`}{t.fitted ? " · swapped into the program assembly" : ""}</div>
            <ul className="mt-1 space-y-0.5 text-[11.5px]">
              {!t.icd_check.envelope.ok && <li className="text-danger">Envelope: {t.icd_check.envelope.measured}</li>}
              {t.icd_check.interfaces.map(r => <li key={r.interface} className={r.ok ? "text-muted" : "text-danger"}>
                {r.ok ? "✓" : "✗"} <span className="font-mono">{r.interface}</span> {r.name.split(": ")[1] ?? r.name}: {r.rows.filter(x => x.ok).length} of {r.rows.length} features
                {!r.ok && r.rows.filter(x => !x.ok).slice(0, 2).map((x, k) => <div key={k} className="pl-4">{x.feature}: specified {x.spec}, measured {x.measured}</div>)}</li>)}
            </ul></div>}
          {t.integration?.summary && <div className="flex items-start gap-2 rounded-md border border-border bg-panel2 p-2.5 text-[12.5px]">
            <Puzzle className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span>{t.integration.summary}</span></div>}
          {canEdit && <div className="flex flex-wrap gap-1.5">
            {t.paused ? <Button size="sm" variant="secondary" loading={busy === "resume"} icon={<Play className="h-3.5 w-3.5" />} onClick={() => control("resume")}>Resume ticket</Button>
              : !done && <Button size="sm" variant="secondary" loading={busy === "pause"} icon={<Pause className="h-3.5 w-3.5" />} onClick={() => control("pause")}>Pause ticket</Button>}
            {t.kind !== "integration" && !done && (t.taken_over
              ? <Button size="sm" variant="secondary" loading={busy === "hand_back"} icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => control("hand_back")}>Hand back to {spec}</Button>
              : <Button size="sm" variant="secondary" loading={busy === "take_over"} icon={<Hand className="h-3.5 w-3.5" />} onClick={() => control("take_over")}
                  title="Stops the agent; you continue in the Design Studio">Take over</Button>)}
            {(done || t.run_status === "blocked") && <Button size="sm" variant="secondary" loading={busy === "reopen"} disabled={busyRun} icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => control("reopen")}>Reopen</Button>}
            {(t.run_status === "blocked" || t.run_status === "retry") && <Button size="sm" loading={busy === "retry"} icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => control("retry")}>Retry now</Button>}
          </div>}
          {deliverable && <Button className="w-full" variant="secondary" icon={<ExternalLink className="h-4 w-4" />}
            onClick={() => { onClose(); nav(`/app/office/programs/${program.id}?tab=deliverables`); }}>Open the deliverables</Button>}
          {canEdit && !deliverable && <Button className="w-full" loading={busy === "start"} icon={<ExternalLink className="h-4 w-4" />} onClick={start}>
            {linked ? (t.kind === "integration" ? "Open the assembly" : t.taken_over ? "Continue in Design Studio" : "Open in Design Studio") : t.kind === "integration" ? "Start: open an assembly" : "Start by hand: open in Design Studio with this brief"}</Button>}
          <div>
            <div className="label mb-1">Brief</div>
            <p className="whitespace-pre-line rounded-md bg-panel2 p-3 text-[12.5px] leading-relaxed">{t.brief}</p>
          </div>
          {deps.length > 0 && <div><div className="label mb-1">Waits for</div>
            <div className="flex flex-wrap gap-1.5">{deps.map(d => <span key={d.id} className="inline-flex items-center gap-1 rounded-full border border-border py-0.5 pl-0.5 pr-2 text-[11.5px]">
              <AgentAvatar code={d.specialist} state={d.agent_state} size={18} still /><span className="font-mono text-muted">{d.key}</span>{d.title}</span>)}</div></div>}
          <div>
            <div className="label mb-1.5">Comments</div>
            <div className="space-y-2">
              {t.comments.length === 0 && <div className="text-[12.5px] text-muted">No comments yet.</div>}
              {t.comments.map(c => <div key={c.id} className="flex gap-2">{c.by.kind === "agent" && c.by.code ? <AgentAvatar code={c.by.code} size={24} still /> : <Avatar name={c.by.name} size={24} />}
                <div className="min-w-0 flex-1 rounded-md bg-panel2 px-2.5 py-1.5"><div className="text-[11.5px] text-muted"><b className="text-text">{c.by.name}</b> · {ago(c.t)}
                  {c.delivery === "queued" && <span className="ml-1.5 text-warning">· queued for {spec}</span>}
                  {c.delivery === "delivered" && <span className="ml-1.5 text-success">· sent to {spec}</span>}</div>
                  <div className="whitespace-pre-line text-[13px]">{c.text}</div></div></div>)}
            </div>
            {canEdit && <form className="mt-2 flex gap-2" onSubmit={e => { e.preventDefault(); if (!comment.trim()) return;
              call("comment", () => api.post<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}/comments`, { text: comment })).then(() => setComment("")); }}>
              <input className="input h-9 flex-1" value={comment} onChange={e => setComment(e.target.value)} placeholder="Add a comment…" maxLength={2000} />
              <Button type="submit" size="md" loading={busy === "comment"} disabled={!comment.trim()} icon={<Send className="h-4 w-4" />} aria-label="Post comment" />
            </form>}
            <p className="mt-1 text-[11px] text-muted">{t.kind === "integration" ? "Comments on assembly tickets are notes for the team." : done
              ? `Reopen the ticket to send a new comment to ${spec}.` : t.taken_over ? "You took over: comments are notes until you hand the ticket back."
              : `Comments reach ${spec} as its next message (queued while it works).`}</p>
          </div>
          {history.length > 0 && <div><div className="label mb-1.5">History</div>
            <ul className="space-y-1.5">{history.map(e => <li key={e.seq} className="flex items-start gap-2 text-[12px]"><ActorBadge e={e} size={20} />
              <span className="min-w-0 flex-1">{e.text} <span className="text-muted">{ago(e.t)}</span></span></li>)}</ul></div>}
        </div>
        <div className="space-y-4">
          <label className="block"><span className="label">Column</span>
            <select className="input mt-1 h-9 py-0" value={t.column} disabled={!canEdit} onChange={e => move(t, e.target.value as Column)}>
              {program.columns.map(c => <option key={c.code} value={c.code}>{c.label}</option>)}</select></label>
          <label className="block"><span className="label">Specialist</span>
            <select className="input mt-1 h-9 py-0" value={t.specialist} disabled={!canEdit}
              onChange={e => call("assign", () => api.patch<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}`, { specialist: e.target.value }))}>
              {AGENTS.filter(x => assignable(t.kind, t.deliverable).includes(x.code)).map(x => <option key={x.code} value={x.code}>{x.name} · {x.role}</option>)}</select></label>
          <label className="block"><span className="label">Priority</span>
            <select className="input mt-1 h-9 py-0" value={t.priority ?? "normal"} disabled={!canEdit}
              onChange={e => call("prio", () => api.patch<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}`, { priority: e.target.value }))}>
              <option value="high">High: next in line</option><option value="normal">Normal: critical path</option><option value="low">Low: after the rest</option></select></label>
          {t.kind !== "standard" && <label className="block"><span className="label">Complexity</span>
            <select className="input mt-1 h-9 py-0" value={t.complexity} disabled={!canEdit}
              onChange={e => call("cx", () => api.patch<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}`, { complexity: Number(e.target.value) }))}>
              {[1, 2, 3, 4, 5].map(c => <option key={c} value={c}>{c}</option>)}</select></label>}
          <div className="rounded-md border border-border p-2.5 text-[12px]">
            <div className="flex justify-between"><span className="text-muted">Estimate</span><b>{fmtMinutes(t.estimate_min)}</b></div>
            {(t.actual_min ?? 0) > 0 && <div className="flex justify-between" data-actual><span className="text-muted">Actual agent time</span>
              <b>{fmtMinutes(t.actual_min ?? 0)}{t.error_pct !== null && t.error_pct !== undefined && <span className={cx("ml-1 font-medium",
                { success: "text-success", warning: "text-warning", danger: "text-danger", neutral: "text-muted" }[errorTone(t.error_pct)])}>({fmtError(t.error_pct)})</span>}</b></div>}
            {t.rounds && Object.keys(t.rounds).length > 0 && <div className="text-[11px] text-muted">{Object.entries(t.rounds).map(([k, v]) =>
              `${{ hex: "Toolbox search", design: "design turns", review: "Gage rounds", fit: "swap-ins", integrate: "integrations", drawings: "drawing runs", dfm: "review runs" }[k] ?? k} ${v}`).join(" · ")}</div>}
            {t.calibrated && <div className="mt-1 text-[11px] text-muted">{t.calibrated.learned
              ? `Taught the estimate: ${AGENT[t.specialist]?.name}'s rate ${t.calibrated.before} → ${t.calibrated.after} min per unit.`
              : `Not used for calibration: ${t.calibrated.why}.`}</div>}
            <div className="flex justify-between"><span className="text-muted">Progress</span><b>{t.progress} %</b></div>
            {t.tokens > 0 && <div className="flex justify-between"><span className="text-muted">Design tokens</span><b>{t.tokens}</b></div>}
            {(t.review_tokens ?? 0) > 0 && <div className="flex justify-between"><span className="text-muted">Review tokens</span><b>{t.review_tokens}</b></div>}
            {(t.run?.review_round ?? 0) > 0 && <div className="flex justify-between"><span className="text-muted">Sent back</span><b>{t.run?.review_round}×</b></div>}
          </div>
          {deliverable ? <p className="text-[11.5px] text-muted">Progress follows the sheets (Ortho) or the parts (Smithy) done; the deliverables cost no tokens.</p> :
          <div>
            <div className="label mb-1">Milestones</div>
            <ul className="space-y-1">{program.constants.milestones.map(m => {
              const on = t.milestones.includes(m.code);
              return <li key={m.code}><label className={cx("flex items-center gap-2 text-[12.5px]", !canEdit && "opacity-70")}>
                <input type="checkbox" checked={on} disabled={!canEdit || busy === m.code}
                  onChange={() => call(m.code, () => api.post<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}/milestones`, { code: m.code, reached: !on }))} />
                <span className="flex-1">{m.label}</span><span className="tabular-nums text-muted">{m.weight} %</span></label></li>;
            })}</ul>
            <p className="mt-1.5 text-[11px] text-muted">Set from the agent's real work: the brief read, its first build, the gating checks on the linked part, its self-review, and Gage's approval.</p>
          </div>}
        </div>
      </div>
    </Modal>
  );
}

/** How the part was designed, said honestly: from the interfaces without AI, or by the design agent and why. */
function DesignPathNote({ d }: { d: DesignPath }) {
  if (d.path === "direct" && !d.superseded) {
    return <div className="flex items-start gap-2 rounded-md border border-success/30 bg-success/5 p-2.5 text-[12.5px]" data-design-path="direct">
      <Ruler className="mt-0.5 h-4 w-4 shrink-0 text-success" />
      <span><b>{d.label ?? "Built from the interface spec (no AI)"}</b>{d.seconds != null ? ` in ${d.seconds} s` : ""}: {d.summary}
        {d.material ? `, ${d.material}` : ""}. {d.template ? `Its mapped sizes come from ICD v${d.icd_version}` : `Every size comes from ICD v${d.icd_version}`}; 0 tokens. Its parameters can be edited in the Design Studio without AI.
        {(d.notes ?? []).length > 0 && <span className="mt-1 block text-[11.5px] text-muted" data-design-notes>{(d.notes ?? []).join(" ")}</span>}</span></div>;
  }
  if (d.path === "direct") {
    return <div className="flex items-start gap-2 rounded-md border border-border bg-panel2 p-2.5 text-[12.5px]" data-design-path="direct-then-agent">
      <Bot className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <span>Started from the interface spec (no AI); the designer has changed it since, for review findings or comments.</span></div>;
  }
  return <div className="flex items-start gap-2 rounded-md border border-border bg-panel2 p-2.5 text-[12.5px]" data-design-path="agent">
    <Bot className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
    <span>Designed with AI{d.seeded ? (d.template ? `, starting from the workspace template ${d.template.name}` : ", starting from a model built from the interface spec") : ""}: {(d.reasons ?? []).join("; ") || "the interfaces don't fix every size"}.</span></div>;
}
