import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Box, Check, CheckCircle2, Download, FileText, FolderTree, ListChecks, Pause, Play, Ruler, RotateCcw, Send } from "lucide-react";
import { LogoMark } from "@/components/ui";
import { cx } from "@/lib/format";
import { AgentAvatar, AGENT } from "@/pages/app/office/Avatars";
import { useInView, useReducedMotion } from "../motion";
import { carrierSpeed, ratio } from "./kinematics";
import {
  APPROVED_AT, ASSEMBLED_AT, BRIEF, BUILD, BUILD_DUR, CHAPTERS, CHIPS_AT, ESTIMATE_AT, FLY, INTERFACES, LOOP, MOTOR_RPM,
  OUTPUT_TORQUE, PLAN_CHECKS, PLAN_ROWS, RUN_AT, SEAT_ORDER, SEND_AT, SUN_SPEED, TICKETS, archieLine, chapterAt, chapterEnd,
  seatAt, span, ticketState, typedChars,
} from "./story";
import manifest from "./gearbox.json";

const GearboxStage = lazy(() => import("./GearboxStage"));

const G = { zs: manifest.gear.zs, zp: manifest.gear.zp, zr: manifest.gear.zr, n: manifest.gear.n, m: manifest.gear.m };
const TOTAL_PARTS = manifest.instances.length;
const FINAL_T = RUN_AT + 7;
const SCREEN_SLOWDOWN = Math.round(MOTOR_RPM / ((SUN_SPEED / (2 * Math.PI)) * 60));

function useMedia(q: string) {
  const [m, setM] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return;
    const f = () => setM(mq.matches);
    f();
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, [q]);
  return m;
}

/** Fades a layer in/out without unmounting it mid-transition. */
function Layer({ on, children, className }: { on: boolean; children: ReactNode; className?: string }) {
  const [mounted, setMounted] = useState(on);
  useEffect(() => {
    if (on) { setMounted(true); return; }
    const id = window.setTimeout(() => setMounted(false), 500);
    return () => window.clearTimeout(id);
  }, [on]);
  if (!mounted && !on) return null;
  return <div className={cx("absolute inset-0 transition-all duration-500 ease-out", on ? "opacity-100" : "pointer-events-none opacity-0", className)}>{children}</div>;
}

const glass = "rounded-[3px] border border-[#7eb2ff]/25 bg-[#0a1a36]/90 shadow-[0_20px_50px_-20px_rgb(0_0_0/.6)]";
const shown = (on: boolean) => cx("transition-all duration-500 ease-out", on ? "translate-y-0 opacity-100" : "translate-y-1.5 opacity-0");

