import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Boxes, Camera, ClipboardList, Download, FileBox, Link2, Move, Pencil, Plus, RotateCcw, RotateCw, ScanSearch, Wrench,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, EmptyState, Input, PageLoader, StatusBadge, Tab, TabList, TabPanel, Tabs, Tip } from "@/components/ui";
import type { AsmView, Clash, FitPlan, HoleFix, Mate, RefreshResult, V3 } from "./types";
import type { AsmPick, FaceMark } from "./viewer";
import { Viewport, topoCache } from "./Viewport";
import { Tree } from "./Tree";
import { MatePanel, describePick, type MateChoice } from "./MatePanel";
import { FastenPanel, holeLabel, type FitOpts } from "./FastenPanel";
import { BomPanel, CheckPanel, plural } from "./CheckPanel";
import { PairPanel } from "./PairPanel";
import { InsertDialog } from "./InsertDialog";
import { Segmented, SolveChip, mm } from "./bits";

const BASE = "/api/m/assembly";
type TabKey = "mate" | "fasten" | "check" | "bom";

export default function Workspace({ aid, onClose }: { aid: string; onClose: () => void }) {
  const qc = useQueryClient();
  const key = useMemo(() => ["asm", aid], [aid]);
  const q = useQuery({ queryKey: key, queryFn: () => api.get<AsmView>(`${BASE}/assemblies/${aid}`) });
  const view = q.data;
  const setView = useCallback((v: AsmView) => qc.setQueryData(key, v), [qc, key]);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("mate");
  const [sel, setSel] = useState<string | null>(null);
  const [picks, setPicks] = useState<AsmPick[]>([]);
  const [choice, setChoice] = useState<MateChoice>("auto");
  const [mval, setMval] = useState("10");
  const [mflip, setMflip] = useState(false);
  const [target, setTarget] = useState<{ inst: string; hole: number } | null>(null);
  const [fit, setFit] = useState<FitOpts>({ style: "hex_bolt", washers: "both", pattern: true, flip: false });
  const [explode, setExplode] = useState(0);
  const [clashFocus, setClashFocus] = useState<number | null>(null);
  const [rowFocus, setRowFocus] = useState<number | null>(null);
  const [hoverMate, setHoverMate] = useState<Mate | null>(null);
  const [bomFocus, setBomFocus] = useState<string[] | null>(null);
  const [insertOpen, setInsertOpen] = useState(false);
  const [editName, setEditName] = useState<string | null>(null);
  const [step, setStep] = useState("10");
  const [editing, setEditing] = useState<Mate | null>(null);
  const [fmode, setFmode] = useState<"hole" | "pair">("hole");
  const [pair, setPair] = useState<[string | null, string | null]>([null, null]);
  const [fitKey, setFitKey] = useState<string | null>(null);
  const [gizmoMode, setGizmoMode] = useState<"translate" | "rotate">("translate");
  const keepPicks = useRef(false);

  const run = useCallback(async (label: string, fn: () => Promise<AsmView>, ok?: string | ((v: AsmView) => string | null)) => {
    setBusy(label);
    try {
      const v = await fn();
      setView(v);
      const msg = typeof ok === "function" ? ok(v) : ok;
      if (msg) toast.success(msg);
      return v;
    } catch (e) {
      toast.error((e as Error).message);
      return null;
    } finally { setBusy(null); }
  }, [setView]);

  const fitQ = useQuery({
    queryKey: ["asm-fit", aid, target, fit, view?.assembly.rev],
    queryFn: () => api.post<FitPlan>(`${BASE}/assemblies/${aid}/fasteners/propose`, { ...target, ...fit }),
    enabled: tab === "fasten" && !!target, placeholderData: keepPreviousData, retry: false, staleTime: 60_000,
  });
  const plan = fitQ.data && target && fitQ.data.holes.some(h => h.inst === target.inst) ? fitQ.data : null;

  useEffect(() => {
    if (keepPicks.current) keepPicks.current = false;
    else { setPicks([]); setEditing(null); }
    setClashFocus(null); setRowFocus(null);
  }, [tab]);
  useEffect(() => {
    if (!view) return;
    const ids = new Set(view.instances.map(i => i.id));
    setPicks(p => p.filter(x => ids.has(x.inst)));
    if (sel && !ids.has(sel)) setSel(null);
    if (target && !ids.has(target.inst)) setTarget(null);
  }, [view, sel, target]);

  const describe = useCallback((p: AsmPick) => view ? describePick(view, p,
    (part, id) => topoCache.get(part)?.faces[id], (part, id) => topoCache.get(part)?.edges[id]) : "", [view]);

  if (q.isLoading) return <PageLoader />;
  if (q.error || !view) {
    const e = q.error as ApiError | null;
    return <div className="flex h-full items-center justify-center p-8"><EmptyState icon={<Boxes className="h-5 w-5" />}
      title={e?.status === 404 ? "Assembly not found" : "Can't open the assembly"} body={e?.message}
      action={<Button variant="secondary" onClick={onClose}>All assemblies</Button>} /></div>;
  }

  const A = `${BASE}/assemblies/${aid}`;
  const patchInst = (iid: string, body: Record<string, unknown>) => run("inst", () => api.patch<AsmView>(`${A}/instances/${iid}`, body));
  const onMate = (mid: string, body: Record<string, unknown> | null) => body
    ? run("mate", () => api.patch<AsmView>(`${A}/mates/${mid}`, body))
    : run("mate", () => api.del<AsmView>(`${A}/mates/${mid}`), "Mate deleted");
  const startEdit = (m: Mate) => {
    keepPicks.current = tab !== "mate";
    setTab("mate"); setEditing(m);
    setChoice(m.type); setMval(String(m.value ?? 0)); setMflip(m.flip);
    const sides: AsmPick[] = [];
    if (!m.a_lost) sides.push({ ...m.a, point: [0, 0, 0] });
    if (!m.b_lost) sides.push({ ...m.b, point: [0, 0, 0] });
    setPicks(sides);
  };
  const saveEdit = async (m: Mate) => {
    if (picks.length !== 2) return;
    const [a, b] = picks as [AsmPick, AsmPick];
    const same = (p: AsmPick, x: Mate["a"]) => p.inst === x.inst && p.kind === x.kind && p.id === x.id;
    const body: Record<string, unknown> = { type: choice === "auto" ? m.type : choice, flip: mflip };
    if (choice === "distance" || choice === "angle") body.value = Number(mval);
    if (!(same(a, m.a) && !m.a_lost)) body.a = { inst: a.inst, kind: a.kind, id: a.id };
    if (!(same(b, m.b) && !m.b_lost)) body.b = { inst: b.inst, kind: b.kind, id: b.id };
    const v = await run("add-mate", () => api.patch<AsmView>(`${A}/mates/${m.id}`, body));
    if (v) {
      setEditing(null); setPicks([]);
      const n = v.mates.find(x => x.id === m.id);
      if (n?.status === "conflict") toast.error(`${n.label} conflicts with the other mates. It is kept but not applied.`);
      else if (n?.status === "broken") toast.warning(`${n.label} still has a missing reference. Pick it in the view.`);
      else toast.success(`${n?.label ?? "Mate"} updated`);
    }
  };
  const addMate = async () => {
    if (editing) return saveEdit(editing);
    if (picks.length !== 2) return;
    const [a, b] = picks as [AsmPick, AsmPick];
    const v = await run("add-mate", () => api.post<AsmView>(`${A}/mates`, {
      type: choice, a: { inst: a.inst, kind: a.kind, id: a.id }, b: { inst: b.inst, kind: b.kind, id: b.id },
      value: choice === "distance" || choice === "angle" ? Number(mval) : 0, flip: mflip,
    }));
    if (v) {
      setPicks([]);
      const m = v.mates[v.mates.length - 1];
      if (m?.status === "conflict") toast.error(`${m.label} conflicts with the existing mates. It is kept but not applied.`);
      else toast.success(`${m?.label ?? "Mate"} added`);
    }
  };
  const runCheck = async () => {
    setBusy("check");
    try {
      const r = await api.post<{ analysis: AsmView["analysis"] }>(`${A}/analyse`);
      setView({ ...view, analysis: r.analysis });
      setClashFocus(null); setRowFocus(null);
      const n = r.analysis?.interference.count ?? 0;
      if (n) toast.error(`${n} interference${n > 1 ? "s" : ""} found`); else toast.success("No interference");
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };
  const knownIssues = () => {
    const bits: string[] = [];
    const nc = view.solve?.conflicts.length ?? 0;
    if (nc) bits.push(plural(nc, "conflicting mate"));
    const nb = view.mates.filter(m => m.status === "broken").length;
    if (nb) bits.push(plural(nb, "broken mate"));
    if (view.analysis && !view.analysis.stale && view.analysis.interference.count) bits.push(plural(view.analysis.interference.count, "interference"));
    return bits;
  };
  const exportStep = async () => {
    setBusy("export");
    try {
      const r = await api.post<{ export: AsmView["export"] }>(`${A}/export`);
      setView({ ...view, export: r.export });
      const issues = knownIssues();
      if (r.export?.ok && issues.length) {
        toast.warning(`STEP exported with ${issues.join(" and ")}. Re-import verified (${plural(r.export.instances, "instance")}).`);
        const a = document.createElement("a"); a.href = r.export.url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
      } else if (r.export?.ok) {
        toast.success(`STEP exported: ${plural(r.export.instances, "instance")}, re-import verified`);
        const a = document.createElement("a"); a.href = r.export.url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
      } else toast.error("STEP exported, but the re-import check did not match. Check the file before use.");
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
  };
  const insert = async (body: Record<string, unknown>) => {
    const v = await run("insert", () => api.post<AsmView>(`${A}/instances`, body), v => {
      const id = (v.result as { instance?: string } | undefined)?.instance;
      return `${v.instances.find(i => i.id === id)?.display ?? "Part"} inserted`;
    });
    if (v) {
      const id = (v.result as { instance?: string } | undefined)?.instance ?? null;
      setInsertOpen(false); setSel(id); setFitKey(id);
    }
  };
  const fitted = (v: AsmView) => {
    const r = v.result as { inserted?: number; clashes?: Clash[] } | undefined;
    const n = r?.inserted ?? 0;
    const cl = r?.clashes ?? [];
    if (cl.length) {
      toast.error(`${plural(n, "fastener stack")} inserted, but ${cl.length === 1 ? "it clashes" : "they clash"}: ` +
        cl.slice(0, 2).map(c => `${c.a_name} ↔ ${c.b_name} ${mm(c.volume_mm3, 1)} mm³`).join(", ") + ". See Check.", { duration: 9000 });
      return null;
    }
    return `${plural(n, "fastener stack")} inserted · no interference with the other parts`;
  };
  const acceptFit = async () => {
    if (!target) return;
    const v = await run("fit", () => api.post<AsmView>(`${A}/fasteners/accept`, { ...target, ...fit }), fitted);
    if (v) setTarget(null);
  };
  const acceptPairs = (targets: { inst: string; hole: number }[]) =>
    run("fit", () => api.post<AsmView>(`${A}/fasteners/accept`, { targets, style: fit.style, washers: fit.washers, pattern: false }), fitted);
  const refreshed = (v: AsmView) => {
    const r = v.result as Partial<RefreshResult> | undefined;
    const lost = r?.broken_mates?.length ?? 0;
    const tail = [r?.references_followed ? `${plural(r.references_followed, "mate reference")} followed the change` : "",
      r?.stacks_to_check ? `${plural(r.stacks_to_check, "fastener stack")} to check` : ""].filter(Boolean).join(" · ");
    if (lost) {
      toast.warning(`Refreshed, but ${plural(lost, "mate")} lost a reference. Use Repair on ${lost === 1 ? "it" : "each"} in the mates list.`, { duration: 9000 });
      return null;
    }
    if (r?.stacks_to_check) { toast.warning(`Part refreshed. ${tail}: use Update on the flagged stack.`, { duration: 9000 }); return null; }
    return tail ? `Part refreshed · ${tail}` : "Part refreshed to its latest build";
  };
  const fixHole = (inst: string, fix: HoleFix) =>
    run("fix", () => api.post<AsmView>(`${A}/fix-hole`, { inst, param: fix.param, value: fix.to }), v => {
      const msg = refreshed(v);
      return msg ? `${fix.project}: ${fix.label} ${fix.from} → ${fix.to}, rebuilt and checked. ${msg}` : null;
    });
  const refit = (gid: string) => run("refit", () => api.post<AsmView>(`${A}/groups/${gid}/refit`), v => {
    const r = v.result as { summary?: string; clashes?: Clash[] } | undefined;
    if (r?.clashes?.length) { toast.error(`Stack updated to ${r.summary}, but it clashes. See Check.`); return null; }
    return `Stack updated: ${r?.summary ?? ""}`;
  });

  // ---- viewer state per tab
  const picking: ("face" | "edge")[] = tab === "mate" ? ["face", "edge"] : ["face"];
  const onPick = (p: AsmPick | null) => {
    if (tab === "mate") {
      if (!p) return;
      const inst = view.instances.find(i => i.id === p.inst);
      setPicks(prev => {
        if (prev.some(x => x.inst === p.inst && x.kind === p.kind && x.id === p.id)) return prev.filter(x => !(x.inst === p.inst && x.kind === p.kind && x.id === p.id));
        if (prev.length === 1 && prev[0]!.inst === p.inst) { toast.info(`Pick the second reference on another part (not ${inst?.display}).`); return prev; }
        return prev.length >= 2 ? [p] : [...prev, p];
      });
      return;
    }
    if (tab === "fasten" && fmode === "pair") {
      const inst = p ? view.instances.find(i => i.id === p.inst) : undefined;
      if (!inst || inst.group) return;
      setPair(([a, b]) => (a === inst.id || b === inst.id) ? [a, b] : !a ? [inst.id, b] : !b ? [a, inst.id] : [b, inst.id]);
      return;
    }
    if (tab === "fasten") {
      if (!p) return;
      const inst = view.instances.find(i => i.id === p.inst);
      const part = inst ? view.parts[inst.part] : undefined;
      const h = !inst?.group && part ? part.holes.find(x => x.faces.includes(p.id)) : undefined;
      if (inst && h) setTarget({ inst: inst.id, hole: h.id });
      else toast.info(inst?.group ? "That's a fastener. Pick a hole in a part." : "That face isn't a recognised hole.");
      return;
    }
    setSel(p ? p.inst : null);
  };
  const marks: FaceMark[] = [];
  if (tab === "fasten") {
    for (const i of view.instances) {
      if (i.group || !i.visible) continue;
      const part = view.parts[i.part];
      if (!part) continue;
      const pat = target && target.inst === i.id ? part.patterns.find(pp => pp.holes.includes(target.hole)) : undefined;
      const chosen = new Set(target && target.inst === i.id ? (fit.pattern && pat ? pat.holes : [target.hole]) : []);
      for (const h of part.holes) marks.push({ inst: i.id, faces: h.faces, color: chosen.has(h.id) ? 0xc8742e : 0x22a85a, opacity: chosen.has(h.id) ? 0.7 : 0.35 });
    }
  }
  if (hoverMate) {
    for (const s of [hoverMate.a, hoverMate.b]) if (s.kind === "face") marks.push({ inst: s.inst, faces: [s.id], color: 0x1f5fbf, opacity: 0.45 });
  }
  const clashPairs = tab === "check" && view.analysis && !view.analysis.stale ? view.analysis.interference.pairs.filter(p => p.kind === "interference" && p.mesh) : [];
  const row = tab === "check" && rowFocus !== null ? view.analysis?.clearance.rows[rowFocus] : undefined;
  const focusPair = clashFocus !== null ? clashPairs[clashFocus] : undefined;
  const ghost = focusPair ? new Set([focusPair.a, focusPair.b]) : null;
  const selected = bomFocus ?? (row ? [row.a, row.b] : sel && tab !== "mate" && tab !== "fasten" ? [sel] : []);
  const measure: [V3, V3] | null = row && row.status === "clear" ? [row.pa, row.pb] : null;
  const hint = tab === "mate" ? (picks.length === 0 ? "Pick the first face or edge" : picks.length === 1 ? "Pick a face or edge on another part" : editing ? "Ready: Save mate" : "Ready: Add mate")
    : tab === "fasten" && fmode === "pair" ? (pair[0] && pair[1] ? "Fastening the two parts" : "Click two parts")
    : tab === "fasten" ? (target ? holeLabel(view, target.inst, target.hole) : "Click a hole to fit fasteners") : null;
  const selInst = view.instances.find(i => i.id === sel);
  const movable = !!selInst && view.can_edit && !selInst.fixed && !(selInst.dof && (selInst.dof.dof === 0 || selInst.dof.spin));
  const gizmo = movable && tab !== "mate" && tab !== "fasten" && explode === 0 ? { id: selInst!.id, mode: gizmoMode } : null;
  if (tab === "fasten" && fmode === "pair") {
    for (const id of pair) if (id) {
      const i = view.instances.find(x => x.id === id);
      const part = i ? view.parts[i.part] : undefined;
      if (part) marks.push({ inst: id, faces: part.holes.flatMap(h => h.faces), color: 0x22a85a, opacity: 0.4 });
    }
  }
  const solve = view.solve;
  const home = view.home_project;
  const exp = view.export;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="asm-workspace">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-panel px-4 py-2">
        {home ? <Link to={`/app/projects/${home.id}`} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Back to project</Link>
          : <button type="button" onClick={onClose} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Assemblies</button>}
        <div className="h-5 w-px bg-border" />
        <div className="flex items-center gap-2"><Boxes className="h-4 w-4 text-primary" /><span className="text-[15px] font-semibold">Assembly Studio</span><StatusBadge status="live" /></div>
        {editName !== null ? (
          <form onSubmit={e => { e.preventDefault(); const n = editName.trim(); setEditName(null); if (n && n !== view.assembly.name) run("name", () => api.patch<AsmView>(A, { name: n })); }}>
            <Input autoFocus value={editName} maxLength={120} onChange={e => setEditName(e.target.value)} onBlur={e => e.currentTarget.form?.requestSubmit()} className="h-8 w-64" />
          </form>
        ) : (
          <button type="button" disabled={!view.can_edit} onClick={() => setEditName(view.assembly.name)}
            className="group flex min-w-0 items-center gap-1.5 rounded border border-border bg-panel2 px-2.5 py-1 text-[13px] font-medium">
            <span className="max-w-[280px] truncate">{view.assembly.name}</span>{view.can_edit && <Pencil className="h-3 w-3 text-muted group-hover:text-text" />}
          </button>
        )}
        {solve && view.instances.length > 0 && <SolveChip status={solve.status} solve={solve} />}
        <div className="ml-auto flex items-center gap-2">
          {view.can_edit && <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setInsertOpen(true)} data-testid="insert">Insert</Button>}
          {view.instances.length > 0 && <Tip content="Product render of this assembly in Mesh Studio, exploded or not, each part in the finish its material suggests" side="bottom">
            <Link to={`/app/modules/mesh?assembly=${aid}`} data-testid="render-assembly"
              className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-panel px-2.5 text-[12.5px] font-medium hover:bg-panel2"><Camera className="h-4 w-4" />Render</Link></Tip>}
          {exp && !exp.stale && <a href={exp.url} className="inline-flex h-8 items-center gap-1.5 rounded border border-border bg-panel px-2.5 text-[12.5px] font-medium hover:bg-panel2" data-testid="step-download">
            <Download className="h-4 w-4" />STEP</a>}
          {view.can_edit && <Tip content="Assembly STEP (AP214) with sub-assemblies, part names and placements; re-imported to verify" side="bottom">
            <Button size="sm" variant="secondary" icon={<FileBox className="h-4 w-4" />} loading={busy === "export"} disabled={!view.instances.length} onClick={exportStep} data-testid="export-step">
              {exp && !exp.stale ? "Re-export" : "Export STEP"}</Button></Tip>}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[264px_minmax(0,1fr)_360px] lg:overflow-hidden">
        <aside className="flex min-h-0 flex-col border-r border-border bg-panel">
          <div className="min-h-0 flex-1">
            <Tree view={view} selected={sel} onSelect={setSel} canEdit={view.can_edit} onPatch={patchInst}
              onDelete={iid => run("del", () => api.del<AsmView>(`${A}/instances/${iid}`), "Instance deleted")}
              onDeleteGroup={gid => run("del", () => api.del<AsmView>(`${A}/groups/${gid}`), "Fastener stack removed")}
              onRefresh={iid => run("refresh", () => api.post<AsmView>(`${A}/instances/${iid}/refresh`), refreshed)}
              onMate={onMate} hoverMate={setHoverMate} focusMate={hoverMate?.id ?? editing?.id ?? null} onEdit={startEdit} onRefit={refit} />
          </div>
          {selInst && view.can_edit && !selInst.fixed && (
            <div className="border-t border-border p-3" data-testid="move-box">
              <div className="mb-2 flex items-center gap-1.5"><Move className="h-3.5 w-3.5 text-muted" /><span className="label">Move {selInst.display}</span></div>
              {selInst.dof && selInst.dof.dof === 0 || selInst.dof?.spin ? (
                <p className="text-[11.5px] leading-snug text-muted">Its mates hold this part in place. Suppress or delete a mate to move it.</p>
              ) : (
                <>
                  <div className="mb-2 flex items-center gap-1.5 text-[12px]"><span className="text-muted">Step</span>
                    <Input type="number" value={step} onChange={e => setStep(e.target.value)} className="h-7 w-16 px-1.5 text-[12px]" /><span className="text-muted">mm</span></div>
                  <div className="grid grid-cols-3 gap-1">
                    {(["X", "Y", "Z"] as const).map((ax, k) => (
                      <div key={ax} className="flex overflow-hidden rounded border border-border text-[12px]">
                        {[-1, 1].map(sgn => (
                          <button key={sgn} type="button" disabled={!!busy} className="flex-1 py-1 hover:bg-text/5"
                            onClick={() => { const t = [0, 0, 0]; t[k] = sgn * (Number(step) || 0); patchInst(selInst.id, { translate: t }); }}>{sgn < 0 ? "−" : "+"}{ax}</button>
                        ))}
                      </div>
                    ))}
                    {(["X", "Y", "Z"] as const).map(ax => (
                      <div key={`r${ax}`} className="flex overflow-hidden rounded border border-border text-[12px]">
                        <button type="button" title={`Rotate −90° about ${ax}`} className="flex flex-1 items-center justify-center py-1 hover:bg-text/5" onClick={() => patchInst(selInst.id, { rotate: { axis: ax, deg: -90 } })}><RotateCcw className="h-3 w-3" /></button>
                        <span className="px-0.5 py-1 text-muted">{ax}</span>
                        <button type="button" title={`Rotate +90° about ${ax}`} className="flex flex-1 items-center justify-center py-1 hover:bg-text/5" onClick={() => patchInst(selInst.id, { rotate: { axis: ax, deg: 90 } })}><RotateCw className="h-3 w-3" /></button>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-[12px]"><span className="text-muted">Drag in view</span>
                    <div className="flex-1"><Segmented size="sm" value={gizmoMode} onChange={setGizmoMode}
                      options={[{ value: "translate", label: "Move" }, { value: "rotate", label: "Rotate" }]} /></div></div>
                  <p className="mt-2 text-[11px] text-muted">{tab === "mate" || tab === "fasten" ? "The drag handles show in the Check and BOM tabs. " : ""}{selInst.dof && selInst.dof.dof < 6 ? "Mates re-apply after each move, so only the free directions change." : "Drag the arrows or rings, or step it here."}</p>
                </>
              )}
            </div>
          )}
        </aside>
        <section className="relative min-h-[460px] min-w-0">
          {view.instances.length === 0 ? (
            <div className="flex h-full items-center justify-center p-8">
              <EmptyState icon={<Boxes className="h-5 w-5" />} title="Empty assembly" body="Insert a verified project part (it comes in fixed at the origin), then Toolbox components or more parts."
                action={view.can_edit ? <Button icon={<Plus className="h-4 w-4" />} onClick={() => setInsertOpen(true)}>Insert component</Button> : undefined} />
            </div>
          ) : (
            <Viewport view={view} picking={picking} picks={picks} marks={marks} selected={selected} ghost={ghost}
              clashes={clashPairs.map(p => p.mesh!)} clashFocus={clashFocus} measure={measure} explode={explode} onExplode={setExplode}
              onPick={onPick} hint={hint} describe={tab === "mate" ? describe : undefined}
              thumbKey={view.can_edit && view.thumb_rev !== view.assembly.rev ? view.assembly.rev : null}
              gizmo={gizmo} fitKey={fitKey} onDrag={(iid, T) => patchInst(iid, { T })}
              onThumb={(png, rev) => { api.post(`${A}/thumbnail`, { png_b64: png, rev }).then(() => qc.setQueryData(key, (old: AsmView | undefined) => old ? { ...old, thumb_rev: rev } : old)).catch(() => {}); }} />
          )}
          {row && <div className="pointer-events-none absolute bottom-14 left-1/2 -translate-x-1/2 rounded-full border border-border bg-panel/95 px-3 py-1 text-[12px] shadow-card">
            {row.a_name} ↔ {row.b_name}: <b>{row.status === "clear" ? `${mm(row.distance_mm, 3)} mm` : row.status}</b></div>}
          {focusPair && <div className="pointer-events-none absolute bottom-14 left-1/2 -translate-x-1/2 rounded-full border border-danger/40 bg-panel/95 px-3 py-1 text-[12px] text-danger shadow-card">
            {focusPair.a_name} ↔ {focusPair.b_name}: <b>{mm(focusPair.volume_mm3, 3)} mm³</b>{explode > 0 ? " (collapse the explode to see it)" : ""}</div>}
        </section>
        <aside className="min-h-0 overflow-y-auto border-l border-border bg-panel">
          <Tabs value={tab} onValueChange={v => setTab(v as TabKey)}>
            <TabList className="sticky top-0 z-10 bg-panel px-2">
              <Tab value="mate" compact><Link2 className="h-3.5 w-3.5" />Mate</Tab>
              <Tab value="fasten" compact><Wrench className="h-3.5 w-3.5" />Fasten</Tab>
              <Tab value="check" compact><ScanSearch className="h-3.5 w-3.5" />Check{view.analysis && !view.analysis.stale && view.analysis.interference.count > 0 &&
                <span className="ml-0.5 rounded-full bg-danger px-1.5 text-[10px] font-bold text-white">{view.analysis.interference.count}</span>}</Tab>
              <Tab value="bom" compact><ClipboardList className="h-3.5 w-3.5" />BOM</Tab>
            </TabList>
            <TabPanel value="mate">
              <MatePanel view={view} choice={choice} onChoice={setChoice} picks={picks} onClearPick={k => setPicks(p => p.filter((_, j) => j !== k))}
                value={mval} onValue={setMval} flip={mflip} onFlip={setMflip} onAdd={addMate} busy={busy === "add-mate"} describe={describe}
                editing={editing} onCancelEdit={() => { setEditing(null); setPicks([]); }} />
            </TabPanel>
            <TabPanel value="fasten">
              <div className="border-b border-border px-4 py-2.5">
                <Segmented value={fmode} onChange={v => { setFmode(v); setTarget(null); }} options={[
                  { value: "hole", label: "Pick a hole", title: "Fit fasteners to one hole or a hole pattern" },
                  { value: "pair", label: "Two parts", title: "Fit every lined-up hole between two parts" }]} />
              </div>
              {fmode === "hole"
                ? <FastenPanel view={view} target={target} onTarget={setTarget} opts={fit} onOpts={setFit} plan={plan} loading={fitQ.isFetching}
                    error={fitQ.error ? (fitQ.error as Error).message : null} onInsert={acceptFit} busy={busy === "fit"} />
                : <PairPanel view={view} aid={aid} pair={pair} onPair={setPair} style={fit.style} washers={fit.washers}
                    onInsert={acceptPairs} onFix={fixHole} busy={busy} />}
            </TabPanel>
            <TabPanel value="check">
              <CheckPanel view={view} onRun={runCheck} busy={busy === "check"} focus={clashFocus} onFocus={setClashFocus} rowFocus={rowFocus} onRowFocus={setRowFocus} />
            </TabPanel>
            <TabPanel value="bom">
              <BomPanel view={view} onFocus={r => setBomFocus(r ? r.instances : null)} />
            </TabPanel>
          </Tabs>
          {exp && (
            <div className={cx("mx-4 my-3 rounded border px-3 py-2 text-[11.5px]", exp.ok ? "border-success/25 bg-success/5 text-success" : "border-warning/30 bg-warning/5 text-warning")}>
              Last STEP: {plural(exp.instances, "instance")}, {plural(exp.groups, "sub-assembly", "sub-assemblies")}; re-import {exp.ok ? "matched" : "did not match"} (placement deviation {mm(exp.placement_dev_mm, 9)} mm){exp.stale ? ". The assembly changed since." : "."}
              {!exp.stale && knownIssues().length > 0 && <span className="mt-1 block font-medium text-warning">Exported with {knownIssues().join(" and ")}.</span>}
            </div>
          )}
        </aside>
      </div>
      <InsertDialog open={insertOpen} onOpenChange={setInsertOpen} busy={busy === "insert"} onInsert={insert} />
    </div>
  );
}
