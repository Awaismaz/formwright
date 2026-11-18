/** Design Office agent avatars (CD-017, plan §3.1): a round badge in the agent's colour, its tool, and a small face.
 * Animated by state: idle breathes and blinks; working plays the agent's own shop-floor animation with a progress
 * ring; review pulses; blocked shakes once in amber; done pops a check. Static under reduced motion. */
import { useId, useMemo, type ReactNode } from "react";
import { cx } from "@/lib/format";
import { gearPath } from "@/pages/app/studio/ShopStatus";
import type { AgentState } from "./types";
import "./avatars.css";

export interface AgentMeta { code: string; name: string; role: string; colour: string }

/** Names and colours (the server roster, src/aicad/office/roster.py, is the source of truth for status). */
export const AGENTS: AgentMeta[] = [
  { code: "archie", name: "Archie", role: "Chief Designer", colour: "#364FC7" },
  { code: "mill", name: "Mill", role: "Machined parts", colour: "#1098AD" },
  { code: "chuck", name: "Chuck", role: "Turned parts", colour: "#E8590C" },
  { code: "axel", name: "Axel", role: "Gears, pulleys and drives", colour: "#7048E8" },
  { code: "benny", name: "Benny", role: "Sheet metal", colour: "#5C940D" },
  { code: "molly", name: "Molly", role: "Plastic and moulded parts", colour: "#D6336C" },
  { code: "hex", name: "Hex", role: "Librarian: Toolbox and company parts", colour: "#495057" },
  { code: "fitz", name: "Fitz", role: "Assembly", colour: "#1971C2" },
  { code: "gage", name: "Gage", role: "Checker (independent)", colour: "#AE3EC9" },
  { code: "ortho", name: "Ortho", role: "Drawings", colour: "#2B8A3E" },
  { code: "smithy", name: "Smithy", role: "Manufacturing review", colour: "#C92A2A" },
];
export const AGENT = Object.fromEntries(AGENTS.map(a => [a.code, a])) as Record<string, AgentMeta>;
export const STATE_LABEL: Record<AgentState, string> = {
  idle: "idle", working: "working", review: "waiting for review", blocked: "changes requested", done: "done",
};

const W = "#fff";
const C = "var(--c)";
const AMBER = "#F59F00";
const PLASTIC = "#FFD43B";

function Archie() {
  const grid = [];
  for (let x = -9; x <= 9; x += 4.5) grid.push(<path key={`v${x}`} d={`M${x} -7.5 v11`} />);
  for (let y = -4; y <= 2; y += 3) grid.push(<path key={`h${y}`} d={`M-12.5 ${y} h25`} />);
  return <>
    <rect x={-13} y={-8} width={26} height={12} rx={1.2} fill={W} />
    <g stroke={C} strokeOpacity={0.25} strokeWidth={0.6}>{grid}</g>
    <path className="fwa-archie-arc" pathLength={100} d="M-7 0.5 A 18.5 18.5 0 0 0 7 0.5" fill="none" stroke={C} strokeWidth={1.3} strokeLinecap="round" />
    <g className="fwa-archie-compass">
      <g strokeLinecap="round" fill="none">
        <path d="M0 -17 L-6.5 1 M0 -17 L6.5 1" stroke={C} strokeWidth={3.4} />
        <path d="M0 -17 L-6.5 1 M0 -17 L6.5 1" stroke={W} strokeWidth={1.7} />
      </g>
      <path d="M6.5 1 l-1.3 -2.6 l2.2 -0.6 z" fill={PLASTIC} stroke={C} strokeWidth={0.5} />
      <rect x={-0.9} y={-22} width={1.8} height={4} rx={0.8} fill={W} />
      <circle cx={0} cy={-17} r={2.1} fill={W} stroke={C} strokeWidth={0.8} />
    </g>
  </>;
}

