import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Ellipsis, Lock } from "lucide-react";
import { cx } from "@/lib/format";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger, Tip } from "@/components/ui";

/** One ribbon command (SOLIDWORKS CommandManager button). Shared by the Design Studio and the Assembly Studio. */
export interface RibbonBtn {
  id: string; label: string; icon: ReactNode; tip: string; onClick?: () => void; active?: boolean; disabled?: boolean;
  /** a flyout (SOLIDWORKS-style): the button opens a short menu */
  menu?: { label: string; onSelect: () => void; on?: boolean }[];
  /** output state (Make tab) and add-on lock */
  status?: { text: string; tone: "ok" | "warn" | "muted" }; locked?: boolean;
  /** stable id the in-app copilot points at (data-copilot) */
  copilot?: string;
  /** extra attributes on the button (data-testid, data-make, ...) */
  attrs?: Record<string, string>;
}

export type RibbonSize = "full" | "mid" | "icon";
const WIDTH: Record<RibbonSize, number> = { full: 76, mid: 62, icon: 42 };
const SEP = 13, MORE = 46;

function stored(key: string, fallback: string): string { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } }
function store(key: string, v: string) { try { localStorage.setItem(key, v); } catch { /* private mode */ } }

/** The command bar: a title row with tabs, then one row of grouped commands. It never hides a command (STU-09):
 * the buttons shrink first, then what still doesn't fit goes into "More". On phones/tablets (`touch`) the title row
 * and the tabs sit on separate rows and the commands scroll sideways. */
