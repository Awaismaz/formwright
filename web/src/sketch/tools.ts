/**
 * Sketch editing tools as pure functions on a `Sketch` (no React): trim, extend, offset, slot, polygon, corner fillet,
 * mirror and the angle dimension. Each takes a sketch and returns a new one (the input is never mutated) or throws an
 * `Error` whose message is shown to the user. Units: mm, angles in radians unless named `deg`.
 */
import { chainsOf, clone, uid, type SConstraint, type SEntity, type Sketch, type SPoint } from "./model";

export type P2 = [number, number];
export type Geom =
  | { kind: "line"; a: P2; b: P2 }
  | { kind: "circle"; c: P2; r: number }
  | { kind: "arc"; c: P2; r: number; a0: number; sweep: number }; // counter-clockwise from angle a0 by sweep ∈ (0, 2π]

type LineE = Extract<SEntity, { type: "line" }>;
type ArcE = Extract<SEntity, { type: "arc" }>;
type NoId<T> = T extends unknown ? Omit<T, "id"> : never;

const TAU = Math.PI * 2;
/** Points closer than this (mm) are the same point. */
export const COINCIDENT = 1e-6;
const normA = (a: number) => ((a % TAU) + TAU) % TAU;
const sub = (a: P2, b: P2): P2 => [a[0] - b[0], a[1] - b[1]];
const add = (a: P2, b: P2): P2 => [a[0] + b[0], a[1] + b[1]];
const mul = (a: P2, k: number): P2 => [a[0] * k, a[1] * k];
const dot = (a: P2, b: P2) => a[0] * b[0] + a[1] * b[1];
const cross = (a: P2, b: P2) => a[0] * b[1] - a[1] * b[0];
const len = (a: P2) => Math.hypot(a[0], a[1]);
const dist = (a: P2, b: P2) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const unit = (a: P2): P2 => { const l = len(a) || 1; return [a[0] / l, a[1] / l]; };
const polar = (c: P2, r: number, a: number): P2 => [c[0] + r * Math.cos(a), c[1] + r * Math.sin(a)];

export const ptOf = (s: Sketch, id: string): P2 => { const p = s.points.find(q => q.id === id); if (!p) throw new Error("Sketch point missing"); return [p.x, p.y]; };
const entOf = (s: Sketch, id: string) => s.entities.find(e => e.id === id);

export function geomOf(s: Sketch, e: SEntity): Geom {
  if (e.type === "line") return { kind: "line", a: ptOf(s, e.p1), b: ptOf(s, e.p2) };
  const c = ptOf(s, e.c);
  if (e.type === "circle") return { kind: "circle", c, r: e.r };
  const p1 = ptOf(s, e.p1), p2 = ptOf(s, e.p2);
  const a0 = Math.atan2(p1[1] - c[1], p1[0] - c[0]);
  const sweep = normA(Math.atan2(p2[1] - c[1], p2[0] - c[0]) - a0) || TAU;
  return { kind: "arc", c, r: dist(p1, c), a0, sweep };
}

// ------------------------------------------------------------------ intersections
/** Intersections of the carriers (infinite line / full circle) of two geometries. */
export function carrierHits(g: Geom, h: Geom): P2[] {
  if (g.kind === "line" && h.kind === "line") {
    const d1 = sub(g.b, g.a), d2 = sub(h.b, h.a); const den = cross(d1, d2);
    if (Math.abs(den) < 1e-12 * (len(d1) * len(d2) || 1)) return [];
    return [add(g.a, mul(d1, cross(sub(h.a, g.a), d2) / den))];
  }
  if (g.kind === "line") return lineCircle(g.a, g.b, (h as { c: P2 }).c, (h as { r: number }).r);
  if (h.kind === "line") return lineCircle(h.a, h.b, g.c, g.r);
  return circleCircle(g.c, g.r, h.c, h.r);
}

