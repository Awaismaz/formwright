import { useRef, type ReactNode } from "react";
import {
  AlertTriangle, Boxes, Check, CheckCircle2, CircleDashed, Cog, Factory, FileUp, Gauge, Info, Layers, MousePointer2,
  PenLine, Ruler, ScanSearch, Spline, SquareDashed, Wrench,
} from "lucide-react";
import { Badge } from "@/components/ui";
import { cx } from "@/lib/format";
import LazyScene from "./LazyScene";
import type { ScenePart } from "./PartScene";
import { Reveal, useInView, useReducedMotion, useTicker } from "./motion";
import OfficeBoard from "./OfficeBoard";

export function LiveBadge({ label = "Live" }: { label?: string }) {
  return (
    <Badge tone="live">
      <span className="relative flex h-1.5 w-1.5"><span className="fw-ping absolute inset-0 rounded-full bg-success" /><span className="relative h-1.5 w-1.5 rounded-full bg-success" /></span>
      {label}
    </Badge>
  );
}

const Illustration = () => <span className="rounded-full bg-panel/90 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted ring-1 ring-border">Illustration</span>;
const RealGeometry = () => <span className="rounded-full bg-panel/90 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary ring-1 ring-primary/25">Real Formwright geometry</span>;

function Feature({ id, icon: I, eyebrow, badge, title, body, bullets, visual, flip }: {
  id?: string; icon: typeof Cog; eyebrow: string; badge: ReactNode; title: string; body: string; bullets: string[]; visual: ReactNode; flip?: boolean;
}) {
  return (
    <div id={id} className="grid scroll-mt-24 items-center gap-8 lg:grid-cols-2 lg:gap-14">
      <Reveal className={cx(flip && "lg:order-2")}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-soft text-primary"><I className="h-4 w-4" /></span>
          <span className="label">{eyebrow}</span>{badge}
        </div>
        <h3 className="mt-4 text-2xl font-semibold tracking-tight sm:text-[28px] sm:leading-tight">{title}</h3>
        <p className="mt-3 leading-relaxed text-muted">{body}</p>
        <ul className="mt-5 space-y-2 text-[14px]">
          {bullets.map((b, i) => <li key={b} className="fw-pop flex items-start gap-2" style={{ ["--d" as string]: `${0.25 + i * 0.1}s` }}><Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />{b}</li>)}
        </ul>
      </Reveal>
      <Reveal className={cx("min-w-0", flip && "lg:order-1")} delay={0.1}>{visual}</Reveal>
    </div>
  );
}

function Stage({ children, tag, className }: { children: ReactNode; tag?: ReactNode; className?: string }) {
  return (
    <div className={cx("relative overflow-hidden rounded-xl border border-border bg-panel shadow-[0_24px_60px_-28px_rgb(16_24_40/.35)]", className)}>
      {tag && <div className="pointer-events-none absolute right-3 top-3 z-10">{tag}</div>}
      {children}
    </div>
  );
}

/* ---------------- Design Studio: CommandManager, feature tree, sketcher ---------------- */

