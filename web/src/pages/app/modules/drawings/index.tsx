import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Box, CheckCircle2, ChevronDown, Download, Eye, EyeOff, FileDown, FileWarning, History, Info,
  Lock, Plus, RefreshCw, Ruler, ShieldAlert, ShieldCheck, X, XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Input, Menu, MenuContent, MenuItem, MenuTrigger, PageLoader, Tab, TabList, TabPanel, Tabs, Tip, Toggle } from "@/components/ui";
import type { ModuleAppProps } from "../registry";
import SheetViewer from "./SheetViewer";
import AnnotatePanel, { type ViewPoint } from "./AnnotatePanel";
import { saveNative } from "@/components/NativeExport";
import { ModuleHeader, PartCard } from "../ModuleHeader";
import DraftEditor from "./draft/DraftEditor";
import { createProject } from "@/components/NewProjectDialog";
import { fileToB64 } from "@/components/StartBox";
import { DraftStrip } from "./draft/DraftHome";
import { DEFAULT_OPTIONS, EMPTY_EDITS, localStamp, type DrawingEdits, type DrawingOptions, type DrawingProject, type DrawingRecord, type DrawingState } from "./types";

const BASE = "/api/m/drawings";

async function fetchText(url: string): Promise<string> {
  const headers: Record<string, string> = {};
  try { const org = localStorage.getItem("fw_org"); if (org) headers["X-Org"] = org; } catch { /* storage unavailable */ }
  const r = await fetch(url, { credentials: "same-origin", headers, cache: "no-store" });
  if (!r.ok) throw new ApiError(r.status, `Could not load the sheet (${r.status})`);
  return r.text();
}

export default function DrawingStudio({ projectId }: ModuleAppProps) {
  const [params, setParams] = useSearchParams();
  const pid = params.get("project") ?? projectId;
  const draft = params.get("draft");
  if (draft) return <DraftEditor id={draft} onBack={() => setParams({})} />;
  if (!pid) return <ProjectPicker onPick={id => setParams({ project: id })} onDraft={id => setParams({ draft: id })} />;
  return <Workspace key={pid} pid={pid} onBack={() => setParams({})} onSwitch={id => setParams({ project: id })} />;
}

/* ------------------------------------------------------------------ project picker */
function ProjectPicker({ onPick, onDraft }: { onPick: (id: string) => void; onDraft: (id: string) => void }) {
  const q = useQuery({ queryKey: ["drw-projects"], queryFn: () => api.get<{ items: DrawingProject[] }>(`${BASE}/projects`) });
  if (q.isLoading) return <PageLoader />;
  if (q.error) return <div className="p-10 text-center text-sm text-muted">{(q.error as Error).message}</div>;
  const items = [...(q.data?.items ?? [])].sort((a, b) => Number(b.verified) - Number(a.verified));
  return (
    <div>
    <ModuleHeader code="drawings" icon={<Ruler className="h-4 w-4" />} title="Drawing Studio" projectId={null} />
    <div className="mx-auto max-w-7xl px-6 py-6">
      <DraftStrip onOpen={onDraft} />
      <h2 className="text-[20px] font-semibold tracking-tight">Choose a part to draw</h2>
      <p className="mb-5 mt-1 text-sm text-muted">The sheet is made from the part's latest verified model.</p>
      <StepToDrawing onDone={onPick} existing={items.map(p => p.name)} />
      <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-panel p-3.5 text-[13px] text-muted">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div>Views are exact hidden-line projections of your model. Dimensions are tagged <b className="text-[#0b3d91]">spec</b> when they equal a declared model parameter and <i className="text-[#9a3412]">inferred</i> when measured from the geometry. Every sheet is consistency-checked and stamped <b>NOT APPROVED FOR MANUFACTURE</b>: an engineer must review it.</div>
      </div>
      {items.length === 0 ? (
        <EmptyState icon={<Box className="h-5 w-5" />} title="No projects yet" body="Create and build a part in the Design Studio, then come back to draw it."
          action={<Link to="/app/projects"><Button>Go to projects</Button></Link>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(p => <PartCard key={p.id} id={p.id} name={p.name} thumbnail={p.thumbnail} sub={p.material ?? "Material not set"} updatedAt={p.updated_at}
            status={<DrawingBadge p={p} />} disabled={!p.verified} onPick={onPick} />)}
        </div>
      )}
    </div>
    </div>
  );
}

/** DRW-016: a STEP file straight to a drawing. The file becomes a part (exact import + feature recognition), then
 *  its sheet opens; every dimension on it is inferred from the imported geometry and labelled so. */
function StepToDrawing({ onDone, existing }: { onDone: (id: string) => void; existing: string[] }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const run = async (f: File) => {
    if (f.size > 50 * 1024 * 1024) { toast.error("STEP files up to 50 MB are supported"); return; }
    setBusy(true);
    try {
      let name = f.name.replace(/\.(step|stp)$/i, "").slice(0, 80) || "Imported part";
      for (let n = 2; existing.includes(name); n++) name = `${f.name.replace(/\.(step|stp)$/i, "").slice(0, 70)} (${n})`;
      const p = await createProject(name, null, `Imported from ${f.name} for a drawing`);
      await api.post(`/api/projects/${p.id}/import-step`, { filename: f.name, data_b64: await fileToB64(f) });
      onDone(p.id);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "The STEP file could not be imported"); }
    finally { setBusy(false); }
  };
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-primary/40 bg-primary-soft/30 p-3.5 text-[13px]" data-testid="step-to-drawing">
      <FileDown className="h-5 w-5 shrink-0 text-primary" />
      <div className="min-w-0 flex-1"><b>Drawing from a STEP file.</b> <span className="text-muted">Import a supplier or legacy part and get its sheet: views, hole callouts and sizes measured from the exact geometry, all marked <i>inferred</i> for you to verify.</span></div>
      <input ref={ref} type="file" accept=".step,.stp" className="hidden" aria-label="STEP file" onChange={ev => { const f = ev.target.files?.[0]; ev.target.value = ""; if (f) void run(f); }} />
      <Button size="sm" loading={busy} onClick={() => ref.current?.click()}>{busy ? "Importing…" : "Choose STEP file"}</Button>
    </div>
  );
}

