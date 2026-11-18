import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, ArrowRightToLine, ArrowUpRight, Baseline, Circle, CircleDot, Columns3, Copy, CopyPlus, CornerUpRight, Crosshair, Diameter,
  Download, FlipHorizontal2, Flag, Grid3x3, Hexagon, Magnet, Maximize2, Milestone, MousePointer2, Move, PenLine, Pill, Radius, Redo2,
  RotateCw, Ruler, Save, Scaling, Scissors, Slash, Sparkles, Spline, Square, SquareDashed, Triangle, Type, Undo2, Waves,
} from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, PageLoader, Tip } from "@/components/ui";
import { addPolygon, addSlot, extend, filletCorner, mirrorEntities, offsetEntities, removeItems, trim, type P2 } from "@/sketch/tools";
import { ModuleHeader } from "../../ModuleHeader";
import { localStamp } from "../types";
import { draftsApi, type DraftState, type Fragment } from "./api";
import {
  addPoint, applySketch, chamferCorner, circleOf, cloneDoc, DEFAULT_SNAPS, findSnap, hatchAt, kOf, moveBy, nearestPoint,
  parsePointInput, pickEntity, pointMap, rotateAbout, scaleAbout, sheetWH, sketchOf, toModel, toPaper, track, transformSelection, uid,
  usedPoints, type Anno, type DEnt, type Dim, type DraftDoc, type GdtSymbol, type Layer, type Snap, type SnapOpts,
} from "./geom";
import { contentPrims, FILLS, LINE_STYLES, primBox, TEXT_COLORS, type Prim } from "./prims";
import { FileButtons } from "@/components/NativeExport";
import { moduleExportUrl } from "@/lib/native";
import { DraftSidePanel, type ToolOpts } from "./DraftPanels";

export type ToolId = "select" | "line" | "centerline" | "rect" | "circle" | "arc" | "slot" | "polygon" | "centermark" | "offset" | "trim" | "extend"
  | "mirror" | "fillet" | "chamfer" | "move" | "copy" | "rotate" | "scale" | "hatch" | "dim" | "dimh" | "dimv" | "dimal" | "dimr" | "dimd"
  | "dima" | "dimo" | "dimb" | "dimc" | "text" | "leader" | "balloon" | "surface" | "gdt" | "datum";

const TOOLS: { group: string; items: { id: ToolId; label: string; icon: ReactNode; key?: string; hint: string }[] }[] = [
  { group: "Draw", items: [
    { id: "line", label: "Line", icon: <Slash />, key: "L", hint: "Line / polyline: click points; Enter, Esc or right-click ends; click the start to close" },
    { id: "rect", label: "Rectangle", icon: <Square />, key: "R", hint: "Rectangle: two opposite corners" },
    { id: "circle", label: "Circle", icon: <Circle />, key: "C", hint: "Circle: centre, then a point on it (or type the radius)" },
    { id: "arc", label: "Arc", icon: <Spline />, key: "A", hint: "Arc: centre, start, end (counter-clockwise)" },
    { id: "slot", label: "Slot", icon: <Pill />, hint: "Slot: two centres, then the width" },
    { id: "polygon", label: "Polygon", icon: <Hexagon />, hint: "Polygon: centre, then a vertex" },
    { id: "centerline", label: "Centre line", icon: <PenLine />, hint: "Centre line (ISO 128 04.1): two points" },
    { id: "centermark", label: "Centre mark", icon: <Crosshair />, hint: "Centre mark: click a circle or arc" },
  ] },
  { group: "Modify", items: [
    { id: "offset", label: "Offset", icon: <CopyPlus />, key: "O", hint: "Offset: pick lines/arcs/circles (Shift adds), then click the side" },
    { id: "trim", label: "Trim", icon: <Scissors />, key: "T", hint: "Trim: click the part to cut away" },
    { id: "extend", label: "Extend", icon: <ArrowRightToLine />, hint: "Extend: click near the free end to extend" },
    { id: "mirror", label: "Mirror", icon: <FlipHorizontal2 />, hint: "Mirror: select the entities first, then click the mirror line" },
    { id: "fillet", label: "Fillet", icon: <CornerUpRight />, hint: "Fillet: click a corner where two lines meet" },
    { id: "chamfer", label: "Chamfer", icon: <Triangle />, hint: "Chamfer: click a corner where two lines meet" },
    { id: "move", label: "Move", icon: <Move />, key: "M", hint: "Move: select, then base point and destination (or type @dx,dy)" },
    { id: "copy", label: "Copy", icon: <Copy />, hint: "Copy: select, then base point and destination" },
    { id: "rotate", label: "Rotate", icon: <RotateCw />, hint: "Rotate: select, centre, then angle (click or type degrees)" },
    { id: "scale", label: "Scale", icon: <Scaling />, hint: "Scale: select, then the base point (factor in the options)" },
  ] },
  { group: "Annotate", items: [
    { id: "hatch", label: "Hatch", icon: <Waves />, key: "H", hint: "Hatch (section): click inside a closed boundary" },
    { id: "text", label: "Note", icon: <Type />, hint: "Note: type the text in the options, then click where it goes" },
    { id: "leader", label: "Leader", icon: <ArrowUpRight />, hint: "Leader: arrow point, then the text end" },
    { id: "balloon", label: "Balloon", icon: <CircleDot />, hint: "Balloon: the item, then the balloon" },
    { id: "surface", label: "Surface", icon: <Milestone />, hint: "Surface texture symbol (ISO 21920): click on the surface; values are yours" },
    { id: "gdt", label: "GD&T", icon: <Columns3 />, hint: "Geometric tolerance frame (ISO 1101): enter it in the options, then arrow point and frame" },
    { id: "datum", label: "Datum", icon: <Flag />, hint: "Datum feature: the feature, then the letter box" },
  ] },
  { group: "Dimension", items: [
    { id: "dim", label: "Smart", icon: <Ruler />, key: "D", hint: "Smart dimension: a line, a circle, two points or two lines; then place it" },
    { id: "dimh", label: "Horizontal", icon: <Baseline />, hint: "Horizontal: two points, then place" },
    { id: "dimv", label: "Vertical", icon: <Baseline className="rotate-90" />, hint: "Vertical: two points, then place" },
    { id: "dimal", label: "Aligned", icon: <Slash />, hint: "Aligned: two points, then place" },
    { id: "dimd", label: "Diameter", icon: <Diameter />, hint: "Diameter: a circle or arc, then place" },
    { id: "dimr", label: "Radius", icon: <Radius />, hint: "Radius: an arc or circle, then place" },
    { id: "dima", label: "Angle", icon: <Triangle />, hint: "Angle: two lines, then place in the sector to measure" },
    { id: "dimo", label: "Ordinate", icon: <Grid3x3 />, hint: "Ordinate: the origin point once, then each feature point and its place" },
    { id: "dimb", label: "Baseline", icon: <SquareDashed />, hint: "Baseline: the base point, then each point (stacked from the base)" },
    { id: "dimc", label: "Chain", icon: <Columns3 />, hint: "Chain: points one after another (end to end on one line)" },
  ] },
];
const TOOL_BY_ID = new Map(TOOLS.flatMap(g => g.items).map(t => [t.id, t]));
const NEEDS_SELECTION = new Set<ToolId>(["mirror", "move", "copy", "rotate", "scale"]);
const POINT_TOOLS = new Set<ToolId>(["line", "centerline", "rect", "circle", "arc", "slot", "polygon", "move", "copy", "rotate", "scale", "leader", "balloon", "gdt", "datum", "text", "surface", "dimh", "dimv", "dimal", "dimb", "dimc", "dimo", "dim"]);

export const DEFAULT_TOOL_OPTS: ToolOpts = {
  offset: 5, fillet: 3, chamfer: 2, sides: 6, inscribed: true, text: "", textSize: 3.5, leaderText: "", balloon: "1",
  surfaceText: "", removal: "required", gdtSymbol: "position", gdtTol: "", gdtDia: true, gdtMod: "", gdtDatums: "", datum: "A",
  hatch: 3, angle: 90, factor: 2, copyMode: false, dimOrient: "auto",
};

type Step = { pts: P2[]; ids: (string | null)[]; ents: string[]; base?: string | null };
const EMPTY_STEP: Step = { pts: [], ids: [], ents: [] };

interface View { k: number; x: number; y: number }

