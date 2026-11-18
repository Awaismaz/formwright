import { Link } from "react-router-dom";
import { Boxes, Camera, CircleAlert, CircleCheck, FolderKanban, Link2Off, MoveRight, Wrench } from "lucide-react";
import type { Impact } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button } from "@/components/ui";

const n1 = (v: number) => String(+v.toFixed(v < 10 ? 2 : 1));

/** ASM-018: what a pending edit does to the assemblies using this part, before it is applied (trial rebuild, nothing
 *  committed). Compact: the headline, then per assembly the mates that break, new clashes, refits and moves. */
export function ImpactDetails({ impact, compact = false }: { impact: Impact; compact?: boolean }) {
  const bad = (impact.issues ?? 0) > 0;
  return (
    <div className="space-y-1.5 text-[12px]" data-testid="impact-details">
      <div className={cx("flex items-start gap-1.5 font-medium", bad ? "text-warning" : "text-success")}>
        {bad ? <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <CircleCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
        <span>{impact.headline}</span>
      </div>
      {!compact && impact.assemblies.map(a => (
        <div key={a.id} className="rounded border border-border bg-panel px-2 py-1.5">
          <Link to={`/app/modules/assembly?assembly=${a.id}`} className="flex items-center gap-1 font-medium hover:text-primary">
            <Boxes className="h-3 w-3" />{a.name}{a.program ? <span className="text-muted"> · program</span> : null}</Link>
          {a.error && <p className="text-muted">{a.error}</p>}
          <ul className="mt-0.5 space-y-0.5">
            {a.mates.filter(m => m.status === "breaks").map(m => <li key={m.id} className="flex gap-1 text-danger"><Link2Off className="mt-0.5 h-3 w-3 shrink-0" />Breaks: {m.text}</li>)}
            {a.clashes.map(c => <li key={c.a + c.b} className="flex gap-1 text-danger"><CircleAlert className="mt-0.5 h-3 w-3 shrink-0" />New clash {c.a_name} ↔ {c.b_name}: {n1(c.volume_mm3)} mm³{c.was_mm3 > 0 ? ` (was ${n1(c.was_mm3)})` : ""}</li>)}
            {a.refit.map(g => <li key={g.id} className="flex gap-1 text-warning"><Wrench className="mt-0.5 h-3 w-3 shrink-0" />{g.name}: {g.why}</li>)}
            {a.moved.map(m => <li key={m.id} className="flex gap-1 text-muted"><MoveRight className="mt-0.5 h-3 w-3 shrink-0" />{m.name} moves {n1(m.mm)} mm{m.deg > 0.01 ? `, turns ${n1(m.deg)}°` : ""}</li>)}
            {a.mates.filter(m => m.status === "follows").length > 0 && <li className="text-muted">{a.mates.filter(m => m.status === "follows").length} mate reference(s) follow the change</li>}
            {a.resolved.map(c => <li key={c.a_name + c.b_name} className="text-success">Clash {c.a_name} ↔ {c.b_name} goes away</li>)}
            {a.behind > 0 && <li className="text-muted">This assembly still shows an older build of the part; refreshing it also brings earlier changes.</li>}
          </ul>
        </div>))}
      {impact.programs.length > 0 && <p className="flex gap-1 text-muted"><FolderKanban className="mt-0.5 h-3 w-3 shrink-0" />Used in {impact.programs.map(p => p.name).join(", ")} (Design Office)</p>}
      {impact.datasheet.shots > 0 && <p className="flex gap-1 text-muted"><Camera className="mt-0.5 h-3 w-3 shrink-0" />{impact.datasheet.shots} datasheet render{impact.datasheet.shots > 1 ? "s" : ""} will need re-rendering</p>}
    </div>
  );
}

/** In the PropertyManager: shown when OK found problems; the user applies anyway or goes back to change the values. */
export default function ImpactPanel({ impact, busy, onApply, onBack }: { impact: Impact; busy?: boolean; onApply: () => void; onBack: () => void }) {
  return (
    <div className="space-y-2 rounded-lg border border-warning/50 bg-warning/5 p-2.5" data-testid="impact-panel">
      <div className="label">Change impact (checked on a trial rebuild, nothing applied yet)</div>
      <ImpactDetails impact={impact} />
      <div className="flex gap-2 pt-1">
        <Button size="sm" variant="danger" onClick={onApply} loading={busy}>Apply anyway</Button>
        <Button size="sm" variant="secondary" onClick={onBack}>Back</Button>
      </div>
    </div>
  );
}
