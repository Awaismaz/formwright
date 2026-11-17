import type { ReactNode } from "react";
import { RotateCcw, Sparkles } from "lucide-react";
import { cx } from "@/lib/format";
import { Toggle } from "@/components/ui";
import type { Presets, Settings } from "./types";

/** Short names for the two-column finish grid (full names show as tooltips and in labels). */
const SHORT: Record<string, string> = {
  anodised: "Anodised Al", bead_blasted: "Blasted Al", brushed_aluminium: "Brushed Al", machined_steel: "Machined steel",
  stainless_brushed: "Stainless", black_oxide: "Black oxide", titanium: "Titanium", abs: "ABS textured",
  pla: "PLA satin", clay: "Studio clay",
};

export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-border px-4 py-4">
      <div className="mb-2.5 flex items-center justify-between"><div className="label">{title}</div>{aside}</div>
      {children}
    </section>
  );
}

export function Seg<T extends string>({ value, options, onChange, name }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; name: string }) {
  return (
    <div role="radiogroup" aria-label={name} className="flex flex-wrap gap-1 rounded-md bg-panel2 p-1">
      {options.map(o => (
        <button key={o.id} role="radio" aria-checked={value === o.id} data-opt={`${name}:${o.id}`} onClick={() => onChange(o.id)}
          className={cx("flex-1 whitespace-nowrap rounded px-2 py-1 text-[12.5px] transition",
            value === o.id ? "bg-panel font-medium text-text shadow-sm" : "text-muted hover:text-text")}>{o.label}</button>
      ))}
    </div>
  );
}

/** Metallic-looking swatch: the finish colour with a soft highlight, so metals read differently from plastics. */
export function Swatch({ hex, metal, size = 28 }: { hex: string; metal: boolean; size?: number }) {
  const bg = metal
    ? `linear-gradient(135deg, rgba(255,255,255,.55) 0%, rgba(255,255,255,0) 38%, rgba(0,0,0,.18) 70%, rgba(255,255,255,.25) 100%), ${hex}`
    : `radial-gradient(circle at 30% 28%, rgba(255,255,255,.35), rgba(255,255,255,0) 55%), ${hex}`;
  return <span className="block shrink-0 rounded-full border border-black/10 shadow-inner" style={{ width: size, height: size, background: bg }} />;
}

export function LookPanel({ presets, value, onChange, suggested, material, finishSlot }: {
  presets: Presets; value: Settings; onChange: (s: Settings) => void;
  suggested: { finish: string; colour: string | null }; material: string | null;
  /** replaces the finish picker (assemblies: one finish per part, from its material) */
  finishSlot?: ReactNode;
}) {
  const set = (patch: Partial<Settings>) => onChange({ ...value, ...patch });
  const finish = presets.finishes.find(f => f.id === value.finish) ?? presets.finishes[0]!;
  const groups = [...new Set(presets.finishes.map(f => f.group))];
  const isSuggested = value.finish === suggested.finish && (value.colour ?? null) === (suggested.colour ?? null);
  const sugLabel = presets.finishes.find(f => f.id === suggested.finish)?.label;

  return (
    <div className="text-sm">
      {finishSlot ?? <Section title="Finish" aside={!isSuggested && <button className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline"
        onClick={() => set({ finish: suggested.finish, colour: suggested.colour })}><RotateCcw className="h-3 w-3" />Suggested</button>}>
        <div className="mb-3 flex items-start gap-2 rounded-md border border-border bg-panel2/60 px-2.5 py-2 text-[12px] text-muted">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <span>{material && material !== "unspecified" ? <>Material <b className="text-text">{material}</b> suggests <b className="text-text">{sugLabel}</b>.</> : <>No material set on this part, so it starts in neutral studio clay.</>}</span>
        </div>
        {groups.map(g => (
          <div key={g} className="mb-2.5">
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">{g}</div>
            <div className="grid grid-cols-2 gap-1">
              {presets.finishes.filter(f => f.group === g).map(f => (
                <button key={f.id} data-finish={f.id} onClick={() => set({ finish: f.id, colour: f.default_colour })} title={f.label}
                  className={cx("flex min-w-0 items-center gap-1.5 rounded-md border px-1.5 py-1 text-left text-[12px] leading-tight transition",
                    value.finish === f.id ? "border-primary bg-primary-soft/60 font-medium" : "border-border/60 hover:bg-panel2")}>
                  <Swatch hex={f.id === value.finish && finish.colours && value.colour ? (finish.colours.find(c => c.id === value.colour)?.hex ?? f.swatch) : f.swatch}
                    metal={f.group === "Metal"} size={18} />
                  <span className="min-w-0 line-clamp-2">{SHORT[f.id] ?? f.label}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {finish.colours && (
          <div className="mt-3">
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Colour</div>
            <div className="flex flex-wrap gap-2">
              {finish.colours.map(c => (
                <button key={c.id} title={c.label} aria-label={c.label} data-colour={c.id} onClick={() => set({ colour: c.id })}
                  className={cx("rounded-full p-0.5 ring-2 transition", value.colour === c.id ? "ring-primary" : "ring-transparent hover:ring-border")}>
                  <Swatch hex={c.hex} metal={finish.group === "Metal"} size={24} />
                </button>
              ))}
            </div>
            <div className="mt-1 text-[12px] text-muted">{finish.colours.find(c => c.id === value.colour)?.label}</div>
          </div>
        )}
      </Section>}

      <Section title="Lighting">
        <div className="grid grid-cols-3 gap-1.5">
          {presets.lighting.map(l => (
            <button key={l.id} data-lighting={l.id} onClick={() => set({ lighting: l.id })} title={l.hint}
              className={cx("overflow-hidden rounded-md border text-left transition",
                value.lighting === l.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-text/30")}>
              <span className="block h-9 w-full" style={{ background: `radial-gradient(circle at 50% 35%, ${l.background}, ${l.id === "dark" ? "#08090b" : l.id === "technical" ? "#f1f2f4" : "#c9ced4"})` }} />
              <span className="block truncate px-1.5 py-1 text-[11.5px] font-medium">{l.label.replace(" softbox", "").replace(" dramatic", "")}</span>
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-[11.5px] text-muted">{presets.lighting.find(l => l.id === value.lighting)?.hint}</p>
      </Section>

      <Section title="Camera">
        <Seg name="camera" value={value.camera} options={presets.cameras} onChange={camera => set({ camera })} />
        <div className="mt-3 mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Frame</div>
        <Seg name="aspect" value={value.aspect} options={presets.aspects.map(a => ({ id: a, label: a }))} onChange={aspect => set({ aspect })} />
        <div className="mt-3 mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Pose</div>
        <Seg name="pose" value={value.pose} options={presets.poses.map(p => ({ id: p.id, label: p.id === "auto" ? "Auto" : "As modelled" }))} onChange={pose => set({ pose })} />
        <p className="mt-1 text-[11.5px] text-muted">Auto lays long, slender parts on their side.</p>
      </Section>

      <Section title="Output">
        <label className="flex items-center justify-between gap-3 py-1"><span>Transparent background<span className="block text-[11.5px] text-muted">PNG with alpha and a soft shadow</span></span>
          <Toggle checked={value.transparent} onChange={transparent => set({ transparent })} label="Transparent background" /></label>
        <label className="mt-2 flex items-center justify-between gap-3 py-1"><span>Soften edges<span className="block text-[11.5px] text-muted">Shading-only edge highlight, geometry unchanged</span></span>
          <Toggle checked={value.soften_edges} onChange={soften_edges => set({ soften_edges })} label="Soften edges" /></label>
      </Section>
    </div>
  );
}
