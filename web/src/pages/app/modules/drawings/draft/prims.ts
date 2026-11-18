/**
 * Sheet primitives for the 2D drafting editor: the same primitive list (and the same ISO 129 dimension layout) the
 * server draws for the SVG / PDF exports in `aicad/drawing/draft.py`, so what the user edits is what prints.
 * Paper millimetres, y down. Arc angles are degrees, counter-clockwise as seen on the sheet.
 */
import type { P2 } from "@/sketch/tools";
import {
  angleSector, circleOf, dimText, kOf, lineOf, measure, pointMap, toPaper,
  type Anno, type DEnt, type Dim, type DraftDoc, type GdtSymbol,
} from "./geom";

export type Prim =
  | { t: "line"; l: string; p: [number, number, number, number]; ent?: string; dim?: string; anno?: string }
  | { t: "poly"; l: string; p: P2[]; closed?: boolean; ent?: string; dim?: string; anno?: string }
  | { t: "circle"; l: string; p: [number, number, number]; ent?: string; dim?: string; anno?: string }
  | { t: "arc"; l: string; p: [number, number, number, number, number]; ent?: string; dim?: string; anno?: string }
  | { t: "fill"; l: string; p: P2[]; ent?: string; dim?: string; anno?: string }
  | { t: "text"; l: string; x: number; y: number; s: number; txt: string; anchor: "start" | "middle" | "end"; rot: number; font?: string; kind?: string; color?: string; ent?: string; dim?: string; anno?: string; box?: number[] };

export const LAYER_STYLE: Record<string, string> = { visible: "visible", hidden: "hidden", center: "center_n", dimension: "dim_n", construction: "construction" };
/** line layer -> [width mm, dash or null, colour] (same values as the server's layout.LAYERS) */
export const LINE_STYLES: Record<string, [number, number[] | null, string]> = {
  visible: [0.5, null, "#111111"], hidden: [0.25, [3, 1.2], "#111111"], center: [0.18, [8, 1.5, 1, 1.5], "#333333"],
  center_n: [0.25, [8, 1.5, 1, 1.5], "#333333"], dim_n: [0.25, null, "#222222"], hatch_n: [0.25, null, "#333333"],
  construction: [0.13, [1, 1], "#5b7db1"], frame: [0.7, null, "#111111"], tb: [0.35, null, "#111111"], tbthin: [0.18, null, "#444444"],
  banner: [0.6, null, "#b91c1c"], hatch: [0.18, null, "#333333"], dim: [0.18, null, "#222222"],
};
export const TEXT_COLORS: Record<string, string> = { normal: "#111111", label: "#555555", banner: "#b91c1c" };
export const FILLS: Record<string, string> = { bannerfill: "#fdecec" };

const ARROW = 2.6, ARROW_W = 0.42, EXT_GAP = 1, EXT_OVER = 2, TXT_GAP = 1;
// Helvetica advance widths (1/1000 em), as used by the server's text metrics
const W: Record<string, number> = { " ": 278, "!": 278, "\"": 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
  A: 667, B: 667, C: 722, D: 722, E: 667, F: 611, G: 778, H: 722, I: 278, J: 500, K: 667, L: 556, M: 833, N: 722, O: 778, P: 667, Q: 778, R: 722, S: 667, T: 611, U: 722, V: 667, W: 944, X: 667, Y: 667, Z: 611,
  "[": 278, "\\": 278, "]": 278, "^": 469, _: 556, a: 556, b: 556, c: 500, d: 556, e: 556, f: 278, g: 556, h: 556, i: 222, j: 222, k: 500, l: 222, m: 833, n: 556, o: 556, p: 556, q: 556, r: 333, s: 500, t: 278, u: 556, v: 500, w: 722, x: 500, y: 500, z: 500,
  "°": 400, "±": 584, "Ø": 778, "×": 584 };
export function textWidth(txt: string, size: number): number { let w = 0; for (const ch of txt) w += W[ch] ?? (ch >= "0" && ch <= "9" ? 556 : 600); return w / 1000 * size; }

export const textSize = (doc: DraftDoc) => (doc.sheet.size === "A4" || doc.sheet.size === "ANSI A" ? 3 : 3.5);

