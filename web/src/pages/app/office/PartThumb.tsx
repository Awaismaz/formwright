import { useEffect, useMemo, useRef, useState } from "react";
import { Box } from "lucide-react";
import { cx } from "@/lib/format";
import { icdRows, reviewMarks, stageView, workStage, type FeatureKind, type WorkStage } from "./model";
import { fadeOnce, reducedMotion, thumbUrl, useSeen, useThumb, type Thumb } from "./thumbs";
import type { Program, Ticket } from "./types";
import "./thumbs.css";

/** The snapshot keys a part ticket can show: its placeholder (ghost) and its approved part (real). */
export function thumbKeys(program: Program, t: Ticket): { ghost: string | null; real: string | null } | null {
  if (t.kind !== "part" && t.kind !== "standard") return null;
  const p = program.assembly?.parts?.[t.item_id];
  if (!p) return null;
  return { ghost: p.kind === "placeholder" ? p.key : p.ghost ?? null, real: p.kind === "real" ? p.key : null };
}

/** One line drawing: each feature group lit, faint, or ticked green / red from Gage's rows. */
function Lines({ thumb, lit, marks, tone }: { thumb: Thumb; lit: Set<FeatureKind> | null; marks: Map<number, "ok" | "fail">; tone: "work" | "done" }) {
  return (
    <svg viewBox={thumb.viewBox} className="h-full w-full" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {thumb.groups.map(g => {
        const m = marks.get(g.g);
        const on = !lit || lit.has(g.feature);
        return (
          <g key={g.g} data-feature={g.feature} data-mark={m}
            className={cx("fw-th-g", m === "fail" ? "text-danger" : m === "ok" ? "text-success" : on ? (tone === "work" ? "text-primary" : "text-text") : "text-text")}
            style={{ opacity: m ? 1 : on ? 0.95 : 0.22 }}>
            {g.hid && <path d={g.hid} strokeWidth={0.7} strokeOpacity={0.5} strokeDasharray="2 1.6" vectorEffect="non-scaling-stroke" />}
            {g.vis && <path d={g.vis} strokeWidth={m === "fail" ? 1.8 : 1.15} vectorEffect="non-scaling-stroke" />}
          </g>);
      })}
    </svg>
  );
}

/** The thumbnail of a part ticket on its card: the placeholder while it waits (faint), the stage reveal while the
 * agent works, Gage's scan while he inspects, the real part once approved (a short cross-fade, once per session),
 * and Gage's rows ticked onto the features. Real geometry only: nothing is drawn until the server's drawing is in. */