function lineCircle(a: P2, b: P2, c: P2, r: number): P2[] {
  const d = sub(b, a), f = sub(a, c);
  const A = dot(d, d), B = 2 * dot(f, d), C = dot(f, f) - r * r;
  if (A < 1e-24) return [];
  const disc = B * B - 4 * A * C;
  const tolDisc = 4 * A * (2 * r * COINCIDENT); // tangent within ~1e-6 mm
  if (disc < -tolDisc) return [];
  if (disc <= tolDisc) return [add(a, mul(d, -B / (2 * A)))];
  const q = Math.sqrt(disc);
  return [add(a, mul(d, (-B - q) / (2 * A))), add(a, mul(d, (-B + q) / (2 * A)))];
}

function circleCircle(c1: P2, r1: number, c2: P2, r2: number): P2[] {
  const d = dist(c1, c2);
  if (d < 1e-12 || d > r1 + r2 + COINCIDENT || d < Math.abs(r1 - r2) - COINCIDENT) return [];
  const a = (r1 * r1 - r2 * r2 + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, r1 * r1 - a * a));
  const u = unit(sub(c2, c1)); const base = add(c1, mul(u, a)); const n: P2 = [-u[1], u[0]];
  return h < COINCIDENT ? [base] : [add(base, mul(n, h)), add(base, mul(n, -h))];
}

/** Position along a geometry: line t ∈ [0,1], circle angle ∈ [0,2π), arc angle from its start ∈ [0, sweep]. */
export function param(g: Geom, p: P2): number {
  if (g.kind === "line") { const d = sub(g.b, g.a); return dot(sub(p, g.a), d) / (dot(d, d) || 1); }
  const ang = Math.atan2(p[1] - g.c[1], p[0] - g.c[0]);
  if (g.kind === "circle") return normA(ang);
  const u = normA(ang - g.a0);
  return u > TAU - COINCIDENT / (g.r || 1) ? 0 : u;
}

/** Whether a point already known to be on the carrier lies on the bounded geometry. */
function within(g: Geom, p: P2, tol = COINCIDENT): boolean {
  if (g.kind === "circle") return true;
  const u = param(g, p);
  if (g.kind === "line") { const l = dist(g.a, g.b) || 1; return u >= -tol / l && u <= 1 + tol / l; }
  return u <= g.sweep + tol / (g.r || 1);
}

/** Intersections of two bounded geometries. */
export function intersect(g: Geom, h: Geom): P2[] {
  return carrierHits(g, h).filter(p => within(g, p) && within(h, p));
}

/** Distance from a point to a bounded geometry (for picking). */
export function distTo(g: Geom, p: P2): number {
  if (g.kind === "line") { const d = sub(g.b, g.a); const t = Math.max(0, Math.min(1, dot(sub(p, g.a), d) / (dot(d, d) || 1))); return dist(add(g.a, mul(d, t)), p); }
  const radial = Math.abs(dist(p, g.c) - g.r);
  if (g.kind === "circle") return radial;
  const u = normA(Math.atan2(p[1] - g.c[1], p[0] - g.c[0]) - g.a0);
  if (u <= g.sweep) return radial;
  return Math.min(dist(p, polar(g.c, g.r, g.a0)), dist(p, polar(g.c, g.r, g.a0 + g.sweep)));
}

export function pointAt(g: Geom, u: number): P2 {
  if (g.kind === "line") return add(g.a, mul(sub(g.b, g.a), u));
  return polar(g.c, g.r, g.kind === "circle" ? u : g.a0 + u);
}

// ------------------------------------------------------------------ bookkeeping
const ENT_KEYS = ["line", "ent", "l1", "l2", "e1", "e2"];
const PT_KEYS = ["a", "b", "pt"];

