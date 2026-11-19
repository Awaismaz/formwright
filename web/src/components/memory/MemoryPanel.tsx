import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Check, Pencil, Pin, PinOff, Plus, Share2, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ORIGIN_LABEL, strength, type DesignProjectSummary, type MemoryFact, type MemoryState } from "@/lib/designProjects";
import { cx } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Input, Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger, Modal, PageLoader, Toggle } from "@/components/ui";

function FactRow({ f, onChange, projects }: { f: MemoryFact; onChange: () => void; projects: DesignProjectSummary[] }) {
  const [edit, setEdit] = useState<string | null>(null);
  const call = async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) toast.success(ok); onChange(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const save = () => edit !== null && edit.trim() && call(() => api.patch(`/api/memory/facts/${f.id}`, { text: edit.trim() }), "Saved").then(() => setEdit(null));
  const s = strength(f);
  return (
    <li className="group flex items-start gap-3 py-2.5" data-fact={f.kind}>
      <div className="min-w-0 flex-1">
        {edit !== null ? (
          <div className="flex gap-1.5">
            <Input autoFocus value={edit} maxLength={200} onChange={e => setEdit(e.target.value)} onKeyDown={e => { if (e.key === "Enter") void save(); if (e.key === "Escape") setEdit(null); }} aria-label="Preference" />
            <Button size="sm" icon={<Check className="h-3.5 w-3.5" />} onClick={() => void save()}>Save</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit(null)} aria-label="Cancel"><X className="h-3.5 w-3.5" /></Button>
          </div>) : <div className="text-[13.5px]">{f.pinned && <Pin className="mr-1 inline h-3 w-3 text-primary" />}{f.text}</div>}
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted">
          <Badge tone={f.origin === "learned" ? "neutral" : "primary"}>{ORIGIN_LABEL[f.origin]}</Badge>
          {s && f.origin === "learned" && <span>{s}</span>}<span>{f.source}</span>
          {f.used === false && <span className="text-muted/80">· not used now (only the top few go to the agent)</span>}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5 opacity-70 group-hover:opacity-100">
        <button className="rounded p-1.5 hover:bg-text/5" onClick={() => setEdit(f.text)} aria-label="Edit" title="Edit"><Pencil className="h-3.5 w-3.5" /></button>
        <button className="rounded p-1.5 hover:bg-text/5" onClick={() => call(() => api.patch(`/api/memory/facts/${f.id}`, { pinned: !f.pinned }))} aria-label={f.pinned ? "Unpin" : "Pin"} title={f.pinned ? "Unpin" : "Pin: always give it to the agent"}>
          {f.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}</button>
        {projects.length > 0 && <Menu>
          <MenuTrigger asChild><button className="rounded p-1.5 hover:bg-text/5" aria-label="Share to a project" title="Share to a project"><Share2 className="h-3.5 w-3.5" /></button></MenuTrigger>
          <MenuContent><MenuLabel>Make it a project decision</MenuLabel>
            {projects.map(p => <MenuItem key={p.id} onSelect={() => call(() => api.post(`/api/memory/facts/${f.id}/share`, { project_id: p.id }), `Added to ${p.name}'s decisions`)}>{p.name}</MenuItem>)}
          </MenuContent></Menu>}
        <button className="rounded p-1.5 text-danger hover:bg-danger/10" onClick={() => call(() => api.del(`/api/memory/facts/${f.id}`), f.origin === "learned" ? "Deleted. It won't be learned again." : "Deleted")} aria-label="Delete" title="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
    </li>);
}