export default function DraftEditor({ id, onBack }: { id: string; onBack: () => void }) {
  const q = useQuery({ queryKey: ["draft", id], queryFn: () => draftsApi.get(id), staleTime: Infinity, refetchOnWindowFocus: false });
  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) {
    return <div className="mx-auto max-w-xl p-10 text-center"><p className="text-sm text-muted">{(q.error as Error)?.message ?? "Not found"}</p>
      <Button className="mt-4" variant="secondary" icon={<ArrowLeft className="h-4 w-4" />} onClick={onBack}>All drawings</Button></div>;
  }
  return <Editor key={id} initial={q.data} onBack={onBack} />;
}

function Editor({ initial, onBack }: { initial: DraftState; onBack: () => void }) {
  const qc = useQueryClient();
  const [state, setState] = useState(initial); // last saved
  const [doc, setDocRaw] = useState<DraftDoc>(initial.doc);
  const [name, setName] = useState(initial.name);
  const [past, setPast] = useState<DraftDoc[]>([]);
  const [future, setFuture] = useState<DraftDoc[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tool, setToolRaw] = useState<ToolId>("select");
  const [step, setStep] = useState<Step>(EMPTY_STEP);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState<P2 | null>(null);
  const [snap, setSnap] = useState<Snap | null>(null);
  const [snaps, setSnaps] = useState<SnapOpts>(DEFAULT_SNAPS);
  const [snapOn, setSnapOn] = useState(true);
  const [ortho, setOrtho] = useState(false);
  const [polar, setPolar] = useState(false);
  const [layer, setLayer] = useState<Layer>("visible");
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set());
  const [opts, setOpts] = useState<ToolOpts>(DEFAULT_TOOL_OPTS);
  const [input, setInput] = useState("");
  const [view, setView] = useState<View>({ k: 2, x: 0, y: 0 });
  const [box, setBox] = useState<{ a: P2; b: P2 } | null>(null);
  const [pendingFrag, setPendingFrag] = useState<{ frag: Fragment; message: string; missing: string[] } | null>(null);
  const [preview, setPreview] = useState<{ rev: number; doc: DraftDoc } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ kind: "pan" | "box" | "grip" | "label"; start: P2; screen: P2; view: View; id?: string; moved?: boolean; base?: DraftDoc } | null>(null);
  const canEdit = state.can_edit && !preview;
  const shown = preview?.doc ?? doc;

  const [W, H] = sheetWH(shown.sheet);
  const kModel = kOf(shown.sheet);

  // ---------------------------------------------------------------- document changes and history
  const commit = useCallback((next: DraftDoc) => {
    setPast(p => [...p.slice(-99), doc]);
    setFuture([]);
    setDocRaw(next);
    setDirty(true);
  }, [doc]);
  const undo = () => { if (!past.length) return; setFuture(f => [doc, ...f]); setDocRaw(past[past.length - 1]!); setPast(p => p.slice(0, -1)); setDirty(true); };
  const redo = () => { if (!future.length) return; setPast(p => [...p, doc]); setDocRaw(future[0]!); setFuture(f => f.slice(1)); setDirty(true); };
  const setTool = (t: ToolId) => { setToolRaw(t); setStep(EMPTY_STEP); setInput(""); if (!NEEDS_SELECTION.has(t) && t !== "offset" && t !== "select") setSel(new Set()); };

  const save = useCallback(async (note = "") => {
    setSaving(true);
    try {
      const r = await draftsApi.save(state.id, { doc, name, note, base_rev: state.rev });
      setState(r); setDocRaw(r.doc); setDirty(false);
      qc.setQueryData(["draft", state.id], r); void qc.invalidateQueries({ queryKey: ["drafts"] });
      toast.success(`Saved as revision ${r.rev}`);
      return r;
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "The drawing could not be saved.");
      return null;
    } finally { setSaving(false); }
  }, [doc, name, state.id, state.rev, qc]);

  // ---------------------------------------------------------------- sheet frame from the server (same code as exports)
  const frameKey = JSON.stringify([shown.sheet, shown.title, shown.revisions, shown.notes]);
  const frameQ = useQuery({ queryKey: ["draft-frame", frameKey], queryFn: () => draftsApi.frame({ sheet: shown.sheet, title: shown.title as unknown as Record<string, string>, revisions: shown.revisions, notes: shown.notes }), staleTime: Infinity, placeholderData: p => p });

  // ---------------------------------------------------------------- prims
  const loopPoly = useCallback((ids: string[]) => {
    const P = pointMap(shown); const out: P2[] = [];
    if (ids.length === 1) { const e = shown.geom.entities.find(x => x.id === ids[0]); if (e?.type === "circle") { const c = P.get(e.c)!; for (let i = 0; i < 72; i++) out.push([c[0] + e.r * Math.cos(Math.PI * 2 * i / 72), c[1] + e.r * Math.sin(Math.PI * 2 * i / 72)]); return out; } }
    // chain by shared end points
    const segs = ids.map(i => shown.geom.entities.find(x => x.id === i)).filter((e): e is DEnt => !!e && e.type !== "circle");
    if (!segs.length) return null;
    const tess = (e: DEnt): P2[] => {
      if (e.type === "line") return [P.get(e.p1)!, P.get(e.p2)!];
      if (e.type !== "arc") return [];
      const c = P.get(e.c)!, a = P.get(e.p1)!, b = P.get(e.p2)!; const r = Math.hypot(a[0] - c[0], a[1] - c[1]);
      const a0 = Math.atan2(a[1] - c[1], a[0] - c[0]); let sw = Math.atan2(b[1] - c[1], b[0] - c[0]) - a0; if (sw <= 0) sw += Math.PI * 2;
      return Array.from({ length: 25 }, (_, i) => [c[0] + r * Math.cos(a0 + sw * i / 24), c[1] + r * Math.sin(a0 + sw * i / 24)] as P2);
    };
    const pieces = segs.map(tess); const line = [...pieces.shift()!];
    const close = (p: P2, q: P2) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 1e-6;
    while (pieces.length) {
      const end = line[line.length - 1]!; const j = pieces.findIndex(s => close(s[0]!, end) || close(s[s.length - 1]!, end));
      if (j < 0) return null;
      const s = pieces.splice(j, 1)[0]!; line.push(...(close(s[0]!, end) ? s.slice(1) : [...s].reverse().slice(1)));
    }
    return line;
  }, [shown]);
  const prims = useMemo(() => contentPrims(shown, { construction: true, hidden: hiddenLayers, loopPoly }), [shown, hiddenLayers, loopPoly]);

  // ---------------------------------------------------------------- view
  const fit = useCallback(() => {
    const el = wrapRef.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const k = Math.max(0.3, Math.min((r.width - 40) / W, (r.height - 40) / H));
    setView({ k, x: (r.width - W * k) / 2, y: (r.height - H * k) / 2 });
  }, [W, H]);
  useEffect(() => { fit(); }, [fit]);
  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault(); const r = el.getBoundingClientRect(); const px = e.clientX - r.left, py = e.clientY - r.top;
      const f = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      setView(v => { const nk = Math.min(80, Math.max(0.2, v.k * f)); return { k: nk, x: px - (px - v.x) * nk / v.k, y: py - (py - v.y) * nk / v.k }; });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  const toPaperXY = (e: { clientX: number; clientY: number }): P2 => {
    const r = wrapRef.current!.getBoundingClientRect();
    return [(e.clientX - r.left - view.x) / view.k, (e.clientY - r.top - view.y) / view.k];
  };
  const tolModel = 9 / view.k / kModel;

  // ---------------------------------------------------------------- input point (snap + ortho/polar)
  const lastPt = step.pts.length ? step.pts[step.pts.length - 1]! : null;
  const resolve = (paper: P2): { p: P2; s: Snap | null } => {
    const raw = toModel(shown.sheet, paper);
    const s = snapOn && POINT_TOOLS.has(tool) ? findSnap(shown, raw, tolModel, snaps, lastPt) : null;
    if (s && s.kind !== "grid") return { p: s.p, s };
    let p = s?.p ?? raw;
    if (lastPt && (ortho || polar) && POINT_TOOLS.has(tool)) p = track(lastPt, p, ortho ? "ortho" : "polar", 15);
    return { p, s };
  };

  // ---------------------------------------------------------------- tool actions
  const fail = (e: unknown) => toast.error(e instanceof Error ? e.message : "That didn't work here");
  const finishStep = () => setStep(EMPTY_STEP);
  const pid = (d: DraftDoc, p: P2, s: Snap | null | undefined) => (s?.pt && d.geom.points.some(q => q.id === s.pt) ? s.pt : addPoint(d, p));
  const pickRound = (p: P2) => pickEntity(shown, p, tolModel, e => e.type !== "line");
  const pickLine = (p: P2) => pickEntity(shown, p, tolModel, e => e.type === "line");
  const dimPos = (d: Dim) => d;

  const addEntities = (mk: (d: DraftDoc) => void) => { const d = cloneDoc(doc); mk(d); commit(d); };

  const placePoint = (p: P2, s: Snap | null) => {
    if (!canEdit) return;
    const st = step;
    const n = st.pts.length;
    const push = (extra: Partial<Step> = {}) => setStep({ pts: [...st.pts, p], ids: [...st.ids, s?.pt ?? null], ents: st.ents, ...extra });
    try {
      switch (tool) {
        case "line": case "centerline": {
          if (n === 0) { push(); return; }
          const lay: Layer = tool === "centerline" ? "center" : layer;
          let endId: string | null = null;
          const d = cloneDoc(doc);
          const a = st.base && d.geom.points.some(q => q.id === st.base) ? st.base : pid(d, lastPt!, st.ids[n - 1] ? { p: lastPt!, kind: "endpoint", pt: st.ids[n - 1]! } : null);
          const closing = tool === "line" && n >= 2 && Math.hypot(p[0] - st.pts[0]![0], p[1] - st.pts[0]![1]) < 1e-9;
          endId = closing && st.ids[0] ? st.ids[0] : pid(d, p, s);
          if (a === endId) return;
          d.geom.entities.push({ id: uid("e"), type: "line", p1: a, p2: endId, layer: lay });
          commit(d);
          if (tool === "centerline" || closing) finishStep();
          else setStep({ pts: [...st.pts, p], ids: [...st.ids, endId], ents: [], base: endId });
          return;
        }
        case "rect": {
          if (n === 0) { push(); return; }
          const [a] = st.pts as [P2];
          if (Math.abs(p[0] - a[0]) < 1e-9 || Math.abs(p[1] - a[1]) < 1e-9) return;
          addEntities(d => {
            const c = [a, [p[0], a[1]], p, [a[0], p[1]]] as P2[];
            const ids = c.map((q, i) => (i === 0 ? pid(d, q, st.ids[0] ? { p: q, kind: "endpoint", pt: st.ids[0] } : null) : i === 2 ? pid(d, q, s) : addPoint(d, q)));
            for (let i = 0; i < 4; i++) d.geom.entities.push({ id: uid("e"), type: "line", p1: ids[i]!, p2: ids[(i + 1) % 4]!, layer });
          });
          finishStep(); return;
        }
        case "circle": {
          if (n === 0) { push(); return; }
          const c = st.pts[0]!; const r = Math.hypot(p[0] - c[0], p[1] - c[1]); if (r < 1e-9) return;
          addEntities(d => d.geom.entities.push({ id: uid("e"), type: "circle", c: pid(d, c, st.ids[0] ? { p: c, kind: "center", pt: st.ids[0] } : null), r, layer }));
          finishStep(); return;
        }
        case "arc": {
          if (n < 2) { push(); return; }
          const [c, a] = st.pts as [P2, P2]; const r = Math.hypot(a[0] - c[0], a[1] - c[1]);
          const ang = Math.atan2(p[1] - c[1], p[0] - c[0]); const b: P2 = [c[0] + r * Math.cos(ang), c[1] + r * Math.sin(ang)];
          if (r < 1e-9 || Math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9) return;
          addEntities(d => d.geom.entities.push({ id: uid("e"), type: "arc", c: pid(d, c, st.ids[0] ? { p: c, kind: "center", pt: st.ids[0] } : null), p1: pid(d, a, st.ids[1] ? { p: a, kind: "endpoint", pt: st.ids[1] } : null), p2: addPoint(d, b), layer }));
          finishStep(); return;
        }
        case "slot": {
          if (n < 2) { push(); return; }
          const [c1, c2] = st.pts as [P2, P2];
          const L = Math.hypot(c2[0] - c1[0], c2[1] - c1[1]); if (L < 1e-9) return;
          const r = Math.abs(((p[0] - c1[0]) * -(c2[1] - c1[1]) + (p[1] - c1[1]) * (c2[0] - c1[0])) / L);
          const d = cloneDoc(doc); const i1 = addPoint(d, c1), i2 = addPoint(d, c2);
          commit(applySketch(d, addSlot(sketchOf(d), i1, i2, r), layer)); finishStep(); return;
        }
        case "polygon": {
          if (n === 0) { push(); return; }
          const d = cloneDoc(doc); const c = addPoint(d, st.pts[0]!);
          commit(applySketch(d, addPolygon(sketchOf(d), c, p, Math.round(opts.sides), opts.inscribed ? "inscribed" : "circumscribed"), layer)); finishStep(); return;
        }
        case "move": case "copy": case "rotate": case "scale": {
          if (!sel.size) { toast.info("Select what to change first (Select tool), then pick this tool"); return; }
          if (tool === "scale") { if (!(opts.factor > 0)) throw new Error("Enter a scale factor above 0"); commit(transformSelection(doc, sel, scaleAbout(p, opts.factor), { scale: opts.factor, copy: opts.copyMode })); finishStep(); return; }
          if (n === 0) { push(); return; }
          const b = st.pts[0]!;
          if (tool === "rotate") { const ang = Math.atan2(p[1] - b[1], p[0] - b[0]) * 180 / Math.PI; commit(transformSelection(doc, sel, rotateAbout(b, ang), { copy: opts.copyMode })); }
          else commit(transformSelection(doc, sel, moveBy(p[0] - b[0], p[1] - b[1]), { copy: tool === "copy" }));
          finishStep(); return;
        }
        case "text": {
          if (!opts.text.trim()) { toast.info("Type the note in the tool options first"); return; }
          addEntities(d => d.annos.push({ id: uid("a"), type: "text", pos: p, text: opts.text.trim(), size: opts.textSize })); return;
        }
        case "surface":
          addEntities(d => d.annos.push({ id: uid("a"), type: "surface", pos: p, text: opts.surfaceText.trim(), removal: opts.removal })); return;
        case "leader": case "balloon": case "gdt": case "datum": {
          if (tool === "gdt" && !/^\d+(\.\d+)?$/.test(opts.gdtTol.trim())) { toast.info("Enter the tolerance value in the tool options first (e.g. 0.05)"); return; }
          if (n === 0) { push(); return; }
          const tip = st.pts[0]!;
          addEntities(d => {
            const id = uid("a");
            if (tool === "leader") d.annos.push({ id, type: "leader", pts: [tip, p], text: opts.leaderText.trim() });
            else if (tool === "balloon") d.annos.push({ id, type: "balloon", tip, pos: p, text: opts.balloon.trim() || "1" });
            else if (tool === "datum") d.annos.push({ id, type: "datum", tip, pos: p, letter: (opts.datum.trim() || "A").toUpperCase() });
            else d.annos.push({ id, type: "gdt", tip, pos: p, symbol: opts.gdtSymbol, tol: opts.gdtTol.trim(), dia: opts.gdtDia, mod: opts.gdtMod, datums: opts.gdtDatums.split(/[\s,|]+/).map(x => x.trim().toUpperCase()).filter(Boolean).slice(0, 3) });
          });
          if (tool === "balloon") setOpts(o => ({ ...o, balloon: String((parseInt(o.balloon, 10) || 0) + 1) }));
          if (tool === "datum") setOpts(o => ({ ...o, datum: String.fromCharCode(Math.min(90, (o.datum.toUpperCase().charCodeAt(0) || 64) + 1)) }));
          finishStep(); return;
        }
        case "dim": case "dimh": case "dimv": case "dimal": case "dimb": case "dimc": case "dimo":
          dimClick(p, s); return;
        default:
      }
    } catch (e) { fail(e); finishStep(); }
  };

  const orientFor = (a: P2, b: P2, at: P2, forced?: "h" | "v" | "aligned"): "h" | "v" | "aligned" => {
    if (forced) return forced;
    if (opts.dimOrient !== "auto") return opts.dimOrient;
    const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])], [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
    if (at[0] >= x0 && at[0] <= x1 && !(at[1] >= y0 && at[1] <= y1)) return "h";
    if (at[1] >= y0 && at[1] <= y1 && !(at[0] >= x0 && at[0] <= x1)) return "v";
    return Math.abs(at[1] - (a[1] + b[1]) / 2) > Math.abs(at[0] - (a[0] + b[0]) / 2) ? "h" : "v";
  };

  /** Point-pair dimensions (smart, H, V, aligned, baseline, chain, ordinate). Points must be existing end points / centres. */
  const dimClick = (p: P2, s: Snap | null) => {
    const st = step; const n = st.pts.length;
    const forced = tool === "dimh" ? "h" : tool === "dimv" ? "v" : tool === "dimal" ? "aligned" : undefined;
    const needPt = () => { if (!s?.pt) { toast.info("Pick an end point or a centre (dimensions stay attached to them)"); return false; } return true; };
    if (tool === "dimo") {
      if (!st.base) { if (needPt()) setStep({ ...EMPTY_STEP, base: s!.pt! }); return; }
      if (n === 0) { if (needPt()) setStep({ ...st, pts: [p], ids: [s!.pt!] }); return; }
      const F = st.pts[0]!; const axis = Math.abs(p[1] - F[1]) > Math.abs(p[0] - F[0]) ? "x" : "y";
      addEntities(d => d.dims.push({ id: uid("d"), type: "ordinate", axis, origin: st.base!, pt: st.ids[0]!, pos: p }));
      setStep({ ...EMPTY_STEP, base: st.base }); return;
    }
    if (tool === "dimb" || tool === "dimc") {
      if (!needPt()) return;
      if (!st.base) { setStep({ ...EMPTY_STEP, base: s!.pt! }); return; }
      if (s!.pt === st.base) return;
      const P = pointMap(doc); const a = P.get(st.base)!, b = P.get(s!.pt!)!;
      const o: "h" | "v" = (st.ents[0] as "h" | "v" | undefined)
        ?? (opts.dimOrient === "h" || opts.dimOrient === "v" ? opts.dimOrient : Math.abs(b[0] - a[0]) >= Math.abs(b[1] - a[1]) ? "h" : "v");
      const gap = 8 / kModel; // ISO 129: about 8 mm between parallel dimension lines on the sheet
      const count = Number(st.ents[2] ?? 0);
      const level0 = st.ents[1] !== undefined ? Number(st.ents[1]) : o === "h" ? Math.min(a[1], b[1]) - 12 / kModel : Math.max(a[0], b[0]) + 12 / kModel;
      const lvl = tool === "dimb" ? level0 + (o === "h" ? -gap : gap) * count : level0;
      const pos: P2 = o === "h" ? [(a[0] + b[0]) / 2, lvl] : [lvl, (a[1] + b[1]) / 2];
      addEntities(d => d.dims.push({ id: uid("d"), type: "linear", orient: o, a: st.base!, b: s!.pt!, pos }));
      setStep({ ...EMPTY_STEP, base: tool === "dimb" ? st.base : s!.pt!, ents: [o, String(level0), String(count + 1)] });
      return;
    }
    // smart / h / v / aligned
    if (n === 0) {
      if (s?.pt) { setStep({ pts: [p], ids: [s.pt], ents: [] }); return; }
      if (tool === "dim") {
        const r = pickRound(p);
        if (r) { setStep({ pts: [p], ids: [null], ents: [r.id] }); return; }
        const l = pickLine(p);
        if (l) { setStep({ pts: [p], ids: [null], ents: [l.id] }); return; }
      } else {
        const l = pickLine(p);
        if (l && l.type === "line") { setStep({ pts: [p, p], ids: [l.p1, l.p2], ents: [] }); return; }
      }
      toast.info("Pick an end point, a centre, a line or a circle"); return;
    }
    const P = pointMap(doc);
    if (st.ents.length) {
      const e = doc.geom.entities.find(x => x.id === st.ents[0]);
      if (!e) { finishStep(); return; }
      if (e.type !== "line") { // circle / arc: place
        addEntities(d => d.dims.push(dimPos({ id: uid("d"), type: e.type === "circle" ? "diameter" : "radius", ent: e.id, pos: p })));
        finishStep(); return;
      }
      if (st.ents.length === 1 && n === 1) {
        const l2 = pickLine(p);
        if (l2 && l2.id !== e.id && l2.type === "line") {
          const a1 = P.get(e.p1)!, b1 = P.get(e.p2)!, a2 = P.get(l2.p1)!, b2 = P.get(l2.p2)!;
          const cr = (b1[0] - a1[0]) * (b2[1] - a2[1]) - (b1[1] - a1[1]) * (b2[0] - a2[0]);
          if (Math.abs(cr) > 1e-9 * Math.hypot(b1[0] - a1[0], b1[1] - a1[1]) * Math.hypot(b2[0] - a2[0], b2[1] - a2[1])) { setStep({ ...st, ents: [e.id, l2.id], pts: [...st.pts, p] }); return; }
          // parallel lines: their distance (exact for horizontal / vertical lines, between end points)
          const vert = Math.abs(b1[0] - a1[0]) < 1e-9, horiz = Math.abs(b1[1] - a1[1]) < 1e-9;
          if (!vert && !horiz) { toast.info("These lines are parallel: dimension the distance between two end points instead"); return; }
          setStep({ pts: [st.pts[0]!, p], ids: [e.p1, l2.p1], ents: [], base: vert ? "h" : "v" });
          return;
        }
        const a = P.get(e.p1)!, b = P.get(e.p2)!;
        const o = Math.abs(a[1] - b[1]) < 1e-9 ? "h" : Math.abs(a[0] - b[0]) < 1e-9 ? "v" : (opts.dimOrient === "auto" ? "aligned" : opts.dimOrient);
        addEntities(d => d.dims.push({ id: uid("d"), type: "linear", orient: o, a: e.p1, b: e.p2, pos: p }));
        finishStep(); return;
      }
      if (st.ents.length === 2) { // angle: place
        const d0 = { id: uid("d"), type: "angle" as const, l1: st.ents[0]!, l2: st.ents[1]!, pos: p };
        addEntities(d => d.dims.push(d0)); finishStep(); return;
      }
    }
    if (n === 1) { if (!needPt()) return; if (s!.pt === st.ids[0]) return; setStep({ pts: [...st.pts, p], ids: [...st.ids, s!.pt!], ents: [] }); return; }
    const [ia, ib] = st.ids as [string, string];
    const a = P.get(ia)!, b = P.get(ib)!;
    const fixed = st.base === "h" || st.base === "v" ? st.base : forced; // parallel lines picked: across them
    addEntities(d => d.dims.push({ id: uid("d"), type: "linear", orient: orientFor(a, b, p, fixed), a: ia, b: ib, pos: p }));
    finishStep();
  };

  const entityClick = (p: P2, shift: boolean) => {
    if (!canEdit) return;
    try {
      switch (tool) {
        case "trim": { const e = pickEntity(shown, p, tolModel); if (!e) return; commit(applySketch(doc, trim(sketchOf(doc), e.id, p), e.layer)); return; }
        case "extend": { const e = pickEntity(shown, p, tolModel); if (!e) return; commit(applySketch(doc, extend(sketchOf(doc), e.id, p), e.layer)); return; }
        case "fillet": case "chamfer": {
          const pt = nearestPoint(doc, p, tolModel * 1.5); if (!pt) { toast.info("Click on a corner"); return; }
          commit(tool === "fillet" ? applySketch(doc, filletCorner(sketchOf(doc), pt, opts.fillet), layerOfPoint(doc, pt)) : chamferCorner(doc, pt, opts.chamfer)); return;
        }
        case "centermark": {
          const e = pickRound(p); if (!e) { toast.info("Click a circle or an arc"); return; }
          if (doc.annos.some(a => a.type === "centermark" && a.ent === e.id)) return;
          addEntities(d => d.annos.push({ id: uid("a"), type: "centermark", ent: e.id })); return;
        }
        case "hatch": {
          const r = hatchAt(doc, p); if (!r) { toast.info("Click inside a closed boundary (visible or hidden lines)"); return; }
          const d = cloneDoc(r.doc); d.annos.push({ id: uid("a"), type: "hatch", loops: r.loops, spacing: opts.hatch }); commit(d); return;
        }
        case "mirror": {
          const ax = pickLine(p); if (!ax) { toast.info("Click the mirror line"); return; }
          const ids = [...sel].filter(i => doc.geom.entities.some(e => e.id === i) && i !== ax.id);
          if (!ids.length) { toast.info("Select the entities to mirror first"); return; }
          const src = doc.geom.entities.find(e => e.id === ids[0])!;
          commit(applySketch(doc, mirrorEntities(sketchOf(doc), ids, ax.id), src.layer)); return;
        }
        case "offset": {
          const e = pickEntity(shown, p, tolModel);
          if (e && !step.pts.length) { setSel(prev => { const n = new Set(shift ? prev : []); n.add(e.id); return n; }); return; }
          const ids = [...sel].filter(i => doc.geom.entities.some(x => x.id === i));
          if (!ids.length) { toast.info("Pick the lines, arcs or circles to offset"); return; }
          const src = doc.geom.entities.find(x => x.id === ids[0])!;
          const tryOff = (flip: boolean) => applySketch(doc, offsetEntities(sketchOf(doc), ids, opts.offset, flip), src.layer);
          const A = tryOff(false), B = tryOff(true);
          const before = new Set(doc.geom.entities.map(x => x.id));
          const gap = (d: DraftDoc) => Math.min(...d.geom.entities.filter(x => !before.has(x.id)).map(x => { const g = pickEntity({ ...d, geom: { ...d.geom, entities: [x] } }, p, 1e9); return g ? distToEnt(d, x, p) : 1e9; }));
          commit(gap(A) <= gap(B) ? A : B); setSel(new Set()); return;
        }
        default:
      }
    } catch (e) { fail(e); }
  };

  // ---------------------------------------------------------------- selection picking (paper space)
  const pickAny = (paper: P2): string | null => {
    const m = toModel(shown.sheet, paper);
    const pad = 2.5 / view.k * 2;
    for (const pr of prims) { if (pr.t !== "text" || !(pr.dim || pr.anno)) continue; const b = primBox(pr); if (paper[0] >= b[0] - pad && paper[0] <= b[2] + pad && paper[1] >= b[1] - pad && paper[1] <= b[3] + pad) return (pr.dim ?? pr.anno)!; }
    const e = pickEntity(shown, m, tolModel, x => !hiddenLayers.has(x.layer)); if (e) return e.id;
    for (const pr of prims) { if (!(pr.dim || pr.anno)) continue; const b = primBox(pr); if (paper[0] >= b[0] - pad && paper[0] <= b[2] + pad && paper[1] >= b[1] - pad && paper[1] <= b[3] + pad) return (pr.dim ?? pr.anno)!; }
    return null;
  };

  // ---------------------------------------------------------------- pointer events
  const onDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const paper = toPaperXY(e);
    if (e.button === 1 || (e.button === 0 && e.altKey)) { drag.current = { kind: "pan", start: paper, screen: [e.clientX, e.clientY], view }; return; }
    if (e.button === 2) { e.preventDefault(); finishStep(); return; }
    if (e.button !== 0) return;
    if (tool === "select") {
      // grip on a selected entity's point?
      const m = toModel(shown.sheet, paper);
      if (canEdit) {
        const P = pointMap(shown);
        for (const id of sel) { const en = shown.geom.entities.find(x => x.id === id); if (!en) continue;
          for (const ptId of usedPoints(en)) { const q = P.get(ptId)!; if (Math.hypot(q[0] - m[0], q[1] - m[1]) <= tolModel) { drag.current = { kind: "grip", start: paper, screen: [e.clientX, e.clientY], view, id: ptId, base: doc }; return; } } }
      }
      const hit = pickAny(paper);
      if (hit) {
        if (e.shiftKey) setSel(s => { const n = new Set(s); if (n.has(hit)) n.delete(hit); else n.add(hit); return n; });
        else if (!sel.has(hit)) setSel(new Set([hit]));
        if (canEdit && (doc.dims.some(d => d.id === hit) || doc.annos.some(a => a.id === hit && a.type !== "hatch" && a.type !== "centermark"))) drag.current = { kind: "label", start: paper, screen: [e.clientX, e.clientY], view, id: hit, base: doc };
        return;
      }
      if (!e.shiftKey) setSel(new Set());
      drag.current = { kind: "box", start: paper, screen: [e.clientX, e.clientY], view };
      setBox({ a: paper, b: paper });
      return;
    }
    const { p, s } = resolve(paper);
    if (["trim", "extend", "fillet", "chamfer", "centermark", "hatch", "mirror", "offset"].includes(tool)) { entityClick(toModel(shown.sheet, paper), e.shiftKey); return; }
    if (tool === "dimr" || tool === "dimd" || tool === "dima") { specialDim(toModel(shown.sheet, paper)); return; }
    placePoint(p, s);
  };

  const specialDim = (m: P2) => {
    if (!canEdit) return;
    const st = step;
    if (tool === "dima") {
      if (st.ents.length < 2) { const l = pickLine(m); if (!l) { toast.info("Pick a line"); return; } if (st.ents.includes(l.id)) return; setStep({ ...st, ents: [...st.ents, l.id] }); return; }
      addEntities(d => d.dims.push({ id: uid("d"), type: "angle", l1: st.ents[0]!, l2: st.ents[1]!, pos: m })); finishStep(); return;
    }
    if (!st.ents.length) { const r = pickRound(m); if (!r) { toast.info("Pick a circle or an arc"); return; } setStep({ ...st, ents: [r.id] }); return; }
    addEntities(d => d.dims.push({ id: uid("d"), type: tool === "dimr" ? "radius" : "diameter", ent: st.ents[0]!, pos: m })); finishStep();
  };

  const onMove = (e: React.PointerEvent) => {
    const paper = toPaperXY(e);
    const dg = drag.current;
    if (dg) {
      if (dg.kind === "pan") { setView({ ...dg.view, x: dg.view.x + e.clientX - dg.screen[0], y: dg.view.y + e.clientY - dg.screen[1] }); return; }
      if (dg.kind === "box") { setBox({ a: dg.start, b: paper }); return; }
      const dm = [(paper[0] - dg.start[0]) / kModel, -(paper[1] - dg.start[1]) / kModel] as P2;
      if (Math.hypot(e.clientX - dg.screen[0], e.clientY - dg.screen[1]) < 3 && !dg.moved) return;
      dg.moved = true;
      const base = dg.base!;
      if (dg.kind === "grip") {
        const raw = toModel(shown.sheet, paper);
        const s = snapOn ? findSnap(base, raw, tolModel, snaps, null, new Set(base.geom.entities.filter(x => usedPoints(x).includes(dg.id!)).map(x => x.id))) : null;
        const tgt = s?.p ?? raw;
        setDocRaw({ ...base, geom: { ...base.geom, points: base.geom.points.map(q => (q.id === dg.id ? { ...q, x: tgt[0], y: tgt[1] } : q)) } });
      } else {
        setDocRaw({ ...base, dims: base.dims.map(d => (d.id === dg.id ? { ...d, pos: [d.pos[0] + dm[0], d.pos[1] + dm[1]] as P2 } : d)),
          annos: base.annos.map(a => (a.id === dg.id && "pos" in a ? { ...a, pos: [a.pos[0] + dm[0], a.pos[1] + dm[1]] as P2 } : a.id === dg.id && a.type === "leader" ? { ...a, pts: a.pts.map((q, i) => (i === 0 ? q : [q[0] + dm[0], q[1] + dm[1]] as P2)) } : a)) });
      }
      return;
    }
    const r = resolve(paper);
    setCursor(r.p); setSnap(r.s);
  };

  const onUp = (e: React.PointerEvent) => {
    const dg = drag.current; drag.current = null;
    if (!dg) return;
    if (dg.kind === "box") {
      const end = toPaperXY(e); // the release point itself: the last move may not have rendered yet
      const [x0, x1] = [Math.min(dg.start[0], end[0]), Math.max(dg.start[0], end[0])], [y0, y1] = [Math.min(dg.start[1], end[1]), Math.max(dg.start[1], end[1])];
      setBox(null);
      if (x1 - x0 < 0.5 && y1 - y0 < 0.5) return;
      const groups = new Map<string, number[][]>();
      for (const pr of prims) { const key = pr.ent ?? pr.dim ?? pr.anno; if (!key) continue; const arr = groups.get(key) ?? []; arr.push(primBox(pr)); groups.set(key, arr); }
      const inside = [...groups].filter(([, bs]) => bs.every(b => b[0] >= x0 && b[2] <= x1 && b[1] >= y0 && b[3] <= y1)).map(([k]) => k);
      setSel(s => new Set([...s, ...inside]));
      return;
    }
    if ((dg.kind === "grip" || dg.kind === "label") && dg.moved && dg.base) {
      setPast(p => [...p.slice(-99), dg.base!]); setFuture([]); setDirty(true);
    }
  };

  // ---------------------------------------------------------------- keyboard + typed input
  const deleteSel = useCallback(() => {
    if (!sel.size || !canEdit) return;
    const entIds = [...sel].filter(i => doc.geom.entities.some(e => e.id === i));
    let d = entIds.length ? applySketch(doc, removeItems(sketchOf(doc), entIds), layer) : cloneDoc(doc);
    d = { ...d, dims: d.dims.filter(x => !sel.has(x.id)), annos: d.annos.filter(x => !sel.has(x.id)) };
    commit(d); setSel(new Set());
  }, [sel, doc, canEdit, layer, commit]);

  const applyInput = () => {
    const t = input.trim(); if (!t) return;
    setInput("");
    if (tool === "rotate" && step.pts.length === 1 && /^-?\d+(\.\d+)?$/.test(t)) { commit(transformSelection(doc, sel, rotateAbout(step.pts[0]!, +t), { copy: opts.copyMode })); finishStep(); return; }
    if ((tool === "circle" && step.pts.length === 1) && /^\d+(\.\d+)?$/.test(t)) { const c = step.pts[0]!; placePoint([c[0] + +t, c[1]], null); return; }
    const p = parsePointInput(t, lastPt, cursor);
    if (!p) { toast.error("Type x,y — @dx,dy — @length<angle — or a length along the cursor"); return; }
    placePoint(p, null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      const typing = tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT") && tgt.dataset.cmd !== "1";
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); void save(); return; }
      if (typing) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
      if (e.key === "Escape") { if (step.pts.length || step.ents.length || step.base) finishStep(); else { setTool("select"); setSel(new Set()); } return; }
      if (e.key === "F8") { e.preventDefault(); setOrtho(o => !o); setPolar(false); return; }
      if (e.key === "F10") { e.preventDefault(); setPolar(o => !o); setOrtho(false); return; }
      if (e.key === "F3") { e.preventDefault(); setSnapOn(o => !o); return; }
      if (tgt?.dataset.cmd === "1") return;
      if (e.key === "Delete" || e.key === "Backspace") { deleteSel(); return; }
      if (e.key === "Enter") { finishStep(); return; }
      if (/^[0-9@.,\-<]$/.test(e.key) && POINT_TOOLS.has(tool) && tool !== "select") { e.preventDefault(); setInput(v => v + e.key); (document.querySelector("[data-cmd='1']") as HTMLInputElement | null)?.focus(); return; }
      const t = TOOLS.flatMap(g => g.items).find(x => x.key?.toLowerCase() === e.key.toLowerCase());
      if (t && !e.ctrlKey && !e.metaKey && !e.altKey) setTool(t.id);
      if (e.key.toLowerCase() === "s" && !e.ctrlKey) setTool("select");
      if (e.key.toLowerCase() === "f") fit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => {
    const beforeUnload = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  // ---------------------------------------------------------------- fragments (templates, assist)
  const insertFragment = (frag: Fragment) => {
    const d = cloneDoc(doc);
    const taken = new Set([...d.geom.points.map(p => p.id), ...d.geom.entities.map(e => e.id), ...d.dims.map(x => x.id), ...d.annos.map(a => a.id)]);
    const ren = new Map<string, string>();
    const R = (i: string) => { if (!ren.has(i)) ren.set(i, taken.has(i) ? uid("f") : i); return ren.get(i)!; };
    frag.geom.points.forEach(p => d.geom.points.push({ ...p, id: R(p.id) }));
    frag.geom.entities.forEach(e => d.geom.entities.push(e.type === "line" ? { ...e, id: R(e.id), p1: R(e.p1), p2: R(e.p2) } : e.type === "circle" ? { ...e, id: R(e.id), c: R(e.c) } : { ...e, id: R(e.id), c: R(e.c), p1: R(e.p1), p2: R(e.p2) }));
    frag.dims.forEach(x => d.dims.push(x.type === "linear" ? { ...x, id: R(x.id), a: R(x.a), b: R(x.b) } : x.type === "angle" ? { ...x, id: R(x.id), l1: R(x.l1), l2: R(x.l2) } : x.type === "ordinate" ? { ...x, id: R(x.id), origin: R(x.origin), pt: R(x.pt) } : { ...x, id: R(x.id), ent: R(x.ent) }));
    frag.annos.forEach(a => d.annos.push(a.type === "centermark" ? { ...a, id: R(a.id), ent: R(a.ent) } : a.type === "hatch" ? { ...a, id: R(a.id), loops: a.loops.map(l => l.map(R)) } : { ...a, id: R(a.id) }));
    commit(d);
    setSel(new Set(frag.geom.entities.map(e => R(e.id))));
  };

  const openRevision = async (rev: number) => {
    if (rev === state.rev) { setPreview(null); return; }
    try { const r = await draftsApi.revision(state.id, rev); setPreview({ rev, doc: r.doc }); } catch (e) { fail(e); }
  };
  const restoreRevision = () => { if (!preview) return; commit(cloneDoc(preview.doc)); setPreview(null); toast.success(`Revision ${preview.rev} restored into the editor. Save to keep it as a new revision.`); };

  const exportFile = async (name: string) => {
    let rev = state.rev;
    if (dirty) { const r = await save("Saved for export"); if (!r) return; rev = r.rev; }
    location.href = draftsApi.file(state.id, name, rev);
  };

  // ---------------------------------------------------------------- render
  const hint = (() => {
    const t = TOOL_BY_ID.get(tool as ToolId);
    if (tool === "select") return "Select: click, Shift-click to add, drag a box; drag a dimension or note to move it; drag a grip to reshape. Delete removes.";
    if (NEEDS_SELECTION.has(tool) && !sel.size) return `${t?.label}: select the entities first (Select tool), then choose ${t?.label}.`;
    if (tool === "dimo" && !step.base) return "Ordinate: click the origin (datum) point first.";
    if ((tool === "dimb" || tool === "dimc") && !step.base) return `${t?.label}: click the first point.`;
    return t?.hint ?? "";
  })();
  const selList = [...sel];
  const P = pointMap(shown);
  const selected = new Set(sel);

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="draft-editor">
      <ModuleHeader code="drawings" icon={<Ruler className="h-4 w-4" />} title="Drawing Studio" projectId={null}
        files={<FileButtons ext="fwdrw" saveUrl={moduleExportUrl("draft", state.id)} saveName={`${name || "drawing"}.fwdrw`} />}
        actions={<div className="flex items-center gap-1.5">
          <Button size="sm" variant={dirty ? "primary" : "secondary"} loading={saving} disabled={!state.can_edit || !!preview} icon={<Save className="h-3.5 w-3.5" />} onClick={() => void save()} data-testid="draft-save">
            {dirty ? "Save revision" : `Saved · rev ${state.rev}`}</Button>
          {["PDF", "DXF", "SVG"].map(f => (
            <Tip key={f} side="bottom" content={f === "DXF" ? "DXF: true-size geometry, real DIMENSION and HATCH entities on ISO 128 layers; sheet in a paper-space layout" : `${f} of the saved revision (saves your changes first)`}>
              <button type="button" data-download={f.toLowerCase()} onClick={() => void exportFile(`sheet.${f.toLowerCase()}`)}
                className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-panel px-2.5 text-[12.5px] font-medium hover:bg-panel2"><Download className="h-3.5 w-3.5" />{f}</button>
            </Tip>))}
        </div>}>
        <span className="mx-1 h-5 w-px bg-border" />
        <button onClick={() => { if (!dirty || confirm("Leave without saving your changes?")) onBack(); }} className="whitespace-nowrap text-[12px] text-muted hover:text-primary">All drawings</button>
        <input aria-label="Drawing name" value={name} disabled={!state.can_edit} onChange={e => { setName(e.target.value); setDirty(true); }} maxLength={80}
          className="h-8 w-56 min-w-[120px] rounded border border-transparent bg-transparent px-2 text-[13px] font-medium hover:border-border focus:border-primary focus:outline-none" />
        <Tip side="bottom" content="This sheet is drawn directly in 2D. It is not linked to a 3D model, so no model-consistency check runs; dimension values are measured from the drawn geometry.">
          <span><Badge className="whitespace-nowrap">2D only · no model</Badge></span></Tip>
        <Badge className="whitespace-nowrap">{shown.sheet.size} · {shown.sheet.scale[0]}:{shown.sheet.scale[1]} · {shown.sheet.units}</Badge>
      </ModuleHeader>

      {/* ribbon */}
      <div className="flex shrink-0 items-stretch gap-0 overflow-x-auto border-b border-border bg-panel px-2 py-1" data-testid="draft-ribbon">
        <div className="flex items-center gap-0.5 pr-2">
          <ToolBtn id="select" active={tool === "select"} label="Select" icon={<MousePointer2 />} onClick={() => setTool("select")} k="S" />
          <ToolBtn label="Undo" icon={<Undo2 />} onClick={undo} disabled={!past.length || !canEdit} k="Ctrl+Z" />
          <ToolBtn label="Redo" icon={<Redo2 />} onClick={redo} disabled={!future.length || !canEdit} k="Ctrl+Y" />
          <ToolBtn label="Fit" icon={<Maximize2 />} onClick={fit} k="F" />
        </div>
        {TOOLS.map(g => (
          <div key={g.group} className="flex flex-col border-l border-border px-1.5">
            <div className="flex items-center gap-0.5">{g.items.map(t => <ToolBtn key={t.id} id={t.id} active={tool === t.id} label={t.label} icon={t.icon} k={t.key} disabled={!canEdit} onClick={() => setTool(t.id)} />)}</div>
            <div className="text-center text-[10px] uppercase tracking-wide text-muted">{g.group}</div>
          </div>
        ))}
      </div>

      {preview && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-[12.5px]" data-testid="rev-preview">
          Viewing revision {preview.rev} (read-only).
          {state.can_edit && <button className="link font-medium" onClick={restoreRevision}>Restore into the editor</button>}
          <button className="link" onClick={() => setPreview(null)}>Back to the current drawing</button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <div ref={wrapRef} className={cx("absolute inset-0 overflow-hidden bg-[#e9edf2] dark:bg-[#1b2027]", tool === "select" ? "cursor-default" : "cursor-crosshair")}
            onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onContextMenu={e => e.preventDefault()} onDoubleClick={() => tool === "select" && fit()}
            onPointerLeave={() => { setCursor(null); setSnap(null); }} data-testid="draft-canvas">
            <svg ref={svgRef} className="absolute left-0 top-0 h-full w-full select-none" style={{ fontFamily: "Helvetica, Arial, 'Liberation Sans', sans-serif" }}>
              <style>{SHEET_CSS}</style>
              <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
                <rect x={0} y={0} width={W} height={H} fill="#fff" stroke="#c8d0da" strokeWidth={0.3} style={{ filter: "drop-shadow(0 1px 3px rgba(0,0,0,.18))" }} />
                {frameQ.data && <PrimsSvg prims={frameQ.data.prims} />}
                <PrimsSvg prims={prims} sel={selected} />
                {/* grips */}
                {tool === "select" && selList.map(id => shown.geom.entities.find(e => e.id === id)).filter((e): e is DEnt => !!e).flatMap(e => usedPoints(e)).map((ptId, i) => {
                  const q = P.get(ptId); if (!q) return null; const pp = toPaper(shown.sheet, q); const s = 4 / view.k;
                  return <rect key={`${ptId}-${i}`} x={pp[0] - s / 2} y={pp[1] - s / 2} width={s} height={s} fill="#2563eb" stroke="#fff" strokeWidth={0.6 / view.k} />;
                })}
                <Preview doc={shown} tool={tool} step={step} cursor={cursor} opts={opts} k={view.k} />
                {snap && cursor && <SnapMark p={toPaper(shown.sheet, snap.p)} kind={snap.kind} k={view.k} />}
                {box && <rect x={Math.min(box.a[0], box.b[0])} y={Math.min(box.a[1], box.b[1])} width={Math.abs(box.b[0] - box.a[0])} height={Math.abs(box.b[1] - box.a[1])}
                  fill="rgba(37,99,235,.08)" stroke="#2563eb" strokeWidth={0.8 / view.k} strokeDasharray={`${3 / view.k} ${2 / view.k}`} />}
              </g>
            </svg>
          </div>
          {pendingFrag && (
            <div className="absolute left-1/2 top-3 z-10 w-[min(560px,90%)] -translate-x-1/2 rounded-lg border border-primary/30 bg-panel p-3 text-[12.5px] shadow-pop" data-testid="assist-result">
              <div className="flex items-start gap-2"><Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <div className="min-w-0 flex-1"><div>{pendingFrag.message}</div>
                  {pendingFrag.missing.length > 0 && <div className="mt-1 text-warning">Not in your request (not drawn): {pendingFrag.missing.join("; ")}</div>}
                  <div className="mt-1 text-muted">{pendingFrag.frag.geom.entities.length} entities, {pendingFrag.frag.dims.length} dimensions. Nothing is saved until you save.</div></div></div>
              <div className="mt-2 flex justify-end gap-1.5">
                <Button size="sm" variant="secondary" onClick={() => setPendingFrag(null)}>Discard</Button>
                <Button size="sm" onClick={() => { insertFragment(pendingFrag.frag); setPendingFrag(null); setTool("select"); }} data-testid="assist-insert">Place on the sheet</Button>
              </div>
            </div>
          )}
        </div>
        <DraftSidePanel doc={shown} canEdit={canEdit} state={state} sel={sel} setSel={setSel} commit={commit} tool={tool} opts={opts} setOpts={setOpts}
          layer={layer} setLayer={setLayer} hiddenLayers={hiddenLayers} setHiddenLayers={setHiddenLayers} onInsert={(f, msg, missing) => setPendingFrag({ frag: f, message: msg, missing })}
          onOpenRev={openRevision} previewRev={preview?.rev ?? null} dirty={dirty} />
      </div>

      {/* status / command line */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-t border-border bg-panel px-3 text-[12px]" data-testid="draft-status">
        <span className="min-w-0 flex-1 truncate text-muted" data-testid="draft-hint">{hint}</span>
        {POINT_TOOLS.has(tool) && tool !== "select" && (
          <input data-cmd="1" value={input} onChange={e => setInput(e.target.value)} placeholder="x,y  @dx,dy  @len<ang  length"
            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); applyInput(); } if (e.key === "Escape") { setInput(""); (e.target as HTMLInputElement).blur(); } }}
            className="h-6 w-48 rounded border border-border bg-panel2 px-2 font-mono text-[11.5px] outline-none focus:border-primary" aria-label="Typed input" />
        )}
        <span className="w-44 text-right font-mono tabular-nums text-muted" data-testid="draft-cursor">{cursor ? `${cursor[0].toFixed(2)}, ${cursor[1].toFixed(2)} ${shown.sheet.units}` : ""}</span>
        <StatusToggle on={snapOn} onClick={() => setSnapOn(v => !v)} label="Snap" title="Object snaps (F3)" icon={<Magnet className="h-3 w-3" />} />
        <StatusToggle on={snaps.grid} onClick={() => setSnaps(s => ({ ...s, grid: !s.grid }))} label={`Grid ${snaps.gridStep}`} title="Snap to grid" />
        <StatusToggle on={ortho} onClick={() => { setOrtho(v => !v); setPolar(false); }} label="Ortho" title="Ortho: 0° / 90° (F8)" />
        <StatusToggle on={polar} onClick={() => { setPolar(v => !v); setOrtho(false); }} label="Polar 15°" title="Polar tracking (F10)" />
      </div>
    </div>
  );
}

