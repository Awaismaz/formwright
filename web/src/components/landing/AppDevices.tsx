import { useRef, type ReactNode } from "react";
import { ArrowUp, Bell, Check, CheckCircle2, Download, FileBox, MonitorSmartphone, WifiOff, Zap } from "lucide-react";
import { LogoMark } from "@/components/ui";
import { cx } from "@/lib/format";
import { MeshingGears } from "@/pages/app/studio/ShopStatus";
import { AgentAvatar } from "@/pages/app/office/Avatars";
import LazyScene from "./LazyScene";
import { Reveal, useInView, useLoopClock, useReducedMotion } from "./motion";
import { SectionHead } from "./site";

/**
 * "Formwright in your pocket": the installable app (PWA) on a generic phone and a generic landscape tablet. Both
 * frames are drawn here (no device-maker artwork). Each screen runs its own short scripted loop; reduced motion shows
 * one settled frame per device.
 */

const PHONE_LOOP = 16;
const TABLET_LOOP = 18;
const BRIEF = "Flange Ø150 × 16, Ø60 bore, 6 × Ø14 on PCD 120";
const step = (t: number, a: number, b: number) => t >= a && t < b;
const fadeIn = (on: boolean) => cx("transition-all duration-500 ease-out", on ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0");

/* ---------------- frames ---------------- */

function Phone({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("relative aspect-[9/19] w-[230px] rounded-[42px] bg-gradient-to-b from-[#2a2f37] to-[#15181d] p-[9px] shadow-[0_40px_80px_-30px_rgb(16_24_40/.65),inset_0_0_0_1.5px_rgb(255_255_255/.08)]", className)}>
      <span className="absolute -left-[3px] top-24 h-10 w-[3px] rounded-l bg-[#2a2f37]" /><span className="absolute -left-[3px] top-36 h-14 w-[3px] rounded-l bg-[#2a2f37]" />
      <span className="absolute -right-[3px] top-32 h-16 w-[3px] rounded-r bg-[#2a2f37]" />
      <div className="relative h-full w-full overflow-hidden rounded-[34px] bg-panel">
        {children}
        <span className="absolute left-1/2 top-2 z-30 h-[22px] w-[74px] -translate-x-1/2 rounded-full bg-black" />
        <span className="absolute bottom-1.5 left-1/2 z-30 h-1 w-24 -translate-x-1/2 rounded-full bg-text/40" />
      </div>
    </div>
  );
}

function Tablet({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("relative aspect-[4/3] w-full max-w-[620px] rounded-[30px] bg-gradient-to-b from-[#2a2f37] to-[#15181d] p-[13px] shadow-[0_50px_100px_-40px_rgb(16_24_40/.7),inset_0_0_0_1.5px_rgb(255_255_255/.08)]", className)}>
      <span className="absolute left-1/2 top-[5px] h-[5px] w-[5px] -translate-x-1/2 rounded-full bg-[#3a404a] ring-1 ring-black/40" />
      <div className="relative h-full w-full overflow-hidden rounded-[18px] bg-panel">{children}</div>
    </div>
  );
}

function StatusBar({ dark }: { dark?: boolean }) {
  return (
    <div className={cx("relative z-20 flex h-8 items-end justify-between px-6 pb-1 text-[10px] font-semibold", dark ? "text-white" : "text-text")}>
      <span>9:41</span>
      <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-[2px] border border-current opacity-80" /></span>
    </div>
  );
}

/* ---------------- phone loop: home → splash → chat → part → board → toast ---------------- */

const APPS = ["#e8590c", "#2b8a3e", "#1971c2", "#ae3ec9", "#f59f00", "#0b7285", "#c92a2a", "#5c940d", "#364fc7", "#495057", "#d6336c"];

