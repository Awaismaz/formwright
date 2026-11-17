import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeftRight, CheckCircle2, Hammer, Wrench, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, Spinner } from "@/components/ui";
import type { AsmView, HoleFix, PairPlan } from "./types";
import { Section, VerifyTag, mm } from "./bits";

/** "Fasten these two parts" (AMI-I2): every coaxial hole pair between two parts, each with its proposed ISO stack.
 * A mismatched pair (Ø6.6 over Ø5.5) is fitted from the smaller hole and offers the one-click part fix: a
 * deterministic parameter edit of that part's project, then a refresh of this assembly. */
export function PairPanel({ view, aid, pair, onPair, style, washers, onInsert, onFix, busy }: {
  view: AsmView; aid: string; pair: [string | null, string | null]; onPair: (p: [string | null, string | null]) => void;
  style: "hex_bolt" | "shcs"; washers: "both" | "head" | "none";
  onInsert: (targets: { inst: string; hole: number }[]) => void;
  onFix: (inst: string, fix: HoleFix) => void; busy: string | null;
}) {
  const parts = view.instances.filter(i => !i.group);
  const [a, b] = pair;
  const q = useQuery({
    queryKey: ["asm-pairs", aid, a, b, style, washers, view.assembly.rev],
    queryFn: () => api.post<PairPlan>(`/api/m/assembly/assemblies/${aid}/fasteners/pairs`, { a, b, style, washers }),
    enabled: !!a && !!b && a !== b, retry: false, staleTime: 60_000,
  });
  const plan = q.data;
  const ok = plan?.pairs.filter(p => p.proposal.ok) ?? [];
  const noRoom = ok.some(p => p.proposal.no_room);
  const pick = (k: 0 | 1, id: string) => onPair(k === 0 ? [id || null, b] : [a, id || null]);
  return (
    <div data-testid="pair-panel">
      <Section title="Parts">
        <div className="space-y-1.5">
          {([0, 1] as const).map(k => (
            <select key={k} value={pair[k] ?? ""} onChange={e => pick(k, e.target.value)} data-pair-part={k}
              className="h-8 w-full rounded border border-border bg-panel px-2 text-[12.5px]">
              <option value="">{k === 0 ? "First part…" : "Second part…"}</option>
              {parts.filter(i => i.id !== pair[1 - k]).map(i => <option key={i.id} value={i.id}>{i.display}</option>)}
            </select>
          ))}
        </div>
        <p className="mt-2 text-[11.5px] leading-snug text-muted">Or click two parts in the view. Every hole of the first part that lines
          up with a hole of the second gets a stack, fitted from the smaller hole.</p>
      </Section>
      {a && b && (
        <div className="border-b border-border px-4 py-3.5" data-testid="pair-results">
          {q.isFetching && !plan && <div className="flex items-center gap-2 py-4 text-[12.5px] text-muted"><Spinner className="h-4 w-4" />Finding lined-up holes and measuring grips…</div>}
          {q.error && <div className="flex items-start gap-2 rounded border border-danger/30 bg-danger/5 p-2.5 text-[12.5px] text-danger"><XCircle className="mt-px h-4 w-4 shrink-0" />{(q.error as Error).message}</div>}
          {plan && plan.pairs.length === 0 && (
            <p className="text-[12.5px] text-muted">No holes of {plan.a_name} line up with holes of {plan.b_name} in the current placement. Mate a pair of holes concentric first.</p>
          )}
          {plan && plan.pairs.length > 0 && (
            <div className={cx("space-y-2", q.isFetching && "opacity-60")}>
              <div className="flex items-center justify-between">
                <span className="text-[12.5px] font-medium">{plan.pairs.length} hole pair{plan.pairs.length > 1 ? "s" : ""} lined up</span>
                <VerifyTag />
              </div>
              {plan.pairs.map((p, k) => {
                const mm_ = p.mismatch;
                const big = mm_ ? Math.max(p.a_d, p.b_d) : null;
                return (
                  <div key={k} className="rounded border border-border px-2.5 py-2 text-[12px]" data-pair={k}>
                    <div className="flex items-center gap-1.5 text-muted">
                      <span>Ø{p.a_d}</span><ArrowLeftRight className="h-3 w-3" /><span>Ø{p.b_d}</span>
                      <span className="ml-auto tabular-nums">grip {p.grip === null ? "—" : `${mm(p.grip, 2)} mm`}</span>
                    </div>
                    {p.proposal.ok
                      ? <div className="mt-0.5 flex items-center gap-1.5 font-medium"><CheckCircle2 className="h-3.5 w-3.5 text-success" />{p.proposal.summary}</div>
                      : <div className="mt-0.5 flex items-start gap-1.5 text-danger"><XCircle className="mt-px h-3.5 w-3.5 shrink-0" />{p.proposal.error}</div>}
                    {mm_ && (
                      <div className="mt-1.5 rounded border border-warning/30 bg-warning/5 px-2 py-1.5 text-[11.5px] text-warning">
                        <div className="flex items-start gap-1.5"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
                          <span>The holes differ: Ø{mm_.d} in {mm_.name} is smaller than Ø{big}. {p.proposal.ok ? `${p.proposal.designation} fits through both.` : ""}</span></div>
                        {mm_.fix ? (
                          <Button size="sm" variant="secondary" className="mt-1.5 h-auto w-full whitespace-normal py-1.5 text-left" icon={<Hammer className="h-3.5 w-3.5" />}
                            disabled={!view.can_edit || !!busy} loading={busy === "fix"} onClick={() => onFix(mm_.inst, mm_.fix!)} data-testid="fix-hole">
                            Open to Ø{mm_.to_d}{mm_.size ? ` for M${mm_.size}` : ""}: {mm_.fix.label} {mm_.fix.from} → {mm_.fix.to}
                          </Button>
                        ) : <p className="mt-1 text-muted">To fit M{mm_.size ?? "?"} instead, open the hole in the Design Studio.</p>}
                        {mm_.fix && <p className="mt-1 leading-snug text-muted">Changes {mm_.fix.project} ({mm_.fix.label} applies to every hole it drives),
                          rebuilt and checked in the Design Studio, then this assembly is refreshed.</p>}
                      </div>
                    )}
                    {p.proposal.warnings.filter(w => !w.includes("ISO 273")).map(w => <p key={w} className="mt-1 text-[11px] text-warning">{w}</p>)}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      {a && b && plan && ok.length > 0 && (
        <div className="sticky bottom-0 z-10 border-t border-border bg-panel/95 px-4 py-3 backdrop-blur">
          <Button variant={noRoom ? "secondary" : "accent"} className="w-full" icon={<Wrench className="h-4 w-4" />} disabled={!view.can_edit || q.isFetching}
            loading={busy === "fit"} onClick={() => onInsert(ok.map(p => p.target))} data-testid="pair-insert">
            {noRoom ? "Insert anyway (will clash)" : `Insert ${ok.length} stack${ok.length > 1 ? "s" : ""}`}
          </Button>
        </div>
      )}
    </div>
  );
}
