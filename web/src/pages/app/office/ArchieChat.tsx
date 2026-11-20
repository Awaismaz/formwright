import { useEffect, useRef, useState } from "react";
import { matchPath, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Eye, MessageSquare, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { pageView, pointAt } from "@/lib/copilot";
import { ago, cx } from "@/lib/format";
import { Badge, Button } from "@/components/ui";
import { VerdictBadge } from "@/components/VisualCheck";
import { AgentAvatar } from "./Avatars";
import { BASE, useProgram } from "./api";
import { SupervisorQuestion } from "./ArchieLog";
import type { ArchieAction, ArchieChat as Chat, ArchieMessage, Program } from "./types";

const QUICK: Record<string, string[]> = {
  planning: ["Status report"],
  plan_review: ["Status report", "Split the housing into base and cover"],
  active: ["Status report", "What's blocked?", "Fix what's stuck", "Can we finish sooner?"],
  complete: ["Status report", "What's left before release?"],
  app: ["What can you do?", "Where are my tokens?", "Start a new program", "Show me how to model by hand"],
};
/** Actions that run on the engineer's screen (no data changes): shown as "Show me", run when the reply arrives. */
const CLIENT = new Set(["navigate", "point", "studio_request"]);

export function openArchie() { window.dispatchEvent(new Event("fw-open-archie")); }

/** The program a route belongs to (its chat is the program's own), else none: the copilot's own thread. */
export function programOf(pathname: string): string | null {
  return matchPath("/app/office/programs/:pid/*", pathname)?.params.pid ?? matchPath("/app/office/programs/:pid", pathname)?.params.pid ?? null;
}

/** Archie on every page (founder 2026-11-20): the copilot for the whole app. On a program page the program's chat
 * (status, changes, supervision) with the same app powers; elsewhere the engineer's own thread. Navigation and
 * pointing run at once; changes are proposals the engineer applies. */
export default function ArchieChat() {
  const qc = useQueryClient();
  const loc = useLocation();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const pid = programOf(loc.pathname);
  const prog = useProgram(pid ?? undefined);
  const program: Program | undefined = pid ? prog.data : undefined;
  const url = pid ? `${BASE}/programs/${pid}/archie` : "/api/copilot";
  const actUrl = pid ? `${BASE}/programs/${pid}/archie/actions` : "/api/copilot/actions";
  const key = pid ? ["office-archie", pid] : ["copilot"];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Chat>(url), enabled: open });
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const msgs = q.data?.messages ?? [];
  const canEdit = q.data?.can_edit !== false && program?.can_edit !== false;

  useEffect(() => {
    const o = () => setOpen(true);
    window.addEventListener("fw-open-archie", o);
    const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") { e.preventDefault(); setOpen(v => !v); } };
    window.addEventListener("keydown", k);
    return () => { window.removeEventListener("fw-open-archie", o); window.removeEventListener("keydown", k); };
  }, []);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs.length, busy, open]);
  useEffect(() => { if (open && pid && msgs.length) markSeen(pid, msgs[msgs.length - 1]!.id); }, [open, msgs, pid]);

  const show = async (a: ArchieAction) => {
    if (a.type === "navigate" && a.to) {
      nav(a.to);
      if (a.highlight) void pointAt(`t:${a.highlight}`, a.highlight, undefined, 6000);
    } else if (a.type === "studio_request" && a.project) {
      nav(`/app/projects/${a.project}?ask=${encodeURIComponent((a.text ?? "").slice(0, 1500))}`);
    } else if (a.type === "point" && a.target) {
      const ok = await pointAt(a.target, a.label, a.note);
      if (!ok) toast.message(`I can't see ${a.label ?? "that control"} on this page right now.`);
    }
  };

  const send = async (body: string) => {
    const t = body.trim();
    if (!t || busy) return;
    setBusy(true); setText("");
    qc.setQueryData<Chat>(key, old => old ? { ...old, messages: [...old.messages, { id: "pending", role: "user", text: t, t: new Date().toISOString() }] } : old);
    try {
      const r = await api.post<Chat>(url, { text: t, page: pageView() });
      qc.setQueryData(key, r);
      const last = r.messages[r.messages.length - 1];
      // navigation and pointing run at once: one navigation, then the pointing on the page it lands on
      const client = (last?.actions ?? []).filter(a => CLIENT.has(a.type) && a.type !== "studio_request");
      const go = client.find(a => a.type === "navigate");
      if (go) await show(go);
      for (const a of client.filter(a => a.type === "point")) { await show(a); break; }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Archie didn't get that");
      setText(t); void q.refetch();
    } finally { setBusy(false); }
  };
  const act = async (m: ArchieMessage, a: ArchieAction, decision: "apply" | "dismiss") => {
    setActing(`${m.id}:${a.id}`);
    try {
      const r = await api.post<Chat & { program?: Program; navigate?: string }>(actUrl, { message: m.id, action: a.id, decision });
      qc.setQueryData(key, { messages: r.messages, ai: r.ai, can_edit: r.can_edit });
      if (r.program && pid) qc.setQueryData(["office-program", pid], (old: Program | undefined) => ({ ...r.program!, can_edit: old?.can_edit }));
      if (decision === "apply") {
        toast.success("Done");
        void qc.invalidateQueries({ queryKey: ["office-home"] });
        if (r.navigate) nav(r.navigate);
      }
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not apply"); void q.refetch(); }
    finally { setActing(null); }
  };

  if (!open) return null;
  const quick = pid ? (QUICK[program?.status ?? "active"] ?? QUICK.active!) : QUICK.app!;
  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[420px] flex-col border-l border-border bg-panel shadow-2xl animate-fade-in" role="dialog" aria-label="Talk to Archie" data-archie-chat>
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <AgentAvatar code="archie" size={36} state={busy ? "working" : "idle"} />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">Archie</div>
          <div className="truncate text-[11.5px] text-muted">{program ? `Chief Designer · ${program.name}` : "Your copilot for all of Formwright"}</div>
        </div>
        <button className="rounded p-1.5 text-muted hover:bg-text/[.06] hover:text-text" aria-label="Close" onClick={() => setOpen(false)}><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {msgs.length === 0 && !q.isLoading && <div className="rounded-lg border border-dashed border-border p-3 text-[12.5px] text-muted">
          {program
            ? "Ask for a status report at any time, or tell me what should change: a part, more agents, a bigger budget, an interface number, or a fresh start from a new brief. I check every change before I propose it; you apply it. Status reports are free."
            : "Ask me anything about Formwright: where something is, how to do it, or what's wrong. I can take you to a page and point at the button, open a part with a request for the design agent, start or repair a program. Changes wait for you to apply them."}
        </div>}
        {msgs.map(m => m.role === "user"
          ? <div key={m.id} className="ml-10 rounded-lg bg-primary-soft px-3 py-2 text-[13px] whitespace-pre-line">{m.text}</div>
          : <div key={m.id} className="flex gap-2">
            <AgentAvatar code="archie" size={26} still />
            <div className="min-w-0 flex-1">
              <div className={cx("rounded-lg border bg-panel2 px-3 py-2 text-[13px] whitespace-pre-line", m.unprompted && m.actions?.length ? "border-warning/50" : "border-border")} data-archie-msg={m.kind}>{m.text}</div>
              {m.visual && (m.visual.image || m.visual.verdict) && <div className="mt-1.5 rounded-md border border-border bg-panel p-2" data-archie-visual>
                {m.visual.image && <a href={m.visual.image} target="_blank" rel="noreferrer"><img src={m.visual.image} alt="The assembly from four sides" className="max-h-[160px] w-full rounded object-contain" /></a>}
                <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted"><VerdictBadge v={m.visual.verdict} />Visual check, advisory{m.visual.tokens ? ` · ${m.visual.tokens} tokens` : ""}</div>
              </div>}
              {program && (m.questions ?? []).map(qq => <SupervisorQuestion key={qq.action} program={program} q={qq} canEdit={canEdit} />)}
              {(m.actions ?? []).map(a => CLIENT.has(a.type)
                ? <button key={a.id} className="mt-1.5 flex w-full items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-left text-[12.5px] hover:border-primary/40" data-archie-action={a.type} onClick={() => void show(a)}>
                  <Eye className="h-3.5 w-3.5 shrink-0 text-primary" /><span className="min-w-0 flex-1">{a.label}</span>
                  <span className="text-[11px] text-muted">{a.type === "studio_request" ? "Open" : "Show me"}</span></button>
                : <div key={a.id} className={cx("mt-1.5 rounded-md border px-2.5 py-2 text-[12.5px]", a.status === "proposed" && !a.stale ? "border-primary/30" : "border-border opacity-75")} data-archie-action={a.type}>
                  <div>{a.label}</div>
                  <div className="mt-1.5 flex items-center gap-2">
                    {a.status === "proposed" && a.stale ? <Badge tone="neutral">No longer needed</Badge>
                      : a.status === "proposed" && canEdit ? <>
                      <Button size="sm" loading={acting === `${m.id}:${a.id}`} disabled={!!acting} icon={<Check className="h-3.5 w-3.5" />} onClick={() => act(m, a, "apply")}>Apply</Button>
                      <Button size="sm" variant="ghost" disabled={!!acting} onClick={() => act(m, a, "dismiss")}>Dismiss</Button></>
                      : <Badge tone={a.status === "applied" ? "success" : "neutral"}>{a.status === "applied" ? `Applied${a.by ? ` by ${a.by.name}` : ""}` : a.status === "dismissed" ? "Dismissed" : "Proposed"}</Badge>}
                  </div>
                </div>)}
              <div className="mt-1 text-[10.5px] text-muted">{m.kind === "status" ? "From the program, no AI" : m.kind === "ai" ? "Archie (AI)" : m.kind === "look" ? "Archie looked" : m.kind === "supervisor" ? (m.supervisor?.mode === "ai" ? "Archie supervising (AI)" : m.supervisor?.mode === "simulated" ? "Archie supervising · Simulated" : "Archie supervising, no AI") : "Office"} · {ago(m.t)}</div>
            </div>
          </div>)}
        {busy && <div className="flex items-center gap-2 text-[12px] text-muted"><AgentAvatar code="archie" size={22} state="working" />Archie is looking into it…</div>}
        <div ref={end} />
      </div>
      {canEdit ? <div className="border-t border-border p-3">
        <div className="mb-2 flex flex-wrap gap-1.5">{quick.map(s => (
          <button key={s} disabled={busy} className="rounded-full border border-border px-2.5 py-0.5 text-[11.5px] text-muted hover:border-primary/40 hover:text-text disabled:opacity-50" onClick={() => void send(s)}>{s}</button>))}</div>
        <form className="flex items-end gap-2" onSubmit={e => { e.preventDefault(); void send(text); }}>
          <textarea className="input min-h-[40px] flex-1 resize-none py-2 text-[13px]" rows={2} maxLength={2000} value={text} aria-label="Message to Archie"
            placeholder={program ? "Ask for status, or say what should change…" : "Ask anything, or tell me what to do…"} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } }} />
          <Button type="submit" loading={busy} disabled={!text.trim()} icon={<Send className="h-4 w-4" />} aria-label="Send" />
        </form>
        <p className="mt-1.5 text-[10.5px] text-muted">{q.data && !q.data.ai ? "AI replies are off here: Archie answers status and the common requests directly." : "Ctrl J opens Archie anywhere."}</p>
      </div> : <div className="border-t border-border p-3 text-[12px] text-muted">Viewers can read the conversation but not change things.</div>}
    </div>
  );
}

