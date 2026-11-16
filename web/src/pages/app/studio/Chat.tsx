import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, Coins, ImagePlus, Loader2, Lock, MousePointer2, RotateCcw, Send, Sparkles, Square, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AgentEvent, Project } from "@/lib/types";
import { cx, num } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import { Button, Tip } from "@/components/ui";
import { agentDescriptor, describe } from "@/viewer/measure";
import type { Pick, Topo } from "@/viewer/types";
import { pickKey } from "@/viewer/types";

type ResultEv = Extract<AgentEvent, { type: "result" }> & { rev_before?: number | null; attachments?: string[] };
type ChatItem =
  | { kind: "user"; text: string } | { kind: "agent"; text: string } | { kind: "error"; text: string }
  | { kind: "tool"; id: string; name: string; brief: string; state: "run" | "ok" | "bad"; result?: string }
  | { kind: "result"; ev: ResultEv };

function reduce(items: ChatItem[], ev: AgentEvent): ChatItem[] {
  switch (ev.type) {
    case "reset": return [];
    case "user": return [...items, { kind: "user", text: ev.text }];
    case "text": return [...items, { kind: "agent", text: ev.text }];
    case "error": return [...items, { kind: "error", text: ev.text }];
    case "tool": return [...items, { kind: "tool", id: ev.id, name: ev.name, brief: ev.brief, state: "run" }];
    case "tool_result": return items.map(i => i.kind === "tool" && i.id === ev.id ? { ...i, state: ev.is_error ? "bad" : "ok", result: ev.brief } : i);
    case "result": return [...items, { kind: "result", ev: ev as ResultEv }];
    default: return items;
  }
}

const TOOL_LABEL: Record<string, string> = { build_model: "Build & verify", Write: "Write", Edit: "Edit", Read: "Read", Glob: "Search files", Grep: "Search", TodoWrite: "Plan", WebFetch: "Read docs" };

interface Att { name: string; mime: string; data_b64: string; url: string }

