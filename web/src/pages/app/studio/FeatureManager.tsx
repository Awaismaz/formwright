import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeftRight, Check, Info, Loader2, Sparkles, TriangleAlert, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Impact, ManualFeature, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button, Field, Input, Tip } from "@/components/ui";
import { describe, edgeMid, edgeRef } from "@/viewer/measure";
import HoleWizard, { type HoleApi, type HolePreset } from "./HoleWizard";
import ImpactPanel from "./ImpactPanel";
import { FEATURE_LABEL, nextName, REF_PLANES, resolveRefPlane, sketchLines, type PlaneDef, type RefPlane } from "@/viewer/planes";
import type { Pick, SketchPreview, Topo, V3 } from "@/viewer/types";

export type FeatureOp = Exclude<ManualFeature["op"], "sketch" | "revolve" | "rib" | "sketch2d">;
const TITLE: Record<FeatureOp, string> = { fillet: "Fillet", chamfer: "Chamfer", hole: "Hole Wizard", extrude: "Extrude", shell: "Shell", mirror: "Mirror", pattern: "Pattern", plane: "Reference Plane", draft: "Draft", sweep: "Swept Boss/Base", loft: "Lofted Boss/Base" };
const PATTERNABLE = new Set(["sketch", "extrude", "revolve", "hole", "sweep", "loft"]);
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
  return op === "fillet" || op === "chamfer" ? ["edge"] : op === "pattern" ? ["edge", "face"] : ["face"]; // plane: a face as its reference
}

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
const fmt = (v: number) => String(+v.toFixed(3));

/** Small crosses at the points a feature was originally picked at (shown while editing or repairing it). */
function pickMarks(e: ManualFeature, size: number): V3[][] {
  const pts: V3[] = [...(e.edges ?? []), ...(e.faces ?? []).map(f => f.point), ...(e.op === "hole" && !e.place && e.point ? [e.point] : []), ...(e.place ? [e.place.face.point] : [])];
  const h = size / 2;
  return pts.flatMap(p => [[[p[0] - h, p[1], p[2]], [p[0] + h, p[1], p[2]]], [[p[0], p[1] - h, p[2]], [p[0], p[1] + h, p[2]]], [[p[0], p[1], p[2] - h], [p[0], p[1], p[2] + h]]] as V3[][]);
}

