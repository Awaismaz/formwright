import type { V3 } from "./types";

/** Sketch plane: origin, outward normal and the sketch X direction (sketch Y = normal × x_dir). */
export interface PlaneDef { origin: V3; normal: V3; x_dir: V3 }

/** Default reference planes (Z up; the front view looks along +Y). Names follow SOLIDWORKS. */
export const REF_PLANES: Record<"Front" | "Top" | "Right", PlaneDef> = {
  Front: { origin: [0, 0, 0], normal: [0, -1, 0], x_dir: [1, 0, 0] },
  Top: { origin: [0, 0, 0], normal: [0, 0, 1], x_dir: [1, 0, 0] },
  Right: { origin: [0, 0, 0], normal: [1, 0, 0], x_dir: [0, 1, 0] },
};
export type RefPlane = keyof typeof REF_PLANES;

/** A reference plane moved along its normal by `offset` mm. */
export function offsetPlane(name: RefPlane, offset = 0): PlaneDef {
  const p = REF_PLANES[name];
  return { origin: [p.normal[0] * offset, p.normal[1] * offset, p.normal[2] * offset], normal: p.normal, x_dir: p.x_dir };
}

/** Readable name for a plane, e.g. "Top Plane" or "Top Plane +12 mm"; null for arbitrary planes. */
export function planeName(p: PlaneDef): string | null {
  for (const [name, r] of Object.entries(REF_PLANES)) {
    const same = r.normal.every((c, i) => Math.abs(c - p.normal[i]!) < 1e-9) && r.x_dir.every((c, i) => Math.abs(c - p.x_dir[i]!) < 1e-9);
    if (!same) continue;
    const off = p.origin[0] * r.normal[0] + p.origin[1] * r.normal[1] + p.origin[2] * r.normal[2];
    const along = Math.hypot(p.origin[0] - r.normal[0] * off, p.origin[1] - r.normal[1] * off, p.origin[2] - r.normal[2] * off);
    if (along > 1e-9) return null;
    return Math.abs(off) < 1e-9 ? `${name} Plane` : `${name} Plane ${off > 0 ? "+" : "−"}${+Math.abs(off).toFixed(3)} mm`;
  }
  return null;
}

/** SOLIDWORKS-style next feature name: "Boss-Extrude3". */
export function nextName(base: string, existing: { name: string }[]): string {
  let n = 1;
  const rx = new RegExp(`^${base.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&")}(\\d+)$`);
  for (const f of existing) { const m = rx.exec(f.name); if (m) n = Math.max(n, Number(m[1]) + 1); }
  return `${base}${n}`;
}

export const FEATURE_LABEL: Record<string, string> = {
  fillet: "Fillet", chamfer: "Chamfer", hole: "Hole", extrude: "Extrude", shell: "Shell", mirror: "Mirror",
  sketch: "Extrude", revolve: "Revolve", pattern: "Pattern", plane: "Plane", draft: "Draft", rib: "Rib", sketch2d: "Sketch", sweep: "Sweep", loft: "Loft",
};

/**
 * Placement of a reference plane feature (same maths as the server's refplane.ref_plane): the base plane turned by
 * `angle`° about its own X or Y axis through its origin, then moved `offset` mm along the new normal.
 */
export function resolveRefPlane(base: PlaneDef, offset: number, angle: number, axis: "x" | "y"): PlaneDef {
  const unit = (v: V3): V3 => { const l = Math.hypot(...v) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
  const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  let n = unit(base.normal); const d = dot(base.x_dir, n);
  let x = unit([base.x_dir[0] - n[0] * d, base.x_dir[1] - n[1] * d, base.x_dir[2] - n[2] * d]);
  const y = cross(n, x);
  const a = ((Number.isFinite(angle) ? angle : 0) * Math.PI) / 180;
  if (Math.abs(a) > 1e-12) {
    const k = axis === "y" ? y : x; const c = Math.cos(a), s = Math.sin(a);
    const rot = (v: V3): V3 => { const kv = cross(k, v), kd = dot(k, v) * (1 - c); return unit([v[0] * c + kv[0] * s + k[0] * kd, v[1] * c + kv[1] * s + k[1] * kd, v[2] * c + kv[2] * s + k[2] * kd]); };
    n = rot(n); x = rot(x);
  }
  const off = Number.isFinite(offset) ? offset : 0;
  return { origin: [base.origin[0] + n[0] * off, base.origin[1] + n[1] * off, base.origin[2] + n[2] * off], normal: n, x_dir: x };
}

type Seg2 = { type: string; a: [number, number]; b: [number, number]; m?: [number, number] };
type Prof2 = { kind: "circle"; cx: number; cy: number; r: number } | { kind: "loop"; segs: Seg2[] };

/** World-space polylines of a saved sketch (closed profiles and open chains) on its plane, for the 3D viewer. */
export function sketchLines(plane: PlaneDef, profiles: unknown[] = [], chains: unknown[] = []): V3[][] {
  const n = plane.normal, x = plane.x_dir;
  const y: V3 = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]];
  const to3 = (u: number, v: number): V3 => [plane.origin[0] + x[0] * u + y[0] * v, plane.origin[1] + x[1] * u + y[1] * v, plane.origin[2] + x[2] * u + y[2] * v];
  const norm = (t: number) => ((t % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const seg = (g: Seg2): V3[] => {
    if (g.type !== "arc" || !g.m) return [to3(...g.a), to3(...g.b)];
    const [ax, ay] = g.a, [mx, my] = g.m, [bx, by] = g.b;
    const d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my));
    if (Math.abs(d) < 1e-12) return [to3(...g.a), to3(...g.b)];
    const ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d;
    const uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d;
    const r = Math.hypot(ax - ux, ay - uy);
    const t0 = Math.atan2(ay - uy, ax - ux), tm = Math.atan2(my - uy, mx - ux), t1 = Math.atan2(by - uy, bx - ux);
    const sweep = norm(tm - t0) < norm(t1 - t0) ? norm(t1 - t0) : -norm(t0 - t1);
    return Array.from({ length: 33 }, (_, i) => to3(ux + r * Math.cos(t0 + (sweep * i) / 32), uy + r * Math.sin(t0 + (sweep * i) / 32)));
  };
  const out: V3[][] = [];
  for (const p of profiles as Prof2[]) {
    if (p.kind === "circle") out.push(Array.from({ length: 65 }, (_, i) => to3(p.cx + p.r * Math.cos((i / 64) * 2 * Math.PI), p.cy + p.r * Math.sin((i / 64) * 2 * Math.PI))));
    else out.push(p.segs.flatMap((g, i) => (i ? seg(g).slice(1) : seg(g))));
  }
  for (const ch of chains as Seg2[][]) out.push(ch.flatMap((g, i) => (i ? seg(g).slice(1) : seg(g))));
  return out;
}
