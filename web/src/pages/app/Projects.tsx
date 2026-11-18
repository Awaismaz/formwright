import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive, ArchiveRestore, Copy, Download, ExternalLink, FileDown, FileUp, FolderKanban, LayoutGrid, List, Lock, MoreHorizontal,
  Pencil, Plus, Ruler, ScanSearch, Search, Share2, Trash2, Users, X,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Project } from "@/lib/types";
import { ago, cx, PAGE, size } from "@/lib/format";
import { Button, EmptyState, Input, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Modal, PageHeader, PageLoader } from "@/components/ui";
import ProjectCard, { ProjectStatus } from "@/components/ProjectCard";
import NewProjectDialog from "@/components/NewProjectDialog";
import { MatchRow, SimilarPartsDialog, type Match } from "@/components/SimilarParts";
import { can, LEVEL_TEXT } from "@/lib/collab";
import ShareDialog from "@/components/collab/ShareDialog";
import { PartExportDialog, saveNative } from "@/components/NativeExport";
import { START_ACCEPT, startFromFile } from "@/components/StartBox";

type Sort = "updated" | "name" | "size" | "created";
const SORTS: [Sort, string][] = [["updated", "Last updated"], ["name", "Name"], ["size", "Size"], ["created", "Date created"]];
const vol = (p: Project) => p.last_status?.fingerprint?.volume ?? -1;

/** Team and access chips on a project card: who owns it, and a lock when you can only look. */
function AccessChips({ p }: { p: Project }) {
  const a = p.access;
  if (!a) return null;
  return (
    <div className="pointer-events-none absolute left-2 top-2 flex flex-wrap gap-1">
      {a.team && <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] font-semibold text-white" style={{ background: a.team.color }}><Users className="h-3 w-3" />{a.team.name}</span>}
      {!a.can_edit && <span className="inline-flex items-center gap-1 rounded bg-panel/90 px-1.5 py-0.5 text-[10.5px] font-medium text-muted" title={`You have ${LEVEL_TEXT[a.level].toLowerCase()} access`}><Lock className="h-3 w-3" />{a.can_comment ? "Comment" : "View"} only</span>}
      {a.guest && <span className="rounded bg-accent px-1.5 py-0.5 text-[10.5px] font-semibold text-white">Guest</span>}
    </div>);
}

