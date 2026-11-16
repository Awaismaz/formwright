import { AlertTriangle, CheckCircle2, CircleDashed, Info } from "lucide-react";
import { Badge } from "./ui";
import { cx } from "@/lib/format";

function SampleFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-panel">
      <div className="flex items-center justify-between border-b border-border bg-panel2 px-4 py-2">
        <span className="text-[13px] font-medium">{title}</span>
        <Badge tone="accent">SAMPLE · illustrative, not generated from your data</Badge>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function DrawingSample() {
  return (
    <SampleFrame title="Drawing sheet — Mounting plate (A3)">
      <svg viewBox="0 0 600 380" className="w-full rounded border border-border bg-white">
        <rect x="8" y="8" width="584" height="364" fill="none" stroke="#1d2330" strokeWidth="1.5" />
        <g fill="none" stroke="#1d2330" strokeWidth="1.2">
          <rect x="60" y="60" width="180" height="120" /><rect x="110" y="95" width="80" height="50" rx="5" />
          {[[75, 75], [225, 75], [75, 165], [225, 165]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="6" />)}
          <rect x="60" y="215" width="180" height="15" /><line x1="110" y1="215" x2="110" y2="223" strokeDasharray="3 2" /><line x1="190" y1="215" x2="190" y2="223" strokeDasharray="3 2" />
          <rect x="290" y="60" width="15" height="120" />
          <path d="M360 170 L430 130 L520 170 L450 210 Z" /><path d="M360 170 L360 180 L450 220 L450 210" /><path d="M450 220 L520 180 L520 170" />
        </g>
        <g stroke="#1F5FBF" strokeWidth=".8" fill="#1F5FBF" fontSize="9" fontFamily="Inter, sans-serif">
          <line x1="60" y1="45" x2="240" y2="45" /><text x="138" y="41" stroke="none">120</text>
          <line x1="250" y1="60" x2="250" y2="180" /><text x="254" y="124" stroke="none">80</text>
          <line x1="110" y1="152" x2="190" y2="152" /><text x="140" y="164" stroke="none">40 ±0.1</text>
          <text x="58" y="198" stroke="none">4× Ø6.6 THRU</text>
          <line x1="60" y1="240" x2="240" y2="240" /><text x="132" y="252" stroke="none">10</text>
        </g>
        <g fontSize="8" fill="#5b6475" fontFamily="Inter, sans-serif"><text x="62" y="54">FRONT</text><text x="290" y="54">RIGHT</text><text x="410" y="120">ISO</text></g>
        <rect x="380" y="290" width="204" height="74" fill="none" stroke="#1d2330" />
        <g fontSize="8.5" fontFamily="Inter, sans-serif" fill="#1d2330">
          <text x="388" y="304" fontWeight="700">MOUNTING PLATE</text><text x="388" y="318">Material: Al 6061-T6 · Units: mm</text>
          <text x="388" y="331">Scale 1:2 · Rev B · Sheet 1/1</text><text x="388" y="344" fill="#c43228" fontWeight="700">NOT APPROVED FOR MANUFACTURE</text>
          <text x="388" y="357" fill="#5b6475">Dims: ● spec  ○ inferred</text>
        </g>
      </svg>
    </SampleFrame>
  );
}

function FindingsTable({ rows }: { rows: [string, string, "high" | "med" | "low" | "ok", string][] }) {
  const tone = { high: "danger", med: "warning", low: "primary", ok: "success" } as const;
  return (
    <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted"><tr><th className="pb-2 font-medium">Feature</th><th className="pb-2 font-medium">Finding</th><th className="pb-2 font-medium">Severity</th><th className="pb-2 font-medium">Suggestion</th></tr></thead>
      <tbody className="divide-y divide-border">{rows.map(([f, r, s, sug]) => (
        <tr key={f + r}><td className="py-2 pr-3 font-mono text-[12px]">{f}</td><td className="py-2 pr-3">{r}</td><td className="py-2 pr-3"><Badge tone={tone[s]}>{s === "ok" ? "OK" : s.toUpperCase()}</Badge></td><td className="py-2 text-muted">{sug}</td></tr>))}
      </tbody></table>
  );
}

