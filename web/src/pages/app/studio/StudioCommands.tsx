import { useEffect, useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Command as CmdIcon, CornerDownLeft, Info } from "lucide-react";
import type { ManualFeature } from "@/lib/types";
import { cx } from "@/lib/format";
import type { ViewerApi } from "@/components/Viewer3D";
import type { Tool } from "@/components/Viewer3D";
import { edgeMid, edgeRef } from "@/viewer/measure";
import type { Pick, Topo } from "@/viewer/types";
import { EXAMPLES, parse, SHORTCUTS, type Parsed } from "./commands";
import type { FeatureOp } from "./FeatureManager";

export { SHORTCUTS };

/** Ctrl+K in the Studio: typed commands on the current selection, run without AI or tokens (IDEA 5). */
export default function StudioCommands({ open, onOpenChange, topo, selection, manual, designFeatures, viewer, onPm, onFeature, onSuppress, onSuppressDesign, onUndo, onRedo, onTool, onShortcuts }: {
  open: boolean; onOpenChange: (v: boolean) => void; topo: Topo | null; selection: Pick[]; manual: ManualFeature[]; designFeatures: string[];
  viewer: { current: ViewerApi | null }; onPm: (op: FeatureOp, preset?: Record<string, unknown>) => void;
  onFeature: (f: Record<string, unknown>, label: string) => void; onSuppress: (f: ManualFeature) => void; onSuppressDesign: (name: string) => void;
  onUndo: () => void; onRedo: () => void; onTool: (t: Tool) => void; onShortcuts: () => void;
}) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  useEffect(() => { if (open) { setQ(""); setSel(0); } }, [open]);
  const edges = selection.filter(p => p.kind === "edge") as Extract<Pick, { kind: "edge" }>[];
  const faces = selection.filter(p => p.kind === "face" && topo?.faces[p.id]?.type === "plane") as Extract<Pick, { kind: "face" }>[];
  const parsed = parse(q);
  const findFeature = (name: string) => {
    const k = name.toLowerCase();
    return manual.find(f => f.name.toLowerCase() === k) ?? manual.find(f => f.name.toLowerCase().includes(k));
  };

  /** What the parsed command will do, or why it can't run yet. */
  const plan = (c: Parsed): { text: string; run?: () => void } => {
    switch (c.kind) {
      case "fillet": case "chamfer": {
        const what = c.kind === "fillet" ? `Fillet R${c.size}` : `Chamfer ${c.size} mm`;
        if (!edges.length || !topo) return { text: `${what}: select the edges first (Select tool, Ctrl+click for several)` };
        return { text: `${what} on ${edges.length} selected edge${edges.length === 1 ? "" : "s"}`, run: () => onFeature({
          op: c.kind, name: c.kind === "fillet" ? `Fillet R${c.size}` : `Chamfer ${c.size}`, [c.kind === "fillet" ? "r" : "d"]: c.size,
          edges: edges.map(p => edgeMid(topo, p.id)), edge_refs: edges.map(p => edgeRef(topo, p.id)) }, what) };
      }
      case "shell":
        if (!faces.length || !topo) return { text: `Shell ${c.size} mm: select the face(s) to remove first` };
        return { text: `Shell ${c.size} mm, removing ${faces.length} face${faces.length === 1 ? "" : "s"}`, run: () => onFeature({
          op: "shell", name: `Shell ${c.size}`, t: c.size, faces: faces.map(p => ({ point: p.point, normal: topo.faces[p.id]!.normal })) }, `Shell ${c.size} mm`) };
      case "hole": {
        const label = c.type === "simple" ? `Ø${c.d} hole` : `M${c.size} ${c.type === "cbore" ? "counterbored" : c.type === "csk" ? "countersunk" : c.type}`;
        const where = c.edge !== undefined ? `, ${c.count && c.count !== 4 ? `${c.count} holes` : "4 corners"} ${c.edge} mm from the edges` : "";
        if (!faces.length) return { text: `Hole Wizard ${label}${where}: select the flat face first` };
        return { text: `Open the Hole Wizard: ${label}${where} (preview, then Enter)`, run: () => onPm("hole", {
          hole: { type: c.type, size: c.size, d: c.d, mode: c.edge !== undefined ? "corners" : "picked", dx: c.edge, dy: c.edge } }) };
      }
      case "view": return { text: `${c.view} view`, run: () => viewer.current?.setView(c.view) };
      case "fit": return { text: "Zoom to fit", run: () => viewer.current?.zoomToFit() };
      case "normal": {
        const n = faces[0] && topo?.faces[faces[0].id]?.normal;
        return n ? { text: "Normal to the selected face", run: () => viewer.current?.normalTo(n) } : { text: "Normal to: select a flat face first" };
      }
      case "suppress": case "unsuppress": {
        const f = findFeature(c.name);
        if (f) return { text: `${c.kind === "suppress" ? "Suppress" : "Unsuppress"} “${f.name}”`, run: f.suppressed === (c.kind === "unsuppress") ? () => onSuppress(f) : undefined };
        const d = c.kind === "suppress" && designFeatures.find(x => x.toLowerCase().includes(c.name.toLowerCase()));
        return d ? { text: `Suppress “${d}”`, run: () => onSuppressDesign(d) } : { text: `No feature called “${c.name}”` };
      }
      case "undo": return { text: "Undo the last change", run: onUndo };
      case "redo": return { text: "Redo", run: onRedo };
      case "measure": return { text: "Measure tool", run: () => onTool("measure") };
      case "select": return { text: "Select tool", run: () => onTool("select") };
      case "section": return { text: "Section view", run: () => viewer.current?.toggleSection() };
      case "shortcuts": return { text: "Keyboard shortcuts", run: onShortcuts };
    }
  };
  const p = parsed ? plan(parsed) : null;
  const examples = useMemo(() => {
    const s = q.trim().toLowerCase().split(" ")[0] ?? "";
    return EXAMPLES.filter(([e]) => !s || e.startsWith(s) || e.includes(s)).slice(0, 7);
  }, [q]);
  const go = (fn?: () => void) => { if (!fn) return; onOpenChange(false); fn(); };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <Dialog.Content className="fixed left-1/2 top-[14vh] z-50 w-[calc(100vw-32px)] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-panel shadow-pop animate-fade-in" aria-describedby={undefined}>
          <Dialog.Title className="sr-only">Studio command</Dialog.Title>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <CmdIcon className="h-4 w-4 text-primary" />
            <input autoFocus value={q} onChange={e => { setQ(e.target.value); setSel(0); }} placeholder="Type a command: fillet 3, hole M6 x4 10 from edges, view top…"
              aria-label="Studio command" className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted"
              onKeyDown={e => {
                if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, examples.length - 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
                if (e.key === "Enter") { e.preventDefault(); if (p) go(p.run); else if (examples[sel]) setQ(examples[sel]![0]); }
                if (e.key === "Tab" && !p && examples[sel]) { e.preventDefault(); setQ(examples[sel]![0]); }
              }} />
            <span className="text-[10.5px] text-muted">no AI</span>
          </div>
          {p && <div className={cx("flex items-center gap-2 border-b border-border px-4 py-2.5 text-[13px]", p.run ? "bg-primary-soft text-primary" : "text-muted")} data-command-plan>
            {p.run ? <CornerDownLeft className="h-4 w-4" /> : <Info className="h-4 w-4" />}{p.text}</div>}
          {!p && <div className="p-1.5">
            {q.trim() && <div className="px-3 py-1.5 text-[12px] text-muted">Not a command yet. Try:</div>}
            {examples.map(([e, d], i) => (
              <button key={e} onMouseEnter={() => setSel(i)} onClick={() => setQ(e)}
                className={cx("flex w-full items-center gap-3 rounded px-3 py-1.5 text-left text-[13px]", i === sel && "bg-primary-soft")}>
                <span className="font-mono text-[12px] text-primary">{e}</span><span className="flex-1 truncate text-right text-[12px] text-muted">{d}</span></button>))}
          </div>}
          <div className="border-t border-border bg-panel2 px-4 py-1.5 text-[11px] text-muted">Runs on the current selection, instantly and without tokens. Undo with Ctrl+Z.</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
