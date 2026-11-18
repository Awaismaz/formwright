import { useRef } from "react";
import { ArrowUp, Check, CheckCircle2, Download, FileBox, Move3d, Play } from "lucide-react";
import { LogoMark } from "./ui";
import { cx } from "@/lib/format";
import { MeshingGears, WORDS } from "@/pages/app/studio/ShopStatus";
import LazyScene from "./landing/LazyScene";
import { useInView, useLoopClock, useReducedMotion } from "./landing/motion";
import { CHECKS, FEATURES, FINAL, LOOP, heroFrame, type HeroPhase } from "./landing/heroTimeline";
import type { ScenePart } from "./landing/PartScene";

const STEP_LINE: Partial<Record<HeroPhase, string>> = {
  plan: "Reading the brief and planning features",
  build: "Building the part",
  inspect: "Running the gating checks",
};

const ALU = "#c4ccd6";
const STAGES: ScenePart[][] = [0, 1, 2, 3].map(n => [
  { id: "blank", url: "/landing/flange-blank.glb", color: ALU, show: n === 1 },
  { id: "bore", url: "/landing/flange-bore.glb", color: ALU, show: n === 2 },
  { id: "final", url: "/landing/flange.glb", color: ALU, show: n >= 3 },
]);

/**
 * The landing hero: a scripted replay of a Design Studio session around a LIVE, orbitable part. The part files are
 * real Formwright Toolbox geometry (flange Ø150 × 16, 6 × Ø14 on PCD 120); the chat is a replay, labelled as such.
 */