function layerOfPoint(doc: DraftDoc, pt: string): Layer { return doc.geom.entities.find(e => usedPoints(e).includes(pt))?.layer ?? "visible"; }
function distToEnt(doc: DraftDoc, e: DEnt, p: P2): number {
  const P = pointMap(doc);
  if (e.type === "line") { const a = P.get(e.p1)!, b = P.get(e.p2)!; const d = [b[0] - a[0], b[1] - a[1]]; const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * d[0]! + (p[1] - a[1]) * d[1]!) / ((d[0]! ** 2 + d[1]! ** 2) || 1))); return Math.hypot(a[0] + d[0]! * t - p[0], a[1] + d[1]! * t - p[1]); }
  const c = circleOf(doc, e.id, P)!; return Math.abs(Math.hypot(p[0] - c.c[0], p[1] - c.c[1]) - c.r);
}

const SHEET_CSS = Object.entries(LINE_STYLES).map(([n, [w, dash, col]]) =>
  `.drw-${n}{fill:none;stroke:${col};stroke-width:${w};${dash ? `stroke-dasharray:${dash.join(" ")};` : ""}stroke-linecap:${n === "visible" || n === "frame" ? "round" : "butt"};stroke-linejoin:round}`).join("")
  + ".drw-sel{stroke:#2563eb!important;fill:none}.drw-selfill{fill:#2563eb!important}.drw-seltext{fill:#2563eb!important}";

