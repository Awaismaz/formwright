import { useEffect, useRef, useState } from "react";
import { Expand, Maximize } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Spinner, Tip } from "@/components/ui";
import type { Topo } from "@/viewer/types";
import { AssemblyViewer, type AsmPick, type AsmView as ViewName, type FaceMark } from "./viewer";
import type { AsmView, V3 } from "./types";

const VIEWS: ViewName[] = ["Iso", "Front", "Top", "Right"];
/** Part topology loaded by the viewport (shared with panels that describe picks). */
export const topoCache = new Map<string, Topo>();

export interface ViewportProps {
  view: AsmView;
  picking: ("face" | "edge")[];
  picks: AsmPick[];
  marks: FaceMark[];
  selected: string[];
  ghost: Set<string> | null;
  clashes: { pos: number[]; idx: number[] }[];
  clashFocus: number | null;
  measure: [V3, V3] | null;
  explode: number;
  onExplode: (f: number) => void;
  onPick: (p: AsmPick | null, e: PointerEvent) => void;
  hint?: string | null;
  describe?: (p: AsmPick) => string | null;
  /** When set (the assembly revision), take an isometric snapshot once the parts are in place. */
  thumbKey?: number | null;
  onThumb?: (png: string, key: number) => void;
}

export function Viewport(props: ViewportProps) {
  const { view, picking, picks, marks, selected, ghost, clashes, clashFocus, measure, explode, onExplode, onPick, hint, describe, thumbKey, onThumb } = props;
  const host = useRef<HTMLDivElement>(null);
  const eng = useRef<AssemblyViewer | null>(null);
  const [loaded, setLoaded] = useState(0);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<AsmPick | null>(null);
  const cbs = useRef({ onPick, describe });
  cbs.current = { onPick, describe };

  useEffect(() => {
    const v = new AssemblyViewer(host.current!, document.documentElement.classList.contains("dark"));
    v.onClick = (p, e) => cbs.current.onPick(p, e);
    v.onHover = p => setHover(p);
    eng.current = v;
    (window as unknown as { __fwAsm?: AssemblyViewer }).__fwAsm = v;
    return () => { v.dispose(); eng.current = null; };
  }, []);

  // load topology of every part once, then place instances
  useEffect(() => {
    const v = eng.current;
    if (!v) return;
    const missing = Object.values(view.parts).filter(p => !v.hasPart(p.key));
    if (!missing.length) { setLoaded(n => n + 1); return; }
    let cancelled = false;
    setLoading(true);
    Promise.all(missing.map(p => api.get<Topo>(p.topo_url).then(t => { topoCache.set(p.key, t); if (!cancelled) v.addPart(p.key, t); })))
      .finally(() => { if (!cancelled) { setLoading(false); setLoaded(n => n + 1); } });
    return () => { cancelled = true; };
  }, [view.parts]);

  useEffect(() => {
    eng.current?.setInstances(view.instances.map(i => ({ id: i.id, part: i.part, T: i.T, visible: i.visible, fastener: !!i.group })));
    eng.current?.setExplode(view.explode, explode);
  }, [view.instances, view.explode, loaded, explode]);
  useEffect(() => { eng.current?.setPicking(picking); }, [picking]);
  useEffect(() => { eng.current?.setPicks(picks); }, [picks, loaded, view.instances, explode]);
  useEffect(() => { eng.current?.setMarks(marks); }, [marks, loaded, view.instances, explode]);
  useEffect(() => { eng.current?.setSelected(selected); }, [selected, loaded]);
  useEffect(() => { eng.current?.setGhost(ghost); }, [ghost, loaded]);
  useEffect(() => { eng.current?.setClashes(clashes, clashFocus); }, [clashes, clashFocus, loaded]);
  useEffect(() => { eng.current?.setMeasure(measure?.[0] ?? null, measure?.[1] ?? null); }, [measure, loaded]);

  const thumbCb = useRef(onThumb);
  thumbCb.current = onThumb;
  useEffect(() => {
    if (thumbKey === null || thumbKey === undefined || loading) return;
    const t = setTimeout(() => {
      const png = eng.current?.thumbnail();
      if (png) thumbCb.current?.(png, thumbKey);
    }, 1500);
    return () => clearTimeout(t);
  }, [thumbKey, loading, loaded]);

  const hoverText = hover && describe ? describe(hover) : null;
  return (
    <div className="viewport-bg relative h-full min-h-[420px] w-full overflow-hidden">
      <div ref={host} className="absolute inset-0" data-testid="asm-viewport" />
      <div className="absolute left-3 top-3 flex items-center gap-1 rounded-md border border-border bg-panel/95 p-0.5 shadow-card">
        {VIEWS.map(n => (
          <button key={n} type="button" onClick={() => eng.current?.setView(n)}
            className="rounded px-2 py-1 text-[12px] font-medium text-muted hover:bg-text/5 hover:text-text">{n}</button>
        ))}
        <div className="mx-0.5 h-4 w-px bg-border" />
        <Tip content="Zoom to fit" side="bottom">
          <button type="button" onClick={() => eng.current?.fit()} className="rounded p-1 text-muted hover:bg-text/5 hover:text-text"><Maximize className="h-3.5 w-3.5" /></button>
        </Tip>
      </div>
      {(hint || hoverText) && (
        <div className="pointer-events-none absolute left-1/2 top-3 max-w-[60%] -translate-x-1/2 truncate rounded-full border border-border bg-panel/95 px-3 py-1 text-[12px] text-muted shadow-card">
          {hoverText ?? hint}
        </div>
      )}
      <div className="absolute bottom-3 left-1/2 flex w-[min(380px,70%)] -translate-x-1/2 items-center gap-3 rounded-full border border-border bg-panel/95 px-3.5 py-1.5 shadow-card">
        <Expand className={cx("h-4 w-4 shrink-0", explode > 0 ? "text-primary" : "text-muted")} />
        <span className="text-[12px] font-medium text-muted">Explode</span>
        <input type="range" min={0} max={100} value={Math.round(explode * 100)} aria-label="Explode"
          onChange={e => onExplode(Number(e.target.value) / 100)} className="h-1 flex-1 accent-[rgb(var(--primary))]" data-testid="explode" />
        <span className="w-9 text-right text-[12px] tabular-nums text-muted">{Math.round(explode * 100)}%</span>
      </div>
      {loading && <div className="absolute right-3 top-3 flex items-center gap-2 rounded-full border border-border bg-panel/95 px-3 py-1 text-xs text-muted shadow-card"><Spinner className="h-3.5 w-3.5" />Loading parts…</div>}
    </div>
  );
}
