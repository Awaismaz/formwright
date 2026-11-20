import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ExternalLink, Info, Loader2, RotateCcw, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import { Badge, Button, Tip } from "@/components/ui";
import { AgentBadge } from "@/components/AgentBadge";
import ShopStatus, { type ShopPhase } from "@/pages/app/studio/ShopStatus";
import type { AsmView } from "./types";
import { EXAMPLES, answerText, liveQuestions, replyMeta, stateTone, type ChatMessage, type ChatQuestion, type ChatStep, type ChatView } from "./chat";

/** WORKLIST 51: one flowing conversation per assembly with the assembly agent. It keeps the context (the server
 * stores the conversation), decides from the history and the assembly what is needed, and acts: makes parts, brings
 * them in, assembles, checks and edits. What it reports after a step comes from the solver and the checks. */
export function AssemblyChat({ aid, view, onChanged, onSelect }: {
  aid: string; view: AsmView; onChanged: () => void; onSelect: (iid: string) => void;
}) {
  const qc = useQueryClient();
  const key = ["asm-chat", aid];
  const q = useQuery({
    queryKey: key, queryFn: () => api.get<ChatView>(`/api/m/assembly/assemblies/${aid}/chat`),
    refetchInterval: d => (d.state.data?.busy || d.state.data?.jobs.some(j => j.status === "running") ? 1200 : false),
  });
  const data = q.data;
  const msgs = data?.messages ?? [];
  const busy = !!data?.busy;
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const seen = useRef<string | null>(null);
  const names = new Map(view.instances.map(i => [i.id, i.display]));   // the tree's names, so a chip finds its row

  useEffect(() => {   // a finished reply (or a design job that brought a part in) changed the assembly: reload it
    const last = msgs[msgs.length - 1];
    const sig = `${msgs.length}:${last?.id ?? ""}:${busy}`;
    if (seen.current !== null && seen.current !== sig && !busy) onChanged();
    seen.current = sig;
  }, [msgs, busy, onChanged]);
  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" }); }, [msgs.length, data?.busy?.step]);

  const send = async (t: string) => {
    const s = t.trim();
    if (!s || busy || sending) return;
    setSending(true);
    try {
      qc.setQueryData(key, await api.post<ChatView>(`/api/m/assembly/assemblies/${aid}/chat`, { text: s }));
      setText("");
    } catch (e) { toast.error((e as Error).message); } finally { setSending(false); }
  };
  const reset = async () => {
    try { qc.setQueryData(key, await api.post<ChatView>(`/api/m/assembly/assemblies/${aid}/chat/reset`)); }
    catch (e) { toast.error((e as Error).message); }
  };
  const since = data?.busy ? Date.parse(data.busy.since) : 0;
  const step = data?.busy?.step ?? null;

  return (
    <section className="flex h-full min-h-[520px] flex-col" data-testid="assembly-chat">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <AgentBadge name="Fitz" size={24} state={busy ? "working" : "idle"} />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-[13px] font-semibold">Assembly agent</div>
          <div className="truncate text-[11px] text-muted">Makes, brings in, assembles and checks, in one conversation</div>
        </div>
        {msgs.length > 0 && view.can_edit && (
          <Tip content="New conversation (the assembly is kept)" side="bottom">
            <button className="rounded p-1.5 text-muted hover:bg-text/5 disabled:opacity-40" disabled={busy} onClick={reset} aria-label="New conversation">
              <RotateCcw className="h-4 w-4" /></button>
          </Tip>)}
      </div>
      <div ref={logRef} className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-3 text-[13px] leading-relaxed" data-chat-log>
        {msgs.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-3.5 text-[12.5px] text-muted">
            <div className="mb-1 font-medium text-text">Tell me what this assembly needs</div>
            I keep the whole conversation, so you can refer back: "that shaft", "the gear I just made". I make parts when
            every size is known (or hand them to the design agent), bring parts from your workspace or the Toolbox,
            assemble them where they belong and check the result.
            <div className="mt-2.5 flex flex-col gap-1">
              {EXAMPLES.map(x => <button key={x} type="button" onClick={() => setText(x)} disabled={!view.can_edit}
                className="rounded-md border border-border bg-panel2 px-2 py-1 text-left text-[11.5px] text-muted hover:border-primary hover:text-text">{x}</button>)}
            </div>
          </div>)}
        {msgs.map((m, n) => m.role === "user"
          ? <div key={m.id} className="ml-8 whitespace-pre-wrap rounded-lg bg-primary px-3 py-2 text-white" data-msg="user">{m.text}</div>
          : <AgentReply key={m.id} m={m} names={names} onSelect={onSelect}
              live={liveQuestions(msgs, n, busy) && view.can_edit} onAnswer={send} />)}
        {(data?.jobs ?? []).filter(j => j.status === "running").map(j => (
          <div key={j.id} className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-[12px]" data-job={j.id}>
            <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
            <div className="min-w-0 flex-1"><div className="font-medium">Designing {j.name} in the Design Studio</div>
              <div className="truncate text-muted">{j.step}</div></div>
            <Link to={`/app/projects/${j.project_id}`} target="_blank" className="shrink-0 text-primary hover:underline" title="Open it in the Design Studio">
              <ExternalLink className="h-3.5 w-3.5" /></Link>
          </div>))}
        {busy && <ShopStatus phase={phaseOf(step)} since={since} step={step} />}
      </div>
      <div className="border-t border-border p-2.5">
        {!view.can_edit ? <p className="text-[12px] text-muted">Viewers can read the conversation but not change the assembly.</p> : <>
          <div className="flex items-end gap-2">
            <textarea value={text} onChange={e => setText(e.target.value)} rows={2} data-testid="chat-input"
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(text); } }}
              placeholder={msgs.length ? "Reply, or ask for the next step" : "e.g. make a stepped shaft Ø20 with a keyseat and bring a gear for it"}
              className="input h-auto min-h-[52px] flex-1 resize-none py-1.5 text-[12.5px] leading-snug" />
            <Button size="sm" icon={<Send className="h-3.5 w-3.5" />} loading={sending} disabled={!text.trim() || busy} onClick={() => send(text)} data-testid="chat-send">Send</Button>
          </div>
          {data && !data.ai && <p className="mt-1.5 text-[11px] text-muted">The AI assistant isn't available on this account right now: I read the common requests (bring, assemble everything, check) without it.</p>}
        </>}
      </div>
    </section>
  );
}