/** Drop points no entity uses and relations that refer to removed entities or points. */
export function cleanup(s: Sketch): Sketch {
  const used = new Set(s.entities.flatMap(e => (e.type === "line" ? [e.p1, e.p2] : e.type === "circle" ? [e.c] : [e.c, e.p1, e.p2])));
  s.points = s.points.filter(p => used.has(p.id));
  const ents = new Set(s.entities.map(e => e.id)), pts = new Set(s.points.map(p => p.id));
  s.constraints = s.constraints.filter(k => Object.entries(k).every(([f, v]) =>
    (!ENT_KEYS.includes(f) || ents.has(v as string)) && (!PT_KEYS.includes(f) || pts.has(v as string))));
  return s;
}

/** Delete the given entities and/or points (and everything that depends on them). */
export function removeItems(s0: Sketch, ids: Iterable<string>): Sketch {
  const s = clone(s0); const gone = new Set(ids);
  s.entities = s.entities.filter(e => !gone.has(e.id) && !(e.type === "line" ? gone.has(e.p1) || gone.has(e.p2) : e.type === "circle" ? gone.has(e.c) : gone.has(e.c) || gone.has(e.p1) || gone.has(e.p2)));
  s.constraints = s.constraints.filter(k => !gone.has(k.id));
  return cleanup(s);
}

/** Id of an existing point at `p`, or a new point (registered in `s`). */
function pointId(s: Sketch, p: P2): { id: string; created: boolean } {
  const q = s.points.find(x => Math.abs(x.x - p[0]) < COINCIDENT && Math.abs(x.y - p[1]) < COINCIDENT);
  if (q) return { id: q.id, created: false };
  const np: SPoint = { id: uid("p"), x: p[0], y: p[1] }; s.points.push(np); return { id: np.id, created: true };
}

const push = (s: Sketch, k: NoId<SConstraint>) => { s.constraints.push({ ...k, id: uid("k") } as SConstraint); };
/** Keep a new point on the entity it was cut against. */
function stickTo(s: Sketch, pt: string, by: string) {
  const o = entOf(s, by); if (!o) return;
  push(s, o.type === "line" ? { type: "onLine", pt, line: o.id } : { type: "onCircle", pt, ent: o.id });
}
const usesOf = (s: Sketch, pt: string) => s.entities.filter(e => (e.type === "line" ? [e.p1, e.p2] : e.type === "circle" ? [e.c] : [e.c, e.p1, e.p2]).includes(pt));
/** Orientation relations of a line, copied onto the pieces a split produces. */
const DIRECTIONAL = new Set(["horizontal", "vertical", "parallel", "perpendicular"]);

// ------------------------------------------------------------------ trim
/**
 * Power trim: remove the portion of an entity between the intersections on either side of the click. An entity with
 * no intersections is deleted; a circle needs two to become an arc. New end points stay on the entity they meet.
 */
