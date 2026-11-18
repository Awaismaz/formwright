/**
 * 2D drafting (DRW-017): the drawing document and its pure geometry helpers (no React). The geometry is the same
 * model as the Design Studio sketcher (`web/src/sketch`), so its trim / extend / offset / fillet / mirror / slot /
 * polygon tools work on it directly; every entity also carries an ISO 128 layer. Dimensions reference point and
 * entity ids and are measured from the geometry (associative): a value is never typed in.
 * Units: drawing units (mm or inch), y up. Paper: millimetres, y down.
 */
import { chainsOf, clone, uid, type SEntity, type Sketch } from "@/sketch/model";
import { distTo, geomOf, intersect, type P2 } from "@/sketch/tools";

export type Layer = "visible" | "hidden" | "center" | "dimension" | "construction";
export const LAYERS: { key: Layer; label: string; iso: string; width: number }[] = [
  { key: "visible", label: "Visible", iso: "01.2 continuous wide", width: 0.5 },
  { key: "hidden", label: "Hidden", iso: "02.1 dashed narrow", width: 0.25 },
  { key: "center", label: "Centre", iso: "04.1 long-dash dotted narrow", width: 0.25 },
  { key: "dimension", label: "Dimension", iso: "01.1 continuous narrow", width: 0.25 },
  { key: "construction", label: "Construction", iso: "not printed", width: 0.13 },
];
export type DEnt = SEntity & { layer: Layer };
export interface DPoint { id: string; x: number; y: number }
export type Tol = { kind: "sym"; up: number } | { kind: "dev" | "limits"; up: number; lo: number } | { kind: "fit"; fit: string };
interface DimBase { id: string; pos: P2; prefix?: string; suffix?: string; tol?: Tol }
export type Dim = DimBase & (
  | { type: "linear"; orient: "h" | "v" | "aligned"; a: string; b: string }
  | { type: "radius"; ent: string }
  | { type: "diameter"; ent: string }
  | { type: "angle"; l1: string; l2: string }
  | { type: "ordinate"; axis: "x" | "y"; origin: string; pt: string });
export const GDT_SYMBOLS = ["straightness", "flatness", "circularity", "cylindricity", "profile_line", "profile_surface", "parallelism",
  "perpendicularity", "angularity", "position", "concentricity", "symmetry", "circular_runout", "total_runout"] as const;
export type GdtSymbol = typeof GDT_SYMBOLS[number];
export const GDT_NEEDS_DATUM = new Set<GdtSymbol>(["parallelism", "perpendicularity", "angularity", "concentricity", "symmetry", "circular_runout", "total_runout"]);
export type Anno =
  | { id: string; type: "text"; pos: P2; text: string; size: number }
  | { id: string; type: "leader"; pts: P2[]; text: string }
  | { id: string; type: "balloon"; tip: P2; pos: P2; text: string }
  | { id: string; type: "surface"; pos: P2; tip?: P2; text: string; removal: "any" | "required" | "prohibited" }
  | { id: string; type: "gdt"; pos: P2; tip?: P2; symbol: GdtSymbol; tol: string; dia: boolean; mod: "" | "M" | "L"; datums: string[] }
  | { id: string; type: "datum"; pos: P2; tip: P2; letter: string }
  | { id: string; type: "centermark"; ent: string }
  | { id: string; type: "hatch"; loops: string[][]; spacing: number };
export interface SheetSpec { size: string; orientation: "landscape" | "portrait"; scale: [number, number]; projection: "first" | "third"; units: "mm" | "in"; origin: P2 }
export interface Title { title: string; drawing_no: string; material: string; company: string; drawn_by: string; checked_by: string; date: string; tolerance: string }
export interface RevRow { rev: string; change: string; date: string; by: string }
export interface DraftDoc {
  schema: number; sheet: SheetSpec; title: Title;
  geom: { points: DPoint[]; entities: DEnt[]; constraints: [] };
  dims: Dim[]; annos: Anno[]; notes: string[]; revisions: RevRow[];
}

export const SHEETS: Record<string, [number, number]> = {
  A4: [297, 210], A3: [420, 297], A2: [594, 420], A1: [841, 594], A0: [1189, 841],
  "ANSI A": [279.4, 215.9], "ANSI B": [431.8, 279.4], "ANSI C": [558.8, 431.8], "ANSI D": [863.6, 558.8], "ANSI E": [1117.6, 863.6],
};
export const SCALES: [number, number][] = [[50, 1], [20, 1], [10, 1], [5, 1], [2, 1], [1, 1], [1, 2], [1, 5], [1, 10], [1, 20], [1, 50], [1, 100], [1, 200], [1, 500], [1, 1000]];

const TAU = Math.PI * 2;
const dist = (a: P2, b: P2) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const sub = (a: P2, b: P2): P2 => [a[0] - b[0], a[1] - b[1]];
const dot = (a: P2, b: P2) => a[0] * b[0] + a[1] * b[1];