/** Sheet primitives as SVG, the same classes and styles as the exported sheet. Construction lines show only here. */
function PrimsSvg({ prims, sel }: { prims: Prim[]; sel?: Set<string> }) {
  return <>{prims.map((p, i) => {
    const key = (p as { ent?: string; dim?: string; anno?: string });
    const on = !!sel && !!(key.ent && sel.has(key.ent) || key.dim && sel.has(key.dim) || key.anno && sel.has(key.anno));
    const cls = `drw-${p.l}${on ? " drw-sel" : ""}`;
    switch (p.t) {
      case "line": return <line key={i} className={cls} x1={p.p[0]} y1={p.p[1]} x2={p.p[2]} y2={p.p[3]} />;
      case "poly": { const pts = p.p.map(q => `${q[0]},${q[1]}`).join(" "); return p.closed ? <polygon key={i} className={cls} points={pts} /> : <polyline key={i} className={cls} points={pts} />; }
      case "circle": return <circle key={i} className={cls} cx={p.p[0]} cy={p.p[1]} r={p.p[2]} />;
      case "arc": {
        const [cx_, cy, r, a0, a1] = p.p; const x0 = cx_ + r * Math.cos(a0 * Math.PI / 180), y0 = cy - r * Math.sin(a0 * Math.PI / 180);
        const x1 = cx_ + r * Math.cos(a1 * Math.PI / 180), y1 = cy - r * Math.sin(a1 * Math.PI / 180);
        if (a1 - a0 >= 359.999) return <circle key={i} className={cls} cx={cx_} cy={cy} r={r} />;
        return <path key={i} className={cls} d={`M${x0} ${y0} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 0 ${x1} ${y1}`} />;
      }
      case "fill": return <polygon key={i} className={on ? "drw-selfill" : undefined} points={p.p.map(q => `${q[0]},${q[1]}`).join(" ")} fill={FILLS[p.l] ?? "#222222"} stroke="none" />;
      case "text": return <text key={i} className={on ? "drw-seltext" : undefined} x={p.x} y={p.y} fontSize={p.s} fill={TEXT_COLORS[p.color ?? "normal"] ?? "#111"} textAnchor={p.anchor}
        fontWeight={p.font === "bold" ? "bold" : undefined} fontStyle={p.font === "italic" ? "italic" : undefined}
        transform={p.rot ? `rotate(${-p.rot} ${p.x} ${p.y})` : undefined}>{p.txt}</text>;
    }
    return null;
  })}</>;
}

