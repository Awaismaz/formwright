import { useEffect, useRef, useState, type MutableRefObject } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { AgentAvatar } from "@/pages/app/office/Avatars";
import manifest from "./gearbox.json";
import { planetPhase, pose, spinUp, type GearSet } from "./kinematics";
import {
  ASSEMBLED_AT, BLANKS_AT, BUILD, BUILD_DUR, CHAPTERS, EXPLODE_DZ, FLY, RUN_AT, SEAT, SUN_SPEED, ease, easeOut, seatAt, span,
} from "./story";

/**
 * The hero's 3D stage: the real PG-5 gearbox parts (scripts/landing_assets.py) driven entirely by the story clock.
 * Build flash (stock blank machined into each part), fly-in to an exploded view, bottom-up assembly, then the gearbox
 * runs with exact planetary kinematics. Every pose is a pure function of `time.current`, so scrubbing just works.
 */

type Move = "fixed" | "sun" | "carrier" | "planet";
type Inst = { id: string; part: string; at: number[]; move: Move };
const INST = manifest.instances as Inst[];
const G: GearSet = { zs: manifest.gear.zs, zp: manifest.gear.zp, zr: manifest.gear.zr, n: manifest.gear.n, m: manifest.gear.m };
const PARTS = [...new Set(INST.map(i => i.part))];

const LOOK: Record<string, { color: string; metal: number; rough: number }> = {
  housing: { color: "#aeb9c7", metal: 0.6, rough: 0.4 },
  ring: { color: "#8c97a6", metal: 0.85, rough: 0.3 },
  sun: { color: "#d8975a", metal: 0.9, rough: 0.28 },
  planet: { color: "#b9c3cf", metal: 0.9, rough: 0.26 },
  carrier: { color: "#4a7cc9", metal: 0.55, rough: 0.34 },
  shaft: { color: "#dfe4ea", metal: 0.95, rough: 0.18 },
  bearing: { color: "#a9b3bf", metal: 0.9, rough: 0.24 },
  screw: { color: "#30353d", metal: 0.6, rough: 0.42 },
};
const LOOK_OF: Record<string, keyof typeof LOOK> = {
  input_cover: "housing", output_cover: "housing", motor_flange: "housing", ring: "ring", sun: "sun", planet: "planet",
  carrier_a: "carrier", carrier_b: "carrier", input_shaft: "shaft", output_shaft: "shaft", pin: "shaft", dowel: "shaft",
  b6204: "bearing", b6001: "bearing", b6000: "bearing", shcs_m5: "screw",
};
/** While it runs, the output side turns to glass so the gear train shows (final opacity per part). */
const GHOST: Record<string, number> = { output_cover: 0.06, b6204: 0.07, shcs_m5: 0.14, dowel: 0.2, carrier_b: 0.24, output_shaft: 0.3 };

const cad = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);
const v3 = new THREE.Vector3();

type Unique = {
  geo: THREE.BufferGeometry; edges: THREE.EdgesGeometry; box: THREE.Box3; centre: THREE.Vector3; size: THREE.Vector3;
  slot: THREE.Vector3; scale: number; item: (typeof BUILD)[number];
};
type Node = {
  inst: Inst; u: Unique; first: boolean; holder: THREE.Group; inner: THREE.Group; mat: THREE.MeshStandardMaterial;
  line: THREE.LineBasicMaterial; asm: THREE.Vector3; exploded: THREE.Vector3; phase: number; k: number; order: number;
  stock?: THREE.Mesh; glow?: THREE.Mesh; clip: THREE.Plane; stockClip: THREE.Plane; clipping: boolean;
};

export type StageProps = {
  time: MutableRefObject<number>;
  still?: boolean;
  compact?: boolean;
  onLoad?: (fraction: number) => void;
  label: string;
};