function Mill({ uid }: { uid: string }) {
  const helix = [];
  for (let i = -2; i <= 6; i++) helix.push(<path key={i} d={`M-3.2 ${-13 + i * 2.4} l6.4 2.8`} />);
  return <>
    <rect x={-12} y={-1} width={24} height={7} rx={1} fill={W} />
    <rect x={-4} y={-1} width={8} height={2.4} rx={0.6} fill={C} opacity={0.45} />
    <g className="fwa-mill-cutter">
      <rect x={-2.4} y={-21} width={4.8} height={8.5} rx={0.6} fill={W} />
      <clipPath id={`${uid}-fl`}><rect x={-2.9} y={-12.8} width={5.8} height={11.2} rx={0.8} /></clipPath>
      <g clipPath={`url(#${uid}-fl)`}>
        <rect x={-3} y={-13} width={6} height={12} fill={W} />
        <g className="fwa-mill-helix" stroke={C} strokeWidth={0.9} strokeOpacity={0.75}>{helix}</g>
      </g>
      <g fill={W}>
        <path className="fwa-mill-chip" d="M3 -2 l2.2 -1.2 l.5 1.9 z" />
        <path className="fwa-mill-chip" d="M-3 -2 l-2.1 -1.4 l-.4 2 z" />
        <path className="fwa-mill-chip" d="M2 -3 l1.6 -1.6 l.9 1.6 z" />
      </g>
    </g>
  </>;
}

function Chuck() {
  return <>
    <g className="fwa-chuck-spin">
      <circle cx={0} cy={-6} r={10.5} fill={W} />
      <circle cx={0} cy={-6} r={8.2} fill="none" stroke={C} strokeOpacity={0.25} strokeWidth={0.8} />
      {[0, 120, 240].map(a => <rect key={a} x={-1.9} y={-15.6} width={3.8} height={6} rx={0.7} fill={C} transform={`rotate(${a} 0 -6)`} />)}
      {[60, 180, 300].map(a => <circle key={a} cx={0} cy={-13} r={0.9} fill={C} opacity={0.45} transform={`rotate(${a} 0 -6)`} />)}
      <circle cx={0} cy={-6} r={2.7} fill={C} />
      <circle cx={0.8} cy={-6.8} r={0.8} fill={W} opacity={0.7} />
    </g>
    <path className="fwa-chuck-swarf" pathLength={40} d="M9.5 -3 c4.5 -0.4 7 3 5 6 c-1.8 2.4 -5.2 0.8 -3.8 -1.6 c0.9 -1.4 2.8 -0.6 2.2 0.7"
      fill="none" stroke={W} strokeWidth={1.3} strokeLinecap="round" />
  </>;
}

function Axel() {
  const big = useMemo(() => gearPath(10, 8.2, 6.5), []);
  const small = useMemo(() => gearPath(7, 5.9, 4.3), []);
  return <>
    <g className="fwa-axel-big"><path d={big} fill={W} transform="translate(-5 -5)" /><circle cx={-5} cy={-5} r={2.4} fill={C} /><circle cx={-5} cy={-5} r={4.4} fill="none" stroke={C} strokeOpacity={0.3} strokeWidth={0.7} /></g>
    <g className="fwa-axel-small"><path d={small} fill={W} transform="translate(6.6 -9.4) rotate(14)" /><circle cx={6.6} cy={-9.4} r={1.7} fill={C} /></g>
  </>;
}

function Benny() {
  return <>
    <rect x={-13} y={1} width={14} height={2.6} rx={0.5} fill={W} />
    <circle cx={1} cy={2.3} r={1.3} fill={W} />
    <g className="fwa-benny-flap">
      <rect x={1} y={1} width={14} height={2.6} rx={0.5} fill={W} />
      <path d="M5 2.3 h2 M9.5 2.3 h2" stroke={C} strokeWidth={0.6} strokeOpacity={0.5} />
    </g>
    <path d="M-10.5 -2 h8" stroke={W} strokeWidth={0.8} strokeDasharray="1.4 1.2" opacity={0.6} />
  </>;
}

