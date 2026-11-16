import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Check, CircleHelp, Coins, Download, FileCode2, History, Lock, Loader2, RotateCcw, Send, SlidersHorizontal,
  Sparkles, Square, Wand2, X,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AgentEvent, BuildStatus, Catalog, Project } from "@/lib/types";
import { ago, cx, num } from "@/lib/format";
import { Markdown } from "@/lib/markdown";
import { Badge, Button, Input, PageLoader, Tab, TabList, TabPanel, Tabs, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import Viewer3D from "@/components/Viewer3D";
import { ProjectStatus } from "@/components/ProjectCard";
import { runTour, seenTour, STUDIO_TOUR } from "@/lib/tour";

type ChatItem =
  | { kind: "user"; text: string } | { kind: "agent"; text: string } | { kind: "error"; text: string }
  | { kind: "tool"; id: string; name: string; brief: string; state: "run" | "ok" | "bad"; result?: string }
  | { kind: "result"; ev: Extract<AgentEvent, { type: "result" }> };

function reduce(items: ChatItem[], ev: AgentEvent): ChatItem[] {
  switch (ev.type) {
    case "reset": return [];
    case "user": return [...items, { kind: "user", text: ev.text }];
    case "text": return [...items, { kind: "agent", text: ev.text }];
    case "error": return [...items, { kind: "error", text: ev.text }];
    case "tool": return [...items, { kind: "tool", id: ev.id, name: ev.name, brief: ev.brief, state: "run" }];
    case "tool_result": return items.map(i => i.kind === "tool" && i.id === ev.id ? { ...i, state: ev.is_error ? "bad" : "ok", result: ev.brief } : i);
    case "result": return [...items, { kind: "result", ev }];
    default: return items;
  }
}

const TOOL_LABEL: Record<string, string> = { build_model: "Build & verify", Write: "Write", Edit: "Edit", Read: "Read", Glob: "Search files", Grep: "Search", TodoWrite: "Plan", WebFetch: "Read docs" };

function Chat({ project, onActivity }: { project: Project; onActivity: () => void }) {
  const { me } = useSession();
  const nav = useNavigate();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState(() => { try { return sessionStorage.getItem(`fw_starter_${project.id}`) ?? ""; } catch { return ""; } });
  const [model, setModel] = useState<string>("");
  const logRef = useRef<HTMLDivElement>(null);
  const agent = project.agent;
  const org = me?.org;

  useEffect(() => {
    setItems([]);
    const es = new EventSource(`/api/projects/${project.id}/agent/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as AgentEvent;
      if (ev.type === "hello") setBusy(ev.busy);
      if (ev.type === "busy") setBusy(ev.value);
      if (ev.type === "system") setModel(ev.model);
      if (ev.type === "tool_result" || ev.type === "result" || (ev.type === "text" && ev.text.startsWith("Parameters updated")) || (ev.type === "text" && ev.text.startsWith("Restored"))) onActivity();
      setItems(prev => reduce(prev, ev));
    };
    return () => es.close();
  }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight; }, [items]);

  const send = async () => {
    const t = text.trim(); if (!t || busy) return;
    try {
      await api.post(`/api/projects/${project.id}/agent/chat`, { prompt: t });
      setText(""); try { sessionStorage.removeItem(`fw_starter_${project.id}`); } catch { /* ignore */ }
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        track("paywall_shown", { where: "studio" });
        toast.error(e.message, { action: e.cta ? { label: "Fix", onClick: () => nav(e.cta!) } : undefined });
      } else toast.error(e instanceof ApiError ? e.message : "Could not send");
    }
  };

  const blocked = agent && !agent.allowed;
  return (
    <section className="flex min-h-0 flex-col border-r border-border bg-panel">
      <div className="flex h-11 items-center gap-2 border-b border-border px-3">
        <Sparkles className="h-4 w-4 text-accent" /><span className="text-sm font-semibold">Design agent</span>
        {model && <span className="truncate text-[11px] text-muted">{model}</span>}
        <Tip content="Start a new conversation (files are kept)" side="bottom">
          <button className="ml-auto rounded p-1.5 text-muted hover:bg-text/5" onClick={async () => { await api.post(`/api/projects/${project.id}/agent/reset`); }}><RotateCcw className="h-4 w-4" /></button>
        </Tip>
      </div>
      <div ref={logRef} className="flex-1 space-y-2.5 overflow-y-auto px-3 py-3 text-[13.5px] leading-relaxed">
        {items.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-4 text-[13px] text-muted">
            <div className="mb-1 font-medium text-text">Describe the part you need</div>
            Include material, overall size, holes (size & position), fillets/chamfers and anything that must not change. The agent states its assumptions, builds, verifies and shows the result.
          </div>
        )}
        {items.map((i, n) => {
          if (i.kind === "user") return <div key={n} className="ml-8 whitespace-pre-wrap rounded-lg bg-primary px-3 py-2 text-white">{i.text}</div>;
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
            </div>);
        })}
        {busy && <div className="flex items-center gap-2 px-1 text-[12px] text-primary"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Working…</div>}
      </div>
      <div className="border-t border-border p-3" data-tour="prompt">
        {blocked ? (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-[13px]">
            <div className="flex items-center gap-2 font-medium"><Lock className="h-4 w-4 text-warning" />{agent?.reason}</div>
            {agent?.cta && <Button size="sm" className="mt-2.5" onClick={() => nav(agent.cta!)}>Upgrade or top up</Button>}
          </div>
        ) : <>
          <textarea value={text} onChange={e => setText(e.target.value)} rows={4} disabled={busy}
            onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }}
            placeholder="e.g. 6061 aluminium L-bracket, 60 × 40 mm legs, 50 mm wide, 5 mm thick, two M5 clearance holes per leg, 3 mm inside fillet"
            className="input h-auto min-h-[84px] resize-y py-2 leading-relaxed" />
          <div className="mt-2 flex items-center gap-2">
            <span className="flex-1 text-[11px] text-muted">{org?.god_unlock || me?.god?.bypass_tokens ? "God mode · tokens bypassed" : `Typical run 20–80 tokens · balance ${num(org?.token_balance)}`} · <span className="kbd">Ctrl ↵</span></span>
            {busy ? <Button size="sm" variant="secondary" icon={<Square className="h-3.5 w-3.5" />} onClick={() => api.post(`/api/projects/${project.id}/agent/interrupt`)}>Stop</Button>
              : <Button size="sm" icon={<Send className="h-3.5 w-3.5" />} onClick={send} disabled={!text.trim()}>Send</Button>}
          </div>
        </>}
      </div>
    </section>
  );
}

function ChecksPanel({ status }: { status?: BuildStatus }) {
  if (!status) return <p className="p-4 text-sm text-muted">No build yet.</p>;
  if (status.error) return <div className="m-3 rounded-lg border border-danger/40 bg-danger/5 p-3 text-[13px] text-danger"><b>Build failed</b><div className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{status.error}</div></div>;
  return (
    <div className="space-y-3 p-3" data-tour="checks">
      <div className={cx("rounded-lg px-3 py-2 text-sm font-semibold", status.ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger")}>
        {status.ok ? "All gating checks pass" : "Some checks fail"}</div>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {(status.checks ?? []).map(c => {
          const d = Object.entries(c.detail).filter(([k]) => !["original", "reimported"].includes(k)).slice(0, 4);
          return (
            <li key={c.id} className="px-3 py-2">
              <div className="flex items-center gap-2 text-[13px]">
                <span className={cx("rounded px-1.5 text-[10px] font-bold", c.passed ? "bg-success/12 text-success" : c.gating ? "bg-danger/12 text-danger" : "bg-text/10 text-muted")}>{c.passed ? "PASS" : c.gating ? "FAIL" : "INFO"}</span>
                <span className="font-medium">{c.name}</span>
              </div>
              <div className="mt-1 text-[11px] text-muted">{d.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.map(x => typeof x === "number" ? +x.toFixed(4) : x).join(" × ") : typeof v === "number" ? (Math.abs(v) < 1e-3 && v !== 0 ? v.toExponential(1) : +v.toFixed(4)) : typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ")}</div>
            </li>);
        })}
      </ul>
      <p className="text-[11px] text-muted">Checks prove geometric consistency with the stated expectations — not strength, fit or manufacturability. Engineering sign-off stays with you.</p>
    </div>
  );
}

function ParamsPanel({ project, status, onChanged }: { project: Project; status?: BuildStatus; onChanged: () => void }) {
  const q = useQuery({ queryKey: ["params", project.id, status?.build_id], queryFn: () => api.get<{ editable: Record<string, number> }>(`/api/projects/${project.id}/params`) });
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { setVals({}); }, [status?.build_id]);
  const editable = q.data?.editable ?? {};
  // Only parameters the model declares in PARAMS are shown; internal/derived variables never appear.
  const shown: Record<string, unknown> = status?.params ?? {};
  const dirty = Object.entries(vals).filter(([k, v]) => v !== "" && Number(v) !== editable[k]);
  if (!status?.fingerprint) return <p className="p-4 text-sm text-muted">Parameters appear after the first successful build.</p>;
  if (!Object.keys(shown).length) return <p className="p-4 text-sm text-muted">This model doesn't declare any design parameters. Ask the agent to “expose the key dimensions as parameters”.</p>;
  return (
    <div className="space-y-3 p-3">
      <p className="text-[12px] text-muted">Edit a value and rebuild instantly — <b className="text-text">no AI call, no tokens</b>. The change is kept only if the part still passes its checks.</p>
      <table className="w-full text-[13px]"><tbody className="divide-y divide-border">
        {Object.entries(shown).map(([k, v]) => {
          const can = k in editable;
          return (
            <tr key={k}><td className="py-1.5 pr-2 font-mono text-[12px] text-muted">{k}</td>
              <td className="py-1.5 text-right">{can
                ? <Input className="h-7 w-24 text-right font-mono text-[12px]" value={vals[k] ?? String(editable[k])} onChange={e => setVals({ ...vals, [k]: e.target.value })} inputMode="decimal" />
                : <Tip content="Derived or compound value — ask the agent to change it" side="left"><span className="font-mono text-[12px]">{String(v)}</span></Tip>}</td></tr>);
        })}
      </tbody></table>
      <Button size="sm" className="w-full" icon={<Wand2 className="h-4 w-4" />} disabled={!dirty.length || project.agent?.busy} loading={busy} onClick={async () => {
        setBusy(true);
        try {
          const values = Object.fromEntries(dirty.map(([k, v]) => [k, Number(v)]));
          if (Object.values(values).some(v => !Number.isFinite(v))) throw new ApiError(422, "Enter valid numbers");
          const r = await api.post<{ revision: number }>(`/api/projects/${project.id}/params`, { values });
          toast.success(`Rebuilt and verified · revision ${r.revision}`); onChanged();
        } catch (e) { toast.error(e instanceof ApiError ? e.message : "Rebuild failed"); }
        finally { setBusy(false); }
      }}>Apply & rebuild ({dirty.length})</Button>
    </div>
  );
}

function RevisionsPanel({ project, onChanged, version }: { project: Project; onChanged: () => void; version?: number }) {
  const q = useQuery({ queryKey: ["revisions", project.id, version], queryFn: () => api.get<{ items: { n: number; ok: boolean; error?: string; fingerprint?: { bbox: number[]; volume: number }; created_at: string }[] }>(`/api/projects/${project.id}/revisions`) });
  const [busy, setBusy] = useState<number | null>(null);
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="p-4 text-sm text-muted">Every build becomes a revision you can restore.</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((r, i) => (
        <li key={r.n} className="flex items-center gap-3 px-3 py-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-panel2 text-[11px] font-semibold">{r.n}</span>
          <div className="min-w-0 flex-1 text-[12px]">
            <div className="flex items-center gap-1.5">{r.ok ? <Badge tone="success">Verified</Badge> : <Badge tone="danger">Failed</Badge>}{i === 0 && <Badge tone="primary">Latest</Badge>}</div>
            <div className="mt-0.5 text-muted">{r.fingerprint ? `${r.fingerprint.bbox.map(n => Math.round(n)).join("×")} mm · ${num(r.fingerprint.volume, 0)} mm³` : r.error?.slice(0, 40)} · {ago(r.created_at)}</div>
          </div>
          {i > 0 && <Button size="sm" variant="secondary" loading={busy === r.n} disabled={busy !== null} onClick={async () => {
            setBusy(r.n);
            try { await api.post(`/api/projects/${project.id}/revisions/${r.n}/restore`); toast.success(`Revision ${r.n} restored`); onChanged(); }
            catch (e) { toast.error(e instanceof ApiError ? e.message : "Restore failed"); } finally { setBusy(null); }
          }}>Restore</Button>}
        </li>
      ))}
    </ul>
  );
}

function FilesPanel({ project, status }: { project: Project; status?: BuildStatus }) {
  if (!status?.fingerprint) return <p className="p-4 text-sm text-muted">Exports appear after the first successful build.</p>;
  const base = `/api/projects/${project.id}/files`;
  return (
    <div className="space-y-2 p-3">
      {[["part.step", "STEP (AP214)", "For SOLIDWORKS, Creo, Fusion, Inventor, NX…"], ["part.stl", "STL", "For slicers and quick viewing"]].map(([f, l, h]) => (
        <a key={f} href={`${base}/${f}`} className="flex items-center gap-3 rounded-lg border border-border p-3 hover:border-primary/50">
          <Download className="h-4 w-4 text-primary" /><div className="flex-1"><div className="text-sm font-medium">{l}</div><div className="text-xs text-muted">{h}</div></div>
        </a>
      ))}
      <div className="rounded-lg border border-dashed border-border p-3 text-xs text-muted">
        <div className="mb-1 flex items-center gap-1.5 font-medium text-text"><Lock className="h-3.5 w-3.5" /> Drawing PDF / DXF</div>
        Manufacturing drawings come with <Link to="/app/modules/drawings" className="link">Drawing Studio</Link> (Preview).
      </div>
      <img src={`${base}/views.png?v=${status.build_id}`} alt="Four-view render" className="mt-2 w-full rounded-lg border border-border" />
    </div>
  );
}

function SourcePanel({ project, version }: { project: Project; version?: number }) {
  const q = useQuery({ queryKey: ["source", project.id, version], queryFn: () => fetch(`/api/projects/${project.id}/source`).then(r => r.text()) });
  if (!q.data) return <p className="p-4 text-sm text-muted">The parametric source appears once the agent writes it.</p>;
  return <pre className="m-3 overflow-x-auto rounded-lg border border-border bg-panel2 p-3 font-mono text-[11.5px] leading-relaxed">{q.data}</pre>;
}

export default function ProjectStudio() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { me } = useSession();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/api/projects/${id}`), refetchInterval: 15_000 });
  const hasBuilds = (project.data?.builds ?? 0) > 0;
  const status = useQuery({ queryKey: ["status", id, hasBuilds], enabled: hasBuilds,
    queryFn: () => fetch(`/api/projects/${id}/files/status.json`).then(r => r.ok ? r.json() as Promise<BuildStatus> : null) });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const p = project.data;
  const st = status.data ?? undefined;

  useEffect(() => { if (p) setName(p.name); }, [p?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!p || seenTour("studio")) return;
    const t = setTimeout(() => runTour(STUDIO_TOUR, "studio"), 900);
    return () => clearTimeout(t);
  }, [p?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["status", id] }); qc.invalidateQueries({ queryKey: ["project", id] });
    qc.invalidateQueries({ queryKey: ["me"] }); qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const previewMods = useMemo(() => (catalog.data?.modules ?? []).filter(m => ["drawings", "manufacturing", "engineering"].includes(m.code)), [catalog.data]);

  if (project.isLoading) return <PageLoader />;
  if (!p) return <div className="p-10 text-center text-muted">Project not found. <Link to="/app/projects" className="link">Back to projects</Link></div>;
  const fp = st?.fingerprint;

  return (
    <div className="flex h-full flex-col">
      {/* command bar */}
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-panel px-3">
        <Link to="/app/projects" className="rounded p-1.5 text-muted hover:bg-text/5" aria-label="Back to projects"><ArrowLeft className="h-4 w-4" /></Link>
        {editing ? <Input autoFocus value={name} onChange={e => setName(e.target.value)} className="h-8 w-64"
          onBlur={async () => { setEditing(false); if (name.trim() && name !== p.name) { await api.patch(`/api/projects/${p.id}`, { name }); refresh(); } }}
          onKeyDown={e => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
          : <button onClick={() => setEditing(true)} className="truncate rounded px-1.5 py-1 text-[15px] font-semibold hover:bg-text/5" title="Rename">{p.name}</button>}
        <ProjectStatus p={p} />
        <nav className="ml-4 hidden items-center gap-1 md:flex" data-tour="studio-tabs">
          <span className="inline-flex items-center gap-1.5 rounded bg-primary-soft px-2.5 py-1 text-[13px] font-medium text-primary"><Icon name="box" className="h-3.5 w-3.5" />Design</span>
          {previewMods.map(m => (
            <Link key={m.code} to={`/app/modules/${m.code}?project=${p.id}`} className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-[13px] text-muted hover:bg-text/5 hover:text-text">
              <Icon name={m.icon} className="h-3.5 w-3.5" />{m.name.replace(" Studio", "").replace(" Advisor", "")}
              <span className="rounded bg-accent/12 px-1 text-[9px] font-bold uppercase text-accent">Prev</span>
            </Link>))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Tip content="Studio tour" side="bottom"><button onClick={() => runTour(STUDIO_TOUR, "studio")} className="rounded p-1.5 text-muted hover:bg-text/5"><CircleHelp className="h-4 w-4" /></button></Tip>
          {fp && <a href={`/api/projects/${p.id}/files/part.step`}><Button size="sm" icon={<Download className="h-4 w-4" />}>STEP</Button></a>}
        </div>
      </div>

      {/* workspace */}
      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[380px_minmax(0,1fr)_330px] max-xl:grid-cols-[340px_minmax(0,1fr)] max-md:grid-cols-1">
        <Chat project={p} onActivity={refresh} />
        <div className="relative min-h-[320px] min-w-0 overflow-hidden">
          <Viewer3D url={fp ? `/api/projects/${p.id}/files/model.glb` : null} version={st?.build_id} bboxMm={fp?.bbox}
            empty={<div className="text-center text-sm text-muted"><Icon name="box" className="mx-auto mb-2 h-10 w-10 text-muted/40" />Your model appears here after the first build.</div>} />
        </div>
        <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden border-l border-border bg-panel max-xl:hidden">
          <Tabs defaultValue="checks" className="flex min-h-0 flex-1 flex-col">
            <TabList className="gap-0 overflow-x-auto px-1 [scrollbar-width:none]"><Tab compact value="checks"><Check className="h-3.5 w-3.5" />Checks</Tab><Tab compact value="params"><SlidersHorizontal className="h-3.5 w-3.5" />Params</Tab>
              <Tab compact value="revs" title="Revisions"><History className="h-3.5 w-3.5" />Revs</Tab><Tab compact value="files" title="Files & exports"><Download className="h-3.5 w-3.5" /></Tab>
              <Tab compact value="src" title="Parametric source (model.py)"><FileCode2 className="h-3.5 w-3.5" /></Tab></TabList>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <TabPanel value="checks"><ChecksPanel status={st} /></TabPanel>
              <TabPanel value="params"><ParamsPanel project={p} status={st} onChanged={refresh} /></TabPanel>
              <TabPanel value="revs"><RevisionsPanel project={p} onChanged={refresh} version={st?.build_id} /></TabPanel>
              <TabPanel value="files"><FilesPanel project={p} status={st} /></TabPanel>
              <TabPanel value="src"><SourcePanel project={p} version={st?.build_id} /></TabPanel>
            </div>
          </Tabs>
        </aside>
      </div>

      {/* status bar */}
      <div className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-panel2 px-3 text-[11.5px] text-muted">
        <span>{st?.part ?? p.name}</span>
        {st?.material && <span>{st.material}</span>}
        {fp && <><span>{fp.bbox.map(n => n.toFixed(2)).join(" × ")} mm</span><span>{num(fp.volume, 1)} mm³</span><span>{fp.faces} faces</span></>}
        {st?.timings_s?.total_s !== undefined && <span>build {st.timings_s.total_s}s</span>}
        <span className="ml-auto">Units: {me?.user?.preferences?.units === "in" ? "in (display) · model mm" : "mm"}</span>
        <span>{p.builds} builds</span>
      </div>
    </div>
  );
}