class Out {
  list: Prim[] = [];
  constructor(private tag: { dim?: string; anno?: string; ent?: string } = {}) {}
  with(tag: { dim?: string; anno?: string; ent?: string }) { const o = new Out(tag); o.list = this.list; return o; }
  line(l: string, a: P2, b: P2) { if (Math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-9) this.list.push({ t: "line", l, p: [a[0], a[1], b[0], b[1]], ...this.tag }); }
  poly(l: string, p: P2[], closed = false) { this.list.push({ t: "poly", l, p, closed, ...this.tag }); }
  circle(l: string, c: P2, r: number) { this.list.push({ t: "circle", l, p: [c[0], c[1], r], ...this.tag }); }
  arc(l: string, c: P2, r: number, a0: number, a1: number) { this.list.push({ t: "arc", l, p: [c[0], c[1], r, a0, a1], ...this.tag }); }
  fill(l: string, p: P2[]) { this.list.push({ t: "fill", l, p, ...this.tag }); }
  arrow(tip: P2, frm: P2, l = "dim_n") {
    const dx = tip[0] - frm[0], dy = tip[1] - frm[1]; const n = Math.hypot(dx, dy) || 1; const ux = dx / n, uy = dy / n;
    const bx = tip[0] - ux * ARROW, by = tip[1] - uy * ARROW;
    this.fill(l, [tip, [bx - uy * ARROW_W, by + ux * ARROW_W], [bx + uy * ARROW_W, by - ux * ARROW_W]]);
  }
  text(x: number, y: number, s: number, txt: string, anchor: "start" | "middle" | "end" = "middle", rot = 0, kind = "anno") {
    this.list.push({ t: "text", l: "text", x, y, s, txt, anchor, rot, kind, ...this.tag });
  }
}

const readable = (theta: number) => { let t = ((theta + 180) % 360 + 360) % 360 - 180; if (t > 90.0001) t -= 180; else if (t <= -90.0001) t += 180; return t; };
const up = (th: number): P2 => [-Math.sin(th * Math.PI / 180), -Math.cos(th * Math.PI / 180)];
const along = (th: number): P2 => [Math.cos(th * Math.PI / 180), -Math.sin(th * Math.PI / 180)];
const stackW = (stack: string[], size: number) => Math.max(0, ...stack.map(t => textWidth(t, size * 0.7)));
export const valueWidth = (main: string, stack: string[], size: number) => (main ? textWidth(main, size) + (stack.length ? stackW(stack, size) + 0.6 : 0) : stackW(stack, size));

function valueText(o: Out, x: number, y: number, th: number, size: number, main: string, stack: string[]) {
  if (main) o.text(x, y, size, main, "middle", th, "dim");
  if (stack.length) {
    const sz = size * 0.7, [ax, ay] = along(th), [ux, uy] = up(th);
    const wm = main ? textWidth(main, size) : 0;
    const [sx, sy] = main ? [x + ax * (wm / 2 + 0.6), y + ay * (wm / 2 + 0.6)] : [x, y];
    const anchor = main ? "start" : "middle";
    o.text(sx + ux * sz * 0.75, sy + uy * sz * 0.75, sz, stack[0]!, anchor, th, "dim");
    o.text(sx - ux * sz * 0.45, sy - uy * sz * 0.45, sz, stack[1]!, anchor, th, "dim");
  }
}

