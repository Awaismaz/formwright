/**
 * PrintViewer: a print-bed view of a triangle mesh (Z-up, like the Studio viewer) with per-triangle overlays:
 * overhangs in red, a wall-thickness heatmap, the build plate grid and the printer's build-volume box.
 * The orientation preview applies the same rotation the export will use and drops the part onto the bed.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { DARK, LIGHT, type Palette } from "@/viewer/engine";

export interface PrintMesh { pos: Float32Array; idx: Uint32Array; thick: Float32Array }
export type Overlay = "shaded" | "overhang" | "thickness";
export interface ThickScale { min: number; warn: number; cap: number }
export type ViewDir = "Iso" | "Front" | "Top" | "Right" | "Underside";

const Z_UP = new THREE.Vector3(0, 0, 1);
const VIEWS: Record<ViewDir, [number, number, number, number, number, number]> = {
  Iso: [1, -1.2, 0.9, 0, 0, 1], Underside: [1, -1.2, -0.75, 0, 0, 1], Front: [0, -1, 0, 0, 0, 1], Top: [0, 0, 1, 0, 1, 0], Right: [1, 0, 0, 0, 0, 1],
};

export function parseMesh(buf: ArrayBuffer): PrintMesh {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "FWPM") throw new Error("Unexpected mesh data");
  const nv = dv.getUint32(4, true), nf = dv.getUint32(8, true);
  let o = 16;
  const pos = new Float32Array(buf.slice(o, o + nv * 12)); o += nv * 12;
  const idx = new Uint32Array(buf.slice(o, o + nf * 12)); o += nf * 12;
  const thick = new Float32Array(buf.slice(o, o + nf * 4));
  return { pos, idx, thick };
}

/** Heat colour for a wall thickness: red below the minimum, amber to the warning limit, then green → blue. */
export function thickColor(t: number, s: ThickScale): [number, number, number] {
  if (t < 0 || t >= s.cap) return [0.62, 0.68, 0.76];
  if (t < s.min) return [0.86, 0.16, 0.16];
  if (t < s.warn) return [0.96, 0.62, 0.1];
  const u = Math.min(1, (t - s.warn) / Math.max(s.cap - s.warn, 1e-6));
  return [0.2 + 0.0 * u, 0.7 - 0.25 * u, 0.35 + 0.55 * u];
}

