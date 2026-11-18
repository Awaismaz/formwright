import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight, Coins, Library, MessageSquare, Puzzle, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx, num } from "@/lib/format";
import { Progress, Tip } from "@/components/ui";
import { AgentAvatar, AGENT } from "./Avatars";
import { BASE } from "./api";
import { boardLanes, canDrop, COLUMN_STATE, fmtEta, fmtMinutes, progressAfterMove } from "./model";
import type { Column, Program, Ticket } from "./types";

const COLUMN_TONE: Record<Column, string> = {
  backlog: "bg-text/20", ready: "bg-primary/50", in_design: "bg-primary", in_review: "bg-accent",
  changes_requested: "bg-warning", approved: "bg-success", integrated: "bg-success",
};

/** Move a ticket with an optimistic update; the live stream and the response confirm it. */
export function useMoveTicket(program: Program) {
  const qc = useQueryClient();
  return async (t: Ticket, column: Column) => {
    const key = ["office-program", program.id];
    const prev = qc.getQueryData<Program>(key);
    if (prev) qc.setQueryData<Program>(key, {
      ...prev, tickets: prev.tickets.map(x => x.id === t.id
        ? { ...x, column, agent_state: COLUMN_STATE[column], progress: progressAfterMove(x, column, prev.constants) } : x),
    });
    try {
      const v = await api.post<Program>(`${BASE}/programs/${program.id}/tickets/${t.id}/move`, { column });
      qc.setQueryData(key, (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
    } catch (e) {
      if (prev) qc.setQueryData(key, prev);
      toast.error(e instanceof ApiError ? e.message : "Could not move the ticket");
    }
  };
}

export function TicketCard({ t, maxEst, onOpen, draggable }: { t: Ticket; maxEst: number; onOpen: () => void; draggable: boolean }) {
  const outline = Math.max(18, Math.min(100, (100 * t.estimate_min) / Math.max(maxEst, 0.1)));
  return (
    <div role="button" tabIndex={0} draggable={draggable} onClick={onOpen} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
      onDragStart={e => { e.dataTransfer.setData("text/plain", t.id); e.dataTransfer.effectAllowed = "move"; }}
      aria-label={`${t.key} ${t.title}, ${AGENT[t.specialist]?.name}, ${t.progress} percent`}
      className={cx("group rounded-md border border-border bg-panel p-2 shadow-sm transition hover:border-primary/40 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        draggable && "cursor-grab active:cursor-grabbing", t.column === "changes_requested" && "border-warning/50")}>
      <div className="flex items-start gap-2">
        <AgentAvatar code={t.specialist} state={t.agent_state} size={30} progress={t.agent_state === "working" ? t.progress : null} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1 text-[10.5px] text-muted">
            <span className="font-mono">{t.key}</span>
            {t.kind === "standard" && <Tip content="Standard part: Hex picks it from the Toolbox"><Library className="h-3 w-3" /></Tip>}
            {t.kind === "integration" && <Tip content="Assembly integration"><Puzzle className="h-3 w-3" /></Tip>}
            {t.qty > 1 && <span>×{t.qty}</span>}
            <span className="ml-auto flex items-center gap-1">
              {t.checks && (t.checks.ok ? <Tip content="Latest Studio build passes the gating checks"><CheckCircle2 className="h-3.5 w-3.5 text-success" /></Tip>
                : <Tip content="Latest Studio build fails a gating check"><XCircle className="h-3.5 w-3.5 text-danger" /></Tip>)}
              {t.tokens > 0 && <Tip content="Tokens spent on this part"><span className="inline-flex items-center gap-0.5"><Coins className="h-3 w-3" />{num(t.tokens)}</span></Tip>}
              {t.comments.length > 0 && <span className="inline-flex items-center gap-0.5" title="Comments"><MessageSquare className="h-3 w-3" />{t.comments.length}</span>}
            </span>
          </div>
          <div className="line-clamp-2 text-[12.5px] font-medium leading-snug">{t.title}</div>
        </div>
      </div>
      <div className="mt-1.5" title={`Estimate ${fmtMinutes(t.estimate_min)} (outline) · ${t.progress} % done (fill)`}>
        <div className="h-1.5 rounded-full border border-text/25" style={{ width: `${outline}%` }}>
          <div className={cx("h-full rounded-full", t.progress >= 100 ? "bg-success" : "bg-primary")} style={{ width: `${t.progress}%` }} />
        </div>
        <div className="mt-0.5 flex justify-between text-[10.5px] tabular-nums text-muted"><span>{fmtMinutes(t.estimate_min)} est.</span><span>{t.progress} %</span></div>
      </div>
    </div>
  );
}

export default function Board({ program, onOpen }: { program: Program; onOpen: (t: Ticket) => void }) {
  const lanes = useMemo(() => boardLanes(program.items, program.tickets), [program.items, program.tickets]);
  const maxEst = Math.max(...program.tickets.map(t => t.estimate_min), 1);
  const move = useMoveTicket(program);
  const [over, setOver] = useState<string | null>(null);
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const canEdit = program.can_edit !== false;
  const byId = useMemo(() => new Map(program.tickets.map(t => [t.id, t])), [program.tickets]);
  const items = useMemo(() => new Map(program.items.map(i => [i.id, i])), [program.items]);

  return (
    <div className="snap-x snap-mandatory overflow-x-auto overscroll-x-contain scroll-pl-2 rounded-lg border border-border bg-panel2/40" data-board-scroll>
      <div className="min-w-[1180px] max-sm:min-w-[calc(7*78vw)]">
        <div className="sticky top-0 z-10 grid grid-cols-7 gap-2 border-b border-border bg-panel px-2 py-2">
          {program.columns.map(c => (
            <div key={c.code} className="flex snap-start items-center gap-1.5 px-1 text-[11.5px] font-semibold uppercase tracking-wider text-muted">
              <span className={cx("h-2 w-2 rounded-full", COLUMN_TONE[c.code])} />{c.label}
              <span className="ml-auto rounded-full bg-text/[.06] px-1.5 text-[10.5px] tabular-nums">{program.counts[c.code] ?? 0}</span>
            </div>))}
        </div>
        {lanes.map(l => {
          const it = l.item ? items.get(l.id) : null;
          const isFolded = folded.has(l.id);
          return (
            <section key={l.id} className="border-b border-border last:border-0" aria-label={`Swimlane ${l.name}`}>
              <button className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-panel max-sm:sticky max-sm:left-0 max-sm:max-w-[calc(100vw-2.5rem)] max-sm:overflow-hidden" aria-expanded={!isFolded}
                onClick={() => setFolded(f => { const n = new Set(f); n.has(l.id) ? n.delete(l.id) : n.add(l.id); return n; })}>
                {isFolded ? <ChevronRight className="h-3.5 w-3.5 text-muted" /> : <ChevronDown className="h-3.5 w-3.5 text-muted" />}
                <span className="whitespace-nowrap text-[13px] font-semibold">{l.name}</span>
                <span className="whitespace-nowrap text-[11.5px] text-muted">{l.tickets.length} tickets</span>
                {it && <>
                  <div className="ml-3 w-40 shrink-0"><Progress className="h-1" value={it.rollup.progress} tone={it.rollup.progress >= 100 ? "success" : "primary"} /></div>
                  <span className="whitespace-nowrap text-[11.5px] tabular-nums text-muted">{Math.round(it.rollup.progress)} % · ETA {fmtEta(it.eta)}</span>
                </>}
              </button>
              {!isFolded && <div className="grid grid-cols-7 gap-2 px-2 pb-2">
                {program.columns.map(c => {
                  const cards = l.tickets.filter(t => t.column === c.code);
                  const zone = `${l.id}:${c.code}`;
                  return (
                    <div key={c.code} data-zone={zone}
                      onDragOver={e => { if (!canEdit) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (over !== zone) setOver(zone); }}
                      onDragLeave={() => setOver(o => (o === zone ? null : o))}
                      onDrop={e => {
                        e.preventDefault(); setOver(null);
                        const t = byId.get(e.dataTransfer.getData("text/plain"));
                        if (!t || !l.tickets.includes(t)) { if (t) toast.info("A ticket stays in its own sub-assembly's lane."); return; }
                        if (canDrop(t, c.code)) move(t, c.code);
                      }}
                      className={cx("min-h-[72px] space-y-2 rounded-md p-1 transition", over === zone ? "bg-primary-soft ring-2 ring-primary/30" : "bg-transparent")}>
                      {cards.map(t => <TicketCard key={t.id} t={t} maxEst={maxEst} draggable={canEdit} onOpen={() => onOpen(t)} />)}
                    </div>);
                })}
              </div>}
            </section>);
        })}
      </div>
    </div>
  );
}
