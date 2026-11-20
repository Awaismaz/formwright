/**
 * A small three.js view for the layout preview: orthographic, Z up, CAD mouse (left / middle drag rotates, right
 * drag pans, wheel zooms about the cursor), one coloured mesh per body with its feature lines, render on demand.
 * Exposes the same ``viewCam`` as the Studio viewer so the viewport dimension layout (DS-038) draws on it unchanged.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { ViewCam } from "@/viewer/dims";
import type { V3 } from "@/viewer/types";
import { bodyGeo, ERROR_COLOR, geomKey, PATH_COLOR, type Geo } from "./build";
import type { PreviewBody } from "./types";

export type PreviewView = "Iso" | "Front" | "Top" | "Right";
const VIEWS: Record<PreviewView, [V3, V3]> = {
  Iso: [[1, -1, 0.8], [0, 0, 1]], Front: [[0, -1, 0], [0, 0, 1]], Top: [[0, 0, 1], [0, 1, 0]], Right: [[1, 0, 0], [0, 0, 1]],
};

interface Item { id: string; item: string; mesh: THREE.Mesh; lines: THREE.LineSegments; mat: THREE.MeshStandardMaterial; base: THREE.Color; open: boolean; flag: boolean }

export class PreviewScene {
  readonly el: HTMLElement;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private cam = new THREE.OrthographicCamera(-1, 1, 1, -1, -1e6, 1e6);
  private controls: OrbitControls;
  private root = new THREE.Group();
  private items: Item[] = [];
  private geos = new Map<string, { mesh: THREE.BufferGeometry; lines: THREE.BufferGeometry }>();
  private box = new THREE.Box3(new THREE.Vector3(-50, -50, -50), new THREE.Vector3(50, 50, 50));
  private radius = 86;
  private ray = new THREE.Raycaster();
  private edgeMat: THREE.LineBasicMaterial;
  private hot = new Set<string>();
  private dark: boolean;
  private frame = 0;
  private listeners = new Set<() => void>();
  private ro: ResizeObserver;
  onHover: (bodyId: string | null) => void = () => {};
  onClick: (bodyId: string | null) => void = () => {};
  private down: [number, number] | null = null;
  private lastHover: string | null = null;

  constructor(el: HTMLElement, dark: boolean) {
    this.el = el;
    this.dark = dark;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    el.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.display = "block";
    this.cam.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.cam, this.renderer.domElement);
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.ROTATE, RIGHT: THREE.MOUSE.PAN };
    this.controls.zoomToCursor = true;
    this.controls.addEventListener("change", () => this.request());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a3, 1.3));
    const key = new THREE.DirectionalLight(0xffffff, 1.4); key.position.set(2, -3, 5); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.5); fill.position.set(-4, 3, -2); this.scene.add(fill);
    const head = new THREE.DirectionalLight(0xffffff, 0.55); this.cam.add(head); this.scene.add(this.cam);
    this.edgeMat = new THREE.LineBasicMaterial({ color: dark ? 0x0b0f17 : 0x1f2733, transparent: true, opacity: 0.55 });
    this.scene.add(this.root);
    this.ro = new ResizeObserver(() => { this.resize(); this.request(); });
    this.ro.observe(el);
    this.resize();
    const dom = this.renderer.domElement;
    dom.addEventListener("pointermove", this.move);
    dom.addEventListener("pointerdown", e => { this.down = [e.clientX, e.clientY]; });
    dom.addEventListener("pointerup", e => {
      if (this.down && Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) < 4) this.onClick(this.pick(e));
      this.down = null;
    });
    dom.addEventListener("pointerleave", () => { if (this.lastHover !== null) { this.lastHover = null; this.onHover(null); } });
  }

  dispose() {
    cancelAnimationFrame(this.frame);
    this.ro.disconnect();
    this.controls.dispose();
    this.clear();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  /** Called after the camera, zoom or size changed (the dimension overlay follows). */
  onView(cb: () => void): () => void { this.listeners.add(cb); cb(); return () => { this.listeners.delete(cb); }; }

  private request() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.renderer.render(this.scene, this.cam);
      this.listeners.forEach(f => f());
    });
  }

  private resize() {
    const r = this.el.getBoundingClientRect();
    const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = `${w}px`; this.renderer.domElement.style.height = `${h}px`;
    const aspect = w / h, half = this.radius * 1.15, hh = aspect >= 1 ? half : half / aspect;
    this.cam.left = -hh * aspect; this.cam.right = hh * aspect; this.cam.top = hh; this.cam.bottom = -hh;
    this.cam.near = -this.radius * 50; this.cam.far = this.radius * 50;
    this.cam.updateProjectionMatrix();
  }

  private clear() {
    for (const it of this.items) { this.root.remove(it.mesh, it.lines); it.mat.dispose(); }
    this.items = [];
    for (const g of this.geos.values()) { g.mesh.dispose(); g.lines.dispose(); }
    this.geos.clear();
  }

  private geometry(b: PreviewBody): { mesh: THREE.BufferGeometry; lines: THREE.BufferGeometry } {
    const k = geomKey(b);
    let g = this.geos.get(k);
    if (!g) {
      const geo: Geo = bodyGeo(b);
      const mesh = new THREE.BufferGeometry();
      mesh.setAttribute("position", new THREE.Float32BufferAttribute(geo.pos, 3));
      mesh.setIndex(geo.idx);
      mesh.computeVertexNormals();
      const lines = new THREE.BufferGeometry();
      lines.setAttribute("position", new THREE.Float32BufferAttribute(geo.edges, 3));
      g = { mesh, lines };
      this.geos.set(k, g);
    }
    return g;
  }

  /** Show these bodies. ``keepView``: an update of the same program keeps the engineer's camera. */
  load(bodies: PreviewBody[], bounds: [number, number, number, number, number, number], keepView: boolean) {
    this.clear();
    for (const b of bodies) {
      const g = this.geometry(b);
      const open = b.kind === "box" && !!b.g.open;
      const flag = b.flag === "error";
      const base = new THREE.Color(flag ? ERROR_COLOR : PATH_COLOR[b.path]);
      const mat = new THREE.MeshStandardMaterial({
        color: base.clone(), metalness: 0.15, roughness: 0.6, side: THREE.DoubleSide,
        transparent: open, opacity: open ? 0.22 : 1, depthWrite: !open,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
      });
      const mesh = new THREE.Mesh(g.mesh, mat);
      const lines = new THREE.LineSegments(g.lines, flag ? new THREE.LineBasicMaterial({ color: ERROR_COLOR }) : this.edgeMat);
      const T = b.T;
      const m = new THREE.Matrix4().set(T[0]!, T[1]!, T[2]!, T[3]!, T[4]!, T[5]!, T[6]!, T[7]!, T[8]!, T[9]!, T[10]!, T[11]!, 0, 0, 0, 1);
      for (const o of [mesh, lines]) { o.matrixAutoUpdate = false; o.matrix.copy(m); o.userData.body = b.id; }
      if (open) mesh.renderOrder = 2;
      this.root.add(mesh, lines);
      this.items.push({ id: b.id, item: b.item, mesh, lines, mat, base, open, flag });
    }
    this.root.updateMatrixWorld(true);
    const [x0, y0, z0, x1, y1, z1] = bounds;
    const before = this.box.clone();
    this.box = new THREE.Box3(new THREE.Vector3(x0, y0, z0), new THREE.Vector3(x1, y1, z1));
    this.radius = Math.max(this.box.getSize(new THREE.Vector3()).length() / 2, 1);
    this.resize();
    const moved = before.min.distanceTo(this.box.min) + before.max.distanceTo(this.box.max) > this.radius * 0.6;
    if (!keepView || moved) this.setView("Iso");
    this.applyHot();
    this.request();
  }

  /** Highlight these bodies (by body id or item id); the rest dim a little so the highlight reads. */
  setHot(ids: Iterable<string>) {
    this.hot = new Set(ids);
    this.applyHot();
    this.request();
  }

  private applyHot() {
    const any = this.hot.size > 0;
    const hi = new THREE.Color(this.dark ? "#7fb0ff" : "#1f5fbf");
    for (const it of this.items) {
      const on = this.hot.has(it.id) || this.hot.has(it.item);
      it.mat.color.copy(on && !it.flag ? it.base.clone().lerp(hi, 0.55) : it.base);
      it.mat.emissive.set(on ? (it.flag ? "#5a0000" : "#0b2a5c") : "#000000");
      it.mat.opacity = it.open ? (on ? 0.4 : 0.22) : any && !on ? 0.55 : 1;
      it.mat.transparent = it.open || (any && !on);
      it.mat.depthWrite = !it.mat.transparent;
      it.mat.needsUpdate = true;
    }
  }

  setView(v: PreviewView) {
    const [d, up] = VIEWS[v];
    const c = this.box.getCenter(new THREE.Vector3());
    const dir = new THREE.Vector3(...d).normalize();
    this.cam.up.set(...up);
    this.cam.position.copy(c).addScaledVector(dir, this.radius * 3);
    this.cam.lookAt(c);
    this.controls.target.copy(c);
    this.controls.update();
    this.fit();
  }

  /** Zoom so the bounding box fills the view (its silhouette in the current direction). */
  fit() {
    this.cam.updateMatrixWorld();
    const right = new THREE.Vector3().setFromMatrixColumn(this.cam.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(this.cam.matrixWorld, 1);
    const c = this.box.getCenter(new THREE.Vector3());
    let w = 0, h = 0;
    for (const x of [this.box.min.x, this.box.max.x]) for (const y of [this.box.min.y, this.box.max.y]) for (const z of [this.box.min.z, this.box.max.z]) {
      const d = new THREE.Vector3(x, y, z).sub(c);
      w = Math.max(w, Math.abs(d.dot(right))); h = Math.max(h, Math.abs(d.dot(up)));
    }
    const halfW = (this.cam.right - this.cam.left) / 2, halfH = (this.cam.top - this.cam.bottom) / 2;
    this.cam.zoom = Math.min(halfW / Math.max(w, 1e-3), halfH / Math.max(h, 1e-3)) * 0.84;  // room for dimensions
    this.cam.updateProjectionMatrix();
    this.request();
  }

  private pick(e: PointerEvent | MouseEvent): string | null {
    const r = this.renderer.domElement.getBoundingClientRect();
    const v = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(v, this.cam);
    const hits = this.ray.intersectObjects(this.items.map(i => i.mesh), false);
    // see-through housings are picked last: what is inside them is what the engineer points at
    const solid = hits.find(h => !this.items.find(i => i.mesh === h.object)?.open);
    const h = solid ?? hits[0];
    return h ? String(h.object.userData.body) : null;
  }

  private move = (e: PointerEvent) => {
    if (e.buttons) return;
    const id = this.pick(e);
    if (id !== this.lastHover) { this.lastHover = id; this.onHover(id); }
  };

  /** The camera as the viewport dimension layout sees it (same contract as the Studio viewer). */
  viewCam(): ViewCam {
    const cam = this.cam;
    cam.updateMatrixWorld();
    const r = this.el.getBoundingClientRect();
    const w = Math.max(r.width, 1), h = Math.max(r.height, 1);
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).normalize();
    const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1).normalize();
    const vd = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 2).normalize();
    const visibleH = (cam.top - cam.bottom) / cam.zoom;
    const v = new THREE.Vector3();
    return {
      project: (p: V3) => { v.set(p[0], p[1], p[2]).project(cam); return [(v.x + 1) / 2 * w, (1 - v.y) / 2 * h]; },
      vd: [vd.x, vd.y, vd.z], right: [right.x, right.y, right.z], up: [up.x, up.y, up.z],
      pxPerMm: h / Math.max(visibleH, 1e-9), width: w, height: h,
    };
  }

  /** Centre of a body in the program frame (its placement origin; a screw: its shank middle). */
  centreOf(id: string): V3 | null {
    const it = this.items.find(i => i.id === id);
    if (!it) return null;
    const g = it.mesh.geometry;
    if (!g.boundingBox) g.computeBoundingBox();
    const c = g.boundingBox!.getCenter(new THREE.Vector3()).applyMatrix4(it.mesh.matrix);
    return [c.x, c.y, c.z];
  }
}