const SAMPLES: Record<string, () => JSX.Element> = {
  drawings: DrawingSample,
  manufacturing: () => (
    <SampleFrame title="DFM report — CNC milling, qty 50, 6061-T6">
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {[["CNC milling", "Recommended", "2 setups · est. relative cost 1.0×"], ["Waterjet + drill", "Alternative", "1.3× · loses pocket"], ["Sheet metal", "Not suitable", "10 mm thickness"]].map(([p, l, d], i) => (
          <div key={p} className={cx("rounded-lg border p-3", i === 0 ? "border-success/40 bg-success/5" : "border-border")}><div className="text-sm font-medium">{p}</div><div className="text-xs text-muted">{l} · {d}</div></div>))}
      </div>
      <FindingsTable rows={[
        ["pocket_1", "Internal corner R3 needs Ø6 end mill", "low", "R4 allows Ø8 tool, faster roughing"],
        ["hole_pattern_1", "Ø6.6 is a non-standard drill", "med", "Use Ø6.5 or Ø6.8 standard drill"],
        ["chamfer_top", "Edge break on top only", "low", "Add 0.5 mm break on bottom edges"],
        ["body", "Stock 125×85×12 → 34% removal", "ok", "Fine for this quantity"],
      ]} />
    </SampleFrame>),
  engineering: () => (
    <SampleFrame title="Engineering review — L-bracket, cantilever 200 N">
      <ul className="space-y-2 text-[13px]">
        {[["Bending stress at fillet", "Preliminary estimate", "σ ≈ 38 MPa vs Sy 276 MPa (SF ≈ 7)", CheckCircle2, "text-success"],
          ["Stress concentration at R3 fillet", "Recommended check", "Kt ≈ 1.6 from chart — confirm with FEA", Info, "text-primary"],
          ["Fatigue (vibrating pump)", "Recommended check", "Load spectrum unknown — needs input", AlertTriangle, "text-warning"],
          ["Bolt preload M5 8.8", "Verified calculation", "Fp = 6.4 kN at 70% proof (tested calculator)", CheckCircle2, "text-success"],
          ["Validated simulation", "Not performed", "Requires external FEA + engineer sign-off", CircleDashed, "text-muted"],
        ].map(([t, lvl, d, I, c]) => { const C = I as typeof Info; return (
          <li key={t as string} className="flex items-start gap-3 rounded-lg border border-border p-3"><C className={cx("mt-0.5 h-4 w-4", c as string)} />
            <div className="flex-1"><div className="font-medium">{t as string}</div><div className="text-xs text-muted">{d as string}</div></div><Badge>{lvl as string}</Badge></li>); })}
      </ul>
    </SampleFrame>),
  assembly: () => (
    <SampleFrame title="Assembly — Damper sub-assembly (5 parts)">
      <div className="grid gap-4 md:grid-cols-2">
        <div><div className="label mb-2">Tree & mates</div>
          <ul className="space-y-1 font-mono text-[12px]">{["▾ damper_asm", "   ├ body (fixed)", "   ├ piston ⟷ body: concentric, slide", "   ├ rod ⟷ piston: rigid", "   ├ cap ⟷ body: coincident", "   └ 2× M6 bolt ⟷ cap: concentric"].map(l => <li key={l}>{l}</li>)}</ul>
          <div className="mt-3 text-xs text-muted">DOF: 1 (slide along Z) · fully constrained otherwise</div></div>
        <div><div className="label mb-2">Interference & clearance</div>
          <FindingsTable rows={[["rod / cap", "Clearance 0.15 mm", "ok", "—"], ["piston / body", "Interference 0.02 mm³", "high", "Reduce piston Ø by 0.05 mm"], ["bolt / body", "Thread engagement 1.8×d", "ok", "—"]]} /></div>
      </div>
    </SampleFrame>),
  image2cad: () => (
    <SampleFrame title="Sketch → model interpretation">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex aspect-[4/3] items-center justify-center rounded-lg border border-dashed border-border bg-[repeating-linear-gradient(0deg,transparent,transparent_19px,rgb(var(--border))_20px)]">
          <svg viewBox="0 0 200 150" className="w-3/4"><path d="M30 110 L30 40 L60 40 L60 95 L170 95 L170 110 Z" fill="none" stroke="#3b4250" strokeWidth="2" strokeLinejoin="round" strokeDasharray="1 0" /><circle cx="45" cy="60" r="5" fill="none" stroke="#3b4250" strokeWidth="1.5" /><circle cx="140" cy="103" r="4" fill="none" stroke="#3b4250" strokeWidth="1.5" /><text x="90" y="125" fontSize="9" fill="#3b4250">~120?</text></svg>
        </div>
        <ul className="space-y-2 text-[13px]">
          {[["Profile: L-section", "high"], ["Hole on vertical leg", "high"], ["Overall length ≈ 120 mm", "low"], ["Thickness", "missing"], ["Hole diameters", "missing"]].map(([t, c]) => (
            <li key={t} className="flex items-center justify-between rounded border border-border px-3 py-2">{t}<Badge tone={c === "high" ? "success" : c === "low" ? "warning" : "danger"}>{c === "missing" ? "Ask user" : `confidence ${c}`}</Badge></li>))}
          <li className="rounded-lg bg-primary-soft p-3 text-primary">“What thickness should the bracket be, and are the holes for M5 or M6 bolts?”</li>
        </ul>
      </div>
    </SampleFrame>),
  print: () => (
    <SampleFrame title="Print readiness — enclosure lid, PLA, 0.4 mm nozzle">
      <FindingsTable rows={[["mesh", "Watertight, 1 shell", "ok", "—"], ["boss_ribs", "Wall 0.8 mm < 2 perimeters", "med", "Increase to 1.2 mm"], ["lid_lip", "Overhang 62° unsupported", "high", "Rotate 180° or add chamfer"], ["orientation", "Best: top face down", "ok", "Support area −71%"]]} />
    </SampleFrame>),
  mesh: () => (
    <SampleFrame title="Mesh Studio — concept renders">
      <div className="grid grid-cols-3 gap-3">{["Brushed steel", "Anodised blue", "Matte black"].map((m, i) => (
        <div key={m} className="overflow-hidden rounded-lg border border-border"><div className="aspect-square" style={{ background: ["radial-gradient(circle at 35% 30%,#f2f4f7,#8d96a3 60%,#4a525e)", "radial-gradient(circle at 35% 30%,#9cc2ff,#2a5db0 60%,#122a55)", "radial-gradient(circle at 35% 30%,#7a7f88,#2b2e33 60%,#111)"][i] }} />
          <div className="px-2 py-1.5 text-xs">{m}</div></div>))}</div>
      <p className="mt-3 text-xs text-muted">Mesh outputs are for visualisation and are kept separate from precision B-rep CAD.</p>
    </SampleFrame>),
};

export default function ModuleSample({ code }: { code: string }) {
  const S = SAMPLES[code];
  return S ? <S /> : null;
}
