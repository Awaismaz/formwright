import { Check, Coins, Send } from "lucide-react";
import { LogoMark } from "./ui";

/** Product illustration for the landing page: the real Design Studio layout, drawn as vector art. */
export default function HeroVisual() {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-panel shadow-[0_30px_80px_-20px_rgb(16_24_40/.35)]">
      <div className="flex h-9 items-center gap-2 border-b border-white/5 bg-chrome px-3">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" /><span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" /><span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
        <LogoMark size={16} className="ml-3" /><span className="text-[11px] text-chrome-muted">Formwright · Bracket rev 3</span>
        <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-chrome-fg"><Coins className="h-3 w-3" />1,412</span>
      </div>
      <div className="grid grid-cols-[1fr_1.5fr_0.95fr] text-[11px] max-md:grid-cols-[1fr_1.4fr]">
        {/* chat */}
        <div className="flex flex-col gap-2 border-r border-border bg-panel p-3">
          <div className="ml-auto max-w-[90%] rounded-lg bg-primary px-2.5 py-1.5 text-white">6061 L-bracket, 60/40 legs, 50 wide, 5 thick, 4× M5 clearance, R3 inside fillet</div>
          <div className="rounded-lg border border-border bg-panel2 px-2.5 py-1.5 text-text">
            <b>Interpreted:</b> legs to outside corner · Ø5.5 holes (ISO 273 medium) · 15 mm from ends.
          </div>
          <div className="flex items-center gap-1.5 text-muted"><Check className="h-3 w-3 text-success" /> Write model.py</div>
          <div className="flex items-center gap-1.5 text-muted"><Check className="h-3 w-3 text-success" /> build_model — all checks pass</div>
          <div className="rounded-lg border border-border bg-panel2 px-2.5 py-1.5 text-text">Built and verified. Volume matches hand calc exactly. ⚠ Vertical-leg holes are 10 mm apart — confirm?</div>
          <div className="mt-auto flex items-center gap-1.5 rounded border border-border bg-panel2 px-2 py-1.5 text-muted">Ask for a change… <Send className="ml-auto h-3 w-3 text-primary" /></div>
        </div>
        {/* viewport */}
        <div className="viewport-bg relative flex min-h-[260px] items-center justify-center">
          <svg viewBox="0 0 300 220" className="w-[86%] drop-shadow-[0_10px_14px_rgb(0_0_0/.18)]">
            <defs>
              <linearGradient id="top" x1="0" x2="1"><stop offset="0" stopColor="#C9D2DE" /><stop offset="1" stopColor="#AEB9C8" /></linearGradient>
              <linearGradient id="left" x1="0" x2="1"><stop offset="0" stopColor="#8E9AAB" /><stop offset="1" stopColor="#7B8798" /></linearGradient>
              <linearGradient id="right" x1="0" x2="1"><stop offset="0" stopColor="#A3AEBE" /><stop offset="1" stopColor="#94A0B1" /></linearGradient>
            </defs>
            <g stroke="#2B313B" strokeWidth="1" strokeLinejoin="round">
              {/* base plate */}
              <polygon points="60,120 170,175 255,130 145,75" fill="url(#top)" />
              <polygon points="60,120 170,175 170,188 60,133" fill="url(#left)" />
              <polygon points="170,175 255,130 255,143 170,188" fill="url(#right)" />
              {/* vertical leg */}
              <polygon points="60,120 145,75 145,10 60,55" fill="url(#right)" />
              <polygon points="60,55 145,10 155,15 70,60" fill="url(#top)" />
              <polygon points="70,60 155,15 155,80 70,125" fill="#A9B4C3" />
              {/* holes */}
              <ellipse cx="170" cy="140" rx="10" ry="5.5" fill="#5F6B7C" />
              <ellipse cx="210" cy="120" rx="10" ry="5.5" fill="#5F6B7C" />
              <ellipse cx="95" cy="62" rx="5.5" ry="9" fill="#5F6B7C" transform="rotate(-28 95 62)" />
              <ellipse cx="128" cy="45" rx="5.5" ry="9" fill="#5F6B7C" transform="rotate(-28 128 45)" />
            </g>
            <g fontSize="8" fill="#1F5FBF" fontFamily="Inter, sans-serif">
              <line x1="60" y1="196" x2="170" y2="196" stroke="#1F5FBF" strokeWidth=".8" /><text x="105" y="207">60.00</text>
            </g>
          </svg>
          <div className="absolute left-2 top-2 flex gap-1">{["Iso", "Front", "Top", "Right"].map(v => <span key={v} className="rounded border border-border bg-panel/90 px-1.5 py-0.5 text-[9.5px] text-muted">{v}</span>)}</div>
        </div>
        {/* checks */}
        <div className="space-y-1.5 border-l border-border bg-panel p-3 max-md:hidden">
          <div className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Checks</div>
          {[["Valid solid", "1 solid"], ["Bounding box", "60 × 50 × 40"], ["Volume", "Δ 0.000%"], ["STEP round-trip", "identical"], ["Deterministic", "byte-equal"]].map(([a, b]) => (
            <div key={a} className="flex items-center gap-1.5"><span className="rounded bg-success/12 px-1 text-[9px] font-bold text-success">PASS</span><span className="flex-1">{a}</span><span className="text-muted">{b}</span></div>
          ))}
          <div className="pt-2 text-[9.5px] font-bold uppercase tracking-wider text-muted">Parameters</div>
          {[["LEG_H", "60"], ["LEG_V", "40"], ["WIDTH", "50"], ["T", "5"], ["FILLET_IN", "3"]].map(([a, b]) => (
            <div key={a} className="flex justify-between font-mono text-[10px]"><span className="text-muted">{a}</span><span>{b}</span></div>
          ))}
        </div>
      </div>
    </div>
  );
}
