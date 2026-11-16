import { useEffect, useState, type ReactNode } from "react";
import { Plus, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Modal } from "@/components/ui";
import type { Machine, MatInfo, ShopProfile, ShopResp } from "./types";

const KINDS: { v: Machine["kind"]; l: string }[] = [
  { v: "mill3", l: "3-axis mill" }, { v: "mill5", l: "5-axis mill" }, { v: "lathe", l: "Lathe" },
  { v: "printer_fdm", l: "FDM printer" }, { v: "printer_sla", l: "SLA printer" }, { v: "printer_sls", l: "SLS printer" },
];
const CLASSES: [string, string][] = [["aluminium", "Aluminium"], ["steel", "Steel"], ["stainless", "Stainless"],
  ["cast_iron", "Cast iron"], ["titanium", "Titanium"], ["copper", "Copper alloys"], ["plastic", "Plastics"]];

function Num({ label, unit, value, onChange, step = 0.1, disabled, hint }: {
  label: string; unit?: string; value: number | null | undefined; onChange: (v: number) => void; step?: number;
  disabled?: boolean; hint?: string;
}) {
  return (
    <label className="block" title={hint}>
      <span className="text-[11.5px] text-muted">{label}</span>
      <div className="relative mt-0.5">
        <input type="number" step={step} disabled={disabled} value={value ?? ""} onChange={e => onChange(Number(e.target.value))}
          className="input h-8 pr-12 text-[13px] tabular-nums disabled:opacity-60" />
        {unit && <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-muted">{unit}</span>}
      </div>
    </label>
  );
}

function Section({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <section className="mb-5">
      <div className="label mb-2">{title}</div>
      {note && <p className="-mt-1 mb-2 text-[11.5px] text-muted">{note}</p>}
      {children}
    </section>
  );
}

export default function ShopProfileDialog({ open, onOpenChange, shop, materials, onSaved }: {
  open: boolean; onOpenChange: (v: boolean) => void; shop: ShopResp | undefined; materials: MatInfo[];
  onSaved: (s: ShopResp) => void;
}) {
  const [p, setP] = useState<ShopProfile | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { if (open && shop) setP(structuredClone(shop.profile)); }, [open, shop]);
  if (!shop || !p) return null;
  const ro = !shop.can_edit;
  const set = <K extends keyof ShopProfile>(k: K, v: ShopProfile[K]) => setP({ ...p, [k]: v });
  const setM = (i: number, m: Partial<Machine>) => set("machines", p.machines.map((x, j) => (j === i ? { ...x, ...m } : x)));
  const cur = p.currency;

  const save = async () => {
    setBusy("save");
    try { const r = await api.post<ShopResp>("/api/m/manufacturing/shop-profile", p); onSaved(r); toast.success("Shop profile saved. Re-analysing with your values."); onOpenChange(false); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); }
    finally { setBusy(null); }
  };
  const reset = async () => {
    setBusy("reset");
    try { const r = await api.del<ShopResp>("/api/m/manufacturing/shop-profile"); onSaved(r); setP(structuredClone(r.profile)); toast.success("Shop profile reset to the default assumptions"); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not reset"); }
    finally { setBusy(null); }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} wide
      title={<span className="flex items-center gap-2">Shop profile {shop.is_default && <Badge tone="warning">Assumed defaults</Badge>}</span>}
      description="DFM limits and the cost estimate are checked against these values. They're shared by everyone in this workspace."
      footer={<>
        {!ro && <Button variant="ghost" icon={<RotateCcw className="h-4 w-4" />} loading={busy === "reset"} onClick={reset} className="mr-auto">Reset to defaults</Button>}
        <Button variant="secondary" onClick={() => onOpenChange(false)}>{ro ? "Close" : "Cancel"}</Button>
        {!ro && <Button loading={busy === "save"} onClick={save}>Save profile</Button>}
      </>}>
      {shop.is_default && <p className="mb-4 rounded border border-warning/30 bg-warning/5 px-3 py-2 text-[12px] text-text">{shop.note}</p>}
      {ro && <p className="mb-4 rounded border border-border bg-panel2 px-3 py-2 text-[12px] text-muted">You have view access. Ask an engineer or admin to change the shop profile.</p>}
      <fieldset disabled={ro}>
        <Section title="General">
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <label className="block"><span className="text-[11.5px] text-muted">Shop name</span>
              <input className="input mt-0.5 h-8 text-[13px]" value={p.name} onChange={e => set("name", e.target.value)} /></label>
            <label className="block"><span className="text-[11.5px] text-muted">Currency</span>
              <input className="input mt-0.5 h-8 text-[13px]" value={p.currency} maxLength={8} onChange={e => set("currency", e.target.value)} /></label>
          </div>
        </Section>

        <Section title="Machines" note="Mills: X × Y × Z travel. Lathes: max turning Ø and length. Printers: build volume.">
          <div className="overflow-x-auto rounded border border-border">
            <table className="w-full text-[12px]">
              <thead className="bg-panel2 text-muted"><tr>
                <th className="px-2 py-1.5 text-left font-medium">Name</th><th className="px-2 py-1.5 text-left font-medium">Type</th>
                <th className="px-2 py-1.5 text-left font-medium">Capacity (mm)</th><th className="px-2 py-1.5 text-left font-medium">Rate / h</th><th /></tr></thead>
              <tbody>
                {p.machines.map((m, i) => (
                  <tr key={i} className="border-t border-border align-top">
                    <td className="px-2 py-1.5"><input className="input h-7 text-[12px]" value={m.name} onChange={e => setM(i, { name: e.target.value })} /></td>
                    <td className="px-2 py-1.5"><select className="input h-7 w-32 text-[12px]" value={m.kind}
                      onChange={e => { const k = e.target.value as Machine["kind"]; setM(i, k === "lathe" ? { kind: k, travel_mm: null, max_diameter_mm: m.max_diameter_mm ?? 200, max_length_mm: m.max_length_mm ?? 400 } : { kind: k, travel_mm: m.travel_mm ?? [300, 200, 200], max_diameter_mm: null, max_length_mm: null }); }}>
                      {KINDS.map(k => <option key={k.v} value={k.v}>{k.l}</option>)}</select></td>
                    <td className="px-2 py-1.5">
                      {m.kind === "lathe"
                        ? <div className="flex items-center gap-1"><span className="text-muted">Ø</span><input type="number" className="input h-7 w-16 px-1.5 text-[12px]" value={m.max_diameter_mm ?? ""} onChange={e => setM(i, { max_diameter_mm: Number(e.target.value) })} />
                          <span className="text-muted">×</span><input type="number" className="input h-7 w-16 px-1.5 text-[12px]" value={m.max_length_mm ?? ""} onChange={e => setM(i, { max_length_mm: Number(e.target.value) })} /></div>
                        : <div className="flex items-center gap-1">{[0, 1, 2].map(k => <span key={k} className="flex items-center gap-1">{k > 0 && <span className="text-muted">×</span>}
                          <input type="number" className="input h-7 w-14 px-1.5 text-[12px]" value={m.travel_mm?.[k] ?? ""} onChange={e => { const t = [...(m.travel_mm ?? [0, 0, 0])]; t[k] = Number(e.target.value); setM(i, { travel_mm: t }); }} /></span>)}</div>}
                    </td>
                    <td className="px-2 py-1.5"><input type="number" className="input h-7 w-20 text-[12px]" value={m.rate_per_hour} onChange={e => setM(i, { rate_per_hour: Number(e.target.value) })} /></td>
                    <td className="px-1 py-1.5">{!ro && <button aria-label={`Remove ${m.name}`} onClick={() => set("machines", p.machines.filter((_, j) => j !== i))} className="rounded p-1 text-muted hover:bg-danger/10 hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
          {!ro && <Button size="sm" variant="ghost" className="mt-1.5" icon={<Plus className="h-3.5 w-3.5" />}
            onClick={() => set("machines", [...p.machines, { name: "New machine", kind: "mill3", travel_mm: [500, 400, 400], rate_per_hour: 70 }])}>Add machine</Button>}
        </Section>

        <Section title="Tooling and DFM limits">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Num label="Smallest end mill Ø" unit="mm" value={p.smallest_tool_d_mm} onChange={v => set("smallest_tool_d_mm", v)} hint="Internal corner radii and slot widths are checked against this tool" />
            <Num label="Tool reach" unit="mm" value={p.max_tool_reach_mm} step={1} onChange={v => set("max_tool_reach_mm", v)} />
            <Num label="Flank (flute) length" unit="mm" step={1} value={p.max_flank_mm} onChange={v => set("max_flank_mm", v)} />
            <Num label="Min. draft" unit="°" value={p.min_draft_deg} onChange={v => set("min_draft_deg", v)} />
            <Num label="Drill L/D, standard" unit="× D" value={p.max_drill_ld} onChange={v => set("max_drill_ld", v)} />
            <Num label="Drill L/D, maximum" unit="× D" value={p.deep_drill_ld} onChange={v => set("deep_drill_ld", v)} />
            <Num label="Min. wall, metal" unit="mm" value={p.min_wall_metal_mm} onChange={v => set("min_wall_metal_mm", v)} />
            <Num label="Min. wall, plastic" unit="mm" value={p.min_wall_plastic_mm} onChange={v => set("min_wall_plastic_mm", v)} />
          </div>
        </Section>

        <Section title="Time and rate assumptions" note="Roughing removal rates by material class. They vary 3-5× with machine, tooling and strategy.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {CLASSES.map(([k, l]) => <Num key={k} label={l} unit="cm³/min" step={1} value={p.mrr_cm3_min[k]} onChange={v => set("mrr_cm3_min", { ...p.mrr_cm3_min, [k]: v })} />)}
            <Num label="Turning rate factor" unit="×" value={p.turning_mrr_factor} onChange={v => set("turning_mrr_factor", v)} />
            <Num label="Setup per setup" unit="min" step={5} value={p.setup_minutes} onChange={v => set("setup_minutes", v)} />
            <Num label="Programming per batch" unit="min" step={5} value={p.programming_minutes} onChange={v => set("programming_minutes", v)} />
            <Num label="Finishing rate" unit="cm²/min" step={1} value={p.finish_cm2_min} onChange={v => set("finish_cm2_min", v)} />
            <Num label="Per drilled hole" unit="min" value={p.minutes_per_hole} onChange={v => set("minutes_per_hole", v)} />
          </div>
        </Section>

        <Section title="Tooling for casting and moulding">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Num label="Injection mould" unit={cur} step={500} value={p.mould_tooling_cost} onChange={v => set("mould_tooling_cost", v)} />
            <Num label="Moulding cycle" unit="s" step={1} value={p.mould_cycle_s} onChange={v => set("mould_cycle_s", v)} />
            <Num label="Moulding machine" unit={`${cur}/h`} step={1} value={p.moulding_rate_per_hour} onChange={v => set("moulding_rate_per_hour", v)} />
            <Num label="Casting pattern / die" unit={cur} step={500} value={p.casting_tooling_cost} onChange={v => set("casting_tooling_cost", v)} />
          </div>
        </Section>

        <Section title="Material prices" note="Library prices are placeholders for relative comparison, not market data. Enter your own to override.">
          <div className="grid max-h-56 grid-cols-1 gap-x-4 gap-y-1.5 overflow-y-auto pr-1 sm:grid-cols-2">
            {materials.map(m => {
              const own = p.material_price_per_kg[m.code];
              return (
                <div key={m.code} className="flex items-center gap-2 text-[12px]">
                  <span className="min-w-0 flex-1 truncate" title={m.name}>{m.name}</span>
                  <input type="number" step={0.5} placeholder={`${m.price_per_kg}`} value={own ?? ""}
                    onChange={e => { const n = { ...p.material_price_per_kg }; if (e.target.value === "") delete n[m.code]; else n[m.code] = Number(e.target.value); set("material_price_per_kg", n); }}
                    className="input h-7 w-24 text-right text-[12px] tabular-nums" aria-label={`${m.name} price per kg`} />
                  <span className="w-12 text-[11px] text-muted">{cur}/kg</span>
                </div>);
            })}
          </div>
        </Section>
      </fieldset>
    </Modal>
  );
}
