import { useRef, useState } from "react";
import { FileUp, ScanSearch, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button, Modal } from "@/components/ui";

export interface Recognition {
  error?: string; summary?: string[]; bbox?: number[]; volume_mm3?: number; faces?: number; unrecognised?: Record<string, number>;
  holes?: unknown[]; patterns?: unknown[]; fillets?: unknown[]; chamfers?: unknown[];
}

export async function fileToB64(f: File): Promise<string> {
  const buf = new Uint8Array(await f.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function RecognitionView({ rec }: { rec: Recognition }) {
  if (rec.error) return <p className="text-[13px] text-danger">Feature recognition failed: {rec.error}</p>;
  return (
    <div className="text-[13px]">
      <div className="mb-1.5 flex items-center gap-1.5 font-medium"><ScanSearch className="h-4 w-4 text-primary" />Recognised features</div>
      <ul className="space-y-1">{(rec.summary ?? []).map((l, i) => <li key={i} className={/^Not recognised/.test(l) ? "text-warning" : ""}>• {l}</li>)}</ul>
      {rec.bbox && <p className="mt-2 text-[12px] text-muted">{rec.bbox.join(" × ")} mm · {rec.faces} faces · {rec.volume_mm3?.toLocaleString()} mm³</p>}
    </div>
  );
}

/** Import a STEP file into this project, show recognised features, offer parametric rebuild (deterministic draft or agent). */
export default function StepImport({ project, onClose, onDone, onAgentPrompt }: {
  project: Project; onClose: () => void; onDone: () => void; onAgentPrompt?: (prompt: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"" | "import" | "agent">("");
  const [rec, setRec] = useState<Recognition | null>(null);

  const doImport = async () => {
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) { toast.error("STEP files up to 50 MB are supported"); return; }
    setBusy("import");
    try {
      const r = await api.post<{ recognition: Recognition; build_s: number }>(`/api/projects/${project.id}/import-step`, { filename: file.name, data_b64: await fileToB64(file) });
      track("step_imported", {}); toast.success(`Imported ${file.name}`); setRec(r.recognition ?? {});
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Import failed"); }
    finally { setBusy(""); }
  };
  const agent = async () => {
    setBusy("agent");
    try {
      await api.post(`/api/projects/${project.id}/recognition/rebuild`);
      onAgentPrompt?.(""); toast.success("The design agent is rebuilding it. Follow along in the chat"); onDone();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not start the agent"); }
    finally { setBusy(""); }
  };

  return (
    <Modal open onOpenChange={v => !v && onClose()} title={<span className="flex items-center gap-2"><FileUp className="h-4 w-4 text-primary" />Import STEP</span>}
      description="Bring in a STEP (AP203/AP214/AP242) solid. It stays geometrically exact; recognised features become editable on top of it."
      footer={rec ? <>
        <Button variant="secondary" loading={busy === "agent"} disabled={!!busy || !!rec.error} icon={<Sparkles className="h-4 w-4" />} onClick={agent}>Rebuild fully parametric (AI)</Button>
        <Button onClick={onDone}>Done</Button>
      </> : <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button loading={busy === "import"} disabled={!file} onClick={doImport}>Import</Button>
      </>}>
      {rec ? <>
        <RecognitionView rec={rec} />
        <p className="mt-3 rounded-md bg-panel2 px-3 py-2 text-[12px] text-muted">
          The model is the <b>exact imported solid</b> ("Imported blank"). Recognised holes and patterns are editable in <b>Params</b>; everything else stays in the blank and can still be changed by the design agent or with manual features. Use <b>Recognize features</b> in the tree for an AI classification, or rebuild it fully parametric with the agent (compared with the original by check CHK-09).
        </p>
      </> : <>
        <input ref={fileRef} type="file" accept=".step,.stp,.STEP,.STP" hidden onChange={e => setFile(e.target.files?.[0] ?? null)} />
        <button onClick={() => fileRef.current?.click()}
          onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) setFile(f); }}
          className="flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed border-border px-4 py-8 text-[13px] text-muted hover:border-primary hover:text-primary">
          <FileUp className="h-8 w-8" />{file ? <span className="font-medium text-text">{file.name} · {(file.size / 1024).toFixed(0)} KB</span> : "Choose or drop a .step / .stp file (max 50 MB)"}
        </button>
        {project.builds > 0 && <p className="mt-3 text-[12px] text-warning">This replaces the current model in this project (it stays available under Revisions).</p>}
      </>}
    </Modal>
  );
}
