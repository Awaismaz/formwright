/**
 * The layout preview's geometry, built in the browser from the compact primitives the server sends (no CAD kernel):
 * boxes, solids and tubes of revolution (shafts with their steps, gear blanks at the tip circle and face width with
 * the pitch circle and one tick per tooth, bearing rings, retaining rings, screws as a shank and a head). Every body
 * is made in its own frame (Z = its axis) and placed by its 12-number transform. Pure functions: no three.js, no DOM
 * (tested in build.test.ts); ``scene3d.ts`` turns the arrays into meshes.
 */
import type { Resolved } from "@/viewer/dims";
import type { V3 } from "@/viewer/types";
import type { BodyGeom, BuildPath, PreviewBody, PreviewDim } from "./types";

/** Triangles (local frame, flat arrays) and feature lines (pairs of points). */
export interface Geo { pos: number[]; idx: number[]; edges: number[] }

export const PATH_COLOR: Record<BuildPath, string> = { spec: "#2a9d8f", toolbox: "#8d97a6", ai: "#7c6fd6" };
export const PATH_LABEL: Record<BuildPath, string> = {
  spec: "Built from the spec (no AI)", toolbox: "Toolbox standard part", ai: "AI designer models it",
};
export const ERROR_COLOR = "#e5484d";

/** Segments around a circle of radius r (smooth enough at any zoom, cheap for small screws). */
export function segmentsFor(r: number): number {
  return 4 * Math.max(4, Math.min(18, Math.round((12 + r * 0.9) / 4)));  // a multiple of 4: the quadrant points are exact
}

/**
 * A solid of revolution about Z from a profile of (r, z) points (an open polyline from the axis to the axis, or a
 * closed loop for a tube). Every profile segment gets its own ring of vertices, so the shading is smooth around the
 * axis and crisp at the steps; a feature circle is drawn at every profile corner off the axis.
 */
export function lathe(profile: [number, number][], closed: boolean, n: number): Geo {
  const pos: number[] = [], idx: number[] = [], edges: number[] = [];
  const pts = profile.filter((p, i) => i === 0 || Math.abs(p[0] - profile[i - 1]![0]) > 1e-9 || Math.abs(p[1] - profile[i - 1]![1]) > 1e-9);
  const segs: [[number, number], [number, number]][] = [];
  for (let i = 0; i + 1 < pts.length; i++) segs.push([pts[i]!, pts[i + 1]!]);
  if (closed && pts.length > 2) segs.push([pts[pts.length - 1]!, pts[0]!]);
  for (const [a, b] of segs) {
    if (a[0] < 1e-9 && b[0] < 1e-9) continue;
    const base = pos.length / 3;
    for (let k = 0; k <= n; k++) {
      const t = (2 * Math.PI * k) / n, c = Math.cos(t), s = Math.sin(t);
      pos.push(a[0] * c, a[0] * s, a[1], b[0] * c, b[0] * s, b[1]);
    }
    for (let k = 0; k < n; k++) {
      const i0 = base + 2 * k, i1 = i0 + 1, i2 = i0 + 2, i3 = i0 + 3;
      if (a[0] > 1e-9) idx.push(i0, i2, i1);
      if (b[0] > 1e-9) idx.push(i1, i2, i3);
    }
  }
  for (const [r, z] of pts) if (r > 1e-9) circle(edges, r, z, n);
  return { pos, idx, edges };
}

function circle(edges: number[], r: number, z: number, n: number) {
  for (let k = 0; k < n; k++) {
    const t0 = (2 * Math.PI * k) / n, t1 = (2 * Math.PI * (k + 1)) / n;
    edges.push(r * Math.cos(t0), r * Math.sin(t0), z, r * Math.cos(t1), r * Math.sin(t1), z);
  }
}

/** A centred box L x W x H: 6 flat faces (own vertices) and its 12 edges. */
export function box(L: number, W: number, H: number): Geo {
  const x = L / 2, y = W / 2, z = H / 2;
  const P: V3[] = [[-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z], [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z]];
  const F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]];
  const pos: number[] = [], idx: number[] = [], edges: number[] = [];
  for (const f of F) {
    const b = pos.length / 3;
    for (const i of f) pos.push(...P[i]!);
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  }
  for (const [a, c] of [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]] as const)
    edges.push(...P[a]!, ...P[c]!);
  return { pos, idx, edges };
}

/** Solid (bore 0) or bored disc of diameter d and length L, centred on Z 0. */
function disc(d: number, L: number, bore = 0): Geo {
  const r = d / 2, h = L / 2, n = segmentsFor(r);
  return bore > 1e-9 && bore < d ? lathe([[bore / 2, -h], [r, -h], [r, h], [bore / 2, h]], true, n)
    : lathe([[0, -h], [r, -h], [r, h], [0, h]], false, n);
}

