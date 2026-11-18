import { useId, useMemo, useState, type ReactNode } from "react";
import { cx } from "@/lib/format";
import { CountUp } from "./motion";
import { PROFILES, RATE_PRESETS, WORKDAYS_PER_MONTH, roi, usd, type Complexity, type Inputs, type PackLike, type PlanLike } from "./roi";

/** Conventional = copper, Formwright = Forge blue (validated light + dark: CVD ΔE ≥ 25, contrast ≥ 3:1). */
const CONV = "bg-[#C8742E] dark:bg-[#CC7A35]";
const FW = "bg-primary";

function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { v: T; l: ReactNode }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="grid auto-cols-fr grid-flow-col gap-1 rounded-lg border border-border bg-panel2 p-1">
      {options.map(o => (
        <button key={o.v} role="radio" aria-checked={value === o.v} onClick={() => onChange(o.v)}
          className={cx("rounded-md px-2 py-1.5 text-[13px] font-medium transition", value === o.v ? "bg-panel text-text shadow-card" : "text-muted hover:text-text")}>
          {o.l}
        </button>
      ))}
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange, display, hint }:
  { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; display: string; hint?: ReactNode }) {
  const id = useId();
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
        <span className="text-sm font-semibold tabular-nums">{display}</span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-[rgb(var(--primary))]" />
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

/** Two-bar comparison with direct value labels; one measure per chart (no dual axis). */
function Bars({ title, conv, fw, fmt, detail }: { title: string; conv: number; fw: number; fmt: (n: number) => string; detail: [string, string] }) {
  const max = Math.max(conv, fw, 1e-9);
  const rows = [
    { k: "Conventional", v: conv, c: CONV, d: detail[0] },
    { k: "Formwright", v: fw, c: FW, d: detail[1] },
  ];
  return (
    <figure>
      <figcaption className="text-xs font-medium text-muted">{title}</figcaption>
      <div className="mt-2 space-y-2">
        {rows.map(r => (
          <div key={r.k} className="group grid grid-cols-[92px_1fr] items-center gap-3" title={`${r.k}: ${fmt(r.v)} — ${r.d}`}>
            <span className="text-xs text-muted">{r.k}</span>
            <div className="flex items-center gap-2">
              <div className="h-5 min-w-[4px] origin-left rounded-r-[4px] transition-[width] duration-700 ease-out motion-reduce:transition-none"
                style={{ width: `${Math.max(0.6, (Math.max(0, r.v) / max) * 78)}%` }}>
                <div className={cx("h-full w-full rounded-r-[4px] opacity-90 group-hover:opacity-100", r.c)} />
              </div>
              <span className="whitespace-nowrap text-xs font-semibold tabular-nums">{fmt(r.v)}</span>
            </div>
          </div>
        ))}
      </div>
    </figure>
  );
}

export default function Calculator({ plans, packs, initial }: { plans: PlanLike[]; packs: PackLike[]; initial: Inputs }) {
  const [parts, setParts] = useState(initial.parts);
  const [complexity, setComplexity] = useState<Complexity>(initial.complexity);
  const [rate, setRate] = useState(initial.rate);
  const [review, setReview] = useState(initial.review);
  const [planCode, setPlanCode] = useState(initial.plan.code);
  const plan = plans.find(p => p.code === planCode) ?? plans[0]!;
  const r = useMemo(() => roi({ parts, complexity, rate, review, plan, packs }), [parts, complexity, rate, review, plan, packs]);
  const prof = PROFILES[complexity];
  const h = (n: number) => `${n.toLocaleString("en-US", { maximumFractionDigits: n < 10 ? 1 : 0 })} h`;
  const saving = r.monthlySaving >= 0;

  return (
    <div className="grid overflow-hidden rounded-xl border border-border bg-panel shadow-card lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* inputs */}
      <div className="space-y-6 border-b border-border bg-panel2/50 p-5 sm:p-7 lg:border-b-0 lg:border-r">
        <Slider label="New parts per month" value={parts} min={1} max={60} step={1} onChange={setParts} display={String(parts)} />
        <div>
          <div className="mb-2 text-sm font-medium">Typical part complexity</div>
          <Seg label="Part complexity" value={complexity} onChange={setComplexity}
            options={(Object.keys(PROFILES) as Complexity[]).map(k => ({ v: k, l: PROFILES[k].label }))} />
          <div className="mt-1.5 text-xs text-muted">{prof.example} · conventional ≈ {prof.convHours} h each incl. drawing · ≈ {prof.tokens} tokens each</div>
        </div>
        <div>
          <div className="flex items-baseline justify-between gap-3">
            <label htmlFor="why-rate" className="text-sm font-medium">Engineer cost per hour</label>
            <div className="flex items-center gap-1 text-sm font-semibold">
              US$<input id="why-rate" type="number" min={1} max={500} value={rate} onChange={e => setRate(Math.max(0, Math.min(500, Number(e.target.value) || 0)))}
                className="w-16 rounded border border-border bg-panel px-1.5 py-0.5 text-right tabular-nums focus:outline-none focus:ring-2 focus:ring-primary/40" />
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {RATE_PRESETS.map(p => (
              <button key={p.key} onClick={() => setRate(p.rate)} title={p.note}
                className={cx("rounded-full border px-2.5 py-1 text-xs transition", rate === p.rate ? "border-primary bg-primary-soft text-primary" : "border-border text-muted hover:text-text")}>
                {p.label} · ${p.rate}
              </button>
            ))}
          </div>
        </div>
        <Slider label="Engineer review time kept" value={Math.round(review * 100)} min={5} max={80} step={5} onChange={v => setReview(v / 100)}
          display={`${Math.round(review * 100)}%`} hint="Share of the conventional hours your engineer still spends checking and signing off each part." />
        <div>
          <div className="mb-2 text-sm font-medium">Plan</div>
          <Seg label="Plan" value={planCode} onChange={setPlanCode}
            options={plans.map(p => ({ v: p.code, l: <span>{p.name} <span className="font-normal text-muted">${p.price_cents / 100}/mo</span></span> }))} />
          <div className="mt-1.5 text-xs text-muted">{plan.tokens.toLocaleString()} tokens/mo included · {plan.seats} {plan.seats === 1 ? "seat" : "seats"} · extra tokens bought in the cheapest packs</div>
        </div>
      </div>

      {/* outputs */}
      <div className="p-5 sm:p-7" aria-live="polite">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className={cx("rounded-lg border p-4", saving ? "border-success/30 bg-success/[.06]" : "border-danger/30 bg-danger/[.06]")}>
            <div className="text-xs font-medium text-muted">{saving ? "Modelled saving per month" : "Extra cost per month"}</div>
            <div className="mt-1 text-3xl font-semibold tracking-tight"><CountUp value={Math.abs(r.monthlySaving)} format={n => usd(n)} duration={500} /></div>
            <div className="mt-1 text-xs text-muted">{saving ? `${Math.round(r.costReduction * 100)}% lower than conventional` : r.convCost > r.fwLabour ? "Too few parts this month to cover the plan" : "Review time exceeds the work saved"}</div>
          </div>
          <div className="rounded-lg border border-border p-4">
            <div className="text-xs font-medium text-muted">{saving ? "Per year" : "Per year (extra)"}</div>
            <div className="mt-1 text-3xl font-semibold tracking-tight"><CountUp value={Math.abs(r.yearlySaving)} format={n => usd(n)} duration={500} /></div>
            <div className="mt-1 text-xs text-muted">{r.speedUp > 0 ? `${r.speedUp.toFixed(1)}× more parts per engineer-hour` : "—"}</div>
          </div>
        </div>

        <div className="mt-6">
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted" aria-hidden>
            <span className="inline-flex items-center gap-1.5"><span className={cx("h-2.5 w-2.5 rounded-sm", CONV)} />Conventional</span>
            <span className="inline-flex items-center gap-1.5"><span className={cx("h-2.5 w-2.5 rounded-sm", FW)} />Formwright + engineer review</span>
          </div>
          <div className="mt-3 grid gap-5 sm:grid-cols-2">
            <Bars title="Cost per month (US$)" conv={r.convCost} fw={r.fwCost} fmt={n => usd(n)}
              detail={[`${h(r.convHours)} × $${rate}/h`, `review ${usd(r.fwLabour)} + plan ${usd(r.subscription)} + top-ups ${usd(r.topups)}`]} />
            <Bars title="Engineer hours per month" conv={r.convHours} fw={r.fwHours} fmt={h}
              detail={[`${parts} × ${prof.convHours} h`, `${parts} × (${Math.round(review * 100)}% review + ${prof.briefMinutes} min brief)`]} />
          </div>
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border pt-5 text-sm sm:grid-cols-3">
          {[
            ["Conventional", `${usd(r.convCost)} · ${h(r.convHours)}`],
            ["Conventional workload", r.convHours / 160 < 0.1 ? "< 0.1 FTE (160 h/mo)" : `≈ ${(r.convHours / 160).toFixed(1)} FTE (160 h/mo)`],
            ["Engineer review", `${usd(r.fwLabour)} · ${h(r.fwHours)}`],
            ["Plan", usd(r.subscription)],
            ["Tokens used", `${r.tokens.toLocaleString()} (${r.extraTokens.toLocaleString()} extra)`],
            ["Top-up packs", usd(r.topups)],
            ["Pays for itself", r.paybackDays === null || r.paybackDays > WORKDAYS_PER_MONTH ? "not within the month" : r.paybackDays < 1 ? "within the first day" : `in ${Math.ceil(r.paybackDays)} working days`],
            ["Speed-up", r.speedUp > 0 ? `${r.speedUp.toFixed(1)}× engineer-hours` : "—"],
            ["First verified model", `${r.firstModelSpeedUp.toFixed(0)}× sooner`],
          ].map(([k, v]) => (
            <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="mt-0.5 font-medium tabular-nums">{v}</dd></div>
          ))}
        </dl>
        <p className="mt-5 text-[11px] leading-relaxed text-muted">
          Formwright cost = engineer review hours × your rate + plan + top-up packs for tokens beyond the plan.
          Conventional = parts × typical hours × your rate. Estimates for illustration; actual savings depend on your parts and workflow.
        </p>
      </div>
    </div>
  );
}