function StudioVisual() {
  const tree = ["Origin", "Sketch1 · L-profile", "Boss-Extrude1 · 50 mm", "Fillet1 · R3 inside", "Hole pattern · 4 × Ø5.5"];
  return (
    <Stage>
      <div className="pointer-events-none absolute bottom-3 left-3 z-10"><Illustration /></div>
      <div className="flex items-center gap-1 overflow-hidden border-b border-border bg-panel2 px-2 py-1.5 text-[11px]">
        {([[PenLine, "Sketch"], [Layers, "Extrude"], [Spline, "Revolve"], [SquareDashed, "Fillet"], [Wrench, "Hole"], [Boxes, "Pattern"]] as const).map(([I, l], i) => (
          <span key={l} className={cx("flex shrink-0 items-center gap-1 rounded px-1.5 py-1", i === 0 ? "bg-primary-soft text-primary" : "text-muted")}><I className="h-3.5 w-3.5" />{l}</span>
        ))}
      </div>
      <div className="grid grid-cols-[minmax(0,.8fr)_minmax(0,1.6fr)] text-[11px]">
        <div className="space-y-1 border-r border-border p-2.5">
          <div className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Feature tree</div>
          {tree.map((t, i) => (
            <div key={t} className={cx("fw-pop truncate rounded px-1.5 py-0.5", i === 1 && "bg-primary-soft text-primary")} style={{ ["--d" as string]: `${0.4 + i * 0.25}s` }}>{t}</div>
          ))}
          <div className="fw-pop mt-3 rounded-md border border-success/25 bg-success/10 px-1.5 py-1 text-[10px] font-medium text-success" style={{ ["--d" as string]: "2.2s" }}>Edit a dimension: free, instant, same answer every time</div>
        </div>
        <div className="relative bg-[radial-gradient(rgb(var(--border))_1px,transparent_1px)] [background-size:14px_14px]">
          <svg viewBox="0 0 260 220" className="h-[230px] w-full sm:h-[260px]" fill="none">
            <g stroke="rgb(var(--primary))" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round">
              <path className="fw-draw" pathLength={1} style={{ ["--len" as string]: 1 }} d="M50 40 V170 H210 V150 H72 V40 Z" />
            </g>
            <g className="fw-pop" style={{ ["--d" as string]: "1.5s" }} fill="rgb(var(--primary))">
              {[[50, 40], [50, 170], [210, 170], [210, 150], [72, 150], [72, 40]].map(([x, y]) => <rect key={`${x}${y}`} x={x! - 2.5} y={y! - 2.5} width="5" height="5" />)}
            </g>
            <g className="fw-pop" style={{ ["--d" as string]: "1.8s" }} stroke="rgb(var(--muted))" strokeWidth=".8" fontSize="9" fontFamily="Inter, sans-serif">
              <line x1="50" y1="190" x2="210" y2="190" /><line x1="50" y1="185" x2="50" y2="195" /><line x1="210" y1="185" x2="210" y2="195" />
              <text x="118" y="203" fill="rgb(var(--text))" stroke="none">60.00</text>
              <line x1="32" y1="40" x2="32" y2="170" /><line x1="27" y1="40" x2="37" y2="40" /><line x1="27" y1="170" x2="37" y2="170" />
              <text x="12" y="108" fill="rgb(var(--text))" stroke="none">40.00</text>
              <text x="80" y="100" fill="rgb(var(--muted))" stroke="none">t 5.00</text>
            </g>
            <g className="fw-pop" style={{ ["--d" as string]: "2.1s" }} fontSize="9" fontFamily="Inter, sans-serif" fill="rgb(var(--success))">
              <text x="215" y="166">⊥</text><text x="56" y="36">‖</text><text x="140" y="146">─</text>
            </g>
          </svg>
          <div className="fw-pop absolute right-2 top-2 flex items-center gap-1 rounded-md border border-border bg-panel px-2 py-1 text-[10.5px] shadow-card" style={{ ["--d" as string]: "2.4s" }}>
            <CheckCircle2 className="h-3 w-3 text-success" />Fully defined · Extrude 50 mm
          </div>
          <MousePointer2 className="fw-float absolute left-[62%] top-[30%] h-4 w-4 fill-panel text-text" />
        </div>
      </div>
    </Stage>
  );
}

/* ---------------- Toolbox: cycling real parts ---------------- */

const STEEL = "#aab3be";
const TOOLBOX: { part: ScenePart; name: string; std: string; params: string[] }[] = [
  { part: { id: "bolt", url: "/landing/hex_bolt.glb", at: [0, 0, 24], color: STEEL }, name: "Hex bolt M12 × 55", std: "ISO 4017 · Steel 8.8", params: ["M12", "L 55"] },
  { part: { id: "gear", url: "/landing/gear.glb", at: [0, 0, -6], color: "#b9c0c9" }, name: "Spur gear m2 z24", std: "ISO 53 profile, α = 20° · Steel C45", params: ["m 2", "z 24", "b 12", "bore 10"] },
  { part: { id: "bearing", url: "/landing/bearing.glb", at: [0, 0, -7], color: "#c9d0d8" }, name: "Ball bearing 6204", std: "ISO 15 envelope · 20 × 47 × 14", params: ["6204"] },
  { part: { id: "shcs", url: "/landing/shcs.glb", at: [0, 0, 11], color: "#4b5059" }, name: "Socket head cap screw M8 × 30", std: "ISO 4762 · Steel 12.9", params: ["M8", "L 30"] },
  { part: { id: "nut", url: "/landing/hex_nut.glb", at: [0, 0, -5.4], color: STEEL }, name: "Hex nut M12", std: "ISO 4032 · Steel 8", params: ["M12"] },
  { part: { id: "washer", url: "/landing/washer.glb", at: [0, 0, -1.25], color: STEEL }, name: "Plain washer M12", std: "ISO 7089 · Steel", params: ["M12"] },
];