function SnapMark({ p, kind, k }: { p: P2; kind: Snap["kind"]; k: number }) {
  const s = 5 / k, w = 1.2 / k, c = "#e11d48";
  const label = <text x={p[0] + s * 1.2} y={p[1] - s * 1.2} fontSize={9 / k} fill={c}>{kind}</text>;
  if (kind === "endpoint") return <g><rect x={p[0] - s} y={p[1] - s} width={2 * s} height={2 * s} fill="none" stroke={c} strokeWidth={w} />{label}</g>;
  if (kind === "midpoint") return <g><polygon points={`${p[0]},${p[1] - s} ${p[0] + s},${p[1] + s} ${p[0] - s},${p[1] + s}`} fill="none" stroke={c} strokeWidth={w} />{label}</g>;
  if (kind === "center") return <g><circle cx={p[0]} cy={p[1]} r={s} fill="none" stroke={c} strokeWidth={w} />{label}</g>;
  if (kind === "intersection") return <g><path d={`M${p[0] - s} ${p[1] - s}L${p[0] + s} ${p[1] + s}M${p[0] + s} ${p[1] - s}L${p[0] - s} ${p[1] + s}`} stroke={c} strokeWidth={w} />{label}</g>;
  if (kind === "perpendicular") return <g><path d={`M${p[0] - s} ${p[1] + s}H${p[0] + s}M${p[0]} ${p[1] + s}V${p[1] - s}`} stroke={c} strokeWidth={w} fill="none" />{label}</g>;
  return <g><circle cx={p[0]} cy={p[1]} r={s * 0.5} fill={c} />{label}</g>;
}

