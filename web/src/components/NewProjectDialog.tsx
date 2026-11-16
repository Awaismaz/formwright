import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import type { Project, Template } from "@/lib/types";
import { Button, Field, Input, Modal } from "./ui";
import { Icon } from "./icons";
import { cx } from "@/lib/format";

export function useTemplates() {
  return useQuery({ queryKey: ["templates"], queryFn: () => api.get<{ items: Template[] }>("/api/templates"), staleTime: Infinity });
}

export async function createProject(name: string, template: string | null, description = ""): Promise<Project> {
  const p = await api.post<Project>("/api/projects", { name, template, description });
  if (p.starter_prompt) try { sessionStorage.setItem(`fw_starter_${p.id}`, p.starter_prompt); } catch { /* ignore */ }
  if (template) track("template_used", { template });
  return p;
}

export default function NewProjectDialog({ open, onOpenChange, initialTemplate }: { open: boolean; onOpenChange: (v: boolean) => void; initialTemplate?: string | null }) {
  const tpl = useTemplates();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [template, setTemplate] = useState<string | null>(initialTemplate ?? null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) { setTemplate(initialTemplate ?? null); setName(""); setDesc(""); } }, [open, initialTemplate]);
  useEffect(() => {
    const t = tpl.data?.items.find(x => x.code === template);
    if (t && !name) setName(t.name);
  }, [template]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await createProject(name.trim(), template, desc);
      await qc.invalidateQueries({ queryKey: ["projects"] });
      await qc.invalidateQueries({ queryKey: ["checklist"] });
      onOpenChange(false);
      nav(`/app/projects/${p.id}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create project"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title="New project" description="Start from a proven template or a blank brief."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy} disabled={!name.trim()}>Create project</Button></>}>
      <div className="grid gap-5">
        <div className="grid gap-2 sm:grid-cols-3">
          <button type="button" onClick={() => setTemplate(null)}
            className={cx("flex flex-col items-start gap-2 rounded-lg border p-3 text-left transition", template === null ? "border-primary bg-primary-soft ring-1 ring-primary" : "border-border hover:border-primary/50")}>
            <FilePlus2 className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">Blank project</div><div className="text-xs text-muted">Describe anything</div></div>
          </button>
          {(tpl.data?.items ?? []).map(t => (
            <button key={t.code} type="button" onClick={() => setTemplate(t.code)}
              className={cx("flex flex-col items-start gap-2 rounded-lg border p-3 text-left transition", template === t.code ? "border-primary bg-primary-soft ring-1 ring-primary" : "border-border hover:border-primary/50")}>
              <Icon name={t.icon} className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">{t.name}</div><div className="line-clamp-2 text-xs text-muted">{t.prompt}</div></div>
            </button>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Project name"><Input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Pump bracket rev A" onKeyDown={e => e.key === "Enter" && submit()} /></Field>
          <Field label="Description (optional)"><Input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Client, purpose, notes" /></Field>
        </div>
      </div>
    </Modal>
  );
}