function ToolboxVisual() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const on = useInView(ref, { threshold: 0.3 });
  const n = useTicker(on && !reduced, 2800) % TOOLBOX.length;
  const cur = TOOLBOX[n]!;
  const parts = TOOLBOX.map((t, i) => ({ ...t.part, show: i === n }));
  return (
    <Stage tag={<RealGeometry />}>
      <div ref={ref} className="viewport-bg relative h-[300px] sm:h-[340px]">
        <LazyScene parts={parts} spin={22} still={reduced} view={[1, -1, 0.9]} zoom={1.25} label={`${cur.name}, a Formwright Toolbox part. Drag to orbit.`} />
        <div className="absolute bottom-3 left-3 right-3 flex flex-wrap items-end justify-between gap-2">
          <div key={cur.name} className="animate-fade-in rounded-lg border border-border bg-panel/95 px-3 py-2 shadow-card">
            <div className="text-[13px] font-semibold">{cur.name}</div>
            <div className="text-[11px] text-muted">{cur.std}</div>
            <div className="mt-1.5 flex flex-wrap gap-1">{cur.params.map(p => <span key={p} className="rounded bg-text/[.06] px-1.5 py-0.5 font-mono text-[10.5px]">{p}</span>)}</div>
          </div>
          <span className="rounded-full bg-success/12 px-2 py-0.5 text-[10.5px] font-semibold text-success ring-1 ring-success/25">0 tokens · instant</span>
        </div>
        <div className="absolute left-3 top-3 flex gap-1">
          {TOOLBOX.map((t, i) => <span key={t.part.id} className={cx("h-1.5 rounded-full transition-all duration-500", i === n ? "w-5 bg-primary" : "w-1.5 bg-text/20")} />)}
        </div>
      </div>
    </Stage>
  );
}

/* ---------------- STEP import + feature recognition ---------------- */

function RecognitionVisual() {
  const reduced = useReducedMotion();
  const lines: [string, string][] = [
    ["Imported blank", "Exact B-rep from the STEP file · 1 solid"],
    ["Component", "Spur gear, 24 teeth, module ≈ 2.0"],
    ["Teeth", "24 × circular pattern · tip Ø52 · root Ø43"],
    ["Bore", "Ø10.0 through"],
    ["Coverage", "651 of 651 faces assigned"],
  ];
  return (
    <Stage>
      <div className="grid sm:grid-cols-[1.15fr_1fr]">
        <div className="viewport-bg relative h-[260px] sm:h-[340px]">
          <div className="pointer-events-none absolute bottom-3 left-3 z-10"><RealGeometry /></div>
          <LazyScene parts={[{ id: "gear", url: "/landing/gear.glb", color: "#bcc4ce", highlight: { rMin: 21.6, rMax: 26.5, color: "#2f7cf0" } }]}
            spin={16} still={reduced} view={[0.8, -1, 1.1]} zoom={1.15} label="An imported spur gear with its 24 recognised teeth highlighted. Drag to orbit." />
          <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-md border border-border bg-panel/95 px-2 py-1 text-[11px]"><FileUp className="h-3.5 w-3.5 text-primary" />gearbox_pinion.step</div>
        </div>
        <div className="space-y-1.5 border-t border-border p-3 text-[12px] sm:border-l sm:border-t-0">
          <div className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Recognised features</div>
          {lines.map(([k, v], i) => (
            <div key={k} className={cx("fw-pop rounded-md border px-2 py-1.5", k === "Teeth" ? "border-primary/40 bg-primary-soft" : "border-border")} style={{ ["--d" as string]: `${0.5 + i * 0.35}s` }}>
              <div className={cx("text-[10px] font-semibold uppercase tracking-wider", k === "Teeth" ? "text-primary" : "text-muted")}>{k}</div>
              <div className="font-medium">{v}</div>
            </div>
          ))}
          <p className="pt-1 text-[10.5px] text-muted">Output of the exact-geometry pass on a Toolbox gear. The AI pass then names the part and its features.</p>
        </div>
      </div>
    </Stage>
  );
}

