import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Box, Building2, FolderInput, FolderOutput, History, ListChecks, MoreHorizontal, NotebookPen,
  Pencil, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Project } from "@/lib/types";
import type { DesignProjectDetail } from "@/lib/designProjects";
import { ago, cx, PAGE, size } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Input, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Modal, PageHeader, PageLoader } from "@/components/ui";
import ProjectCard from "@/components/ProjectCard";
import NewProjectDialog from "@/components/NewProjectDialog";
import NotFoundPanel from "@/components/NotFoundPanel";

const SOURCE_TONE = { manual: "neutral", chat: "accent", memory: "primary", program: "primary" } as const;

function AddExisting({ open, onOpenChange, dp, onAdded }: { open: boolean; onOpenChange: (v: boolean) => void; dp: DesignProjectDetail; onAdded: () => void }) {
  const list = useQuery({ queryKey: ["projects", false], enabled: open, queryFn: () => api.get<{ items: (Project & { design_project?: { id: string; name: string } | null })[] }>("/api/projects?archived=false") });
  const [q, setQ] = useState("");
  const rows = (list.data?.items ?? []).filter(p => p.design_project?.id !== dp.id && p.access?.can_edit !== false
    && (!q || p.name.toLowerCase().includes(q.toLowerCase())));
  const add = async (p: Project) => {
    try { await api.post(`/api/design-projects/${dp.id}/parts`, { part_id: p.id }); toast.success(`Added “${p.name}”`); onAdded(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not add the part"); }
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`Add parts to ${dp.name}`} description="A part belongs to one project at a time: adding a part that is in another project moves it here.">
      <div className="relative mb-3"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
        <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search parts" className="pl-9" aria-label="Search parts" /></div>
      {list.isLoading ? <div className="py-4 text-sm text-muted">Loading…</div> : rows.length === 0 ? <p className="py-3 text-sm text-muted">No other parts to add.</p> : (
        <ul className="max-h-[50vh] divide-y divide-border overflow-y-auto">
          {rows.map(p => <li key={p.id} className="flex items-center gap-3 py-2">
            <div className="min-w-0 flex-1"><div className="truncate text-[13.5px] font-medium">{p.name}</div>
              <div className="truncate text-[12px] text-muted">{[p.last_status?.material, size(p.last_status?.fingerprint?.bbox), p.design_project ? `in ${p.design_project.name}` : null].filter(Boolean).join(" · ") || "No builds yet"}</div></div>
            <Button size="sm" variant="secondary" onClick={() => void add(p)}>{p.design_project ? "Move here" : "Add"}</Button>
          </li>)}
        </ul>)}
    </Modal>);
}

/** A Project: related parts, their purpose, shared decisions and notes; the design agent knows all of it when you
 *  chat in any part of the project. */
export default function DesignProjectPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { me } = useSession();
  const units = me?.user?.preferences?.units;
  const q = useQuery({ queryKey: ["design-project", id], queryFn: () => api.get<DesignProjectDetail>(`/api/design-projects/${id}`), retry: false });
  const [newPart, setNewPart] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<{ name: string; purpose: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [decision, setDecision] = useState("");
  const [notes, setNotes] = useState<string | null>(null);
  const dp = q.data;
  useEffect(() => { if (dp) setNotes(n => (n === null ? dp.notes : n)); }, [dp]);
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["design-project", id] }); void qc.invalidateQueries({ queryKey: ["design-projects"] }); void qc.invalidateQueries({ queryKey: ["projects"] }); };
  const call = async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) toast.success(ok); refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const built = useMemo(() => (dp?.items ?? []).filter(p => p.builds > 0).length, [dp]);
  if (q.isError) return <NotFoundPanel />;
  if (!dp) return <PageLoader />;
  const edit = dp.can_edit;
  const saveNotes = () => { if (notes !== null && notes !== dp.notes) void call(() => api.patch(`/api/design-projects/${dp.id}`, { notes }), "Notes saved"); };
  const addDecision = () => { const t = decision.trim(); if (!t) return; void call(() => api.post(`/api/design-projects/${dp.id}/decisions`, { text: t })).then(() => setDecision("")); };

  return (
    <div className={PAGE}>
      <PageHeader eyebrow={<Link to="/app/projects" className="hover:text-primary">Projects</Link>} title={dp.name}
        subtitle={dp.purpose || (edit ? <button className="link" onClick={() => setEditing({ name: dp.name, purpose: "" })}>Add a purpose: what are these parts for?</button> : undefined)}
        actions={edit && <>
          <Button variant="secondary" icon={<FolderInput className="h-4 w-4" />} onClick={() => setAdding(true)}>Add parts</Button>
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewPart(true)}>New part</Button>
          <Menu><MenuTrigger asChild><Button variant="ghost" aria-label="Project actions"><MoreHorizontal className="h-4 w-4" /></Button></MenuTrigger>
            <MenuContent>
              <MenuItem icon={<Pencil />} onSelect={() => setEditing({ name: dp.name, purpose: dp.purpose })}>Rename / edit purpose…</MenuItem>
              {dp.archived ? <MenuItem icon={<ArchiveRestore />} onSelect={() => call(() => api.patch(`/api/design-projects/${dp.id}`, { archived: false }), "Project restored")}>Restore</MenuItem>
                : <MenuItem icon={<Archive />} onSelect={() => call(() => api.patch(`/api/design-projects/${dp.id}`, { archived: true }), "Project archived")}>Archive</MenuItem>}
              {dp.can_delete && <><MenuSeparator /><MenuItem icon={<Trash2 />} danger onSelect={() => setConfirm(true)}>Delete project…</MenuItem></>}
            </MenuContent></Menu></>} />
      {dp.program && <div className="mb-4 flex items-center gap-2 rounded-lg border border-primary/25 bg-primary-soft px-3 py-2 text-[13px]">
        <Building2 className="h-4 w-4 text-primary" />Parts of the Design Office program <Link to={`/app/office/programs/${dp.program.id}`} className="font-medium text-primary hover:underline">{dp.program.name}</Link></div>}
      <div className="mb-5 flex items-start gap-2 text-[12.5px] text-muted"><Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
        When you chat in any of these parts, the design agent knows the other parts' sizes, materials and mating features (hole patterns, bores, shaft diameters) and follows the decisions below.</div>
      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <section>
          <div className="mb-3 flex items-baseline gap-2"><h2 className="font-semibold">Parts</h2><span className="text-[12px] text-muted">{dp.items.length} · {built} built{dp.hidden_parts ? ` · ${dp.hidden_parts} private to others` : ""}</span></div>
          {dp.items.length === 0 ? <EmptyState icon={<Box className="h-6 w-6" />} title="No parts yet"
            body="Start a part here, or add parts you already made. Parts in one project can be designed to fit each other."
            action={edit && <div className="flex gap-2"><Button variant="secondary" onClick={() => setAdding(true)}>Add parts</Button><Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewPart(true)}>New part</Button></div>} />
            : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{dp.items.map(p => (
              <div key={p.id} className="relative flex flex-col">
                <ProjectCard p={p} units={units} />
                {p.facts.interfaces.length > 0 && <div className="mt-1.5 line-clamp-2 px-1 text-[11.5px] text-muted" title={p.facts.interfaces.join("\n")}>{p.facts.interfaces.join(" · ")}</div>}
                {edit && p.access?.can_edit && <div className="absolute right-2 top-2 rounded bg-panel/90"><Menu>
                  <MenuTrigger asChild><button className="rounded p-1.5 text-muted hover:bg-text/5" aria-label={`Actions for ${p.name}`}><MoreHorizontal className="h-4 w-4" /></button></MenuTrigger>
                  <MenuContent><MenuItem icon={<FolderOutput />} onSelect={() => call(() => api.del(`/api/design-projects/${dp.id}/parts/${p.id}`), `“${p.name}” left the project`)}>Remove from project</MenuItem></MenuContent></Menu></div>}
              </div>))}</div>}
        </section>
        <aside className="space-y-4">
          <Card className="p-4">
            <h3 className="mb-1 flex items-center gap-2 text-[14px] font-semibold"><ListChecks className="h-4 w-4 text-primary" />Decisions</h3>
            <p className="mb-3 text-[12px] text-muted">Every part follows these unless a request says otherwise. Statements like “all fasteners M6” in a part's chat are added here.</p>
            {dp.decisions.length === 0 ? <p className="mb-3 text-[13px] text-muted">None yet.</p> : (
              <ul className="mb-3 space-y-2">{dp.decisions.map(d => (
                <li key={d.id} className="group flex items-start gap-2" data-decision>
                  <div className="min-w-0 flex-1"><div className="text-[13px]">{d.text}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-muted"><Badge tone={SOURCE_TONE[d.source]}>{d.category}</Badge>{d.source_label}{d.created_by ? ` · ${d.created_by}` : ""}</div></div>
                  {edit && <button className="rounded p-1 text-muted opacity-60 hover:bg-text/5 group-hover:opacity-100" aria-label="Remove decision" onClick={() => call(() => api.del(`/api/design-projects/${dp.id}/decisions/${d.id}`))}><X className="h-3.5 w-3.5" /></button>}
                </li>))}</ul>)}
            {edit && <div className="flex gap-1.5"><Input value={decision} maxLength={240} onChange={e => setDecision(e.target.value)} onKeyDown={e => e.key === "Enter" && addDecision()} placeholder="e.g. All fasteners M6 ISO 4762" aria-label="New decision" className="h-8 text-[13px]" />
              <Button size="sm" variant="secondary" onClick={addDecision} disabled={!decision.trim()}>Add</Button></div>}
          </Card>
          <Card className="p-4">
            <h3 className="mb-2 flex items-center gap-2 text-[14px] font-semibold"><NotebookPen className="h-4 w-4 text-primary" />Notes</h3>
            <textarea value={notes ?? ""} onChange={e => setNotes(e.target.value)} onBlur={saveNotes} disabled={!edit} rows={5} maxLength={8000}
              placeholder={edit ? "Context the team and the agent should keep in mind: interfaces, loads, the customer's constraints…" : ""}
              className="input h-auto min-h-[96px] resize-y py-2 text-[13px] leading-relaxed" aria-label="Project notes" />
            <p className="mt-1 text-[11px] text-muted">The first lines of the notes go to the design agent with each new conversation.</p>
          </Card>
          <Card className="p-4">
            <h3 className="mb-2 flex items-center gap-2 text-[14px] font-semibold"><History className="h-4 w-4 text-primary" />Activity</h3>
            {dp.activity.length === 0 ? <p className="text-[13px] text-muted">Nothing yet.</p> : (
              <ol className="space-y-2">{dp.activity.map((a, i) => (
                <li key={i} className="text-[12.5px] leading-snug">
                  {a.kind === "revision" && a.part ? <><Link to={`/app/projects/${a.part.id}`} className="font-medium hover:text-primary">{a.part.name}</Link> <span className="text-muted">rev {a.revision}</span> · {a.what}</>
                    : <><span className="font-medium">Decision</span> · {a.what}</>}
                  <div className="text-[11px] text-muted">{ago(a.at)}{a.by ? ` · ${a.by}` : ""}</div>
                </li>))}</ol>)}
          </Card>
        </aside>
      </div>
      <NewProjectDialog open={newPart} onOpenChange={setNewPart} designProject={{ id: dp.id, name: dp.name }} />
      {adding && <AddExisting open onOpenChange={setAdding} dp={dp} onAdded={refresh} />}
      <Modal open={!!editing} onOpenChange={o => !o && setEditing(null)} title="Edit project"
        footer={<><Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
          <Button disabled={!editing?.name.trim()} onClick={() => editing && call(() => api.patch(`/api/design-projects/${dp.id}`, { name: editing.name.trim(), purpose: editing.purpose }), "Saved").then(() => setEditing(null))}>Save</Button></>}>
        <div className="space-y-3">
          <label className="block space-y-1.5"><span className="text-[13px] font-medium">Name</span>
            <Input value={editing?.name ?? ""} maxLength={120} onChange={e => editing && setEditing({ ...editing, name: e.target.value })} /></label>
          <label className="block space-y-1.5"><span className="text-[13px] font-medium">Purpose</span>
            <textarea value={editing?.purpose ?? ""} maxLength={2000} rows={3} onChange={e => editing && setEditing({ ...editing, purpose: e.target.value })}
              placeholder="e.g. Gearbox for a 0.5 kW conveyor drive: housing, cover, two shafts" className={cx("input h-auto py-2 text-[13px]")} /></label>
        </div>
      </Modal>
      <Modal open={confirm} onOpenChange={setConfirm} title="Delete project?"
        description={<>“{dp.name}”, its notes and decisions are deleted. Its {dp.items.length} part{dp.items.length === 1 ? "" : "s"} are kept and become unsorted.</>}
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button>
          <Button variant="danger" onClick={() => call(() => api.del(`/api/design-projects/${dp.id}`), "Project deleted").then(() => nav("/app/projects"))}>Delete project</Button></>} />
    </div>
  );
}
