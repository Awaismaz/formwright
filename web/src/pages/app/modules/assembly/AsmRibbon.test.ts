import { describe, expect, it, vi } from "vitest";
import { ASM_TABS, assemblyRibbon, type AsmRibbonCtx } from "./AsmRibbon";
import { fitRibbon } from "@/pages/app/studio/Ribbon";

function ctx(over: Partial<AsmRibbonCtx> = {}): AsmRibbonCtx {
  const f = vi.fn();
  return {
    canEdit: true, hasParts: true, panel: "chat", setPanel: f, onInsert: f, onNewPart: f, mateChoice: "auto", onMateType: f,
    move: { can: true, mode: null }, onMove: f, fmode: "hole", onFasten: f, onInterference: f, onClearance: f, checking: false,
    onFit: f, onView: f, explode: 0, onExplode: f, selected: { name: "Plate", visible: true }, onToggleVisible: f, hidden: 0, onShowAll: f,
    onExport: f, exporting: false, exported: true, stepUrl: "/x.step", onDownloadStep: f, onSave: f, onOpen: f, onRender: f, ...over,
  };
}

describe("Assembly command bar (ASM-RB-1)", () => {
  it("has the SOLIDWORKS tabs, each with commands", () => {
    const g = assemblyRibbon(ctx());
    expect(Object.keys(g)).toEqual([...ASM_TABS]);
    for (const t of ASM_TABS) expect(g[t].flat().length).toBeGreaterThan(0);
    const labels = (t: (typeof ASM_TABS)[number]) => g[t].flat().map(b => b.label);
    expect(labels("Assembly")).toEqual(expect.arrayContaining(["Insert Components", "New Part", "Mate", "Standard Mates", "Move Component", "Rotate Component", "Smart Fasteners"]));
    expect(labels("Evaluate")).toEqual(expect.arrayContaining(["Interference Detection", "Clearance Verification", "Motion Study"]));
    expect(labels("View")).toEqual(expect.arrayContaining(["Zoom to Fit", "View Orientation", "Exploded View"]));
    expect(labels("Make")).toEqual(expect.arrayContaining(["Bill of Materials", "Re-export STEP", "Save .fwasm", "Open .fwasm", "Render"]));
  });

  it("gives every button a unique id, a copilot id, a tooltip and an icon", () => {
    const all = Object.values(assemblyRibbon(ctx())).flat(2);
    expect(new Set(all.map(b => b.id)).size).toBe(all.length);
    expect(new Set(all.map(b => b.copilot)).size).toBe(all.length);
    for (const b of all) {
      expect(b.copilot).toMatch(/^asm-[a-z-]+$/);
      expect(b.tip.length).toBeGreaterThan(5);
      expect(b.icon).toBeTruthy();
      expect(!!b.onClick || !!b.menu?.length).toBe(true);
    }
  });

  it("keeps the old header's test ids", () => {
    const all = Object.values(assemblyRibbon(ctx())).flat(2);
    const ids = all.map(b => b.attrs?.["data-testid"]).filter(Boolean);
    expect(ids).toEqual(expect.arrayContaining(["insert", "export-step", "step-download", "render-assembly"]));
  });

  it("highlights the open panel and offers only the mate types the solver has", () => {
    const g = assemblyRibbon(ctx({ panel: "mate", mateChoice: "concentric" }));
    expect(g.Assembly.flat().find(b => b.id === "mate")?.active).toBe(true);
    const menu = g.Assembly.flat().find(b => b.id === "mates")!.menu!;
    expect(menu.map(m => m.label)).toEqual(["Smart", "Coincident", "Flush", "Concentric", "Distance", "Angle", "Gear mesh"]);
    expect(menu.find(m => m.on)?.label).toBe("Concentric");
  });

  it("disables editing when read-only or empty, and drops outputs that don't exist", () => {
    const ro = Object.values(assemblyRibbon(ctx({ canEdit: false }))).flat(2);
    for (const id of ["insert", "newpart", "quick", "move", "rotate", "hide"]) expect(ro.find(b => b.id === id)?.disabled).toBe(true);
    expect(ro.find(b => b.id === "export")).toBeUndefined();
    const empty = Object.values(assemblyRibbon(ctx({ hasParts: false, stepUrl: null, exported: false, selected: null, move: null }))).flat(2);
    for (const id of ["mate", "interference", "clearance", "motion", "fit", "explode", "export"]) expect(empty.find(b => b.id === id)?.disabled).toBe(true);
    expect(empty.find(b => b.id === "insert")?.disabled).toBe(false);
    for (const id of ["download", "save", "render"]) expect(empty.find(b => b.id === id)).toBeUndefined();
    expect(empty.find(b => b.id === "move")?.tip).toMatch(/Select a component/);
  });

  it("shrinks, then folds into More, but never on touch", () => {
    const g = assemblyRibbon(ctx()).Assembly;
    expect(fitRibbon(g, 2000, false).size).toBe("full");
    expect(fitRibbon(g, 700, false).size).toBe("mid");
    const tight = fitRibbon(g, 300, false);
    expect(tight.size).toBe("icon");
    expect(tight.visible.flat().length + tight.overflow.length).toBe(g.flat().length);
    expect(tight.overflow.length).toBeGreaterThan(0);
    expect(fitRibbon(g, 300, true).overflow).toEqual([]);
  });
});
