import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Pause, Play, Plus, RotateCw, Trash2 } from "lucide-react";
import { cx } from "@/lib/format";
import { Button, Input } from "@/components/ui";
import type { AsmView, Joint, MotionResult, V3 } from "./types";
import { Segmented } from "./bits";

/** What the viewport shows for one step of a motion check: placements of the moving parts, the parts in a
 * collision, and the overlap volumes (kept for the worst step only). */
export function stepScene(m: MotionResult | null, k: number): { poses: Record<string, number[]> | null; hot: string[];
  meshes: { pos: number[]; idx: number[] }[] } {
  const s = m?.steps[k];
  if (!s) return { poses: null, hot: [], meshes: [] };
  return { poses: s.T, hot: [...new Set(s.collisions.flatMap(c => [c.a, c.b]))],
    meshes: s.collisions.filter(c => c.mesh).map(c => c.mesh!) };
}

function fmtV(v: number, unit: string) { return `${Number(v.toFixed(2))}${unit}`; }

/** The sweep result: a strip of steps (red = collision), a scrubber with play, the collisions at the current step
 * and a jump to the worst step. ``step`` / ``onStep`` are lifted so the viewport can follow. */
export function MotionScrubber({ m, step, onStep }: { m: MotionResult; step: number; onStep: (k: number) => void }) {
  const [playing, setPlaying] = useState(false);
  const n = m.steps.length;
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => onStep((step + 1) % n), 350);
    return () => clearInterval(t);
  }, [playing, step, n, onStep]);
  const s = m.steps[step];
  const worstIdx = m.worst === null ? -1 : m.steps.findIndex(x => x.i === m.worst);
  return (
    <div className="space-y-2 text-[12.5px]" data-motion>
      <div className={cx("flex items-start gap-1.5 rounded border px-2.5 py-1.5", m.colliding_steps.length ? "border-danger/30 bg-danger/5 text-danger" : "border-success/30 bg-success/5 text-success")} data-motion-summary>
        {m.colliding_steps.length ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
        <span>{m.summary}{m.stale ? " The assembly changed since: run it again." : ""}</span>
      </div>
      <div className="flex h-4 gap-px overflow-hidden rounded" aria-label="Collisions per step" data-motion-strip>
        {m.steps.map((x, k) => (
          <button key={x.i} type="button" title={`${fmtV(x.value, m.unit)}${x.collisions.length ? `: ${x.collisions.length} collision${x.collisions.length > 1 ? "s" : ""}, ${x.total_mm3.toFixed(1)} mm³` : ": clear"}`}
            onClick={() => { setPlaying(false); onStep(k); }}
            className={cx("min-w-[3px] flex-1", x.collisions.length ? (k === worstIdx ? "bg-danger" : "bg-danger/60") : "bg-success/35",
              k === step && "outline outline-2 -outline-offset-2 outline-text")} />
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => setPlaying(p => !p)} className="rounded border border-border p-1 hover:bg-text/5" aria-label={playing ? "Pause" : "Play"} data-motion-play>
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}</button>
        <input type="range" min={0} max={n - 1} value={step} onChange={e => { setPlaying(false); onStep(Number(e.target.value)); }}
          className="h-1 flex-1 accent-[rgb(var(--primary))]" aria-label="Motion step" data-motion-scrub />
        <span className="w-24 text-right tabular-nums text-muted">{m.driver_name.replace(/ rotation$/, "")} {fmtV(s.value, m.unit)}</span>
      </div>
      <div className="flex items-center gap-2 text-[11.5px] text-muted">
        <span>Step {step + 1} of {n}</span>
        {worstIdx >= 0 && <button type="button" className="ml-auto text-danger hover:underline" onClick={() => { setPlaying(false); onStep(worstIdx); }} data-motion-worst>
          Worst step: {fmtV(m.steps[worstIdx].value, m.unit)}</button>}
      </div>
      {s.collisions.length > 0 ? (
        <div className="rounded border border-danger/30 px-2.5 py-1.5" data-motion-step-collisions>
          {s.collisions.slice(0, 8).map((c, k) => <div key={k} className="text-danger">{c.a_name} ↔ {c.b_name}: {c.volume_mm3.toFixed(2)} mm³</div>)}
          {s.collisions.length > 8 && <div className="text-muted">and {s.collisions.length - 8} more</div>}
        </div>
      ) : <div className="text-[11.5px] text-success">No collision at this step.</div>}
      {(m.notes ?? []).map((t, k) => <p key={k} className="text-[11px] text-warning">{t}</p>)}
      <p className="text-[11px] text-muted">{m.note}{m.elapsed_s ? ` Checked in ${Math.round(m.elapsed_s)} s.` : ""}</p>
    </div>
  );
}

type Kind = "revolute" | "slider" | "gear";
const AXES: Record<string, V3> = { X: [1, 0, 0], Y: [0, 1, 0], Z: [0, 0, 1] };

function centreOf(view: AsmView, iid: string): V3 {
  const i = view.instances.find(x => x.id === iid);
  const p = i ? view.parts[i.part] : null;
  if (!i || !p) return [0, 0, 0];
  const T = i.T, c = p.center;
  return [T[0] * c[0] + T[1] * c[1] + T[2] * c[2] + T[3], T[4] * c[0] + T[5] * c[1] + T[6] * c[2] + T[7], T[8] * c[0] + T[9] * c[1] + T[10] * c[2] + T[11]];
}

/** Assembly Studio's Motion tab: declare joints, run the sweep, scrub it. */
export function MotionPanel({ view, motion, step, onStep, onAddJoint, onDeleteJoint, onRun, busy }: {
  view: AsmView; motion: MotionResult | null; step: number; onStep: (k: number) => void;
  onAddJoint: (body: Record<string, unknown>) => void; onDeleteJoint: (id: string) => void;
  onRun: (body: { driver?: string; start?: number; end?: number; steps: number }) => void; busy: string | null;
}) {
  const joints: Joint[] = view.joints ?? [];
  const names = useMemo(() => new Map(view.instances.map(i => [i.id, i.display])), [view.instances]);
  const movable = view.instances.filter(i => !i.group);
  const [kind, setKind] = useState<Kind>("revolute");
  const [picked, setPicked] = useState<string[]>([]);
  const [axisFrom, setAxisFrom] = useState<string>("a:Z");
  const [lo, setLo] = useState("");
  const [hi, setHi] = useState("");
  const [ga, setGa] = useState("");
  const [gb, setGb] = useState("");
  const [teeth, setTeeth] = useState(["", ""]);
  const [driver, setDriver] = useState("");
  const [steps, setSteps] = useState("24");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const concentric = view.mates.filter(m => m.type === "concentric");
  const revs = joints.filter(j => j.type === "revolute");
  const movers = joints.filter(j => j.type !== "gear");

  const add = () => {
    if (kind === "gear") {
      const t = teeth.map(Number);
      onAddJoint({ type: "gear", a: ga, b: gb, ...(t[0] > 0 && t[1] > 0 ? { teeth: t } : {}) });
      return;
    }
    const body: Record<string, unknown> = { type: kind, insts: picked };
    if (axisFrom.startsWith("m:")) body.from_mate = axisFrom.slice(2);
    else {
      const d = AXES[axisFrom.slice(2) || "Z"];
      body.dir = d;
      body.p = picked.length ? centreOf(view, picked[0]) : [0, 0, 0];
    }
    if (lo !== "" && hi !== "") body.limits = [Number(lo), Number(hi)];
    onAddJoint(body);
  };

  return (
    <div className="space-y-3 px-4 py-3 text-[12.5px]" data-motion-panel>
      <div>
        <div className="mb-1 font-semibold">Joints</div>
        {joints.length === 0 && <p className="text-muted">No joints yet. A revolute joint turns the parts you pick about an axis; a gear pair turns a second revolute by the tooth ratio; a slider moves parts along a direction.</p>}
        {joints.map(j => (
          <div key={j.id} className="flex items-start gap-1.5 border-b border-border/60 py-1 last:border-0" data-joint={j.type}>
            <RotateCw className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
            <div className="min-w-0 flex-1">
              <div className="font-medium">{j.name}</div>
              <div className="text-[11.5px] text-muted">{j.type === "gear" ? `Gear pair ${j.teeth ? `${j.teeth[0]} : ${j.teeth[1]} teeth` : `ratio ${j.ratio?.toFixed(3)}`}`
                : `${j.type === "revolute" ? "Revolute" : "Slider"} · ${(j.insts ?? []).map(x => names.get(x) ?? x).join(", ")}${j.limits ? ` · ${j.limits[0]} to ${j.limits[1]}${j.type === "revolute" ? "°" : " mm"}` : ""}`}</div>
            </div>
            {view.can_edit && <button type="button" onClick={() => onDeleteJoint(j.id)} className="text-muted hover:text-danger" aria-label="Delete joint"><Trash2 className="h-3.5 w-3.5" /></button>}
          </div>))}
      </div>
      {view.can_edit && (
        <div className="space-y-2 rounded border border-border p-2.5" data-add-joint>
          <Segmented value={kind} onChange={setKind} size="sm" options={[
            { value: "revolute", label: "Revolute" }, { value: "gear", label: "Gear pair", title: "Couple two revolute joints" }, { value: "slider", label: "Slider" }]} />
          {kind === "gear" ? (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                <select className="rounded border border-border bg-panel px-1.5 py-1" value={ga} onChange={e => setGa(e.target.value)} aria-label="Driving joint">
                  <option value="">Driving joint…</option>{revs.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select>
                <select className="rounded border border-border bg-panel px-1.5 py-1" value={gb} onChange={e => setGb(e.target.value)} aria-label="Driven joint">
                  <option value="">Driven joint…</option>{revs.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <Input placeholder="Teeth (driving)" value={teeth[0]} onChange={e => setTeeth([e.target.value, teeth[1]])} />
                <Input placeholder="Teeth (driven)" value={teeth[1]} onChange={e => setTeeth([teeth[0], e.target.value])} />
              </div>
              <p className="text-[11px] text-muted">Leave the teeth empty to read them from the gears on the two joints.</p>
            </>
          ) : (
            <>
              <div className="max-h-32 overflow-y-auto rounded border border-border/70 px-1.5 py-1">
                {movable.map(i => (
                  <label key={i.id} className="flex items-center gap-1.5 py-0.5">
                    <input type="checkbox" checked={picked.includes(i.id)} onChange={e => setPicked(p => e.target.checked ? [...p, i.id] : p.filter(x => x !== i.id))} />
                    <span className="truncate">{i.display}</span></label>))}
              </div>
              <select className="w-full rounded border border-border bg-panel px-1.5 py-1" value={axisFrom} onChange={e => setAxisFrom(e.target.value)} aria-label="Axis">
                {kind === "revolute" && concentric.map(m => <option key={m.id} value={`m:${m.id}`}>Axis of {m.a_name} ↔ {m.b_name} (concentric)</option>)}
                {["Z", "X", "Y"].map(a => <option key={a} value={`a:${a}`}>{kind === "revolute" ? `${a} axis through the first part's centre` : `Along ${a}`}</option>)}
              </select>
              <div className="grid grid-cols-2 gap-1.5">
                <Input placeholder={kind === "revolute" ? "From (°, optional)" : "From (mm)"} value={lo} onChange={e => setLo(e.target.value)} />
                <Input placeholder={kind === "revolute" ? "To (°, optional)" : "To (mm)"} value={hi} onChange={e => setHi(e.target.value)} />
              </div>
            </>
          )}
          <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} loading={busy === "joint"} onClick={add}
            disabled={kind === "gear" ? !ga || !gb : !picked.length}>Add joint</Button>
        </div>
      )}
      {movers.length > 0 && (
        <div className="space-y-2 rounded border border-border p-2.5">
          <div className="font-semibold">Check motion</div>
          <select className="w-full rounded border border-border bg-panel px-1.5 py-1" value={driver} onChange={e => setDriver(e.target.value)} aria-label="Driving joint">
            {movers.map(j => <option key={j.id} value={j.id}>Drive {j.name}</option>)}</select>
          <div className="grid grid-cols-3 gap-1.5">
            <Input placeholder="From" value={from} onChange={e => setFrom(e.target.value)} aria-label="From" />
            <Input placeholder="To" value={to} onChange={e => setTo(e.target.value)} aria-label="To" />
            <Input placeholder="Steps" value={steps} onChange={e => setSteps(e.target.value)} aria-label="Steps" />
          </div>
          <Button size="sm" icon={<RotateCw className="h-3.5 w-3.5" />} loading={busy === "motion"} data-run-motion
            onClick={() => onRun({ driver: driver || movers[0].id, steps: Math.max(2, Math.min(120, Number(steps) || 24)),
              ...(from !== "" ? { start: Number(from) } : {}), ...(to !== "" ? { end: Number(to) } : {}) })}>Check motion</Button>
          <p className="text-[11px] text-muted">Default range: the joint's limits, or one full turn. Each step is an exact clash check, so many steps take longer.</p>
        </div>
      )}
      {motion && <MotionScrubber m={motion} step={step} onStep={onStep} />}
    </div>
  );
}
