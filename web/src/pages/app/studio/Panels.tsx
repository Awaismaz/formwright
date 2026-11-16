import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Bot, Box, ChevronRight, ChevronsDown, Crosshair, Download, Eye, EyeOff, FileText, GitCompare, Hand, MessageSquarePlus, MoreHorizontal, Pencil, PenLine, ScanSearch, SlidersHorizontal, Sparkles, Square, TextCursorInput, Trash2, TriangleAlert, Undo2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { BuildStatus, CheckResult, ManualFeature, Project, RepairItem } from "@/lib/types";
import { ago, cx, num } from "@/lib/format";
import { Badge, Button, Input, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Toggle, Tip } from "@/components/ui";
import type { Topo } from "@/viewer/types";
import { FEATURE_LABEL, type RefPlane } from "@/viewer/planes";
import ChangeNotice from "./ChangeNotice";
import HandoffCard from "./HandoffCard";
import VariantsBar from "./Variants";

/* ------------------------------------------------------------------ checks */
const CHECK_TITLE: Record<string, string> = { "CHK-02": "Valid solid", "CHK-03": "Closed (watertight)", "CHK-04": "Overall size", "CHK-05": "Volume",
  "CHK-06": "Holes and cylinders", "CHK-07": "STEP round trip", "CHK-08": "Repeatable rebuild", "CHK-09": "Matches the imported part" };
const n3 = (v: unknown) => (typeof v === "number" ? num(v, Math.abs(v) >= 100 ? 2 : 3) : String(v));
const pct = (v: unknown) => (typeof v === "number" ? (v < 1e-6 ? "< 0.0001 %" : `${+(v * 100).toPrecision(2)} %`) : "—");
const dims = (v: unknown) => (Array.isArray(v) ? v.map(x => n3(x)).join(" × ") : "—");

/** One check as a sentence an engineer reads (raw values stay in the tooltip). */
export function checkSentence(c: CheckResult): string {
  const d = c.detail as Record<string, unknown>;
  switch (c.id) {
    case "CHK-02": { const n = Number(d.solids ?? 0); return `${n} solid${n === 1 ? "" : "s"}, ${d.is_valid ? "valid geometry" : "invalid geometry"}${d.expected != null && d.expected !== n ? ` (expected ${d.expected})` : ""}`; }
    case "CHK-03": { const n = Number(d.free_or_nonmanifold_edges ?? 0); return n === 0 ? "Watertight: every edge joins exactly two faces" : `${n} open or non-manifold edge${n === 1 ? "" : "s"}`; }
    case "CHK-04": return d.expected_mm ? `${dims(d.got_mm)} mm vs the stated ${dims(d.expected_mm)} mm (largest difference ${n3(d.max_err_mm)} mm)` : `${dims(d.got_mm)} mm (the design states no size to compare)`;
    case "CHK-05": return d.expected_mm3 !== undefined ? `${n3(d.got_mm3)} mm³ vs the stated ${n3(d.expected_mm3)} mm³ (difference ${pct(d.rel_err)})` : `${n3(d.got_mm3)} mm³ (the design states no volume to compare)`;
    case "CHK-06": return c.passed ? "Cylinder count by radius as stated" : "Cylinder count by radius differs from the design's statement";
    case "CHK-07": return d.pending ? "Being verified in the background…" : c.passed ? `Re-imported STEP is identical (volume difference ${pct(d.volume_rel_err)})` : "The re-imported STEP differs from the model";
    case "CHK-08": return d.note ? "Checked at the last full build (skipped for this quick edit)" : d.fingerprint_equal && d.step_bytes_equal ? "Rebuilt twice: identical geometry and identical STEP file" : "Two rebuilds differ";
    case "CHK-09": return `Differs from the imported original by ${pct(d.rel_err)} of its volume`;
    default: return c.name;
  }
}

