import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MessageSquare, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, Button } from "@/components/ui";
import { AgentAvatar } from "./Avatars";
import { BASE } from "./api";
import type { ArchieChat as Chat, ArchieMessage, Program } from "./types";

const QUICK: Record<string, string[]> = {
  planning: ["Status report"],
  plan_review: ["Status report", "Split the housing into base and cover"],
  active: ["Status report", "What's blocked?", "Can we finish sooner?", "Pause the office"],
  complete: ["Status report", "What's left before release?"],
};

/** Talk to Archie at any stage (CD-026): status from the program itself, change requests as proposals you apply. */
export default function ArchieChat({ program, open, onOpenChange }: { program: Program; open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const key = ["office-archie", program.id];
  const q = useQuery({ queryKey: key, enabled: open, queryFn: () => api.get<Chat>(`${BASE}/programs/${program.id}/archie`) });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const msgs = q.data?.messages ?? [];
  const canEdit = q.data?.can_edit !== false && program.can_edit !== false;
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length, busy, open]);

  const send = async (body: string) => {
    const t = body.trim();
    if (!t || busy) return;
    setBusy(true); setText("");
    qc.setQueryData<Chat>(key, old => old ? { ...old, messages: [...old.messages, { id: "pending", role: "user", text: t, t: new Date().toISOString() }] } : old);
    try {
      const r = await api.post<Chat>(`${BASE}/programs/${program.id}/archie`, { text: t });
      qc.setQueryData(key, r);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Archie didn't get that");
      setText(t); void q.refetch();
    } finally { setBusy(false); }
  };
  const act = async (m: ArchieMessage, aid: string, decision: "apply" | "dismiss") => {
    setActing(`${m.id}:${aid}`);
    try {
      const r = await api.post<Chat & { program: Program }>(`${BASE}/programs/${program.id}/archie/actions`, { message: m.id, action: aid, decision });
      qc.setQueryData(key, { messages: r.messages, ai: r.ai, can_edit: r.can_edit });
      qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...r.program, can_edit: old?.can_edit }));
      if (decision === "apply") toast.success("Done");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not apply"); void q.refetch(); }
    finally { setActing(null); }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[420px] flex-col border-l border-border bg-panel shadow-2xl animate-fade-in" role="dialog" aria-label="Talk to Archie" data-archie-chat>
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <AgentAvatar code="archie" size={36} state={busy ? "working" : "idle"} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">Archie</div>
          <div className="truncate text-[11.5px] text-muted">Chief Designer · {program.name}</div>
        </div>
        <button className="rounded p-1.5 text-muted hover:bg-text/[.06] hover:text-text" aria-label="Close" onClick={() => onOpenChange(false)}><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {msgs.length === 0 && !q.isLoading && <div className="rounded-lg border border-dashed border-border p-3 text-[12.5px] text-muted">
          Ask for a status report at any time, or tell me what should change: a new requirement for a part, more agents, a bigger budget, a different
          interface number. I propose the change and you apply it. Status reports are free.</div>}
        {msgs.map(m => m.role === "user"
          ? <div key={m.id} className="ml-10 rounded-lg bg-primary-soft px-3 py-2 text-[13px] whitespace-pre-line">{m.text}</div>
          : <div key={m.id} className="flex gap-2">
            <AgentAvatar code="archie" size={26} still />
            <div className="min-w-0 flex-1">
              <div className="rounded-lg border border-border bg-panel2 px-3 py-2 text-[13px] whitespace-pre-line">{m.text}</div>
              {(m.actions ?? []).map(a => (
                <div key={a.id} className={cx("mt-1.5 rounded-md border px-2.5 py-2 text-[12.5px]", a.status === "proposed" ? "border-primary/30" : "border-border opacity-75")} data-archie-action={a.type}>
                  <div>{a.label}</div>
                  <div className="mt-1.5 flex items-center gap-2">
                    {a.status === "proposed" && canEdit ? <>
                      <Button size="sm" loading={acting === `${m.id}:${a.id}`} disabled={!!acting} icon={<Check className="h-3.5 w-3.5" />} onClick={() => act(m, a.id, "apply")}>Apply</Button>
                      <Button size="sm" variant="ghost" disabled={!!acting} onClick={() => act(m, a.id, "dismiss")}>Dismiss</Button></>
                      : <Badge tone={a.status === "applied" ? "success" : "neutral"}>{a.status === "applied" ? `Applied${a.by ? ` by ${a.by.name}` : ""}` : a.status === "dismissed" ? "Dismissed" : "Proposed"}</Badge>}
                  </div>
                </div>))}
              <div className="mt-1 text-[10.5px] text-muted">{m.kind === "status" ? "From the program, no AI" : m.kind === "ai" ? "Archie (AI)" : "Office"} · {ago(m.t)}</div>
            </div>
          </div>)}
        {busy && <div className="flex items-center gap-2 text-[12px] text-muted"><AgentAvatar code="archie" size={22} state="working" />Archie is looking at the board…</div>}
        <div ref={end} />
      </div>
      {canEdit ? <div className="border-t border-border p-3">
        <div className="mb-2 flex flex-wrap gap-1.5">{(QUICK[program.status] ?? QUICK.active!).map(s => (
          <button key={s} disabled={busy} className="rounded-full border border-border px-2.5 py-0.5 text-[11.5px] text-muted hover:border-primary/40 hover:text-text disabled:opacity-50" onClick={() => void send(s)}>{s}</button>))}</div>
        <form className="flex items-end gap-2" onSubmit={e => { e.preventDefault(); void send(text); }}>
          <textarea className="input min-h-[40px] flex-1 resize-none py-2 text-[13px]" rows={2} maxLength={2000} value={text} aria-label="Message to Archie"
            placeholder="Ask for status, or say what should change…" onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } }} />
          <Button type="submit" loading={busy} disabled={!text.trim()} icon={<Send className="h-4 w-4" />} aria-label="Send" />
        </form>
        {q.data && !q.data.ai && <p className="mt-1.5 text-[10.5px] text-muted">AI replies are off here: Archie answers status and the common requests directly.</p>}
      </div> : <div className="border-t border-border p-3 text-[12px] text-muted">Viewers can read the conversation but not change the program.</div>}
    </div>
  );
}

export function TalkToArchieButton({ onClick }: { onClick: () => void }) {
  return <Button variant="secondary" size="sm" icon={<MessageSquare className="h-4 w-4" />} onClick={onClick} data-talk-archie>Talk to Archie</Button>;
}
