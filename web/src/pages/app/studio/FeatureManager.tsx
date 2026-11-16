import { useEffect, useMemo, useState } from "react";
import { Check, Info, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { ManualFeature, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button, Field, Input } from "@/components/ui";
import { describe, edgeMid } from "@/viewer/measure";
import type { Pick, SketchPreview, Topo, V3 } from "@/viewer/types";

export type FeatureOp = Exclude<ManualFeature["op"], "sketch">;
const TITLE: Record<FeatureOp, string> = { fillet: "Fillet", chamfer: "Chamfer", hole: "Hole", extrude: "Extrude", shell: "Shell", mirror: "Mirror" };

export function xDirFor(n: V3): V3 {
  if (Math.abs(n[2]) > 0.9) return [1, 0, 0];
  const c: V3 = [n[1], -n[0], 0]; // n × Z
  const l = Math.hypot(...c) || 1;
  return [c[0] / l, c[1] / l, c[2] / l];
}

export function selectKindsFor(op: FeatureOp): Pick["kind"][] {
  return op === "fillet" || op === "chamfer" ? ["edge"] : ["face"];
}

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
const fmt = (v: number) => String(+v.toFixed(3));

export default function FeatureManager({ project, op, editing, preset, topo, selection, onSelection, onSketch, onDone, onCancel, onBusy }: {
  project: Project; op: FeatureOp; editing: ManualFeature | null; preset?: Record<string, unknown>; topo: Topo | null; selection: Pick[];
  onSelection: (p: Pick[]) => void; onSketch: (s: SketchPreview | null) => void; onDone: () => void; onCancel: () => void; onBusy: (b: boolean) => void;
}) {
  const e = editing;
  const pre = preset ?? {};
  const [name, setName] = useState(e?.name ?? (op === "extrude" ? (pre.mode === "cut" ? "Extruded Cut" : "Extruded Boss") : pre.pattern ? `${pre.pattern === "circular" ? "Circular" : "Linear"} hole pattern` : TITLE[op]));
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
  const [mirrorPlane, setMirrorPlane] = useState<"face" | "YZ" | "XZ" | "XY">("face");
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

  useEffect(() => {
    if (op === "extrude" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind, w: num(w), h: num(h), r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 });
    else if (op === "hole" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind: "circle", r: num(size) / 2, cx: 0, cy: 0 });
    else onSketch(null);
  }, [op, plane, kind, w, h, r, cx_, cy_, size]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onSketch(null), []); // eslint-disable-line react-hooks/exhaustive-deps

  const needsEdges = op === "fillet" || op === "chamfer";
  const ready = needsEdges ? (edges.length > 0 || !!e?.edges?.length)
    : op === "shell" ? (planarFaces.length > 0 || !!e?.faces?.length)
    : op === "mirror" ? (mirrorPlane !== "face" || !!plane)
    : !!plane;

  const submit = async () => {
    let f: Record<string, unknown> = { op, name, suppressed: e?.suppressed ?? false };
    if (needsEdges) {
      const pts = edges.length && topo ? edges.map(p => edgeMid(topo, p.id)) : e?.edges;
      f = { ...f, edges: pts, [op === "fillet" ? "r" : "d"]: num(size) };
    } else if (op === "hole") {
      f = { ...f, point: plane!.origin, normal: plane!.normal, d: num(size), depth: depth ? num(depth) : null };
      if (pattern !== "none" && num(count) > 1) f = { ...f, count: num(count), ...(pattern === "circular" ? { pattern: "circular", center: center.map(num) } : { step: step.map(num) }) };
    } else if (op === "shell") {
      const faces = planarFaces.length && topo ? planarFaces.map(p => ({ point: p.point, normal: topo.faces[p.id]!.normal! })) : e?.faces;
      f = { ...f, faces, t: num(size) };
    } else if (op === "mirror") {
      const pl = mirrorPlane === "face" ? { origin: plane!.origin, normal: plane!.normal }
        : { origin: bbc, normal: mirrorPlane === "YZ" ? [1, 0, 0] : mirrorPlane === "XZ" ? [0, 1, 0] : [0, 0, 1] };
      f = { ...f, plane: pl };
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
        <span className="flex-1 text-sm font-semibold">{e ? "Edit" : ""} {op === "extrude" ? (mode === "cut" ? "Extruded Cut" : "Extruded Boss") : TITLE[op]}</span>
        <button onClick={submit} disabled={!ready || busy} className="rounded bg-success p-1 text-white disabled:opacity-40" aria-label="OK"><Check className="h-4 w-4" /></button>
        <button onClick={onCancel} className="rounded bg-danger p-1 text-white" aria-label="Cancel"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3 text-[13px]">
        <div className="rounded-lg border border-border bg-panel2 p-2.5">
          <div className="label mb-1">{needsEdges ? "Edges" : op === "shell" ? "Faces to remove" : op === "mirror" ? "Mirror plane" : "Placement face"}</div>
          {op === "mirror" && <div className="mb-2">{seg<"face" | "YZ" | "XZ" | "XY">([["face", "Picked face"], ["YZ", "YZ"], ["XZ", "XZ"], ["XY", "XY"]], mirrorPlane, setMirrorPlane)}</div>}
          {needsEdges ? (edges.length ? <ul className="space-y-0.5">{edges.map(p => <li key={p.id} className="flex items-center justify-between text-[12px]">{topo ? describe(p, topo) : `Edge ${p.id}`}
              <button onClick={() => onSelection(selection.filter(x => x !== p))} aria-label="Remove"><X className="h-3 w-3 text-muted" /></button></li>)}</ul>
            : <p className="text-[12px] text-muted">{e?.edges?.length ? `${e.edges.length} edge(s) from the original selection. Click edges to replace.` : "Click edges in the viewer (Ctrl+click for several)."}</p>)
          : op === "shell" ? (planarFaces.length ? <ul className="space-y-0.5">{planarFaces.map(p => <li key={p.id} className="text-[12px]">{topo ? describe(p, topo) : `Face ${p.id}`}</li>)}</ul>
              : <p className="text-[12px] text-muted">{e?.faces?.length ? `${e.faces.length} face(s) from the original selection.` : "Click the face(s) to open (Ctrl+click for several)."}</p>)
          : op === "mirror" && mirrorPlane !== "face" ? <p className="text-[12px] text-muted">{mirrorPlane} plane through the model centre ({bbc.map(fmt).join(", ")}).</p>
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
      </div>
      <div className="flex gap-2 border-t border-border p-3">
        <Button className="flex-1" onClick={submit} loading={busy} disabled={!ready}>{e ? "Update" : "Add"} feature</Button>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
