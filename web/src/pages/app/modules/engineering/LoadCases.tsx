import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus, Save, Trash2, Weight } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";
import { ago, cx } from "@/lib/format";
import { type Catalog, type Load, type LoadCase, type ModelInfo, type Support, fmt } from "./types";

const KINDS = ["static", "fatigue", "impact", "thermal", "transport", "other"];
const LOAD_TYPES: Record<string, string[]> = { force: ["N", "kN", "lbf", "kip"], moment: ["N*m", "N*mm", "kN*m", "lbf*in", "lbf*ft"], pressure: ["MPa", "kPa", "psi", "bar"], acceleration: ["g", "m/s²"], temperature: ["°C"], displacement: ["mm", "in"] };
const BASIS = ["specified", "measured", "derived", "assumed"];
const SUPPORTS = ["fixed", "pinned", "roller", "bolted", "bearing", "contact", "symmetry", "other"];

type Draft = Omit<LoadCase, "id" | "updated_at" | "updated_by"> & { id?: string };
const blank = (): Draft => ({ name: "", kind: "static", description: "", loads: [{ name: "Load 1", type: "force", value: 0, unit: "N", direction: "", location: "", basis: "assumed", source: "" }], supports: [{ type: "fixed", location: "", note: "" }], cycles: null, temperature_c: null, environment: "", source: "" });

