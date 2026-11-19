import { useEffect, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { cx } from "@/lib/format";

/**
 * A small, self-contained three.js stage for the landing page. It shows real Formwright geometry: GLB files exported
 * from Toolbox parts (see scripts/landing_assets.py). Coordinates are CAD millimetres, Z up.
 * Renders only while on screen; under reduced motion it renders still frames and never spins or explodes on its own.
 */

export type V3 = [number, number, number];
export type ScenePart = {
  id: string;
  url: string;
  /** Position (mm, CAD axes). */
  at?: V3;
  /** Offset at full explode (mm, CAD axes). */
  explode?: V3;
  color?: string;
  /** Fades the part in/out (default true). */
  show?: boolean;
  /** Pulse a highlight on side faces whose distance from the Z axis is in [rMin, rMax] mm (e.g. gear teeth). */
  highlight?: { rMin: number; rMax: number; color?: string };
};
export type PartSceneProps = {
  parts: ScenePart[];
  /** 0 = assembled, 1 = fully exploded; animated smoothly. */
  explode?: number;
  /** Turntable speed in degrees per second (0 = none). */
  spin?: number;
  /** Camera direction in CAD axes (default SOLIDWORKS-like isometric). */
  view?: V3;
  /** Extra zoom factor (>1 = closer). */
  zoom?: number;
  still?: boolean;
  /** Turntable angle in degrees, set from outside (for example by scroll); eased. */
  turn?: number;
  /** Shown while the parts load and when WebGL is unavailable. */
  poster?: ReactNode;
  className?: string;
  label: string;
};

const cad = (v: V3) => new THREE.Vector3(v[0], v[2], -v[1]);
const cache = new Map<string, Promise<THREE.Group>>();
const load = (url: string) => {
  let p = cache.get(url);
  if (!p) { p = new GLTFLoader().loadAsync(url).then(g => g.scene); cache.set(url, p); p.catch(() => cache.delete(url)); }
  return p;
};
const edgeCache = new WeakMap<THREE.BufferGeometry, THREE.EdgesGeometry>();
const edgesOf = (g: THREE.BufferGeometry) => {
  let e = edgeCache.get(g);
  if (!e) { e = new THREE.EdgesGeometry(g, 28); edgeCache.set(g, e); }
  return e;
};

/** Triangles of `g` whose centroid lies in the radial band and whose normal is roughly radial (side faces). */
function bandGeometry(g: THREE.BufferGeometry, rMin: number, rMax: number): THREE.BufferGeometry {
  const pos = g.getAttribute("position");
  const idx = g.getIndex();
  const n = idx ? idx.count : pos.count;
  const out: number[] = [];
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), nrm = new THREE.Vector3(), e = new THREE.Vector3();
  for (let i = 0; i + 2 < n; i += 3) {
    const [i0, i1, i2] = idx ? [idx.getX(i), idx.getX(i + 1), idx.getX(i + 2)] : [i, i + 1, i + 2];
    a.fromBufferAttribute(pos, i0); b.fromBufferAttribute(pos, i1); c.fromBufferAttribute(pos, i2);
    const r = Math.hypot((a.x + b.x + c.x) / 3, (a.y + b.y + c.y) / 3) * 1000; // geometry is CAD metres
    if (r < rMin || r > rMax) continue;
    nrm.subVectors(b, a).cross(e.subVectors(c, a)).normalize();
    if (Math.abs(nrm.z) > 0.6) continue;
    out.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
  }
  const bg = new THREE.BufferGeometry();
  bg.setAttribute("position", new THREE.Float32BufferAttribute(out, 3));
  return bg;
}

type Inst = {
  part: ScenePart; holder: THREE.Group; mats: THREE.MeshStandardMaterial[]; lines: THREE.LineBasicMaterial[];
  hl: THREE.MeshBasicMaterial[]; opacity: number;
};

