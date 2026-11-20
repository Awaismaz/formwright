import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LayoutTemplate, Wrench } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import type { Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Badge, Button, Field, Input, Modal } from "@/components/ui";
import { Icon } from "@/components/icons";

export interface TbParam { name: string; label: string; default: number; unit: string; min: number | null; max: number | null; options: number[] | null; help: string; integer: boolean }
export interface TbItem { code: string; name: string; category: string; standard: string; material: string; note: string; icon: string; params: TbParam[]; version: number }
export interface TbMatch { code: string; name: string; title: string; standard: string; params: Record<string, number>; prefilled: string[] }

export function useToolbox() {
  return useQuery({ queryKey: ["toolbox"], queryFn: () => api.get<{ items: TbItem[] }>("/api/toolbox"), staleTime: Infinity });
}

/** A workspace part template (kept in the Design Office from a part that passed its checks), as the Studio starts a part
 * from it: its parameters with their labels and limits (``/api/part-templates``, this organisation's only). */
export interface TplParam { name: string; value: number; label: string; unit: string; group: string; min: number | null; max: number | null }
export interface TplItem {
  id: string; name: string; family: string; params: number; mapped: number; uses: number; material: string | null;
  created_at: string | null; source: { program_name?: string; title?: string }; param_list: TplParam[];
}

export function usePartTemplates() {
  return useQuery({ queryKey: ["part-templates"], queryFn: () => api.get<{ items: TplItem[] }>("/api/part-templates"), staleTime: 30_000 });
}

/** The values to send: only the parameters the engineer changed, as numbers (empty or unchanged ones keep the template's). */
export function templateValues(params: TplParam[], vals: Record<string, string>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of params) {
    const raw = (vals[p.name] ?? "").trim();
    const v = Number(raw);
    if (raw !== "" && Number.isFinite(v) && v !== p.value) out[p.name] = v;
  }
  return out;
}

