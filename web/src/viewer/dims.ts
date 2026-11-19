/**
 * Design parameters drawn on the model as CAD dimensions (SOLIDWORKS "show feature dimensions", automatic).
 * The server says which faces each parameter measures (GET /dims, found by rebuilding with each value nudged);
 * this module resolves that on the current geometry and lays it out in screen space every frame. Pure functions:
 * no three.js, no DOM (tested in dims.test.ts).
 */
import type { Topo, TopoFace, V3 } from "./types";

export type DimKind = "linear" | "diameter" | "radius" | "count" | "angle" | "none" | "hidden" | "label";
export interface DimRef { face: number; ref: "plane" | "axis" | "tangent"; side?: number }
export interface DimSpec {
  param: string; kind: DimKind; a?: DimRef; b?: DimRef; u?: V3; s?: number; faces?: number[]; count?: number; per?: number;
  driven?: number[]; circle?: boolean; pa?: V3; pb?: V3; at?: V3; as?: string; explicit?: boolean;
}
export interface DimsDoc { state: "ready" | "pending" | "paused" | "none"; build_id?: number; dims: DimSpec[]; error?: boolean; whole?: string[] }

interface Circle { c: V3; axis: V3; r: number }
export type Resolved =
  | { param: string; kind: "linear"; A: number[]; B: number[]; u: V3; s: number; faces: number[]; circle?: boolean }
  | { param: string; kind: "round"; sym: "Ø" | "R"; circles: Circle[]; count: number; faces: number[] }
  | { param: string; kind: "tag"; tag: "count" | "angle" | "label"; at: V3[]; count?: number; faces: number[] };

// ------------------------------------------------------------------ vectors
export const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const add = (a: V3, b: V3, k = 1): V3 => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];
export const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const len = (a: V3) => Math.hypot(a[0], a[1], a[2]);
export const unit = (a: V3): V3 => { const n = len(a) || 1; return [a[0] / n, a[1] / n, a[2] / n]; };
const pt = (f: number[], i: number): V3 => [f[i]!, f[i + 1]!, f[i + 2]!];

/** Faces a parameter's dimension measures (strong highlight), else the faces it moves. */
export function dimFaces(d: DimSpec | undefined): number[] {
  if (!d) return [];
  if (d.kind === "linear" && d.a && d.b) return [d.a.face, d.b.face];
  if (d.faces?.length) return d.faces;
  return d.driven ?? [];
}

/** Is the parameter shown on the model at all (not just highlighted)? */
export const onModel = (d: DimSpec) => !["none", "hidden"].includes(d.kind);

const vtol = (v: number) => 1e-3 * Math.max(1, Math.abs(v)) + 1e-4; // topo.json is rounded to 1e-4 mm

/** Point on a cylinder's axis level with the middle of the face. */
function axisMid(f: TopoFace): V3 | null {
  if (!f.axis || !f.axis_point) return null;
  const a = unit(f.axis);
  return add(f.axis_point, a, dot(sub(f.center, f.axis_point), a));
}

function refPoints(f: TopoFace | undefined, r: DimRef, u: V3): { x: number; pts: number[] } | null {
  if (!f) return null;
  if (r.ref === "plane") {
    if (f.type !== "plane" || !f.normal || Math.abs(Math.abs(dot(unit(f.normal), u)) - 1) > 1e-4) return null;
    return { x: dot(f.center, u), pts: f.pos.length ? f.pos : [...f.center] };
  }
  if (f.type !== "cylinder" || f.radius === undefined) return null;
  const m = axisMid(f);
  if (!m || Math.abs(dot(unit(f.axis!), u)) > 1e-4) return null;
  const p = r.ref === "tangent" ? add(m, u, (r.side ?? 1) * f.radius) : m;
  return { x: dot(p, u), pts: [...p] };
}

function circlesOf(topo: Topo, faces: number[], r: number): Circle[] {
  const out: Circle[] = [];
  for (const fid of faces) {
    const f = topo.faces[fid];
    if (!f) continue;
    for (const eid of f.edges) {
      const e = topo.edges[eid];
      if (e?.type === "circle" && e.center && e.axis && e.radius !== undefined && Math.abs(e.radius - r) < vtol(r)
        && !out.some(c => len(sub(c.c, e.center!)) < 1e-6)) out.push({ c: e.center, axis: unit(e.axis), r: e.radius });
    }
  }
  return out;
}

/**
 * The dimensions that still hold on this geometry with these values: a mapping made for an earlier build is shown
 * only where it measures exactly the current value (so a stale one never shows a wrong number).
 */
