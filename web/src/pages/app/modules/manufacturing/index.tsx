import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Box as BoxIcon, CheckCircle2, ChevronRight, CircleSlash, Download, Factory, FileText, Info,
  Loader2, Play, RefreshCw, Settings2, X, XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, Button, EmptyState, Menu, MenuContent, MenuItem, MenuTrigger, PageLoader, StatusBadge, Tab, TabList, TabPanel, Tabs, Tip } from "@/components/ui";
import Viewer3D, { type Tool } from "@/components/Viewer3D";
import type { Pick } from "@/viewer/types";
import type { ModuleAppProps } from "../registry";
import CostChart, { money, seriesColor } from "./CostChart";
import ShopProfileDialog from "./ShopProfileDialog";
import {
  COST_NAMES, PROCESS_LABEL, type Analysis, type Finding, type MatInfo, type MfgProject, type ProcessKey, type Severity,
  type ShopResp, type Tolerance,
} from "./types";

const BASE = "/api/m/manufacturing";
const SEV: Record<Severity, { label: string; icon: ReactNode; text: string; ring: string; bg: string }> = {
  critical: { label: "Critical", icon: <XCircle className="h-4 w-4" />, text: "text-danger", ring: "border-danger/40", bg: "bg-danger/10" },
  warning: { label: "Warnings", icon: <AlertTriangle className="h-4 w-4" />, text: "text-warning", ring: "border-warning/40", bg: "bg-warning/10" },
  info: { label: "Notes", icon: <Info className="h-4 w-4" />, text: "text-primary", ring: "border-primary/30", bg: "bg-primary-soft" },
};
const LEVELS = "Advice levels: Recommended check → Preliminary estimate → Verified calculation → Validated simulation. "
  + "Measurements here are deterministic; the limits are published guidance and your shop profile.";

function Level({ children }: { children: ReactNode }) {
  return <Tip content={LEVELS} side="bottom"><span className="inline-flex cursor-help items-center rounded-full border border-primary/25 bg-primary-soft px-2 py-0.5 text-[10.5px] font-semibold text-primary">{children}</span></Tip>;
}

async function download(path: string, filename: string | null) {
  const headers: Record<string, string> = {};
  try { const org = localStorage.getItem("fw_org"); if (org) headers["X-Org"] = org; } catch { /* ignore */ }
  const r = await fetch(path, { headers, credentials: "same-origin" });
  if (!r.ok) throw new ApiError(r.status, r.status === 404 ? "Run the analysis first" : `Report failed (${r.status})`);
  const url = URL.createObjectURL(await r.blob());
  if (filename) {
    const a = document.createElement("a"); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  } else window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/* ============================================================================ page */
export default function ManufacturingAdvisor({ projectId }: ModuleAppProps) {
  const [params, setParams] = useSearchParams();
  const pid = params.get("project") ?? projectId;
  const open = (id: string | null) => { const n = new URLSearchParams(params); if (id) n.set("project", id); else n.delete("project"); setParams(n, { replace: false }); };
  return pid ? <Workspace key={pid} pid={pid} onPick={open} /> : <Picker onPick={open} />;
}

function Header({ children, back }: { children?: ReactNode; back: ReactNode }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-panel px-3">
      {back}
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-soft text-primary"><Factory className="h-4 w-4" /></div>
        <span className="text-[14px] font-semibold tracking-tight">Manufacturing Advisor</span>
        <StatusBadge status="live" />
      </div>
      {children}
    </div>
  );
}

