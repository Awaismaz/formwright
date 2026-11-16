import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ModuleHeader } from "../ModuleHeader";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Printer, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Project } from "@/lib/types";
import { Button, EmptyState, PageLoader, Spinner } from "@/components/ui";
import type { ModuleAppProps } from "../registry";
import type { Presets, Report, Settings, UploadMeta } from "./types";
import { PrintViewport } from "./Viewport";
import { SettingsPanel } from "./SettingsPanel";
import { ResultsPanel } from "./ResultsPanel";
import { SourcePicker, UploadDialog } from "./Sources";

export type Src = { kind: "projects" | "uploads"; id: string };

function defaults(p: Presets, process: Settings["process"] = "fdm"): Settings {
  const s = p.processes[process];
  return { process, material: s.default_material, tolerance: 0.05, overhang_deg: s.overhang_deg,
    printer_mm: [...s.printer_mm] as [number, number, number], load_dir: "", overrides: {} };
}

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export default function PrintPrep({ projectId }: ModuleAppProps) {
  const { me } = useSession();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const initial: Src | null = projectId ? { kind: "projects", id: projectId }
    : params.get("upload") ? { kind: "uploads", id: params.get("upload")! } : null;
  const [src, setSrc] = useState<Src | null>(initial);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const canEdit = me?.org?.role !== "viewer";

  const presets = useQuery({ queryKey: ["print-presets"], queryFn: () => api.get<Presets>("/api/m/print/presets"), staleTime: 600_000 });
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects") });
  const uploads = useQuery({ queryKey: ["print-uploads"], queryFn: () => api.get<{ items: UploadMeta[] }>("/api/m/print/uploads") });
  useEffect(() => { if (presets.data && !settings) setSettings(defaults(presets.data)); }, [presets.data, settings]);

  const choose = (s: Src | null) => {
    setSrc(s); setSel(null);
    const next = new URLSearchParams(params);
    next.delete("project"); next.delete("upload");
    if (s) next.set(s.kind === "projects" ? "project" : "upload", s.id);
    setParams(next, { replace: true });
  };

  const dSettings = useDebounced(settings, 450);
  const body = useMemo(() => dSettings && ({
    process: dSettings.process, material: dSettings.material, tolerance: dSettings.tolerance,
    overhang_deg: dSettings.overhang_deg, printer_mm: dSettings.printer_mm, load_dir: dSettings.load_dir || null,
    overrides: dSettings.overrides,
  }), [dSettings]);
  const analysis = useQuery({
    queryKey: ["print-analysis", src?.kind, src?.id, body],
    queryFn: () => api.post<Report>(`/api/m/print/${src!.kind}/${src!.id}/analyse`, body),
    enabled: !!src && !!body, placeholderData: keepPreviousData, retry: false, staleTime: 60_000,
  });
  const report = analysis.data && analysis.data.source.id === src?.id ? analysis.data : undefined;
  useEffect(() => {
    if (report && (!sel || !report.orientations.some(o => o.id === sel))) setSel(report.orientations[0]?.id ?? null);
  }, [report, sel]);
  const orient = report?.orientations.find(o => o.id === sel) ?? report?.orientations[0];

  if (!presets.data || !settings) return presets.error ? <div className="p-10 text-center text-muted">{(presets.error as Error).message}</div> : <PageLoader />;
  const srcName = src?.kind === "projects" ? projects.data?.items.find(p => p.id === src.id)?.name
    : uploads.data?.items.find(u => u.id === src?.id)?.name;
  const err = analysis.error instanceof ApiError ? analysis.error : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ModuleHeader code="print" icon={<Printer className="h-4 w-4" />} title="3D Print Prep" projectId={src?.kind === "projects" ? src.id : null} projectName={srcName}
        projects={projects.data?.items.filter(p => p.builds > 0 && p.last_status?.ok).map(p => ({ id: p.id, name: p.name }))}
        onSwitch={id => choose(id ? { kind: "projects", id } : null)}
        actions={<>
          {src?.kind === "uploads" && <Button size="sm" variant="secondary" icon={<FolderOpen className="h-4 w-4" />} onClick={() => choose(null)}>Change source</Button>}
          {canEdit && <Button size="sm" variant="secondary" icon={<Upload className="h-4 w-4" />} onClick={() => setUploadOpen(true)}>Upload mesh</Button>}
        </>}>
        {src?.kind === "uploads" && <div className="flex min-w-0 items-center gap-2 rounded border border-border bg-panel2 px-2.5 py-1 text-[12.5px]">
          <Upload className="h-3.5 w-3.5 text-muted" /><span className="max-w-[260px] truncate font-medium">{srcName ?? report?.source.name ?? "…"}</span>
          <span className="text-muted">uploaded mesh</span></div>}
      </ModuleHeader>

      {!src ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <SourcePicker projects={projects.data?.items ?? []} uploads={uploads.data?.items ?? []} loading={projects.isLoading}
            onPick={choose} onUpload={canEdit ? () => setUploadOpen(true) : undefined}
            onDeleted={() => qc.invalidateQueries({ queryKey: ["print-uploads"] })} canEdit={canEdit} />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[256px_minmax(0,1fr)_340px] 2xl:grid-cols-[288px_minmax(0,1fr)_392px] lg:overflow-hidden">
          <aside className="min-h-0 overflow-y-auto border-r border-border bg-panel">
            <SettingsPanel presets={presets.data} value={settings} onChange={setSettings} isProject={src.kind === "projects"}
              onReset={() => setSettings(defaults(presets.data!, settings.process))} busy={analysis.isFetching} />
          </aside>
          <section className="relative min-h-[420px] min-w-0">
            {err && !report ? (
              <div className="flex h-full items-center justify-center p-8">
                <EmptyState icon={<Printer className="h-5 w-5" />} title={err.status === 409 ? "No verified model yet" : "Can't analyse this source"}
                  body={err.message} action={src.kind === "projects" && err.status === 409 ? <Link to={`/app/projects/${src.id}`}><Button>Open in Design Studio</Button></Link> : undefined} />
              </div>
            ) : report ? (
              <PrintViewport src={src} report={report} orient={orient ?? null} />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-muted"><Spinner className="h-6 w-6" />Tessellating and analysing the model…</div>
            )}
            {analysis.isFetching && report && <div className="absolute right-3 top-14 flex items-center gap-2 rounded-full border border-border bg-panel/95 px-3 py-1 text-xs text-muted shadow-card"><Spinner className="h-3.5 w-3.5" />Updating analysis…</div>}
          </section>
          <aside className="min-h-0 overflow-y-auto border-l border-border bg-panel">
            {report ? <ResultsPanel src={src} report={report} orient={orient ?? null} selected={sel} onSelect={setSel} settings={settings}
              canEdit={canEdit} onRepaired={() => { qc.invalidateQueries({ queryKey: ["print-analysis"] }); qc.invalidateQueries({ queryKey: ["print-uploads"] }); }} />
              : <div className="p-6 text-sm text-muted">{err ? "" : "Results appear here."}</div>}
          </aside>
        </div>
      )}
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} maxMb={presets.data.max_upload_mb}
        onDone={(u) => { qc.invalidateQueries({ queryKey: ["print-uploads"] }); choose({ kind: "uploads", id: u.id }); toast.success(`Uploaded ${u.name}`); }} />
    </div>
  );
}
