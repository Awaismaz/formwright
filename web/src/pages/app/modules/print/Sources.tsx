import { useRef, useState } from "react";
import { FileUp, Printer, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import type { Project } from "@/lib/types";
import { Badge, Button, Card, Modal, Spinner } from "@/components/ui";
import { PartCard } from "../ModuleHeader";
import type { UploadMeta } from "./types";
import type { Src } from "./index";

async function toB64(file: File): Promise<string> {
  const buf = new Uint8Array(await file.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function SourcePicker({ projects, uploads, loading, onPick, onUpload, onDeleted, canEdit }: {
  projects: Project[]; uploads: UploadMeta[]; loading: boolean; onPick: (s: Src) => void; onUpload?: () => void;
  onDeleted: () => void; canEdit: boolean;
}) {
  const built = projects.filter(p => p.builds > 0 && p.last_status?.ok);
  const other = projects.filter(p => !(p.builds > 0 && p.last_status?.ok));
  const del = async (u: UploadMeta) => {
    try { await api.del(`/api/m/print/uploads/${u.id}`); onDeleted(); toast.success(`Deleted ${u.name}`); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Delete failed"); }
  };
  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[20px] font-semibold tracking-tight">Prepare a part for 3D printing</h2>
          <p className="mt-1 max-w-2xl text-sm text-muted">Pick a project's verified model (meshed from the exact geometry at a tolerance you choose) or upload an STL, OBJ or 3MF. You get watertight and wall-thickness checks, an overhang map, ranked print orientations and oriented STL / 3MF exports.</p>
        </div>
        {onUpload && <Button icon={<Upload className="h-4 w-4" />} onClick={onUpload}>Upload mesh</Button>}
      </div>

      <div className="mt-7 label">Projects with a verified model</div>
      {loading ? <div className="mt-4"><Spinner /></div> : built.length === 0 ? (
        <Card className="mt-3 p-6 text-sm text-muted">No built projects yet. Build a part in the Design Studio, or upload a mesh.</Card>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {built.map(p => <PartCard key={p.id} id={p.id} name={p.name} thumbnail={p.thumbnail} version={p.last_status?.build_id ?? 0} updatedAt={p.updated_at}
            sub={p.last_status?.material && p.last_status.material !== "unspecified" ? String(p.last_status.material) : "Material not set"}
            status={<Badge tone="success">Verified model</Badge>} onPick={id => onPick({ kind: "projects", id })} />)}
        </div>
      )}
      {other.length > 0 && <p className="mt-2 text-[12px] text-muted">{other.length} project(s) without a verified build are hidden.</p>}

      <div className="mt-8 label">Uploaded meshes</div>
      {uploads.length === 0 ? (
        <Card className="mt-3 flex items-center gap-4 p-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-soft text-primary"><FileUp className="h-5 w-5" /></div>
          <div className="flex-1 text-sm text-muted">Upload an STL, OBJ or 3MF from another tool to check and repair it before slicing.</div>
          {onUpload && <Button variant="secondary" onClick={onUpload}>Upload</Button>}
        </Card>
      ) : (
        <Card className="mt-3 divide-y divide-border">
          {uploads.map(u => (
            <div key={u.id} className="flex items-center gap-3 px-4 py-2.5">
              <Printer className="h-4 w-4 text-muted" />
              <button className="min-w-0 flex-1 truncate text-left text-[13px] font-medium hover:text-primary" onClick={() => onPick({ kind: "uploads", id: u.id })} data-upload={u.id}>{u.name}</button>
              <span className="text-[12px] text-muted">{u.format.replace("-", " ").toUpperCase()} · {u.triangles.toLocaleString()} triangles · {u.units}</span>
              {u.repaired && <Badge tone="success">Repaired</Badge>}
              <span className="w-20 text-right text-[12px] text-muted">{ago(u.created_at)}</span>
              {canEdit && <button aria-label={`Delete ${u.name}`} onClick={() => del(u)} className="rounded p-1 text-muted hover:bg-danger/10 hover:text-danger"><Trash2 className="h-4 w-4" /></button>}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

export function UploadDialog({ open, onOpenChange, onDone, maxMb }: { open: boolean; onOpenChange: (o: boolean) => void; onDone: (u: UploadMeta) => void; maxMb: number }) {
  const [file, setFile] = useState<File | null>(null);
  const [units, setUnits] = useState("mm");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const is3mf = file?.name.toLowerCase().endsWith(".3mf");
  const submit = async () => {
    if (!file) return;
    if (file.size > maxMb * 1024 * 1024) { toast.error(`The file is larger than ${maxMb} MB`); return; }
    setBusy(true);
    try {
      const u = await api.post<UploadMeta>("/api/m/print/uploads", { filename: file.name, data_b64: await toB64(file), units });
      onOpenChange(false); setFile(null); onDone(u);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Upload failed"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Upload a mesh" description={`STL (binary or ASCII), OBJ or 3MF, up to ${maxMb} MB.`}
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!file} loading={busy} onClick={submit} data-testid="print-upload-submit">Upload and analyse</Button></>}>
      <div
        onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); const fl = e.dataTransfer.files[0]; if (fl) setFile(fl); }}
        onClick={() => input.current?.click()}
        className={cx("flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition", drag ? "border-primary bg-primary-soft" : "border-border hover:border-primary/50")}>
        <FileUp className="h-7 w-7 text-primary" />
        <div className="mt-2 text-sm font-medium">{file ? file.name : "Drop a file here or click to choose"}</div>
        {file && <div className="text-xs text-muted">{(file.size / 1e6).toFixed(2)} MB</div>}
        <input ref={input} type="file" accept=".stl,.obj,.3mf" className="hidden" data-testid="print-upload-input" onChange={e => setFile(e.target.files?.[0] ?? null)} />
      </div>
      <label className="mt-4 block space-y-1">
        <span className="text-[13px] font-medium">File units</span>
        <select className="input" value={units} onChange={e => setUnits(e.target.value)} disabled={is3mf}>
          <option value="mm">Millimetres</option><option value="in">Inches</option><option value="cm">Centimetres</option><option value="m">Metres</option>
        </select>
        <span className="block text-xs text-muted">{is3mf ? "3MF files carry their own units." : "STL and OBJ files have no units; choose what the exporting tool used."}</span>
      </label>
    </Modal>
  );
}