/* ---------------- Assembly Studio: bolted flange joint, exploding ---------------- */

const PCD_R = 60;
const holes = Array.from({ length: 6 }, (_, i) => [PCD_R * Math.cos((i * Math.PI) / 3), PCD_R * Math.sin((i * Math.PI) / 3)] as const);
const ASSEMBLY: ScenePart[] = [
  { id: "f1", url: "/landing/flange.glb", at: [0, 0, 0], color: "#c4ccd6" },
  { id: "f2", url: "/landing/flange.glb", at: [0, 0, 16], explode: [0, 0, 40], color: "#9fb6d6" },
  ...holes.flatMap(([x, y], i): ScenePart[] => [
    { id: `w${i}`, url: "/landing/washer.glb", at: [x, y, 32], explode: [0, 0, 70], color: "#b3bac3" },
    { id: `b${i}`, url: "/landing/hex_bolt.glb", at: [x, y, 34.5], explode: [0, 0, 105], color: "#8f98a4" },
    { id: `v${i}`, url: "/landing/washer.glb", at: [x, y, -2.5], explode: [0, 0, -30], color: "#b3bac3" },
    { id: `n${i}`, url: "/landing/hex_nut.glb", at: [x, y, -13.3], explode: [0, 0, -55], color: "#8f98a4" },
  ]),
];

function AssemblyVisual() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const on = useInView(ref, { threshold: 0.3 });
  const tick = useTicker(on && !reduced, 2600);
  const exploded = reduced ? true : tick % 2 === 1;
  return (
    <Stage>
      <div ref={ref} className="grid sm:grid-cols-[1.1fr_1fr]">
        <div className="viewport-bg relative h-[280px] sm:h-[360px]">
          <div className="pointer-events-none absolute bottom-3 left-3 z-10"><RealGeometry /></div>
          <LazyScene parts={ASSEMBLY} explode={exploded ? 1 : 0} spin={10} still={reduced} view={[1, -1.1, 0.55]} zoom={1.05} label="Two flanges bolted with six M12 bolts, washers and nuts, shown assembled and exploded. Drag to orbit." />
          <span className="absolute left-3 top-3 rounded-md border border-border bg-panel/95 px-2 py-1 text-[11px] font-medium">{exploded ? "Exploded view" : "Assembled · 0 interferences"}</span>
        </div>
        <div className="space-y-3 border-t border-border p-3 text-[12px] sm:border-l sm:border-t-0">
          <div>
            <div className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Mates</div>
            <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
              <li>Coincident · flange ↔ flange</li><li>Concentric · bore ↔ bore</li><li>Concentric · Ø14 ↔ M12 × 6</li>
            </ul>
          </div>
          <div>
            <div className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Fastener auto-fit</div>
            <table className="mt-1 w-full text-[11.5px] tabular-nums"><tbody className="divide-y divide-border">
              {[["Grip measured", "16 + 16 = 32"], ["Washers 7089", "2 × 2.5"], ["Nut 4032", "10.8"], ["Protrusion 2P", "3.5"], ["Min. length", "≥ 51.3 → M12×55"]].map(([k, v]) => (
                <tr key={k}><td className="py-1 pr-2 text-muted">{k}</td><td className="whitespace-nowrap py-1 text-right font-medium">{v}</td></tr>))}
            </tbody></table>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-muted"><Badge tone="warning">VERIFY</Badge>ISO tables and a stated rule, not a joint calculation.</div>
        </div>
      </div>
    </Stage>
  );
}

/* ---------------- Drawing Studio ---------------- */