export function trim(s0: Sketch, entId: string, click: P2): Sketch {
  const s = clone(s0);
  const e = entOf(s, entId); if (!e) throw new Error("Nothing to trim there");
  const g = geomOf(s, e);
  const span = g.kind === "line" ? 1 : g.kind === "arc" ? g.sweep : TAU;
  const scale = g.kind === "line" ? dist(g.a, g.b) : g.r;
  const du = 1e-6 / (scale || 1);
  const cuts: { u: number; p: P2; by: string }[] = [];
  for (const o of s.entities) {
    if (o.id === entId) continue;
    for (const p of intersect(g, geomOf(s, o))) {
      const u = param(g, p);
      if (g.kind !== "circle" && (u <= du || u >= span - du)) continue;
      if (!cuts.some(c => Math.abs(c.u - u) < du || (g.kind === "circle" && Math.abs(Math.abs(c.u - u) - TAU) < du))) cuts.push({ u, p, by: o.id });
    }
  }
  cuts.sort((a, b) => a.u - b.u);
  if (g.kind === "circle" ? cuts.length < 2 : cuts.length === 0) return removeItems(s, [entId]);
  const uc = Math.min(Math.max(param(g, click), 0), span);
  const at = (c: { p: P2; by: string }) => { const r = pointId(s, c.p); if (r.created) stickTo(s, r.id, c.by); return r.id; };

  if (e.type === "circle") {
    const hiIdx = cuts.findIndex(c => c.u > uc); const hi = cuts[hiIdx < 0 ? 0 : hiIdx]!;
    const lo = cuts[hiIdx <= 0 ? cuts.length - 1 : hiIdx - 1]!;
    const arc: ArcE = { id: e.id, type: "arc", c: e.c, p1: at(hi), p2: at(lo), ...(e.construction ? { construction: true } : {}) };
    s.entities = s.entities.map(x => (x.id === e.id ? arc : x));
    return cleanup(s);
  }
  const lo = [...cuts].reverse().find(c => c.u < uc), hi = cuts.find(c => c.u > uc);
  const pieces: [string, string][] = [];
  if (lo) pieces.push([e.p1, at(lo)]);
  if (hi) pieces.push([at(hi), e.p2]);
  const idx = s.entities.indexOf(e);
  const made: SEntity[] = pieces.map(([p1, p2], i) => {
    const id = i === 0 ? e.id : uid("e");
    return e.type === "line" ? { ...e, id, p1, p2 } : { ...e, id, p1, p2 };
  });
  s.entities.splice(idx, 1, ...made);
  if (e.type === "line") {
    s.constraints = s.constraints.filter(k => !((k.type === "length" && k.line === e.id) || (k.type === "equal" && (k.l1 === e.id || k.l2 === e.id))));
    if (made.length === 2) for (const k of s.constraints.filter(k => DIRECTIONAL.has(k.type))) {
      const kk = k as { line?: string; l1?: string; l2?: string };
      if (kk.line === e.id) push(s, { ...(k as object), line: made[1]!.id } as NoId<SConstraint>);
      else if (kk.l1 === e.id) push(s, { ...(k as object), l1: made[1]!.id } as NoId<SConstraint>);
      else if (kk.l2 === e.id) push(s, { ...(k as object), l2: made[1]!.id } as NoId<SConstraint>);
    }
  }
  return cleanup(s);
}

// ------------------------------------------------------------------ extend
/** Extend the free end of a line or arc nearest the click to the next entity it would meet. */
export function extend(s0: Sketch, entId: string, click: P2): Sketch {
  const s = clone(s0);
  const e = entOf(s, entId); if (!e) throw new Error("Nothing to extend there");
  if (e.type === "circle") throw new Error("A circle is closed; there is nothing to extend");
  const g = geomOf(s, e);
  const endKey: "p1" | "p2" = dist(click, ptOf(s, e.p1)) <= dist(click, ptOf(s, e.p2)) ? "p1" : "p2";
  const pid = e[endKey];
  if (usesOf(s, pid).length > 1) throw new Error("Only a free end can be extended (this end is connected)");
  let best: { k: number; p: P2; by: string } | null = null;
  for (const o of s.entities) {
    if (o.id === entId) continue;
    const h = geomOf(s, o);
    for (const p of carrierHits(g, h)) {
      if (!within(h, p)) continue;
      let k: number;
      if (g.kind === "line") { const t = param(g, p); const l = dist(g.a, g.b) || 1; k = endKey === "p2" ? (t - 1) * l : -t * l; }
      else if (g.kind === "arc") {
        const ang = Math.atan2(p[1] - g.c[1], p[0] - g.c[0]);
        k = (endKey === "p2" ? normA(ang - (g.a0 + g.sweep)) : normA(g.a0 - ang)) * g.r;
        if (k / g.r > TAU - g.sweep - 1e-9) continue; // would wrap past the other end
      } else continue;
      if (k > 1e-6 && (!best || k < best.k)) best = { k, p, by: o.id };
    }
  }
  if (!best) throw new Error("Nothing to extend to in that direction");
  const hit = s.points.find(q => q.id !== pid && Math.abs(q.x - best!.p[0]) < COINCIDENT && Math.abs(q.y - best!.p[1]) < COINCIDENT);
  if (hit) (e as LineE | ArcE)[endKey] = hit.id;
  else {
    const q = s.points.find(x => x.id === pid)!; q.x = best.p[0]; q.y = best.p[1]; delete q.fixed;
    s.constraints = s.constraints.filter(k => !(k.type === "fix" && k.pt === pid));
    stickTo(s, pid, best.by);
  }
  s.constraints = s.constraints.filter(k => !(k.type === "length" && k.line === e.id));
  return cleanup(s);
}

