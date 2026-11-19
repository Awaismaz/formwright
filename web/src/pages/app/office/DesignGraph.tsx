import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { HelpCircle, Link2, Network } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Card } from "@/components/ui";
import { BASE } from "./api";
import type { PlanGraph, Program } from "./types";

const SOURCE_TONE: Record<string, string> = {
  "from the brief": "text-text", "your answer": "text-primary", standard: "text-success",
  "design rule": "text-muted", assumed: "text-warning", "laid out": "text-muted", "from the plan": "text-muted",
};

/** Archie's clarifying questions (at most three): click an option, then apply. Nothing is approved until answered. */
export function GraphQuestions({ program, graph }: { program: Program; graph: PlanGraph }) {
  const qc = useQueryClient();
  const qs = graph.questions ?? [];
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  if (!qs.length) return null;
  const canEdit = program.can_edit !== false;
  const send = async (answers: Record<string, string>) => {
    setBusy(true);
    try {
      await api.post(`${BASE}/programs/${program.id}/plan/answers`, { answers });
      toast.success("Answers applied: the plan is updated.");
      setPicked({});
      qc.invalidateQueries({ queryKey: ["office-program", program.id] });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not apply the answers"); } finally { setBusy(false); }
  };
  const defaults = Object.fromEntries(qs.map(q => [q.id, q.default ?? q.options[0] ?? ""]));
  return (
    <Card className="border-primary/40 p-4" data-graph-questions>
      <div className="mb-2 flex items-center gap-2 text-[14px] font-semibold"><HelpCircle className="h-4 w-4 text-primary" />
        Archie needs {qs.length === 1 ? "one answer" : `${qs.length} answers`} before you approve</div>
      <div className="space-y-3">{qs.map(q => (
        <div key={q.id}>
          <div className="text-[13px] font-medium">{q.question}</div>
          {q.why && <div className="text-[11.5px] text-muted">{q.why}</div>}
          <div className="mt-1.5 flex flex-wrap gap-1.5">{q.options.map(o => {
            const on = (picked[q.id] ?? null) === o;
            return <button key={o} type="button" disabled={!canEdit || busy} onClick={() => setPicked(p => ({ ...p, [q.id]: o }))}
              className={cx("rounded-full border px-2.5 py-1 text-[12px] transition-colors", on ? "border-primary bg-primary text-white" : "border-border hover:border-primary/60")}>
              {o}{o === q.default ? <span className={cx("ml-1 text-[10.5px]", on ? "text-white/80" : "text-muted")}>(default)</span> : null}</button>;
          })}</div>
        </div>))}</div>
      {canEdit && <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" loading={busy} disabled={busy || !Object.keys(picked).length} onClick={() => send(picked)}>Apply my answers</Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => send(defaults)}>Take Archie's defaults</Button>
      </div>}
    </Card>
  );
}

/** The design graph behind the plan as a compact, readable list: parts with their key sizes (and where each size came
 *  from) and the connections between them. */
export default function DesignGraphCard({ graph }: { graph: PlanGraph }) {
  const v = graph.view;
  const [open, setOpen] = useState(true);
  if (!v) return null;
  const check = graph.check ?? [];
  return (
    <Card className="p-4" data-design-graph>
      <button type="button" className="flex w-full items-center gap-2 text-left" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <Network className="h-4 w-4 text-primary" />
        <span className="text-[14px] font-semibold">Design</span>
        <span className="text-[12px] text-muted">{v.components.length} part{v.components.length === 1 ? "" : "s"} · {v.connections.length} connection{v.connections.length === 1 ? "" : "s"}</span>
        {check.length === 0 ? <Badge tone="success" className="ml-auto">Layout matches</Badge> : <Badge tone="warning" className="ml-auto">Layout differs in {check.length} place{check.length === 1 ? "" : "s"}</Badge>}
      </button>
      {open && <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div>
          <div className="label mb-1">Parts</div>
          <ul className="space-y-1.5">{v.components.map((c, i) => (
            <li key={i} className="text-[12.5px]">
              <div className="flex flex-wrap items-baseline gap-1.5">
                <b>{c.qty > 1 ? `${c.qty} × ` : ""}{c.name}</b>
                {c.standard && <span className="text-[11px] text-muted">{c.standard}</span>}
                {c.material && <span className="text-[11px] text-primary">{c.material}</span>}
                {c.added && <Badge tone="neutral">added</Badge>}
              </div>
              {c.params.length > 0 && <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11.5px]">{c.params.map((p, j) => (
                <span key={j} className={SOURCE_TONE[p.source] ?? "text-muted"} title={`${p.source}${p.note ? `: ${p.note}` : ""}`}>{p.text}</span>))}</div>}
            </li>))}</ul>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-muted">
            <span className="text-text">from the brief</span><span className="text-success">standard</span>
            <span className="text-warning">assumed</span><span>design rule</span></div>
        </div>
        <div>
          <div className="label mb-1">Connections</div>
          {v.connections.length === 0 ? <p className="text-[12px] text-muted">None.</p> :
            <ul className="space-y-1.5">{v.connections.map((x, i) => (
              <li key={i} className="flex gap-1.5 text-[12.5px]" title={x.placement}>
                <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
                <div><div>{x.text}</div><div className="text-[11.5px] text-muted">{x.kind}{x.detail ? ` · ${x.detail}` : ""}</div></div>
              </li>))}</ul>}
          {v.constraints.excluded.length > 0 && <p className="mt-2 text-[11.5px] text-muted">Ruled out by the brief: {v.constraints.excluded.join(", ")}.</p>}
          {check.length > 0 && <ul className="mt-2 list-disc pl-4 text-[11.5px] text-warning">{check.map((c, i) => <li key={i}>{c}</li>)}</ul>}
          {(graph.limits ?? []).length > 0 && <div className="mt-2 text-[11.5px] text-muted"><span className="font-medium">Not laid out yet:</span>
            <ul className="list-disc pl-4">{graph.limits!.map((c, i) => <li key={i}>{c}</li>)}</ul></div>}
        </div>
      </div>}
    </Card>
  );
}
