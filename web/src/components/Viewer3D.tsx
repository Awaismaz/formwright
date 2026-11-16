import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { Box, Eye, Grid3x3, Ruler, Scissors } from "lucide-react";
import { cx } from "@/lib/format";
import { Tip } from "./ui";

// glTF is Y-up; build123d exports CAD +Z as glTF +Y and CAD +Y as glTF -Z.
const VIEWS: Record<string, THREE.Vector3> = {
  Iso: new THREE.Vector3(1, 0.9, 1.2), Front: new THREE.Vector3(0, 0, 1),
  Top: new THREE.Vector3(0, 1, 0.0001), Right: new THREE.Vector3(1, 0, 0),
};

type Axis = "X" | "Y" | "Z";
// CAD axis -> glTF direction (glTF is Y-up; CAD +Z = glTF +Y, CAD +Y = glTF -Z)
const AXIS_DIR: Record<Axis, THREE.Vector3> = {
  X: new THREE.Vector3(1, 0, 0), Y: new THREE.Vector3(0, 0, -1), Z: new THREE.Vector3(0, 1, 0),
};

function hatchTexture(dark: boolean) {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = dark ? "#5a3a1f" : "#f2c49b"; g.fillRect(0, 0, 64, 64);
  g.strokeStyle = dark ? "#e0965a" : "#c8742e"; g.lineWidth = 6;
  for (let i = -64; i <= 128; i += 16) { g.beginPath(); g.moveTo(i, 64); g.lineTo(i + 64, 0); g.stroke(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

interface Props { url: string | null; version?: number | string; bboxMm?: number[]; className?: string; empty?: React.ReactNode }

export default function Viewer3D({ url, version, bboxMm, className, empty }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{ setView: (v: string) => void; setEdges: (b: boolean) => void; setWire: (b: boolean) => void;
    setSection: (on: boolean, t: number, axis: Axis, flip: boolean) => number; setMeasure: (b: boolean) => void } | null>(null);
  const [edges, setEdges] = useState(true);
  const [wire, setWire] = useState(false);
  const [section, setSection] = useState(false);
  const [sectionT, setSectionT] = useState(0.5);
  const [sectionAxis, setSectionAxis] = useState<Axis>("X");
  const [sectionFlip, setSectionFlip] = useState(false);
  const [sectionMm, setSectionMm] = useState<number | null>(null);
  const [measure, setMeasure] = useState(false);
  const [measureText, setMeasureText] = useState("");
  const [loaded, setLoaded] = useState(false);
  const loadRef = useRef<(u: string) => void>(() => {});
  const bboxRef = useRef<number[] | undefined>(bboxMm);
  bboxRef.current = bboxMm;

  useEffect(() => {
    const el = host.current!;
    const dark = document.documentElement.classList.contains("dark");
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true, stencil: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.localClippingEnabled = true;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 1e6);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a93a3, 1.5));
    const key = new THREE.DirectionalLight(0xffffff, 1.7); key.position.set(3, 5, 4); scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.55); fill.position.set(-4, -2, -3); scene.add(fill);
    const clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
    const mat = new THREE.MeshStandardMaterial({ color: dark ? 0xaab4c3 : 0xb7c0cd, metalness: 0.3, roughness: 0.45,
      side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
    const edgeMat = new THREE.LineBasicMaterial({ color: dark ? 0x0b0d12 : 0x1d2330 });
    let model: THREE.Object3D | null = null;
    let edgeObjs: THREE.LineSegments[] = [];
    let box = new THREE.Box3();
    let first = true;
    let state = { edges: true, section: false, t: 0.5, measuring: false, axis: "X" as Axis, flip: false };
    // Section capping (stencil technique): back faces +1, front faces -1 inside the clipped region;
    // where the stencil is non-zero the cut plane is inside material -> draw a solid hatched cap there.
    const stencilBase = { depthWrite: false, depthTest: false, colorWrite: false, stencilWrite: true,
      stencilFunc: THREE.AlwaysStencilFunc, clippingPlanes: [clip] };
    const backMat = new THREE.MeshBasicMaterial({ ...stencilBase, side: THREE.BackSide,
      stencilFail: THREE.IncrementWrapStencilOp, stencilZFail: THREE.IncrementWrapStencilOp, stencilZPass: THREE.IncrementWrapStencilOp });
    const frontMat = new THREE.MeshBasicMaterial({ ...stencilBase, side: THREE.FrontSide,
      stencilFail: THREE.DecrementWrapStencilOp, stencilZFail: THREE.DecrementWrapStencilOp, stencilZPass: THREE.DecrementWrapStencilOp });
    const hatch = hatchTexture(dark);
    const capMat = new THREE.MeshBasicMaterial({ map: hatch, side: THREE.DoubleSide, stencilWrite: true, stencilRef: 0,
      stencilFunc: THREE.NotEqualStencilFunc, stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp,
      stencilZPass: THREE.ReplaceStencilOp });
    const cap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), capMat);
    cap.renderOrder = 2; cap.visible = false;
    cap.onAfterRender = (r) => r.clearStencil();
    scene.add(cap);
    let stencilObjs: THREE.Mesh[] = [];
    const loader = new GLTFLoader();

    const resize = () => {
      const r = el.getBoundingClientRect();
      renderer.setSize(r.width, r.height, false);
      camera.aspect = r.width / Math.max(r.height, 1); camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize); ro.observe(el); resize();

    const setView = (name: string) => {
      const c = box.getCenter(new THREE.Vector3());
      const rad = box.getBoundingSphere(new THREE.Sphere()).radius || 1;
      const dir = (VIEWS[name] ?? VIEWS.Iso!).clone().normalize();
      const vHalf = THREE.MathUtils.degToRad(camera.fov / 2);
      const hHalf = Math.atan(Math.tan(vHalf) * camera.aspect);
      const dist = rad / Math.sin(Math.min(vHalf, hHalf)) * 1.12; // fit in the narrower direction
      camera.position.copy(c).addScaledVector(dir, dist);
      camera.near = dist / 100; camera.far = dist * 100; camera.updateProjectionMatrix();
      controls.target.copy(c); controls.update();
    };
    /** Returns the cut position in CAD millimetres along the chosen axis. */
    const applySection = (): number => {
      const on = state.section && !!model;
      mat.clippingPlanes = on ? [clip] : []; edgeMat.clippingPlanes = on ? [clip] : [];
      mat.needsUpdate = edgeMat.needsUpdate = true;
      stencilObjs.forEach(o => (o.visible = on));
      cap.visible = on;
      const dir = AXIS_DIR[state.axis];
      const corners = [0, 1].flatMap(i => [0, 1].flatMap(j => [0, 1].map(k => new THREE.Vector3(
        i ? box.max.x : box.min.x, j ? box.max.y : box.min.y, k ? box.max.z : box.min.z))));
      const proj = corners.map(c => c.dot(dir));
      const lo = Math.min(...proj), hi = Math.max(...proj);
      const d = THREE.MathUtils.lerp(lo, hi, state.t);
      // keep material on the side opposite to the arrow (flip keeps the other side)
      clip.normal.copy(dir).multiplyScalar(state.flip ? 1 : -1);
      clip.constant = state.flip ? -d : d;
      const centre = box.getCenter(new THREE.Vector3());
      const onPlane = centre.clone().addScaledVector(dir, d - centre.dot(dir));
      const size = box.getSize(new THREE.Vector3()).length() * 1.5 || 1;
      cap.position.copy(onPlane);
      cap.lookAt(onPlane.clone().add(dir));
      cap.scale.set(size, size, 1);
      hatch.repeat.set(size / (size / 24), size / (size / 24));
      const s = box.getSize(new THREE.Vector3());
      const cadMax = Math.max(...(bboxRef.current ?? [Math.max(s.x, s.y, s.z)]));
      const mmPerUnit = cadMax / Math.max(s.x, s.y, s.z, 1e-9);
      return d * mmPerUnit;
    };
    const load = (u: string) => {
      loader.load(u, gltf => {
        if (model) { scene.remove(model); model.traverse(o => (o as THREE.Mesh).geometry?.dispose()); }
        edgeObjs = []; stencilObjs = [];
        model = gltf.scene;
        const meshes: THREE.Mesh[] = [];
        model.traverse(o => { if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh); });
        meshes.forEach(m => {
          {
            m.material = mat;
            const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 25), edgeMat);
            e.visible = state.edges; m.add(e); edgeObjs.push(e);
            for (const sm of [backMat, frontMat]) {
              const st = new THREE.Mesh(m.geometry, sm); st.renderOrder = 1; st.visible = false;
              m.add(st); stencilObjs.push(st);
            }
          }
        });
        scene.add(model);
        box = new THREE.Box3().setFromObject(model);
        applySection();
        if (first) { setView("Iso"); first = false; }
        setLoaded(true);
      }, undefined, () => setLoaded(false));
    };
    loadRef.current = load;

    // measuring
    const ray = new THREE.Raycaster(); const mouse = new THREE.Vector2();
    let pts: THREE.Vector3[] = []; let marks: THREE.Object3D[] = [];
    const markMat = new THREE.MeshBasicMaterial({ color: 0x1f5fbf, depthTest: false });
    const clearMarks = () => { marks.forEach(m => scene.remove(m)); marks = []; pts = []; };
    let down: [number, number] | null = null;
    const onDown = (e: PointerEvent) => { down = [e.clientX, e.clientY]; };
    const onUp = (e: PointerEvent) => {
      if (!state.measuring || !model || !down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const r = renderer.domElement.getBoundingClientRect();
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObject(model, true).find(h => (h.object as THREE.Mesh).isMesh);
      if (!hit) return;
      if (pts.length === 2) clearMarks();
      pts.push(hit.point.clone());
      const s = new THREE.Mesh(new THREE.SphereGeometry(box.getBoundingSphere(new THREE.Sphere()).radius * 0.01, 12, 8), markMat);
      s.position.copy(hit.point); s.renderOrder = 10; scene.add(s); marks.push(s);
      if (pts.length === 2) {
        const size = box.getSize(new THREE.Vector3());
        const cadMax = Math.max(...(bboxRef.current ?? [Math.max(size.x, size.y, size.z)]));
        const scale = cadMax / Math.max(size.x, size.y, size.z);
        const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x1f5fbf, depthTest: false }));
        line.renderOrder = 10; scene.add(line); marks.push(line);
        setMeasureText(`${(pts[0]!.distanceTo(pts[1]!) * scale).toFixed(2)} mm`);
      } else setMeasureText("Pick a second point");
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);

    api.current = {
      setView,
      setEdges: (b) => { state.edges = b; edgeObjs.forEach(e => (e.visible = b)); },
      setWire: (b) => { mat.wireframe = b; },
      setSection: (on, t, axis, flip) => { state = { ...state, section: on, t, axis, flip }; return applySection(); },
      setMeasure: (b) => { state.measuring = b; if (!b) clearMarks(); },
    };
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
    return () => {
      renderer.setAnimationLoop(null); ro.disconnect(); controls.dispose(); renderer.dispose();
      renderer.domElement.remove(); state = { ...state };
    };
  }, []);

  useEffect(() => { if (url) loadRef.current(`${url}${url.includes("?") ? "&" : "?"}v=${version ?? 0}`); else setLoaded(false); }, [url, version]);
  useEffect(() => { api.current?.setEdges(edges); }, [edges]);
  useEffect(() => { api.current?.setWire(wire); }, [wire]);
  useEffect(() => {
    const mm = api.current?.setSection(section, sectionT, sectionAxis, sectionFlip);
    setSectionMm(section && mm !== undefined ? mm : null);
  }, [section, sectionT, sectionAxis, sectionFlip, loaded]);
  useEffect(() => { api.current?.setMeasure(measure); setMeasureText(measure ? "Pick two points on the part" : ""); }, [measure]);

  const tool = (on: boolean, set: (v: boolean) => void, icon: React.ReactNode, label: string) => (
    <Tip content={label} side="bottom">
      <button onClick={() => set(!on)} aria-pressed={on}
        className={cx("rounded p-1.5 transition", on ? "bg-primary text-white" : "text-muted hover:bg-text/5 hover:text-text")}>{icon}</button>
    </Tip>
  );

  return (
    <div className={cx("viewport-bg relative h-full w-full overflow-hidden", className)} data-tour="viewer">
      <div ref={host} className="absolute inset-0 [&>canvas]:h-full [&>canvas]:w-full" />
      {!loaded && <div className="absolute inset-0 flex items-center justify-center">{empty}</div>}
      <div className="absolute left-3 top-3 flex items-center gap-0.5 rounded-lg border border-border bg-panel/95 p-1 shadow-card">
        {Object.keys(VIEWS).map(v => <button key={v} onClick={() => api.current?.setView(v)} className="rounded px-2 py-1 text-[12px] text-muted hover:bg-text/5 hover:text-text">{v}</button>)}
        <span className="mx-1 h-5 w-px bg-border" />
        {tool(edges, setEdges, <Box className="h-4 w-4" />, "Edges")}
        {tool(wire, setWire, <Grid3x3 className="h-4 w-4" />, "Wireframe")}
        {tool(section, setSection, <Scissors className="h-4 w-4" />, "Section view")}
        {tool(measure, setMeasure, <Ruler className="h-4 w-4" />, "Measure (mesh pick)")}
      </div>
      {section && <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-panel/95 px-3 py-1.5 text-xs shadow-card">
        <Scissors className="h-3.5 w-3.5 text-muted" />
        <span className="inline-flex overflow-hidden rounded border border-border">
          {(["X", "Y", "Z"] as Axis[]).map(a => <button key={a} onClick={() => setSectionAxis(a)}
            className={cx("px-2 py-0.5 font-semibold", sectionAxis === a ? "bg-primary text-white" : "text-muted hover:bg-text/5")}>{a}</button>)}
        </span>
        <input type="range" min={0} max={1} step={0.002} value={sectionT} onChange={e => setSectionT(+e.target.value)} aria-label="Section position" />
        <span className="w-24 tabular-nums text-text">{sectionAxis} = {sectionMm !== null ? sectionMm.toFixed(2) : "—"} mm</span>
        <button onClick={() => setSectionFlip(!sectionFlip)} className="rounded border border-border px-2 py-0.5 hover:bg-text/5" title="Keep the other side">Flip</button>
      </div>}
      {measureText && <div className="absolute bottom-3 right-3 rounded-lg border border-border bg-panel/95 px-3 py-1.5 text-xs font-medium tabular-nums shadow-card"><Eye className="mr-1 inline h-3.5 w-3.5 text-muted" />{measureText}</div>}
    </div>
  );
}
