import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Eye, EyeOff, History, Info, Plus, ShieldAlert, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, Input, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import type { P2 } from "@/sketch/tools";
import { draftsApi, type DraftState, type Fragment } from "./api";
import {
  circleOf, dimText, GDT_NEEDS_DATUM, GDT_SYMBOLS, kOf, LAYERS, lineOf, measure, pointMap, SCALES, SHEETS, sheetWH,
  type Anno, type DEnt, type Dim, type DraftDoc, type GdtSymbol, type Layer, type Tol,
} from "./geom";
import type { ToolId } from "./DraftEditor";

export interface ToolOpts {
  offset: number; fillet: number; chamfer: number; sides: number; inscribed: boolean; text: string; textSize: number; leaderText: string;
  balloon: string; surfaceText: string; removal: "any" | "required" | "prohibited"; gdtSymbol: GdtSymbol; gdtTol: string; gdtDia: boolean;
  gdtMod: "" | "M" | "L"; gdtDatums: string; datum: string; hatch: number; angle: number; factor: number; copyMode: boolean;
  dimOrient: "auto" | "h" | "v" | "aligned";
}

const GDT_LABEL: Record<GdtSymbol, string> = {
  straightness: "Straightness", flatness: "Flatness", circularity: "Circularity (roundness)", cylindricity: "Cylindricity", profile_line: "Profile of a line",
  profile_surface: "Profile of a surface", parallelism: "Parallelism", perpendicularity: "Perpendicularity", angularity: "Angularity", position: "Position",
  concentricity: "Concentricity / coaxiality", symmetry: "Symmetry", circular_runout: "Circular run-out", total_runout: "Total run-out",
};

function Sec({ title, children, hint }: { title: string; children: ReactNode; hint?: ReactNode }) {
  return <div className="space-y-2 border-b border-border px-4 py-3"><div className="label">{title}</div>{children}{hint && <p className="text-[11.5px] leading-snug text-muted">{hint}</p>}</div>;
}
function Num({ label, value, onChange, step = 0.5, min, disabled, suffix }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; disabled?: boolean; suffix?: string }) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  return (
    <label className="flex items-center justify-between gap-2 text-[12.5px]"><span className="text-muted">{label}</span>
      <span className="flex items-center gap-1"><input type="number" step={step} min={min} value={v} disabled={disabled} onChange={e => setV(e.target.value)}
        onBlur={() => { const n = parseFloat(v); if (Number.isFinite(n) && (min === undefined || n >= min)) onChange(n); else setV(String(value)); }}
        onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        className="h-7 w-24 rounded border border-border bg-panel px-1.5 text-right text-[12.5px] tabular-nums outline-none focus:border-primary disabled:opacity-60" />{suffix && <span className="w-6 text-[11px] text-muted">{suffix}</span>}</span>
    </label>
  );
}
function Txt({ label, value, onChange, placeholder, disabled, max = 60, area }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean; max?: number; area?: boolean }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const cls = "mt-0.5 w-full rounded border border-border bg-panel px-2 py-1 text-[12.5px] outline-none focus:border-primary disabled:opacity-60";
  return (
    <label className="block text-[12px]"><span className="text-muted">{label}</span>
      {area ? <textarea rows={3} value={v} maxLength={max} placeholder={placeholder} disabled={disabled} className={cls} onChange={e => setV(e.target.value)} onBlur={() => v !== value && onChange(v)} />
        : <input value={v} maxLength={max} placeholder={placeholder} disabled={disabled} className={cx(cls, "h-7")} onChange={e => setV(e.target.value)} onBlur={() => v !== value && onChange(v)}
          onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />}
    </label>
  );
}
function Sel<T extends string>({ label, value, options, onChange, disabled }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <label className="flex items-center justify-between gap-2 text-[12.5px]"><span className="text-muted">{label}</span>
      <select value={value} disabled={disabled} onChange={e => onChange(e.target.value as T)} className="input h-7 w-40 py-0 text-[12.5px]">
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    </label>
  );
}

