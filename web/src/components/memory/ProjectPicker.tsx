import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Folders } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { DesignProjectSummary, ProjectRef } from "@/lib/designProjects";
import { cx } from "@/lib/format";
import { Button, Input, Modal } from "@/components/ui";

/** "Add to project": put a part in an existing project or a new one (a part belongs to at most one project). */
export default function ProjectPicker({ open, onOpenChange, part, current, onDone }: {
  open: boolean; onOpenChange: (v: boolean) => void; part: { id: string; name: string };
  current?: ProjectRef | null; onDone?: (p: ProjectRef | null) => void;
}) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["design-projects"], enabled: open,
    queryFn: () => api.get<{ items: DesignProjectSummary[] }>("/api/design-projects") });
  const [pick, setPick] = useState<string | "new" | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setPick(current?.id ?? null); setName(""); } }, [open, current?.id]);
  const items = (list.data?.items ?? []).filter(p => p.can_edit);
  useEffect(() => { if (open && list.isSuccess && !items.length) setPick("new"); }, [open, list.isSuccess, items.length]);

  const done = async (p: ProjectRef | null, msg: string) => {
    toast.success(msg);
    await qc.invalidateQueries({ queryKey: ["projects"] });
    await qc.invalidateQueries({ queryKey: ["design-projects"] });
    await qc.invalidateQueries({ queryKey: ["design-project"] });
    await qc.invalidateQueries({ queryKey: ["agent-context", part.id] });
    await qc.invalidateQueries({ queryKey: ["project", part.id] });
    onDone?.(p);
    onOpenChange(false);
  };
  const submit = async () => {
    setBusy(true);
    try {
      let target: ProjectRef;
      if (pick === "new") {
        const p = await api.post<DesignProjectSummary>("/api/design-projects", { name: name.trim() });
        target = { id: p.id, name: p.name };
      } else {
        const p = items.find(x => x.id === pick);
        if (!p) return;
        target = { id: p.id, name: p.name };
      }
      await api.post(`/api/design-projects/${target.id}/parts`, { part_id: part.id });
      await done(target, `“${part.name}” is now in ${target.name}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not add the part"); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!current) return;
    setBusy(true);
    try { await api.del(`/api/design-projects/${current.id}/parts/${part.id}`); await done(null, `“${part.name}” left ${current.name}`); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not remove the part"); }
    finally { setBusy(false); }
  };
  const ok = pick === "new" ? !!name.trim() : !!pick && pick !== current?.id;

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={current ? "Move to another project" : "Add to project"}
      description="Parts in the same project share their purpose, decisions and key sizes with the design agent, so a new part can be made to fit the others."
      footer={<>
        {current && <Button variant="secondary" className="mr-auto" onClick={remove} disabled={busy}>Remove from {current.name}</Button>}
        <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button onClick={submit} loading={busy} disabled={!ok}>{pick === "new" ? "Create and add" : current ? "Move" : "Add"}</Button></>}>
      <div className="space-y-1.5" role="radiogroup" aria-label="Project">
        {items.map(p => (
          <button key={p.id} role="radio" aria-checked={pick === p.id} onClick={() => setPick(p.id)}
            className={cx("flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left", pick === p.id ? "border-primary bg-primary-soft" : "border-border hover:border-primary/50")}>
            <Folders className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{p.name}</span>
              <span className="block truncate text-[12px] text-muted">{p.parts} part{p.parts === 1 ? "" : "s"}{p.purpose ? ` · ${p.purpose}` : ""}</span></span>
            {current?.id === p.id && <span className="text-[11.5px] text-muted">current</span>}
          </button>))}
        <button role="radio" aria-checked={pick === "new"} onClick={() => setPick("new")}
          className={cx("flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left", pick === "new" ? "border-primary bg-primary-soft" : "border-dashed border-border hover:border-primary/50")}>
          <FolderPlus className="h-4 w-4 shrink-0 text-primary" /><span className="text-[13.5px] font-medium">New project</span>
        </button>
        {pick === "new" && <Input autoFocus value={name} maxLength={120} onChange={e => setName(e.target.value)} placeholder="e.g. Pump skid PS-1"
          onKeyDown={e => e.key === "Enter" && ok && submit()} aria-label="New project name" />}
      </div>
    </Modal>
  );
}