export default function FeatureManager({ project, op, editing, preset, topo, selection, manual, onSelection, onSketch, onDone, onCancel, onBusy, repair, usedIn = 0 }: {
  project: Project; op: FeatureOp; editing: ManualFeature | null; preset?: Record<string, unknown>; topo: Topo | null; selection: Pick[];
  manual: ManualFeature[];
  onSelection: (p: Pick[]) => void; onSketch: (s: SketchPreview | null) => void; onDone: () => void; onCancel: () => void; onBusy: (b: boolean) => void;
  /** the feature failed to rebuild: why (shown with its original picks marked, IDEA 1) */
  repair?: string | null;
  /** assemblies using this part: OK first previews the change's impact on them (ASM-018) */
  usedIn?: number;
}) {
  const e = editing;
  const pre = preset ?? {};
  const patKind0 = (e?.kind ?? (pre.kind as "linear" | "circular" | undefined) ?? "linear");
  const [name, setName] = useState(e?.name ?? (op === "pattern" ? nextName(patKind0 === "circular" ? "CirPattern" : "LPattern", manual)
    : op === "mirror" ? nextName("Mirror", manual) : op === "plane" ? nextName("Plane", manual) : op === "draft" ? nextName("Draft", manual)
    : op === "sweep" ? nextName(pre.mode === "cut" ? "Cut-Sweep" : "Sweep", manual) : op === "loft" ? nextName(pre.mode === "cut" ? "Cut-Loft" : "Loft", manual)
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
  const [size, setSize] = useState(String(e?.r ?? e?.d ?? e?.t ?? (pre.size as number | undefined) ?? (op === "hole" ? 6.6 : op === "fillet" ? 2 : op === "shell" ? 2 : 1)));
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
  // sweep / loft: sketch nodes from the tree
  const sketchNodes = manual.filter(m => m.op === "sketch2d");
  const closedNodes = sketchNodes.filter(m => (m.profiles?.length ?? 0) > 0);
  const [swProfile, setSwProfile] = useState<string>(e?.profile ?? closedNodes[0]?.id ?? "");
  const [swPath, setSwPath] = useState<string>(e?.path ?? sketchNodes.find(m => (m.chains?.length ?? 0) > 0)?.id ?? sketchNodes.find(m => m.id !== (e?.profile ?? closedNodes[0]?.id))?.id ?? "");
  const [loftSecs, setLoftSecs] = useState<string[]>(e?.sections ?? []);
  const [ruled, setRuled] = useState(!!e?.ruled);
  const usedSketches = op === "sweep" ? [swProfile, swPath] : op === "loft" ? loftSecs : [];
  const sketchPreviewKey = usedSketches.join(",");
  // draft: a neutral face, then the faces to draft (the next picked face fills the active box)
  const [neutral, setNeutral] = useState<{ point: V3; normal: V3; label: string } | null>(e?.neutral ? { ...e.neutral, label: "Original neutral face" } : null);
  const [draftBox, setDraftBox] = useState<"neutral" | "faces">(e?.neutral ? "faces" : "neutral");
  const [draftAngle, setDraftAngle] = useState(String(op === "draft" && e?.angle ? e.angle : 3));
  const [draftRev, setDraftRev] = useState(!!e?.reverse);
  useEffect(() => {
    if (op !== "draft" || draftBox !== "neutral" || !topo) return;
    const pick = selection.find(p => p.kind === "face" && topo.faces[p.id]?.type === "plane") as Extract<Pick, { kind: "face" }> | undefined;
    if (!pick) return;
    setNeutral({ point: pick.point, normal: topo.faces[pick.id]!.normal!, label: describe(pick, topo) });
    onSelection(selection.filter(p => p !== pick)); setDraftBox("faces");
  }, [selection]); // eslint-disable-line react-hooks/exhaustive-deps
  const draftFaces = op === "draft" ? selection.filter(p => p.kind === "face") as Extract<Pick, { kind: "face" }>[] : [];
  // reference plane
  const otherPlanes = manual.filter(m => m.op === "plane" && m.id !== e?.id && m.plane);
  const [refBase, setRefBase] = useState<string>(() => {
    if (!e?.base) return "Top";
    const named = (["Front", "Top", "Right"] as RefPlane[]).find(n => e.base_name === `${n} Plane`);
    if (named) return named;
    return otherPlanes.find(m => m.name === e.base_name) ? `pl:${otherPlanes.find(m => m.name === e.base_name)!.id}` : "face";
  });
  const [planeOff, setPlaneOff] = useState(String(e?.offset ?? 10));
  const [planeAng, setPlaneAng] = useState(String(e?.angle && op === "plane" ? e.angle : 0));
  const [rotAxis, setRotAxis] = useState<"x" | "y">(e?.rot_axis ?? "x");
  const [mirrorWhat, setMirrorWhat] = useState<"features" | "body">(e ? (e.source?.length ? "features" : "body") : candidates.length ? "features" : "body");
  const [mirrorPlane, setMirrorPlane] = useState<MirrorPlane>(() => {
    if (!e?.plane) return "Right";
    const n = e.plane.normal, o = e.plane.origin;
    if (Math.hypot(...o) > 1e-9) return "face";
    return (Object.entries(PRINCIPAL).find(([, v]) => Math.abs(Math.abs(v[0] * n[0] + v[1] * n[1] + v[2] * n[2]) - Math.hypot(...n)) < 1e-9)?.[0] as MirrorPlane | undefined) ?? "face";
  });
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [impact, setImpact] = useState<{ data: Impact; key: string } | null>(null);
  const hole = useRef<HoleApi | null>(null);
  const [holeReady, setHoleReady] = useState(false);

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

  const planeBase: { def: PlaneDef; name: string } | null = op !== "plane" ? null
    : refBase === "face" ? (face && faceN ? { def: { origin: face.point, normal: faceN, x_dir: xDirFor(faceN) }, name: "Face" } : e?.base ? { def: e.base, name: e.base_name || "Face" } : null)
    : refBase.startsWith("pl:") ? (() => { const m = otherPlanes.find(x => `pl:${x.id}` === refBase); return m?.plane ? { def: { origin: m.plane.origin, normal: m.plane.normal, x_dir: m.plane.x_dir ?? xDirFor(m.plane.normal) }, name: m.name } : null; })()
    : { def: REF_PLANES[refBase as RefPlane], name: `${refBase} Plane` };
  const refResolved = planeBase ? resolveRefPlane(planeBase.def, num(planeOff), num(planeAng), rotAxis) : null;
  const mirrorPl = op !== "mirror" ? null : mirrorPlane === "face" ? (plane ? { origin: plane.origin, normal: plane.normal } : null) : { origin: [0, 0, 0] as V3, normal: PRINCIPAL[mirrorPlane] };
  const marks = e && (op === "fillet" || op === "chamfer" || op === "shell" || op === "draft") && !selection.length && topo
    ? pickMarks(e, Math.max(2, Math.hypot(topo.bbox[3] - topo.bbox[0], topo.bbox[4] - topo.bbox[1], topo.bbox[5] - topo.bbox[2]) / 40)) : null;
  useEffect(() => {
    if (op === "hole") return; // the Hole Wizard draws its own preview
    if (marks?.length) onSketch({ origin: [0, 0, 0], normal: [0, 0, 1], xDir: [1, 0, 0], kind: "lines", lines: marks, cx: 0, cy: 0 });
    else if (op === "extrude" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind, w: num(w), h: num(h), r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 });
    else if (mirrorPl) onSketch(planePreview(mirrorPl.origin, mirrorPl.normal, topo));
    else if (refResolved) onSketch(planePreview(refResolved.origin, refResolved.normal, topo));
    else if (op === "pattern" && topo) { // instance positions of each source, before OK (STU-21)
      const d = patDir(); const cnt = Math.min(num(patCount), 200);
      const anchors = manual.filter(m => sources.includes(m.id)).map(m => m.point ?? m.plane?.origin).filter((x): x is V3 => !!x);
      if (!d || !(cnt >= 2) || !anchors.length) { onSketch(null); return; }
      const sz = Math.max(1.5, Math.hypot(topo.bbox[3] - topo.bbox[0], topo.bbox[4] - topo.bbox[1], topo.bbox[5] - topo.bbox[2]) / 50);
      const total = num(patAngle), stepA = (Math.abs(total - 360) < 1e-9 ? total / cnt : total / Math.max(cnt - 1, 1)) * Math.PI / 180;
      const o = axOrigin.map(num) as V3;
      const at = (a: V3, k: number): V3 => {
        if (patKind === "linear") { const s = num(spacing) * k; return [a[0] + d[0] * s, a[1] + d[1] * s, a[2] + d[2] * s]; }
        const v: V3 = [a[0] - o[0], a[1] - o[1], a[2] - o[2]], th = stepA * k, c = Math.cos(th), s = Math.sin(th);
        const kv = d[0] * v[0] + d[1] * v[1] + d[2] * v[2];
        const cr: V3 = [d[1] * v[2] - d[2] * v[1], d[2] * v[0] - d[0] * v[2], d[0] * v[1] - d[1] * v[0]];
        return [0, 1, 2].map(i => o[i]! + v[i]! * c + cr[i]! * s + d[i]! * kv * (1 - c)) as V3;
      };
      const lines: V3[][] = [];
      for (const a of anchors) for (let k = 1; k < cnt; k++) { const q = at(a, k);
        lines.push([[q[0] - sz, q[1], q[2]], [q[0] + sz, q[1], q[2]]], [[q[0], q[1] - sz, q[2]], [q[0], q[1] + sz, q[2]]], [[q[0], q[1], q[2] - sz], [q[0], q[1], q[2] + sz]]); }
      onSketch({ origin: [0, 0, 0], normal: [0, 0, 1], xDir: [1, 0, 0], kind: "lines", lines, cx: 0, cy: 0 });
    }
    else if (op === "sweep" || op === "loft") {
      const lines = usedSketches.flatMap(id => { const s = sketchNodes.find(m => m.id === id); return s?.plane ? sketchLines({ origin: s.plane.origin, normal: s.plane.normal, x_dir: s.plane.x_dir ?? xDirFor(s.plane.normal) }, s.profiles, s.chains) : []; });
      onSketch(lines.length ? { origin: [0, 0, 0], normal: [0, 0, 1], xDir: [1, 0, 0], kind: "lines", lines, cx: 0, cy: 0 } : null);
    }
    else onSketch(null);
  }, [op, plane, kind, w, h, r, cx_, cy_, size, mirrorPl?.origin.join(","), mirrorPl?.normal.join(","), refResolved?.origin.join(","), refResolved?.normal.join(","), sketchPreviewKey, !!marks, selection.length, patKind, patCount, spacing, axisKey, flip, patAngle, axOrigin.join(","), sources.join(","), picked?.label]); // eslint-disable-line react-hooks/exhaustive-deps
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
    : op === "plane" ? !!planeBase && Number.isFinite(num(planeOff)) && Number.isFinite(num(planeAng))
    : op === "sweep" ? !!swProfile && !!swPath && swProfile !== swPath
    : op === "loft" ? loftSecs.length >= 2
    : op === "draft" ? !!neutral && (draftFaces.length > 0 || !!e?.faces?.length) && num(draftAngle) > 0
    : op === "hole" ? holeReady
    : !!plane;

  // features are replayed in tree order, whatever order they were ticked in
  const inTreeOrder = manual.filter(m => sources.includes(m.id)).map(m => m.id);
  const submit = async (force = false) => {
    let f: Record<string, unknown> = { op, name, suppressed: e?.suppressed ?? false };
    if (op === "pattern") {
      const d = patDir()!;
      f = { ...f, source: inTreeOrder, count: num(patCount), ...(patKind === "circular"
        ? { kind: "circular", axis: { origin: axOrigin.map(num), dir: d }, angle: num(patAngle) }
        : { kind: "linear", step: d.map(c => c * num(spacing)) }) };
    } else if (needsEdges) {
      // the true middle of each picked edge plus its kind/direction: exactly that edge, also after size changes
      f = { ...f, [op === "fillet" ? "r" : "d"]: num(size),
        ...(edges.length && topo ? { edges: edges.map(p => edgeMid(topo, p.id)), edge_refs: edges.map(p => edgeRef(topo, p.id)) } : {}) };
    } else if (op === "hole") {
      f = { ...f, ...hole.current!.payload() };
      if (!e && name === TITLE.hole) { // SOLIDWORKS-like default name: "M6 Clearance Hole (4×)"
        const sp = f.spec as { type: string; size: number } | undefined, pl = f.place as { mode: string; pts?: unknown[] } | undefined;
        const n = pl ? (pl.mode === "corners" ? 4 : pl.pts?.length ?? 1) : 1;
        f.name = `${sp ? `M${sp.size} ${{ clearance: "Clearance", tapped: "Tapped", cbore: "Counterbored", csk: "Countersunk" }[sp.type] ?? ""}` : `Ø${f.d}`} Hole${n > 1 ? ` (${n}×)` : ""}`;
      }
      if (!f.place && pattern !== "none" && num(count) > 1) f = { ...f, count: num(count), ...(pattern === "circular" ? { pattern: "circular", center: center.map(num) } : { step: step.map(num) }) };
    } else if (op === "shell") {
      const faces = planarFaces.length && topo ? planarFaces.map(p => ({ point: p.point, normal: topo.faces[p.id]!.normal! })) : e?.faces;
      f = { ...f, faces, t: num(size) };
    } else if (op === "sweep") {
      f = { ...f, profile: swProfile, path: swPath, mode };
    } else if (op === "loft") {
      f = { ...f, sections: loftSecs, ruled, mode };
    } else if (op === "draft") {
      const faces = draftFaces.length && topo ? draftFaces.map(p => { const fc = topo.faces[p.id]!; return fc.type === "plane" && fc.normal ? { point: p.point, normal: fc.normal } : { point: p.point }; }) : e?.faces;
      f = { ...f, neutral: { point: neutral!.point, normal: neutral!.normal }, faces, angle: num(draftAngle), reverse: draftRev };
    } else if (op === "plane") {
      f = { ...f, base: planeBase!.def, base_name: planeBase!.name, offset: num(planeOff), angle: num(planeAng), rot_axis: rotAxis };
    } else if (op === "mirror") {
      f = { ...f, plane: mirrorPl, source: mirrorWhat === "features" ? inTreeOrder : null };
    } else {
      f = { ...f, plane, distance: num(dist), mode,
        sketch: kind === "rect" ? { kind, w: num(w), h: num(h), cx: num(cx_) || 0, cy: num(cy_) || 0 } : { kind, r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 } };
    }
    // ASM-018: a part used in assemblies previews the change on a trial rebuild first; problems stop at the panel
    const key = JSON.stringify(f);
    if (usedIn > 0 && !(force && impact?.key === key)) {
      setChecking(true);
      try {
        const r = await api.post<Impact>(`/api/m/assembly/impact/${project.id}`, e ? { kind: "edit", id: e.id, feature: f } : { kind: "feature", feature: f });
        if ((r.issues ?? 0) > 0) { setImpact({ data: r, key }); return; }
      } catch (err) {
        if (err instanceof ApiError && err.status === 422) { toast.error(err.message); return; }
        // the preview is advisory: if it can't run (no module, engine busy), the change still goes through the normal path
      } finally { setChecking(false); }
    }
    setImpact(null);
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

  const submitRef = useRef(submit); submitRef.current = submit;
  const okRef = useRef(false); okRef.current = ready && !busy && !checking && !impact;
  useEffect(() => {
    const h = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement | null;
      if (ev.key === "Escape" && !document.querySelector("[role=menu],[role=dialog]")) { ev.preventDefault(); ev.stopPropagation(); onCancel(); }
      else if (ev.key === "Enter" && !ev.shiftKey && !(t && /^(TEXTAREA|SELECT|BUTTON)$/.test(t.tagName)) && okRef.current) { ev.preventDefault(); void submitRef.current(); }
    };
    addEventListener("keydown", h);
    return () => removeEventListener("keydown", h);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const featurePicker = (label: string, verb: string) => (
    <div className="rounded-lg border border-border bg-panel2 p-2.5">
      <div className="label mb-1">{label}</div>
      {candidates.length === 0 ? <p className="text-[12px] text-muted">Add a boss, cut, revolve, sweep, loft or hole first. Fillets and shells are not {verb}.</p>
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
        <span className="flex-1 text-sm font-semibold">{e ? "Edit" : ""} {op === "extrude" ? (mode === "cut" ? "Extruded Cut" : "Extruded Boss") : op === "pattern" ? (patKind === "circular" ? "Circular Pattern" : "Linear Pattern") : op === "sweep" ? (mode === "cut" ? "Swept Cut" : "Swept Boss/Base") : op === "loft" ? (mode === "cut" ? "Lofted Cut" : "Lofted Boss/Base") : TITLE[op]}</span>
        <Tip content="OK (Enter)" side="bottom"><button onClick={() => void submit()} disabled={!ready || busy || checking} className="rounded bg-success p-1 text-white disabled:opacity-40" aria-label="OK"><Check className="h-4 w-4" /></button></Tip>
        <Tip content="Cancel (Esc)" side="bottom"><button onClick={onCancel} className="rounded bg-danger p-1 text-white" aria-label="Cancel"><X className="h-4 w-4" /></button></Tip>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3 text-[13px]">
        {typeof pre.agent === "string" && <div className="flex gap-2 rounded-lg border border-accent/40 bg-accent/5 p-2.5 text-[12px]" data-agent-edit>
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <span><b>Suggested by the design agent:</b> {pre.agent}. Check the highlighted {needsEdges ? "edges" : "faces"} and the values, then OK. Nothing changes until you do.</span></div>}
        {impact && <ImpactPanel impact={impact.data} busy={busy} onApply={() => void submit(true)} onBack={() => setImpact(null)} />}
        {repair && <div className="flex gap-2 rounded-lg border border-warning/50 bg-warning/10 p-2.5 text-[12px]" data-repair-note>
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span><b>This feature no longer rebuilds:</b> {repair}. {needsEdges || op === "shell" || op === "draft" ? "The crosses mark where it was picked: click the edges or faces again, or change the size, then OK." : "Change its values or placement, then OK."}</span></div>}
        {op === "sweep" || op === "loft" ? <>
          {sketchNodes.length < 2 && <p className="flex gap-1 rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-[12px]"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
            <span>{op === "sweep" ? "A sweep needs two sketches in the tree: a closed profile, and a path (an open chain of lines/arcs) that starts where the profile is, across it."
              : "A loft needs two or more sketches with one closed profile each, usually on parallel or offset planes."} Make each with <b>Sketch</b> on a plane, then choose <b>Sketch only</b> and <b>Exit sketch</b>.</span></p>}
          {op === "sweep" ? <>
            <Field label="Profile (closed sketch)"><select value={swProfile} onChange={ev => setSwProfile(ev.target.value)} className="h-8 w-full rounded border border-border bg-panel px-1.5 text-[12.5px]" aria-label="Profile sketch">
              <option value="">Choose a sketch…</option>{sketchNodes.map(m => <option key={m.id} value={m.id} disabled={!(m.profiles?.length)}>{m.name}{m.profiles?.length ? "" : " (no closed profile)"}</option>)}</select></Field>
            <Field label="Path (open chain or one loop)"><select value={swPath} onChange={ev => setSwPath(ev.target.value)} className="h-8 w-full rounded border border-border bg-panel px-1.5 text-[12.5px]" aria-label="Path sketch">
              <option value="">Choose a sketch…</option>{sketchNodes.map(m => <option key={m.id} value={m.id} disabled={m.id === swProfile}>{m.name}{m.chains?.length ? " (open chain)" : ""}</option>)}</select></Field>
            <p className="text-[11.5px] text-muted">The profile is swept along the path; sharp corners are mitred. The green lines show both sketches.</p>
          </> : <>
            <div className="rounded-lg border border-border bg-panel2 p-2.5">
              <div className="label mb-1 flex items-center">Sections, in order{loftSecs.length > 0 && <button onClick={() => setLoftSecs([])} className="ml-auto text-[11px] font-normal normal-case text-primary hover:underline">Clear</button>}</div>
              {closedNodes.length === 0 ? <p className="text-[12px] text-muted">No sketches with a closed profile yet.</p>
                : <ul className="space-y-0.5">{closedNodes.map(m => { const k = loftSecs.indexOf(m.id); return (
                  <li key={m.id}><button onClick={() => setLoftSecs(s => (k >= 0 ? s.filter(x => x !== m.id) : [...s, m.id]))} className={cx("flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-[12.5px] hover:bg-text/5", k >= 0 && "bg-primary-soft")}>
                    <span className={cx("flex h-5 w-5 items-center justify-center rounded-full text-[10.5px] font-semibold", k >= 0 ? "bg-primary text-white" : "border border-border text-muted")}>{k >= 0 ? k + 1 : ""}</span>{m.name}</button></li>); })}</ul>}
              <p className="mt-1 text-[11.5px] text-muted">Click the sketches in the order the loft passes through them.</p>
            </div>
            <label className="flex items-center gap-2 text-[12.5px]"><input type="checkbox" checked={ruled} onChange={ev => setRuled(ev.target.checked)} />Ruled (straight between sections)</label>
          </>}
          <div>{seg<"add" | "cut">([["add", op === "sweep" ? "Swept Boss" : "Lofted Boss"], ["cut", op === "sweep" ? "Swept Cut" : "Lofted Cut"]], mode, m => { if (m === "cut" && !topo) return; setMode(m); })}</div>
          <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
        </> : op === "draft" ? <>
          {(["neutral", "faces"] as const).map(b => (
            <button key={b} onClick={() => setDraftBox(b)} className={cx("block w-full rounded-lg border p-2.5 text-left", draftBox === b ? "border-primary bg-primary-soft/40" : "border-border bg-panel2")}>
              <div className="label mb-1">{b === "neutral" ? "Neutral plane (a planar face)" : "Faces to draft"}</div>
              {b === "neutral" ? <p className="text-[12px]">{neutral ? neutral.label : <span className="text-muted">Click the face the draft pivots about (e.g. the parting face or base).</span>}</p>
                : draftFaces.length ? <ul className="space-y-0.5">{draftFaces.map(p => <li key={p.id} className="text-[12px]">{topo ? describe(p, topo) : `Face ${p.id}`}</li>)}</ul>
                : <p className="text-[12px] text-muted">{e?.faces?.length ? `${e.faces.length} face(s) from the original selection. Click faces to replace.` : "Click the side faces to taper (Ctrl+click for several)."}</p>}
            </button>))}
          <div className="flex items-end gap-2">
            <div className="flex-1">{numField("Draft angle", draftAngle, setDraftAngle, "°", "0–45°")}</div>
            <Tip content="Reverse the pull direction" side="top"><button onClick={() => setDraftRev(!draftRev)} className={cx("mb-1 rounded border p-1.5", draftRev ? "border-primary bg-primary-soft text-primary" : "border-border text-muted")} aria-label="Reverse pull direction"><ArrowLeftRight className="h-4 w-4" /></button></Tip>
          </div>
          <p className="flex gap-1 text-[11px] text-muted"><Info className="mt-0.5 h-3 w-3 shrink-0" />{draftRev ? "The faces lean outwards going away from the neutral face." : "The faces lean inwards going away from the neutral face (the part narrows away from it)."}</p>
          <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
        </> : op === "plane" ? <>
          <div className="rounded-lg border border-border bg-panel2 p-2.5">
            <div className="label mb-1">First reference</div>
            <div className="flex flex-wrap gap-1">{seg<string>([["Top", "Top"], ["Front", "Front"], ["Right", "Right"], ["face", "Face"], ...otherPlanes.map(m => [`pl:${m.id}`, m.name] as [string, string])], refBase, setRefBase)}</div>
            <p className="mt-1 text-[12px] text-muted">{refBase === "face" ? (face && topo ? `${describe(face, topo)}: offset from its plane.` : e?.base ? "Using the original face. Click a planar face to change it." : "Click a planar face in the viewer.")
              : refBase.startsWith("pl:") ? `Offset from ${planeBase?.name ?? "the plane"} (its placement now; later edits to it don't move this plane).` : `${refBase} Plane through the origin.`}</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {numField("Offset distance", planeOff, setPlaneOff, "mm", "Negative = other side")}
            {numField("Angle", planeAng, setPlaneAng, "°", "Turns the plane first")}
          </div>
          {Math.abs(num(planeAng) || 0) > 0 && <div><div className="label mb-1">Rotate about</div>{seg<"x" | "y">([["x", "Reference X axis"], ["y", "Reference Y axis"]], rotAxis, setRotAxis)}</div>}
          <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
          <p className="flex gap-1 text-[11px] text-muted"><Info className="mt-0.5 h-3 w-3 shrink-0" />A plane is reference geometry: it never changes the solid. Sketch on it from the feature tree; sketches on it move when you edit the plane.</p>
        </> : op === "mirror" ? <>
          <div>{seg<"features" | "body">([["features", "Mirror features"], ["body", "Mirror body"]], mirrorWhat, setMirrorWhat)}</div>
          {mirrorWhat === "features" ? featurePicker("Features to mirror", "mirrored")
            : <p className="text-[12px] text-muted">The whole body is mirrored and joined to the original.</p>}
          <div className="rounded-lg border border-border bg-panel2 p-2.5">
            <div className="label mb-1">Mirror plane</div>
            <div className="mb-2">{seg<MirrorPlane>([["Right", "Right"], ["Front", "Front"], ["Top", "Top"], ["face", "Face"]], mirrorPlane, setMirrorPlane)}</div>
            <p className="text-[12px] text-muted">{mirrorPlane !== "face" ? `${mirrorPlane} Plane through the origin (green outline).`
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
          : (face && topo ? <p className="text-[12px]">{describe(face, topo)}{op === "hole" ? "" : " — origin at the picked point"}</p>
              : <p className="text-[12px] text-muted">{plane ? "Using the original placement. Click a planar face to move it." : op === "hole" ? "Click the flat face to drill." : "Click a planar face in the viewer. The point you click becomes the origin."}</p>)}
        </div>
        <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
        {op === "fillet" && numField("Radius", size, setSize)}
        {op === "chamfer" && numField("Distance", size, setSize)}
        {op === "shell" && numField("Wall thickness", size, setSize)}
        {op === "hole" && <>
          <HoleWizard editing={e} topo={topo} preset={pre.hole as HolePreset | undefined} face={face && faceN ? { point: face.point, normal: faceN, id: face.id } : null} onSketch={onSketch}
            onApi={a => { hole.current = a; if (a.ready !== holeReady) setHoleReady(a.ready); }} />
          {!e?.place && (e?.count ?? 0) > 1 && <>
            <div><div className="label mb-1">Pattern</div>{seg<"none" | "linear" | "circular">([["none", "Single"], ["linear", "Linear"], ["circular", "Circular"]], pattern, setPattern)}</div>
            {pattern !== "none" && numField("Instances", count, setCount, "")}
            {pattern === "linear" && vec("Spacing (X, Y, Z mm)", step, setStep)}
            {pattern === "circular" && <>{vec("Axis centre (X, Y, Z mm)", center, setCenter)}<p className="text-[11px] text-muted">The axis runs through this point along the face normal. Defaults to the model centre.</p></>}
          </>}
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
        <Button className="flex-1" onClick={() => void submit()} loading={busy} disabled={!ready || !!impact || checking}>{checking ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />Checking assemblies</> : <>{e ? "Update" : "Add"} feature <span className="ml-1 text-[10.5px] opacity-70">Enter</span></>}</Button>
        <Button variant="secondary" onClick={onCancel}>Cancel <span className="ml-1 text-[10.5px] opacity-70">Esc</span></Button>
      </div>
    </div>
  );
}