// ------------------------------------------------------------------ offset
type Chain = { items: { e: LineE | ArcE; rev: boolean }[]; closed: boolean };

/** Signed area of a chain (positive = counter-clockwise), arcs included via their bulge. */
function chainArea(s: Sketch, ch: Chain): number {
  let a2 = 0;
  for (const { e, rev } of ch.items) {
    const g = geomOf(s, e);
    const n = e.type === "arc" ? 24 : 1; const pts: P2[] = [];
    for (let i = 0; i <= n; i++) { const u = i / n; pts.push(g.kind === "line" ? pointAt(g, rev ? 1 - u : u) : pointAt(g, (g as { sweep: number }).sweep * (rev ? 1 - u : u))); }
    for (let i = 0; i < n; i++) a2 += cross(pts[i]!, pts[i + 1]!);
  }
  return a2 / 2;
}

/**
 * Offset lines, arcs and circles by `d`. Connected lines/arcs are offset as a chain and re-joined at their
 * intersections. By default closed chains and circles grow outwards and open chains go to the left of their
 * direction; `flip` takes the other side. Lines get a parallel relation, arcs and circles share the original centre.
 */
export function offsetEntities(s0: Sketch, ids: string[], d: number, flip = false): Sketch {
  if (!(d > 0)) throw new Error("Offset distance must be positive");
  const s = clone(s0);
  const sel = ids.map(id => entOf(s, id)).filter((e): e is SEntity => !!e);
  if (!sel.length) throw new Error("Select lines, arcs or circles to offset");
  for (const e of sel) if (e.type === "circle") {
    const r = e.r + (flip ? -d : d);
    if (r <= 1e-6) throw new Error("The offset is larger than a circle's radius");
    s.entities.push({ id: uid("e"), type: "circle", c: e.c, r, ...(e.construction ? { construction: true } : {}) });
  }
  const segs = sel.filter((e): e is LineE | ArcE => e.type !== "circle");
  for (const ch of chainsOf(s, segs) as Chain[]) {
    const sigma = (ch.closed ? (chainArea(s, ch) > 0 ? -1 : 1) : 1) * (flip ? -1 : 1); // +1 = left of travel
    // offset carrier of each oriented item, plus its naive offset start/end
    const off = ch.items.map(({ e, rev }) => {
      const g = geomOf(s, e);
      if (g.kind === "line") {
        const a = rev ? g.b : g.a, b = rev ? g.a : g.b; const u = unit(sub(b, a)); const n = mul([-u[1], u[0]], sigma * d);
        return { g: { kind: "line", a: add(a, n), b: add(b, n) } as Geom, start: add(a, n), end: add(b, n) };
      }
      const arc = g as Extract<Geom, { kind: "arc" }>;
      const r = arc.r + (rev ? 1 : -1) * sigma * d; // CCW travel: left is towards the centre
      if (r <= 1e-6) throw new Error("The offset is larger than an arc's radius");
      const sa = rev ? arc.a0 + arc.sweep : arc.a0, ea = rev ? arc.a0 : arc.a0 + arc.sweep;
      return { g: { kind: "circle", c: arc.c, r } as Geom, start: polar(arc.c, r, sa), end: polar(arc.c, r, ea) };
    });
    const n = off.length;
    const joins: P2[] = []; // vertex i = start of item i
    for (let i = 0; i < (ch.closed ? n : n + 1); i++) {
      const prev = i > 0 ? off[i - 1]! : ch.closed ? off[n - 1]! : null;
      const next = i < n ? off[i]! : null;
      if (!prev) { joins.push(next!.start); continue; }
      if (!next) { joins.push(prev.end); continue; }
      const hits = carrierHits(prev.g, next.g);
      const guess = mul(add(prev.end, next.start), 0.5);
      joins.push(hits.length ? hits.reduce((b, p) => (dist(p, guess) < dist(b, guess) ? p : b)) : guess);
    }
    const vid = joins.map(p => pointId(s, p).id);
    ch.items.forEach(({ e, rev }, i) => {
      const a = vid[i]!, b = vid[(i + 1) % vid.length]!;
      const [p1, p2] = rev ? [b, a] : [a, b];
      const id = uid("e");
      if (e.type === "line") { s.entities.push({ id, type: "line", p1, p2, ...(e.construction ? { construction: true } : {}) }); push(s, { type: "parallel", l1: e.id, l2: id }); }
      else s.entities.push({ id, type: "arc", c: e.c, p1, p2, ...(e.construction ? { construction: true } : {}) });
    });
  }
  return s;
}