async function toAtt(f: File): Promise<Att> {
  if (!/^image\/(png|jpeg|webp|gif)$/.test(f.type)) throw new Error(`${f.name}: use PNG, JPEG, WebP or GIF`);
  if (f.size > 6 * 1024 * 1024) throw new Error(`${f.name}: larger than 6 MB`);
  const buf = new Uint8Array(await f.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return { name: f.name || "pasted.png", mime: f.type, data_b64: btoa(bin), url: URL.createObjectURL(f) };
}

export default function Chat({ project, topo, selection, onSelectionChange, onActivity }: {
  project: Project; topo: Topo | null; selection: Pick[]; onSelectionChange: (p: Pick[]) => void; onActivity: () => void;
}) {
  const { me } = useSession();
  const nav = useNavigate();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState(() => { try { return sessionStorage.getItem(`fw_starter_${project.id}`) ?? ""; } catch { return ""; } });
  const [model, setModel] = useState("");
  const [atts, setAtts] = useState<Att[]>([]);
  const [drag, setDrag] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const est = useQuery({ queryKey: ["estimate", project.id, items.length], queryFn: () => api.get<{ typical: number; low: number; high: number; basis: string }>(`/api/projects/${project.id}/estimate`) });
  const agent = project.agent;
  const unlimited = !!(me?.god?.enabled && me.god.bypass_tokens);

  useEffect(() => {
    setItems([]);
    const es = new EventSource(`/api/projects/${project.id}/agent/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as AgentEvent;
      if (ev.type === "hello") setBusy(ev.busy);
      if (ev.type === "busy") setBusy(ev.value);
      if (ev.type === "system") setModel(ev.model);
      if (ev.type === "tool_result" || ev.type === "result" || (ev.type === "text" && /^(Parameters updated|Restored|Manual feature)/.test(ev.text))) onActivity();
      setItems(prev => reduce(prev, ev));
    };
    return () => es.close();
  }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight; }, [items]);

  const addFiles = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      try { const a = await toAtt(f); setAtts(prev => (prev.length >= 4 ? prev : [...prev, a])); }
      catch (e) { toast.error((e as Error).message); }
    }
  };

  const send = async () => {
    let t = text.trim(); if ((!t && !atts.length) || busy) return;
    if (!t) t = "Model the part shown in the attached reference image(s).";
    if (selection.length && topo) t += "\n\n[Selected in viewer: " + selection.map((p, i) => `(${i + 1}) ${agentDescriptor(p, topo)}`).join("; ") + "]";
    try {
      await api.post(`/api/projects/${project.id}/agent/chat`, { prompt: t, attachments: atts.map(({ name, mime, data_b64 }) => ({ name, mime, data_b64 })) });
      setText(""); setAtts([]); onSelectionChange([]);
      try { sessionStorage.removeItem(`fw_starter_${project.id}`); } catch { /* ignore */ }
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        track("paywall_shown", { where: "studio" });
        toast.error(e.message, { action: e.cta ? { label: "Fix", onClick: () => nav(e.cta!) } : undefined });
      } else toast.error(e instanceof ApiError ? e.message : "Could not send");
    }
  };

  const undo = async (rev: number) => {
    try { await api.post(`/api/projects/${project.id}/revisions/${rev}/restore`); toast.success(`Reverted to revision ${rev}`); onActivity(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Undo failed"); }
  };
  const lastResultIdx = items.map(i => i.kind).lastIndexOf("result");
  const blocked = agent && !agent.allowed;

  return (
    <section className="flex min-h-0 flex-col border-r border-border bg-panel">
      <div className="flex h-11 items-center gap-2 border-b border-border px-3">
        <Sparkles className="h-4 w-4 text-accent" /><span className="text-sm font-semibold">Design agent</span>
        {model && <span className="truncate text-[11px] text-muted">{model}</span>}
        <Tip content="New conversation (model files are kept)" side="bottom">
          <button className="ml-auto rounded p-1.5 text-muted hover:bg-text/5" onClick={() => api.post(`/api/projects/${project.id}/agent/reset`)}><RotateCcw className="h-4 w-4" /></button>
        </Tip>
      </div>
      <div ref={logRef} className="flex-1 space-y-2.5 overflow-y-auto px-3 py-3 text-[13.5px] leading-relaxed">
        {items.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-4 text-[13px] text-muted">
            <div className="mb-1 font-medium text-text">Describe the part you need</div>
            Include material, overall size, holes, fillets and anything that must not change. Attach a sketch or photo, or select faces and edges in the viewer and say what to do with them.
          </div>)}
        {items.map((i, n) => {
          if (i.kind === "user") return <div key={n} className="ml-8 whitespace-pre-wrap rounded-lg bg-primary px-3 py-2 text-white">{i.text.replace(/\n\n\[Selected in viewer:[\s\S]*$/, "").replace(/\n\n\[Reference image[\s\S]*$/, "")}
            {/\[Selected in viewer:/.test(i.text) && <div className="mt-1 text-[11px] text-white/75"><MousePointer2 className="mr-1 inline h-3 w-3" />with viewer selection</div>}
            {/\[Reference image/.test(i.text) && <div className="mt-1 text-[11px] text-white/75"><ImagePlus className="mr-1 inline h-3 w-3" />with reference image</div>}</div>;
          if (i.kind === "agent") return <div key={n} className="rounded-lg border border-border bg-panel2 px-3 py-2"><Markdown text={i.text} /></div>;
          if (i.kind === "error") return <div key={n} className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-danger">{i.text}</div>;
          if (i.kind === "tool") return (
            <div key={n} className="flex items-start gap-2 px-1 text-[12px] text-muted" title={i.result}>
              <span className="mt-0.5">{i.state === "run" ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : i.state === "ok" ? <Check className="h-3.5 w-3.5 text-success" /> : <X className="h-3.5 w-3.5 text-danger" />}</span>
              <span><b className="font-medium text-text">{TOOL_LABEL[i.name] ?? i.name}</b> {i.brief}
                {i.name === "build_model" && i.result && <span className={cx("ml-1", i.result.includes("PASS") ? "text-success" : "text-danger")}>— {i.result}</span>}</span>
            </div>);
          return (
            <div key={n} className="flex flex-wrap items-center justify-center gap-x-2 border-b border-dashed border-border pb-2 text-[11px] text-muted">
              <span>{i.ev.subtype === "success" ? "Done" : i.ev.subtype}</span>·<span>{i.ev.turns} turns</span>·<span>{i.ev.duration_s}s</span>
              {i.ev.tokens_charged !== undefined && <>·<span className="inline-flex items-center gap-1 font-medium text-text"><Coins className="h-3 w-3 text-accent" />{i.ev.tokens_charged} tokens</span></>}
              {n === lastResultIdx && typeof i.ev.rev_before === "number" && !busy &&
                <>·<button onClick={() => undo(i.ev.rev_before as number)} className="inline-flex items-center gap-1 font-medium text-primary hover:underline"><Undo2 className="h-3 w-3" />Undo this change</button></>}
            </div>);
        })}
        {busy && <div className="flex items-center gap-2 px-1 text-[12px] text-primary"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Working…</div>}
      </div>
      <div className={cx("border-t border-border p-3", drag && "bg-primary-soft")} data-tour="prompt"
        onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); }}>
        {blocked ? (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-[13px]">
            <div className="flex items-center gap-2 font-medium"><Lock className="h-4 w-4 text-warning" />{agent?.reason}</div>
            {agent?.cta && <Button size="sm" className="mt-2.5" onClick={() => nav(agent.cta!)}>Upgrade or top up</Button>}
          </div>
        ) : <>
          {(selection.length > 0 || atts.length > 0) && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {selection.map(p => (
                <span key={pickKey(p)} className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary-soft px-2 py-0.5 text-[11.5px] text-primary">
                  <MousePointer2 className="h-3 w-3" />{topo ? describe(p, topo) : p.kind}
                  <button onClick={() => onSelectionChange(selection.filter(x => pickKey(x) !== pickKey(p)))} aria-label="Remove selection"><X className="h-3 w-3" /></button>
                </span>))}
              {atts.map((a, i) => (
                <span key={a.url} className="relative inline-block">
                  <img src={a.url} alt={a.name} className="h-12 w-12 rounded border border-border object-cover" />
                  <button onClick={() => setAtts(atts.filter((_, j) => j !== i))} className="absolute -right-1.5 -top-1.5 rounded-full bg-chrome p-0.5 text-white" aria-label="Remove image"><X className="h-3 w-3" /></button>
                </span>))}
            </div>)}
          <textarea value={text} onChange={e => setText(e.target.value)} rows={4} disabled={busy}
            onPaste={e => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs); } }}
            onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }}
            placeholder={selection.length ? "Say what to do with the selection, e.g. “fillet these edges R2”" : "e.g. 6061 aluminium L-bracket, 60 × 40 mm legs, 50 mm wide, 5 mm thick, two M5 clearance holes per leg, 3 mm inside fillet"}
            className="input h-auto min-h-[84px] resize-y py-2 leading-relaxed" />
          <div className="mt-2 flex items-center gap-2">
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden onChange={e => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
            <Tip content="Attach a sketch, photo or drawing (or paste / drop an image)" side="top">
              <button onClick={() => fileRef.current?.click()} className="rounded p-1.5 text-muted hover:bg-text/5" aria-label="Attach image"><ImagePlus className="h-4 w-4" /></button>
            </Tip>
            <span className="flex-1 text-[11px] text-muted">{unlimited ? "Unlimited tokens (God mode)" : est.data ? `≈ ${est.data.typical} tokens (${est.data.low}–${est.data.high}) · balance ${num(me?.org?.token_balance)}` : ""} · <span className="kbd">Ctrl ↵</span></span>
            {busy ? <Button size="sm" variant="secondary" icon={<Square className="h-3.5 w-3.5" />} onClick={() => api.post(`/api/projects/${project.id}/agent/interrupt`)}>Stop</Button>
              : <Button size="sm" icon={<Send className="h-3.5 w-3.5" />} onClick={send} disabled={!text.trim() && !atts.length}>Send</Button>}
          </div>
        </>}
      </div>
    </section>
  );
}
