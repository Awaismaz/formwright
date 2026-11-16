import { useState, type ReactNode } from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, Box, ChevronDown, ChevronUp, Circle, CircleDot, Diamond, Eye, FlipHorizontal2, GitCompare, Grid3x3,
  Cone, Fence, Layers2, Lock, Maximize, MousePointer2, Package, PenLine, RectangleHorizontal, RefreshCcwDot, RotateCw, Ruler, Scale, Scissors, ShieldCheck,
  ScanSearch, Squircle, Triangle, Upload, Waypoints, Wrench,
} from "lucide-react";
import { cx } from "@/lib/format";
import { Tip } from "@/components/ui";
import type { ViewerApi } from "@/components/Viewer3D";
import type { DisplayMode, ViewName } from "@/viewer/types";

export type Command =
  | { kind: "feature"; op: "extrude" | "hole" | "fillet" | "chamfer" | "shell" | "mirror" | "pattern" | "plane" | "draft" | "sweep" | "loft"; preset?: Record<string, unknown> }
  | { kind: "sketch"; preset?: { feature?: "extrude" | "revolve" | "rib" | "sketch"; mode?: "add" | "cut" } }
  | { kind: "tool"; tool: "measure" | "select" }
  | { kind: "panel"; tab: string; extra?: "com" }
  | { kind: "import" } | { kind: "toolbox" } | { kind: "similar" };

interface Btn { id: string; label: string; icon: ReactNode; tip: string; cmd?: Command; onClick?: () => void; active?: boolean; disabled?: boolean; needsBody?: boolean; status?: MakeModule["status"]; locked?: boolean }

const TABS = ["Features", "Sketch", "Evaluate", "View", "Library", "Make"] as const;

/** Downstream modules shown on the Make tab (only the Live ones are passed in). */
export interface MakeModule {
  code: string; name: string; icon: ReactNode; tip: string;
  /** One-line state of this module's output for the current part (Make tab), e.g. "Rev A" or "Model changed · update". */
  status?: { text: string; tone: "ok" | "warn" | "muted" };
  /** Not in the workspace's plan: shown with a lock, opens the add-on page. */
  locked?: boolean;
}

