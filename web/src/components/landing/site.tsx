import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Moon, Sun } from "lucide-react";
import { LogoMark } from "@/components/ui";
import { cx } from "@/lib/format";
import "./site.css";

/**
 * The public website's "Sheet" design system (docs/design-system/MASTER.md): an engineering-drawing language.
 * Paper (light) and Blueprint (dark) themes live on `.fw-site`, separate from the app theme, so a visitor can pick one
 * without touching their workspace preference.
 */

type Theme = "light" | "dark";
type Pref = Theme | "system";
const KEY = "fw.site.theme";
const DARK_Q = "(prefers-color-scheme: dark)";

function readPref(): Pref {
  try { const v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : "system"; } catch { return "system"; }
}

const Ctx = createContext<{ theme: Theme; set: (t: Theme) => void }>({ theme: "light", set: () => {} });
export const useSiteTheme = () => useContext(Ctx);

/** Wraps a public page in the site tokens and theme. */
export function SiteScope({ children, className }: { children: ReactNode; className?: string }) {
  const [pref, setPref] = useState<Pref>(readPref);
  const [sysDark, setSysDark] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(DARK_Q).matches);
  useEffect(() => {
    const m = window.matchMedia?.(DARK_Q);
    if (!m) return;
    const f = () => setSysDark(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  const theme: Theme = pref === "system" ? (sysDark ? "dark" : "light") : pref;
  const set = (t: Theme) => { setPref(t); try { localStorage.setItem(KEY, t); } catch { /* private window */ } };
  return (
    <Ctx.Provider value={{ theme, set }}>
      <div className={cx("fw-site", className)} data-theme={theme}>{children}</div>
    </Ctx.Provider>
  );
}

/** Paper (day, light) / Blueprint (night, dark): a two-key rocker with sun and moon icons; the chosen key stays pressed. */
export function ThemeSwitch({ className }: { className?: string }) {
  const { theme, set } = useSiteTheme();
  return (
    <div role="group" aria-label="Page theme" className={cx("inline-flex gap-1", className)}>
      {([["light", "Paper", Sun], ["dark", "Blueprint", Moon]] as const).map(([t, l, Icon]) => (
        <Button3D key={t} size="xs" finish="steel" pressed={theme === t} onClick={() => set(t)}>
          <span className="inline-flex items-center gap-1.5"><Icon className="h-3.5 w-3.5" aria-hidden="true" />{l}</span>
        </Button3D>
      ))}
    </div>
  );
}

export function SiteLogo({ size = 26, onPrint }: { size?: number; onPrint?: boolean }) {
  return (
    <span className="inline-flex select-none items-center gap-2.5">
      <LogoMark size={size} />
      <span className={cx("font-display font-extrabold uppercase leading-none tracking-[.02em]", onPrint ? "text-white" : "text-ink")}
        style={{ fontSize: size * 0.62, fontStretch: "125%" }}>Formwright</span>
    </span>
  );
}

type KeyProps = {
  children: ReactNode; to?: string; href?: string; onClick?: () => void; type?: "button" | "submit";
  finish?: "hi" | "steel"; size?: "xs" | "sm" | "md" | "lg"; icon?: ReactNode; block?: boolean; loading?: boolean;
  disabled?: boolean; pressed?: boolean; className?: string; target?: string; "aria-label"?: string;
};

/**
 * Button3D: a solid-modelled key. A chamfered face over a visible side face; it lifts on hover and travels down on
 * press. Router link, anchor or button. `pressed` makes it a toggle (aria-pressed) that stays down.
 */
export function Button3D({ children, to, href, onClick, type = "button", finish = "hi", size = "md", icon, block, loading, disabled, pressed, className, target, ...rest }: KeyProps) {
  const cls = cx("s-key", `k-${finish}`, size !== "md" && `k-${size}`, block && "is-block", pressed && "is-down", className);
  const body = (
    <>
      <span className="k-side" aria-hidden="true" />
      <span className="k-face"><span className="k-top">
        {loading && <span className="h-4 w-4 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" aria-hidden="true" />}
        {children}{!loading && icon}
      </span></span>
    </>
  );
  if (to && !disabled) return <Link to={to} className={cls} target={target} aria-label={rest["aria-label"]}>{body}</Link>;
  if (href && !disabled) return <a href={href} className={cls} target={target} aria-label={rest["aria-label"]}>{body}</a>;
  return (
    <button type={type} onClick={onClick} disabled={disabled || loading} aria-busy={loading || undefined}
      aria-pressed={pressed === undefined ? undefined : pressed} aria-label={rest["aria-label"]} className={cls}>{body}</button>
  );
}

/** Card3D: a machined plate with two chamfered corners and a hatched cut face for its thickness. */
export function Card3D({ children, className, inner, to, href, lift, hi, flat, screws, as: Tag = "div" }: {
  children: ReactNode; className?: string; inner?: string; to?: string; href?: string; lift?: boolean; hi?: boolean; flat?: boolean;
  screws?: boolean; as?: "div" | "li" | "article";
}) {
  const cls = cx("s-plate", lift && "p-lift", hi && "p-hi", flat && "p-flat", className);
  const body = (
    <>
      <span className="p-side" aria-hidden="true" />
      <div className="p-face"><div className={cx("p-top", inner)}>
        {screws && <>
          <span className="s-screw right-2.5 top-2.5" style={{ ["--r" as string]: "20deg" }} aria-hidden="true" />
          <span className="s-screw bottom-2.5 left-2.5" style={{ ["--r" as string]: "-40deg" }} aria-hidden="true" />
        </>}
        {children}
      </div></div>
    </>
  );
  if (to) return <Link to={to} className={cls}>{body}</Link>;
  if (href) return <a href={href} className={cls}>{body}</a>;
  return <Tag className={cls}>{body}</Tag>;
}

/** Badge3D: a stamped metal tag with a punched hole. */
export function Badge3D({ children, tone, className }: { children: ReactNode; tone?: "live" | "hi"; className?: string }) {
  return <span className={cx("s-tag", tone && `t-${tone}`, className)}><span className="t-hole" aria-hidden="true" />{children}</span>;
}

/** Scroll progress of an element through the viewport: 0 when its top reaches the viewport top, 1 when its bottom does. */
export function useScrollProgress(ref: React.RefObject<HTMLElement | null>, enabled = true): number {
  const [p, setP] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    let raf = 0, on = false;
    const measure = () => {
      raf = 0;
      const r = el.getBoundingClientRect();
      const run = r.height - window.innerHeight;
      const v = run > 0 ? Math.min(1, Math.max(0, -r.top / run)) : (r.top < 0 ? 1 : 0);
      setP(prev => (Math.abs(prev - v) > 0.002 ? v : prev));
    };
    const tick = () => { if (on && !raf) raf = requestAnimationFrame(measure); };
    // measure on every visibility change too, so a jump past the section (or back above it) settles at 0 or 1
    const io = new IntersectionObserver(([e]) => { on = !!e?.isIntersecting; if (!raf) raf = requestAnimationFrame(measure); }, { rootMargin: "50px 0px" });
    io.observe(el);
    window.addEventListener("scroll", tick, { passive: true });
    window.addEventListener("resize", tick, { passive: true });
    return () => { io.disconnect(); window.removeEventListener("scroll", tick); window.removeEventListener("resize", tick); if (raf) cancelAnimationFrame(raf); };
  }, [ref, enabled]);
  return p;
}

