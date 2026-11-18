import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { cx } from "@/lib/format";

const REDUCED = "(prefers-reduced-motion: reduce)";

/** True when the visitor asked the system for less motion; every landing animation settles to its end state. */
export function useReducedMotion(): boolean {
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

/** Whether the element is on screen (IntersectionObserver). `once` latches true after the first sighting. */
export function useInView(ref: RefObject<Element | null>, { once = false, margin = "0px", threshold = 0.15 } = {}): boolean {
  const [v, setV] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") { setV(true); return; }
    const io = new IntersectionObserver(([e]) => {
      if (e?.isIntersecting) { setV(true); if (once) io.disconnect(); }
      else if (!once) setV(false);
    }, { rootMargin: margin, threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, once, margin, threshold]);
  return v;
}

/** A looping clock in seconds that only advances while `running` (on screen, motion allowed). */
export function useLoopClock(running: boolean, loop: number, stepMs = 80): number {
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!running) return;
    let last = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      const dt = Math.min(0.25, (now - last) / 1000);
      last = now;
      setT(x => (x + dt) % loop);
    }, stepMs);
    return () => window.clearInterval(id);
  }, [running, loop, stepMs]);
  return t;
}

/** A step counter that ticks every `ms` while running. */
export function useTicker(running: boolean, ms: number): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setN(x => x + 1), ms);
    return () => window.clearInterval(id);
  }, [running, ms]);
  return n;
}

/** Fades and lifts its children in the first time they scroll into view; adds `is-in` for child keyframes. */
export function Reveal({ children, className, as: Tag = "div", delay = 0 }:
  { children: ReactNode; className?: string; as?: "div" | "section" | "li"; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "0px 0px -8% 0px", threshold: 0.05 });
  return (
    <Tag ref={ref as never} className={cx("fw-reveal", seen && "is-in", className)} style={delay ? { transitionDelay: `${delay}s` } : undefined}>
      {children}
    </Tag>
  );
}