export function sheetWH(s: SheetSpec): [number, number] {
  const [w, h] = SHEETS[s.size] ?? [420, 297];
  return s.orientation === "portrait" ? [h, w] : [w, h];
}
/** Paper millimetres per drawing unit. */
export const kOf = (s: SheetSpec) => (s.units === "in" ? 25.4 : 1) * s.scale[0] / s.scale[1];
export const decimalsOf = (s: SheetSpec) => (s.units === "in" ? 3 : 2);
export function toPaper(s: SheetSpec, p: P2): P2 { const k = kOf(s); return [s.origin[0] + p[0] * k, s.origin[1] - p[1] * k]; }
export function toModel(s: SheetSpec, q: P2): P2 { const k = kOf(s); return [(q[0] - s.origin[0]) / k, (s.origin[1] - q[1]) / k]; }

// ------------------------------------------------------------------ lookups
export function pointMap(doc: DraftDoc): Map<string, P2> { return new Map(doc.geom.points.map(p => [p.id, [p.x, p.y] as P2])); }
export const entOf = (doc: DraftDoc, id: string) => doc.geom.entities.find(e => e.id === id);
export function sketchOf(doc: DraftDoc): Sketch { return { points: doc.geom.points, entities: doc.geom.entities, constraints: [] }; }
export function circleOf(doc: DraftDoc, id: string, P = pointMap(doc)): { c: P2; r: number; e: DEnt } | null {
  const e = entOf(doc, id);
  if (!e || e.type === "line") return null;
  const c = P.get(e.c); if (!c) return null;
  if (e.type === "circle") return { c, r: e.r, e };
  const p1 = P.get(e.p1); if (!p1) return null;
  return { c, r: dist(c, p1), e };
}
export function lineOf(doc: DraftDoc, id: string, P = pointMap(doc)): [P2, P2] | null {
  const e = entOf(doc, id);
  if (!e || e.type !== "line") return null;
  const a = P.get(e.p1), b = P.get(e.p2);
  return a && b ? [a, b] : null;
}
export const usedPoints = (e: SEntity): string[] => (e.type === "line" ? [e.p1, e.p2] : e.type === "circle" ? [e.c] : [e.c, e.p1, e.p2]);

/**
 * Put a sketch tool's result back into the document: entities a tool created get a layer (the layer of the entity they
 * came from, else `fallback`; construction helpers such as a slot axis go on the construction layer), relations the
 * tool added are dropped (constraints are optional in drafting), and dimensions / annotations whose geometry is gone
 * are removed.
 */
export function applySketch(doc: DraftDoc, s: Sketch, fallback: Layer): DraftDoc {
  const before = new Map(doc.geom.entities.map(e => [e.id, e.layer]));
  const entities = s.entities.map(e => {
    const { construction, ...rest } = e as SEntity & { layer?: Layer };
    const layer: Layer = (rest as { layer?: Layer }).layer ?? before.get(e.id) ?? (construction ? "construction" : fallback);
    return { ...rest, layer } as DEnt;
  });
  return prune({ ...doc, geom: { points: s.points.map(p => ({ id: p.id, x: p.x, y: p.y })), entities, constraints: [] } });
}

/** Drop dimensions and annotations whose referenced geometry no longer exists. */
export function prune(doc: DraftDoc): DraftDoc {
  const P = new Set(doc.geom.points.map(p => p.id)), E = new Map(doc.geom.entities.map(e => [e.id, e]));
  const isLine = (id: string) => E.get(id)?.type === "line", isRound = (id: string) => !!E.get(id) && E.get(id)!.type !== "line";
  const dims = doc.dims.filter(d => d.type === "linear" ? P.has(d.a) && P.has(d.b) : d.type === "angle" ? isLine(d.l1) && isLine(d.l2)
    : d.type === "ordinate" ? P.has(d.origin) && P.has(d.pt) : isRound(d.ent));
  const annos = doc.annos.filter(a => a.type === "centermark" ? isRound(a.ent) : a.type === "hatch" ? a.loops.every(l => l.every(id => E.has(id))) : true);
  return dims.length === doc.dims.length && annos.length === doc.annos.length ? doc : { ...doc, dims, annos };
}

// ------------------------------------------------------------------ values
export function fmt(v: number, decimals = 2): string {
  const s = (Math.round((v + 0) * 10 ** decimals) / 10 ** decimals).toFixed(decimals).replace(/0+$/, "").replace(/\.$/, "");
  return s === "-0" || s === "" ? "0" : s;
}
export function fmtDev(v: number, decimals: number): string { const s = fmt(v, Math.max(decimals, 3)); return s === "0" || s.startsWith("-") ? s : `+${s}`; }

