import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Coins, Gauge } from "lucide-react";
import { api } from "@/lib/api";
import type { RunEstimate } from "@/lib/types";
import { cx, num } from "@/lib/format";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "./ui";

export interface MeterEvent { tokens: number; budget_tokens: number | null }

const PRESETS = [100, 250, 500, 1000, 2000];

/** Replaces the static estimate beside Send: before a run, the measured range and the budget it will stop at;
 *  during a run, tokens spent so far against that budget. */
export default function RunMeter({ projectId, busy, meter, unlimited, balance, long, budget, onBudget, version }: {
  projectId: string; busy: boolean; meter: MeterEvent | null; unlimited: boolean; balance?: number;
  /** a long brief (pasted spec): learned estimates keep short and long briefs apart */
  long: boolean; budget: number | null; onBudget: (v: number | null) => void; version: number;
}) {
  const est = useQuery({ queryKey: ["estimate", projectId, long, version],
    queryFn: () => api.get<RunEstimate>(`/api/projects/${projectId}/estimate?chars=${long ? 1200 : 0}`) });
  const e = est.data;
  if (unlimited) return <span className="flex-1 truncate text-[11px] text-muted">Unlimited tokens (God mode) · <span className="kbd">Ctrl ↵</span></span>;

  if (busy) {
    const spent = meter?.tokens ?? 0;
    const cap = meter?.budget_tokens ?? null;
    return (
      <span className="flex min-w-0 flex-1 items-center gap-2 text-[11px] text-muted" aria-live="polite">
        <Coins className="h-3.5 w-3.5 shrink-0 text-accent" />
        <span className="tabular-nums"><b className="font-semibold text-text">{num(spent)}</b>{cap ? ` / ${num(cap)}` : ""} tokens</span>
        {cap && <span className="h-1 w-16 overflow-hidden rounded-full bg-text/10"><span className={cx("block h-full rounded-full transition-all", spent / cap > 0.85 ? "bg-warning" : "bg-primary")} style={{ width: `${Math.min(100, (spent / cap) * 100)}%` }} /></span>}
      </span>);
  }

  if (!e) return <span className="flex-1" />;
  const stopAt = budget ?? e.budget;
  const short = e.budget !== null && e.budget < e.typical;
  const presets = PRESETS.filter(p => p >= e.budget_min && p <= e.budget_max && p !== e.default_budget);
  return (
    <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 text-[11px] text-muted">
      <span title={e.basis === "workspace" ? `Learned from ${e.samples} runs in this workspace` : "Measured on typical runs"}>
        ≈ {num(e.typical)} tokens ({num(e.low)} to {num(e.high)}) · {e.kind === "new" ? "new part" : "change"}
      </span>
      {stopAt !== null && <>·
        <Menu>
          <MenuTrigger asChild>
            <button className={cx("inline-flex items-center gap-0.5 rounded px-1 hover:bg-text/5", short ? "text-warning" : "text-text")} aria-label="Run budget">
              <Gauge className="h-3 w-3" />stops at {num(stopAt)}<ChevronDown className="h-3 w-3" />
            </button>
          </MenuTrigger>
          <MenuContent align="start">
            <MenuLabel>Stop this run at</MenuLabel>
            <MenuItem onSelect={() => onBudget(null)}>{num(Math.min(e.default_budget, e.budget ?? e.default_budget))} tokens · workspace default{budget === null ? " ✓" : ""}</MenuItem>
            {presets.map(p => <MenuItem key={p} onSelect={() => onBudget(p)}>{num(p)} tokens{budget === p ? " ✓" : ""}{balance !== undefined && p > balance ? " (more than your balance)" : ""}</MenuItem>)}
            <MenuSeparator />
            <div className="max-w-[240px] px-2.5 py-1.5 text-[11px] leading-snug text-muted">The run stops cleanly at the budget and is never charged more. It can't exceed your balance.</div>
          </MenuContent>
        </Menu></>}
      {short && <span className="text-warning">· balance covers only part of a typical run</span>}
      <span className="kbd ml-0.5 max-sm:hidden">Ctrl ↵</span>
    </span>);
}
