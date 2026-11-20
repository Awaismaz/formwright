import { driver } from "driver.js";
import "driver.js/dist/driver.css";

/** What Archie sees of the screen (founder 2026-11-20, the whole-app copilot): the page and its visible controls. */
export interface PageTarget { id: string; label: string }
export interface PageView { path: string; title: string; targets: PageTarget[] }

const SEL = "button, a[href], [role=tab], [data-copilot], [data-tour]";
const MAX = 80;

function labelOf(el: Element): string {
  const raw = el.getAttribute("aria-label") || el.getAttribute("title") || (el as HTMLElement).innerText || el.textContent || "";
  return raw.replace(/\s+/g, " ").trim().slice(0, 60);
}

function idOf(el: Element, label: string): string {
  const c = el.getAttribute("data-copilot");
  if (c) return c;
  const t = el.getAttribute("data-tour");
  if (t) return `tour:${t}`;
  return `t:${label}`;
}

function visible(el: Element): boolean {
  const h = el as HTMLElement;
  if (h.closest("[data-archie-chat]")) return false; // never Archie's own drawer
  return h.getClientRects().length > 0 && getComputedStyle(h).visibility !== "hidden";
}

/** The visible controls of the page, labelled; ids prefer data-copilot / data-tour, else the label. */
export function pageTargets(root: ParentNode = document): PageTarget[] {
  const out: PageTarget[] = [];
  const seen = new Set<string>();
  for (const el of Array.from(root.querySelectorAll(SEL))) {
    if (!visible(el)) continue;
    const label = labelOf(el);
    if (!label) continue;
    const id = idOf(el, label);
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({ id, label });
    if (out.length >= MAX) break;
  }
  return out;
}

export function pageView(): PageView {
  return { path: window.location.pathname + window.location.search, title: document.title, targets: pageTargets() };
}

/** The element for a target id or label (the page may have re-rendered since Archie saw it). */
export function findTarget(id: string, label?: string, root: ParentNode = document): HTMLElement | null {
  const els = Array.from(root.querySelectorAll(SEL)).filter(visible) as HTMLElement[];
  const want = (label ?? "").toLowerCase();
  const bare = id.startsWith("t:") ? id.slice(2).toLowerCase() : id.toLowerCase();
  return els.find(e => idOf(e, labelOf(e)) === id)
    ?? els.find(e => labelOf(e).toLowerCase() === (want || bare))
    ?? els.find(e => { const l = labelOf(e).toLowerCase(); return !!l && (l.startsWith(want || bare) || (want || bare).startsWith(l)); })
    ?? null;
}

/** Point at a control: a spotlight with Archie's note. Waits a moment for a page that is still loading. */
export async function pointAt(id: string, label?: string, note?: string, waitMs = 4000): Promise<boolean> {
  const t0 = Date.now();
  let el = findTarget(id, label);
  while (!el && Date.now() - t0 < waitMs) {
    await new Promise(r => setTimeout(r, 200));
    el = findTarget(id, label);
  }
  if (!el) return false;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  const d = driver({ popoverClass: "fw-tour", overlayOpacity: 0.35, stagePadding: 6, allowClose: true });
  d.highlight({ element: el, popover: { title: label || labelOf(el), description: note || "Archie is pointing here.", side: "bottom" } });
  return true;
}
