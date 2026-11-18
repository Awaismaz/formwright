import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Field, Input } from "@/components/ui";

/** Cosmetic thread fields (CAD-027): ISO 261 size and pitch, ISO 965 class, thread depth. The geometry stays the plain
 *  hole or cylinder; the thread is metadata the drawing calls out ("4X M6×1-6H ▽12") and the STEP file carries. */

export interface ThreadTables {
  sizes: number[]; pitches: Record<string, number[]>; tap_drill: Record<string, Record<string, number>>;
  internal_classes: string[]; external_classes: string[]; sources: Record<string, string>;
}
export interface ThreadValue { size: number; pitch: number; cls: string; depth: string }
export interface ThreadSpec { size: number; pitch: number; cls?: string; depth: number | null }

export function useThreadTables() {
  const q = useQuery({ queryKey: ["hole-standards"], queryFn: () => api.get<{ threads?: ThreadTables }>("/api/holes/standards"), staleTime: Infinity });
  return q.data?.threads;
}

const key = (n: number) => String(+n.toFixed(3));

/** Nearest ISO size for a cylinder: the major Ø for a shaft, the size whose tap drill matches a hole. */
export function sizeFor(dia: number, internal: boolean | null, T: ThreadTables | undefined): number {
  const sizes = T?.sizes ?? [3, 4, 5, 6, 8, 10, 12, 16, 20, 24];
  const score = (s: number) => {
    const drill = T?.tap_drill[key(s)]?.[key((T?.pitches[key(s)] ?? [1])[0]!)] ?? s * 0.85;
    return internal === false ? Math.abs(s - dia) : internal ? Math.abs(drill - dia) : Math.min(Math.abs(s - dia), Math.abs(drill - dia));
  };
  return sizes.reduce((a, b) => (score(b) < score(a) ? b : a), sizes[0]!);
}

export function toSpec(v: ThreadValue): ThreadSpec {
  const d = v.depth.trim() === "" ? null : Number(v.depth);
  return { size: v.size, pitch: v.pitch, ...(v.cls ? { cls: v.cls } : {}), depth: d && d > 0 ? d : null };
}

export default function ThreadFields({ value, onChange, internal, lockSize, depthHint }: {
  value: ThreadValue; onChange: (v: ThreadValue) => void;
  /** true: tapped hole, false: shaft, null: decided by the picked face (both class lists offered) */
  internal: boolean | null; lockSize?: boolean; depthHint?: string;
}) {
  const T = useThreadTables();
  const pitches = T?.pitches[key(value.size)] ?? [value.pitch];
  const classes = internal === true ? T?.internal_classes ?? ["6H"] : internal === false ? T?.external_classes ?? ["6g"]
    : [...(T?.internal_classes ?? ["6H"]), ...(T?.external_classes ?? ["6g"])];
  const sel = "h-8 w-full rounded border border-border bg-panel px-1.5 text-[12.5px]";
  const drill = T?.tap_drill[key(value.size)]?.[key(value.pitch)];
  return (
    <div className="space-y-2" data-thread-fields>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Size"><select className={sel} value={value.size} disabled={lockSize} aria-label="Thread size"
          onChange={ev => { const s = Number(ev.target.value); onChange({ ...value, size: s, pitch: (T?.pitches[key(s)] ?? [value.pitch])[0]! }); }}>
          {(T?.sizes ?? [value.size]).map(s => <option key={s} value={s}>M{s}</option>)}</select></Field>
        <Field label="Pitch"><select className={sel} value={value.pitch} aria-label="Thread pitch" onChange={ev => onChange({ ...value, pitch: Number(ev.target.value) })}>
          {pitches.map((p, i) => <option key={p} value={p}>{p}{i === 0 ? " coarse" : " fine"}</option>)}</select></Field>
        <Field label="Class"><select className={sel} value={value.cls} aria-label="Thread class" onChange={ev => onChange({ ...value, cls: ev.target.value })}>
          {internal === null && <option value="">Auto</option>}
          {classes.map(c => <option key={c} value={c}>{c}</option>)}</select></Field>
      </div>
      <Field label="Thread depth" hint={depthHint ?? "Empty = the full length"}>
        <div className="flex items-center gap-1.5"><Input value={value.depth} onChange={ev => onChange({ ...value, depth: ev.target.value })} inputMode="decimal" className="h-8" aria-label="Thread depth" placeholder="Full" /><span className="w-7 text-xs text-muted">mm</span></div>
      </Field>
      <p className="text-[11px] leading-snug text-muted">
        M{value.size}×{value.pitch}{value.cls ? `-${value.cls}` : ""}{internal !== false && drill ? ` · tap drill Ø${drill}` : ""}. Cosmetic: the model keeps the plain {internal === false ? "cylinder" : "hole"}; drawings and the STEP file carry the thread. {T?.sources.pitch ?? ""}
      </p>
    </div>
  );
}
