/** Typed Studio commands (IDEA 5): short verbs with numbers, parsed deterministically (no AI, no tokens). */
import type { ViewName } from "@/viewer/types";

export type Parsed =
  | { kind: "fillet" | "chamfer" | "shell"; size: number }
  | { kind: "hole"; type: "clearance" | "tapped" | "cbore" | "csk" | "simple"; size?: number; d?: number; count?: number; edge?: number }
  | { kind: "view"; view: ViewName } | { kind: "fit" } | { kind: "normal" }
  | { kind: "suppress" | "unsuppress"; name: string }
  | { kind: "undo" } | { kind: "redo" } | { kind: "measure" } | { kind: "select" } | { kind: "section" } | { kind: "shortcuts" };

const VIEWS: ViewName[] = ["Iso", "Front", "Top", "Right", "Back", "Left", "Bottom"];
const NUM = String.raw`(\d+(?:[.,]\d+)?)`;
const n = (s: string) => Number(s.replace(",", "."));

export function parse(raw: string): Parsed | null {
  const t = raw.trim().toLowerCase().replace(/\s+/g, " ");
  if (!t) return null;
  let m: RegExpMatchArray | null;
  if ((m = t.match(new RegExp(`^(fillet|round|chamfer|shell)\\s*(?:r|d|t|=)?\\s*${NUM}\\s*(?:mm)?$`)))) {
    const kind = m[1] === "round" ? "fillet" : (m[1] as "fillet" | "chamfer" | "shell");
    return n(m[2]!) > 0 ? { kind, size: n(m[2]!) } : null;
  }
  if (/^(tapped |c'?bore |counterbored? |c'?sink |countersunk |clearance )?holes?\b/.test(t) || /^(tap|cbore|csk)\b/.test(t)) {
    const type = /tap/.test(t) ? "tapped" : /c'?bore|counterbore/.test(t) ? "cbore" : /c'?sink|countersun/.test(t) ? "csk" : "clearance";
    const out: Extract<Parsed, { kind: "hole" }> = { kind: "hole", type };
    if ((m = t.match(/\bm\s?(\d{1,2})\b/))) out.size = Number(m[1]);
    else if ((m = t.match(new RegExp(`(?:ø|dia(?:meter)?\\s*|d\\s*=?\\s*)${NUM}`)) ?? t.match(new RegExp(`^holes?\\s+${NUM}\\s*(?:mm)?\\b`)))) { out.type = "simple"; out.d = n(m[1]!); }
    if ((m = t.match(/(?:x|×|\*)\s*(\d+)\b/) ?? t.match(/\b(\d+)\s*(?:x|×)?\s*holes?\b/))) out.count = Number(m[1]);
    if ((m = t.match(new RegExp(`${NUM}\\s*(?:mm)?\\s*(?:from|off)\\s*(?:the\\s*)?edges?`)))) out.edge = n(m[1]!);
    return out.size !== undefined || out.d !== undefined ? out : null;
  }
  if ((m = t.match(/^(?:view\s+)?(iso|isometric|front|top|right|back|left|bottom)(?:\s+view)?$/))) {
    const v = m[1] === "isometric" ? "iso" : m[1]!;
    return { kind: "view", view: VIEWS.find(x => x.toLowerCase() === v)! };
  }
  if (/^(fit|zoom ?(to )?fit|zoom all)$/.test(t)) return { kind: "fit" };
  if (/^normal( to)?$/.test(t)) return { kind: "normal" };
  if ((m = t.match(/^(un)?suppress\s+(.+)$/))) return { kind: m[1] ? "unsuppress" : "suppress", name: raw.trim().replace(/^\s*(un)?suppress\s+/i, "") };
  if (/^undo$/.test(t)) return { kind: "undo" };
  if (/^redo$/.test(t)) return { kind: "redo" };
  if (/^measure$/.test(t)) return { kind: "measure" };
  if (/^select$/.test(t)) return { kind: "select" };
  if (/^section( view)?$/.test(t)) return { kind: "section" };
  if (/^(shortcuts|keys|help)$/.test(t)) return { kind: "shortcuts" };
  return null;
}

/** Examples shown in the palette (and matched while typing). */
export const EXAMPLES: [string, string][] = [
  ["fillet 3", "Round the selected edges R3"],
  ["chamfer 1", "Chamfer the selected edges 1 mm"],
  ["hole M6 x4 10 from edges", "Hole Wizard on the selected face: 4 × M6 clearance at the corners"],
  ["tapped hole M8", "Hole Wizard: M8 tapped on the selected face"],
  ["shell 2", "Shell 2 mm, removing the selected faces"],
  ["view top", "Top view (also front, right, iso, back, left, bottom)"],
  ["fit", "Zoom to fit, keeping the orientation"],
  ["normal to", "Look straight at the selected face"],
  ["suppress Centre pocket", "Suppress a feature by name"],
  ["undo", "Undo the last change"],
  ["measure", "Measure tool"],
];

export const SHORTCUTS: [string, string][] = [
  ["Ctrl+K", "Type a command (fillet 3, hole M6 x4 10 from edges, view top…)"],
  ["Ctrl+Z / Ctrl+Y", "Undo / redo the last change (no AI)"],
  ["Enter / Esc", "OK / cancel in a feature panel"],
  ["F", "Zoom to fit"],
  ["D", "Show or hide the design dimensions on the model (click a value to change it)"],
  ["Ctrl+1 … Ctrl+7", "Iso, Front, Top, Right, Back, Left, Bottom view"],
  ["Esc", "Clear the selection, leave a tool or the plane picker"],
  ["?", "This list"],
];