const Arrow = ({ dir }: { dir: "l" | "r" }) => (
  <svg width="9" height="8" viewBox="0 0 9 8" aria-hidden="true">
    <path d={dir === "l" ? "M0 4 9 0.6 9 7.4Z" : "M9 4 0 0.6 0 7.4Z"} fill="currentColor" />
  </svg>
);

/** A dimension: extension lines, arrowheads and the value. Purely decorative unless `label` carries meaning. */
export function Dim({ label, className, load, delay }: { label: ReactNode; className?: string; load?: boolean; delay?: number }) {
  return (
    <div className={cx("s-dim", load && "s-load", className)} style={delay != null ? { ["--d" as string]: `${delay}s` } : undefined}>
      <span className="s-dim-ext" /><Arrow dir="l" /><span className="s-dim-line" style={{ ["--o" as string]: "right" }} />
      <span className="s-dim-label s-anno">{label}</span>
      <span className="s-dim-line" /><Arrow dir="r" /><span className="s-dim-ext" />
    </div>
  );
}

/** GD&T position symbol. */
export const PositionSymbol = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.3">
    <circle cx="7" cy="7" r="4.2" /><path d="M7 0.5v13M0.5 7h13" />
  </svg>
);

/** Third-angle projection symbol (ISO 128). */
export const ThirdAngle = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 46 20" className={className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.2">
    <path d="M2 6.5 16 3v14L2 13.5Z" /><path d="M1 10h17" strokeDasharray="3 1.5 0.6 1.5" strokeWidth=".7" />
    <circle cx="33" cy="10" r="7" /><circle cx="33" cy="10" r="3.2" /><path d="M24 10h18M33 1v18" strokeDasharray="3 1.5 0.6 1.5" strokeWidth=".7" />
  </svg>
);

