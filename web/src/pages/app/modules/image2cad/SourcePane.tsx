import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Layers, Maximize2, Minus, Plus } from "lucide-react";
import { cx } from "@/lib/format";
import { spreadPins } from "./pins";

/** ``corner``: the pin marks the top-right corner of a text box (so the text stays visible), else its centre. */
export interface Pin { id: string; x: number; y: number; n: number; title: string; tone: "read" | "ask" | "ref" | "off" | "done"; corner?: boolean }
interface Box { id: string; box: number[]; label: string }

const TONE: Record<Pin["tone"], string> = {
  read: "bg-primary text-white border-white",
  ask: "bg-warning text-white border-white",
  ref: "bg-[#111827] text-white border-accent ring-4 ring-accent/35",
  off: "bg-[#9aa3af] text-white border-white",
  done: "bg-success text-white border-white",
};

/** The uploaded drawing / image with every reading pinned where it was found. Wheel to zoom, drag to pan. */
export default function SourcePane({ src, pins, boxes, hot, onHot, onPick }: {
  src: string; pins: Pin[]; boxes: Box[]; hot: string | null; onHot: (id: string | null) => void; onPick: (id: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [view, setView] = useState({ z: 1, x: 0, y: 0 });
  const [showViews, setShowViews] = useState(true);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const shift = useMemo(() => (nat ? spreadPins(pins, nat.w, nat.h, view.z) : {}), [pins, nat, view.z]);

  const fit = useCallback(() => {
    const el = wrap.current;
    if (!el || !nat) return;
    const pad = 24;
    const z = Math.min((el.clientWidth - pad * 2) / nat.w, (el.clientHeight - pad * 2) / nat.h);
    setView({ z, x: (el.clientWidth - nat.w * z) / 2, y: (el.clientHeight - nat.h * z) / 2 });
  }, [nat]);
  useEffect(() => { fit(); }, [fit]);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  const zoomAt = (factor: number, cx0?: number, cy0?: number) => {
    const el = wrap.current;
    if (!el) return;
    const px = cx0 ?? el.clientWidth / 2;
    const py = cy0 ?? el.clientHeight / 2;
    setView(v => {
      const z = Math.min(Math.max(v.z * factor, 0.05), 12);
      const k = z / v.z;
      return { z, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
    });
  };

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  return (
    <div ref={wrap} className="relative h-full w-full cursor-grab touch-none select-none overflow-hidden bg-[#e3e8ee] active:cursor-grabbing dark:bg-[#171b21]"
      data-testid="source-pane"
      onPointerDown={e => { if ((e.target as HTMLElement).closest("[data-pin]")) return; drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
      onPointerMove={e => { const d = drag.current; if (!d) return; d.moved = true; setView(v => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y })); }}
      onPointerUp={() => { drag.current = null; }}>
      <div className="pointer-events-none absolute inset-0 opacity-50 [background-image:radial-gradient(rgb(var(--border))_1px,transparent_1px)] [background-size:18px_18px]" />
      <div className="absolute left-0 top-0 origin-top-left" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`, width: nat?.w, height: nat?.h }}>
        <img src={src} alt="Uploaded drawing" draggable={false} onLoad={e => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
          className="block max-w-none bg-white shadow-[0_2px_12px_rgb(16_24_40/.18)]" style={{ width: nat?.w, height: nat?.h }} />
        {nat && showViews && boxes.map(b => (
          <div key={b.id} className="pointer-events-none absolute border border-dashed border-primary/50 bg-primary/[.03]"
            style={{ left: `${b.box[0]! * 100}%`, top: `${b.box[1]! * 100}%`, width: `${(b.box[2]! - b.box[0]!) * 100}%`, height: `${(b.box[3]! - b.box[1]!) * 100}%` }}>
            <span className="absolute -top-px left-0 origin-bottom-left -translate-y-full whitespace-nowrap rounded-t bg-primary/80 px-1.5 py-px text-[11px] font-medium text-white"
              style={{ transform: `translateY(-100%) scale(${1 / view.z})` }}>{b.label}</span>
          </div>
        ))}
        {nat && pins.map(p => (
          <button key={p.id} type="button" data-pin={p.id} title={p.title} aria-label={p.title}
            onMouseEnter={() => onHot(p.id)} onMouseLeave={() => onHot(null)} onClick={() => onPick(p.id)}
            className="absolute" style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%`, transformOrigin: p.corner ? "0 100%" : "50% 50%",
              transform: `translateX(${(shift[p.id] ?? 0) / view.z}px) ` + (p.corner ? `translate(-4px, -100%) scale(${1 / view.z})` : `translate(-50%, -50%) scale(${1 / view.z})`) }}>
            <span className={cx("flex h-[20px] min-w-[20px] items-center justify-center rounded-full border-2 px-1 text-[10.5px] font-bold shadow-md transition-transform",
              TONE[p.tone], hot === p.id && "scale-[1.35]", p.tone === "ask" && "animate-[pulse_2s_ease-in-out_infinite]")}>
              {p.n || (p.tone === "done" ? "✓" : "?")}
            </span>
          </button>
        ))}
      </div>
      <div className="absolute bottom-3 left-3 flex items-center gap-1 rounded-lg border border-border bg-panel/95 p-1 shadow-card">
        <button type="button" className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Zoom out" onClick={() => zoomAt(1 / 1.25)}><Minus className="h-4 w-4" /></button>
        <span className="w-11 text-center text-[11.5px] tabular-nums text-muted">{Math.round(view.z * 100)}%</span>
        <button type="button" className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Zoom in" onClick={() => zoomAt(1.25)}><Plus className="h-4 w-4" /></button>
        <button type="button" className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Fit" title="Fit" onClick={fit}><Maximize2 className="h-4 w-4" /></button>
        {boxes.length > 0 && <button type="button" className={cx("rounded p-1.5 hover:bg-text/5", showViews ? "text-primary" : "text-muted")} aria-label="Show views" title="Show view regions" onClick={() => setShowViews(s => !s)}><Layers className="h-4 w-4" /></button>}
      </div>
      <div className="absolute bottom-3 right-3 flex items-center gap-3 rounded-lg border border-border bg-panel/95 px-2.5 py-1.5 text-[11.5px] text-muted shadow-card">
        <Legend cls="bg-primary" label="Read" /><Legend cls="bg-warning" label="Needs you" /><Legend cls="bg-[#111827] ring-2 ring-accent" label="Reference" /><Legend cls="bg-[#9aa3af]" label="Left out" />
      </div>
    </div>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return <span className="inline-flex items-center gap-1"><span className={cx("h-2.5 w-2.5 rounded-full", cls)} />{label}</span>;
}
