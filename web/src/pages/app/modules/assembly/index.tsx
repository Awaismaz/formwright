import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Boxes, Info, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { Button, EmptyState, Input, Modal, PageLoader, Spinner, StatusBadge } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";
import type { ModuleAppProps } from "../registry";
import type { AsmSummary, AsmView } from "./types";
import { SolveChip } from "./bits";
import Workspace from "./Workspace";
import { FileButtons } from "@/components/NativeExport";

export const BASE = "/api/m/assembly";

export default function AssemblyStudio({ projectId }: ModuleAppProps) {
  const [params, setParams] = useSearchParams();
  const aid = params.get("assembly");
  const pid = params.get("project") ?? projectId;
  const open = (id: string | null) => {
    const next = new URLSearchParams(params);
    next.delete("project");
    if (id) next.set("assembly", id); else next.delete("assembly");
    setParams(next, { replace: !id });
  };
  if (aid) return <Workspace key={aid} aid={aid} onClose={() => open(null)} />;
  if (pid) return <OpenForProject pid={pid} onOpen={open} />;
  return <AssemblyList onOpen={open} />;
}

/** Opened from a project (Studio → Make): reuse that project's assembly, or start one with the part fixed. */
function OpenForProject({ pid, onOpen }: { pid: string; onOpen: (id: string | null) => void }) {
  const started = useRef(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [stage, setStage] = useState<"find" | "engine" | "snapshot">("find");
  const [t0] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const r = await api.get<{ assembly: AsmSummary | null }>(`${BASE}/for-project/${pid}`);
        if (r.assembly) { onOpen(r.assembly.id); return; }
        setStage("engine");
        await api.post(`${BASE}/warm`).catch(() => undefined);
        setStage("snapshot");
        const v = await api.post<AsmView>(`${BASE}/assemblies`, { project_id: pid });
        onOpen(v.assembly.id);
      } catch (e) { setErr(e as ApiError); }
    })();
  }, [pid, onOpen]);
  if (err) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState icon={<Boxes className="h-5 w-5" />} title={err.status === 409 ? "No verified build yet" : "Can't open the assembly"}
          body={err.message} action={<div className="flex gap-2">
            {err.status === 409 && <Link to={`/app/projects/${pid}`}><Button>Open in Design Studio</Button></Link>}
            <Button variant="secondary" onClick={() => onOpen(null)}>All assemblies</Button></div>} />
      </div>
    );
  }
  const steps: { key: typeof stage; label: string }[] = [
    { key: "find", label: "Looking for this project's assembly" },
    { key: "engine", label: "Starting the geometry engine" },
    { key: "snapshot", label: "Snapshotting the part: exact faces, recognised holes" },
  ];
  const at = steps.findIndex(s => s.key === stage);
  return (
    <div className="flex h-full items-center justify-center p-8" data-testid="asm-preparing">
      <div className="w-[min(420px,100%)] rounded-lg border border-border bg-panel p-5 shadow-card">
        <div className="mb-3 flex items-center gap-2 text-[14px] font-semibold"><Boxes className="h-4 w-4 text-primary" />Preparing the assembly
          <span className="ml-auto text-[12px] font-normal tabular-nums text-muted">{Math.round((now - t0) / 1000)} s</span></div>
        <ol className="space-y-2 text-[13px]">
          {steps.map((s, k) => (
            <li key={s.key} className={k > at ? "text-muted/60" : k < at ? "text-muted" : "font-medium"}>
              <span className="inline-flex items-center gap-2">{k === at ? <Spinner className="h-3.5 w-3.5" /> : <span className="inline-block h-3.5 w-3.5 text-center">{k < at ? "✓" : "·"}</span>}{s.label}</span>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-[11.5px] leading-snug text-muted">The first start on this server loads the CAD kernel and can take about half a
          minute. After that, inserting parts and solving mates takes well under a second.</p>
      </div>
    </div>
  );
}

function AssemblyList({ onOpen }: { onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["asm-list"], queryFn: () => api.get<{ items: AsmSummary[] }>(`${BASE}/assemblies`) });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState<AsmSummary | null>(null);
  useEffect(() => { api.post(`${BASE}/warm`).catch(() => undefined); }, []);  // start the geometry engine early (AMI-08)
  if (q.isLoading) return <PageLoader />;
  if (q.error) return <div className="p-10 text-center text-sm text-muted">{(q.error as Error).message}</div>;
  const items = q.data?.items ?? [];
  const create = async () => {
    setBusy(true);
    try {
      const v = await api.post<AsmView>(`${BASE}/assemblies`, { name: name.trim() || null });
      onOpen(v.assembly.id);
    } catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary-soft text-primary"><Boxes className="h-5 w-5" /></div>
          <div>
            <div className="flex items-center gap-2"><h1 className="text-[22px] font-semibold tracking-tight">Assembly Studio</h1><StatusBadge status="live" /></div>
            <p className="mt-0.5 text-sm text-muted">Put verified parts and standard components together, check fits and clashes, and fasten them.</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FileButtons ext="fwasm" openOnly size="md" />
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New assembly</Button>
        </div>
      </div>
      <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-panel p-3.5 text-[13px] text-muted">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div>Parts come in at their latest verified build and stay pinned to it until you refresh. Mates are solved exactly and the
          assembly tells you when a part can still move or a mate conflicts. Interference volumes and clearances are exact on the
          nominal geometry. Fastener proposals follow ISO tables and stated rules, and are marked <b>verify</b>: they are not a
          joint calculation.</div>
      </div>
      {items.length === 0 ? (
        <EmptyState icon={<Boxes className="h-5 w-5" />} title="No assemblies yet"
          body="Start an empty assembly, or open one from a project's Make tab so its part comes in fixed at the origin."
          action={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New assembly</Button>} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(a => (
            <div key={a.id} className="card group relative flex flex-col overflow-hidden transition hover:-translate-y-0.5 hover:shadow-pop">
              <button type="button" onClick={() => onOpen(a.id)} data-assembly={a.id} className="flex flex-1 flex-col text-left">
                <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-border">
                  {a.thumbnail ? (a.own_thumbnail ? <img src={a.thumbnail} alt="" className="absolute inset-0 h-full w-full object-contain p-2 transition group-hover:scale-[1.02]" /> : <IsoThumb src={a.thumbnail} />)
                    : <Boxes className="h-10 w-10 text-muted/50" />}
                  <span className="absolute left-2 top-2 rounded bg-panel/90 px-1.5 py-0.5 text-[11px] font-medium text-muted shadow-sm">{a.instances} parts · {a.mates} mates</span>
                </div>
                <div className="flex flex-1 flex-col gap-2 p-3.5">
                  <div className="truncate text-sm font-semibold">{a.name}</div>
                  {(!!a.broken_mates || !!a.stale_parts || !!a.stacks_to_check) && (
                    <div className="flex flex-wrap gap-1 text-[11px] font-medium">
                      {!!a.broken_mates && <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-1.5 py-px text-danger"><AlertTriangle className="h-3 w-3" />{a.broken_mates} broken mate{a.broken_mates > 1 ? "s" : ""}</span>}
                      {!!a.stale_parts && <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-1.5 py-px text-warning"><RefreshCw className="h-3 w-3" />{a.stale_parts === 1 ? "part updated" : `${a.stale_parts} parts updated`}</span>}
                      {!!a.stacks_to_check && <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-1.5 py-px text-warning">{a.stacks_to_check} stack{a.stacks_to_check > 1 ? "s" : ""} to check</span>}
                    </div>
                  )}
                  <div className="mt-auto flex items-center justify-between gap-2 text-xs text-muted">
                    {a.status && a.instances ? <SolveChip status={a.status} compact dof={a.dof} spins={a.free_spins} /> : <span>Empty</span>}<span>{ago(a.updated_at)}</span>
                  </div>
                </div>
              </button>
              <button type="button" title="Delete assembly" onClick={() => setDel(a)}
                className="absolute right-2 top-2 hidden rounded bg-panel/90 p-1.5 text-muted shadow-sm hover:text-danger group-hover:block"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
      )}
      <Modal open={creating} onOpenChange={setCreating} title="New assembly" description="You can insert project parts and Toolbox components next."
        footer={<><Button variant="secondary" onClick={() => setCreating(false)}>Cancel</Button><Button loading={busy} onClick={create}>Create</Button></>}>
        <Input autoFocus placeholder="Assembly name" value={name} maxLength={120} onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") create(); }} />
      </Modal>
      <Modal open={!!del} onOpenChange={o => !o && setDel(null)} title="Delete assembly?"
        description={del ? `"${del.name}" and its exports will be deleted. The parts' projects are not affected.` : undefined}
        footer={<><Button variant="secondary" onClick={() => setDel(null)}>Cancel</Button>
          <Button variant="danger" onClick={async () => {
            if (!del) return;
            try { await api.del(`${BASE}/assemblies/${del.id}`); qc.invalidateQueries({ queryKey: ["asm-list"] }); toast.success("Assembly deleted"); }
            catch (e) { toast.error((e as Error).message); }
            setDel(null);
          }}>Delete</Button></>} />
    </div>
  );
}
