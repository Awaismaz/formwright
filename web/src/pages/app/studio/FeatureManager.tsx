import { useEffect, useMemo, useState } from "react";
import { Check, Info, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { ManualFeature, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button, Field, Input } from "@/components/ui";
import { describe, edgeMid } from "@/viewer/measure";
import type { Pick, SketchPreview, Topo, V3 } from "@/viewer/types";

const TITLE: Record<ManualFeature["op"], string> = { fillet: "Fillet", chamfer: "Chamfer", hole: "Hole", extrude: "Extrude / Cut" };

export function xDirFor(n: V3): V3 {
  if (Math.abs(n[2]) > 0.9) return [1, 0, 0];
  const c: V3 = [n[1] * 1 - n[2] * 0, n[2] * 0 - n[0] * 1, 0]; // n × Z
  const l = Math.hypot(...c) || 1;
  return [c[0] / l, c[1] / l, c[2] / l];
}

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));

export default function FeatureManager({ project, op, editing, topo, selection, onSelection, onSketch, onDone, onCancel }: {
  project: Project; op: ManualFeature["op"]; editing: ManualFeature | null; topo: Topo | null; selection: Pick[];
  onSelection: (p: Pick[]) => void; onSketch: (s: SketchPreview | null) => void; onDone: () => void; onCancel: () => void;
}) {
  const e = editing;
  const [name, setName] = useState(e?.name ?? TITLE[op]);
  const [size, setSize] = useState(String(e?.r ?? e?.d ?? (op === "hole" ? 6.6 : op === "fillet" ? 2 : 1)));
  const [depth, setDepth] = useState(e?.depth ? String(e.depth) : "");
  const [count, setCount] = useState(String(e?.count ?? 1));
  const [step, setStep] = useState<[string, string, string]>(e?.step ? e.step.map(String) as [string, string, string] : ["20", "0", "0"]);
  const [kind, setKind] = useState<"rect" | "circle">(e?.sketch?.kind === "circle" ? "circle" : "rect");
  const [w, setW] = useState(String(e?.sketch?.w ?? 20));
  const [h, setH] = useState(String(e?.sketch?.h ?? 10));
  const [r, setR] = useState(String(e?.sketch?.r ?? 5));
  const [cx_, setCx] = useState(String(e?.sketch?.cx ?? 0));
  const [cy_, setCy] = useState(String(e?.sketch?.cy ?? 0));
  const [dist, setDist] = useState(String(e?.distance ?? 5));
  const [mode, setMode] = useState<"add" | "cut">(e?.mode ?? "add");
  const [busy, setBusy] = useState(false);

  const edges = selection.filter(p => p.kind === "edge") as Extract<Pick, { kind: "edge" }>[];
  const face = selection.find(p => p.kind === "face" && topo?.faces[p.id]?.type === "plane") as Extract<Pick, { kind: "face" }> | undefined;
  const faceN = face && topo ? topo.faces[face.id]!.normal! : null;
  const plane = useMemo(() => {
    if (face && faceN) return { origin: face.point, normal: faceN, x_dir: xDirFor(faceN) };
    if (e?.plane) return { origin: e.plane.origin, normal: e.plane.normal, x_dir: e.plane.x_dir ?? xDirFor(e.plane.normal) };
    if (e?.point && e?.normal) return { origin: e.point, normal: e.normal, x_dir: xDirFor(e.normal) };
    return null;
  }, [face, faceN, e]);

  useEffect(() => {
    if (op === "extrude" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind, w: num(w), h: num(h), r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 });
    else if (op === "hole" && plane) onSketch({ origin: plane.origin, normal: plane.normal, xDir: plane.x_dir, kind: "circle", r: num(size) / 2, cx: 0, cy: 0 });
    else onSketch(null);
  }, [op, plane, kind, w, h, r, cx_, cy_, size]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onSketch(null), []); // eslint-disable-line react-hooks/exhaustive-deps

  const needsEdges = op === "fillet" || op === "chamfer";
  const ready = needsEdges ? (edges.length > 0 || !!e?.edges?.length) : !!plane;

  const submit = async () => {
    let f: Record<string, unknown> = { op, name, suppressed: e?.suppressed ?? false };
    if (needsEdges) {
      const pts = edges.length && topo ? edges.map(p => edgeMid(topo, p.id)) : e?.edges;
      f = { ...f, edges: pts, [op === "fillet" ? "r" : "d"]: num(size) };
    } else if (op === "hole") {
      f = { ...f, point: plane!.origin, normal: plane!.normal, d: num(size), depth: depth ? num(depth) : null };
      if (num(count) > 1) f = { ...f, count: num(count), step: step.map(num) };
    } else {
      f = { ...f, plane: plane, distance: num(dist), mode,
        sketch: kind === "rect" ? { kind, w: num(w), h: num(h), cx: num(cx_) || 0, cy: num(cy_) || 0 } : { kind, r: num(r), cx: num(cx_) || 0, cy: num(cy_) || 0 } };
    }
    setBusy(true);
    try {
      if (e) await api.patch(`/api/projects/${project.id}/manual/${e.id}`, { feature: f });
      else await api.post(`/api/projects/${project.id}/manual`, { feature: f });
      toast.success(`${name} ${e ? "updated" : "added"} — rebuilt and verified`);
      onSelection([]); onDone();
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Feature failed"); }
    finally { setBusy(false); }
  };

  const numField = (label: string, v: string, set: (s: string) => void, unit = "mm", hint?: string) => (
    <Field label={label} hint={hint}><div className="flex items-center gap-1.5"><Input value={v} onChange={ev => set(ev.target.value)} inputMode="decimal" className="h-8" /><span className="w-7 text-xs text-muted">{unit}</span></div></Field>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border bg-gradient-to-r from-primary-soft to-transparent px-3 py-2.5">
        <span className="flex-1 text-sm font-semibold">{e ? "Edit" : "New"} {TITLE[op]}</span>
        <button onClick={submit} disabled={!ready || busy} className="rounded bg-success p-1 text-white disabled:opacity-40" aria-label="OK"><Check className="h-4 w-4" /></button>
        <button onClick={onCancel} className="rounded bg-danger p-1 text-white" aria-label="Cancel"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3 text-[13px]">
        <div className="rounded-lg border border-border bg-panel2 p-2.5">
          <div className="label mb-1">{needsEdges ? "Edges" : "Placement face"}</div>
          {needsEdges ? (edges.length ? <ul className="space-y-0.5">{edges.map(p => <li key={p.id} className="flex items-center justify-between text-[12px]">{topo ? describe(p, topo) : `Edge ${p.id}`}
              <button onClick={() => onSelection(selection.filter(x => x !== p))} aria-label="Remove"><X className="h-3 w-3 text-muted" /></button></li>)}</ul>
            : <p className="text-[12px] text-muted">{e?.edges?.length ? `${e.edges.length} edge(s) from the original selection. Click edges in the viewer to replace.` : "Click edges in the viewer (Ctrl+click for several)."}</p>)
            : (face && topo ? <p className="text-[12px]">{describe(face, topo)} — origin at the picked point</p>
              : <p className="text-[12px] text-muted">{plane ? "Using the original placement. Click a planar face to move it." : "Click a planar face in the viewer. The point you click becomes the origin."}</p>)}
        </div>
        <Field label="Name"><Input value={name} onChange={ev => setName(ev.target.value)} className="h-8" /></Field>
        {op === "fillet" && numField("Radius", size, setSize)}
        {op === "chamfer" && numField("Distance", size, setSize)}
        {op === "hole" && <>
          {numField("Diameter", size, setSize, "mm", "e.g. 6.6 for M6 clearance (ISO 273 medium)")}
          {numField("Depth", depth, setDepth, "mm", "Leave empty for a through hole")}
          <div className="grid grid-cols-[1fr_2fr] gap-2">
            {numField("Count", count, setCount, "")}
            <Field label="Spacing (X, Y, Z mm)"><div className="flex gap-1">{step.map((s, i) => <Input key={i} value={s} onChange={ev => { const n = [...step] as [string, string, string]; n[i] = ev.target.value; setStep(n); }} className="h-8 px-1.5 text-center" />)}</div></Field>
          </div>
        </>}
        {op === "extrude" && <>
          <div className="inline-flex overflow-hidden rounded border border-border text-[12.5px]">
            {(["add", "cut"] as const).map(m => <button key={m} onClick={() => setMode(m)} className={cx("px-3 py-1", mode === m ? "bg-primary text-white" : "text-muted")}>{m === "add" ? "Boss (add)" : "Cut (remove)"}</button>)}
          </div>
          <div>
            <div className="label mb-1">Sketch on face</div>
            <div className="mb-2 inline-flex overflow-hidden rounded border border-border text-[12.5px]">
              {(["rect", "circle"] as const).map(k => <button key={k} onClick={() => setKind(k)} className={cx("px-3 py-1", kind === k ? "bg-primary text-white" : "text-muted")}>{k === "rect" ? "Rectangle" : "Circle"}</button>)}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {kind === "rect" ? <>{numField("Width", w, setW)}{numField("Height", h, setH)}</> : numField("Radius", r, setR)}
              {numField("Offset X", cx_, setCx)}{numField("Offset Y", cy_, setCy)}
            </div>
            <p className="mt-1 flex gap-1 text-[11px] text-muted"><Info className="mt-0.5 h-3 w-3 shrink-0" />Offsets are measured on the face from the picked point. The green outline previews the sketch.</p>
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
