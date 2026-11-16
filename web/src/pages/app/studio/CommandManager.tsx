import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, ChevronDown, ChevronUp, Circle, CircleDotDashed, Cone, Cuboid, Diamond, Drill, Fence, FlipHorizontal2,
  Focus, GitCompare, Grid3x3, Layers2, Maximize, MousePointer2, PackageOpen, PenLine, Pyramid, RectangleHorizontal, RefreshCcwDot, Rotate3d,
  RotateCw, Route, Ruler, Scale, Scissors, ShieldCheck, ScanSearch, Spline, SquareDashed, Squircle, Triangle, Upload, Wrench, Hexagon, Ellipsis,
} from "lucide-react";
import { cx } from "@/lib/format";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger, Tip } from "@/components/ui";
import type { ViewerApi } from "@/components/Viewer3D";
import type { DisplayMode, ViewName } from "@/viewer/types";

export type Command =
  | { kind: "feature"; op: "extrude" | "hole" | "fillet" | "chamfer" | "shell" | "mirror" | "pattern" | "plane" | "draft" | "sweep" | "loft"; preset?: Record<string, unknown> }
  | { kind: "sketch"; preset?: { feature?: "extrude" | "revolve" | "rib" | "sketch"; mode?: "add" | "cut" } }
  | { kind: "tool"; tool: "measure" | "select" }
  | { kind: "panel"; tab: string; extra?: "com" }
  | { kind: "import" } | { kind: "toolbox" } | { kind: "similar" } | { kind: "normal" };

interface Btn {
  id: string; label: string; icon: ReactNode; tip: string; cmd?: Command; onClick?: () => void; active?: boolean; disabled?: boolean; needsBody?: boolean;
  /** a flyout (SOLIDWORKS-style): the button opens a short menu */
  menu?: { label: string; onSelect: () => void; on?: boolean }[]; key?: string;
}

const TABS = ["Features", "Sketch", "Evaluate", "View", "Library", "Make"] as const;
type Size = "full" | "mid" | "icon";
const WIDTH: Record<Size, number> = { full: 76, mid: 62, icon: 42 };
const SEP = 13, MORE = 46;

/** Downstream modules shown on the Make tab (only the Live ones are passed in). */
export interface MakeModule { code: string; name: string; icon: ReactNode; tip: string }