export function ChecksPanel({ status }: { status?: BuildStatus }) {
  if (!status) return <p className="p-4 text-sm text-muted">No build yet.</p>;
  if (status.error) return <div className="m-3 rounded-lg border border-danger/40 bg-danger/5 p-3 text-[13px] text-danger"><b>Build failed</b><div className="mt-1 text-[12px]">{status.error_plain ?? "The model couldn't be built."}</div></div>;
  return (
    <div className="space-y-3 p-3" data-tour="checks">
      <div className={cx("rounded-lg px-3 py-2 text-sm font-semibold", status.ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger")}>{status.ok ? "All gating checks pass" : "Some checks fail"}</div>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {(status.checks ?? []).map(c => {
          const raw = Object.entries(c.detail).filter(([k]) => !["original", "reimported"].includes(k)).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("\n");
          const info = !c.gating && /informational/.test(c.name);
          return (
            <li key={c.id} className="px-3 py-2" title={raw}>
              <div className="flex items-center gap-2 text-[13px]">
                <span className={cx("rounded px-1.5 text-[10px] font-bold", c.passed ? "bg-success/12 text-success" : c.gating ? "bg-danger/12 text-danger" : "bg-text/10 text-muted")}>{c.passed ? "PASS" : c.gating ? "FAIL" : "INFO"}</span>
                <span className="font-medium">{CHECK_TITLE[c.id] ?? c.name}</span>
              </div>
              <div className="mt-1 text-[11.5px] text-muted">{checkSentence(c)}</div>
              {info && <div className="mt-0.5 text-[11px] text-muted">For information only: features added by hand, suppressed or deleted aren't in the design's stated values.</div>}
            </li>);
        })}
      </ul>
      <p className="text-[11px] text-muted">Checks prove geometric consistency with the stated expectations — not strength, fit or manufacturability. Engineering sign-off stays with you.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ parameters (smart) */
export function ParamsPanel({ project, status, onChanged, focus, onChangedInfo }: { project: Project; status?: BuildStatus; onChanged: () => void;
  /** a design feature's name: its parameter group is highlighted (Edit from the tree) */
  focus?: string | null;
  /** response of a successful change (undo info, features that need repair) */
  onChangedInfo?: (r: { revision?: number; rev_before?: number | null; repairs?: RepairItem[]; label: string }) => void }) {
  const q = useQuery({ queryKey: ["params", project.id, status?.build_id], queryFn: () => api.get<{ editable: Record<string, number> }>(`/api/projects/${project.id}/params`) });
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(() => { try { return localStorage.getItem("fw_params_auto") !== "0"; } catch { return true; } });
  const timer = useRef<number | null>(null);
  useEffect(() => { setVals({}); }, [status?.build_id]);
  const editable = q.data?.editable ?? {};
  const meta = status?.param_meta ?? {};
  const shown: Record<string, unknown> = status?.params ?? {};
  const dirty = Object.entries(vals).filter(([k, v]) => v !== "" && Number(v) !== editable[k]);

  const apply = async (values: Record<string, number>) => {
    if (!Object.keys(values).length) return;
    if (Object.values(values).some(v => !Number.isFinite(v))) { toast.error("Enter valid numbers"); return; }
    setBusy(true);
    const bad = Object.entries(values).map(([k, v]) => { const m = meta[k] ?? {}; return (m.min !== undefined && v < m.min) || (m.max !== undefined && v > m.max) ? `${m.label ?? k} must be ${m.min}–${m.max}${m.unit ? ` ${m.unit}` : ""}` : null; }).find(Boolean);
    if (bad) { toast.error(bad); return; }
    try {
      const r = await api.post<{ revision: number; rev_before?: number | null; build_s?: number; repairs?: RepairItem[] }>(`/api/projects/${project.id}/params`, { values });
      const label = Object.keys(values).map(k => meta[k]?.label ?? k).join(", ");
      if (r.repairs?.length) toast.warning(`Rebuilt · ${r.repairs.length} feature${r.repairs.length === 1 ? "" : "s"} need${r.repairs.length === 1 ? "s" : ""} repair (see the feature tree)`);
      else toast.success(`Rebuilt and verified · rev ${r.revision}${r.build_s ? ` · ${r.build_s.toFixed(1)} s` : ""}`);
      onChangedInfo?.({ revision: r.revision, rev_before: r.rev_before, repairs: r.repairs, label: `Changed ${label}` });
      onChanged();
    }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Rebuild failed"); setVals({}); }
    finally { setBusy(false); }
  };
  const schedule = (next: Record<string, string>) => {
    if (!auto) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const values = Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== "" && Number(v) !== editable[k]).map(([k, v]) => [k, Number(v)]));
      apply(values);
    }, 650);
  };
  const groups = useMemo(() => {
    const g = new Map<string, string[]>();
    for (const k of Object.keys(shown)) { const gr = meta[k]?.group ?? "Parameters"; g.set(gr, [...(g.get(gr) ?? []), k]); }
    return [...g.entries()];
  }, [shown, meta]);
  // a design feature opened from the tree: its group is the one sharing a word with the feature name
  const words = (focus ?? "").toLowerCase().split(/[^a-z]+/).filter(w => w.length > 2).map(w => w.replace(/e?s$/, ""));
  const focusGroup = focus ? groups.find(([g]) => g.toLowerCase().split(/[^a-z]+/).some(w => words.includes(w.replace(/e?s$/, ""))))?.[0] ?? null : null;
  const focusRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { focusRef.current?.scrollIntoView({ block: "nearest" }); }, [focusGroup]);

  if (!status?.fingerprint) return <p className="p-4 text-sm text-muted">Parameters appear after the first successful build.</p>;
  if (!Object.keys(shown).length) return <p className="p-4 text-sm text-muted">This model doesn't declare any design parameters. Ask the agent to “expose the key dimensions as parameters with limits”.</p>;
  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-muted">Edits rebuild without AI or tokens and are kept only if checks pass.</p>
        <label className="flex shrink-0 items-center gap-1.5 text-[11.5px] text-muted">Auto <Toggle checked={auto} onChange={v => { setAuto(v); try { localStorage.setItem("fw_params_auto", v ? "1" : "0"); } catch { /* */ } }} /></label>
      </div>
      {focus && <p className="rounded-md bg-primary-soft px-2.5 py-1.5 text-[12px] text-primary">{focusGroup ? `Parameters of “${focus}”: ${focusGroup}` : `“${focus}” has no parameter group of its own; all design parameters are below.`}</p>}
      {groups.map(([g, keys]) => (
        <div key={g} ref={g === focusGroup ? focusRef : undefined} className={cx(g === focusGroup && "rounded-lg ring-2 ring-primary/40 ring-offset-2 ring-offset-panel")}>
          <div className="label mb-1">{g}</div>
          <div className="space-y-2">
            {keys.map(k => {
              const m = meta[k] ?? {}; const can = k in editable;
              const cur = vals[k] ?? String(editable[k] ?? shown[k]);
              const hasRange = can && m.min !== undefined && m.max !== undefined;
              return (
                <div key={k} className="rounded-md border border-border px-2.5 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[12.5px]" title={m.help ?? (m.label ? `${m.label} (${k} in the design)` : k)}>{m.label ?? k.replace(/_/g, " ").toLowerCase().replace(/^\w/, c => c.toUpperCase())}</span>
                    {can ? <span className="flex items-center gap-1"><Input className={cx("h-7 w-20 text-right font-mono text-[12px]", ((m.min !== undefined && Number(cur) < m.min) || (m.max !== undefined && Number(cur) > m.max)) && "border-danger text-danger")} value={cur} inputMode="decimal" disabled={busy}
                        title={m.min !== undefined && m.max !== undefined ? `${m.min}–${m.max}${m.unit ? ` ${m.unit}` : ""}` : undefined}
                        onChange={e => setVals({ ...vals, [k]: e.target.value })} onBlur={() => schedule(vals)} onKeyDown={e => e.key === "Enter" && schedule(vals)} />
                        {m.unit && <span className="w-6 text-[11px] text-muted">{m.unit}</span>}</span>
                      : <Tip content="Derived value — ask the agent to change it" side="left"><span className="font-mono text-[12px] text-muted">{String(shown[k])}</span></Tip>}
                  </div>
                  {hasRange && <input type="range" min={m.min} max={m.max} step={m.step ?? (m.max! - m.min!) / 200} value={Number(cur)} disabled={busy}
                    onChange={e => setVals({ ...vals, [k]: e.target.value })} onPointerUp={() => schedule(vals)} onKeyUp={() => schedule(vals)} className="mt-1 w-full" aria-label={m.label ?? k} />}
                  {hasRange && <div className="flex justify-between text-[10px] text-muted"><span>{m.min}</span><span>{m.max}</span></div>}
                </div>);
            })}
          </div>
        </div>))}
      {!auto && <Button size="sm" className="w-full" icon={<Wand2 className="h-4 w-4" />} disabled={!dirty.length || project.agent?.busy} loading={busy}
        onClick={() => apply(Object.fromEntries(dirty.map(([k, v]) => [k, Number(v)])))}>Apply & rebuild ({dirty.length})</Button>}
      {busy && <div className="text-center text-[12px] text-primary">Rebuilding and verifying…</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ mass properties */
interface Material { code: string; name: string; group: string; density_g_cm3: number }
const IU = { "kg·mm²": 1, "g·mm²": 1000, "kg·m²": 1e-6 } as const;
export function MassPanel({ project, status, showCom, onShowCom }: { project: Project; status?: BuildStatus; showCom: boolean; onShowCom: (v: boolean) => void }) {
  const mats = useQuery({ queryKey: ["materials"], queryFn: () => api.get<{ items: Material[]; source_note: string }>("/api/materials"), staleTime: Infinity });
  const settings = useQuery({ queryKey: ["settings", project.id], queryFn: () => api.get<{ material?: string; material_guess?: string; custom_density_g_cm3?: number }>(`/api/projects/${project.id}/settings`) });
  const [custom, setCustom] = useState("");
  const [iu, setIu] = useState<keyof typeof IU>("kg·mm²");
  if (!status?.mass) return <p className="p-4 text-sm text-muted">Mass properties appear after a successful build.</p>;
  const chosen = settings.data?.material ?? settings.data?.material_guess;
  const code = chosen ?? "al_6061";
  const mat = mats.data?.items.find(m => m.code === code);
  const density = code === "custom" ? settings.data?.custom_density_g_cm3 ?? 1 : mat?.density_g_cm3 ?? 1;
  const kgPerMm3 = density * 1e-6;
  const mass = status.mass.volume_mm3 * kgPerMm3;
  const I = status.mass.inertia_com_mm5.map(r => r.map(v => v * kgPerMm3));
  const fmtI = (kgmm2: number) => { const v = kgmm2 * IU[iu]; const a = Math.abs(v); return a < 5e-13 ? "0" : a >= 1000 ? num(v, 1) : a >= 1 ? num(v, 3) : v.toPrecision(4); };
  const save = async (body: Record<string, unknown>) => {
    try { await api.patch(`/api/projects/${project.id}/settings`, body); settings.refetch(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const groups = [...new Set(mats.data?.items.map(m => m.group))];
  return (
    <div className="space-y-4 p-3 text-[13px]">
      <div>
        <div className="label mb-1">Material</div>
        <select className="input" value={chosen ?? ""} onChange={e => save({ material: e.target.value })}>
          {!chosen && <option value="" disabled>No material: pick one</option>}
          {groups.map(g => <optgroup key={g} label={g}>{mats.data!.items.filter(m => m.group === g).map(m => <option key={m.code} value={m.code}>{m.name} — {m.density_g_cm3} g/cm³</option>)}</optgroup>)}
          <option value="custom">Custom density…</option>
        </select>
        {code === "custom" && <div className="mt-2 flex gap-2"><Input placeholder={String(density)} value={custom} onChange={e => setCustom(e.target.value)} inputMode="decimal" />
          <Button size="sm" variant="secondary" onClick={() => save({ material: "custom", custom_density_g_cm3: Number(custom) })}>Set g/cm³</Button></div>}
        {!settings.data?.material && settings.data?.material_guess && <p className="mt-1 text-[11px] text-muted">Guessed from the model's material “{status.material}”. Pick one to confirm.</p>}
        {!chosen && <p className="mt-1 text-[11px] text-warning">No material chosen yet: mass below is at 6061 aluminium density, for orientation only.</p>}
      </div>
      <div className="rounded-lg border border-border">
        {[["Mass", chosen ? (mass >= 1 ? `${num(mass, 4)} kg` : `${num(mass * 1000, 2)} g`) : `≈ ${mass >= 1 ? `${num(mass, 3)} kg` : `${num(mass * 1000, 1)} g`} (no material)`, !!chosen], ["Volume", `${num(status.mass.volume_mm3, 2)} mm³`], ["Surface area", `${num(status.mass.area_mm2, 2)} mm²`], ["Density", chosen ? `${density} g/cm³` : "—"]].map(([l, v, p]) => (
          <div key={l as string} className="flex justify-between border-b border-border px-3 py-1.5 last:border-0"><span className="text-muted">{l as string}</span><span className={cx("tabular-nums", p ? "font-semibold text-primary" : "")}>{v as string}</span></div>))}
      </div>
      <div>
        <div className="flex items-center justify-between"><div className="label">Centre of mass (mm)</div>
          <label className="flex items-center gap-1.5 text-[11.5px] text-muted"><Crosshair className="h-3.5 w-3.5" />Show <Toggle checked={showCom} onChange={onShowCom} /></label></div>
        <div className="mt-1 grid grid-cols-3 gap-1.5 font-mono text-[12px]">{status.mass.com_mm.map((v, i) => <div key={i} className="rounded bg-panel2 px-2 py-1 text-center">{"XYZ"[i]} {v.toFixed(3)}</div>)}</div>
      </div>
      <div>
        <div className="flex items-center justify-between"><div className="label">Moments of inertia at CoM</div>
          <select value={iu} onChange={e => setIu(e.target.value as keyof typeof IU)} className="rounded border border-border bg-panel px-1 text-[11px]" aria-label="Inertia unit">{Object.keys(IU).map(u => <option key={u}>{u}</option>)}</select></div>
        <table className="mt-1 w-full font-mono text-[11px]"><tbody>{I.map((r, i) => <tr key={i}><td className="pr-1 text-muted">{"XYZ"[i]}</td>{r.map((v, j) => <td key={j} className="px-1 py-0.5 text-right tabular-nums">{fmtI(v)}</td>)}</tr>)}</tbody></table>
        <div className="mt-1 text-[11px] text-muted">Principal moments ({iu}): {status.mass.principal_mm5.map(v => fmtI(v * kgPerMm3)).join(" · ")}</div>
      </div>
      <p className="text-[11px] text-muted">{mats.data?.source_note}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ feature tree */
export interface RecFeature { id: string; name: string; kind: string; count?: number; params: Record<string, unknown>; faces: number[] }
export interface Recognition {
  build_id?: number; faces: number; summary: string[]; features: RecFeature[];
  component: { kind: string; name: string; params: Record<string, unknown> } | null;
  ai?: { component: { name?: string; kind?: string; standard?: string; confidence?: string; description?: string } | null;
         features: { id: string; name: string; kind: string; note: string; params: Record<string, unknown> }[] };
}

const fmtParams = (p: Record<string, unknown>) => Object.entries(p).filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
  .slice(0, 4).map(([k, v]) => `${k.replace(/_/g, " ")} ${typeof v === "number" ? +v.toFixed(3) : String(v)}`).join(" · ");

/** SOLIDWORKS-style rollback bar: the features below it stay in the tree but are not built; new features go in here. */
function RollbackBar({ busy, hidden, canUp, onUp, onDown, onEnd }: { busy: boolean; hidden: number; canUp: boolean; onUp: () => void; onDown: () => void; onEnd: () => void }) {
  return (
    <li className="my-1 flex items-center gap-1 rounded border-y-2 border-primary bg-primary-soft/60 px-2 py-0.5 text-[11.5px] text-primary" data-rollback-bar>
      <Undo2 className="h-3.5 w-3.5 shrink-0" /><span className="flex-1 truncate">Rolled back · {hidden} feature{hidden === 1 ? "" : "s"} below not built</span>
      <Tip content="Move the bar up one feature" side="top"><button disabled={busy || !canUp} onClick={onUp} className="rounded p-0.5 hover:bg-primary/10 disabled:opacity-30" aria-label="Roll back one more"><ArrowUp className="h-3.5 w-3.5" /></button></Tip>
      <Tip content="Move the bar down one feature" side="top"><button disabled={busy} onClick={onDown} className="rounded p-0.5 hover:bg-primary/10 disabled:opacity-30" aria-label="Roll forward one"><ArrowDown className="h-3.5 w-3.5" /></button></Tip>
      <Tip content="Roll forward to the end (build every feature)" side="top"><button disabled={busy} onClick={onEnd} className="rounded p-0.5 hover:bg-primary/10 disabled:opacity-30" aria-label="Roll to end"><ChevronsDown className="h-3.5 w-3.5" /></button></Tip>
    </li>);
}

export function TreePanel({ status, topo, manual, onHover, onEdit, onToggle, onMove, onDelete, busy, recognition, onRecognize, recognizing, onSketchPlane,
  selectedFeatures = [], onPickFeature, onSuppressDesign, onDeleteDesign, agentBusy = false, onSketchOn, onPreviewPlane, onRename, onRollback,
  onEditParams, onAskRepair }: {
  status?: BuildStatus; topo: Topo | null; manual: ManualFeature[]; busy: boolean;
  onHover: (faces: number[]) => void; onEdit: (f: ManualFeature) => void;
  onToggle: (f: ManualFeature) => void; onMove: (f: ManualFeature, dir: -1 | 1) => void; onDelete: (f: ManualFeature) => void;
  /** ai=false: the free geometric pass only; ai=true: also let the design agent classify (uses tokens) */
  recognition: Recognition | null; onRecognize: (ai: boolean) => void; recognizing: boolean; onSketchPlane: (p: RefPlane) => void;
  /** a design feature's parameters (no AI) and the repair prompt for a feature that no longer rebuilds */
  onEditParams?: (name: string) => void; onAskRepair?: (f: ManualFeature, why: string) => void;
  /** Design (agent-built) feature actions: pick as a chat reference, suppress/restore without AI, delete via the agent. */
  selectedFeatures?: string[]; onPickFeature?: (name: string) => void;
  onSuppressDesign?: (name: string, suppressed: boolean) => void; onDeleteDesign?: (name: string) => void; agentBusy?: boolean;
  /** Reference planes and sketch nodes: open a sketch on a plane; show either in the viewer while hovered. */
  onSketchOn?: (f: ManualFeature) => void; onPreviewPlane?: (f: ManualFeature | null) => void;
  /** Manual features: rename (double-click) and move the rollback bar (null = roll forward to the end). */
  onRename?: (f: ManualFeature, name: string) => void; onRollback?: (beforeId: string | null) => void;
}) {
  const [openMenu, setOpenMenu] = useState<string | null>(null); // right-click opens the row's menu
  const [renaming, setRenaming] = useState<{ id: string; text: string } | null>(null);
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rb = manual.findIndex(f => f.rolled_back); // rollback bar sits just above this row (-1: at the end)
  const commitRename = (f: ManualFeature) => {
    const t = renaming?.text.trim(); setRenaming(null);
    if (t && t !== f.name) onRename?.(f, t);
  };
  const modelFeats = (status?.features ?? []).filter(f => f.kind !== "manual" && f.kind !== "edit");
  const facesOf = (name: string) => topo ? topo.faces.filter(f => f.feature === name).map(f => f.id) : [];
  const ai = recognition?.ai;
  const aiName = (id: string) => ai?.features.find(f => f.id === id);
  const comp = ai?.component?.name ? ai.component : recognition?.component;
  const recFeats = (recognition?.features ?? []).filter(f => f.kind !== "body");
  const extraAi = (ai?.features ?? []).filter(f => !recognition?.features.some(r => r.id === f.id));
  const imported = !!(status as { imported?: boolean } | undefined)?.imported;
  const broken = new Map((status?.manual_errors ?? []).map(m => [m.id, m.error]));
  const faces = (n: number) => `${n} face${n === 1 ? "" : "s"}`;
  return (
    <div className="p-3 text-[13px]">
      <div className="mb-2 flex items-center gap-2">
        <span className="label flex-1">Feature tree</span>
        <Menu>
          <MenuTrigger asChild><Button size="sm" variant="secondary" loading={recognizing} disabled={busy || !status?.fingerprint} icon={<ScanSearch className="h-3.5 w-3.5 text-primary" />}>Recognise</Button></MenuTrigger>
          <MenuContent>
            <MenuItem icon={<ScanSearch className="h-4 w-4" />} onSelect={() => onRecognize(false)}>Recognise features <span className="ml-1 text-[11px] text-muted">free, geometric</span></MenuItem>
            <MenuItem icon={<Sparkles className="h-4 w-4" />} onSelect={() => onRecognize(true)}>Also classify with AI <span className="ml-1 text-[11px] text-muted">uses tokens</span></MenuItem>
          </MenuContent>
        </Menu>
      </div>
      <ul className="mb-2 space-y-0.5 border-b border-border pb-2">
        <li className="flex items-center gap-2 px-2 py-0.5 text-muted"><Crosshair className="h-3.5 w-3.5 shrink-0" /><span className="flex-1">Origin</span></li>
        {(["Front", "Top", "Right"] as RefPlane[]).map(n => (
          <li key={n}><Tip content={`Sketch on the ${n} Plane`} side="right"><button disabled={busy} onClick={() => onSketchPlane(n)} className="flex w-full items-center gap-2 rounded px-2 py-0.5 text-left hover:bg-primary-soft disabled:opacity-50">
            <Square className="h-3.5 w-3.5 shrink-0 -skew-x-12 text-primary/70" /><span className="flex-1">{n} Plane</span></button></Tip></li>))}
      </ul>
      {modelFeats.length === 0 ? (manual.length || !status?.fingerprint ? null : <p className="text-[12px] text-muted">No named features recorded for this model yet. Use <b>Recognise</b> to find its holes, pockets and fillets.</p>) :
        <ul className="space-y-0.5">{modelFeats.map((f, i) => {
          const blank = f.kind === "blank";
          const n = facesOf(f.name).length;
          const sup = !!f.suppressed;
          const canSup = f.kind === "feature" && (!!f.chain || sup);
          const picked = selectedFeatures.includes(f.name);
          const label = aiName(f.name)?.name ?? f.name;
          return (
            <li key={i} onMouseEnter={() => onHover(sup ? [] : facesOf(f.name))} onMouseLeave={() => onHover([])} onContextMenu={ev => { ev.preventDefault(); setOpenMenu(`d:${f.name}`); }}
              onDoubleClick={() => !blank && onEditParams?.(f.name)}
              className={cx("group flex items-center gap-1.5 rounded px-2 py-1 hover:bg-primary-soft", picked && "bg-accent/10 ring-1 ring-accent/40", sup && "opacity-55")}>
              {blank ? <Box className="h-3.5 w-3.5 shrink-0 text-muted" /> : imported ? <ScanSearch className="h-3.5 w-3.5 shrink-0 text-primary" /> : <Bot className="h-3.5 w-3.5 shrink-0 text-muted" />}
              <button onClick={() => onPickFeature?.(f.name)} disabled={!onPickFeature}
                className={cx("flex-1 truncate text-left", (blank || sup) && "italic", sup && "line-through decoration-muted/60")}
                title={blank ? "Exact imported solid. Geometry not resolved into features stays here; it can still be edited by the design agent or with manual features."
                  : `${fmtParams(f.params) ? fmtParams(f.params) + " · " : ""}Click to reference it in the design agent chat · double-click to edit its parameters`}>
                {label}</button>
              <span className="text-[10.5px] text-muted">{sup ? "suppressed" : faces(n)}</span>
              {/* fixed slots: hovering never moves a button under the cursor (STU-02) */}
              <span className="flex w-[19px] justify-center">{canSup && <Tip content={sup ? "Unsuppress (no AI)" : "Suppress (no AI)"} side="left">
                <button disabled={busy || agentBusy} onClick={() => onSuppressDesign?.(f.name, !sup)} className={cx("rounded p-0.5 text-muted hover:text-text disabled:opacity-30", !sup && "invisible group-hover:visible")} aria-label={sup ? `Unsuppress ${f.name}` : `Suppress ${f.name}`}>
                  {sup ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button></Tip>}</span>
              <Menu open={openMenu === `d:${f.name}`} onOpenChange={o => setOpenMenu(o ? `d:${f.name}` : null)}>
                <MenuTrigger asChild><button className="invisible rounded p-0.5 text-muted hover:text-text group-hover:visible data-[state=open]:visible" aria-label={`Actions for ${f.name}`}><MoreHorizontal className="h-3.5 w-3.5" /></button></MenuTrigger>
                <MenuContent>
                  <MenuLabel>{label}</MenuLabel>
                  {!blank && onEditParams && <MenuItem icon={<SlidersHorizontal className="h-4 w-4" />} onSelect={() => onEditParams(f.name)}>Edit parameters <span className="ml-1 text-[11px] text-muted">no AI</span></MenuItem>}
                  <MenuItem icon={<MessageSquarePlus className="h-4 w-4" />} onSelect={() => onPickFeature?.(f.name)}>{picked ? "Remove from chat" : "Ask the design agent about it"}</MenuItem>
                  {f.kind === "feature" && (canSup
                    ? <MenuItem icon={sup ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />} onSelect={() => onSuppressDesign?.(f.name, !sup)}>{sup ? "Unsuppress" : "Suppress"} <span className="ml-1 text-[11px] text-muted">no AI</span></MenuItem>
                    : <div className="px-2 py-1.5 text-[11.5px] text-muted">Base feature: can't be suppressed</div>)}
                  {canSup && <MenuSeparator />}
                  {canSup && <MenuItem danger icon={<Trash2 className="h-4 w-4" />} onSelect={() => onDeleteDesign?.(f.name)}>Delete… <span className="ml-1 text-[11px] text-muted">no AI</span></MenuItem>}
                </MenuContent>
              </Menu>
            </li>);
        })}</ul>}

      {recognition && (
        <div className="mt-4 rounded-lg border border-border bg-panel2/60 p-2.5">
          <div className="label mb-1 flex items-center gap-1"><ScanSearch className="h-3.5 w-3.5" />Recognised {ai ? <Badge tone="primary" className="ml-1">AI</Badge> : <Badge className="ml-1">geometry</Badge>}</div>
          {comp?.name && <div className="mb-1.5 rounded bg-panel px-2 py-1.5">
            <div className="font-medium">{comp.name}</div>
            {ai?.component?.description && <div className="text-[11.5px] text-muted">{ai.component.description}</div>}
            {ai?.component?.confidence && <div className="text-[11px] text-muted">Confidence: {ai.component.confidence}{ai.component.standard ? ` · ${ai.component.standard}` : ""}</div>}
          </div>}
          <ul className="space-y-0.5">
            {recFeats.map(f => {
              const a = aiName(f.id);
              const unrec = f.kind === "unrecognised";
              return (
                <li key={f.id} onMouseEnter={() => onHover(f.faces)} onMouseLeave={() => onHover([])} className="rounded px-2 py-1 hover:bg-primary-soft">
                  <div className="flex items-center gap-2"><span className={cx("flex-1 truncate", unrec && "text-warning")}>{a?.name ?? (unrec ? `Imported blank (unresolved, ${faces(f.faces.length)})` : f.name.replace(/\((\d+) faces\)/, (_m, k: string) => `(${faces(Number(k))})`).replace(/face\(s\)/, "faces"))}</span>
                    <span className="text-[10.5px] text-muted">{faces(f.faces.length)}</span></div>
                  {(a?.note || Object.keys(a?.params ?? f.params).length > 0) && <div className="truncate text-[11px] text-muted" title={a?.note}>{a?.note || fmtParams(a?.params ?? f.params)}</div>}
                </li>);
            })}
            {extraAi.map(f => <li key={f.id} className="rounded px-2 py-1"><div className="truncate">{f.name}</div>
              {(f.note || Object.keys(f.params).length > 0) && <div className="truncate text-[11px] text-muted" title={f.note}>{f.note || fmtParams(f.params)}</div>}</li>)}
          </ul>
          <p className="mt-1.5 text-[11px] text-muted">Hover to highlight. Ask the design agent to change any of these — it edits the exact solid even where features are unresolved.</p>
        </div>)}

      {/* one tree in build order: the design's steps above, then the features added by hand (STU-14) */}
      {manual.length === 0 ? <p className="mt-3 text-[12px] text-muted">{status?.fingerprint ? "Add features from the command bar (Features / Sketch). They appear here in build order and stay editable." : "Start a part by hand: click a plane above (or Extruded / Revolved Boss in the command bar), sketch a closed profile and extrude or revolve it."}</p> :
        <ul className={cx("space-y-0.5", modelFeats.length > 0 && "mt-0.5")}>{manual.map((f, i) => {
          const key = `m:${f.id}`; const rolled = !!f.rolled_back; const why = !f.suppressed && !rolled ? broken.get(f.id) : undefined;
          return (<Fragment key={f.id}>
          {i === rb && onRollback && <RollbackBar busy={busy} hidden={manual.length - rb} onUp={() => onRollback(manual[rb - 1]?.id ?? manual[0]!.id)} canUp={rb > 0}
            onDown={() => onRollback(manual[rb + 1]?.id ?? null)} onEnd={() => onRollback(null)} />}
          <li onMouseEnter={() => (rolled ? undefined : f.op === "plane" || f.op === "sketch2d" ? onPreviewPlane?.(f) : onHover(f.suppressed ? [] : facesOf(f.name)))} onMouseLeave={() => (f.op === "plane" || f.op === "sketch2d" ? onPreviewPlane?.(null) : onHover([]))}
            onContextMenu={ev => { ev.preventDefault(); setOpenMenu(key); }}
            className={cx("group flex items-center gap-1 rounded px-2 py-1 hover:bg-primary-soft", f.suppressed && "opacity-50", rolled && "opacity-45", why && "bg-warning/10")}>
            {why ? <Tip content={`Rebuild error: ${why}`} side="right"><TriangleAlert className="h-3.5 w-3.5 shrink-0 text-warning" aria-label="Rebuild error" /></Tip>
              : f.op === "plane" ? <Square className="h-3.5 w-3.5 shrink-0 -skew-x-12 text-primary/70" />
              : f.op === "sketch2d" ? <PenLine className="h-3.5 w-3.5 shrink-0 text-primary/70" />
              : <Hand className="h-3.5 w-3.5 shrink-0 text-muted" aria-label="Added by hand" />}
            {renaming?.id === f.id
              ? <Input autoFocus value={renaming.text} onChange={ev => setRenaming({ id: f.id, text: ev.target.value })} onBlur={() => commitRename(f)} aria-label="Feature name"
                  onKeyDown={ev => { if (ev.key === "Enter") commitRename(f); if (ev.key === "Escape") setRenaming(null); }} className="h-6 flex-1 px-1.5 text-[13px]" />
              : <button className={cx("flex-1 truncate text-left", rolled && "italic", why && "text-warning")} disabled={busy} title={why ? `Doesn't rebuild: ${why}. Click to repair.` : "Click to edit · double-click to rename · right-click for more"}
                  onClick={() => { if (clickTimer.current) clearTimeout(clickTimer.current); clickTimer.current = setTimeout(() => onEdit(f), 230); }}
                  onDoubleClick={() => { if (clickTimer.current) clearTimeout(clickTimer.current); if (onRename) setRenaming({ id: f.id, text: f.name }); }}>
                  {f.name} <Badge className="ml-1">{f.op === "sketch" && f.mode === "cut" ? "Cut" : FEATURE_LABEL[f.op] ?? f.op}</Badge></button>}
            {f.op === "plane" && onSketchOn && <Tip content={`Sketch on ${f.name}`} side="left"><button disabled={busy} onClick={() => onSketchOn(f)} className="rounded p-0.5 text-muted hover:text-primary" aria-label={`Sketch on ${f.name}`}><PenLine className="h-3.5 w-3.5" /></button></Tip>}
            {/* fixed slots: the eye never moves and nothing destructive appears on hover (STU-02) */}
            <Tip content={f.suppressed ? "Unsuppress" : "Suppress"} side="left"><button disabled={busy} onClick={() => onToggle(f)} className="rounded p-0.5 text-muted hover:text-text" aria-label={f.suppressed ? `Unsuppress ${f.name}` : `Suppress ${f.name}`}>{f.suppressed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button></Tip>
            <button disabled={busy || i === 0} onClick={() => onMove(f, -1)} className="invisible rounded p-0.5 text-muted hover:text-text disabled:opacity-30 group-hover:visible" aria-label="Move up"><ArrowUp className="h-3.5 w-3.5" /></button>
            <button disabled={busy || i === manual.length - 1} onClick={() => onMove(f, 1)} className="invisible rounded p-0.5 text-muted hover:text-text disabled:opacity-30 group-hover:visible" aria-label="Move down"><ArrowDown className="h-3.5 w-3.5" /></button>
            <Menu open={openMenu === key} onOpenChange={o => setOpenMenu(o ? key : null)}>
              <MenuTrigger asChild><button className="invisible rounded p-0.5 text-muted hover:text-text group-hover:visible data-[state=open]:visible" aria-label={`Actions for ${f.name}`}><MoreHorizontal className="h-3.5 w-3.5" /></button></MenuTrigger>
              <MenuContent>
                <MenuLabel>{f.name}</MenuLabel>
                <MenuItem icon={<Pencil className="h-4 w-4" />} onSelect={() => onEdit(f)}>Edit feature</MenuItem>
                {onRename && <MenuItem icon={<TextCursorInput className="h-4 w-4" />} onSelect={() => setTimeout(() => setRenaming({ id: f.id, text: f.name }), 0)}>Rename</MenuItem>}
                {f.op === "plane" && onSketchOn && <MenuItem icon={<PenLine className="h-4 w-4" />} onSelect={() => onSketchOn(f)}>Sketch on this plane</MenuItem>}
                <MenuItem icon={f.suppressed ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />} onSelect={() => onToggle(f)}>{f.suppressed ? "Unsuppress" : "Suppress"}</MenuItem>
                {onRollback && (rolled ? <MenuItem icon={<ChevronsDown className="h-4 w-4" />} onSelect={() => onRollback(manual[i + 1]?.id ?? null)}>Roll forward to after this</MenuItem>
                  : <MenuItem icon={<Undo2 className="h-4 w-4" />} onSelect={() => onRollback(f.id)}>Roll back to before this</MenuItem>)}
                {onRollback && rb >= 0 && <MenuItem icon={<ChevronsDown className="h-4 w-4" />} onSelect={() => onRollback(null)}>Roll to end</MenuItem>}
                <MenuSeparator />
                <MenuItem danger icon={<Trash2 className="h-4 w-4" />} onSelect={() => onDelete(f)}>Delete… <span className="ml-1 text-[11px] text-muted">undo with Ctrl+Z</span></MenuItem>
              </MenuContent>
            </Menu>
          </li>
          {why && <li className="mb-1 ml-6 rounded-md border border-warning/40 bg-warning/5 px-2 py-1.5 text-[11.5px]" data-repair={f.id}>
            <div className="text-text/85">{why[0]!.toUpperCase() + why.slice(1)}.</div>
            <div className="mt-1 flex flex-wrap gap-1">
              <button onClick={() => onEdit(f)} disabled={busy} className="rounded border border-border bg-panel px-2 py-0.5 font-medium hover:border-primary hover:text-primary">{["fillet", "chamfer", "shell", "draft"].includes(f.op) ? "Re-pick" : "Edit"}</button>
              <button onClick={() => onToggle(f)} disabled={busy} className="rounded border border-border bg-panel px-2 py-0.5 font-medium hover:border-primary hover:text-primary">Suppress</button>
              {onAskRepair && <button onClick={() => onAskRepair(f, why)} disabled={busy || agentBusy} className="inline-flex items-center gap-1 rounded border border-border bg-panel px-2 py-0.5 font-medium hover:border-primary hover:text-primary"><Sparkles className="h-3 w-3 text-accent" />Ask the agent to repair</button>}
            </div></li>}
          </Fragment>);
        })}</ul>}
      {(status?.manual_features ?? 0) > 0 && status?.checks?.some(c => c.id === "CHK-05" && (c.detail as Record<string, unknown>)?.expected_mm3 !== undefined) && <p className="mt-3 rounded border border-border bg-panel2 p-2 text-[11px] text-muted">With features added by hand, the size and volume checks are for information only: the design's stated values don't include them.</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ revisions + compare */
export function RevisionsPanel({ project, onChanged, version, onCompare, comparing }: { project: Project; onChanged: () => void; version?: number; onCompare: (n: number) => void; comparing: number | null }) {
  const q = useQuery({ queryKey: ["revisions", project.id, version], queryFn: () => api.get<{ items: { n: number; ok: boolean; error?: string; fingerprint?: { bbox: number[]; volume: number }; created_at: string; why?: string | null; by?: string | null; kind?: string | null }[] }>(`/api/projects/${project.id}/revisions`) });
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<number | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="p-4 text-sm text-muted">Every build becomes a revision you can restore or compare.</p>;
  // consecutive edits made without AI fold into one row (the newest), expandable
  const handEdit = (r: (typeof items)[number]) => r.kind === "manual" || r.kind === "params";
  type Row = { r: (typeof items)[number]; i: number; group?: number; hidden?: boolean };
  const rows: Row[] = [];
  let head: Row | null = null;
  for (let i = 0; i < items.length; i++) {
    const r = items[i]!;
    if (i > 0 && handEdit(r) && head && handEdit(head.r) && head.i > 0) {
      head.group = (head.group ?? 1) + 1; rows.push({ r, i, hidden: !open.has(head.r.n) });
    } else { head = { r, i }; rows.push(head); }
  }
  return (<>
    <VariantsBar project={project} version={version} onCompare={onCompare} onChanged={onChanged} />
    <ul className="divide-y divide-border">
      {rows.filter(x => !x.hidden).map(({ r, i, group }) => (
        <li key={r.n} className={cx("flex items-center gap-2 px-3 py-2.5", comparing === r.n && "bg-primary-soft")}>
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-panel2 text-[11px] font-semibold">{r.n}</span>
          <div className="min-w-0 flex-1 text-[12px]">
            <div className="flex items-center gap-1.5">{r.ok ? <Badge tone="success">Verified</Badge> : <Badge tone="danger">Failed</Badge>}{i === 0 && <Badge tone="primary">Latest</Badge>}</div>
            {r.why && <div className="mt-0.5 line-clamp-2 text-text/85" title={r.why}>{r.why}</div>}
            {group && group > 1 && <button onClick={() => setOpen(s => { const n = new Set(s); if (n.has(r.n)) n.delete(r.n); else n.add(r.n); return n; })}
              className="mt-0.5 inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline"><ChevronRight className={cx("h-3 w-3 transition", open.has(r.n) && "rotate-90")} />{open.has(r.n) ? "Hide" : "Show"} {group - 1} earlier edit{group === 2 ? "" : "s"} without AI</button>}
            <div className="mt-0.5 truncate text-muted">{r.fingerprint ? `${r.fingerprint.bbox.map(n => Math.round(n)).join("×")} mm · ${num(r.fingerprint.volume, 0)} mm³` : "build failed"} · {ago(r.created_at)}{r.by ? ` · ${r.by}` : ""}</div>
          </div>
          <Tip content="Change notice: what changed and why" side="left"><button onClick={() => setNotice(r.n)} className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-primary" aria-label={`Change notice for revision ${r.n}`}><FileText className="h-4 w-4" /></button></Tip>
          {i > 0 && <>
            <Tip content="Compare with current model" side="left"><button onClick={() => onCompare(r.n)} className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-primary" aria-label="Compare"><GitCompare className="h-4 w-4" /></button></Tip>
            <Button size="sm" variant="secondary" loading={busy === r.n} disabled={busy !== null} onClick={async () => {
              setBusy(r.n);
              try { await api.post(`/api/projects/${project.id}/revisions/${r.n}/restore`); toast.success(`Revision ${r.n} restored`); onChanged(); }
              catch (e) { toast.error(e instanceof ApiError ? e.message : "Restore failed"); } finally { setBusy(null); }
            }}>Restore</Button></>}
        </li>))}
      <ChangeNotice projectId={project.id} n={notice} onClose={() => setNotice(null)} />
    </ul>
  </>);
}

/* ------------------------------------------------------------------ files & source */
export function FilesPanel({ project, status }: { project: Project; status?: BuildStatus }) {
  if (!status?.fingerprint) return <p className="p-4 text-sm text-muted">Exports appear after the first successful build.</p>;
  const base = `/api/projects/${project.id}/files`;
  return (
    <div className="space-y-2 p-3">
      <HandoffCard projectId={project.id} version={status.build_id} />
      {[["part.step", "STEP (AP214)", "SOLIDWORKS, Creo, Fusion, Inventor, NX…"], ["part.stl", "STL", "Slicers and quick viewing"], ["part.3mf", "3MF", "Modern 3D-printing format with units"]].map(([f, l, h]) => (
        <a key={f} href={`${base}/${f}`} className="flex items-center gap-3 rounded-lg border border-border p-3 hover:border-primary/50">
          <Download className="h-4 w-4 text-primary" /><div className="flex-1"><div className="text-sm font-medium">{l}</div><div className="text-xs text-muted">{h}</div></div>
        </a>))}
      <Link to={`/app/modules/drawings?project=${project.id}`} className="flex items-center gap-3 rounded-lg border border-border p-3 hover:border-primary/50">
        <FileText className="h-4 w-4 text-primary" /><div className="flex-1"><div className="text-sm font-medium">Drawing PDF / DXF / SVG</div><div className="text-xs text-muted">Generate the drawing sheet in Drawing Studio</div></div>
      </Link>
      <img src={`${base}/views.png?v=${status.build_id}`} alt="Four-view render" className="mt-2 w-full rounded-lg border border-border" />
    </div>
  );
}

export function SourcePanel({ project, version }: { project: Project; version?: number }) {
  const q = useQuery({ queryKey: ["source", project.id, version], queryFn: () => fetch(`/api/projects/${project.id}/source`).then(r => r.text()) });
  if (!q.data) return <p className="p-4 text-sm text-muted">No model source yet.</p>;
  return (<div className="p-3">
    <p className="mb-2 rounded border border-warning/40 bg-warning/10 px-2 py-1 text-[11px]">Support view (superadmins only). Users never see this.</p>
    <pre className="overflow-x-auto rounded-lg border border-border bg-panel2 p-3 font-mono text-[11.5px] leading-relaxed">{q.data}</pre></div>);
}
