import { useState, type ReactNode } from "react";
import { Crosshair, Plus, Trash2 } from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import type { DatumIn, DrawingEdits, DrawingRecord, FrameIn, GdtTarget } from "./types";

/** Drawing Studio "Annotate" tab: cosmetic threads (read from the model), detail views (DRW-011) and GD&T (DRW-013).
 *  GD&T is never added automatically: only what the user enters here, or what a Design Office interface spec states
 *  (shown read-only with its interface). */

export type ViewPoint = { view: string; u: number; v: number };
export type RequestPick = (hint: string, cb: (p: ViewPoint) => void) => void;

const CHARS: [string, string, "none" | "required" | "optional"][] = [
  ["flatness", "Flatness", "none"], ["straightness", "Straightness", "none"], ["circularity", "Circularity", "none"],
  ["cylindricity", "Cylindricity", "none"], ["parallelism", "Parallelism", "required"], ["perpendicularity", "Perpendicularity", "required"],
  ["angularity", "Angularity", "required"], ["position", "Position", "optional"], ["concentricity", "Coaxiality", "required"],
  ["symmetry", "Symmetry", "required"], ["circular_runout", "Circular run-out", "required"], ["total_runout", "Total run-out", "required"],
  ["profile_line", "Profile of a line", "optional"], ["profile_surface", "Profile of a surface", "optional"],
];
const DIA_OK = new Set(["position", "concentricity", "straightness", "perpendicularity", "parallelism", "angularity"]);
const LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ".split("");
const SCALES = ["", "2:1", "5:1", "10:1", "20:1"];
const sel = "h-8 w-full rounded border border-border bg-panel px-1.5 text-[12.5px]";

function Section({ title, children, hint }: { title: string; children: ReactNode; hint?: ReactNode }) {
  return <div className="border-b border-border px-4 py-3.5"><div className="label mb-1.5">{title}</div>{hint && <p className="mb-2 text-[11.5px] leading-snug text-muted">{hint}</p>}{children}</div>;
}