function linear(o: Out, doc: DraftDoc, d: Extract<Dim, { type: "linear" }>, size: number, P: Map<string, P2>) {
  const v = measure(doc, d, P); if (v === null) return;
  const A = toPaper(doc.sheet, P.get(d.a)!), B = toPaper(doc.sheet, P.get(d.b)!), Q = toPaper(doc.sheet, d.pos);
  let u: P2 = d.orient === "h" ? [1, 0] : d.orient === "v" ? [0, 1] : [B[0] - A[0], B[1] - A[1]];
  if (d.orient === "aligned") { const l = Math.hypot(...u); if (l < 1e-9) return; u = [u[0] / l, u[1] / l]; }
  const n: P2 = [-u[1], u[0]];
  const dq = (Q[0] - A[0]) * n[0] + (Q[1] - A[1]) * n[1];
  const db = (A[0] - B[0]) * n[0] + (A[1] - B[1]) * n[1] + dq;
  let A2: P2 = [A[0] + n[0] * dq, A[1] + n[1] * dq], B2: P2 = [B[0] + n[0] * db, B[1] + n[1] * db];
  for (const [P0, P1, off] of [[A, A2, dq], [B, B2, db]] as [P2, P2, number][]) if (Math.abs(off) > EXT_GAP) {
    const sg = off > 0 ? 1 : -1;
    o.line("dim_n", [P0[0] + n[0] * sg * EXT_GAP, P0[1] + n[1] * sg * EXT_GAP], [P1[0] + n[0] * sg * EXT_OVER, P1[1] + n[1] * sg * EXT_OVER]);
  }
  let span = (B2[0] - A2[0]) * u[0] + (B2[1] - A2[1]) * u[1];
  if (span < 0) { [A2, B2] = [B2, A2]; span = -span; }
  const tq = (Q[0] - A2[0]) * u[0] + (Q[1] - A2[1]) * u[1];
  const { main, stack } = dimText(doc, d, v);
  const th = readable(Math.atan2(-u[1], u[0]) * 180 / Math.PI);
  const tw = valueWidth(main, stack, size);
  const inside = span >= 2 * ARROW + 1;
  let lo = 0, hi = span;
  if (tq - tw / 2 < 0) lo = tq - tw / 2 - 1;
  if (tq + tw / 2 > span) hi = tq + tw / 2 + 1;
  if (!inside) { lo = Math.min(lo, -ARROW - 3); hi = Math.max(hi, span + ARROW + 3); }
  o.line("dim_n", [A2[0] + u[0] * lo, A2[1] + u[1] * lo], [A2[0] + u[0] * hi, A2[1] + u[1] * hi]);
  if (inside) { o.arrow(A2, [A2[0] + u[0], A2[1] + u[1]]); o.arrow(B2, [B2[0] - u[0], B2[1] - u[1]]); }
  else { o.arrow(A2, [A2[0] - u[0], A2[1] - u[1]]); o.arrow(B2, [B2[0] + u[0], B2[1] + u[1]]); }
  const [ux, uy] = up(th);
  const cx = A2[0] + u[0] * tq, cy = A2[1] + u[1] * tq;
  valueText(o, cx + ux * TXT_GAP, cy + uy * TXT_GAP, th, size, main, stack);
}

function shoulder(o: Out, Q: P2, fromX: number, size: number, main: string, stack: string[]) {
  const w = valueWidth(main, stack, size); const sg = Q[0] >= fromX ? 1 : -1;
  const end: P2 = [Q[0] + sg * (w + 2), Q[1]];
  o.line("dim_n", Q, end);
  const mid = (Q[0] + end[0]) / 2 - (stack.length && main ? (stackW(stack, size) + 0.6) / 2 : 0);
  valueText(o, mid, Q[1] - TXT_GAP, 0, size, main, stack);
}

function radial(o: Out, doc: DraftDoc, d: Extract<Dim, { type: "radius" | "diameter" }>, size: number, P: Map<string, P2>) {
  const c = circleOf(doc, d.ent, P); if (!c) return;
  const v = d.type === "radius" ? c.r : 2 * c.r;
  const k = kOf(doc.sheet);
  const C = toPaper(doc.sheet, c.c), r = c.r * k, Q = toPaper(doc.sheet, d.pos);
  const dq = Math.hypot(Q[0] - C[0], Q[1] - C[1]);
  const w: P2 = dq > 1e-9 ? [(Q[0] - C[0]) / dq, (Q[1] - C[1]) / dq] : [Math.SQRT1_2, -Math.SQRT1_2];
  const Pp: P2 = [C[0] + w[0] * r, C[1] + w[1] * r];
  const far: P2 = [C[0] - w[0] * r, C[1] - w[1] * r];
  const { main, stack } = dimText(doc, d, v);
  if (dq <= r - 1e-6) {
    const start = d.type === "radius" ? C : far;
    o.line("dim_n", start, Pp); o.arrow(Pp, C);
    if (d.type === "diameter") o.arrow(start, C);
    const th = readable(Math.atan2(-w[1], w[0]) * 180 / Math.PI); const [ux, uy] = up(th);
    valueText(o, Q[0] + ux * TXT_GAP, Q[1] + uy * TXT_GAP, th, size, main, stack);
    return;
  }
  if (d.type === "radius") { o.line("dim_n", C, Q); o.arrow(Pp, C); }
  else { o.line("dim_n", far, Q); o.arrow(Pp, Q); o.arrow(far, C); }
  shoulder(o, Q, C[0], size, main, stack);
}