function PhoneScreen({ t, still }: { t: number; still: boolean }) {
  const home = t < 2.1, splash = step(t, 2.1, 3.2), chat = step(t, 3.2, 7.6), part = step(t, 7.6, 11), board = t >= 11;
  const typed = BRIEF.slice(0, Math.max(0, Math.min(BRIEF.length, Math.floor((t - 3.5) * 18))));
  const sent = t >= 6.0;
  const toast = t >= 13.6;
  return (
    <div className="absolute inset-0">
      {/* home screen */}
      <div className={cx("absolute inset-0 bg-[linear-gradient(160deg,#c9d9f2,#7f9cc9_55%,#3d5a8a)] transition-opacity duration-500", home ? "opacity-100" : "opacity-0")}>
        <StatusBar dark />
        <div className="grid grid-cols-4 gap-x-3 gap-y-4 px-5 pt-6">
          {APPS.map((c, i) => <span key={i} className="aspect-square rounded-[12px] shadow-sm" style={{ background: `linear-gradient(150deg, ${c}, ${c}bb)` }} />)}
          <span className="relative flex aspect-square items-center justify-center rounded-[12px] bg-white shadow-md">
            <LogoMark size={26} />
            <span className={cx("absolute inset-0 rounded-[12px] bg-black/25 transition-opacity", step(t, 1.4, 2.1) ? "opacity-100" : "opacity-0")} />
            <span className={cx("absolute -inset-2 rounded-[16px] ring-2 ring-white/80", step(t, 1.4, 2.1) ? "animate-ping" : "hidden")} />
          </span>
        </div>
        <div className="mt-1.5 grid grid-cols-4 px-5"><span className="col-start-4 text-center text-[8.5px] font-medium text-white">Formwright</span></div>
      </div>
      {/* splash */}
      <div className={cx("absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-[#1F5FBF] to-[#143E80] transition-all duration-500", splash ? "scale-100 opacity-100" : home ? "scale-50 opacity-0" : "opacity-0")}>
        <span className="rounded-2xl bg-white p-3 shadow-xl"><LogoMark size={44} /></span>
        <span className="mt-3 text-[13px] font-semibold text-white">Formwright</span>
      </div>
      {/* app */}
      <div className={cx("absolute inset-0 flex flex-col bg-panel transition-opacity duration-500", chat || part || board ? "opacity-100" : "opacity-0")}>
        <StatusBar />
        <div className="flex items-center gap-1.5 border-b border-border px-3 pb-2 pt-1">
          <LogoMark size={16} /><span className="truncate text-[11px] font-semibold">{board ? "Design Office · PG-5" : "Flange rev 1"}</span>
        </div>
        {(chat || part) && (
          <div className="flex min-h-0 flex-1 flex-col gap-1.5 p-2.5 text-[10.5px]">
            <div className="relative h-[190px] shrink-0 overflow-hidden rounded-lg border border-border viewport-bg">
              <div className={cx("pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-[10px] text-muted transition-opacity duration-500", part ? "opacity-0" : "opacity-100")}>
                <span className="rounded-full border border-border bg-panel/85 px-2 py-0.5">{sent ? "Building the part…" : "Waiting for a brief"}</span>
              </div>
              <div className={cx("absolute inset-0 transition-opacity duration-700", part ? "opacity-100" : "opacity-0")}>
              <LazyScene parts={[{ id: "f", url: "/landing/flange.glb", color: "#c4ccd6" }]} spin={40} zoom={1.15} still={still} label="Flange built in the Formwright app on a phone" />
              </div>
            </div>
            {sent && <div className="ml-auto max-w-[88%] animate-fade-in rounded-lg bg-primary px-2 py-1.5 text-white">{BRIEF}</div>}
            {sent && !part && (
              <div className="flex animate-fade-in items-center gap-1.5 rounded-lg border border-primary/20 bg-primary-soft/50 px-2 py-1.5">
                <MeshingGears size={18} speed={1.4} /><span className="font-medium text-primary">{t < 6.9 ? "Squaring the stock…" : "Drilling 6 × Ø14…"}</span>
              </div>
            )}
            {part && <div className="animate-fade-in rounded-lg border border-border bg-panel2 px-2 py-1.5"><span className="inline-flex items-center gap-1 font-semibold text-success"><CheckCircle2 className="h-3 w-3" />All gating checks pass</span></div>}
            <div className="mt-auto flex items-center gap-1 rounded-full border border-border bg-panel2 px-2.5 py-1.5">
              <span className={cx("min-w-0 flex-1 truncate", sent || !typed ? "text-muted" : "text-text")}>{sent || !typed ? "Describe a part…" : typed}</span>
              <span className={cx("flex h-4 w-4 items-center justify-center rounded-full", typed && !sent ? "bg-primary text-white" : "bg-border text-muted")}><ArrowUp className="h-2.5 w-2.5" /></span>
            </div>
          </div>
        )}
        {board && <MiniBoard t={t - 11} cols={2} />}
      </div>
      {/* push toast */}
      <div className={cx("absolute inset-x-2 top-9 z-20 flex items-center gap-2 rounded-2xl bg-panel/95 p-2 shadow-lg ring-1 ring-border backdrop-blur transition-all duration-500",
        toast ? "translate-y-0 opacity-100" : "-translate-y-6 opacity-0")}>
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white ring-1 ring-border"><LogoMark size={18} /></span>
        <div className="min-w-0 text-[10px] leading-tight"><div className="font-semibold">Formwright</div><div className="truncate text-muted">Gearbox approved ✓ · STEP and BOM ready</div></div>
      </div>
    </div>
  );
}

