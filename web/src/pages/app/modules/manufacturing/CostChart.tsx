import { useMemo, useState } from "react";
import { cx } from "@/lib/format";
import { COST_NAMES, type CostProc } from "./types";

/** Categorical slots follow the process (entity), never its rank. Reference palette, light / dark steps. */
const SLOT: Record<string, [string, string]> = {
  cnc_milling: ["#2a78d6", "#3987e5"], cnc_turning: ["#eb6834", "#d95926"], sheet_metal: ["#1baf7a", "#199e70"],
  fdm: ["#eda100", "#c98500"], sla: ["#e87ba4", "#d55181"], sls: ["#008300", "#0ca30c"],
  casting: ["#6250d6", "#9085e9"], injection_moulding: ["#e34948", "#e66767"],
};
export function seriesColor(p: string): string {
  const dark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");
  return (SLOT[p] ?? ["#62666e", "#9aa0aa"])[dark ? 1 : 0];
}

export function money(v: number | null | undefined, cur: string, digits = 2) {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  return `${cur} ${v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

const W = 340, H = 210, PL = 46, PR = 10, PT = 10, PB = 26;

/** Unit cost vs quantity, log-log. One y-axis; crosshair + tooltip; legend plus a table view. */
export default function CostChart({ procs, quantities, quantity, currency }: {
  procs: Record<string, CostProc>; quantities: number[]; quantity: number; currency: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const names = Object.keys(procs);
  const { ys, yTicks, x, y } = useMemo(() => {
    const vals = names.flatMap(n => procs[n]!.curve.map(p => p.unit)).filter(v => v > 0);
    const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...vals))));
    const hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...vals) * 1.0001)));
    const qlo = Math.log10(quantities[0] ?? 1), qhi = Math.log10(quantities[quantities.length - 1] ?? 10);
    const x = (q: number) => PL + ((Math.log10(q) - qlo) / Math.max(qhi - qlo, 1e-9)) * (W - PL - PR);
    const y = (v: number) => PT + (1 - (Math.log10(Math.max(v, lo)) - Math.log10(lo)) / Math.max(Math.log10(hi) - Math.log10(lo), 1e-9)) * (H - PT - PB);
    const yTicks: number[] = [];
    for (let v = lo; v <= hi * 1.0001; v *= 10) yTicks.push(v);
    return { ys: vals, yTicks, x, y };
  }, [procs, quantities]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!names.length || !ys.length) return null;
  const qi = hover;
  const fmtQ = (q: number) => (q >= 1000 ? `${q / 1000}k` : `${q}`);
  const fmtV = (v: number) => (v >= 1000 ? `${Math.round(v / 1000)}k` : `${v}`);

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] text-muted">Unit cost vs quantity (log scales)</span>
        <button onClick={() => setTable(t => !t)} className="text-[11px] font-medium text-primary hover:underline">{table ? "Chart" : "Table"}</button>
      </div>
      {table ? (
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-[11px]">
            <thead className="bg-panel2 text-muted"><tr><th className="px-2 py-1 text-left font-medium">Process</th>
              {quantities.map(q => <th key={q} className={cx("px-2 py-1 text-right font-medium", q === quantity && "text-text")}>{fmtQ(q)}</th>)}</tr></thead>
            <tbody>{names.map(n => <tr key={n} className="border-t border-border">
              <td className="px-2 py-1">{COST_NAMES[n] ?? n}</td>
              {procs[n]!.curve.map(p => <td key={p.q} className={cx("px-2 py-1 text-right tabular-nums", p.q === quantity && "font-semibold")}>{money(p.unit, "", p.unit >= 100 ? 0 : 2)}</td>)}
            </tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full select-none" role="img" aria-label="Relative unit cost by quantity"
            onMouseLeave={() => setHover(null)}
            onMouseMove={e => {
              const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
              const px = ((e.clientX - r.left) / r.width) * W;
              let best = 0, bd = Infinity;
              quantities.forEach((q, i) => { const d = Math.abs(x(q) - px); if (d < bd) { bd = d; best = i; } });
              setHover(best);
            }}>
            {yTicks.map(v => <g key={v}>
              <line x1={PL} x2={W - PR} y1={y(v)} y2={y(v)} stroke="rgb(var(--border))" strokeWidth={1} />
              <text x={PL - 5} y={y(v) + 3} textAnchor="end" fontSize={9} fill="rgb(var(--muted))">{fmtV(v)}</text>
            </g>)}
            {quantities.map(q => <text key={q} x={x(q)} y={H - 8} textAnchor="middle" fontSize={9}
              fill={q === quantity ? "rgb(var(--text))" : "rgb(var(--muted))"} fontWeight={q === quantity ? 600 : 400}>{fmtQ(q)}</text>)}
            <line x1={x(quantity)} x2={x(quantity)} y1={PT} y2={H - PB} stroke="rgb(var(--muted))" strokeDasharray="3 3" strokeWidth={1} />
            {qi !== null && <line x1={x(quantities[qi]!)} x2={x(quantities[qi]!)} y1={PT} y2={H - PB} stroke="rgb(var(--text))" strokeOpacity={0.35} strokeWidth={1} />}
            {names.map(n => {
              const c = procs[n]!.curve;
              const col = seriesColor(n);
              const at = c.find(p => p.q === quantity);
              return <g key={n}>
                <polyline fill="none" stroke={col} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                  points={c.map(p => `${x(p.q)},${y(p.unit)}`).join(" ")} />
                {at && <circle cx={x(at.q)} cy={y(at.unit)} r={4} fill={col} stroke="rgb(var(--panel))" strokeWidth={2} />}
                {qi !== null && <circle cx={x(c[qi]!.q)} cy={y(c[qi]!.unit)} r={3.5} fill={col} stroke="rgb(var(--panel))" strokeWidth={2} />}
              </g>;
            })}
          </svg>
          {qi !== null && (
            <div className="pointer-events-none absolute top-1 rounded border border-border bg-panel px-2 py-1.5 text-[11px] shadow-pop"
              style={{ left: `${Math.min(62, Math.max(2, (x(quantities[qi]!) / W) * 100 - (qi > quantities.length / 2 ? 40 : -4)))}%` }}>
              <div className="mb-0.5 font-semibold">{quantities[qi]!.toLocaleString()} parts</div>
              {[...names].sort((a, b) => procs[a]!.curve[qi]!.unit - procs[b]!.curve[qi]!.unit).map(n => (
                <div key={n} className="flex items-center gap-1.5 whitespace-nowrap">
                  <span className="h-2 w-2 rounded-full" style={{ background: seriesColor(n) }} />
                  <span className="text-muted">{COST_NAMES[n] ?? n}</span>
                  <span className="ml-auto pl-2 tabular-nums">{money(procs[n]!.curve[qi]!.unit, currency)}</span>
                </div>))}
            </div>
          )}
        </div>
      )}
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
        {names.map(n => <span key={n} className="inline-flex items-center gap-1.5 text-[11px] text-muted">
          <span className="h-[3px] w-3 rounded-full" style={{ background: seriesColor(n) }} />{COST_NAMES[n] ?? n}</span>)}
      </div>
    </div>
  );
}
