import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, CircleDot, MousePointerClick, Wrench, X, XCircle } from "lucide-react";
import { cx } from "@/lib/format";
import { Button, Spinner, Toggle } from "@/components/ui";
import type { AsmView, FitPlan } from "./types";
import { Section, Segmented, VerifyTag, mm } from "./bits";
import { StackDiagram } from "./StackDiagram";

export interface FitOpts { style: "hex_bolt" | "shcs"; washers: "both" | "head" | "none"; pattern: boolean; flip: boolean }
const SERIES = [3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 180, 200, 220, 240, 260, 280, 300];

export function holeLabel(view: AsmView, inst: string, hole: number): string {
  const i = view.instances.find(x => x.id === inst);
  const p = i ? view.parts[i.part] : undefined;
  const h = p?.holes[hole];
  if (!i || !h) return "";
  return `Ø${h.d} ${h.through ? "through" : `blind ${mm(h.depth, 1)} mm`} · ${i.display}`;
}

export function FastenPanel({ view, target, onTarget, opts, onOpts, plan, loading, error, onInsert, busy }: {
  view: AsmView; target: { inst: string; hole: number } | null; onTarget: (t: { inst: string; hole: number } | null) => void;
  opts: FitOpts; onOpts: (o: FitOpts) => void; plan: FitPlan | null; loading: boolean; error: string | null;
  onInsert: () => void; busy: boolean;
}) {
  const [showSrc, setShowSrc] = useState(false);
  const candidates = view.instances.filter(i => !i.group && i.visible).flatMap(i => {
    const p = view.parts[i.part];
    if (!p) return [];
    const axis = (hid: number) => {
      const a = p.holes[hid]?.axis ?? [0, 0, 1];
      const T = i.T;
      const w = [0, 1, 2].map(r => T[4 * r]! * a[0] + T[4 * r + 1]! * a[1] + T[4 * r + 2]! * a[2]);
      const k = w.reduce((best, v, j) => (Math.abs(v) > Math.abs(w[best]!) ? j : best), 0);
      return Math.abs(w[k]!) > 0.999 ? `along ${"XYZ"[k]}` : "inclined";
    };
    const inPattern = new Set(p.patterns.flatMap(pt => pt.holes));
    const rows = p.patterns.map(pt => ({ inst: i.id, hole: pt.holes[0]!, label: `${pt.count} × Ø${pt.d}`, sub: `${pt.kind === "set" ? "set" : pt.kind} · ${axis(pt.holes[0]!)} · ${i.display}` }));
    p.holes.forEach(h => { if (!inPattern.has(h.id)) rows.push({ inst: i.id, hole: h.id, label: `Ø${h.d}`, sub: `${h.through ? "through" : "blind"} · ${axis(h.id)} · ${i.display}` }); });
    return rows;
  });
  const tPart = target ? view.parts[view.instances.find(i => i.id === target.inst)?.part ?? ""] : undefined;
  const pattern = target && tPart ? tPart.patterns.find(p => p.holes.includes(target.hole)) : undefined;
  const first = plan?.holes.find(h => h.proposal.ok) ?? plan?.holes[0];
  const prop = first?.proposal;
  const lens = prop?.length;
  const uniform = plan ? plan.stacks.length <= 1 && plan.failed === 0 : true;
  const noRoom = !!plan?.holes.some(h => h.proposal.ok && h.proposal.no_room);
  return (
    <div data-testid="fasten-panel">
      <div className="flex items-start gap-2.5 border-b border-border bg-gradient-to-b from-accent/[.07] to-transparent px-4 py-3.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent/15 text-accent"><Wrench className="h-4 w-4" /></div>
        <div className="text-[12.5px] leading-snug text-muted"><b className="text-text">Fastener auto-fit.</b> Pick a hole. Formwright measures the
          clamped thickness through the mated parts and proposes an ISO stack with a standard length.</div>
      </div>
      <Section title="1 · Hole">
        {target ? (
          <div className="flex items-center gap-2 rounded border border-primary/40 bg-primary-soft/50 px-2.5 py-2 text-[12.5px]" data-testid="fit-target">
            <CircleDot className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 flex-1 truncate">{holeLabel(view, target.inst, target.hole)}</span>
            <button type="button" onClick={() => onTarget(null)} className="rounded p-0.5 text-muted hover:text-text"><X className="h-3.5 w-3.5" /></button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 rounded border border-dashed border-primary/50 px-2.5 py-2 text-[12.5px] text-muted">
            <MousePointerClick className="h-3.5 w-3.5" />Click a hole in the view (recognised holes glow green), or choose:
          </div>
        )}
        {!target && candidates.length > 0 && (
          <div className="mt-2 space-y-1">
            {candidates.map(c => (
              <button key={`${c.inst}-${c.hole}`} type="button" onClick={() => onTarget({ inst: c.inst, hole: c.hole })} data-fit-hole={`${c.inst}-${c.hole}`}
                className="flex w-full items-center gap-2 rounded border border-border px-2.5 py-1.5 text-left text-[12.5px] hover:border-primary/40 hover:bg-primary-soft/40">
                <span className="font-semibold">{c.label}</span><span className="truncate text-muted">{c.sub}</span>
              </button>
            ))}
          </div>
        )}
        {!target && candidates.length === 0 && <p className="mt-2 text-[12px] text-muted">No recognised holes in the visible parts.</p>}
        {pattern && (
          <label className="mt-2.5 flex items-center gap-2 text-[12.5px]">
            <Toggle checked={opts.pattern} onChange={v => onOpts({ ...opts, pattern: v })} label="Whole pattern" />
            All {pattern.count} holes of this pattern
          </label>
        )}
      </Section>
      <Section title="2 · Stack">
        <div className="space-y-2">
          <Segmented value={opts.style} onChange={v => onOpts({ ...opts, style: v })} options={[
            { value: "hex_bolt", label: "Hex bolt", title: "ISO 4017 hex head screw" }, { value: "shcs", label: "Socket head", title: "ISO 4762 socket head cap screw" }]} />
          <Segmented value={opts.washers} onChange={v => onOpts({ ...opts, washers: v })} size="sm" options={[
            { value: "both", label: "2 washers" }, { value: "head", label: "Under head" }, { value: "none", label: "No washers" }]} />
          {first?.probe.kind !== "tapped" && (
            <label className="flex items-center gap-2 text-[12.5px]">
              <Toggle checked={opts.flip} onChange={v => onOpts({ ...opts, flip: v })} label="Other side" />Head on the other side
            </label>
          )}
        </div>
      </Section>
      {target && (
        <div className="border-b border-border px-4 py-3.5" data-testid="fit-proposal">
          {loading && !plan && <div className="flex items-center gap-2 py-6 text-[12.5px] text-muted"><Spinner className="h-4 w-4" />Measuring the grip along the hole axis…</div>}
          {error && <div className="flex items-start gap-2 rounded border border-danger/30 bg-danger/5 p-2.5 text-[12.5px] text-danger"><XCircle className="mt-px h-4 w-4 shrink-0" />{error}</div>}
          {plan && prop && (
            <div className={cx("space-y-3", loading && "opacity-60")}>
              {prop.ok ? (
                <>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-[14px] font-semibold leading-tight">{prop.summary}</div>
                      <div className="mt-0.5 text-[11.5px] text-muted">{first!.probe.kind === "tapped" ? "Tapped joint" : "Through joint"} · {plan.ok} hole{plan.ok === 1 ? "" : "s"}</div>
                    </div>
                    <VerifyTag />
                  </div>
                  <div className="rounded-md border border-border bg-panel2/60 p-1.5"><StackDiagram probe={first!.probe} prop={prop} /></div>
                  <div className="text-[12px]">
                    <div className="mb-1 font-medium">{first!.probe.kind === "tapped" ? "Screw length" : "Bolt length"}</div>
                    <table className="w-full tabular-nums">
                      <tbody>
                        {lens!.terms.map(t => <tr key={t.label}><td className="py-0.5 text-muted">{t.label}</td><td className="py-0.5 text-right">{mm(t.mm, 3)} mm</td></tr>)}
                        <tr className="border-t border-border font-medium"><td className="pt-1">Minimum length</td><td className="pt-1 text-right">≥ {mm(lens!.L_min, 3)} mm</td></tr>
                        {lens!.L_max !== undefined && <tr><td className="text-muted">Maximum (thread depth)</td><td className="text-right">≤ {mm(lens!.L_max, 3)} mm</td></tr>}
                      </tbody>
                    </table>
                    <div className="mt-2 flex flex-wrap gap-1" aria-label="ISO 888 lengths">
                      {SERIES.filter(L => L >= (lens!.L ?? 0) - 15 && L <= (lens!.L ?? 0) + 15).map(L => (
                        <span key={L} className={cx("rounded px-1.5 py-0.5 text-[11px] tabular-nums",
                          L === lens!.L ? "bg-primary font-bold text-primary-fg" : L < lens!.L_min || (lens!.L_max !== undefined && L > lens!.L_max) ? "bg-text/5 text-muted/60 line-through" : "bg-text/5 text-muted")}>{L}</span>
                      ))}
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
                      {lens!.protrusion !== undefined && <><span className="text-muted">Thread past nut</span><span className="text-right">{mm(lens!.protrusion)} mm ({lens!.protrusion_threads} × P)</span></>}
                      {lens!.engagement !== undefined && <><span className="text-muted">Thread engaged</span><span className="text-right">{mm(lens!.engagement)} mm</span></>}
                      {!!lens!.protrudes && <><span className="text-muted">Protrudes below</span><span className="text-right">{mm(lens!.protrudes)} mm</span></>}
                      <span className="text-muted">Grip measured</span><span className="text-right">{mm(first!.probe.grip, 3)} mm</span>
                    </div>
                    <div className="mt-1.5 text-[11.5px] text-muted">{first!.probe.members.map(m => `${m.name} ${mm(m.t, 3)}`).join(" + ")}{first!.probe.tapped ? ` · into ${first!.probe.tapped.name}` : ""}</div>
                  </div>
                  {prop.clearance && <div className="rounded bg-text/[.04] px-2.5 py-1.5 text-[11.5px]">{prop.clearance.text}.</div>}
                  <p className="text-[11px] leading-snug text-muted">{prop.rule}</p>
                </>
              ) : (
                <div className="rounded border border-danger/30 bg-danger/5 p-2.5 text-[12.5px] text-danger">
                  <div className="flex items-start gap-2"><XCircle className="mt-px h-4 w-4 shrink-0" />{prop.error}</div>
                  {first?.probe.mismatch && (
                    <Button size="sm" variant="secondary" className="mt-2 w-full" data-testid="fit-smaller"
                      onClick={() => { onOpts({ ...opts, pattern: false }); onTarget({ inst: first.probe.mismatch!.inst, hole: first.probe.mismatch!.hole }); }}>
                      Fit M{first.probe.mismatch.size} from the {first.probe.mismatch.name} hole</Button>
                  )}
                </div>
              )}
              {!uniform && (
                <div className="rounded border border-border">
                  {plan.holes.map((h, k) => (
                    <div key={k} className="flex items-center justify-between gap-2 border-b border-border px-2 py-1 text-[11.5px] last:border-0">
                      <span className="text-muted">Hole {k + 1} · grip {mm(h.probe.grip, 2)}</span>
                      <span className={cx("truncate", !h.proposal.ok && "text-danger")}>{h.proposal.ok ? h.proposal.items![0]!.title.replace(/^.* (M\d+×\d+)$/, "$1") : h.proposal.error}</span>
                    </div>
                  ))}
                </div>
              )}
              {[...new Set(plan.holes.flatMap(h => h.proposal.warnings))].map(w => (
                <div key={w} className="flex items-start gap-1.5 rounded border border-warning/30 bg-warning/5 px-2 py-1.5 text-[11.5px] text-warning"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{w}</div>
              ))}
              <button type="button" onClick={() => setShowSrc(s => !s)} className="flex items-center gap-1 text-[11.5px] text-muted hover:text-text">
                {showSrc ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}Sources
              </button>
              {showSrc && <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted">{prop.sources.map(s => <li key={s}>{s}</li>)}</ul>}
            </div>
          )}
        </div>
      )}
      {target && (
        <div className="sticky bottom-0 z-10 border-t border-border bg-panel/95 px-4 py-3 backdrop-blur">
          <Button variant={noRoom ? "secondary" : "accent"} className="w-full" icon={<Wrench className="h-4 w-4" />} disabled={!plan || plan.ok === 0 || !view.can_edit || loading}
            loading={busy} onClick={onInsert} data-testid="fit-insert">
            {noRoom ? "Insert anyway (will clash)" : plan && plan.ok > 1 ? `Insert ${plan.ok} stacks` : "Insert stack"}
          </Button>
          <p className="mt-1.5 text-[11px] leading-snug text-muted">{noRoom
            ? "Another part is in the way of the head or nut (see the warning). Move it, flip the stack or change the washers first."
            : "Inserted as Toolbox parts, mated concentric with the hole and seated on the faces, then checked for interference."}</p>
        </div>
      )}
    </div>
  );
}