export default function AnnotatePanel({ rec, edits, disabled, onSave, requestPick }: {
  rec: DrawingRecord; edits: DrawingEdits; disabled: boolean; onSave: (e: DrawingEdits) => void; requestPick: RequestPick;
}) {
  const details = edits.details ?? [];
  const gdt = edits.gdt ?? { datums: [], frames: [] };
  const drawn = rec.details?.drawn ?? [];
  const icdDatums = (rec.gdt?.datums ?? []).filter(d => d.source === "icd");
  const allLetters = [...new Set([...icdDatums.map(d => d.letter), ...gdt.datums.map(d => d.letter)])];
  const freeLetters = LETTERS.filter(l => !allLetters.includes(l));
  const targets: { value: string; label: string }[] = [
    ...rec.callouts.filter(c => !c.hidden).map(c => ({ value: `callout:${c.id}`, label: `${c.lines.map(l => l.text).join(" / ")} (${c.view})` })),
    ...rec.dimensions.filter(d => !d.hidden && !d.aux).map(d => ({ value: `dim:${d.id}`, label: `${d.text} (${d.view})` })),
  ];
  const saveGdt = (g: { datums: DatumIn[]; frames: FrameIn[] }) => onSave({ ...edits, gdt: g });

  // detail form
  const [dr, setDr] = useState("10");
  const [dscale, setDscale] = useState("");
  // datum form
  const [dl, setDl] = useState(freeLetters[0] ?? "A");
  const [dAttach, setDAttach] = useState("pick");
  // frame form
  const [ch, setCh] = useState("position");
  const [tol, setTol] = useState("0.1");
  const [dia, setDia] = useState(true);
  const [mod, setMod] = useState<"" | "M" | "L">("");
  const [refs, setRefs] = useState<string[]>(["", "", ""]);
  const [fAttach, setFAttach] = useState("pick");
  const need = CHARS.find(c => c[0] === ch)![2];

  const withTarget = (attach: string, hint: string, done: (t: GdtTarget) => void) => {
    if (attach === "pick") requestPick(hint, p => done({ kind: "point", ...p }));
    else { const [k, id] = attach.split(":"); done({ kind: k as "dim" | "callout", id: id! }); }
  };
  const attachSelect = (v: string, set: (s: string) => void, label: string) => (
    <select className={sel} value={v} onChange={ev => set(ev.target.value)} aria-label={label}>
      <option value="pick">Pick a point on the sheet…</option>
      {targets.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
    </select>);

  return (
    <div data-testid="annotate-panel">
      <Section title="Threads" hint="Cosmetic threads come from the model (Hole Wizard → Cosmetic thread, or Features → Cosmetic Thread in the Design Studio).">
        {(rec.threads ?? []).length === 0 ? <p className="text-[12.5px] text-muted">No cosmetic threads on this model.</p>
          : <ul className="space-y-1 text-[12.5px]">{rec.threads!.map((t, i) => <li key={i} className="flex items-center gap-2"><Badge>{t.internal ? "Internal" : "External"}</Badge><span className="font-medium">{t.designation}</span><span className="text-muted">{t.depth ? `${t.depth} mm deep` : "full length"}{t.feature ? ` · ${t.feature}` : ""}</span></li>)}</ul>}
        {(rec.threads_unmatched ?? 0) > 0 && <p className="mt-1 text-[11.5px] text-warning">{rec.threads_unmatched} thread(s) not drawn: they are not on a hole or cylinder along a principal axis.</p>}
      </Section>

      <Section title="Detail views" hint="Pick the centre of a region on a view; it is redrawn at a larger standard scale and stays in step with the model.">
        {details.length > 0 && <ul className="mb-2 space-y-1 text-[12.5px]">{details.map((d, i) => {
          const dd = drawn.find(x => x.parent === d.view && Math.abs(x.u - d.u) < 1e-6 && Math.abs(x.v - d.v) < 1e-6);
          return <li key={i} className="flex items-center gap-2" data-detail>
            <span className="font-medium">{dd ? `Detail ${dd.letter} (${dd.scale})` : "Not drawn"}</span>
            <span className="flex-1 text-muted">{d.view} view, R{d.r}</span>
            <button disabled={disabled} onClick={() => onSave({ ...edits, details: details.filter((_, j) => j !== i) })} aria-label="Remove detail" className="text-muted hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>
          </li>;
        })}</ul>}
        {(rec.details?.skipped ?? []).map(s => <p key={s} className="text-[11.5px] text-warning">{s}</p>)}
        <div className="grid grid-cols-2 gap-2">
          <label className="text-[11.5px] text-muted">Radius (model mm)<Input value={dr} onChange={ev => setDr(ev.target.value)} className="mt-0.5 h-8" inputMode="decimal" aria-label="Detail radius" /></label>
          <label className="text-[11.5px] text-muted">Scale<select className={`${sel} mt-0.5`} value={dscale} onChange={ev => setDscale(ev.target.value)} aria-label="Detail scale">
            {SCALES.map(s => <option key={s} value={s}>{s || "Auto"}</option>)}</select></label>
        </div>
        <Button size="sm" variant="secondary" className="mt-2" icon={<Crosshair className="h-3.5 w-3.5" />} disabled={disabled || !(Number(dr) > 0)} data-testid="add-detail"
          onClick={() => requestPick("Click the centre of the detail on a view", p => onSave({ ...edits, details: [...details, { ...p, r: Number(dr), scale: dscale || null }] }))}>
          Add detail view</Button>
      </Section>

      <Section title="Datums" hint="Datum feature symbols (ISO 5459). Interface-spec datums come from the Design Office ICD.">
        <ul className="mb-2 space-y-1 text-[12.5px]">
          {(rec.gdt?.datums ?? []).map(d => <li key={d.letter} className="flex items-center gap-2" data-datum={d.letter}>
            <span className="inline-flex h-5 w-5 items-center justify-center border border-text text-[11px] font-semibold">{d.letter}</span>
            <span className="flex-1 truncate text-muted">{d.source === "icd" ? `From the interface spec (${d.ref}): ${d.label ?? ""}` : `${d.view} view`}</span>
            {d.source === "user" && <button disabled={disabled} onClick={() => saveGdt({ ...gdt, datums: gdt.datums.filter(x => x.letter !== d.letter) })} aria-label={`Remove datum ${d.letter}`} className="text-muted hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>}
          </li>)}
        </ul>
        <div className="grid grid-cols-[64px_1fr] gap-2">
          <select className={sel} value={dl} onChange={ev => setDl(ev.target.value)} aria-label="Datum letter">{freeLetters.map(l => <option key={l}>{l}</option>)}</select>
          {attachSelect(dAttach, setDAttach, "Datum attached to")}
        </div>
        <Button size="sm" variant="secondary" className="mt-2" icon={<Plus className="h-3.5 w-3.5" />} disabled={disabled || !freeLetters.includes(dl)} data-testid="add-datum"
          onClick={() => withTarget(dAttach, `Click the face (an edge seen on a view) for datum ${dl}`, t => { saveGdt({ ...gdt, datums: [...gdt.datums, { letter: dl, target: t }] }); setDl(freeLetters.filter(l => l !== dl)[0] ?? ""); })}>
          Add datum {dl}</Button>
      </Section>

      <Section title="Geometric tolerances" hint="Feature control frames (ISO 1101). Only what you enter here, or what the interface spec states, is drawn.">
        <ul className="mb-2 space-y-1 text-[12.5px]">
          {(rec.gdt?.frames ?? []).map(f => <li key={f.id} className="flex items-center gap-2" data-frame={f.id}>
            <span className="flex-1">{f.text}<span className="ml-1 text-[11px] text-muted">{f.source === "icd" ? `· interface spec ${f.ref ?? ""}` : `· ${f.view} view`}</span></span>
            {f.source === "user" && <button disabled={disabled} onClick={() => saveGdt({ ...gdt, frames: gdt.frames.filter((_, j) => `gdt-${j + 1}` !== f.id) })} aria-label="Remove frame" className="text-muted hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>}
          </li>)}
        </ul>
        <div className="grid grid-cols-2 gap-2">
          <select className={sel} value={ch} onChange={ev => { setCh(ev.target.value); setDia(DIA_OK.has(ev.target.value) && ev.target.value === "position"); }} aria-label="Characteristic">
            {CHARS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <div className="flex items-center gap-1.5">
            {DIA_OK.has(ch) && <label className="flex items-center gap-1 text-[12px]"><input type="checkbox" checked={dia} onChange={ev => setDia(ev.target.checked)} />Ø</label>}
            <Input value={tol} onChange={ev => setTol(ev.target.value)} className="h-8" inputMode="decimal" aria-label="Tolerance" />
          </div>
          <select className={sel} value={mod} onChange={ev => setMod(ev.target.value as "" | "M" | "L")} aria-label="Material condition">
            <option value="">No modifier</option><option value="M">Ⓜ maximum material</option><option value="L">Ⓛ least material</option></select>
          <div className="flex gap-1">{refs.map((r, i) => <select key={i} className={sel} value={r} disabled={need === "none"} aria-label={`Datum reference ${i + 1}`}
            onChange={ev => setRefs(x => x.map((y, j) => (j === i ? ev.target.value : y)))}><option value="">-</option>{allLetters.map(l => <option key={l}>{l}</option>)}</select>)}</div>
        </div>
        <div className="mt-2">{attachSelect(fAttach, setFAttach, "Frame attached to")}</div>
        {need === "required" && !refs.some(Boolean) && <p className="mt-1 text-[11.5px] text-muted">This characteristic needs a datum reference.</p>}
        <Button size="sm" variant="secondary" className="mt-2" icon={<Plus className="h-3.5 w-3.5" />} data-testid="add-frame"
          disabled={disabled || !(Number(tol) > 0) || (need === "required" && !refs.some(Boolean))}
          onClick={() => withTarget(fAttach, "Click the feature the frame points to", t => saveGdt({ ...gdt, frames: [...gdt.frames, {
            char: ch, tol: Number(tol), dia: DIA_OK.has(ch) && dia, mod: mod || null, datums: need === "none" ? [] : refs.filter(Boolean), target: t }] }))}>
          Add tolerance frame</Button>
        {((rec.gdt?.unresolved ?? []).length > 0 || (rec.gdt?.missing ?? []).length > 0) && <div className="mt-2 rounded border border-warning/40 bg-warning/5 p-2 text-[11.5px]">
          <div className="font-medium">Not on the sheet</div>
          {(rec.gdt?.unresolved ?? []).map((u, i) => <div key={i}>{u.type === "datum" ? `Datum ${u.letter}` : `${u.char} frame`}{u.label ? `: ${u.label}` : ""}{u.ref ? ` (${u.ref})` : ""}</div>)}
          {(rec.gdt?.missing ?? []).map((m, i) => <div key={`m${i}`}>{m.ref}: its dimension is not on this view</div>)}
        </div>}
      </Section>
    </div>
  );
}