export function DraftSidePanel(p: {
  doc: DraftDoc; canEdit: boolean; state: DraftState; sel: Set<string>; setSel: (s: Set<string>) => void; commit: (d: DraftDoc) => void;
  tool: ToolId; opts: ToolOpts; setOpts: (f: (o: ToolOpts) => ToolOpts) => void; layer: Layer; setLayer: (l: Layer) => void;
  hiddenLayers: Set<string>; setHiddenLayers: (s: Set<string>) => void; onInsert: (f: Fragment, msg: string, missing: string[]) => void;
  onOpenRev: (rev: number) => void; previewRev: number | null; dirty: boolean;
}) {
  const [tab, setTab] = useState("props");
  useEffect(() => { if (p.sel.size) setTab("props"); }, [p.sel]);
  return (
    <aside className="flex w-[336px] shrink-0 flex-col border-l border-border bg-panel" data-testid="draft-panel">
      <ToolOptions {...p} />
      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <TabList className="overflow-x-auto px-2"><Tab value="props" compact>Item</Tab><Tab value="sheet" compact>Sheet</Tab><Tab value="layers" compact>Layers</Tab><Tab value="assist" compact>Assist</Tab><Tab value="check" compact>Check</Tab><Tab value="rev" compact>Revs</Tab></TabList>
        <TabPanel value="props" className="min-h-0 flex-1 overflow-y-auto"><Props {...p} /></TabPanel>
        <TabPanel value="sheet" className="min-h-0 flex-1 overflow-y-auto"><SheetPanel {...p} /></TabPanel>
        <TabPanel value="layers" className="min-h-0 flex-1 overflow-y-auto"><LayersPanel {...p} /></TabPanel>
        <TabPanel value="assist" className="min-h-0 flex-1 overflow-y-auto"><AssistPanel {...p} /></TabPanel>
        <TabPanel value="check" className="min-h-0 flex-1 overflow-y-auto"><CheckPanel {...p} /></TabPanel>
        <TabPanel value="rev" className="min-h-0 flex-1 overflow-y-auto"><RevPanel {...p} /></TabPanel>
      </Tabs>
    </aside>
  );
}

/* ------------------------------------------------------------------ tool options */
function ToolOptions({ tool, opts, setOpts, canEdit, layer, setLayer }: Parameters<typeof DraftSidePanel>[0]) {
  const set = <K extends keyof ToolOpts>(k: K) => (v: ToolOpts[K]) => setOpts(o => ({ ...o, [k]: v }));
  let body: ReactNode = null;
  const draws = ["line", "rect", "circle", "arc", "slot", "polygon"].includes(tool);
  if (tool === "offset") body = <Num label="Distance" value={opts.offset} min={0.001} onChange={set("offset")} />;
  else if (tool === "fillet") body = <Num label="Radius" value={opts.fillet} min={0.001} onChange={set("fillet")} />;
  else if (tool === "chamfer") body = <Num label="Distance (each side)" value={opts.chamfer} min={0.001} onChange={set("chamfer")} />;
  else if (tool === "polygon") body = <><Num label="Sides" value={opts.sides} step={1} min={3} onChange={v => set("sides")(Math.max(3, Math.min(64, Math.round(v))))} />
    <Sel label="Size by" value={opts.inscribed ? "in" : "out"} options={[["in", "Inscribed (vertex)"], ["out", "Circumscribed (flat)"]]} onChange={v => set("inscribed")(v === "in")} /></>;
  else if (tool === "hatch") body = <Num label="Line spacing (paper)" value={opts.hatch} min={0.5} onChange={set("hatch")} suffix="mm" />;
  else if (tool === "rotate") body = <><p className="text-[11.5px] text-muted">Click the centre, then the angle, or type the angle in degrees.</p><label className="flex items-center gap-2 text-[12.5px]"><input type="checkbox" checked={opts.copyMode} onChange={e => set("copyMode")(e.target.checked)} />Keep the original (copy)</label></>;
  else if (tool === "scale") body = <><Num label="Factor" value={opts.factor} min={0.001} step={0.1} onChange={set("factor")} /><label className="flex items-center gap-2 text-[12.5px]"><input type="checkbox" checked={opts.copyMode} onChange={e => set("copyMode")(e.target.checked)} />Keep the original (copy)</label></>;
  else if (tool === "text") body = <><Txt label="Note text" value={opts.text} onChange={set("text")} placeholder="e.g. BREAK ALL SHARP EDGES" max={500} area /><Num label="Text height" value={opts.textSize} min={1.8} step={0.5} onChange={set("textSize")} suffix="mm" /></>;
  else if (tool === "leader") body = <Txt label="Leader text" value={opts.leaderText} onChange={set("leaderText")} placeholder="e.g. 2X M6 THRU" max={120} />;
  else if (tool === "balloon") body = <Txt label="Item number" value={opts.balloon} onChange={set("balloon")} max={4} />;
  else if (tool === "datum") body = <Txt label="Datum letter" value={opts.datum} onChange={v => set("datum")(v.toUpperCase().slice(0, 2))} max={2} />;
  else if (tool === "surface") body = <><Txt label="Requirement (as you specify it)" value={opts.surfaceText} onChange={set("surfaceText")} placeholder="e.g. Ra 1.6" max={24} />
    <Sel label="Material removal" value={opts.removal} options={[["required", "Required"], ["prohibited", "Not allowed"], ["any", "Any process"]]} onChange={set("removal")} /></>;
  else if (tool === "gdt") body = <>
    <Sel label="Characteristic" value={opts.gdtSymbol} options={GDT_SYMBOLS.map(s => [s, GDT_LABEL[s]] as [GdtSymbol, string])} onChange={set("gdtSymbol")} />
    <Txt label="Tolerance value (you enter it)" value={opts.gdtTol} onChange={set("gdtTol")} placeholder="e.g. 0.05" max={10} />
    <div className="flex items-center gap-3 text-[12.5px]"><label className="flex items-center gap-1.5"><input type="checkbox" checked={opts.gdtDia} onChange={e => set("gdtDia")(e.target.checked)} />Ø zone</label>
      <Sel label="Modifier" value={opts.gdtMod} options={[["", "None"], ["M", "Ⓜ MMC"], ["L", "Ⓛ LMC"]]} onChange={set("gdtMod")} /></div>
    <Txt label={`Datums${GDT_NEEDS_DATUM.has(opts.gdtSymbol) ? " (required)" : ""}`} value={opts.gdtDatums} onChange={set("gdtDatums")} placeholder="e.g. A B C" max={12} />
    <p className="text-[11px] text-muted">Formwright never proposes a tolerance: the frame prints exactly what you enter.</p></>;
  else if (["dim", "dimh", "dimv", "dimal", "dimb", "dimc"].includes(tool)) body = <Sel label="Orientation" value={opts.dimOrient} options={[["auto", "Automatic"], ["h", "Horizontal"], ["v", "Vertical"], ["aligned", "Aligned"]]} onChange={set("dimOrient")} />;
  if (draws) body = <>{body}<Sel label="Layer" value={layer} options={LAYERS.filter(l => l.key !== "dimension").map(l => [l.key, l.label] as [Layer, string])} onChange={setLayer} /></>;
  if (!body || !canEdit) return null;
  return <div className="border-b border-border bg-panel2/60" data-testid="tool-options"><Sec title="Tool options">{body}</Sec></div>;
}