export function angleSector(doc: DraftDoc, d: Extract<Dim, { type: "angle" }>, P = pointMap(doc)): { x: P2; a0: number; sweep: number; r: number } | null {
  const l1 = lineOf(doc, d.l1, P), l2 = lineOf(doc, d.l2, P);
  if (!l1 || !l2) return null;
  const d1 = sub(l1[1], l1[0]), d2 = sub(l2[1], l2[0]);
  const den = d1[0] * d2[1] - d1[1] * d2[0];
  if (Math.abs(den) < 1e-12 * (Math.hypot(...d1) * Math.hypot(...d2) || 1)) return null;
  const t = ((l2[0][0] - l1[0][0]) * d2[1] - (l2[0][1] - l1[0][1]) * d2[0]) / den;
  const x: P2 = [l1[0][0] + d1[0] * t, l1[0][1] + d1[1] * t];
  const deg = (v: P2) => ((Math.atan2(v[1], v[0]) * 180 / Math.PI) % 360 + 360) % 360;
  const aq = deg(sub(d.pos, x));
  let best: { x: P2; a0: number; sweep: number; r: number } | null = null;
  for (const s1 of [1, -1]) for (const s2 of [1, -1]) {
    const a = deg([s1 * d1[0], s1 * d1[1]]), b = deg([s2 * d2[0], s2 * d2[1]]);
    const ab = ((b - a) % 360 + 360) % 360;
    const [lo, sw] = ab <= 180 ? [a, ab] : [b, ((a - b) % 360 + 360) % 360];
    if (sw < 1e-9) continue;
    if (((aq - lo) % 360 + 360) % 360 <= sw + 1e-9 && (!best || sw < best.sweep)) best = { x, a0: lo, sweep: sw, r: dist(d.pos, x) };
  }
  return best;
}

/** A dimension's value measured from the geometry; null when what it references is gone. */
export function measure(doc: DraftDoc, d: Dim, P = pointMap(doc)): number | null {
  if (d.type === "linear") {
    const a = P.get(d.a), b = P.get(d.b); if (!a || !b) return null;
    return d.orient === "h" ? Math.abs(b[0] - a[0]) : d.orient === "v" ? Math.abs(b[1] - a[1]) : dist(a, b);
  }
  if (d.type === "radius" || d.type === "diameter") { const c = circleOf(doc, d.ent, P); return c ? (d.type === "radius" ? c.r : 2 * c.r) : null; }
  if (d.type === "angle") { const s = angleSector(doc, d, P); return s ? s.sweep : null; }
  const o = P.get(d.origin), p = P.get(d.pt); if (!o || !p) return null;
  return d.axis === "x" ? p[0] - o[0] : p[1] - o[1];
}

/** Printed value: prefix, Ø / R, measured value, tolerance (± / deviations / limits / fit), suffix. Mirrors the server. */
export function dimText(doc: DraftDoc, d: Dim, value: number): { main: string; stack: string[] } {
  const dec = decimalsOf(doc.sheet);
  let main = "", stack: string[] = [];
  const t = d.tol;
  if (d.type === "angle") {
    main = `${fmt(value, 1)}°`;
    if (t?.kind === "sym") main += ` ±${fmt(t.up, 2)}°`;
    else if (t && (t.kind === "dev" || t.kind === "limits")) stack = [`${fmtDev(t.up, 2)}°`, `${fmtDev(t.lo, 2)}°`];
  } else {
    const v = d.type === "ordinate" ? value : Math.abs(value);
    main = fmt(v, dec);
    if (t?.kind === "sym") main = `${main} ±${fmt(Math.abs(t.up), Math.max(dec, 3))}`;
    else if (t?.kind === "dev") stack = [fmtDev(t.up, dec), fmtDev(t.lo, dec)];
    else if (t?.kind === "limits") { const dd = Math.max(dec, 3); stack = [fmt(v + t.up, dd), fmt(v + t.lo, dd)]; main = ""; }
    else if (t?.kind === "fit") main = `${main} ${t.fit}`;
    const sym = d.type === "diameter" ? "Ø" : d.type === "radius" ? "R" : "";
    if (main) main = sym + main; else if (sym) stack = stack.map(s => sym + s);
  }
  if (d.prefix) main = d.prefix.endsWith(" ") ? d.prefix + main : `${d.prefix} ${main}`.trim();
  if (d.suffix) main = `${main} ${d.suffix}`.trim();
  return { main, stack };
}

// ------------------------------------------------------------------ snapping
export type SnapKind = "endpoint" | "midpoint" | "center" | "intersection" | "perpendicular" | "grid" | "nearest";
export interface Snap { p: P2; kind: SnapKind; pt?: string; ent?: string }
export interface SnapOpts { endpoint: boolean; midpoint: boolean; center: boolean; intersection: boolean; perpendicular: boolean; grid: boolean; nearest: boolean; gridStep: number }
export const DEFAULT_SNAPS: SnapOpts = { endpoint: true, midpoint: true, center: true, intersection: true, perpendicular: true, grid: false, nearest: false, gridStep: 5 };

/**
 * The snapped point for a cursor at `p` (drawing units). `tol` is the capture radius in drawing units. Priority:
 * endpoint / centre > intersection > midpoint > perpendicular (from `from`) > nearest > grid.
 */
