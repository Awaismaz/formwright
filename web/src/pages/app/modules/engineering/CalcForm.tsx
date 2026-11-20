import { Fragment, useMemo, useState } from "react";
import { AlertTriangle, BookOpen, CheckCircle2, ChevronDown, ChevronRight, CircleSlash, Info, Minus, Plus, Sigma, XCircle } from "lucide-react";
import { Badge } from "@/components/ui";
import { cx } from "@/lib/format";
import { type CalcResult, type CalcSchema, type Catalog, type Column, type FormState, type FormVal, type Param, type UnitSystem, display, fmt, isUnitKind, LEVEL_TONE, UNITLESS, visible } from "./types";

/* ------------------------------------------------------------------ advice level badge (ENG-007) */
export function LevelBadge({ level, cat, className, label, selfCheck }: { level: string; cat: Catalog; className?: string; label?: string; selfCheck?: boolean }) {
  const l = cat.levels[level];
  const text = label ?? l?.label ?? level;
  if (level === "verified_calculation" && selfCheck) {  // signed by an author of the set: amber outline, said in the badge itself
    return <span title={`${l?.meaning ?? ""} The signer also authored calculations in this set (self-checked), so it is not an independent check.`} className={className}>
      <span className="inline-flex items-center gap-1 rounded-full border border-warning/70 px-2 py-0.5 text-[11px] font-medium text-warning"><Sigma className="h-3 w-3" />{text}</span></span>;
  }
  return <span title={l?.meaning} className={className}><Badge tone={LEVEL_TONE[level] ?? "neutral"}><Sigma className="h-3 w-3" />{text}</Badge></span>;
}

/** A load from the project's load cases that can fill a calculator input of the same kind. */
export interface LoadOption { label: string; kind: "force" | "moment"; value: number; unit: string }

/* ------------------------------------------------------------------ schema-driven input form */
function UnitInput({ value, onChange, units, disabled, label }: { value: { value: string; unit: string }; onChange: (v: { value: string; unit: string }) => void; units: { unit: string; label: string }[]; disabled?: boolean; label: string }) {
  return (
    <div className="flex">
      <input aria-label={label} inputMode="decimal" disabled={disabled} className="input h-8 rounded-r-none text-[13px] tabular-nums" value={value.value}
        onChange={e => onChange({ ...value, value: e.target.value })} />
      {units.length > 1 ? (
        <select aria-label={`${label} unit`} disabled={disabled} className="h-8 rounded-r border border-l-0 border-border bg-panel2 px-1.5 text-[12px] text-muted" value={value.unit}
          onChange={e => onChange({ ...value, unit: e.target.value })}>
          {units.map(u => <option key={u.unit} value={u.unit}>{u.label}</option>)}
        </select>
      ) : <span className="inline-flex h-8 min-w-[42px] items-center justify-center rounded-r border border-l-0 border-border bg-panel2 px-2 text-[12px] text-muted">{units[0]?.label || "-"}</span>}
    </div>
  );
}