function DrawingVisual() {
  const d = (s: number) => ({ ["--d" as string]: `${s}s`, ["--len" as string]: 1 });
  // flange Ø150 × 16, Ø60 bore, 6 × Ø14 on PCD 120 at 1.12 px/mm; section A-A cuts the vertical centreline
  const k = 1.12, cx0 = 130, cy0 = 160, R = 75 * k, rb = 30 * k, rp = 60 * k, rh = 7 * k, t = 16 * k, sx = 270;
  const holeXY = Array.from({ length: 6 }, (_, i) => [cx0 + rp * Math.cos(i * Math.PI / 3 + Math.PI / 6), cy0 + rp * Math.sin(i * Math.PI / 3 + Math.PI / 6)]);
  const top = cy0 - R, bot = cy0 + R;
  const cuts = [cy0 - rp - rh, cy0 - rp + rh, cy0 - rb, cy0 + rb, cy0 + rp - rh, cy0 + rp + rh];
  const solid: [number, number][] = [[top, cuts[0]!], [cuts[1]!, cuts[2]!], [cuts[3]!, cuts[4]!], [cuts[5]!, bot]];
  return (
    <Stage className="p-3">
      <div className="pointer-events-none absolute right-5 top-5 z-10"><Illustration /></div>
      <svg viewBox="0 0 520 330" className="w-full rounded-md border border-border bg-white" fill="none">
        <defs><pattern id="fw-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" stroke="#1d2330" strokeWidth=".7" /></pattern></defs>
        <rect x="6" y="6" width="508" height="318" stroke="#1d2330" strokeWidth="1.2" />
        {/* front view */}
        <g stroke="#1d2330" strokeWidth="1.3">
          <circle className="fw-draw" pathLength={1} style={d(0.2)} cx={cx0} cy={cy0} r={R} />
          <circle className="fw-draw" pathLength={1} style={d(0.5)} cx={cx0} cy={cy0} r={rb} />
          {holeXY.map(([x, y], i) => <circle key={i} className="fw-draw" pathLength={1} style={d(0.8 + i * 0.08)} cx={x} cy={y} r={rh} />)}
        </g>
        <g className="fw-pop" style={d(1.2)} stroke="#c8742e" strokeWidth=".7" strokeDasharray="8 2 2 2">
          <circle cx={cx0} cy={cy0} r={rp} /><line x1={cx0 - R - 10} y1={cy0} x2={cx0 + R + 10} y2={cy0} /><line x1={cx0} y1={top - 10} x2={cx0} y2={bot + 10} />
        </g>
        {/* section A-A */}
        <g className="fw-pop" style={d(1.4)}>{solid.map(([a, b]) => <rect key={a} x={sx} y={a} width={t} height={b - a} fill="url(#fw-hatch)" />)}</g>
        <g stroke="#1d2330" strokeWidth="1.3">
          <rect className="fw-draw" pathLength={1} style={d(1.0)} x={sx} y={top} width={t} height={bot - top} />
          <path className="fw-draw" pathLength={1} style={d(1.3)} d={cuts.map(y => `M${sx} ${y.toFixed(1)} H${sx + t}`).join(" ")} />
        </g>
        <g className="fw-pop" style={d(1.7)} stroke="#1F5FBF" strokeWidth=".7">
          <line x1={cx0 - R} y1={top - 18} x2={cx0 + R} y2={top - 18} /><line x1={cx0 - R} y1={top - 23} x2={cx0 - R} y2={top - 4} /><line x1={cx0 + R} y1={top - 23} x2={cx0 + R} y2={top - 4} />
          <line x1={sx} y1={top - 10} x2={sx + t} y2={top - 10} />
          <line x1={holeXY[0]![0] + rh * 0.7} y1={holeXY[0]![1] + rh * 0.7} x2={cx0 + R + 6} y2={bot + 14} /><line x1={cx0 + R + 6} y1={bot + 14} x2={cx0 + R + 20} y2={bot + 14} />
        </g>
        <g className="fw-pop" style={d(1.8)} fill="#1F5FBF" stroke="none" fontSize="10" fontFamily="Inter, sans-serif">
          <text x={cx0 - 12} y={top - 22}>Ø150</text><text x={cx0 + 4} y={cy0 - 4}>Ø60</text>
          <text x={sx + t + 4} y={top - 7}>16</text>
          <text x={cx0 + R - 64} y={bot + 28}>6× Ø14 THRU EQ SP</text><text x={cx0 + R - 64} y={bot + 40}>ON PCD 120</text>
        </g>
        <g className="fw-pop" style={d(1.8)} fill="#1d2330" fontSize="9" fontWeight="600" fontFamily="Inter, sans-serif">
          <text x={sx - 22} y={bot + 18}>SECTION A-A</text><text x={cx0 - 48} y={bot + 18}>FRONT</text>
        </g>
        <g className="fw-pop" style={d(2.0)}>
          <rect x="330" y="246" width="176" height="70" stroke="#1d2330" />
          <g fontSize="8.5" fontFamily="Inter, sans-serif" fill="#1d2330">
            <text x="338" y="261" fontWeight="700">FLANGE Ø150 × 16</text><text x="338" y="274">Material: Al 6061-T6 · Units: mm</text>
            <text x="338" y="287">A4 · Third angle · Sheet 1/1</text>
            <text x="338" y="300" fill="#c43228" fontWeight="700">NOT APPROVED FOR MANUFACTURE</text>
            <text x="338" y="311" fill="#5b6475">Dims: ● spec  ○ inferred</text>
          </g>
        </g>
      </svg>
    </Stage>
  );
}

