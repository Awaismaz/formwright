import { useState, type ReactNode } from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, Circle, CircleDotDashed, Cone, Cuboid, Diamond, Drill, Fence, FlipHorizontal2,
  Focus, GitCompare, Grid3x3, Layers2, Maximize, MousePointer2, PackageOpen, PenLine, Pyramid, RectangleHorizontal, RefreshCcwDot, Rotate3d,
  RotateCw, Route, Ruler, Scale, Scissors, ShieldCheck, ScanSearch, Spline, SquareDashed, Squircle, Triangle, Upload, Wrench, Hexagon,
  PanelBottom, CornerRightUp, Undo2, FoldHorizontal, FileDown, StepForward,
} from "lucide-react";
import { Ribbon, type RibbonBtn } from "./Ribbon";
import type { ViewerApi } from "@/components/Viewer3D";
import type { DisplayMode, ViewName } from "@/viewer/types";

export type Command =
  | { kind: "feature"; op: "extrude" | "hole" | "fillet" | "chamfer" | "shell" | "mirror" | "pattern" | "plane" | "draft" | "sweep" | "loft" | "thread" | "sm_flange" | "sm_hem" | "sm_jog"; preset?: Record<string, unknown> }
  | { kind: "sketch"; preset?: { feature?: "extrude" | "revolve" | "rib" | "sketch" | "sheet"; mode?: "add" | "cut" } }
  | { kind: "tool"; tool: "measure" | "select" }
  | { kind: "panel"; tab: string; extra?: "com" }
  | { kind: "import" } | { kind: "toolbox" } | { kind: "similar" } | { kind: "normal" };

interface Btn {
  id: string; label: string; icon: ReactNode; tip: string; cmd?: Command; onClick?: () => void; active?: boolean; disabled?: boolean; needsBody?: boolean;
  /** a flyout (SOLIDWORKS-style): the button opens a short menu */
  menu?: { label: string; onSelect: () => void; on?: boolean }[]; key?: string;
  /** Make tab: output state for this part, and add-on lock */
  status?: MakeModule["status"]; locked?: boolean;
}

const TABS = ["Features", "Sketch", "Sheet Metal", "Evaluate", "View", "Library", "Make"] as const;

/** Downstream modules shown on the Make tab (only the Live ones are passed in). */
export interface MakeModule {
  code: string; name: string; icon: ReactNode; tip: string;
  /** One-line state of this module's output for the current part (Make tab), e.g. "Rev A" or "Model changed · update". */
  status?: { text: string; tone: "ok" | "warn" | "muted" };
  /** Not in the workspace's plan: shown with a lock, opens the add-on page. */
  locked?: boolean;
}

/** Sheet metal state for the Sheet Metal tab (CAD-026). */
export interface SheetTab { has: boolean; flat: boolean; onFlat: () => void; onDxf: () => void }

