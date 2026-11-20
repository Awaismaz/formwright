import {
  Camera, ClipboardList, Download, Expand, Eye, EyeOff, FileBox, FileDown, FilePlus2, FolderOpen, Link2, ListChecks, Maximize, MessagesSquare,
  Move, Orbit, Plus, Rotate3d, Ruler, Scale, ScanSearch, Sparkles, Wrench, RotateCw,
} from "lucide-react";
import type { RibbonBtn } from "@/pages/app/studio/Ribbon";
import { MATE_CHOICES, type MateChoice } from "./MatePanel";
import type { AsmView as ViewName } from "./viewer";

/** The right-hand panels of the Assembly Studio (the command bar opens and highlights them). */
export type TabKey = "chat" | "describe" | "mate" | "fasten" | "check" | "motion" | "bom";

/** Command bar tabs, named as SOLIDWORKS names them (founder 2026-11-20: nobody should feel like an alien here). */
export const ASM_TABS = ["Assembly", "Evaluate", "View", "Make"] as const;
export type AsmRibbonTab = (typeof ASM_TABS)[number];

export const ASM_VIEWS: ViewName[] = ["Iso", "Front", "Top", "Right", "Back", "Left", "Bottom"];

/** Everything the Assembly command bar shows and does; Workspace wires it to its existing handlers. */
export interface AsmRibbonCtx {
  canEdit: boolean; hasParts: boolean; panel: TabKey; setPanel: (t: TabKey) => void;
  onInsert: () => void; onNewPart: () => void;
  mateChoice: MateChoice; onMateType: (c: MateChoice) => void;
  /** null: nothing selected; otherwise whether the selected part can move, and why not */
  move: { can: boolean; why?: string; mode: "translate" | "rotate" | null } | null;
  onMove: (mode: "translate" | "rotate") => void;
  fmode: "hole" | "pair"; onFasten: (m: "hole" | "pair") => void;
  onInterference: () => void; onClearance: () => void; checking: boolean;
  onFit: () => void; onView: (v: ViewName) => void;
  explode: number; onExplode: () => void;
  selected: { name: string; visible: boolean } | null; onToggleVisible: () => void; hidden: number; onShowAll: () => void;
  onExport: () => void; exporting: boolean; exported: boolean; stepUrl: string | null; onDownloadStep: () => void;
  onSave: () => void; onOpen: () => void; onRender: () => void;
}

const I = "h-5 w-5";
const READ_ONLY = "You can view this assembly but not change it";

