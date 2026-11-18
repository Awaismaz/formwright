import { useEffect, useMemo, useState } from "react";

/** What the agent is doing right now, used to pick the shop-floor vocabulary. */
export type ShopPhase = "plan" | "read" | "build" | "inspect" | "finish";

/** Status words by phase, like a machinist talking you through the job. Shuffled, never repeated back to back. */
const WORDS: Record<ShopPhase, string[]> = {
  plan: ["Sketching the concept", "Laying out datums", "Squaring the stock", "Picking cutters", "Planning the setup",
    "Sizing the blank", "Choosing tolerances", "Fixturing the idea", "Zeroing the machine", "Scribing layout lines",
    "Checking the print", "Counting the features"],
  read: ["Reading the print", "Indicating the part", "Edge-finding", "Measuring up", "Studying the reference",
    "Checking the title block", "Tracing the profile"],
  build: ["Machining", "Facing off", "Roughing pockets", "Boring", "Reaming", "Tapping threads", "Chamfering edges",
    "Hobbing teeth", "Broaching", "Turning diameters", "Drilling", "Spot-facing", "Counter-boring", "Deburring",
    "Knurling", "Profiling", "Taking a finish pass", "Clearing chips"],
  inspect: ["Gauging", "Mic-ing diameters", "Checking runout", "Go / no-go testing", "Verifying tolerances",
    "Inspecting the first article", "Checking for burrs", "Measuring on the surface plate"],
  finish: ["Polishing", "Lapping", "Honing the finish", "Writing up the traveller", "Stamping the part number",
    "Bagging and tagging"],
};

function gearPath(teeth: number, rOuter: number, rRoot: number): string {
  const pts: string[] = [];
  const step = (Math.PI * 2) / teeth;
  for (let i = 0; i < teeth; i++) {
    const a = i * step;
    const seq: [number, number][] = [[rRoot, a], [rOuter, a + step * 0.18], [rOuter, a + step * 0.45], [rRoot, a + step * 0.63]];
    for (const [r, t] of seq) pts.push(`${(r * Math.cos(t)).toFixed(2)},${(r * Math.sin(t)).toFixed(2)}`);
  }
  return `M${pts.join("L")}Z`;
}

/** Two meshing spur gears; the small one turns faster by the tooth ratio, in the opposite direction. */
export function MeshingGears({ size = 30, speed = 1 }: { size?: number; speed?: number }) {
  const big = useMemo(() => gearPath(12, 10, 8), []);
  const small = useMemo(() => gearPath(8, 7, 5.2), []);
  const period = 3.2 / speed; // seconds per turn of the big gear
  return (
    <svg width={size * 1.6} height={size} viewBox="-12 -12 36 24" aria-hidden className="shrink-0 overflow-visible">
      <g style={{ transformOrigin: "0px 0px", animation: `fw-spin ${period}s linear infinite` }}>
        <path d={big} className="fill-primary/85" /><circle r={2.6} className="fill-panel" /><circle r={5.2} className="fill-none stroke-panel/60" strokeWidth={0.8} />
      </g>
      <g transform="translate(16.4 0)">
        <g style={{ transformOrigin: "0px 0px", animation: `fw-spin ${(period * 8) / 12}s linear infinite reverse` }}>
          <g transform="rotate(22.5)"><path d={small} className="fill-accent/90" /><circle r={1.9} className="fill-panel" /></g>
        </g>
      </g>
    </svg>
  );
}

/** Claude-style live status: animated gears, a rotating mechanical status word, elapsed time and the real step. */
export default function ShopStatus({ phase, since, step }: { phase: ShopPhase; since: number; step?: string | null }) {
  const [word, setWord] = useState(() => WORDS[phase][Math.floor(Math.random() * WORDS[phase].length)]!);
  const [, tick] = useState(0);
  useEffect(() => {
    const pickNext = () => setWord(w => {
      const list = WORDS[phase];
      let n = w;
      while (n === w && list.length > 1) n = list[Math.floor(Math.random() * list.length)]!;
      return n;
    });
    pickNext();
    const t = setInterval(pickNext, 2600);
    return () => clearInterval(t);
  }, [phase]);
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t); }, []);
  const s = since > 0 ? Math.max(0, Math.round((Date.now() - since) / 1000)) : 0;
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-primary/20 bg-primary-soft/40 px-2.5 py-2" role="status" aria-live="polite">
      <MeshingGears size={30} speed={phase === "build" ? 1.6 : phase === "inspect" ? 0.7 : 1} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5 text-[13.5px]">
          <span key={word} className="animate-fade-in font-medium text-primary">{word}…</span>
          {s > 0 && <span className="tabular-nums text-[11px] text-muted">{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</span>}
        </div>
        {step && <div className="truncate text-[11.5px] text-muted">{step}</div>}
      </div>
    </div>
  );
}

/** Map the agent's latest visible step to a shop phase. */
export function phaseFor(step: { name: string; brief: string; running: boolean } | null, lastWasText: boolean): ShopPhase {
  if (!step) return lastWasText ? "finish" : "plan";
  const b = step.brief.toLowerCase();
  if (step.running && step.name === "build") return "build";
  if (/check|verif|inspect|measur|compar/.test(b)) return "inspect";
  if (/read|look|review|open|stud/.test(b) && step.running) return "read";
  if (step.name === "build" && !step.running) return "inspect";
  return lastWasText ? "finish" : "plan";
}