function angular(o: Out, doc: DraftDoc, d: Extract<Dim, { type: "angle" }>, size: number, P: Map<string, P2>) {
  const s = angleSector(doc, d, P); if (!s) return;
  const k = kOf(doc.sheet);
  const X = toPaper(doc.sheet, s.x), R = s.r * k; if (R < 1e-6) return;
  const a0 = s.a0, a1 = s.a0 + s.sweep;
  o.arc("dim_n", X, R, a0, a1);
  const rad = (a: number) => a * Math.PI / 180;
  for (const [ang, sg, lid] of [[a0, 1, d.l1], [a1, -1, d.l2]] as [number, number, string][]) {
    const c = Math.cos(rad(ang)), sn = Math.sin(rad(ang));
    const tip: P2 = [X[0] + R * c, X[1] - R * sn];
    o.arrow(tip, [tip[0] - sn * sg, tip[1] - c * sg]);
    const ln = lineOf(doc, lid, P);
    if (ln) {
      const reach = Math.max(...ln.map(p => { const q = toPaper(doc.sheet, p); return (q[0] - X[0]) * c - (q[1] - X[1]) * sn; }));
      if (reach < R - EXT_GAP) { const st = Math.max(reach, 0) + EXT_GAP; o.line("dim_n", [X[0] + st * c, X[1] - st * sn], [X[0] + (R + EXT_OVER) * c, X[1] - (R + EXT_OVER) * sn]); }
    }
  }
  const mid = rad(a0 + s.sweep / 2);
  const { main, stack } = dimText(doc, d, s.sweep);
  const tx = X[0] + (R + TXT_GAP + size * 0.6) * Math.cos(mid), ty = X[1] - (R + TXT_GAP + size * 0.6) * Math.sin(mid);
  valueText(o, tx, ty + size * 0.36, 0, size, main, stack);
}

function ordinate(o: Out, doc: DraftDoc, d: Extract<Dim, { type: "ordinate" }>, size: number, P: Map<string, P2>) {
  const v = measure(doc, d, P); if (v === null) return;
  const F = toPaper(doc.sheet, P.get(d.pt)!), Q = toPaper(doc.sheet, d.pos);
  const { main, stack } = dimText(doc, d, v);
  if (d.axis === "x") {
    const sg = Q[1] < F[1] ? -1 : 1;
    o.line("dim_n", [F[0], F[1] + sg * EXT_GAP], [F[0], Q[1]]);
    valueText(o, F[0] - TXT_GAP, Q[1] + sg * (textWidth(main, size) / 2 + 1), 90, size, main, stack);
  } else {
    const sg = Q[0] < F[0] ? -1 : 1;
    o.line("dim_n", [F[0] + sg * EXT_GAP, F[1]], [Q[0], F[1]]);
    valueText(o, Q[0] + sg * (textWidth(main, size) / 2 + 1), F[1] - TXT_GAP, 0, size, main, stack);
  }
}

