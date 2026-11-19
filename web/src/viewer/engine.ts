/**
 * CadViewer — renders an exact B-rep topology (topo.json) the way CAD tools do:
 * Z-up, orthographic by default, real model edges (not mesh triangles), face/edge/vertex picking with
 * snapping, persistent selection, capped section, part explode, compare overlays.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import type { Axis, DisplayMode, Pick, SketchPreview, Topo, TopoEdge, V3, ViewName } from "./types";
import type { ViewCam } from "./dims";
import { pickKey } from "./types";

const Z_UP = new THREE.Vector3(0, 0, 1);
const VIEW_DIRS: Record<ViewName, [V3, V3]> = { // [camera direction from target, up]
  Iso: [[1, -1, 0.85], [0, 0, 1]], Front: [[0, -1, 0], [0, 0, 1]], Back: [[0, 1, 0], [0, 0, 1]],
  Top: [[0, 0, 1], [0, 1, 0]], Bottom: [[0, 0, -1], [0, -1, 0]], Right: [[1, 0, 0], [0, 0, 1]], Left: [[-1, 0, 0], [0, 0, 1]],
};
const AXIS: Record<Axis, THREE.Vector3> = { X: new THREE.Vector3(1, 0, 0), Y: new THREE.Vector3(0, 1, 0), Z: new THREE.Vector3(0, 0, 1) };

export interface Palette {
  face: number; edge: number; hiddenEdge: number; hover: number; select: number; bgFace: number; cap: [string, string];
}
export const LIGHT: Palette = { face: 0xb9c2cf, edge: 0x1d2330, hiddenEdge: 0x8a93a3, hover: 0xe07b24, select: 0x1f5fbf, bgFace: 0xf6f7f9, cap: ["#f2c49b", "#c8742e"] };
export const DARK: Palette = { face: 0x9aa5b6, edge: 0x0b0d12, hiddenEdge: 0x5a6375, hover: 0xf09a4a, select: 0x5691eb, bgFace: 0x262b33, cap: ["#5a3a1f", "#e0965a"] };

interface SolidRender {
  group: THREE.Group; mesh: THREE.Mesh; triFace: Int32Array; edges: THREE.LineSegments; hidden: THREE.LineSegments;
  stencils: THREE.Mesh[]; center: THREE.Vector3; mat: THREE.MeshStandardMaterial;
}

export interface ViewerEvents {
  onHover?: (p: Pick | null) => void;
  onClick?: (p: Pick | null, additive: boolean) => void;
}

function hatch(colors: [string, string]) {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = colors[0]; g.fillRect(0, 0, 64, 64);
  g.strokeStyle = colors[1]; g.lineWidth = 6;
  for (let i = -64; i <= 128; i += 16) { g.beginPath(); g.moveTo(i, 64); g.lineTo(i + 64, 0); g.stroke(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function dotTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 32;
  const g = c.getContext("2d")!;
  g.fillStyle = "#fff"; g.beginPath(); g.arc(16, 16, 12, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#000"; g.lineWidth = 3; g.stroke();
  return new THREE.CanvasTexture(c);
}

export class CadViewer {
  readonly el: HTMLElement;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private persp = new THREE.PerspectiveCamera(30, 1, 0.1, 1e7);
  private ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e6, 1e6);
  private camera: THREE.Camera;
  private controls: OrbitControls;
  private pal: Palette;
  private topo: Topo | null = null;
  private solids: SolidRender[] = [];
  private box = new THREE.Box3();
  private radius = 1;
  private display: DisplayMode = "shaded-edges";
  private orthoOn = true;
  private section = { on: false, axis: "Z" as Axis, t: 0.5, flip: false };
  private clip = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0);
  private capMat: THREE.MeshBasicMaterial;
  private cap: THREE.Mesh;
  private hatchTex: THREE.CanvasTexture;
  private backMat: THREE.MeshBasicMaterial;
  private frontMat: THREE.MeshBasicMaterial;
  private edgeMat: THREE.LineBasicMaterial;
  private hiddenMat: THREE.LineDashedMaterial;
  private hoverObjs: THREE.Object3D[] = [];
  private selObjs: THREE.Object3D[] = [];
  private markObjs: THREE.Object3D[] = [];
  private overlayObjs: THREE.Object3D[] = [];
  private featureObjs: THREE.Object3D[] = [];
  private sketchObj: THREE.Object3D | null = null;
  private comObj: THREE.Object3D | null = null;
  private dotTex = dotTexture();
  private lineMats: LineMaterial[] = [];
  private ray = new THREE.Raycaster();
  private picking: Set<Pick["kind"]> = new Set();
  private events: ViewerEvents;
  private ro: ResizeObserver;
  private downAt: [number, number] | null = null;
  private explode = 0;
  private hiddenParts = new Set<number>();
  private ghost = false;

  constructor(el: HTMLElement, dark: boolean, events: ViewerEvents = {}) {
    this.el = el;
    this.events = events;
    this.pal = dark ? DARK : LIGHT;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, stencil: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.localClippingEnabled = true;
    el.appendChild(this.renderer.domElement);
    this.persp.up.copy(Z_UP); this.ortho.up.copy(Z_UP);
    this.camera = this.ortho;
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.15;
    // SOLIDWORKS-style mouse: middle-drag rotates (left-drag too, for trackpads), Ctrl+middle or right-drag pans,
    // and the wheel zooms about the cursor (STU-12).
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.ROTATE, RIGHT: THREE.MOUSE.PAN };
    this.controls.zoomToCursor = true;
    this.buildTriad();
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a3, 1.35));
    const key = new THREE.DirectionalLight(0xffffff, 1.5); key.position.set(2, -3, 5); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.55); fill.position.set(-4, 3, -2); this.scene.add(fill);
    // headlight follows the camera so faces facing the viewer are always lit (CAD-like)
    const head = new THREE.DirectionalLight(0xffffff, 0.6); this.persp.add(head); this.ortho.add(head.clone());
    this.scene.add(this.persp, this.ortho);
    this.edgeMat = new THREE.LineBasicMaterial({ color: this.pal.edge });
    this.hiddenMat = new THREE.LineDashedMaterial({ color: this.pal.hiddenEdge, dashSize: 1, gapSize: 1, depthTest: false, transparent: true, opacity: 0.8 });
    const stencilBase = { depthWrite: false, depthTest: false, colorWrite: false, stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc };
    this.backMat = new THREE.MeshBasicMaterial({ ...stencilBase, side: THREE.BackSide, stencilFail: THREE.IncrementWrapStencilOp, stencilZFail: THREE.IncrementWrapStencilOp, stencilZPass: THREE.IncrementWrapStencilOp });
    this.frontMat = new THREE.MeshBasicMaterial({ ...stencilBase, side: THREE.FrontSide, stencilFail: THREE.DecrementWrapStencilOp, stencilZFail: THREE.DecrementWrapStencilOp, stencilZPass: THREE.DecrementWrapStencilOp });
    this.hatchTex = hatch(this.pal.cap);
    this.capMat = new THREE.MeshBasicMaterial({ map: this.hatchTex, side: THREE.DoubleSide, stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc, stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp });
    this.cap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), this.capMat);
    this.cap.renderOrder = 2; this.cap.visible = false;
    this.cap.onAfterRender = (r) => r.clearStencil();
    this.scene.add(this.cap);
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(el); this.resize();
    const dom = this.renderer.domElement;
    dom.addEventListener("pointermove", this.onMove);
    dom.addEventListener("pointerdown", this.onDown);
    dom.addEventListener("pointerup", this.onUp);
    dom.addEventListener("pointerleave", () => { this.clearHover(); this.events.onHover?.(null); });
    this.renderer.setAnimationLoop(() => { this.controls.update(); this.renderer.render(this.scene, this.camera); this.renderTriad(); this.notifyView(); });
  }

  // ---------------------------------------------------------------- screen-space overlays (viewport dimensions)
  private viewListeners = new Set<() => void>();
  private viewSig = "";
  /** Called after a frame whose camera, zoom or size changed (screen-space overlays follow the model). */
  onView(cb: () => void): () => void { this.viewListeners.add(cb); cb(); return () => { this.viewListeners.delete(cb); }; }
  private notifyView() {
    if (!this.viewListeners.size) return;
    const cam = this.camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
    const r = this.el.getBoundingClientRect();
    const sig = `${cam.matrixWorld.elements.map(x => x.toFixed(5)).join()}|${cam.projectionMatrix.elements.map(x => x.toFixed(6)).join()}|${r.width}x${r.height}|${this.topo?.bbox.join()}`;
    if (sig === this.viewSig) return;
    this.viewSig = sig;
    this.viewListeners.forEach(f => f());
  }
  /** The current camera as the dimension layout sees it: CSS-pixel projection and screen axes in model millimetres. */
  viewCam(): ViewCam {
    const cam = this.camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
    cam.updateMatrixWorld();
    const r = this.el.getBoundingClientRect();
    const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).normalize();
    const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1).normalize();
    const vd = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 2).normalize();
    const visibleH = cam === this.ortho ? (this.ortho.top - this.ortho.bottom) / this.ortho.zoom
      : 2 * this.persp.position.distanceTo(this.controls.target) * Math.tan(THREE.MathUtils.degToRad(this.persp.fov / 2));
    const v = new THREE.Vector3();
    return {
      project: (p: V3) => { v.set(p[0], p[1], p[2]).project(cam); return [(v.x + 1) / 2 * w, (1 - v.y) / 2 * h]; },
      vd: [vd.x, vd.y, vd.z], right: [right.x, right.y, right.z], up: [up.x, up.y, up.z],
      pxPerMm: h / Math.max(visibleH, 1e-9), width: w, height: h,
    };
  }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this.ro.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  setEvents(e: ViewerEvents) { this.events = e; }

  // ---------------------------------------------------------------- loading
  load(topo: Topo, keepView: boolean) {
    for (const s of this.solids) this.scene.remove(s.group);
    this.solids = [];
    this.topo = topo;
    const [x0, y0, z0, x1, y1, z1] = topo.bbox;
    this.box = new THREE.Box3(new THREE.Vector3(x0, y0, z0), new THREE.Vector3(x1, y1, z1));
    this.radius = Math.max(this.box.getSize(new THREE.Vector3()).length() / 2, 1e-3);
    this.hiddenMat.dashSize = this.radius / 60; this.hiddenMat.gapSize = this.radius / 90;
    const solidEdges = new Map<number, Set<number>>();
    for (const f of topo.faces) {
      const set = solidEdges.get(f.solid) ?? new Set<number>();
      f.edges.forEach(e => set.add(e)); solidEdges.set(f.solid, set);
    }
    for (const sol of topo.solids) {
      const pos: number[] = []; const idx: number[] = []; const triFace: number[] = [];
      for (const fid of sol.faces) {
        const f = topo.faces[fid]!;
        const base = pos.length / 3;
        pos.push(...f.pos);
        for (let i = 0; i < f.idx.length; i += 3) { idx.push(base + f.idx[i]!, base + f.idx[i + 1]!, base + f.idx[i + 2]!); triFace.push(fid); }
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      g.setIndex(idx);
      g.computeVertexNormals();
      const mat = new THREE.MeshStandardMaterial({ color: this.pal.face, metalness: 0.25, roughness: 0.5, side: THREE.DoubleSide,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, transparent: false });
      const mesh = new THREE.Mesh(g, mat);
      const seg: number[] = [];
      for (const eid of solidEdges.get(sol.id) ?? []) {
        const p = topo.edges[eid]!.pts;
        for (let i = 0; i + 5 < p.length; i += 3) seg.push(p[i]!, p[i + 1]!, p[i + 2]!, p[i + 3]!, p[i + 4]!, p[i + 5]!);
      }
      const eg = new THREE.BufferGeometry(); eg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
      const edges = new THREE.LineSegments(eg, this.edgeMat);
      const hidden = new THREE.LineSegments(eg, this.hiddenMat); hidden.computeLineDistances(); hidden.renderOrder = 3;
      const stencils = [this.backMat, this.frontMat].map(m => { const s = new THREE.Mesh(g, m); s.renderOrder = 1; return s; });
      const group = new THREE.Group();
      group.add(mesh, edges, hidden, ...stencils);
      group.userData.solid = sol.id;
      this.scene.add(group);
      this.solids.push({ group, mesh, triFace: Int32Array.from(triFace), edges, hidden, stencils, center: new THREE.Vector3(...sol.center), mat });
    }
    this.applyDisplay(); this.applyExplode(); this.applyParts(); this.applySection();
    this.clearHover();
    if (!keepView) this.setView("Iso");
    else this.refitIfClipped();
  }

  /** Keep the user's view, but zoom out (same direction) when the rebuilt part would extend past the window. */
  private refitIfClipped() {
    const cam = this.camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
    cam.updateMatrixWorld();
    let clipped = false;
    for (const x of [this.box.min.x, this.box.max.x]) for (const y of [this.box.min.y, this.box.max.y]) for (const z of [this.box.min.z, this.box.max.z]) {
      const p = new THREE.Vector3(x, y, z).project(cam);
      if (Math.abs(p.x) > 0.98 || Math.abs(p.y) > 0.98) clipped = true;
    }
    if (!clipped) return;
    const c = this.box.getCenter(new THREE.Vector3());
    const shift = c.clone().sub(this.controls.target);
    for (const k of [this.persp, this.ortho]) k.position.add(shift);
    this.controls.target.copy(c); this.controls.update();
    this.updateOrthoFrustum();
    this.fitProjected();
  }

  // ---------------------------------------------------------------- camera
  private resize() {
    const r = this.el.getBoundingClientRect();
    const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
    this.renderer.setSize(w, h, false);
    this.persp.aspect = w / h; this.persp.updateProjectionMatrix();
    this.updateOrthoFrustum();
    this.lineMats.forEach(m => m.resolution.set(w, h));
  }

  private updateOrthoFrustum() {
    const r = this.el.getBoundingClientRect();
    const aspect = Math.max(r.width, 1) / Math.max(r.height, 1);
    const half = this.radius * 1.15;
    const hh = aspect >= 1 ? half : half / aspect;
    this.ortho.left = -hh * aspect; this.ortho.right = hh * aspect; this.ortho.top = hh; this.ortho.bottom = -hh;
    this.ortho.near = -this.radius * 50; this.ortho.far = this.radius * 50;
    this.ortho.updateProjectionMatrix();
  }

  setView(name: ViewName) {
    const [d, up] = VIEW_DIRS[name];
    this.lookFrom(d, up);
  }

  /** Zoom to fit the whole model, keeping the current view direction (CAD "Zoom to Fit", F). */
  zoomToFit() {
    const c = this.box.getCenter(new THREE.Vector3());
    const shift = c.clone().sub(this.controls.target);
    for (const k of [this.persp, this.ortho]) k.position.add(shift);
    this.controls.target.copy(c); this.controls.update();
    this.ortho.zoom = 1; this.updateOrthoFrustum();
    this.fitProjected();
  }

  /** "Normal To": look straight at a planar face (its outward normal points at the viewer). */
  normalTo(n: V3) {
    const up: V3 = Math.abs(n[2]) > 0.9 ? [0, Math.sign(n[2]), 0] : [0, 0, 1];
    this.lookFrom(n, up);
  }

  private lookFrom(d: V3, up: V3) {
    const dir = new THREE.Vector3(...d).normalize();
    const c = this.box.getCenter(new THREE.Vector3());
    const vHalf = THREE.MathUtils.degToRad(this.persp.fov / 2);
    const hHalf = Math.atan(Math.tan(vHalf) * this.persp.aspect);
    const dist = this.radius / Math.sin(Math.min(vHalf, hHalf)) * 1.12;
    for (const cam of [this.persp, this.ortho]) { cam.up.set(...up); cam.position.copy(c).addScaledVector(dir, dist); cam.lookAt(c); }
    this.persp.near = dist / 200; this.persp.far = dist * 200; this.persp.updateProjectionMatrix();
    this.ortho.zoom = 1; this.updateOrthoFrustum();
    this.controls.target.copy(c); this.controls.update();
    this.fitProjected();
  }

  /** Zoom to fit using the silhouette of the bounding box in the current view direction (CAD "zoom to fit"). */
  private fitProjected() {
    const cam = this.camera === this.ortho ? this.ortho : this.persp;
    cam.updateMatrixWorld();
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1);
    const c = this.box.getCenter(new THREE.Vector3());
    let w = 0, h = 0;
    for (const x of [this.box.min.x, this.box.max.x]) for (const y of [this.box.min.y, this.box.max.y]) for (const z of [this.box.min.z, this.box.max.z]) {
      const d = new THREE.Vector3(x, y, z).sub(c);
      w = Math.max(w, Math.abs(d.dot(right))); h = Math.max(h, Math.abs(d.dot(up)));
    }
    w = Math.max(w, this.radius * 0.02); h = Math.max(h, this.radius * 0.02);
    const halfW = (this.ortho.right - this.ortho.left) / 2, halfH = (this.ortho.top - this.ortho.bottom) / 2;
    this.ortho.zoom = Math.min(halfW / w, halfH / h) * 0.82;
    this.ortho.updateProjectionMatrix();
    if (cam === this.persp) {
      const vHalf = THREE.MathUtils.degToRad(this.persp.fov / 2);
      const hHalf = Math.atan(Math.tan(vHalf) * this.persp.aspect);
      const dist = Math.max(h / Math.tan(vHalf), w / Math.tan(hHalf)) * 1.25 + this.radius * 0.5;
      const dir = this.persp.position.clone().sub(c).normalize();
      this.persp.position.copy(c).addScaledVector(dir, dist);
      this.persp.near = dist / 200; this.persp.far = dist * 200; this.persp.updateProjectionMatrix();
    }
  }

  /** fovDeg controls perspective strength (higher = stronger). */
  setProjection(ortho: boolean, fovDeg: number) {
    const target = this.controls.target.clone();
    const from = this.camera as THREE.PerspectiveCamera | THREE.OrthographicCamera;
    this.persp.fov = THREE.MathUtils.clamp(fovDeg, 5, 90);
    const dir = from.position.clone().sub(target).normalize();
    // keep apparent size: distance ↔ ortho zoom
    const vHalf = THREE.MathUtils.degToRad(this.persp.fov / 2);
    if (ortho && !this.orthoOn) {
      const d = this.persp.position.distanceTo(target);
      const visibleH = 2 * d * Math.tan(vHalf);
      this.ortho.position.copy(this.persp.position); this.ortho.up.copy(this.persp.up);
      this.ortho.zoom = (this.ortho.top - this.ortho.bottom) / visibleH;
    } else if (!ortho) {
      const visibleH = (this.ortho.top - this.ortho.bottom) / (this.orthoOn ? this.ortho.zoom : 1);
      const d = this.orthoOn ? visibleH / (2 * Math.tan(vHalf)) : this.persp.position.distanceTo(target);
      const up = (this.orthoOn ? this.ortho.up : this.persp.up).clone();
      this.persp.up.copy(up);
      this.persp.position.copy(target).addScaledVector(dir, d);
      this.persp.near = d / 200; this.persp.far = d * 200;
    }
    this.persp.updateProjectionMatrix(); this.ortho.updateProjectionMatrix();
    this.orthoOn = ortho;
    this.camera = ortho ? this.ortho : this.persp;
    this.controls.object = this.camera;
    this.camera.lookAt(target);
    this.controls.update();
  }

  // ---------------------------------------------------------------- orientation triad (bottom-left)
  private triScene = new THREE.Scene();
  private triCam = new THREE.OrthographicCamera(-1.7, 1.7, 1.7, -1.7, -10, 10);
  private buildTriad() {
    const label = (t: string, color: string) => {
      const c = document.createElement("canvas"); c.width = c.height = 64;
      const g = c.getContext("2d")!; g.fillStyle = color; g.font = "bold 44px Inter, Arial, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(t, 32, 34);
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
      s.scale.set(0.55, 0.55, 1); return s;
    };
    for (const [d, color, css, t] of [[[1, 0, 0], 0xd03a2f, "#d03a2f", "X"], [[0, 1, 0], 0x2f9a4e, "#2f9a4e", "Y"], [[0, 0, 1], 0x2f62d0, "#2f62d0", "Z"]] as [V3, number, string, string][]) {
      const v = new THREE.Vector3(...d);
      this.triScene.add(new THREE.ArrowHelper(v, new THREE.Vector3(), 1, color, 0.28, 0.16));
      const l = label(t, css); l.position.copy(v.multiplyScalar(1.35)); this.triScene.add(l);
    }
  }
  private renderTriad() {
    const r = this.renderer, size = 76, el = this.el.getBoundingClientRect();
    const target = this.controls.target;
    this.triCam.position.copy(this.camera.position).sub(target).normalize().multiplyScalar(5);
    this.triCam.up.copy(this.camera.up); this.triCam.lookAt(0, 0, 0);
    const ac = r.autoClear; r.autoClear = false;
    r.setScissorTest(true); r.setScissor(6, 6, size, size); r.setViewport(6, 6, size, size);
    r.clearDepth(); r.render(this.triScene, this.triCam);
    r.setScissorTest(false); r.setViewport(0, 0, Math.max(el.width, 1), Math.max(el.height, 1)); r.autoClear = ac;
  }

  // ---------------------------------------------------------------- display
  setDisplay(mode: DisplayMode) { this.display = mode; this.applyDisplay(); }

  private applyDisplay() {
    const m = this.display;
    for (const s of this.solids) {
      const hiddenPart = this.hiddenParts.has(s.group.userData.solid);
      s.mesh.visible = !hiddenPart;
      s.mat.visible = m === "shaded-edges" || m === "shaded" || m === "hidden";
      if (m === "hidden") { s.mat.color.setHex(this.pal.bgFace); s.mat.emissive.setHex(this.pal.bgFace); s.mat.emissiveIntensity = 0.85; }
      else { s.mat.color.setHex(this.pal.face); s.mat.emissive.setHex(0); s.mat.emissiveIntensity = 0; }
      s.mat.needsUpdate = true;
      s.edges.visible = !hiddenPart && m !== "shaded";
      s.hidden.visible = !hiddenPart && m === "hidden";
    }
  }

  // ---------------------------------------------------------------- section
  setSection(on: boolean, axis: Axis, t: number, flip: boolean): number {
    this.section = { on, axis, t, flip };
    return this.applySection();
  }

  private applySection(): number {
    const on = this.section.on && this.solids.length > 0;
    const planes = on ? [this.clip] : [];
    for (const s of this.solids) {
      s.mat.clippingPlanes = planes; s.mat.needsUpdate = true;
      s.stencils.forEach(st => { st.visible = on && s.mesh.visible; (st.material as THREE.Material).clippingPlanes = planes; });
    }
    this.edgeMat.clippingPlanes = planes; this.hiddenMat.clippingPlanes = planes;
    this.edgeMat.needsUpdate = this.hiddenMat.needsUpdate = true;
    this.cap.visible = on;
    const dir = AXIS[this.section.axis];
    const lo = this.box.min.dot(dir), hi = this.box.max.dot(dir);
    const d = THREE.MathUtils.lerp(lo, hi, this.section.t);
    this.clip.normal.copy(dir).multiplyScalar(this.section.flip ? 1 : -1);
    this.clip.constant = this.section.flip ? -d : d;
    const c = this.box.getCenter(new THREE.Vector3());
    const p = c.clone().addScaledVector(dir, d - c.dot(dir));
    const size = this.radius * 3;
    this.cap.position.copy(p); this.cap.lookAt(p.clone().add(dir)); this.cap.scale.set(size, size, 1);
    this.hatchTex.repeat.set(24, 24);
    return d; // CAD millimetres (topology is in mm)
  }

  // ---------------------------------------------------------------- parts
  setExplode(f: number) { this.explode = f; this.applyExplode(); }
  private applyExplode() {
    const c = this.box.getCenter(new THREE.Vector3());
    for (const s of this.solids) s.group.position.copy(s.center.clone().sub(c).multiplyScalar(this.explode));
  }
  setHiddenParts(ids: number[]) { this.hiddenParts = new Set(ids); this.applyParts(); }
  setGhost(on: boolean) { this.ghost = on; this.applyParts(); }
  private applyParts() {
    for (const s of this.solids) {
      s.mat.transparent = this.ghost; s.mat.opacity = this.ghost ? 0.18 : 1; s.mat.depthWrite = !this.ghost;
      s.mat.needsUpdate = true;
    }
    this.applyDisplay();
  }

  // ---------------------------------------------------------------- picking
  setPicking(kinds: Pick["kind"][]) {
    this.picking = new Set(kinds);
    this.controls.enabled = true;
    if (!kinds.length) this.clearHover();
  }

  private ndc(e: PointerEvent) {
    const r = this.renderer.domElement.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * 2 - 1, y: -((e.clientY - r.top) / r.height) * 2 + 1, px: e.clientX - r.left, py: e.clientY - r.top, w: r.width, h: r.height };
  }

  private toScreen(p: THREE.Vector3, w: number, h: number) {
    const v = p.clone().project(this.camera);
    return { x: (v.x + 1) / 2 * w, y: (1 - v.y) / 2 * h };
  }

  private solidOffset(solidId: number) {
    return this.solids.find(s => s.group.userData.solid === solidId)?.group.position ?? new THREE.Vector3();
  }

  pickAt(e: PointerEvent): Pick | null {
    if (!this.topo || !this.picking.size) return null;
    const n = this.ndc(e);
    this.ray.setFromCamera(new THREE.Vector2(n.x, n.y), this.camera);
    const meshes = this.solids.filter(s => s.mesh.visible).map(s => s.mesh);
    let hits = this.ray.intersectObjects(meshes, false);
    if (this.section.on) hits = hits.filter(h => this.clip.distanceToPoint(h.point) >= -1e-6);
    const topo = this.topo;
    const candEdges = new Set<number>();
    let faceHit: { fid: number; point: THREE.Vector3; off: THREE.Vector3 } | null = null;
    if (hits[0]) {
      const s = this.solids.find(x => x.mesh === hits[0]!.object)!;
      const fid = s.triFace[hits[0].faceIndex ?? 0]!;
      faceHit = { fid, point: hits[0].point.clone().sub(s.group.position), off: s.group.position.clone() };
      topo.faces[fid]!.edges.forEach(e => candEdges.add(e));
    }
    if (this.display === "wireframe" || !faceHit) {
      // wireframe / near silhouettes: consider every edge (bounded)
      if (topo.edges.length <= 4000) topo.edges.forEach(e => candEdges.add(e.id));
    }
    const cursor = { x: n.px, y: n.py };
    let best: { d: number; pick: Pick } | null = null;
    const meshList = meshes;
    const occluded = (pt: V3): boolean => {
      if (this.display === "wireframe") return false;
      const P = new THREE.Vector3(...pt);
      const camPos = this.camera === this.ortho
        ? P.clone().addScaledVector(new THREE.Vector3().setFromMatrixColumn(this.ortho.matrixWorld, 2), this.radius * 10)
        : (this.camera as THREE.PerspectiveCamera).position.clone();
      const dir = P.clone().sub(camPos); const dist = dir.length(); dir.normalize();
      const r = new THREE.Raycaster(camPos, dir, 0, dist);
      let hs = r.intersectObjects(meshList, false);
      if (this.section.on) hs = hs.filter(h => this.clip.distanceToPoint(h.point) >= -1e-6);
      return !!hs[0] && hs[0].distance < dist - this.radius * 0.004;
    };
    const consider = (d: number, pick: Pick, limit: number) => {
      if (d <= limit && (!best || d < best.d) && !occluded(pick.point)) best = { d, pick };
    };
    for (const eid of candEdges) {
      const e = topo.edges[eid]!;
      const off = this.solidOffset(topo.faces[e.faces[0] ?? 0]?.solid ?? 0);
      if (this.picking.has("vertex")) for (const vid of e.verts) {
        const v = new THREE.Vector3(...topo.vertices[vid]!).add(off);
        const sp = this.toScreen(v, n.w, n.h);
        consider(Math.hypot(sp.x - cursor.x, sp.y - cursor.y), { kind: "vertex", id: vid, point: topo.vertices[vid]! }, 11);
      }
      if (this.picking.has("center") && e.type === "circle" && e.center) {
        const sp = this.toScreen(new THREE.Vector3(...e.center).add(off), n.w, n.h);
        consider(Math.hypot(sp.x - cursor.x, sp.y - cursor.y) - 0.5, { kind: "center", edge: eid, point: e.center }, 11);
      }
    }
    if (best) return (best as { pick: Pick }).pick;
    if (this.picking.has("edge")) {
      for (const eid of candEdges) {
        const e = topo.edges[eid]!;
        const off = this.solidOffset(topo.faces[e.faces[0] ?? 0]?.solid ?? 0);
        const p = e.pts;
        for (let i = 0; i + 5 < p.length; i += 3) {
          const a = new THREE.Vector3(p[i], p[i + 1], p[i + 2]).add(off), b = new THREE.Vector3(p[i + 3], p[i + 4], p[i + 5]).add(off);
          const sa = this.toScreen(a, n.w, n.h), sb = this.toScreen(b, n.w, n.h);
          const dx = sb.x - sa.x, dy = sb.y - sa.y, L2 = dx * dx + dy * dy || 1;
          const t = THREE.MathUtils.clamp(((cursor.x - sa.x) * dx + (cursor.y - sa.y) * dy) / L2, 0, 1);
          const d = Math.hypot(sa.x + t * dx - cursor.x, sa.y + t * dy - cursor.y);
          const pt = a.clone().lerp(b, t).sub(off);
          consider(d, { kind: "edge", id: eid, point: [pt.x, pt.y, pt.z] }, 7);
        }
      }
      if (best) return (best as { pick: Pick }).pick;
    }
    if (faceHit && this.picking.has("face") && this.display !== "wireframe")
      return { kind: "face", id: faceHit.fid, point: [faceHit.point.x, faceHit.point.y, faceHit.point.z] };
    return null;
  }

  private onMove = (e: PointerEvent) => {
    if (!this.picking.size || e.buttons) return;
    const p = this.pickAt(e);
    this.showHover(p);
    this.events.onHover?.(p);
  };
  private onDown = (e: PointerEvent) => { this.downAt = [e.clientX, e.clientY]; };
  private onUp = (e: PointerEvent) => {
    if (!this.downAt || e.button !== 0) return;
    const moved = Math.hypot(e.clientX - this.downAt[0], e.clientY - this.downAt[1]) > 4;
    this.downAt = null;
    if (moved || !this.picking.size) return;
    this.events.onClick?.(this.pickAt(e), e.ctrlKey || e.shiftKey || e.metaKey);
  };

  // ---------------------------------------------------------------- highlight helpers
  private fatLine(pts: number[], color: number, width: number, off: THREE.Vector3) {
    const g = new LineGeometry(); g.setPositions(pts);
    const m = new LineMaterial({ color, linewidth: width, depthTest: false, transparent: true });
    const r = this.el.getBoundingClientRect(); m.resolution.set(r.width, r.height);
    this.lineMats.push(m);
    const l = new Line2(g, m); l.computeLineDistances(); l.renderOrder = 10; l.position.copy(off);
    return l;
  }
  private dot(p: V3, color: number, size: number, off: THREE.Vector3) {
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
    const m = new THREE.PointsMaterial({ color, size, sizeAttenuation: false, map: this.dotTex, transparent: true, depthTest: false, alphaTest: 0.2 });
    const o = new THREE.Points(g, m); o.renderOrder = 11; o.position.copy(off);
    return o;
  }
  /** Translucent copy of a face, or null if the id is not in the current topology (e.g. a highlight from before a rebuild). */
  private faceOverlay(fid: number, color: number, opacity: number): THREE.Mesh | null {
    const f = this.topo?.faces[fid];
    if (!f) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(f.pos, 3)); g.setIndex(f.idx);
    const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, clippingPlanes: this.section.on ? [this.clip] : [] });
    const o = new THREE.Mesh(g, m); o.renderOrder = 5; o.position.copy(this.solidOffset(f.solid));
    return o;
  }
  private objectsFor(p: Pick, color: number, strong: boolean): THREE.Object3D[] {
    const topo = this.topo!;
    if (p.kind === "face") { const o = this.faceOverlay(p.id, color, strong ? 0.45 : 0.3); return o ? [o] : []; }
    if (p.kind === "edge") {
      const e = topo.edges[p.id]; if (!e) return [];
      return [this.fatLine(e.pts, color, strong ? 4 : 3.5, this.solidOffset(topo.faces[e.faces[0] ?? 0]?.solid ?? 0))];
    }
    if (p.kind === "center") {
      const e = topo.edges[p.edge]; if (!e) return [];
      const off = this.solidOffset(topo.faces[e.faces[0] ?? 0]?.solid ?? 0);
      return [this.fatLine(e.pts, color, 2, off), this.dot(p.point, color, 12, off)];
    }
    return [this.dot(p.point, color, 13, new THREE.Vector3())];
  }
  private dropAll(list: THREE.Object3D[]) {
    for (const o of list) {
      this.scene.remove(o);
      const m = (o as THREE.Mesh).material as THREE.Material | undefined;
      if (m && this.lineMats.includes(m as LineMaterial)) this.lineMats.splice(this.lineMats.indexOf(m as LineMaterial), 1);
      (o as THREE.Mesh).geometry?.dispose(); m?.dispose();
    }
    list.length = 0;
  }
  private clearHover() { this.dropAll(this.hoverObjs); this.renderer.domElement.style.cursor = ""; }
  private showHover(p: Pick | null) {
    this.clearHover();
    if (!p) return;
    this.renderer.domElement.style.cursor = "crosshair";
    for (const o of this.objectsFor(p, this.pal.hover, false)) { this.scene.add(o); this.hoverObjs.push(o); }
  }

  setSelection(picks: Pick[]) {
    this.dropAll(this.selObjs);
    if (!this.topo) return;
    for (const p of picks) for (const o of this.objectsFor(p, this.pal.select, true)) { this.scene.add(o); this.selObjs.push(o); }
  }

  /** Measurement graphics: a dimension line between two points. */
  setMeasureLine(a: V3 | null, b: V3 | null) {
    this.dropAll(this.markObjs);
    if (!a || !b) return;
    const l = this.fatLine([...a, ...b], 0x1f5fbf, 2, new THREE.Vector3());
    (l.material as LineMaterial).dashed = true; (l.material as LineMaterial).dashSize = this.radius / 40; (l.material as LineMaterial).gapSize = this.radius / 80;
    this.scene.add(l); this.markObjs.push(l);
  }

  highlightFaces(ids: number[]) {
    this.dropAll(this.featureObjs);
    if (!this.topo) return;
    for (const id of ids) { const o = this.faceOverlay(id, 0x2fa36b, 0.4); if (o) { this.scene.add(o); this.featureObjs.push(o); } }
  }

  setCenterOfMass(p: V3 | null) {
    if (this.comObj) { this.scene.remove(this.comObj); this.comObj = null; }
    if (!p) return;
    const g = new THREE.Group();
    const L = this.radius * 0.25;
    for (const [d, c] of [[[L, 0, 0], 0xd03a2f], [[0, L, 0], 0x2f9a4e], [[0, 0, L], 0x2f62d0]] as [V3, number][]) {
      g.add(this.fatLine([p[0] - d[0], p[1] - d[1], p[2] - d[2], p[0] + d[0], p[1] + d[1], p[2] + d[2]], c, 2.5, new THREE.Vector3()));
    }
    g.add(this.dot(p, 0x111111, 14, new THREE.Vector3()));
    this.comObj = g; this.scene.add(g);
  }

  setSketchPreview(s: SketchPreview | null) {
    if (this.sketchObj) {
      const parts = this.sketchObj instanceof THREE.Group ? [...this.sketchObj.children] : [this.sketchObj];
      this.scene.remove(this.sketchObj); this.dropAll(parts); this.sketchObj = null;
    }
    if (!s) return;
    if (s.kind === "lines") {
      const g = new THREE.Group();
      for (const pl of s.lines ?? []) if (pl.length > 1) g.add(this.fatLine(pl.flat(), 0x2fa36b, 3, new THREE.Vector3()));
      this.sketchObj = g; this.scene.add(g);
      if (!this.topo && s.lines?.length) { // nothing modelled yet: frame the sketches themselves
        this.box = new THREE.Box3().setFromPoints(s.lines.flat().map(p => new THREE.Vector3(...p)));
        this.radius = Math.max(this.box.getSize(new THREE.Vector3()).length() / 2, 1);
        this.setView("Iso");
      }
      return;
    }
    const o = new THREE.Vector3(...s.origin), n = new THREE.Vector3(...s.normal).normalize(), x = new THREE.Vector3(...s.xDir).normalize();
    const y = n.clone().cross(x).normalize();
    const at = (u: number, v: number) => o.clone().addScaledVector(x, u + s.cx).addScaledVector(y, v + s.cy).addScaledVector(n, this.radius * 0.002);
    const pts: number[] = [];
    if (s.kind === "rect") {
      const w = (s.w ?? 0) / 2, h = (s.h ?? 0) / 2;
      for (const [u, v] of [[-w, -h], [w, -h], [w, h], [-w, h], [-w, -h]] as [number, number][]) pts.push(...at(u, v).toArray());
    } else {
      const r = s.r ?? 0;
      for (let i = 0; i <= 64; i++) { const a = (i / 64) * Math.PI * 2; pts.push(...at(Math.cos(a) * r, Math.sin(a) * r).toArray()); }
    }
    this.sketchObj = this.fatLine(pts, 0x2fa36b, 3, new THREE.Vector3());
    this.scene.add(this.sketchObj);
  }

  /** Compare overlay: material added (green) / removed (red) relative to a base revision. */
  setOverlay(added: Topo | null, removed: Topo | null) {
    this.dropAll(this.overlayObjs);
    const make = (t: Topo, color: number) => {
      const pos: number[] = [], idx: number[] = [];
      for (const f of t.faces) { const b = pos.length / 3; pos.push(...f.pos); f.idx.forEach(i => idx.push(b + i)); }
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
      const m = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.75, side: THREE.DoubleSide, depthWrite: false });
      const mesh = new THREE.Mesh(g, m); mesh.renderOrder = 4;
      const seg: number[] = [];
      for (const e of t.edges) for (let i = 0; i + 5 < e.pts.length; i += 3) seg.push(...e.pts.slice(i, i + 6));
      const eg = new THREE.BufferGeometry(); eg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
      const lines = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color, depthTest: false }));
      return [mesh, lines];
    };
    if (added) for (const o of make(added, 0x22a85a)) { this.scene.add(o); this.overlayObjs.push(o); }
    if (removed) for (const o of make(removed, 0xd8402f)) { this.scene.add(o); this.overlayObjs.push(o); }
  }

  get edgeById(): (id: number) => TopoEdge | undefined { return (id) => this.topo?.edges[id]; }
  get keyOf() { return pickKey; }
}