/** The program conversation, polled while the chat is closed so Archie can speak first. */
function useArchieChat(pid: string) {
  return useQuery({ queryKey: ["office-archie", pid], enabled: !!pid, queryFn: () => api.get<Chat>(`${BASE}/programs/${pid}/archie`),
    refetchInterval: 8000 });
}
const SEEN = (pid: string) => `fw-archie-seen-${pid}`;
function markSeen(pid: string, id: string) { try { localStorage.setItem(SEEN(pid), id); } catch { /* private mode */ } }
function seenId(pid: string): string | null { try { return localStorage.getItem(SEEN(pid)); } catch { return null; } }

/** Messages Archie posted by himself (a look at the layout, a stopped step) since the engineer last opened the chat. */
export function unread(msgs: ArchieMessage[], seen: string | null): ArchieMessage[] {
  const k = seen ? msgs.findIndex(m => m.id === seen) : -1;
  return msgs.slice(k + 1).filter(m => m.role === "archie" && m.unprompted);
}

export function TalkToArchieButton({ onClick = openArchie, programId }: { onClick?: () => void; programId?: string }) {
  const q = useArchieChat(programId ?? "");
  const fresh = programId ? unread(q.data?.messages ?? [], seenId(programId)) : [];
  const told = useRef<string | null>(null);
  useEffect(() => {
    const last = fresh[fresh.length - 1];
    if (!last || told.current === last.id) return;
    told.current = last.id;
    toast.message("Archie has something to tell you", { description: last.text.split(String.fromCharCode(10))[0]?.slice(0, 140), action: { label: "Open", onClick } });
  }, [fresh, onClick]);
  return <span className="relative inline-flex">
    <Button variant="secondary" size="sm" icon={<MessageSquare className="h-4 w-4" />} onClick={onClick} data-talk-archie data-copilot="talk-archie">Talk to Archie</Button>
    {fresh.length > 0 && <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[10px] font-semibold text-white" data-archie-unread>{fresh.length}</span>}
  </span>;
}
