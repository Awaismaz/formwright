import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { cx } from "@/lib/format";

const REDUCED = "(prefers-reduced-motion: reduce)";

export function useReduced(): boolean {
  const [r, setR] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(REDUCED).matches);
  useEffect(() => {
    const m = window.matchMedia?.(REDUCED);
    if (!m) return;
    const f = () => setR(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  return r;
}

/** Latches true the first time the element scrolls into view. */
export function useSeen<T extends Element>(threshold = 0.12) {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e?.isIntersecting) { setSeen(true); io.disconnect(); } },
      { rootMargin: "0px 0px -6% 0px", threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [seen, threshold]);
  return [ref, seen] as const;
}

/** Fades and lifts children in on first sight; reduced motion shows them at once. */
export function Reveal({ children, className, delay = 0, style }: { children: ReactNode; className?: string; delay?: number; style?: CSSProperties }) {
  const [ref, seen] = useSeen<HTMLDivElement>(0.05);
  const reduced = useReduced();
  const on = seen || reduced;
  return (
    <div ref={ref} className={cx("transition-[opacity,transform] duration-700 ease-out motion-reduce:transition-none", on ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0", className)}
      style={{ transitionDelay: on && !reduced ? `${delay}s` : undefined, ...style }}>
      {children}
    </div>
  );
}

/** Counts up to `value` once on screen (ease-out, ~1.2 s); reduced motion renders the final value. */
export function CountUp({ value, format, duration = 1200 }: { value: number; format: (n: number) => string; duration?: number }) {
  const [ref, seen] = useSeen<HTMLSpanElement>(0.3);
  const reduced = useReduced();
  const [shown, setShown] = useState(reduced ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced) { setShown(value); return; }
    if (!seen) return;
    const start = performance.now(), a = from.current;
    let id = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / duration);
      const v = a + (value - a) * (1 - Math.pow(1 - k, 3));
      setShown(v);
      from.current = v;
      if (k < 1) id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [seen, value, reduced, duration]);
  return <span ref={ref} className="tabular-nums">{format(shown)}</span>;
}