// ------------------------------------------------------------------ annotations
function gdtSymbol(o: Out, sym: GdtSymbol, cx: number, cy: number, h: number) {
  const L = "dim_n", s = h * 0.32;
  switch (sym) {
    case "straightness": o.line(L, [cx - s, cy], [cx + s, cy]); break;
    case "flatness": o.poly(L, [[cx - s, cy + s * 0.5], [cx + s * 0.5, cy + s * 0.5], [cx + s, cy - s * 0.5], [cx - s * 0.5, cy - s * 0.5]], true); break;
    case "circularity": o.circle(L, [cx, cy], s * 0.8); break;
    case "cylindricity": o.circle(L, [cx, cy], s * 0.6); o.line(L, [cx - s * 0.95, cy + s], [cx - s * 0.25, cy - s]); o.line(L, [cx + s * 0.25, cy + s], [cx + s * 0.95, cy - s]); break;
    case "profile_line": o.arc(L, [cx, cy + s * 0.5], s, 0, 180); break;
    case "profile_surface": o.arc(L, [cx, cy + s * 0.5], s, 0, 180); o.line(L, [cx - s, cy + s * 0.5], [cx + s, cy + s * 0.5]); break;
    case "parallelism": o.line(L, [cx - s, cy + s], [cx - s * 0.2, cy - s]); o.line(L, [cx + s * 0.2, cy + s], [cx + s, cy - s]); break;
    case "perpendicularity": o.line(L, [cx - s, cy + s], [cx + s, cy + s]); o.line(L, [cx, cy + s], [cx, cy - s]); break;
    case "angularity": o.line(L, [cx - s, cy + s], [cx + s, cy + s]); o.line(L, [cx - s, cy + s], [cx + s, cy - s * 0.6]); break;
    case "position": o.circle(L, [cx, cy], s * 0.6); o.line(L, [cx - s, cy], [cx + s, cy]); o.line(L, [cx, cy - s], [cx, cy + s]); break;
    case "concentricity": o.circle(L, [cx, cy], s * 0.85); o.circle(L, [cx, cy], s * 0.45); break;
    case "symmetry": o.line(L, [cx - s, cy], [cx + s, cy]); o.line(L, [cx - s * 0.6, cy - s * 0.6], [cx + s * 0.6, cy - s * 0.6]); o.line(L, [cx - s * 0.6, cy + s * 0.6], [cx + s * 0.6, cy + s * 0.6]); break;
    default: {
      const tip: P2 = [cx + s * 0.6, cy - s]; o.line(L, [cx - s * 0.6, cy + s], tip); o.arrow(tip, [cx - s * 0.6, cy + s], L);
      if (sym === "total_runout") { o.line(L, [cx - s * 0.1, cy + s], [cx + s * 1.1, cy - s * 0.4]); o.line(L, [cx - s * 0.6, cy + s], [cx + s * 0.4, cy + s]); }
    }
  }
}

export function gdtCells(a: Extract<Anno, { type: "gdt" }>, size: number): [string, number][] {
  const h = 2 * size;
  const tol = (a.dia ? "Ø" : "") + a.tol + (a.mod ? ` ${a.mod}` : "");
  return [["@sym", h], [tol, textWidth(tol, size) + 2.4], ...a.datums.map(d => [d, Math.max(h, textWidth(d, size) + 2.4)] as [string, number])];
}

