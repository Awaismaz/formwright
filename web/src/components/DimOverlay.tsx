import { useEffect, useMemo, useRef, useState } from "react";
import type { CadViewer } from "@/viewer/engine";
import { checkEdit, layout, placeLabels, resolveDims, type DimDraw, type DimSpec } from "@/viewer/dims";
import type { Topo, V3 } from "@/viewer/types";
import { cx } from "@/lib/format";

export interface ParamMeta { min?: number; max?: number; step?: number; unit?: string; label?: string; help?: string }
export interface DimOverlayProps {
  specs: DimSpec[];
  values: Record<string, number>;
  meta: Record<string, ParamMeta>;
  /** parameters that take whole numbers only */
  whole: string[];
  hover: string | null;
  onHover: (param: string | null) => void;
  /** apply an on-screen edit (the parameter rebuild path); undefined = view only */
  onEdit?: (param: string, value: number) => void;
  busy?: boolean;
}

const LABEL_H = 18;
/** the parameter's friendly name (as the Params panel writes it), never the script variable as such */
const nameOf = (k: string, m?: ParamMeta) => m?.label ?? k.replace(/_/g, " ").toLowerCase().replace(/^\w/, c => c.toUpperCase());
const labelW = (t: string) => t.length * 7 + 12;

function arrowPath(a: { x: number; y: number; dx: number; dy: number }) {
  const L = 7, W = 2.6, bx = a.x - a.dx * L, by = a.y - a.dy * L, nx = -a.dy * W, ny = a.dx * W;
  return `M${a.x},${a.y}L${bx + nx},${by + ny}L${bx - nx},${by - ny}Z`;
}

/** Design parameters as CAD dimensions over the 3D view: screen-space, follows the camera, click a value to edit. */
export default function DimOverlay({ eng, topo, specs, values, meta, whole, hover, onHover, onEdit, busy }: DimOverlayProps & { eng: CadViewer; topo: Topo }) {
  const [, setTick] = useState(0);
  const dirs = useRef(new Map<string, V3>());
  const [edit, setEdit] = useState<{ param: string; text: string; error?: string } | null>(null);
  useEffect(() => eng.onView(() => setTick(t => (t + 1) % 1_000_000)), [eng]);
  useEffect(() => { if (busy) setEdit(null); }, [busy]);
  const resolved = useMemo(() => resolveDims(specs, topo, values), [specs, topo, values]);
  const units = useMemo(() => Object.fromEntries(Object.entries(meta).map(([k, m]) => [k, m.unit])), [meta]);

  const cam = eng.viewCam();
  const draws: DimDraw[] = layout(resolved, cam, { bbox: topo.bbox, values, units, dirs: dirs.current });
  // a stable order (never by hover: a label that moved away from the cursor would flicker)
  const spots = placeLabels(draws.map(d => ({ x: d.lx, y: d.ly, w: labelW(d.text), h: LABEL_H, angle: d.angle })), { width: cam.width, height: cam.height });

  const start = (param: string) => {
    if (!onEdit || busy) return;
    setEdit({ param, text: String(values[param]) });
  };
  const commit = () => {
    if (!edit || !onEdit) return;
    const r = checkEdit(edit.text, whole.includes(edit.param), { ...meta[edit.param], label: nameOf(edit.param, meta[edit.param]) });
    if (!r.ok) { setEdit({ ...edit, error: r.error }); return; }
    setEdit(null);
    if (r.value !== values[edit.param]) onEdit(edit.param, r.value);
  };

  return (
    <div className="pointer-events-none absolute inset-0 z-[5] overflow-hidden" data-dims>
      <svg className="absolute inset-0 h-full w-full" aria-hidden>
        {draws.map((d, i) => {
          const on = d.param === hover || d.param === edit?.param;
          const col = on ? "rgb(var(--primary))" : "rgb(var(--text) / 0.72)";
          return (
            <g key={`${d.param}-${i}`} style={{ stroke: col, fill: col }}>
              {d.lines.map((l, j) => <line key={j} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} strokeWidth={on ? 1.6 : 1} />)}
              {d.arrows.map((a, j) => <path key={j} d={arrowPath(a)} strokeWidth={0.5} />)}
            </g>);
        })}
      </svg>
      {draws.map((d, i) => {
        const p = spots[i]!;
        const m = meta[d.param] ?? {};
        const on = d.param === hover;
        if (edit?.param === d.param) {
          const range = m.min !== undefined || m.max !== undefined ? `${m.min ?? "−∞"} to ${m.max ?? "∞"}${m.unit ? ` ${m.unit}` : ""}` : null;
          return (
            <div key={`${d.param}-${i}`} className="pointer-events-auto absolute z-10 -translate-x-1/2 -translate-y-1/2 rounded-md border border-primary bg-panel p-1 shadow-pop" style={{ left: p.x, top: p.y }} data-dim-edit={d.param}>
              <input autoFocus value={edit.text} inputMode="decimal" aria-label={`${nameOf(d.param, m)} value`}
                onFocus={e => e.currentTarget.select()}
                onChange={e => setEdit({ param: d.param, text: e.target.value })}
                onKeyDown={e => { e.stopPropagation(); if (e.key === "Enter") commit(); else if (e.key === "Escape") setEdit(null); }}
                onBlur={() => setEdit(null)}
                className={cx("h-7 w-24 rounded border bg-panel px-1.5 text-right font-mono text-[12.5px] outline-none", edit.error ? "border-danger text-danger" : "border-border focus:border-primary")} />
              <div className="mt-0.5 whitespace-nowrap px-0.5 text-[10.5px] text-muted">
                {edit.error ? <span className="text-danger">{edit.error}</span> : <>{nameOf(d.param, m)}{range && <> · {range}</>} · Enter / Esc</>}
              </div>
            </div>);
        }
        return (
          <div key={`${d.param}-${i}`} className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: p.x, top: p.y }}>
            {on && <div className="pointer-events-none absolute bottom-full left-1/2 mb-1 -translate-x-1/2 whitespace-nowrap rounded bg-chrome/90 px-1.5 py-0.5 text-[11px] text-chrome-fg shadow-card">
              {nameOf(d.param, m)}{onEdit ? (busy ? " · rebuilding…" : " · click to edit") : " · view only"}</div>}
            <button type="button" data-dim={d.param}
              onPointerEnter={() => onHover(d.param)} onPointerLeave={() => onHover(null)}
              onPointerDown={e => e.stopPropagation()}
              onClick={() => start(d.param)}
              className={cx("pointer-events-auto block whitespace-nowrap rounded border px-1 font-mono text-[12px] leading-[16px] tabular-nums shadow-sm transition-colors",
                on ? "border-primary bg-primary text-white" : "border-border/70 bg-panel/90 text-text hover:border-primary",
                onEdit && !busy ? "cursor-text" : "cursor-default")}>
              {d.text}
            </button>
          </div>);
      })}
    </div>
  );
}