export default function HeroVisual() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const onScreen = useInView(ref, { threshold: 0.1 });
  const t = useLoopClock(onScreen && !reduced, LOOP);
  const f = reduced ? FINAL : heroFrame(t);
  const words = f.phase === "plan" || f.phase === "build" || f.phase === "inspect" ? WORDS[f.phase] : null;
  const word = words ? words[Math.floor(t / 1.1) % words.length] : "";

  return (
    <div ref={ref} className="relative">
      <div className="pointer-events-none absolute -inset-x-10 -bottom-10 top-10 -z-10 rounded-[40px] bg-[radial-gradient(closest-side,rgb(var(--primary)/.18),transparent)] blur-2xl" />
      <div className="relative overflow-hidden rounded-xl border border-border bg-panel text-left shadow-[0_30px_80px_-20px_rgb(16_24_40/.35)]">
        {/* title bar */}
        <div className="flex h-9 items-center gap-2 border-b border-white/5 bg-chrome px-3">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" /><span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" /><span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
          <LogoMark size={16} className="ml-3" /><span className="truncate text-[11px] text-chrome-muted">Formwright · Design Studio · Flange rev 1</span>
          <span className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-chrome-fg"><Play className="h-2.5 w-2.5" />Replay</span>
        </div>

        <div className="grid text-[11.5px] md:grid-cols-[1fr_1.45fr_.9fr]">
          {/* chat */}
          <div className="order-2 flex min-h-[250px] flex-col gap-2 border-t border-border bg-panel p-3 md:order-1 md:min-h-[340px] md:border-r md:border-t-0">
            {f.sent && <div className="ml-auto max-w-[92%] animate-fade-in rounded-lg bg-primary px-2.5 py-1.5 text-white">{f.typed}</div>}
            {f.interpreted && (
              <div className="animate-fade-in rounded-lg border border-border bg-panel2 px-2.5 py-1.5 text-text">
                <b>Interpreted:</b> 6061-T6 · Ø150 × 16 disc · Ø60 bore · 6 × Ø14 through, equally spaced on PCD 120.
              </div>
            )}
            {words && (
              <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary-soft/40 px-2 py-1.5" role="status">
                <MeshingGears size={22} speed={f.phase === "build" ? 1.6 : 1} />
                <div className="min-w-0">
                  <div key={word} className="animate-fade-in truncate font-medium text-primary">{word}…</div>
                  <div className="truncate text-[10.5px] text-muted">{STEP_LINE[f.phase]}</div>
                </div>
              </div>
            )}
            {f.done && (
              <div className="animate-fade-in space-y-1.5 rounded-lg border border-border bg-panel2 px-2.5 py-2 text-text">
                <div>Built and verified. Volume 222,726 mm³ matches the hand calculation; mass ≈ 601 g in 6061-T6.</div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded-full bg-success/12 px-2 py-0.5 text-[10.5px] font-semibold text-success"><CheckCircle2 className="h-3 w-3" />All gating checks pass</span>
                  {f.step && <span className="inline-flex animate-fade-in items-center gap-1 rounded-full border border-primary/30 bg-primary-soft px-2 py-0.5 text-[10.5px] font-semibold text-primary"><Download className="h-3 w-3" />Flange.step</span>}
                </div>
              </div>
            )}
            <div className="mt-auto flex min-h-[30px] items-center gap-1.5 rounded border border-border bg-panel2 px-2 py-1.5">
              <span className={cx("min-w-0 flex-1 truncate", f.sent || !f.typed ? "text-muted" : "text-text")}>
                {f.sent || !f.typed ? "Describe a part or ask for a change…" : f.typed}
                {!f.sent && !reduced && <span className="fw-caret text-primary" />}
              </span>
              <span className={cx("flex h-5 w-5 shrink-0 items-center justify-center rounded-full", f.typed && !f.sent ? "bg-primary text-white" : "bg-border text-muted")}><ArrowUp className="h-3 w-3" /></span>
            </div>
          </div>

          {/* viewport */}
          <div className="viewport-bg relative order-1 h-[250px] md:order-2 md:h-auto">
            <LazyScene eager parts={STAGES[f.features]!} spin={14} still={reduced} zoom={1.12} label="Flange Ø150 with six bolt holes, built by Formwright. Drag to orbit." />
            {f.features === 0 && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[11px] text-muted">
                <span className="rounded-full border border-border bg-panel/80 px-2.5 py-1">{f.sent ? "Planning features…" : "Waiting for a brief"}</span>
              </div>
            )}
            <div className="pointer-events-none absolute left-2 top-2 flex gap-1">{["Iso", "Front", "Top", "Right"].map((v, i) => <span key={v} className={cx("rounded border px-1.5 py-0.5 text-[9.5px]", i === 0 ? "border-primary/40 bg-primary-soft text-primary" : "border-border bg-panel/90 text-muted")}>{v}</span>)}</div>
            <div className="pointer-events-none absolute bottom-2 left-2 hidden items-center gap-1 rounded bg-panel/85 px-1.5 py-0.5 text-[9.5px] text-muted sm:inline-flex"><Move3d className="h-3 w-3" />Drag to orbit · real Formwright geometry</div>
          </div>

          {/* feature tree + checks */}
          <div className="order-3 hidden space-y-1.5 border-l border-border bg-panel p-3 md:block">
            <div className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Feature tree</div>
            <div className="flex items-center gap-1.5 font-medium"><FileBox className="h-3.5 w-3.5 text-primary" />Flange · 6061-T6</div>
            {FEATURES.map((ft, i) => (
              <div key={ft.name} className={cx("flex items-center gap-1.5 pl-4 transition-all duration-500", i < f.features ? "translate-x-0 opacity-100" : "-translate-x-1 opacity-0")}>
                <span className="h-1.5 w-1.5 rounded-sm bg-primary/70" />{ft.name}
              </div>
            ))}
            <div className="pt-2 text-[9.5px] font-bold uppercase tracking-wider text-muted">Checks</div>
            {CHECKS.map(([a, b], i) => {
              const ok = i < f.checks;
              return (
                <div key={a} className="flex items-center gap-1.5">
                  <span className={cx("w-9 rounded px-1 text-center text-[9px] font-bold transition-colors", ok ? "bg-success/12 text-success" : "bg-border/60 text-muted")}>{ok ? "PASS" : "…"}</span>
                  <span className="flex-1 truncate">{a}</span><span className={cx("text-muted transition-opacity", ok ? "opacity-100" : "opacity-0")}>{b}</span>
                </div>
              );
            })}
            <div className={cx("mt-2 flex items-center gap-1 rounded-md px-2 py-1 text-[10.5px] font-semibold transition-all duration-500", f.done ? "bg-success/12 text-success opacity-100" : "opacity-0")}>
              <Check className="h-3 w-3" />All gating checks pass
            </div>
          </div>
        </div>
        {/* replay progress */}
        <div className="h-0.5 bg-border/60"><div className="h-full bg-primary/70" style={{ width: `${(reduced ? 1 : f.progress) * 100}%` }} /></div>
      </div>
      <p className="mt-3 text-center text-[11.5px] text-muted">A scripted replay of a Design Studio session. The 3D part is real Formwright output: built by the Toolbox flange generator and exported from the exact model.</p>
    </div>
  );
}