function DrawingBadge({ p }: { p: DrawingProject }) {
  if (!p.verified) return <Badge><Lock className="h-3 w-3" />No verified build</Badge>;
  if (!p.drawing) return <Badge tone="primary">No drawing yet</Badge>;
  if (p.drawing.stale) return <Badge tone="warning"><AlertTriangle className="h-3 w-3" />Model changed</Badge>;
  const rev = p.drawing.sheet_rev && p.drawing.sheet_rev !== "DRAFT" ? `Rev ${p.drawing.sheet_rev}` : "Draft";
  return <Badge tone={p.drawing.chk12 ? "success" : "danger"}>{p.drawing.chk12 ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}{rev} · {p.drawing.sheet} {p.drawing.scale}</Badge>;
}

/* ------------------------------------------------------------------ workspace */
function Segmented<T extends string>({ value, options, onChange, disabled }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; disabled?: boolean;
}) {
  return (
    <div className="flex rounded-md border border-border bg-panel2 p-0.5">
      {options.map(o => (
        <button key={o.value} type="button" title={o.title} disabled={disabled} onClick={() => onChange(o.value)}
          className={cx("flex-1 rounded px-2 py-1 text-[12.5px] transition disabled:cursor-not-allowed disabled:opacity-60",
            value === o.value ? "bg-panel font-medium text-text shadow-sm" : "text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Section({ title, children, hint }: { title: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="space-y-2 border-b border-border px-4 py-3.5">
      <div className="label">{title}</div>
      {children}
      {hint && <p className="text-[11.5px] leading-snug text-muted">{hint}</p>}
    </div>
  );
}

const VIEW_LABELS: Record<string, string> = { front: "Front", top: "Top", right: "Right", iso: "Isometric" };

/** Update / regenerate and the downloads. Kept as one element so a shared module header can host it. */
export function DrawingActions({ pid, rec, canEdit, verified, stale, busy, onRegenerate }: {
  pid: string; rec: DrawingRecord | null; canEdit: boolean; verified: boolean; stale: boolean; busy: boolean; onRegenerate: () => void;
}) {
  const file = (n: string, copy?: "review") => `${BASE}/projects/${pid}/files/${n}?download=1${copy ? `&copy=${copy}` : ""}`;
  return (
    <div className="flex items-center gap-1.5" data-testid="drawing-actions">
      {canEdit && <Button size="sm" variant={stale ? "primary" : "secondary"} loading={busy} disabled={!verified} icon={<RefreshCw className="h-3.5 w-3.5" />}
        onClick={onRegenerate} data-testid="regenerate">{stale ? "Update drawing" : "Regenerate"}</Button>}
      {rec && <>
        <Tip content="Issue copy: monochrome, no tag legend" side="bottom">
          <a href={file("sheet.pdf")} data-download="pdf" className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-panel px-2.5 text-[12.5px] font-medium hover:bg-panel2">
            <Download className="h-3.5 w-3.5" />PDF</a>
        </Tip>
        <Tip content="DXF: geometry at true size in model space, the sheet in a paper-space layout" side="bottom">
          <a href={file("sheet.dxf")} data-download="dxf" className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-panel px-2.5 text-[12.5px] font-medium hover:bg-panel2">
            <Download className="h-3.5 w-3.5" />DXF</a>
        </Tip>
        <Menu>
          <MenuTrigger asChild><button type="button" aria-label="More downloads" className="inline-flex h-8 items-center rounded border border-border bg-panel px-1.5 text-muted hover:bg-panel2 hover:text-text"><ChevronDown className="h-3.5 w-3.5" /></button></MenuTrigger>
          <MenuContent>
            <MenuItem icon={<Download />} onSelect={() => { location.href = file("sheet.svg"); }}>SVG (issue copy)</MenuItem>
            <MenuItem icon={<Eye />} onSelect={() => { location.href = file("sheet.pdf", "review"); }}>Review copy PDF (tags and legend)</MenuItem>
            {rec.flat_pattern && <MenuItem icon={<Download />} onSelect={() => { location.href = file("flat.pdf"); }}>Flat pattern sheet PDF</MenuItem>}
            {rec.flat_pattern && <MenuItem icon={<Download />} onSelect={() => { location.href = file("flat.dxf"); }}>Flat pattern sheet DXF</MenuItem>}
            <MenuItem icon={<FileDown />} onSelect={() => { void saveNative(`/api/native/drawings/${pid}/export`, "drawing.fwdrw", "fwdrw"); }}>Formwright drawing (.fwdrw) with its model</MenuItem>
          </MenuContent>
        </Menu>
      </>}
    </div>
  );
}

function Workspace({ pid, onBack, onSwitch }: { pid: string; onBack: () => void; onSwitch: (id: string) => void }) {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["drw-projects"], queryFn: () => api.get<{ items: DrawingProject[] }>(`${BASE}/projects`) });
  const q = useQuery({ queryKey: ["drw", pid], queryFn: () => api.get<DrawingState>(`${BASE}/projects/${pid}`) });
  const st = q.data;
  const rec = st?.drawing ?? null;
  const [opts, setOpts] = useState<DrawingOptions>(DEFAULT_OPTIONS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [customTol, setCustomTol] = useState("");
  const [locate, setLocate] = useState<{ id: string; n: number } | null>(null);
  const [pick, setPick] = useState<{ hint: string; cb: (p: ViewPoint) => void } | null>(null);
  useEffect(() => {
    if (!pick) return;
    const h = (ev: KeyboardEvent) => { if (ev.key === "Escape") setPick(null); };
    addEventListener("keydown", h);
    return () => removeEventListener("keydown", h);
  }, [pick]);
  const inited = useRef(false);
  const autoRan = useRef(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!st || inited.current) return;
    inited.current = true;
    if (st.drawing) { setOpts({ ...DEFAULT_OPTIONS, ...st.drawing.options }); setCustomTol(st.drawing.options.tolerance.text ?? ""); }
  }, [st]);

  const done = useCallback((r: DrawingState, reason?: string) => {
    qc.setQueryData(["drw", pid], r);
    qc.invalidateQueries({ queryKey: ["drw-projects"] });
    qc.invalidateQueries({ queryKey: ["deliverables", pid] });
    setNonce(n => n + 1);
    if (reason) toast.success(reason);
  }, [pid, qc]);

  const generate = useCallback(async (o: DrawingOptions, reason?: string) => {
    setBusy(true);
    setError(null);
    try {
      done(await api.post<DrawingState>(`${BASE}/projects/${pid}/generate`, { ...o, ...localStamp() }), reason);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The drawing could not be generated.");
    } finally { setBusy(false); }
  }, [pid, done]);

  const saveEdits = useCallback(async (next: DrawingEdits) => {
    setBusy(true);
    setError(null);
    try {
      done(await api.post<DrawingState>(`${BASE}/projects/${pid}/edits`, { ...next, ...localStamp() }));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "The edit could not be saved.");
    } finally { setBusy(false); }
  }, [pid, done]);

  // first open: draw it. A changed model is never redrawn silently: the user updates it (one rule in every module).
  useEffect(() => {
    if (!st || autoRan.current || !st.can_edit || !st.project.verified || st.drawing) return;
    autoRan.current = true;
    void generate(DEFAULT_OPTIONS);
  }, [st, generate]);

  const change = (patch: Partial<DrawingOptions>) => {
    const next = { ...opts, ...patch };
    setOpts(next);
    if (!st?.can_edit) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void generate(next), 250);
  };

  const [sheetNo, setSheetNo] = useState<"views" | "flat">("views"); // sheet metal: the flat-pattern sheet
  const showFlat = sheetNo === "flat" && !!rec?.flat_pattern;
  const svgQ = useQuery({
    queryKey: ["drw-svg", pid, rec?.build_id, nonce, showFlat],
    queryFn: () => fetchText(`${BASE}/projects/${pid}/files/${showFlat ? "flat.svg" : "sheet.svg"}`),
    enabled: !!rec,
    staleTime: Infinity,
  });

  if (q.isLoading) return <PageLoader />;
  if (q.error || !st) {
    return <div className="mx-auto max-w-xl p-10 text-center">
      <p className="text-sm text-muted">{(q.error as Error)?.message ?? "Not found"}</p>
      <Button className="mt-4" variant="secondary" icon={<ArrowLeft className="h-4 w-4" />} onClick={onBack}>All projects</Button>
    </div>;
  }
  const chk = rec?.check;
  const edits = st.edits ?? rec?.edits ?? EMPTY_EDITS;
  const counts = { spec: 0, inferred: 0, ref: 0 };
  rec?.dimensions.forEach(d => { if (d.hidden) return; if (d.aux) counts.ref++; else counts[d.tag]++; });
  rec?.callouts.forEach(c => { if (!c.hidden) c.lines.forEach(l => counts[l.tag]++); });
  const canEdit = st.can_edit && st.project.verified;

  return (
    <div className="flex h-full flex-col">
      <ModuleHeader code="drawings" icon={<Ruler className="h-4 w-4" />} title="Drawing Studio" projectId={pid} projectName={st.project.name}
        projects={projects.data?.items.map(p => ({ id: p.id, name: p.name, disabled: !p.verified }))} onSwitch={id => id ? onSwitch(id) : onBack()}
        actions={<DrawingActions pid={pid} rec={rec} canEdit={st.can_edit} verified={st.project.verified} stale={st.stale} busy={busy}
            onRegenerate={() => void generate(opts, st.stale ? `Drawing updated to model rev ${st.current_rev ?? "—"}` : "Drawing regenerated from the latest build")} />}>
        {rec && <div className="flex items-center gap-1.5" data-testid="drawing-toolbar">
          <Badge className="whitespace-nowrap">{rec.sheet.size} · {rec.sheet.scale}</Badge>
          {chk && <CheckBadge chk={chk} />}
        </div>}
      </ModuleHeader>
      {st.stale && rec && !busy && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-[12.5px]" data-testid="stale-banner">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
          <span>Model changed since this sheet (model rev {st.made_from_rev ?? rec.model_rev ?? "—"} → {st.current_rev ?? "—"}). The sheet still shows the earlier model.</span>
          {st.can_edit && <button className="link ml-1 font-medium" onClick={() => void generate(opts, `Drawing updated to model rev ${st.current_rev ?? "—"}`)}>Update drawing</button>}
        </div>
      )}
      {rec?.imported && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-[12.5px]" data-testid="inferred-banner">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
          <span><b>Dimensions inferred from imported geometry — verify.</b> This part came from a STEP file, so no value on the sheet is a design intent{rec.imported.component ? ` (recognised as ${rec.imported.component})` : ""}{rec.imported.unrecognised_faces ? `; ${rec.imported.unrecognised_faces} face(s) were not recognised and are drawn but not dimensioned` : ""}.</span>
        </div>
      )}
      {st.release && !st.stale && (
        <div className={cx("flex items-center gap-2 border-b px-4 py-1.5 text-[12.5px]", st.release.current ? "border-success/25 bg-success/5" : "border-border bg-panel2 text-muted")}>
          {st.release.current ? <><ShieldCheck className="h-4 w-4 text-success" />Issued as Rev {st.release.rev} on {st.release.date}{st.release.by ? ` by ${st.release.by}` : ""}. Downloads are the issued revision.</>
            : <><Info className="h-4 w-4" />Draft: changes since Rev {st.release.rev} ({st.release.date}) are not issued.</>}
        </div>
      )}
      {(!st.can_edit || error || !st.project.verified || rec?.plan?.note || rec?.sheet.iso_dropped) && (
        <div className={cx("flex items-center gap-2 border-b px-4 py-2 text-[12.5px]", error ? "border-danger/25 bg-danger/5 text-danger" : "border-border bg-panel2 text-muted")}>
          {error ? <><FileWarning className="h-4 w-4" />{error}</>
            : !st.project.verified ? <><Lock className="h-4 w-4" />This project has no verified build. <Link to={`/app/projects/${pid}`} className="link">Build it in the Design Studio</Link> first.</>
            : !st.can_edit ? <><Info className="h-4 w-4" />You have view-only access: you can open and download drawings but not change them.</>
            : <><Info className="h-4 w-4" />{[rec?.plan?.note, rec?.sheet.iso_dropped ? `The isometric view is left out so the views can stay at ${rec.sheet.scale}. Choose A3 to show it.` : null].filter(Boolean).join(" ")}</>}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {/* side panel */}
        <aside className="flex w-[320px] shrink-0 flex-col border-r border-border bg-panel">
          <Tabs defaultValue="sheet" className="flex min-h-0 flex-1 flex-col">
            <TabList className="px-2"><Tab value="sheet" compact>Sheet</Tab><Tab value="dims" compact>Dimensions</Tab><Tab value="annot" compact>Annotate</Tab><Tab value="title" compact>Notes</Tab><Tab value="check" compact>Check</Tab><Tab value="rev" compact>History</Tab></TabList>
            <TabPanel value="sheet" className="min-h-0 flex-1 overflow-y-auto">
              <OptionsPanel opts={opts} change={change} disabled={!canEdit} customTol={customTol} setCustomTol={setCustomTol} rec={rec} />
              <div className="px-4 py-3.5"><Legend counts={counts} /></div>
            </TabPanel>
            <TabPanel value="dims" className="min-h-0 flex-1 overflow-y-auto">{rec ? <DimsPanel rec={rec} edits={edits} disabled={!canEdit || busy} onSave={saveEdits} onLocate={id => setLocate(l => ({ id, n: (l?.n ?? 0) + 1 }))} /> : <Empty />}</TabPanel>
            <TabPanel value="annot" className="min-h-0 flex-1 overflow-y-auto">{rec ? <AnnotatePanel rec={rec} edits={edits} disabled={!canEdit || busy} onSave={saveEdits}
              requestPick={(hint, cb) => setPick({ hint, cb })} /> : <Empty />}</TabPanel>
            <TabPanel value="title" className="min-h-0 flex-1 overflow-y-auto">{rec ? <TitlePanel rec={rec} edits={edits} disabled={!canEdit || busy} onSave={saveEdits} /> : <Empty />}</TabPanel>
            <TabPanel value="check" className="min-h-0 flex-1 overflow-y-auto">{rec ? <CheckPanel rec={rec} /> : <Empty />}</TabPanel>
            <TabPanel value="rev" className="min-h-0 flex-1 overflow-y-auto">{rec ? <RevPanel rec={rec} /> : <Empty />}</TabPanel>
          </Tabs>
        </aside>
        {/* sheet */}
        <div className="relative min-w-0 flex-1">
          {rec && svgQ.data ? <SheetViewer svg={svgQ.data} widthMm={rec.sheet.w} heightMm={rec.sheet.h} busy={busy} highlight={locate}
              pickHint={pick && !showFlat ? `${pick.hint} · Esc to cancel` : undefined}
              onPick={pick && !showFlat ? (x, y) => {
                const p = sheetToView(rec, x, y);
                if (!p) { toast.error("Click inside the front, top, right or section view."); return; }
                const cb = pick.cb; setPick(null); cb(p);
              } : undefined} />
            : <div className="flex h-full items-center justify-center bg-[#e9edf2] text-sm text-muted dark:bg-[#1b2027]">
                {busy || svgQ.isLoading ? <span className="inline-flex items-center gap-2"><RefreshCw className="h-4 w-4 animate-spin" />Generating views from the verified model…</span>
                  : st.project.verified ? "No drawing yet." : "Nothing to draw yet."}
              </div>}
          {rec?.flat_pattern && <div className="absolute left-3 top-3 z-10 inline-flex overflow-hidden rounded border border-border bg-panel text-[12px] shadow-card" data-sheet-switch>
            <button onClick={() => setSheetNo("views")} className={cx("px-2.5 py-1", !showFlat ? "bg-primary text-white" : "text-muted hover:bg-panel2")}>Sheet 1 · Views</button>
            <button onClick={() => setSheetNo("flat")} className={cx("px-2.5 py-1", showFlat ? "bg-primary text-white" : "text-muted hover:bg-panel2")} data-flat-sheet>Sheet 2 · Flat pattern ({rec.flat_pattern.bends} bend{rec.flat_pattern.bends === 1 ? "" : "s"})</button>
          </div>}
          {busy && rec && <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-full border border-border bg-panel px-3 py-1 text-[12px] text-muted shadow-card"><span className="inline-flex items-center gap-1.5"><RefreshCw className="h-3.5 w-3.5 animate-spin" />Regenerating…</span></div>}
        </div>
      </div>
    </div>
  );
}

/** A click on the sheet (paper mm) as a point of the view under it, in that view's model coordinates. */
function sheetToView(rec: DrawingRecord, x: number, y: number): ViewPoint | null {
  for (const [view, v] of Object.entries(rec.sheet.views ?? {})) {
    const [x0, y0, x1, y1] = v.rect as [number, number, number, number];
    const pad = 2;
    if (x < x0 - pad || x > x1 + pad || y < y0 - pad || y > y1 + pad) continue;
    return { view, u: +(v.origin[0]! + (x - x0) / v.scale).toFixed(3), v: +(v.origin[1]! - (y - y0) / v.scale).toFixed(3) };
  }
  return null;
}

function Empty() {
  return <p className="p-4 text-sm text-muted">Generate the drawing first.</p>;
}

function CheckBadge({ chk }: { chk: DrawingRecord["check"] }) {
  return (
    <Tip side="bottom" content={chk.passed ? "CHK-12 drawing consistency passed: tags, spec parameters, view extents vs model, each value against its own span, no text overlaps, hole callouts vs census." : chk.problems.join(" · ")}>
      <span data-testid="chk12">
        <Badge tone={chk.passed ? "success" : "danger"} className="whitespace-nowrap">{chk.passed ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}CHK-12 {chk.passed ? "passed" : "failed"}</Badge>
      </span>
    </Tip>
  );
}

function Legend({ counts }: { counts: { spec: number; inferred: number; ref: number } }) {
  return (
    <div className="space-y-2" data-testid="legend">
      <div className="label">Dimension tags (review copy)</div>
      <div className="flex items-baseline gap-2.5 text-[12.5px]"><span className="w-10 font-medium text-[#0b3d91] dark:text-[#7fa6ef]">120</span><span><b>Spec</b> · equals a declared model parameter</span><span className="ml-auto tabular-nums text-muted">{counts.spec}</span></div>
      <div className="flex items-baseline gap-2.5 text-[12.5px]"><span className="w-10 font-medium italic text-[#9a3412] dark:text-[#f0a46b]">120</span><span><b>Inferred</b> · measured from the geometry</span><span className="ml-auto tabular-nums text-muted">{counts.inferred}</span></div>
      <div className="flex items-baseline gap-2.5 text-[12.5px]"><span className="w-10 italic text-[#9a3412] dark:text-[#f0a46b]">(40)</span><span><b>Reference</b> · for information only</span><span className="ml-auto tabular-nums text-muted">{counts.ref}</span></div>
      <p className="text-[11.5px] text-muted">The PDF, SVG and DXF downloads are the issue copy: monochrome, without these tags.</p>
    </div>
  );
}

function OptionsPanel({ opts, change, disabled, customTol, setCustomTol, rec }: {
  opts: DrawingOptions; change: (p: Partial<DrawingOptions>) => void; disabled: boolean; customTol: string; setCustomTol: (s: string) => void;
  rec: DrawingRecord | null;
}) {
  const [customOpen, setCustomOpen] = useState(opts.tolerance.mode === "custom");
  const tolValue = customOpen ? "custom" : opts.tolerance.mode === "iso2768" ? `iso-${opts.tolerance.class}` : opts.tolerance.mode;
  const turned = !!rec?.plan?.turned;
  const shown = opts.views ?? rec?.plan?.views ?? ["front", "top", "right", "iso"];
  const setView = (v: string, on: boolean) => {
    const set = new Set(shown);
    if (on) set.add(v); else set.delete(v);
    change({ views: ["front", "top", "right", "iso"].filter(x => set.has(x)) });
  };
  const sec = opts.section;
  const turnedSec = sec === "auto" ? "auto" : sec === null ? "off" : sec === "x" || sec === "cross" ? "cross" : "axial";
  return (
    <div>
      <Section title="Sheet">
        <Segmented value={opts.sheet} disabled={disabled} onChange={v => change({ sheet: v })}
          options={[{ value: "A3", label: "A3 landscape" }, { value: "A4", label: "A4 landscape" }]} />
        <p className="text-[11.5px] text-muted">Scale is picked automatically from ISO 5455 ratios (1:1, 1:2, 2:1 …) to fit the sheet.</p>
      </Section>
      <Section title="Projection" hint="First angle is the ISO default (Europe); third angle is common in North America.">
        <Segmented value={opts.projection} disabled={disabled} onChange={v => change({ projection: v })}
          options={[{ value: "first", label: "First angle", title: "ISO method E" }, { value: "third", label: "Third angle", title: "ISO method A" }]} />
      </Section>
      <Section title="Views" hint={turned ? "Turned part: drawn with its axis horizontal. One elevation and the end view; the top view would repeat the front." : undefined}>
        <div className="grid grid-cols-2 gap-1.5">
          {["front", "top", "right", "iso"].map(v => (
            <label key={v} className={cx("flex items-center gap-2 rounded border border-border px-2 py-1.5 text-[12.5px]", (disabled || v === "front") && "opacity-70")}>
              <input type="checkbox" className="accent-[rgb(var(--primary))]" checked={shown.includes(v)} disabled={disabled || v === "front"}
                onChange={e => setView(v, e.target.checked)} />{VIEW_LABELS[v]}
            </label>
          ))}
        </div>
        {opts.views !== null && <button type="button" className="link text-[12px]" disabled={disabled} onClick={() => change({ views: null })}>Use the views chosen for this part</button>}
        <label className="flex items-center justify-between pt-1 text-[12.5px]">Hidden lines (dashed)<Toggle checked={opts.hidden} disabled={disabled} onChange={v => change({ hidden: v })} label="Hidden lines" /></label>
      </Section>
      {turned ? (
        <Section title="Section A-A" hint="Parts with a bore are sectioned along the axis in place of the elevation. Solid shafts are never sectioned lengthwise (ISO 128-50): a cross-section through the keyway or flat is shown instead.">
          <Segmented value={turnedSec} disabled={disabled}
            onChange={v => change({ section: v === "off" ? null : v === "auto" ? "auto" : v as "axial" | "cross" })}
            options={[{ value: "auto", label: "Auto" }, { value: "off", label: "Off" }, { value: "axial", label: "Along axis" }, { value: "cross", label: "Across" }]} />
        </Section>
      ) : (
        <Section title="Section A-A" hint="Cutting plane through the model centre, normal to the chosen axis; the cut faces are hatched.">
          <label className="flex items-center justify-between text-[12.5px]">Show section view<Toggle checked={sec === "x" || sec === "y" || sec === "z"} disabled={disabled} onChange={v => change({ section: v ? "y" : null })} label="Section view" /></label>
          {(sec === "x" || sec === "y" || sec === "z") && <Segmented value={sec} disabled={disabled} onChange={v => change({ section: v })}
            options={[{ value: "x", label: "X plane" }, { value: "y", label: "Y plane" }, { value: "z", label: "Z plane" }]} />}
        </Section>
      )}
      <Section title="General tolerances" hint="Printed only as you choose it here. Formwright never invents tolerances or GD&T.">
        <select className="input h-8 py-0 text-[13px]" value={tolValue} disabled={disabled} data-testid="tolerance"
          onChange={e => {
            const v = e.target.value;
            setCustomOpen(v === "custom");
            if (v === "none") change({ tolerance: { mode: "none", class: null, text: null } });
            else if (v === "custom") { if (customTol.trim()) change({ tolerance: { mode: "custom", class: null, text: customTol.trim() } }); }
            else change({ tolerance: { mode: "iso2768", class: v.slice(4) as "f" | "m" | "c" | "v", text: null } });
          }}>
          <option value="none">Not specified</option>
          <option value="iso-f">ISO 2768-f (fine)</option>
          <option value="iso-m">ISO 2768-m (medium)</option>
          <option value="iso-c">ISO 2768-c (coarse)</option>
          <option value="iso-v">ISO 2768-v (very coarse)</option>
          <option value="custom">Custom text…</option>
        </select>
        {customOpen && (
          <Input value={customTol} autoFocus={!customTol} maxLength={60} disabled={disabled} placeholder="e.g. ±0.2 mm unless stated"
            onChange={e => setCustomTol(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            onBlur={() => { const t = customTol.trim(); if (t && t !== opts.tolerance.text) change({ tolerance: { mode: "custom", class: null, text: t } }); }} />
        )}
      </Section>
    </div>
  );
}

function TagText({ text, tag, aux, hidden }: { text: string; tag: "spec" | "inferred"; aux?: boolean; hidden?: boolean }) {
  return <span className={cx("font-medium tabular-nums", hidden ? "text-muted line-through" : tag === "spec" && !aux ? "text-[#0b3d91] dark:text-[#7fa6ef]" : "italic text-[#9a3412] dark:text-[#f0a46b]")}>{text}</span>;
}

/** Tolerance or fit text for one dimension (user-entered), committed on Enter or blur. */
function TolInput({ value, disabled, onCommit }: { value: string; disabled: boolean; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <input value={v} disabled={disabled} maxLength={24} placeholder="tol." aria-label="Tolerance or fit"
      onChange={e => setV(e.target.value)} onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      onBlur={() => { if (v.trim() !== value) onCommit(v.trim()); }}
      className="h-6 w-[64px] rounded border border-border bg-panel px-1.5 text-[11.5px] tabular-nums outline-none placeholder:text-muted/60 focus:border-primary disabled:opacity-60" />
  );
}

function DimsPanel({ rec, edits, disabled, onSave, onLocate }: {
  rec: DrawingRecord; edits: DrawingEdits; disabled: boolean; onSave: (e: DrawingEdits) => void; onLocate: (id: string) => void;
}) {
  const dims = useMemo(() => [...rec.dimensions].sort((a, b) => a.view.localeCompare(b.view) || a.id.localeCompare(b.id)), [rec]);
  const label = (p: string) => rec.param_labels?.[p] ?? p;
  const setDim = (id: string, patch: { hidden?: boolean; tol?: string }) => {
    const cur = { ...(edits.dims[id] ?? {}), ...patch };
    const dimsNext = { ...edits.dims };
    if (!cur.hidden && !cur.tol) delete dimsNext[id]; else dimsNext[id] = { ...(cur.hidden ? { hidden: true } : {}), ...(cur.tol ? { tol: cur.tol } : {}) };
    onSave({ ...edits, dims: dimsNext });
  };
  const base = (text: string, tol?: string | null) => (tol && text.endsWith(` ${tol}`) ? text.slice(0, -tol.length - 1) : text);
  const HideBtn = ({ id, hidden }: { id: string; hidden?: boolean }) => (
    <Tip content={hidden ? "Show on the sheet" : "Hide from the sheet"} side="left">
      <button type="button" disabled={disabled} onClick={() => setDim(id, { hidden: !hidden })} aria-label={hidden ? "Show" : "Hide"}
        className="rounded p-0.5 text-muted hover:bg-text/5 hover:text-text disabled:opacity-50">{hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button>
    </Tip>);
  return (
    <div className="divide-y divide-border">
      <p className="px-4 pt-3 text-[11.5px] text-muted">Click a value to find it on the sheet. Tolerances and fits you enter print after the value and are marked as user-entered; your edits are kept when the model is rebuilt.</p>
      <div className="px-4 py-3">
        <div className="label mb-2">Callouts</div>
        {rec.callouts.length === 0 ? <p className="text-[12.5px] text-muted">No holes, radii or chamfers on principal axes.</p>
          : rec.callouts.map(c => (
            <div key={c.id} className="mb-1.5 flex items-start gap-1.5 text-[12.5px]" data-dim={c.id}>
              <HideBtn id={c.id} hidden={c.hidden} />
              <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onLocate(c.id)}>
                {c.lines.map((l, i) => <div key={i}><TagText text={i === 0 ? base(l.text, c.tol) : l.text} tag={l.tag} hidden={c.hidden} /></div>)}
                <div className="text-[11px] text-muted"><span className="capitalize">{c.view}</span> view{c.lines.some(l => l.param) ? ` · ${c.lines.flatMap(l => [l.param, ...(l.params ?? [])]).filter((x): x is string => !!x).map(label).join(", ")}` : ""}</div>
              </button>
              <TolInput value={edits.dims[c.id]?.tol ?? ""} disabled={disabled || !!c.hidden} onCommit={t => setDim(c.id, { tol: t })} />
            </div>
          ))}
      </div>
      <div className="px-4 py-3">
        <div className="label mb-2">Dimensions ({dims.length})</div>
        <table className="w-full text-[12.5px]">
          <tbody>
            {dims.map(d => (
              <tr key={d.id} className="border-b border-border/60 last:border-0" data-dim={d.id}>
                <td className="w-5 py-1"><HideBtn id={d.id} hidden={d.hidden} /></td>
                <td className="py-1"><button type="button" className="text-left" onClick={() => onLocate(d.id)}><TagText text={base(d.text, d.tol)} tag={d.tag} aux={d.aux} hidden={d.hidden} /></button></td>
                <td className="py-1 text-[11.5px] text-muted">{d.aux ? "reference" : d.param ? label(d.param) : "measured"}</td>
                <td className="py-1 text-right">{!d.aux && <TolInput value={edits.dims[d.id]?.tol ?? ""} disabled={disabled || !!d.hidden} onCommit={t => setDim(d.id, { tol: t })} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-3">
        <div className="label mb-1.5">Parameters not on the sheet as a value</div>
        {rec.mapping.unmapped.length === 0 ? <p className="text-[12.5px] text-muted">Every declared parameter appears on the sheet.</p>
          : <>
            <div className="flex flex-wrap gap-1">{rec.mapping.unmapped.map(p => <span key={p} className="rounded bg-text/5 px-1.5 py-0.5 text-[11.5px]">{label(p)}</span>)}</div>
            <p className="mt-1.5 text-[11.5px] leading-snug text-muted">Their sizes are on the sheet but shown as measured, because the same value appears more than once (no unambiguous match).</p>
          </>}
      </div>
    </div>
  );
}

function TitlePanel({ rec, edits, disabled, onSave }: { rec: DrawingRecord; edits: DrawingEdits; disabled: boolean; onSave: (e: DrawingEdits) => void }) {
  const fields: [keyof DrawingEdits["title"], string, string][] = [
    ["title", "Title", rec.title.title], ["drawing_no", "Drawing number", rec.title.drawing_no],
    ["company", "Company", "Your company"], ["checked_by", "Checked by", "Name of the checker"]];
  const [vals, setVals] = useState<Record<string, string>>({ ...edits.title });
  const [note, setNote] = useState("");
  useEffect(() => setVals({ ...edits.title }), [edits.title]);
  const commit = (k: string) => {
    const v = (vals[k] ?? "").trim();
    if (v === (edits.title[k as keyof DrawingEdits["title"]] ?? "")) return;
    const t = { ...edits.title, [k]: v };
    if (!v) delete t[k as keyof DrawingEdits["title"]];
    onSave({ ...edits, title: t });
  };
  const addNote = () => { const n = note.trim(); if (!n) return; onSave({ ...edits, notes: [...edits.notes, n] }); setNote(""); };
  return (
    <div>
      <Section title="Title block" hint="Approval stays “not approved”: the sheet never claims manufacturing approval.">
        {fields.map(([k, lab, ph]) => (
          <label key={k} className="block text-[12px]"><span className="text-muted">{lab}</span>
            <Input value={vals[k] ?? ""} placeholder={ph} maxLength={60} disabled={disabled} className="mt-0.5 h-8 text-[13px]"
              onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))} onBlur={() => commit(k)}
              onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
          </label>
        ))}
      </Section>
      <Section title="Notes" hint="Printed after the standard notes, as you write them.">
        {edits.notes.length > 0 && <ol className="space-y-1">
          {edits.notes.map((n, i) => (
            <li key={i} className="flex items-start gap-1.5 text-[12.5px]"><span className="text-muted">{i + 1}.</span><span className="min-w-0 flex-1">{n}</span>
              <button type="button" disabled={disabled} aria-label="Remove note" onClick={() => onSave({ ...edits, notes: edits.notes.filter((_, j) => j !== i) })}
                className="rounded p-0.5 text-muted hover:bg-text/5 hover:text-danger"><X className="h-3.5 w-3.5" /></button></li>))}
        </ol>}
        <div className="flex gap-1.5">
          <Input value={note} maxLength={160} disabled={disabled} placeholder="e.g. Break sharp edges 0.2–0.5 mm" className="h-8 text-[13px]"
            onChange={e => setNote(e.target.value)} onKeyDown={e => { if (e.key === "Enter") addNote(); }} />
          <Button size="sm" variant="secondary" disabled={disabled || !note.trim()} icon={<Plus className="h-3.5 w-3.5" />} onClick={addNote}>Add</Button>
        </div>
      </Section>
    </div>
  );
}

function Row({ ok, label, detail }: { ok: boolean; label: string; detail?: ReactNode }) {
  return (
    <div className="flex items-start gap-2 py-1.5 text-[12.5px]">
      {ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />}
      <div><div className="font-medium">{label}</div>{detail && <div className="text-[11.5px] text-muted">{detail}</div>}</div>
    </div>
  );
}

function CheckPanel({ rec }: { rec: DrawingRecord }) {
  const d = rec.check.detail;
  const maxErr = Math.max(0, ...Object.values(d.extents).map(e => e.max_err_mm));
  const holes = Object.entries(d.holes.census).map(([k, v]) => `${v}× Ø${+k}`).join(", ") || "none";
  const hidden = d.spec_once.hidden_by_user ?? [];
  const label = (p: string) => rec.param_labels?.[p] ?? p;
  return (
    <div className="px-4 py-3">
      <Card className={cx("mb-3 p-3", rec.check.passed ? "border-success/30" : "border-danger/30")}>
        <div className="flex items-center gap-2 text-[13px] font-semibold">{rec.check.passed ? <ShieldCheck className="h-4 w-4 text-success" /> : <ShieldAlert className="h-4 w-4 text-danger" />}CHK-12 drawing consistency</div>
        <p className="mt-1 text-[11.5px] text-muted">A deterministic check of this sheet against the model. It does not make the drawing approved for manufacture.</p>
      </Card>
      <Row ok={d.tags.untagged.length === 0} label="Every value tagged spec or inferred" detail={`${d.tags.dimensions} dimensions, ${d.tags.callout_lines} callout lines`} />
      <Row ok={d.spec_once.missing.length === 0 && d.spec_once.duplicates.length === 0 && d.spec_once.not_placed.length === 0}
        label="Spec parameters shown, nothing dimensioned twice" detail={Object.keys(d.spec_once.spec_on_sheet).map(label).join(", ") || "no spec dimensions"} />
      <Row ok={Object.values(d.extents).every(e => e.passed)} label="View extents match the model" detail={`max deviation ${maxErr.toFixed(4)} mm (limit 0.01)`} />
      {d.placement && <Row ok={d.placement.misplaced.length === 0} label="Each value against its own span" detail={d.placement.misplaced.length ? d.placement.misplaced.map(m => `${m.text}: ${m.why}`).join("; ") : `${d.placement.checked} dimension values checked`} />}
      <Row ok={d.overlap.text_overlaps.length === 0 && d.overlap.text_over_geometry.length === 0 && d.overlap.outside_frame.length === 0}
        label="No overlapping text" detail={`${d.overlap.texts} texts checked`} />
      <Row ok={Object.keys(d.holes.mismatch).length === 0} label="Hole callouts match the census" detail={holes} />
      {hidden.length > 0 && <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-muted"><EyeOff className="mt-0.5 h-3.5 w-3.5 shrink-0" />{hidden.length} dimension{hidden.length > 1 ? "s" : ""} hidden by you. Make sure the sheet still defines the part.</p>}
      {rec.check.problems.length > 0 && <div className="mt-2 rounded border border-danger/25 bg-danger/5 p-2 text-[12px] text-danger">{rec.check.problems.map(p => <div key={p}>• {p}</div>)}</div>}
      <p className="mt-3 text-[11px] text-muted">Generated in {rec.timings.total_s.toFixed(2)} s (geometry {rec.timings.geometry_s.toFixed(2)} s).</p>
    </div>
  );
}

function RevPanel({ rec }: { rec: DrawingRecord }) {
  const issued = rec.revisions ?? [];
  return (
    <div className="px-4 py-3">
      <div className="label mb-2 flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" />Issued revisions</div>
      {issued.length === 0 ? <p className="mb-4 text-[12px] text-muted">None yet. The sheet is a draft until you issue a release from the Design Studio; the issue freezes this sheet, the model and the reports as Rev A.</p>
        : <ol className="mb-4 space-y-1.5">{[...issued].reverse().map(r => (
          <li key={r.rev} className="rounded border border-border p-2 text-[12.5px]"><div className="flex justify-between"><span className="font-semibold">Rev {r.rev}</span><span className="text-[11px] text-muted">{r.date}</span></div>
            <div>{r.change}</div><div className="text-[11px] text-muted">by {r.by || "—"}</div></li>))}</ol>}
      <div className="label mb-2 flex items-center gap-1.5"><History className="h-3.5 w-3.5" />Model builds drawn</div>
      <p className="mb-3 text-[11.5px] text-muted">Each verified build that was drawn. These are working drafts, not revisions of the drawing.</p>
      <ol className="space-y-2">
        {[...rec.history].reverse().map((h, i) => (
          <li key={`${h.build_id}-${i}`} className="rounded border border-border p-2 text-[12.5px]">
            <div className="flex items-center justify-between"><span className="font-semibold">Model rev {h.rev}</span><span className="text-[11px] text-muted">{h.date}</span></div>
            <div className="mt-0.5">{h.change}</div>
            <div className="text-[11px] text-muted">by {h.by || "—"}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}