function annotation(o: Out, doc: DraftDoc, a: Anno, size: number, P: Map<string, P2>, loopPoly: (ids: string[]) => P2[] | null) {
  const T = (p: P2) => toPaper(doc.sheet, p);
  const L = "dim_n";
  switch (a.type) {
    case "text": { const p = T(a.pos); a.text.split("\n").forEach((ln, i) => o.text(p[0], p[1] + i * a.size * 1.5, a.size, ln, "start")); break; }
    case "leader": {
      const pts = a.pts.map(T); o.poly(L, pts); o.arrow(pts[0]!, pts[1]!);
      if (a.text) { const end = pts[pts.length - 1]!, sg = end[0] >= pts[pts.length - 2]![0] ? 1 : -1; const w = textWidth(a.text, size); o.line(L, end, [end[0] + sg * (w + 2), end[1]]); o.text(end[0] + sg * (w / 2 + 1), end[1] - TXT_GAP, size, a.text); }
      break;
    }
    case "balloon": {
      const tip = T(a.tip), p = T(a.pos), r = size * 1.45, dd = Math.hypot(tip[0] - p[0], tip[1] - p[1]);
      if (dd > r) o.line(L, [p[0] + (tip[0] - p[0]) / dd * r, p[1] + (tip[1] - p[1]) / dd * r], tip);
      o.circle(L, p, r);
      o.fill(L, Array.from({ length: 8 }, (_, i) => [tip[0] + 0.7 * Math.cos(i * Math.PI / 4), tip[1] + 0.7 * Math.sin(i * Math.PI / 4)] as P2));
      o.text(p[0], p[1] + size * 0.36, size, a.text);
      break;
    }
    case "surface": {
      const p = T(a.pos);
      if (a.tip) { const tip = T(a.tip); o.line(L, tip, p); o.arrow(tip, p); }
      const h1 = 1.4 * size, h2 = 2.8 * size, t60 = Math.tan(Math.PI / 3);
      const left: P2 = [p[0] - h1 / t60, p[1] - h1], right: P2 = [p[0] + h2 / t60, p[1] - h2];
      o.line(L, left, p); o.line(L, p, right);
      if (a.removal === "required") o.line(L, left, [p[0] + h1 / t60, p[1] - h1]);
      else if (a.removal === "prohibited") o.circle(L, [p[0], p[1] - h1 * 0.62], h1 * 0.36);
      if (a.text) { const w = textWidth(a.text, size); o.line(L, right, [right[0] + w + 2, right[1]]); o.text(right[0] + 1, right[1] + size + 1.2, size, a.text, "start"); }
      break;
    }
    case "gdt": {
      const p = T(a.pos), h = 2 * size; let x = p[0]; const y0 = p[1] - h / 2;
      if (a.tip) {
        const tip = T(a.tip); const knee = Math.abs(tip[0] - p[0]) > 1 && Math.abs(tip[1] - p[1]) > 1;
        o.poly(L, knee ? [tip, [tip[0], p[1]], p] : [tip, p]); o.arrow(tip, Math.abs(tip[1] - p[1]) > 1 ? [tip[0], p[1]] : p);
      }
      for (const [content, w] of gdtCells(a, size)) {
        o.poly(L, [[x, y0], [x + w, y0], [x + w, y0 + h], [x, y0 + h]], true);
        if (content === "@sym") gdtSymbol(o, a.symbol, x + w / 2, p[1], h); else o.text(x + w / 2, p[1] + size * 0.36, size, content, "middle", 0, "gdt");
        x += w;
      }
      break;
    }
    case "datum": {
      const tip = T(a.tip), p = T(a.pos), h = 2 * size;
      o.poly(L, [[p[0] - h / 2, p[1] - h / 2], [p[0] + h / 2, p[1] - h / 2], [p[0] + h / 2, p[1] + h / 2], [p[0] - h / 2, p[1] + h / 2]], true);
      o.text(p[0], p[1] + size * 0.36, size, a.letter);
      const dd = Math.hypot(tip[0] - p[0], tip[1] - p[1]);
      if (dd > h / 2 + 1) {
        const u: P2 = [(tip[0] - p[0]) / dd, (tip[1] - p[1]) / dd];
        const start: P2 = Math.abs(u[1]) >= Math.abs(u[0]) ? [p[0] + u[0] * h / 2, p[1] + u[1] * h / 2] : [p[0] + Math.sign(u[0]) * h / 2, p[1]];
        o.line(L, start, tip);
        const n: P2 = [-u[1], u[0]], b: P2 = [tip[0] - u[0] * 2.6, tip[1] - u[1] * 2.6];
        o.fill(L, [[tip[0] + n[0] * 1.5, tip[1] + n[1] * 1.5], [tip[0] - n[0] * 1.5, tip[1] - n[1] * 1.5], b]);
      }
      break;
    }
    case "centermark": {
      const c = circleOf(doc, a.ent, P); if (!c) return;
      const C = T(c.c), r = c.r * kOf(doc.sheet) + 2.5;
      o.line("center_n", [C[0] - r, C[1]], [C[0] + r, C[1]]); o.line("center_n", [C[0], C[1] - r], [C[0], C[1] + r]);
      break;
    }
    case "hatch": {
      const loops = a.loops.map(loopPoly).filter((x): x is P2[] => !!x).map(l => l.map(T));
      for (const s of hatchLines(loops, a.spacing)) o.line("hatch_n", [s[0], s[1]], [s[2], s[3]]);
      break;
    }
  }
}

/** 45° hatch lines clipped to the even-odd region of the loops (paper coordinates); same as the server. */
export function hatchLines(loops: P2[][], spacing: number): [number, number, number, number][] {
  const c = Math.cos(-Math.PI / 4), s = Math.sin(-Math.PI / 4);
  const rot = (p: P2, sg = 1): P2 => [p[0] * c - sg * p[1] * s, sg * p[0] * s + p[1] * c];
  const r = loops.map(l => l.map(p => rot(p)));
  const ys = r.flat().map(p => p[1]); if (!ys.length) return [];
  const out: [number, number, number, number][] = [];
  const ymax = Math.max(...ys);
  for (let y = Math.floor(Math.min(...ys) / spacing) * spacing + spacing / 2; y < ymax; y += spacing) {
    const xs: number[] = [];
    for (const l of r) for (let i = 0; i < l.length; i++) { const a = l[i]!, b = l[(i + 1) % l.length]!; if ((a[1] - y) * (b[1] - y) < 0) xs.push(a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0])); }
    xs.sort((p, q) => p - q);
    for (let i = 0; i + 1 < xs.length; i += 2) { const p0 = rot([xs[i]!, y], -1), p1 = rot([xs[i + 1]!, y], -1); out.push([p0[0], p0[1], p1[0], p1[1]]); }
  }
  return out;
}

