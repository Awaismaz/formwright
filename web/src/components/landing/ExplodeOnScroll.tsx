import { useEffect, useMemo, useRef, useState } from "react";
import { cx } from "@/lib/format";
import LazyScene from "./LazyScene";
import type { ScenePart } from "./PartScene";
import { useReducedMotion } from "./motion";
import { Badge3D, Card3D, useScrollProgress } from "./site";
import { EXPLODE_DZ, SEAT_ORDER } from "./hero/story";
import manifest from "./hero/gearbox.json";

/**
 * Sticky scroll story: the real PG-5 gearbox parts (the same files as the hero) assemble bottom-up as the page
 * scrolls, group by group in the Design Office's seating order, while the parts list ticks off each item.
 * Reduced motion: no pinning, a still exploded view and the full list.
 */

type Inst = { id: string; part: string; at: number[] };
const INST = manifest.instances as Inst[];
const COLOR: Record<string, string> = {
  input_cover: "#aeb9c7", output_cover: "#aeb9c7", motor_flange: "#9eabbb", ring: "#8c97a6", sun: "#d8975a", planet: "#c3ccd6",
  carrier_a: "#4a7cc9", carrier_b: "#4a7cc9", input_shaft: "#dfe4ea", output_shaft: "#dfe4ea", pin: "#dfe4ea", dowel: "#dfe4ea",
  b6204: "#a9b3bf", b6001: "#a9b3bf", b6000: "#a9b3bf", shcs_m5: "#30353d",
};
const groupOf = (part: string) => SEAT_ORDER.findIndex(g => g.includes(part));
const N = SEAT_ORDER.length;

/** Parts list rows: balloon, item, quantity, and the seating groups it waits for. */
const BOM: { item: string; qty: string; groups: number[] }[] = [
  { item: "Motor flange and input cover, NEMA 23", qty: "1 + 1", groups: [0] },
  { item: "Deep groove ball bearing 6001", qty: "1", groups: [1] },
  { item: "Input shaft, Ø6.35 motor socket", qty: "1", groups: [2] },
  { item: "Carrier plate A with planet pins Ø10", qty: "1 + 3", groups: [3, 4] },
  { item: "Planet gear 27T, m1.5, on 6000 bearings", qty: "3 + 3", groups: [5, 6] },
  { item: "Sun gear 18T and internal ring 72T", qty: "1 + 1", groups: [7, 8] },
  { item: "Carrier plate B, output shaft Ø20, 2 × 6204", qty: "1 + 1 + 2", groups: [9, 10, 11, 12] },
  { item: "Output cover, 6 × M5 socket head cap screws", qty: "1 + 6", groups: [13, 14] },
];

const ease = (x: number) => x * x * (3 - 2 * x);
const clamp = (x: number) => Math.min(1, Math.max(0, x));

/** 1 = fully exploded, 0 = seated, for one seating group at assembly progress a (0..1). */
const lift = (g: number, a: number) => 1 - ease(clamp((a * (N + 0.6) - g) / 1.6));

