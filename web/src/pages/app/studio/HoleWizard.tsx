import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Info, Plus, TriangleAlert, X } from "lucide-react";
import { api } from "@/lib/api";
import type { ManualFeature } from "@/lib/types";
import { cx } from "@/lib/format";
import { Field, Input } from "@/components/ui";
import type { SketchPreview, Topo, V3 } from "@/viewer/types";

/** Hole Wizard (STU-08 / IDEA 3): ISO fastener holes placed by distance from the face's edges, with the edge-distance
 *  and washer checks shown before OK. Sizes come from the server tables (ISO 273, DIN 974-1, ISO 10642, ISO 7089). */

export interface HoleTables {
  sizes: number[]; fits: string[];
  clearance: Record<string, Record<string, number>>; tap_drill: Record<string, number>; pitch: Record<string, number>;
  cbore_d: Record<string, number>; cbore_depth: Record<string, number>; csk_d: Record<string, number>; washer_od: Record<string, number>;
  sources: Record<string, string>;
}
export type HoleType = "simple" | "clearance" | "tapped" | "cbore" | "csk";
type Mode = "corners" | "points" | "picked";
export interface HoleApi { ready: boolean; payload: () => Record<string, unknown> }
/** Values typed with Ctrl+K ("hole M6 x4 10 from edges") */
export interface HolePreset { type?: HoleType; size?: number; d?: number; mode?: Mode; dx?: number; dy?: number }
interface FaceRef { point: V3; normal: V3; id: number | null }

const TYPES: [HoleType, string][] = [["clearance", "Clearance"], ["tapped", "Tapped"], ["cbore", "C'bore"], ["csk", "C'sink"], ["simple", "Simple"]];
const n2 = (s: string) => (s.trim() === "" ? NaN : Number(s));
const r1 = (v: number) => String(+v.toFixed(3));

export function xDir(n: V3): V3 {
  if (Math.abs(n[2]) > 0.9) return [1, 0, 0];
  const l = Math.hypot(n[1], n[0]) || 1; return [n[1] / l, -n[0] / l, 0];
}
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/** The face's extent in its sketch frame (x along xDir, y = normal × x), from its exact-B-rep triangulation. */
export function faceBox(topo: Topo, id: number, origin: V3, n: V3): [number, number, number, number] | null {
  const f = topo.faces[id]; if (!f) return null;
  const x = xDir(n), y = cross(n, x);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < f.pos.length; i += 3) {
    const d: V3 = [f.pos[i]! - origin[0], f.pos[i + 1]! - origin[1], f.pos[i + 2]! - origin[2]];
    const u = dot(d, x), v = dot(d, y);
    x0 = Math.min(x0, u); x1 = Math.max(x1, u); y0 = Math.min(y0, v); y1 = Math.max(y1, v);
  }
  return Number.isFinite(x0) ? [x0, y0, x1, y1] : null;
}

/** Hole centres in face coordinates, as the kernel places them (fw.hole_centres). */
export function centres(mode: Mode, box: [number, number, number, number], dx: number, dy: number, pts: [number, number][]): [number, number][] {
  const [x0, y0, x1, y1] = box;
  if (mode === "corners") return [[x0 + dx, y0 + dy], [x1 - dx, y0 + dy], [x1 - dx, y1 - dy], [x0 + dx, y1 - dy]];
  return pts.map(([u, v]) => [x0 + u, y0 + v]);
}

