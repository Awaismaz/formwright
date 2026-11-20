/** 2D sketch model + geometric constraint solver (Levenberg-Marquardt, numeric Jacobian). Units: mm. */

export interface SPoint { id: string; x: number; y: number; fixed?: boolean }
export type SEntity =
  | { id: string; type: "line"; p1: string; p2: string; construction?: boolean }
  | { id: string; type: "circle"; c: string; r: number; construction?: boolean }
  | { id: string; type: "arc"; c: string; p1: string; p2: string; construction?: boolean }; // CCW from p1 to p2
export type SConstraint =
  | { id: string; type: "horizontal" | "vertical"; line: string }
  | { id: string; type: "distance" | "hdist" | "vdist"; a: string; b: string; value: number }
  | { id: string; type: "length"; line: string; value: number }
  | { id: string; type: "radius" | "diameter"; ent: string; value: number }
  | { id: string; type: "parallel" | "perpendicular" | "equal"; l1: string; l2: string }
  | { id: string; type: "fix"; pt: string }
  | { id: string; type: "onLine"; pt: string; line: string }
  | { id: string; type: "onCircle"; pt: string; ent: string }
  | { id: string; type: "tangent"; line: string; ent: string }
  | { id: string; type: "concentric"; e1: string; e2: string }
  /** angle in degrees between two lines; f1/f2 flip a line's direction (p2→p1) so the angle is measured at their corner */
  | { id: string; type: "angle"; l1: string; l2: string; value: number; f1?: boolean; f2?: boolean }
  /** points a and b mirror each other about the (infinite) line */
  | { id: string; type: "symmetric"; a: string; b: string; line: string };

export interface Sketch { points: SPoint[]; entities: SEntity[]; constraints: SConstraint[] }