/** Line-drawing poster of the exploded stack: shown while the 3D loads, on low-end devices and without WebGL. */
function Poster() {
  const rows = [[150, 18], [92, 10], [40, 26], [132, 8], [150, 22], [132, 8], [78, 34], [150, 20]];
  let y = 26;
  return (
    <svg viewBox="0 0 320 520" className="h-full w-full" role="img" aria-label="Exploded view of the PG-5 planetary gearbox: eight groups of parts stacked on one axis.">
      <path d="M160 6v508" stroke="rgb(var(--s-bp))" strokeWidth="1" strokeDasharray="14 4 2 4" opacity=".7" />
      {rows.map(([w, h], i) => {
        const top = y; y += h + 34;
        const rx = w / 2, ry = w / 7;
        return (
          <g key={i} fill="none" stroke="rgb(var(--s-ink))" strokeWidth="1.2">
            <ellipse cx="160" cy={top} rx={rx} ry={ry} fill="rgb(var(--s-slab))" />
            <path d={`M${160 - rx} ${top}v${h}a${rx} ${ry} 0 0 0 ${w} 0v${-h}`} fill="rgb(var(--s-sheet-2))" />
            <ellipse cx="160" cy={top} rx={rx} ry={ry} />
            <path d={`M${160 + rx} ${top + h / 2}h${150 - rx - 18}`} stroke="rgb(var(--s-ink-2))" strokeWidth=".8" />
            <circle cx="300" cy={top + h / 2} r="11" fill="rgb(var(--s-sheet))" />
            <text x="300" y={top + h / 2 + 4} textAnchor="middle" fontSize="11" fill="rgb(var(--s-ink))" stroke="none" fontFamily="IBM Plex Mono, monospace">{i + 1}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Narrow (portrait) stages fit the tall exploded stack better with a closer camera. */
function useNarrow() {
  const q = "(max-width: 1023px)";
  const [m, setM] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return;
    const f = () => setM(mq.matches);
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  return m;
}

export default function ExplodeOnScroll() {
  const narrow = useNarrow();
  const z0 = narrow ? 1.3 : 1.05;
  const ref = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();
  const p = useScrollProgress(ref, !reduced);
  const a = reduced ? 0 : clamp((p - 0.08) / 0.78);
  const parts: ScenePart[] = useMemo(() => INST.map(i => ({
    id: i.id, url: `/landing/gearbox/${i.part}.glb`, at: i.at as [number, number, number], color: COLOR[i.part],
    explode: [0, 0, (EXPLODE_DZ[i.part] ?? 0) * (reduced ? 1 : lift(groupOf(i.part), a))] as [number, number, number],
    fitExplode: [0, 0, EXPLODE_DZ[i.part] ?? 0] as [number, number, number],
  })), [a, reduced]);
  const seated = (row: (typeof BOM)[number]) => !reduced && row.groups.every(g => lift(g, a) < 0.02);
  const done = BOM.filter(seated).length;
  const all = done === BOM.length;

  return (
    <section ref={ref} id="explode" aria-labelledby="explode-h" className={cx("relative border-y border-ink/80 bg-sheet2", !reduced && "h-[260vh]")}>
      <div className={cx("s-grid", !reduced && "sticky top-[68px] h-[calc(100svh-68px)] overflow-hidden")}>
        <div className="mx-auto grid h-full max-w-[1240px] grid-rows-[auto_minmax(0,1fr)] gap-5 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.2fr)] lg:grid-rows-1 lg:gap-12 lg:py-12">
          <div className="flex min-h-0 flex-col">
            <div className="flex items-center gap-3 text-bp"><span className="s-anno">03</span><span className="s-anno">Exploded view</span><span className="h-px flex-1 bg-rule2/70" aria-hidden="true" /></div>
            <h2 id="explode-h" className="s-h2 mt-4 text-[28px] sm:text-[40px]">29 parts. One axis. Zero interferences.</h2>
            <p className="mt-3 max-w-md text-[15.5px] leading-relaxed text-ink2 sm:text-[17px]">
              Scroll to seat the PG-5 gearbox the way Fitz assembles it: bottom up, every part placed from the frozen interface spec.
            </p>
            {/* parts list: a BOM table that ticks off as each group seats */}
            <ol className="mt-6 hidden min-h-0 border-t border-ink/70 lg:block" aria-label="Parts list">
              {BOM.map((row, i) => {
                const on = seated(row);
                return (
                  <li key={row.item} className={cx("flex items-center gap-3 border-b border-rule py-2 transition-colors duration-300", on ? "text-ink" : "text-ink2")}>
                    <span className={cx("s-balloon h-7 w-7 transition-colors duration-300", on ? "border-bp bg-bp text-sheet" : "border-ink2/60")}>{i + 1}</span>
                    <span className="min-w-0 flex-1 text-[14px] leading-snug">{row.item}</span>
                    <span className="s-anno shrink-0 tabular-nums text-ink2">{row.qty}</span>
                  </li>
                );
              })}
            </ol>
            <div className="mt-auto hidden pt-5 lg:block">
              <div className="flex items-center gap-3">
                <div className="relative h-1.5 flex-1 overflow-hidden bg-rule" aria-hidden="true"><div className="absolute inset-y-0 left-0 w-full origin-left bg-bp" style={{ transform: `scaleX(${reduced ? 1 : a})` }} /></div>
                <span className="s-anno tabular-nums text-ink">{reduced ? "8 groups" : `${done} / ${BOM.length} seated`}</span>
              </div>
            </div>
          </div>

          <Card3D className="min-h-0 flex-1" inner="relative h-full min-h-[360px] overflow-hidden">
            <div className="viewport-bg absolute inset-0" />
            <div className="absolute inset-0">
              <LazyScene parts={parts} explode={1} still={reduced} turn={reduced ? undefined : -18 + a * 70} view={[1, -1.15, 0.42]} zoom={reduced ? z0 : z0 + 0.4 * ease(clamp((a - 0.7) / 0.3))}
                poster={<div className="h-full w-full p-6"><Poster /></div>}
                label="The PG-5 planetary gearbox assembling along its axis as you scroll: motor flange, bearings, shafts, carrier, planets, sun, ring, covers and screws." />
            </div>
            <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap gap-2">
              <Badge3D tone={all ? "live" : undefined}>{all ? "Assembled · 0 interferences" : reduced ? "Exploded view" : `Seating ${Math.min(done + 1, BOM.length)} of ${BOM.length}`}</Badge3D>
            </div>
            <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex items-end justify-between gap-3 lg:hidden">
              <span className="bg-sheet/90 px-2 py-1 text-[13px] leading-snug text-ink ring-1 ring-rule">{BOM[Math.min(done, BOM.length - 1)]!.item}</span>
            </div>
            <span className="s-anno pointer-events-none absolute bottom-3 right-3 hidden bg-slab/85 px-1.5 py-0.5 text-ink2 lg:block">Real Formwright geometry · drag to orbit</span>
          </Card3D>
        </div>
      </div>
    </section>
  );
}
