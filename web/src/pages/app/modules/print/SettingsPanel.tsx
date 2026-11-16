import { useState } from "react";
import { ChevronDown, ChevronRight, Info, RotateCcw } from "lucide-react";
import { cx } from "@/lib/format";
import { Badge, Spinner } from "@/components/ui";
import type { Presets, ProcessCode, Settings } from "./types";

const ADV: { key: string; label: string; unit: string; step: number; processes?: ProcessCode[] }[] = [
  { key: "layer_mm", label: "Layer height", unit: "mm", step: 0.01 },
  { key: "min_wall_mm", label: "Minimum wall", unit: "mm", step: 0.1 },
  { key: "warn_wall_mm", label: "Warn below wall", unit: "mm", step: 0.1 },
  { key: "min_hole_mm", label: "Minimum hole Ø", unit: "mm", step: 0.1 },
  { key: "min_pin_mm", label: "Minimum pin Ø", unit: "mm", step: 0.1 },
  { key: "min_gap_mm", label: "Minimum clearance", unit: "mm", step: 0.05 },
  { key: "max_bridge_mm", label: "Maximum bridge", unit: "mm", step: 1, processes: ["fdm"] },
  { key: "nozzle_mm", label: "Nozzle", unit: "mm", step: 0.05, processes: ["fdm"] },
  { key: "infill", label: "Infill", unit: "0–1", step: 0.05, processes: ["fdm"] },
  { key: "flow_mm3_s", label: "Average flow", unit: "mm³/s", step: 0.5, processes: ["fdm"] },
  { key: "layer_overhead_s", label: "Time per layer", unit: "s", step: 0.5 },
];

const TOLS = [0.1, 0.05, 0.02, 0.01];

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="border-b border-border px-4 py-3.5">
      <div className="mb-2.5 flex items-center justify-between"><div className="label">{title}</div>{right}</div>
      <div className="space-y-2.5">{children}</div>
    </div>
  );
}