export default function HoleWizard({ editing, face, topo, onSketch, onApi, preset }: {
  editing: ManualFeature | null; face: FaceRef | null; topo: Topo | null; preset?: HolePreset;
  onSketch: (s: SketchPreview | null) => void; onApi: (a: HoleApi) => void;
}) {
  const e = editing;
  const pr = preset ?? {};
  const tables = useQuery({ queryKey: ["hole-standards"], queryFn: () => api.get<HoleTables>("/api/holes/standards"), staleTime: Infinity });
  const T = tables.data;
  const [type, setType] = useState<HoleType>((e?.spec?.type as HoleType | undefined) ?? pr.type ?? (e ? "simple" : "clearance"));
  const [size, setSize] = useState(String(e?.spec?.size ?? pr.size ?? 6));
  const [fit, setFit] = useState(e?.spec?.fit ?? "medium");
  const [dia, setDia] = useState(String(e?.d ?? pr.d ?? 6.6));
  const [blind, setBlind] = useState(!!e?.depth);
  const [depth, setDepth] = useState(e?.depth ? String(e.depth) : "10");
  const [mode, setMode] = useState<Mode>(e ? (e.place ? e.place.mode : "picked") : pr.mode ?? "corners");
  const [dx, setDx] = useState(String(e?.place?.dx ?? pr.dx ?? 10));
  const [dy, setDy] = useState(String(e?.place?.dy ?? pr.dy ?? 10));
  const [pts, setPts] = useState<[string, string][]>(e?.place?.pts?.map(([u, v]) => [String(u), String(v)] as [string, string]) ?? [["10", "10"]]);

  const sz = Number(size);
  const drill = type === "simple" ? n2(dia) : !T ? NaN : type === "tapped" ? T.tap_drill[sz]! : T.clearance[sz]?.[fit] ?? NaN;
  const cb = type === "cbore" && T ? { d: T.cbore_d[sz]!, depth: T.cbore_depth[sz]! } : null;
  const csk = type === "csk" && T ? T.csk_d[sz] ?? null : null;
  const washer = T && type !== "simple" && type !== "tapped" ? T.washer_od[sz] : undefined;
  const pl = face ?? (e?.place ? { point: e.place.face.point, normal: e.normal ?? [0, 0, 1], id: null } : e?.point && e.normal ? { point: e.point, normal: e.normal, id: null } : null);
  const box = useMemo(() => (pl && topo && face?.id != null ? faceBox(topo, face.id, pl.point, pl.normal) : null), [pl?.point.join(","), face?.id, topo]); // eslint-disable-line react-hooks/exhaustive-deps
  const uv = box && mode !== "picked" ? centres(mode, box, n2(dx), n2(dy), pts.map(([u, v]) => [n2(u), n2(v)])) : [];
  // edge distance of each hole to the face boundary (the closest side)
  const edgeDist = box ? Math.min(...uv.map(([u, v]) => Math.min(u - box[0], box[2] - u, v - box[1], box[3] - v))) : NaN;
  const nominal = type === "simple" ? NaN : sz;
  const checks: { ok: boolean; text: string }[] = [];
  if (Number.isFinite(edgeDist) && uv.length) {
    const ref = Number.isFinite(nominal) ? nominal : drill;
    checks.push({ ok: edgeDist >= 1.5 * ref - 1e-9, text: `Edge distance ${r1(edgeDist)} mm ${edgeDist >= 1.5 * ref - 1e-9 ? "≥" : "<"} 1.5 × ${Number.isFinite(nominal) ? `d (M${sz})` : "Ø"} = ${r1(1.5 * ref)} mm` });
    if (washer) checks.push({ ok: edgeDist >= washer / 2 - 1e-9, text: `Washer Ø${washer} (ISO 7089) ${edgeDist >= washer / 2 - 1e-9 ? "stays on the face" : "overhangs the edge"}` });
    if (cb) checks.push({ ok: edgeDist >= cb.d / 2 + 1, text: `Counterbore wall to the edge ${r1(edgeDist - cb.d / 2)} mm` });
  }
  const fitsFace = !box || uv.every(([u, v]) => u > box[0] && u < box[2] && v > box[1] && v < box[3]);
  const ready = !!pl && Number.isFinite(drill) && drill > 0 && (!blind || n2(depth) > 0)
    && (mode === "picked" || (!!box || !!e?.place) && fitsFace && (mode !== "corners" || (n2(dx) > 0 && n2(dy) > 0)));

  // preview: each hole (and its counterbore / countersink outline) on the face, plus the face's reference box
  useEffect(() => {
    if (!pl) { onSketch(null); return; }
    const n = pl.normal, x = xDir(n), y = cross(n, x), o = pl.point;
    const at = (u: number, v: number): V3 => [o[0] + x[0] * u + y[0] * v, o[1] + x[1] * u + y[1] * v, o[2] + x[2] * u + y[2] * v];
    const circle = (u: number, v: number, r: number) => Array.from({ length: 49 }, (_, i) => { const a = (i / 48) * Math.PI * 2; return at(u + Math.cos(a) * r, v + Math.sin(a) * r); });
    const list: [number, number][] = mode === "picked" ? [[0, 0]] : uv;
    const lines: V3[][] = [];
    for (const [u, v] of list) {
      if (Number.isFinite(drill)) lines.push(circle(u, v, drill / 2));
      if (cb) lines.push(circle(u, v, cb.d / 2)); else if (csk) lines.push(circle(u, v, csk / 2));
    }
    if (box && mode !== "picked") lines.push([at(box[0], box[1]), at(box[2], box[1]), at(box[2], box[3]), at(box[0], box[3]), at(box[0], box[1])]);
    onSketch(lines.length ? { origin: [0, 0, 0], normal: [0, 0, 1], xDir: [1, 0, 0], kind: "lines", lines, cx: 0, cy: 0 } : null);
  }, [pl?.point.join(","), pl?.normal.join(","), mode, drill, cb?.d, csk, JSON.stringify(uv), box?.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    onApi({
      ready,
      payload: () => {
        const f: Record<string, unknown> = { point: pl!.point, normal: pl!.normal, d: Number.isFinite(drill) ? drill : 1, depth: blind ? n2(depth) : null };
        if (type !== "simple") f.spec = { type, size: sz, fit };
        if (mode !== "picked") f.place = { mode, face: { point: pl!.point }, x_dir: xDir(pl!.normal), ...(mode === "corners" ? { dx: n2(dx), dy: n2(dy) } : { pts: pts.map(([u, v]) => [n2(u), n2(v)]) }) };
        return f;
      },
    });
  }); // every render: the parent always submits the latest values

  const seg = <K extends string>(opts: [K, string][], v: K, set: (x: K) => void, label: string) => (
    <div className="inline-flex flex-wrap overflow-hidden rounded border border-border text-[12px]" role="group" aria-label={label}>{opts.map(([k, l]) =>
      <button key={k} onClick={() => set(k)} className={cx("px-2 py-1", v === k ? "bg-primary text-white" : "text-muted hover:bg-text/5")}>{l}</button>)}</div>
  );
  const numIn = (label: string, v: string, set: (s: string) => void, hint?: string) => (
    <Field label={label} hint={hint}><div className="flex items-center gap-1.5"><Input value={v} onChange={ev => set(ev.target.value)} inputMode="decimal" className="h-8" aria-label={label} /><span className="w-7 text-xs text-muted">mm</span></div></Field>
  );

  return (
    <div className="space-y-3">
      <div><div className="label mb-1">Hole type</div>{seg(TYPES, type, setType, "Hole type")}</div>
      {type === "simple" ? numIn("Diameter", dia, setDia) : (
        <div className="grid grid-cols-2 gap-2">
          <Field label="Size (ISO metric)"><select value={size} onChange={ev => setSize(ev.target.value)} className="h-8 w-full rounded border border-border bg-panel px-1.5 text-[12.5px]" aria-label="Fastener size">
            {(T?.sizes ?? [3, 4, 5, 6, 8, 10, 12, 16, 20, 24]).map(s => <option key={s} value={s} disabled={type === "csk" && !!T && !T.csk_d[s]}>M{s}</option>)}</select></Field>
          {type !== "tapped" && <Field label="Fit (ISO 273)"><select value={fit} onChange={ev => setFit(ev.target.value)} className="h-8 w-full rounded border border-border bg-panel px-1.5 text-[12.5px]" aria-label="Clearance fit">
            {["fine", "medium", "coarse"].map(f => <option key={f} value={f}>{f[0]!.toUpperCase() + f.slice(1)}{T ? ` · Ø${T.clearance[sz]?.[f]}` : ""}</option>)}</select></Field>}
        </div>)}
      {type !== "simple" && T && (
        <div className="rounded-md bg-panel2 px-2.5 py-1.5 text-[12px]">
          <div className="font-medium">{type === "tapped" ? `M${sz} × ${T.pitch[sz]} tapped · Ø${drill} drill` : `Ø${drill} through clearance`}
            {cb && ` · counterbore Ø${cb.d} × ${cb.depth}`}{csk && ` · countersink Ø${csk} × 90°`}</div>
          <div className="mt-0.5 text-[10.5px] text-muted">{T.sources[type === "cbore" ? "cbore" : type === "csk" ? "csk" : type === "tapped" ? "tapped" : "clearance"]}</div>
        </div>)}
      <div><div className="label mb-1">End condition</div>{seg<"t" | "b">([["t", "Through all"], ["b", "Blind"]], blind ? "b" : "t", k => setBlind(k === "b"), "End condition")}</div>
      {blind && numIn("Depth", depth, setDepth, type === "tapped" ? "Drill depth; the thread is cosmetic" : undefined)}
      <div>
        <div className="label mb-1">Position on the face</div>
        {seg<Mode>([["corners", "4 corners"], ["points", "By X / Y"], ["picked", "At picked point"]], mode, setMode, "Position")}
        {mode === "corners" && <div className="mt-2 grid grid-cols-2 gap-2">{numIn("From left/right edges", dx, setDx)}{numIn("From bottom/top edges", dy, setDy)}</div>}
        {mode === "points" && <div className="mt-2 space-y-1.5">
          <div className="text-[11px] text-muted">Measured from the face's lower-left corner (X along the face, Y across it).</div>
          {pts.map(([u, v], i) => (
            <div key={i} className="flex items-center gap-1.5">
              <span className="w-4 text-[11px] text-muted">{i + 1}</span>
              <Input value={u} onChange={ev => setPts(p => p.map((q, j) => (j === i ? [ev.target.value, q[1]] : q)))} className="h-7 px-1.5 text-center" aria-label={`Hole ${i + 1} X`} placeholder="X" />
              <Input value={v} onChange={ev => setPts(p => p.map((q, j) => (j === i ? [q[0], ev.target.value] : q)))} className="h-7 px-1.5 text-center" aria-label={`Hole ${i + 1} Y`} placeholder="Y" />
              <button onClick={() => setPts(p => p.filter((_, j) => j !== i))} disabled={pts.length === 1} className="rounded p-0.5 text-muted hover:text-text disabled:opacity-30" aria-label={`Remove hole ${i + 1}`}><X className="h-3.5 w-3.5" /></button>
            </div>))}
          <button onClick={() => setPts(p => [...p, [p.at(-1)?.[0] ?? "10", String(n2(p.at(-1)?.[1] ?? "0") + 20)]])} className="flex items-center gap-1 text-[12px] text-primary hover:underline"><Plus className="h-3.5 w-3.5" />Add hole</button>
        </div>}
        {mode === "picked" && <p className="mt-1 text-[11.5px] text-muted">One hole at the point you clicked on the face.</p>}
        {box && mode !== "picked" && <p className="mt-1 text-[11px] text-muted">Face {r1(box[2] - box[0])} × {r1(box[3] - box[1])} mm. The holes follow its edges when the part changes size.</p>}
        {!box && e?.place && <p className="mt-1 text-[11px] text-muted">Using the original face. Click a flat face to move the holes.</p>}
        {!fitsFace && <p className="mt-1 text-[11.5px] text-danger">Some holes fall outside the face.</p>}
      </div>
      {checks.length > 0 && (
        <ul className="space-y-0.5 rounded-md border border-border px-2.5 py-1.5 text-[12px]" aria-label="Hole checks">
          {checks.map(c => <li key={c.text} className="flex items-start gap-1.5">{c.ok ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> : <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />}{c.text}</li>)}
          <li className="flex gap-1 pt-0.5 text-[10.5px] text-muted"><Info className="mt-0.5 h-3 w-3 shrink-0" />{T?.sources.edge ?? "Guidance only, not a strength check."}</li>
        </ul>)}
    </div>
  );
}
