import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, FolderPlus, Folders } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { DesignProjectSummary } from "@/lib/designProjects";
import { ago } from "@/lib/format";
import { Button, Input, Modal } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";

export function NewDesignProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await api.post<DesignProjectSummary>("/api/design-projects", { name: name.trim(), purpose: purpose.trim() });
      await qc.invalidateQueries({ queryKey: ["design-projects"] });
      onOpenChange(false); setName(""); setPurpose("");
      nav(`/app/p/${p.id}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create the project"); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="New project"
      description="A project holds related parts. When you design one of them, the design agent knows the others: their sizes, mating features and the decisions you set for the project."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={create} loading={busy} disabled={!name.trim()}>Create project</Button></>}>
      <div className="space-y-3">
        <label className="block space-y-1.5"><span className="text-[13px] font-medium">Name</span>
          <Input autoFocus value={name} maxLength={120} onChange={e => setName(e.target.value)} placeholder="e.g. Conveyor gearbox GB-2" onKeyDown={e => e.key === "Enter" && create()} /></label>
        <label className="block space-y-1.5"><span className="text-[13px] font-medium">Purpose <span className="font-normal text-muted">(optional)</span></span>
          <textarea value={purpose} maxLength={2000} rows={3} onChange={e => setPurpose(e.target.value)} className="input h-auto py-2 text-[13px]"
            placeholder="What the parts are for, loads, environment, who it's for" /></label>
      </div>
    </Modal>);
}

/** The Projects row at the top of the Projects page (groups of related parts). */
export default function ProjectStrip({ canCreate }: { canCreate: boolean }) {
  const q = useQuery({ queryKey: ["design-projects"], queryFn: () => api.get<{ items: DesignProjectSummary[] }>("/api/design-projects") });
  const [open, setOpen] = useState(false);
  const items = q.data?.items ?? [];
  if (!q.data) return null;
  return (
    <section className="mb-7" data-design-projects>
      <div className="mb-3 flex items-center gap-2">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Folders className="h-4 w-4 text-primary" />Projects</h2>
        <span className="text-[12px] text-muted">related parts the design agent sees together</span>
        {canCreate && <Button size="sm" variant="secondary" className="ml-auto" icon={<FolderPlus className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>New project</Button>}
      </div>
      {items.length === 0 ? (
        <button onClick={() => canCreate && setOpen(true)} className="flex w-full items-center gap-3 rounded-xl border border-dashed border-border px-4 py-3 text-left text-[13px] text-muted hover:border-primary/50">
          <FolderPlus className="h-5 w-5 shrink-0 text-primary" />
          <span><span className="font-medium text-text">Group related parts into a project.</span> Ask for “the cover for the housing” and the agent already knows the housing's size and hole pattern.</span>
        </button>) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(p => (
            <Link key={p.id} to={`/app/p/${p.id}`} className="card group flex items-center gap-3 p-3 transition hover:-translate-y-0.5 hover:shadow-pop" data-design-project={p.name}>
              <div className="viewport-bg relative grid h-14 w-14 shrink-0 grid-cols-2 grid-rows-2 overflow-hidden rounded-md border border-border">
                {p.thumbnails.length ? p.thumbnails.slice(0, 4).map((t, i) => <div key={i} className="relative overflow-hidden">{t && <IsoThumb src={t} />}</div>)
                  : <Folders className="col-span-2 row-span-2 m-auto h-6 w-6 text-muted/60" />}
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1 truncate text-[13.5px] font-semibold group-hover:text-primary">{p.program_id && <Building2 className="h-3.5 w-3.5 shrink-0 text-muted" />}{p.name}</div>
                <div className="truncate text-[12px] text-muted">{p.parts} part{p.parts === 1 ? "" : "s"} · {ago(p.updated_at)}</div>
                {p.purpose && <div className="truncate text-[11.5px] text-muted">{p.purpose}</div>}
              </div>
            </Link>))}
        </div>)}
      <NewDesignProjectDialog open={open} onOpenChange={setOpen} />
    </section>);
}