/* ============================================================================ project picker */
function Picker({ onPick }: { onPick: (id: string) => void }) {
  const q = useQuery({ queryKey: ["mfg-projects"], queryFn: () => api.get<{ items: MfgProject[] }>(`${BASE}/projects`) });
  return (
    <div className="flex h-full flex-col">
      <Header back={<Link to="/app/modules" className="rounded p-1 text-muted hover:bg-text/5 hover:text-text" aria-label="All modules"><ArrowLeft className="h-4 w-4" /></Link>} />
      <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-6">
        <h1 className="text-[20px] font-semibold tracking-tight">Choose a part to analyse</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">Design-for-manufacture checks run on the exact geometry of the latest verified build: internal radii, holes, walls,
          cavities, undercuts and setups, turning and moulding screens, a process shortlist and a relative cost estimate. All advice is advisory and checked against your shop profile.</p>
        {q.isLoading ? <PageLoader /> : !q.data?.items.length ? (
          <div className="mt-10"><EmptyState icon={<BoxIcon className="h-6 w-6" />} title="No projects yet" body="Create a part in the Design Studio, then come back to analyse it."
            action={<Link to="/app/projects" className="link text-sm">Go to projects</Link>} /></div>
        ) : (
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {q.data.items.map(p => (
              <button key={p.id} disabled={!p.built} onClick={() => onPick(p.id)} data-project={p.id}
                className="card group overflow-hidden text-left transition enabled:hover:-translate-y-0.5 enabled:hover:shadow-pop disabled:opacity-60">
                <div className="viewport-bg flex h-32 items-center justify-center border-b border-border">
                  {p.thumbnail ? <img src={p.thumbnail} alt="" className="h-full w-full object-contain" /> : <BoxIcon className="h-9 w-9 text-muted/40" />}
                </div>
                <div className="p-3">
                  <div className="truncate text-[13.5px] font-semibold">{p.name}</div>
                  <div className="mt-0.5 truncate text-[11.5px] text-muted">{p.material ?? "No material set"} · updated {ago(p.updated_at)}</div>
                  <div className="mt-2 flex items-center gap-1.5">
                    {!p.built ? <Badge>Not built yet</Badge> : p.counts ? <>
                      {p.counts.critical > 0 && <Badge tone="danger">{p.counts.critical} critical</Badge>}
                      {p.counts.warning > 0 && <Badge tone="warning">{p.counts.warning} warning{p.counts.warning > 1 ? "s" : ""}</Badge>}
                      {p.counts.critical + p.counts.warning === 0 && <Badge tone="success">No issues flagged</Badge>}
                    </> : <Badge tone="primary">Ready to analyse</Badge>}
                    <ChevronRight className="ml-auto h-4 w-4 text-muted transition group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================================================================ workspace */
function Workspace({ pid, onPick }: { pid: string; onPick: (id: string | null) => void }) {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["mfg-projects"], queryFn: () => api.get<{ items: MfgProject[] }>(`${BASE}/projects`) });
  const mats = useQuery({ queryKey: ["mfg-materials"], queryFn: () => api.get<{ items: MatInfo[]; version: string }>(`${BASE}/materials`), staleTime: 600_000 });
  const shop = useQuery({ queryKey: ["mfg-shop"], queryFn: () => api.get<ShopResp>(`${BASE}/shop-profile`) });
  const saved = useQuery({
    queryKey: ["mfg-analysis", pid], retry: false,
    queryFn: () => api.get<Analysis | null>(`${BASE}/projects/${pid}/analysis`),
  });
  const [a, setA] = useState<Analysis | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [qty, setQty] = useState(10);
  const [mat, setMat] = useState<string>("");
  const [tol, setTol] = useState<Tolerance>("general");
  const [sel, setSel] = useState<string | null>(null);
  const [hlOverride, setHlOverride] = useState<{ label: string; faces: number[] } | null>(null);
  const [proc, setProc] = useState<"all" | ProcessKey | null>(null);
  const [tool, setTool] = useState<Tool>("select");
  const [picks, setPicks] = useState<Pick[]>([]);
  const [shopOpen, setShopOpen] = useState(false);
  const [tab, setTab] = useState("process");
  const [costProc, setCostProc] = useState<string | null>(null);
  const auto = useRef(false);
  const canEdit = shop.data?.can_edit ?? false;
  const project = projects.data?.items.find(p => p.id === pid);

  const run = async (over?: { quantity?: number; material?: string; tolerance?: Tolerance }) => {
    setRunning(true); setErr(null);
    try {
      const body = { quantity: over?.quantity ?? qty, material: (over?.material ?? mat) || null, tolerance: over?.tolerance ?? tol };
      const r = await api.post<Analysis>(`${BASE}/projects/${pid}/analyse`, body);
      setA(r); setMat(r.material.code); qc.setQueryData(["mfg-analysis", pid], r); qc.invalidateQueries({ queryKey: ["mfg-projects"] });
    } catch (e) { const m = e instanceof ApiError ? e.message : "Analysis failed"; setErr(m); toast.error(m); }
    finally { setRunning(false); }
  };

  useEffect(() => {
    if (saved.isLoading || !shop.data) return;
    const s = saved.data;
    if (s && !a) { setA(s); setQty(s.inputs.quantity); setTol(s.inputs.tolerance); setMat(s.material.code); }
    if (!s && !auto.current && shop.data.can_edit && !saved.isError) { auto.current = true; void run(); }
  }, [saved.isLoading, saved.data, shop.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const top = a?.process.ranking.find(r => r.feasible)?.process;
  const procF: "all" | ProcessKey = proc ?? (top === "cnc_turning" ? "cnc_turning" : top === "casting" || top === "injection_moulding" ? "moulding_casting" : "cnc_milling");
  const facePick = picks.find(p => p.kind === "face") as Extract<Pick, { kind: "face" }> | undefined;
  const findings = useMemo(() => (a?.findings ?? []).filter(f => (procF === "all" || f.process === procF) && (!facePick || f.faces.includes(facePick.id))), [a, procF, facePick]);
  const selected = a?.findings.find(f => f.id === sel) ?? null;
  const hl = hlOverride?.faces ?? selected?.faces ?? [];
  const cur = a?.cost.currency ?? shop.data?.profile.currency ?? "USD";
  const procCount = (p: ProcessKey) => (a?.findings ?? []).filter(f => f.process === p && f.severity !== "info").length;

  const back = <Link to={`/app/projects/${pid}`} className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[12.5px] text-muted hover:bg-text/5 hover:text-text" title="Back to the Design Studio"><ArrowLeft className="h-4 w-4" />Studio</Link>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header back={back}>
        <div className="mx-1 h-6 w-px bg-border" />
        <select aria-label="Project" className="input h-8 w-60 text-[13px]" value={pid} onChange={e => onPick(e.target.value)}>
          {projects.data?.items.filter(p => p.built || p.id === pid).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          {!project && <option value={pid}>Loading…</option>}
        </select>
        <button onClick={() => onPick(null)} className="whitespace-nowrap text-[12px] text-muted hover:text-primary">All parts</button>
        <div className="ml-auto flex items-center gap-2">
          <ReportMenu pid={pid} name={project?.name ?? "part"} disabled={!a} />
          <Button size="sm" variant="secondary" icon={<Settings2 className="h-3.5 w-3.5" />} onClick={() => setShopOpen(true)} data-action="shop-profile">Shop profile</Button>
        </div>
      </Header>
      <div className="flex h-11 shrink-0 items-center gap-3 border-b border-border bg-panel2 px-3">
        <span className="label">Analysis inputs</span>
        <label className="flex items-center gap-1.5 text-[12px] text-muted">Material
          <select aria-label="Material" className="input h-8 w-52 text-[12.5px]" value={mat} onChange={e => { setMat(e.target.value); if (a) void run({ material: e.target.value }); }}>
            {!mat && <option value="">From the model</option>}
            {mats.data?.items.map(m => <option key={m.code} value={m.code}>{m.name}</option>)}
          </select></label>
        <label className="flex items-center gap-1.5 text-[12px] text-muted">Quantity
          <input aria-label="Quantity" type="number" min={1} max={1000000} className="input h-8 w-24 text-[12.5px] tabular-nums" value={qty}
            onChange={e => setQty(Math.max(1, Math.min(1_000_000, Math.round(Number(e.target.value) || 1))))}
            onKeyDown={e => { if (e.key === "Enter") void run(); }} /></label>
        <label className="flex items-center gap-1.5 text-[12px] text-muted">Tolerance
          <select aria-label="Tolerance class" className="input h-8 w-36 text-[12.5px]" value={tol} onChange={e => { const t = e.target.value as Tolerance; setTol(t); if (a) void run({ tolerance: t }); }}>
            <option value="general">General (±0.1)</option><option value="fine">Fine (±0.05)</option><option value="precision">Precision (±0.01)</option>
          </select></label>
        <Button size="sm" icon={a ? <RefreshCw className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} loading={running} disabled={!canEdit} onClick={() => run()} data-action="analyse"
          title={canEdit ? "Run the DFM analysis with these inputs" : "View access: you can open saved analyses"}>{a ? "Re-analyse" : "Analyse"}</Button>
        {a && <span className="ml-auto truncate text-[11.5px] text-muted">Analysed {ago(a.generated_at)} · {a.shop.name}</span>}
      </div>

      {a?.stale && <div className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-[12.5px]">
        <AlertTriangle className="h-4 w-4 text-warning" />The model has been rebuilt since this analysis.
        {canEdit && <button className="font-medium text-primary hover:underline" onClick={() => run()}>Re-analyse</button>}</div>}
      {shop.data?.is_default && a && <div className="flex items-center gap-2 border-b border-border bg-panel2 px-4 py-1.5 text-[12px] text-muted">
        <Info className="h-3.5 w-3.5" />Checked against an <b className="font-medium text-text">assumed default shop</b> (Ø{shop.data.profile.smallest_tool_d_mm} mm smallest tool, typical rates).
        {canEdit && <button className="font-medium text-primary hover:underline" onClick={() => setShopOpen(true)}>Enter your shop</button>}</div>}

      <div className="flex min-h-0 flex-1">
        {/* findings */}
        <aside className="flex w-[340px] shrink-0 flex-col border-r border-border bg-panel">
          <div className="border-b border-border px-3 pb-2 pt-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="text-[13px] font-semibold">DFM findings</span><span className="text-[11px] text-muted">CHK-13 · advisory</span></div>
              <Level>Recommended check</Level>
            </div>
            {a && <div className="mt-2 grid grid-cols-3 gap-1.5">
              {(["critical", "warning", "info"] as Severity[]).map(s => <div key={s} className={cx("rounded border px-2 py-1", SEV[s].ring, SEV[s].bg)}>
                <div className={cx("flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-wide", SEV[s].text)}>{SEV[s].icon}{SEV[s].label}</div>
                <div className="text-[17px] font-semibold tabular-nums leading-tight">{a.findings.filter(f => f.severity === s && (procF === "all" || f.process === procF)).length}</div></div>)}
            </div>}
            <div className="mt-2 flex flex-wrap gap-1">
              {(["all", "cnc_milling", "cnc_turning", "moulding_casting"] as const).map(p => {
                const n = p === "all" ? null : procCount(p);
                const na = p === "cnc_turning" && a && !a.signals.turning.turnable;
                return <button key={p} data-filter={p} onClick={() => setProc(p)} disabled={!!na} title={na ? "Not a rotational part" : undefined}
                  className={cx("rounded-full border px-2.5 py-0.5 text-[11.5px] transition disabled:opacity-40", procF === p ? "border-primary bg-primary-soft font-medium text-primary" : "border-border text-muted hover:text-text")}>
                  {p === "all" ? "All" : PROCESS_LABEL[p]}{n ? <span className="ml-1 tabular-nums">{n}</span> : null}</button>;
              })}
            </div>
            {facePick && <div className="mt-2 flex items-center gap-2 rounded border border-primary/30 bg-primary-soft px-2 py-1 text-[11.5px]">
              Showing findings on face #{facePick.id}<button aria-label="Clear face filter" className="ml-auto text-muted hover:text-text" onClick={() => setPicks([])}><X className="h-3.5 w-3.5" /></button></div>}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2" data-panel="findings">
            {!a ? <div className="flex h-40 flex-col items-center justify-center gap-2 text-[12.5px] text-muted">
              {running || saved.isLoading ? <><Loader2 className="h-5 w-5 animate-spin" />Analysing the exact geometry…</> : err ? <span className="px-4 text-center text-danger">{err}</span>
                : canEdit ? <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} onClick={() => run()}>Analyse this part</Button> : "No saved analysis yet."}
            </div> : !findings.length ? <div className="px-3 py-8 text-center text-[12.5px] text-muted"><CheckCircle2 className="mx-auto mb-2 h-6 w-6 text-success" />No findings for this filter.</div>
              : (["critical", "warning", "info"] as Severity[]).map(s => {
                const fs = findings.filter(f => f.severity === s);
                if (!fs.length) return null;
                return <div key={s} className="mb-2">
                  <div className={cx("sticky top-0 z-[1] flex items-center gap-1.5 bg-panel px-1 py-1 text-[11px] font-semibold uppercase tracking-wide", SEV[s].text)}>{SEV[s].icon}{SEV[s].label} · {fs.length}</div>
                  {fs.map(f => <FindingRow key={f.id} f={f} open={sel === f.id} onClick={() => { setHlOverride(null); setSel(sel === f.id ? null : f.id); }} />)}
                </div>;
              })}
          </div>
          {a && <div className="border-t border-border px-3 py-2 text-[10.5px] leading-snug text-muted">{a.disclaimer}</div>}
        </aside>

        {/* viewer */}
        <div className="relative min-w-0 flex-1">
          <Viewer3D topoUrl={`/api/projects/${pid}/files/topo.json`} version={a?.build.build_id ?? "0"} tool={tool} onToolChange={setTool}
            selection={picks} onSelectionChange={p => { setPicks(p); setSel(null); setHlOverride(null); }} selectKinds={["face"]} highlightFaces={hl}
            empty={<div className="text-sm text-muted">Loading the model…</div>} />
          {(selected || hlOverride) && <div className="pointer-events-auto absolute left-3 top-14 z-10 flex max-w-[60%] items-center gap-2 rounded-md border border-[#2fa36b]/50 bg-panel/95 px-3 py-1.5 text-[12px] shadow-pop backdrop-blur">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm bg-[#2fa36b]" />
            <span className="truncate"><b className="font-medium">{hlOverride?.label ?? `${selected!.id} · ${selected!.title}`}</b> <span className="text-muted">· {hl.length ? `${hl.length} face${hl.length > 1 ? "s" : ""} highlighted` : "whole part"}</span></span>
            <button aria-label="Clear highlight" className="text-muted hover:text-text" onClick={() => { setSel(null); setHlOverride(null); }}><X className="h-3.5 w-3.5" /></button>
          </div>}
          {a && <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-md border border-border bg-panel/90 px-3 py-2 text-[11.5px] shadow-card backdrop-blur">
            <div className="font-medium">{a.project.name}</div>
            <div className="text-muted tabular-nums">{a.part.bbox.map(v => +v.toFixed(2)).join(" × ")} mm · {a.part.mass_kg.toFixed(3)} kg · {a.material.name}</div>
            <div className="text-muted">{a.signals.setups.length} setup{a.signals.setups.length > 1 ? "s" : ""} ({a.signals.setups.join(", ")}){a.signals.turning.turnable ? ` · rotational about ${a.signals.turning.axis}` : ""}{a.signals.sheet.sheet_like ? ` · ${a.signals.sheet.thickness} mm sheet-like` : ""}</div>
          </div>}
          {running && a && <div className="absolute right-3 top-14 z-10 flex items-center gap-2 rounded-md border border-border bg-panel/95 px-3 py-1.5 text-[12px] shadow-pop"><Loader2 className="h-3.5 w-3.5 animate-spin" />Re-analysing…</div>}
        </div>

        {/* process / cost / report */}
        <aside className="flex w-[380px] shrink-0 flex-col border-l border-border bg-panel">
          <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
            <TabList className="px-2"><Tab value="process" compact>Process</Tab><Tab value="cost" compact>Cost</Tab><Tab value="report" compact>Checks &amp; report</Tab></TabList>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {!a ? <div className="p-6 text-center text-[12.5px] text-muted">{running ? "Working…" : "Run the analysis to see process options and costs."}</div> : <>
                <TabPanel value="process" className="p-3"><ProcessPanel a={a} cur={cur} /></TabPanel>
                <TabPanel value="cost" className="p-3"><CostPanel a={a} cur={cur} which={costProc ?? a.cost.primary} onWhich={setCostProc}
                  onHighlight={(label, faces) => { setSel(null); setHlOverride({ label, faces }); }} /></TabPanel>
                <TabPanel value="report" className="p-3"><ReportPanel a={a} pid={pid} name={project?.name ?? "part"} /></TabPanel>
              </>}
            </div>
          </Tabs>
        </aside>
      </div>

      <ShopProfileDialog open={shopOpen} onOpenChange={setShopOpen} shop={shop.data} materials={mats.data?.items ?? []}
        onSaved={s => { qc.setQueryData(["mfg-shop"], s); if (canEdit) void run(); }} />
    </div>
  );
}

/* ============================================================================ findings */
function FindingRow({ f, open, onClick }: { f: Finding; open: boolean; onClick: () => void }) {
  const s = SEV[f.severity];
  return (
    <div className={cx("mb-1 rounded-md border transition", open ? cx(s.ring, "bg-panel2 shadow-card") : "border-transparent hover:border-border hover:bg-panel2/60")} data-finding={f.rule}>
      <button className="flex w-full items-start gap-2 px-2 py-1.5 text-left" onClick={onClick} aria-expanded={open}>
        <span className={cx("mt-0.5 shrink-0", s.text)}>{s.icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-[12.5px] font-medium leading-snug">{f.title}</span>
          <span className="block truncate text-[11px] text-muted">{f.measured}</span>
        </span>
        <span className="mt-0.5 shrink-0 font-mono text-[10px] text-muted">{f.rule}</span>
      </button>
      {open && <div className="space-y-1.5 px-2 pb-2 pl-8 text-[11.5px] leading-snug">
        <div className="grid grid-cols-[62px_1fr] gap-x-2 gap-y-0.5">
          <span className="text-muted">Measured</span><span className="font-medium">{f.measured}</span>
          <span className="text-muted">Limit</span><span>{f.limit}</span>
          {f.features.length > 0 && <><span className="text-muted">Feature</span><span>{f.features.join(", ")}</span></>}
          <span className="text-muted">Faces</span><span className="text-muted">{f.faces.length ? `${f.faces.length} highlighted in the view` : "whole part"}</span>
        </div>
        <p className="text-text/90">{f.rationale}</p>
        <p><span className="font-medium">Suggested fix: </span>{f.fix}</p>
        <p className="text-[10.5px] text-muted">Source: {f.source} · {f.advice_level}</p>
      </div>}
    </div>
  );
}

/* ============================================================================ process */
function ProcessPanel({ a, cur }: { a: Analysis; cur: string }) {
  const [openP, setOpenP] = useState<string | null>(a.process.ranking[0]?.process ?? null);
  return (
    <div>
      <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-semibold">Process shortlist</span><Level>{a.process.advice_level}</Level></div>
      <p className="mb-3 text-[11.5px] text-muted">For {a.inputs.quantity.toLocaleString()} parts in {a.material.name}, {a.inputs.tolerance} tolerances. A starting point for a supplier conversation, not a decision.</p>
      <div className="space-y-1.5">
        {a.process.ranking.map((r, i) => {
          const open = openP === r.process;
          const tone = !r.feasible ? "neutral" : r.score >= 70 ? "success" : r.score >= 45 ? "primary" : "warning";
          return <div key={r.process} className={cx("rounded-md border border-border", !r.feasible && "opacity-60")} data-process={r.process}>
            <button className="flex w-full items-center gap-2 px-2.5 py-2 text-left" onClick={() => setOpenP(open ? null : r.process)}>
              <span className="w-4 text-[11px] font-semibold text-muted tabular-nums">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5"><span className="truncate text-[12.5px] font-semibold">{r.name}</span><Badge tone={tone as "success"}>{r.fit}</Badge></span>
                <span className="mt-1 flex items-center gap-2">
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-text/10"><span className="block h-full rounded-full bg-primary" style={{ width: `${r.score}%` }} /></span>
                  <span className="w-6 text-right text-[11px] tabular-nums text-muted">{r.score}</span>
                </span>
              </span>
            </button>
            {open && <div className="space-y-1.5 border-t border-border px-2.5 py-2 text-[11.5px]">
              <div className="flex items-center justify-between text-muted"><span>Confidence: <b className="font-medium text-text">{r.confidence}</b></span>
                {r.unit_cost != null && <span>≈ {money(r.unit_cost, cur)} / part <span className="text-[10px]">(estimate)</span></span>}</div>
              {r.pros.map(t => <div key={t} className="flex gap-1.5"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />{t}</div>)}
              {r.cons.map(t => <div key={t} className="flex gap-1.5">{r.feasible ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" /> : <CircleSlash className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />}{t}</div>)}
            </div>}
          </div>;
        })}
      </div>
      <ul className="mt-3 list-disc space-y-1 pl-4 text-[11px] text-muted">{a.process.assumptions.map(t => <li key={t}>{t}</li>)}</ul>
    </div>
  );
}

/* ============================================================================ cost */
function CostPanel({ a, cur, which, onWhich, onHighlight }: { a: Analysis; cur: string; which: string; onWhich: (p: string) => void;
  onHighlight: (label: string, faces: number[]) => void }) {
  const procs = a.cost.processes;
  const key = procs[which] ? which : a.cost.primary;
  const p = procs[key];
  const total = p ? p.breakdown.material + p.breakdown.machine_time + p.breakdown.setup_tooling : 0;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-semibold">Relative cost</span><Level>{a.cost.advice_level}</Level></div>
      <div className="mb-3 rounded border border-accent/30 bg-accent/5 px-2.5 py-1.5 text-[11.5px] font-medium text-accent">{a.cost.label}. Inputs and assumptions are listed below.</div>
      <div className="mb-2 flex flex-wrap gap-1">
        {Object.keys(procs).map(k => <button key={k} onClick={() => onWhich(k)}
          className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11.5px]", k === key ? "border-primary bg-primary-soft font-medium text-primary" : "border-border text-muted hover:text-text")}>
          <span className="h-2 w-2 rounded-full" style={{ background: seriesColor(k) }} />{COST_NAMES[k] ?? k}</button>)}
      </div>
      {p && <div className="rounded-md border border-border p-2.5">
        <div className="flex items-baseline justify-between">
          <div><div className="text-[11px] text-muted">Per part at {a.inputs.quantity.toLocaleString()} parts</div>
            <div className="text-[22px] font-semibold tabular-nums tracking-tight">{money(p.unit_cost, cur)}</div></div>
          <div className="text-right text-[11px] text-muted">Batch<div className="text-[13px] font-medium tabular-nums text-text">{money(p.batch_cost, cur, 0)}</div></div>
        </div>
        <div className="mt-2 space-y-1">
          {([["Material", p.breakdown.material], ["Machine time", p.breakdown.machine_time], ["Setup & tooling", p.breakdown.setup_tooling]] as [string, number][]).map(([l, v]) => (
            <div key={l} className="grid grid-cols-[1fr_70px_36px] items-center gap-2 text-[11.5px]">
              <span className="flex items-center gap-2"><span className="w-[118px] shrink-0 truncate text-muted">{l}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-text/10"><span className="block h-full rounded-full bg-primary" style={{ width: `${total ? (100 * v) / total : 0}%` }} /></span></span>
              <span className="text-right tabular-nums">{money(v, cur)}</span><span className="text-right tabular-nums text-muted">{total ? Math.round((100 * v) / total) : 0}%</span>
            </div>))}
        </div>
      </div>}
      <div className="mt-3"><CostChart procs={procs} quantities={a.cost.quantities} quantity={a.inputs.quantity} currency={cur} /></div>
      <div className="mt-4 mb-1.5 text-[12.5px] font-semibold">Cost drivers and suggestions</div>
      {!a.drivers.length ? <p className="text-[11.5px] text-muted">No significant cost drivers flagged for these inputs.</p> : <div className="space-y-1.5">
        {a.drivers.map(d => <button key={d.title} disabled={!d.faces.length} onClick={() => onHighlight(d.title, d.faces)} data-driver
          className="block w-full rounded-md border border-border px-2.5 py-2 text-left transition enabled:hover:border-primary/50 enabled:hover:bg-primary-soft/40">
          <div className="flex items-start justify-between gap-2"><span className="text-[12px] font-medium leading-snug">{d.title}</span>
            {d.saving_per_unit != null && <Badge tone="success">≈ −{money(d.saving_per_unit, cur)}</Badge>}</div>
          <p className="mt-0.5 text-[11.5px] leading-snug text-muted">{d.rationale}</p>
          {d.faces.length > 0 && <p className="mt-1 text-[10.5px] font-medium text-primary">Show {d.faces.length} face{d.faces.length > 1 ? "s" : ""} in the view</p>}
        </button>)}
      </div>}
      {p && <div className="mt-4 rounded-md bg-panel2 p-2.5 text-[11px] text-muted">
        <div className="mb-1 font-semibold text-text">Assumptions ({COST_NAMES[key] ?? key})</div>
        <ul className="list-disc space-y-0.5 pl-4">{p.notes.map(n => <li key={n}>{n}</li>)}
          <li>Material {a.material.name}: {a.material.price_used} {cur}/kg ({a.material.provenance.price_per_kg})</li></ul>
      </div>}
    </div>
  );
}

/* ============================================================================ report */
function ReportMenu({ pid, name, disabled }: { pid: string; name: string; disabled: boolean }) {
  const [busy, setBusy] = useState(false);
  const go = async (kind: "html" | "pdf") => {
    setBusy(true);
    try { await download(`${BASE}/projects/${pid}/report.${kind}`, kind === "pdf" ? `${name.replace(/[^\w.-]+/g, "_")}_dfm.pdf` : null); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Report failed"); } finally { setBusy(false); }
  };
  return (
    <Menu>
      <MenuTriggerButton disabled={disabled} busy={busy} />
      <MenuContent>
        <MenuItem icon={<FileText className="h-4 w-4" />} onSelect={() => go("html")}>Open printable report (HTML)</MenuItem>
        <MenuItem icon={<Download className="h-4 w-4" />} onSelect={() => go("pdf")}>Download PDF</MenuItem>
      </MenuContent>
    </Menu>
  );
}

function MenuTriggerButton({ disabled, busy }: { disabled: boolean; busy: boolean }) {
  return <MenuTrigger asChild><Button size="sm" variant="secondary" disabled={disabled} loading={busy} icon={<FileText className="h-3.5 w-3.5" />} data-action="report">Report</Button></MenuTrigger>;
}

function ReportPanel({ a, pid, name }: { a: Analysis; pid: string; name: string }) {
  const [busy, setBusy] = useState<string | null>(null);
  const go = async (kind: "html" | "pdf") => {
    setBusy(kind);
    try { await download(`${BASE}/projects/${pid}/report.${kind}`, kind === "pdf" ? `${name.replace(/[^\w.-]+/g, "_")}_dfm.pdf` : null); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Report failed"); } finally { setBusy(null); }
  };
  const groups = (Object.keys(PROCESS_LABEL) as ProcessKey[]).map(p => [p, a.chk13.rules.filter(r => r.process === p)] as const);
  return (
    <div>
      <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-semibold">Manufacturability report</span><Level>Recommended check</Level></div>
      <p className="mb-2 text-[11.5px] text-muted">Findings with highlighted views, process shortlist, relative cost and the assumptions behind them. Marked “not approved for manufacture”.</p>
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" loading={busy === "html"} icon={<FileText className="h-3.5 w-3.5" />} onClick={() => go("html")}>Printable (HTML)</Button>
        <Button size="sm" loading={busy === "pdf"} icon={<Download className="h-3.5 w-3.5" />} onClick={() => go("pdf")}>Download PDF</Button>
      </div>
      <div className="mt-4 mb-1 flex items-center justify-between text-[12.5px] font-semibold">CHK-13 rules <span className="text-[11px] font-normal text-muted">advisory, not a gate</span></div>
      {groups.map(([p, rows]) => <div key={p} className="mb-2">
        <div className="label mb-1 mt-2">{PROCESS_LABEL[p]}</div>
        <table className="w-full text-[11.5px]"><tbody>
          {rows.map(r => <tr key={r.rule} className="border-t border-border">
            <td className="whitespace-nowrap py-1 pr-2 font-mono text-[10px] text-muted">{r.rule}</td>
            <td className="py-1 pr-2">{r.name}</td>
            <td className="py-1 text-right">{r.status === "pass" ? <span className="inline-flex items-center gap-1 text-success"><CheckCircle2 className="h-3.5 w-3.5" />Pass</span>
              : r.status === "flagged" ? <span className={cx("inline-flex items-center gap-1", r.worst === "critical" ? "text-danger" : "text-warning")}>{r.worst === "critical" ? <XCircle className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}Flagged</span>
                : <span className="text-muted">n/a</span>}</td>
          </tr>)}
        </tbody></table>
      </div>)}
      <div className="mt-3 rounded-md bg-panel2 p-2.5 text-[11px] text-muted">
        <div><b className="font-medium text-text">Part:</b> {a.part.bbox.map(v => +v.toFixed(2)).join(" × ")} mm, {a.part.volume_mm3.toLocaleString(undefined, { maximumFractionDigits: 0 })} mm³, {a.part.faces} faces</div>
        <div><b className="font-medium text-text">Material:</b> {a.material.name} ({a.material.how}); {a.material.library_version}</div>
        <div><b className="font-medium text-text">Shop:</b> {a.shop.name}</div>
        <div><b className="font-medium text-text">Analyser:</b> {a.analyser}; {a.tables}</div>
      </div>
    </div>
  );
}