// ------------------------------------------------------------------ slot, polygon
/** Straight slot between two centre points (existing point ids) with end radius r: two lines tangent to two arcs. */
export function addSlot(s0: Sketch, c1: string, c2: string, r: number): Sketch {
  if (!(r > 0)) throw new Error("Slot width must be positive");
  const s = clone(s0);
  const C1 = ptOf(s, c1), C2 = ptOf(s, c2);
  if (dist(C1, C2) < 1e-6) throw new Error("The slot's two centres must differ");
  const u = unit(sub(C2, C1)); const n: P2 = [-u[1], u[0]];
  const P = (p: P2) => { const q: SPoint = { id: uid("p"), x: p[0], y: p[1] }; s.points.push(q); return q.id; };
  const A = P(add(C1, mul(n, r))), B = P(add(C2, mul(n, r))), C = P(add(C2, mul(n, -r))), D = P(add(C1, mul(n, -r)));
  const top: LineE = { id: uid("e"), type: "line", p1: A, p2: B }, bot: LineE = { id: uid("e"), type: "line", p1: C, p2: D };
  const end2: ArcE = { id: uid("e"), type: "arc", c: c2, p1: C, p2: B }, end1: ArcE = { id: uid("e"), type: "arc", c: c1, p1: A, p2: D };
  const axis: LineE = { id: uid("e"), type: "line", p1: c1, p2: c2, construction: true };
  s.entities.push(top, end2, bot, end1, axis);
  for (const l of [top, bot]) for (const a of [end1, end2]) push(s, { type: "tangent", line: l.id, ent: a.id });
  push(s, { type: "equal", l1: end1.id, l2: end2.id });
  return s;
}

/**
 * Regular n-gon centred on an existing point. Inscribed: `v` is a vertex on the construction circle. Circumscribed:
 * `v` is the midpoint of a side and the construction circle is tangent to every side. Solved by equal sides plus
 * vertices on (or sides tangent to) the construction circle, so it stays regular when dragged or dimensioned.
 */