/* ------------------------------------------------------------------ properties of the selection */
function Props({ doc, sel, setSel, commit, canEdit }: Parameters<typeof DraftSidePanel>[0]) {
  const ids = [...sel];
  if (!ids.length) {
    const g = doc.geom;
    return <div className="space-y-2 px-4 py-3 text-[12.5px] text-muted">
      <p>Nothing selected. Pick a tool in the ribbon, or use Select to pick geometry, dimensions and notes.</p>
      <p>{g.entities.length} entities · {doc.dims.length} dimensions · {doc.annos.length} annotations</p>
      <div className="rounded border border-border bg-panel2 p-2 text-[11.5px] leading-relaxed">
        <b className="text-text">Keys</b>: L line · R rectangle · C circle · A arc · O offset · T trim · M move · H hatch · D dimension · S select · F fit ·
        F3 snap · F8 ortho · F10 polar · Enter / Esc finish · Ctrl+Z / Ctrl+Y · Ctrl+S save. Type coordinates while drawing: <code>x,y</code>, <code>@dx,dy</code>, <code>@len&lt;angle</code> or a length.
      </div>
    </div>;
  }
  const ents = doc.geom.entities.filter(e => sel.has(e.id));
  const dims = doc.dims.filter(d => sel.has(d.id));
  const annos = doc.annos.filter(a => sel.has(a.id));
  const upd = (f: (d: DraftDoc) => DraftDoc) => commit(f(doc));
  const del = () => {
    const d = { ...doc, dims: doc.dims.filter(x => !sel.has(x.id)), annos: doc.annos.filter(x => !sel.has(x.id)) };
    commit(d); setSel(new Set(ents.map(e => e.id)));
  };
  return (
    <div>
      {ents.length > 0 && <Sec title={ents.length === 1 ? `${ents[0]!.type} · ${LAYERS.find(l => l.key === ents[0]!.layer)?.label}` : `${ents.length} entities`}>
        <Sel label="Layer" value={ents.every(e => e.layer === ents[0]!.layer) ? ents[0]!.layer : "visible"} disabled={!canEdit} options={LAYERS.map(l => [l.key, l.label] as [Layer, string])}
          onChange={v => upd(d => ({ ...d, geom: { ...d.geom, entities: d.geom.entities.map(e => (sel.has(e.id) ? { ...e, layer: v } as DEnt : e)) } }))} />
        {ents.length === 1 && <EntityFacts doc={doc} e={ents[0]!} canEdit={canEdit} upd={upd} />}
      </Sec>}
      {dims.map(d => <DimProps key={d.id} doc={doc} d={d} canEdit={canEdit} upd={upd} />)}
      {annos.map(a => <AnnoProps key={a.id} doc={doc} a={a} canEdit={canEdit} upd={upd} />)}
      {(dims.length > 0 || annos.length > 0) && canEdit && <div className="px-4 py-3"><Button size="sm" variant="secondary" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={del}>Delete annotations</Button></div>}
      {canEdit && <p className="px-4 pb-3 text-[11.5px] text-muted">Press Delete to remove the selection with its dimensions.</p>}
    </div>
  );
}

