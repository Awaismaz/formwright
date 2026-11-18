import { useLayoutEffect, useRef } from "react";
import { Box, Cog, Compass, Container, Disc3, Drill, FoldVertical, Gauge, Hammer, Hexagon, PenTool, Puzzle } from "lucide-react";
import { cx } from "@/lib/format";
import { Reveal, useInView, useReducedMotion, useTicker } from "./motion";

/** The Design Office (docs/plans/CHIEF_DESIGNER.md): a Chief Designer running named specialist agents on a live board. */

type Agent = { name: string; role: string; color: string; icon: typeof Box };
const AGENTS: Record<string, Agent> = {
  Archie: { name: "Archie", role: "Chief Designer", color: "#1F5FBF", icon: Compass },
  Mill: { name: "Mill", role: "Machined parts", color: "#3B7DD8", icon: Drill },
  Chuck: { name: "Chuck", role: "Turned parts", color: "#C8742E", icon: Disc3 },
  Axel: { name: "Axel", role: "Gears & drives", color: "#7A5AC8", icon: Cog },
  Benny: { name: "Benny", role: "Sheet metal", color: "#2E9C8F", icon: FoldVertical },
  Molly: { name: "Molly", role: "Moulded parts", color: "#C8478F", icon: Container },
  Hex: { name: "Hex", role: "Librarian", color: "#5B6475", icon: Hexagon },
  Fitz: { name: "Fitz", role: "Assembly", color: "#1E874C", icon: Puzzle },
  Gage: { name: "Gage", role: "Checker", color: "#C4800C", icon: Gauge },
  Ortho: { name: "Ortho", role: "Drawings", color: "#2B6CB0", icon: PenTool },
  Smithy: { name: "Smithy", role: "Manufacturing review", color: "#B5442E", icon: Hammer },
};

export function AgentAvatar({ name, size = 28, working }: { name: string; size?: number; working?: boolean }) {
  const a = AGENTS[name]!;
  const I = a.icon;
  return (
    <span className="relative inline-flex shrink-0" title={`${a.name} · ${a.role}`}>
      {working && <span className="fw-ping absolute inset-0 rounded-full" style={{ background: a.color }} />}
      <span className="relative flex items-center justify-center rounded-full text-white ring-2 ring-panel" style={{ width: size, height: size, background: a.color }}>
        <I style={{ width: size * 0.52, height: size * 0.52 }} className={cx(working && name === "Axel" && "motion-safe:animate-[fw-spin_3s_linear_infinite]")} />
      </span>
    </span>
  );
}

const COLS = ["Backlog", "In progress", "Review · Gage", "Done"] as const;
type Card = { id: string; title: string; agent: string; status: string[] };
const CARDS: Card[] = [
  { id: "GBX-3", title: "Output shaft Ø25", agent: "Chuck", status: ["Queued", "Turning the Ø25 journal", "Gage measuring the H7 seat", "Fitted"] },
  { id: "GBX-4", title: "Gear pair m3 · z40 / z20", agent: "Axel", status: ["Queued", "Hobbing 40 teeth, m3", "Gage checking centre distance", "Fitted"] },
  { id: "GBX-5", title: "Motor plate", agent: "Mill", status: ["Queued", "Pocketing the motor plate", "Gage checking the bolt pattern", "Fitted"] },
  { id: "GBX-6", title: "Bearings 6205 × 2", agent: "Hex", status: ["Queued", "Found 6205 in the Toolbox", "Gage checking bore fits", "Fitted"] },
  { id: "GBX-7", title: "Housing cover", agent: "Molly", status: ["Queued", "Adding 1.5° draft", "Gage checking wall thickness", "Fitted"] },
  { id: "GBX-8", title: "Sheet 2 of 5", agent: "Ortho", status: ["Queued", "Dimensioning sheet 2", "Gage checking callouts", "Issued"] },
];
const ARCHIE = ["Archie is splitting the gearbox into 3 sub-assemblies", "Archie froze the shaft-to-bearing interface", "Archie assigned the gear pair to Axel", "Fitz mated 14 of 18 parts, 0 clashes", "Smithy flagged a 0.5 mm wall as too thin to mill"];

/** Deterministic board state at step n: cards advance one column at a time, staggered, then the sprint restarts. */
function columnsAt(n: number): number[] {
  const s = n % (CARDS.length * 2 + 10);
  return CARDS.map((_, i) => (s < 2 * i ? 0 : Math.min(3, Math.floor((s - 2 * i) / 3) + 1)));
}

