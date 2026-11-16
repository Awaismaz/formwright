import { AlertOctagon, CheckCircle2, Download, Info, RefreshCw, ScanSearch } from "lucide-react";
import { ago, cx } from "@/lib/format";
import { Button } from "@/components/ui";
import type { AsmView, BomRow } from "./types";
import { Section, grams, mm } from "./bits";

const STATUS: Record<string, { label: string; cls: string }> = {
  interference: { label: "Interference", cls: "bg-danger/10 text-danger border-danger/25" },
  thread: { label: "Thread", cls: "bg-text/[.06] text-muted border-border" },
  contact: { label: "Contact", cls: "bg-primary-soft text-primary border-primary/20" },
  clear: { label: "Clear", cls: "bg-success/10 text-success border-success/25" },
};

export function plural(n: number, word: string, many = `${word}s`): string { return `${n} ${n === 1 ? word : many}`; }

/** Two-line pair name, so long instance names are never cut in the 360 px panel. */
function PairName({ a, b }: { a: string; b: string }) {
  return <span className="min-w-0 leading-tight"><span className="block truncate">{a}</span><span className="block truncate text-muted">↔ {b}</span></span>;
}

export function CheckPanel({ view, onRun, busy, focus, onFocus, rowFocus, onRowFocus }: {
  view: AsmView; onRun: () => void; busy: boolean; focus: number | null; onFocus: (k: number | null) => void;
  rowFocus: number | null; onRowFocus: (k: number | null) => void;
}) {
  const an = view.analysis;
  const clashes = an?.interference.pairs.filter(p => p.kind === "interference") ?? [];
  const threads = an?.interference.pairs.filter(p => p.kind === "thread") ?? [];
  return (
    <div data-testid="check-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Button size="sm" icon={an ? <RefreshCw className="h-3.5 w-3.5" /> : <ScanSearch className="h-3.5 w-3.5" />} loading={busy}
          disabled={!view.can_edit || !view.instances.length} onClick={onRun} data-testid="run-check">{an ? "Re-run check" : "Run check"}</Button>
        {an && <span className={cx("text-[11.5px]", an.stale ? "font-medium text-warning" : "text-muted")}>{an.stale ? "Assembly changed since this check" : `Checked ${ago(an.at)}`}</span>}
      </div>
      {!an && <div className="px-4 py-6 text-[12.5px] leading-relaxed text-muted">Runs an exact boolean intersection between every pair of
        parts whose boxes overlap (interference volume in mm³) and the exact minimum distance between mated and neighbouring parts.</div>}
      {an && (
        <div className={cx(an.stale && "opacity-55 grayscale")} data-stale={an.stale || undefined}>
          <Section title="Interference" right={<span className="text-[11.5px] tabular-nums text-muted">{plural(an.interference.checked_pairs, "pair")} checked</span>}>
            {clashes.length === 0 ? (
              <div className={cx("flex items-center gap-2 rounded border px-2.5 py-2 text-[12.5px]",
                an.stale ? "border-border bg-text/[.03] text-muted" : "border-success/25 bg-success/5 text-success")} data-testid="no-clash">
                <CheckCircle2 className="h-4 w-4" />{an.stale ? "No interference at the last check. Re-run it for the current assembly." : "No interference"}</div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-center gap-2 rounded border border-danger/30 bg-danger/5 px-2.5 py-2 text-[12.5px] font-medium text-danger" data-testid="clash-summary">
                  <AlertOctagon className="h-4 w-4" />{clashes.length} interference{clashes.length > 1 ? "s" : ""} · {mm(an.interference.total_mm3, 3)} mm³</div>
                {clashes.map((p, k) => (
                  <button key={k} type="button" onClick={() => onFocus(focus === k ? null : k)} data-clash={k}
                    className={cx("flex w-full items-center justify-between gap-2 rounded border px-2.5 py-1.5 text-left text-[12px]",
                      focus === k ? "border-danger bg-danger/10" : "border-border hover:border-danger/50")}>
                    <PairName a={p.a_name} b={p.b_name} />
                    <span className="shrink-0 font-semibold tabular-nums text-danger">{mm(p.volume_mm3, 3)} mm³</span>
                  </button>
                ))}
              </div>
            )}
            {threads.length > 0 && <p className="mt-2 text-[11.5px] leading-snug text-muted">{threads.length} thread engagement{threads.length > 1 ? "s" : ""} (overlap inside a fastener's
              nominal thread Ø, expected with cosmetic threads) not counted.</p>}
          </Section>
          <Section title="Clearance" right={<span className="text-[11.5px] text-muted">min clear {an.clearance.min_clear_mm === null ? "—" : `${mm(an.clearance.min_clear_mm, 3)} mm`}</span>}>
            <div className="-mx-1 max-h-[340px] overflow-y-auto">
              <table className="w-full text-[12px]" data-testid="clearance-table">
                <thead><tr className="text-left text-[11px] text-muted"><th className="px-1 pb-1 font-medium">Pair</th><th className="px-1 pb-1 text-right font-medium">Min. distance</th><th className="px-1 pb-1" /></tr></thead>
                <tbody>
                  {an.clearance.rows.map((r, k) => (
                    <tr key={k} onClick={() => onRowFocus(rowFocus === k ? null : k)}
                      className={cx("cursor-pointer border-t border-border", rowFocus === k ? "bg-primary-soft/60" : "hover:bg-text/[.03]")}>
                      <td className="px-1 py-1" title={`${r.a_name} ↔ ${r.b_name}${r.mates.length ? " (mated)" : ""}`}><PairName a={r.a_name} b={r.b_name} /></td>
                      <td className="px-1 py-1 text-right tabular-nums">{r.status === "clear" ? `${mm(r.distance_mm, 3)} mm` : "0"}</td>
                      <td className="px-1 py-1 text-right"><span className={cx("rounded-full border px-1.5 py-px text-[10.5px] font-semibold", STATUS[r.status]!.cls)}>{STATUS[r.status]!.label}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11.5px] text-muted">Mated pairs, plus neighbours closer than 5 % of the assembly size (about {Math.max(1, Math.round(an.clearance.near_mm))} mm here). Click a row to show the gap.</p>
          </Section>
          <div className="flex items-start gap-2 px-4 py-3 text-[11.5px] leading-snug text-muted"><Info className="mt-px h-3.5 w-3.5 shrink-0" />{an.note}</div>
        </div>
      )}
    </div>
  );
}

export function BomPanel({ view, onFocus }: { view: AsmView; onFocus: (r: BomRow | null) => void }) {
  const b = view.bom;
  return (
    <div data-testid="bom-panel">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="text-[12.5px]"><b>{b.total_qty}</b> <span className="text-muted">parts ·</span> <b>{b.rows.length}</b> <span className="text-muted">line items</span></div>
        <a href={`/api/m/assembly/assemblies/${view.assembly.id}/bom?format=csv`} download>
          <Button size="sm" variant="secondary" icon={<Download className="h-3.5 w-3.5" />} disabled={!b.rows.length}>CSV</Button>
        </a>
      </div>
      <table className="w-full text-[12px]" data-testid="bom-table">
        <thead><tr className="border-b border-border text-left text-[11px] text-muted">
          <th className="py-1.5 pl-4 pr-1 font-medium">#</th><th className="px-1 py-1.5 font-medium">Qty</th>
          <th className="px-1 py-1.5 font-medium">Part</th><th className="py-1.5 pl-1 pr-4 text-right font-medium">Mass</th></tr></thead>
        <tbody>
          {b.rows.map(r => (
            <tr key={r.item} className="border-b border-border align-top hover:bg-text/[.03]" onMouseEnter={() => onFocus(r)} onMouseLeave={() => onFocus(null)}>
              <td className="py-1.5 pl-4 pr-1 tabular-nums text-muted">{r.item}</td>
              <td className="px-1 py-1.5 font-semibold tabular-nums">{r.qty}</td>
              <td className="px-1 py-1.5">
                <div className="font-medium leading-tight">{r.part}</div>
                <div className="text-[11px] leading-tight text-muted">{r.kind === "toolbox" ? r.standard : r.description}{r.material ? ` · ${r.material}` : ""}</div>
              </td>
              <td className="py-1.5 pl-1 pr-4 text-right tabular-nums">{grams(r.mass_total_g)}{r.qty > 1 && r.mass_each_g !== null && <div className="text-[10.5px] text-muted">{grams(r.mass_each_g)} ea</div>}</td>
            </tr>
          ))}
        </tbody>
        <tfoot><tr><td colSpan={3} className="py-2 pl-4 font-semibold">Total</td><td className="py-2 pr-4 text-right font-semibold tabular-nums">{grams(b.total_mass_g)}</td></tr></tfoot>
      </table>
      <p className="px-4 pb-4 text-[11.5px] leading-snug text-muted">{b.note}{b.mass_unknown_qty ? ` ${b.mass_unknown_qty} part(s) have no density on file and are not in the total.` : ""}</p>
    </div>
  );
}