function EntityFacts({ doc, e, canEdit, upd }: { doc: DraftDoc; e: DEnt; canEdit: boolean; upd: (f: (d: DraftDoc) => DraftDoc) => void }) {
  const u = doc.sheet.units;
  if (e.type === "line") { const l = lineOf(doc, e.id)!; return <p className="text-[12px] text-muted">Length {Math.hypot(l[1][0] - l[0][0], l[1][1] - l[0][1]).toFixed(3)} {u} · angle {(Math.atan2(l[1][1] - l[0][1], l[1][0] - l[0][0]) * 180 / Math.PI).toFixed(2)}°</p>; }
  if (e.type === "circle") return <Num label={`Diameter (${u})`} value={+(2 * e.r).toFixed(6)} min={0.0001} disabled={!canEdit} onChange={v => upd(d => ({ ...d, geom: { ...d.geom, entities: d.geom.entities.map(x => (x.id === e.id && x.type === "circle" ? { ...x, r: v / 2 } : x)) } }))} />;
  const c = circleOf(doc, e.id); return <p className="text-[12px] text-muted">Radius {c?.r.toFixed(3)} {u}</p>;
}

const DIM_LABEL: Record<Dim["type"], string> = { linear: "Linear dimension", radius: "Radius", diameter: "Diameter", angle: "Angle", ordinate: "Ordinate" };

function DimProps({ doc, d, canEdit, upd }: { doc: DraftDoc; d: Dim; canEdit: boolean; upd: (f: (x: DraftDoc) => DraftDoc) => void }) {
  const v = measure(doc, d);
  const set = (patch: Partial<Dim>) => upd(x => ({ ...x, dims: x.dims.map(y => (y.id === d.id ? { ...y, ...patch } as Dim : y)) }));
  const tol = d.tol;
  const kind = tol?.kind ?? "none";
  const setTol = (t: Tol | undefined) => upd(x => ({ ...x, dims: x.dims.map(y => { if (y.id !== d.id) return y; const n = { ...y } as Dim; if (t) n.tol = t; else delete n.tol; return n; }) }));
  const text = v === null ? "-" : (() => { const r = dimText(doc, d, v); return [r.main, ...r.stack].join(" "); })();
  return (
    <Sec title={DIM_LABEL[d.type]} hint="The value is measured from the geometry and follows it when the geometry changes. Tolerances and fits are printed exactly as you enter them.">
      <div className="flex items-baseline justify-between text-[12.5px]"><span className="text-muted">Prints</span><b className="tabular-nums" data-testid="dim-text">{text}</b></div>
      {d.type === "linear" && <Sel label="Orientation" value={d.orient} disabled={!canEdit} options={[["h", "Horizontal"], ["v", "Vertical"], ["aligned", "Aligned"]]} onChange={o => set({ orient: o } as Partial<Dim>)} />}
      {d.type === "ordinate" && <Sel label="Measures" value={d.axis} disabled={!canEdit} options={[["x", "X from origin"], ["y", "Y from origin"]]} onChange={o => set({ axis: o } as Partial<Dim>)} />}
      <div className="grid grid-cols-2 gap-2">
        <Txt label="Prefix" value={d.prefix ?? ""} disabled={!canEdit} max={24} placeholder="e.g. 4X" onChange={x => set({ prefix: x.trim() || undefined })} />
        <Txt label="Suffix" value={d.suffix ?? ""} disabled={!canEdit} max={24} placeholder="e.g. THRU" onChange={x => set({ suffix: x.trim() || undefined })} />
      </div>
      <Sel label="Tolerance" value={kind} disabled={!canEdit} options={[["none", "None (general)"], ["sym", "± symmetric"], ["dev", "Deviations"], ["limits", "Limits"], ...(d.type !== "angle" ? [["fit", "ISO fit (e.g. H7)"] as ["fit", string]] : [])]}
        onChange={k => setTol(k === "none" ? undefined : k === "fit" ? { kind: "fit", fit: "H7" } : k === "sym" ? { kind: "sym", up: tol && "up" in tol ? Math.abs(tol.up) || 0.1 : 0.1 } : { kind: k, up: tol && "up" in tol ? tol.up : 0.1, lo: tol && "lo" in tol ? tol.lo : -0.1 })} />
      {tol?.kind === "sym" && <Num label="±" value={tol.up} min={0.0001} step={0.01} disabled={!canEdit} onChange={x => setTol({ kind: "sym", up: x })} />}
      {(tol?.kind === "dev" || tol?.kind === "limits") && <>
        <Num label="Upper deviation" value={tol.up} step={0.01} disabled={!canEdit} onChange={x => setTol({ ...tol, up: x })} />
        <Num label="Lower deviation" value={tol.lo} step={0.01} disabled={!canEdit} onChange={x => setTol({ ...tol, lo: x })} /></>}
      {tol?.kind === "fit" && <Txt label="Fit (ISO 286)" value={tol.fit} disabled={!canEdit} max={9} placeholder="H7, g6 or H7/g6" onChange={x => { if (/^[A-Za-z]{1,2}\d{1,2}(\/[A-Za-z]{1,2}\d{1,2})?$/.test(x.trim())) setTol({ kind: "fit", fit: x.trim() }); else toast.error("A fit looks like H7, g6 or H7/g6"); }} />}
    </Sec>
  );
}

