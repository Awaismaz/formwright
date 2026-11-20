import type { ToasterProps } from "sonner";

/** Where notifications appear (founder, 2026-11-20: "Archie has something to tell you" covered the problem text at
 * the interfaces gate). Bottom right, narrow, at most three at once, each with a close button: never over the page
 * heading, gate cards or the primary text, which sit at the top and in the middle of every page. */
export const TOASTER_PROPS = {
  position: "bottom-right",
  richColors: true,
  closeButton: true,
  visibleToasts: 3,
  duration: 6000,
  toastOptions: { style: { maxWidth: "min(360px, calc(100vw - 32px))" } },
} satisfies ToasterProps;