export default function PartThumb({ program, t, size = 52, stage: forced, show: forcedShow, className, label }: {
  program: Program; t: Ticket; size?: number; stage?: WorkStage; show?: "ghost" | "real"; className?: string; label?: string;
}) {
  const keys = thumbKeys(program, t);
  const stage = forced ?? workStage(t);
  const sv = stageView(stage);
  const show: "ghost" | "real" = forcedShow ?? (sv.show === "real" && keys?.real ? "real" : "ghost");
  const [ref, seen] = useSeen<HTMLDivElement>();
  const ghostUrl = keys?.ghost ? thumbUrl(program.id, t.item_id, "ghost", keys.ghost) : null;
  const realUrl = keys?.real ? thumbUrl(program.id, t.item_id, "real", keys.real) : null;
  const real = useThumb(realUrl, seen && show === "real");
  // until the approved part's drawing is in, the card keeps the placeholder (never an empty box mid-swap)
  const ghost = useThumb(ghostUrl, seen && (show === "ghost" || !real));
  // the cross-fade: only when this card saw the real part arrive (not on a page that opens on a finished program),
  // once its drawing is in, once per part per session
  const firstReal = useRef(keys?.real ?? null);
  const [arrived, setArrived] = useState<string | null>(null);
  const [fading, setFading] = useState(false);
  useEffect(() => {
    if (forcedShow || !keys?.real || firstReal.current === keys.real) return;
    firstReal.current = keys.real;
    if (keys.ghost && !reducedMotion()) setArrived(keys.real);
  }, [keys?.real, keys?.ghost, forcedShow]);
  useEffect(() => {
    if (!arrived || !real || !ghost || arrived !== keys?.real) return;
    setArrived(null);
    if (fadeOnce(arrived)) setFading(true);
  }, [arrived, real, ghost, keys?.real]);
  useEffect(() => {
    if (!fading) return;
    const id = setTimeout(() => setFading(false), 700);
    return () => clearTimeout(id);
  }, [fading]);
  // what is on screen: the approved part once its drawing is in; while it loads, the placeholder
  const shown: "ghost" | "real" = show === "real" && real !== undefined ? "real" : "ghost";
  const main = shown === "real" ? real : ghost;
  const rows = useMemo(() => icdRows(t), [t]);
  const marks = useMemo(() => (main && rows.length ? reviewMarks(rows, main.groups) : new Map<number, "ok" | "fail">()),
    [main, rows]);
  if (!keys || (!keys.ghost && !keys.real)) return null;
  const lit = shown === "ghost" ? new Set(sv.lit) : null;
  const fails = [...marks.values()].filter(m => m === "fail").length;
  const oks = [...marks.values()].filter(m => m === "ok").length;
  const words = shown === "real" ? "Line drawing of the approved part" : "Line drawing of the placeholder from the interfaces";
  return (
    <div ref={ref} role="img" aria-label={label ?? `${words}${marks.size ? `: ${oks} interface feature${oks === 1 ? "" : "s"} conform${fails ? `, ${fails} off` : ""}` : ""}`}
      data-thumb={shown} data-stage={stage}
      className={cx("fw-th relative shrink-0 overflow-hidden rounded border border-border bg-panel2/60", sv.faint && shown === "ghost" && "fw-th--faint", className)}
      style={{ width: size, height: size, ["--fw-th-h" as string]: `${size - 2}px` }}>
      {!main
        ? <span className="flex h-full w-full items-center justify-center text-text/20" data-thumb-wait><Box style={{ width: size * 0.45, height: size * 0.45 }} strokeWidth={1.25} /></span>
        : <>
          {fading && ghost && shown === "real" && <div className="fw-th-out absolute inset-0"><Lines thumb={ghost} lit={null} marks={new Map()} tone="work" /></div>}
          <div className={cx("absolute inset-0", fading && shown === "real" && "fw-th-in")}>
            <Lines thumb={main} lit={lit} marks={marks} tone={shown === "real" ? "done" : "work"} />
          </div>
        </>}
      {sv.scan && main && shown === "ghost" && <span className="fw-th-scan" aria-hidden />}
      {fails > 0 && <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-danger" aria-hidden />}
    </div>
  );
}

/** The drawer's larger view: the placeholder and the approved part side by side (when both exist). */
export function ThumbPair({ program, t }: { program: Program; t: Ticket }) {
  const keys = thumbKeys(program, t);
  if (!keys || (!keys.ghost && !keys.real)) return null;
  const stage = workStage(t);
  const rows = icdRows(t);
  return (
    <div className="rounded-lg border border-border p-3" data-thumb-pair>
      <div className="mb-2 text-[12px] font-medium">Line drawing{keys.ghost && keys.real ? "s" : ""}
        <span className="ml-1.5 font-normal text-muted">· the geometry as it is now{rows.length ? "; green and red are Gage's interface measurements" : ""}</span></div>
      <div className="flex flex-wrap gap-3">
        {keys.ghost && <figure className="m-0">
          <PartThumb program={program} t={t} size={150} show="ghost" stage={keys.real ? "done" : stage} />
          <figcaption className="mt-1 text-[11px] text-muted">Placeholder from the interfaces</figcaption></figure>}
        {keys.real && <figure className="m-0">
          <PartThumb program={program} t={t} size={150} show="real" stage="done" />
          <figcaption className="mt-1 text-[11px] text-muted">Approved part</figcaption></figure>}
      </div>
    </div>
  );
}