export default function CommandManager({ onCommand, viewerRef, disabled, activeTool, left, right, make = [], onMake, library = [] }: {
  onCommand: (c: Command) => void; viewerRef: { current: ViewerApi | null }; disabled: boolean; activeTool: string;
  left?: ReactNode; right?: ReactNode; make?: MakeModule[]; onMake?: (code: string) => void; library?: MakeModule[];
}) {
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("fw_cm_collapsed") === "1"; } catch { return false; } });
  const toggle = () => setCollapsed(c => { try { localStorage.setItem("fw_cm_collapsed", c ? "0" : "1"); } catch { /* */ } return !c; });
  const [, setTick] = useState(0);
  const viewer = viewerRef.current;
  const [tab, setTab] = useState<(typeof TABS)[number]>(() => { try { return (localStorage.getItem("fw_cm_tab") as (typeof TABS)[number]) || "Features"; } catch { return "Features"; } });
  const pick = (t: (typeof TABS)[number]) => { setTab(t); try { localStorage.setItem("fw_cm_tab", t); } catch { /* */ } };
  const views: ViewName[] = ["Iso", "Front", "Top", "Right", "Back", "Left", "Bottom"];
  const displays: [DisplayMode, string, ReactNode][] = [["shaded-edges", "Shaded + edges", <Box className="h-5 w-5" />], ["shaded", "Shaded", <Package className="h-5 w-5" />],
    ["hidden", "Hidden lines", <Grid3x3 className="h-5 w-5" />], ["wireframe", "Wireframe", <Diamond className="h-5 w-5" />]];

  const groups: Record<(typeof TABS)[number], Btn[][]> = {
    Features: [[
      { id: "boss", label: "Extruded Boss/Base", icon: <ArrowUpFromLine className="h-5 w-5" />, tip: "Sketch on a plane or planar face, then extrude to add material", cmd: { kind: "sketch", preset: { feature: "extrude", mode: "add" } } },
      { id: "revolve", label: "Revolved Boss/Base", icon: <RotateCw className="h-5 w-5" />, tip: "Sketch a profile and a centerline, then revolve it", cmd: { kind: "sketch", preset: { feature: "revolve", mode: "add" } } },
      { id: "cut", label: "Extruded Cut", icon: <ArrowDownToLine className="h-5 w-5" />, tip: "Sketch, then cut: blind, mid plane or through all", cmd: { kind: "sketch", preset: { feature: "extrude", mode: "cut" } }, needsBody: true },
      { id: "revcut", label: "Revolved Cut", icon: <RefreshCcwDot className="h-5 w-5" />, tip: "Sketch a profile and a centerline, then revolve it to remove material (grooves)", cmd: { kind: "sketch", preset: { feature: "revolve", mode: "cut" } }, needsBody: true },
      { id: "sweep", label: "Swept Boss/Base", icon: <Waypoints className="h-5 w-5" />, tip: "Sweep a closed profile sketch along a path sketch", cmd: { kind: "feature", op: "sweep", preset: { mode: "add" } } },
      { id: "loft", label: "Lofted Boss/Base", icon: <Cone className="h-5 w-5" />, tip: "Blend between two or more closed profile sketches", cmd: { kind: "feature", op: "loft", preset: { mode: "add" } } },
      { id: "sweepcut", label: "Swept Cut", icon: <Waypoints className="h-5 w-5" />, tip: "Remove material by sweeping a profile along a path", cmd: { kind: "feature", op: "sweep", preset: { mode: "cut" } }, needsBody: true },
      { id: "loftcut", label: "Lofted Cut", icon: <Cone className="h-5 w-5" />, tip: "Remove material lofted between profile sketches", cmd: { kind: "feature", op: "loft", preset: { mode: "cut" } }, needsBody: true },
      { id: "hole", label: "Hole", icon: <CircleDot className="h-5 w-5" />, tip: "Simple, blind or through hole on a planar face (optionally patterned)", cmd: { kind: "feature", op: "hole" }, needsBody: true },
    ], [
      { id: "fillet", label: "Fillet", icon: <Squircle className="h-5 w-5" />, tip: "Round selected edges", cmd: { kind: "feature", op: "fillet" }, needsBody: true },
      { id: "chamfer", label: "Chamfer", icon: <Diamond className="h-5 w-5" />, tip: "Bevel selected edges", cmd: { kind: "feature", op: "chamfer" }, needsBody: true },
      { id: "shell", label: "Shell", icon: <Package className="h-5 w-5" />, tip: "Hollow the part, removing the selected faces", cmd: { kind: "feature", op: "shell" }, needsBody: true },
      { id: "draft", label: "Draft", icon: <Triangle className="h-5 w-5" />, tip: "Taper faces by an angle about a neutral plane (moulding/casting release)", cmd: { kind: "feature", op: "draft" }, needsBody: true },
      { id: "rib", label: "Rib", icon: <Fence className="h-5 w-5" />, tip: "Sketch an open line between walls, then thicken it into a rib", cmd: { kind: "sketch", preset: { feature: "rib" } }, needsBody: true },
    ], [
      { id: "linpat", label: "Linear Pattern", icon: <Grid3x3 className="h-5 w-5" />, tip: "Repeat bosses, cuts, revolves or holes along a direction", cmd: { kind: "feature", op: "pattern", preset: { kind: "linear" } }, needsBody: true },
      { id: "cirpat", label: "Circular Pattern", icon: <RotateCw className="h-5 w-5" />, tip: "Repeat bosses, cuts, revolves or holes around an axis", cmd: { kind: "feature", op: "pattern", preset: { kind: "circular" } }, needsBody: true },
      { id: "mirror", label: "Mirror", icon: <FlipHorizontal2 className="h-5 w-5" />, tip: "Mirror selected features, or the whole body, about a plane or face", cmd: { kind: "feature", op: "mirror" }, needsBody: true },
    ], [
      { id: "plane", label: "Reference Plane", icon: <Layers2 className="h-5 w-5" />, tip: "A plane offset from Front/Top/Right or a face, optionally at an angle, to sketch on", cmd: { kind: "feature", op: "plane" } },
    ]],
    Sketch: [[
      { id: "sketch", label: "Sketch", icon: <PenLine className="h-5 w-5" />, tip: "A 2D sketch on a plane or planar face, kept in the tree (profiles and paths for sweeps and lofts); you can still turn it into a feature on exit", cmd: { kind: "sketch", preset: { feature: "sketch" } } },
    ], [
      { id: "rect", label: "Quick Rectangle", icon: <RectangleHorizontal className="h-5 w-5" />, tip: "Quick rectangle boss/cut on a picked face", cmd: { kind: "feature", op: "extrude", preset: { kind: "rect" } }, needsBody: true },
      { id: "circ", label: "Quick Circle", icon: <Circle className="h-5 w-5" />, tip: "Quick circular boss/cut on a picked face", cmd: { kind: "feature", op: "extrude", preset: { kind: "circle" } }, needsBody: true },
    ]],
    Evaluate: [[
      { id: "measure", label: "Measure", icon: <Ruler className="h-5 w-5" />, tip: "Snap measurement", cmd: { kind: "tool", tool: "measure" }, active: activeTool === "measure" },
      { id: "select", label: "Select", icon: <MousePointer2 className="h-5 w-5" />, tip: "Select faces and edges for the agent", cmd: { kind: "tool", tool: "select" }, active: activeTool === "select" },
    ], [
      { id: "mass", label: "Mass Properties", icon: <Scale className="h-5 w-5" />, tip: "Mass, centre of mass, inertia", cmd: { kind: "panel", tab: "mass", extra: "com" } },
      { id: "section", label: "Section View", icon: <Scissors className="h-5 w-5" />, tip: "Cut through the part", onClick: () => viewer?.toggleSection(), active: viewer?.section },
      { id: "checks", label: "Checks", icon: <ShieldCheck className="h-5 w-5" />, tip: "Geometry verification results", cmd: { kind: "panel", tab: "checks" } },
      { id: "compare", label: "Compare", icon: <GitCompare className="h-5 w-5" />, tip: "Compare revisions", cmd: { kind: "panel", tab: "revs" } },
    ]],
    View: [
      views.map(v => ({ id: v, label: v, icon: <Eye className="h-5 w-5" />, tip: `${v} view`, onClick: () => viewer?.setView(v) })),
      [{ id: "fit", label: "Zoom to Fit", icon: <Maximize className="h-5 w-5" />, tip: "Fit the model in the window", onClick: () => viewer?.setView("Iso") },
       { id: "ortho", label: viewer?.ortho ? "Orthographic" : "Perspective", icon: <Box className="h-5 w-5" />, tip: "Toggle orthographic / perspective", onClick: () => viewer?.setOrtho(!viewer.ortho), active: !viewer?.ortho }],
      displays.map(([m, l, i]) => ({ id: m, label: l, icon: i, tip: l, onClick: () => viewer?.setDisplay(m), active: viewer?.display === m })),
    ],
    Library: [[
      { id: "toolbox", label: "Toolbox", icon: <Wrench className="h-5 w-5" />, tip: "Standard components (fasteners, bearings, gears…) from repeatable generators", cmd: { kind: "toolbox" } },
      { id: "similar", label: "Similar Parts", icon: <ScanSearch className="h-5 w-5" />, tip: "Find parts you already made that look like this one: same envelope, proportions and holes", cmd: { kind: "similar" }, needsBody: true },
      { id: "import", label: "Import STEP", icon: <Upload className="h-5 w-5" />, tip: "Import a STEP file, recognise its features and rebuild it as a parametric model", cmd: { kind: "import" } },
    ], ...(library.length ? [library.map(m => ({ id: m.code, label: m.name, icon: m.icon, tip: m.tip, onClick: () => onMake?.(m.code) })) as Btn[]] : [])],
    Make: [make.map(m => ({ id: m.code, label: m.name, icon: m.icon, onClick: () => onMake?.(m.code), disabled: disabled && !m.locked, status: m.locked ? undefined : m.status, locked: m.locked,
      tip: m.locked ? `Add-on, not in your plan yet: ${m.tip}. Opens the add-on page.` : m.status ? `${m.tip}. Now: ${m.status.text}` : m.tip })) as Btn[]],
  };

  return (
    <div className="shrink-0 border-b border-border bg-panel" data-tour="command-manager">
      <div className="flex h-9 items-end gap-0.5 border-b border-border bg-panel2 px-2">
        {left && <div className="mr-2 flex min-w-0 shrink items-center gap-1.5 self-center">{left}</div>}
        {TABS.filter(t => t !== "Make" || make.length > 0).map(t => (
          <button key={t} onClick={() => { pick(t); if (collapsed) toggle(); }} data-tour={t === "Make" ? "make" : undefined}
            className={cx("shrink-0 rounded-t px-3 py-1 text-[12px]", tab === t && !collapsed ? "border border-b-0 border-border bg-panel font-semibold text-text" : "text-muted hover:text-text")}>{t}
            {t === "Make" && make.some(m => m.status?.tone === "warn") && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-warning align-middle" title="An output is out of date with the model" />}</button>))}
        <div className="ml-auto flex shrink-0 items-center gap-1 self-center">
          {right}
          <Tip content={collapsed ? "Show command bar" : "Hide command bar"} side="bottom">
            <button onClick={toggle} className="rounded p-1 text-muted hover:bg-text/5 hover:text-text" aria-label="Toggle command bar">
              {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}</button>
          </Tip>
        </div>
      </div>
      {!collapsed && <div className="flex h-[66px] items-stretch gap-1 overflow-x-auto px-2 py-1 [scrollbar-width:thin]">
        {groups[tab === "Make" && !make.length ? "Features" : tab].map((g, gi) => (
          <div key={gi} className="flex items-stretch gap-0.5">
            {gi > 0 && <span className="mx-1.5 my-1 w-px bg-border" />}
            {g.map(b => {
              const dis = b.disabled || (disabled && !!b.needsBody);
              return (
                <Tip key={b.id} content={dis && b.needsBody ? "Needs a solid first: start with Extruded or Revolved Boss, ask the agent, use the Toolbox or import a STEP" : b.tip} side="bottom">
                  <button disabled={dis} onClick={() => { if (b.onClick) { b.onClick(); setTimeout(() => setTick(t => t + 1), 0); } else if (b.cmd) onCommand(b.cmd); }}
                    data-make={tab === "Make" ? b.id : undefined}
                    className={cx("relative flex flex-col items-center justify-center gap-1 rounded px-1 text-[10.5px] leading-tight transition disabled:opacity-35",
                      tab === "Make" ? "min-w-[88px] max-w-[150px] px-2.5" : "w-[74px]",
                      b.active ? "bg-primary-soft text-primary ring-1 ring-primary/40" : "text-text hover:bg-primary-soft hover:text-primary")}>
                    {b.locked && <Lock className="absolute right-1 top-1 h-3 w-3 text-muted" aria-label="Add-on" />}
                    <span className={b.locked ? "text-muted" : "text-primary"}>{b.icon}</span><span className={cx("text-center", tab === "Make" && "whitespace-nowrap")}>{b.label}</span>
                    {b.status && <span className={cx("max-w-full truncate text-[9.5px] leading-none", b.status.tone === "warn" ? "font-semibold text-warning" : b.status.tone === "ok" ? "text-success" : "text-muted")}>{b.status.text}</span>}
                  </button>
                </Tip>);
            })}
          </div>))}
      </div>}
    </div>
  );
}
