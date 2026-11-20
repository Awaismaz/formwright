import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Box, Loader2, Maximize2, Ruler } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge } from "@/components/ui";
import { layout, placeLabels, type DimDraw } from "@/viewer/dims";
import type { V3 } from "@/viewer/types";
import { BASE } from "../api";
import type { Plan, Program } from "../types";
import { ERROR_COLOR, PATH_COLOR, PATH_LABEL, sig, toResolved, visibleDims, withPaths, worldBounds } from "./build";
import { PreviewScene, type PreviewView } from "./scene3d";
import type { BuildPath, PreviewData, PreviewDim } from "./types";

/** The preview of a program: its stored plan or interfaces, or the plan review's unsaved edits (debounced). */
export function useProgramPreview(program: Program, edited: Plan | null) {
  const [plan, setPlan] = useState<Plan | null>(edited);
  const editedSig = edited ? sig(edited) : null;
  useEffect(() => { const t = setTimeout(() => setPlan(edited), 300); return () => clearTimeout(t); }, [editedSig]); // eslint-disable-line react-hooks/exhaustive-deps
  const stored = sig([program.status, program.plan?.subassemblies, program.plan?.graph?.view, program.plan?.graph?.questions, program.plan?.layout_path?.path,
    program.icd?.version, program.icd?.status, program.icd?.interfaces?.map(f => [f.id, f.data])]);
  return useQuery({
    queryKey: ["office-preview", program.id, stored, plan ? sig(plan) : null],
    queryFn: () => (plan ? api.post<PreviewData>(`${BASE}/programs/${program.id}/preview`, { plan })
      : api.get<PreviewData>(`${BASE}/programs/${program.id}/preview`)),
    enabled: !!program.plan, placeholderData: keepPreviousData, staleTime: 60_000, retry: false,
  });
}

const SOURCE_TONE: Record<string, string> = {
  "from the brief": "text-text", "your answer": "text-primary", standard: "text-success", "design rule": "text-muted",
  assumed: "text-warning", "laid out": "text-muted", "from the plan": "text-muted", "measured from the master model": "text-primary",
};
const STATE_WORD: Record<PreviewData["state"], string> = { plan: "The plan, laid out", edited: "Your edits, laid out", icd: "The interfaces" };
const LABEL_H = 18;
const labelW = (t: string) => t.length * 7 + 12;
function arrowPath(a: { x: number; y: number; dx: number; dy: number }) {
  const L = 7, W = 2.6, bx = a.x - a.dx * L, by = a.y - a.dy * L, nx = -a.dy * W, ny = a.dx * W;
  return `M${a.x},${a.y}L${bx + nx},${by + ny}L${bx - nx},${by - ny}Z`;
}
const fmtVal = (v: unknown) => (typeof v === "number" ? `${Math.round(v * 100) / 100}` : String(v ?? ""));

interface Props {
  data: PreviewData | undefined;
  loading?: boolean;
  error?: unknown;
  /** item id under the cursor here or in the plan rows */
  hot: string | null;
  onHot: (item: string | null) => void;
  height?: number;
  title?: ReactNode;
  /** smaller chrome (before / after pairs) */
  compact?: boolean;
  testId?: string;
  /** items to highlight as well (the selected interface's two sides) */
  highlight?: string[];
  /** build path per item id (the plan review's per-part paths, the source of its estimates) */
  paths?: Record<string, BuildPath> | null;
}

/**
 * The instant, dimensioned 3D preview of a layout: every part at its solved placement, coloured by how it will be
 * made, with the key numbers on the model in the viewport dimension style (DS-038). Click a number to see where it
 * came from; problems are drawn in red with their text. A picture of the layout, not an acceptance check.
 */
