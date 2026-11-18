import { useSyncExternalStore } from "react";

/** A CSS media query as React state. */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (l) => { const m = matchMedia(query); m.addEventListener("change", l); return () => m.removeEventListener("change", l); },
    () => matchMedia(query).matches,
    () => false,
  );
}

/** Phone layout (UX-018): below Tailwind's `md`. */
export const PHONE = "(max-width: 767px)";
/** Phones and tablets in portrait: side panels overlay the viewer instead of squeezing it (below `lg`). */
export const COMPACT = "(max-width: 1023px)";
/** A desktop: wide screen and a precise pointer. Local integrations (CAD plugins, bridges) need one. */
export const DESKTOP = "(min-width: 1024px) and (pointer: fine)";
