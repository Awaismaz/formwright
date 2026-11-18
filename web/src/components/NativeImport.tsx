import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Boxes, CheckCircle2, FileBox, FileUp, FolderKanban, Loader2, PenTool, ShieldAlert, ShieldCheck } from "lucide-react";
import { ApiError, track } from "@/lib/api";
import {
  describe, FORMAT_LABEL, fileSize, importNative, inspectNative, NATIVE_EVENT, openNativeImport, resultLink, STATE_TONE,
  type ImportResult, type Inspection, type NativeKind, type Verification,
} from "@/lib/native";
import { cx } from "@/lib/format";
import { Badge, Button, Modal } from "./ui";

type Step = { s: "inspecting" } | { s: "review"; info: Inspection } | { s: "importing"; info: Inspection }
  | { s: "done"; info: Inspection; res: ImportResult } | { s: "error"; message: string };

const KIND_ICON: Record<NativeKind, typeof FileBox> = { part: FileBox, assembly: Boxes, drawing: PenTool, program: FolderKanban, projects: FolderKanban };
const OPEN_LABEL: Record<NativeKind, string> = { part: "Open the part", assembly: "Open the assembly", drawing: "Open the drawing", program: "Open the program", projects: "Open projects" };

/** A module's "Import .fwasm" (etc.) button: picks a file and hands it to the import dialog. */
export function NativeImportButton({ accept, children, size = "md" }: { accept: string; children: React.ReactNode; size?: "sm" | "md" }) {
  const ref = useRef<HTMLInputElement>(null);
  return (<>
    <input ref={ref} type="file" accept={accept} hidden onChange={e => { const f = e.target.files?.[0]; if (f) openNativeImport(f); e.target.value = ""; }} />
    <Button variant="secondary" size={size} icon={<FileUp className="h-4 w-4" />} onClick={() => ref.current?.click()}>{children}</Button>
  </>);
}

export function VerifyBadge({ v, className }: { v: Verification; className?: string }) {
  const Icon = v.state === "identical" ? CheckCircle2 : AlertTriangle;
  return <Badge tone={STATE_TONE[v.state]} className={cx("gap-1", className)}><Icon className="h-3.5 w-3.5" />{v.label}</Badge>;
}

function VerifyDetail({ v }: { v: Verification }) {
  if (v.state === "identical")
    return <p className="text-[13px] text-muted">Rebuilt here from its parametric model: the same volume, size, faces, edges and solids as the exported part{v.step_identical ? ", and a byte-identical STEP" : ""}.</p>;
  if (v.state === "fallback")
    return <p className="text-[13px] text-muted">The part's model could not be rebuilt here{v.reason ? ` (${v.reason})` : ""}. Its exact exported geometry is kept as a read-only body; ask the design agent to rebuild it as a parametric model.</p>;
  return (<div className="text-[13px] text-muted"><p>The model rebuilt, but its geometry differs from the exported part:</p>
    <ul className="mt-1 list-disc pl-5">{v.diffs.slice(0, 6).map(d => <li key={d}>{d}</li>)}</ul></div>);
}

