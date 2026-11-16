import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Download, FileBox, Info, PenTool, RotateCcw, Wrench, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import type { Check, ExportFile, Orientation, Report, Settings, Status } from "./types";
import type { Src } from "./index";
import { studioAskUrl } from "../fixit";

const ICON: Record<Status, JSX.Element> = {
  pass: <CheckCircle2 className="h-4 w-4 text-success" />, warn: <AlertTriangle className="h-4 w-4 text-warning" />,
  fail: <XCircle className="h-4 w-4 text-danger" />, info: <Info className="h-4 w-4 text-muted" />,
};
const TONE: Record<Status, "success" | "warning" | "danger" | "neutral"> = { pass: "success", warn: "warning", fail: "danger", info: "neutral" };

export const f = (n: number | null | undefined, d = 1) => n === null || n === undefined || !Number.isFinite(n) ? "—"
  : n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
export function dur(s: number) {
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}
const kb = (b: number) => b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} kB`;

function value(c: Check): string {
  if (c.value === null || c.value === undefined) return "";
  if (Array.isArray(c.value)) return c.value.map(v => f(v, 1)).join(" × ") + " mm";
  const v = c.value;
  const d = c.unit.startsWith("mm") && !c.unit.includes("²") ? (Math.abs(v) < 0.1 && v !== 0 ? 4 : 2) : 0;
  return `${f(v, Number.isInteger(v) && d === 0 ? 0 : d)} ${c.unit}`;
}

const where = (c: Check) => {
  const feats = [...new Set((c.regions ?? []).map(r => r.feature).filter(Boolean))].slice(0, 3);
  return feats.length ? ` (at ${feats.join(", ")})` : "";
};
/** A plain request for the design agent when a finding can only be fixed in the model (not by orientation). */
export function fixPrompt(c: Check, process: string): string | null {
  if (c.status === "pass" || c.status === "info") return null;
  const lim = typeof c.limit === "number" ? c.limit : null;
  const v = typeof c.value === "number" ? c.value : null;
  switch (c.id) {
    case "PP-08": return `For ${process} 3D printing, thicken the walls that are thinner than ${lim ?? "the minimum"} mm${v !== null ? ` (thinnest ${f(v, 2)} mm)` : ""}${where(c)} to at least ${lim ?? "the minimum"} mm. Keep the outside size and every other feature unchanged.`;
    case "PP-09": return `For ${process} 3D printing, widen the gaps and slots narrower than ${lim ?? "the minimum"} mm${where(c)} to at least ${lim ?? "the minimum"} mm so they do not fuse. Keep everything else unchanged.`;
    case "PP-10": return `For ${process} 3D printing, the holes smaller than Ø${lim ?? "the minimum"} mm will print undersize. If they are functional, keep them in the model but tell me which ones should be drilled after printing; otherwise enlarge them to at least Ø${lim ?? "the minimum"} mm.`;
    case "PP-11": return `For ${process} 3D printing, make the pins and bosses thinner than Ø${lim ?? "the minimum"} mm at least Ø${lim ?? "the minimum"} mm, or add a fillet at their base. Keep everything else unchanged.`;
    case "PP-12": return `For ${process} 3D printing, remove or enlarge the loose features smaller than ${lim ?? "the minimum"} mm. Keep everything else unchanged.`;
    default: return null;
  }
}

function CheckRow({ c, fixUrl }: { c: Check; fixUrl?: string | null }) {
  const [open, setOpen] = useState(false);
  const more = (c.regions && c.regions.length > 0) || (c.items && c.items.length > 0);
  return (
    <div className="border-b border-border px-4 py-2.5 last:border-b-0" data-check={c.id} data-status={c.status}>
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5">{ICON[c.status]}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <div className="text-[13px] font-medium">{c.name}</div>
            <div className="shrink-0 text-[12px] tabular-nums text-muted">{value(c)}</div>
          </div>
          <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{c.detail}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted">
            <span className="rounded bg-text/[.05] px-1.5 py-0.5">{c.level}</span>
            {c.limit_is_assumption && c.limit !== null && <span className="rounded bg-accent/10 px-1.5 py-0.5 text-accent">limit is an assumption</span>}
            {more && <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-0.5 text-primary hover:underline">{open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}Details</button>}
            {fixUrl && <Link to={fixUrl} className="ml-auto inline-flex items-center gap-1 rounded border border-primary/30 px-1.5 py-0.5 text-primary hover:bg-primary-soft" title="Opens the Design Studio with this request written in the chat, for you to review and send" data-fix={c.id}><PenTool className="h-3 w-3" />Fix in Studio</Link>}
          </div>
          {open && c.regions && <ul className="mt-1.5 space-y-0.5 text-[11.5px]">
            {c.regions.slice(0, 10).map((r, i) => <li key={i} className="flex justify-between gap-2"><span className="truncate">{r.feature ?? (r.face !== undefined ? `Face ${r.face + 1}` : `Region ${i + 1}`)}</span><span className="tabular-nums text-muted">{f(r.min_mm, 2)} mm · {f(r.area_mm2, 0)} mm²</span></li>)}
          </ul>}
          {open && c.items && <ul className="mt-1.5 space-y-0.5 text-[11.5px]">
            {c.items.slice(0, 10).map((r, i) => <li key={i} className="flex justify-between"><span>{r.kind ? `${r.kind[0]!.toUpperCase()}${r.kind.slice(1)}` : `Piece ${i + 1}`}</span><span className="tabular-nums text-muted">{r.diameter_mm !== undefined ? `Ø${f(r.diameter_mm, 2)} mm` : `${f(r.size_mm, 2)} mm`}</span></li>)}
          </ul>}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[10.5px] uppercase tracking-wide text-muted">{label}</div><div className="text-[13px] font-semibold tabular-nums">{value}</div></div>;
}

function OrientCard({ o, active, onClick, supports }: { o: Orientation; active: boolean; onClick: () => void; supports: boolean }) {
  const [a, b, c] = o.euler_xyz_deg;
  return (
    <button onClick={onClick} data-orient={o.id} aria-pressed={active}
      className={cx("w-full rounded-lg border p-3 text-left transition", active ? "border-primary bg-primary-soft/60 ring-1 ring-primary/30" : "border-border bg-panel hover:border-primary/40")}>
      <div className="flex items-center gap-2">
        <span className={cx("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-bold", o.rank === 1 ? "bg-primary text-primary-fg" : "bg-text/10 text-text")}>{o.rank}</span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{o.label}</span>
        {o.rank === 1 && <Badge tone="primary">Suggested</Badge>}
        {!o.fits && <Badge tone="danger">Too big</Badge>}
      </div>
      <div className="mt-2.5 grid grid-cols-4 gap-2">
        <Metric label="Height" value={`${f(o.height_mm, 1)} mm`} />
        <Metric label={supports ? "Support" : "Overhang"} value={`${f(supports ? o.support_area_mm2 : o.overhang_area_mm2, 0)} mm²`} />
        <Metric label="Bed contact" value={`${f(o.contact_area_mm2, 0)} mm²`} />
        <Metric label="Time*" value={dur(o.estimate.time_s)} />
      </div>
      {active && <>
        <ul className="mt-2.5 space-y-1 text-[12px] leading-relaxed">
          {o.rationale.map((r, i) => <li key={i} className="flex gap-1.5"><span className="text-primary">•</span>{r}</li>)}
          <li className="flex gap-1.5 text-muted"><span className="text-primary">•</span>{o.strength_note}</li>
        </ul>
        <div className="mt-2 rounded bg-text/[.04] px-2 py-1.5 text-[11.5px] text-muted">
          Rotation to apply (fixed axes): X {f(a, 1)}°, then Y {f(b, 1)}°, then Z {f(c, 1)}°
        </div>
      </>}
    </button>
  );
}

export function ResultsPanel({ src, report, orient, selected, onSelect, settings, canEdit, onRepaired }: {
  src: Src; report: Report; orient: Orientation | null; selected: string | null; onSelect: (id: string) => void;
  settings: Settings; canEdit: boolean; onRepaired: () => void;
}) {
  const [tab, setTab] = useState("checks");
  const [exports, setExports] = useState<ExportFile[]>(report.exports);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => setExports(report.exports), [report.exports]);
  const ocs = orient?.checks ?? [];
  const all = [...report.checks, ...ocs];
  const status: Status = all.some(c => c.status === "fail") ? "fail" : all.some(c => c.status === "warn") ? "warn" : "pass";
  const fails = all.filter(c => c.status === "fail").length, warns = all.filter(c => c.status === "warn").length;
  const meshIssues = report.checks.some(c => ["PP-01", "PP-02", "PP-03", "PP-04"].includes(c.id) && c.status !== "pass");
  const supports = report.process.supports;
  const e = orient?.estimate;
  const est = report.estimates;

  const doExport = async (format: "stl" | "3mf") => {
    if (!orient) return;
    setBusy(format);
    try {
      const r = await api.post<ExportFile & { url: string; volume_match: boolean }>(`/api/m/print/${src.kind}/${src.id}/export`, {
        format, rotation: orient.rotation, tolerance: settings.tolerance, printer_mm: report.process.printer_mm,
        label: `#${orient.rank} ${orient.label}`, tag: orient.id, process: report.process.code,
      });
      setExports(x => [{ name: r.name, bytes: r.bytes, format: r.format, state: "current", made_from_rev: r.made_from_rev, label: r.label }, ...x.filter(y => y.name !== r.name)]);
      toast.success(`${format.toUpperCase()} ready: ${r.name}`, { description: r.volume_match ? "Reloaded and checked: same volume, millimetres." : undefined });
      window.location.assign(r.url);
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Export failed"); } finally { setBusy(null); }
  };
  const doRepair = async (revert = false) => {
    setBusy(revert ? "revert" : "repair");
    try {
      await api.post(`/api/m/print/uploads/${src.id}/${revert ? "revert" : "repair"}`);
      toast.success(revert ? "Restored the original mesh" : "Mesh repaired. Re-analysing…");
      onRepaired();
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Repair failed"); } finally { setBusy(null); }
  };
  const rep = report.source.repair;

  return (
    <div className="flex min-h-full flex-col">
      <div className={cx("border-b border-border px-4 py-3", status === "fail" ? "bg-danger/5" : status === "warn" ? "bg-warning/5" : "bg-success/5")} data-testid="print-summary">
        <div className="flex items-center gap-2">
          {ICON[status]}
          <div className="text-[14px] font-semibold">{status === "pass" ? "Geometry checks passed" : status === "warn" ? "Printable, with points to check" : "Fix before printing"}</div>
          <Badge tone={TONE[status]} className="ml-auto">{fails} fail · {warns} check</Badge>
        </div>
        <p className="mt-1 text-[11.5px] text-muted">{report.process.name} · {report.material?.name ?? "no material"} · {report.source.triangles.toLocaleString()} triangles
          {report.source.tolerance_mm !== undefined && <> · tolerance {report.source.tolerance_mm} mm (measured {f(report.source.deviation?.max_mm, 4)} mm)</>}</p>
        {report.design_material?.metal && <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] text-warning" data-testid="print-design-material"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />Design material: {report.design_material.name}. This print is a form and fit model, not a functional part.</p>}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <TabList className="px-2"><Tab value="checks">Checks</Tab><Tab value="orient">Orientation</Tab><Tab value="export">Estimates</Tab></TabList>

        <TabPanel value="checks" className="flex-1">
          {src.kind === "uploads" && (meshIssues || report.source.repaired) && (
            <div className="m-3 rounded-lg border border-border bg-panel2 p-3">
              <div className="flex items-center gap-2 text-[13px] font-semibold"><Wrench className="h-4 w-4 text-primary" />Mesh repair</div>
              {rep ? <>
                <ul className="mt-1.5 space-y-0.5 text-[12px]">{rep.actions.map((a, i) => <li key={i}>• {a}</li>)}</ul>
                <table className="mt-2 w-full text-[11.5px] tabular-nums">
                  <thead><tr className="text-muted"><th className="text-left font-normal" /><th className="text-right font-normal">Before</th><th className="text-right font-normal">After</th></tr></thead>
                  <tbody>{([["triangles", "Triangles"], ["boundary_edges", "Open edges"], ["nonmanifold_edges", "Non-manifold edges"], ["inconsistent_edges", "Flipped-winding edges"], ["degenerate_faces", "Degenerate triangles"], ["holes", "Holes"]] as const).map(([k, l]) => (
                    <tr key={k}><td>{l}</td><td className="text-right">{rep.before[k]?.toLocaleString()}</td><td className={cx("text-right", rep.after[k] !== rep.before[k] && "font-semibold text-success")}>{rep.after[k]?.toLocaleString()}</td></tr>))}</tbody>
                </table>
                {canEdit && <Button className="mt-2" size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy === "revert"} onClick={() => doRepair(true)}>Restore original</Button>}
              </> : <>
                <p className="mt-1 text-[12px] text-muted">Weld duplicate vertices, remove degenerate and duplicate triangles, make the winding consistent and outward, and fill holes. The original upload is kept.</p>
                {canEdit && <Button className="mt-2" size="sm" icon={<Wrench className="h-3.5 w-3.5" />} loading={busy === "repair"} onClick={() => doRepair(false)} data-testid="print-repair">Repair mesh</Button>}
              </>}
            </div>
          )}
          <div className="px-4 pb-1 pt-3 label">Mesh and geometry</div>
          <div>{report.checks.map(c => { const fp = src.kind === "projects" && canEdit ? fixPrompt(c, report.process.name) : null;
            return <CheckRow key={c.id} c={c} fixUrl={fp ? studioAskUrl(src.id, fp) : null} />; })}</div>
          {orient && <>
            <div className="px-4 pb-1 pt-3 label">For orientation #{orient.rank} · {orient.label}</div>
            <div>{ocs.map(c => <CheckRow key={c.id} c={c} />)}</div>
          </>}
        </TabPanel>

        <TabPanel value="orient" className="flex-1 space-y-2 p-3">
          <p className="px-1 text-[12px] leading-relaxed text-muted">Candidate orientations: as modelled, each model axis down, flat faces resting on the bed and principal axes, ranked by {supports ? "support area, height and bed contact" : "build height"}{settings.load_dir ? " and the load direction" : ""}. Click one to preview it on the bed.</p>
          {report.orientations.map(o => <OrientCard key={o.id} o={o} active={o.id === selected} onClick={() => onSelect(o.id)} supports={supports} />)}
          <p className="px-1 text-[11px] text-muted">* Rough time estimate. {report.notes}</p>
        </TabPanel>

        <TabPanel value="export" className="flex-1 p-3">
          <div className="rounded-lg border border-border p-3">
            <div className="flex items-center justify-between"><div className="text-[13px] font-semibold">Estimates</div><span className="rounded bg-text/[.05] px-1.5 py-0.5 text-[10.5px] text-muted">{est.level}</span></div>
            <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2.5">
              <Metric label="Part volume" value={`${f(est.volume_mm3 / 1000, 2)} cm³`} />
              <Metric label="Surface area" value={`${f(est.area_mm2 / 100, 1)} cm²`} />
              <Metric label="Bounding box" value={est.bbox_mm.map(x => f(x, 1)).join(" × ") + " mm"} />
              <Metric label="Solid mass" value={est.mass_solid_g !== null ? `${f(est.mass_solid_g, 1)} g` : "—"} />
              {e && <>
                <Metric label="Printed part" value={e.part_mass_g !== null ? `${f(e.part_mass_g, 1)} g` : "—"} />
                <Metric label="Supports" value={e.support_mass_g !== null ? `${f(e.support_mass_g, 1)} g` : "—"} />
                <Metric label="Print time" value={dur(e.time_s)} />
                <Metric label="Layers" value={orient!.layers.toLocaleString()} />
              </>}
            </div>
            {e && <p className="mt-2.5 text-[11px] leading-relaxed text-muted">For orientation #{orient!.rank}. Model: {e.model}. Material {report.material?.name} at {report.material?.density_g_cm3} g/cm³ (typical; verify). Slicer times usually differ, often by 30% or more.</p>}
          </div>

          <div className="mt-3 rounded-lg border border-border p-3">
            <div className="text-[13px] font-semibold">Export oriented mesh</div>
            <p className="mt-1 text-[12px] text-muted">{orient ? <>Orientation #{orient.rank} ({orient.label}), placed on the bed at the centre of a {report.process.printer_mm.map(x => f(x, 0)).join(" × ")} mm volume. Millimetres.</> : "Pick an orientation first."}</p>
            {canEdit ? <div className="mt-2.5 flex gap-2">
              <Button size="sm" icon={<Download className="h-4 w-4" />} disabled={!orient} loading={busy === "3mf"} onClick={() => doExport("3mf")} data-testid="print-export-3mf">3MF (units in file)</Button>
              <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} disabled={!orient} loading={busy === "stl"} onClick={() => doExport("stl")}>STL</Button>
            </div> : <p className="mt-2 text-[12px] text-muted">Viewers can download existing exports. Ask an engineer to create new ones.</p>}
            {exports.length > 0 && <ul className="mt-3 divide-y divide-border rounded border border-border">
              {exports.map(x => { const old = x.state === "outdated"; return (
                <li key={x.name} className={cx("flex items-center gap-2 px-2.5 py-1.5 text-[12px]", old && "bg-text/[.03]")} data-export-state={x.state ?? "current"}>
                  <FileBox className={cx("h-3.5 w-3.5 shrink-0", old ? "text-muted/60" : "text-muted")} />
                  <span className="min-w-0 flex-1"><span className={cx("block truncate", old && "text-muted line-through decoration-muted/50")}>{x.name}</span>
                    {old && <span className="block text-[11px] text-warning">{x.made_from_rev ? `From model rev ${x.made_from_rev}` : "From an earlier model"}: outdated, the part has changed. Export again.</span>}</span>
                  <span className="text-muted">{kb(x.bytes)}</span>
                  {old ? <span className="cursor-not-allowed text-muted/60" title="Made from an earlier version of the part">Download</span>
                    : <a className="link" href={`/api/m/print/${src.kind}/${src.id}/files/${encodeURIComponent(x.name)}`}>Download</a>}
                </li>); })}
            </ul>}
            <p className="mt-3 text-[11px] leading-relaxed text-muted">STL has no units; slicers assume millimetres. 3MF stores millimetres explicitly. Check the result in your slicer before printing.</p>
          </div>
          <p className="mt-3 px-1 text-[11px] leading-relaxed text-muted">{report.presets_source}</p>
        </TabPanel>
      </Tabs>
    </div>
  );
}