/* ---------------- Manufacturing + Engineering advisors ---------------- */

function AdvisorsVisual() {
  const procs: [string, number, string][] = [["Turning + drilling", 92, "Recommended"], ["CNC milling", 74, "Alternative"], ["Waterjet + facing", 48, "Loses the bore finish"]];
  const calcs: [string, string, string, typeof Info, string][] = [
    ["Bolted joint · 6 × M12 8.8", "Preload ≈ 34 kN per bolt at 70 % proof", "Hand calculation", CheckCircle2, "text-success"],
    ["Flange bending between bolts", "σ well below yield for the stated load", "Preliminary estimate", Info, "text-primary"],
    ["Fatigue", "Load spectrum unknown: needs input", "Recommended check", AlertTriangle, "text-warning"],
    ["Validated simulation", "Requires external FEA and engineer sign-off", "Not performed", CircleDashed, "text-muted"],
  ];
  return (
    <div className="grid gap-4">
      <Stage tag={<Illustration />} className="p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold"><Factory className="h-4 w-4 text-primary" />Manufacturing Advisor · flange, qty 50</div>
        <div className="mt-3 space-y-2">
          {procs.map(([p, v, l], i) => (
            <div key={p} className="text-[12px]">
              <div className="flex justify-between"><span className="font-medium">{p}</span><span className="text-muted">{l}</span></div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-text/[.07]">
                <div className={cx("fw-bar h-full rounded-full", i === 0 ? "bg-success" : "bg-primary/60")}
                  style={{ width: `${v}%`, transitionDelay: `${0.3 + i * 0.15}s` }} />
              </div>
            </div>
          ))}
        </div>
        <div className="fw-pop mt-3 flex items-start gap-2 rounded-md border border-border px-2.5 py-2 text-[12px]" style={{ ["--d" as string]: "1.2s" }}>
          <Badge tone="success">OK</Badge><span>6 × Ø14 holes: stock drill size, 8 mm wall to the outside edge.</span>
        </div>
      </Stage>
      <Stage tag={<Illustration />} className="p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold"><Gauge className="h-4 w-4 text-primary" />Engineering Advisor</div>
        <ul className="mt-3 space-y-1.5 text-[12px]">
          {calcs.map(([t, dsc, lvl, I, c], i) => (
            <li key={t} className="fw-pop flex items-start gap-2.5 rounded-md border border-border px-2.5 py-2" style={{ ["--d" as string]: `${0.4 + i * 0.25}s` }}>
              <I className={cx("mt-0.5 h-4 w-4 shrink-0", c)} />
              <div className="min-w-0 flex-1"><div className="font-medium">{t}</div><div className="text-[11px] text-muted">{dsc}</div></div>
              <Badge className="hidden shrink-0 sm:inline-flex">{lvl}</Badge>
            </li>
          ))}
        </ul>
      </Stage>
    </div>
  );
}