export function resolveDims(specs: DimSpec[], topo: Topo, values: Record<string, number>): Resolved[] {
  const out: Resolved[] = [];
  for (const d of specs) {
    const v = values[d.param];
    if (v === undefined || !Number.isFinite(v)) continue;
    if (d.kind === "linear" && d.explicit && d.pa && d.pb) {
      const s = len(sub(d.pb, d.pa));
      if (s > 1e-6) out.push({ param: d.param, kind: "linear", A: [...d.pa], B: [...d.pb], u: unit(sub(d.pb, d.pa)), s, faces: [] });
    } else if (d.kind === "linear" && d.a && d.b && d.u) {
      const u = unit(d.u), fa = topo.faces[d.a.face], fb = topo.faces[d.b.face];
      let s: number | null = null, A: number[] = [], B: number[] = [];
      if (d.a.ref === "axis" && d.b.ref === "axis") {
        const ma = fa && axisMid(fa), mb = fb && axisMid(fb);
        if (ma && mb && fa!.axis) { const w = sub(mb, ma); const k = dot(w, unit(fa!.axis)); const perp = add(w, unit(fa!.axis), -k); s = len(perp); A = [...ma]; B = [...add(ma, perp)]; }
      } else {
        const ra = refPoints(fa, d.a, u), rb = refPoints(fb, d.b, u);
        if (ra && rb) { s = rb.x - ra.x; A = ra.pts; B = rb.pts; }
      }
      if (s === null || Math.abs(s - v) > vtol(v)) continue;
      out.push({ param: d.param, kind: "linear", A, B, u: d.a.ref === "axis" && d.b.ref === "axis" ? unit(sub(pt(B, 0), pt(A, 0))) : u, s, faces: [d.a.face, d.b.face], circle: d.circle });
    } else if ((d.kind === "diameter" || d.kind === "radius" || d.kind === "count") && d.faces?.length) {
      const f0 = d.faces.map(i => topo.faces[i]).find(f => f?.type === "cylinder" && f.radius !== undefined);
      if (!f0) continue;
      const r = f0.radius!;
      if (d.kind === "diameter" && Math.abs(2 * r - v) > vtol(v)) continue;
      if (d.kind === "radius" && Math.abs(r - v) > vtol(v)) continue;
      const circles = circlesOf(topo, d.faces, r);
      if (d.kind === "count") {
        const n = new Set(d.faces.map(i => topo.faces[i]).filter(f => f?.axis_point).map(f => axisMid(f!)!.map(x => x.toFixed(3)).join())).size;
        if (n !== Math.round(v) * (d.per ?? 1) || !circles.length) continue;
        out.push({ param: d.param, kind: "tag", tag: "count", at: circles.map(c => c.c), count: n, faces: d.faces });
      } else if (circles.length) {
        out.push({ param: d.param, kind: "round", sym: d.kind === "diameter" ? "Ø" : "R", circles, count: d.count ?? 1, faces: d.faces });
      }
    } else if (d.kind === "angle" && d.faces?.length) {
      const f = topo.faces[d.faces[d.faces.length - 1]!];
      if (f) out.push({ param: d.param, kind: "tag", tag: "angle", at: [f.center], faces: d.faces });
    } else if (d.kind === "label" && d.at) {
      out.push({ param: d.param, kind: "tag", tag: "label", at: [d.at], faces: [] });
    }
  }
  return out;
}

// ------------------------------------------------------------------ layout
/** What the layout needs from the camera: CSS-pixel projection and the screen axes in model space. */
export interface ViewCam {
  project: (p: V3) => [number, number];
  /** unit vector from the target towards the camera, and the screen's right / up directions (model space) */
  vd: V3; right: V3; up: V3;
  /** CSS pixels per model millimetre at the target */
  pxPerMm: number;
  width: number; height: number;
}

/** Two unit directions perpendicular to u, world-axis aligned when u is (the candidate offset sides are ±each). */
export function perpBasis(u: V3): [V3, V3] {
  const n = unit(u);
  const ref: V3 = Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
  const a = unit(cross(ref, n));
  return [a, unit(cross(n, a))];
}

/** The point furthest along w; among points level with it, the one nearest the viewer (``tie``), so a dimension
 * drawn above a face runs along its front edge rather than an arbitrary one. */
export function extreme(pts: number[], w: V3, tie?: V3): V3 {
  let best = -Infinity;
  for (let i = 0; i + 2 < pts.length; i += 3) best = Math.max(best, dot(pt(pts, i), w));
  let at: V3 = pt(pts, 0), near = -Infinity;
  for (let i = 0; i + 2 < pts.length; i += 3) {
    const p = pt(pts, i);
    if (dot(p, w) < best - 2e-4) continue;
    const k = tie ? dot(p, tie) : 0;
    if (k > near + 1e-9) { near = k; at = p; }
  }
  return at;
}