function Preview({ doc, tool, step, cursor, opts, k }: { doc: DraftDoc; tool: ToolId; step: Step; cursor: P2 | null; opts: ToolOpts; k: number }) {
  if (!cursor) return null;
  const T = (p: P2) => toPaper(doc.sheet, p);
  const c = T(cursor); const st = { stroke: "#2563eb", strokeWidth: 0.8 / k, fill: "none", strokeDasharray: `${4 / k} ${2 / k}` };
  const cross = <g stroke="#2563eb" strokeWidth={0.6 / k} opacity={0.5}><line x1={c[0] - 12 / k} y1={c[1]} x2={c[0] + 12 / k} y2={c[1]} /><line x1={c[0]} y1={c[1] - 12 / k} x2={c[0]} y2={c[1] + 12 / k} /></g>;
  if (!step.pts.length) return tool === "select" ? null : cross;
  const a = T(step.pts[0]!), last = T(step.pts[step.pts.length - 1]!);
  const kk = kOf(doc.sheet);
  let shape: ReactNode = null;
  switch (tool) {
    case "line": case "centerline": case "move": case "copy": case "leader": case "balloon": case "gdt": case "datum": case "dimh": case "dimv": case "dimal": case "dim":
      shape = <line {...st} x1={last[0]} y1={last[1]} x2={c[0]} y2={c[1]} />; break;
    case "rect": shape = <rect {...st} x={Math.min(a[0], c[0])} y={Math.min(a[1], c[1])} width={Math.abs(c[0] - a[0])} height={Math.abs(c[1] - a[1])} />; break;
    case "circle": shape = <circle {...st} cx={a[0]} cy={a[1]} r={Math.hypot(c[0] - a[0], c[1] - a[1])} />; break;
    case "polygon": { const r = Math.hypot(c[0] - a[0], c[1] - a[1]); const a0 = Math.atan2(c[1] - a[1], c[0] - a[0]); const n = Math.max(3, Math.round(opts.sides)); const R = opts.inscribed ? r : r / Math.cos(Math.PI / n); const s0 = opts.inscribed ? a0 : a0 - Math.PI / n;
      shape = <polygon {...st} points={Array.from({ length: n }, (_, i) => `${a[0] + R * Math.cos(s0 + i * 2 * Math.PI / n)},${a[1] + R * Math.sin(s0 + i * 2 * Math.PI / n)}`).join(" ")} />; break; }
    case "arc": case "slot": case "rotate": shape = <>{step.pts.map((p, i) => { const q = T(p); return <circle key={i} cx={q[0]} cy={q[1]} r={1.5 / k} fill="#2563eb" />; })}<line {...st} x1={a[0]} y1={a[1]} x2={c[0]} y2={c[1]} />
      {tool === "arc" && step.pts.length === 1 && <circle {...st} cx={a[0]} cy={a[1]} r={Math.hypot(c[0] - a[0], c[1] - a[1])} opacity={0.4} />}
      {tool === "slot" && step.pts.length === 2 && <line {...st} x1={a[0]} y1={a[1]} x2={T(step.pts[1]!)[0]} y2={T(step.pts[1]!)[1]} />}</>; break;
    default: shape = <line {...st} x1={last[0]} y1={last[1]} x2={c[0]} y2={c[1]} />;
  }
  void kk;
  return <g>{cross}{shape}</g>;
}

function ToolBtn({ id, active, label, icon, onClick, disabled, k }: { id?: string; active?: boolean; label: string; icon: ReactNode; onClick: () => void; disabled?: boolean; k?: string }) {
  return (
    <Tip side="bottom" content={k ? `${label} (${k})` : label}>
      <button type="button" data-tool={id} aria-label={label} disabled={disabled} onClick={onClick}
        className={cx("flex h-8 w-8 items-center justify-center rounded text-text transition disabled:opacity-40 [&>svg]:h-4 [&>svg]:w-4",
          active ? "bg-primary-soft text-primary ring-1 ring-primary/40" : "hover:bg-text/5")}>{icon}</button>
    </Tip>
  );
}

function StatusToggle({ on, onClick, label, title, icon }: { on: boolean; onClick: () => void; label: string; title: string; icon?: ReactNode }) {
  return <button type="button" title={title} onClick={onClick} className={cx("inline-flex h-6 items-center gap-1 rounded px-2 text-[11.5px] font-medium", on ? "bg-primary-soft text-primary" : "text-muted hover:bg-text/5")}>{icon}{label}</button>;
}

export type { GdtSymbol, Anno, Dim };
export { localStamp };