function phaseOf(step: string | null): ShopPhase {
  const s = (step ?? "").toLowerCase();
  if (/check|clash|turning|looking/.test(s)) return "inspect";
  if (/build|making|resiz|rebuild/.test(s)) return "build";
  if (/assembl|mating|bring/.test(s)) return "finish";
  if (/reading|conversation/.test(s)) return "read";
  return "plan";
}

function AgentReply({ m, names, onSelect, live, onAnswer }: {
  m: ChatMessage; names: Map<string, string>; onSelect: (iid: string) => void; live: boolean; onAnswer: (t: string) => void;
}) {
  return (
    <div className="space-y-1.5" data-msg="agent">
      {m.text && <div className="rounded-lg border border-border bg-panel2 px-3 py-2"><Markdown text={m.text} /></div>}
      {(m.steps ?? []).map((s, k) => <StepRow key={k} s={s} names={names} onSelect={onSelect} />)}
      {(m.questions ?? []).length > 0 && <Chips qs={m.questions!} live={live} onAnswer={onAnswer} />}
      {(m.state || m.seconds !== undefined) && (
        <div className="px-1 text-[11px] text-muted" data-state>
          <div className="flex items-center gap-2">
            {m.state && m.state_text && <Badge tone={stateTone(m.state)}>{m.state.unplaced ? `${m.state.unplaced} unplaced` : m.state.bad ? `${m.state.bad} mate${m.state.bad > 1 ? "s" : ""} not satisfied` : m.state.mates ? "all mates satisfied" : `${m.state.parts} part${m.state.parts === 1 ? "" : "s"}`}</Badge>}
            {m.seconds !== undefined && <span className="ml-auto tabular-nums">{replyMeta(m)}</span>}
          </div>
          {m.state_text && <div className="mt-0.5 leading-snug">{m.state_text}</div>}
        </div>)}
    </div>
  );
}

function StepRow({ s, names, onSelect }: { s: ChatStep; names: Map<string, string>; onSelect: (iid: string) => void }) {
  const Icon = s.status === "ok" ? Check : s.status === "fail" ? X : s.status === "warn" ? AlertTriangle : Info;
  const tone = s.status === "ok" ? "text-success" : s.status === "fail" ? "text-danger" : s.status === "warn" ? "text-warning" : "text-muted";
  const [open, setOpen] = useState(s.status !== "ok" || s.lines.length <= 3);
  return (
    <div className="rounded-md px-1 text-[12px]" data-step={s.status}>
      <button type="button" className="flex w-full items-start gap-1.5 text-left" onClick={() => setOpen(o => !o)}>
        <Icon className={cx("mt-0.5 h-3.5 w-3.5 shrink-0", tone)} />
        <span className="font-medium text-text">{s.label}</span>
        {!open && s.lines.length > 0 && <span className="text-muted">· {s.lines.length} lines</span>}
      </button>
      {open && <ul className="ml-5 mt-0.5 space-y-0.5 text-muted">
        {s.lines.map((l, k) => <li key={k} className={cx(s.status === "fail" && "text-danger")}>{l}</li>)}
      </ul>}
      {s.parts.length > 0 && <div className="ml-5 mt-1 flex flex-wrap gap-1">
        {s.parts.filter(p => names.has(p)).slice(0, 8).map(p => <button key={p} type="button" onClick={() => onSelect(p)}
          className="rounded-full border border-border bg-panel px-2 py-px text-[11px] text-muted hover:border-primary hover:text-primary" title="Show it in the view">{names.get(p)}</button>)}
      </div>}
    </div>
  );
}

function Chips({ qs, live, onAnswer }: { qs: ChatQuestion[]; live: boolean; onAnswer: (t: string) => void }) {
  const [sent, setSent] = useState<string | null>(null);
  const on = live && !sent;
  const pick = (q: ChatQuestion, o: string) => { setSent(o); onAnswer(answerText(q, o)); };
  return (
    <div className="rounded-lg border border-primary/30 bg-primary-soft/40 px-3 py-2.5" data-questions>
      {qs.map(q => (
        <div key={q.id} className="mb-2 last:mb-0">
          <div className="mb-1.5 text-[12.5px] font-medium">{q.question}</div>
          <div className="flex flex-wrap gap-1.5">
            {q.options.map(o => <button key={o} type="button" disabled={!on} onClick={() => pick(q, o)} data-chip={o}
              className={cx("rounded-full border px-2.5 py-1 text-[12px] transition", sent === o ? "border-primary bg-primary text-white" : "border-border bg-panel hover:border-primary hover:text-primary", !on && sent !== o && "opacity-50")}>{o}</button>)}
          </div>
        </div>))}
    </div>
  );
}