export class PrintViewer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(30, 1, 0.1, 1e6);
  private controls: OrbitControls;
  private ro: ResizeObserver;
  private pal: Palette;
  private part = new THREE.Group();
  private geo: THREE.BufferGeometry | null = null;
  private mesh: THREE.Mesh | null = null;
  private edges: THREE.LineSegments | null = null;
  private bed = new THREE.Group();
  private data: PrintMesh | null = null;
  private normals: Float32Array = new Float32Array(0);
  private rot = new THREE.Matrix3();
  private printer: [number, number, number] = [220, 220, 250];
  private partBox = new THREE.Box3();

  constructor(private el: HTMLElement, dark: boolean) {
    this.pal = dark ? DARK : LIGHT;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(this.renderer.domElement);
    this.camera.up.copy(Z_UP);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.15;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a3, 1.25));
    const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(2, -3, 5); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5); fill.position.set(-4, 3, -2); this.scene.add(fill);
    const head = new THREE.DirectionalLight(0xffffff, 0.5); this.camera.add(head); this.scene.add(this.camera);
    this.scene.add(this.bed, this.part);
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(el); this.resize();
    this.renderer.setAnimationLoop(() => { this.controls.update(); this.renderer.render(this.scene, this.camera); });
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.ro.disconnect();
    this.controls.dispose();
    this.geo?.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  private resize() {
    const r = this.el.getBoundingClientRect();
    const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  load(m: PrintMesh) {
    this.data = m;
    if (this.mesh) { this.part.remove(this.mesh); this.geo?.dispose(); }
    if (this.edges) { this.part.remove(this.edges); this.edges.geometry.dispose(); }
    const nf = m.idx.length / 3;
    const pos = new Float32Array(nf * 9);
    this.normals = new Float32Array(nf * 3);
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
    for (let i = 0; i < nf; i++) {
      for (let k = 0; k < 3; k++) {
        const vi = m.idx[i * 3 + k]! * 3;
        pos[i * 9 + k * 3] = m.pos[vi]!; pos[i * 9 + k * 3 + 1] = m.pos[vi + 1]!; pos[i * 9 + k * 3 + 2] = m.pos[vi + 2]!;
      }
      a.fromArray(pos, i * 9); b.fromArray(pos, i * 9 + 3); c.fromArray(pos, i * 9 + 6);
      n.subVectors(b, a).cross(c.clone().sub(a)).normalize();
      this.normals[i * 3] = n.x; this.normals[i * 3 + 1] = n.y; this.normals[i * 3 + 2] = n.z;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(nf * 9), 3));
    g.computeVertexNormals();
    this.geo = g;
    this.mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.15, roughness: 0.6,
      side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
    const eg = new THREE.EdgesGeometry(g, 28);
    this.edges = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: this.pal.edge, transparent: true, opacity: 0.55 }));
    this.part.add(this.mesh, this.edges);
  }

  /** Apply the print orientation (row-major 3×3 from the analysis) and place the part centred on the bed. */
  setOrientation(r: number[][]) {
    this.rot.set(r[0]![0]!, r[0]![1]!, r[0]![2]!, r[1]![0]!, r[1]![1]!, r[1]![2]!, r[2]![0]!, r[2]![1]!, r[2]![2]!);
    const m4 = new THREE.Matrix4().setFromMatrix3(this.rot);
    this.part.matrixAutoUpdate = false;
    this.part.matrix.copy(m4);
    this.part.updateMatrixWorld(true);
    if (!this.data) return;
    const box = new THREE.Box3();
    const v = new THREE.Vector3();
    const p = this.data.pos;
    for (let i = 0; i < p.length; i += 3) { v.set(p[i]!, p[i + 1]!, p[i + 2]!).applyMatrix3(this.rot); box.expandByPoint(v); }
    const shift = new THREE.Vector3(this.printer[0] / 2 - (box.min.x + box.max.x) / 2, this.printer[1] / 2 - (box.min.y + box.max.y) / 2, -box.min.z);
    m4.premultiply(new THREE.Matrix4().makeTranslation(shift.x, shift.y, shift.z));
    this.part.matrix.copy(m4);
    this.part.updateMatrixWorld(true);
    this.partBox = box.translate(shift);
  }

  /** Per-triangle colours. Overhang rule matches the analysis: rotated n_z < -sin(angle), bed-contact excluded. */
  colour(mode: Overlay, overhangDeg: number, bedEps: number, scale: ThickScale) {
    if (!this.geo || !this.data) return;
    const col = this.geo.getAttribute("color") as THREE.BufferAttribute;
    const arr = col.array as Float32Array;
    const base = new THREE.Color(this.pal.face);
    const red = new THREE.Color(0xd9342b);
    const thr = -Math.sin(overhangDeg * Math.PI / 180);
    const nf = this.data.idx.length / 3;
    const pos = this.geo.getAttribute("position").array as Float32Array;
    const e = this.rot.elements; // column-major
    const z0 = mode === "overhang" ? this.rotZmin() : 0;
    for (let i = 0; i < nf; i++) {
      let rgb: [number, number, number] = [base.r, base.g, base.b];
      if (mode === "overhang") {
        const nx = this.normals[i * 3]!, ny = this.normals[i * 3 + 1]!, nz = this.normals[i * 3 + 2]!;
        const rz = e[2]! * nx + e[5]! * ny + e[8]! * nz;
        let zmax = -Infinity;
        for (let k = 0; k < 3; k++) {
          const o = i * 9 + k * 3;
          const z = e[2]! * pos[o]! + e[5]! * pos[o + 1]! + e[8]! * pos[o + 2]!;
          zmax = Math.max(zmax, z);
        }
        const onBed = rz < -0.999 && zmax - z0 <= bedEps;
        if (rz < thr && !onBed) rgb = [red.r, red.g, red.b];
      } else if (mode === "thickness") {
        rgb = thickColor(this.data.thick[i]!, scale);
      }
      for (let k = 0; k < 3; k++) { arr[i * 9 + k * 3] = rgb[0]; arr[i * 9 + k * 3 + 1] = rgb[1]; arr[i * 9 + k * 3 + 2] = rgb[2]; }
    }
    col.needsUpdate = true;
  }

  private rotZmin(): number {
    if (!this.data) return 0;
    const e = this.rot.elements, p = this.data.pos;
    let z0 = Infinity;
    for (let i = 0; i < p.length; i += 3) z0 = Math.min(z0, e[2]! * p[i]! + e[5]! * p[i + 1]! + e[8]! * p[i + 2]!);
    return z0;
  }

  setPrinter(size: [number, number, number], showVolume: boolean) {
    this.printer = size;
    this.bed.clear();
    const [px, py, pz] = size;
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(px, py), new THREE.MeshBasicMaterial({ color: this.pal.bgFace, transparent: true, opacity: 0.4, side: THREE.DoubleSide, depthWrite: false }));
    plate.position.set(px / 2, py / 2, -0.01);
    this.bed.add(plate);
    const step = Math.max(px, py) > 400 ? 50 : 10;
    const minor: number[] = [], major: number[] = [];
    for (let x = 0; x <= px + 1e-6; x += step) (Math.round(x / step) % 5 === 0 ? major : minor).push(x, 0, 0, x, py, 0);
    for (let y = 0; y <= py + 1e-6; y += step) (Math.round(y / step) % 5 === 0 ? major : minor).push(0, y, 0, px, y, 0);
    const lines = (pts: number[], color: number, opacity: number) => {
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
    };
    this.bed.add(lines(minor, this.pal.hiddenEdge, 0.35), lines(major, this.pal.hiddenEdge, 0.7));
    if (showVolume) {
      const box = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(px, py, pz)),
        new THREE.LineDashedMaterial({ color: this.pal.select, dashSize: Math.max(px, py) / 60, gapSize: Math.max(px, py) / 90, transparent: true, opacity: 0.8 }));
      box.position.set(px / 2, py / 2, pz / 2); box.computeLineDistances();
      this.bed.add(box);
    }
    const ax = (to: [number, number, number], color: number) => lines([0, 0, 0, ...to], color, 1);
    const L = Math.min(px, py) * 0.12;
    this.bed.add(ax([L, 0, 0], 0xd9342b), ax([0, L, 0], 0x2f9e44), ax([0, 0, L], 0x1f5fbf));
  }

  view(dir: ViewDir, target: "part" | "volume" = "part") {
    const box = target === "part" && !this.partBox.isEmpty() ? this.partBox.clone()
      : new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(...this.printer));
    if (target === "part") box.expandByPoint(new THREE.Vector3(box.min.x, box.min.y, 0));
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1);
    const [dx, dy, dz, ux, uy, uz] = VIEWS[dir];
    const d = new THREE.Vector3(dx, dy, dz).normalize();
    const vHalf = THREE.MathUtils.degToRad(this.camera.fov / 2);
    const hHalf = Math.atan(Math.tan(vHalf) * this.camera.aspect);
    const dist = r / Math.sin(Math.min(vHalf, hHalf)) * 1.3;
    this.camera.position.copy(c).addScaledVector(d, dist);
    this.camera.up.set(ux, uy, uz);
    this.camera.near = dist / 100; this.camera.far = dist * 100; this.camera.updateProjectionMatrix();
    this.controls.target.copy(c);
    this.controls.update();
  }
}
