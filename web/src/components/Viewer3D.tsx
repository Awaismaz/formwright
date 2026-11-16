import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-dialog";
import { Box, ChevronDown, Crosshair, Eye, EyeOff, Layers, MousePointer2, Ruler, Scissors, X } from "lucide-react";
import { CadViewer } from "@/viewer/engine";
import { measure, describe, type MeasureResult } from "@/viewer/measure";
import type { Axis, DisplayMode, Pick, SketchPreview, Topo, V3, ViewName } from "@/viewer/types";
import { pickKey } from "@/viewer/types";
import { cx } from "@/lib/format";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger, Tip } from "./ui";

export type Tool = "orbit" | "measure" | "select";

export interface ViewerApi {
  setView: (v: ViewName) => void;
  setDisplay: (m: DisplayMode) => void;
  toggleSection: () => void;
  setOrtho: (ortho: boolean) => void;
  display: DisplayMode;
  section: boolean;
  ortho: boolean;
}

interface Props {
  topoUrl: string | null;
  version?: number | string;
  tool: Tool;
  onToolChange: (t: Tool) => void;
  selection: Pick[];
  onSelectionChange: (p: Pick[]) => void;
  selectKinds?: Pick["kind"][];
  highlightFaces?: number[];
  com?: V3 | null;
  sketch?: SketchPreview | null;
  compare?: { added: Topo | null; removed: Topo | null } | null;
  onTopo?: (t: Topo | null) => void;
  empty?: ReactNode;
  className?: string;
  apiRef?: { current: ViewerApi | null };
}

const DISPLAY: { mode: DisplayMode; label: string }[] = [
  { mode: "shaded-edges", label: "Shaded with edges" }, { mode: "shaded", label: "Shaded" },
  { mode: "hidden", label: "Hidden lines visible" }, { mode: "wireframe", label: "Wireframe" },
];

function useStored<T>(key: string, init: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => { try { const s = localStorage.getItem(key); return s ? JSON.parse(s) as T : init; } catch { return init; } });
  return [v, (n: T) => { setV(n); try { localStorage.setItem(key, JSON.stringify(n)); } catch { /* ignore */ } }];
}

