import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Box as BoxIcon, Layers } from "lucide-react";
import { cx } from "@/lib/format";
import { Spinner } from "@/components/ui";
import { PrintViewer, parseMesh, thickColor, type Overlay, type PrintMesh, type ViewDir } from "./viewer";
import type { Orientation, Report } from "./types";
import type { Src } from "./index";

const OVERLAYS: { key: Overlay; label: string }[] = [
  { key: "overhang", label: "Overhangs" }, { key: "thickness", label: "Wall thickness" }, { key: "shaded", label: "Plain" },
];

function orgHeader(): Record<string, string> {
  try { const o = localStorage.getItem("fw_org"); return o ? { "X-Org": o } : {}; } catch { return {}; }
}

const rgb = (c: [number, number, number]) => `rgb(${c.map(x => Math.round(x * 255)).join(",")})`;

export function PrintViewport({ src, report, orient }: { src: Src; report: Report; orient: Orientation | null }) {
  const host = useRef<HTMLDivElement>(null);
  const eng = useRef<PrintViewer | null>(null);
  const [mesh, setMesh] = useState<PrintMesh | null>(null);
  const [loading, setLoading] = useState(false);
  const [overlay, setOverlay] = useState<Overlay>("overhang");
  const [showVol, setShowVol] = useState(true);
  const [fit, setFit] = useState<"part" | "volume">("part");
  const meshUrl = `/api/m/print/${src.kind}/${src.id}/mesh?${report.mesh_query}`;
  const t = report.thickness;
  const scale = { min: t.min_wall_mm, warn: t.warn_wall_mm, cap: t.cap_mm };
  const printer = report.process.printer_mm;

  useEffect(() => {
    const dark = document.documentElement.classList.contains("dark");
    eng.current = new PrintViewer(host.current!, dark);
    return () => { eng.current?.dispose(); eng.current = null; };
  }, []);

  useEffect(() => {
    let off = false;
    setLoading(true);
    fetch(meshUrl, { credentials: "same-origin", headers: orgHeader() })
      .then(r => { if (!r.ok) throw new Error(`Mesh request failed (${r.status})`); return r.arrayBuffer(); })
      .then(b => { if (!off) setMesh(parseMesh(b)); })
      .catch(() => { /* the analysis panel shows errors */ })
      .finally(() => { if (!off) setLoading(false); });
    return () => { off = true; };
  }, [meshUrl]);

  const first = useRef(true);
  useEffect(() => {
    const v = eng.current;
    if (!v || !mesh) return;
    v.load(mesh);
    first.current = true;
  }, [mesh]);

  const rotKey = JSON.stringify(orient?.rotation ?? null);
  const lastRot = useRef<string>("");
  const lastOverlay = useRef<Overlay>("overhang");
  useEffect(() => {
    const v = eng.current;
    if (!v || !mesh) return;
    v.setPrinter(printer, showVol);
    v.setOrientation(orient?.rotation ?? [[1, 0, 0], [0, 1, 0], [0, 0, 1]]);
    v.colour(overlay, report.overhang.angle_deg, report.overhang.bed_eps_mm, scale);
    if (first.current || lastRot.current !== rotKey || lastOverlay.current !== overlay) {
      const under = overlay === "overhang" && (orient?.overhang_area_mm2 ?? 0) > 0.5;
      if (first.current || lastRot.current !== rotKey || overlay === "overhang") v.view(under ? "Underside" : "Iso", fit);
      first.current = false; lastRot.current = rotKey; lastOverlay.current = overlay;
    }
  }, [mesh, rotKey, overlay, showVol, printer.join(","), report.overhang.angle_deg, scale.min, scale.warn, scale.cap]); // eslint-disable-line react-hooks/exhaustive-deps

  const view = (d: ViewDir) => eng.current?.view(d, fit);

  return (
    <div className="viewport-bg relative h-full w-full">
      <div ref={host} className="absolute inset-0 [&>canvas]:!h-full [&>canvas]:!w-full" data-testid="print-viewer" />
      {(loading || !mesh) && <div className="absolute inset-0 flex items-center justify-center"><Spinner className="h-6 w-6" /></div>}
      <div className="absolute left-3 right-3 top-3 flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-border bg-panel/95 p-0.5 shadow-card" role="tablist" aria-label="Overlay">
          {OVERLAYS.map(o => (
            <button key={o.key} role="tab" aria-selected={overlay === o.key} onClick={() => setOverlay(o.key)} data-overlay={o.key}
              className={cx("rounded px-2.5 py-1 text-[12px] font-medium transition", overlay === o.key ? "bg-primary text-primary-fg" : "text-muted hover:text-text")}>{o.label}</button>
          ))}
        </div>
        <div className="flex rounded-md border border-border bg-panel/95 p-0.5 shadow-card">
          {(["Iso", "Underside", "Front", "Right", "Top"] as ViewDir[]).map(d => (
            <button key={d} onClick={() => view(d)} className="rounded px-2 py-1 text-[12px] text-muted hover:bg-text/5 hover:text-text">{d}</button>
          ))}
        </div>
        <div className="flex rounded-md border border-border bg-panel/95 p-0.5 shadow-card">
          <button onClick={() => { setFit("part"); eng.current?.view("Iso", "part"); }} className={cx("inline-flex items-center gap-1 rounded px-2 py-1 text-[12px]", fit === "part" ? "text-text font-medium" : "text-muted hover:text-text")}><BoxIcon className="h-3.5 w-3.5" />Fit part</button>
          <button onClick={() => { setFit("volume"); eng.current?.view("Iso", "volume"); }} className={cx("inline-flex items-center gap-1 rounded px-2 py-1 text-[12px]", fit === "volume" ? "text-text font-medium" : "text-muted hover:text-text")}><Layers className="h-3.5 w-3.5" />Fit build volume</button>
        </div>
        <label className="flex items-center gap-1.5 rounded-md border border-border bg-panel/95 px-2.5 py-1 text-[12px] text-muted shadow-card">
          <input type="checkbox" checked={showVol} onChange={e => setShowVol(e.target.checked)} className="accent-primary" />Build volume
        </label>
      </div>

      <div className="absolute bottom-14 left-3 rounded-md border border-border bg-panel/95 px-3 py-2 text-[11.5px] shadow-card">
        {overlay === "overhang" && <div className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm bg-[#d9342b]" />Needs support beyond {report.overhang.angle_deg.toFixed(0)}° from vertical</div>}
        {overlay === "thickness" && <div className="space-y-1">
          <div className="font-medium">Wall thickness (along the inward normal)</div>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm" style={{ background: rgb(thickColor(scale.min / 2, scale)) }} />&lt; {scale.min} mm</span>
            <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm" style={{ background: rgb(thickColor((scale.min + scale.warn) / 2, scale)) }} />&lt; {scale.warn} mm</span>
            <span className="flex items-center gap-1"><span className="h-3 w-8 rounded-sm" style={{ background: `linear-gradient(90deg, ${rgb(thickColor(scale.warn, scale))}, ${rgb(thickColor(scale.cap * 0.999, scale))})` }} />{scale.warn} to {scale.cap} mm</span>
            <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-sm" style={{ background: rgb(thickColor(-1, scale)) }} />≥ {scale.cap} mm</span>
          </div>
        </div>}
        {overlay === "shaded" && <div className="text-muted">{report.source.triangles.toLocaleString()} triangles</div>}
        {orient && <div className="mt-1 text-muted">Preview: <span className="font-medium text-text">#{orient.rank} {orient.label}</span> · {orient.height_mm.toFixed(1)} mm tall</div>}
      </div>

      <div className="absolute bottom-3 left-3 right-3 flex items-start gap-2 rounded-md border border-warning/30 bg-panel/95 px-3 py-1.5 text-[11.5px] leading-snug shadow-card" data-testid="print-disclosure">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
        <span><b>Not slicer-verified.</b> {report.disclosure.replace(/^Not slicer-verified\.\s*/, "")}</span>
      </div>
    </div>
  );
}
