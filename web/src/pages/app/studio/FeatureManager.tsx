import { useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, Check, Info, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { ManualFeature, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button, Field, Input, Tip } from "@/components/ui";
import { describe, edgeMid } from "@/viewer/measure";
import { FEATURE_LABEL, nextName } from "@/viewer/planes";
import type { Pick, SketchPreview, Topo, V3 } from "@/viewer/types";

export type FeatureOp = Exclude<ManualFeature["op"], "sketch" | "revolve">;
const TITLE: Record<FeatureOp, string> = { fillet: "Fillet", chamfer: "Chamfer", hole: "Hole", extrude: "Extrude", shell: "Shell", mirror: "Mirror", pattern: "Pattern" };
const PATTERNABLE = new Set(["sketch", "extrude", "revolve", "hole"]);
type AxisKey = "X" | "Y" | "Z" | "pick";
const AXES: Record<Exclude<AxisKey, "pick">, V3> = { X: [1, 0, 0], Y: [0, 1, 0], Z: [0, 0, 1] };

/** Direction (and a point on it) from a picked straight edge, circular edge or cylindrical/conical face. */
function pickedAxis(sel: Pick[], topo: Topo | null): { origin: V3; dir: V3; label: string } | null {
  if (!topo) return null;
  for (const p of sel) {
    if (p.kind === "edge") {
      const e = topo.edges[p.id]; if (!e) continue;
      if (e.type === "line") { const q = e.pts; const a: V3 = [q[0]!, q[1]!, q[2]!], b: V3 = [q[q.length - 3]!, q[q.length - 2]!, q[q.length - 1]!];
        const d: V3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]]; const l = Math.hypot(...d) || 1; return { origin: a, dir: [d[0] / l, d[1] / l, d[2] / l], label: `Edge (${fmt(e.length)} mm)` }; }
      if (e.type === "circle" && e.center && e.axis) return { origin: e.center, dir: e.axis, label: `Axis of circular edge R${fmt(e.radius ?? 0)}` };
    }
    if (p.kind === "face") {
      const f = topo.faces[p.id];
      if (f && (f.type === "cylinder" || f.type === "cone") && f.axis) return { origin: f.axis_point ?? f.center, dir: f.axis, label: `Axis of ${f.type === "cylinder" ? `cylinder R${fmt(f.radius ?? 0)}` : "cone"}` };
      if (f?.type === "plane" && f.normal) return { origin: f.center, dir: f.normal, label: "Normal of the picked face" };
    }
  }
  return null;
}

type MirrorPlane = "Right" | "Front" | "Top" | "face";
const PRINCIPAL: Record<Exclude<MirrorPlane, "face">, V3> = { Right: [1, 0, 0], Front: [0, 1, 0], Top: [0, 0, 1] };

/** A square preview of a plane, centred on the model's projection onto it and sized to the model. */
export function planePreview(origin: V3, normal: V3, topo: Topo | null): SketchPreview {
  const l = Math.hypot(...normal) || 1; const n: V3 = [normal[0] / l, normal[1] / l, normal[2] / l];
  const b = topo?.bbox ?? [-25, -25, -25, 25, 25, 25];
  const c: V3 = [(b[0]! + b[3]!) / 2, (b[1]! + b[4]!) / 2, (b[2]! + b[5]!) / 2];
  const d = (c[0] - origin[0]) * n[0] + (c[1] - origin[1]) * n[1] + (c[2] - origin[2]) * n[2];
  const size = Math.max(b[3]! - b[0]!, b[4]! - b[1]!, b[5]! - b[2]!, 20) * 1.3;
  return { origin: [c[0] - n[0] * d, c[1] - n[1] * d, c[2] - n[2] * d], normal: n, xDir: xDirFor(n), kind: "rect", w: size, h: size, cx: 0, cy: 0 };
}

export function xDirFor(n: V3): V3 {
  if (Math.abs(n[2]) > 0.9) return [1, 0, 0];
  const c: V3 = [n[1], -n[0], 0]; // n × Z
  const l = Math.hypot(...c) || 1;
  return [c[0] / l, c[1] / l, c[2] / l];
}

