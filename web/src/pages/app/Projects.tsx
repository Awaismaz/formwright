import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, FolderKanban, LayoutGrid, List, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";
import { ago } from "@/lib/format";
import { Button, EmptyState, Input, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Modal, PageHeader, PageLoader, StatusBadge } from "@/components/ui";
import ProjectCard, { ProjectStatus } from "@/components/ProjectCard";
import NewProjectDialog from "@/components/NewProjectDialog";
import { cx } from "@/lib/format";

export default function Projects() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const [archived, setArchived] = useState(false);
  const [q, setQ] = useState("");
  const [view, setView] = useState<"grid" | "list">(() => { try { return (localStorage.getItem("fw_pview") as "grid" | "list") || "grid"; } catch { return "grid"; } });
  const [newOpen, setNewOpen] = useState(params.get("new") === "1");
  const [confirm, setConfirm] = useState<Project | null>(null);
  const list = useQuery({ queryKey: ["projects", archived], queryFn: () => api.get<{ items: Project[] }>(`/api/projects?archived=${archived}`) });

  useEffect(() => { if (params.get("new") === "1") { setNewOpen(true); params.delete("new"); setParams(params, { replace: true }); } }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem("fw_pview", view); } catch { /* ignore */ } }, [view]);

  const items = useMemo(() => (list.data?.items ?? []).filter(p => !q || p.name.toLowerCase().includes(q.toLowerCase()) || p.description.toLowerCase().includes(q.toLowerCase())), [list.data, q]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["projects"] });
  const setArch = async (p: Project, v: boolean) => {
    try { await api.patch(`/api/projects/${p.id}`, { archived: v }); toast.success(v ? "Project archived" : "Project restored"); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const del = async () => {
    if (!confirm) return;
    try { await api.del(`/api/projects/${confirm.id}`); toast.success("Project deleted"); setConfirm(null); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const rowMenu = (p: Project) => (
    <Menu>
      <MenuTrigger asChild><button className="rounded p-1.5 text-muted hover:bg-text/5" aria-label="Project actions" onClick={e => e.preventDefault()}><MoreHorizontal className="h-4 w-4" /></button></MenuTrigger>
      <MenuContent>
        {archived ? <MenuItem icon={<ArchiveRestore />} onSelect={() => setArch(p, false)}>Restore</MenuItem> : <MenuItem icon={<Archive />} onSelect={() => setArch(p, true)}>Archive</MenuItem>}
        <MenuSeparator />
        <MenuItem icon={<Trash2 />} danger onSelect={() => setConfirm(p)}>Delete…</MenuItem>
      </MenuContent>
    </Menu>
  );

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader title="Projects" eyebrow={<StatusBadge status="live" />} subtitle="Each project holds a design conversation, its parametric model, checks, revisions and exports."
        actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New project</Button>} />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search projects" className="pl-9" /></div>
        <div className="inline-flex rounded-lg border border-border bg-panel p-0.5 text-sm">
          {[["Active", false], ["Archived", true]].map(([l, v]) => (
            <button key={l as string} onClick={() => setArchived(v as boolean)} className={cx("rounded px-3 py-1", archived === v ? "bg-primary text-white" : "text-muted")}>{l as string}</button>))}
        </div>
        <div className="ml-auto inline-flex rounded-lg border border-border bg-panel p-0.5">
          <button onClick={() => setView("grid")} className={cx("rounded p-1.5", view === "grid" ? "bg-panel2 text-text" : "text-muted")} aria-label="Grid view"><LayoutGrid className="h-4 w-4" /></button>
          <button onClick={() => setView("list")} className={cx("rounded p-1.5", view === "list" ? "bg-panel2 text-text" : "text-muted")} aria-label="List view"><List className="h-4 w-4" /></button>
        </div>
      </div>
      {list.isLoading ? <PageLoader /> : items.length === 0 ? (
        <EmptyState icon={<FolderKanban className="h-6 w-6" />} title={q ? "No matching projects" : archived ? "No archived projects" : "No projects yet"}
          body={!q && !archived ? "Start with a template or a blank brief. The design agent will model, verify and show your part live." : undefined}
          action={!archived && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New project</Button>} />
      ) : view === "grid" ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(p => <div key={p.id} className="relative"><ProjectCard p={p} /><div className="absolute right-2 top-2 rounded bg-panel/90">{rowMenu(p)}</div></div>)}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel2 text-left text-xs text-muted"><tr><th className="px-4 py-2.5 font-medium">Name</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">Size (mm)</th><th className="px-4 py-2.5 font-medium">Builds</th><th className="px-4 py-2.5 font-medium">Updated</th><th /></tr></thead>
            <tbody className="divide-y divide-border">
              {items.map(p => (
                <tr key={p.id} className="hover:bg-panel2/60">
                  <td className="px-4 py-2.5"><Link to={`/app/projects/${p.id}`} className="font-medium hover:text-primary">{p.name}</Link><div className="text-xs text-muted">{p.created_by ? `by ${p.created_by}` : ""}</div></td>
                  <td className="px-4 py-2.5"><ProjectStatus p={p} /></td>
                  <td className="px-4 py-2.5 tabular-nums text-muted">{p.last_status?.fingerprint?.bbox?.map(n => Math.round(n)).join(" × ") ?? "—"}</td>
                  <td className="px-4 py-2.5 tabular-nums">{p.builds}</td>
                  <td className="px-4 py-2.5 text-muted">{ago(p.updated_at)}</td>
                  <td className="px-4 py-2.5 text-right">{rowMenu(p)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <NewProjectDialog open={newOpen} onOpenChange={setNewOpen} />
      <Modal open={!!confirm} onOpenChange={o => !o && setConfirm(null)} title="Delete project?"
        description={<>“{confirm?.name}”, its model files, revisions and conversation will be permanently deleted.</>}
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" onClick={del}>Delete project</Button></>} />
    </div>
  );
}