/** Toolbox browser: standard components from deterministic generators (same inputs → identical model). */
export default function Toolbox({ project, initial, onClose, onDone }: {
  project: Project; initial?: { code: string; params: Record<string, number> } | null; onClose: () => void; onDone: () => void;
}) {
  const tb = useToolbox();
  const tq = usePartTemplates();
  const items = tb.data?.items ?? [];
  const tpls = tq.data?.items ?? [];
  const [code, setCode] = useState<string | null>(initial?.code ?? null);
  const [tplId, setTplId] = useState<string | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [tvals, setTvals] = useState<Record<string, string>>({});
  const tpl = tplId ? tpls.find(t => t.id === tplId) ?? null : null;
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  // SOLIDWORKS users expect a Toolbox part to be a part of its own, not to overwrite the one being designed (STU-16)
  const [target, setTarget] = useState<"new" | "replace">(project.builds > 0 ? "new" : "replace");
  const item = items.find(i => i.code === code) ?? items[0];
  const cats = useMemo(() => [...new Set(items.map(i => i.category))], [items]);

  useEffect(() => {
    if (!item) return;
    const pre = initial?.code === item.code ? initial.params : {};
    setVals(Object.fromEntries(item.params.map(p => [p.name, String(pre[p.name] ?? p.default)])));
  }, [item?.code]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tpl) setTvals(Object.fromEntries(tpl.param_list.map(p => [p.name, String(p.value)])));
  }, [tpl?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const insertTemplate = async () => {
    if (!tpl) return;
    setBusy(true);
    try {
      const pid = target === "new" ? (await api.post<{ id: string }>("/api/projects", { name: tpl.name })).id : project.id;
      const r = await api.post<{ title: string; build_s: number }>(`/api/projects/${pid}/part-template`, { template_id: tpl.id, values: templateValues(tpl.param_list, tvals) });
      track("template_used", { family: tpl.family });
      if (target === "new") { toast.success(`${r.title} started from the workspace template`); onClose(); nav(`/app/projects/${pid}`); }
      else { toast.success(`${r.title} started from the workspace template`); onDone(); }
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not start the part from the template"); }
    finally { setBusy(false); }
  };

  const insert = async () => {
    if (!item) return;
    setBusy(true);
    try {
      const params = Object.fromEntries(item.params.map(p => [p.name, Number(vals[p.name])]));
      const pid = target === "new" ? (await api.post<{ id: string }>("/api/projects", { name: item.name })).id : project.id;
      const r = await api.post<{ title: string; build_s: number }>(`/api/projects/${pid}/toolbox`, { code: item.code, params });
      track("toolbox_used", { code: item.code });
      if (target === "new") { await api.patch(`/api/projects/${pid}`, { name: r.title }).catch(() => {}); toast.success(`${r.title} created as a new part${r.build_s ? ` · ${r.build_s} s` : ""}`); onClose(); nav(`/app/projects/${pid}`); }
      else { toast.success(`${r.title} created${r.build_s ? ` · ${r.build_s} s` : ""}`); onDone(); }
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create the component"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onOpenChange={v => !v && onClose()} wide title={<span className="flex items-center gap-2"><Wrench className="h-4 w-4 text-primary" />Toolbox</span>}
      description="Standard components from repeatable generators (the same inputs always produce the identical model), and your workspace's part templates."
      footer={<>
        {project.builds > 0 && <div className="mr-auto inline-flex overflow-hidden rounded border border-border text-[12.5px]" role="group" aria-label="Where to create it">
          {([["new", "As a new part"], ["replace", "Replace this model"]] as const).map(([k, l]) => <button key={k} onClick={() => setTarget(k)} className={cx("px-2.5 py-1", target === k ? "bg-primary text-white" : "text-muted hover:bg-text/5")}>{l}</button>)}</div>}
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button loading={busy} onClick={tpl ? insertTemplate : insert} disabled={tpl ? false : !item} data-toolbox-create>{target === "replace" && project.builds > 0 ? "Replace model (kept in Revisions)" : "Create part"}</Button></>}>
      {tb.isLoading ? <div className="py-10 text-center text-sm text-muted">Loading…</div> : (
        <div className="grid gap-4 md:grid-cols-[220px_1fr]">
          <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
            {tpls.length > 0 && <div data-toolbox-templates>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Templates</div>
              {tpls.map(t => (
                <button key={t.id} onClick={() => setTplId(t.id)} data-template={t.id}
                  className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px]", tplId === t.id ? "bg-primary-soft font-medium text-primary" : "hover:bg-text/5")}>
                  <LayoutTemplate className="h-4 w-4 shrink-0" /><span className="min-w-0 truncate">{t.name}</span>
                </button>))}
            </div>}
            {cats.map(c => (
              <div key={c}>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{c}</div>
                {items.filter(i => i.category === c).map(i => (
                  <button key={i.code} onClick={() => { setCode(i.code); setTplId(null); }}
                    className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px]", !tpl && item?.code === i.code ? "bg-primary-soft font-medium text-primary" : "hover:bg-text/5")}>
                    <Icon name={i.icon} className="h-4 w-4 shrink-0" />{i.name}
                  </button>))}
              </div>))}
          </div>
          {tpl && (
            <div data-template-panel>
              <div className="flex flex-wrap items-center gap-2"><h3 className="text-[15px] font-semibold">{tpl.name}</h3><Badge>Workspace template</Badge><Badge tone="neutral">{tpl.family}</Badge></div>
              <p className="mt-1 text-[12.5px] text-muted">
                {tpl.source.program_name ? `Kept from ${tpl.source.title ?? tpl.name} in ${tpl.source.program_name}` : "Kept from a part that passed its checks"}
                {tpl.material && ` · ${tpl.material}`}{tpl.uses > 0 && ` · used ${tpl.uses} time${tpl.uses === 1 ? "" : "s"}`}</p>
              {tpl.param_list.length > 0 ? <div className="mt-3 grid max-h-[300px] gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
                {tpl.param_list.map(p => (
                  <Field key={p.name} label={`${p.label}${p.unit ? ` (${p.unit})` : ""}`} hint={p.min !== null && p.max !== null ? `${p.min} to ${p.max}` : undefined}>
                    <Input value={tvals[p.name] ?? ""} inputMode="decimal" onChange={e => setTvals({ ...tvals, [p.name]: e.target.value })} />
                  </Field>))}
              </div> : <p className="mt-3 text-[12.5px] text-muted">This template has no editable sizes: it starts the part as it was kept.</p>}
              <p className="mt-4 rounded-md bg-panel2 px-3 py-2 text-[12px] text-muted">
                The part is built from the template's model with your sizes and checked like any other (no AI). Keep editing it in the <b>Params</b> panel, add manual features, or ask the design agent to extend it.
              </p>
            </div>)}
          {!tpl && item && (
            <div>
              <div className="flex flex-wrap items-center gap-2"><h3 className="text-[15px] font-semibold">{item.name}</h3><Badge>{item.standard}</Badge><Badge tone="neutral">v{item.version}</Badge></div>
              <p className="mt-1 text-[12.5px] text-muted">Material: {item.material}{item.note && ` · ${item.note}`}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {item.params.map(p => (
                  <Field key={p.name} label={`${p.label}${p.unit ? ` (${p.unit})` : ""}`} hint={p.help || (p.min !== null && p.max !== null ? `${p.min} to ${p.max}` : undefined)}>
                    {p.options ? (
                      <select className="input" value={vals[p.name] ?? ""} onChange={e => setVals({ ...vals, [p.name]: e.target.value })}>
                        {p.options.map(o => <option key={o} value={String(o)}>{p.name === "D" ? `M${o}` : o}</option>)}
                      </select>
                    ) : <Input value={vals[p.name] ?? ""} inputMode="decimal" onChange={e => setVals({ ...vals, [p.name]: e.target.value })} />}
                  </Field>))}
              </div>
              <p className="mt-4 rounded-md bg-panel2 px-3 py-2 text-[12px] text-muted">
                After creating, edit sizes in the <b>Params</b> panel (no AI needed), add manual features, or ask the design agent to modify or extend it.
              </p>
            </div>)}
        </div>)}
    </Modal>
  );
}
