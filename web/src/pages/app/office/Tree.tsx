import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Puzzle } from "lucide-react";
import { cx } from "@/lib/format";
import { Progress } from "@/components/ui";
import { AgentAvatar } from "./Avatars";
import { fmtEta, fmtMinutes } from "./model";
import type { Item, Program, Ticket } from "./types";

/** Program -> sub-assemblies -> parts, each with its effort-weighted progress; ETA ranges at assembly levels. */
export default function Tree({ program, onOpen }: { program: Program; onOpen: (t: Ticket) => void }) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const kids = useMemo(() => {
    const m = new Map<string, Item[]>();
    for (const i of program.items) if (i.parent_id) m.set(i.parent_id, [...(m.get(i.parent_id) ?? []), i]);
    return m;
  }, [program.items]);
  const ticketOf = useMemo(() => new Map(program.tickets.map(t => [t.item_id, t])), [program.tickets]);
  const col = Object.fromEntries(program.columns.map(c => [c.code, c.label]));
  const rows: React.ReactNode[] = [];
  const walk = (it: Item, depth: number) => {
    const t = ticketOf.get(it.id);
    const children = kids.get(it.id) ?? [];
    const open = !closed.has(it.id);
    const toggle = () => setClosed(s => { const n = new Set(s); n.has(it.id) ? n.delete(it.id) : n.add(it.id); return n; });
    rows.push(
      <tr key={it.id} className={cx("border-t border-border", it.kind !== "part" && "bg-panel2/50")}>
        <td className="py-2 pr-3">
          <div className="flex items-center gap-2" style={{ paddingLeft: depth * 22 }}>
            {children.length ? <button onClick={toggle} aria-label={open ? `Collapse ${it.name}` : `Expand ${it.name}`} aria-expanded={open} className="rounded p-0.5 text-muted hover:bg-text/5">
              {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button> : <span className="w-5" />}
            {t ? <AgentAvatar code={t.specialist} state={t.agent_state} size={26} progress={t.agent_state === "working" ? t.progress : null} /> : null}
            <button className={cx("min-w-0 truncate text-left hover:text-primary", it.kind === "program" ? "text-[14px] font-semibold" : it.kind === "subassembly" ? "font-semibold" : "")}
              onClick={() => t && onOpen(t)}>{it.kind === "program" ? program.name : it.name}{it.qty && it.qty > 1 ? <span className="text-muted"> ×{it.qty}</span> : null}</button>
            {it.kind !== "part" && t && <span className="inline-flex items-center gap-1 text-[11px] text-muted"><Puzzle className="h-3 w-3" />{t.key}</span>}
          </div>
        </td>
        <td className="w-48 py-2 pr-3">
          <div className="flex items-center gap-2"><Progress className="flex-1" value={it.rollup.progress} tone={it.rollup.progress >= 100 ? "success" : "primary"} />
            <span className="w-11 text-right text-[12px] tabular-nums">{Math.round(it.rollup.progress)} %</span></div>
        </td>
        <td className="w-24 py-2 pr-3 text-right text-[12.5px] tabular-nums text-muted">{fmtMinutes(it.rollup.estimate_min)}</td>
        <td className="w-32 py-2 pr-3 text-right text-[12.5px] tabular-nums">{it.eta ? fmtEta(it.eta) : ""}</td>
        <td className="w-40 py-2 text-[12px] text-muted">{t ? (it.kind === "part" ? col[t.column] : `Integration: ${col[t.column]}`) : ""}</td>
      </tr>);
    if (open) for (const c of children) walk(c, depth + 1);
  };
  const root = program.items.find(i => i.id === "root");
  if (root) walk(root, 0);
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[760px] text-[13px]">
        <thead><tr className="text-left text-[11px] uppercase tracking-wider text-muted">
          <th className="px-0 py-2 pl-3">Item</th><th className="py-2">Progress (effort-weighted)</th><th className="py-2 text-right">Effort</th>
          <th className="py-2 pr-3 text-right" title="Estimated remaining agent time at the program's concurrency">ETA range</th><th className="py-2">Status</th></tr></thead>
        <tbody className="[&_td:first-child]:pl-3">{rows}</tbody>
      </table>
      <p className="border-t border-border px-3 py-2 text-[11.5px] text-muted">Each assembly level includes its own integration effort. ETA = remaining critical path and work shared over {program.concurrency} agents in parallel; a range, never a promise.</p>
    </div>
  );
}
