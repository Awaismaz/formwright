import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, FileUp, ScanLine } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import type { Project, Template } from "@/lib/types";
import { Button, Field, Input, Modal } from "./ui";
import { Icon } from "./icons";
import { cx } from "@/lib/format";
import { startFromFile, uniqueName } from "./StartBox";
import { isNativeFile, NATIVE_ACCEPT, openNativeImport } from "@/lib/native";

export function useTemplates() {
  return useQuery({ queryKey: ["templates"], queryFn: () => api.get<{ items: Template[] }>("/api/templates"), staleTime: Infinity });
}

export async function createProject(name: string, template: string | null, description = ""): Promise<Project> {
  const p = await api.post<Project>("/api/projects", { name, template, description });
  if (p.starter_prompt) try { sessionStorage.setItem(`fw_starter_${p.id}`, p.starter_prompt); } catch { /* ignore */ }
  if (template) track("template_used", { template });
  return p;
}

const tile = (on: boolean) => cx("flex flex-col items-start gap-2 rounded-lg border p-3 text-left transition",
  on ? "border-primary bg-primary-soft ring-1 ring-primary" : "border-border hover:border-primary/50");

export default function NewProjectDialog({ open, onOpenChange, initialTemplate }: { open: boolean; onOpenChange: (v: boolean) => void; initialTemplate?: string | null }) {
  const tpl = useTemplates();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [typed, setTyped] = useState(false); // the user named it: never overwrite with a template name
  const [desc, setDesc] = useState("");
  const [template, setTemplate] = useState<string | null>(initialTemplate ?? null);
  const [busy, setBusy] = useState<string | null>(null);
  const stepRef = useRef<HTMLInputElement>(null);
  const drawRef = useRef<HTMLInputElement>(null);
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects"), enabled: open });

  useEffect(() => { if (open) { setTemplate(initialTemplate ?? null); setName(""); setTyped(false); setDesc(""); } }, [open, initialTemplate]);
  useEffect(() => {
    if (typed) return;
    const t = tpl.data?.items.find(x => x.code === template);
    setName(t ? t.name : "");
  }, [template]); // eslint-disable-line react-hooks/exhaustive-deps

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    if (isNativeFile(f.name)) { onOpenChange(false); openNativeImport(f); return; }
    setBusy("file");
    try { await startFromFile(f, nav, (projects.data?.items ?? []).map(p => p.name)); onOpenChange(false); await qc.invalidateQueries({ queryKey: ["projects"] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not open that file"); }
    finally { setBusy(null); }
  };

  const submit = async () => {
    if (!name.trim()) return;
    setBusy("create");
    try {
      const finalName = typed ? name.trim() : uniqueName(name.trim(), (projects.data?.items ?? []).map(p => p.name));
      const p = await createProject(finalName, template, desc);
      await qc.invalidateQueries({ queryKey: ["projects"] });
      await qc.invalidateQueries({ queryKey: ["checklist"] });
      onOpenChange(false);
      nav(`/app/projects/${p.id}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create project"); }
    finally { setBusy(null); }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title="New project" description="Start from what you have: a brief, a template, a STEP file or a drawing."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy === "create"} disabled={!name.trim() || !!busy}>Create project</Button></>}>
      <div className="grid gap-5">
        <div className="grid gap-2 sm:grid-cols-2">
          <input ref={stepRef} type="file" accept={`.step,.stp,${NATIVE_ACCEPT}`} hidden onChange={e => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
          <input ref={drawRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" hidden onChange={e => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
          <button type="button" disabled={!!busy} onClick={() => stepRef.current?.click()} className={tile(false)}>
            <FileUp className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">Import a STEP or Formwright file</div><div className="text-xs text-muted">STEP: exact solid, features recognised. .fwpart: the full parametric model</div></div>
          </button>
          <button type="button" disabled={!!busy} onClick={() => drawRef.current?.click()} className={tile(false)}>
            <ScanLine className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">From a drawing, sketch or photo</div><div className="text-xs text-muted">PDF, PNG or JPEG; every value read is shown for review</div></div>
          </button>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <button type="button" onClick={() => setTemplate(null)} className={tile(template === null)}>
            <FilePlus2 className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">Blank project</div><div className="text-xs text-muted">Describe anything, or model by hand</div></div>
          </button>
          {(tpl.data?.items ?? []).map(t => (
            <button key={t.code} type="button" onClick={() => setTemplate(t.code)} className={tile(template === t.code)}>
              <Icon name={t.icon} className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">{t.name}</div><div className="line-clamp-2 text-xs text-muted">{t.prompt}</div></div>
            </button>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Project name"><Input value={name} onChange={e => { setName(e.target.value); setTyped(e.target.value.length > 0); }} placeholder="e.g. Pump bracket rev A" onKeyDown={e => e.key === "Enter" && submit()} /></Field>
          <Field label="Description (optional)"><Input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Client, purpose, notes" /></Field>
        </div>
      </div>
    </Modal>
  );
}