function Num({ value, onChange, step, min, max, unit, ariaLabel }: { value: number; onChange: (v: number) => void; step: number; min?: number; max?: number; unit: string; ariaLabel: string }) {
  return (
    <div className="relative">
      <input type="number" className={cx("input h-8 text-[13px] tabular-nums", !unit ? "px-2" : unit.length > 2 ? "pr-12" : "pr-6")} value={Number.isFinite(value) ? value : ""} step={step} min={min} max={max} aria-label={ariaLabel}
        onChange={e => { const v = parseFloat(e.target.value); if (Number.isFinite(v)) onChange(v); }} />
      {unit && <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-muted">{unit}</span>}
    </div>
  );
}

export function SettingsPanel({ presets, value, onChange, isProject, onReset, busy }: {
  presets: Presets; value: Settings; onChange: (s: Settings) => void; isProject: boolean; onReset: () => void; busy: boolean;
}) {
  const [adv, setAdv] = useState(false);
  const proc = presets.processes[value.process];
  const set = (p: Partial<Settings>) => onChange({ ...value, ...p });
  const setProcess = (code: ProcessCode) => {
    const s = presets.processes[code];
    onChange({ ...value, process: code, material: s.default_material, overhang_deg: s.overhang_deg,
      printer_mm: [...s.printer_mm] as [number, number, number], overrides: {} });
  };
  const edited = Object.keys(value.overrides).length + (value.overhang_deg !== proc.overhang_deg ? 1 : 0)
    + (value.printer_mm.join() !== proc.printer_mm.join() ? 1 : 0);
  const mat = presets.materials[value.material];

  return (
    <div className="text-[13px]">
      <Section title="Process" right={busy ? <Spinner className="h-3.5 w-3.5" /> : undefined}>
        <div className="grid grid-cols-3 gap-1 rounded-md border border-border bg-panel2 p-0.5" role="radiogroup" aria-label="Process">
          {(Object.keys(presets.processes) as ProcessCode[]).map(code => (
            <button key={code} role="radio" aria-checked={value.process === code} data-process={code} onClick={() => setProcess(code)}
              className={cx("rounded px-2 py-1.5 text-[12px] font-semibold transition", value.process === code ? "bg-panel text-text shadow-sm" : "text-muted hover:text-text")}>
              {code.toUpperCase()}
            </button>
          ))}
        </div>
        <p className="text-[12px] leading-relaxed text-muted">{proc.name}. {proc.note}</p>
        <label className="block space-y-1">
          <span className="text-[12px] font-medium">Material</span>
          <select className="input h-8 text-[13px]" value={value.material} onChange={e => set({ material: e.target.value })} aria-label="Material">
            {proc.materials.map(c => <option key={c} value={c}>{presets.materials[c]?.name ?? c}</option>)}
          </select>
          {mat && <span className="block text-[11px] text-muted">{mat.density_g_cm3} g/cm³ typical{mat.verify ? " (verify with your resin datasheet)" : ""}. Verify with your supplier datasheet.</span>}
        </label>
      </Section>

      <Section title="Printer">
        <div>
          <span className="text-[12px] font-medium">Build volume X × Y × Z (mm)</span>
          <div className="mt-1 grid grid-cols-3 gap-1.5">
            {[0, 1, 2].map(i => <Num key={i} ariaLabel={`Build volume ${"XYZ"[i]}`} value={value.printer_mm[i]!} step={5} min={10} max={3000} unit=""
              onChange={v => { const p = [...value.printer_mm] as [number, number, number]; p[i] = v; set({ printer_mm: p }); }} />)}
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between"><span className="text-[12px] font-medium">Overhang angle</span><span className="tabular-nums text-muted">{value.overhang_deg.toFixed(0)}° from vertical</span></div>
          <input type="range" min={20} max={80} step={1} value={value.overhang_deg} onChange={e => set({ overhang_deg: parseFloat(e.target.value) })} className="mt-1 w-full accent-primary" aria-label="Overhang angle" />
        </div>
        <label className="block space-y-1">
          <span className="text-[12px] font-medium">Main load direction (model axis)</span>
          <select className="input h-8 text-[13px]" value={value.load_dir} onChange={e => set({ load_dir: e.target.value as Settings["load_dir"] })} aria-label="Load direction">
            <option value="">Not specified</option><option value="X">Along model X</option><option value="Y">Along model Y</option><option value="Z">Along model Z</option>
          </select>
        </label>
      </Section>

      {isProject && <Section title="Mesh from exact model">
        <label className="block space-y-1">
          <span className="text-[12px] font-medium">Chordal tolerance</span>
          <select className="input h-8 text-[13px]" value={value.tolerance} onChange={e => set({ tolerance: parseFloat(e.target.value) })} aria-label="Chordal tolerance">
            {TOLS.map(t => <option key={t} value={t}>{t} mm{t === 0.05 ? " (default)" : ""}</option>)}
          </select>
          <span className="block text-[11px] text-muted">Maximum distance between the triangles and the exact surface. The measured deviation is reported with the checks.</span>
        </label>
      </Section>}

      <div className="border-b border-border px-4 py-3">
        <button className="flex w-full items-center justify-between text-left" onClick={() => setAdv(!adv)} aria-expanded={adv}>
          <span className="flex items-center gap-1.5"><span className="label">Process assumptions</span>{edited > 0 && <Badge tone="accent">{edited} edited</Badge>}</span>
          {adv ? <ChevronDown className="h-4 w-4 text-muted" /> : <ChevronRight className="h-4 w-4 text-muted" />}
        </button>
        {adv && <div className="mt-3 space-y-2">
          {ADV.filter(a => !a.processes || a.processes.includes(value.process)).map(a => {
            const def = (proc as unknown as Record<string, number | null>)[a.key];
            if (def === null || def === undefined) return null;
            const cur = value.overrides[a.key] ?? def;
            return (
              <div key={a.key} className="grid grid-cols-[1fr_118px] items-center gap-2">
                <span className={cx("text-[12px]", value.overrides[a.key] !== undefined && "font-semibold text-accent")} title={`Default ${def} ${a.unit}`}>{a.label}</span>
                <Num ariaLabel={a.label} value={cur} step={a.step} unit={a.unit} onChange={v => {
                  const o = { ...value.overrides };
                  if (v === def) delete o[a.key]; else o[a.key] = v;
                  set({ overrides: o });
                }} />
              </div>
            );
          })}
          <button onClick={onReset} className="mt-1 inline-flex items-center gap-1 text-[12px] text-primary hover:underline"><RotateCcw className="h-3.5 w-3.5" />Reset to {value.process.toUpperCase()} defaults</button>
        </div>}
        <p className="mt-2.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-muted"><Info className="mt-0.5 h-3 w-3 shrink-0" />Defaults are assumptions from generic design-rule tables, not your printer's limits. Edit them to match your machine and material.</p>
      </div>
    </div>
  );
}