export function Ribbon<T extends string>({ tabs, groups, storageKey, left, right, touch = false, wide = [], tabAttrs, onSize, tour }: {
  tabs: readonly T[]; groups: Record<T, RibbonBtn[][]>;
  /** localStorage prefix for the open tab and the collapsed state */
  storageKey: string;
  left?: ReactNode; right?: ReactNode; touch?: boolean;
  /** tabs whose buttons are wide, labelled even at icon size, and may show a status line (Make) */
  wide?: readonly T[];
  tabAttrs?: (t: T) => { tour?: string; dot?: string; copilot?: string } | undefined;
  onSize?: (s: RibbonSize) => void;
  tour?: string;
}) {
  const [collapsed, setCollapsed] = useState(() => stored(`${storageKey}_collapsed`, "0") === "1");
  const toggle = () => setCollapsed(c => { store(`${storageKey}_collapsed`, c ? "0" : "1"); return !c; });
  const [tabRaw, setTab] = useState<T>(() => stored(`${storageKey}_tab`, tabs[0] ?? "") as T);
  const tab = tabs.includes(tabRaw) ? tabRaw : tabs[0]!;
  const pick = (t: T) => { setTab(t); store(`${storageKey}_tab`, t); };
  const shown = groups[tab] ?? [];
  const isWide = wide.includes(tab);

  const row = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(2000);
  useLayoutEffect(() => {
    const el = row.current; if (!el) return;
    const ro = new ResizeObserver(() => setAvail(el.clientWidth - 16)); ro.observe(el); setAvail(el.clientWidth - 16);
    return () => ro.disconnect();
  }, [collapsed]);
  const { size, visible, overflow } = fitRibbon(shown, avail, touch);
  const onSizeRef = useRef(onSize);
  onSizeRef.current = onSize;
  useEffect(() => { onSizeRef.current?.(size); }, [size]);

  const run = (b: RibbonBtn) => b.onClick?.();
  const face = (b: RibbonBtn) => (
    <>{b.locked && <Lock className="absolute right-1 top-1 h-3 w-3 text-muted" aria-label="Add-on" />}
      <span className={b.locked ? "text-muted" : "text-primary"}>{b.icon}</span>{(size !== "icon" || isWide) && <span className={cx("text-center", isWide && "whitespace-nowrap")}>{b.label}</span>}
      {b.menu && size !== "icon" && <ChevronDown className="-mt-0.5 h-3 w-3 text-muted" />}
      {b.status && <span className={cx("max-w-full truncate text-[9.5px] leading-none", b.status.tone === "warn" ? "font-semibold text-warning" : b.status.tone === "ok" ? "text-success" : "text-muted")}>{b.status.text}</span>}</>
  );
  const btnCls = (b: RibbonBtn) => cx("relative flex flex-col items-center justify-center gap-1 rounded px-1 leading-tight transition disabled:opacity-35",
    isWide ? "min-w-[88px] max-w-[150px] px-2.5 text-[10.5px]" : size === "full" ? "w-[76px] text-[10.5px]" : size === "mid" ? "w-[62px] text-[9.5px]" : "w-[42px]",
    b.active ? "bg-primary-soft text-primary ring-1 ring-primary/40" : "text-text hover:bg-primary-soft hover:text-primary");
  const tipOf = (b: RibbonBtn) => (size === "icon" && !isWide ? `${b.label}: ${b.tip}` : b.tip);
  const attrs = (b: RibbonBtn) => ({ ...(b.copilot ? { "data-copilot": b.copilot } : {}), ...b.attrs });

  const tabButtons = tabs.map(t => {
    const a = tabAttrs?.(t);
    return (
      <button key={t} onClick={() => { pick(t); if (collapsed) toggle(); }} data-tour={a?.tour} data-copilot={a?.copilot} data-ribbon-tab={t}
        className={cx("shrink-0 rounded-t px-3 py-1 text-[12px]", tab === t && !collapsed ? "border border-b-0 border-border bg-panel font-semibold text-text" : "text-muted hover:text-text")}>{t}
        {a?.dot && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-warning align-middle" title={a.dot} />}</button>);
  });
  const rightSide = (
    <div className="ml-auto flex shrink-0 items-center gap-1 self-center">
      {right}
      <Tip content={collapsed ? "Show command bar" : "Hide command bar"} side="bottom">
        <button onClick={toggle} className={cx("rounded text-muted hover:bg-text/5 hover:text-text", touch ? "p-2" : "p-1")} aria-label="Toggle command bar">
          {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}</button>
      </Tip>
    </div>);

  return (
    <div className="shrink-0 border-b border-border bg-panel" data-tour={tour} data-touch={touch || undefined}>
      {touch ? (<>
        <div className="flex h-11 items-center gap-1 border-b border-border bg-panel2 px-2">
          {left && <div className="flex min-w-0 flex-1 items-center gap-1.5">{left}</div>}
          {rightSide}
        </div>
        {!collapsed && <div className="fw-hscroll flex h-9 items-end gap-0.5 border-b border-border bg-panel2 px-2">{tabButtons}</div>}
      </>) : (
      <div className="flex h-9 items-end gap-0.5 border-b border-border bg-panel2 px-2">
        {left && <div className="mr-2 flex min-w-0 shrink items-center gap-1.5 self-center">{left}</div>}
        {tabButtons}
        {rightSide}
      </div>)}
      {!collapsed && <div ref={row} className={cx("flex items-stretch gap-1 px-2 py-1", touch ? "fw-hscroll snap-x" : "overflow-hidden", size === "icon" ? "h-[46px]" : "h-[66px]")} data-ribbon-size={size}>
        {visible.map((g, gi) => (
          <div key={gi} className={cx("flex shrink-0 items-stretch gap-0.5", touch && "snap-start")}>
            {gi > 0 && <span className="mx-1.5 my-1 w-px bg-border" />}
            {g.map(b => b.menu ? (
              <Menu key={b.id}>
                <Tip content={tipOf(b)} side="bottom"><MenuTrigger asChild><button disabled={b.disabled} className={btnCls(b)} aria-label={b.label} {...attrs(b)}>{face(b)}</button></MenuTrigger></Tip>
                <MenuContent align="start"><MenuLabel>{b.label}</MenuLabel>
                  {b.menu.map(m => <MenuItem key={m.label} onSelect={m.onSelect}>{m.label}{m.on && <span className="ml-auto text-primary">●</span>}</MenuItem>)}</MenuContent>
              </Menu>
            ) : (
              <Tip key={b.id} content={tipOf(b)} side="bottom">
                <button disabled={b.disabled} onClick={() => run(b)} className={btnCls(b)} aria-label={b.label} {...attrs(b)}>{face(b)}</button>
              </Tip>))}
          </div>))}
        {overflow.length > 0 && <Menu>
          <MenuTrigger asChild><button className="ml-1 flex w-[46px] flex-col items-center justify-center gap-0.5 rounded text-[10px] text-muted hover:bg-primary-soft hover:text-primary" aria-label="More commands" data-ribbon-more>
            <Ellipsis className="h-5 w-5" />More</button></MenuTrigger>
          <MenuContent align="end"><MenuLabel>More commands</MenuLabel>
            {overflow.flatMap(b => b.menu ? b.menu.map(m => <MenuItem key={`${b.id}-${m.label}`} onSelect={m.onSelect}>{b.label}: {m.label}</MenuItem>)
              : b.disabled ? [<div key={b.id} className="px-2.5 py-1.5 text-sm text-muted/60">{b.label}</div>]
              : [<MenuItem key={b.id} icon={b.icon} onSelect={() => run(b)}>{b.label}</MenuItem>])}
          </MenuContent>
        </Menu>}
      </div>}
    </div>
  );
}

/** Which size the buttons take and which commands fold into "More" for the available width (pure; tested). */
export function fitRibbon(shown: RibbonBtn[][], avail: number, touch: boolean): { size: RibbonSize; visible: RibbonBtn[][]; overflow: RibbonBtn[] } {
  const count = shown.reduce((n, g) => n + g.length, 0);
  const need = (s: RibbonSize) => count * (WIDTH[s] + 2) + Math.max(0, shown.length - 1) * SEP;
  const size: RibbonSize = need("full") <= avail ? "full" : need("mid") <= avail || touch ? "mid" : "icon";
  const fits = need(size) <= avail || touch ? count : Math.max(1, Math.floor((avail - MORE - (shown.length - 1) * SEP) / (WIDTH.icon + 2)));
  let k = 0;
  const visible = shown.map(g => g.filter(() => k++ < fits)).filter(g => g.length);
  return { size, visible, overflow: shown.flat().slice(fits) };
}
