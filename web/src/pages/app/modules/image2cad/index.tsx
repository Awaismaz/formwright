import { useCallback, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Box, CheckCircle2, FileText, Image as ImageIcon, Loader2, ScanLine, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, PageLoader, StatusBadge } from "@/components/ui";
import type { ModuleAppProps } from "../registry";
import ReviewScreen from "./Review";
import { CostStrip } from "./Cost";
import { BASE, type Estimate, type UploadSummary } from "./types";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp";

export default function ImageToCad({ projectId }: ModuleAppProps) {
  const [params, setParams] = useSearchParams();
  const uid = params.get("upload");
  const pid = params.get("project") ?? projectId;
  const go = (next: { upload?: string | null }) => {
    const p: Record<string, string> = {};
    if (pid) p.project = pid;
    if (next.upload) p.upload = next.upload;
    setParams(p);
  };
  if (uid) return <ReviewScreen key={uid} uid={uid} targetProject={pid} onBack={() => go({})} />;
  return <Home targetProject={pid} onOpen={id => go({ upload: id })} />;
}

function fileToB64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(new Error("Could not read the file"));
    r.readAsDataURL(f);
  });
}

function Home({ targetProject, onOpen }: { targetProject: string | null; onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["i2c-uploads"], queryFn: () => api.get<{ items: UploadSummary[]; max_mb: number; can_edit: boolean; estimate: Estimate }>(`${BASE}/uploads`),
    refetchInterval: d => (d.state.data?.items.some(i => i.status === "reading") ? 1500 : false),
  });
  const proj = useQuery({ queryKey: ["project", targetProject], enabled: !!targetProject,
    queryFn: () => api.get<{ id: string; name: string }>(`/api/projects/${targetProject}`) });
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const send = useCallback(async (f: File | undefined) => {
    if (!f) return;
    const max = (q.data?.max_mb ?? 20) * 1024 * 1024;
    if (f.size > max) { toast.error(`${f.name} is larger than ${q.data?.max_mb ?? 20} MB.`); return; }
    setBusy(true);
    try {
      const r = await api.post<{ upload: UploadSummary }>(`${BASE}/uploads`, { filename: f.name, data_b64: await fileToB64(f) });
      await qc.invalidateQueries({ queryKey: ["i2c-uploads"] });
      onOpen(r.upload.id);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Upload failed");
    } finally { setBusy(false); }
  }, [q.data, qc, onOpen]);

  if (q.isLoading) return <PageLoader />;
  if (q.error) return <div className="p-10 text-center text-sm text-muted">{(q.error as Error).message}</div>;
  const items = q.data?.items ?? [];
  const canEdit = q.data?.can_edit ?? false;

  const remove = async (u: UploadSummary) => {
    if (!window.confirm(`Delete “${u.name}” and its review? Models already created are kept.`)) return;
    try { await api.del(`${BASE}/uploads/${u.id}`); await qc.invalidateQueries({ queryKey: ["i2c-uploads"] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Delete failed"); }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary-soft text-primary"><ScanLine className="h-5 w-5" /></div>
        <div>
          <div className="flex items-center gap-2"><h1 className="text-[22px] font-semibold tracking-tight">Image &amp; Drawing to CAD</h1><StatusBadge status="live" /></div>
          <p className="mt-0.5 text-sm text-muted">We never guess scale. You see exactly what was read and what is missing before anything is modelled.</p>
        </div>
      </div>

      <ol className="mb-5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted" aria-label="How it works">
        {["Upload", "Review what we read", "Answer what's missing", "Confirm one real size", "Model in the Design Studio"].map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            {i > 0 && <ArrowRight className="h-3 w-3 text-border" />}
            <span className="flex h-[18px] w-[18px] items-center justify-center rounded-full bg-primary-soft text-[10.5px] font-bold text-primary">{i + 1}</span>{s}
          </li>
        ))}
      </ol>

      {targetProject && proj.data && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/25 bg-primary-soft/60 px-3.5 py-2.5 text-[13px]">
          <Box className="h-4 w-4 text-primary" />The model will be built in <b>{proj.data.name}</b>. You can change this on the review screen.
        </div>
      )}

      {canEdit && (
        <div
          onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={e => { e.preventDefault(); setDrag(false); void send(e.dataTransfer.files[0]); }}
          className={cx("relative overflow-hidden rounded-xl border-2 border-dashed transition",
            drag ? "border-primary bg-primary-soft/60" : "border-border bg-panel hover:border-primary/50")}
          data-testid="dropzone">
          <div className="pointer-events-none absolute inset-0 opacity-[.35] [background-image:linear-gradient(rgb(var(--border))_1px,transparent_1px),linear-gradient(90deg,rgb(var(--border))_1px,transparent_1px)] [background-size:24px_24px]" />
          <div className="relative flex flex-col items-center gap-2.5 px-6 py-8 text-center">
            {busy ? <Loader2 className="h-8 w-8 animate-spin text-primary" /> : <Upload className="h-8 w-8 text-primary" />}
            <div className="text-[15px] font-semibold">{busy ? "Uploading…" : "Drop a drawing, sketch or photo"}</div>
            <div className="max-w-xl text-[13px] text-muted">
              PDF drawings (vector or scanned, up to {q.data?.max_mb ?? 20} MB) or PNG, JPG and WebP images (up to 12 MB).
              Vector PDFs are read exactly from their text, with no tokens. Scans, sketches and photos are read by AI vision.
            </div>
            {q.data?.estimate && <CostStrip e={q.data.estimate} />}
            <button type="button" disabled={busy} onClick={() => input.current?.click()}
              className="pointer-events-auto mt-1 inline-flex h-9 items-center gap-2 rounded border border-transparent bg-primary px-4 text-sm font-medium text-primary-fg shadow-sm hover:brightness-110 disabled:opacity-50">
              Choose a file
            </button>
            <input ref={input} type="file" accept={ACCEPT} className="hidden" data-testid="file-input"
              onChange={e => { void send(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
        </div>
      )}

      <div className="mt-8">
        <div className="label mb-2">Your uploads</div>
        {items.length === 0 ? (
          <div className="rounded-lg border border-border bg-panel px-4 py-8 text-center text-sm text-muted">Nothing uploaded yet.</div>
        ) : (
          <div className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-panel">
            {items.map(u => <Row key={u.id} u={u} onOpen={onOpen} onDelete={canEdit ? () => void remove(u) : undefined} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusChip({ u }: { u: UploadSummary }) {
  if (u.status === "reading") return <Badge tone="primary"><Loader2 className="h-3 w-3 animate-spin" />{u.step ?? "Reading"}</Badge>;
  if (u.status === "failed") return <Badge tone="danger"><AlertTriangle className="h-3 w-3" />Couldn't read</Badge>;
  if (u.status === "created") return <Badge tone="success"><CheckCircle2 className="h-3 w-3" />Model requested</Badge>;
  const open = u.counts?.open ?? 0;
  return open > 0 ? <Badge tone="warning">{open} to answer</Badge> : <Badge tone="success">Ready to model</Badge>;
}

function Row({ u, onOpen, onDelete }: { u: UploadSummary; onOpen: (id: string) => void; onDelete?: () => void }) {
  return (
    <div className="group flex items-center gap-3 px-3 py-2.5 hover:bg-panel2" data-upload={u.id}>
      <button type="button" onClick={() => onOpen(u.id)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <div className="flex h-12 w-16 shrink-0 items-center justify-center overflow-hidden rounded border border-border bg-white">
          {u.preview ? <img src={u.preview} alt="" className="h-full w-full object-contain" />
            : u.type === "pdf" ? <FileText className="h-5 w-5 text-muted" /> : <ImageIcon className="h-5 w-5 text-muted" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-medium">{u.name}</div>
          <div className="truncate text-xs text-muted">
            {u.type.toUpperCase()} · {u.method === "vector" ? "read from drawing text" : u.method === "vision" ? "read by AI vision" : "—"}
            {u.counts ? ` · ${u.counts.dims} values` : ""} · {ago(u.created_at)}
          </div>
          {u.status === "failed" && u.error && <div className="truncate text-xs text-danger">{u.error}</div>}
        </div>
        {u.roundtrip && u.roundtrip.checked > 0 && (
          <span className={cx("text-[12px] tabular-nums", u.roundtrip.matched === u.roundtrip.checked ? "text-success" : "text-warning")}
            title="Confirmed values found on the model's drawing">{u.roundtrip.matched}/{u.roundtrip.checked} on the model</span>
        )}
        <StatusChip u={u} />
      </button>
      {u.status === "created" && u.project_id && (
        <Link to={`/app/projects/${u.project_id}`} className="inline-flex items-center gap-1 text-[12.5px] text-primary hover:underline">Open in Studio<ArrowRight className="h-3.5 w-3.5" /></Link>
      )}
      {onDelete && u.status !== "reading" && (
        <button type="button" onClick={onDelete} aria-label="Delete upload" title="Delete"
          className="rounded p-1.5 text-muted opacity-0 hover:bg-danger/10 hover:text-danger group-hover:opacity-100"><Trash2 className="h-4 w-4" /></button>
      )}
    </div>
  );
}