export default function PlanPreview({ data: raw, loading, error, hot, onHot, height = 420, title, compact = false, testId, highlight, paths }: Props) {
  const pathSig = paths ? sig(paths) : "";
  const data = useMemo(() => (raw ? withPaths(raw, paths) : raw), [raw, pathSig]); // eslint-disable-line react-hooks/exhaustive-deps
  const host = useRef<HTMLDivElement>(null);
  const eng = useRef<PreviewScene | null>(null);
  const [, setTick] = useState(0);
  const [dimsOn, setDimsOn] = useState(true);
  const [allSizes, setAllSizes] = useState(false);
  const [hoverBody, setHoverBody] = useState<string | null>(null);
  const [hoverDim, setHoverDim] = useState<string | null>(null);
  const [hoverIssue, setHoverIssue] = useState<number | null>(null);
  const [openDim, setOpenDim] = useState<string | null>(null);
  const [renderMs, setRenderMs] = useState<number | null>(null);
  const dirs = useRef(new Map<string, V3>());
  const loadedFor = useRef<string | null>(null);
  const hotRef = useRef(onHot);
  hotRef.current = onHot;

  useEffect(() => {
    const dark = document.documentElement.classList.contains("dark");
    const s = new PreviewScene(host.current!, dark);
    eng.current = s;
    const off = s.onView(() => setTick(t => (t + 1) % 1_000_000));
    return () => { off(); s.dispose(); eng.current = null; };
  }, []);

  const bodyItem = useMemo(() => new Map((data?.bodies ?? []).map(b => [b.id, b.item])), [data]);
  useEffect(() => {
    const s = eng.current;
    if (!s) return;
    s.onHover = id => { setHoverBody(id); hotRef.current(id ? bodyItem.get(id) ?? null : null); };
    s.onClick = () => setOpenDim(null);
  }, [bodyItem]);

  const bounds = useMemo(() => (data ? worldBounds(data.bodies) : null), [data]);
  useEffect(() => {
    const s = eng.current;
    if (!s || !data || !bounds) return;
    const t0 = performance.now();
    s.load(data.bodies, bounds, loadedFor.current !== null);
    loadedFor.current = "loaded";
    requestAnimationFrame(() => setRenderMs(Math.round(performance.now() - t0)));
  }, [data, bounds]);

  const issues = useMemo(() => (data?.issues ?? []).filter(x => !x.acknowledged), [data]);
  const errors = issues.filter(x => x.severity === "error");
  const dimById = useMemo(() => new Map((data?.dims ?? []).map(d => [d.id, d])), [data]);

  useEffect(() => {
    const ids = new Set<string>();
    if (hot) ids.add(hot);
    for (const i of highlight ?? []) ids.add(i);
    if (hoverDim) for (const i of dimById.get(hoverDim)?.items ?? []) ids.add(i);
    if (openDim) for (const i of dimById.get(openDim)?.items ?? []) ids.add(i);
    if (hoverIssue !== null) for (const b of issues[hoverIssue]?.bodies ?? []) ids.add(b);
    eng.current?.setHot(ids);
  }, [hot, hoverDim, openDim, hoverIssue, issues, dimById, data, highlight?.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = eng.current;
  const shown: PreviewDim[] = data && dimsOn ? visibleDims(data.dims, hot, allSizes) : [];
  let draws: DimDraw[] = [];
  let spots: { x: number; y: number }[] = [];
  let badges: { n: number; x: number; y: number }[] = [];
  if (s && data && bounds) {
    const cam = s.viewCam();
    const texts = new Map(shown.map(d => [d.id, d.text]));
    draws = layout(toResolved(shown), cam, {
      bbox: bounds, values: Object.fromEntries(shown.map(d => [d.id, d.value ?? 0])), units: {}, dirs: dirs.current,
    }).map(d => ({ ...d, text: texts.get(d.param) ?? d.text }));
    spots = placeLabels(draws.map(d => ({ x: d.lx, y: d.ly, w: labelW(d.text), h: LABEL_H, angle: d.angle })), { width: cam.width, height: cam.height });
    errors.forEach(x => {
      for (const b of x.bodies.slice(0, 4)) {
        const c = s.centreOf(b);
        if (!c) continue;
        const [px, py] = cam.project(c);
        if (px >= 0 && py >= 0 && px <= cam.width && py <= cam.height) badges.push({ n: issues.indexOf(x) + 1, x: px, y: py });
      }
    });
    badges = badges.slice(0, 24);
  }
  const open = openDim ? dimById.get(openDim) : undefined;
  const openAt = open ? spots[draws.findIndex(d => d.param === open.id)] : undefined;
  const hotRow = hot && data ? data.rows[hot] : undefined;
  const hoverName = hoverBody ? data?.bodies.find(b => b.id === hoverBody)?.name : null;
  const errText = error instanceof ApiError ? error.message : error ? "The preview could not be laid out." : null;

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-panel" data-plan-preview={testId ?? "preview"}
      data-render-ms={renderMs ?? undefined} data-server-ms={data?.ms.total ?? undefined} data-errors={errors.length}>
      <div className={cx("flex flex-wrap items-center gap-2 border-b border-border px-3", compact ? "py-1.5" : "py-2")}>
        <Box className="h-4 w-4 text-primary" />
        <span className="text-[13.5px] font-semibold">{title ?? "Layout preview"}</span>
        {data && <span className="text-[11.5px] text-muted">{STATE_WORD[data.state]}{data.state === "icd" && data.icd_version ? ` (ICD v${data.icd_version}${data.icd_status === "draft" ? ", draft" : ""})` : ""}</span>}
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted" aria-label="Updating" />}
        {data && (errors.length ? <Badge tone="danger">{errors.length} problem{errors.length === 1 ? "" : "s"}</Badge> : <Badge tone="success">Places every part</Badge>)}
        <div className="ml-auto flex items-center gap-1">
          {(["Iso", "Front", "Top", "Right"] as PreviewView[]).map(v => (
            <button key={v} type="button" className="rounded px-1.5 py-0.5 text-[11.5px] text-muted hover:bg-text/[.06] hover:text-text" onClick={() => eng.current?.setView(v)}>{v}</button>))}
          <button type="button" title="Zoom to fit" aria-label="Zoom to fit" className="rounded p-1 text-muted hover:bg-text/[.06] hover:text-text" onClick={() => eng.current?.fit()}><Maximize2 className="h-3.5 w-3.5" /></button>
          <button type="button" aria-pressed={dimsOn} title="Dimensions" className={cx("flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px]", dimsOn ? "bg-primary/10 text-primary" : "text-muted hover:bg-text/[.06]")} onClick={() => setDimsOn(v => !v)} data-preview-dims-toggle>
            <Ruler className="h-3.5 w-3.5" />Dimensions</button>
          {!compact && <button type="button" aria-pressed={allSizes} className={cx("rounded px-1.5 py-0.5 text-[11.5px]", allSizes ? "bg-primary/10 text-primary" : "text-muted hover:bg-text/[.06]")} onClick={() => setAllSizes(v => !v)}>Part sizes</button>}
        </div>
      </div>

      <div className="relative" style={{ height }}>
        <div ref={host} className="absolute inset-0" />
        {!data && !errText && <div className="absolute inset-0 flex items-center justify-center text-[12.5px] text-muted"><Loader2 className="mr-2 h-4 w-4 animate-spin" />Laying out the plan…</div>}
        {errText && !data && <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-[12.5px] text-muted">{errText}</div>}

        {/* dimensions, in the Studio's viewport dimension style */}
        <div className="pointer-events-none absolute inset-0 z-[5] overflow-hidden" data-preview-dims>
          <svg className="absolute inset-0 h-full w-full" aria-hidden>
            {draws.map((d, i) => {
              const on = d.param === hoverDim || d.param === openDim || (hot !== null && dimById.get(d.param)?.items.includes(hot));
              const col = on ? "rgb(var(--primary))" : "rgb(var(--text) / 0.72)";
              return <g key={`${d.param}-${i}`} style={{ stroke: col, fill: col }}>
                {d.lines.map((l, j) => <line key={j} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} strokeWidth={on ? 1.6 : 1} />)}
                {d.arrows.map((a, j) => <path key={j} d={arrowPath(a)} strokeWidth={0.5} />)}
              </g>;
            })}
          </svg>
          {draws.map((d, i) => {
            const p = spots[i]!;
            const dm = dimById.get(d.param);
            const on = d.param === hoverDim || d.param === openDim;
            return <div key={`${d.param}-${i}`} className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: p.x, top: p.y }}>
              <button type="button" data-preview-dim={d.param} title={dm ? `${dm.label}: click to see where it came from` : undefined}
                onPointerEnter={() => setHoverDim(d.param)} onPointerLeave={() => setHoverDim(null)} onPointerDown={e => e.stopPropagation()}
                onClick={() => setOpenDim(o => (o === d.param ? null : d.param))}
                className={cx("pointer-events-auto block whitespace-nowrap rounded border px-1 font-mono text-[12px] leading-[16px] tabular-nums shadow-sm transition-colors",
                  on ? "border-primary bg-primary text-white" : "border-border/70 bg-panel/90 text-text hover:border-primary")}>{d.text}</button>
            </div>;
          })}
          {badges.map((b, i) => <div key={i} className="absolute flex h-5 w-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full text-[11px] font-bold text-white shadow"
            style={{ left: b.x, top: b.y, background: ERROR_COLOR }} aria-hidden>{b.n}</div>)}
        </div>

        {/* where a number came from */}
        {open && openAt && <div className="absolute z-20 w-[290px] rounded-lg border border-border bg-panel p-2.5 text-[12px] shadow-pop" data-dim-source={open.id}
          style={{ left: Math.min(Math.max(openAt.x - 145, 6), Math.max(6, (host.current?.clientWidth ?? 300) - 296)), top: Math.min(openAt.y + 14, Math.max(6, height - 150)) }}>
          <div className="mb-1 flex items-start gap-2"><b className="flex-1">{open.label}</b><button type="button" className="text-muted hover:text-text" aria-label="Close" onClick={() => setOpenDim(null)}>×</button></div>
          <ul className="space-y-1">{open.sources.map((x, i) => (
            <li key={i}><span className="text-muted">{x.what}</span> <b className="font-mono">{fmtVal(x.value)}</b>{" "}
              <span className={cx("font-medium", SOURCE_TONE[x.word] ?? "text-muted")}>{x.word}</span>
              {x.note && <div className="text-[11.5px] text-muted">{x.note}</div>}</li>))}</ul>
        </div>}

        {/* problems before approval: red on the model, the text here */}
        {data && issues.length > 0 && <div className={cx("absolute left-2 top-2 z-10 max-h-[60%] overflow-y-auto rounded-md border bg-panel/95 p-2 text-[11.5px] shadow-card", compact ? "max-w-[70%]" : "max-w-[46%]",
          errors.length ? "border-danger/40" : "border-warning/40")} data-preview-issues>
          <div className={cx("mb-1 flex items-center gap-1 font-semibold", errors.length ? "text-danger" : "text-warning")}><AlertTriangle className="h-3.5 w-3.5" />
            {errors.length ? `${errors.length} problem${errors.length === 1 ? "" : "s"} to clear before the interfaces gate` : `${issues.length} note${issues.length === 1 ? "" : "s"}`}</div>
          <ol className="space-y-1">{issues.map((x, i) => (
            <li key={i} className={cx("flex gap-1.5 rounded px-1 py-0.5", hoverIssue === i && "bg-text/[.05]")} onPointerEnter={() => setHoverIssue(i)} onPointerLeave={() => setHoverIssue(null)} data-preview-issue={x.code}>
              <span className={cx("mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white", x.severity === "error" ? "bg-danger" : "bg-warning")}>{i + 1}</span>
              <span className={x.severity === "error" ? "text-text" : "text-muted"}>{x.text}</span></li>))}</ol>
        </div>}

        {/* what is under the cursor */}
        {(hoverName || hotRow) && <div className="pointer-events-none absolute right-2 top-2 z-10 max-w-[45%] rounded-md bg-chrome/90 px-2 py-1 text-[11.5px] text-chrome-fg shadow-card" data-preview-hover>
          <b>{hoverName ?? hotRow?.name}</b>{hotRow && <> · {PATH_LABEL[hotRow.path]}{hotRow.why && hotRow.path !== "toolbox" ? `: ${hotRow.why}` : ""}</>}
        </div>}

        {/* legend: how each part will be made */}
        {data && <div className="pointer-events-none absolute bottom-2 left-2 z-10 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-panel/85 px-2 py-1 text-[11px] text-muted">
          {(["spec", "template", "toolbox", "ai"] as BuildPath[]).filter(k => data.paths[k] > 0).map(k => (
            <span key={k} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: PATH_COLOR[k] }} />{PATH_LABEL[k]} ({data.paths[k]})</span>))}
          {errors.length > 0 && <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: ERROR_COLOR }} />Problem</span>}
        </div>}
        {data && !compact && <div className="pointer-events-none absolute bottom-2 right-2 z-10 rounded bg-panel/85 px-1.5 py-0.5 text-[10.5px] tabular-nums text-muted" data-preview-timing>
          Laid out in {Math.round(data.ms.total ?? data.ms.scene)} ms{renderMs !== null ? ` · drawn in ${renderMs} ms` : ""} · no CAD build</div>}
      </div>
      {!compact && data && <div className="border-t border-border px-3 py-1.5 text-[11px] text-muted">
        Every part at its solved placement, sized from the plan (gears at their tip circle, screws as simple cylinders). Click a number to see where it came from. A picture of the layout for your review, not a check: the parts are verified when they are built.
      </div>}
    </div>
  );
}
