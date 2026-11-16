import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, Check, Circle as CircleIcon, CircleDashed, Equal, Grid2x2, Lock, MousePointer2,
  Pencil, RectangleHorizontal, Redo2, Ruler, Spline, Trash2, Undo2, X,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { ManualFeature, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button, Input, Tip } from "@/components/ui";
import { clone, profiles, solve, uid, type SConstraint, type SEntity, type Sketch, type SPoint } from "@/sketch/model";
import type { Topo, V3 } from "@/viewer/types";

type ToolT = "select" | "line" | "rect" | "circle" | "arc" | "dim";
type Sel = { kind: "pt" | "ent"; id: string };
type NoId<T> = T extends unknown ? Omit<T, "id"> : never;
interface PlaneDef { origin: V3; normal: V3; x_dir: V3 }

const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const crossV = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const EMPTY: Sketch = { points: [], entities: [], constraints: [] };

export default function SketchEditor({ project, topo, plane, faceId, editing, onDone, onCancel }: {
  project: Project; topo: Topo | null; plane: PlaneDef; faceId: number | null; editing: ManualFeature | null;
  onDone: () => void; onCancel: () => void;
}) {
  const yDir = useMemo(() => crossV(plane.normal, plane.x_dir), [plane]);
  const to2 = (p: V3): [number, number] => { const d: V3 = [p[0] - plane.origin[0], p[1] - plane.origin[1], p[2] - plane.origin[2]]; return [dot(d, plane.x_dir), dot(d, yDir)]; };
  // reference geometry: edges of the face being sketched on
  const ref = useMemo(() => {
    if (!topo || faceId === null) return [] as [number, number][][];
    return topo.faces[faceId]!.edges.map(eid => { const p = topo.edges[eid]!.pts; const out: [number, number][] = []; for (let i = 0; i < p.length; i += 3) out.push(to2([p[i]!, p[i + 1]!, p[i + 2]!])); return out; });
  }, [topo, faceId]); // eslint-disable-line react-hooks/exhaustive-deps
  const refVerts = useMemo(() => {
    if (!topo || faceId === null) return [] as [number, number][];
    const ids = new Set<number>(); topo.faces[faceId]!.edges.forEach(e => topo.edges[e]!.verts.forEach(v => ids.add(v)));
    return [...ids].map(v => to2(topo.vertices[v]!));
  }, [topo, faceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const initial = (editing?.editor as Sketch | undefined) ?? EMPTY;
  const [sk, setSk] = useState<Sketch>(() => clone(initial));
  const [hist, setHist] = useState<Sketch[]>([]);
  const [fut, setFut] = useState<Sketch[]>([]);
  const [tool, setTool] = useState<ToolT>("line");
  const [sel, setSel] = useState<Sel[]>([]);
  const [pending, setPending] = useState<string[]>([]); // point ids placed by the active tool
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [dimEdit, setDimEdit] = useState<{ cid: string; x: number; y: number; value: string } | null>(null);
  const [mode, setMode] = useState<"add" | "cut">(editing?.mode ?? "add");
  const [dist, setDist] = useState(String(editing?.distance ?? 10));
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; dof: number }>({ ok: true, dof: 0 });
  const svg = useRef<SVGSVGElement>(null);
  const [view, setView] = useState({ s: 4, ox: 0, oy: 0 }); // px per mm, screen offset of sketch origin
  const drag = useRef<{ pt?: string; pan?: [number, number, number, number] } | null>(null);

  // fit reference into view
  useEffect(() => {
    const r = svg.current!.getBoundingClientRect();
    const pts = ref.flat(); if (!pts.length) { setView({ s: 4, ox: r.width / 2, oy: r.height / 2 }); return; }
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const w = Math.max(...xs) - Math.min(...xs) || 50, h = Math.max(...ys) - Math.min(...ys) || 50;
    const s = Math.min(r.width / w, r.height / h) * 0.75;
    const cxm = (Math.max(...xs) + Math.min(...xs)) / 2, cym = (Math.max(...ys) + Math.min(...ys)) / 2;
    setView({ s, ox: r.width / 2 - cxm * s, oy: r.height / 2 + cym * s });
  }, [ref]);

  const scr = (p: [number, number]) => [view.ox + p[0] * view.s, view.oy - p[1] * view.s] as [number, number];
  const mm = (e: { clientX: number; clientY: number }) => { const r = svg.current!.getBoundingClientRect(); return [(e.clientX - r.left - view.ox) / view.s, -(e.clientY - r.top - view.oy) / view.s] as [number, number]; };
  const P = (id: string) => sk.points.find(p => p.id === id)!;
  const snapTol = 9 / view.s;

  const commit = (next: Sketch, resolve = true) => {
    setHist(h => [...h.slice(-80), sk]); setFut([]);
    if (resolve) { const r = solve(next); setSk(r.sketch); setStatus({ ok: r.ok, dof: r.dof }); if (!r.ok) toast.warning("Constraints conflict — the sketch is over-defined. Undo or remove a relation."); }
    else setSk(next);
  };
  useEffect(() => { const r = solve(sk); setStatus({ ok: r.ok, dof: r.dof }); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /** Snap to an existing sketch point, a reference vertex, or nothing. Returns [point id | null, position]. */
  const snap = (p: [number, number], s: Sketch): [string | null, [number, number], SPoint | null] => {
    let best: SPoint | null = null; let bd = snapTol;
    for (const q of s.points) { const d = Math.hypot(q.x - p[0], q.y - p[1]); if (d < bd) { bd = d; best = q; } }
    if (best) return [best.id, [best.x, best.y], null];
    for (const v of refVerts) if (Math.hypot(v[0] - p[0], v[1] - p[1]) < snapTol) {
      const np: SPoint = { id: uid("p"), x: v[0], y: v[1], fixed: true }; return [null, v, np];
    }
    if (Math.hypot(p[0], p[1]) < snapTol) { const np: SPoint = { id: uid("p"), x: 0, y: 0, fixed: true }; return [null, [0, 0], np]; }
    return [null, p, null];
  };
  const getPoint = (s: Sketch, p: [number, number]): string => {
    const [id, pos, np] = snap(p, s);
    if (id) return id;
    const pt = np ?? { id: uid("p"), x: pos[0], y: pos[1] };
    s.points.push(pt); return pt.id;
  };
  const inferHV = (s: Sketch, line: Extract<SEntity, { type: "line" }>) => {
    const a = s.points.find(p => p.id === line.p1)!, b = s.points.find(p => p.id === line.p2)!;
    const ang = Math.abs(Math.atan2(b.y - a.y, b.x - a.x)) % Math.PI;
    if (Math.min(ang, Math.PI - ang) < 0.05) s.constraints.push({ id: uid("k"), type: "horizontal", line: line.id });
    else if (Math.abs(ang - Math.PI / 2) < 0.05) s.constraints.push({ id: uid("k"), type: "vertical", line: line.id });
  };

  // ------------------------------------------------------------------ hit testing
  const hitEnt = (p: [number, number]): string | null => {
    let best: string | null = null; let bd = snapTol;
    for (const e of sk.entities) {
      let d = Infinity;
      if (e.type === "line") { const a = P(e.p1), b = P(e.p2); const dx = b.x - a.x, dy = b.y - a.y, L2 = dx * dx + dy * dy || 1; const t = Math.max(0, Math.min(1, ((p[0] - a.x) * dx + (p[1] - a.y) * dy) / L2)); d = Math.hypot(a.x + t * dx - p[0], a.y + t * dy - p[1]); }
      else { const c = P(e.c); const R = e.type === "circle" ? e.r : Math.hypot(P(e.p1).x - c.x, P(e.p1).y - c.y); d = Math.abs(Math.hypot(p[0] - c.x, p[1] - c.y) - R); }
      if (d < bd) { bd = d; best = e.id; }
    }
    return best;
  };
  const hitPt = (p: [number, number]) => sk.points.find(q => Math.hypot(q.x - p[0], q.y - p[1]) < snapTol)?.id ?? null;

  // ------------------------------------------------------------------ dimensions
  const addDim = (k: SConstraint) => {
    const s = clone(sk); s.constraints.push(k); commit(s);
    const lbl = dimAnchor(k, s); if (lbl) setDimEdit({ cid: k.id, x: lbl[0], y: lbl[1], value: String(+(k as { value: number }).value.toFixed(3)) });
  };
  const dimAnchor = (k: SConstraint, s: Sketch): [number, number] | null => {
    const pp = (id: string) => s.points.find(p => p.id === id)!;
    const en = (id: string) => s.entities.find(e => e.id === id);
    if (k.type === "length") { const e = en(k.line) as Extract<SEntity, { type: "line" }>; if (!e) return null; const a = pp(e.p1), b = pp(e.p2); return [(a.x + b.x) / 2, (a.y + b.y) / 2]; }
    if (k.type === "radius" || k.type === "diameter") { const e = en(k.ent); if (!e || e.type === "line") return null; const c = pp(e.c); const R = e.type === "circle" ? e.r : Math.hypot(pp(e.p1).x - c.x, pp(e.p1).y - c.y); return [c.x + R * 0.7, c.y + R * 0.7]; }
    if (k.type === "distance" || k.type === "hdist" || k.type === "vdist") { const a = pp(k.a), b = pp(k.b); return [(a.x + b.x) / 2, (a.y + b.y) / 2]; }
    return null;
  };
  const dimText = (k: SConstraint) => k.type === "diameter" ? `Ø${(+k.value.toFixed(3))}` : k.type === "radius" ? `R${+k.value.toFixed(3)}` : `${+(k as { value: number }).value.toFixed(3)}`;

  // ------------------------------------------------------------------ pointer handling
  const onDown = (ev: React.PointerEvent) => {
    if (ev.button === 1 || (ev.button === 0 && ev.altKey)) { drag.current = { pan: [ev.clientX, ev.clientY, view.ox, view.oy] }; return; }
    if (ev.button === 2) { setPending([]); return; }
    const p = mm(ev);
    if (tool === "select") {
      const pt = hitPt(p);
      if (pt) { drag.current = { pt }; setHist(h => [...h.slice(-80), sk]); setSel(s => ev.shiftKey || ev.ctrlKey ? [...s.filter(x => x.id !== pt), { kind: "pt", id: pt }] : [{ kind: "pt", id: pt }]); return; }
      const e = hitEnt(p);
      if (e) setSel(s => ev.shiftKey || ev.ctrlKey ? (s.some(x => x.id === e) ? s.filter(x => x.id !== e) : [...s, { kind: "ent", id: e }]) : [{ kind: "ent", id: e }]);
      else setSel([]);
      return;
    }
    if (tool === "dim") {
      const pt = hitPt(p);
      if (pt) {
        if (pending.length === 1 && pending[0] !== pt) {
          const a = P(pending[0]!), b = P(pt);
          addDim({ id: uid("k"), type: "distance", a: a.id, b: b.id, value: Math.hypot(b.x - a.x, b.y - a.y) }); setPending([]);
        } else setPending([pt]);
        return;
      }
      const eid = hitEnt(p); if (!eid) return;
      const e = sk.entities.find(x => x.id === eid)!;
      if (e.type === "line") { const a = P(e.p1), b = P(e.p2); addDim({ id: uid("k"), type: "length", line: e.id, value: Math.hypot(b.x - a.x, b.y - a.y) }); }
      else if (e.type === "circle") addDim({ id: uid("k"), type: "diameter", ent: e.id, value: e.r * 2 });
      else { const c = P(e.c), a = P(e.p1); addDim({ id: uid("k"), type: "radius", ent: e.id, value: Math.hypot(a.x - c.x, a.y - c.y) }); }
      return;
    }
    const s = clone(sk);
    if (tool === "line") {
      const id = getPoint(s, p);
      if (pending.length) {
        if (id === pending[0]) { setPending([]); return; }
        const ln: SEntity = { id: uid("e"), type: "line", p1: pending[0]!, p2: id };
        s.entities.push(ln); inferHV(s, ln); commit(s);
        const closes = sk.points.some(q => q.id === id) && sk.entities.some(e => e.type === "line" && (e.p1 === id || e.p2 === id));
        setPending(closes ? [] : [id]);
      } else { setSk(s); setPending([id]); }
    } else if (tool === "rect") {
      if (!pending.length) { const id = getPoint(s, p); setSk(s); setPending([id]); return; }
      const a = P(pending[0]!) ?? s.points.find(q => q.id === pending[0])!;
      const [, q] = snap(p, s);
      const ids = [a.id, uid("p"), uid("p"), uid("p")];
      s.points.push({ id: ids[1]!, x: q[0], y: a.y }, { id: ids[2]!, x: q[0], y: q[1] }, { id: ids[3]!, x: a.x, y: q[1] });
      const lines = [0, 1, 2, 3].map(i => ({ id: uid("e"), type: "line" as const, p1: ids[i]!, p2: ids[(i + 1) % 4]! }));
      s.entities.push(...lines);
      lines.forEach((l, i) => s.constraints.push({ id: uid("k"), type: i % 2 === 0 ? "horizontal" : "vertical", line: l.id }));
      commit(s); setPending([]);
    } else if (tool === "circle") {
      if (!pending.length) { const id = getPoint(s, p); setSk(s); setPending([id]); return; }
      const c = s.points.find(q => q.id === pending[0])!;
      s.entities.push({ id: uid("e"), type: "circle", c: c.id, r: Math.max(Math.hypot(p[0] - c.x, p[1] - c.y), 0.1) });
      commit(s); setPending([]);
    } else if (tool === "arc") {
      if (pending.length < 2) { const id = getPoint(s, p); setSk(s); setPending([...pending, id]); return; }
      const c = s.points.find(q => q.id === pending[0])!, a = s.points.find(q => q.id === pending[1])!;
      const R = Math.hypot(a.x - c.x, a.y - c.y); const ang = Math.atan2(p[1] - c.y, p[0] - c.x);
      const id = getPoint(s, [c.x + R * Math.cos(ang), c.y + R * Math.sin(ang)]);
      s.entities.push({ id: uid("e"), type: "arc", c: c.id, p1: a.id, p2: id });
      commit(s); setPending([]);
    }
  };
  const onMove = (ev: React.PointerEvent) => {
    const p = mm(ev); setCursor(p);
    const d = drag.current;
    if (d?.pan) { setView(v => ({ ...v, ox: d.pan![2] + ev.clientX - d.pan![0], oy: d.pan![3] + ev.clientY - d.pan![1] })); return; }
    if (d?.pt) {
      const s = clone(sk); const q = s.points.find(x => x.id === d.pt)!;
      if (q.fixed || s.constraints.some(k => k.type === "fix" && k.pt === q.id)) return;
      q.x = p[0]; q.y = p[1]; q.fixed = true;
      const r = solve(s, 25); const back = r.sketch.points.find(x => x.id === d.pt)!; back.fixed = false;
      setSk(r.sketch);
    }
  };
  const onUp = () => { if (drag.current?.pt) { const r = solve(sk); setSk(r.sketch); setStatus({ ok: r.ok, dof: r.dof }); } drag.current = null; };
  const onWheel = (ev: React.WheelEvent) => {
    const r = svg.current!.getBoundingClientRect(); const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const f = ev.deltaY < 0 ? 1.15 : 1 / 1.15;
    setView(v => ({ s: v.s * f, ox: mx - (mx - v.ox) * f, oy: my - (my - v.oy) * f }));
  };
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "Escape") { setPending([]); setTool("select"); }
      if (e.key === "Delete") del();
      if ((e.ctrlKey || e.metaKey) && e.key === "z") undo();
    };
    addEventListener("keydown", h); return () => removeEventListener("keydown", h);
  });

  // ------------------------------------------------------------------ relations
  const selEnts = sel.filter(x => x.kind === "ent").map(x => sk.entities.find(e => e.id === x.id)!).filter(Boolean);
  const selPts = sel.filter(x => x.kind === "pt").map(x => x.id);
  const lines = selEnts.filter(e => e.type === "line");
  const curves = selEnts.filter(e => e.type !== "line");
  const rel = (k: NoId<SConstraint>) => { const s = clone(sk); s.constraints.push({ ...k, id: uid("k") } as SConstraint); commit(s); };
  const relations: { label: string; icon: React.ReactNode; can: boolean; run: () => void }[] = [
    { label: "Horizontal", icon: <span className="text-[13px] font-bold">—</span>, can: lines.length >= 1, run: () => lines.forEach(l => rel({ type: "horizontal", line: l.id })) },
    { label: "Vertical", icon: <span className="text-[13px] font-bold">|</span>, can: lines.length >= 1, run: () => lines.forEach(l => rel({ type: "vertical", line: l.id })) },
    { label: "Parallel", icon: <span className="text-[13px] font-bold">∥</span>, can: lines.length === 2, run: () => rel({ type: "parallel", l1: lines[0]!.id, l2: lines[1]!.id }) },
    { label: "Perpendicular", icon: <span className="text-[13px] font-bold">⊥</span>, can: lines.length === 2, run: () => rel({ type: "perpendicular", l1: lines[0]!.id, l2: lines[1]!.id }) },
    { label: "Equal", icon: <Equal className="h-4 w-4" />, can: lines.length === 2 || curves.length === 2, run: () => rel({ type: "equal", l1: (lines.length === 2 ? lines : curves)[0]!.id, l2: (lines.length === 2 ? lines : curves)[1]!.id }) },
    { label: "Tangent", icon: <Spline className="h-4 w-4" />, can: lines.length === 1 && curves.length === 1, run: () => rel({ type: "tangent", line: lines[0]!.id, ent: curves[0]!.id }) },
    { label: "Concentric", icon: <CircleDashed className="h-4 w-4" />, can: curves.length === 2, run: () => rel({ type: "concentric", e1: curves[0]!.id, e2: curves[1]!.id }) },
    { label: "Point on line/arc", icon: <span className="text-[11px] font-bold">•/</span>, can: selPts.length === 1 && selEnts.length === 1, run: () => rel(selEnts[0]!.type === "line" ? { type: "onLine", pt: selPts[0]!, line: selEnts[0]!.id } : { type: "onCircle", pt: selPts[0]!, ent: selEnts[0]!.id }) },
    { label: "Fix", icon: <Lock className="h-4 w-4" />, can: selPts.length >= 1, run: () => selPts.forEach(pt => rel({ type: "fix", pt })) },
  ];
  const del = () => {
    if (!sel.length) return;
    const s = clone(sk); const ids = new Set(sel.map(x => x.id));
    s.entities = s.entities.filter(e => !ids.has(e.id) && !(e.type === "line" ? ids.has(e.p1) || ids.has(e.p2) : e.type === "circle" ? ids.has(e.c) : ids.has(e.c) || ids.has(e.p1) || ids.has(e.p2)));
    const live = new Set(s.entities.map(e => e.id));
    s.constraints = s.constraints.filter(k => !ids.has(k.id) && Object.entries(k).every(([f, v]) => !["line", "ent", "l1", "l2", "e1", "e2"].includes(f) || live.has(v as string)) && Object.entries(k).every(([f, v]) => !["a", "b", "pt"].includes(f) || !ids.has(v as string)));
    const used = new Set(s.entities.flatMap(e => (e.type === "line" ? [e.p1, e.p2] : e.type === "circle" ? [e.c] : [e.c, e.p1, e.p2])));
    s.points = s.points.filter(p => used.has(p.id));
    commit(s); setSel([]);
  };
  const undo = () => { if (!hist.length) return; setFut(f => [sk, ...f]); setSk(hist[hist.length - 1]!); setHist(h => h.slice(0, -1)); };
  const redo = () => { if (!fut.length) return; setHist(h => [...h, sk]); setSk(fut[0]!); setFut(f => f.slice(1)); };

  const prof = useMemo(() => profiles(sk), [sk]);
  const finish = async () => {
    if (!prof.loops.length) { toast.error("Draw at least one closed profile (lines/arcs meeting end-to-end, or a circle)."); return; }
    const d = Number(dist); if (!(d > 0)) { toast.error("Enter a positive distance"); return; }
    setBusy(true);
    const feature = { op: "sketch", name: editing?.name ?? (mode === "cut" ? "Sketch cut" : "Sketch boss"), suppressed: editing?.suppressed ?? false,
      plane, profiles: prof.loops, distance: d, mode, editor: sk };
    try {
      const t0 = performance.now();
      if (editing) await api.patch(`/api/projects/${project.id}/manual/${editing.id}`, { feature });
      else await api.post(`/api/projects/${project.id}/manual`, { feature });
      toast.success(`${feature.name} ${editing ? "updated" : "added"} · ${((performance.now() - t0) / 1000).toFixed(1)} s`); onDone();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Feature failed"); } finally { setBusy(false); }
  };

  // ------------------------------------------------------------------ render
  const tools: [ToolT, string, React.ReactNode][] = [["select", "Select / drag", <MousePointer2 className="h-4 w-4" />], ["line", "Line (chain; Esc to stop)", <Pencil className="h-4 w-4" />],
    ["rect", "Corner rectangle", <RectangleHorizontal className="h-4 w-4" />], ["circle", "Circle", <CircleIcon className="h-4 w-4" />], ["arc", "Centre-point arc (centre, start, end CCW)", <Spline className="h-4 w-4" />],
    ["dim", "Smart Dimension (line, circle/arc, or two points)", <Ruler className="h-4 w-4" />]];
  const selIds = new Set(sel.map(x => x.id));
  const preview = (() => {
    if (!cursor || !pending.length) return null;
    const a = sk.points.find(p => p.id === pending[0]); if (!a) return null;
    const [, q] = snap(cursor, sk);
    if (tool === "line") return <line x1={scr([a.x, a.y])[0]} y1={scr([a.x, a.y])[1]} x2={scr(q)[0]} y2={scr(q)[1]} className="stroke-primary" strokeDasharray="4 3" />;
    if (tool === "rect") { const [x1, y1] = scr([a.x, a.y]), [x2, y2] = scr(q); return <rect x={Math.min(x1, x2)} y={Math.min(y1, y2)} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} className="fill-none stroke-primary" strokeDasharray="4 3" />; }
    if (tool === "circle") { const [x1, y1] = scr([a.x, a.y]); return <circle cx={x1} cy={y1} r={Math.hypot(q[0] - a.x, q[1] - a.y) * view.s} className="fill-none stroke-primary" strokeDasharray="4 3" />; }
    return null;
  })();
  const defined = status.ok ? (status.dof === 0 ? "Fully defined" : `Under defined · ${status.dof} DOF`) : "Over defined — conflicting relations";

  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-[#f7f9fc] dark:bg-[#161a21]">
      <div className="flex flex-wrap items-center gap-1 border-b border-border bg-panel px-2 py-1.5">
        <span className="mr-2 text-[13px] font-semibold">Sketch</span>
        {tools.map(([t, l, i]) => <Tip key={t} content={l} side="bottom"><button onClick={() => { setTool(t); setPending([]); }} className={cx("rounded p-1.5", tool === t ? "bg-primary text-white" : "text-muted hover:bg-text/5 hover:text-text")} aria-label={l}>{i}</button></Tip>)}
        <span className="mx-1 h-5 w-px bg-border" />
        {relations.map(r => <Tip key={r.label} content={r.label} side="bottom"><button disabled={!r.can} onClick={r.run} className="flex h-7 min-w-7 items-center justify-center rounded px-1 text-muted hover:bg-text/5 hover:text-text disabled:opacity-30" aria-label={r.label}>{r.icon}</button></Tip>)}
        <span className="mx-1 h-5 w-px bg-border" />
        <Tip content="Delete selection" side="bottom"><button onClick={del} disabled={!sel.length} className="rounded p-1.5 text-muted hover:bg-text/5 disabled:opacity-30" aria-label="Delete"><Trash2 className="h-4 w-4" /></button></Tip>
        <Tip content="Undo (Ctrl+Z)" side="bottom"><button onClick={undo} disabled={!hist.length} className="rounded p-1.5 text-muted hover:bg-text/5 disabled:opacity-30" aria-label="Undo"><Undo2 className="h-4 w-4" /></button></Tip>
        <Tip content="Redo" side="bottom"><button onClick={redo} disabled={!fut.length} className="rounded p-1.5 text-muted hover:bg-text/5 disabled:opacity-30" aria-label="Redo"><Redo2 className="h-4 w-4" /></button></Tip>
        <span className={cx("ml-auto rounded-full px-2 py-0.5 text-[11.5px] font-medium", !status.ok ? "bg-danger/10 text-danger" : status.dof === 0 ? "bg-text/10 text-text" : "bg-primary-soft text-primary")}>{defined}</span>
      </div>
      <div className="relative min-h-0 flex-1">
        <svg ref={svg} className="h-full w-full touch-none select-none" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onWheel={onWheel} onContextMenu={e => e.preventDefault()}>
          <defs><pattern id="g" width={10 * view.s} height={10 * view.s} patternUnits="userSpaceOnUse" x={view.ox} y={view.oy}><path d={`M ${10 * view.s} 0 L 0 0 0 ${10 * view.s}`} className="fill-none stroke-border" strokeWidth={0.6} /></pattern></defs>
          <rect width="100%" height="100%" fill="url(#g)" />
          <line x1={view.ox} y1={0} x2={view.ox} y2="100%" className="stroke-success/50" strokeWidth={1} /><line x1={0} y1={view.oy} x2="100%" y2={view.oy} className="stroke-danger/50" strokeWidth={1} />
          {ref.map((pl, i) => <polyline key={i} points={pl.map(p => scr(p).join(",")).join(" ")} className="fill-none stroke-muted" strokeWidth={1.2} strokeDasharray="5 3" />)}
          {prof.loops.map((l, i) => l.kind === "circle"
            ? <circle key={`f${i}`} cx={scr([l.cx, l.cy])[0]} cy={scr([l.cx, l.cy])[1]} r={l.r * view.s} className="fill-primary/10" />
            : <polygon key={`f${i}`} points={l.segs.map(sg => scr(sg.a).join(",")).join(" ")} className="fill-primary/10" />)}
          {sk.entities.map(e => {
            const on = selIds.has(e.id); const col = on ? "stroke-accent" : status.dof === 0 && status.ok ? "stroke-text" : "stroke-primary";
            if (e.type === "line") { const a = scr([P(e.p1).x, P(e.p1).y]), b = scr([P(e.p2).x, P(e.p2).y]); return <line key={e.id} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} className={col} strokeWidth={on ? 3 : 2} strokeDasharray={e.construction ? "6 4" : undefined} />; }
            const c = P(e.c); const [sx, sy] = scr([c.x, c.y]);
            if (e.type === "circle") return <circle key={e.id} cx={sx} cy={sy} r={e.r * view.s} className={cx("fill-none", col)} strokeWidth={on ? 3 : 2} />;
            const a = P(e.p1), b = P(e.p2); const R = Math.hypot(a.x - c.x, a.y - c.y) * view.s;
            let a1 = Math.atan2(a.y - c.y, a.x - c.x), a2 = Math.atan2(b.y - c.y, b.x - c.x); if (a2 <= a1) a2 += Math.PI * 2;
            const [ax, ay] = scr([a.x, a.y]), [bx, by] = scr([b.x, b.y]);
            return <path key={e.id} d={`M ${ax} ${ay} A ${R} ${R} 0 ${a2 - a1 > Math.PI ? 1 : 0} 0 ${bx} ${by}`} className={cx("fill-none", col)} strokeWidth={on ? 3 : 2} />;
          })}
          {sk.points.map(p => { const [x, y] = scr([p.x, p.y]); const on = selIds.has(p.id); return <circle key={p.id} cx={x} cy={y} r={on ? 4.5 : 3} className={p.fixed || sk.constraints.some(k => k.type === "fix" && k.pt === p.id) ? "fill-text" : on ? "fill-accent" : "fill-primary"} />; })}
          {sk.constraints.map(k => {
            if (k.type === "horizontal" || k.type === "vertical") { const e = sk.entities.find(x => x.id === k.line) as Extract<SEntity, { type: "line" }> | undefined; if (!e) return null; const m = scr([(P(e.p1).x + P(e.p2).x) / 2, (P(e.p1).y + P(e.p2).y) / 2]);
              return <g key={k.id}><rect x={m[0] + 6} y={m[1] - 16} width={13} height={12} rx={2} className="fill-success/15 stroke-success/60" strokeWidth={0.8} /><text x={m[0] + 12.5} y={m[1] - 7} textAnchor="middle" className="fill-success text-[9px] font-bold">{k.type === "horizontal" ? "H" : "V"}</text></g>; }
            const anchor = dimAnchor(k, sk); if (!anchor || !("value" in k)) return null; const [x, y] = scr(anchor);
            return <g key={k.id} className="cursor-pointer" onDoubleClick={() => setDimEdit({ cid: k.id, x: anchor[0], y: anchor[1], value: String(+k.value.toFixed(3)) })}>
              <rect x={x - 22} y={y - 22} width={44} height={15} rx={3} className="fill-panel stroke-primary/40" strokeWidth={0.8} /><text x={x} y={y - 11} textAnchor="middle" className="fill-primary text-[10.5px] font-semibold">{dimText(k)}</text></g>;
          })}
          {preview}
        </svg>
        {dimEdit && (() => { const [x, y] = scr([dimEdit.x, dimEdit.y]); return (
          <form className="absolute z-10 flex items-center gap-1 rounded-md border border-primary bg-panel p-1 shadow-pop" style={{ left: x - 50, top: y - 50 }}
            onSubmit={e => { e.preventDefault(); const v = Number(dimEdit.value); if (!(v > 0)) return; const s = clone(sk); const k = s.constraints.find(c => c.id === dimEdit.cid) as { value: number } | undefined; if (k) k.value = v; commit(s); setDimEdit(null); }}>
            <Input autoFocus value={dimEdit.value} onChange={e => setDimEdit({ ...dimEdit, value: e.target.value })} className="h-7 w-20 text-right" inputMode="decimal" />
            <button type="submit" className="rounded bg-success p-1 text-white" aria-label="Apply dimension"><Check className="h-3.5 w-3.5" /></button>
            <button type="button" onClick={() => setDimEdit(null)} className="rounded bg-text/10 p-1" aria-label="Cancel"><X className="h-3.5 w-3.5" /></button>
          </form>); })()}
        <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-panel/90 px-2 py-1 text-[11px] text-muted shadow-card">
          {cursor && `${cursor[0].toFixed(2)}, ${cursor[1].toFixed(2)} mm · `}Wheel zoom · Alt/middle-drag pan · Right-click/Esc ends a tool{prof.open > 0 && <span className="ml-1 text-warning">· {prof.open} open contour(s)</span>}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border bg-panel px-3 py-2">
        <Grid2x2 className="h-4 w-4 text-muted" /><span className="text-[12.5px] text-muted">{prof.loops.length} closed profile(s)</span>
        <div className="ml-auto inline-flex overflow-hidden rounded border border-border text-[12.5px]">
          <button onClick={() => setMode("add")} className={cx("flex items-center gap-1 px-2.5 py-1", mode === "add" ? "bg-primary text-white" : "text-muted")}><ArrowUpFromLine className="h-3.5 w-3.5" />Boss</button>
          <button onClick={() => setMode("cut")} className={cx("flex items-center gap-1 px-2.5 py-1", mode === "cut" ? "bg-primary text-white" : "text-muted")}><ArrowDownToLine className="h-3.5 w-3.5" />Cut</button>
        </div>
        <label className="flex items-center gap-1.5 text-[12.5px]">{mode === "add" ? "Distance" : "Depth"}<Input value={dist} onChange={e => setDist(e.target.value)} className="h-8 w-20 text-right" inputMode="decimal" />mm</label>
        <Button size="sm" loading={busy} onClick={finish} icon={<Check className="h-4 w-4" />}>{editing ? "Update" : "Exit sketch & create"}</Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