function TableInput({ p, rows, onChange, disabled }: { p: Param; rows: Record<string, unknown>[]; onChange: (r: Record<string, unknown>[]) => void; disabled?: boolean }) {
  const cols = p.columns ?? [];
  const blank = () => Object.fromEntries(cols.map(c => [c.key, c.kind === "text" || c.kind === "enum" ? (c.default ?? "") : (c.kind === "ratio" || c.kind === "count") ? String(c.default ?? "") : { value: String(c.default ?? ""), unit: c.unit }]));
  const set = (i: number, k: string, v: unknown) => onChange(rows.map((r, j) => j === i ? { ...r, [k]: v } : r));
  const cell = (c: Column, r: Record<string, unknown>, i: number) => {
    const v = r[c.key];
    if (c.kind === "enum") return <select disabled={disabled} aria-label={c.label} className="input h-8 px-1.5 text-[12.5px]" value={String(v ?? "")} onChange={e => set(i, c.key, e.target.value)}>{c.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>;
    if (c.kind === "text") return <input disabled={disabled} aria-label={c.label} className="input h-8 px-2 text-[12.5px]" value={String(v ?? "")} onChange={e => set(i, c.key, e.target.value)} />;
    if (c.kind === "ratio" || c.kind === "count") return <input disabled={disabled} aria-label={c.label} inputMode="decimal" className="input h-8 px-2 text-[12.5px] tabular-nums" value={String(v ?? "")} onChange={e => set(i, c.key, e.target.value)} />;
    return <UnitInput label={c.label} disabled={disabled} value={(v as { value: string; unit: string }) ?? { value: "", unit: c.unit }} units={c.units ?? []} onChange={x => set(i, c.key, x)} />;
  };
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="w-full text-[12.5px]">
        <thead className="bg-panel2 text-left text-[11px] text-muted"><tr>{cols.map(c => <th key={c.key} className="px-2 py-1.5 font-medium">{c.label}</th>)}<th className="w-8" /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border">
              {cols.map(c => <td key={c.key} className={cx("px-1.5 py-1", isUnitKind(c.kind) && !UNITLESS.has(c.kind) ? "min-w-[150px]" : c.kind === "text" ? "min-w-[110px]" : "min-w-[80px]")}>{cell(c, r, i)}</td>)}
              <td className="px-1"><button type="button" disabled={disabled || rows.length <= 1} aria-label="Remove row" className="rounded p-1 text-muted hover:bg-text/5 disabled:opacity-30" onClick={() => onChange(rows.filter((_, j) => j !== i))}><Minus className="h-3.5 w-3.5" /></button></td>
            </tr>))}
        </tbody>
      </table>
      {!disabled && <button type="button" className="flex w-full items-center justify-center gap-1 border-t border-border py-1.5 text-[12px] text-primary hover:bg-primary-soft" onClick={() => onChange([...rows, blank()])}><Plus className="h-3.5 w-3.5" />Add row</button>}
    </div>
  );
}