/** A view key that changes only when the camera moves to another side of the part (dimensions don't flicker while
 * orbiting a little, and jump to the better side once the view really changes). */
export function viewKey(vd: V3): string {
  const ax = [0, 1, 2].reduce((m, i) => (Math.abs(vd[i]!) > Math.abs(vd[m]!) ? i : m), 0);
  return `${ax}${vd.map(c => (c > 0.15 ? "+" : c < -0.15 ? "-" : "0")).join("")}`;
}

/**
 * Side on which a linear dimension is drawn (its extension lines run along this direction): visible in this view
 * (not pointing at the camera), outside the material (anchors at the part's extreme on that side), towards the
 * viewer and screen up / right on ties.
 */
export function chooseOffsetDir(u: V3, A: number[], B: number[], bbox: [number, number, number, number, number, number], vd: V3, up: V3, right: V3): V3 {
  const [e1, e2] = perpBasis(u);
  const corners: V3[] = [];
  for (const x of [bbox[0], bbox[3]]) for (const y of [bbox[1], bbox[4]]) for (const z of [bbox[2], bbox[5]]) corners.push([x, y, z]);
  const size = Math.max(1e-6, Math.hypot(bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]));
  let best: V3 = e1, score = -Infinity;
  for (const w of [e1, e2, e1.map(c => -c) as V3, e2.map(c => -c) as V3]) {
    const vis = Math.sqrt(Math.max(0, 1 - dot(w, vd) ** 2));
    const top = Math.max(...corners.map(c => dot(c, w)));
    const reach = Math.max(dot(extreme(A, w), w), dot(extreme(B, w), w));
    const outside = 1 - Math.min(1, (top - reach) / size * 4);
    const sc = 1.0 * vis + 0.8 * outside + 0.15 * dot(w, vd) + 0.1 * dot(w, up) + 0.05 * dot(w, right);
    if (sc > score + 1e-9) { score = sc; best = w; }
  }
  return best;
}

export interface Seg { x1: number; y1: number; x2: number; y2: number }
export interface Arrow { x: number; y: number; dx: number; dy: number }
export interface DimDraw { param: string; lines: Seg[]; arrows: Arrow[]; lx: number; ly: number; text: string; angle: number }

const ARROW = 7, GAP_PX = 22, STEP_PX = 20, EXT_PX = 5;

export function fmtValue(v: number, unit?: string): string {
  const a = Math.abs(v);
  const t = a >= 100 ? v.toFixed(1) : a >= 10 ? v.toFixed(2) : v.toFixed(2);
  return t.replace(/\.?0+$/, "") + (unit && !["mm", ""].includes(unit) ? (unit === "deg" || unit === "°" ? "°" : ` ${unit}`) : "");
}

/** Label text for a resolved dimension (SOLIDWORKS style: 120 · Ø6.6 · 4× Ø6.6 · R3 · 6× · 30°). */
export function dimText(r: Resolved, v: number, unit?: string): string {
  if (r.kind === "linear") return (r.circle ? "Ø" : "") + fmtValue(v, unit);
  if (r.kind === "round") return `${r.count > 1 ? `${r.count}× ` : ""}${r.sym}${fmtValue(v, unit)}`;
  if (r.tag === "count") return `${Math.round(v)}×`;
  if (r.tag === "angle") return `${fmtValue(v)}°`;
  return fmtValue(v, unit);
}

/** Stacking level per linear dimension: dimensions measured along the same direction and drawn on the same side are
 * nested outward, shortest nearest the part. */
export function levels(items: { key: string; s: number }[]): number[] {
  const out = new Array<number>(items.length).fill(0);
  const groups = new Map<string, number[]>();
  items.forEach((it, i) => groups.set(it.key, [...(groups.get(it.key) ?? []), i]));
  for (const idx of groups.values()) idx.sort((a, b) => items[a]!.s - items[b]!.s).forEach((i, k) => { out[i] = k; });
  return out;
}

const dirKey = (v: V3) => { const c = Math.abs(v[0]) > 1e-6 ? Math.sign(v[0]) : Math.abs(v[1]) > 1e-6 ? Math.sign(v[1]) : Math.sign(v[2]); return v.map(x => (x * c).toFixed(3)).join(); };