export function addPolygon(s0: Sketch, center: string, v: P2, n: number, mode: "inscribed" | "circumscribed" = "inscribed"): Sketch {
  if (!Number.isInteger(n) || n < 3 || n > 64) throw new Error("A polygon needs 3 to 64 sides");
  const s = clone(s0);
  const c = ptOf(s, center); const r = dist(c, v);
  if (r < 1e-6) throw new Error("Drag out the polygon's size");
  const a0 = Math.atan2(v[1] - c[1], v[0] - c[0]);
  const R = mode === "inscribed" ? r : r / Math.cos(Math.PI / n);
  const start = mode === "inscribed" ? a0 : a0 - Math.PI / n;
  const ids = Array.from({ length: n }, (_, k) => { const p = polar(c, R, start + (TAU * k) / n); const q: SPoint = { id: uid("p"), x: p[0], y: p[1] }; s.points.push(q); return q.id; });
  const circle: SEntity = { id: uid("e"), type: "circle", c: center, r, construction: true };
  const sides: LineE[] = ids.map((id, k) => ({ id: uid("e"), type: "line", p1: id, p2: ids[(k + 1) % n]! }));
  s.entities.push(circle, ...sides);
  sides.slice(1).forEach(l => push(s, { type: "equal", l1: sides[0]!.id, l2: l.id }));
  if (mode === "inscribed") ids.forEach(pt => push(s, { type: "onCircle", pt, ent: circle.id }));
  else sides.forEach(l => push(s, { type: "tangent", line: l.id, ent: circle.id }));
  return s;
}

// ------------------------------------------------------------------ corner fillet
/** Round the corner where exactly two lines meet with a tangent arc of radius r (both lines are trimmed back). */
export function filletCorner(s0: Sketch, ptId: string, r: number): Sketch {
  if (!(r > 0)) throw new Error("Fillet radius must be positive");
  const s = clone(s0);
  const users = usesOf(s, ptId);
  const lines = users.filter((e): e is LineE => e.type === "line");
  if (users.length !== 2 || lines.length !== 2) throw new Error("Pick a corner where exactly two lines meet");
  const P = ptOf(s, ptId);
  const far = lines.map(l => ptOf(s, l.p1 === ptId ? l.p2 : l.p1));
  const u1 = unit(sub(far[0]!, P)), u2 = unit(sub(far[1]!, P));
  const theta = Math.acos(Math.max(-1, Math.min(1, dot(u1, u2))));
  if (theta < 1e-4 || Math.PI - theta < 1e-4) throw new Error("The lines are collinear; there is no corner to round");
  const t = r / Math.tan(theta / 2);
  if (t >= dist(far[0]!, P) - 1e-9 || t >= dist(far[1]!, P) - 1e-9) throw new Error("The radius is too large for these lines");
  const T1 = add(P, mul(u1, t)), T2 = add(P, mul(u2, t));
  const O = add(P, mul(unit(add(u1, u2)), r / Math.sin(theta / 2)));
  const mk = (p: P2) => { const q: SPoint = { id: uid("p"), x: p[0], y: p[1] }; s.points.push(q); return q.id; };
  const t1 = mk(T1), t2 = mk(T2), o = mk(O);
  lines.forEach((l, i) => { if (l.p1 === ptId) l.p1 = i === 0 ? t1 : t2; else l.p2 = i === 0 ? t1 : t2; });
  const ccw = cross(sub(T1, O), sub(T2, O)) > 0;
  const arc: ArcE = { id: uid("e"), type: "arc", c: o, p1: ccw ? t1 : t2, p2: ccw ? t2 : t1 };
  s.entities.push(arc);
  s.constraints = s.constraints.filter(k => !(k.type === "length" && lines.some(l => l.id === k.line)));
  lines.forEach(l => push(s, { type: "tangent", line: l.id, ent: arc.id }));
  push(s, { type: "radius", ent: arc.id, value: r });
  return cleanup(s);
}