function AnnoProps({ doc, a, canEdit, upd }: { doc: DraftDoc; a: Anno; canEdit: boolean; upd: (f: (x: DraftDoc) => DraftDoc) => void }) {
  const set = (patch: Partial<Anno>) => upd(x => ({ ...x, annos: x.annos.map(y => (y.id === a.id ? { ...y, ...patch } as Anno : y)) }));
  void doc;
  switch (a.type) {
    case "text": return <Sec title="Note"><Txt label="Text" value={a.text} area max={500} disabled={!canEdit} onChange={t => t.trim() && set({ text: t } as Partial<Anno>)} /><Num label="Height" value={a.size} min={1.8} disabled={!canEdit} onChange={s => set({ size: s } as Partial<Anno>)} suffix="mm" /></Sec>;
    case "leader": return <Sec title="Leader"><Txt label="Text" value={a.text} max={120} disabled={!canEdit} onChange={t => set({ text: t } as Partial<Anno>)} /></Sec>;
    case "balloon": return <Sec title="Balloon"><Txt label="Item number" value={a.text} max={4} disabled={!canEdit} onChange={t => t.trim() && set({ text: t.trim() } as Partial<Anno>)} /></Sec>;
    case "datum": return <Sec title="Datum feature"><Txt label="Letter" value={a.letter} max={2} disabled={!canEdit} onChange={t => /^[A-Za-z]{1,2}$/.test(t.trim()) && set({ letter: t.trim().toUpperCase() } as Partial<Anno>)} /></Sec>;
    case "surface": return <Sec title="Surface texture (ISO 21920)"><Txt label="Requirement" value={a.text} max={24} disabled={!canEdit} onChange={t => set({ text: t } as Partial<Anno>)} />
      <Sel label="Material removal" value={a.removal} disabled={!canEdit} options={[["required", "Required"], ["prohibited", "Not allowed"], ["any", "Any process"]]} onChange={r => set({ removal: r } as Partial<Anno>)} /></Sec>;
    case "gdt": return <Sec title="Geometric tolerance (ISO 1101)" hint="Printed exactly as entered; never proposed by Formwright.">
      <Sel label="Characteristic" value={a.symbol} disabled={!canEdit} options={GDT_SYMBOLS.map(s => [s, GDT_LABEL[s]] as [GdtSymbol, string])} onChange={s => set({ symbol: s } as Partial<Anno>)} />
      <Txt label="Tolerance" value={a.tol} max={10} disabled={!canEdit} onChange={t => /^\d+(\.\d+)?$/.test(t.trim()) ? set({ tol: t.trim() } as Partial<Anno>) : toast.error("Enter a number, e.g. 0.05")} />
      <Txt label="Datums" value={a.datums.join(" ")} max={12} disabled={!canEdit} onChange={t => set({ datums: t.split(/[\s,|]+/).map(x => x.toUpperCase()).filter(x => /^[A-Z]{1,2}$/.test(x)).slice(0, 3) } as Partial<Anno>)} /></Sec>;
    case "hatch": return <Sec title="Section hatch"><Num label="Spacing (paper)" value={a.spacing} min={0.5} disabled={!canEdit} onChange={s => set({ spacing: s } as Partial<Anno>)} suffix="mm" /></Sec>;
    case "centermark": return <Sec title="Centre mark"><p className="text-[12px] text-muted">Follows its circle.</p></Sec>;
  }
}

