/**
 * AssemblyViewer — many placed instances of exact B-rep parts (topo.json per part, shared geometry), Z-up and
 * orthographic like the Studio viewer. Instance placements are rigid 3x4 transforms; the exploded view adds a
 * per-instance offset. Picks report (instance, local face/edge id) so mates can reference exact part geometry.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { DARK, LIGHT, type Palette } from "@/viewer/engine";
import type { Topo } from "@/viewer/types";
import type { V3 } from "./types";

export interface AsmPick { inst: string; kind: "face" | "edge"; id: number; point: V3 }
/** ``tone: "placeholder"`` draws an envelope body translucent orange (Design Office placeholders, CD-013). */
export interface InstSpec { id: string; part: string; T: number[]; visible: boolean; fastener: boolean; tone?: "placeholder" }
export type AsmView = "Iso" | "Front" | "Top" | "Right" | "Back" | "Bottom" | "Left";
export interface FaceMark { inst: string; faces: number[]; color: number; opacity?: number }

const Z_UP = new THREE.Vector3(0, 0, 1);
const VIEWS: Record<AsmView, [V3, V3]> = {
  Iso: [[1, -1, 0.85], [0, 0, 1]], Front: [[0, -1, 0], [0, 0, 1]], Back: [[0, 1, 0], [0, 0, 1]],
  Top: [[0, 0, 1], [0, 1, 0]], Bottom: [[0, 0, -1], [0, -1, 0]], Right: [[1, 0, 0], [0, 0, 1]], Left: [[-1, 0, 0], [0, 0, 1]],
};
const FASTENER = { light: 0x8f99a8, dark: 0x7d8796 };
const PLACEHOLDER = 0xf08c2e;
const FIT_MS = 900;

interface PartGeo { topo: Topo; faces: THREE.BufferGeometry; triFace: Int32Array; edges: THREE.BufferGeometry }
interface InstObj {
  id: string; part: string; group: THREE.Group; mesh: THREE.Mesh; edges: THREE.LineSegments;
  base: THREE.Matrix4; mat: THREE.MeshStandardMaterial; fastener: boolean; visible: boolean; tone?: "placeholder";
}

function m4(T: number[]): THREE.Matrix4 {
  const m = new THREE.Matrix4();
  m.set(T[0]!, T[1]!, T[2]!, T[3]!, T[4]!, T[5]!, T[6]!, T[7]!, T[8]!, T[9]!, T[10]!, T[11]!, 0, 0, 0, 1);
  return m;
}