/** The import dialog for Formwright files, opened by `openNativeImport(file)` from anywhere in the app. */
export default function NativeImportHost() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>({ s: "inspecting" });

  useEffect(() => {
    const on = (e: Event) => {
      const f = (e as CustomEvent<File>).detail;
      if (!f) return;
      setFile(f); setStep({ s: "inspecting" });
      inspectNative(f).then(info => setStep({ s: "review", info }))
        .catch(err => setStep({ s: "error", message: err instanceof ApiError ? err.message : "That file could not be read." }));
    };
    window.addEventListener(NATIVE_EVENT, on);
    return () => window.removeEventListener(NATIVE_EVENT, on);
  }, []);

  const close = () => { if (step.s !== "importing") { setFile(null); } };
  const run = async (info: Inspection) => {
    if (!file) return;
    setStep({ s: "importing", info });
    try {
      const res = await importNative(file, info.needs_confirm);
      track("native_import", { format: info.format, trust: info.trust });
      await qc.invalidateQueries({ queryKey: ["projects"] });
      setStep({ s: "done", info, res });
    } catch (e) { setStep({ s: "error", message: e instanceof ApiError ? e.message : "The import failed. Nothing was changed." }); }
  };

  const info = "info" in step ? step.info : null;
  const Icon = info ? KIND_ICON[info.kind] : FileBox;
  const title = step.s === "done" ? "Imported" : step.s === "error" ? "Couldn't import this file" : `Import ${info ? FORMAT_LABEL[info.format].toLowerCase() : "a Formwright file"}`;
  const footer = step.s === "review" ? <>
      <Button variant="secondary" onClick={close}>Cancel</Button>
      <Button onClick={() => void run(step.info)}>{step.info.needs_confirm ? "I trust this file: import and rebuild" : "Import"}</Button></>
    : step.s === "done" ? <>
      <Button variant="secondary" onClick={close}>Close</Button>
      <Button onClick={() => { const to = resultLink(step.res); setFile(null); nav(to); }}>{OPEN_LABEL[step.res.kind]}</Button></>
    : step.s === "error" ? <Button variant="secondary" onClick={close}>Close</Button> : undefined;

  return (
    <Modal open={!!file} onOpenChange={o => { if (!o) close(); }} title={title} footer={footer}
      description={file ? <span className="break-all">{file.name}{info ? ` · ${fileSize(info.size)}` : ""}</span> : undefined}>
      {step.s === "inspecting" && <div className="flex items-center gap-2 py-4 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin text-primary" />Checking the file…</div>}
      {step.s === "error" && <p className="text-sm text-danger" role="alert">{step.message}</p>}
      {info && step.s !== "done" && step.s !== "error" && (
        <div className="space-y-3" data-testid="native-review">
          <div className="flex items-start gap-3 rounded-lg border border-border p-3">
            <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-semibold">{info.summary.title}</div>
              <div className="text-[12.5px] text-muted">{describe(info.summary)}</div>
              {info.summary.description && <p className="mt-1 line-clamp-3 text-[12.5px]">{info.summary.description}</p>}
            </div>
          </div>
          {info.trust === "workspace"
            ? <div className="flex items-start gap-2 rounded-lg border border-success/40 bg-success/10 p-3 text-[13px]"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" /><span><b>From your workspace.</b> Exported here and unchanged since (signature verified).</span></div>
            : <div className="flex items-start gap-2 rounded-lg border border-warning/50 bg-warning/10 p-3 text-[13px]"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <span><b>From another workspace.</b> Every file inside was checked and its model may only describe geometry. Formwright will rebuild it in your workspace and compare the result with the exported part. Import it only if you trust the sender.{info.trust_note && <span className="mt-1 block">{info.trust_note}</span>}</span></div>}
          {info.warnings.map(w => <p key={w} className="text-[12px] text-muted">{w}</p>)}
          {step.s === "importing" && <div className="flex items-center gap-2 text-sm text-muted"><Loader2 className="h-4 w-4 animate-spin text-primary" />Rebuilding the model and comparing its geometry…</div>}
        </div>)}
      {step.s === "done" && <ImportDone res={step.res} />}
    </Modal>
  );
}

function ImportDone({ res }: { res: ImportResult }) {
  const parts = res.parts ?? [];
  return (
    <div className="space-y-3" data-testid="native-result">
      {res.verification && <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
        <VerifyBadge v={res.verification} className="self-start text-[13px]" />
        {res.kind === "part" || res.kind === "drawing" ? <VerifyDetail v={res.verification} />
          : <p className="text-[13px] text-muted">{res.verification.state === "identical" ? "Every part was rebuilt from its model (or matched an identical part already here) and compared with the exported geometry." : "Some parts differ from the exported geometry; see below."}</p>}
      </div>}
      {res.kind === "part" && res.project && <p className="text-[13px]">Created <b>{res.project.name}</b>. Parameters, the feature tree and manual features are editable now.</p>}
      {res.kind === "assembly" && res.assembly && <p className="text-[13px]">Created the assembly <b>{res.assembly.name}</b> with {res.mates} mate{res.mates === 1 ? "" : "s"}{res.mates_dropped ? ` (${res.mates_dropped} could not be matched and were left out)` : ""}.</p>}
      {res.kind === "program" && res.program && <p className="text-[13px]">Created the program <b>{res.program.name}</b>.</p>}
      {res.drawing_note && <p className="text-[13px] text-warning">{res.drawing_note}</p>}
      {parts.length > 0 && <ul className="divide-y divide-border rounded-lg border border-border text-[13px]">
        {parts.map(p => <li key={p.project.id + p.action} className="flex items-center gap-2 px-3 py-2">
          <span className="min-w-0 flex-1 truncate">{p.project.name}</span>
          <span className="text-[12px] text-muted">{p.action === "linked" ? "already here" : "imported"}</span>
          <VerifyBadge v={p.verification} />
        </li>)}
      </ul>}
    </div>
  );
}
