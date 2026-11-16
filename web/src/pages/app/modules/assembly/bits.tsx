import type { ReactNode } from "react";
import { AlertOctagon, CheckCircle2, CircleDashed, Move3d } from "lucide-react";
import { cx } from "@/lib/format";
import type { Solve, SolveStatus } from "./types";

export function SolveChip({ status, solve, compact, dof, spins: spinsIn }: {
  status: SolveStatus; solve?: Solve | null; compact?: boolean; dof?: number | null; spins?: number | null;
}) {
  const spins = solve?.free_spins ?? spinsIn ?? 0;
  const known = solve ? solve.dof : dof ?? null;
  const other = known === null ? 1 : known - spins;
  if (status === "over_defined") {
    return <span className="inline-flex items-center gap-1 rounded-full border border-danger/30 bg-danger/10 px-2 py-0.5 text-[11.5px] font-semibold text-danger">
      <AlertOctagon className="h-3.5 w-3.5" />Over-defined{solve && !compact ? ` · ${solve.conflicts.length} conflicting` : ""}</span>;
  }
  if (status === "fully_defined" || other === 0) {
    return <span className="inline-flex items-center gap-1 rounded-full border border-success/30 bg-success/10 px-2 py-0.5 text-[11.5px] font-semibold text-success">
      <CheckCircle2 className="h-3.5 w-3.5" />Fully positioned{!compact && spins ? ` · ${spins} free spin${spins > 1 ? "s" : ""}` : ""}</span>;
  }
  return <span className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-[11.5px] font-semibold text-warning">
    {compact ? <CircleDashed className="h-3.5 w-3.5" /> : <Move3d className="h-3.5 w-3.5" />}Under-defined{solve && !compact ? ` · ${other} DOF` : ""}</span>;
}

export function Segmented<T extends string>({ value, options, onChange, disabled, size = "md" }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; disabled?: boolean; size?: "sm" | "md";
}) {
  return (
    <div className="flex rounded-md border border-border bg-panel2 p-0.5">
      {options.map(o => (
        <button key={o.value} type="button" title={o.title} disabled={disabled} onClick={() => onChange(o.value)}
          className={cx("flex flex-1 items-center justify-center gap-1 rounded transition disabled:cursor-not-allowed disabled:opacity-60",
            size === "sm" ? "px-1.5 py-0.5 text-[12px]" : "px-2 py-1 text-[12.5px]",
            value === o.value ? "bg-panel font-medium text-text shadow-sm" : "text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Section({ title, children, right, className }: { title: ReactNode; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cx("border-b border-border px-4 py-3.5", className)}>
      <div className="mb-2 flex items-center justify-between gap-2"><div className="label">{title}</div>{right}</div>
      {children}
    </div>
  );
}

export function mm(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

export function grams(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(3)} kg` : `${v.toFixed(1)} g`;
}

export function VerifyTag() {
  return <span title="Nominal catalogue values and common design rules. Check against your standard before release."
    className="inline-flex items-center rounded border border-accent/40 bg-accent/10 px-1.5 py-px text-[10.5px] font-bold uppercase tracking-wide text-accent">Verify</span>;
}