export function CalcForm({ calc, form, setForm, prov, disabled, examples = [], onConfirm, loads = [], onLoadPick }: {
  calc: CalcSchema; form: FormState; setForm: (f: FormState) => void; prov?: Record<string, string> | null; disabled?: boolean;
  /** load inputs still at their textbook example value and not confirmed by the user */
  examples?: string[]; onConfirm?: (key: string) => void;
  loads?: LoadOption[]; onLoadPick?: (key: string, l: LoadOption) => void;
}) {
  const groups = useMemo(() => {
    const g: [string, Param[]][] = [];
    for (const p of calc.inputs) {
      let e = g.find(x => x[0] === p.group);
      if (!e) { e = [p.group, []]; g.push(e); }
      e[1].push(p);
    }
    return g;
  }, [calc]);
  const set = (k: string, v: FormVal) => setForm({ ...form, [k]: v });
  return (
    <div className="space-y-4">
      {groups.map(([name, params]) => {
        const shown = params.filter(p => visible(p, form));
        if (!shown.length) return null;
        return (
          <fieldset key={name} className={cx("rounded-lg border p-3", name === "Safety factor" ? "border-accent/40 bg-accent/5" : "border-border")}>
            <legend className="label px-1">{name}</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {shown.map(p => {
                const v = form[p.key];
                const from = prov?.[p.key];
                const wide = p.kind === "table" || p.kind === "text";
                const example = examples.includes(p.key);
                const lcOpts = loads.filter(l => l.kind === p.kind);
                return (
                  <div key={p.key} className={cx("space-y-1", wide && "sm:col-span-2")}>
                    <div className="flex items-center gap-1.5 text-[12.5px] font-medium">
                      <span>{p.label}{!p.optional && p.kind !== "bool" && <span className="text-danger" title="Required"> *</span>}</span>
                      {p.help && <span title={p.help} className="cursor-help text-muted"><Info className="h-3 w-3" /></span>}
                      {from && <Badge tone="primary" className="ml-auto !py-0 !text-[10px]">{from.startsWith("Load case") ? "from load case" : "from model"}</Badge>}
                      {!from && lcOpts.length > 0 && onLoadPick && !disabled && (
                        <select aria-label={`${p.label} from a load case`} className="ml-auto h-5 max-w-[150px] rounded border border-border bg-panel px-1 text-[10.5px] text-muted" value=""
                          onChange={e => { const l = lcOpts[Number(e.target.value)]; if (l) onLoadPick(p.key, l); }}>
                          <option value="">Use a load case…</option>
                          {lcOpts.map((l, i) => <option key={i} value={i}>{l.label}</option>)}
                        </select>)}
                    </div>
                    {p.kind === "enum" ? (
                      <select disabled={disabled} aria-label={p.label} className="input h-8 text-[13px]" value={String(v)} onChange={e => set(p.key, e.target.value)}>
                        {p.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    ) : p.kind === "bool" ? (
                      <label className="flex h-8 items-center gap-2 text-[13px]"><input disabled={disabled} type="checkbox" checked={Boolean(v)} onChange={e => set(p.key, e.target.checked)} className="h-4 w-4 accent-[rgb(var(--primary))]" />Yes</label>
                    ) : p.kind === "text" ? (
                      <input disabled={disabled} aria-label={p.label} className={cx("input h-8 text-[13px]", p.key === "sf_source" && !String(v).trim() && "border-accent")} value={String(v)} placeholder={p.key === "sf_source" ? "e.g. Customer spec CS-12 §4.2, or company standard ES-001" : ""} onChange={e => set(p.key, e.target.value)} />
                    ) : p.kind === "table" ? (
                      <TableInput p={p} rows={v as Record<string, unknown>[]} disabled={disabled} onChange={r => set(p.key, r)} />
                    ) : typeof v === "string" ? (
                      <input disabled={disabled} aria-label={p.label} inputMode="decimal" className="input h-8 text-[13px] tabular-nums" value={v} onChange={e => set(p.key, e.target.value)} />
                    ) : (
                      <UnitInput label={p.label} disabled={disabled} value={v as { value: string; unit: string }} units={p.units ?? []} onChange={x => set(p.key, x)} />
                    )}
                    {from && <div className="text-[11px] leading-snug text-primary">{from}</div>}
                    {example && <div className="flex items-center gap-1.5 text-[11px] leading-snug text-warning" data-example={p.key}>
                      <AlertTriangle className="h-3 w-3 shrink-0" /><span>Example value: replace it with your load.</span>
                      {onConfirm && !disabled && <button type="button" className="ml-auto shrink-0 underline" onClick={() => onConfirm(p.key)}>Keep this value</button>}</div>}
                  </div>
                );
              })}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ results panel */
export function ResultView({ r, cat, sys, compact, levelLabel, selfCheck }: { r: CalcResult; cat: Catalog; sys: UnitSystem; compact?: boolean; levelLabel?: string; selfCheck?: boolean }) {
  const [open, setOpen] = useState(!compact);
  const lab = (k: string) => cat.units[k]?.label ?? "";
  const prim = r.outputs.filter(o => o.primary);
  const rest = r.outputs.filter(o => !o.primary);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <LevelBadge level={r.level} cat={cat} label={levelLabel} selfCheck={selfCheck} />
        <span className="text-[11px] text-muted">{r.calc_name} · v{r.calc_version}</span>
      </div>
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
        {prim.map(o => { const d = display(o, sys, lab); return (
          <div key={o.key} className="rounded-lg border border-border bg-panel2/60 px-3 py-2">
            <div className="text-[11px] text-muted">{o.label}</div>
            <div className="mt-0.5 text-[17px] font-semibold tabular-nums tracking-tight">{d.value} <span className="text-[12px] font-normal text-muted">{d.unit}</span></div>
          </div>); })}
      </div>
      {r.checks.length > 0 && (
        <div className="rounded-lg border border-border">
          <div className="border-b border-border bg-panel2 px-3 py-1.5 label">Checks</div>
          <ul className="divide-y divide-border">
            {r.checks.map((c, i) => (
              <li key={i} className="flex items-start gap-2.5 px-3 py-2 text-[13px]">
                {c.passed === null ? <CircleSlash className="mt-0.5 h-4 w-4 shrink-0 text-muted" /> : c.passed ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />}
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{c.label}</div>
                  <div className="text-[11.5px] text-muted">{c.basis}</div>
                  {c.required !== null && <div className="mt-0.5 text-[11.5px]"><span className="text-muted">Required factor {fmt(c.required)} · source: </span><span className="font-medium">{c.source || "-"}</span></div>}
                </div>
                {c.achieved !== null && <div className="text-right tabular-nums"><div className="font-semibold">{c.required !== null ? `n = ${fmt(c.achieved, 3)}` : fmt(c.achieved, 3)}</div>
                  {c.passed !== null && <div className={cx("text-[11px]", c.passed ? "text-success" : "text-danger")}>{c.passed ? (c.required !== null ? "meets required factor" : "met") : (c.required !== null ? "below required factor" : "not met")}</div>}</div>}
              </li>))}
          </ul>
        </div>
      )}
      {r.warnings.map(w => <div key={w} className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-[12.5px]"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />{w}</div>)}
      {rest.length > 0 && (
        <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          {rest.map(o => { const d = display(o, sys, lab); return <div key={o.key} className="flex items-baseline justify-between border-b border-dashed border-border py-1 text-[12.5px]"><span className="text-muted">{o.label}</span><span className="tabular-nums">{d.value} <span className="text-muted">{d.unit}</span></span></div>; })}
        </div>
      )}
      <div className="rounded-lg border border-border">
        <button type="button" className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[13px] font-medium" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}Working ({r.steps.length} steps)
        </button>
        {open && (
          <ol className="divide-y divide-border border-t border-border text-[12px]" data-panel="working">
            {r.steps.map((s, i) => (
              <li key={i} className="px-3 py-2">
                <div className="flex items-baseline gap-2">
                  <span className="w-5 shrink-0 text-right text-[10.5px] tabular-nums text-muted">{i + 1}</span>
                  <span className="min-w-0 flex-1 font-medium">{s.label}{s.ref && <span className="ml-1.5 text-[10.5px] font-normal text-muted">{s.ref}</span>}</span>
                  <span className="shrink-0 text-right font-semibold tabular-nums">{fmt(s.value)} <span className="font-normal text-muted">{s.unit}</span></span>
                </div>
                <div className="ml-7 mt-0.5 break-words font-mono text-[11.5px]">{s.equation}</div>
                {s.substitution && <div className="ml-7 break-words font-mono text-[11px] text-muted">= {s.substitution}</div>}
              </li>))}
          </ol>
        )}
      </div>
      <Sources r={r} />
    </div>
  );
}

export function Sources({ r }: { r: Pick<CalcResult, "references" | "assumptions" | "verified_against" | "notes"> }) {
  return (
    <div className="grid gap-3 text-[12px] md:grid-cols-2">
      <div className="rounded-lg border border-border p-3">
        <div className="mb-1.5 flex items-center gap-1.5 label"><BookOpen className="h-3.5 w-3.5" />Source</div>
        <ul className="list-disc space-y-1 pl-4">{r.references.map(x => <li key={x}>{x}</li>)}</ul>
        <div className="mb-1 mt-3 label">Calculator checked against</div>
        <ul className="list-disc space-y-1 pl-4 text-muted">{r.verified_against.map(x => <li key={x}>{x}</li>)}</ul>
      </div>
      <div className="rounded-lg border border-border p-3">
        <div className="mb-1.5 label">Assumptions</div>
        <ul className="list-disc space-y-1 pl-4">{r.assumptions.map(x => <li key={x}>{x}</li>)}</ul>
        {r.notes.length > 0 && <Fragment><div className="mb-1 mt-3 label">Notes</div><ul className="list-disc space-y-1 pl-4 text-muted">{r.notes.map(x => <li key={x}>{x}</li>)}</ul></Fragment>}
      </div>
    </div>
  );
}
