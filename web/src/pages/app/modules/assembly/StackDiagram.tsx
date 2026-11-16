import type { Probe, Proposal } from "./types";

/** ISO dimensions used for drawing only (same values as the Toolbox tables the stack is built from). */
const HEX: Record<number, [number, number]> = { 3: [5.5, 2], 4: [7, 2.8], 5: [8, 3.5], 6: [10, 4], 8: [13, 5.3], 10: [16, 6.4], 12: [18, 7.5], 16: [24, 10], 20: [30, 12.5], 24: [36, 15] };
const SHCS: Record<number, [number, number]> = { 3: [5.5, 3], 4: [7, 4], 5: [8.5, 5], 6: [10, 6], 8: [13, 8], 10: [16, 10], 12: [18, 12], 16: [24, 16], 20: [30, 20], 24: [36, 24] };
const NUT: Record<number, number> = { 3: 2.4, 4: 3.2, 5: 4.7, 6: 5.2, 8: 6.8, 10: 8.4, 12: 10.8, 16: 14.8, 20: 18, 24: 21.5 };
const WASHER: Record<number, [number, number, number]> = { 3: [3.2, 7, 0.5], 4: [4.3, 9, 0.8], 5: [5.3, 10, 1], 6: [6.4, 12, 1.6], 8: [8.4, 16, 1.6], 10: [10.5, 20, 2], 12: [13, 24, 2.5], 16: [17, 30, 3], 20: [21, 37, 3], 24: [25, 44, 4] };

/**
 * Half-section of the proposed joint, to scale: clamped parts (hatched) with the clearance hole, the screw with its
 * head and washers, the nut (through joint) or the tapped part (tapped joint), and the grip / length / protrusion
 * dimensions the length rule used.
 */