export function findSnap(doc: DraftDoc, p: P2, tol: number, o: SnapOpts, from?: P2 | null, skip?: Set<string>): Snap | null {
  const s = sketchOf(doc); const P = pointMap(doc);
  const ents = doc.geom.entities.filter(e => !skip?.has(e.id));
  let best: Snap | null = null, bestD = tol, bestRank = 99;
  const offer = (q: P2, kind: SnapKind, rank: number, extra: Partial<Snap> = {}) => {
    const d = dist(q, p);
    if (d <= tol && (rank < bestRank || (rank === bestRank && d < bestD))) { best = { p: q, kind, ...extra }; bestD = d; bestRank = rank; }
  };
  for (const e of ents) {
    if (o.endpoint && e.type !== "circle") for (const id of [e.p1, e.p2]) { const q = P.get(id); if (q) offer(q, "endpoint", 0, { pt: id }); }
    if (o.center && e.type !== "line") { const q = P.get(e.c); if (q) offer(q, "center", 0, { pt: e.c, ent: e.id }); }
    if (o.midpoint && e.type === "line") { const a = P.get(e.p1)!, b = P.get(e.p2)!; offer([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], "midpoint", 2, { ent: e.id }); }
  }
  if (o.intersection) {
    const near = ents.filter(e => distTo(geomOf(s, e), p) <= tol * 2);
    for (let i = 0; i < near.length; i++) for (let j = i + 1; j < near.length; j++)
      for (const q of intersect(geomOf(s, near[i]!), geomOf(s, near[j]!))) offer(q, "intersection", 1);
  }
  if (o.perpendicular && from) for (const e of ents) {
    const g = geomOf(s, e);
    let q: P2 | null = null;
    if (g.kind === "line") { const d = sub(g.b, g.a); const t = dot(sub(from, g.a), d) / (dot(d, d) || 1); if (t >= 0 && t <= 1) q = [g.a[0] + d[0] * t, g.a[1] + d[1] * t]; }
    else { const v = sub(from, g.c); const l = Math.hypot(...v); if (l > 1e-9) q = [g.c[0] + v[0] / l * g.r, g.c[1] + v[1] / l * g.r]; }
    if (q && dist(q, from) > 1e-9) offer(q, "perpendicular", 3, { ent: e.id });
  }
  if (o.nearest) for (const e of ents) {
    const g = geomOf(s, e);
    if (distTo(g, p) > tol) continue;
    let q: P2;
    if (g.kind === "line") { const d = sub(g.b, g.a); const t = Math.max(0, Math.min(1, dot(sub(p, g.a), d) / (dot(d, d) || 1))); q = [g.a[0] + d[0] * t, g.a[1] + d[1] * t]; }
    else { const v = sub(p, g.c); const l = Math.hypot(...v) || 1; q = [g.c[0] + v[0] / l * g.r, g.c[1] + v[1] / l * g.r]; }
    offer(q, "nearest", 4, { ent: e.id });
  }
  if (!best && o.grid && o.gridStep > 0) {
    const g = o.gridStep;
    return { p: [Math.round(p[0] / g) * g, Math.round(p[1] / g) * g], kind: "grid" };
  }
  return best;
}

/** Ortho (0/90°) or polar tracking (multiples of `inc` degrees) from `from`, keeping the cursor's distance. */
export function track(from: P2, p: P2, mode: "ortho" | "polar", inc = 15): P2 {
  const v = sub(p, from); const r = Math.hypot(...v);
  if (r < 1e-12) return p;
  const step = mode === "ortho" ? 90 : inc;
  const a = Math.round(Math.atan2(v[1], v[0]) * 180 / Math.PI / step) * step * Math.PI / 180;
  // keep the projected length so the point stays under the cursor along the tracked direction
  const L = mode === "ortho" ? Math.abs(dot(v, [Math.cos(a), Math.sin(a)])) : r;
  return [from[0] + L * Math.cos(a), from[1] + L * Math.sin(a)];
}

/**
 * Typed point input: "x,y" absolute, "@dx,dy" relative to `last`, "@r<a" polar relative, or a single distance along the
 * cursor direction from `last` (direct distance entry). Returns null when the text isn't a point.
 */
export function parsePointInput(text: string, last: P2 | null, cursor: P2 | null): P2 | null {
  const t = text.trim().replace(/\s+/g, "");
  const num = "(-?\\d+(?:\\.\\d+)?)";
  let m = t.match(new RegExp(`^@${num}<${num}$`));
  if (m && last) { const r = +m[1]!, a = +m[2]! * Math.PI / 180; return [last[0] + r * Math.cos(a), last[1] + r * Math.sin(a)]; }
  m = t.match(new RegExp(`^(@?)${num}[,;]${num}$`));
  if (m) { const x = +m[2]!, y = +m[3]!; return m[1] && last ? [last[0] + x, last[1] + y] : m[1] ? null : [x, y]; }
  m = t.match(new RegExp(`^${num}$`));
  if (m && last) {
    const L = +m[1]!; const dir = cursor ? sub(cursor, last) : [1, 0] as P2; const l = Math.hypot(...dir);
    const u: P2 = l > 1e-12 ? [dir[0] / l, dir[1] / l] : [1, 0];
    return [last[0] + u[0] * L, last[1] + u[1] * L];
  }
  return null;
}

// ------------------------------------------------------------------ picking
export function pickEntity(doc: DraftDoc, p: P2, tol: number, filter?: (e: DEnt) => boolean): DEnt | null {
  const s = sketchOf(doc);
  let best: DEnt | null = null, bd = tol;
  for (const e of doc.geom.entities) {
    if (filter && !filter(e)) continue;
    const d = distTo(geomOf(s, e), p);
    if (d <= bd) { bd = d; best = e; }
  }
  return best;
}
/** The end point of a line or arc nearest p (corner picking for fillet / chamfer). */
export function nearestPoint(doc: DraftDoc, p: P2, tol: number): string | null {
  let best: string | null = null, bd = tol;
  for (const q of doc.geom.points) { const d = Math.hypot(q.x - p[0], q.y - p[1]); if (d <= bd) { bd = d; best = q.id; } }
  return best;
}