export default function LoadCasesPanel({ pid, cat, model }: { pid: string; cat: Catalog; model: ModelInfo | undefined }) {
  const qc = useQueryClient();
  const lcs = useQuery({ queryKey: ["eng-lc", pid], queryFn: () => api.get<{ items: LoadCase[] }>(`/api/m/engineering/projects/${pid}/loadcases`) });
  const [d, setD] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  if (!lcs.data) return <Spinner />;
  const ro = !cat.can_edit;
  const save = async () => {
    if (!d) return;
    setBusy(true);
    const body = { ...d, id: undefined, cycles: d.cycles === null || (d.cycles as unknown) === "" ? null : Number(d.cycles), temperature_c: d.temperature_c === null || (d.temperature_c as unknown) === "" ? null : Number(d.temperature_c), loads: d.loads.map(l => ({ ...l, value: Number(l.value) })) };
    try {
      const r = d.id ? await api.patch<LoadCase>(`/api/m/engineering/projects/${pid}/loadcases/${d.id}`, body) : await api.post<LoadCase>(`/api/m/engineering/projects/${pid}/loadcases`, body);
      qc.invalidateQueries({ queryKey: ["eng-lc", pid] }); qc.invalidateQueries({ queryKey: ["eng-sets", pid] }); qc.invalidateQueries({ queryKey: ["eng-review", pid] });
      setD({ ...r }); toast.success("Load case saved");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  const del = async (id: string) => {
    try { await api.del(`/api/m/engineering/projects/${pid}/loadcases/${id}`); qc.invalidateQueries({ queryKey: ["eng-lc", pid] }); setD(null); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const w = model?.mass?.weight_N;
  const addWeight = () => d && w && setD({ ...d, loads: [...d.loads, { name: "Self-weight", type: "force", value: Number(w.toPrecision(4)), unit: "N", direction: "−Z (gravity)", location: `CoG ${model?.mass?.com_mm?.map(x => fmt(x, 3)).join(", ")} mm`, basis: "derived", source: `Model mass ${fmt((model?.mass?.mass_kg ?? 0) * 1000)} g × 9.80665 m/s² (${model?.material?.name})` }] });
  const setLoad = (i: number, patch: Partial<Load>) => d && setD({ ...d, loads: d.loads.map((l, j) => j === i ? { ...l, ...patch } : l) });
  const setSup = (i: number, patch: Partial<Support>) => d && setD({ ...d, supports: d.supports.map((l, j) => j === i ? { ...l, ...patch } : l) });
  return (
    <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="space-y-2">
        {!ro && <Button className="w-full" icon={<Plus className="h-4 w-4" />} onClick={() => setD(blank())}>New load case</Button>}
        {lcs.data.items.map(l => (
          <button key={l.id} onClick={() => setD({ ...l })} className={cx("w-full rounded-lg border p-3 text-left", d?.id === l.id ? "border-primary bg-primary-soft/60" : "border-border bg-panel hover:bg-panel2")}>
            <div className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{l.name}</span><Badge>{l.kind}</Badge></div>
            <div className="mt-1 text-[11.5px] text-muted">{l.loads.length} load(s) · {l.supports.length} support(s) · {ago(l.updated_at)}</div>
          </button>))}
        {!lcs.data.items.length && <p className="px-1 text-[12.5px] text-muted">Record the loads, supports and environment each part must survive. Calculation sets link to them, and a sign-off covers their content.</p>}
      </aside>
      {d ? (
        <Card className="space-y-4 p-4" data-panel="load-case">
          <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
            <label className="space-y-1"><span className="text-[13px] font-medium">Name</span><input disabled={ro} className="input" value={d.name} onChange={e => setD({ ...d, name: e.target.value })} placeholder="e.g. Lifting, 2 g shock" aria-label="Load case name" /></label>
            <label className="space-y-1"><span className="text-[13px] font-medium">Type</span><select disabled={ro} className="input" value={d.kind} onChange={e => setD({ ...d, kind: e.target.value })}>{KINDS.map(k => <option key={k}>{k}</option>)}</select></label>
          </div>
          <label className="block space-y-1"><span className="text-[13px] font-medium">Description</span><textarea disabled={ro} className="input min-h-[56px] py-2" value={d.description} onChange={e => setD({ ...d, description: e.target.value })} /></label>
          <div>
            <div className="mb-1.5 flex items-center"><span className="label">Loads</span>{!ro && w && <Button size="sm" variant="ghost" className="ml-auto" icon={<Weight className="h-4 w-4" />} onClick={addWeight}>Add self-weight from model ({fmt(w)} N)</Button>}</div>
            <div className="overflow-x-auto rounded border border-border">
              <table className="w-full text-[12.5px]">
                <thead className="bg-panel2 text-left text-[11px] text-muted"><tr>{["Name", "Type", "Value", "Unit", "Direction", "Location / feature", "Basis", "Source"].map(h => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}<th /></tr></thead>
                <tbody>{d.loads.map((l, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="p-1"><input disabled={ro} className="input h-8 min-w-[100px] text-[12.5px]" value={l.name} onChange={e => setLoad(i, { name: e.target.value })} /></td>
                    <td className="p-1"><select disabled={ro} className="input h-8 px-1 text-[12.5px]" value={l.type} onChange={e => setLoad(i, { type: e.target.value, unit: LOAD_TYPES[e.target.value]![0]! })}>{Object.keys(LOAD_TYPES).map(k => <option key={k}>{k}</option>)}</select></td>
                    <td className="p-1"><input disabled={ro} inputMode="decimal" className="input h-8 w-24 text-[12.5px] tabular-nums" value={String(l.value)} onChange={e => setLoad(i, { value: e.target.value as unknown as number })} aria-label="Load value" /></td>
                    <td className="p-1"><select disabled={ro} className="input h-8 px-1 text-[12.5px]" value={l.unit} onChange={e => setLoad(i, { unit: e.target.value })}>{LOAD_TYPES[l.type]!.map(u => <option key={u} value={u}>{u.replace("*", "·")}</option>)}</select></td>
                    <td className="p-1"><input disabled={ro} className="input h-8 min-w-[80px] text-[12.5px]" value={l.direction} onChange={e => setLoad(i, { direction: e.target.value })} placeholder="−Z" /></td>
                    <td className="p-1"><input disabled={ro} className="input h-8 min-w-[120px] text-[12.5px]" value={l.location} onChange={e => setLoad(i, { location: e.target.value })} placeholder="e.g. 4 × Ø6.6 holes" /></td>
                    <td className="p-1"><select disabled={ro} className="input h-8 min-w-[104px] px-1 text-[12.5px]" value={l.basis} onChange={e => setLoad(i, { basis: e.target.value })}>{BASIS.map(b => <option key={b}>{b}</option>)}</select></td>
                    <td className="p-1"><input disabled={ro} className="input h-8 min-w-[120px] text-[12.5px]" value={l.source} onChange={e => setLoad(i, { source: e.target.value })} placeholder="spec, measurement, estimate" /></td>
                    <td className="p-1">{!ro && <button aria-label="Remove load" className="rounded p-1 text-muted hover:bg-text/5" onClick={() => setD({ ...d, loads: d.loads.filter((_, j) => j !== i) })}><Minus className="h-3.5 w-3.5" /></button>}</td>
                  </tr>))}</tbody>
              </table>
              {!ro && <button className="flex w-full items-center justify-center gap-1 border-t border-border py-1.5 text-[12px] text-primary hover:bg-primary-soft" onClick={() => setD({ ...d, loads: [...d.loads, { ...blank().loads[0]!, name: `Load ${d.loads.length + 1}` }] })}><Plus className="h-3.5 w-3.5" />Add load</button>}
            </div>
            <p className="mt-1 text-[11px] text-muted">Basis says where a value comes from: <b>specified</b> (requirement), <b>measured</b>, <b>derived</b> (computed, e.g. from mass) or <b>assumed</b>. Assumed values should be confirmed before sign-off.</p>
          </div>
          <div>
            <div className="mb-1.5 label">Supports / boundary conditions</div>
            {d.supports.map((s, i) => (
              <div key={i} className="mb-1.5 flex gap-1.5">
                <select disabled={ro} className="input h-8 w-32 px-1 text-[12.5px]" value={s.type} onChange={e => setSup(i, { type: e.target.value })}>{SUPPORTS.map(x => <option key={x}>{x}</option>)}</select>
                <input disabled={ro} className="input h-8 text-[12.5px]" value={s.location} onChange={e => setSup(i, { location: e.target.value })} placeholder="Where (face, holes, feature)" />
                <input disabled={ro} className="input h-8 text-[12.5px]" value={s.note} onChange={e => setSup(i, { note: e.target.value })} placeholder="Note" />
                {!ro && <button aria-label="Remove support" className="rounded p-1 text-muted hover:bg-text/5" onClick={() => setD({ ...d, supports: d.supports.filter((_, j) => j !== i) })}><Minus className="h-3.5 w-3.5" /></button>}
              </div>))}
            {!ro && <button className="text-[12px] text-primary" onClick={() => setD({ ...d, supports: [...d.supports, { type: "fixed", location: "", note: "" }] })}>+ Add support</button>}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1"><span className="text-[13px] font-medium">Cycles (fatigue)</span><input disabled={ro} inputMode="numeric" className="input" value={d.cycles ?? ""} onChange={e => setD({ ...d, cycles: e.target.value as unknown as number })} placeholder="e.g. 1e7" /></label>
            <label className="space-y-1"><span className="text-[13px] font-medium">Temperature (°C)</span><input disabled={ro} inputMode="decimal" className="input" value={d.temperature_c ?? ""} onChange={e => setD({ ...d, temperature_c: e.target.value as unknown as number })} /></label>
            <label className="space-y-1"><span className="text-[13px] font-medium">Environment</span><input disabled={ro} className="input" value={d.environment} onChange={e => setD({ ...d, environment: e.target.value })} placeholder="indoor, salt spray…" /></label>
          </div>
          <label className="block space-y-1"><span className="text-[13px] font-medium">Source of this load case</span><input disabled={ro} className="input" value={d.source} onChange={e => setD({ ...d, source: e.target.value })} placeholder="Requirement document, customer spec, design standard" /></label>
          {!ro && <div className="flex gap-2"><Button icon={<Save className="h-4 w-4" />} loading={busy} disabled={!d.name.trim()} onClick={save} data-action="save-lc">Save load case</Button>{d.id && <Button variant="ghost" icon={<Trash2 className="h-4 w-4" />} onClick={() => del(d.id!)}>Delete</Button>}</div>}
          {d.id && <p className="text-[11.5px] text-muted">Editing a load case linked to a signed calculation set invalidates that signature.</p>}
        </Card>
      ) : <EmptyState icon={<Weight className="h-5 w-5" />} title="Load cases" body="A structured record of loads, supports, cycles and environment for this part (with where each value comes from)." action={!ro ? <Button icon={<Plus className="h-4 w-4" />} onClick={() => setD(blank())}>New load case</Button> : undefined} />}
    </div>
  );
}