export default function PartScene({ parts, explode = 0, spin = 0, view = [1, -1, 0.75], zoom = 1, still = false, turn, poster, className, label }: PartSceneProps) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ parts, explode, spin, still, turn, zoom });
  live.current = { parts, explode, spin, still, turn, zoom };
  const kick = useRef<() => void>(() => {});
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = parts.map(p => `${p.id}:${p.url}`).join("|");

  useEffect(() => { kick.current(); }, [parts, explode, spin, still, turn, zoom]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch { setFailed(true); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    const canvas = renderer.domElement;
    canvas.style.cssText = "display:block;width:100%;height:100%;outline:none";
    canvas.setAttribute("aria-label", label);
    canvas.setAttribute("role", "img");
    el.appendChild(canvas);

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(3, 6, 4);
    scene.add(sun, new THREE.HemisphereLight(0xdfe8f5, 0x8a94a3, 0.35));
    const pivot = new THREE.Group();
    const root = new THREE.Group();
    pivot.add(root);
    scene.add(pivot);

    const camera = new THREE.PerspectiveCamera(28, 1, 1, 5000);
    const controls = new OrbitControls(camera, canvas);
    controls.enableZoom = false;
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    const coarse = window.matchMedia?.("(pointer: coarse)").matches;
    if (coarse) { controls.enabled = false; canvas.style.touchAction = "pan-y"; }
    let userHold = 0;
    controls.addEventListener("start", () => { userHold = Infinity; kick.current(); });
    controls.addEventListener("end", () => { userHold = performance.now() + 2500; });
    controls.addEventListener("change", () => kick.current());

    const insts: Inst[] = [];
    let ex = live.current.still ? live.current.explode : 0;
    let disposed = false;
    let raf = 0;
    let visible = false;
    let last = performance.now();
    let settleFrames = 0;

    let sphere: THREE.Sphere | null = null;
    let zNow = live.current.zoom;
    const place = () => {
      if (!sphere) return;
      // fit the bounding sphere in the narrower of the vertical and horizontal fields of view
      const half = THREE.MathUtils.degToRad(camera.fov / 2);
      const halfH = Math.atan(Math.tan(half) * Math.min(1, camera.aspect));
      const dist = (sphere.radius / Math.sin(Math.min(half, halfH))) / zNow;
      const dir = cad(view).normalize();
      camera.position.copy(sphere.center).addScaledVector(dir, dist);
      camera.near = dist / 20; camera.far = dist * 6;
      camera.updateProjectionMatrix();
      controls.target.copy(sphere.center);
      controls.update();
    };
    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      place();
      kick.current();
    };

    const fit = () => {
      const box = new THREE.Box3();
      root.updateMatrixWorld(true);
      for (const i of insts) {
        const b = new THREE.Box3().setFromObject(i.holder);
        box.union(b);
        if (i.part.explode) box.union(b.clone().translate(cad(i.part.explode)));
      }
      if (box.isEmpty()) return;
      const s = box.getBoundingSphere(new THREE.Sphere());
      // turntable about the middle of the parts, not the CAD origin
      pivot.position.copy(s.center);
      root.position.copy(s.center).negate();
      sphere = s;
      place();
    };

    const step = (now: number) => {
      raf = 0;
      if (disposed) return;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const L = live.current;
      let moving = false;
      const k = L.still ? 1 : 1 - Math.exp(-dt * 5);
      // explode
      const exT = L.explode;
      if (Math.abs(exT - ex) > 1e-3) { ex += (exT - ex) * k; moving = true; } else ex = exT;
      // parts
      for (const i of insts) {
        const p = L.parts.find(q => q.id === i.part.id) ?? i.part;
        const want = p.show === false ? 0 : 1;
        if (Math.abs(want - i.opacity) > 1e-3) { i.opacity += (want - i.opacity) * (L.still ? 1 : 1 - Math.exp(-dt * 7)); moving = true; } else i.opacity = want;
        const o = i.opacity;
        i.holder.visible = o > 0.01;
        const s = 0.965 + 0.035 * o;
        i.holder.scale.setScalar(s);
        i.holder.position.copy(cad(p.at ?? [0, 0, 0])).addScaledVector(cad(p.explode ?? [0, 0, 0]), ex);
        for (const m of i.mats) {
          const tr = o < 0.995;
          if (m.transparent !== tr) { m.transparent = tr; m.needsUpdate = true; }
          m.opacity = o; m.depthWrite = o > 0.6;
        }
        for (const m of i.lines) m.opacity = 0.5 * o;
        for (const m of i.hl) m.opacity = o * (L.still ? 0.55 : 0.18 + 0.5 * (0.5 + 0.5 * Math.sin(now / 1000 * 2.6)));
        if (i.hl.length && !L.still) moving = true;
      }
      // zoom can change after load (e.g. closer as an exploded view assembles)
      if (Math.abs(L.zoom - zNow) > 1e-3) { zNow += (L.zoom - zNow) * k; place(); moving = true; }
      // turntable: an angle set from outside, else a steady spin
      if (L.turn != null) {
        const d = THREE.MathUtils.degToRad(L.turn) - pivot.rotation.y;
        if (Math.abs(d) > 1e-4) { pivot.rotation.y += d * k; moving = true; }
      } else
      if (L.spin && !L.still && now > userHold) { pivot.rotation.y += THREE.MathUtils.degToRad(L.spin) * dt; moving = true; }
      if (controls.update()) moving = true;
      renderer.render(scene, camera);
      if (moving) settleFrames = 20; else settleFrames--;
      if (visible && settleFrames > 0) raf = requestAnimationFrame(step);
    };
    kick.current = () => {
      settleFrames = Math.max(settleFrames, 20);
      if (!raf && visible && !disposed) { last = performance.now(); raf = requestAnimationFrame(step); }
    };

    const ro = new ResizeObserver(resize);
    ro.observe(el);
    const io = new IntersectionObserver(([e]) => { visible = !!e?.isIntersecting; if (visible) kick.current(); }, { rootMargin: "100px" });
    io.observe(el);
    resize();

    Promise.all(live.current.parts.map(p => load(p.url).then(src => ({ p, src })))).then(list => {
      if (disposed) return;
      for (const { p, src } of list) {
        const holder = new THREE.Group();
        const obj = src.clone(true);
        obj.scale.setScalar(1000);
        holder.add(obj);
        const mats: THREE.MeshStandardMaterial[] = [], lines: THREE.LineBasicMaterial[] = [], hl: THREE.MeshBasicMaterial[] = [];
        const meshes: THREE.Mesh[] = [];
        obj.traverse(o => { if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh); });
        for (const mesh of meshes) {
          const m = new THREE.MeshStandardMaterial({ color: p.color ?? "#b9c3cf", metalness: 0.55, roughness: 0.36, envMapIntensity: 0.95,
            polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
          mesh.material = m; mats.push(m);
          const lm = new THREE.LineBasicMaterial({ color: "#262c36", transparent: true, opacity: 0.5 });
          mesh.add(new THREE.LineSegments(edgesOf(mesh.geometry), lm)); lines.push(lm);
          if (p.highlight) {
            const hm = new THREE.MeshBasicMaterial({ color: p.highlight.color ?? "#2f7cf0", transparent: true, opacity: 0.4, depthWrite: false,
              polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
            mesh.add(new THREE.Mesh(bandGeometry(mesh.geometry, p.highlight.rMin, p.highlight.rMax), hm)); hl.push(hm);
          }
        }
        holder.position.copy(cad(p.at ?? [0, 0, 0]));
        root.add(holder);
        insts.push({ part: p, holder, mats, lines, hl, opacity: p.show === false ? 0 : (live.current.still ? 1 : 0) });
      }
      fit();
      setReady(true);
      kick.current();
    }).catch(() => { if (!disposed) setFailed(true); });

    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect(); io.disconnect(); controls.dispose();
      for (const i of insts) { i.mats.forEach(m => m.dispose()); i.lines.forEach(m => m.dispose()); i.hl.forEach(m => m.dispose()); }
      env.dispose(); pmrem.dispose(); renderer.dispose();
      canvas.remove();
      kick.current = () => {};
    };
    // the scene is rebuilt only when the set of parts changes; other props flow through `live`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <div className={cx("relative h-full w-full", className)}>
      <div ref={host} className={cx("absolute inset-0 transition-opacity duration-700", ready ? "opacity-100" : "opacity-0", !still && "cursor-grab active:cursor-grabbing")} />
      {!ready && !failed && (poster ? <div className="absolute inset-0">{poster}</div> : <div className="absolute inset-0 flex items-center justify-center"><div className="h-16 w-16 rounded-full border-2 border-primary/20 border-t-primary/70 motion-safe:animate-spin" /></div>)}
      {failed && (poster ? <div className="absolute inset-0">{poster}</div> : <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-muted">3D preview unavailable in this browser.</div>)}
    </div>
  );
}