/* ---------------- shared mini board ---------------- */

const MINI = [
  { key: "PG-1", title: "Sun 18T", agent: "axel", at: 0.4 },
  { key: "PG-4", title: "Input shaft", agent: "chuck", at: 0.9 },
  { key: "PG-7", title: "Carrier plates", agent: "mill", at: 1.4 },
  { key: "PG-10", title: "Bearings 6204", agent: "hex", at: 0.1 },
  { key: "PG-3", title: "Ring 72T", agent: "axel", at: 2.2 },
];

function MiniBoard({ t, cols }: { t: number; cols: 2 | 3 }) {
  const names = cols === 3 ? ["In design", "Review · Gage", "Done"] : ["In design", "Done"];
  const colOf = (at: number) => {
    const s = t - at;
    if (cols === 2) return s < 1.6 ? 0 : 1;
    return s < 1.4 ? 0 : s < 2.3 ? 1 : 2;
  };
  return (
    <div className={cx("grid min-h-0 flex-1 gap-1.5 p-2", cols === 3 ? "grid-cols-3" : "grid-cols-2")}>
      {names.map((n, ci) => (
        <div key={n} className="min-w-0 rounded-md bg-panel2 p-1.5 ring-1 ring-border">
          <div className="mb-1 truncate text-[8.5px] font-bold uppercase tracking-wider text-muted">{n}</div>
          <div className="space-y-1">
            {MINI.filter(c => colOf(c.at) === ci).map(c => {
              const p = Math.min(1, Math.max(0, (t - c.at) / 1.4));
              const done = ci === names.length - 1;
              return (
                <div key={c.key} className={cx("animate-fade-in rounded border bg-panel p-1 text-[9px]", done ? "border-success/40" : "border-border")}>
                  <div className="flex items-center gap-1">
                    <span className="min-w-0 flex-1 truncate font-medium">{c.title}</span>
                    <AgentAvatar code={ci === 1 && cols === 3 ? "gage" : c.agent} state={done ? "done" : ci === 1 && cols === 3 ? "review" : "working"} size={14} />
                  </div>
                  {!done && ci === 0 && <div className="mt-0.5 h-0.5 rounded bg-border"><div className="h-full rounded bg-primary" style={{ width: `${p * 100}%` }} /></div>}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- tablet loop: Design Studio, then the Design Office board ---------------- */

const TREE = ["Gear blank Ø57", "Involute teeth · z24", "Bore Ø10", "Chamfers 0.5"];
const CHECKS = ["Valid solid", "Bounding box", "Volume Δ 0.000%", "STEP round-trip", "Deterministic"];

function TabletScreen({ t, still }: { t: number; still: boolean }) {
  const studio = t < 10.5;
  const feats = Math.min(TREE.length, Math.max(0, Math.floor((t - 1.2) / 1.1)));
  const checks = Math.min(CHECKS.length, Math.max(0, Math.floor((t - 6) / 0.5)));
  return (
    <div className="absolute inset-0 flex flex-col text-[10px]">
      <div className="flex h-7 shrink-0 items-center gap-2 bg-chrome px-3 text-chrome-fg">
        <LogoMark size={14} /><span className="truncate text-[10px]">{studio ? "Design Studio · Spur gear m2 z24" : "Design Office · PG-5 Planetary gearbox"}</span>
        <span className="ml-auto flex gap-0.5">{["archie", "axel", "chuck", "mill", "gage"].map(c => <AgentAvatar key={c} code={c} size={14} still />)}</span>
      </div>
      {studio ? (
        <div className="grid min-h-0 flex-1 grid-cols-[1fr_2.1fr_1.15fr]">
          <div className="space-y-1 border-r border-border bg-panel p-2">
            <div className="text-[8.5px] font-bold uppercase tracking-wider text-muted">Feature tree</div>
            <div className="flex items-center gap-1 font-medium"><FileBox className="h-3 w-3 text-primary" />Spur gear</div>
            {TREE.map((f, i) => <div key={f} className={cx("pl-3", fadeIn(i < feats))}>▪ {f}</div>)}
            <div className="pt-1.5 text-[8.5px] font-bold uppercase tracking-wider text-muted">Checks</div>
            {CHECKS.map((c, i) => (
              <div key={c} className="flex items-center gap-1">
                <span className={cx("w-7 rounded text-center text-[7.5px] font-bold transition-colors", i < checks ? "bg-success/15 text-success" : "bg-border/60 text-muted")}>{i < checks ? "PASS" : "…"}</span>
                <span className="truncate">{c}</span>
              </div>
            ))}
          </div>
          <div className="viewport-bg relative">
            <LazyScene parts={[{ id: "g", url: "/landing/gear.glb", color: "#b9c0c9" }]} spin={22} zoom={1.1} still={still} label="Spur gear in the Design Studio on a tablet" />
          </div>
          <div className="flex flex-col gap-1.5 border-l border-border bg-panel p-2">
            <div className="ml-auto max-w-[95%] rounded-md bg-primary px-1.5 py-1 text-white">Spur gear m2, 24 teeth, 12 wide, Ø10 bore</div>
            <div className={cx("rounded-md border border-border bg-panel2 px-1.5 py-1", fadeIn(t > 1))}><b>Interpreted:</b> m2 · z24 · α 20° · b 12 · Ø10</div>
            <div className={cx("flex items-center gap-1 rounded-md border border-primary/20 bg-primary-soft/50 px-1.5 py-1", fadeIn(t > 1.8 && t < 8.6))}>
              <MeshingGears size={16} speed={1.4} /><span className="font-medium text-primary">Hobbing 24 teeth…</span>
            </div>
            <div className={cx("rounded-md border border-border bg-panel2 px-1.5 py-1", fadeIn(t >= 8.6))}>
              <span className="inline-flex items-center gap-1 font-semibold text-success"><Check className="h-3 w-3" />All gating checks pass</span>
              <span className="mt-1 flex w-fit items-center gap-1 rounded-full border border-primary/30 bg-primary-soft px-1.5 py-0.5 text-[9px] font-semibold text-primary"><Download className="h-2.5 w-2.5" />Gear.step</span>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col bg-panel">
          <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
            <AgentAvatar code="archie" state="working" size={20} />
            <span className="truncate font-medium">Archie assigned 11 tickets to 5 specialists</span>
            <span className="ml-auto flex gap-0.5">{["axel", "chuck", "mill", "hex"].map(c => <AgentAvatar key={c} code={c} state="working" size={18} />)}</span>
          </div>
          <MiniBoard t={t - 10.5} cols={3} />
        </div>
      )}
    </div>
  );
}

/* ---------------- section ---------------- */

const POINTS: [typeof Zap, string, string][] = [
  [MonitorSmartphone, "Any phone, any tablet", "iPhone, iPad and Android, in portrait or landscape."],
  [Download, "Install from the browser", "Add it to your home screen in two taps. No app store needed."],
  [WifiOff, "Offline-ready shell", "Opens instantly and keeps your projects close, even on a patchy shop-floor signal."],
  [Bell, "Everything but the desktop bridges", "Brief, review, approve and export on the move. Desktop CAD stays on your workstation."],
];

export default function AppDevices() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const on = useInView(ref, { threshold: 0.15 });
  const phoneT = useLoopClock(on && !reduced, PHONE_LOOP, 100);
  const tabT = useLoopClock(on && !reduced, TABLET_LOOP, 100);
  return (
    <section id="mobile" className="s-grid relative scroll-mt-20 overflow-hidden border-b border-ink/80 bg-sheet2">
      <div ref={ref} className="relative mx-auto grid max-w-[1240px] items-center gap-12 px-4 py-20 sm:px-6 sm:py-24 lg:grid-cols-[.85fr_1.4fr]">
        <Reveal>
          <SectionHead n="06" kicker="Mobile and tablet" title="Formwright in your pocket."
            body="Install the app on iPhone and Android, no app store needed. Brief a part from the shop floor, watch the Design Office work, and approve the result before you are back at your desk." />
          <ul className="mt-6 space-y-3.5">
            {POINTS.map(([I, h, b]) => (
              <li key={h} className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center border border-ink/70 bg-slab text-bp"><I className="h-[18px] w-[18px]" strokeWidth={1.6} aria-hidden="true" /></span>
                <div><div className="text-[15px] font-semibold text-ink">{h}</div><div className="text-[14px] text-ink2">{b}</div></div>
              </li>
            ))}
          </ul>
        </Reveal>
        <Reveal delay={0.1} className="relative flex flex-col items-center gap-8 lg:block lg:min-h-[520px] lg:[perspective:1600px]">
          <Tablet className="lg:absolute lg:left-0 lg:top-4 lg:w-[560px] lg:[transform:rotateY(10deg)_rotateX(4deg)]">
            <TabletScreen t={reduced ? 9.2 : tabT} still={reduced} />
          </Tablet>
          <Phone className="lg:absolute lg:bottom-0 lg:right-0 lg:z-10 lg:[transform:rotateY(-8deg)_rotateZ(2deg)]">
            <PhoneScreen t={reduced ? 9 : phoneT} still={reduced} />
          </Phone>
        </Reveal>
      </div>
    </section>
  );
}