/* ------------------------------------------------------------------ sheet + title + notes + revision table */
function SheetPanel({ doc, commit, canEdit }: Parameters<typeof DraftSidePanel>[0]) {
  const s = doc.sheet, t = doc.title;
  const setSheet = (patch: Partial<DraftDoc["sheet"]>) => {
    const next = { ...s, ...patch };
    // keep the drawing centred on the sheet when the paper changes
    if (patch.size || patch.orientation) { const [w0, h0] = sheetWH(s), [w1, h1] = sheetWH(next); next.origin = [s.origin[0] * w1 / w0, s.origin[1] * h1 / h0] as P2; }
    commit({ ...doc, sheet: next });
  };
  const setTitle = (k: keyof DraftDoc["title"]) => (v: string) => commit({ ...doc, title: { ...t, [k]: v.trim() } });
  const [note, setNote] = useState("");
  const scaleKey = `${s.scale[0]}:${s.scale[1]}`;
  return (
    <div>
      <Sec title="Sheet" hint="Changing the scale redraws the geometry at the new scale; sizes and dimension values do not change.">
        <Sel label="Size" value={s.size} disabled={!canEdit} options={Object.keys(SHEETS).map(k => [k, k] as [string, string])} onChange={v => setSheet({ size: v })} />
        <Sel label="Orientation" value={s.orientation} disabled={!canEdit} options={[["landscape", "Landscape"], ["portrait", "Portrait"]]} onChange={v => setSheet({ orientation: v })} />
        <Sel label="Scale" value={scaleKey} disabled={!canEdit} options={SCALES.map(([n, d]) => [`${n}:${d}`, `${n}:${d}`] as [string, string])} onChange={v => { const [n, d] = v.split(":").map(Number); setSheet({ scale: [n!, d!] }); }} />
        <Sel label="Projection" value={s.projection} disabled={!canEdit} options={[["first", "First angle (ISO E)"], ["third", "Third angle (ISO A)"]]} onChange={v => setSheet({ projection: v })} />
        <Sel label="Units" value={s.units} disabled={!canEdit} options={[["mm", "Millimetres"], ["in", "Inches"]]} onChange={v => setSheet({ units: v })} />
        <p className="text-[11.5px] text-muted">1 {s.units} draws as {kOf(s).toFixed(3).replace(/\.?0+$/, "")} mm on the paper.</p>
      </Sec>
      <Sec title="Title block" hint="Approval always stays “not approved”: Formwright never marks a drawing approved for manufacture.">
        <Txt label="Title" value={t.title} disabled={!canEdit} onChange={setTitle("title")} />
        <div className="grid grid-cols-2 gap-2"><Txt label="Drawing number" value={t.drawing_no} disabled={!canEdit} onChange={setTitle("drawing_no")} /><Txt label="Material" value={t.material} disabled={!canEdit} onChange={setTitle("material")} placeholder="Not specified" /></div>
        <div className="grid grid-cols-2 gap-2"><Txt label="Drawn by" value={t.drawn_by} disabled={!canEdit} onChange={setTitle("drawn_by")} /><Txt label="Date" value={t.date} disabled={!canEdit} onChange={setTitle("date")} /></div>
        <div className="grid grid-cols-2 gap-2"><Txt label="Checked by" value={t.checked_by} disabled={!canEdit} onChange={setTitle("checked_by")} /><Txt label="Company" value={t.company} disabled={!canEdit} onChange={setTitle("company")} /></div>
        <Txt label="General tolerances" value={t.tolerance} disabled={!canEdit} onChange={setTitle("tolerance")} placeholder="Not specified (e.g. ISO 2768-m)" />
      </Sec>
      <Sec title="Notes">
        {doc.notes.length > 0 && <ol className="space-y-1">{doc.notes.map((n, i) => (
          <li key={i} className="flex items-start gap-1.5 text-[12.5px]"><span className="text-muted">{i + 1}.</span><span className="min-w-0 flex-1">{n}</span>
            {canEdit && <button type="button" aria-label="Remove note" onClick={() => commit({ ...doc, notes: doc.notes.filter((_, j) => j !== i) })} className="rounded p-0.5 text-muted hover:text-danger"><X className="h-3.5 w-3.5" /></button>}</li>))}</ol>}
        {canEdit && <div className="flex gap-1.5"><Input value={note} maxLength={300} placeholder="e.g. Deburr all edges" className="h-8 text-[13px]" onChange={e => setNote(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && note.trim()) { commit({ ...doc, notes: [...doc.notes, note.trim()] }); setNote(""); } }} />
          <Button size="sm" variant="secondary" disabled={!note.trim()} icon={<Plus className="h-3.5 w-3.5" />} onClick={() => { commit({ ...doc, notes: [...doc.notes, note.trim()] }); setNote(""); }}>Add</Button></div>}
      </Sec>
      <RevTable doc={doc} commit={commit} canEdit={canEdit} />
    </div>
  );
}

function RevTable({ doc, commit, canEdit }: { doc: DraftDoc; commit: (d: DraftDoc) => void; canEdit: boolean }) {
  const [row, setRow] = useState({ rev: "", change: "", date: new Date().toISOString().slice(0, 10), by: doc.title.drawn_by });
  const next = String.fromCharCode(65 + doc.revisions.length);
  return (
    <Sec title="Revision table" hint="The rows you enter print in the title block's revision table (the last three); REV shows the latest. Saved versions are under History.">
      {doc.revisions.map((r, i) => (
        <div key={i} className="flex items-start gap-1.5 text-[12.5px]"><b className="w-6">{r.rev}</b><span className="min-w-0 flex-1">{r.change}<span className="block text-[11px] text-muted">{r.date} · {r.by}</span></span>
          {canEdit && <button type="button" aria-label="Remove row" onClick={() => commit({ ...doc, revisions: doc.revisions.filter((_, j) => j !== i) })} className="rounded p-0.5 text-muted hover:text-danger"><X className="h-3.5 w-3.5" /></button>}</div>))}
      {canEdit && <div className="space-y-1.5 rounded border border-border p-2">
        <div className="grid grid-cols-[48px_1fr] gap-1.5"><Input value={row.rev} placeholder={next} maxLength={6} className="h-7 text-[12.5px]" onChange={e => setRow({ ...row, rev: e.target.value })} />
          <Input value={row.change} placeholder="Description of the change" maxLength={120} className="h-7 text-[12.5px]" onChange={e => setRow({ ...row, change: e.target.value })} /></div>
        <div className="grid grid-cols-2 gap-1.5"><Input value={row.date} maxLength={12} className="h-7 text-[12.5px]" onChange={e => setRow({ ...row, date: e.target.value })} />
          <Input value={row.by} placeholder="By" maxLength={30} className="h-7 text-[12.5px]" onChange={e => setRow({ ...row, by: e.target.value })} /></div>
        <Button size="sm" variant="secondary" disabled={!row.change.trim()} icon={<Plus className="h-3.5 w-3.5" />}
          onClick={() => { commit({ ...doc, revisions: [...doc.revisions, { ...row, rev: row.rev.trim() || next, change: row.change.trim() }] }); setRow({ ...row, rev: "", change: "" }); }}>Add revision row</Button>
      </div>}
    </Sec>
  );
}

