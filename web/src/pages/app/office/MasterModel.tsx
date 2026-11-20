import { AlertTriangle, Boxes, CheckCircle2, Route } from "lucide-react";
import { Badge, Card } from "@/components/ui";
import type { Plan } from "./types";

/** How the office will lay the program out (WORKLIST 50): the fast path, or a master model with the reason, and
 *  what was measured from the master. Plain words only. */
export default function LayoutPathCard({ plan }: { plan: Plan }) {
  const lp = plan.layout_path;
  if (!lp || lp.path === "pending") return null;
  const m = plan.master;
  const master = lp.path === "master";
  const errors = m?.errors ?? [];
  const warnings = m?.warnings ?? [];
  return (
    <Card className={master ? "border-primary/40 p-4" : "p-4"} data-layout-path={lp.path}>
      <div className="flex flex-wrap items-center gap-2">
        {master ? <Boxes className="h-4 w-4 text-primary" /> : <Route className="h-4 w-4 text-muted" />}
        <span className="text-[14px] font-semibold">{lp.words}</span>
        {master && m?.ok && <Badge tone="primary">Master model measured</Badge>}
        {lp.state === "fallback" && <Badge tone="warning">Fallback</Badge>}
      </div>
      {master && lp.reasons.length > 0 && <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[12.5px] text-muted">
        {lp.reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul>}
      {!master && lp.fallback && <p className="mt-1.5 text-[12.5px] text-muted">{lp.fallback}</p>}
      {master && m?.ok && m.summary && <p className="mt-2 text-[12.5px]">
        Archie modelled the whole product as {m.summary.bodies} bodies in one coordinate system. Every part is placed where
        its body sits, and the interfaces are measured from it: {m.summary.bolted} bolted joint{m.summary.bolted === 1 ? "" : "s"},
        {" "}{m.summary.faces} seating face{m.summary.faces === 1 ? "" : "s"}{m.summary.fits ? `, ${m.summary.fits} bore fit${m.summary.fits === 1 ? "" : "s"}` : ""}.
      </p>}
      {master && m?.graph?.view && m.graph.view.connections.length > 0 && <div className="mt-2">
        <div className="label mb-1">Measured connections</div>
        <ul className="space-y-0.5 text-[12.5px]">{m.graph.view.connections.map((c, i) => (
          <li key={i} className="flex items-start gap-1.5"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
            <span>{c.text}{c.detail ? <span className="text-muted"> · {c.detail}</span> : null}</span></li>))}</ul>
      </div>}
      {errors.length > 0 && <div className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12.5px]" role="alert">
        <div className="mb-1 flex items-center gap-1.5 font-medium text-danger"><AlertTriangle className="h-4 w-4" />
          The measurement found {errors.length} problem{errors.length === 1 ? "" : "s"} (shown again at the interfaces gate)</div>
        <ul className="list-disc space-y-0.5 pl-5">{errors.slice(0, 6).map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
      {warnings.length > 0 && <div className="mt-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-[12.5px]">
        <ul className="list-disc space-y-0.5 pl-5">{warnings.slice(0, 6).map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
    </Card>
  );
}
