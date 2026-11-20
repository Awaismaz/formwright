import { ArrowDownUp, Link2, MousePointerClick, Pencil, Sparkles, X } from "lucide-react";
import { cx } from "@/lib/format";
import { Button, Input, Toggle } from "@/components/ui";
import type { AsmPick } from "./viewer";
import type { AsmView, Mate, MateType } from "./types";
import { MATE_ICON } from "./Tree";
import { Section } from "./bits";

export type MateChoice = "auto" | MateType;
export const MATE_CHOICES: { value: MateChoice; label: string; help: string }[] = [
  { value: "auto", label: "Smart", help: "Two flat faces → coincident, two cylinders or circular edges → concentric." },
  { value: "coincident", label: "Coincident", help: "Flat faces touch, facing each other." },
  { value: "flush", label: "Flush", help: "Flat faces in the same plane, facing the same way." },
  { value: "concentric", label: "Concentric", help: "Axes of cylinders, circular or straight edges in line." },
  { value: "distance", label: "Distance", help: "Flat faces facing each other with a gap." },
  { value: "angle", label: "Angle", help: "Angle between the face normals (0° = parallel, same direction)." },
  { value: "gear", label: "Gear mesh", help: "Two gear bores (or their shafts): axes parallel at the centre distance. Leave it blank for m(z1+z2)/2 from the gears." },
];

/** Plain description of a pick: "Flat face", "Cylinder Ø6.6", "Circular edge Ø12". */
export function describePick(view: AsmView, p: AsmPick, topoFace?: (part: string, id: number) => { type: string; radius?: number } | undefined,
  topoEdge?: (part: string, id: number) => { type: string; radius?: number } | undefined): string {
  const inst = view.instances.find(i => i.id === p.inst);
  if (!inst) return "";
  if (p.kind === "face") {
    const f = topoFace?.(inst.part, p.id);
    const t = f?.type === "plane" ? "Flat face" : f?.type === "cylinder" ? `Cylinder Ø${+((f.radius ?? 0) * 2).toFixed(3)}` : f ? `${f.type[0]!.toUpperCase()}${f.type.slice(1)} face` : "Face";
    return `${t} · ${inst.display}`;
  }
  const e = topoEdge?.(inst.part, p.id);
  const t = e?.type === "circle" ? `Circular edge Ø${+((e.radius ?? 0) * 2).toFixed(3)}` : e?.type === "line" ? "Straight edge" : "Edge";
  return `${t} · ${inst.display}`;
}

export function MatePanel({ view, choice, onChoice, picks, onClearPick, value, onValue, flip, onFlip, onAdd, busy, describe, editing, onCancelEdit }: {
  view: AsmView; choice: MateChoice; onChoice: (c: MateChoice) => void; picks: AsmPick[]; onClearPick: (k: number) => void;
  value: string; onValue: (v: string) => void; flip: boolean; onFlip: (v: boolean) => void; onAdd: () => void; busy: boolean;
  describe: (p: AsmPick) => string; editing?: Mate | null; onCancelEdit?: () => void;
}) {
  const help = MATE_CHOICES.find(c => c.value === choice)!.help;
  const needsValue = choice === "distance" || choice === "angle";
  const showValue = needsValue || choice === "gear";
  const ready = picks.length === 2 && (!needsValue || value.trim() !== "");
  return (
    <div data-testid="mate-panel">
      {editing && (
        <div className="flex items-center gap-2 border-b border-primary/30 bg-primary-soft/60 px-4 py-2.5 text-[12.5px]" data-testid="mate-editing">
          <Pencil className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">Editing <b>{editing.label}</b>{editing.status === "broken" ? ": pick the missing reference in the view." : ". Clear a reference to re-pick it."}</span>
          <button type="button" onClick={onCancelEdit} className="text-[12px] font-medium text-muted hover:text-text">Cancel</button>
        </div>
      )}
      <Section title="Mate type">
        <div className="grid grid-cols-3 gap-1.5">
          {MATE_CHOICES.filter(c => !editing || c.value !== "auto").map(c => (
            <button key={c.value} type="button" onClick={() => onChoice(c.value)} data-mate-type={c.value}
              className={cx("flex items-center justify-center gap-1.5 rounded border px-2 py-1.5 text-[12.5px] transition",
                choice === c.value ? "border-primary bg-primary-soft font-medium text-primary" : "border-border text-muted hover:border-primary/40 hover:text-text")}>
              {c.value === "auto" ? <Sparkles className="h-3.5 w-3.5" /> : MATE_ICON[c.value]}{c.label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-[11.5px] leading-snug text-muted">{help}</p>
      </Section>
      <Section title="References">
        <div className="space-y-1.5">
          {[0, 1].map(k => {
            const p = picks[k];
            return (
              <div key={k} className={cx("flex items-center gap-2 rounded border px-2.5 py-2 text-[12.5px]",
                p ? "border-primary/40 bg-primary-soft/50" : k === picks.length ? "border-dashed border-primary/50" : "border-dashed border-border")}>
                <span className={cx("flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                  p ? "bg-primary text-primary-fg" : "bg-text/10 text-muted")}>{k + 1}</span>
                {p ? <span className="min-w-0 flex-1 truncate">{describe(p)}</span>
                  : <span className="flex flex-1 items-center gap-1.5 text-muted"><MousePointerClick className="h-3.5 w-3.5" />{k === picks.length ? "Pick a face or edge in the view" : "Then a second one on another part"}</span>}
                {p && <button type="button" onClick={() => onClearPick(k)} className="rounded p-0.5 text-muted hover:text-text"><X className="h-3.5 w-3.5" /></button>}
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-[11.5px] leading-snug text-muted">The second part moves to meet the first. Fixed parts never move.</p>
      </Section>
      {(needsValue || choice !== "auto") && (
        <Section title="Options">
          {showValue && (
            <label className="mb-2.5 flex items-center gap-2 text-[12.5px]">
              <span className="w-20 text-muted">{choice === "distance" ? "Distance" : choice === "gear" ? "Centre dist." : "Angle"}</span>
              <Input type="number" value={value} onChange={e => onValue(e.target.value)} step={choice === "angle" ? 5 : 0.5}
                min={0} max={choice === "angle" ? 180 : 10000} className="h-8 w-28" data-testid="mate-value"
                placeholder={choice === "gear" ? "auto" : undefined} />
              <span className="text-muted">{choice === "angle" ? "°" : "mm"}</span>
            </label>
          )}
          {choice !== "gear" && <label className="flex items-center gap-2 text-[12.5px]">
            <Toggle checked={flip} onChange={onFlip} label="Flip" />
            <ArrowDownUp className="h-3.5 w-3.5 text-muted" />
            <span>{choice === "concentric" ? "Reverse axis direction" : "Flip alignment"}</span>
          </label>}
        </Section>
      )}
      <div className="px-4 py-3.5">
        <Button className="w-full" icon={editing ? <Pencil className="h-4 w-4" /> : <Link2 className="h-4 w-4" />} disabled={!ready || !view.can_edit} loading={busy} onClick={onAdd} data-testid="add-mate">
          {editing ? "Save mate" : "Add mate"}
        </Button>
        {!view.can_edit && <p className="mt-2 text-[11.5px] text-muted">Viewers can't add mates.</p>}
      </div>
    </div>
  );
}