/** The local geometry of one body. */
export function bodyGeo(b: BodyGeom): Geo {
  switch (b.kind) {
    case "box": case "key": return box(b.g.s[0], b.g.s[1], b.g.s[2]);
    case "cyl": return disc(b.g.d, b.g.L, b.g.bore ?? 0);
    case "ring": return disc(b.g.D, b.g.s, b.g.d);
    case "bearing": {
      const g = disc(b.g.D, b.g.B, b.g.d), n = segmentsFor(b.g.D / 2), w = (b.g.D - b.g.d) / 2;
      for (const z of [-b.g.B / 2, b.g.B / 2]) { circle(g.edges, b.g.d / 2 + 0.3 * w, z, n); circle(g.edges, b.g.D / 2 - 0.3 * w, z, n); }
      return g;
    }
    case "shaft": {
      const s = [...b.g.segs].sort((p, q) => p[0] - q[0]);
      if (!s.length) return { pos: [], idx: [], edges: [] };
      const prof: [number, number][] = [[0, s[0]![0]]];
      for (const [z0, z1, d] of s) prof.push([d / 2, z0], [d / 2, z1]);
      prof.push([0, s[s.length - 1]![1]]);
      return lathe(prof, false, segmentsFor(Math.max(...s.map(x => x[2])) / 2));
    }
    case "gear": {
      const { tip, pitch, width, bore, m, z } = b.g;
      const g = disc(tip, width, bore);
      const n = segmentsFor(tip / 2), root = Math.max(pitch / 2 - 1.25 * m, (bore || 0) / 2);
      for (const zz of [-width / 2, width / 2]) {
        circle(g.edges, pitch / 2, zz, n);   // the pitch circle on both faces
        for (let k = 0; k < z; k++) {          // one tick per tooth, root to tip (a blank that still reads as a gear)
          const t = (2 * Math.PI * k) / z;
          g.edges.push(root * Math.cos(t), root * Math.sin(t), zz, (tip / 2) * Math.cos(t), (tip / 2) * Math.sin(t), zz);
        }
      }
      return g;
    }
    case "screw": {
      const { d, L, head_d, head_h } = b.g;
      return lathe([[0, 0], [d / 2, 0], [d / 2, L], [head_d / 2, L], [head_d / 2, L + head_h], [0, L + head_h]], false, segmentsFor(head_d));
    }
  }
}

/** Same primitive, same geometry: copies (bearings, screws) share one buffer. */
export function geomKey(b: BodyGeom): string {
  return `${b.kind}:${JSON.stringify(b.g)}`;
}

/** A point of the body's frame in the program frame. */
export function apply(T: number[], p: V3 | number[]): V3 {
  return [0, 1, 2].map(r => T[4 * r]! * p[0]! + T[4 * r + 1]! * p[1]! + T[4 * r + 2]! * p[2]! + T[4 * r + 3]!) as V3;
}

/** The program-frame box of the drawn bodies [x0, y0, z0, x1, y1, z1] (exact on the tessellation). */
export function worldBounds(bodies: PreviewBody[], cache = new Map<string, Geo>()): [number, number, number, number, number, number] {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const b of bodies) {
    const k = geomKey(b);
    let g = cache.get(k);
    if (!g) { g = bodyGeo(b); cache.set(k, g); }
    for (let i = 0; i + 2 < g.pos.length; i += 3) {
      const w = apply(b.T, [g.pos[i]!, g.pos[i + 1]!, g.pos[i + 2]!]);
      for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a]!, w[a]!); hi[a] = Math.max(hi[a]!, w[a]!); }
    }
  }
  if (!bodies.length) return [0, 0, 0, 0, 0, 0];
  return [lo[0]!, lo[1]!, lo[2]!, hi[0]!, hi[1]!, hi[2]!];
}

const unit = (v: V3): V3 => { const n = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / n, v[1] / n, v[2] / n]; };

/** The preview's dimensions in the viewport dimension layout's terms (DS-038, ``viewer/dims.ts``). */
export function toResolved(dims: PreviewDim[]): Resolved[] {
  const out: Resolved[] = [];
  for (const d of dims) {
    if (d.kind === "linear") {
      const u: V3 = [d.b[0] - d.a[0], d.b[1] - d.a[1], d.b[2] - d.a[2]];
      const s = Math.hypot(u[0], u[1], u[2]);
      if (s > 1e-6) out.push({ param: d.id, kind: "linear", A: [...d.a], B: [...d.b], u: unit(u), s, faces: [] });
    } else if (d.kind === "diameter") {
      out.push({ param: d.id, kind: "round", sym: "Ø", circles: [{ c: d.c, axis: unit(d.axis), r: d.r }], count: 1, faces: [] });
    } else {
      out.push({ param: d.id, kind: "tag", tag: "label", at: [d.at], faces: [] });
    }
  }
  return out;
}

/** Which dimensions to draw: the key ones always (centre distances, envelope, seat diameters, bolt circles), part
 * sizes for the part under the cursor (or all of them when asked). */
export function visibleDims(dims: PreviewDim[], hot: string | null, all: boolean): PreviewDim[] {
  return dims.filter(d => d.prio === 1 || all || (hot !== null && d.items.includes(hot)));
}

/** Plan rows by item id: the stored plan by its ids, an edited plan by position (approval renumbers it) and name. */
export function itemOfRow(rows: Record<string, { name: string; at?: [number, number] }>, si: number, pi: number, name: string, sid: string, pid: string): string | null {
  const direct = `i_${sid}_${pid}`;
  if (rows[direct] && rows[direct]!.name.trim() === name.trim()) return direct;
  for (const [k, r] of Object.entries(rows)) if (r.at && r.at[0] === si && r.at[1] === pi && r.name.trim() === name.trim()) return k;
  for (const [k, r] of Object.entries(rows)) if (r.name.trim() === name.trim()) return k;
  return rows[direct] ? direct : null;
}

/** A short stable signature of anything JSON (query keys for live updates). */
export function sig(x: unknown): string {
  const s = JSON.stringify(x ?? null);
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}