/** Settings → Memory: everything the app has learned or been told about how this person designs, in this workspace. */
export default function MemoryPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["memory"], queryFn: () => api.get<MemoryState>("/api/memory") });
  const projects = useQuery({ queryKey: ["design-projects"], queryFn: () => api.get<{ items: DesignProjectSummary[] }>("/api/design-projects") });
  const [adding, setAdding] = useState("");
  const [forget, setForget] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["memory"] }).then(() => qc.invalidateQueries({ queryKey: ["agent-context"] }));
  const set = async (b: { learning?: boolean; use?: boolean }) => {
    try { await api.patch("/api/memory/settings", b); await refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const add = async () => {
    if (!adding.trim()) return;
    try { await api.post("/api/memory/facts", { text: adding.trim() }); setAdding(""); await refresh(); toast.success("Added to your memory"); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  if (!q.data) return <PageLoader />;
  const m = q.data;
  const editable = (projects.data?.items ?? []).filter(p => p.can_edit);
  return (
    <div className="space-y-6">
      <Card className="grid gap-6 p-6 md:grid-cols-[240px_1fr]">
        <div><h2 className="flex items-center gap-2 font-semibold"><Brain className="h-4 w-4 text-accent" />Design memory</h2>
          <p className="mt-1 text-sm text-muted">What the app has learned about how you design in <span className="font-medium text-text">{m.workspace}</span>. Private to you, never shared with other workspaces. An explicit request always wins over anything here.</p></div>
        <div className="max-w-lg space-y-4">
          <div className="flex items-center justify-between gap-4"><div><div className="text-sm font-medium">Learn from my work</div>
            <div className="text-xs text-muted">Counts the materials, fillets, chamfers and Hole Wizard holes you choose, the edits you make right after the agent builds, and “always / never” statements in your chats.</div></div>
            <Toggle checked={m.learning} onChange={v => set({ learning: v })} label="Learn from my work" /></div>
          <div className="flex items-center justify-between gap-4"><div><div className="text-sm font-medium">Use my preferences in the design agent</div>
            <div className="text-xs text-muted">The top {m.limits.facts_used} preferences (pinned first, then the most relevant) start each conversation.</div></div>
            <Toggle checked={m.use} onChange={v => set({ use: v })} label="Use my preferences" /></div>
        </div>
      </Card>
      <Card className="p-6">
        <div className="mb-3 flex flex-wrap items-center gap-2"><h3 className="font-semibold">Preferences</h3>
          <span className="text-[12px] text-muted">{m.facts.length} kept · {m.observations} observations counted (the latest {m.limits.observations_kept} are kept)</span></div>
        <div className="mb-3 flex gap-2">
          <Input value={adding} maxLength={200} onChange={e => setAdding(e.target.value)} onKeyDown={e => e.key === "Enter" && add()} placeholder="Add one yourself, e.g. “Outside edges get 0.5 mm chamfers”" aria-label="Add a preference" />
          <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={add} disabled={!adding.trim()}>Add</Button>
        </div>
        {m.facts.length === 0 ? <EmptyState icon={<Brain className="h-6 w-6" />} title="Nothing learned yet"
          body={m.learning ? "As you model, habits that repeat show up here, each with where it came from. You can edit, pin or delete any of them." : "Learning is off. Turn it on to let the app pick up your habits."} />
          : <ul className={cx("divide-y divide-border")}>{m.facts.map(f => <FactRow key={f.id} f={f} onChange={refresh} projects={editable} />)}</ul>}
        <div className="mt-4 border-t border-border pt-4"><Button variant="ghost" className="text-danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setForget(true)} disabled={!m.facts.length && !m.observations}>Forget everything</Button></div>
      </Card>
      <Modal open={forget} onOpenChange={setForget} title="Forget everything?"
        description={<>Deletes every preference and observation kept for you in {m.workspace}. Parts you made before now won't be learned from again. Project decisions you shared stay with their projects.</>}
        footer={<><Button variant="secondary" onClick={() => setForget(false)}>Cancel</Button>
          <Button variant="danger" onClick={async () => { await api.post("/api/memory/forget"); setForget(false); await refresh(); toast.success("Memory cleared"); }}>Forget everything</Button></>} />
    </div>
  );
}
