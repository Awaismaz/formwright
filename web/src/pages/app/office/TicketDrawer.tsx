import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Info, Send } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Avatar, Badge, Button, Modal } from "@/components/ui";
import { AgentAvatar, AGENT, AGENTS, STATE_LABEL } from "./Avatars";
import { BASE } from "./api";
import { useMoveTicket } from "./Board";
import { fmtMinutes } from "./model";
import type { Column, OfficeEvent, Program, Ticket } from "./types";

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
  const deps = t.depends_on.map(id => program.tickets.find(x => x.id === id)).filter(Boolean) as Ticket[];
  const history = (acts.data?.items ?? []).filter(e => e.ticket_id === t.id).slice(0, 12);
  const linked = t.project_id || t.assembly_id;
  return (
    <Modal open onOpenChange={o => { if (!o) onClose(); }} wide
      title={<span className="flex items-center gap-2"><span className="font-mono text-[13px] text-muted">{t.key}</span>{t.title}{t.qty > 1 && <Badge>×{t.qty}</Badge>}</span>}
      description={`${program.name} · ${t.kind === "integration" ? "assembly integration" : t.kind === "standard" ? "standard part" : `${program.families.find(f => f.code === t.family)?.label.toLowerCase()} part`}`}>
      <div className="grid gap-5 md:grid-cols-[1fr_220px]">
        <div className="min-w-0 space-y-4">
          <div className="flex items-center gap-3 rounded-lg border border-border p-3">
            <AgentAvatar code={t.specialist} state={t.agent_state} size={56} progress={t.agent_state === "working" ? t.progress : null} />
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-semibold" style={{ color: a?.colour }}>{a?.name}</div>
              <div className="text-[12px] text-muted">{a?.role} · {STATE_LABEL[t.agent_state]}</div>
              <div className="mt-1 flex items-center gap-1.5 text-[11.5px] text-muted"><Info className="h-3.5 w-3.5" />Auto-run arrives with the orchestrator. Start opens the {t.kind === "integration" ? "assembly" : "part in Design Studio"}.</div>
            </div>
          </div>
          {canEdit && <Button className="w-full" loading={busy === "start"} icon={<ExternalLink className="h-4 w-4" />} onClick={start}>
            {linked ? (t.kind === "integration" ? "Open the assembly" : "Open in Design Studio") : t.kind === "integration" ? "Start: open an assembly" : "Start: open in Design Studio with this brief"}</Button>}
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
              {t.comments.map(c => <div key={c.id} className="flex gap-2"><Avatar name={c.by.name} size={24} />
                <div className="min-w-0 flex-1 rounded-md bg-panel2 px-2.5 py-1.5"><div className="text-[11.5px] text-muted"><b className="text-text">{c.by.name}</b> · {ago(c.t)}</div>
                  <div className="whitespace-pre-line text-[13px]">{c.text}</div></div></div>)}
            </div>
            {canEdit && <form className="mt-2 flex gap-2" onSubmit={e => { e.preventDefault(); if (!comment.trim()) return;
              call("comment", () => api.post<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}/comments`, { text: comment })).then(() => setComment("")); }}>
              <input className="input h-9 flex-1" value={comment} onChange={e => setComment(e.target.value)} placeholder="Add a comment…" maxLength={2000} />
              <Button type="submit" size="md" loading={busy === "comment"} disabled={!comment.trim()} icon={<Send className="h-4 w-4" />} aria-label="Post comment" />
            </form>}
            <p className="mt-1 text-[11px] text-muted">Comments reach the working agent once auto-run arrives.</p>
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
              {AGENTS.filter(x => x.code !== "archie").map(x => <option key={x.code} value={x.code}>{x.name} · {x.role}</option>)}</select></label>
          {t.kind !== "standard" && <label className="block"><span className="label">Complexity</span>
            <select className="input mt-1 h-9 py-0" value={t.complexity} disabled={!canEdit}
              onChange={e => call("cx", () => api.patch<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}`, { complexity: Number(e.target.value) }))}>
              {[1, 2, 3, 4, 5].map(c => <option key={c} value={c}>{c}</option>)}</select></label>}
          <div className="rounded-md border border-border p-2.5 text-[12px]">
            <div className="flex justify-between"><span className="text-muted">Estimate</span><b>{fmtMinutes(t.estimate_min)}</b></div>
            <div className="flex justify-between"><span className="text-muted">Progress</span><b>{t.progress} %</b></div>
            {t.tokens > 0 && <div className="flex justify-between"><span className="text-muted">Tokens</span><b>{t.tokens}</b></div>}
          </div>
          <div>
            <div className="label mb-1">Milestones</div>
            <ul className="space-y-1">{program.constants.milestones.map(m => {
              const on = t.milestones.includes(m.code);
              return <li key={m.code}><label className={cx("flex items-center gap-2 text-[12.5px]", !canEdit && "opacity-70")}>
                <input type="checkbox" checked={on} disabled={!canEdit || busy === m.code}
                  onChange={() => call(m.code, () => api.post<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}/milestones`, { code: m.code, reached: !on }))} />
                <span className="flex-1">{m.label}</span><span className="tabular-nums text-muted">{m.weight} %</span></label></li>;
            })}</ul>
            <p className="mt-1.5 text-[11px] text-muted">First build and checks pass are set from the linked Design Studio part automatically.</p>
          </div>
        </div>
      </div>
    </Modal>
  );
}
