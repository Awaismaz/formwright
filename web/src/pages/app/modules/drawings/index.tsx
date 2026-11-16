import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Box, CheckCircle2, Download, ExternalLink, FileWarning, History, Info, Lock, RefreshCw,
  Ruler, ShieldAlert, ShieldCheck, XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Input, PageLoader, StatusBadge, Tab, TabList, TabPanel, Tabs, Tip, Toggle } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";
import type { ModuleAppProps } from "../registry";
import SheetViewer from "./SheetViewer";
import { DEFAULT_OPTIONS, type DrawingOptions, type DrawingProject, type DrawingRecord, type DrawingState } from "./types";

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
  if (!pid) return <ProjectPicker onPick={id => setParams({ project: id })} />;
  return <Workspace key={pid} pid={pid} onBack={() => setParams({})} />;
}

/* ------------------------------------------------------------------ project picker */
function ProjectPicker({ onPick }: { onPick: (id: string) => void }) {
  const q = useQuery({ queryKey: ["drw-projects"], queryFn: () => api.get<{ items: DrawingProject[] }>(`${BASE}/projects`) });
  if (q.isLoading) return <PageLoader />;
  if (q.error) return <div className="p-10 text-center text-sm text-muted">{(q.error as Error).message}</div>;
  const items = [...(q.data?.items ?? [])].sort((a, b) => Number(b.verified) - Number(a.verified));
  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary-soft text-primary"><Ruler className="h-5 w-5" /></div>
          <div>
            <div className="flex items-center gap-2"><h1 className="text-[22px] font-semibold tracking-tight">Drawing Studio</h1><StatusBadge status="live" /></div>
            <p className="mt-0.5 text-sm text-muted">Pick a project to turn its latest verified model into a drawing sheet.</p>
          </div>
        </div>
      </div>
      <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-panel p-3.5 text-[13px] text-muted">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div>Views are exact hidden-line projections of your model. Dimensions are tagged <b className="text-[#0b3d91]">spec</b> when they equal a declared model parameter and <i className="text-[#9a3412]">inferred</i> when measured from the geometry. Every sheet is consistency-checked and stamped <b>NOT APPROVED FOR MANUFACTURE</b>: an engineer must review it.</div>
      </div>
      {items.length === 0 ? (
        <EmptyState icon={<Box className="h-5 w-5" />} title="No projects yet" body="Create and build a part in the Design Studio, then come back to draw it."
          action={<Link to="/app/projects"><Button>Go to projects</Button></Link>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(p => <PickCard key={p.id} p={p} onPick={onPick} />)}
        </div>
      )}
    </div>
  );
}

function DrawingBadge({ p }: { p: DrawingProject }) {
  if (!p.verified) return <Badge><Lock className="h-3 w-3" />No verified build</Badge>;
  if (!p.drawing) return <Badge tone="primary">No drawing yet</Badge>;
  if (p.drawing.stale) return <Badge tone="warning"><AlertTriangle className="h-3 w-3" />Model changed</Badge>;
  return <Badge tone={p.drawing.chk12 ? "success" : "danger"}>{p.drawing.chk12 ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}Rev {p.drawing.model_rev ?? "—"} · {p.drawing.sheet} {p.drawing.scale}</Badge>;
}