// ------------------------------------------------------------------ mirror
/** Mirror entities about a line (usually a centerline). Points on the line are shared; others get a symmetric relation. */
export function mirrorEntities(s0: Sketch, ids: string[], axisId: string): Sketch {
  const s = clone(s0);
  const ax = entOf(s, axisId);
  if (!ax || ax.type !== "line") throw new Error("Select a centerline (or line) to mirror about");
  const A = ptOf(s, ax.p1), B = ptOf(s, ax.p2); const u = unit(sub(B, A));
  const reflect = (p: P2): P2 => { const v = sub(p, A); const along = mul(u, dot(v, u)); return add(A, sub(mul(along, 2), v)); };
  const map = new Map<string, string>();
  const image = (pid: string) => {
    const got = map.get(pid); if (got) return got;
    const p = ptOf(s, pid);
    if (Math.abs(cross(u, sub(p, A))) < COINCIDENT) { map.set(pid, pid); return pid; }
    const q = pointId(s, reflect(p));
    if (q.created) push(s, { type: "symmetric", a: pid, b: q.id, line: axisId });
    map.set(pid, q.id); return q.id;
  };
  const src = ids.filter(id => id !== axisId).map(id => entOf(s, id)).filter((e): e is SEntity => !!e);
  if (!src.length) throw new Error("Select the entities to mirror as well as the centerline");
  for (const e of src) {
    const id = uid("e"); const cons = e.construction ? { construction: true } : {};
    if (e.type === "line") s.entities.push({ id, type: "line", p1: image(e.p1), p2: image(e.p2), ...cons });
    else if (e.type === "circle") { s.entities.push({ id, type: "circle", c: image(e.c), r: e.r, ...cons }); push(s, { type: "equal", l1: e.id, l2: id }); }
    else s.entities.push({ id, type: "arc", c: image(e.c), p1: image(e.p2), p2: image(e.p1), ...cons }); // reflection reverses the sense
  }
  return s;
}

// ------------------------------------------------------------------ angle dimension
/** Angle relation between two lines, measured at their corner (directions point away from the intersection). */
export function angleBetween(s: Sketch, l1: string, l2: string): NoId<Extract<SConstraint, { type: "angle" }>> {
  const e1 = entOf(s, l1), e2 = entOf(s, l2);
  if (e1?.type !== "line" || e2?.type !== "line") throw new Error("Pick two lines for an angle");
  const g1 = geomOf(s, e1) as Extract<Geom, { kind: "line" }>, g2 = geomOf(s, e2) as Extract<Geom, { kind: "line" }>;
  const x = carrierHits(g1, g2)[0];
  if (!x) throw new Error("The lines are parallel; dimension their distance instead");
  const f1 = dist(g1.b, x) < dist(g1.a, x), f2 = dist(g2.b, x) < dist(g2.a, x);
  const d1 = f1 ? sub(g1.a, g1.b) : sub(g1.b, g1.a), d2 = f2 ? sub(g2.a, g2.b) : sub(g2.b, g2.a);
  const value = (Math.atan2(Math.abs(cross(d1, d2)), dot(d1, d2)) * 180) / Math.PI;
  return { type: "angle", l1, l2, value, ...(f1 ? { f1 } : {}), ...(f2 ? { f2 } : {}) };
}

/** Where to draw an angle dimension: on the bisector, a little way out from the corner. */
export function angleAnchor(s: Sketch, k: Extract<SConstraint, { type: "angle" }>): P2 | null {
  const e1 = entOf(s, k.l1), e2 = entOf(s, k.l2);
  if (e1?.type !== "line" || e2?.type !== "line") return null;
  const g1 = geomOf(s, e1) as Extract<Geom, { kind: "line" }>, g2 = geomOf(s, e2) as Extract<Geom, { kind: "line" }>;
  const x = carrierHits(g1, g2)[0]; if (!x) return null;
  const d1 = unit(k.f1 ? sub(g1.a, g1.b) : sub(g1.b, g1.a)), d2 = unit(k.f2 ? sub(g2.a, g2.b) : sub(g2.b, g2.a));
  const bis = len(add(d1, d2)) > 1e-9 ? unit(add(d1, d2)) : [-d1[1], d1[0]] as P2;
  const reach = 0.35 * Math.min(dist(g1.a, g1.b), dist(g2.a, g2.b));
  return add(x, mul(bis, reach));
}