export default function Projects() {
  const { me } = useSession();
  const units = me?.user?.preferences?.units;
  const viewer = me?.org?.role === "viewer";
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const [archived, setArchived] = useState(false);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>(() => { try { return (localStorage.getItem("fw_psort") as Sort) || "updated"; } catch { return "updated"; } });
  const [view, setView] = useState<"grid" | "list">(() => { try { return (localStorage.getItem("fw_pview") as "grid" | "list") || "grid"; } catch { return "grid"; } });
  const [newOpen, setNewOpen] = useState(params.get("new") === "1");
  const [confirm, setConfirm] = useState<Project | null>(null);
  const [renaming, setRenaming] = useState<{ p: Project; name: string } | null>(null);
  const [similar, setSimilar] = useState<string | null>(null);
  const [exporting, setExporting] = useState<Project | null>(null);
  const [drag, setDrag] = useState(false);
  const [allBusy, setAllBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const list = useQuery({ queryKey: ["projects", archived], enabled: !!me?.org, queryFn: () => api.get<{ items: Project[] }>(`/api/projects?archived=${archived}`) });
  const shared = useQuery({ queryKey: ["projects", "shared-with-me"], queryFn: () => api.get<{ items: Project[] }>("/api/shared-with-me") });
  const [sharing, setSharing] = useState<string | null>(null);

  useEffect(() => { if (params.get("new") === "1") { setNewOpen(true); params.delete("new"); setParams(params, { replace: true }); } }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const s = params.get("q"); if (s) { setQ(s); params.delete("q"); setParams(params, { replace: true }); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem("fw_pview", view); localStorage.setItem("fw_psort", sort); } catch { /* ignore */ } }, [view, sort]);

  const sizeQuery = /\d\s*(mm|in|")?\s*[x×*]\s*\d/i.test(q);
  const [debounced, setDebounced] = useState(q);
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  const bySize = useQuery({ queryKey: ["search-size", debounced], enabled: sizeQuery && debounced === q,
    queryFn: () => api.get<{ dims: number[] | null; items: Match[]; unit?: "mm" | "in" }>(`/api/search/size?q=${encodeURIComponent(debounced)}`) });
  const items = useMemo(() => {
    const s = q.toLowerCase();
    const rows = (list.data?.items ?? []).filter(p => sizeQuery || !q || p.name.toLowerCase().includes(s) || p.description.toLowerCase().includes(s)
      || (p.last_status?.material ?? "").toLowerCase().includes(s));
    const by: Record<Sort, (a: Project, b: Project) => number> = {
      updated: (a, b) => b.updated_at.localeCompare(a.updated_at), created: (a, b) => b.created_at.localeCompare(a.created_at),
      name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }), size: (a, b) => vol(b) - vol(a),
    };
    return [...rows].sort(by[sort]);
  }, [list.data, q, sizeQuery, sort]);
  const sharedOnly = useMemo(() => (shared.data?.items ?? []).filter(s => !(list.data?.items ?? []).some(p => p.id === s.id)), [shared.data, list.data]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["projects"] });
  const call = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast.success(ok); refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const del = async () => {
    if (!confirm) return;
    await call(() => api.del(`/api/projects/${confirm.id}`), "Project deleted");
    setConfirm(null);
  };
  const duplicate = async (p: Project) => {
    try { const d = await api.post<Project>(`/api/projects/${p.id}/duplicate`); toast.success(`Saved as “${d.name}”`, { action: { label: "Open", onClick: () => nav(`/app/projects/${d.id}`) } }); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not duplicate"); }
  };
  const onFile = async (f: File | undefined) => {
    if (!f || viewer) return;
    try { await startFromFile(f, nav, (list.data?.items ?? []).map(p => p.name)); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not open that file"); }
  };
  const downloadAll = async () => {
    setAllBusy(true);
    await saveNative("/api/native/projects/export-all", "projects.zip", "zip");
    setAllBusy(false);
  };
  const rename = async () => {
    if (!renaming?.name.trim()) return;
    await call(() => api.patch(`/api/projects/${renaming.p.id}`, { name: renaming.name.trim() }), "Project renamed");
    setRenaming(null);
  };
  const rowMenu = (p: Project) => (
    <Menu>
      <MenuTrigger asChild><button className="rounded p-1.5 text-muted hover:bg-text/5" aria-label={`Actions for ${p.name}`} onClick={e => e.preventDefault()}><MoreHorizontal className="h-4 w-4" /></button></MenuTrigger>
      <MenuContent>
        <MenuItem icon={<ExternalLink />} onSelect={() => window.open(`/app/projects/${p.id}`, "_blank", "noopener")}>Open in new tab</MenuItem>
        {!viewer && can(p.access, "edit") && <MenuItem icon={<Pencil />} onSelect={() => setRenaming({ p, name: p.name })}>Rename…</MenuItem>}
        {!viewer && !p.access?.guest && <MenuItem icon={<Copy />} onSelect={() => duplicate(p)}>Duplicate</MenuItem>}
        <MenuItem icon={<Share2 />} onSelect={() => setSharing(p.id)}>{can(p.access, "share") ? "Share…" : "Who has access"}</MenuItem>
        {p.builds > 0 && <MenuItem icon={<FileDown />} onSelect={() => setExporting(p)}>Download as .fwpart…</MenuItem>}
        {p.builds > 0 && !p.access?.guest && <MenuItem icon={<ScanSearch />} onSelect={() => setSimilar(p.id)}>Find similar parts</MenuItem>}
        {!viewer && can(p.access, "edit") && <><MenuSeparator />
          {archived ? <MenuItem icon={<ArchiveRestore />} onSelect={() => call(() => api.patch(`/api/projects/${p.id}`, { archived: false }), "Project restored")}>Restore</MenuItem>
            : <MenuItem icon={<Archive />} onSelect={() => call(() => api.patch(`/api/projects/${p.id}`, { archived: true }), "Project archived")}>Archive</MenuItem>}
          {can(p.access, "delete") && <MenuItem icon={<Trash2 />} danger onSelect={() => setConfirm(p)}>Delete…</MenuItem>}</>}
      </MenuContent>
    </Menu>
  );
  const unitLabel = units === "in" ? "in" : "mm";
  const dims = bySize.data?.dims;

  return (
    <div className={cx(PAGE, drag && "rounded-xl ring-2 ring-primary/40")}
      onDragOver={e => { if (!viewer && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDrag(true); } }}
      onDragLeave={e => { if (e.currentTarget === e.target) setDrag(false); }}
      onDrop={e => { e.preventDefault(); setDrag(false); void onFile(e.dataTransfer.files[0]); }}>
      <input ref={fileRef} type="file" accept={START_ACCEPT} hidden onChange={e => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
      <PageHeader title="Projects" subtitle="Each project holds a part: its model, checks, revisions, exports and design conversation."
        actions={<>
          <Button variant="secondary" icon={<Download className="h-4 w-4" />} loading={allBusy} onClick={() => void downloadAll()}
            title="Every built project as Formwright parts (.fwpart) in one zip">Download all</Button>
          {!viewer && <Button variant="secondary" icon={<FileUp className="h-4 w-4" />} onClick={() => fileRef.current?.click()}
            title="Formwright files (.fwpart, .fwasm, .fwdrw, .fwprog), STEP, drawings or photos">Import</Button>}
          {!viewer && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New project</Button>}</>} />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:max-w-xs"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input value={q} onChange={e => setQ(e.target.value)} placeholder={`Search by name, or by size: ${units === "in" ? "4.7 x 3.1 in" : "120x80x10"}`} className="px-9" aria-label="Search projects by name or size" />
          {q && <button onClick={() => setQ("")} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted hover:text-text" aria-label="Clear search"><X className="h-3.5 w-3.5" /></button>}</div>
        <div className="inline-flex rounded-lg border border-border bg-panel p-0.5 text-sm">
          {[["Active", false], ["Archived", true]].map(([l, v]) => (
            <button key={l as string} onClick={() => setArchived(v as boolean)} className={cx("rounded px-3 py-1", archived === v ? "bg-primary text-white" : "text-muted")}>{l as string}</button>))}
        </div>
        <label className="ml-auto flex items-center gap-2 text-[13px] text-muted">Sort
          <select value={sort} onChange={e => setSort(e.target.value as Sort)} className="input h-8 w-auto py-0 pr-8 text-[13px]" aria-label="Sort projects">
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></label>
        <div className="inline-flex rounded-lg border border-border bg-panel p-0.5">
          <button onClick={() => setView("grid")} className={cx("rounded p-1.5", view === "grid" ? "bg-panel2 text-text" : "text-muted")} aria-label="Grid view"><LayoutGrid className="h-4 w-4" /></button>
          <button onClick={() => setView("list")} className={cx("rounded p-1.5", view === "list" ? "bg-panel2 text-text" : "text-muted")} aria-label="Catalogue view"><List className="h-4 w-4" /></button>
        </div>
      </div>
      {sizeQuery && (
        <section className="mb-6 rounded-xl border border-border bg-panel2/60 p-4">
          <div className="mb-3 flex flex-wrap items-baseline gap-2">
            <Ruler className="h-4 w-4 self-center text-primary" />
            <h2 className="text-[14px] font-semibold">Parts sized like {dims ? size(dims, bySize.data?.unit === "in" ? "in" : units) : "…"}</h2>
            <span className="text-[12px] text-muted">any orientation · matched on the verified model's envelope</span>
          </div>
          {bySize.isLoading || debounced !== q ? <div className="py-3 text-sm text-muted">Searching…</div>
            : !bySize.data?.items.length ? <p className="text-sm text-muted">No part in this workspace has that envelope yet. <button className="link" onClick={() => setQ("")}>Clear search</button></p>
            : <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{bySize.data.items.map(m => <MatchRow key={m.project.id} m={m} />)}</div>}
        </section>)}
      {list.isLoading ? <PageLoader /> : items.length === 0 ? (
        <EmptyState icon={<FolderKanban className="h-6 w-6" />} title={q ? "No matching projects" : archived ? "No archived projects" : "No projects yet"}
          body={q ? <>Nothing is named like “{q}”. Try part of the name, or a size such as {units === "in" ? "4.7 x 3.1 in" : "120x80x10"}.</> : !archived ? "Describe a part from Home, or start from a template, a STEP file or a drawing." : undefined}
          action={q ? <Button variant="secondary" onClick={() => setQ("")}>Clear search</Button> : !archived && !viewer && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New project</Button>} />
      ) : view === "grid" ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(p => <div key={p.id} className="relative"><ProjectCard p={p} units={units} /><AccessChips p={p} /><div className="absolute right-2 top-2 rounded bg-panel/90">{rowMenu(p)}</div></div>)}
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-panel2 text-left text-xs text-muted"><tr>
              <th className="px-4 py-2.5 font-medium">Part</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">Material</th>
              <th className="px-4 py-2.5 font-medium">Envelope ({unitLabel})</th><th className="px-4 py-2.5 font-medium">Volume</th>
              <th className="px-4 py-2.5 font-medium">Builds</th><th className="px-4 py-2.5 font-medium">Updated</th><th /></tr></thead>
            <tbody className="divide-y divide-border">
              {items.map(p => {
                const v = p.last_status?.fingerprint?.volume;
                return (
                  <tr key={p.id} className="hover:bg-panel2/60">
                    <td className="px-4 py-2.5"><Link to={`/app/projects/${p.id}`} className="font-medium hover:text-primary">{p.name}</Link><div className="text-xs text-muted">{p.created_by ? `by ${p.created_by}` : ""}</div></td>
                    <td className="px-4 py-2.5"><ProjectStatus p={p} /></td>
                    <td className="max-w-[180px] truncate px-4 py-2.5 text-muted">{p.last_status?.material ?? "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums text-muted">{size(p.last_status?.fingerprint?.bbox, units).replace(/ (mm|in)$/, "") || "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums text-muted">{v ? (units === "in" ? `${(v / 16387.064).toFixed(2)} in³` : `${(v / 1000).toFixed(1)} cm³`) : "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums">{p.builds}</td>
                    <td className="px-4 py-2.5 text-muted">{ago(p.updated_at)}</td>
                    <td className="px-4 py-2.5 text-right">{rowMenu(p)}</td>
                  </tr>);
              })}
            </tbody>
          </table>
        </div>
      )}
      {!archived && !q && sharedOnly.length > 0 && (
        <section className="mt-8" data-shared-with-me>
          <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold"><Share2 className="h-4 w-4 text-primary" />Shared with me</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {sharedOnly.map(p => <div key={p.id} className="relative"><ProjectCard p={p} units={units} /><AccessChips p={p} />
              {p.workspace && p.workspace !== me?.org?.name && <span className="absolute bottom-[4.6rem] left-2 rounded bg-panel/90 px-1.5 text-[10.5px] text-muted">from {p.workspace}</span>}</div>)}
          </div>
        </section>)}
      {sharing && <ShareDialog projectId={sharing} open onOpenChange={o => !o && setSharing(null)} />}
      <NewProjectDialog open={newOpen} onOpenChange={setNewOpen} />
      <Modal open={!!confirm} onOpenChange={o => !o && setConfirm(null)} title="Delete project?"
        description={<>“{confirm?.name}”, its model files, revisions and conversation will be permanently deleted.</>}
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button><Button variant="danger" onClick={del}>Delete project</Button></>} />
      <Modal open={!!renaming} onOpenChange={o => !o && setRenaming(null)} title="Rename project"
        footer={<><Button variant="secondary" onClick={() => setRenaming(null)}>Cancel</Button><Button onClick={rename} disabled={!renaming?.name.trim()}>Rename</Button></>}>
        <Input autoFocus value={renaming?.name ?? ""} maxLength={120} onChange={e => renaming && setRenaming({ ...renaming, name: e.target.value })} onKeyDown={e => e.key === "Enter" && rename()} aria-label="Project name" />
      </Modal>
      {similar && <SimilarPartsDialog projectId={similar} open onClose={() => setSimilar(null)} />}
      {exporting && <PartExportDialog open projectId={exporting.id} name={exporting.name} onOpenChange={o => { if (!o) setExporting(null); }} />}
    </div>
  );
}