/** A feature control frame used as an eyebrow: position, zero tolerance, to datum BRIEF. */
export function Fcf({ cells, className }: { cells: ReactNode[]; className?: string }) {
  return (
    <span className={cx("s-fcf s-anno text-ink", className)}>
      <span aria-hidden="true"><PositionSymbol /></span>
      {cells.map((c, i) => <span key={i}>{c}</span>)}
    </span>
  );
}

/** Section heading: zone number, a leader to the margin, then the title. */
export function SectionHead({ n, kicker, title, body, className, onPrint }: {
  n: string; kicker: string; title: ReactNode; body?: ReactNode; className?: string; onPrint?: boolean;
}) {
  return (
    <div className={className}>
      <div className={cx("flex items-center gap-3", onPrint ? "text-[#9cc3ff]" : "text-bp")}>
        <span className="s-anno tabular-nums">{n}</span>
        <span className="s-anno">{kicker}</span>
        <span className={cx("s-draw-x h-px flex-1 origin-left", onPrint ? "bg-white/25" : "bg-rule2/70")} aria-hidden="true" />
      </div>
      <h2 className={cx("s-h2 mt-4 max-w-3xl text-[32px] sm:text-[44px]", onPrint ? "text-white" : "text-ink")}>{title}</h2>
      {body && <p className={cx("mt-4 max-w-2xl text-[17px] leading-relaxed", onPrint ? "text-[#b8c8e0]" : "text-ink2")}>{body}</p>}
    </div>
  );
}

/** One title-block cell: a small caption over a value. */
export function TbCell({ k, children, className }: { k: string; children: ReactNode; className?: string }) {
  return <div className={className}><span className="s-tb-k">{k}</span><div className="mt-1 min-w-0">{children}</div></div>;
}

/** Zone numbers along the sheet border, as on a drawing frame. */
export function Zones({ n = 8, className }: { n?: number; className?: string }) {
  return (
    <div className={cx("pointer-events-none grid select-none text-ink2/70", className)} style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }} aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <span key={i} className="s-anno border-l border-rule2/60 py-1 text-center text-[9.5px] first:border-l-0">{n - i}</span>
      ))}
    </div>
  );
}

/**
 * Drop-in for the app's `Button` on public pages (auth, onboarding): same props, rendered as a Button3D.
 * primary/accent: safety yellow; secondary/ghost/chrome: steel. `w-full` in className makes it full width.
 */
export function KeyButton({ variant = "primary", size = "md", className, loading, disabled, onClick, type = "button", icon, children, to }: {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "accent" | "chrome"; size?: "sm" | "md" | "lg"; className?: string;
  loading?: boolean; disabled?: boolean; onClick?: () => void; type?: "button" | "submit"; icon?: ReactNode; children: ReactNode; to?: string;
}) {
  const full = !!className?.split(/\s+/).includes("w-full");
  const rest = className?.split(/\s+/).filter(c => c !== "w-full").join(" ");
  return (
    <Button3D to={to} type={type} onClick={onClick} loading={loading} disabled={disabled} icon={icon} block={full} className={rest}
      size={size === "lg" ? "lg" : size === "sm" ? "sm" : "md"} finish={variant === "primary" || variant === "accent" ? "hi" : "steel"}>{children}</Button3D>
  );
}
