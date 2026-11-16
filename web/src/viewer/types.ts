export type V3 = [number, number, number];

export interface TopoFace {
  id: number; solid: number; type: "plane" | "cylinder" | "cone" | "sphere" | "torus" | "freeform";
  area: number; center: V3; normal?: V3; axis?: V3; axis_point?: V3; radius?: number; semi_angle_deg?: number;
  feature?: string | null; pos: number[]; idx: number[]; edges: number[];
}
export interface TopoEdge {
  id: number; type: "line" | "circle" | "curve"; length: number; pts: number[]; faces: number[]; verts: number[];
  center?: V3; radius?: number; axis?: V3; full?: boolean;
}
export interface TopoSolid { id: number; label: string; faces: number[]; volume: number; center: V3 }
export interface Topo {
  units: "mm"; up: "Z"; bbox: [number, number, number, number, number, number];
  solids: TopoSolid[]; faces: TopoFace[]; edges: TopoEdge[]; vertices: V3[];
  features?: { name: string; kind: string; params: Record<string, unknown> }[];
}

export type Pick =
  | { kind: "vertex"; id: number; point: V3 }
  | { kind: "center"; edge: number; point: V3 }
  | { kind: "edge"; id: number; point: V3 }
  | { kind: "face"; id: number; point: V3 };

export type DisplayMode = "shaded-edges" | "shaded" | "hidden" | "wireframe";
export type Axis = "X" | "Y" | "Z";
export type ViewName = "Iso" | "Front" | "Back" | "Top" | "Bottom" | "Right" | "Left";

export interface SketchPreview {
  origin: V3; normal: V3; xDir: V3;
  kind: "rect" | "circle" | "lines"; w?: number; h?: number; r?: number; cx: number; cy: number;
  /** kind "lines": world-space polylines (e.g. saved sketches shown in the viewer) */
  lines?: V3[][];
}

export function pickKey(p: Pick): string {
  return p.kind === "center" ? `c${p.edge}` : `${p.kind[0]}${p.id}`;
}