// ------------------------------------------------------------------ editing
/** Register a point at p (reusing an existing point there) and return its id. */
export function addPoint(doc: DraftDoc, p: P2, reuse = true): string {
  if (reuse) { const q = doc.geom.points.find(x => Math.abs(x.x - p[0]) < 1e-9 && Math.abs(x.y - p[1]) < 1e-9); if (q) return q.id; }
  const id = uid("p"); doc.geom.points.push({ id, x: p[0], y: p[1] }); return id;
}
export function cloneDoc(d: DraftDoc): DraftDoc { return JSON.parse(JSON.stringify(d)) as DraftDoc; }

/** Chamfer the corner where exactly two lines meet: both lines are cut back by `d` and joined by a new line. */
export function chamferCorner(doc0: DraftDoc, ptId: string, d: number): DraftDoc {
  if (!(d > 0)) throw new Error("Chamfer distance must be positive");
  const doc = cloneDoc(doc0); const P = pointMap(doc);
  const users = doc.geom.entities.filter(e => usedPoints(e).includes(ptId));
  const lines = users.filter((e): e is Extract<DEnt, { type: "line" }> => e.type === "line");
  if (users.length !== 2 || lines.length !== 2) throw new Error("Pick a corner where exactly two lines meet");
  const C = P.get(ptId)!;
  const cut = lines.map(l => {
    const far = P.get(l.p1 === ptId ? l.p2 : l.p1)!; const L = dist(far, C);
    if (d >= L - 1e-9) throw new Error("The chamfer is longer than one of the lines");
    return [C[0] + (far[0] - C[0]) / L * d, C[1] + (far[1] - C[1]) / L * d] as P2;
  });
  const ids = cut.map(p => { const id = uid("p"); doc.geom.points.push({ id, x: p[0], y: p[1] }); return id; });
  lines.forEach((l, i) => { if (l.p1 === ptId) l.p1 = ids[i]!; else l.p2 = ids[i]!; });
  doc.geom.entities.push({ id: uid("e"), type: "line", p1: ids[0]!, p2: ids[1]!, layer: lines[0]!.layer });
  doc.geom.points = doc.geom.points.filter(p => p.id !== ptId || doc.geom.entities.some(e => usedPoints(e).includes(ptId)));
  return prune(doc);
}

export type Xform = (p: P2) => P2;
export const moveBy = (dx: number, dy: number): Xform => p => [p[0] + dx, p[1] + dy];
export const rotateAbout = (c: P2, deg: number): Xform => { const a = deg * Math.PI / 180, cs = Math.cos(a), sn = Math.sin(a); return p => [c[0] + (p[0] - c[0]) * cs - (p[1] - c[1]) * sn, c[1] + (p[0] - c[0]) * sn + (p[1] - c[1]) * cs]; };
export const scaleAbout = (c: P2, f: number): Xform => p => [c[0] + (p[0] - c[0]) * f, c[1] + (p[1] - c[1]) * f];

/**
 * Move / rotate / scale (or copy with `copy`) the selected entities and annotations. Points shared with entities that
 * are not selected are split first, so the rest of the drawing stays where it is. Circle radii scale with `scale`.
 * Dimensions on the selected geometry follow it (they are associative); their text positions move too.
 */
