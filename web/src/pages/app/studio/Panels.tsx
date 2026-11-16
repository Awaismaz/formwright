import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Bot, Box, Crosshair, Download, Eye, EyeOff, FileText, GitCompare, Lock, MessageSquarePlus, MoreHorizontal, Pencil, ScanSearch, Sparkles, Square, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { BuildStatus, ManualFeature, Project } from "@/lib/types";
import { ago, cx, num } from "@/lib/format";
import { Badge, Button, Input, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Toggle, Tip } from "@/components/ui";
import type { Topo } from "@/viewer/types";
import { FEATURE_LABEL, type RefPlane } from "@/viewer/planes";
import ChangeNotice from "./ChangeNotice";

/* ------------------------------------------------------------------ checks */
export function ChecksPanel({ status }: { status?: BuildStatus }) {
  if (!status) return <p className="p-4 text-sm text-muted">No build yet.</p>;
  if (status.error) return <div className="m-3 rounded-lg border border-danger/40 bg-danger/5 p-3 text-[13px] text-danger"><b>Build failed</b><div className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{status.error}</div></div>;
  return (
    <div className="space-y-3 p-3" data-tour="checks">
      <div className={cx("rounded-lg px-3 py-2 text-sm font-semibold", status.ok ? "bg-success/10 text-success" : "bg-danger/10 text-danger")}>{status.ok ? "All gating checks pass" : "Some checks fail"}</div>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {(status.checks ?? []).map(c => {
          const d = Object.entries(c.detail).filter(([k]) => !["original", "reimported"].includes(k)).slice(0, 4);
          return (
            <li key={c.id} className="px-3 py-2">
              <div className="flex items-center gap-2 text-[13px]">
                <span className={cx("rounded px-1.5 text-[10px] font-bold", c.passed ? "bg-success/12 text-success" : c.gating ? "bg-danger/12 text-danger" : "bg-text/10 text-muted")}>{c.passed ? "PASS" : c.gating ? "FAIL" : "INFO"}</span>
                <span className="font-medium">{c.name}</span>
              </div>
              <div className="mt-1 text-[11px] text-muted">{d.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.map(x => typeof x === "number" ? +x.toFixed(4) : x).join(" × ") : typeof v === "number" ? (Math.abs(v) < 1e-3 && v !== 0 ? v.toExponential(1) : +v.toFixed(4)) : typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(" · ")}</div>
            </li>);
        })}
      </ul>
      <p className="text-[11px] text-muted">Checks prove geometric consistency with the stated expectations — not strength, fit or manufacturability. Engineering sign-off stays with you.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ parameters (smart) */
export function ParamsPanel({ project, status, onChanged }: { project: Project; status?: BuildStatus; onChanged: () => void }) {
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
    try { const r = await api.post<{ revision: number; build_s?: number }>(`/api/projects/${project.id}/params`, { values }); toast.success(`Rebuilt and verified · rev ${r.revision}${r.build_s ? ` · ${r.build_s.toFixed(1)} s` : ""}`); onChanged(); }
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

  if (!status?.fingerprint) return <p className="p-4 text-sm text-muted">Parameters appear after the first successful build.</p>;
  if (!Object.keys(shown).length) return <p className="p-4 text-sm text-muted">This model doesn't declare any design parameters. Ask the agent to “expose the key dimensions as parameters with limits”.</p>;
  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-muted">Edits rebuild without AI or tokens and are kept only if checks pass.</p>
        <label className="flex shrink-0 items-center gap-1.5 text-[11.5px] text-muted">Auto <Toggle checked={auto} onChange={v => { setAuto(v); try { localStorage.setItem("fw_params_auto", v ? "1" : "0"); } catch { /* */ } }} /></label>
      </div>
      {groups.map(([g, keys]) => (
        <div key={g}>
          <div className="label mb-1">{g}</div>
          <div className="space-y-2">
            {keys.map(k => {
              const m = meta[k] ?? {}; const can = k in editable;
              const cur = vals[k] ?? String(editable[k] ?? shown[k]);
              const hasRange = can && m.min !== undefined && m.max !== undefined;
              return (
                <div key={k} className="rounded-md border border-border px-2.5 py-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[12.5px]" title={k}>{m.label ?? k}{m.label && <span className="ml-1 font-mono text-[10px] text-muted">{k}</span>}</span>
                    {can ? <span className="flex items-center gap-1"><Input className="h-7 w-20 text-right font-mono text-[12px]" value={cur} inputMode="decimal" disabled={busy}
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
export function MassPanel({ project, status, showCom, onShowCom }: { project: Project; status?: BuildStatus; showCom: boolean; onShowCom: (v: boolean) => void }) {
  const mats = useQuery({ queryKey: ["materials"], queryFn: () => api.get<{ items: Material[]; source_note: string }>("/api/materials"), staleTime: Infinity });
  const settings = useQuery({ queryKey: ["settings", project.id], queryFn: () => api.get<{ material?: string; material_guess?: string; custom_density_g_cm3?: number }>(`/api/projects/${project.id}/settings`) });
  const [custom, setCustom] = useState("");
  if (!status?.mass) return <p className="p-4 text-sm text-muted">Mass properties appear after a successful build.</p>;
  const code = settings.data?.material ?? settings.data?.material_guess ?? "al_6061";
  const mat = mats.data?.items.find(m => m.code === code);
  const density = code === "custom" ? settings.data?.custom_density_g_cm3 ?? 1 : mat?.density_g_cm3 ?? 1;
  const kgPerMm3 = density * 1e-6;
  const mass = status.mass.volume_mm3 * kgPerMm3;
  const I = status.mass.inertia_com_mm5.map(r => r.map(v => v * kgPerMm3));
  const save = async (body: Record<string, unknown>) => {
    try { await api.patch(`/api/projects/${project.id}/settings`, body); settings.refetch(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const groups = [...new Set(mats.data?.items.map(m => m.group))];
  return (
    <div className="space-y-4 p-3 text-[13px]">
      <div>
        <div className="label mb-1">Material</div>
        <select className="input" value={code} onChange={e => save({ material: e.target.value })}>
          {groups.map(g => <optgroup key={g} label={g}>{mats.data!.items.filter(m => m.group === g).map(m => <option key={m.code} value={m.code}>{m.name} — {m.density_g_cm3} g/cm³</option>)}</optgroup>)}
          <option value="custom">Custom density…</option>
        </select>
        {code === "custom" && <div className="mt-2 flex gap-2"><Input placeholder={String(density)} value={custom} onChange={e => setCustom(e.target.value)} inputMode="decimal" />
          <Button size="sm" variant="secondary" onClick={() => save({ material: "custom", custom_density_g_cm3: Number(custom) })}>Set g/cm³</Button></div>}
        {!settings.data?.material && settings.data?.material_guess && <p className="mt-1 text-[11px] text-muted">Guessed from the model's material “{status.material}”. Pick one to confirm.</p>}
      </div>
      <div className="rounded-lg border border-border">
        {[["Mass", mass >= 1 ? `${num(mass, 4)} kg` : `${num(mass * 1000, 2)} g`, true], ["Volume", `${num(status.mass.volume_mm3, 2)} mm³`], ["Surface area", `${num(status.mass.area_mm2, 2)} mm²`], ["Density", `${density} g/cm³`]].map(([l, v, p]) => (
          <div key={l as string} className="flex justify-between border-b border-border px-3 py-1.5 last:border-0"><span className="text-muted">{l as string}</span><span className={cx("tabular-nums", p ? "font-semibold text-primary" : "")}>{v as string}</span></div>))}
      </div>
      <div>
        <div className="flex items-center justify-between"><div className="label">Centre of mass (mm)</div>
          <label className="flex items-center gap-1.5 text-[11.5px] text-muted"><Crosshair className="h-3.5 w-3.5" />Show <Toggle checked={showCom} onChange={onShowCom} /></label></div>
        <div className="mt-1 grid grid-cols-3 gap-1.5 font-mono text-[12px]">{status.mass.com_mm.map((v, i) => <div key={i} className="rounded bg-panel2 px-2 py-1 text-center">{"XYZ"[i]} {v.toFixed(3)}</div>)}</div>
      </div>
      <div>
        <div className="label">Moments of inertia at CoM (kg·mm²)</div>
        <table className="mt-1 w-full font-mono text-[11px]"><tbody>{I.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="px-1 py-0.5 text-right tabular-nums">{v.toExponential(3)}</td>)}</tr>)}</tbody></table>
        <div className="mt-1 text-[11px] text-muted">Principal: {status.mass.principal_mm5.map(v => (v * kgPerMm3).toExponential(3)).join(", ")}</div>
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

export function TreePanel({ status, topo, manual, onHover, onEdit, onToggle, onMove, onDelete, busy, recognition, onRecognize, recognizing, onSketchPlane,
  selectedFeatures = [], onPickFeature, onSuppressDesign, onDeleteDesign, agentBusy = false }: {
  status?: BuildStatus; topo: Topo | null; manual: ManualFeature[]; busy: boolean;
  onHover: (faces: number[]) => void; onEdit: (f: ManualFeature) => void;
  onToggle: (f: ManualFeature) => void; onMove: (f: ManualFeature, dir: -1 | 1) => void; onDelete: (f: ManualFeature) => void;
  recognition: Recognition | null; onRecognize: () => void; recognizing: boolean; onSketchPlane: (p: RefPlane) => void;
  /** Design (agent-built) feature actions: pick as a chat reference, suppress/restore without AI, delete via the agent. */
  selectedFeatures?: string[]; onPickFeature?: (name: string) => void;
  onSuppressDesign?: (name: string, suppressed: boolean) => void; onDeleteDesign?: (name: string) => void; agentBusy?: boolean;
}) {
  const modelFeats = (status?.features ?? []).filter(f => f.kind !== "manual" && f.kind !== "edit");
  const facesOf = (name: string) => topo ? topo.faces.filter(f => f.feature === name).map(f => f.id) : [];
  const ai = recognition?.ai;
  const aiName = (id: string) => ai?.features.find(f => f.id === id);
  const comp = ai?.component?.name ? ai.component : recognition?.component;
  const recFeats = (recognition?.features ?? []).filter(f => f.kind !== "body");
  const extraAi = (ai?.features ?? []).filter(f => !recognition?.features.some(r => r.id === f.id));
  const imported = !!(status as { imported?: boolean } | undefined)?.imported;
  return (
    <div className="p-3 text-[13px]">
      <div className="mb-2 flex items-center gap-2">
        <span className="label flex-1">Feature tree</span>
        <Tip content="AI looks at standard views and the exact geometry, then classifies the part and its features" side="bottom">
          <Button size="sm" variant="secondary" loading={recognizing} disabled={busy || !status?.fingerprint} icon={<Sparkles className="h-3.5 w-3.5 text-accent" />} onClick={onRecognize}>Recognize features</Button>
        </Tip>
      </div>
      <ul className="mb-2 space-y-0.5 border-b border-border pb-2">
        <li className="flex items-center gap-2 px-2 py-0.5 text-muted"><Crosshair className="h-3.5 w-3.5 shrink-0" /><span className="flex-1">Origin</span></li>
        {(["Front", "Top", "Right"] as RefPlane[]).map(n => (
          <li key={n}><Tip content={`Sketch on the ${n} Plane`} side="right"><button disabled={busy} onClick={() => onSketchPlane(n)} className="flex w-full items-center gap-2 rounded px-2 py-0.5 text-left hover:bg-primary-soft disabled:opacity-50">
            <Square className="h-3.5 w-3.5 shrink-0 -skew-x-12 text-primary/70" /><span className="flex-1">{n} Plane</span></button></Tip></li>))}
      </ul>
      {modelFeats.length === 0 ? (manual.length || !status?.fingerprint ? null : <p className="text-[12px] text-muted">No named features recorded for this model yet — use <b>Recognize features</b>.</p>) :
        <ul className="space-y-0.5">{modelFeats.map((f, i) => {
          const blank = f.kind === "blank";
          const n = facesOf(f.name).length;
          const sup = !!f.suppressed;
          const canSup = f.kind === "feature" && (!!f.chain || sup);
          const picked = selectedFeatures.includes(f.name);
          const label = aiName(f.name)?.name ?? f.name;
          return (
            <li key={i} onMouseEnter={() => onHover(sup ? [] : facesOf(f.name))} onMouseLeave={() => onHover([])}
              className={cx("group flex items-center gap-1.5 rounded px-2 py-1 hover:bg-primary-soft", picked && "bg-accent/10 ring-1 ring-accent/40", sup && "opacity-55")}>
              {blank ? <Box className="h-3.5 w-3.5 shrink-0 text-muted" /> : imported ? <ScanSearch className="h-3.5 w-3.5 shrink-0 text-primary" /> : <Bot className="h-3.5 w-3.5 shrink-0 text-muted" />}
              <button onClick={() => onPickFeature?.(f.name)} disabled={!onPickFeature}
                className={cx("flex-1 truncate text-left", (blank || sup) && "italic", sup && "line-through decoration-muted/60")}
                title={blank ? "Exact imported solid. Geometry not resolved into features stays here; it can still be edited by the design agent or with manual features."
                  : `${fmtParams(f.params) ? fmtParams(f.params) + " · " : ""}Click to reference it in the design agent chat`}>
                {label}</button>
              <span className="text-[10.5px] text-muted group-hover:hidden">{sup ? "suppressed" : `${n} faces`}</span>
              {canSup && <Tip content={sup ? "Unsuppress (no AI)" : "Suppress (no AI)"} side="left">
                <button disabled={busy || agentBusy} onClick={() => onSuppressDesign?.(f.name, !sup)} className={cx("rounded p-0.5 text-muted hover:text-text disabled:opacity-30", !sup && "hidden group-hover:block")} aria-label={sup ? `Unsuppress ${f.name}` : `Suppress ${f.name}`}>
                  {sup ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button></Tip>}
              <Menu>
                <MenuTrigger asChild><button className="hidden rounded p-0.5 text-muted hover:text-text group-hover:block data-[state=open]:block" aria-label={`Actions for ${f.name}`}><MoreHorizontal className="h-3.5 w-3.5" /></button></MenuTrigger>
                <MenuContent>
                  <MenuLabel>{label}</MenuLabel>
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
          <div className="label mb-1 flex items-center gap-1"><ScanSearch className="h-3.5 w-3.5" />Recognized {ai ? <Badge tone="primary" className="ml-1">AI</Badge> : <Badge className="ml-1">geometry</Badge>}</div>
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
                  <div className="flex items-center gap-2"><span className={cx("flex-1 truncate", unrec && "text-warning")}>{a?.name ?? (unrec ? `Imported blank (unresolved, ${f.faces.length} faces)` : f.name)}</span>
                    <span className="text-[10.5px] text-muted">{f.faces.length} faces</span></div>
                  {(a?.note || Object.keys(a?.params ?? f.params).length > 0) && <div className="truncate text-[11px] text-muted" title={a?.note}>{a?.note || fmtParams(a?.params ?? f.params)}</div>}
                </li>);
            })}
            {extraAi.map(f => <li key={f.id} className="rounded px-2 py-1"><div className="truncate">{f.name}</div>
              {(f.note || Object.keys(f.params).length > 0) && <div className="truncate text-[11px] text-muted" title={f.note}>{f.note || fmtParams(f.params)}</div>}</li>)}
          </ul>
          <p className="mt-1.5 text-[11px] text-muted">Hover to highlight. Ask the design agent to change any of these — it edits the exact solid even where features are unresolved.</p>
        </div>)}

      <div className="label mb-1 mt-4 flex items-center gap-1"><Pencil className="h-3.5 w-3.5" />Manual features</div>
      {manual.length === 0 ? <p className="text-[12px] text-muted">{status?.fingerprint ? "Use the command bar (Features / Sketch) to add features by hand. They stay editable here." : "Start a part by hand: click a plane above (or Extruded / Revolved Boss in the command bar), sketch a closed profile and extrude or revolve it."}</p> :
        <ul className="space-y-0.5">{manual.map((f, i) => (
          <li key={f.id} onMouseEnter={() => onHover(f.suppressed ? [] : facesOf(f.name))} onMouseLeave={() => onHover([])}
            className={cx("group flex items-center gap-1 rounded px-2 py-1 hover:bg-primary-soft", f.suppressed && "opacity-50")}>
            <button className="flex-1 truncate text-left" onClick={() => onEdit(f)} disabled={busy}>{f.name} <Badge className="ml-1">{f.op === "sketch" && f.mode === "cut" ? "Cut" : FEATURE_LABEL[f.op] ?? f.op}</Badge></button>
            <Tip content={f.suppressed ? "Unsuppress" : "Suppress"} side="left"><button disabled={busy} onClick={() => onToggle(f)} className="rounded p-0.5 text-muted hover:text-text">{f.suppressed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button></Tip>
            <button disabled={busy || i === 0} onClick={() => onMove(f, -1)} className="rounded p-0.5 text-muted hover:text-text disabled:opacity-30" aria-label="Move up"><ArrowUp className="h-3.5 w-3.5" /></button>
            <button disabled={busy || i === manual.length - 1} onClick={() => onMove(f, 1)} className="rounded p-0.5 text-muted hover:text-text disabled:opacity-30" aria-label="Move down"><ArrowDown className="h-3.5 w-3.5" /></button>
            <button disabled={busy} onClick={() => onDelete(f)} className="rounded p-0.5 text-muted hover:text-danger" aria-label="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
          </li>))}</ul>}
      {(status?.manual_features ?? 0) > 0 && status?.checks?.some(c => c.id === "CHK-05" && (c.detail as Record<string, unknown>)?.expected_mm3 !== undefined) && <p className="mt-3 rounded border border-border bg-panel2 p-2 text-[11px] text-muted">With manual features, the size and volume checks are informational: they compare against the original expectation, which doesn't include your manual edits.</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ revisions + compare */
export function RevisionsPanel({ project, onChanged, version, onCompare, comparing }: { project: Project; onChanged: () => void; version?: number; onCompare: (n: number) => void; comparing: number | null }) {
  const q = useQuery({ queryKey: ["revisions", project.id, version], queryFn: () => api.get<{ items: { n: number; ok: boolean; error?: string; fingerprint?: { bbox: number[]; volume: number }; created_at: string; why?: string | null; by?: string | null }[] }>(`/api/projects/${project.id}/revisions`) });
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<number | null>(null);
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="p-4 text-sm text-muted">Every build becomes a revision you can restore or compare.</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((r, i) => (
        <li key={r.n} className={cx("flex items-center gap-2 px-3 py-2.5", comparing === r.n && "bg-primary-soft")}>
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-panel2 text-[11px] font-semibold">{r.n}</span>
          <div className="min-w-0 flex-1 text-[12px]">
            <div className="flex items-center gap-1.5">{r.ok ? <Badge tone="success">Verified</Badge> : <Badge tone="danger">Failed</Badge>}{i === 0 && <Badge tone="primary">Latest</Badge>}</div>
            {r.why && <div className="mt-0.5 truncate text-text/85" title={r.why}>{r.why}</div>}
            <div className="mt-0.5 truncate text-muted">{r.fingerprint ? `${r.fingerprint.bbox.map(n => Math.round(n)).join("×")} mm · ${num(r.fingerprint.volume, 0)} mm³` : r.error?.slice(0, 40)} · {ago(r.created_at)}{r.by ? ` · ${r.by}` : ""}</div>
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
  );
}

/* ------------------------------------------------------------------ files & source */
export function FilesPanel({ project, status }: { project: Project; status?: BuildStatus }) {
  if (!status?.fingerprint) return <p className="p-4 text-sm text-muted">Exports appear after the first successful build.</p>;
  const base = `/api/projects/${project.id}/files`;
  return (
    <div className="space-y-2 p-3">
      {[["part.step", "STEP (AP214)", "SOLIDWORKS, Creo, Fusion, Inventor, NX…"], ["part.stl", "STL", "Slicers and quick viewing"], ["part.3mf", "3MF", "Modern 3D-printing format with units"]].map(([f, l, h]) => (
        <a key={f} href={`${base}/${f}`} className="flex items-center gap-3 rounded-lg border border-border p-3 hover:border-primary/50">
          <Download className="h-4 w-4 text-primary" /><div className="flex-1"><div className="text-sm font-medium">{l}</div><div className="text-xs text-muted">{h}</div></div>
        </a>))}
      <div className="rounded-lg border border-dashed border-border p-3 text-xs text-muted">
        <div className="mb-1 flex items-center gap-1.5 font-medium text-text"><Lock className="h-3.5 w-3.5" /> Drawing PDF / DXF</div>
        Manufacturing drawings come with <Link to="/app/modules/drawings" className="link">Drawing Studio</Link> (Preview).
      </div>
      <img src={`${base}/views.png?v=${status.build_id}`} alt="Four-view render" className="mt-2 w-full rounded-lg border border-border" />
    </div>
  );
}

export function SourcePanel({ project, version }: { project: Project; version?: number }) {
  const q = useQuery({ queryKey: ["source", project.id, version], queryFn: () => fetch(`/api/projects/${project.id}/source`).then(r => r.text()) });
  if (!q.data) return <p className="p-4 text-sm text-muted">The parametric source appears once the agent writes it.</p>;
  return <pre className="m-3 overflow-x-auto rounded-lg border border-border bg-panel2 p-3 font-mono text-[11.5px] leading-relaxed">{q.data}</pre>;
}