export default function CommandManager({ onCommand, viewerRef, disabled, activeTool, left, right, make = [], onMake, library = [], canNormal = false, touch = false, sheet }: {
  onCommand: (c: Command) => void; viewerRef: { current: ViewerApi | null }; disabled: boolean; activeTool: string;
  left?: ReactNode; right?: ReactNode; make?: MakeModule[]; onMake?: (code: string) => void; library?: MakeModule[];
  /** a planar face is selected (enables Normal To) */
  canNormal?: boolean;
  /** phones/tablets (UX-018): title row and tabs on separate rows, and the ribbon scrolls sideways instead of
   * folding commands into "More" (a swipe beats a menu on touch) */
  touch?: boolean;
  /** sheet metal: whether the part is sheet metal, the flat-pattern toggle and the DXF download */
  sheet?: SheetTab;
}) {
  const [, setTick] = useState(0);
  const viewer = viewerRef.current;
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
      { id: "thread", label: "Cosmetic Thread", icon: <Spline className="h-5 w-5 rotate-90" />, tip: "ISO metric thread on a hole or shaft: called out on drawings and written to the STEP file (the geometry stays plain)", cmd: { kind: "feature", op: "thread" }, needsBody: true },
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
    "Sheet Metal": [[
      { id: "smbase", label: "Base Flange", icon: <PanelBottom className="h-5 w-5" />, tip: disabled ? "Sketch a closed profile, then thicken it into a sheet: thickness, default bend radius, K-factor and relief type are set here for the whole part" : "A base flange starts a sheet-metal part: use it on a new part", cmd: { kind: "sketch", preset: { feature: "sheet" } }, disabled: !disabled && !sheet?.has },
      { id: "smflange", label: "Edge Flange", icon: <CornerRightUp className="h-5 w-5" />, tip: sheet?.has ? "Bend a flange up from a straight edge of the sheet: length, angle, bend radius, position, end offsets" : "Needs a sheet-metal part: start it with a Base Flange", cmd: { kind: "feature", op: "sm_flange" }, needsBody: true, disabled: !sheet?.has },
      { id: "smhem", label: "Hem", icon: <Undo2 className="h-5 w-5 rotate-90" />, tip: sheet?.has ? "Fold an edge back on itself (open hem with a gap)" : "Needs a sheet-metal part: start it with a Base Flange", cmd: { kind: "feature", op: "sm_hem" }, needsBody: true, disabled: !sheet?.has },
      { id: "smjog", label: "Jog", icon: <StepForward className="h-5 w-5 -rotate-45" />, tip: sheet?.has ? "Raise (or lower) the end of the sheet at a picked edge with two opposite bends: jog line distance, offset and angle" : "Needs a sheet-metal part: start it with a Base Flange", cmd: { kind: "feature", op: "sm_jog" }, needsBody: true, disabled: !sheet?.has },
    ], [
      { id: "smflat", label: sheet?.flat ? "Fold" : "Flatten", icon: <FoldHorizontal className="h-5 w-5" />, tip: sheet?.flat ? "Show the folded part again" : "Show the flat pattern (bend allowance from the K-factor)", onClick: () => sheet?.onFlat(), active: !!sheet?.flat, disabled: !sheet?.has },
      { id: "smdxf", label: "Flat DXF", icon: <FileDown className="h-5 w-5" />, tip: "Download the flat pattern as DXF: outline at true size, bend lines (UP / DOWN layers) and bend notes", onClick: () => sheet?.onDxf(), disabled: !sheet?.has },
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
      { id: "orient", label: "View Orientation", icon: <Rotate3d className="h-5 w-5" />, tip: "Standard views (Ctrl+1 to 7)", menu: views.map((v, i) => ({ label: `${v}  · Ctrl+${i + 1}`, onSelect: () => viewer?.setView(v) })) },
    ], [
      { id: "display", label: "Display Style", icon: <Cuboid className="h-5 w-5" />, tip: "Shaded, edges, hidden lines, wireframe", menu: displays.map(([m, l]) => ({ label: l, on: viewer?.display === m, onSelect: () => viewer?.setDisplay(m) })) },
      { id: "ortho", label: viewer?.ortho ? "Perspective" : "Orthographic", icon: viewer?.ortho ? <Hexagon className="h-5 w-5" /> : <SquareDashed className="h-5 w-5" />, tip: viewer?.ortho ? "Switch to a perspective view" : "Switch back to the orthographic (CAD) view", onClick: () => viewer?.setOrtho(!viewer.ortho) },
    ]],
    Library: [[
      { id: "toolbox", label: "Toolbox", icon: <Wrench className="h-5 w-5" />, tip: "Standard components (fasteners, bearings, gears…) from repeatable generators", cmd: { kind: "toolbox" } },
      { id: "similar", label: "Similar Parts", icon: <ScanSearch className="h-5 w-5" />, tip: "Find parts you already made that look like this one: same envelope, proportions and holes", cmd: { kind: "similar" }, needsBody: true },
      { id: "import", label: "Import STEP", icon: <Upload className="h-5 w-5" />, tip: "Import a STEP file, recognise its features and rebuild it as a parametric model", cmd: { kind: "import" } },
    ], ...(library.length ? [library.map(m => ({ id: m.code, label: m.name, icon: m.icon, tip: m.tip, onClick: () => onMake?.(m.code) })) as Btn[]] : [])],
    Make: [make.map(m => ({ id: m.code, label: m.name, icon: m.icon, onClick: () => onMake?.(m.code), disabled: disabled && !m.locked, status: m.locked ? undefined : m.status, locked: m.locked,
      tip: m.locked ? `Add-on, not in your plan yet: ${m.tip}. Opens the add-on page.` : m.status ? `${m.tip}. Now: ${m.status.text}` : m.tip })) as Btn[]],
  };
  // Commands become plain ribbon buttons; a click re-renders so toggles (section, ortho, display) show their new state.
  const after = () => setTimeout(() => setTick(t => t + 1), 0);
  const toRibbon = (b: Btn, makeTab: boolean): RibbonBtn => {
    const off = b.disabled || (disabled && !!b.needsBody);
    return {
      id: b.id, label: b.label, icon: b.icon, active: b.active, disabled: off, status: b.status, locked: b.locked,
      tip: off && b.needsBody ? "Needs a solid first: start with Extruded or Revolved Boss, ask the agent, use the Toolbox or import a STEP" : b.tip,
      onClick: () => { if (b.onClick) { b.onClick(); after(); } else if (b.cmd) onCommand(b.cmd); },
      menu: b.menu?.map(m => ({ ...m, onSelect: () => { m.onSelect(); after(); } })),
      attrs: makeTab && !b.menu ? { "data-make": b.id } : undefined,
    };
  };
  const ribbon = Object.fromEntries(TABS.map(t => [t, groups[t].map(g => g.map(b => toRibbon(b, t === "Make")))])) as Record<(typeof TABS)[number], RibbonBtn[][]>;
  const tabs = TABS.filter(t => t !== "Make" || make.length > 0);

  return (
    <Ribbon tabs={tabs} groups={ribbon} storageKey="fw_cm" left={left} right={right} touch={touch} wide={["Make"]} tour="command-manager"
      onSize={() => setTick(t => t + 1)}
      tabAttrs={t => t === "Make" ? { tour: "make", dot: make.some(m => m.status?.tone === "warn") ? "An output is out of date with the model" : undefined } : undefined} />
  );
}
