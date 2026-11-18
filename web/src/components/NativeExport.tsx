import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileDown, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { downloadNative, type Verification } from "@/lib/native";
import { Button, Modal, Toggle } from "./ui";
import { NativeImportButton, VerifyBadge } from "./NativeImport";

/** Download a native file and say so (or why not). */
export async function saveNative(url: string, fallback: string, _format: string): Promise<boolean> {
  try {
    const name = await downloadNative(url, fallback);
    toast.success(`Downloaded ${name}`);
    return true;
  } catch (e) {
    toast.error(e instanceof ApiError ? e.message : "The download failed");
    return false;
  }
}

/** "Download as .fwpart": the full parametric model, with the choice of what else to include. */
export function PartExportDialog({ open, onOpenChange, projectId, name }: { open: boolean; onOpenChange: (v: boolean) => void; projectId: string; name: string }) {
  const [history, setHistory] = useState(true);
  const [refs, setRefs] = useState(true);
  const [chat, setChat] = useState(false);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const q = new URLSearchParams({ history: history ? "1" : "0", refs: refs ? "1" : "0", chat: chat ? "1" : "0" });
    const ok = await saveNative(`/api/native/projects/${projectId}/export?${q}`, `${name}.fwpart`, "fwpart");
    setBusy(false);
    if (ok) onOpenChange(false);
  };
  const row = (label: string, hint: string, v: boolean, set: (v: boolean) => void) => (
    <label className="flex items-start justify-between gap-4 py-2">
      <span><span className="block text-[13.5px] font-medium">{label}</span><span className="block text-[12px] text-muted">{hint}</span></span>
      <Toggle checked={v} onChange={set} label={label} />
    </label>);
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Download as Formwright part (.fwpart)"
      description="The full parametric model: parameters, feature tree, manual features and sketches, plus the exact geometry. Another Formwright workspace opens it fully editable, with no feature recognition."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button icon={<Download className="h-4 w-4" />} loading={busy} onClick={() => void go()}>Download .fwpart</Button></>}>
      <div className="divide-y divide-border">
        {row("Revision history", "Every saved revision of the model, with what changed and why.", history, setHistory)}
        {row("Reference images", "Photos and sketches attached to the design.", refs, setRefs)}
        {row("Design conversation", "Your messages and the design agent's replies. Off by default: the conversation may hold private notes.", chat, setChat)}
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-[12px] text-muted"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />Signed by this workspace, so a re-import here is recognised as unchanged.</p>
    </Modal>
  );
}

interface Provenance { file: string; trust: string; verification: Verification; imported_at: string; imported_by?: string }

/** Studio Files panel: how an imported part was verified (shown only for parts that came from a Formwright file). */
export function ImportProvenance({ projectId }: { projectId: string }) {
  const q = useQuery({ queryKey: ["native-provenance", projectId], queryFn: () => api.get<{ import: Provenance | null }>(`/api/native/projects/${projectId}/provenance`), staleTime: 60_000 });
  const p = q.data?.import;
  if (!p) return null;
  return (
    <div className="rounded-lg border border-border p-3" data-testid="import-provenance">
      <div className="flex flex-wrap items-center gap-2"><VerifyBadge v={p.verification} /><span className="text-[12px] text-muted">{p.trust === "workspace" ? "from your workspace" : "from another workspace"}</span></div>
      <div className="mt-1 truncate text-[12px] text-muted">Imported from {p.file}{p.imported_by ? ` by ${p.imported_by}` : ""}</div>
    </div>
  );
}

/** A module's file buttons, same everywhere: "Save .fwxxx" (download this work) and "Open .fwxxx" (import one). */
export function FileButtons({ ext, saveUrl, saveName, size = "sm", openOnly }: {
  ext: string; saveUrl?: string | null; saveName?: string; size?: "sm" | "md"; openOnly?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <span className="inline-flex items-center gap-1.5" data-native-files={ext}>
      {!openOnly && saveUrl && <Button size={size} variant="secondary" icon={<FileDown className="h-4 w-4" />} loading={busy} data-action="save-file"
        title={`Save this work as a Formwright file (.${ext}) to hand to anyone with Formwright`}
        onClick={async () => { setBusy(true); await saveNative(saveUrl, saveName ?? `formwright.${ext}`, ext); setBusy(false); }}>Save .{ext}</Button>}
      <NativeImportButton accept={`.${ext}`} size={size}>Open .{ext}</NativeImportButton>
    </span>
  );
}