export default function Viewer3D(props: Props) {
  const { topoUrl, version, tool, onToolChange, selection, onSelectionChange, selectKinds, highlightFaces, com, sketch, compare, onTopo, empty, className, apiRef } = props;
  const host = useRef<HTMLDivElement>(null);
  const eng = useRef<CadViewer | null>(null);
  const [topo, setTopo] = useState<Topo | null>(null);
  const [display, setDisplay] = useStored<DisplayMode>("fw_view_display", "shaded-edges");
  const [proj, setProj] = useStored<{ ortho: boolean; fov: number }>("fw_view_proj", { ortho: true, fov: 30 });
  const [section, setSection] = useState(false);
  const [axis, setAxis] = useState<Axis>("Z");
  const [secT, setSecT] = useState(0.5);
  const [flip, setFlip] = useState(false);
  const [secMm, setSecMm] = useState<number | null>(null);
  const [hover, setHover] = useState<Pick | null>(null);
  const [mpicks, setMpicks] = useState<Pick[]>([]);
  const [hidden, setHidden] = useState<number[]>([]);
  const [explode, setExplode] = useState(0);
  const loadedUrl = useRef<string | null>(null);
  const state = useRef({ tool, selection, mpicks, topo, onSelectionChange });
  state.current = { tool, selection, mpicks, topo, onSelectionChange };

  useEffect(() => {
    const dark = document.documentElement.classList.contains("dark");
    const v = new CadViewer(host.current!, dark, {
      onHover: (p) => setHover(p),
      onClick: (p, additive) => {
        const s = state.current;
        if (s.tool === "measure") {
          if (!p) { setMpicks([]); return; }
          setMpicks(prev => (prev.length >= 2 ? [p] : [...prev, p]));
        } else if (s.tool === "select") {
          if (!p) { if (!additive) s.onSelectionChange([]); return; }
          const k = pickKey(p);
          const exists = s.selection.some(x => pickKey(x) === k);
          s.onSelectionChange(additive ? (exists ? s.selection.filter(x => pickKey(x) !== k) : [...s.selection, p]) : [p]);
        }
      },
    });
    eng.current = v;
    v.setProjection(proj.ortho, proj.fov);
    return () => { v.dispose(); eng.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!topoUrl) { setTopo(null); onTopo?.(null); loadedUrl.current = null; return; }
    let cancel = false;
    if (version === "keep" && loadedUrl.current === topoUrl) return () => {}; // failed build: keep last good geometry
    fetch(`${topoUrl}${topoUrl.includes("?") ? "&" : "?"}v=${version ?? 0}`).then(r => (r.ok ? r.json() : null)).then((t: Topo | null) => {
      if (cancel || !t || !eng.current) return;
      eng.current.load(t, loadedUrl.current === topoUrl);
      loadedUrl.current = topoUrl;
      setTopo(t); onTopo?.(t); setMpicks([]);
    }).catch(() => {});
    return () => { cancel = true; };
  }, [topoUrl, version]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { eng.current?.setDisplay(display); }, [display, topo]);
  useEffect(() => { eng.current?.setProjection(proj.ortho, proj.fov); }, [proj.ortho, proj.fov]);
  useEffect(() => { const v = eng.current?.setSection(section, axis, secT, flip); setSecMm(section && v !== undefined ? v : null); }, [section, axis, secT, flip, topo]);
  useEffect(() => {
    const kinds: Pick["kind"][] = tool === "orbit" ? [] : tool === "measure" ? ["vertex", "center", "edge", "face"] : selectKinds ?? ["vertex", "center", "edge", "face"];
    eng.current?.setPicking(kinds);
    if (tool !== "measure") setMpicks([]);
  }, [tool, selectKinds, topo]);
  useEffect(() => { eng.current?.setSelection(tool === "measure" ? mpicks : selection); }, [selection, mpicks, tool, topo]);
  useEffect(() => { eng.current?.highlightFaces(highlightFaces ?? []); }, [highlightFaces, topo]);
  useEffect(() => { eng.current?.setCenterOfMass(com ?? null); }, [com, topo]);
  useEffect(() => { eng.current?.setSketchPreview(sketch ?? null); }, [sketch, topo]);
  useEffect(() => { eng.current?.setOverlay(compare?.added ?? null, compare?.removed ?? null); eng.current?.setGhost(!!compare); }, [compare, topo]);
  useEffect(() => { eng.current?.setHiddenParts(hidden); }, [hidden, topo]);
  useEffect(() => { eng.current?.setExplode(explode); }, [explode, topo]);

  if (apiRef) apiRef.current = {
    setView: (v) => eng.current?.setView(v), setDisplay, toggleSection: () => setSection(!section),
    setOrtho: (o) => setProj({ ...proj, ortho: o }), display, section, ortho: proj.ortho,
  };

  const result: MeasureResult | null = useMemo(() => (topo && tool === "measure" ? measure(mpicks, topo) : null), [mpicks, topo, tool]);
  useEffect(() => { eng.current?.setMeasureLine(result?.line?.[0] ?? null, result?.line?.[1] ?? null); }, [result]);
  const multi = (topo?.solids.length ?? 0) > 1;

  const btn = (active: boolean, onClick: () => void, icon: ReactNode, label: string) => (
    <Tip content={label} side="bottom">
      <button onClick={onClick} aria-pressed={active} aria-label={label}
        className={cx("rounded p-1.5 transition", active ? "bg-primary text-white" : "text-muted hover:bg-text/5 hover:text-text")}>{icon}</button>
    </Tip>
  );
  const view = (v: ViewName) => <button key={v} onClick={() => eng.current?.setView(v)} className="rounded px-2 py-1 text-[12px] text-muted hover:bg-text/5 hover:text-text">{v}</button>;

  return (
    <div className={cx("viewport-bg relative h-full w-full overflow-hidden", className)} data-tour="viewer">
      <div ref={host} className="absolute inset-0 [&>canvas]:h-full [&>canvas]:w-full" />
      {!topo && <div className="absolute inset-0 flex items-center justify-center">{empty}</div>}

      {/* toolbar */}
      <div className="absolute left-3 top-3 flex flex-wrap items-center gap-0.5 rounded-lg border border-border bg-panel/95 p-1 shadow-card">
        {(["Iso", "Front", "Top", "Right"] as ViewName[]).map(view)}
        <Menu>
          <MenuTrigger asChild><button className="rounded px-1 py-1 text-muted hover:bg-text/5" aria-label="More views"><ChevronDown className="h-3.5 w-3.5" /></button></MenuTrigger>
          <MenuContent align="start">{(["Back", "Left", "Bottom"] as ViewName[]).map(v => <MenuItem key={v} onSelect={() => eng.current?.setView(v)}>{v}</MenuItem>)}</MenuContent>
        </Menu>
        <span className="mx-1 h-5 w-px bg-border" />
        <Popover.Root>
          <Tip content={proj.ortho ? "Orthographic (CAD) — click for perspective options" : "Perspective — click for options"} side="bottom">
            <Popover.Trigger asChild>
              <button className={cx("rounded px-2 py-1 text-[12px] font-medium", !proj.ortho ? "bg-primary text-white" : "text-muted hover:bg-text/5 hover:text-text")}>{proj.ortho ? "Ortho" : "Persp"}</button>
            </Popover.Trigger>
          </Tip>
          <Popover.Portal>
            <Popover.Content className="fixed left-1/2 top-1/3 z-50 w-72 -translate-x-1/2 rounded-lg border border-border bg-panel p-4 shadow-pop">
              <Popover.Title className="text-sm font-semibold">Projection</Popover.Title>
              <div className="mt-3 inline-flex overflow-hidden rounded border border-border text-sm">
                {[[true, "Orthographic"], [false, "Perspective"]].map(([o, l]) => (
                  <button key={String(o)} onClick={() => setProj({ ...proj, ortho: o as boolean })}
                    className={cx("px-3 py-1", proj.ortho === o ? "bg-primary text-white" : "text-muted")}>{l as string}</button>))}
              </div>
              <label className="mt-4 block text-[13px]">Perspective strength <span className="text-muted">({proj.fov}° field of view)</span></label>
              <input type="range" min={10} max={70} step={1} value={proj.fov} onChange={e => setProj({ ortho: false, fov: +e.target.value })} className="mt-2 w-full" aria-label="Perspective strength" />
              <p className="mt-2 text-xs text-muted">Orthographic is the CAD default: parallel lines stay parallel and Front/Top/Right are true projections.</p>
              <Popover.Close className="mt-3 rounded border border-border px-3 py-1 text-sm hover:bg-text/5">Done</Popover.Close>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
        <Menu>
          <MenuTrigger asChild>
            <button className="flex items-center gap-1 rounded px-1.5 py-1 text-muted hover:bg-text/5 hover:text-text" aria-label="Display style"><Box className="h-4 w-4" /><ChevronDown className="h-3 w-3" /></button>
          </MenuTrigger>
          <MenuContent align="start">
            <MenuLabel>Display style</MenuLabel>
            {DISPLAY.map(d => <MenuItem key={d.mode} onSelect={() => setDisplay(d.mode)}>{d.label}{display === d.mode && <span className="ml-auto text-primary">●</span>}</MenuItem>)}
          </MenuContent>
        </Menu>
        {btn(section, () => setSection(!section), <Scissors className="h-4 w-4" />, "Section view")}
        <span className="mx-1 h-5 w-px bg-border" />
        {btn(tool === "measure", () => onToolChange(tool === "measure" ? "orbit" : "measure"), <Ruler className="h-4 w-4" />, "Measure (snaps to vertices, edges, centres, faces)")}
        {btn(tool === "select", () => onToolChange(tool === "select" ? "orbit" : "select"), <MousePointer2 className="h-4 w-4" />, "Select faces/edges (Ctrl+click to add)")}
        {multi && <Menu>
          <MenuTrigger asChild><button className="flex items-center gap-1 rounded px-1.5 py-1 text-muted hover:bg-text/5" aria-label="Parts"><Layers className="h-4 w-4" /><ChevronDown className="h-3 w-3" /></button></MenuTrigger>
          <MenuContent align="start" className="w-64">
            <MenuLabel>Parts ({topo!.solids.length})</MenuLabel>
            {topo!.solids.map(s => (
              <button key={s.id} onClick={() => setHidden(hidden.includes(s.id) ? hidden.filter(x => x !== s.id) : [...hidden, s.id])}
                className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm hover:bg-primary-soft">
                {hidden.includes(s.id) ? <EyeOff className="h-4 w-4 text-muted" /> : <Eye className="h-4 w-4 text-primary" />}
                <span className="flex-1 truncate">{s.label}</span><span className="text-xs text-muted">{(s.volume / 1000).toFixed(1)} cm³</span>
              </button>))}
            <div className="px-2.5 pb-2 pt-1"><div className="text-xs text-muted">Explode</div>
              <input type="range" min={0} max={1.5} step={0.01} value={explode} onChange={e => setExplode(+e.target.value)} className="w-full" aria-label="Explode" /></div>
          </MenuContent>
        </Menu>}
      </div>

      {tool !== "orbit" && hover && topo && (
        <div className="pointer-events-none absolute left-3 top-14 rounded-md bg-chrome/90 px-2.5 py-1 text-[11.5px] text-chrome-fg shadow-card">
          <Crosshair className="mr-1 inline h-3 w-3" />{describe(hover, topo)}
        </div>)}

      {section && (
        <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-panel/95 px-3 py-1.5 text-xs shadow-card">
          <Scissors className="h-3.5 w-3.5 text-muted" />
          <span className="inline-flex overflow-hidden rounded border border-border">
            {(["X", "Y", "Z"] as Axis[]).map(a => <button key={a} onClick={() => setAxis(a)} className={cx("px-2 py-0.5 font-semibold", axis === a ? "bg-primary text-white" : "text-muted hover:bg-text/5")}>{a}</button>)}
          </span>
          <input type="range" min={0} max={1} step={0.002} value={secT} onChange={e => setSecT(+e.target.value)} aria-label="Section position" />
          <span className="w-24 tabular-nums text-text">{axis} = {secMm !== null ? secMm.toFixed(2) : "—"} mm</span>
          <button onClick={() => setFlip(!flip)} className="rounded border border-border px-2 py-0.5 hover:bg-text/5" title="Keep the other side">Flip</button>
        </div>)}

      {tool === "measure" && (
        <div className="absolute bottom-3 right-3 w-72 rounded-lg border border-border bg-panel/95 shadow-card">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="flex items-center gap-1.5 text-[13px] font-semibold"><Ruler className="h-4 w-4 text-primary" />Measure</span>
            <button onClick={() => setMpicks([])} className="rounded p-0.5 text-muted hover:bg-text/5" aria-label="Clear measurement"><X className="h-3.5 w-3.5" /></button>
          </div>
          {result ? (
            <div className="px-3 py-2 text-[12.5px]">
              <div className="mb-1.5 text-[11.5px] text-muted">{result.title}</div>
              {result.rows.map(r => <div key={r.label} className="flex justify-between py-0.5"><span className="text-muted">{r.label}</span>
                <span className={cx("tabular-nums", r.primary && "text-[14px] font-semibold text-primary")}>{r.value}</span></div>)}
              {mpicks.length === 1 && <div className="mt-1.5 text-[11px] text-muted">Pick a second entity to measure between them.</div>}
            </div>
          ) : <div className="px-3 py-3 text-[12px] text-muted">Hover to snap to a vertex, edge, circle centre or face, then click. Pick two to measure between them.</div>}
        </div>)}
    </div>
  );
}
