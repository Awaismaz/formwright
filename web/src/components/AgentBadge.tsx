import { cx } from "@/lib/format";

/** Design Office agents shown in the app (plan: docs/plans/CHIEF_DESIGNER.md §3). A round badge in the agent's
 * colour carrying its tool; "working" animates it (static when the system asks for reduced motion). */
export type AgentName = "Hex" | "Fitz";
export type AgentState = "idle" | "working" | "done";

const AGENTS: Record<AgentName, { color: string; role: string }> = {
  Hex: { color: "#b7791f", role: "Librarian: Toolbox and your parts" },
  Fitz: { color: "#2563eb", role: "Assembly: places and mates parts" },
};

function Glyph({ name }: { name: AgentName }) {
  if (name === "Hex") {   // a hex nut on a bolt
    return (
      <g>
        <rect x="10.6" y="3" width="2.8" height="18" rx="1" fill="#fff" opacity=".55" />
        <polygon points="12,6.2 17,9.1 17,14.9 12,17.8 7,14.9 7,9.1" fill="#fff" />
        <circle cx="12" cy="12" r="2.1" fill="currentColor" />
      </g>
    );
  }
  return (   // two parts with a dowel
    <g>
      <rect x="4" y="13" width="16" height="5" rx="1" fill="#fff" />
      <rect x="6" y="6" width="9" height="5.4" rx="1" fill="#fff" opacity=".85" />
      <rect x="9.2" y="4.5" width="2.6" height="12" rx="1.2" fill="currentColor" stroke="#fff" strokeWidth=".8" />
    </g>
  );
}

export function AgentBadge({ name, state = "idle", size = 28, className }: {
  name: AgentName; state?: AgentState; size?: number; className?: string;
}) {
  const a = AGENTS[name];
  return (
    <span title={`${name} · ${a.role}`} data-agent={name} data-state={state}
      className={cx("relative inline-flex shrink-0 items-center justify-center rounded-full", className)}
      style={{ width: size, height: size, background: a.color, color: a.color }}>
      <svg viewBox="0 0 24 24" width={size * 0.78} height={size * 0.78} aria-hidden
        className={cx(state === "working" && (name === "Hex" ? "animate-[spin_2.4s_linear_infinite]" : "animate-bounce"),
          "motion-reduce:animate-none")}>
        <Glyph name={name} />
      </svg>
      {state === "working" && <span className="absolute inset-[-3px] rounded-full border-2 border-transparent motion-reduce:hidden"
        style={{ borderTopColor: a.color, animation: "spin 1s linear infinite" }} />}
      {state === "done" && <span className="absolute -bottom-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-success text-[8px] font-bold text-white ring-2 ring-panel">✓</span>}
    </span>
  );
}

export function agentRole(name: AgentName): string {
  return AGENTS[name].role;
}
