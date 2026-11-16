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
  sketch: "Extrude", revolve: "Revolve", pattern: "Pattern",
};