export function StackDiagram({ probe, prop }: { probe: Probe; prop: Proposal }) {
  if (!prop.ok || !prop.size || !prop.items || !prop.length?.L) return null;
  const d = prop.size;
  const L = prop.length.L;
  const screw = prop.items[0]!;
  const [hs, hk] = screw.code === "shcs" ? SHCS[d]! : HEX[d]!;
  const wHead = prop.items.some(i => i.role === "washer_head");
  const wNut = prop.items.some(i => i.role === "washer_nut");
  const hasNut = prop.items.some(i => i.role === "nut");
  const [, wd2, wh] = WASHER[d]!;
  const m = NUT[d]!;
  const grip = probe.grip;
  const tapped = probe.kind === "tapped" ? probe.tapped : null;
  // axial coordinates (mm), y downwards from the head top
  const yHeadTop = 0;
  const yHeadBot = hk;
  const ySeat = yHeadBot + (wHead ? wh : 0);
  const yNutSeat = ySeat + grip;
  const yTip = yHeadBot + L;
  const yNutTop = yNutSeat + (wNut ? wh : 0);
  const yNutBot = yNutTop + (hasNut ? m : 0);
  const tapDepth = tapped ? Math.max(tapped.depth, 0) : 0;
  const yEnd = Math.max(yTip, hasNut ? yNutBot : yNutSeat + tapDepth) + 1;
  const halfW = Math.max(wd2, hs) * 1.25;
  // fit into the box
  const W = 300, H = 230, padT = 10, padB = 14, padL = 18, dimW = 92;
  const s = Math.min((H - padT - padB) / yEnd, (W - padL - dimW) / (2 * halfW));
  const cx = padL + halfW * s;
  const X = (x: number) => cx + x * s;
  const Y = (y: number) => padT + y * s;
  const hole = probe.hole_d / 2;
  const rect = (x0: number, y0: number, x1: number, y1: number, cls: string, key: string) =>
    <rect key={key} x={X(x0)} y={Y(y0)} width={(x1 - x0) * s} height={(y1 - y0) * s} className={cls} />;
  // clamped members (head side first)
  let y = ySeat;
  const members = probe.members.map((mem, k) => {
    const y0 = y; y += mem.t;
    return (
      <g key={`m${k}`}>
        {rect(-halfW, y0, -hole, y, "asm-part", `ml${k}`)}{rect(hole, y0, halfW, y, "asm-part", `mr${k}`)}
        <text x={X(-halfW) + 3} y={Y((y0 + y) / 2) + 3.5} className="asm-dim-text" textAnchor="start">{mem.name.replace(/<\d+>$/, "")}</text>
      </g>
    );
  });
  const tapY0 = yNutSeat, tapY1 = yNutSeat + tapDepth;
  const P = prop.pitch ?? 1;
  const threadFrom = screw.code === "hex_bolt" ? yHeadBot : Math.max(yHeadBot, yTip - (2 * d + 12));
  const dimX = X(halfW) + 10;
  const dim = (y0: number, y1: number, label: string, x: number, key: string) => (
    <g key={key} className="asm-dim">
      <line x1={x - 4} y1={Y(y0)} x2={x + 4} y2={Y(y0)} /><line x1={x - 4} y1={Y(y1)} x2={x + 4} y2={Y(y1)} />
      <line x1={x} y1={Y(y0)} x2={x} y2={Y(y1)} markerStart="url(#asm-arrow)" markerEnd="url(#asm-arrow)" />
      <text x={x + 6} y={(Y(y0) + Y(y1)) / 2 + 3.5} className="asm-dim-text">{label}</text>
    </g>
  );
  const fmt = (v: number) => (+v.toFixed(2)).toString();
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Section through the proposed fastener stack" data-testid="stack-diagram">
      <defs>
        <pattern id="asm-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" className="asm-hatch-line" />
        </pattern>
        <marker id="asm-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="asm-arrow" />
        </marker>
      </defs>
      <style>{`
        .asm-part { fill: url(#asm-hatch); stroke: rgb(var(--muted)); stroke-width: .8; }
        .asm-hatch-line { stroke: rgb(var(--muted) / .55); stroke-width: 1.2; }
        .asm-steel { fill: rgb(var(--text) / .16); stroke: rgb(var(--text) / .75); stroke-width: .9; }
        .asm-washer { fill: rgb(var(--accent) / .22); stroke: rgb(var(--accent)); stroke-width: .9; }
        .asm-thread { stroke: rgb(var(--text) / .45); stroke-width: .7; stroke-dasharray: 2 1.5; }
        .asm-axis { stroke: rgb(var(--primary)); stroke-width: .7; stroke-dasharray: 6 2 1 2; }
        .asm-dim line { stroke: rgb(var(--primary)); stroke-width: .8; }
        .asm-arrow { fill: rgb(var(--primary)); }
        .asm-dim-text { font: 600 9.5px ui-sans-serif, system-ui; fill: rgb(var(--text) / .8); }
        .asm-tap { stroke: rgb(var(--danger) / .7); stroke-width: .7; }
      `}</style>
      {members}
      {tapped && <g>
        {rect(-halfW, tapY0, -d / 2, tapY1, "asm-part", "tl")}{rect(d / 2, tapY0, halfW, tapY1, "asm-part", "tr")}
        {!tapped.blind ? null : rect(-halfW, tapY1, halfW, tapY1 + 2, "asm-part", "tb")}
        {Array.from({ length: Math.max(1, Math.floor(tapDepth / P)) }, (_, k) => (
          <line key={k} x1={X(-d / 2)} x2={X(-d / 2 + 0.6 * P)} y1={Y(tapY0 + k * P)} y2={Y(tapY0 + k * P + P / 2)} className="asm-tap" />
        ))}
        <text x={X(-halfW) + 3} y={Y((tapY0 + tapY1) / 2) + 3.5} className="asm-dim-text">{tapped.name.replace(/<\d+>$/, "")} (tapped)</text>
      </g>}
      {/* screw */}
      {rect(-hs / 2, yHeadTop, hs / 2, yHeadBot, "asm-steel", "head")}
      {rect(-d / 2, yHeadBot, d / 2, yTip, "asm-steel", "shank")}
      <line x1={X(-d * 0.42)} x2={X(-d * 0.42)} y1={Y(threadFrom)} y2={Y(yTip)} className="asm-thread" />
      <line x1={X(d * 0.42)} x2={X(d * 0.42)} y1={Y(threadFrom)} y2={Y(yTip)} className="asm-thread" />
      {wHead && rect(-wd2 / 2, yHeadBot, wd2 / 2, ySeat, "asm-washer", "wh")}
      {wNut && rect(-wd2 / 2, yNutSeat, wd2 / 2, yNutTop, "asm-washer", "wn")}
      {hasNut && rect(-hs / 2, yNutTop, hs / 2, yNutBot, "asm-steel", "nut")}
      <line x1={X(0)} x2={X(0)} y1={Y(-0.5)} y2={Y(yEnd - 0.3)} className="asm-axis" />
      {dim(ySeat, yNutSeat, `grip ${fmt(grip)}`, dimX, "dg")}
      {dim(yHeadBot, yTip, `L ${L}`, dimX + 46, "dl")}
      {hasNut && prop.length.protrusion !== undefined && yTip > yNutBot + 0.05 && dim(yNutBot, yTip, `${fmt(prop.length.protrusion)} out`, dimX, "dp")}
      {tapped && prop.length.engagement !== undefined && dim(yNutSeat, Math.min(yTip, tapY1), `engaged ${fmt(prop.length.engagement)}`, dimX, "de")}
    </svg>
  );
}