function Molly() {
  return <>
    <g className="fwa-molly-left">
      <rect x={-14} y={-16} width={12} height={17} rx={1.2} fill={W} />
      <path d="M-2 -11 h-4 a2 2 0 0 0 -2 2 v3 a2 2 0 0 0 2 2 h4 z" fill={C} opacity={0.4} />
      <path d="M-12 -14 v13" stroke={C} strokeOpacity={0.25} strokeWidth={0.7} />
    </g>
    <g className="fwa-molly-right">
      <rect x={2} y={-16} width={12} height={17} rx={1.2} fill={W} />
      <path d="M2 -11 h4 a2 2 0 0 1 2 2 v3 a2 2 0 0 1 -2 2 h-4 z" fill={C} opacity={0.4} />
      <path d="M12 -14 v13" stroke={C} strokeOpacity={0.25} strokeWidth={0.7} />
    </g>
    <rect className="fwa-molly-part" x={-7.5} y={-10.6} width={15} height={6.2} rx={2.2} fill={PLASTIC} stroke={C} strokeWidth={0.5} />
    <rect className="fwa-molly-shine" x={-6} y={-9.8} width={4} height={4.6} rx={1.5} fill={W} />
  </>;
}

function Hex({ uid }: { uid: string }) {
  const threads = [];
  for (let y = -12; y <= 3; y += 1.7) threads.push(<path key={y} d={`M-2.4 ${y} l4.8 -0.9`} />);
  return <>
    <g className="fwa-hex-drawer">
      <rect x={6} y={-1} width={9} height={5} rx={0.8} fill={W} opacity={0.92} />
      <path d="M9 1.5 h3" stroke={C} strokeWidth={0.9} strokeLinecap="round" />
    </g>
    <rect x={-6.5} y={-20} width={13} height={4.4} rx={0.8} fill={W} />
    <path d="M-2.2 -20 v4.4 M2.2 -20 v4.4" stroke={C} strokeOpacity={0.35} strokeWidth={0.7} />
    <rect x={-2.4} y={-15.6} width={4.8} height={19} fill={W} />
    <g stroke={C} strokeOpacity={0.45} strokeWidth={0.6}>{threads}</g>
    <g className="fwa-hex-nut">
      <clipPath id={`${uid}-nut`}><rect x={-6.2} y={-10} width={12.4} height={5} rx={0.7} /></clipPath>
      <rect x={-6.2} y={-10} width={12.4} height={5} rx={0.7} fill={W} stroke={C} strokeWidth={0.8} />
      <g clipPath={`url(#${uid}-nut)`}>
        <g className="fwa-hex-facets" stroke={C} strokeOpacity={0.55} strokeWidth={0.7}>
          {[-10, -6, -2, 2, 6].map(x => <path key={x} d={`M${x} -10 v5`} />)}
        </g>
      </g>
    </g>
  </>;
}

function Fitz() {
  return <>
    <rect x={-14} y={-14} width={12.5} height={12} rx={1.3} fill={W} />
    <rect x={-2} y={-9.6} width={5.5} height={3.2} rx={1.4} fill={W} stroke={C} strokeWidth={0.7} />
    <g className="fwa-fitz-right">
      <rect x={1.6} y={-14} width={12.5} height={12} rx={1.3} fill={W} />
      <rect x={1.6} y={-9.6} width={2.4} height={3.2} fill={C} opacity={0.45} />
      <path d="M10 -12 v8" stroke={C} strokeOpacity={0.2} strokeWidth={0.8} />
    </g>
    <g className="fwa-fitz-click" stroke={W} strokeWidth={1.1} strokeLinecap="round">
      <path d="M0 -16 v-3 M-3 -15 l-2 -2 M3 -15 l2 -2" />
    </g>
  </>;
}

function Gage() {
  return <>
    <rect x={-15} y={-17} width={30} height={3.4} rx={0.6} fill={W} />
    <g stroke={C} strokeOpacity={0.5} strokeWidth={0.5}>
      {[-12, -10, -8, -6, -4, -2, 0, 2, 4].map(x => <path key={x} d={`M${x} -17 v${x % 4 === 0 ? 1.8 : 1.1}`} />)}
    </g>
    <path d="M-15 -13.6 h3.6 v10 l-1.8 1.6 l-1.8 -1.6 z" fill={W} />
    <circle cx={-7.1} cy={-7.6} r={4.3} fill={W} opacity={0.6} />
    <circle cx={-7.1} cy={-7.6} r={4.3} fill="none" stroke={W} strokeWidth={0.8} />
    <g className="fwa-gage-jaw">
      <rect x={4.6} y={-18.4} width={8.4} height={6} rx={1} fill={W} stroke={C} strokeWidth={0.6} />
      <rect x={5.6} y={-17.4} width={6.4} height={2.8} rx={0.4} fill={C} opacity={0.85} />
      <g fill={W}>{[6.6, 8.4, 10.2].map(x => <rect key={x} className="fwa-gage-digit" x={x} y={-16.6} width={1.1} height={1.4} />)}</g>
      <path d="M4.6 -12.4 h3.6 v8.8 l-1.8 1.6 l-1.8 -1.6 z" fill={W} />
    </g>
  </>;
}

