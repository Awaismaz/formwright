import { useState, type ReactNode } from "react";
import {
  AlertTriangle, ArrowDownUp, Ban, Box, ChevronDown, ChevronRight, Circle, CircleDot, Eye, EyeOff, Link2, MoreHorizontal,
  Pin, PinOff, RefreshCw, RotateCw, Ruler, Trash2, Wrench, Layers, Equal, TriangleRight,
} from "lucide-react";
import { cx } from "@/lib/format";
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Tip } from "@/components/ui";
import type { AsmView, Instance, Mate, MateType } from "./types";

export const MATE_ICON: Record<MateType, ReactNode> = {
  coincident: <Layers className="h-3.5 w-3.5" />, flush: <Equal className="h-3.5 w-3.5" />,
  concentric: <CircleDot className="h-3.5 w-3.5" />, distance: <Ruler className="h-3.5 w-3.5" />,
  angle: <TriangleRight className="h-3.5 w-3.5" />,
};

/** SOLIDWORKS-style state prefix: (f) fixed, (-) under-defined, (+) over-defined, none when fully positioned. */
function StatePrefix({ i }: { i: Instance }) {
  if (i.fixed) return <Tip content="Fixed in place"><span className="text-[11px] font-medium text-muted">(f)</span></Tip>;
  const d = i.dof;
  if (d?.over) return <Tip content="Involved in a conflicting mate"><span className="text-[11px] font-bold text-danger">(+)</span></Tip>;
  if (d && d.dof > 0 && !d.spin) {
    return <Tip content={`Can still move: ${d.dof} degree${d.dof > 1 ? "s" : ""} of freedom (${d.trans} translation, ${d.rot} rotation)`}>
      <span className="text-[11px] font-bold text-warning">(−)</span></Tip>;
  }
  if (d?.spin) return <Tip content="Positioned; free to spin about its axis (normal for fasteners and shafts)"><span className="font-mono text-[11px] text-muted">⟳</span></Tip>;
  return null;
}

interface TreeProps {
  view: AsmView;
  selected: string | null;
  onSelect: (id: string | null) => void;
  canEdit: boolean;
  onPatch: (iid: string, body: Record<string, unknown>) => void;
  onDelete: (iid: string) => void;
  onDeleteGroup: (gid: string) => void;
  onRefresh: (iid: string) => void;
  onMate: (mid: string, body: Record<string, unknown> | null) => void;
  hoverMate: (m: Mate | null) => void;
  focusMate: string | null;
}