export function selectKindsFor(op: FeatureOp): Pick["kind"][] {
  return op === "fillet" || op === "chamfer" ? ["edge"] : op === "pattern" ? ["edge", "face"] : ["face"];
}

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
const fmt = (v: number) => String(+v.toFixed(3));

export default function FeatureManager({ project, op, editing, preset, topo, selection, manual, onSelection, onSketch, onDone, onCancel, onBusy }: {
  project: Project; op: FeatureOp; editing: ManualFeature | null; preset?: Record<string, unknown>; topo: Topo | null; selection: Pick[];
  manual: ManualFeature[];
  onSelection: (p: Pick[]) => void; onSketch: (s: SketchPreview | null) => void; onDone: () => void; onCancel: () => void; onBusy: (b: boolean) => void;
}) {
  const e = editing;
  const pre = preset ?? {};
  const patKind0 = (e?.kind ?? (pre.kind as "linear" | "circular" | undefined) ?? "linear");
  const [name, setName] = useState(e?.name ?? (op === "pattern" ? nextName(patKind0 === "circular" ? "CirPattern" : "LPattern", manual)
    : op === "mirror" ? nextName("Mirror", manual)
    : op === "extrude" ? (pre.mode === "cut" ? "Extruded Cut" : "Extruded Boss") : pre.pattern ? `${pre.pattern === "circular" ? "Circular" : "Linear"} hole pattern` : TITLE[op]));
  // feature pattern
  const idx = e ? manual.findIndex(m => m.id === e.id) : manual.length;
  const candidates = manual.slice(0, idx < 0 ? manual.length : idx).filter(m => PATTERNABLE.has(m.op) && !m.suppressed);
  const [sources, setSources] = useState<string[]>(e?.source ?? (candidates.length ? [candidates[candidates.length - 1]!.id] : []));
  const [patKind, setPatKind] = useState<"linear" | "circular">(patKind0);
  const ax0 = e?.axis && "dir" in e.axis ? e.axis : null;
  const [axisKey, setAxisKey] = useState<AxisKey>(() => {
    const d = e?.kind === "circular" ? ax0?.dir : e?.step;
    if (!d) return patKind0 === "circular" ? "Z" : "X";
    const l = Math.hypot(...d) || 1;
    return (Object.entries(AXES).find(([, v]) => v.every((c, i) => Math.abs(c - d[i]! / l) < 1e-9))?.[0] as AxisKey | undefined) ?? "pick";
  });
  const [spacing, setSpacing] = useState(String(e?.step ? +Math.hypot(...e.step).toFixed(4) : 20));
  const [flip, setFlip] = useState(false);
  const [patCount, setPatCount] = useState(String(e?.count ?? (patKind0 === "circular" ? 6 : 3)));
  const [patAngle, setPatAngle] = useState(String(e?.angle ?? 360));
  const [axOrigin, setAxOrigin] = useState<[string, string, string]>(ax0 ? ax0.origin.map(String) as [string, string, string] : ["0", "0", "0"]);
  const picked = op === "pattern" ? pickedAxis(selection, topo) : null;
  const keptPick = axisKey === "pick" && !picked && e ? (e.kind === "circular" ? ax0 : e.step ? { origin: [0, 0, 0] as V3, dir: e.step } : null) : null;
  const [size, setSize] = useState(String(e?.r ?? e?.d ?? e?.t ?? (op === "hole" ? 6.6 : op === "fillet" ? 2 : op === "shell" ? 2 : 1)));
  const [depth, setDepth] = useState(e?.depth ? String(e.depth) : "");
  const [pattern, setPattern] = useState<"none" | "linear" | "circular">(e?.pattern === "circular" ? "circular" : (e?.count ?? 1) > 1 ? "linear" : (pre.pattern as "linear" | "circular") ?? "none");
  const [count, setCount] = useState(String(e?.count ?? (pre.pattern ? 6 : 1)));
  const [step, setStep] = useState<[string, string, string]>(e?.step ? e.step.map(String) as [string, string, string] : ["20", "0", "0"]);
  const [center, setCenter] = useState<[string, string, string]>(e?.center ? e.center.map(String) as [string, string, string] : ["", "", ""]);
  const [kind, setKind] = useState<"rect" | "circle">(e?.sketch?.kind === "circle" || pre.kind === "circle" ? "circle" : "rect");
  const [w, setW] = useState(String(e?.sketch?.w ?? 20));
  const [h, setH] = useState(String(e?.sketch?.h ?? 10));
  const [r, setR] = useState(String(e?.sketch?.r ?? 5));
  const [cx_, setCx] = useState(String(e?.sketch?.cx ?? 0));
  const [cy_, setCy] = useState(String(e?.sketch?.cy ?? 0));
  const [dist, setDist] = useState(String(e?.distance ?? 5));
  const [mode, setMode] = useState<"add" | "cut">(e?.mode ?? (pre.mode as "add" | "cut") ?? "add");
  const [mirrorWhat, setMirrorWhat] = useState<"features" | "body">(e ? (e.source?.length ? "features" : "body") : candidates.length ? "features" : "body");
  const [mirrorPlane, setMirrorPlane] = useState<MirrorPlane>(() => {
    if (!e?.plane) return "Right";
    const n = e.plane.normal, o = e.plane.origin;
    if (Math.hypot(...o) > 1e-9) return "face";
    return (Object.entries(PRINCIPAL).find(([, v]) => Math.abs(Math.abs(v[0] * n[0] + v[1] * n[1] + v[2] * n[2]) - Math.hypot(...n)) < 1e-9)?.[0] as MirrorPlane | undefined) ?? "face";
  });
  const [busy, setBusy] = useState(false);

  const edges = selection.filter(p => p.kind === "edge") as Extract<Pick, { kind: "edge" }>[];
  const planarFaces = selection.filter(p => p.kind === "face" && topo?.faces[p.id]?.type === "plane") as Extract<Pick, { kind: "face" }>[];
  const face = planarFaces[0];
  const faceN = face && topo ? topo.faces[face.id]!.normal! : null;
  const bbc: V3 = topo ? [(topo.bbox[0] + topo.bbox[3]) / 2, (topo.bbox[1] + topo.bbox[4]) / 2, (topo.bbox[2] + topo.bbox[5]) / 2] : [0, 0, 0];
  const plane = useMemo(() => {
    if (face && faceN) return { origin: face.point, normal: faceN, x_dir: xDirFor(faceN) };
    if (e?.plane) return { origin: e.plane.origin, normal: e.plane.normal, x_dir: e.plane.x_dir ?? xDirFor(e.plane.normal) };
    if (e?.point && e?.normal) return { origin: e.point, normal: e.normal, x_dir: xDirFor(e.normal) };
    return null;
  }, [face, faceN, e]);

  // default circular pattern centre: model centre projected onto the picked face plane
  useEffect(() => {
    if (pattern === "circular" && plane && center.every(c => c === "")) {
      const n = plane.normal; const o = plane.origin;
      const d = (bbc[0] - o[0]) * n[0] + (bbc[1] - o[1]) * n[1] + (bbc[2] - o[2]) * n[2];
      setCenter([fmt(bbc[0] - n[0] * d), fmt(bbc[1] - n[1] * d), fmt(bbc[2] - n[2] * d)]);
    }
  }, [pattern, plane]); // eslint-disable-line react-hooks/exhaustive-deps

  const mirrorPl = op !== "mirror" ? null : mirrorPlane === "face" ? (plane ? { origin: plane.origin, normal: plane.normal } : null) : { origin: [0, 0, 0] as V3, normal: PRINCIPAL[mirrorPlane] };
  useEffect(() => {
    if (op === "extrude" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind, w: num(w), h: num(h), r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 });
    else if (op === "hole" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind: "circle", r: num(size) / 2, cx: 0, cy: 0 });
    else if (mirrorPl) onSketch(planePreview(mirrorPl.origin, mirrorPl.normal, topo));
    else onSketch(null);
  }, [op, plane, kind, w, h, r, cx_, cy_, size, mirrorPl?.origin.join(","), mirrorPl?.normal.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onSketch(null), []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (op === "pattern" && picked) { setAxisKey("pick"); if (patKind === "circular") setAxOrigin(picked.origin.map(fmt) as [string, string, string]); } }, [picked?.label, patKind]); // eslint-disable-line react-hooks/exhaustive-deps
  const patDir = (): V3 | null => {
    const d = axisKey === "pick" ? (picked ?? keptPick)?.dir ?? null : AXES[axisKey];
    if (!d) return null; const l = Math.hypot(...d) || 1; const s = flip ? -1 : 1;
    return [s * d[0] / l, s * d[1] / l, s * d[2] / l];
  };
  const needsEdges = op === "fillet" || op === "chamfer";
  const ready = op === "pattern" ? sources.length > 0 && !!patDir() && num(patCount) >= 2
    : needsEdges ? (edges.length > 0 || !!e?.edges?.length)
    : op === "shell" ? (planarFaces.length > 0 || !!e?.faces?.length)
    : op === "mirror" ? !!mirrorPl && (mirrorWhat === "body" || sources.length > 0)
    : !!plane;

  const submit = async () => {
    let f: Record<string, unknown> = { op, name, suppressed: e?.suppressed ?? false };
    if (op === "pattern") {
      const d = patDir()!;
      f = { ...f, source: sources, count: num(patCount), ...(patKind === "circular"
        ? { kind: "circular", axis: { origin: axOrigin.map(num), dir: d }, angle: num(patAngle) }
        : { kind: "linear", step: d.map(c => c * num(spacing)) }) };
    } else if (needsEdges) {
      const pts = edges.length && topo ? edges.map(p => edgeMid(topo, p.id)) : e?.edges;
      f = { ...f, edges: pts, [op === "fillet" ? "r" : "d"]: num(size) };
    } else if (op === "hole") {
      f = { ...f, point: plane!.origin, normal: plane!.normal, d: num(size), depth: depth ? num(depth) : null };
      if (pattern !== "none" && num(count) > 1) f = { ...f, count: num(count), ...(pattern === "circular" ? { pattern: "circular", center: center.map(num) } : { step: step.map(num) }) };
    } else if (op === "shell") {
      const faces = planarFaces.length && topo ? planarFaces.map(p => ({ point: p.point, normal: topo.faces[p.id]!.normal! })) : e?.faces;
      f = { ...f, faces, t: num(size) };
    } else if (op === "mirror") {
      f = { ...f, plane: mirrorPl, source: mirrorWhat === "features" ? sources : null };
    } else {
      f = { ...f, plane, distance: num(dist), mode,
        sketch: kind === "rect" ? { kind, w: num(w), h: num(h), cx: num(cx_) || 0, cy: num(cy_) || 0 } : { kind, r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 } };
    }
    setBusy(true); onBusy(true);
    try {
      const t0 = performance.now();
      if (e) await api.patch(`/api/projects/${project.id}/manual/${e.id}`, { feature: f });
      else await api.post(`/api/projects/${project.id}/manual`, { feature: f });
      toast.success(`${name} ${e ? "updated" : "added"} · ${((performance.now() - t0) / 1000).toFixed(1)} s`);
      onSelection([]); onDone();
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Feature failed"); }
    finally { setBusy(false); onBusy(false); }
  };

  const featurePicker = (label: string, verb: string) => (
    <div className="rounded-lg border border-border bg-panel2 p-2.5">
      <div className="label mb-1">{label}</div>
      {candidates.length === 0 ? <p className="text-[12px] text-muted">Add a boss, cut, revolve or hole first. Fillets and shells are not {verb}.</p>
        : <ul className="space-y-0.5">{candidates.map(m => (
          <li key={m.id}><label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-text/5">
            <input type="checkbox" checked={sources.includes(m.id)} onChange={ev => setSources(s => ev.target.checked ? [...s, m.id] : s.filter(x => x !== m.id))} />
            <span className="flex-1 truncate text-[12.5px]">{m.name}</span><span className="text-[10.5px] text-muted">{FEATURE_LABEL[m.op]}</span></label></li>))}</ul>}
    </div>
  );
  const numField = (label: string, v: string, set: (s: string) => void, unit = "mm", hint?: string) => (
    <Field label={label} hint={hint}><div className="flex items-center gap-1.5"><Input value={v} onChange={ev => set(ev.target.value)} inputMode="decimal" className="h-8" /><span className="w-7 text-xs text-muted">{unit}</span></div></Field>
  );
  const vec = (label: string, v: [string, string, string], set: (x: [string, string, string]) => void) => (
    <Field label={label}><div className="flex gap-1">{v.map((s, i) => <Input key={i} value={s} onChange={ev => { const n = [...v] as [string, string, string]; n[i] = ev.target.value; set(n); }} className="h-8 px-1.5 text-center" placeholder={"XYZ"[i]} />)}</div></Field>
  );
  const seg = <T extends string>(opts: [T, string][], v: T, set: (x: T) => void) => (
    <div className="inline-flex overflow-hidden rounded border border-border text-[12.5px]">{opts.map(([k, l]) => <button key={k} onClick={() => set(k)} className={cx("px-2.5 py-1", v === k ? "bg-primary text-white" : "text-muted hover:bg-text/5")}>{l}</button>)}</div>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border bg-gradient-to-r from-primary-soft to-transparent px-3 py-2.5">
        <span className="flex-1 text-sm font-semibold">{e ? "Edit" : ""} {op === "extrude" ? (mode === "cut" ? "Extruded Cut" : "Extruded Boss") : op === "pattern" ? (patKind === "circular" ? "Circular Pattern" : "Linear Pattern") : TITLE[op]}</span>
        <button onClick={submit} disabled={!ready || busy} className="rounded bg-success p-1 text-white disabled:opacity-40" aria-label="OK"><Check className="h-4 w-4" /></button>
        <button onClick={onCancel} className="rounded bg-danger p-1 text-white" aria-label="Cancel"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3 text-[13px]">
        {op === "mirror" ? <>
          <div>{seg<"features" | "body">([["features", "Mirror features"], ["body", "Mirror body"]], mirrorWhat, setMirrorWhat)}</div>
          {mirrorWhat === "features" ? featurePicker("Features to mirror", "mirrored")
            : <p className="text-[12px] text-muted">The whole body is mirrored and joined to the original.</p>}
          <div className="rounded-lg border border-border bg-panel2 p-2.5">
            <div className="label mb-1">Mirror plane</div>
            <div className="mb-2">{seg<MirrorPlane>([["Right", "Right"], ["Front", "Front"], ["Top", "Top"], ["face", "Face"]], mirrorPlane, setMirrorPlane)}</div>
            <p className="text-[12px] text-muted">{mirrorPlane !== "face" ? `${mirrorPlane} Plane through the origin. The blue rectangle shows it.`
              : face && topo ? `${describe(face, topo)}: its plane is the mirror plane.`
              : plane ? "Using the original plane. Click a planar face to change it." : "Click a planar face in the viewer."}</p>
          </div>
          <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
        </> : op === "pattern" ? <>
          {featurePicker("Features to pattern", "patterned")}
          <div>{seg<"linear" | "circular">([["linear", "Linear"], ["circular", "Circular"]], patKind, k => { setPatKind(k); if (!e) setName(nextName(k === "circular" ? "CirPattern" : "LPattern", manual)); })}</div>
          <div className="rounded-lg border border-border bg-panel2 p-2.5">
            <div className="label mb-1">{patKind === "linear" ? "Direction" : "Axis"}</div>
            <div className="flex items-center gap-2">{seg<AxisKey>([["X", "X"], ["Y", "Y"], ["Z", "Z"], ["pick", "Picked"]], axisKey, setAxisKey)}
              <Tip content="Reverse direction" side="top"><button onClick={() => setFlip(!flip)} className={cx("rounded border p-1", flip ? "border-primary bg-primary-soft text-primary" : "border-border text-muted")} aria-label="Reverse direction"><ArrowLeftRight className="h-3.5 w-3.5" /></button></Tip></div>
            <p className="mt-1 text-[11.5px] text-muted">{axisKey === "pick" ? (picked?.label ?? (keptPick ? "Using the original direction." : "Click a straight edge, a circular edge, a hole or a face.")) : `Along the model ${axisKey} axis.`}</p>
          </div>
          {numField("Instances (incl. original)", patCount, setPatCount, "")}
          {patKind === "linear" ? numField("Spacing", spacing, setSpacing)
            : <>{numField("Total angle", patAngle, setPatAngle, "°", "360° spaces the instances equally around the axis")}{vec("Axis through point (X, Y, Z mm)", axOrigin, setAxOrigin)}</>}
        </> : <>
        <div className="rounded-lg border border-border bg-panel2 p-2.5">
          <div className="label mb-1">{needsEdges ? "Edges" : op === "shell" ? "Faces to remove" : "Placement face"}</div>
          {needsEdges ? (edges.length ? <ul className="space-y-0.5">{edges.map(p => <li key={p.id} className="flex items-center justify-between text-[12px]">{topo ? describe(p, topo) : `Edge ${p.id}`}
              <button onClick={() => onSelection(selection.filter(x => x !== p))} aria-label="Remove"><X className="h-3 w-3 text-muted" /></button></li>)}</ul>
            : <p className="text-[12px] text-muted">{e?.edges?.length ? `${e.edges.length} edge(s) from the original selection. Click edges to replace.` : "Click edges in the viewer (Ctrl+click for several)."}</p>)
          : op === "shell" ? (planarFaces.length ? <ul className="space-y-0.5">{planarFaces.map(p => <li key={p.id} className="text-[12px]">{topo ? describe(p, topo) : `Face ${p.id}`}</li>)}</ul>
              : <p className="text-[12px] text-muted">{e?.faces?.length ? `${e.faces.length} face(s) from the original selection.` : "Click the face(s) to open (Ctrl+click for several)."}</p>)
          : (face && topo ? <p className="text-[12px]">{describe(face, topo)} — origin at the picked point</p>
              : <p className="text-[12px] text-muted">{plane ? "Using the original placement. Click a planar face to move it." : "Click a planar face in the viewer. The point you click becomes the origin."}</p>)}
        </div>
        <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
        {op === "fillet" && numField("Radius", size, setSize)}
        {op === "chamfer" && numField("Distance", size, setSize)}
        {op === "shell" && numField("Wall thickness", size, setSize)}
        {op === "hole" && <>
          {numField("Diameter", size, setSize, "mm", "e.g. 6.6 for M6 clearance (ISO 273 medium)")}
          {numField("Depth", depth, setDepth, "mm", "Leave empty for a through hole")}
          <div><div className="label mb-1">Pattern</div>{seg<"none" | "linear" | "circular">([["none", "Single"], ["linear", "Linear"], ["circular", "Circular"]], pattern, setPattern)}</div>
          {pattern !== "none" && numField("Instances", count, setCount, "")}
          {pattern === "linear" && vec("Spacing (X, Y, Z mm)", step, setStep)}
          {pattern === "circular" && <>{vec("Axis centre (X, Y, Z mm)", center, setCenter)}<p className="text-[11px] text-muted">The axis runs through this point along the face normal. Defaults to the model centre.</p></>}
        </>}
        {op === "extrude" && <>
          {seg<"add" | "cut">([["add", "Boss (add)"], ["cut", "Cut (remove)"]], mode, setMode)}
          <div>
            <div className="label mb-1">Sketch on face</div>
            <div className="mb-2">{seg<"rect" | "circle">([["rect", "Rectangle"], ["circle", "Circle"]], kind, setKind)}</div>
            <div className="grid grid-cols-2 gap-2">
              {kind === "rect" ? <>{numField("Width", w, setW)}{numField("Height", h, setH)}</> : numField("Radius", r, setR)}
              {numField("Offset X", cx_, setCx)}{numField("Offset Y", cy_, setCy)}
            </div>
            <p className="mt-1 flex gap-1 text-[11px] text-muted"><Info className="mt-0.5 h-3 w-3 shrink-0" />Offsets are measured on the face from the picked point. The green outline previews the sketch. For free-form profiles use Sketch.</p>
          </div>
          {numField(mode === "add" ? "Extrude distance" : "Cut depth", dist, setDist)}
        </>}
        </>}
      </div>
      <div className="flex gap-2 border-t border-border p-3">
        <Button className="flex-1" onClick={submit} loading={busy} disabled={!ready}>{e ? "Update" : "Add"} feature</Button>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