function Ortho() {
  return <>
    <rect x={-13} y={-17} width={24} height={19} rx={1} fill={W} />
    <rect x={-11.6} y={-15.6} width={21.2} height={16.2} fill="none" stroke={C} strokeOpacity={0.25} strokeWidth={0.5} />
    <rect x={3.6} y={-2.4} width={6} height={3} fill="none" stroke={C} strokeOpacity={0.3} strokeWidth={0.5} />
    <path className="fwa-ortho-view" pathLength={100} d="M-9 -13 h10 v8 h-10 z" fill="none" stroke={C} strokeWidth={1.2} strokeLinejoin="round" />
    <path className="fwa-ortho-dim" pathLength={100} d="M-9 -2.4 h10 M-9 -3.6 v2.4 M1 -3.6 v2.4" fill="none" stroke={C} strokeWidth={0.6} />
    <g className="fwa-ortho-pen">
      <path d="M0 0 l1.2 -3.6 l7.4 -7.4 l2.4 2.4 l-7.4 7.4 z" fill={PLASTIC} stroke="#5c4400" strokeWidth={0.5} strokeLinejoin="round" />
      <path d="M0 0 l1.2 -3.6 l2.4 2.4 z" fill="#5c4400" />
    </g>
  </>;
}

function Smithy() {
  return <>
    <path d="M-10 -5 h17 v3.4 h-17 z M-10 -5 L-16 -4 L-10 -1.6 z" fill={W} />
    <rect x={-5.5} y={-1.6} width={7} height={3.6} fill={W} />
    <rect x={-8.5} y={2} width={13} height={2.8} rx={0.6} fill={W} />
    <rect className="fwa-smithy-glow" x={-5.5} y={-6.6} width={8} height={1.8} rx={0.9} fill="#FF922B" />
    <g fill="#FFE066">
      <rect className="fwa-smithy-spark" x={-2} y={-8} width={1.2} height={1.2} rx={0.3} />
      <rect className="fwa-smithy-spark" x={-1} y={-8} width={1} height={1} rx={0.3} />
      <rect className="fwa-smithy-spark" x={0} y={-8} width={1.2} height={1.2} rx={0.3} />
      <rect className="fwa-smithy-spark" x={-2.5} y={-7.5} width={0.9} height={0.9} rx={0.3} />
    </g>
    <g className="fwa-smithy-hammer">
      <rect x={-1} y={-11.5} width={15.5} height={2.4} rx={1} fill={PLASTIC} stroke="#5c4400" strokeWidth={0.4} />
      <rect x={-4.4} y={-14.6} width={6.4} height={7.8} rx={1} fill={W} stroke={C} strokeWidth={0.6} />
    </g>
  </>;
}

const GLYPHS: Record<string, (p: { uid: string }) => ReactNode> = {
  archie: Archie, mill: Mill, chuck: Chuck, axel: Axel, benny: Benny, molly: Molly, hex: Hex, fitz: Fitz, gage: Gage,
  ortho: Ortho, smithy: Smithy,
};