/** Everything the user drew, as sheet primitives (construction geometry included only when asked). */
export function contentPrims(doc: DraftDoc, opts: { construction?: boolean; hidden?: Set<string>; loopPoly: (ids: string[]) => P2[] | null }): Prim[] {
  const P = pointMap(doc); const o = new Out(); const size = textSize(doc); const k = kOf(doc.sheet);
  for (const e of doc.geom.entities as DEnt[]) {
    if ((e.layer === "construction" && !opts.construction) || opts.hidden?.has(e.layer)) continue;
    const g = o.with({ ent: e.id }); const l = LAYER_STYLE[e.layer] ?? "visible";
    if (e.type === "line") g.line(l, toPaper(doc.sheet, P.get(e.p1)!), toPaper(doc.sheet, P.get(e.p2)!));
    else if (e.type === "circle") g.circle(l, toPaper(doc.sheet, P.get(e.c)!), e.r * k);
    else {
      const c = P.get(e.c)!, p1 = P.get(e.p1)!, p2 = P.get(e.p2)!;
      const a0 = Math.atan2(p1[1] - c[1], p1[0] - c[0]) * 180 / Math.PI;
      const sw = ((Math.atan2(p2[1] - c[1], p2[0] - c[0]) * 180 / Math.PI - a0) % 360 + 360) % 360 || 360;
      g.arc(l, toPaper(doc.sheet, c), Math.hypot(p1[0] - c[0], p1[1] - c[1]) * k, a0, a0 + sw);
    }
  }
  const dimHidden = opts.hidden?.has("dimension");
  for (const a of doc.annos) if ((a.type === "hatch" || a.type === "centermark") && !(a.type === "centermark" && opts.hidden?.has("center"))) annotation(o.with({ anno: a.id }), doc, a, size, P, opts.loopPoly);
  if (!dimHidden) {
    for (const d of doc.dims) {
      const g = o.with({ dim: d.id });
      if (d.type === "linear") linear(g, doc, d, size, P);
      else if (d.type === "radius" || d.type === "diameter") radial(g, doc, d, size, P);
      else if (d.type === "angle") angular(g, doc, d, size, P);
      else ordinate(g, doc, d, size, P);
    }
    for (const a of doc.annos) if (a.type !== "hatch" && a.type !== "centermark") annotation(o.with({ anno: a.id }), doc, a, size, P, opts.loopPoly);
  }
  return o.list;
}

/** Paper bounding box of a primitive (for picking and box selection). */
export function primBox(p: Prim): [number, number, number, number] {
  if (p.t === "text") {
    const w = textWidth(p.txt, p.s); const off = p.anchor === "start" ? 0 : p.anchor === "middle" ? -w / 2 : -w;
    const c = Math.cos(p.rot * Math.PI / 180), s = Math.sin(p.rot * Math.PI / 180);
    const xs: number[] = [], ys: number[] = [];
    for (const [u, v] of [[off, -0.21 * p.s], [off + w, -0.21 * p.s], [off, 0.73 * p.s], [off + w, 0.73 * p.s]] as P2[]) { xs.push(p.x + u * c - v * s); ys.push(p.y - (u * s + v * c)); }
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }
  if (p.t === "line") return [Math.min(p.p[0], p.p[2]), Math.min(p.p[1], p.p[3]), Math.max(p.p[0], p.p[2]), Math.max(p.p[1], p.p[3])];
  if (p.t === "poly" || p.t === "fill") { const xs = p.p.map(q => q[0]), ys = p.p.map(q => q[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; }
  const [cx, cy, r] = p.p; return [cx - r, cy - r, cx + r, cy + r];
}