/* ------------------------------------------------------------------ layers */
function LayersPanel({ doc, layer, setLayer, hiddenLayers, setHiddenLayers, canEdit }: Parameters<typeof DraftSidePanel>[0]) {
  const counts = new Map<string, number>(); doc.geom.entities.forEach(e => counts.set(e.layer, (counts.get(e.layer) ?? 0) + 1));
  return (
    <div className="px-4 py-3">
      <p className="mb-2 text-[11.5px] text-muted">ISO 128-2 line types. New geometry goes on the active layer; centre lines and centre marks use Centre, dimensions and notes are on Dimension. Construction lines help you draw and are never printed or exported to PDF.</p>
      {LAYERS.map(l => (
        <div key={l.key} className={cx("mb-1 flex items-center gap-2 rounded border px-2 py-1.5 text-[12.5px]", layer === l.key ? "border-primary/50 bg-primary-soft/40" : "border-border")}>
          <input type="radio" name="active-layer" checked={layer === l.key} disabled={!canEdit || l.key === "dimension"} onChange={() => setLayer(l.key)} aria-label={`Make ${l.label} active`} />
          <svg width="36" height="10" className="shrink-0"><line x1="1" y1="5" x2="35" y2="5" stroke={l.key === "construction" ? "#5b7db1" : "#111"} strokeWidth={l.width * 4}
            strokeDasharray={l.key === "hidden" ? "6 2.4" : l.key === "center" ? "12 2 2 2" : l.key === "construction" ? "2 2" : undefined} /></svg>
          <span className="min-w-0 flex-1"><b>{l.label}</b><span className="block text-[11px] text-muted">{l.iso} · {l.width} mm · {counts.get(l.key) ?? 0}</span></span>
          <button type="button" aria-label={hiddenLayers.has(l.key) ? "Show layer" : "Hide layer"} className="rounded p-1 text-muted hover:bg-text/5 hover:text-text"
            onClick={() => { const n = new Set(hiddenLayers); if (n.has(l.key)) n.delete(l.key); else n.add(l.key); setHiddenLayers(n); }}>
            {hiddenLayers.has(l.key) ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button>
        </div>))}
      <p className="mt-2 text-[11px] text-muted">DXF layers: VISIBLE, HIDDEN (ACAD_ISO02W100), CENTER (ACAD_ISO04W100), DIMENSION, HATCH, TEXT, CONSTRUCTION (does not plot), SHEET.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ assist + templates */
function AssistPanel({ state, doc, canEdit, onInsert }: Parameters<typeof DraftSidePanel>[0]) {
  const tq = useQuery({ queryKey: ["draft-templates"], queryFn: draftsApi.templates, staleTime: Infinity });
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [tpl, setTpl] = useState("gasket");
  const [vals, setVals] = useState<Record<string, number>>({});
  const def = tq.data?.items.find(t => t.name === tpl);
  useEffect(() => { if (def) setVals(Object.fromEntries(def.params.map(p => [p.key, p.default]))); }, [def]);
  const ask = async () => {
    setBusy(true);
    try { const r = await draftsApi.assist(state.id, prompt, `a${Date.now().toString(36).slice(-5)}`); onInsert(r.fragment, r.message, r.missing); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "The request could not be drafted."); }
    finally { setBusy(false); }
  };
  const insertTpl = async () => {
    setBusy(true);
    try { const f = await draftsApi.template(tpl, { params: vals, scale: doc.sheet.scale, units: doc.sheet.units, prefix: `t${Date.now().toString(36).slice(-5)}` }); onInsert(f, `${def?.label} from your values.`, []); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "The template could not be drawn."); }
    finally { setBusy(false); }
  };
  return (
    <div>
      <Sec title="Draft from a description" hint="Gaskets, washers and plates with holes are read without AI. Anything else goes to the design agent (uses tokens); it may only use the sizes you give, and every value appears as a dimension measured from the drawn geometry for you to check.">
        <textarea rows={3} value={prompt} maxLength={400} disabled={!canEdit} onChange={e => setPrompt(e.target.value)} data-testid="assist-prompt"
          placeholder="e.g. draw a gasket Ø150 OD, Ø60 ID, 6 × Ø14 on PCD 120" className="w-full rounded border border-border bg-panel px-2 py-1.5 text-[12.5px] outline-none focus:border-primary" />
        <Button size="sm" loading={busy} disabled={!canEdit || !prompt.trim()} icon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => void ask()} data-testid="assist-go">Draft it</Button>
      </Sec>
      <Sec title="Templates (no AI)" hint="Deterministic: positions are calculated exactly from your values. Dimensions are attached to the geometry.">
        <Sel label="Part" value={tpl} options={(tq.data?.items ?? []).map(t => [t.name, t.label] as [string, string])} onChange={setTpl} disabled={!canEdit} />
        {def?.params.map(p => <Num key={p.key} label={p.label} value={vals[p.key] ?? p.default} step={p.integer ? 1 : 0.5} disabled={!canEdit} onChange={v => setVals(s => ({ ...s, [p.key]: p.integer ? Math.round(v) : v }))} />)}
        <Button size="sm" variant="secondary" loading={busy} disabled={!canEdit || !def} onClick={() => void insertTpl()} data-testid="template-insert">Draw template</Button>
      </Sec>
    </div>
  );
}

