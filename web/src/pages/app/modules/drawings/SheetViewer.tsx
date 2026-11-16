import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { Tip } from "@/components/ui";

/**
 * Pan / zoom viewer for a drawing sheet. The SVG (generated server-side by Drawing Studio, all text escaped) is
 * inlined so it stays crisp at any zoom and its dimension tooltips work. Wheel zooms about the cursor, drag pans,
 * double-click fits the sheet.
 */
export default function SheetViewer({ svg, widthMm, heightMm, busy }: { svg: string; widthMm: number; heightMm: number; busy?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ k: 1, x: 0, y: 0 }); // k: screen px per sheet mm; x, y: sheet offset
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
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

  const fitK = (() => {
    const el = box.current;
    if (!el) return 1;
    const r = el.getBoundingClientRect();
    return Math.min((r.width - 48) / widthMm, (r.height - 48) / heightMm);
  })();

  return (
    <div ref={box} data-testid="sheet-viewer"
      className="relative h-full w-full cursor-grab select-none overflow-hidden bg-[#e9edf2] active:cursor-grabbing dark:bg-[#1b2027]"
      onPointerDown={e => { if (e.button !== 0) return; (e.target as Element).setPointerCapture?.(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, ox: off.x, oy: off.y }; }}
      onPointerMove={e => { const d = drag.current; if (d) setView(v => ({ ...v, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y })); }}
      onPointerUp={() => { drag.current = null; }}
      onDoubleClick={fit}>
      <div className="absolute left-0 top-0 bg-white shadow-[0_2px_12px_rgba(16,24,40,.18)] [&>svg]:block [&>svg]:h-full [&>svg]:w-full"
        style={{ width: widthMm * k, height: heightMm * k, transform: `translate(${off.x}px, ${off.y}px)` }}
        dangerouslySetInnerHTML={{ __html: svg }} />
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
