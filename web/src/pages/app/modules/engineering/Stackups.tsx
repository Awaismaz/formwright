import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Minus, Plus, Ruler, Save, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";
import { ago, cx } from "@/lib/format";
import { Sources } from "./CalcForm";
import { type Catalog, type StackRow, type Stackup, type UnitSystem, fmt } from "./types";

type Draft = { id?: string; name: string; description: string; unit: "mm" | "in"; rows: StackRow[]; spec_min: string; spec_max: string };
const blank = (): Draft => ({ name: "", description: "", unit: "mm", spec_min: "", spec_max: "", rows: [
  { name: "Housing depth", dir: "+", nominal: 50, plus: 0.1, minus: 0.1, sens: 1 }, { name: "Part length", dir: "-", nominal: 49.6, plus: 0.05, minus: 0.05, sens: 1 }] });

export default function StackupsPanel({ pid, cat }: { pid: string; cat: Catalog; sys: UnitSystem }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["eng-stack", pid], queryFn: () => api.get<{ items: Stackup[] }>(`/api/m/engineering/projects/${pid}/stackups`) });
  const [d, setD] = useState<Draft | null>(null);
  const [res, setRes] = useState<Stackup | null>(null);
  const [busy, setBusy] = useState(false);
  if (!list.data) return <Spinner />;
  const ro = !cat.can_edit;
  const open = (s: Stackup) => { setD({ id: s.id, name: s.name, description: s.description, unit: s.unit, rows: s.rows, spec_min: s.spec_min === null ? "" : String(s.spec_min), spec_max: s.spec_max === null ? "" : String(s.spec_max) }); setRes(s); };
  const save = async () => {
    if (!d) return;
    setBusy(true);
    const body = { name: d.name || "Stack-up", description: d.description, unit: d.unit, spec_min: d.spec_min === "" ? null : Number(d.spec_min), spec_max: d.spec_max === "" ? null : Number(d.spec_max),
      rows: d.rows.map(r => ({ ...r, nominal: Number(r.nominal), plus: Number(r.plus), minus: Number(r.minus), sens: Number(r.sens) })) };
    try {
      const r = d.id ? await api.patch<Stackup>(`/api/m/engineering/projects/${pid}/stackups/${d.id}`, body) : await api.post<Stackup>(`/api/m/engineering/projects/${pid}/stackups`, body);
      qc.invalidateQueries({ queryKey: ["eng-stack", pid] }); open(r); toast.success("Stack-up saved");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  const del = async () => {
    if (!d?.id) return;
    try { await api.del(`/api/m/engineering/projects/${pid}/stackups/${d.id}`); qc.invalidateQueries({ queryKey: ["eng-stack", pid] }); setD(null); setRes(null); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const setRow = (i: number, p: Partial<StackRow>) => d && setD({ ...d, rows: d.rows.map((r, j) => j === i ? { ...r, ...p } : r) });
  const k = d?.unit === "in" ? 25.4 : 1;
  const val = (key: string) => { const o = res?.result.outputs.find(x => x.key === key); return typeof o?.value === "number" ? o.value / k : null; };
  return (
    <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="space-y-2">
        {!ro && <Button className="w-full" icon={<Plus className="h-4 w-4" />} onClick={() => { setD(blank()); setRes(null); }}>New stack-up</Button>}
        {list.data.items.map(s => (
          <button key={s.id} onClick={() => open(s)} className={cx("w-full rounded-lg border p-3 text-left", d?.id === s.id ? "border-primary bg-primary-soft/60" : "border-border bg-panel hover:bg-panel2")}>
            <div className="truncate text-[13px] font-medium">{s.name}</div>
            <div className="mt-1 text-[11.5px] text-muted">{s.rows.length} dimensions · {ago(s.updated_at)}</div>
          </button>))}
      </aside>
      {d ? (
        <div className="space-y-4">
          <Card className="space-y-3 p-4" data-panel="stackup">
            <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
              <label className="space-y-1"><span className="text-[13px] font-medium">Name</span><input disabled={ro} className="input" value={d.name} onChange={e => setD({ ...d, name: e.target.value })} placeholder="e.g. Lid-to-PCB gap" aria-label="Stack-up name" /></label>
              <label className="space-y-1"><span className="text-[13px] font-medium">Unit</span><select disabled={ro} className="input" value={d.unit} onChange={e => setD({ ...d, unit: e.target.value as "mm" | "in" })}><option value="mm">mm</option><option value="in">in</option></select></label>
            </div>
            <div className="overflow-x-auto rounded border border-border">
              <table className="w-full text-[12.5px]">
                <thead className="bg-panel2 text-left text-[11px] text-muted"><tr>{["Dimension", "Dir.", "Nominal", "+ Tol", "− Tol", "Sensitivity", "Source"].map(h => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}<th /></tr></thead>
                <tbody>{d.rows.map((r, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="p-1"><input disabled={ro} className="input h-8 min-w-[130px] text-[12.5px]" value={r.name} onChange={e => setRow(i, { name: e.target.value })} /></td>
                    <td className="p-1"><select disabled={ro} className="input h-8 w-16 px-1 text-[12.5px]" value={r.dir} onChange={e => setRow(i, { dir: e.target.value as "+" | "-" })}><option value="+">+</option><option value="-">−</option></select></td>
                    {(["nominal", "plus", "minus", "sens"] as const).map(f => <td key={f} className="p-1"><input disabled={ro} inputMode="decimal" className="input h-8 w-24 text-[12.5px] tabular-nums" value={String(r[f])} onChange={e => setRow(i, { [f]: e.target.value } as Partial<StackRow>)} aria-label={f} /></td>)}
                    <td className="p-1"><input disabled={ro} className="input h-8 min-w-[110px] text-[12.5px]" value={r.source ?? ""} onChange={e => setRow(i, { source: e.target.value })} placeholder="drawing / model" /></td>
                    <td className="p-1">{!ro && <button aria-label="Remove dimension" disabled={d.rows.length <= 1} className="rounded p-1 text-muted hover:bg-text/5 disabled:opacity-30" onClick={() => setD({ ...d, rows: d.rows.filter((_, j) => j !== i) })}><Minus className="h-3.5 w-3.5" /></button>}</td>
                  </tr>))}</tbody>
              </table>
              {!ro && <button className="flex w-full items-center justify-center gap-1 border-t border-border py-1.5 text-[12px] text-primary hover:bg-primary-soft" onClick={() => setD({ ...d, rows: [...d.rows, { name: "", dir: "+", nominal: 0, plus: 0.1, minus: 0.1, sens: 1 }] })}><Plus className="h-3.5 w-3.5" />Add dimension</button>}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1"><span className="text-[13px] font-medium">Required minimum ({d.unit})</span><input disabled={ro} inputMode="decimal" className="input" value={d.spec_min} onChange={e => setD({ ...d, spec_min: e.target.value })} placeholder="e.g. 0.1 (minimum gap)" /></label>
              <label className="space-y-1"><span className="text-[13px] font-medium">Allowed maximum ({d.unit})</span><input disabled={ro} inputMode="decimal" className="input" value={d.spec_max} onChange={e => setD({ ...d, spec_max: e.target.value })} /></label>
            </div>
            {!ro && <div className="flex gap-2"><Button icon={<Save className="h-4 w-4" />} loading={busy} onClick={save} data-action="save-stack">Calculate and save</Button>{d.id && <Button variant="ghost" icon={<Trash2 className="h-4 w-4" />} onClick={del}>Delete</Button>}</div>}
          </Card>
          {res && (
            <Card className="space-y-4 p-4" data-panel="stack-result">
              <div className="grid gap-2 sm:grid-cols-3">
                {[["Mean", fmt(val("mean")), ""], ["Worst case", `${fmt(val("wc_min"))} … ${fmt(val("wc_max"))}`, `± ${fmt(val("wc"))}`], ["RSS (statistical)", `${fmt(val("rss_min"))} … ${fmt(val("rss_max"))}`, `± ${fmt(val("rss"))}`]].map(([l, v, s]) => (
                  <div key={l} className="rounded-lg border border-border bg-panel2/60 px-3 py-2"><div className="text-[11px] text-muted">{l}</div><div className="text-[16px] font-semibold tabular-nums">{v} <span className="text-[12px] font-normal text-muted">{d.unit}</span></div>{s && <div className="text-[11.5px] text-muted">{s}</div>}</div>))}
              </div>
              {res.result.checks.length > 0 && <ul className="space-y-1 text-[13px]">{res.result.checks.map(c => <li key={c.label} className="flex items-center gap-2">{c.passed ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-danger" />}{c.label}<span className="text-[11.5px] text-muted">({c.basis})</span></li>)}</ul>}
              <div>
                <div className="label mb-1.5">Contribution to the variation</div>
                {res.result.contributions.map((c, i) => (
                  <div key={i} className="mb-1.5 grid grid-cols-[140px_1fr_90px] items-center gap-2 text-[12px]">
                    <span className="truncate">{c.name || `Dimension ${i + 1}`}</span>
                    <div className="h-2.5 overflow-hidden rounded-full bg-text/10"><div className="h-full rounded-full bg-primary" style={{ width: `${c.pct_rss}%` }} /></div>
                    <span className="text-right tabular-nums text-muted">{fmt(c.pct_rss, 3)} % RSS</span>
                  </div>))}
              </div>
              <div className="flex items-center gap-2"><Badge tone="warning">Preliminary estimate</Badge><span className="text-[11.5px] text-muted">Add the stack-up to a calculation set (Calculators → 1D tolerance stack-up) to have it signed.</span></div>
              <Sources r={res.result} />
            </Card>
          )}
        </div>
      ) : <EmptyState icon={<Ruler className="h-5 w-5" />} title="Tolerance stack-ups" body="1D dimension chains with worst-case and RSS results, the contribution of each tolerance, and a check against the required gap." action={!ro ? <Button icon={<Plus className="h-4 w-4" />} onClick={() => setD(blank())}>New stack-up</Button> : undefined} />}
    </div>
  );
}