/* ------------------------------------------------------------------ check + history */
function CheckPanel({ state, doc, dirty }: Parameters<typeof DraftSidePanel>[0]) {
  const c = state.check;
  const P = pointMap(doc);
  const dangling = doc.dims.filter(d => measure(doc, d, P) === null).length;
  return (
    <div className="px-4 py-3">
      <div className="mb-3 flex items-start gap-2 rounded-lg border border-border bg-panel2 p-3 text-[12.5px]" data-testid="no-model-note">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div><b>Not linked to a model.</b> This is a 2D-only drawing, so no model-consistency check (CHK-12) runs on it. Dimension values are measured from the drawn geometry; whether the part is right is for you to judge. The sheet stays “NOT APPROVED FOR MANUFACTURE”.</div>
      </div>
      <div className="flex items-center gap-2 text-[13px] font-semibold">{c.passed ? <ShieldCheck className="h-4 w-4 text-success" /> : <ShieldAlert className="h-4 w-4 text-warning" />}Sheet layout check {dirty && <span className="text-[11px] font-normal text-muted">(last saved revision)</span>}</div>
      <ul className="mt-2 space-y-1 text-[12.5px]">
        <Row ok={!c.dangling.length} label="Every dimension and centre mark still references geometry" />
        <Row ok={!c.outside.length} label="Everything inside the drawing frame" />
        <Row ok={!c.over_title_block.length} label="Nothing over the title block or notes" />
        <Row ok={!c.overlaps.length} label="No overlapping dimension values" />
      </ul>
      {c.problems.length > 0 && <div className="mt-2 rounded border border-warning/30 bg-warning/5 p-2 text-[12px]">{c.problems.map(x => <div key={x}>• {x}</div>)}</div>}
      {dangling > 0 && <p className="mt-2 text-[12px] text-warning">{dangling} dimension(s) in the editor lost their geometry.</p>}
    </div>
  );
}
function Row({ ok, label }: { ok: boolean; label: string }) {
  return <li className="flex items-start gap-1.5">{ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> : <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />}{label}</li>;
}

function RevPanel({ state, onOpenRev, previewRev }: Parameters<typeof DraftSidePanel>[0]) {
  return (
    <div className="px-4 py-3">
      <div className="label mb-2 flex items-center gap-1.5"><History className="h-3.5 w-3.5" />Saved revisions</div>
      <p className="mb-2 text-[11.5px] text-muted">Each save keeps a snapshot. Open one to view it; restore it into the editor and save to make it current. Downloads always use a saved revision.</p>
      <ol className="space-y-1.5">{[...state.revs].reverse().map(r => (
        <li key={r.rev}><button type="button" onClick={() => onOpenRev(r.rev)} className={cx("w-full rounded border p-2 text-left text-[12.5px] hover:bg-panel2",
          (previewRev ?? state.rev) === r.rev ? "border-primary/50 bg-primary-soft/40" : "border-border")}>
          <div className="flex justify-between"><b>Revision {r.rev}{r.rev === state.rev ? " · current" : ""}</b><span className="text-[11px] text-muted">{r.date.slice(0, 16).replace("T", " ")}</span></div>
          <div className="text-[11.5px] text-muted">{r.note || "Saved"} · {r.entities} entities, {r.dims} dims · {r.by}</div></button></li>))}</ol>
    </div>
  );
}