function Board({ step, reduced }: { step: number; reduced: boolean }) {
  const cols = reduced ? CARDS.map((_, i) => [3, 3, 2, 1, 1, 0][i]!) : columnsAt(step);
  const refs = useRef(new Map<string, HTMLElement>());
  const prev = useRef(new Map<string, DOMRect>());
  // FLIP: cards glide from their old column to the new one
  useLayoutEffect(() => {
    const now = new Map<string, DOMRect>();
    refs.current.forEach((el, id) => now.set(id, el.getBoundingClientRect()));
    if (!reduced) {
      refs.current.forEach((el, id) => {
        const a = prev.current.get(id), b = now.get(id);
        if (!a || !b || (Math.abs(a.left - b.left) < 1 && Math.abs(a.top - b.top) < 1)) return;
        el.animate([{ transform: `translate(${a.left - b.left}px, ${a.top - b.top}px)`, boxShadow: "0 12px 28px rgb(16 24 40 / .22)" }, { transform: "none" }],
          { duration: 650, easing: "cubic-bezier(.2,.7,.2,1)" });
      });
    }
    prev.current = now;
  });
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {COLS.map((c, ci) => {
        const here = CARDS.filter((_, i) => cols[i] === ci);
        return (
          <div key={c} className="min-h-[150px] rounded-lg bg-white/[.04] p-2 ring-1 ring-white/10">
            <div className="mb-2 flex items-center justify-between text-[10.5px] font-semibold uppercase tracking-wider text-chrome-muted">{c}<span className="rounded bg-white/10 px-1.5 text-chrome-fg">{here.length}</span></div>
            <div className="space-y-1.5">
              {here.map(card => (
                <div key={card.id} ref={el => { if (el) refs.current.set(card.id, el); else refs.current.delete(card.id); }}
                  className={cx("rounded-md border bg-chrome-2 p-2 text-[11px]", ci === 3 ? "border-success/40" : ci === 2 ? "border-warning/40" : "border-white/10")}>
                  <div className="flex items-start gap-1.5">
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-[9.5px] text-chrome-muted">{card.id}</div>
                      <div className="truncate font-medium text-white">{card.title}</div>
                    </div>
                    <AgentAvatar name={card.agent} size={20} working={ci === 1 && !reduced} />
                  </div>
                  <div className={cx("mt-1 truncate text-[10px]", ci === 3 ? "text-[#6FD39B]" : "text-chrome-muted")}>{card.status[ci]}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function OfficeBoard() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const on = useInView(ref, { threshold: 0.2 });
  const step = useTicker(on && !reduced, 1500);
  const line = ARCHIE[Math.floor(step / 3) % ARCHIE.length]!;
  return (
    <div ref={ref} id="office" className="scroll-mt-20 bg-chrome text-chrome-fg">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <Reveal className="grid items-end gap-6 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <span className="text-[11px] font-semibold uppercase tracking-[.14em] text-[#F2B784]">Design Office</span>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-white">A whole design office, not one assistant.</h2>
            <p className="mt-3 text-chrome-muted">
              Archie, your Chief Designer, splits a machine into parts and interfaces and hands each one to a named specialist on a board you
              can watch. Specialists work in parallel, Hex pulls standard parts from the Toolbox instantly, and every part passes the same gating
              checks before Fitz fits it.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            {Object.values(AGENTS).map(a => (
              <span key={a.name} className="inline-flex items-center gap-1.5 rounded-full bg-white/[.06] py-0.5 pl-0.5 pr-2.5 text-[11.5px] ring-1 ring-white/10">
                <AgentAvatar name={a.name} size={22} /><span className="font-medium text-white">{a.name}</span><span className="hidden text-chrome-muted sm:inline">{a.role}</span>
              </span>
            ))}
          </div>
        </Reveal>
        <Reveal delay={0.1} className="mt-10 overflow-hidden rounded-xl border border-white/10 bg-[#1b1f25] p-3 sm:p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <AgentAvatar name="Archie" size={26} working={!reduced} />
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-semibold text-white">Gearbox GBX · sprint board</div>
              <div key={line} className="animate-fade-in truncate text-[11.5px] text-chrome-muted">{line}</div>
            </div>
          </div>
          <Board step={step} reduced={reduced} />
        </Reveal>
      </div>
    </div>
  );
}