export class AssemblyViewer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e6, 1e6);
  private controls: OrbitControls;
  private ro: ResizeObserver;
  private pal: Palette;
  private dark: boolean;
  private parts = new Map<string, PartGeo>();
  private insts = new Map<string, InstObj>();
  private offsets: Record<string, V3> = {};
  private explodeF = 0;
  private selected = new Set<string>();
  private hot = new Set<string>();
  private picking: Set<"face" | "edge"> = new Set();
  private edgeMat: THREE.LineBasicMaterial;
  private overlays: { picks: THREE.Object3D[]; hover: THREE.Object3D[]; marks: THREE.Object3D[]; clash: THREE.Object3D[]; measure: THREE.Object3D[] } =
    { picks: [], hover: [], marks: [], clash: [], measure: [] };
  private lineMats: LineMaterial[] = [];
  private ray = new THREE.Raycaster();
  private radius = 100;
  private downAt: [number, number] | null = null;
  private lastPicks: AsmPick[] = [];
  private lastMarks: FaceMark[] = [];
  private fitted = false;
  private anims = new Map<string, number>();
  onHover?: (p: AsmPick | null) => void;
  onClick?: (p: AsmPick | null, e: PointerEvent) => void;
  /** Drag gizmo released: the instance's new rigid placement (3x4, row-major) for the server to re-solve. */
  onDrag?: (id: string, T: number[]) => void;
  private tc: TransformControls;
  private tcHelper: THREE.Object3D;
  private pivot = new THREE.Object3D();
  private pivotStart = new THREE.Matrix4();
  private dragId: string | null = null;
  private dragBase = new THREE.Matrix4();

  constructor(private el: HTMLElement, dark: boolean) {
    this.dark = dark;
    this.pal = dark ? DARK : LIGHT;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(this.renderer.domElement);
    this.camera.up.copy(Z_UP);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.15;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a3, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 1.5); key.position.set(2, -3, 5); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.55); fill.position.set(-4, 3, -2); this.scene.add(fill);
    const head = new THREE.DirectionalLight(0xffffff, 0.6); this.camera.add(head); this.scene.add(this.camera);
    this.edgeMat = new THREE.LineBasicMaterial({ color: this.pal.edge });
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(el); this.resize();
    const dom = this.renderer.domElement;
    dom.addEventListener("pointermove", this.onMove);
    dom.addEventListener("pointerdown", this.onDown);
    dom.addEventListener("pointerup", this.onUp);
    dom.addEventListener("pointerleave", () => { this.drop("hover"); this.onHover?.(null); });
    this.tc = new TransformControls(this.camera, dom);
    this.tc.setRotationSnap(THREE.MathUtils.degToRad(15));
    this.tc.setSize(0.8);
    this.tcHelper = this.tc.getHelper();
    this.tcHelper.visible = false;
    this.scene.add(this.pivot, this.tcHelper);
    this.tc.addEventListener("dragging-changed", e => {
      const dragging = !!e.value;
      this.controls.enabled = !dragging;
      if (dragging) { this.pivot.updateMatrixWorld(true); this.pivotStart.copy(this.pivot.matrixWorld); return; }
      const o = this.dragId ? this.insts.get(this.dragId) : undefined;
      if (!o) return;
      const T = this.dragDelta().multiply(this.dragBase);
      const m = T.elements; // column-major
      this.onDrag?.(o.id, [m[0]!, m[4]!, m[8]!, m[12]!, m[1]!, m[5]!, m[9]!, m[13]!, m[2]!, m[6]!, m[10]!, m[14]!]);
    });
    this.tc.addEventListener("objectChange", () => {
      const o = this.dragId ? this.insts.get(this.dragId) : undefined;
      if (!o) return;
      o.group.matrix.copy(this.dragDelta().multiply(this.dragBase));
      o.group.matrixWorldNeedsUpdate = true;
    });
    this.renderer.setAnimationLoop(() => { this.controls.update(); this.stepAnims(); this.renderer.render(this.scene, this.camera); });
  }

  private dragDelta(): THREE.Matrix4 {
    this.pivot.updateMatrixWorld(true);
    return this.pivot.matrixWorld.clone().multiply(this.pivotStart.clone().invert());
  }

  /** Show a move (translate) or rotate gizmo on one instance, at its centre; null hides it. Free directions only
   * stay where they are dropped: the server re-solves the mates after every drop. */
  setGizmo(id: string | null, mode: "translate" | "rotate" = "translate") {
    const o = id ? this.insts.get(id) : undefined;
    if (!o || !o.visible || this.explodeF > 1e-6) {
      this.tc.detach(); this.tcHelper.visible = false; this.dragId = null; return;
    }
    if (this.tc.dragging) return;
    this.dragId = o.id;
    this.dragBase.copy(o.base);
    const c = new THREE.Box3().setFromObject(o.group).getCenter(new THREE.Vector3());
    this.pivot.position.copy(c); this.pivot.quaternion.identity(); this.pivot.scale.set(1, 1, 1);
    this.pivot.updateMatrixWorld(true);
    this.tc.setMode(mode);
    this.tc.attach(this.pivot);
    this.tcHelper.visible = true;
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.ro.disconnect();
    this.tc.detach(); this.tc.dispose();
    this.controls.dispose();
    for (const p of this.parts.values()) { p.faces.dispose(); p.edges.dispose(); }
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  // ---------------------------------------------------------------- content
  hasPart(key: string) { return this.parts.has(key); }

  addPart(key: string, topo: Topo) {
    if (this.parts.has(key)) return;
    const pos: number[] = [], idx: number[] = [], tri: number[] = [];
    for (const f of topo.faces) {
      const b = pos.length / 3;
      pos.push(...f.pos);
      for (let i = 0; i < f.idx.length; i += 3) { idx.push(b + f.idx[i]!, b + f.idx[i + 1]!, b + f.idx[i + 2]!); tri.push(f.id); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
    const seg: number[] = [];
    for (const e of topo.edges) for (let i = 0; i + 5 < e.pts.length; i += 3) seg.push(...e.pts.slice(i, i + 6));
    const eg = new THREE.BufferGeometry(); eg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
    this.parts.set(key, { topo, faces: g, triFace: Int32Array.from(tri), edges: eg });
  }

  setInstances(list: InstSpec[]) {
    const keep = new Set(list.map(i => i.id));
    for (const [id, o] of this.insts) if (!keep.has(id)) { this.scene.remove(o.group); o.mat.dispose(); this.insts.delete(id); }
    for (const s of list) {
      const geo = this.parts.get(s.part);
      if (!geo) continue;
      let o = this.insts.get(s.id);
      if (o && o.part !== s.part) { this.scene.remove(o.group); o.mat.dispose(); this.insts.delete(s.id); o = undefined; }
      if (!o) {
        const mat = new THREE.MeshStandardMaterial({ color: this.pal.face, metalness: 0.25, roughness: 0.5, side: THREE.DoubleSide,
          polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
        const mesh = new THREE.Mesh(geo.faces, mat);
        mesh.userData.inst = s.id;
        const edges = new THREE.LineSegments(geo.edges, this.edgeMat);
        const group = new THREE.Group(); group.matrixAutoUpdate = false; group.add(mesh, edges);
        this.scene.add(group);
        o = { id: s.id, part: s.part, group, mesh, edges, base: new THREE.Matrix4(), mat, fastener: s.fastener, visible: true };
        this.insts.set(s.id, o);
      }
      o.base = m4(s.T); o.fastener = s.fastener; o.visible = s.visible; o.tone = s.tone;
      o.group.visible = s.visible;
      this.place(o); this.tint(o);
    }
    this.refreshOverlays();
    if (!this.fitted && this.insts.size) { this.fitted = true; this.setView("Iso"); }
  }

  /** A part just replaced its placeholder: it drops into place and glows briefly (call only without reduced motion). */
  animateFit(id: string) {
    if (this.insts.has(id)) this.anims.set(id, performance.now());
  }

  private stepAnims() {
    if (!this.anims.size) return;
    const now = performance.now();
    for (const [id, t0] of this.anims) {
      const o = this.insts.get(id);
      if (!o) { this.anims.delete(id); continue; }
      const k = Math.min(1, (now - t0) / FIT_MS);
      if (k >= 1) this.anims.delete(id);
      this.place(o); this.tint(o);
    }
  }

  private place(o: InstObj) {
    const off = this.offsets[o.id] ?? [0, 0, 0];
    const t0 = this.anims.get(o.id);
    const k = t0 === undefined ? 1 : Math.min(1, (performance.now() - t0) / FIT_MS);
    const lift = (1 - (1 - Math.pow(1 - k, 3))) * this.radius * 0.18;   // ease-out drop from above
    const t = new THREE.Matrix4().makeTranslation(off[0] * this.explodeF, off[1] * this.explodeF, off[2] * this.explodeF + lift);
    o.group.matrix.copy(t.multiply(o.base));
    o.group.matrixWorldNeedsUpdate = true;
    o.group.updateMatrixWorld(true);
  }

  private tint(o: InstObj) {
    const ph = o.tone === "placeholder";
    const base = ph ? PLACEHOLDER : o.fastener ? (this.dark ? FASTENER.dark : FASTENER.light) : this.pal.face;
    const c = new THREE.Color(base);
    if (this.selected.has(o.id)) c.lerp(new THREE.Color(this.pal.select), 0.4);
    if (this.hot.has(o.id)) c.lerp(new THREE.Color(0xd93a3a), 0.65);
    o.mat.color.copy(c);
    o.mat.metalness = o.fastener ? 0.55 : ph ? 0.05 : 0.25;
    o.mat.roughness = o.fastener ? 0.38 : ph ? 0.8 : 0.5;
    if (o.mat.transparent !== ph || (ph && o.mat.opacity !== 0.4)) {
      o.mat.transparent = ph; o.mat.opacity = ph ? 0.4 : 1; o.mat.depthWrite = !ph; o.mat.needsUpdate = true;
    }
    const t0 = this.anims.get(o.id);
    const glow = t0 === undefined ? 0 : Math.max(0, 1 - (performance.now() - t0) / FIT_MS);
    o.mat.emissive.setRGB(0.12 * glow, 0.55 * glow, 0.25 * glow);
  }

  setExplode(offsets: Record<string, V3>, f: number) {
    this.offsets = offsets; this.explodeF = f;
    for (const o of this.insts.values()) this.place(o);
    this.refreshOverlays();
    for (const c of this.overlays.clash) c.visible = f < 1e-6;
    for (const c of this.overlays.measure) c.visible = f < 1e-6;
  }

  setSelected(ids: string[]) {
    this.selected = new Set(ids);
    for (const o of this.insts.values()) this.tint(o);
  }

  /** Parts in a collision (motion check): tinted red. */
  setHot(ids: string[]) {
    this.hot = new Set(ids);
    for (const o of this.insts.values()) this.tint(o);
  }

  setGhost(ids: Set<string> | null) {
    for (const o of this.insts.values()) {
      const g = !!ids && !ids.has(o.id);
      o.mat.transparent = g; o.mat.opacity = g ? 0.16 : 1; o.mat.depthWrite = !g; o.mat.needsUpdate = true;
      o.edges.visible = !g;
    }
  }

  // ---------------------------------------------------------------- overlays
  private add(kind: keyof AssemblyViewer["overlays"], o: THREE.Object3D) { this.scene.add(o); this.overlays[kind].push(o); }
  private drop(kind: keyof AssemblyViewer["overlays"]) {
    for (const o of this.overlays[kind]) {
      this.scene.remove(o);
      o.traverse(x => {
        const m = (x as THREE.Mesh).material as THREE.Material | undefined;
        if (m && this.lineMats.includes(m as LineMaterial)) this.lineMats.splice(this.lineMats.indexOf(m as LineMaterial), 1);
        if ((x as THREE.Mesh).geometry && !(x as THREE.Mesh).userData.shared) (x as THREE.Mesh).geometry.dispose();
        m?.dispose();
      });
    }
    this.overlays[kind] = [];
  }

  private fatLine(pts: number[], color: number, width: number, dashed = false) {
    const g = new LineGeometry(); g.setPositions(pts);
    const m = new LineMaterial({ color, linewidth: width, depthTest: false, transparent: true, dashed,
      dashSize: this.radius / 40, gapSize: this.radius / 80 });
    const r = this.el.getBoundingClientRect(); m.resolution.set(r.width, r.height);
    this.lineMats.push(m);
    const l = new Line2(g, m); l.computeLineDistances(); l.renderOrder = 10;
    return l;
  }

  private faceObj(inst: InstObj, fid: number, color: number, opacity: number) {
    const f = this.parts.get(inst.part)!.topo.faces[fid];
    if (!f) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(f.pos, 3)); g.setIndex(f.idx);
    const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    const o = new THREE.Mesh(g, m); o.renderOrder = 5;
    o.matrixAutoUpdate = false; o.matrix.copy(inst.group.matrix);
    return o;
  }

  private pickObjs(p: AsmPick, color: number, strong: boolean): THREE.Object3D[] {
    const inst = this.insts.get(p.inst);
    if (!inst) return [];
    if (p.kind === "face") { const o = this.faceObj(inst, p.id, color, strong ? 0.5 : 0.32); return o ? [o] : []; }
    const e = this.parts.get(inst.part)!.topo.edges[p.id];
    if (!e) return [];
    const pts: number[] = [];
    for (let i = 0; i < e.pts.length; i += 3) {
      const v = new THREE.Vector3(e.pts[i], e.pts[i + 1], e.pts[i + 2]).applyMatrix4(inst.group.matrix);
      pts.push(v.x, v.y, v.z);
    }
    return [this.fatLine(pts, color, strong ? 4 : 3.5)];
  }

  setPicks(picks: AsmPick[]) {
    this.lastPicks = picks;
    this.drop("picks");
    for (const p of picks) for (const o of this.pickObjs(p, this.pal.select, true)) this.add("picks", o);
  }

  setMarks(marks: FaceMark[]) {
    this.lastMarks = marks;
    this.drop("marks");
    for (const mk of marks) {
      const inst = this.insts.get(mk.inst);
      if (!inst || !inst.visible) continue;
      for (const fid of mk.faces) { const o = this.faceObj(inst, fid, mk.color, mk.opacity ?? 0.45); if (o) this.add("marks", o); }
    }
  }

  private refreshOverlays() {
    if (this.lastPicks.length) this.setPicks(this.lastPicks);
    if (this.lastMarks.length) this.setMarks(this.lastMarks);
  }

  /** Interference volumes (world coordinates) in red; hidden while exploded. */
  setClashes(meshes: { pos: number[]; idx: number[] }[], focus: number | null) {
    this.drop("clash");
    meshes.forEach((mesh, k) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(mesh.pos, 3)); g.setIndex(mesh.idx); g.computeVertexNormals();
      const on = focus === null || focus === k;
      const m = new THREE.MeshBasicMaterial({ color: 0xd8312a, transparent: true, opacity: on ? 0.85 : 0.35, depthTest: false, side: THREE.DoubleSide });
      const o = new THREE.Mesh(g, m); o.renderOrder = 8; o.visible = this.explodeF < 1e-6;
      this.add("clash", o);
      const wire = new THREE.LineSegments(new THREE.EdgesGeometry(g, 30), new THREE.LineBasicMaterial({ color: 0x8a0f0a, depthTest: false }));
      wire.renderOrder = 9; wire.visible = o.visible;
      this.add("clash", wire);
    });
  }

  /** Minimum-distance line between two points (clearance), with end dots. */
  setMeasure(a: V3 | null, b: V3 | null, color = 0x1f8f5a) {
    this.drop("measure");
    if (!a || !b) return;
    const l = this.fatLine([...a, ...b], color, 2.5, true);
    l.visible = this.explodeF < 1e-6;
    this.add("measure", l);
    for (const p of [a, b]) {
      const g = new THREE.SphereGeometry(this.radius / 160, 12, 8);
      const s = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color, depthTest: false })); s.position.set(...p); s.renderOrder = 11;
      s.visible = l.visible;
      this.add("measure", s);
    }
  }

  // ---------------------------------------------------------------- camera
  private resize() {
    const r = this.el.getBoundingClientRect();
    const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
    this.renderer.setSize(w, h, false);
    this.frustum();
    this.lineMats.forEach(m => m.resolution.set(w, h));
  }

  private frustum() {
    const r = this.el.getBoundingClientRect();
    const aspect = Math.max(r.width, 1) / Math.max(r.height, 1);
    const half = this.radius * 1.15;
    const hh = aspect >= 1 ? half : half / aspect;
    Object.assign(this.camera, { left: -hh * aspect, right: hh * aspect, top: hh, bottom: -hh, near: -this.radius * 60, far: this.radius * 60 });
    this.camera.updateProjectionMatrix();
  }

  private box(): THREE.Box3 {
    const b = new THREE.Box3();
    for (const o of this.insts.values()) if (o.visible) b.expandByObject(o.group);
    if (b.isEmpty()) b.set(new THREE.Vector3(-50, -50, -50), new THREE.Vector3(50, 50, 50));
    return b;
  }

  setView(name: AsmView) {
    const [d, up] = VIEWS[name];
    const b = this.box();
    const c = b.getCenter(new THREE.Vector3());
    this.radius = Math.max(b.getSize(new THREE.Vector3()).length() / 2, 1);
    this.frustum();
    const dir = new THREE.Vector3(...d).normalize();
    this.camera.up.set(...up);
    this.camera.position.copy(c).addScaledVector(dir, this.radius * 4);
    this.camera.lookAt(c);
    this.controls.target.copy(c);
    this.camera.zoom = 1; this.camera.updateProjectionMatrix();
    this.controls.update();
    this.fitZoom(b);
  }

  fit() {
    const b = this.box();
    const c = b.getCenter(new THREE.Vector3());
    const shift = c.clone().sub(this.controls.target);
    this.camera.position.add(shift); this.controls.target.copy(c);
    this.radius = Math.max(b.getSize(new THREE.Vector3()).length() / 2, 1);
    this.frustum(); this.controls.update();
    this.fitZoom(b);
  }

  private fitZoom(b: THREE.Box3) {
    this.camera.updateMatrixWorld();
    const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
    const c = b.getCenter(new THREE.Vector3());
    let w = 0, h = 0;
    for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) {
      const v = new THREE.Vector3(x, y, z).sub(c);
      w = Math.max(w, Math.abs(v.dot(right))); h = Math.max(h, Math.abs(v.dot(up)));
    }
    w = Math.max(w, this.radius * 0.02); h = Math.max(h, this.radius * 0.02);
    const halfW = (this.camera.right - this.camera.left) / 2, halfH = (this.camera.top - this.camera.bottom) / 2;
    this.camera.zoom = Math.min(halfW / w, halfH / h) * 0.8;
    this.camera.updateProjectionMatrix();
  }

  /** Screen position (px) of a world point, for HTML labels. */
  project(p: V3): { x: number; y: number } | null {
    const r = this.el.getBoundingClientRect();
    const v = new THREE.Vector3(...p).project(this.camera);
    if (Math.abs(v.z) > 1) return null;
    return { x: (v.x + 1) / 2 * r.width, y: (1 - v.y) / 2 * r.height };
  }

  /** Isometric, fitted, overlay-free snapshot (for the assembly list); restores the user's view afterwards. */
  thumbnail(w = 640, h = 480): string | null {
    if (!this.insts.size) return null;
    const saved = { pos: this.camera.position.clone(), up: this.camera.up.clone(), zoom: this.camera.zoom,
      target: this.controls.target.clone(), radius: this.radius, explode: this.explodeF, selected: this.selected };
    const hidden: THREE.Object3D[] = [];
    for (const list of Object.values(this.overlays)) for (const o of list) if (o.visible) { o.visible = false; hidden.push(o); }
    this.selected = new Set();
    this.explodeF = 0;
    for (const o of this.insts.values()) { this.tint(o); this.place(o); }
    this.setView("Iso");
    this.renderer.render(this.scene, this.camera);
    const src = this.renderer.domElement;
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const s = Math.min(w / src.width, h / src.height) * 1.4;
    c.getContext("2d")!.drawImage(src, (w - src.width * s) / 2, (h - src.height * s) / 2, src.width * s, src.height * s);
    const url = c.toDataURL("image/png");
    hidden.forEach(o => { o.visible = true; });
    this.selected = saved.selected; this.explodeF = saved.explode;
    for (const o of this.insts.values()) { this.tint(o); this.place(o); }
    this.radius = saved.radius; this.frustum();
    this.camera.position.copy(saved.pos); this.camera.up.copy(saved.up); this.camera.zoom = saved.zoom;
    this.controls.target.copy(saved.target); this.camera.lookAt(saved.target); this.camera.updateProjectionMatrix();
    this.controls.update();
    return url;
  }

  // ---------------------------------------------------------------- picking
  /** The instance under the pointer, translucent placeholders included (for status tooltips). */
  instanceAt(clientX: number, clientY: number): string | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const nx = ((clientX - r.left) / r.width) * 2 - 1, ny = -((clientY - r.top) / r.height) * 2 + 1;
    this.ray.setFromCamera(new THREE.Vector2(nx, ny), this.camera);
    const hit = this.ray.intersectObjects([...this.insts.values()].filter(o => o.visible).map(o => o.mesh), false)[0];
    return hit ? (hit.object.userData.inst as string) : null;
  }

  setPicking(kinds: ("face" | "edge")[]) {
    this.picking = new Set(kinds);
    if (!kinds.length) this.drop("hover");
  }

  private pickAt(e: PointerEvent): AsmPick | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const nx = ((e.clientX - r.left) / r.width) * 2 - 1, ny = -((e.clientY - r.top) / r.height) * 2 + 1;
    this.ray.setFromCamera(new THREE.Vector2(nx, ny), this.camera);
    const meshes = [...this.insts.values()].filter(o => o.visible && !o.mat.transparent).map(o => o.mesh);
    const hit = this.ray.intersectObjects(meshes, false)[0];
    if (!hit) return null;
    const inst = this.insts.get(hit.object.userData.inst as string)!;
    const geo = this.parts.get(inst.part)!;
    const fid = geo.triFace[hit.faceIndex ?? 0]!;
    const inv = inst.group.matrix.clone().invert();
    const local = hit.point.clone().applyMatrix4(inv);
    if (this.picking.has("edge")) {
      const cursor = { x: e.clientX - r.left, y: e.clientY - r.top };
      let best: { d: number; id: number } | null = null;
      for (const eid of geo.topo.faces[fid]!.edges) {
        const ed = geo.topo.edges[eid]!;
        if (ed.type === "curve") continue;
        const p = ed.pts;
        for (let i = 0; i + 5 < p.length; i += 3) {
          const a = new THREE.Vector3(p[i], p[i + 1], p[i + 2]).applyMatrix4(inst.group.matrix).project(this.camera);
          const b = new THREE.Vector3(p[i + 3], p[i + 4], p[i + 5]).applyMatrix4(inst.group.matrix).project(this.camera);
          const ax = (a.x + 1) / 2 * r.width, ay = (1 - a.y) / 2 * r.height, bx = (b.x + 1) / 2 * r.width, by = (1 - b.y) / 2 * r.height;
          const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1;
          const t = THREE.MathUtils.clamp(((cursor.x - ax) * dx + (cursor.y - ay) * dy) / L2, 0, 1);
          const d = Math.hypot(ax + t * dx - cursor.x, ay + t * dy - cursor.y);
          if (d < 7 && (!best || d < best.d)) best = { d, id: eid };
        }
      }
      if (best) return { inst: inst.id, kind: "edge", id: best.id, point: [local.x, local.y, local.z] };
    }
    if (!this.picking.has("face")) return null;
    return { inst: inst.id, kind: "face", id: fid, point: [local.x, local.y, local.z] };
  }

  private onMove = (e: PointerEvent) => {
    if (e.buttons) return;
    const p = this.picking.size ? this.pickAt(e) : null;
    this.drop("hover");
    if (p) for (const o of this.pickObjs(p, this.pal.hover, false)) this.add("hover", o);
    this.renderer.domElement.style.cursor = p ? "crosshair" : "";
    this.onHover?.(p);
  };
  private onDown = (e: PointerEvent) => { this.downAt = [e.clientX, e.clientY]; };
  private onUp = (e: PointerEvent) => {
    if (!this.downAt || e.button !== 0) return;
    if (this.tc.axis !== null || this.tc.dragging) { this.downAt = null; return; }  // a gizmo click is not a pick
    const moved = Math.hypot(e.clientX - this.downAt[0], e.clientY - this.downAt[1]) > 4;
    this.downAt = null;
    if (moved) return;
    const savedPicking = this.picking;
    if (!this.picking.size) this.picking = new Set(["face"]);
    const p = this.pickAt(e);
    this.picking = savedPicking;
    this.onClick?.(p, e);
  };
}