export function Tree(p: TreeProps) {
  const { view } = p;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const loose = view.instances.filter(i => !i.group);
  const groups = view.groups.map(g => ({ g, items: view.instances.filter(i => i.group === g.id) })).filter(x => x.items.length);
  const userMates = view.mates.filter(m => !m.group);
  const stackMates = view.mates.filter(m => m.group);
  const problems = view.mates.filter(m => m.status !== "ok" && m.status !== "suppressed");
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="asm-tree">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <Box className="h-4 w-4 text-primary" /><div className="min-w-0 truncate text-[13px] font-semibold">{view.assembly.name}</div>
        <span className="ml-auto text-[11px] tabular-nums text-muted">{view.instances.length}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {loose.map(i => <Row key={i.id} i={i} {...p} />)}
        {groups.map(({ g, items }) => {
          const isOpen = open[g.id] ?? false;
          const anySel = items.some(i => i.id === p.selected);
          return (
            <div key={g.id}>
              <div className={cx("group flex items-center gap-1 px-2 py-1 text-[12.5px] hover:bg-text/[.04]", anySel && "bg-primary-soft/60")}>
                <button type="button" onClick={() => setOpen(o => ({ ...o, [g.id]: !isOpen }))} className="rounded p-0.5 text-muted hover:text-text">
                  {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </button>
                <Wrench className="h-3.5 w-3.5 shrink-0 text-accent" />
                <button type="button" className="min-w-0 flex-1 truncate text-left" title={g.name}
                  onClick={() => p.onSelect(items[1]?.id ?? items[0]!.id)}>{g.name.replace(/ \(.*\)$/, "")}
                  <span className="ml-1 text-muted">{g.spec.designation}×{g.spec.length?.L}</span></button>
                {p.canEdit && <Tip content="Remove this fastener stack"><button type="button" onClick={() => p.onDeleteGroup(g.id)}
                  className="hidden rounded p-0.5 text-muted hover:text-danger group-hover:block"><Trash2 className="h-3.5 w-3.5" /></button></Tip>}
              </div>
              {isOpen && <div className="ml-4 border-l border-border">{items.map(i => <Row key={i.id} i={i} {...p} />)}</div>}
            </div>
          );
        })}
        <div className="mt-2 flex items-center gap-1.5 border-t border-border px-3 pb-1 pt-2.5">
          <Link2 className="h-3.5 w-3.5 text-muted" /><span className="label">Mates</span>
          <span className="ml-auto text-[11px] tabular-nums text-muted">{view.mates.length}</span>
        </div>
        {problems.length > 0 && <div className="mx-2 mb-1 flex items-start gap-1.5 rounded border border-danger/30 bg-danger/5 px-2 py-1.5 text-[11.5px] text-danger">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{problems.length} mate{problems.length > 1 ? "s" : ""} not satisfied. Delete or suppress {problems.length > 1 ? "them" : "it"}, or change the value.</div>}
        {userMates.length === 0 && stackMates.length === 0 && <div className="px-3 py-2 text-[12px] text-muted">No mates yet. Use the Mate tab to pick two faces.</div>}
        {userMates.map(m => <MateRow key={m.id} m={m} {...p} />)}
        {stackMates.length > 0 && (
          <div>
            <button type="button" onClick={() => setOpen(o => ({ ...o, __stack: !o.__stack }))}
              className="flex w-full items-center gap-1 px-2 py-1 text-[12px] text-muted hover:text-text">
              {open.__stack ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}Fastener mates ({stackMates.length})
            </button>
            {open.__stack && stackMates.map(m => <MateRow key={m.id} m={m} {...p} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ i, selected, onSelect, canEdit, onPatch, onDelete, onRefresh }: { i: Instance } & TreeProps) {
  const sel = selected === i.id;
  return (
    <div className={cx("group flex items-center gap-1.5 px-2 py-1 text-[12.5px]", sel ? "bg-primary-soft text-primary" : "hover:bg-text/[.04]")}
      data-inst={i.id}>
      <button type="button" title={i.visible ? "Hide" : "Show"} onClick={() => onPatch(i.id, { visible: !i.visible })}
        className={cx("rounded p-0.5", i.visible ? "text-muted hover:text-text" : "text-muted/50")}>
        {i.visible ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
      </button>
      {i.source.kind === "toolbox" ? <Circle className="h-3 w-3 shrink-0 text-accent" /> : <Box className="h-3.5 w-3.5 shrink-0 text-primary" />}
      <StatePrefix i={i} />
      <button type="button" onClick={() => onSelect(sel ? null : i.id)} className={cx("min-w-0 flex-1 truncate text-left", !i.visible && "text-muted")}
        title={i.display}>{i.display}</button>
      {i.stale && (
        <Tip content="The part changed in the Design Studio. Refresh to use the latest verified build.">
          <button type="button" disabled={!canEdit} onClick={() => onRefresh(i.id)}
            className="inline-flex items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-1.5 text-[10.5px] font-semibold text-warning hover:bg-warning/20">
            <RefreshCw className="h-3 w-3" />Updated</button>
        </Tip>
      )}
      {i.source_missing && <Tip content="The source project was deleted; the pinned snapshot is still used."><AlertTriangle className="h-3.5 w-3.5 text-warning" /></Tip>}
      {canEdit && (
        <Menu>
          <MenuTrigger asChild><button type="button" className="rounded p-0.5 text-muted opacity-0 hover:text-text group-hover:opacity-100 data-[state=open]:opacity-100"><MoreHorizontal className="h-3.5 w-3.5" /></button></MenuTrigger>
          <MenuContent>
            <MenuItem icon={i.fixed ? <PinOff /> : <Pin />} onSelect={() => onPatch(i.id, { fixed: !i.fixed })}>{i.fixed ? "Float" : "Fix in place"}</MenuItem>
            <MenuItem icon={i.visible ? <EyeOff /> : <Eye />} onSelect={() => onPatch(i.id, { visible: !i.visible })}>{i.visible ? "Hide" : "Show"}</MenuItem>
            {i.source.kind === "project" && <MenuItem icon={<RefreshCw />} onSelect={() => onRefresh(i.id)}>Refresh from project</MenuItem>}
            <MenuSeparator />
            <MenuItem icon={<Trash2 />} danger onSelect={() => onDelete(i.id)}>Delete instance</MenuItem>
          </MenuContent>
        </Menu>
      )}
    </div>
  );
}

function MateRow({ m, canEdit, onMate, hoverMate, focusMate }: { m: Mate } & TreeProps) {
  const bad = m.status === "conflict" || m.status === "unsatisfied" || m.status === "broken";
  const val = m.type === "distance" ? ` ${m.value ?? 0} mm` : m.type === "angle" ? ` ${m.value ?? 0}°` : "";
  return (
    <div className={cx("group flex items-center gap-1.5 px-2 py-1 text-[12px]", focusMate === m.id ? "bg-primary-soft" : "hover:bg-text/[.04]",
      m.suppressed && "opacity-50")} onMouseEnter={() => hoverMate(m)} onMouseLeave={() => hoverMate(null)} data-mate={m.id}>
      <span className={cx("shrink-0", bad ? "text-danger" : "text-muted")}>{MATE_ICON[m.type]}</span>
      <span className="min-w-0 flex-1 truncate" title={`${m.label}${val}: ${m.a_name} ↔ ${m.b_name}`}>
        <span className={cx("font-medium", bad && "text-danger")}>{m.label}{val}</span>
        <span className="text-muted"> {m.a_name} · {m.b_name}</span>
      </span>
      {m.status === "conflict" && <Tip content={`Conflicts with earlier mates (off by ${m.residual_mm?.toFixed(3)} mm / ${m.residual_deg?.toFixed(2)}°). It is not applied.`}><Ban className="h-3.5 w-3.5 text-danger" /></Tip>}
      {m.status === "broken" && <Tip content="The referenced face no longer exists after the part was updated."><AlertTriangle className="h-3.5 w-3.5 text-danger" /></Tip>}
      {canEdit && (
        <Menu>
          <MenuTrigger asChild><button type="button" className="rounded p-0.5 text-muted opacity-0 hover:text-text group-hover:opacity-100 data-[state=open]:opacity-100"><MoreHorizontal className="h-3.5 w-3.5" /></button></MenuTrigger>
          <MenuContent>
            {m.type !== "concentric" && <MenuItem icon={<ArrowDownUp />} onSelect={() => onMate(m.id, { flip: !m.flip })}>Flip alignment</MenuItem>}
            {m.type === "concentric" && <MenuItem icon={<RotateCw />} onSelect={() => onMate(m.id, { flip: !m.flip })}>Reverse axis</MenuItem>}
            <MenuItem icon={<Ban />} onSelect={() => onMate(m.id, { suppressed: !m.suppressed })}>{m.suppressed ? "Unsuppress" : "Suppress"}</MenuItem>
            <MenuSeparator />
            <MenuItem icon={<Trash2 />} danger onSelect={() => onMate(m.id, null)}>Delete mate</MenuItem>
          </MenuContent>
        </Menu>
      )}
    </div>
  );
}