// ------------------------------------------------------------------ a. brief
function BriefPanel({ t, compact }: { t: number; compact: boolean }) {
  const n = typedChars(t);
  const sent = t >= SEND_AT;
  const ready = n >= BRIEF.length;
  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div className={cx(glass, "w-full max-w-[680px] p-4 sm:p-5")}>
        <div className="flex items-center gap-2.5">
          <AgentAvatar code="archie" state={sent ? "working" : "idle"} size={compact ? 30 : 36} />
          <div className="min-w-0">
            <div className="text-[13px] font-semibold text-white">New program · brief for Archie</div>
            <div className="text-[11px] text-white/55">Chief Designer · plans the machine and runs the office</div>
          </div>
          <span className="ml-auto hidden rounded-full bg-white/[.06] px-2 py-0.5 text-[10.5px] text-white/60 ring-1 ring-white/10 sm:inline">PG-5</span>
        </div>
        <div className={cx("mt-3 rounded-lg border border-white/10 bg-black/25 p-3 text-white/90", compact ? "min-h-[190px] text-[12px] leading-[1.55]" : "min-h-[150px] text-[13.5px] leading-relaxed")}>
          {BRIEF.slice(0, n)}{!sent && <span className="fw-caret text-[#7fb0ff]" />}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {["5:1", "12 Nm", "NEMA 23", "m1.5", "6204-2RS"].map((c, i) => (
            <span key={c} className={cx("rounded-full bg-[#2f6fd0]/15 px-2 py-0.5 text-[10.5px] font-medium text-[#9cc2ff] ring-1 ring-[#2f6fd0]/30", shown(n > [40, 75, 50, 200, 330][i]!))}>{c}</span>
          ))}
          <span className={cx("ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold transition-all duration-300",
            sent ? "scale-95 bg-[#1e874c] text-white" : ready ? "bg-[#2f6fd0] text-white shadow-[0_0_0_4px_rgb(47_111_208/.25)]" : "bg-white/10 text-white/50")}>
            {sent ? <><Check className="h-3.5 w-3.5" />Sent</> : <><Send className="h-3.5 w-3.5" />Send to Archie</>}
          </span>
        </div>
      </div>
      {!compact && (
        <div className="mt-5 flex flex-wrap justify-center gap-1.5">
          {["mill", "chuck", "axel", "hex", "fitz", "gage", "ortho", "smithy"].map(c => (
            <span key={c} className="inline-flex items-center gap-1.5 rounded-full bg-white/[.05] py-0.5 pl-0.5 pr-2.5 text-[11px] text-white/70 ring-1 ring-white/10">
              <AgentAvatar code={c} size={20} />{AGENT[c]!.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ b. plan
function PlanPanel({ t, compact }: { t: number; compact: boolean }) {
  const approved = t >= APPROVED_AT;
  return (
    <div className={cx("grid h-full gap-3 p-3 sm:p-5", compact ? "grid-rows-[auto_1fr]" : "grid-cols-[1.15fr_1fr]")}>
      {compact && <ArchieBar t={t} />}
      <div className={cx(glass, "relative min-h-0 overflow-hidden p-3 sm:p-4")}>
        <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-white/50"><FolderTree className="h-3.5 w-3.5" />Product tree</div>
        <div className="space-y-[3px]">
          {PLAN_ROWS.map(({ node, depth, at }) => (
            <div key={node.name} className={cx("flex items-center gap-2 rounded-md pr-1", compact ? "py-[1px]" : "py-[3px]", shown(t >= at), depth === 0 && "mb-1")}
              style={{ paddingLeft: depth * (compact ? 12 : 18) }}>
              {depth > 0 && <span className="h-px w-2.5 shrink-0 bg-white/20" />}
              {node.children ? <FolderTree className="h-3.5 w-3.5 shrink-0 text-[#7fb0ff]" /> : <Box className="h-3.5 w-3.5 shrink-0 text-white/45" />}
              <span className={cx("shrink-0 font-medium text-white", depth === 0 ? "text-[13.5px]" : "text-[12px]")}>{node.name}</span>
              {node.detail && <span className={cx("min-w-0 truncate text-[11px] text-white/45", compact && depth > 1 && "hidden")}>{node.detail}</span>}
              <span className="ml-auto"><AgentAvatar code={node.agent} size={depth === 0 ? 22 : 18} still /></span>
            </div>
          ))}
        </div>
        <div className={cx("absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg border border-[#1e874c]/60 bg-[#1e874c]/20 px-2.5 py-1 text-[12px] font-semibold text-[#7ee2a8] transition-all duration-500",
          approved ? "scale-100 opacity-100" : "scale-110 opacity-0")}><CheckCircle2 className="h-4 w-4" />Plan approved</div>
      </div>
      {!compact && (
        <div className="flex min-h-0 flex-col gap-3">
          <ArchieBar t={t} />
          <div className={cx(glass, "p-3")}>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/50">Gear set checks</div>
            {PLAN_CHECKS.map(c => (
              <div key={c.label} className={cx("flex items-center gap-2 py-0.5 text-[12px]", shown(t >= c.at))}>
                <span className="w-[104px] shrink-0 text-white/70">{c.label}</span>
                <span className="font-mono text-[11px] text-white/45">{c.calc}</span>
                <span className="ml-auto font-mono font-semibold tabular-nums text-[#7ee2a8]">{c.value}</span>
              </div>
            ))}
          </div>
          <div className={cx(glass, "p-3")}>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/50">Interfaces frozen</div>
            {INTERFACES.map(i => (
              <div key={i.text} className={cx("flex items-center gap-2 py-0.5 text-[12px] text-white/80", shown(t >= i.at))}><span className="h-1.5 w-1.5 rounded-full bg-[#7fb0ff]" />{i.text}</div>
            ))}
          </div>
          <div className={cx("flex flex-wrap gap-1.5", shown(t >= ESTIMATE_AT))}>
            {[`${TOTAL_PARTS} parts`, "16 unique", "11 tickets", "5 specialists"].map(c => (
              <span key={c} className="rounded-full bg-white/[.07] px-2.5 py-1 text-[11.5px] font-medium text-white ring-1 ring-white/10">{c}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ArchieBar({ t }: { t: number }) {
  const line = archieLine(t);
  return (
    <div className={cx(glass, "flex items-center gap-2.5 px-3 py-2")}>
      <AgentAvatar code="archie" state={t >= APPROVED_AT && t < CHAPTERS[2].start ? "done" : "working"} size={30} />
      <div className="min-w-0">
        <div className="text-[11px] font-semibold text-white/50">Archie · Chief Designer</div>
        <div key={line} className="animate-fade-in truncate text-[12.5px] font-medium text-white">{line}</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ c. board
const COLS = ["Backlog", "In design", "Review · Gage", "Done"] as const;
const CHECK_DOTS = 7;

function BoardPanel({ t, compact }: { t: number; compact: boolean }) {
  const states = TICKETS.map((tk, i) => ({ tk, s: ticketState(tk, i, t), i }));
  const refs = useRef(new Map<string, HTMLElement>());
  const prev = useRef(new Map<string, DOMRect>());
  useLayoutEffect(() => {
    // layout position without any running FLIP transform, so re-renders mid-animation never compound
    const now = new Map<string, DOMRect>();
    refs.current.forEach((el, id) => {
      const r = el.getBoundingClientRect();
      const tf = getComputedStyle(el).transform;
      const m = tf && tf !== "none" ? new DOMMatrix(tf) : null;
      now.set(id, m ? new DOMRect(r.left - m.m41, r.top - m.m42, r.width, r.height) : r);
    });
    refs.current.forEach((el, id) => {
      const a = prev.current.get(id), b = now.get(id);
      if (!a || !b || (Math.abs(a.left - b.left) < 2 && Math.abs(a.top - b.top) < 2)) return;
      el.animate([{ transform: `translate(${a.left - b.left}px, ${a.top - b.top}px)`, boxShadow: "0 14px 30px rgb(0 0 0 / .45)" }, { transform: "none" }],
        { duration: 520, easing: "cubic-bezier(.2,.7,.2,1)" });
    });
    prev.current = now;
  });
  const setRef = (id: string) => (el: HTMLElement | null) => { if (el) refs.current.set(id, el); else refs.current.delete(id); };
  const working = new Set(states.filter(x => x.s.col === 1).map(x => x.tk.agent));
  const reviewing = states.some(x => x.s.col === 2);

  const card = ({ tk, s }: (typeof states)[number]) => {
    const st = s.col === 1 ? "working" : s.col === 2 ? "review" : s.col === 3 ? "done" : "idle";
    if (s.col === 0 || s.col === 3) {
      return (
        <div key={tk.key} ref={setRef(tk.key)} className={cx("flex items-center gap-1.5 rounded-md border px-1.5 py-1 text-[11px]",
          s.col === 3 ? "border-[#1e874c]/40 bg-[#1e874c]/10" : "border-white/10 bg-white/[.04]", !s.visible && "opacity-0")}>
          <span className="w-9 shrink-0 font-mono text-[9.5px] text-white/45">{tk.key}</span>
          <span className="min-w-0 flex-1 truncate font-medium text-white/90">{tk.title}</span>
          {s.col === 3 && <span className="shrink-0 text-[9.5px] font-semibold text-[#7ee2a8]">✓ {tk.agent === "hex" ? "0 tokens" : `${CHECK_DOTS}/${CHECK_DOTS}`}</span>}
          <AgentAvatar code={tk.agent} state={st} size={16} still={s.col === 0} />
        </div>
      );
    }
    const checks = s.col === 2 ? Math.min(CHECK_DOTS, Math.floor(span(t, tk.start + tk.dur, tk.start + tk.dur + 0.6) * CHECK_DOTS) + 1) : 0;
    return (
      <div key={tk.key} ref={setRef(tk.key)} className={cx("rounded-lg border p-2 text-[11px]", s.col === 2 ? "border-[#c4800c]/50 bg-[#c4800c]/10" : "border-[#2f6fd0]/40 bg-[#2f6fd0]/10")}>
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[9.5px] text-white/45">{tk.key}</div>
            <div className="truncate text-[12px] font-semibold text-white">{tk.title}</div>
          </div>
          <AgentAvatar code={s.col === 2 ? "gage" : tk.agent} state={s.col === 2 ? "review" : "working"} size={26} progress={s.col === 1 ? s.progress * 100 : null} />
        </div>
        {s.col === 1 ? <>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-[#5ea8ff] transition-[width] duration-150 ease-linear" style={{ width: `${s.progress * 100}%` }} /></div>
          <div className="mt-1 truncate text-[10.5px] text-white/60">{tk.status}</div>
        </> : <div className="mt-1.5 flex items-center gap-1">
          {Array.from({ length: CHECK_DOTS }, (_, k) => <span key={k} className={cx("h-1.5 flex-1 rounded-full transition-colors duration-200", k < checks ? "bg-[#3fbf77]" : "bg-white/15")} />)}
          <span className="ml-1 text-[10px] text-[#f2c06a]">Gage checking</span>
        </div>}
      </div>
    );
  };

  return (
    <div className="flex h-full flex-col gap-2.5 p-3 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1"><ArchieBar t={t} /></div>
        {!compact && (
          <div className={cx(glass, "flex items-center gap-1 px-2 py-1.5")}>
            {["axel", "chuck", "mill", "hex", "gage", "fitz"].map(c => (
              <AgentAvatar key={c} code={c} size={28}
                state={c === "gage" ? (reviewing ? "review" : "idle") : working.has(c) ? "working" : states.some(x => x.tk.agent === c && x.s.col === 3) ? "done" : "idle"} />
            ))}
          </div>
        )}
      </div>
      {compact ? (
        <div className="min-h-0 flex-1 space-y-1.5 overflow-hidden">
          {[1, 2, 3, 0].flatMap(c => states.filter(x => x.s.col === c)).slice(0, 9).map(card)}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-4 gap-2">
          {COLS.map((c, ci) => {
            const here = states.filter(x => x.s.col === ci && x.s.visible);
            return (
              <div key={c} className="flex min-h-0 flex-col rounded-xl bg-white/[.03] p-2 ring-1 ring-white/[.08]">
                <div className="mb-2 flex items-center justify-between text-[10.5px] font-semibold uppercase tracking-wider text-white/50">{c}
                  <span className="rounded bg-white/10 px-1.5 tabular-nums text-white/80">{here.length}</span></div>
                <div className="space-y-1.5">{here.map(card)}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ d/e/f. HUDs over the 3D stage
function Caption({ eyebrow, title, agent, state, children }: { eyebrow: string; title: string; agent: string; state: "working" | "done"; children?: ReactNode }) {
  return (
    <div className={cx(glass, "flex max-w-[360px] items-start gap-2.5 px-3 py-2.5")}>
      <AgentAvatar code={agent} state={state} size={34} />
      <div className="min-w-0">
        <div className="text-[10.5px] font-semibold uppercase tracking-wider text-[#7fb0ff]">{eyebrow}</div>
        <div className="text-[13.5px] font-semibold leading-snug text-white">{title}</div>
        {children}
      </div>
    </div>
  );
}

function BuildHud({ t }: { t: number }) {
  const built = BUILD.filter(b => t >= b.at + (b.stock ? BUILD_DUR : 0.35)).length;
  const now = BUILD.filter(b => b.stock && t >= b.at && t < b.at + BUILD_DUR).map(b => b.agent);
  return (
    <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-start justify-between gap-2 sm:inset-x-5 sm:top-5">
      <Caption eyebrow="Build" title="Every part, modelled and checked" agent={now[0] ?? "gage"} state={now.length ? "working" : "done"}>
        <div className="mt-0.5 text-[11.5px] text-white/60">Stock to finished part in seconds. Hex's Toolbox parts arrive instantly.</div>
      </Caption>
      <div className={cx(glass, "flex items-center gap-2 px-3 py-2 text-[12px] text-white")}>
        <span className="font-mono text-[18px] font-semibold tabular-nums">{built}<span className="text-white/40">/{BUILD.length}</span></span>
        <span className="leading-tight text-white/60">unique parts<br /><span className="text-[#7ee2a8]">gating checks pass</span></span>
      </div>
    </div>
  );
}

const SEAT_NAMES: Record<string, string> = {
  motor_flange: "Motor flange + input cover", b6001: "6001 into its seat", input_shaft: "Input shaft", carrier_a: "Carrier plate A",
  pin: "Planet pins", b6000: "6000 planet bearings", planet: "Planets 27T × 3", sun: "Sun 18T meshes 3 planets", ring: "Ring 72T over the planets",
  dowel: "Dowels Ø5", carrier_b: "Carrier plate B", output_shaft: "Output shaft", b6204: "2 × 6204-2RS", output_cover: "Output cover",
  shcs_m5: "6 × M5 × 35 torqued",
};

function AssembleHud({ t }: { t: number }) {
  const placed = manifest.instances.filter(i => t >= seatAt(i.part) + 0.4).length;
  const last = [...SEAT_ORDER].reverse().find(g => t >= seatAt(g[0]!) + 0.2);
  const done = t >= ASSEMBLED_AT;
  return (
    <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-start justify-between gap-2 sm:inset-x-5 sm:top-5">
      <Caption eyebrow="Assemble" title={t < FLY.start + FLY.dur ? "Fitz lays out the exploded view" : done ? "PG-5 assembled" : "Fitz mates it bottom-up"} agent="fitz" state={done ? "done" : "working"}>
        <div key={last?.[0]} className="mt-0.5 animate-fade-in truncate text-[11.5px] text-white/60">{last ? `Seated: ${SEAT_NAMES[last[0]!]}` : "Axial stack along the gearbox axis"}</div>
      </Caption>
      <div className={cx(glass, "grid grid-cols-2 gap-x-4 gap-y-0.5 px-3 py-2 text-[11.5px]")}>
        <span className="text-white/55">Parts placed</span><span className="text-right font-mono font-semibold tabular-nums text-white">{placed}/{TOTAL_PARTS}</span>
        <span className="text-white/55">Interferences</span><span className={cx("text-right font-mono font-semibold tabular-nums", done ? "text-[#7ee2a8]" : "text-white/40")}>{done ? "0" : "…"}</span>
        <span className="text-white/55">Gear mesh</span><span className={cx("text-right font-semibold", t >= seatAt("ring") + 0.4 ? "text-[#7ee2a8]" : "text-white/40")}>{t >= seatAt("ring") + 0.4 ? "a = 33.75 ✓" : "…"}</span>
      </div>
    </div>
  );
}

function RunHud({ t, still, compact }: { t: number; still: boolean; compact: boolean }) {
  // `still` = the reduced-motion end state: the static story steps take the left side
  const ramp = still ? 1 : 1 - Math.exp(-Math.max(0, t - RUN_AT) / 1.2);
  const motor = MOTOR_RPM * ramp;
  const out = carrierSpeed(motor, G);
  return (
    <>
      <div className={cx("pointer-events-none absolute left-3 top-3 sm:left-5 sm:top-5", still && "hidden")}>
        <Caption eyebrow="Run" title="It turns. Exactly 5 : 1." agent="gage" state="done">
          <div className="mt-0.5 text-[11.5px] text-white/60">Sun in, planets roll inside the fixed ring, carrier out. Shown at 1/{SCREEN_SLOWDOWN} speed.</div>
        </Caption>
      </div>
      {compact ? (
        <div className={cx(glass, "pointer-events-none absolute inset-x-3 bottom-[76px] grid grid-cols-3 px-2 py-2 text-center")}>
          {[["Ratio", `${ratio(G).toFixed(2)} : 1`], ["Motor", `${Math.round(motor)} rpm`], ["Output", `${Math.round(out)} rpm`]].map(([k, v]) => (
            <div key={k}><div className="text-[10px] text-white/50">{k}</div><div className="font-mono text-[13px] font-semibold tabular-nums text-white">{v}</div></div>
          ))}
        </div>
      ) : (
      <div className={cx(glass, "pointer-events-none absolute bottom-16 right-5 w-[208px] px-3 py-2.5")}>
        {[
          ["Ratio", `${ratio(G).toFixed(2)} : 1`],
          ["Motor", `${Math.round(motor)} rpm`],
          ["Output", `${Math.round(out)} rpm`],
          ["Output torque", `${OUTPUT_TORQUE} Nm`],
          ["Input torque", `${(OUTPUT_TORQUE / ratio(G)).toFixed(1)} Nm`],
        ].map(([k, v], i) => (
          <div key={k} className={cx("flex items-baseline justify-between py-[1px]", i === 0 && "mb-1 border-b border-white/10 pb-1")}>
            <span className="text-[11.5px] text-white/55">{k}</span>
            <span className={cx("font-mono font-semibold tabular-nums", i === 0 ? "text-[17px] text-white" : "text-[12.5px] text-white/90")}>{v}</span>
          </div>
        ))}
        <div className="mt-1 text-[10px] text-white/40">Design point, ideal efficiency</div>
      </div>
      )}
      <div className={cx("pointer-events-none absolute bottom-16 left-5 hidden flex-col gap-1", !still && "md:flex")}>
        {[["#d8975a", "Sun · input"], ["#b9c3cf", "Planets 27T × 3"], ["#4a7cc9", "Carrier · output"], ["#8c97a6", "Ring 72T · fixed"]].map(([c, l]) => (
          <span key={l} className="inline-flex items-center gap-1.5 text-[11px] text-white/70"><span className="h-2 w-2 rounded-full" style={{ background: c }} />{l}</span>
        ))}
      </div>
      <div className={cx("pointer-events-none absolute inset-x-0 bottom-3 flex flex-wrap justify-center gap-1.5 px-3 transition-all duration-700", t >= CHIPS_AT || still ? "opacity-100" : "translate-y-2 opacity-0")}>
        <span className="inline-flex items-center gap-1 rounded-full bg-[#1e874c] px-2.5 py-1 text-[11.5px] font-semibold text-white shadow-lg"><CheckCircle2 className="h-3.5 w-3.5" />All gating checks pass</span>
        {[[Download, "STEP"], [ListChecks, "BOM"], [Ruler, "Drawings"], [FileText, "Shop pack"]].slice(0, compact ? 3 : 4).map(([I, l]) => {
          const C = I as typeof Download;
          return <span key={l as string} className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-[11.5px] font-semibold text-white ring-1 ring-white/15 backdrop-blur"><C className="h-3.5 w-3.5" />{l as string}</span>;
        })}
      </div>
    </>
  );
}

const STATIC_STEPS = [
  ["archie", "Brief", "A detailed brief: 5:1 planetary for a NEMA 23 motor, 12 Nm out."],
  ["archie", "Plan", "Archie splits it into a product tree, checks the gear set and freezes interfaces."],
  ["axel", "Board", "Tickets go to Axel, Chuck, Mill and Hex, who work in parallel."],
  ["gage", "Build", "Every part is modelled and passes Gage's gating checks."],
  ["fitz", "Assemble", "Fitz mates 29 parts: 0 interferences."],
  ["gage", "Run", "Ratio 5.00 : 1. STEP, BOM and drawings ready."],
] as const;

// ------------------------------------------------------------------ the hero
export default function OfficeHero() {
  const reduced = useReducedMotion();
  const compact = useMedia("(max-width: 767px)");
  const ref = useRef<HTMLDivElement>(null);
  const onScreen = useInView(ref, { threshold: 0.05 });
  const time = useRef(reduced ? FINAL_T : 0);
  const [t, setT] = useState(time.current);
  const [playing, setPlaying] = useState(true);
  const [loaded, setLoaded] = useState(0);
  const loadedRef = useRef(0);
  loadedRef.current = loaded;

  useEffect(() => {
    if (reduced) { time.current = FINAL_T; setT(FINAL_T); return; }
    if (!playing || !onScreen) return;
    let raf = 0, last = performance.now(), shown = -1;
    const tick = (now: number) => {
      const dt = Math.min(0.5, (now - last) / 1000); // real time even on slow GPUs; big gaps (hidden tab) are capped
      last = now;
      if (!document.hidden) {
        let x = time.current + dt;
        // hold at the build chapter until the geometry is in
        if (x >= CHAPTERS[3].start && time.current < CHAPTERS[3].start + 0.01 && loadedRef.current < 1) x = CHAPTERS[3].start;
        time.current = x % LOOP;
      }
      const q = Math.floor(time.current * 15);
      if (q !== shown) { shown = q; setT(time.current); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reduced, playing, onScreen]);

  const seek = useCallback((x: number) => { time.current = x; setT(x); }, []);
  const ch = chapterAt(t);
  const id = CHAPTERS[ch]!.id;
  const threeOn = ch >= 3;
  const waiting = ch === 3 && loaded < 1 && t <= CHAPTERS[3].start + 0.01;

  return (
    <div ref={ref} className="relative" data-hero="office">
      <div className="relative overflow-hidden bg-[#071328] text-left">
        {/* title bar */}
        <div className="flex h-10 items-center gap-2 border-b border-white/[.06] bg-[#0b1d3d] px-3">
          <span className="font-anno text-[10.5px] font-medium uppercase tracking-[.14em] text-[#9cc3ff]">Iso</span>
          <LogoMark size={16} className="ml-3" />
          <span className="truncate text-[11.5px] text-white/60">Formwright · Design Office · <span className="text-white/85">PG-5 Planetary gearbox 5:1</span></span>
          <span className="ml-auto hidden shrink-0 items-center gap-1.5 text-[11px] text-white/50 sm:inline-flex">
            {["archie", "axel", "chuck", "mill", "hex", "gage", "fitz"].map(c => <AgentAvatar key={c} code={c} size={18} still />)}
          </span>
        </div>

        {/* stage */}
        <div className={cx("relative overflow-hidden", compact ? "h-[560px]" : "h-[600px]")}>
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_30%,#163061_0%,#0b1a37_55%,#06112a_100%)]" />
          <div className="absolute inset-0 opacity-40 [background-image:linear-gradient(rgb(126_178_255/.07)_1px,transparent_1px),linear-gradient(90deg,rgb(126_178_255/.07)_1px,transparent_1px)] [background-size:28px_28px] [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" />

          {/* 3D: mounted from the start so the parts load during the brief */}
          <div className={cx("absolute inset-0 transition-opacity duration-700", threeOn || reduced ? "opacity-100" : "opacity-0")}>
            <Suspense fallback={null}>
              <GearboxStage time={time} still={reduced} compact={compact} onLoad={setLoaded}
                label="Planetary gearbox PG-5 built by the Formwright Design Office: sun, three planets and an internal ring gear running at 5 to 1." />
            </Suspense>
          </div>
          {waiting && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="flex items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-[12px] text-white/80"><span className="h-3.5 w-3.5 rounded-full border-2 border-white/20 border-t-white/80 motion-safe:animate-spin" />Loading geometry {Math.round(loaded * 100)}%</div>
            </div>
          )}

          {reduced ? (
            <div className="absolute inset-y-3 left-3 flex w-[min(340px,calc(100%-24px))] flex-col gap-1.5 overflow-hidden sm:inset-y-5 sm:left-5">
              {STATIC_STEPS.map(([a, h, b], i) => (
                <div key={h} className={cx(glass, "flex items-start gap-2.5 px-3 py-2")}>
                  <AgentAvatar code={a} state="done" size={26} still />
                  <div className="min-w-0"><div className="text-[12px] font-semibold text-white">{i + 1}. {h}</div><div className="text-[11.5px] leading-snug text-white/65">{b}</div></div>
                </div>
              ))}
            </div>
          ) : <>
            <Layer on={id === "brief"}><BriefPanel t={t} compact={compact} /></Layer>
            <Layer on={id === "plan"}><PlanPanel t={t} compact={compact} /></Layer>
            <Layer on={id === "board"}><BoardPanel t={t} compact={compact} /></Layer>
            <Layer on={id === "build" && !waiting}><BuildHud t={t} /></Layer>
            <Layer on={id === "assemble"}><AssembleHud t={t} /></Layer>
            <Layer on={id === "run"}><RunHud t={t} still={false} compact={compact} /></Layer>
          </>}
          {reduced && <RunHud t={FINAL_T} still compact={compact} />}
        </div>

        {/* transport: play/pause, replay, chapters (click to jump) */}
        {!reduced && (
          <div className="flex items-center gap-2 border-t border-white/[.06] bg-[#0a1834] px-2 py-2 sm:px-3">
            <button type="button" onClick={() => setPlaying(p => !p)} aria-label={playing ? "Pause" : "Play"}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20">
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </button>
            <button type="button" onClick={() => { seek(0); setPlaying(true); }} aria-label="Replay from the start"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white/70 transition hover:bg-white/10 hover:text-white">
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
            <div className="grid min-w-0 flex-1 grid-cols-6 gap-1" role="tablist" aria-label="Chapters">
              {CHAPTERS.map((c, i) => {
                const fill = i < ch ? 1 : i > ch ? 0 : span(t, c.start, chapterEnd(i));
                return (
                  <button key={c.id} type="button" role="tab" aria-selected={i === ch} onClick={() => seek(c.start + 0.01)}
                    className="group min-w-0 rounded-md px-1 pb-1 pt-1.5 text-left transition hover:bg-white/[.06]">
                    <div className="h-[3px] overflow-hidden rounded-full bg-white/15"><div className="h-full rounded-full bg-[#5ea8ff]" style={{ width: `${fill * 100}%` }} /></div>
                    <div className={cx("mt-1 truncate text-[10.5px] font-medium sm:text-[11px]", i === ch ? "text-white" : "text-white/45 group-hover:text-white/75")}>
                      <span className="hidden tabular-nums text-white/35 sm:inline">{i + 1} </span>{c.label}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