export function assemblyRibbon(c: AsmRibbonCtx): Record<AsmRibbonTab, RibbonBtn[][]> {
  const edit = (tip: string) => (c.canEdit ? tip : READ_ONLY);
  const noParts = "Insert a component first";
  const at = (t: TabKey) => ({ onClick: () => c.setPanel(t), active: c.panel === t });
  const moveTip = (verb: string, how: string) => !c.canEdit ? READ_ONLY : !c.move ? `Select a component in the tree or the view, then ${how}`
    : !c.move.can ? (c.move.why ?? "This component can't move") : `${verb} the selected component: ${how}. Mates re-apply after each move.`;
  const make: RibbonBtn[] = [
    { id: "bom", copilot: "asm-bom", label: "Bill of Materials", icon: <ClipboardList className={I} />, tip: "Parts list with quantities, materials and masses", ...at("bom") },
  ];
  if (c.canEdit) make.push({ id: "export", copilot: "asm-export-step", label: c.exported ? "Re-export STEP" : "Export STEP", icon: <FileBox className={I} />,
    tip: "Assembly STEP (AP214) with sub-assemblies, part names and placements; re-imported to verify", onClick: c.onExport,
    disabled: !c.hasParts || c.exporting, attrs: { "data-testid": "export-step" } });
  if (c.stepUrl) make.push({ id: "download", copilot: "asm-download-step", label: "Download STEP", icon: <Download className={I} />,
    tip: "Download the last exported STEP (still matches the assembly)", onClick: c.onDownloadStep, attrs: { "data-testid": "step-download" } });
  const files: RibbonBtn[] = [];
  if (c.hasParts) files.push({ id: "save", copilot: "asm-save", label: "Save .fwasm", icon: <FileDown className={I} />,
    tip: "Save this assembly as a Formwright file (.fwasm) to hand to anyone with Formwright", onClick: c.onSave, attrs: { "data-action": "save-file" } });
  files.push({ id: "open", copilot: "asm-open", label: "Open .fwasm", icon: <FolderOpen className={I} />, tip: "Open a Formwright assembly file (.fwasm) shared from any workspace",
    onClick: c.onOpen, attrs: { "data-action": "open-file" } });
  const out: RibbonBtn[][] = [make, files];
  if (c.hasParts) out.push([{ id: "render", copilot: "asm-render", label: "Render", icon: <Camera className={I} />,
    tip: "Product render of this assembly in Mesh Studio, exploded or not, each part in the finish its material suggests", onClick: c.onRender, attrs: { "data-testid": "render-assembly" } }]);

  return {
    Assembly: [[
      { id: "insert", copilot: "asm-insert", label: "Insert Components", icon: <Plus className={I} />, tip: edit("Insert a verified project part, a Toolbox component or a sub-assembly"),
        onClick: c.onInsert, disabled: !c.canEdit, attrs: { "data-testid": "insert" } },
      { id: "newpart", copilot: "asm-new-part", label: "New Part", icon: <FilePlus2 className={I} />, tip: edit("Describe a new part: the assembly agent designs it, verifies it and brings it into this assembly"),
        onClick: c.onNewPart, disabled: !c.canEdit },
    ], [
      { id: "mate", copilot: "asm-mate", label: "Mate", icon: <Link2 className={I} />, tip: "Pick a face or edge on two parts and mate them; the mates list shows what still moves", ...at("mate"), disabled: !c.hasParts },
      { id: "mates", copilot: "asm-standard-mates", label: "Standard Mates", icon: <ListChecks className={I} />, tip: "Start a mate of a given type", disabled: !c.hasParts || !c.canEdit,
        menu: MATE_CHOICES.map(m => ({ label: m.label, on: c.panel === "mate" && c.mateChoice === m.value, onSelect: () => c.onMateType(m.value) })) },
      { id: "quick", copilot: "asm-quick-add", label: "Quick Add", icon: <Sparkles className={I} />, tip: edit("Describe the components you need: they are found, inserted and mated for you"), ...at("describe"), disabled: !c.canEdit },
    ], [
      { id: "move", copilot: "asm-move", label: "Move Component", icon: <Move className={I} />, tip: moveTip("Move", "drag the arrows in the view"),
        onClick: () => c.onMove("translate"), active: c.move?.mode === "translate", disabled: !c.canEdit || !c.move?.can },
      { id: "rotate", copilot: "asm-rotate", label: "Rotate Component", icon: <RotateCw className={I} />, tip: moveTip("Rotate", "drag the rings in the view"),
        onClick: () => c.onMove("rotate"), active: c.move?.mode === "rotate", disabled: !c.canEdit || !c.move?.can },
    ], [
      { id: "fasten", copilot: "asm-fasteners", label: "Smart Fasteners", icon: <Wrench className={I} />, tip: c.hasParts ? "ISO bolts, nuts and washers fitted to recognised holes" : noParts,
        active: c.panel === "fasten", disabled: !c.hasParts,
        menu: [
          { label: "Fit to a hole or hole pattern", on: c.panel === "fasten" && c.fmode === "hole", onSelect: () => c.onFasten("hole") },
          { label: "Fasten two parts", on: c.panel === "fasten" && c.fmode === "pair", onSelect: () => c.onFasten("pair") },
        ] },
      { id: "chat", copilot: "asm-chat", label: "Assembly Chat", icon: <MessagesSquare className={I} />, tip: "Talk to the assembly agent: one conversation that keeps the context", ...at("chat") },
    ]],
    Evaluate: [[
      { id: "interference", copilot: "asm-interference", label: "Interference Detection", icon: <ScanSearch className={I} />,
        tip: c.hasParts ? "Find every pair of parts that overlap, with the exact overlap volume" : noParts, onClick: c.onInterference, active: c.panel === "check", disabled: !c.hasParts || c.checking },
      { id: "clearance", copilot: "asm-clearance", label: "Clearance Verification", icon: <Ruler className={I} />,
        tip: c.hasParts ? "The smallest gap between neighbouring parts, measured on the exact geometry" : noParts, onClick: c.onClearance, disabled: !c.hasParts || c.checking },
    ], [
      { id: "motion", copilot: "asm-motion", label: "Motion Study", icon: <Orbit className={I} />, tip: c.hasParts ? "Joints and a motion range check: steps through the range and flags collisions" : noParts, ...at("motion"), disabled: !c.hasParts },
      { id: "mass", copilot: "asm-mass", label: "Mass Properties", icon: <Scale className={I} />, tip: "Mass of each part and the assembly total, from the parts' materials", ...at("bom"), active: false, disabled: !c.hasParts },
    ]],
    View: [[
      { id: "fit", copilot: "asm-zoom-fit", label: "Zoom to Fit", icon: <Maximize className={I} />, tip: "Fit the assembly in the window (F)", onClick: c.onFit, disabled: !c.hasParts },
      { id: "orient", copilot: "asm-view-orientation", label: "View Orientation", icon: <Rotate3d className={I} />, tip: "Standard views (Ctrl+1–7)", disabled: !c.hasParts,
        menu: ASM_VIEWS.map((v, i) => ({ label: `${v}  · Ctrl+${i + 1}`, onSelect: () => c.onView(v) })) },
    ], [
      { id: "explode", copilot: "asm-explode", label: "Exploded View", icon: <Expand className={I} />, tip: c.explode > 0 ? "Collapse the exploded view (the slider under the view sets how far)" : "Explode the assembly (the slider under the view sets how far)",
        onClick: c.onExplode, active: c.explode > 0, disabled: !c.hasParts },
    ], [
      { id: "hide", copilot: "asm-hide-show", label: c.selected && !c.selected.visible ? "Show Component" : "Hide Component", icon: c.selected && !c.selected.visible ? <Eye className={I} /> : <EyeOff className={I} />,
        tip: !c.canEdit ? READ_ONLY : c.selected ? `${c.selected.visible ? "Hide" : "Show"} ${c.selected.name}` : "Select a component in the tree or the view first",
        onClick: c.onToggleVisible, disabled: !c.canEdit || !c.selected },
      { id: "showall", copilot: "asm-show-all", label: "Show All", icon: <Eye className={I} />, tip: c.hidden ? `Show the ${c.hidden} hidden component${c.hidden > 1 ? "s" : ""}` : "No hidden components",
        onClick: c.onShowAll, disabled: !c.canEdit || !c.hidden },
    ]],
    Make: out,
  };
}