let seq = 0;
export const uid = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`;

export function clone(s: Sketch): Sketch { return JSON.parse(JSON.stringify(s)) as Sketch; }

type Getter = { pt: (id: string) => [number, number]; rad: (id: string) => number };

function entOf(s: Sketch, id: string) { return s.entities.find(e => e.id === id); }

function residuals(s: Sketch, g: Getter): number[] {
  const r: number[] = [];
  const line = (id: string) => { const e = entOf(s, id); if (!e || e.type !== "line") return null; const a = g.pt(e.p1), b = g.pt(e.p2); return { a, b, dx: b[0] - a[0], dy: b[1] - a[1] }; };
  const radius = (id: string) => { const e = entOf(s, id); if (!e) return null;
    if (e.type === "circle") return { c: g.pt(e.c), r: g.rad(e.id) };
    if (e.type === "arc") { const c = g.pt(e.c), p = g.pt(e.p1); return { c, r: Math.hypot(p[0] - c[0], p[1] - c[1]) }; }
    return null; };
  // implicit arc constraint: both ends on the same circle
  for (const e of s.entities) if (e.type === "arc") {
    const c = g.pt(e.c), a = g.pt(e.p1), b = g.pt(e.p2);
    r.push(Math.hypot(a[0] - c[0], a[1] - c[1]) - Math.hypot(b[0] - c[0], b[1] - c[1]));
  }
  for (const k of s.constraints) {
    switch (k.type) {
      case "horizontal": { const l = line(k.line); if (l) r.push(l.dy); break; }
      case "vertical": { const l = line(k.line); if (l) r.push(l.dx); break; }
      case "distance": { const a = g.pt(k.a), b = g.pt(k.b); r.push(Math.hypot(b[0] - a[0], b[1] - a[1]) - k.value); break; }
      case "hdist": { const a = g.pt(k.a), b = g.pt(k.b); r.push(Math.abs(b[0] - a[0]) - k.value); break; }
      case "vdist": { const a = g.pt(k.a), b = g.pt(k.b); r.push(Math.abs(b[1] - a[1]) - k.value); break; }
      case "length": { const l = line(k.line); if (l) r.push(Math.hypot(l.dx, l.dy) - k.value); break; }
      case "radius": case "diameter": { const c = radius(k.ent); if (c) r.push(c.r - (k.type === "radius" ? k.value : k.value / 2)); break; }
      case "parallel": { const a = line(k.l1), b = line(k.l2); if (a && b) { const la = Math.hypot(a.dx, a.dy) || 1, lb = Math.hypot(b.dx, b.dy) || 1; r.push((a.dx * b.dy - a.dy * b.dx) / (la * lb)); } break; }
      case "perpendicular": { const a = line(k.l1), b = line(k.l2); if (a && b) { const la = Math.hypot(a.dx, a.dy) || 1, lb = Math.hypot(b.dx, b.dy) || 1; r.push((a.dx * b.dx + a.dy * b.dy) / (la * lb)); } break; }
      case "equal": {
        const a = line(k.l1), b = line(k.l2);
        if (a && b) r.push(Math.hypot(a.dx, a.dy) - Math.hypot(b.dx, b.dy));
        else { const ca = radius(k.l1), cb = radius(k.l2); if (ca && cb) r.push(ca.r - cb.r); }
        break; }
      case "fix": break; // handled by removing the point from the unknowns
      case "onLine": { const l = line(k.line); if (l) { const p = g.pt(k.pt); const L = Math.hypot(l.dx, l.dy) || 1; r.push(((p[0] - l.a[0]) * l.dy - (p[1] - l.a[1]) * l.dx) / L); } break; }
      case "onCircle": { const c = radius(k.ent); if (c) { const p = g.pt(k.pt); r.push(Math.hypot(p[0] - c.c[0], p[1] - c.c[1]) - c.r); } break; }
      case "tangent": { const l = line(k.line), c = radius(k.ent); if (l && c) {
        const L = Math.hypot(l.dx, l.dy) || 1;
        // An arc ending on the line: radius perpendicular to the line at the shared point (the distance form has a
        // zero gradient there, which hides a degree of freedom).
        const le = entOf(s, k.line) as Extract<SEntity, { type: "line" }>, ae = entOf(s, k.ent)!;
        const shared = ae.type === "arc" ? [ae.p1, ae.p2].find(p => p === le.p1 || p === le.p2) : undefined;
        if (shared) { const p = g.pt(shared); const vx = p[0] - c.c[0], vy = p[1] - c.c[1]; r.push((vx * l.dx + vy * l.dy) / ((Math.hypot(vx, vy) || 1) * L)); }
        else r.push(Math.abs(((c.c[0] - l.a[0]) * l.dy - (c.c[1] - l.a[1]) * l.dx) / L) - c.r); } break; }
      case "concentric": { const a = radius(k.e1), b = radius(k.e2); if (a && b) { r.push(a.c[0] - b.c[0], a.c[1] - b.c[1]); } break; }
      case "angle": { const a = line(k.l1), b = line(k.l2); if (a && b) {
        const ax = k.f1 ? -a.dx : a.dx, ay = k.f1 ? -a.dy : a.dy, bx = k.f2 ? -b.dx : b.dx, by = k.f2 ? -b.dy : b.dy;
        r.push(Math.atan2(Math.abs(ax * by - ay * bx), ax * bx + ay * by) - (k.value * Math.PI) / 180); } break; }
      case "symmetric": { const l = line(k.line); if (l) { const p = g.pt(k.a), q = g.pt(k.b); const L = Math.hypot(l.dx, l.dy) || 1;
        const mx = (p[0] + q[0]) / 2 - l.a[0], my = (p[1] + q[1]) / 2 - l.a[1];
        r.push((mx * l.dy - my * l.dx) / L, ((q[0] - p[0]) * l.dx + (q[1] - p[1]) * l.dy) / L); } break; }
    }
  }
  return r;
}

interface Vars { keys: { kind: "x" | "y" | "r"; id: string }[] }

function varsOf(s: Sketch): Vars {
  const fixed = new Set(s.constraints.filter(c => c.type === "fix").map(c => (c as { pt: string }).pt));
  const keys: Vars["keys"] = [];
  for (const p of s.points) if (!p.fixed && !fixed.has(p.id)) keys.push({ kind: "x", id: p.id }, { kind: "y", id: p.id });
  for (const e of s.entities) if (e.type === "circle") keys.push({ kind: "r", id: e.id });
  return { keys };
}

function makeGetter(s: Sketch, keys: Vars["keys"], x: number[]): Getter {
  const pm = new Map(s.points.map(p => [p.id, [p.x, p.y] as [number, number]]));
  const rm = new Map(s.entities.filter(e => e.type === "circle").map(e => [e.id, (e as { r: number }).r]));
  keys.forEach((k, i) => {
    if (k.kind === "r") rm.set(k.id, x[i]!);
    else { const v = pm.get(k.id)!; if (k.kind === "x") v[0] = x[i]!; else v[1] = x[i]!; }
  });
  return { pt: id => pm.get(id) ?? [0, 0], rad: id => rm.get(id) ?? 0 };
}

function solveLinear(A: number[][], b: number[]): number[] | null {
  const n = b.length; const M = A.map((row, i) => [...row, b[i]!]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let i = c + 1; i < n; i++) if (Math.abs(M[i]![c]!) > Math.abs(M[p]![c]!)) p = i;
    if (Math.abs(M[p]![c]!) < 1e-14) return null;
    [M[c], M[p]] = [M[p]!, M[c]!];
    for (let i = 0; i < n; i++) if (i !== c) { const f = M[i]![c]! / M[c]![c]!; for (let j = c; j <= n; j++) M[i]![j]! -= f * M[c]![j]!; }
  }
  return M.map((row, i) => row[n]! / row[i]!);
}

function rank(J: number[][], tol = 1e-8): number {
  const M = J.map(r => [...r]); const rows = M.length, cols = rows ? M[0]!.length : 0;
  let rk = 0;
  for (let c = 0; c < cols && rk < rows; c++) {
    let p = rk; for (let i = rk + 1; i < rows; i++) if (Math.abs(M[i]![c]!) > Math.abs(M[p]![c]!)) p = i;
    if (Math.abs(M[p]![c]!) < tol) continue;
    [M[rk], M[p]] = [M[p]!, M[rk]!];
    for (let i = rk + 1; i < rows; i++) { const f = M[i]![c]! / M[rk]![c]!; for (let j = c; j < cols; j++) M[i]![j]! -= f * M[rk]![j]!; }
    rk++;
  }
  return rk;
}

export interface SolveResult { sketch: Sketch; ok: boolean; residual: number; dof: number }

/** Solve constraints in place of a copy; minimal movement from the current positions. */
export function solve(input: Sketch, iterations = 60): SolveResult {
  const s = clone(input);
  const { keys } = varsOf(s);
  const x = keys.map(k => (k.kind === "r" ? (entOf(s, k.id) as { r: number }).r : (s.points.find(p => p.id === k.id)! as SPoint)[k.kind]));
  const F = (v: number[]) => residuals(s, makeGetter(s, keys, v));
  let r = F(x); let err = r.reduce((a, b) => a + b * b, 0);
  let lambda = 1e-3;
  const jac = (v: number[], r0: number[]) => {
    const J: number[][] = r0.map(() => new Array(v.length).fill(0));
    for (let j = 0; j < v.length; j++) {
      const h = 1e-7 * Math.max(1, Math.abs(v[j]!));
      const vp = [...v]; vp[j]! += h; const rp = F(vp);
      for (let i = 0; i < r0.length; i++) J[i]![j] = (rp[i]! - r0[i]!) / h;
    }
    return J;
  };
  for (let it = 0; it < iterations && err > 1e-20 && keys.length && r.length; it++) {
    const J = jac(x, r);
    const n = x.length;
    const A = Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => J.reduce((a, row) => a + row[i]! * row[j]!, 0)));
    const g = Array.from({ length: n }, (_, i) => J.reduce((a, row, k) => a + row[i]! * r[k]!, 0));
    let improved = false;
    for (let t = 0; t < 8 && !improved; t++) {
      const Ad = A.map((row, i) => row.map((v, j) => (i === j ? v + lambda * (1 + v) : v)));
      const d = solveLinear(Ad, g.map(v => -v));
      if (!d) { lambda *= 10; continue; }
      const xn = x.map((v, i) => v + d[i]!);
      const rn = F(xn); const en = rn.reduce((a, b) => a + b * b, 0);
      if (en < err) { x.splice(0, x.length, ...xn); r = rn; err = en; lambda = Math.max(lambda / 10, 1e-12); improved = true; }
      else lambda *= 10;
    }
    if (!improved) break;
  }
  const getter = makeGetter(s, keys, x);
  for (const p of s.points) { const [px, py] = getter.pt(p.id); p.x = px; p.y = py; }
  for (const e of s.entities) if (e.type === "circle") e.r = getter.rad(e.id);
  const J = keys.length && r.length ? jac(x, r) : [];
  const dof = keys.length - (J.length ? rank(J) : 0);
  return { sketch: s, ok: Math.sqrt(err) < 1e-6, residual: Math.sqrt(err), dof };
}

// ------------------------------------------------------------------ profiles
export type ProfileSeg = { type: "line"; a: [number, number]; b: [number, number] } | { type: "arc"; a: [number, number]; b: [number, number]; m: [number, number] };
export interface Profile { kind: "loop"; segs: ProfileSeg[] }
export interface CircleProfile { kind: "circle"; cx: number; cy: number; r: number }

/** Canonical id per point: points at the same position (within 1e-6 mm) chain as one. */
export function coincidentMap(s: Sketch, tol = 1e-6): Map<string, string> {
  const out = new Map<string, string>(); const reps: SPoint[] = [];
  for (const p of s.points) {
    const r = reps.find(q => Math.abs(q.x - p.x) < tol && Math.abs(q.y - p.y) < tol);
    if (r) out.set(p.id, r.id); else { reps.push(p); out.set(p.id, p.id); }
  }
  return out;
}

type ChainSeg = Extract<SEntity, { type: "line" | "arc" }>;
/** Chains of lines/arcs joined end to end (by position). `rev` means the entity is travelled p2 → p1. */
export function chainsOf(s: Sketch, segs: ChainSeg[]): { items: { e: ChainSeg; rev: boolean }[]; closed: boolean }[] {
  const canon = coincidentMap(s); const C = (id: string) => canon.get(id) ?? id;
  const used = new Set<string>(); const out: { items: { e: ChainSeg; rev: boolean }[]; closed: boolean }[] = [];
  for (const start of segs) {
    if (used.has(start.id)) continue;
    used.add(start.id);
    const items: { e: ChainSeg; rev: boolean }[] = [{ e: start, rev: false }];
    const head = C(start.p1); let tail = C(start.p2); let closed = head === tail;
    while (!closed) { // forward from the tail
      const nxt = segs.find(e => !used.has(e.id) && (C(e.p1) === tail || C(e.p2) === tail)); if (!nxt) break;
      used.add(nxt.id); const rev = C(nxt.p2) === tail; items.push({ e: nxt, rev }); tail = rev ? C(nxt.p1) : C(nxt.p2);
      if (tail === head) closed = true;
    }
    if (!closed) { // backward from the head
      let h = head;
      for (;;) {
        const prv = segs.find(e => !used.has(e.id) && (C(e.p1) === h || C(e.p2) === h)); if (!prv) break;
        used.add(prv.id); const rev = C(prv.p1) === h; items.unshift({ e: prv, rev }); h = rev ? C(prv.p2) : C(prv.p1);
      }
    }
    out.push({ items, closed });
  }
  return out;
}

/** Closed loops (and open chains) from the non-construction geometry, chaining coincident endpoints. */
export function profiles(s: Sketch): { loops: (Profile | CircleProfile)[]; open: number; chains: ProfileSeg[][] } {
  const P = new Map(s.points.map(p => [p.id, [p.x, p.y] as [number, number]]));
  const out: (Profile | CircleProfile)[] = [];
  for (const e of s.entities) if (e.type === "circle" && !e.construction) { const c = P.get(e.c)!; out.push({ kind: "circle", cx: c[0], cy: c[1], r: e.r }); }
  const segs = s.entities.filter(e => (e.type === "line" || e.type === "arc") && !e.construction) as ChainSeg[];
  const toSegs = (items: { e: ChainSeg; rev: boolean }[]) => items.map(({ e, rev }) => {
    const a = P.get(rev ? e.p2 : e.p1)!, b = P.get(rev ? e.p1 : e.p2)!;
    if (e.type === "line") return { type: "line", a, b } as ProfileSeg;
    const c = P.get(e.c)!; const R = Math.hypot(P.get(e.p1)![0] - c[0], P.get(e.p1)![1] - c[1]);
    const a1 = Math.atan2(P.get(e.p1)![1] - c[1], P.get(e.p1)![0] - c[0]);
    let a2 = Math.atan2(P.get(e.p2)![1] - c[1], P.get(e.p2)![0] - c[0]); if (a2 <= a1) a2 += Math.PI * 2;
    const am = (a1 + a2) / 2;
    return { type: "arc", a, b, m: [c[0] + R * Math.cos(am), c[1] + R * Math.sin(am)] } as ProfileSeg;
  });
  const chains: ProfileSeg[][] = [];
  for (const ch of chainsOf(s, segs)) {
    if (ch.closed) out.push({ kind: "loop", segs: toSegs(ch.items) }); else chains.push(toSegs(ch.items));
  }
  return { loops: out, open: chains.length, chains };
}
