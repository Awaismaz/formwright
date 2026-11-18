import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Box, ChevronRight, Stamp } from "lucide-react";
import { Badge, StatusBadge, Tip } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";
import { ReleaseDialog, releaseChip, useDeliverables, type Deliverables } from "@/components/Release";
import { ago, cx } from "@/lib/format";
import { moduleExportUrl } from "@/lib/native";
import { FileButtons } from "@/components/NativeExport";

export type MakeCode = "drawings" | "manufacturing" | "engineering" | "print";

/** What each module calls its output, for "Model changed since this …". */
const OUTPUT: Record<MakeCode, string> = { drawings: "sheet", manufacturing: "analysis", engineering: "sign-off", print: "export" };

/**
 * One header for the downstream modules (MAKE-18): back to the part in the Studio, module name, part switcher, model
 * revision, release state (opens the release gate) and this module's staleness from the one rule in aicad.deliverables.
 * Module-specific actions go on the right.
 */
/** Save / open as a Formwright file, per module: the extension and the export of a part's work in that module. */
const FILE: Record<MakeCode, { ext: string; url: (pid: string) => string }> = {
  drawings: { ext: "fwdrw", url: pid => `/api/native/drawings/${pid}/export` },
  manufacturing: { ext: "fwmfg", url: pid => moduleExportUrl("mfg", pid) },
  engineering: { ext: "fwcalc", url: pid => moduleExportUrl("calc", pid) },
  print: { ext: "fwprint", url: pid => moduleExportUrl("print", pid) },
};

export function ModuleHeader({ code, icon, title, projectId, projectName, projects, onSwitch, actions, children, files }: {
  code: MakeCode; icon: ReactNode; title: string;
  projectId: string | null; projectName?: string | null;
  /** Parts the user can switch to; omit to hide the switcher. `null` from onSwitch means "all parts" (the picker). */
  projects?: { id: string; name: string; disabled?: boolean }[]; onSwitch?: (id: string | null) => void;
  actions?: ReactNode; children?: ReactNode;
  /** Replaces the default Save/Open file buttons (e.g. a 2D drawing or an uploaded mesh). */
  files?: ReactNode;
}) {
  const d = useDeliverables(projectId);
  const [rel, setRel] = useState(false);
  return (
    <div className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-2 border-b border-border bg-panel px-3" data-module-header={code}>
      {projectId
        ? <Tip content="Back to this part in the Design Studio" side="bottom"><Link to={`/app/projects/${projectId}`} data-action="back-to-studio"
            className="inline-flex max-w-[220px] items-center gap-1 rounded px-1.5 py-1 text-[12.5px] text-muted hover:bg-text/5 hover:text-text">
            <ArrowLeft className="h-4 w-4 shrink-0" /><span className="truncate">{projectName ?? "Part"}</span></Link></Tip>
        : <Link to="/app/modules" className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[12.5px] text-muted hover:bg-text/5 hover:text-text">
            <ArrowLeft className="h-4 w-4" />Modules</Link>}
      <span className="h-5 w-px bg-border" />
      <div className="flex shrink-0 items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-soft text-primary">{icon}</span>
        <h1 className="text-[14px] font-semibold tracking-tight">{title}</h1>
        <StatusBadge status="live" />
      </div>
      {projectId && projects && onSwitch && <>
        <span className="mx-1 h-5 w-px bg-border" />
        <select aria-label="Part" className="input h-8 w-48 min-w-[120px] shrink py-0 text-[12.5px]" value={projectId} onChange={e => onSwitch(e.target.value || null)}>
          {projects.filter(p => !p.disabled || p.id === projectId).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          {!projects.some(p => p.id === projectId) && <option value={projectId}>{projectName ?? "Loading…"}</option>}
        </select>
        <button onClick={() => onSwitch(null)} className="whitespace-nowrap text-[12px] text-muted hover:text-primary">All parts</button>
      </>}
      {projectId && d.data && <StatusChips code={code} d={d.data} onRelease={() => setRel(true)} />}
      {children}
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {files ?? <FileButtons ext={FILE[code].ext} saveUrl={projectId ? FILE[code].url(projectId) : null}
          saveName={`${projectName ?? "part"}.${FILE[code].ext}`} openOnly={!projectId} />}
        {actions}
      </div>
      {projectId && <ReleaseDialog projectId={projectId} open={rel} onOpenChange={setRel} />}
    </div>
  );
}

function StatusChips({ code, d, onRelease }: { code: MakeCode; d: Deliverables; onRelease: () => void }) {
  const m = d.modules[code];
  const chip = releaseChip(d);
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      {d.build.model_rev && <Tip content="The model revision this module is looking at (each verified build of the part is a revision)" side="bottom">
        <span><Badge className="whitespace-nowrap">Model rev {d.build.model_rev}</Badge></span></Tip>}
      {m?.state === "stale" && <Tip content={`The part changed after this ${OUTPUT[code]} was made${m.made_from_rev ? ` (model rev ${m.made_from_rev})` : ""}. It is kept as it was until you update it.`} side="bottom">
        <span data-stale={code}><Badge tone="warning" className="whitespace-nowrap"><AlertTriangle className="h-3 w-3" />Model changed</Badge></span></Tip>}
      {chip && <Tip content={`${chip.tip} Click to open the release gate.`} side="bottom">
        <button onClick={onRelease} data-action="release" className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-4 transition hover:brightness-95",
          chip.tone === "success" ? "border-success/25 bg-success/10 text-success" : chip.tone === "warning" ? "border-warning/25 bg-warning/10 text-warning" : "border-border bg-panel2 text-muted hover:text-text")}>
          <Stamp className="h-3 w-3" />{chip.text}</button></Tip>}
    </div>
  );
}

/** One picker card for every downstream module (MAKE-18): iso thumbnail, name, material, age, module status. */
export function PartCard({ id, name, thumbnail, version, sub, updatedAt, status, disabled, disabledHint, onPick }: {
  id: string; name: string; thumbnail?: string | null; version?: string | number | null; sub?: ReactNode; updatedAt?: string;
  status?: ReactNode; disabled?: boolean; disabledHint?: string; onPick: (id: string) => void;
}) {
  const body = <>
    <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-border">
      {thumbnail ? <IsoThumb src={version != null ? `${thumbnail}?v=${version}` : thumbnail} /> : <Box className="h-10 w-10 text-muted/50" />}
    </div>
    <div className="flex flex-1 flex-col gap-2 p-3">
      <div className="min-w-0"><div className="truncate text-[13.5px] font-semibold">{name}</div>
        <div className="mt-0.5 truncate text-[11.5px] text-muted">{sub}{updatedAt ? <>{sub ? " · " : ""}updated {ago(updatedAt)}</> : null}</div></div>
      <div className="mt-auto flex min-w-0 items-center gap-1.5">{status}
        {!disabled && <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-muted transition group-hover:translate-x-0.5 group-hover:text-primary" />}</div>
    </div>
  </>;
  if (disabled) {
    return (
      <div className="card flex flex-col overflow-hidden opacity-70" title={disabledHint ?? "Build and verify this model in the Design Studio first"}>
        {body}
        <Link to={`/app/projects/${id}`} className="border-t border-border px-3 py-2 text-xs text-primary hover:underline">Open in Design Studio →</Link>
      </div>
    );
  }
  return (
    <button type="button" onClick={() => onPick(id)} data-project={id}
      className="card group flex flex-col overflow-hidden text-left transition hover:-translate-y-0.5 hover:shadow-pop">{body}</button>
  );
}
