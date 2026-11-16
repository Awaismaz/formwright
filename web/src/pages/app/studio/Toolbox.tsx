import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Wrench } from "lucide-react";
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

/** Toolbox browser: standard components from deterministic generators (same inputs → identical model). */
export default function Toolbox({ project, initial, onClose, onDone }: {
  project: Project; initial?: { code: string; params: Record<string, number> } | null; onClose: () => void; onDone: () => void;
}) {
  const tb = useToolbox();
  const items = tb.data?.items ?? [];
  const [code, setCode] = useState<string | null>(initial?.code ?? null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const item = items.find(i => i.code === code) ?? items[0];
  const cats = useMemo(() => [...new Set(items.map(i => i.category))], [items]);

  useEffect(() => {
    if (!item) return;
    const pre = initial?.code === item.code ? initial.params : {};
    setVals(Object.fromEntries(item.params.map(p => [p.name, String(pre[p.name] ?? p.default)])));
  }, [item?.code]); // eslint-disable-line react-hooks/exhaustive-deps

  const insert = async () => {
    if (!item) return;
    setBusy(true);
    try {
      const params = Object.fromEntries(item.params.map(p => [p.name, Number(vals[p.name])]));
      const r = await api.post<{ title: string; build_s: number }>(`/api/projects/${project.id}/toolbox`, { code: item.code, params });
      track("toolbox_used", { code: item.code });
      toast.success(`${r.title} created · ${r.build_s ?? "–"} s`); onDone();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create the component"); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onOpenChange={v => !v && onClose()} wide title={<span className="flex items-center gap-2"><Wrench className="h-4 w-4 text-primary" />Toolbox</span>}
      description="Standard components from repeatable generators — the same inputs always produce the identical model. The current model is kept in Revisions."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={insert} disabled={!item}>{project.builds > 0 ? "Replace model with component" : "Create component"}</Button></>}>
      {tb.isLoading ? <div className="py-10 text-center text-sm text-muted">Loading…</div> : (
        <div className="grid gap-4 md:grid-cols-[220px_1fr]">
          <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
            {cats.map(c => (
              <div key={c}>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{c}</div>
                {items.filter(i => i.category === c).map(i => (
                  <button key={i.code} onClick={() => setCode(i.code)}
                    className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px]", item?.code === i.code ? "bg-primary-soft font-medium text-primary" : "hover:bg-text/5")}>
                    <Icon name={i.icon} className="h-4 w-4 shrink-0" />{i.name}
                  </button>))}
              </div>))}
          </div>
          {item && (
            <div>
              <div className="flex flex-wrap items-center gap-2"><h3 className="text-[15px] font-semibold">{item.name}</h3><Badge>{item.standard}</Badge><Badge tone="neutral">v{item.version}</Badge></div>
              <p className="mt-1 text-[12.5px] text-muted">Material: {item.material}{item.note && ` · ${item.note}`}</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {item.params.map(p => (
                  <Field key={p.name} label={`${p.label}${p.unit ? ` (${p.unit})` : ""}`} hint={p.help || (p.min !== null && p.max !== null ? `${p.min}–${p.max}` : undefined)}>
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
