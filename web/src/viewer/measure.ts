import type { Pick, Topo, V3 } from "./types";

export interface MeasureRow { label: string; value: string; primary?: boolean }
export interface MeasureResult { title: string; rows: MeasureRow[]; line?: [V3, V3] }

const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const len = (a: V3) => Math.sqrt(dot(a, a));
const norm = (a: V3): V3 => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const f = (v: number, d = 3) => (Math.abs(v) < 5e-10 ? 0 : v).toFixed(d);
const mm = (v: number) => `${f(v)} mm`;
const deg = (rad: number) => `${f((rad * 180) / Math.PI, 2)}°`;
const pt = (p: V3) => `(${f(p[0], 2)}, ${f(p[1], 2)}, ${f(p[2], 2)})`;

export function describe(p: Pick, t: Topo): string {
  if (p.kind === "vertex") return `Vertex ${pt(p.point)}`;
  if (p.kind === "center") { const e = t.edges[p.edge]!; return `Circle centre ${pt(p.point)} · Ø${f(2 * (e.radius ?? 0))}`; }
  if (p.kind === "edge") {
    const e = t.edges[p.id]!;
    return e.type === "circle" ? `${e.full ? "Circle" : "Arc"} R${f(e.radius ?? 0)} (Ø${f(2 * (e.radius ?? 0))})` : e.type === "line" ? `Line ${mm(e.length)}` : `Curve ${mm(e.length)}`;
  }
  const fc = t.faces[p.id]!;
  if (fc.type === "plane") return `Planar face · ${f(fc.area, 1)} mm²`;
  if (fc.type === "cylinder") return `Cylindrical face Ø${f(2 * (fc.radius ?? 0))}`;
  return `${fc.type[0]!.toUpperCase() + fc.type.slice(1)} face · ${f(fc.area, 1)} mm²`;
}

/** Text a design agent can act on, with exact geometry (used for point-and-tell). */
export function agentDescriptor(p: Pick, t: Topo): string {
  if (p.kind === "vertex") return `vertex at ${pt(p.point)}`;
  if (p.kind === "center") { const e = t.edges[p.edge]!; return `centre of circular edge R${f(e.radius ?? 0)} at ${pt(p.point)}, axis ${pt(e.axis ?? [0, 0, 1])}`; }
  if (p.kind === "edge") {
    const e = t.edges[p.id]!;
    const mid = edgeMid(t, p.id);
    const feat = t.faces[e.faces[0] ?? -1]?.feature;
    if (e.type === "circle") return `${e.full ? "circular" : "arc"} edge R${f(e.radius ?? 0)} centre ${pt(e.center!)} axis ${pt(e.axis!)}, passes through ${pt(mid)}${feat ? `, on feature "${feat}"` : ""}`;
    const a = e.pts.slice(0, 3) as V3, b = e.pts.slice(-3) as V3;
    return `${e.type} edge length ${f(e.length)} mm from ${pt(a)} to ${pt(b)}, passes through ${pt(mid)}${feat ? `, on feature "${feat}"` : ""}`;
  }
  const fc = t.faces[p.id]!;
  const where = `picked at ${pt(p.point)}`;
  if (fc.type === "plane") return `planar face normal ${pt(fc.normal!)} area ${f(fc.area, 2)} mm², ${where}${fc.feature ? `, feature "${fc.feature}"` : ""}`;
  if (fc.type === "cylinder") return `cylindrical face R${f(fc.radius ?? 0)} axis ${pt(fc.axis!)} through ${pt(fc.axis_point!)}, ${where}${fc.feature ? `, feature "${fc.feature}"` : ""}`;
  return `${fc.type} face area ${f(fc.area, 2)} mm², ${where}`;
}

/** The point halfway along an edge (by arc length along its polyline). For a straight edge: the average of its
 *  two ends — never an end vertex, which would also touch the neighbouring edges (STU-01). */
export function edgeMid(t: Topo, id: number): V3 {
  const p = t.edges[id]!.pts;
  const n = p.length / 3;
  if (n < 2) return [p[0]!, p[1]!, p[2]!];
  const at = (i: number): V3 => [p[3 * i]!, p[3 * i + 1]!, p[3 * i + 2]!];
  const seg: number[] = [];
  let total = 0;
  for (let i = 1; i < n; i++) { const l = len(sub(at(i), at(i - 1))); seg.push(l); total += l; }
  let half = total / 2;
  for (let i = 1; i < n; i++) {
    const l = seg[i - 1]!;
    if (half <= l || i === n - 1) {
      const a = at(i - 1), b = at(i), k = l > 0 ? Math.min(1, half / l) : 0;
      return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
    }
    half -= l;
  }
  return at(0);
}

/** What kind of edge was picked (line direction / circle axis), so the kernel re-finds exactly that edge. */
export function edgeRef(t: Topo, id: number): { kind: "line" | "circle" | "other"; dir?: V3 } {
  const e = t.edges[id]!;
  if (e.type === "line") { const d = lineDir(t, id); return d ? { kind: "line", dir: d } : { kind: "line" }; }
  if (e.type === "circle" && e.axis) return { kind: "circle", dir: e.axis };
  return { kind: "other" };
}

function pointOf(p: Pick): V3 { return p.point; }

function lineDir(t: Topo, id: number): V3 | null {
  const e = t.edges[id]!;
  if (e.type !== "line") return null;
  return norm(sub(e.pts.slice(-3) as V3, e.pts.slice(0, 3) as V3));
}