function PickCard({ p, onPick }: { p: DrawingProject; onPick: (id: string) => void }) {
  const body = (
    <>
      <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-border">
        {p.thumbnail ? <IsoThumb src={p.thumbnail} /> : <Box className="h-10 w-10 text-muted/50" />}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <div className="min-w-0"><div className="truncate text-sm font-semibold">{p.name}</div>
          <div className="truncate text-xs text-muted">{p.material ?? "—"}</div></div>
        <div className="mt-auto flex items-center justify-between gap-2 text-xs text-muted">
          <DrawingBadge p={p} /><span>{ago(p.updated_at)}</span>
        </div>
      </div>
    </>
  );
  if (!p.verified) {
    return (
      <div className="card flex flex-col overflow-hidden opacity-70" title="Build and verify this model in the Design Studio first">
        {body}
        <Link to={`/app/projects/${p.id}`} className="border-t border-border px-3.5 py-2 text-xs text-primary hover:underline">Open in Design Studio →</Link>
      </div>
    );
  }
  return (
    <button type="button" onClick={() => onPick(p.id)} data-project={p.id}
      className="card group flex flex-col overflow-hidden text-left transition hover:-translate-y-0.5 hover:shadow-pop">
      {body}
    </button>
  );
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

function Workspace({ pid, onBack }: { pid: string; onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["drw", pid], queryFn: () => api.get<DrawingState>(`${BASE}/projects/${pid}`) });
  const st = q.data;
  const rec = st?.drawing ?? null;
  const [opts, setOpts] = useState<DrawingOptions>(DEFAULT_OPTIONS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [customTol, setCustomTol] = useState("");
  const inited = useRef(false);
  const autoRan = useRef(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!st || inited.current) return;
    inited.current = true;
    if (st.drawing) { setOpts(st.drawing.options); setCustomTol(st.drawing.options.tolerance.text ?? ""); }
  }, [st]);

  const generate = useCallback(async (o: DrawingOptions, reason?: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<DrawingState>(`${BASE}/projects/${pid}/generate`, o);
      qc.setQueryData(["drw", pid], r);
      qc.invalidateQueries({ queryKey: ["drw-projects"] });
      setNonce(n => n + 1);
      if (reason) toast.success(reason);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The drawing could not be generated.");
    } finally { setBusy(false); }
  }, [pid, qc]);

  // associative: open with no drawing / a changed model -> (re)generate from the latest verified build
  useEffect(() => {
    if (!st || autoRan.current || !st.can_edit || !st.project.verified) return;
    if (!st.drawing || st.stale) {
      autoRan.current = true;
      void generate(st.drawing?.options ?? DEFAULT_OPTIONS, st.drawing ? `Drawing updated to model rev ${st.current_rev ?? "—"}` : undefined);
    }
  }, [st, generate]);

  const change = (patch: Partial<DrawingOptions>) => {
    const next = { ...opts, ...patch };
    setOpts(next);
    if (!st?.can_edit) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void generate(next), 250);
  };

  const svgQ = useQuery({
    queryKey: ["drw-svg", pid, rec?.build_id, nonce],
    queryFn: () => fetchText(`${BASE}/projects/${pid}/files/sheet.svg`),
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
  const counts = { spec: 0, inferred: 0, ref: 0 };
  rec?.dimensions.forEach(d => { if (d.aux) counts.ref++; else counts[d.tag]++; });
  rec?.callouts.forEach(c => c.lines.forEach(l => counts[l.tag]++));
  const file = (n: string) => `${BASE}/projects/${pid}/files/${n}?download=1`;

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-panel px-3">
        <Tip content="All projects" side="bottom"><button onClick={onBack} aria-label="All projects" className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text"><ArrowLeft className="h-4 w-4" /></button></Tip>
        <div className="flex min-w-0 items-center gap-2">
          <Ruler className="h-4 w-4 shrink-0 text-primary" />
          <span className="truncate text-[14px] font-semibold">{st.project.name}</span>
          {rec && <Badge>Model rev {rec.model_rev ?? "—"}</Badge>}
          {rec && <Badge>{rec.sheet.size} · {rec.sheet.scale}</Badge>}
          {chk && <CheckBadge chk={chk} />}
          {st.stale && !busy && <Badge tone="warning"><AlertTriangle className="h-3 w-3" />Model changed since this sheet</Badge>}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {st.can_edit && <Button size="sm" variant="secondary" loading={busy} disabled={!st.project.verified} icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => void generate(opts, "Drawing regenerated from the latest build")} data-testid="regenerate">Regenerate</Button>}
          {rec && (["svg", "pdf", "dxf"] as const).map(ext => (
            <Tip key={ext} content={{ svg: "Vector sheet (SVG)", pdf: "Print-ready PDF", dxf: "DXF at true size (1:1 model units)" }[ext]} side="bottom">
              <a href={file(`sheet.${ext}`)} data-download={ext} className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-panel px-2.5 text-[12.5px] font-medium hover:bg-panel2">
                <Download className="h-3.5 w-3.5" />{ext.toUpperCase()}</a>
            </Tip>
          ))}
          <Tip content="Open the model in the Design Studio" side="bottom"><Link to={`/app/projects/${pid}`} className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Open in Design Studio"><ExternalLink className="h-4 w-4" /></Link></Tip>
        </div>
      </div>
      {(!st.can_edit || error || !st.project.verified) && (
        <div className={cx("flex items-center gap-2 border-b px-4 py-2 text-[12.5px]", error ? "border-danger/25 bg-danger/5 text-danger" : "border-border bg-panel2 text-muted")}>
          {error ? <><FileWarning className="h-4 w-4" />{error}</>
            : !st.project.verified ? <><Lock className="h-4 w-4" />This project has no verified build. <Link to={`/app/projects/${pid}`} className="link">Build it in the Design Studio</Link> first.</>
            : <><Info className="h-4 w-4" />You have view-only access: you can open and download drawings but not regenerate them.</>}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {/* side panel */}
        <aside className="flex w-[300px] shrink-0 flex-col border-r border-border bg-panel">
          <Tabs defaultValue="sheet" className="flex min-h-0 flex-1 flex-col">
            <TabList className="px-2"><Tab value="sheet" compact>Sheet</Tab><Tab value="dims" compact>Dimensions</Tab><Tab value="check" compact>Check</Tab><Tab value="rev" compact>History</Tab></TabList>
            <TabPanel value="sheet" className="min-h-0 flex-1 overflow-y-auto">
              <OptionsPanel opts={opts} change={change} disabled={!st.can_edit || !st.project.verified} customTol={customTol} setCustomTol={setCustomTol} />
              <div className="px-4 py-3.5"><Legend counts={counts} /></div>
            </TabPanel>
            <TabPanel value="dims" className="min-h-0 flex-1 overflow-y-auto">{rec ? <DimsPanel rec={rec} /> : <Empty />}</TabPanel>
            <TabPanel value="check" className="min-h-0 flex-1 overflow-y-auto">{rec ? <CheckPanel rec={rec} /> : <Empty />}</TabPanel>
            <TabPanel value="rev" className="min-h-0 flex-1 overflow-y-auto">{rec ? <RevPanel rec={rec} /> : <Empty />}</TabPanel>
          </Tabs>
        </aside>
        {/* sheet */}
        <div className="relative min-w-0 flex-1">
          {rec && svgQ.data ? <SheetViewer svg={svgQ.data} widthMm={rec.sheet.w} heightMm={rec.sheet.h} busy={busy} />
            : <div className="flex h-full items-center justify-center bg-[#e9edf2] text-sm text-muted dark:bg-[#1b2027]">
                {busy || svgQ.isLoading ? <span className="inline-flex items-center gap-2"><RefreshCw className="h-4 w-4 animate-spin" />Generating views from the verified model…</span>
                  : st.project.verified ? "No drawing yet." : "Nothing to draw yet."}
              </div>}
          {busy && rec && <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-full border border-border bg-panel px-3 py-1 text-[12px] text-muted shadow-card"><span className="inline-flex items-center gap-1.5"><RefreshCw className="h-3.5 w-3.5 animate-spin" />Regenerating…</span></div>}
        </div>
      </div>
    </div>
  );
}

function Empty() {
  return <p className="p-4 text-sm text-muted">Generate the drawing first.</p>;
}

function CheckBadge({ chk }: { chk: DrawingRecord["check"] }) {
  return (
    <Tip side="bottom" content={chk.passed ? "CHK-12 drawing consistency passed: tags, spec parameters, view extents vs model, no text overlaps, hole callouts vs census." : chk.problems.join(" · ")}>
      <span data-testid="chk12">
        <Badge tone={chk.passed ? "success" : "danger"}>{chk.passed ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}CHK-12 {chk.passed ? "passed" : "failed"}</Badge>
      </span>
    </Tip>
  );
}

function Legend({ counts }: { counts: { spec: number; inferred: number; ref: number } }) {
  return (
    <div className="space-y-2" data-testid="legend">
      <div className="label">Dimension tags</div>
      <div className="flex items-baseline gap-2.5 text-[12.5px]"><span className="w-10 font-medium text-[#0b3d91] dark:text-[#7fa6ef]">120</span><span><b>Spec</b> · equals a declared model parameter</span><span className="ml-auto tabular-nums text-muted">{counts.spec}</span></div>
      <div className="flex items-baseline gap-2.5 text-[12.5px]"><span className="w-10 font-medium italic text-[#9a3412] dark:text-[#f0a46b]">120</span><span><b>Inferred</b> · measured from the geometry</span><span className="ml-auto tabular-nums text-muted">{counts.inferred}</span></div>
      <div className="flex items-baseline gap-2.5 text-[12.5px]"><span className="w-10 italic text-[#9a3412] dark:text-[#f0a46b]">(40)</span><span><b>Reference</b> · for information only</span><span className="ml-auto tabular-nums text-muted">{counts.ref}</span></div>
    </div>
  );
}

function OptionsPanel({ opts, change, disabled, customTol, setCustomTol }: {
  opts: DrawingOptions; change: (p: Partial<DrawingOptions>) => void; disabled: boolean; customTol: string; setCustomTol: (s: string) => void;
}) {
  const [customOpen, setCustomOpen] = useState(opts.tolerance.mode === "custom");
  const tolValue = customOpen ? "custom" : opts.tolerance.mode === "iso2768" ? `iso-${opts.tolerance.class}` : opts.tolerance.mode;
  const setView = (v: string, on: boolean) => {
    const set = new Set(opts.views);
    if (on) set.add(v); else set.delete(v);
    change({ views: ["front", "top", "right", "iso"].filter(x => set.has(x)) });
  };
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
      <Section title="Views">
        <div className="grid grid-cols-2 gap-1.5">
          {["front", "top", "right", "iso"].map(v => (
            <label key={v} className={cx("flex items-center gap-2 rounded border border-border px-2 py-1.5 text-[12.5px]", (disabled || v === "front") && "opacity-70")}>
              <input type="checkbox" className="accent-[rgb(var(--primary))]" checked={opts.views.includes(v)} disabled={disabled || v === "front"}
                onChange={e => setView(v, e.target.checked)} />{VIEW_LABELS[v]}
            </label>
          ))}
        </div>
        <label className="flex items-center justify-between pt-1 text-[12.5px]">Hidden lines (dashed)<Toggle checked={opts.hidden} disabled={disabled} onChange={v => change({ hidden: v })} label="Hidden lines" /></label>
      </Section>
      <Section title="Section A-A" hint="Cutting plane through the model centre, normal to the chosen axis; the cut faces are hatched.">
        <label className="flex items-center justify-between text-[12.5px]">Show section view<Toggle checked={!!opts.section} disabled={disabled} onChange={v => change({ section: v ? "y" : null })} label="Section view" /></label>
        {opts.section && <Segmented value={opts.section} disabled={disabled} onChange={v => change({ section: v })}
          options={[{ value: "x", label: "X plane" }, { value: "y", label: "Y plane" }, { value: "z", label: "Z plane" }]} />}
      </Section>
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

function TagText({ text, tag, aux }: { text: string; tag: "spec" | "inferred"; aux?: boolean }) {
  return <span className={cx("font-medium tabular-nums", tag === "spec" && !aux ? "text-[#0b3d91] dark:text-[#7fa6ef]" : "italic text-[#9a3412] dark:text-[#f0a46b]")}>{text}</span>;
}

function DimsPanel({ rec }: { rec: DrawingRecord }) {
  const dims = useMemo(() => [...rec.dimensions].sort((a, b) => a.view.localeCompare(b.view) || a.id.localeCompare(b.id)), [rec]);
  return (
    <div className="divide-y divide-border">
      <div className="px-4 py-3">
        <div className="label mb-2">Hole callouts</div>
        {rec.callouts.length === 0 ? <p className="text-[12.5px] text-muted">No holes on principal axes.</p>
          : rec.callouts.map(c => (
            <div key={c.id} className="mb-1.5 text-[12.5px]">
              {c.lines.map((l, i) => <div key={i} className="flex items-baseline justify-between gap-2"><TagText text={l.text} tag={l.tag} /><span className="text-[11px] text-muted">{l.param ?? "measured"}</span></div>)}
              <div className="text-[11px] capitalize text-muted">{c.view} view</div>
            </div>
          ))}
      </div>
      <div className="px-4 py-3">
        <div className="label mb-2">Dimensions ({dims.length})</div>
        <table className="w-full text-[12.5px]">
          <tbody>
            {dims.map(d => (
              <tr key={d.id} className="border-b border-border/60 last:border-0">
                <td className="py-1"><TagText text={d.text} tag={d.tag} aux={d.aux} /></td>
                <td className="py-1 text-muted">{d.aux ? "reference" : d.param ? <code className="rounded bg-text/5 px-1 text-[11.5px] text-text">{d.param}</code> : "measured"}</td>
                <td className="py-1 text-right capitalize text-muted">{d.view}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-3">
        <div className="label mb-1.5">Parameters not on the sheet</div>
        {rec.mapping.unmapped.length === 0 ? <p className="text-[12.5px] text-muted">Every declared parameter appears as a spec dimension.</p>
          : <>
            <div className="flex flex-wrap gap-1">{rec.mapping.unmapped.map(p => <code key={p} className="rounded bg-text/5 px-1.5 py-0.5 text-[11.5px]">{p}</code>)}</div>
            <p className="mt-1.5 text-[11.5px] leading-snug text-muted">No unambiguous match in the drawn geometry (radii, chamfers, counts, or values that coincide with another size). They are listed in the sheet notes.</p>
          </>}
      </div>
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
  return (
    <div className="px-4 py-3">
      <Card className={cx("mb-3 p-3", rec.check.passed ? "border-success/30" : "border-danger/30")}>
        <div className="flex items-center gap-2 text-[13px] font-semibold">{rec.check.passed ? <ShieldCheck className="h-4 w-4 text-success" /> : <ShieldAlert className="h-4 w-4 text-danger" />}CHK-12 drawing consistency</div>
        <p className="mt-1 text-[11.5px] text-muted">A deterministic check of this sheet against the model. It does not make the drawing approved for manufacture.</p>
      </Card>
      <Row ok={d.tags.untagged.length === 0} label="Every value tagged spec or inferred" detail={`${d.tags.dimensions} dimensions, ${d.tags.callout_lines} callout lines`} />
      <Row ok={d.spec_once.missing.length === 0 && d.spec_once.duplicates.length === 0 && d.spec_once.not_placed.length === 0}
        label="Spec parameters shown, nothing dimensioned twice" detail={Object.keys(d.spec_once.spec_on_sheet).join(", ") || "no spec dimensions"} />
      <Row ok={Object.values(d.extents).every(e => e.passed)} label="View extents match the model" detail={`max deviation ${maxErr.toFixed(4)} mm (limit 0.01)`} />
      <Row ok={d.overlap.text_overlaps.length === 0 && d.overlap.text_over_geometry.length === 0 && d.overlap.outside_frame.length === 0}
        label="No overlapping text" detail={`${d.overlap.texts} texts checked`} />
      <Row ok={Object.keys(d.holes.mismatch).length === 0} label="Hole callouts match the census" detail={holes} />
      {rec.check.problems.length > 0 && <div className="mt-2 rounded border border-danger/25 bg-danger/5 p-2 text-[12px] text-danger">{rec.check.problems.map(p => <div key={p}>• {p}</div>)}</div>}
      <p className="mt-3 text-[11px] text-muted">Generated in {rec.timings.total_s.toFixed(2)} s (geometry {rec.timings.geometry_s.toFixed(2)} s).</p>
    </div>
  );
}

function RevPanel({ rec }: { rec: DrawingRecord }) {
  return (
    <div className="px-4 py-3">
      <div className="label mb-2 flex items-center gap-1.5"><History className="h-3.5 w-3.5" />Revision history</div>
      <p className="mb-3 text-[11.5px] text-muted">The sheet follows the model: each new verified build that is drawn adds a row (shown in the sheet's revision table).</p>
      <ol className="space-y-2">
        {[...rec.history].reverse().map((h, i) => (
          <li key={`${h.build_id}-${i}`} className="rounded border border-border p-2 text-[12.5px]">
            <div className="flex items-center justify-between"><span className="font-semibold">Rev {h.rev}</span><span className="text-[11px] text-muted">{h.date}</span></div>
            <div className="mt-0.5">{h.change}</div>
            <div className="text-[11px] text-muted">by {h.by || "—"}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}
