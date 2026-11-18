import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { Tip } from "@/components/ui";

/**
 * Pan / zoom viewer for a drawing sheet. The SVG (generated server-side by Drawing Studio, all text escaped) is
 * inlined so it stays crisp at any zoom and its dimension tooltips work. Wheel zooms about the cursor, drag pans,
 * double-click fits the sheet.
 */
export default function SheetViewer({ svg, widthMm, heightMm, busy, highlight, onPick, pickHint }: {
  svg: string; widthMm: number; heightMm: number; busy?: boolean;
  /** pick mode: a click (not a drag) reports the sheet point in paper millimetres */
  onPick?: (x: number, y: number) => void; pickHint?: string;
  /** A dimension / callout id to locate on the sheet: it is coloured and brought to the centre. */
  highlight?: { id: string; n: number } | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ k: 1, x: 0, y: 0 }); // k: screen px per sheet mm; x, y: sheet offset
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const down = useRef<{ x: number; y: number } | null>(null);
  const { k } = view;
  const off = { x: view.x, y: view.y };

  const fit = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const kk = Math.min((r.width - 48) / widthMm, (r.height - 48) / heightMm);
    const z = Math.max(0.2, kk);
    setView({ k: z, x: (r.width - widthMm * z) / 2, y: (r.height - heightMm * z) / 2 });
  }, [widthMm, heightMm]);

  useLayoutEffect(() => { fit(); }, [fit]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  const zoomAt = useCallback((factor: number, cx?: number, cy?: number) => {
    const el = box.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = cx ?? r.width / 2, py = cy ?? r.height / 2;
    setView(v => {
      const nk = Math.min(40, Math.max(0.2, v.k * factor));
      return { k: nk, x: px - (px - v.x) * (nk / v.k), y: py - (py - v.y) * (nk / v.k) };
    });
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // locate a dimension picked in the side panel: colour its value(s) and centre the first one
  useEffect(() => {
    const el = sheet.current, outer = box.current;
    if (!el || !outer) return;
    el.querySelectorAll(".drw-hl").forEach(n => n.classList.remove("drw-hl"));
    if (!highlight) return;
    const hits = Array.from(el.querySelectorAll(`[data-ref="${CSS.escape(highlight.id)}"]`));
    if (!hits.length) return;
    hits.forEach(n => n.classList.add("drw-hl"));
    const r = hits[0]!.getBoundingClientRect(), o = outer.getBoundingClientRect();
    const cx = r.left + r.width / 2 - o.left, cy = r.top + r.height / 2 - o.top;
    setView(v => {
      const nk = Math.max(v.k, Math.min(40, (o.width - 48) / widthMm * 2.2));
      const sx = (cx - v.x) / v.k, sy = (cy - v.y) / v.k; // sheet mm under the value
      return { k: nk, x: o.width / 2 - sx * nk, y: o.height / 2 - sy * nk };
    });
  }, [highlight, svg, widthMm]);

  const fitK = (() => {
    const el = box.current;
    if (!el) return 1;
    const r = el.getBoundingClientRect();
    return Math.min((r.width - 48) / widthMm, (r.height - 48) / heightMm);
  })();

  return (
    <div ref={box} data-testid="sheet-viewer"
      className={`relative h-full w-full select-none overflow-hidden bg-[#e9edf2] dark:bg-[#1b2027] ${onPick ? "cursor-crosshair" : "cursor-grab active:cursor-grabbing"}`}
      data-pick={onPick ? "1" : undefined}
      onPointerDown={e => { if (e.button !== 0) return; (e.target as Element).setPointerCapture?.(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, ox: off.x, oy: off.y }; down.current = { x: e.clientX, y: e.clientY }; }}
      onPointerMove={e => { const d = drag.current; if (d) setView(v => ({ ...v, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y })); }}
      onPointerUp={e => {
        drag.current = null;
        const d0 = down.current; down.current = null;
        if (onPick && d0 && Math.hypot(e.clientX - d0.x, e.clientY - d0.y) < 4 && box.current) {
          const r = box.current.getBoundingClientRect();
          onPick((e.clientX - r.left - view.x) / view.k, (e.clientY - r.top - view.y) / view.k);
        }
      }}
      onDoubleClick={fit}>
      <style>{".drw-hl{fill:#d97706 !important;font-weight:700;paint-order:stroke;stroke:#fde68a;stroke-width:1.2px}"}</style>
      <div ref={sheet} className="absolute left-0 top-0 bg-white shadow-[0_2px_12px_rgba(16,24,40,.18)] [&>svg]:block [&>svg]:h-full [&>svg]:w-full"
        style={{ width: widthMm * k, height: heightMm * k, transform: `translate(${off.x}px, ${off.y}px)` }}
        dangerouslySetInnerHTML={{ __html: svg }} />
      {onPick && pickHint && <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full border border-primary/40 bg-panel px-3 py-1 text-[12px] text-primary shadow-card" data-testid="pick-hint">{pickHint}</div>}
      {busy && <div className="pointer-events-none absolute inset-0 bg-white/30 backdrop-blur-[1px] dark:bg-black/20" />}
      <div className="absolute bottom-3 right-3 flex items-center gap-0.5 rounded-md border border-border bg-panel/95 p-0.5 shadow-card"
        onPointerDown={e => e.stopPropagation()} onDoubleClick={e => e.stopPropagation()}>
        <Tip content="Zoom out" side="top"><button className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Zoom out" onClick={() => zoomAt(1 / 1.25)}><ZoomOut className="h-4 w-4" /></button></Tip>
        <span className="w-12 text-center text-[11.5px] tabular-nums text-muted">{Math.round((k / Math.max(fitK, 0.01)) * 100)}%</span>
        <Tip content="Zoom in" side="top"><button className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Zoom in" onClick={() => zoomAt(1.25)}><ZoomIn className="h-4 w-4" /></button></Tip>
        <Tip content="Fit sheet (double-click)" side="top"><button className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Fit sheet" onClick={fit}><Maximize2 className="h-4 w-4" /></button></Tip>
      </div>
    </div>
  );
}