export function layoutLinear(r: Extract<Resolved, { kind: "linear" }>, w: V3, level: number, cam: ViewCam, text: string): DimDraw | null {
  const ea = extreme(r.A, w, cam.vd), eb = extreme(r.B, w, cam.vd);
  const mm = (px: number) => px / Math.max(cam.pxPerMm, 1e-9);
  const m = Math.max(dot(ea, w), dot(eb, w)) + mm(GAP_PX + level * STEP_PX);
  const v = unit(cross(r.u, w));
  const lat = dot(ea, v);
  const da = add(ea, w, m - dot(ea, w));
  const db = add(da, r.u, r.s);
  const ebl = add(eb, v, lat - dot(eb, v)); // B's extension starts level with A's (lines stay parallel)
  const P = cam.project;
  const [ax, ay] = P(da), [bx, by] = P(db);
  const L = Math.hypot(bx - ax, by - ay);
  if (L < 1.5 || L < 0.15 * r.s * cam.pxPerMm) return null; // looking along the dimension (a short one still shows)
  const ux = (bx - ax) / L, uy = (by - ay) / L;
  const ext = (from: V3, to: V3): Seg => {
    const [x1, y1] = P(from), [x2, y2] = P(add(to, w, mm(EXT_PX)));
    const dl = Math.hypot(x2 - x1, y2 - y1) || 1;
    return { x1: x1 + (x2 - x1) / dl * 3, y1: y1 + (y2 - y1) / dl * 3, x2, y2 };
  };
  const inside = L > 2 * ARROW + 8;
  const lines: Seg[] = [ext(ea, da), ext(ebl, db), { x1: ax, y1: ay, x2: bx, y2: by }];
  const arrows: Arrow[] = inside ? [{ x: ax, y: ay, dx: -ux, dy: -uy }, { x: bx, y: by, dx: ux, dy: uy }]
    : [{ x: ax, y: ay, dx: ux, dy: uy }, { x: bx, y: by, dx: -ux, dy: -uy }];
  if (!inside) lines.push({ x1: ax - ux * 14, y1: ay - uy * 14, x2: ax, y2: ay }, { x1: bx, y1: by, x2: bx + ux * 14, y2: by + uy * 14 });
  let ang = Math.atan2(uy, ux) * 180 / Math.PI;
  if (ang > 90) ang -= 180; else if (ang < -90) ang += 180;
  return { param: r.param, lines, arrows, lx: (ax + bx) / 2, ly: (ay + by) / 2, text, angle: Math.abs(ang) < 1e-6 ? 0 : ang };
}

/** Leader from a model point outward (up-right on screen, away from the part's centre) to a label. */
function leader(param: string, at: V3, cam: ViewCam, center: [number, number], text: string, arrow: boolean): DimDraw {
  const [x, y] = cam.project(at);
  let dx = x - center[0], dy = y - center[1];
  const n = Math.hypot(dx, dy);
  if (n < 1) { dx = 0.7; dy = -0.7; } else { dx /= n; dy /= n; }
  dx = dx * 0.6 + 0.4 * 0.7; dy = dy * 0.6 - 0.4 * 0.7; // lean up-right like a drawing leader
  const k = Math.hypot(dx, dy) || 1; dx /= k; dy /= k;
  const ex = x + dx * 34, ey = y + dy * 34, sh = dx >= 0 ? 10 : -10;
  return { param, lines: [{ x1: x, y1: y, x2: ex, y2: ey }, { x1: ex, y1: ey, x2: ex + sh, y2: ey }],
    arrows: arrow ? [{ x, y, dx: -dx, dy: -dy }] : [], lx: ex + sh + (sh > 0 ? 1 : -1) * text.length * 3.6, ly: ey, text, angle: 0 };
}

/** The circle (of a pattern) nearest the viewer, and its rim point up-right on screen. */
export function rimPoint(circles: Circle[], cam: ViewCam): V3 {
  const c = circles.reduce((b, x) => (dot(x.c, cam.vd) > dot(b.c, cam.vd) + 1e-6 ? x : b), circles[0]!);
  const want = unit(add(cam.right, cam.up));
  let d = add(want, c.axis, -dot(want, c.axis));
  if (len(d) < 1e-6) d = add(cam.right, c.axis, -dot(cam.right, c.axis));
  return add(c.c, unit(d), c.r);
}

export interface LayoutOpts { bbox: Topo["bbox"]; values: Record<string, number>; units: Record<string, string | undefined>; dirs: Map<string, V3> }

/** Every resolved dimension as screen-space lines, arrows and a label. ``dirs`` keeps each linear dimension's side
 * per view key (pass the same Map every frame). */