export function transformSelection(doc0: DraftDoc, sel: Set<string>, f: Xform, opts: { copy?: boolean; scale?: number } = {}): DraftDoc {
  const doc = cloneDoc(doc0); const k = opts.scale ?? 1;
  const ents = doc.geom.entities.filter(e => sel.has(e.id));
  const P = new Map(doc.geom.points.map(p => [p.id, p]));
  const map = new Map<string, string>();
  const shared = (id: string) => doc.geom.entities.some(e => !sel.has(e.id) && usedPoints(e).includes(id));
  const target = (id: string) => {
    const got = map.get(id); if (got) return got;
    const src = P.get(id)!;
    let nid = id;
    if (opts.copy || shared(id)) { nid = uid("p"); doc.geom.points.push({ id: nid, x: src.x, y: src.y }); }
    map.set(id, nid); return nid;
  };
  const outEnts: DEnt[] = [];
  for (const e of ents) {
    const ne = opts.copy ? { ...e, id: uid("e") } : e;
    if (ne.type === "line") { ne.p1 = target(ne.p1); ne.p2 = target(ne.p2); }
    else if (ne.type === "circle") { ne.c = target(ne.c); ne.r = ne.r * Math.abs(k); }
    else { ne.c = target(ne.c); ne.p1 = target(ne.p1); ne.p2 = target(ne.p2); }
    if (opts.copy) outEnts.push(ne);
  }
  if (opts.copy) doc.geom.entities.push(...outEnts);
  const P2m = new Map(doc.geom.points.map(p => [p.id, p]));
  for (const nid of new Set(map.values())) { const q = P2m.get(nid)!; const [x, y] = f([q.x, q.y]); q.x = x; q.y = y; }
  // annotations and dimension text positions
  const entMap = new Map<string, string>();
  if (opts.copy) ents.forEach((e, i) => entMap.set(e.id, outEnts[i]!.id));
  const moveAnno = (a: Anno): Anno => {
    const b = JSON.parse(JSON.stringify(a)) as Anno & { pos?: P2; tip?: P2; pts?: P2[] };
    if (b.pos) b.pos = f(b.pos); if (b.tip) b.tip = f(b.tip); if (b.pts) b.pts = b.pts.map(f);
    return b;
  };
  const newAnnos: Anno[] = [], newDims: Dim[] = [];
  doc.annos = doc.annos.map(a => {
    const onSel = a.type === "centermark" ? sel.has(a.ent) : a.type === "hatch" ? a.loops.flat().every(id => sel.has(id)) : sel.has(a.id);
    if (!onSel) return a;
    if (opts.copy) {
      const c = moveAnno(a); c.id = uid("a");
      if (c.type === "centermark") c.ent = entMap.get(c.ent) ?? c.ent;
      if (c.type === "hatch") c.loops = c.loops.map(l => l.map(id => entMap.get(id) ?? id));
      newAnnos.push(c); return a;
    }
    return moveAnno(a);
  });
  const ptsOfDim = (d: Dim) => d.type === "linear" ? [d.a, d.b] : d.type === "ordinate" ? [d.pt] : [];
  const entsOfDim = (d: Dim) => d.type === "radius" || d.type === "diameter" ? [d.ent] : d.type === "angle" ? [d.l1, d.l2] : [];
  doc.dims = doc.dims.map(d => {
    const pts = ptsOfDim(d), es = entsOfDim(d);
    const follows = sel.has(d.id) || (es.length > 0 && es.every(id => sel.has(id))) || (pts.length > 0 && pts.every(id => map.has(id)));
    if (!follows) return d;
    if (opts.copy) {
      const c = JSON.parse(JSON.stringify(d)) as Dim; c.id = uid("d"); c.pos = f(c.pos);
      if (c.type === "linear") { c.a = map.get(c.a) ?? c.a; c.b = map.get(c.b) ?? c.b; }
      else if (c.type === "ordinate") c.pt = map.get(c.pt) ?? c.pt;
      else if (c.type === "angle") { c.l1 = entMap.get(c.l1) ?? c.l1; c.l2 = entMap.get(c.l2) ?? c.l2; }
      else c.ent = entMap.get(c.ent) ?? c.ent;
      newDims.push(c); return d;
    }
    return { ...d, pos: f(d.pos) };
  });
  doc.annos.push(...newAnnos); doc.dims.push(...newDims);
  return doc;
}