export default function CommandManager({ onCommand, viewerRef, disabled, activeTool, left, right, make = [], onMake, library = [], canNormal = false }: {
  onCommand: (c: Command) => void; viewerRef: { current: ViewerApi | null }; disabled: boolean; activeTool: string;
  left?: ReactNode; right?: ReactNode; make?: MakeModule[]; onMake?: (code: string) => void; library?: MakeModule[];
  /** a planar face is selected (enables Normal To) */
  canNormal?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("fw_cm_collapsed") === "1"; } catch { return false; } });
  const toggle = () => setCollapsed(c => { try { localStorage.setItem("fw_cm_collapsed", c ? "0" : "1"); } catch { /* */ } return !c; });
  const [, setTick] = useState(0);
  const viewer = viewerRef.current;
  const [tab, setTab] = useState<(typeof TABS)[number]>(() => { try { return (localStorage.getItem("fw_cm_tab") as (typeof TABS)[number]) || "Features"; } catch { return "Features"; } });
  const pick = (t: (typeof TABS)[number]) => { setTab(t); try { localStorage.setItem("fw_cm_tab", t); } catch { /* */ } };
  const views: ViewName[] = ["Iso", "Front", "Top", "Right", "Back", "Left", "Bottom"];
  const displays: [DisplayMode, string][] = [["shaded-edges", "Shaded with edges"], ["shaded", "Shaded"], ["hidden", "Hidden lines visible"], ["wireframe", "Wireframe"]];

  const groups: Record<(typeof TABS)[number], Btn[][]> = {
    Features: [[
      { id: "boss", label: "Extruded Boss/Base", icon: <ArrowUpFromLine className="h-5 w-5" />, tip: "Sketch on a plane or planar face, then extrude to add material", cmd: { kind: "sketch", preset: { feature: "extrude", mode: "add" } } },
      { id: "revolve", label: "Revolved Boss/Base", icon: <RotateCw className="h-5 w-5" />, tip: "Sketch a profile and a centerline, then revolve it", cmd: { kind: "sketch", preset: { feature: "revolve", mode: "add" } } },
      { id: "sweep", label: "Swept Boss/Base", icon: <Spline className="h-5 w-5" />, tip: "Sweep a closed profile sketch along a path sketch", cmd: { kind: "feature", op: "sweep", preset: { mode: "add" } } },
      { id: "loft", label: "Lofted Boss/Base", icon: <Cone className="h-5 w-5" />, tip: "Blend between two or more closed profile sketches", cmd: { kind: "feature", op: "loft", preset: { mode: "add" } } },
    ], [
      { id: "cut", label: "Extruded Cut", icon: <ArrowDownToLine className="h-5 w-5" />, tip: "Sketch, then cut: blind, mid plane or through all", cmd: { kind: "sketch", preset: { feature: "extrude", mode: "cut" } }, needsBody: true },
      { id: "hole", label: "Hole Wizard", icon: <Drill className="h-5 w-5" />, tip: "Clearance, tapped, counterbored or countersunk holes for ISO fasteners, placed by distance from the face edges", cmd: { kind: "feature", op: "hole" }, needsBody: true },
      { id: "revcut", label: "Revolved Cut", icon: <RefreshCcwDot className="h-5 w-5" />, tip: "Sketch a profile and a centerline, then revolve it to remove material (grooves)", cmd: { kind: "sketch", preset: { feature: "revolve", mode: "cut" } }, needsBody: true },
      { id: "sweepcut", label: "Swept Cut", icon: <Route className="h-5 w-5" />, tip: "Remove material by sweeping a profile along a path", cmd: { kind: "feature", op: "sweep", preset: { mode: "cut" } }, needsBody: true },
      { id: "loftcut", label: "Lofted Cut", icon: <Pyramid className="h-5 w-5" />, tip: "Remove material lofted between profile sketches", cmd: { kind: "feature", op: "loft", preset: { mode: "cut" } }, needsBody: true },
    ], [
      { id: "fillet", label: "Fillet", icon: <Squircle className="h-5 w-5" />, tip: "Round selected edges", cmd: { kind: "feature", op: "fillet" }, needsBody: true },
      { id: "chamfer", label: "Chamfer", icon: <Diamond className="h-5 w-5" />, tip: "Bevel selected edges", cmd: { kind: "feature", op: "chamfer" }, needsBody: true },
      { id: "shell", label: "Shell", icon: <PackageOpen className="h-5 w-5" />, tip: "Hollow the part, removing the selected faces", cmd: { kind: "feature", op: "shell" }, needsBody: true },
      { id: "draft", label: "Draft", icon: <Triangle className="h-5 w-5" />, tip: "Taper faces by an angle about a neutral plane (moulding/casting release)", cmd: { kind: "feature", op: "draft" }, needsBody: true },
      { id: "rib", label: "Rib", icon: <Fence className="h-5 w-5" />, tip: "Sketch an open line between walls, then thicken it into a rib", cmd: { kind: "sketch", preset: { feature: "rib" } }, needsBody: true },
    ], [
      { id: "linpat", label: "Linear Pattern", icon: <Grid3x3 className="h-5 w-5" />, tip: "Repeat bosses, cuts, revolves or holes along a direction", cmd: { kind: "feature", op: "pattern", preset: { kind: "linear" } }, needsBody: true },
      { id: "cirpat", label: "Circular Pattern", icon: <CircleDotDashed className="h-5 w-5" />, tip: "Repeat bosses, cuts, revolves or holes around an axis", cmd: { kind: "feature", op: "pattern", preset: { kind: "circular" } }, needsBody: true },
      { id: "mirror", label: "Mirror", icon: <FlipHorizontal2 className="h-5 w-5" />, tip: "Mirror selected features, or the whole body, about a plane or face", cmd: { kind: "feature", op: "mirror" }, needsBody: true },
      { id: "plane", label: "Reference Plane", icon: <Layers2 className="h-5 w-5" />, tip: "A plane offset from Front/Top/Right or a face, optionally at an angle, to sketch on", cmd: { kind: "feature", op: "plane" } },
    ]],
    Sketch: [[
      { id: "sketch", label: "Sketch", icon: <PenLine className="h-5 w-5" />, tip: "A 2D sketch on a plane or planar face: lines, arcs, circles, slots, polygons, trims, offsets, smart dimensions and relations. Kept in the tree; turn it into a feature on exit", cmd: { kind: "sketch", preset: { feature: "sketch" } } },
    ], [
      { id: "rect", label: "Quick Rectangle", icon: <RectangleHorizontal className="h-5 w-5" />, tip: "Quick rectangle boss/cut on a picked face", cmd: { kind: "feature", op: "extrude", preset: { kind: "rect" } }, needsBody: true },
      { id: "circ", label: "Quick Circle", icon: <Circle className="h-5 w-5" />, tip: "Quick circular boss/cut on a picked face", cmd: { kind: "feature", op: "extrude", preset: { kind: "circle" } }, needsBody: true },
    ]],
    Evaluate: [[
      { id: "measure", label: "Measure", icon: <Ruler className="h-5 w-5" />, tip: "Snap measurement (Esc clears)", cmd: { kind: "tool", tool: "measure" }, active: activeTool === "measure" },
      { id: "select", label: "Select", icon: <MousePointer2 className="h-5 w-5" />, tip: "Select faces and edges for the agent", cmd: { kind: "tool", tool: "select" }, active: activeTool === "select" },
    ], [
      { id: "mass", label: "Mass Properties", icon: <Scale className="h-5 w-5" />, tip: "Mass, centre of mass, inertia", cmd: { kind: "panel", tab: "mass", extra: "com" } },
      { id: "section", label: "Section View", icon: <Scissors className="h-5 w-5" />, tip: "Cut through the part", onClick: () => viewer?.toggleSection(), active: viewer?.section },
      { id: "checks", label: "Checks", icon: <ShieldCheck className="h-5 w-5" />, tip: "Geometry verification results", cmd: { kind: "panel", tab: "checks" } },
      { id: "compare", label: "Compare", icon: <GitCompare className="h-5 w-5" />, tip: "Compare revisions", cmd: { kind: "panel", tab: "revs" } },
    ]],
    View: [[
      { id: "fit", label: "Zoom to Fit", icon: <Maximize className="h-5 w-5" />, tip: "Fit the model in the window, keeping the orientation (F)", onClick: () => viewer?.zoomToFit() },
      { id: "normal", label: "Normal To", icon: <Focus className="h-5 w-5" />, tip: canNormal ? "Look straight at the selected face" : "Select a flat face first (Select tool), then look straight at it", cmd: { kind: "normal" }, disabled: !canNormal },
      { id: "orient", label: "View Orientation", icon: <Rotate3d className="h-5 w-5" />, tip: "Standard views (Ctrl+1–7)", menu: views.map((v, i) => ({ label: `${v}  · Ctrl+${i + 1}`, onSelect: () => viewer?.setView(v) })) },
    ], [
      { id: "display", label: "Display Style", icon: <Cuboid className="h-5 w-5" />, tip: "Shaded, edges, hidden lines, wireframe", menu: displays.map(([m, l]) => ({ label: l, on: viewer?.display === m, onSelect: () => viewer?.setDisplay(m) })) },
      { id: "ortho", label: viewer?.ortho ? "Perspective" : "Orthographic", icon: viewer?.ortho ? <Hexagon className="h-5 w-5" /> : <SquareDashed className="h-5 w-5" />, tip: viewer?.ortho ? "Switch to a perspective view" : "Switch back to the orthographic (CAD) view", onClick: () => viewer?.setOrtho(!viewer.ortho) },
    ]],
    Library: [[
      { id: "toolbox", label: "Toolbox", icon: <Wrench className="h-5 w-5" />, tip: "Standard components (fasteners, bearings, gears…) from repeatable generators", cmd: { kind: "toolbox" } },
      { id: "similar", label: "Similar Parts", icon: <ScanSearch className="h-5 w-5" />, tip: "Find parts you already made that look like this one: same envelope, proportions and holes", cmd: { kind: "similar" }, needsBody: true },
      { id: "import", label: "Import STEP", icon: <Upload className="h-5 w-5" />, tip: "Import a STEP file, recognise its features and rebuild it as a parametric model", cmd: { kind: "import" } },
    ], ...(library.length ? [library.map(m => ({ id: m.code, label: m.name, icon: m.icon, tip: m.tip, onClick: () => onMake?.(m.code) })) as Btn[]] : [])],
    Make: [make.map(m => ({ id: m.code, label: m.name, icon: m.icon, tip: m.tip, onClick: () => onMake?.(m.code), disabled })) as Btn[]],
  };
  const shown = groups[tab === "Make" && !make.length ? "Features" : tab];

  // Never hide a command (STU-09): shrink the buttons first, then move what still doesn't fit into "More".
  const row = useRef<HTMLDivElement>(null);
  const [avail, setAvail] = useState(2000);
  useLayoutEffect(() => {
    const el = row.current; if (!el) return;
    const ro = new ResizeObserver(() => setAvail(el.clientWidth - 16)); ro.observe(el); setAvail(el.clientWidth - 16);
    return () => ro.disconnect();
  }, [collapsed]);
  const count = shown.reduce((n, g) => n + g.length, 0);
  const need = (s: Size) => count * (WIDTH[s] + 2) + (shown.length - 1) * SEP;
  const size: Size = need("full") <= avail ? "full" : need("mid") <= avail ? "mid" : "icon";
  const fits = need(size) <= avail ? count : Math.max(1, Math.floor((avail - MORE - (shown.length - 1) * SEP) / (WIDTH.icon + 2)));
  let k = 0;
  const visible = shown.map(g => g.filter(() => k++ < fits)).filter(g => g.length);
  const overflow = shown.flat().slice(fits);
  useEffect(() => { setTick(t => t + 1); }, [size]);

  const run = (b: Btn) => { if (b.onClick) { b.onClick(); setTimeout(() => setTick(t => t + 1), 0); } else if (b.cmd) onCommand(b.cmd); };
  const isDisabled = (b: Btn) => b.disabled || (disabled && !!b.needsBody);
  const face = (b: Btn) => (
    <><span className="text-primary">{b.icon}</span>{size !== "icon" && <span className="text-center">{b.label}</span>}
      {b.menu && size !== "icon" && <ChevronDown className="-mt-0.5 h-3 w-3 text-muted" />}</>
  );
  const btnCls = (b: Btn) => cx("flex flex-col items-center justify-center gap-1 rounded px-1 leading-tight transition disabled:opacity-35",
    size === "full" ? "w-[76px] text-[10.5px]" : size === "mid" ? "w-[62px] text-[9.5px]" : "w-[42px]",
    b.active ? "bg-primary-soft text-primary ring-1 ring-primary/40" : "text-text hover:bg-primary-soft hover:text-primary");
  const tipOf = (b: Btn) => (isDisabled(b) && b.needsBody ? "Needs a solid first: start with Extruded or Revolved Boss, ask the agent, use the Toolbox or import a STEP"
    : size === "icon" ? `${b.label}: ${b.tip}` : b.tip);

  return (
    <div className="shrink-0 border-b border-border bg-panel" data-tour="command-manager">
      <div className="flex h-9 items-end gap-0.5 border-b border-border bg-panel2 px-2">
        {left && <div className="mr-2 flex min-w-0 shrink items-center gap-1.5 self-center">{left}</div>}
        {TABS.filter(t => t !== "Make" || make.length > 0).map(t => (
          <button key={t} onClick={() => { pick(t); if (collapsed) toggle(); }}
            className={cx("shrink-0 rounded-t px-3 py-1 text-[12px]", tab === t && !collapsed ? "border border-b-0 border-border bg-panel font-semibold text-text" : "text-muted hover:text-text")}>{t}</button>))}
        <div className="ml-auto flex shrink-0 items-center gap-1 self-center">
          {right}
          <Tip content={collapsed ? "Show command bar" : "Hide command bar"} side="bottom">
            <button onClick={toggle} className="rounded p-1 text-muted hover:bg-text/5 hover:text-text" aria-label="Toggle command bar">
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}</button>
          </Tip>
        </div>
      </div>
      {!collapsed && <div ref={row} className={cx("flex items-stretch gap-1 overflow-hidden px-2 py-1", size === "icon" ? "h-[46px]" : "h-[66px]")} data-ribbon-size={size}>
        {visible.map((g, gi) => (
          <div key={gi} className="flex items-stretch gap-0.5">
            {gi > 0 && <span className="mx-1.5 my-1 w-px bg-border" />}
            {g.map(b => b.menu ? (
              <Menu key={b.id}>
                <Tip content={b.tip} side="bottom"><MenuTrigger asChild><button disabled={isDisabled(b)} className={btnCls(b)} aria-label={b.label}>{face(b)}</button></MenuTrigger></Tip>
                <MenuContent align="start"><MenuLabel>{b.label}</MenuLabel>
                  {b.menu.map(m => <MenuItem key={m.label} onSelect={() => { m.onSelect(); setTimeout(() => setTick(t => t + 1), 0); }}>{m.label}{m.on && <span className="ml-auto text-primary">●</span>}</MenuItem>)}</MenuContent>
              </Menu>
            ) : (
              <Tip key={b.id} content={tipOf(b)} side="bottom">
                <button disabled={isDisabled(b)} onClick={() => run(b)} className={btnCls(b)} aria-label={b.label}>{face(b)}</button>
              </Tip>))}
          </div>))}
        {overflow.length > 0 && <Menu>
          <MenuTrigger asChild><button className="ml-1 flex w-[46px] flex-col items-center justify-center gap-0.5 rounded text-[10px] text-muted hover:bg-primary-soft hover:text-primary" aria-label="More commands" data-ribbon-more>
            <Ellipsis className="h-5 w-5" />More</button></MenuTrigger>
          <MenuContent align="end"><MenuLabel>More commands</MenuLabel>
            {overflow.flatMap(b => b.menu ? b.menu.map(m => <MenuItem key={`${b.id}-${m.label}`} onSelect={m.onSelect}>{b.label}: {m.label}</MenuItem>)
              : isDisabled(b) ? [<div key={b.id} className="px-2.5 py-1.5 text-sm text-muted/60">{b.label}</div>]
              : [<MenuItem key={b.id} icon={b.icon} onSelect={() => run(b)}>{b.label}</MenuItem>])}
          </MenuContent>
        </Menu>}
      </div>}
    </div>
  );
}