/* ---------------- the section ---------------- */

export default function Showcase() {
  return (
    <section id="tour" className="relative scroll-mt-20 overflow-hidden border-b border-border">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <Reveal className="mx-auto max-w-2xl text-center">
          <div className="label">A tour of the platform</div>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">See what it actually does.</h2>
          <p className="mt-3 text-muted">The 3D stages below are real parts made by Formwright, rendered live in your browser. Drag any of them to orbit.</p>
        </Reveal>
        <div className="mt-16 space-y-24">
          <Feature id="studio" icon={PenLine} eyebrow="Design Studio" badge={<LiveBadge />}
            title="Talk to it, or drive it by hand."
            body="Brief the design agent in plain language and watch the exact B-rep model build in the viewer. Or work the way you always have: a feature tree, a constrained 2D sketcher and a CommandManager ribbon for extrude, revolve, fillet, holes and patterns."
            bullets={["Parametric feature tree: edit, suppress, reorder, restore", "2D sketcher with dimensions and constraints", "Manual edits are free and deterministic"]}
            visual={<StudioVisual />} />
          <Feature id="toolbox" icon={Cog} eyebrow="Toolbox" badge={<LiveBadge label="Included" />} flip
            title="Standard parts, to the standard."
            body="Bolts, nuts, washers, bearings, gears, shafts, dowels, flanges and brackets, generated from the ISO tables at the size you ask for. Drop them into a part or an assembly without spending a token."
            bullets={["ISO 4017, 4032, 4762, 7089 fasteners; ISO 53 involute gears", "Every part passes the same gating checks as agent work", "Offered automatically when your brief matches a standard part"]}
            visual={<ToolboxVisual />} />
          <Feature id="import" icon={ScanSearch} eyebrow="STEP import + feature recognition" badge={<LiveBadge />}
            title="Bring your own parts. It reads them."
            body="Import a STEP file as an exact solid, then let recognition find the stock, holes, patterns, bosses, fillets, chamfers and gear teeth on it. Recognised holes and patterns become editable features on the exact body."
            bullets={["Exact-geometry pass, then an AI pass that names the part", "Recognised faces highlight in the viewer", "Edit hole patterns on a part you didn't model"]}
            visual={<RecognitionVisual />} />
          <Feature id="assembly" icon={Boxes} eyebrow="Assembly Studio" badge={<LiveBadge />} flip
            title="Mate it, check it, explode it."
            body="Assemble verified parts and Toolbox components with mates that report what is still free. Interference is computed on the exact B-rep, and Fastener auto-fit sizes the bolt stack from the measured grip."
            bullets={["Coincident, concentric, distance and angle mates with DOF analysis", "Exact interference volumes and minimum clearances", "Exploded view, BOM and assembly STEP"]}
            visual={<AssemblyVisual />} />
          <Feature id="drawings" icon={Ruler} eyebrow="Drawing Studio" badge={<LiveBadge />}
            title="A drawing sheet from the model, not from scratch."
            body="Hidden-line views, a hatched section, hole callouts and a title block, with every dimension tagged as specified or inferred. Sheets regenerate when the model changes and stay marked not approved for manufacture until your engineer signs."
            bullets={["Front, top, right and isometric; first or third angle", "SVG, PDF and DXF export", "Consistency-checked against the model"]}
            visual={<DrawingVisual />} />
          <Feature id="advisors" icon={Factory} eyebrow="Manufacturing & Engineering Advisors" badge={<LiveBadge />} flip
            title="Ask the shop and the stress engineer early."
            body="Advisory DFM checks on the exact model with a ranked process shortlist and a relative cost (not a quote), plus hand-calculation checks for beams, bolted joints, shafts, fits and springs with the working shown."
            bullets={["Every result carries its advice level", "Inputs pre-filled from the model", "Never labelled validated: sign-off stays with your engineers"]}
            visual={<AdvisorsVisual />} />
        </div>
      </div>
      <OfficeBoard />
    </section>
  );
}