export default function GearboxStage({ time, still = false, compact = false, onLoad, label }: StageProps) {
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const onLoadRef = useRef(onLoad);
  onLoadRef.current = onLoad;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch { setFailed(true); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, compact ? 1.5 : 1.75));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.localClippingEnabled = true;
    const canvas = renderer.domElement;
    canvas.style.cssText = "display:block;width:100%;height:100%";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", label);
    el.appendChild(canvas);

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 0.85;
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(260, 420, 300);
    const rim = new THREE.DirectionalLight(0x7fb0ff, 1.1);
    rim.position.set(-300, 120, -360);
    scene.add(key, rim, new THREE.HemisphereLight(0xe6eef9, 0x2a3240, 0.45));

    // soft contact shadow under the assembled gearbox
    const shadowTex = (() => {
      const c = document.createElement("canvas");
      c.width = c.height = 128;
      const g = c.getContext("2d")!;
      const grd = g.createRadialGradient(64, 64, 4, 64, 64, 64);
      grd.addColorStop(0, "rgba(0,0,0,.55)"); grd.addColorStop(0.55, "rgba(0,0,0,.22)"); grd.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
      return new THREE.CanvasTexture(c);
    })();
    const shadowMat = new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false, opacity: 0 });
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(300, 300), shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = -27;
    scene.add(shadow);

    const camera = new THREE.PerspectiveCamera(30, 1, 5, 6000);
    const nodes: Node[] = [];
    let gridCentre = new THREE.Vector3();
    let gridHalf = { w: 470, h: 300 };
    let disposed = false;
    let raf = 0;
    let visible = true;
    let aspect = 1;
    // a still stage (reduced motion) renders a handful of frames after load/resize, then stops
    let stillFrames = 0;
    const kickStill = () => { if (!raf && !disposed) raf = requestAnimationFrame(loop); };

    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      aspect = w / h;
      camera.aspect = aspect;
      camera.updateProjectionMatrix();
      if (still) { stillFrames = 12; kickStill(); }
    };

    // ---------------------------------------------------------------- camera keyframes (three coords)
    /** Camera keyframe: orbit angles about `target` and the half width/height (mm) that must stay in frame. */
    type Cam = { target: THREE.Vector3; az: number; el: number; w: number; h: number };
    const camAt = (t: number): Cam => {
      const grid: Cam = { target: gridCentre, az: 1.2 + 0.12 * span(t, CHAPTERS[3].start, FLY.start), el: 0.92, ...gridHalf };
      const exploded: Cam = { target: new THREE.Vector3(0, 22, 0), az: 0.62, el: 0.2, w: 125, h: 300 };
      const assembled: Cam = { target: new THREE.Vector3(0, 12, 0), az: 0.7 + 0.25 * span(t, ASSEMBLED_AT - 2, RUN_AT), el: 0.45, w: 120, h: 108 };
      const run: Cam = { target: new THREE.Vector3(0, 2, 0), az: 1.0 + 0.55 * span(t, RUN_AT, RUN_AT + 14), el: 0.78, w: 84, h: 72 };
      const mix = (a: Cam, b: Cam, k: number): Cam => ({
        target: a.target.clone().lerp(b.target, k), az: a.az + (b.az - a.az) * k, el: a.el + (b.el - a.el) * k, w: a.w + (b.w - a.w) * k, h: a.h + (b.h - a.h) * k,
      });
      if (t < FLY.start) return grid;
      if (t < SEAT.start) return mix(grid, exploded, ease(span(t, FLY.start, SEAT.start)));
      if (t < RUN_AT) return mix(exploded, assembled, ease(span(t, SEAT.start + 0.6, ASSEMBLED_AT + 0.4)));
      return mix(assembled, run, ease(span(t, RUN_AT, RUN_AT + 2.6)));
    };
    const placeCamera = (c: Cam) => {
      const tv = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      const d = Math.max(c.h / tv, c.w / (tv * aspect));
      camera.position.set(
        c.target.x + d * Math.cos(c.el) * Math.cos(c.az), c.target.y + d * Math.sin(c.el), c.target.z + d * Math.cos(c.el) * Math.sin(c.az));
      camera.near = d / 20; camera.far = d * 8;
      camera.updateProjectionMatrix();
      camera.lookAt(c.target);
    };

    // ---------------------------------------------------------------- per-frame pose
    const sunAngleAt = (t: number) => spinUp(t - RUN_AT, SUN_SPEED);
    const labelEls = () => Array.from(labels.current?.children ?? []) as HTMLElement[];

    const frame = () => {
      if (disposed || !nodes.length) return;
      const t = time.current;
      const buildOn = t >= CHAPTERS[3].start - 0.01;
      const p = pose(sunAngleAt(t), G);
      for (const n of nodes) {
        const { u, inst } = n;
        const it = u.item;
        // build flash state (only the first instance of each part lives on the table)
        const buildK = it.stock ? ease(span(t, it.at, it.at + BUILD_DUR)) : 1;
        const popK = it.stock ? 1 : easeOut(span(t, it.at, it.at + 0.35));
        const flyK = ease(span(t, FLY.start + n.order * FLY.stagger, FLY.start + n.order * FLY.stagger + FLY.dur));
        const seatK = ease(span(t, seatAt(inst.part), seatAt(inst.part) + SEAT.dur));
        const onTable = buildOn && t < FLY.start + n.order * FLY.stagger;
        const show = buildOn && (onTable ? n.first && (it.stock ? t >= BLANKS_AT : t >= it.at) : true);
        n.holder.visible = show;
        if (!show) continue;

        // position / scale: table slot -> exploded -> assembled
        const s = THREE.MathUtils.lerp(u.scale, 1, flyK) * (onTable && !it.stock ? 0.2 + 0.8 * popK : 1);
        const exploded = v3.copy(u.slot).lerp(n.exploded, flyK);
        exploded.y += Math.sin(Math.PI * flyK) * 60;
        const pos = exploded.lerp(n.asm, seatK);
        n.inner.position.copy(u.centre).multiplyScalar(-(1 - flyK));
        n.holder.scale.setScalar(s);
        // running: orbit and spin
        let rot = n.phase;
        if (inst.move === "sun") rot = p.sun;
        else if (inst.move === "carrier" || inst.move === "planet") {
          rot = inst.move === "carrier" ? p.carrier : p.planets[n.k]!.spin;
          pos.applyAxisAngle(THREE.Object3D.DEFAULT_UP, p.carrier);
        }
        n.holder.position.copy(pos);
        n.holder.rotation.y = rot;

        // machining sweep: finished part above the plane, stock blank below
        const clipping = !!it.stock && onTable && buildK < 1;
        if (clipping !== n.clipping) {
          n.mat.clippingPlanes = clipping ? [n.clip] : null;
          n.line.clippingPlanes = clipping ? [n.clip] : null;
          n.mat.needsUpdate = true; n.line.needsUpdate = true;
          n.clipping = clipping;
        }
        if (n.stock && n.glow) {
          const stockOn = onTable && buildK < 1;
          n.stock.visible = stockOn;
          n.glow.visible = stockOn && buildK > 0;
          if (stockOn) {
            n.holder.updateMatrixWorld(true);
            const yTop = u.box.max.y - u.centre.y, yBot = u.box.min.y - u.centre.y;
            const yLocal = THREE.MathUtils.lerp(yTop + 2, yBot - 2, buildK);
            const yWorld = n.holder.position.y + yLocal * s;
            n.clip.set(new THREE.Vector3(0, 1, 0), -yWorld);
            n.stockClip.set(new THREE.Vector3(0, -1, 0), yWorld);
            n.glow.position.y = yLocal;
            (n.glow.material as THREE.MeshBasicMaterial).opacity = 0.75 * Math.sin(Math.PI * buildK);
          }
        }
        // emissive flash as a part completes, ghosting while it runs
        const done = it.at + (it.stock ? BUILD_DUR : 0.35);
        const flash = onTable ? Math.max(0, 1 - Math.abs(t - done) / 0.45) : 0;
        n.mat.emissive.setRGB(0.12 * flash, 0.3 * flash, 0.75 * flash);
        const ghost = inst.part in GHOST ? ease(span(t, RUN_AT + 0.3, RUN_AT + 1.8)) : 0;
        const o = 1 - ghost * (1 - (GHOST[inst.part] ?? 1));
        const tr = o < 0.995;
        if (n.mat.transparent !== tr) { n.mat.transparent = tr; n.mat.depthWrite = !tr; n.mat.needsUpdate = true; }
        n.mat.opacity = o;
        n.line.opacity = 0.32 * Math.min(1, o * 1.3);
      }
      shadowMat.opacity = 0.9 * span(t, ASSEMBLED_AT - 1.2, ASSEMBLED_AT);
      placeCamera(camAt(t));
      renderer.render(scene, camera);

      // table labels (build chapter)
      const els = labelEls();
      const labelOn = t >= CHAPTERS[3].start && t < FLY.start + 0.2;
      const w = el.clientWidth, h = el.clientHeight;
      PARTS_ORDER.forEach((part, i) => {
        const le = els[i];
        if (!le) return;
        const u = uniques.get(part);
        const it = u?.item;
        const doneAt = it ? it.at + (it.stock ? BUILD_DUR : 0.35) : Infinity;
        const latest = !compact || PARTS_ORDER.every(q => { const o = uniques.get(q)?.item; return !o || o.at + (o.stock ? BUILD_DUR : 0.35) <= doneAt || o.at + (o.stock ? BUILD_DUR : 0.35) > t; });
        if (!u || !labelOn || t < doneAt - 0.1 || !latest) { le.style.opacity = "0"; return; }
        v3.copy(u.slot); v3.y -= (u.size.y / 2) * u.scale + 6;
        v3.project(camera);
        le.style.opacity = String(Math.min(1, (t - doneAt + 0.1) / 0.3) * (1 - span(t, FLY.start - 0.3, FLY.start + 0.2)));
        le.style.transform = `translate(-50%, 0) translate(${((v3.x + 1) / 2) * w}px, ${((1 - v3.y) / 2) * h}px)`;
      });
    };

    const loop = () => {
      raf = 0;
      if (disposed) return;
      frame();
      if (visible && (!still || stillFrames-- > 0)) raf = requestAnimationFrame(loop);
    };

    // ---------------------------------------------------------------- loading
    const uniques = new Map<string, Unique>();
    const PARTS_ORDER = BUILD.map(b => b.part);
    const loader = new GLTFLoader();
    let loaded = 0;
    Promise.all(PARTS.map(part => loader.loadAsync(`/landing/gearbox/${part}.glb`).then(g => {
      loaded += 1;
      onLoadRef.current?.(loaded / PARTS.length);
      let geo: THREE.BufferGeometry | null = null;
      g.scene.traverse(o => { if (!geo && (o as THREE.Mesh).isMesh) geo = (o as THREE.Mesh).geometry; });
      const gm = (geo as unknown as THREE.BufferGeometry).clone();
      gm.scale(1000, 1000, 1000);
      gm.computeBoundingBox();
      return [part, gm] as const;
    }))).then(list => {
      if (disposed) return;
      const wide = aspect > 1.25;
      const cols = wide ? 6 : 4;
      const pitch = 150;
      const rows = Math.ceil(BUILD.length / cols);
      BUILD.forEach((item, i) => {
        const gm = list.find(([p]) => p === item.part)![1];
        const box = gm.boundingBox!.clone();
        const size = box.getSize(new THREE.Vector3());
        const centre = box.getCenter(new THREE.Vector3());
        const r = i % cols, c = Math.floor(i / cols);
        const inRow = c === rows - 1 ? BUILD.length - c * cols : cols;
        const slot = new THREE.Vector3((r - (inRow - 1) / 2) * pitch, 0, (c - (rows - 1) / 2) * pitch * 0.95);
        const scale = THREE.MathUtils.clamp(112 / Math.max(size.x, size.y, size.z), 0.72, 3.2);
        uniques.set(item.part, { geo: gm, edges: new THREE.EdgesGeometry(gm, 30), box, centre, size, slot, scale, item });
      });
      gridCentre = new THREE.Vector3(0, 0, 0);
      gridHalf = wide ? { w: 470, h: 300 } : { w: 390, h: 300 };
      let order = 0;
      for (const inst of INST) {
        const u = uniques.get(inst.part)!;
        const lk = LOOK[LOOK_OF[inst.part] ?? "housing"]!;
        const mat = new THREE.MeshStandardMaterial({ color: lk.color, metalness: lk.metal, roughness: lk.rough, envMapIntensity: 1,
          polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, side: THREE.DoubleSide });
        const line = new THREE.LineBasicMaterial({ color: "#10141a", transparent: true, opacity: 0.32 });
        const holder = new THREE.Group();
        const inner = new THREE.Group();
        inner.add(new THREE.Mesh(u.geo, mat), new THREE.LineSegments(u.edges, line));
        holder.add(inner);
        scene.add(holder);
        const [x, y, z] = inst.at as [number, number, number];
        const asm = cad(x, y, z);
        const exploded = cad(x, y, z + (EXPLODE_DZ[inst.part] ?? 0));
        const k = inst.move === "planet" ? Math.round(Math.atan2(y, x) / ((2 * Math.PI) / G.n) + G.n) % G.n : 0;
        const node: Node = {
          inst, u, first: !nodes.some(n => n.inst.part === inst.part), holder, inner, mat, line, asm, exploded,
          phase: inst.move === "planet" ? planetPhase(k, G) : 0, k, order: order++,
          clip: new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), stockClip: new THREE.Plane(new THREE.Vector3(0, -1, 0), 0), clipping: false,
        };
        if (node.first && u.item.stock) {
          const stockGeo = u.item.stock === "box"
            ? new THREE.BoxGeometry(u.size.x + 1, u.size.y + 1, u.size.z + 1)
            : new THREE.CylinderGeometry(Math.max(u.size.x, u.size.z) / 2 + 0.5, Math.max(u.size.x, u.size.z) / 2 + 0.5, u.size.y + 1, 56);
          const stockMat = new THREE.MeshStandardMaterial({ color: "#9aa5b3", metalness: 0.35, roughness: 0.55, clippingPlanes: [node.stockClip] });
          node.stock = new THREE.Mesh(stockGeo, stockMat);
          const gr = Math.max(u.size.x, u.size.z) / 2 + 3;
          const glowGeo = u.item.stock === "box" ? new THREE.PlaneGeometry(u.size.x + 6, u.size.z + 6) : new THREE.CircleGeometry(gr, 56);
          node.glow = new THREE.Mesh(glowGeo, new THREE.MeshBasicMaterial({ color: "#5ea8ff", transparent: true, opacity: 0, depthWrite: false,
            blending: THREE.AdditiveBlending, side: THREE.DoubleSide }));
          node.glow.rotation.x = -Math.PI / 2;
          holder.add(node.stock, node.glow);
        }
        nodes.push(node);
      }
      resize();
      onLoadRef.current?.(1);
      if (still) { stillFrames = 12; kickStill(); } else if (!raf) raf = requestAnimationFrame(loop);
    }).catch(() => { if (!disposed) setFailed(true); });

    const ro = new ResizeObserver(resize);
    ro.observe(el);
    const io = new IntersectionObserver(([e]) => {
      visible = !!e?.isIntersecting;
      if (visible && !still && !raf && nodes.length) raf = requestAnimationFrame(loop);
    });
    io.observe(el);
    resize();

    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect(); io.disconnect();
      scene.traverse(o => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        const mm = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mm)) mm.forEach(x => x.dispose()); else mm?.dispose();
      });
      shadowTex.dispose(); env.dispose(); pmrem.dispose(); renderer.dispose();
      canvas.remove();
    };
  }, [time, still, compact, label]);

  return (
    <div className="absolute inset-0">
      <div ref={host} className="absolute inset-0" />
      <div ref={labels} className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
        {BUILD.map(b => (
          <div key={b.part} className="absolute left-0 top-0 flex items-center gap-1 whitespace-nowrap rounded-full bg-[#0d1117]/80 py-0.5 pl-0.5 pr-2 text-[10.5px] font-medium text-white opacity-0 ring-1 ring-white/10 backdrop-blur-sm">
            <AgentAvatar code={b.agent} state="done" size={16} still label={b.label} />
            <span className="text-[#7ee2a8]">✓</span>{b.label}
          </div>
        ))}
      </div>
      {failed && <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-white/60">3D view unavailable in this browser.</div>}
    </div>
  );
}