export function measure(sel: Pick[], t: Topo): MeasureResult | null {
  if (!sel.length) return null;
  const [a, b] = sel;
  if (sel.length === 1 && a) {
    if (a.kind === "vertex" || a.kind === "center")
      return { title: describe(a, t), rows: [{ label: "X", value: mm(a.point[0]) }, { label: "Y", value: mm(a.point[1]) }, { label: "Z", value: mm(a.point[2]) }] };
    if (a.kind === "edge") {
      const e = t.edges[a.id]!;
      const rows: MeasureRow[] = [];
      if (e.type === "circle") {
        rows.push({ label: "Diameter", value: mm(2 * e.radius!), primary: true }, { label: "Radius", value: mm(e.radius!) });
        if (!e.full) rows.push({ label: "Arc length", value: mm(e.length) }, { label: "Arc angle", value: deg(e.length / e.radius!) });
        rows.push({ label: "Centre", value: pt(e.center!) });
      } else {
        rows.push({ label: "Length", value: mm(e.length), primary: true });
        const d = lineDir(t, a.id); if (d) rows.push({ label: "Direction", value: pt(d) });
      }
      return { title: describe(a, t), rows };
    }
    const fc = t.faces[a.id]!;
    const rows: MeasureRow[] = [{ label: "Area", value: `${f(fc.area, 3)} mm²`, primary: fc.type !== "cylinder" }];
    if (fc.type === "plane") rows.push({ label: "Normal", value: pt(fc.normal!) });
    if (fc.type === "cylinder") rows.unshift({ label: "Diameter", value: mm(2 * fc.radius!), primary: true }, { label: "Radius", value: mm(fc.radius!) }), rows.push({ label: "Axis", value: pt(fc.axis!) });
    if (fc.feature) rows.push({ label: "Feature", value: fc.feature });
    return { title: describe(a, t), rows };
  }
  if (!a || !b) return null;
  const isPlane = (p: Pick) => p.kind === "face" && t.faces[p.id]!.type === "plane";
  // plane ↔ plane
  if (isPlane(a) && isPlane(b)) {
    const fa = t.faces[(a as { id: number }).id]!, fb = t.faces[(b as { id: number }).id]!;
    const na = norm(fa.normal!), nb = norm(fb.normal!);
    const c = Math.min(1, Math.abs(dot(na, nb)));
    if (c > 0.999999) {
      const d = Math.abs(dot(sub(fb.center, fa.center), na));
      return { title: "Parallel faces", rows: [{ label: "Distance", value: mm(d), primary: true }], line: [a.point, [a.point[0] + na[0] * dot(sub(fb.center, a.point), na), a.point[1] + na[1] * dot(sub(fb.center, a.point), na), a.point[2] + na[2] * dot(sub(fb.center, a.point), na)]] };
    }
    return { title: "Faces", rows: [{ label: "Angle", value: deg(Math.acos(Math.min(1, Math.max(-1, dot(na, nb))))), primary: true }, { label: "Dihedral", value: deg(Math.PI - Math.acos(Math.min(1, Math.max(-1, dot(na, nb))))) }] };
  }
  // line ↔ line
  if (a.kind === "edge" && b.kind === "edge") {
    const da = lineDir(t, a.id), db = lineDir(t, b.id);
    if (da && db) {
      const c = Math.abs(dot(da, db));
      if (c > 0.999999) {
        const pa = t.edges[a.id]!.pts.slice(0, 3) as V3, pb = t.edges[b.id]!.pts.slice(0, 3) as V3;
        const w = sub(pb, pa); const d = len(cross(w, da));
        return { title: "Parallel edges", rows: [{ label: "Distance", value: mm(d), primary: true }] };
      }
      return { title: "Edges", rows: [{ label: "Angle", value: deg(Math.acos(Math.min(1, c))), primary: true }] };
    }
    const ea = t.edges[a.id]!, eb = t.edges[b.id]!;
    if (ea.type === "circle" && eb.type === "circle") {
      const d = sub(eb.center!, ea.center!);
      return { title: "Circle centres", rows: [{ label: "Centre distance", value: mm(len(d)), primary: true }, { label: "ΔX", value: mm(d[0]) }, { label: "ΔY", value: mm(d[1]) }, { label: "ΔZ", value: mm(d[2]) }], line: [ea.center!, eb.center!] };
    }
  }
  // point/anything ↔ plane : perpendicular distance
  const planeAndPoint = isPlane(a) && !isPlane(b) ? [a, b] : isPlane(b) && !isPlane(a) ? [b, a] : null;
  if (planeAndPoint && planeAndPoint[1]!.kind !== "face") {
    const pf = t.faces[(planeAndPoint[0] as { id: number }).id]!; const n = norm(pf.normal!);
    const p = pointOf(planeAndPoint[1]!); const d = dot(sub(p, pf.center), n);
    const foot: V3 = [p[0] - n[0] * d, p[1] - n[1] * d, p[2] - n[2] * d];
    return { title: "Point to plane", rows: [{ label: "Distance", value: mm(Math.abs(d)), primary: true }], line: [p, foot] };
  }
  // generic: point to point (vertices, centres, picked points)
  const pa = pointOf(a), pb = pointOf(b); const d = sub(pb, pa);
  return { title: `${describe(a, t)} → ${describe(b, t)}`, line: [pa, pb], rows: [
    { label: "Distance", value: mm(len(d)), primary: true }, { label: "ΔX", value: mm(Math.abs(d[0])) },
    { label: "ΔY", value: mm(Math.abs(d[1])) }, { label: "ΔZ", value: mm(Math.abs(d[2])) }] };
}