// ------------------------------------------------------------------ hatch boundaries
function polyOf(doc: DraftDoc, ids: string[]): P2[] {
  const s = sketchOf(doc); const out: P2[] = [];
  const P = pointMap(doc);
  if (ids.length === 1) { const e = entOf(doc, ids[0]!); if (e?.type === "circle") { const c = P.get(e.c)!; for (let i = 0; i < 64; i++) out.push([c[0] + e.r * Math.cos(TAU * i / 64), c[1] + e.r * Math.sin(TAU * i / 64)]); return out; } }
  const segs = ids.map(id => entOf(doc, id)).filter((e): e is Extract<DEnt, { type: "line" | "arc" }> => !!e && e.type !== "circle");
  for (const ch of chainsOf(s, segs)) for (const { e, rev } of ch.items) {
    const g = geomOf(s, e);
    const n = g.kind === "arc" ? 24 : 1;
    for (let i = 0; i < n; i++) {
      const u = rev ? 1 - i / n : i / n;
      out.push(g.kind === "line" ? [g.a[0] + (g.b[0] - g.a[0]) * u, g.a[1] + (g.b[1] - g.a[1]) * u]
        : g.kind === "arc" ? [g.c[0] + g.r * Math.cos(g.a0 + g.sweep * u), g.c[1] + g.r * Math.sin(g.a0 + g.sweep * u)] : g.c);
    }
  }
  return out;
}
export function polyArea(pts: P2[]): number { let a = 0; for (let i = 0; i < pts.length; i++) { const p = pts[i]!, q = pts[(i + 1) % pts.length]!; a += p[0] * q[1] - q[0] * p[1]; } return Math.abs(a) / 2; }
export function inPoly(p: P2, pts: P2[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[i]!, b = pts[j]!;
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

/** Closed boundaries (entity id lists) of the printed geometry: closed chains of lines/arcs, and circles. */
export function closedLoops(doc: DraftDoc): { ids: string[]; poly: P2[]; area: number }[] {
  const s = sketchOf(doc);
  const usable = doc.geom.entities.filter(e => e.layer === "visible" || e.layer === "hidden");
  const out: { ids: string[]; poly: P2[]; area: number }[] = [];
  for (const e of usable) if (e.type === "circle") { const poly = polyOf(doc, [e.id]); out.push({ ids: [e.id], poly, area: Math.PI * e.r * e.r }); }
  const segs = usable.filter((e): e is Extract<DEnt, { type: "line" | "arc" }> => e.type !== "circle");
  for (const ch of chainsOf(s, segs)) if (ch.closed) { const ids = ch.items.map(i => i.e.id); const poly = polyOf(doc, ids); out.push({ ids, poly, area: polyArea(poly) }); }
  return out;
}

/** Hatch region at p: the smallest closed boundary around p, plus the boundaries directly inside it (islands). */
export function hatchRegionAt(doc: DraftDoc, p: P2): string[][] | null {
  const loops = closedLoops(doc);
  const around = loops.filter(l => inPoly(p, l.poly)).sort((a, b) => a.area - b.area);
  const outer = around[0]; if (!outer) return null;
  const inside = loops.filter(l => l !== outer && l.area < outer.area && l.poly.every(q => inPoly(q, outer.poly)));
  const islands = inside.filter(l => !inside.some(m => m !== l && m.area > l.area && l.poly.every(q => inPoly(q, m.poly))));
  if (islands.some(l => inPoly(p, l.poly))) return null;
  return [outer.ids, ...islands.map(l => l.ids)];
}

type Piece = { ent: string; u0: number; u1: number; full: boolean; poly: P2[] };

/**
 * Hatch at p for any arrangement of lines, arcs and circles (T-junctions and crossings included): the entities are cut
 * at their intersections, the faces of that planar graph are traced, and the smallest face around p is taken. Entities
 * that only partly bound it are split at the corners (same look, exact pieces), so the hatch can reference whole
 * entities and stays associative. Closed boundaries inside the face become islands. Returns null when p is not enclosed.
 */
export function hatchAt(doc0: DraftDoc, p: P2): { doc: DraftDoc; loops: string[][] } | null {
  const s = sketchOf(doc0);
  const ents = doc0.geom.entities.filter(e => e.layer === "visible" || e.layer === "hidden");
  const G = new Map(ents.map(e => [e.id, geomOf(s, e)]));
  const pieces: Piece[] = [];
  const freeCircles: string[] = [];
  const at = (g: ReturnType<typeof geomOf>, u: number): P2 => g.kind === "line" ? [g.a[0] + (g.b[0] - g.a[0]) * u, g.a[1] + (g.b[1] - g.a[1]) * u]
    : [g.c[0] + g.r * Math.cos((g.kind === "arc" ? g.a0 : 0) + u), g.c[1] + g.r * Math.sin((g.kind === "arc" ? g.a0 : 0) + u)];
  const tess = (g: ReturnType<typeof geomOf>, u0: number, u1: number): P2[] => {
    const n = g.kind === "line" ? 1 : Math.max(4, Math.ceil(Math.abs(u1 - u0) / (Math.PI / 36)));
    return Array.from({ length: n + 1 }, (_, i) => at(g, u0 + (u1 - u0) * i / n));
  };
  for (const e of ents) {
    const g = G.get(e.id)!;
    const span = g.kind === "line" ? 1 : g.kind === "arc" ? g.sweep : TAU;
    const scale = g.kind === "line" ? dist(g.a, g.b) : g.r;
    const du = 1e-7 / (scale || 1);
    const us: number[] = [];
    for (const o of ents) if (o.id !== e.id) for (const q of intersect(g, G.get(o.id)!)) {
      let u: number;
      if (g.kind === "line") { const d = sub(g.b, g.a); u = dot(sub(q, g.a), d) / (dot(d, d) || 1); }
      else { u = ((Math.atan2(q[1] - g.c[1], q[0] - g.c[0]) - (g.kind === "arc" ? g.a0 : 0)) % TAU + TAU) % TAU; if (g.kind === "arc" && u > TAU - du) u = 0; }
      if (g.kind !== "circle" && (u <= du || u >= span - du)) continue;
      if (!us.some(x => Math.abs(x - u) < du)) us.push(u);
    }
    us.sort((a, b) => a - b);
    if (g.kind === "circle") {
      if (us.length === 0) { freeCircles.push(e.id); continue; } // a free circle is a loop on its own
      for (let i = 0; i < us.length; i++) { const u0 = us[i]!, u1 = i + 1 < us.length ? us[i + 1]! : us[0]! + TAU; pieces.push({ ent: e.id, u0, u1, full: false, poly: tess(g, u0, u1) }); }
    } else {
      const cuts = [0, ...us, span];
      for (let i = 0; i + 1 < cuts.length; i++) pieces.push({ ent: e.id, u0: cuts[i]!, u1: cuts[i + 1]!, full: cuts.length === 2, poly: tess(g, cuts[i]!, cuts[i + 1]!) });
    }
  }
  // half-edges and faces (face on the left of each half-edge)
  const key = (q: P2) => `${Math.round(q[0] * 1e5)}:${Math.round(q[1] * 1e5)}`;
  type HE = { piece: number; rev: boolean; from: string; to: string; ang: number; poly: P2[] };
  const hes: HE[] = [];
  pieces.forEach((pc, i) => {
    const f = pc.poly, r = [...pc.poly].reverse();
    hes.push({ piece: i, rev: false, from: key(f[0]!), to: key(f[f.length - 1]!), ang: Math.atan2(f[1]![1] - f[0]![1], f[1]![0] - f[0]![0]), poly: f });
    hes.push({ piece: i, rev: true, from: key(r[0]!), to: key(r[r.length - 1]!), ang: Math.atan2(r[1]![1] - r[0]![1], r[1]![0] - r[0]![0]), poly: r });
  });
  const out = new Map<string, number[]>();
  hes.forEach((h, i) => { const l = out.get(h.from) ?? []; l.push(i); out.set(h.from, l); });
  for (const l of out.values()) l.sort((a, b) => hes[a]!.ang - hes[b]!.ang);
  const used = new Set<number>();
  let best: { hs: number[]; poly: P2[]; area: number; circle?: string } | null = null;
  for (let start = 0; start < hes.length; start++) {
    if (used.has(start)) continue;
    const hs: number[] = []; let cur = start; let guard = 0;
    while (!used.has(cur) && guard++ < 20000) {
      used.add(cur); hs.push(cur);
      const h = hes[cur]!; const twin = cur ^ 1; const ring = out.get(h.to) ?? [];
      const ti = ring.indexOf(twin); if (ti < 0) break;
      cur = ring[(ti - 1 + ring.length) % ring.length]!;
    }
    if (cur !== start) continue;
    const poly = hs.flatMap(i => hes[i]!.poly.slice(0, -1));
    let a2 = 0; for (let i = 0; i < poly.length; i++) { const a = poly[i]!, b = poly[(i + 1) % poly.length]!; a2 += a[0] * b[1] - b[0] * a[1]; }
    if (a2 <= 1e-12 || !inPoly(p, poly)) continue;
    if (!best || a2 / 2 < best.area) best = { hs, poly, area: a2 / 2 };
  }
  for (const cid of freeCircles) {
    const g = G.get(cid)!; if (g.kind !== "circle" || dist(p, g.c) >= g.r) continue;
    const area = Math.PI * g.r * g.r;
    if (!best || area < best.area) best = { hs: [], poly: tess(g, 0, TAU).slice(0, -1), area, circle: cid };
  }
  if (!best) return null;
  // split partly-used entities at the corners of the face, so the boundary is made of whole entities
  const doc = cloneDoc(doc0);
  const usedPieces = best.hs.map(i => pieces[hes[i]!.piece]!);
  const cutsBy = new Map<string, number[]>();
  for (const pc of usedPieces) if (!pc.full) { const l = cutsBy.get(pc.ent) ?? []; l.push(pc.u0, pc.u1); cutsBy.set(pc.ent, l); }
  const pieceIds = new Map<Piece, string>();
  for (const pc of usedPieces) if (pc.full) pieceIds.set(pc, pc.ent);
  for (const [eid, raw] of cutsBy) {
    const e = doc.geom.entities.find(x => x.id === eid)!; const g = G.get(eid)!;
    const span = g.kind === "line" ? 1 : g.kind === "arc" ? g.sweep : TAU;
    const norm = (u: number) => (g.kind === "circle" ? ((u % TAU) + TAU) % TAU : u);
    let cuts = [...new Set(raw.map(u => Math.round(norm(u) * 1e9) / 1e9))].sort((a, b) => a - b);
    const subs: { u0: number; u1: number; id: string }[] = [];
    const ptAt = (u: number) => addPoint(doc, at(g, u));
    const idx = doc.geom.entities.indexOf(e);
    const made: DEnt[] = [];
    if (g.kind === "circle") {
      for (let i = 0; i < cuts.length; i++) { const u0 = cuts[i]!, u1 = i + 1 < cuts.length ? cuts[i + 1]! : cuts[0]! + TAU; const id = i === 0 ? e.id : uid("e");
        made.push({ id, type: "arc", c: (e as { c: string }).c, p1: ptAt(u0), p2: ptAt(u1), layer: e.layer }); subs.push({ u0, u1, id }); }
    } else {
      cuts = [0, ...cuts.filter(u => u > 1e-9 && u < span - 1e-9), span];
      for (let i = 0; i + 1 < cuts.length; i++) {
        const u0 = cuts[i]!, u1 = cuts[i + 1]!; const id = i === 0 ? e.id : uid("e");
        const p1 = i === 0 ? (e as { p1: string }).p1 : ptAt(u0), p2 = i + 2 === cuts.length ? (e as { p2: string }).p2 : ptAt(u1);
        made.push(e.type === "line" ? { id, type: "line", p1, p2, layer: e.layer } : { id, type: "arc", c: (e as { c: string }).c, p1, p2, layer: e.layer });
        subs.push({ u0, u1, id });
      }
    }
    doc.geom.entities.splice(idx, 1, ...made);
    for (const pc of usedPieces) if (pc.ent === eid) {
      const u0 = norm(pc.u0); const hit = subs.find(sb => Math.abs(sb.u0 - u0) < 1e-6) ?? subs[0]!;
      pieceIds.set(pc, hit.id);
    }
  }
  const outer = best.circle ? [best.circle] : [...new Set(usedPieces.map(pc => pieceIds.get(pc)!))];
  const facePoly = best.poly;
  const islands = closedLoops(doc0).filter(l => l.area < best!.area && l.poly.every(q => inPoly(q, facePoly)) && !l.ids.some(i => outer.includes(i)));
  const top = islands.filter(l => !islands.some(m => m !== l && m.area > l.area && l.poly.every(q => inPoly(q, m.poly))));
  if (top.some(l => inPoly(p, l.poly))) return null;
  return { doc, loops: [outer, ...top.map(l => l.ids)] };
}

export { clone, dist, uid };