function Face({ state }: { state: AgentState }) {
  const mouth = state === "done" ? "M-3.6 13.4 Q0 17.6 3.6 13.4" : state === "blocked" ? "M-3 15.8 Q0 13.4 3 15.8"
    : state === "working" ? "M-1.6 14.2 Q0 15.8 1.6 14.2" : "M-3 13.8 Q0 16.4 3 13.8";
  return <g>
    <ellipse cx={-8.2} cy={13.4} rx={2} ry={1.2} fill="#ff8fab" opacity={0.35} />
    <ellipse cx={8.2} cy={13.4} rx={2} ry={1.2} fill="#ff8fab" opacity={0.35} />
    <g className="fwa-eyes">
      <circle cx={-4.4} cy={10.6} r={2.4} fill={W} /><circle cx={4.4} cy={10.6} r={2.4} fill={W} />
      <circle cx={state === "working" ? -4.4 : -4} cy={state === "working" ? 9.9 : 10.9} r={1.25} fill="#15171c" />
      <circle cx={state === "working" ? 4.4 : 4.8} cy={state === "working" ? 9.9 : 10.9} r={1.25} fill="#15171c" />
    </g>
    <path d={mouth} fill="none" stroke={W} strokeWidth={1.3} strokeLinecap="round" />
  </g>;
}

export function AgentAvatar({ code, state = "idle", size = 40, progress, still, className, label }: {
  code: string; state?: AgentState; size?: number; progress?: number | null; still?: boolean; className?: string;
  /** Accessible name; defaults to "<Name>, <state>". */ label?: string;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const a = AGENT[code] ?? { code, name: code, role: "", colour: "#868E96" };
  const Glyph = GLYPHS[code];
  const R = 23.2, circ = 2 * Math.PI * R;
  const pct = progress == null ? null : Math.max(0, Math.min(100, progress));
  return (
    <span className={cx("fwa", `fwa--${state}`, still && "fwa--still", className)} style={{ width: size, height: size, ["--c" as string]: a.colour }}
      role="img" aria-label={label ?? `${a.name}, ${STATE_LABEL[state]}`} title={label ?? `${a.name} · ${a.role} · ${STATE_LABEL[state]}`}>
      <svg viewBox="-26 -26 52 52" width={size} height={size} aria-hidden>
        <defs>
          <radialGradient id={`${uid}-shine`} cx="35%" cy="28%" r="75%">
            <stop offset="0%" stopColor="#fff" stopOpacity={0.32} /><stop offset="60%" stopColor="#fff" stopOpacity={0} />
            <stop offset="100%" stopColor="#000" stopOpacity={0.18} />
          </radialGradient>
          <clipPath id={`${uid}-badge`}><circle r={20.5} /></clipPath>
        </defs>
        {state === "working" && <>
          <circle r={R} fill="none" stroke={a.colour} strokeWidth={2.4} className="fwa-ring-track" />
          {pct != null && pct > 0
            ? <circle r={R} fill="none" stroke={a.colour} strokeWidth={2.4} strokeLinecap="round" className="fwa-ring-fill"
                strokeDasharray={`${(circ * pct) / 100} ${circ}`} transform="rotate(-90)" />
            : <circle r={R} fill="none" stroke={a.colour} strokeWidth={2.4} strokeLinecap="round" className="fwa-ring-spin"
                strokeDasharray={`${circ * 0.22} ${circ}`} />}
        </>}
        {state === "review" && <circle r={R} fill="none" stroke={a.colour} strokeWidth={2.2} className="fwa-ring-pulse" />}
        {state === "blocked" && <circle r={R} fill="none" stroke={AMBER} strokeWidth={2.2} />}
        <g className="fwa-body">
          <circle r={20.5} fill={a.colour} />
          <circle r={20.5} fill={`url(#${uid}-shine)`} />
          {Glyph && <g clipPath={`url(#${uid}-badge)`}><Glyph uid={uid} /></g>}
          <Face state={state} />
        </g>
        {state === "done" && <g className="fwa-badge">
          <circle cx={16.5} cy={-16.5} r={6.6} fill="#2F9E44" stroke="#fff" strokeWidth={1.6} />
          <path d="M13.6 -16.6 l2 2.1 l3.8 -4.1" fill="none" stroke="#fff" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
        </g>}
        {state === "blocked" && <g className="fwa-badge">
          <circle cx={16.5} cy={-16.5} r={6.6} fill={AMBER} stroke="#fff" strokeWidth={1.6} />
          <path d="M16.5 -20 v4.2" stroke="#fff" strokeWidth={2} strokeLinecap="round" /><circle cx={16.5} cy={-13.2} r={1.1} fill="#fff" />
        </g>}
      </svg>
    </span>
  );
}
