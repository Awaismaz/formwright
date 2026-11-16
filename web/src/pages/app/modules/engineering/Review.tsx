import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Calculator, FlaskConical, MapPin } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Badge, Card, EmptyState, Spinner } from "@/components/ui";
import { cx } from "@/lib/format";
import { LevelBadge } from "./CalcForm";
import { type Catalog, type Review, type ReviewItem, SEVERITY_TONE, fmt } from "./types";

const STATUS: Record<string, string> = { open: "Open", in_progress: "In progress", addressed: "Addressed", not_applicable: "Not applicable" };

export default function ReviewPanel({ pid, cat, openCalc }: { pid: string; cat: Catalog; openCalc: (id: string, inputs?: Record<string, unknown>, p?: Record<string, string> | null) => void }) {
  const rv = useQuery({ queryKey: ["eng-review", pid], queryFn: () => api.get<Review>(`/api/m/engineering/projects/${pid}/review`) });
  if (rv.isLoading) return <div className="flex items-center gap-2 text-[13px] text-muted"><Spinner className="h-4 w-4" />Reviewing the geometry…</div>;
  if (!rv.data) return null;
  if (!rv.data.available) return <EmptyState icon={<AlertTriangle className="h-5 w-5" />} title="No model to review" body={rv.data.reason} />;
  const name = (id: string) => cat.calculators.find(c => c.id === id)?.name ?? id;
  const done = rv.data.items.filter(i => ["addressed", "not_applicable"].includes(i.state.status)).length;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="space-y-3">
        <div className="flex items-center gap-2"><h2 className="text-[15px] font-semibold">Failure-mode checklist</h2><LevelBadge level="recommended_check" cat={cat} /><span className="ml-auto text-[12px] text-muted">{done} / {rv.data.items.length} closed</span></div>
        {rv.data.items.map(it => <Item key={it.id} it={it} pid={pid} cat={cat} name={name} openCalc={openCalc} />)}
      </div>
      <div className="space-y-4">
        <Card className="p-4" data-panel="hints">
          <div className="mb-1 flex items-center gap-2"><MapPin className="h-4 w-4 text-accent" /><h3 className="text-[14px] font-semibold">Stress-concentration hints</h3><Badge tone="accent">Heuristic</Badge></div>
          <p className="mb-3 text-[11.5px] text-muted">{rv.data.heuristic_note}</p>
          {!rv.data.hints.length && <p className="text-[12.5px] text-muted">No small fillets at section changes, sharp internal corners or holes near edges were found.</p>}
          <ul className="space-y-2">
            {rv.data.hints.map(h => (
              <li key={h.id} className="rounded-lg border border-border p-2.5 text-[12.5px]" data-hint={h.kind}>
                <div className="flex items-start gap-2"><Badge tone={SEVERITY_TONE[h.severity]}>{h.severity}</Badge><span className="font-medium">{h.title}</span></div>
                <p className="mt-1 text-muted">{h.detail}</p>
                <p className="mt-1">{h.suggestion}</p>
                <div className="mt-1 flex items-center gap-3 text-[11px] text-muted">
                  {h.location && <span>at ({h.location.map(x => fmt(x, 4)).join(", ")}) mm</span>}
                  {h.calc && <button className="text-primary hover:underline" onClick={() => openCalc(h.calc!, h.prefill ? Object.fromEntries(Object.entries(h.prefill).map(([k, v]) => [k, { value: v, unit: "mm" }])) : undefined, h.prefill ? Object.fromEntries(Object.keys(h.prefill).map(k => [k, `From the hint: ${h.title}`])) : null)}>Check with {name(h.calc)} →</button>}
                </div>
              </li>))}
          </ul>
        </Card>
        <Card className="p-4">
          <div className="mb-2 flex items-center gap-2"><FlaskConical className="h-4 w-4 text-primary" /><h3 className="text-[14px] font-semibold">Recommended analyses and tests</h3></div>
          <ul className="space-y-2 text-[12.5px]">
            {rv.data.analyses.map(a => <li key={a.what} className="border-b border-dashed border-border pb-2 last:border-0"><div className="font-medium">{a.what}</div><div className="text-muted">{a.why}</div><div className="mt-0.5 text-[11px] text-muted">For: {a.for.join(", ")}</div></li>)}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function Item({ it, pid, cat, name, openCalc }: { it: ReviewItem; pid: string; cat: Catalog; name: (id: string) => string; openCalc: (id: string) => void }) {
  const qc = useQueryClient();
  const [note, setNote] = useState(it.state.note ?? "");
  const save = async (status: string, n = note) => {
    try { await api.patch(`/api/m/engineering/projects/${pid}/review/items/${it.id}`, { status, note: n }); qc.invalidateQueries({ queryKey: ["eng-review", pid] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const closed = ["addressed", "not_applicable"].includes(it.state.status);
  return (
    <Card className={cx("p-3", closed && "opacity-75")} data-check={it.id}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{it.mode}</div>
          <div className="text-[13.5px] font-medium">{it.title}</div>
          <p className="mt-0.5 text-[12.5px] text-muted">{it.why}</p>
          {it.calculators.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1.5">{it.calculators.map(c => <button key={c} onClick={() => openCalc(c)} className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11.5px] text-primary hover:bg-primary-soft"><Calculator className="h-3 w-3" />{name(c)}</button>)}</div>}
        </div>
        <select aria-label={`Status of ${it.title}`} disabled={!cat.can_edit} className="input h-8 w-36 text-[12.5px]" value={it.state.status} onChange={e => save(e.target.value)}>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {cat.can_edit && <input className="input mt-2 h-8 text-[12px]" value={note} placeholder="Note: how it was addressed (e.g. calculation set name)" onChange={e => setNote(e.target.value)} onBlur={() => note !== (it.state.note ?? "") && save(it.state.status, note)} />}
      {it.state.by && <div className="mt-1 text-[10.5px] text-muted">{STATUS[it.state.status]} · {it.state.by.name}</div>}
    </Card>
  );
}