export function layout(res: Resolved[], cam: ViewCam, o: LayoutOpts): DimDraw[] {
  const vk = viewKey(cam.vd);
  const center = cam.project([(o.bbox[0] + o.bbox[3]) / 2, (o.bbox[1] + o.bbox[4]) / 2, (o.bbox[2] + o.bbox[5]) / 2]);
  const lin = res.filter((r): r is Extract<Resolved, { kind: "linear" }> => r.kind === "linear");
  const ws = lin.map(r => {
    const k = `${r.param}|${vk}`;
    let w = o.dirs.get(k);
    if (!w) { w = chooseOffsetDir(r.u, r.A, r.B, o.bbox, cam.vd, cam.up, cam.right); o.dirs.set(k, w); }
    return w;
  });
  const lv = levels(lin.map((r, i) => ({ key: `${dirKey(r.u)}|${ws[i]!.map(x => x.toFixed(3)).join()}`, s: r.s })));
  const out: DimDraw[] = [];
  lin.forEach((r, i) => { const d = layoutLinear(r, ws[i]!, lv[i]!, cam, dimText(r, o.values[r.param]!, o.units[r.param])); if (d) out.push(d); });
  for (const r of res) {
    if (r.kind === "round") out.push(leader(r.param, rimPoint(r.circles, cam), cam, center, dimText(r, o.values[r.param]!, o.units[r.param]), true));
    else if (r.kind === "tag") {
      const at = r.at.reduce((b, x) => (dot(x, cam.vd) > dot(b, cam.vd) + 1e-6 ? x : b), r.at[0]!);
      out.push(leader(r.param, at, cam, center, dimText(r, o.values[r.param]!, o.units[r.param]), r.tag !== "count"));
    }
  }
  return out;
}

export interface Rect { x: number; y: number; w: number; h: number }
const hit = (a: Rect, b: Rect) => Math.abs(a.x - b.x) * 2 < a.w + b.w && Math.abs(a.y - b.y) * 2 < a.h + b.h;

/**
 * Labels that don't sit on each other: each label (centre x, y; size w, h) takes the first free spot among small
 * moves along its own dimension line, then across it. Earlier labels (priority order) keep their place. Returns
 * the label centres and whether each one had to move.
 */
export function placeLabels(items: { x: number; y: number; w: number; h: number; angle?: number }[], bounds?: { width: number; height: number }): { x: number; y: number; moved: boolean }[] {
  const placed: Rect[] = [];
  return items.map(it => {
    const a = ((it.angle ?? 0) * Math.PI) / 180;
    const along: [number, number] = [Math.cos(a), Math.sin(a)], across: [number, number] = [-Math.sin(a), Math.cos(a)];
    const sx = it.w * 0.6 + 4, sy = it.h + 3;
    const tries: [number, number][] = [[0, 0]];
    for (let k = 1; k <= 3; k++) tries.push([along[0] * sx * k, along[1] * sx * k], [-along[0] * sx * k, -along[1] * sx * k]);
    for (let k = 1; k <= 3; k++) tries.push([across[0] * sy * k, across[1] * sy * k], [-across[0] * sy * k, -across[1] * sy * k]);
    for (const [dx, dy] of tries) {
      const r = { x: it.x + dx, y: it.y + dy, w: it.w, h: it.h };
      const inView = !bounds || (r.x - r.w / 2 >= 0 && r.y - r.h / 2 >= 0 && r.x + r.w / 2 <= bounds.width && r.y + r.h / 2 <= bounds.height);
      if (inView && !placed.some(p => hit(p, r))) { placed.push(r); return { x: r.x, y: r.y, moved: dx !== 0 || dy !== 0 }; }
    }
    placed.push({ x: it.x, y: it.y, w: it.w, h: it.h });
    return { x: it.x, y: it.y, moved: false };
  });
}

/** Parse and check an on-screen edit against the parameter's limits (same rules as the panel and the server). */
export function checkEdit(text: string, whole: boolean, meta: { min?: number; max?: number; unit?: string; label?: string } = {}): { ok: true; value: number } | { ok: false; error: string } {
  const t = text.trim().replace(",", ".");
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t)) return { ok: false, error: "Enter a number" };
  const v = Number(t);
  if (!Number.isFinite(v)) return { ok: false, error: "Enter a number" };
  if (whole && !Number.isInteger(v)) return { ok: false, error: `${meta.label ?? "This value"} must be a whole number` };
  if ((meta.min !== undefined && v < meta.min) || (meta.max !== undefined && v > meta.max))
    return { ok: false, error: `${meta.label ?? "Value"} must be ${meta.min ?? "−∞"}–${meta.max ?? "∞"}${meta.unit ? ` ${meta.unit}` : ""}` };
  return { ok: true, value: v };
}
