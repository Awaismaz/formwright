import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, LayoutTemplate, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx, PAGE } from "@/lib/format";
import { Badge, Button, Card, Field, Input, PageHeader } from "@/components/ui";
import { AgentAvatar } from "./Avatars";
import { BASE } from "./api";
import type { Program } from "./types";

const EXAMPLES = [
  { name: "Gear reducer", brief: "Single-stage spur gear reducer, 3:1 ratio, 1.5 kW input at 1450 rpm. Foot-mounted cast aluminium housing split at the shaft centreline, 6204 bearings on both shafts, keyed Ø20 input and Ø28 output shafts, oil bath lubrication." },
  { name: "Belt conveyor", brief: "Bench-top belt conveyor, 1200 mm long, 200 mm belt, 10 kg parts at 0.3 m/s. Bent sheet-steel side rails on four adjustable legs, crowned drive pulley driven by a small gear motor, tail pulley with belt take-up, carry rollers every 200 mm." },
  { name: "Robot gripper", brief: "Parallel two-jaw gripper for a cobot with an ISO 9409-1-50-4-M6 flange. 40 mm stroke, 150 N grip force, pneumatic actuator in a machined aluminium housing, replaceable printed nylon fingers for 30–60 mm round parts." },
];

export default function NewProgram() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [planner, setPlanner] = useState<"archie" | "standard">("archie");
  const [concurrency, setConcurrency] = useState(3);
  const [deliverables, setDeliverables] = useState(true);
  const [budget, setBudget] = useState(3000);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const p = await api.post<Program>(`${BASE}/programs`, { name, brief, planner, concurrency, budget_tokens: budget, deliverables });
      qc.invalidateQueries({ queryKey: ["office-home"] });
      nav(`/app/office/programs/${p.id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not create the program");
      if (e instanceof ApiError && e.cta) nav(e.cta);
    } finally { setBusy(false); }
  };
  const choice = ({ value, icon, title, body, badge }: { value: "archie" | "standard"; icon: React.ReactNode; title: string; body: string; badge: string }) => (
    <button type="button" onClick={() => setPlanner(value)} aria-pressed={planner === value}
      className={cx("flex flex-1 items-start gap-3 rounded-lg border p-3 text-left transition", planner === value ? "border-primary bg-primary-soft/50 ring-2 ring-primary/20" : "border-border hover:border-primary/40")}>
      {icon}
      <span className="min-w-0"><span className="flex items-center gap-2 text-[13.5px] font-semibold">{title}<Badge tone={value === "archie" ? "primary" : "neutral"}>{badge}</Badge></span>
        <span className="mt-0.5 block text-[12px] text-muted">{body}</span></span>
    </button>
  );
  return (
    <div className={PAGE}>
      <Link to="/app/office" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-3.5 w-3.5" />Design Office</Link>
      <PageHeader title="New program" subtitle="Write the brief as you would for a design office. Archie breaks it down; you review the plan before any ticket opens." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="space-y-4 p-5 lg:col-span-2">
          <Field label="Program name" hint="Optional: taken from the brief if left empty.">
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Gear reducer GR-1" maxLength={120} />
          </Field>
          <Field label="Brief" hint="What it is, what it must do (loads, speeds, sizes), materials and standard parts you already know. Numbers help most.">
            <textarea className="input min-h-[170px] py-2 leading-relaxed" value={brief} onChange={e => setBrief(e.target.value)} maxLength={20000}
              placeholder="e.g. Single-stage spur gear reducer, 3:1, 1.5 kW at 1450 rpm, foot mounted…" />
          </Field>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">Try:
            {EXAMPLES.map(x => <button key={x.name} type="button" className="rounded-full border border-border px-2.5 py-1 hover:border-primary/40 hover:text-text"
              onClick={() => { setName(x.name); setBrief(x.brief); }}>{x.name}</button>)}
          </div>
          <div>
            <div className="mb-1.5 text-[13px] font-medium">Who plans it</div>
            <div className="flex flex-col gap-2 sm:flex-row">
              {choice({ value: "archie", icon: <AgentAvatar code="archie" size={40} state={planner === "archie" ? "working" : "idle"} />, title: "Archie", badge: "AI",
                body: "Reads the brief and proposes sub-assemblies, parts, families and complexity. Uses tokens (capped at 200 per plan)." })}
              {choice({ value: "standard", icon: <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-text/[.06] text-muted"><LayoutTemplate className="h-5 w-5" /></span>,
                title: "Standard breakdown", badge: "No AI", body: "Instant breakdown from product templates and keywords in the brief. Free; review it closely." })}
            </div>
          </div>
          <details className="rounded-lg border border-border px-3 py-2 text-[13px]">
            <summary className="cursor-pointer select-none font-medium">Concurrency, budget and deliverables</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="Agents in parallel" hint="Used for ETA ranges now, and as the cap when auto-run arrives.">
                <Input type="number" min={1} max={12} value={concurrency} onChange={e => setConcurrency(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} />
              </Field>
              <Field label="Token budget" hint="Shown against spend on the board.">
                <Input type="number" min={0} step={100} value={budget} onChange={e => setBudget(Math.max(0, Number(e.target.value) || 0))} />
              </Field>
            </div>
            <label className="mt-3 flex items-start gap-2 text-[12.5px]"><input type="checkbox" className="mt-0.5" checked={deliverables} onChange={e => setDeliverables(e.target.checked)} />
              <span>After integration, Ortho draws every part and the assembly with its BOM, and Smithy reviews every part for manufacture (no tokens).</span></label>
          </details>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button variant="secondary" onClick={() => nav("/app/office")}>Cancel</Button>
            <Button loading={busy} disabled={brief.trim().length < 20} icon={planner === "archie" ? <Sparkles className="h-4 w-4" /> : undefined} onClick={submit}>
              {planner === "archie" ? "Ask Archie to plan" : "Create the breakdown"}</Button>
          </div>
        </Card>
        <Card className="h-fit space-y-3 p-5 text-[13px]">
          <div className="flex items-center gap-3"><AgentAvatar code="archie" size={48} /><div><div className="font-semibold">Archie</div><div className="text-[12px] text-muted">Chief Designer</div></div></div>
          <p className="text-muted">Archie plans; Archie does not model. Each part becomes a ticket owned by a specialist:</p>
          <ul className="space-y-1.5">
            {[["mill", "Mill", "machined parts"], ["chuck", "Chuck", "turned parts"], ["axel", "Axel", "gears and drives"], ["benny", "Benny", "sheet metal"],
              ["molly", "Molly", "plastic parts"], ["hex", "Hex", "standard parts from the Toolbox"], ["fitz", "Fitz", "assembly at each level"]].map(([c, n, r]) => (
              <li key={c} className="flex items-center gap-2"><AgentAvatar code={c!} size={24} still /><b>{n}</b><span className="text-muted">{r}</span></li>))}
          </ul>
          <p className="text-[12px] text-muted">Estimates are complexity × calibrated minutes per family, shown as ranges.</p>
        </Card>
      </div>
    </div>
  );
}
