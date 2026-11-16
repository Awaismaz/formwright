import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Columns3, GitCompare, Plus, Star, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";
import { cx, num } from "@/lib/format";
import { Badge, Button, Input, Modal, Tip } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";

interface Summary { ok: boolean; material?: string | null; params: Record<string, unknown>; volume?: number; bbox?: number[]; faces?: number; mass_g?: number | null }
interface Variant extends Summary { id: string; name: string; rev: number; note: string; by?: string; created_at: string; views: boolean; current: boolean }
interface List { items: Variant[]; current_rev: number | null; current: Summary; current_is_variant: boolean }

const LETTERS = "ABCDEFGHIJKL";
const pct = (v?: number | null, ref?: number | null) => (v == null || ref == null || !ref || Math.abs(v - ref) < 1e-9 ? null : ((v - ref) / ref) * 100);

/** Variants: name the current design, keep alternatives side by side, switch between them without AI. */
export default function VariantsBar({ project, version, onCompare, onChanged }: {
  project: Project; version?: number; onCompare: (rev: number) => void; onChanged: () => void;
}) {
  const qc = useQueryClient();
  const key = ["variants", project.id, version];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<List>(`/api/projects/${project.id}/variants`) });
  const [naming, setNaming] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const data = q.data;
  if (!data) return null;
  const refresh = () => qc.invalidateQueries({ queryKey: ["variants", project.id] });
  const save = async () => {
    if (naming === null) return;
    try { await api.post(`/api/projects/${project.id}/variants`, { name: naming }); toast.success(`Saved “${naming.trim()}”`); setNaming(null); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't save the variant"); }
  };
  const nextName = `Variant ${LETTERS[data.items.length] ?? data.items.length + 1}`;
  return (
    <div className="border-b border-border bg-panel2/50 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="label flex-1">Variants</span>
        {data.items.length > 0 && <Button size="sm" variant="secondary" icon={<Columns3 className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>Compare</Button>}
        {!data.current_is_variant && data.current_rev !== null && naming === null &&
          <Tip content="Keep the current design as a named alternative" side="bottom"><Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setNaming(nextName)}>Save current</Button></Tip>}
      </div>
      {naming !== null && (
        <form className="mt-2 flex items-center gap-1.5" onSubmit={e => { e.preventDefault(); void save(); }}>
          <Input autoFocus value={naming} onChange={e => setNaming(e.target.value)} onFocus={e => e.target.select()} className="h-7 flex-1" aria-label="Variant name" maxLength={40} />
          <button type="submit" className="rounded bg-success p-1 text-white" aria-label="Save variant"><Check className="h-3.5 w-3.5" /></button>
          <button type="button" onClick={() => setNaming(null)} className="rounded bg-text/10 p-1" aria-label="Cancel"><X className="h-3.5 w-3.5" /></button>
        </form>)}
      {data.items.length === 0 && naming === null
        ? <p className="mt-1 text-[11.5px] text-muted">Trying alternatives? Save this design as a variant, change it, save again, then compare them side by side.</p>
        : <div className="mt-2 flex flex-wrap gap-1.5">{data.items.map(v => (
            <button key={v.id} onClick={() => setOpen(true)} title={v.note || `Revision ${v.rev}`}
              className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px]",
                v.current ? "border-primary bg-primary-soft font-medium text-primary" : "border-border bg-panel text-text hover:border-primary/50")}>
              <Star className={cx("h-3 w-3", v.current ? "fill-primary" : "text-muted")} />{v.name}</button>))}</div>}
      <CompareVariants open={open} onClose={() => setOpen(false)} project={project} data={data} onCompare={onCompare}
        onChanged={() => { onChanged(); refresh(); }} />
    </div>
  );
}

function CompareVariants({ open, onClose, project, data, onCompare, onChanged }: {
  open: boolean; onClose: () => void; project: Project; data: List; onCompare: (rev: number) => void; onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ id: string; name: string } | null>(null);
  const [allParams, setAllParams] = useState(false);
  type Col = { key: string; name: string; rev: number | null; current: boolean; v?: Variant; s: Summary };
  const cols: Col[] = [...data.items.map(v => ({ key: v.id, name: v.name, rev: v.rev, current: v.current, v, s: v as Summary })),
    ...(data.current_is_variant ? [] : [{ key: "current", name: "Current design", rev: data.current_rev, current: true, s: data.current }])];
  const ref = cols.find(c => c.current)?.s ?? cols[0]?.s;
  const keys = [...new Set(cols.flatMap(c => Object.keys(c.s.params ?? {})))];
  const differs = (k: string) => new Set(cols.map(c => JSON.stringify(c.s.params?.[k] ?? null))).size > 1;
  const pkeys = [...keys.filter(differs), ...(allParams ? keys.filter(k => !differs(k)) : [])];
  const hidden = keys.filter(k => !differs(k)).length;
  const makeCurrent = async (c: Col) => {
    if (c.rev === null) return;
    setBusy(c.key);
    try { await api.post(`/api/projects/${project.id}/revisions/${c.rev}/restore`); toast.success(`“${c.name}” is now the current design (no AI)`); onChanged(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Switch failed"); } finally { setBusy(null); }
  };
  const rename = async () => {
    if (!edit) return;
    try { await api.patch(`/api/projects/${project.id}/variants/${edit.id}`, { name: edit.name }); setEdit(null); onChanged(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Rename failed"); }
  };
  const remove = async (v: Variant) => {
    try { await api.del(`/api/projects/${project.id}/variants/${v.id}`); toast.success(`Removed “${v.name}” (its revision stays in history)`); onChanged(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Delete failed"); }
  };
  const delta = (v?: number | null, r?: number | null) => { const d = pct(v, r); return d === null ? null
    : <span className="ml-1 text-[11px] text-muted">{d > 0 ? "+" : "−"}{Math.abs(d).toFixed(1)} %</span>; };
  const row = (label: string, cell: (c: Col) => React.ReactNode, hl = false) => (
    <tr className={cx(hl && "bg-accent/5")}>
      <th className="sticky left-0 z-[1] whitespace-nowrap bg-panel px-3 py-2 text-left text-[12px] font-medium text-muted">{label}</th>
      {cols.map(c => <td key={c.key} className={cx("px-3 py-2 text-[12.5px] tabular-nums", c.current && "bg-primary-soft/40")}>{cell(c)}</td>)}
    </tr>);
  return (
    <Modal wide open={open} onOpenChange={o => !o && onClose()} title="Compare variants"
      description="Alternatives of this part side by side. Differences are highlighted; percentages are relative to the current design. Switching restores a variant without AI.">
      <div className="max-h-[66vh] overflow-auto rounded-lg border border-border">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-[2] bg-panel">
            <tr className="border-b border-border">
              <th className="sticky left-0 z-[3] bg-panel" />
              {cols.map(c => (
                <th key={c.key} className={cx("min-w-[170px] px-3 py-2.5 text-left align-top", c.current && "bg-primary-soft/40")}>
                  <div className="fw-crop relative aspect-[4/3] w-full overflow-hidden rounded-md border border-border bg-gradient-to-b from-[#eef2f8] to-[#dfe6f0] dark:from-[#232a35] dark:to-[#1b2029]">
                    {c.rev !== null && (c.v ? c.v.views : true) ? <IsoThumb src={`/api/projects/${project.id}/revisions/${c.rev}/files/views.png`} />
                      : <div className="flex h-full items-center justify-center text-[11px] text-muted">No preview for this revision</div>}
                  </div>
                  {edit?.id === c.key
                    ? <form className="mt-1.5 flex gap-1" onSubmit={e => { e.preventDefault(); void rename(); }}>
                        <Input autoFocus value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} className="h-7" aria-label="Rename variant" maxLength={40} />
                        <button type="submit" className="rounded bg-success p-1 text-white" aria-label="Save name"><Check className="h-3.5 w-3.5" /></button></form>
                    : <div className="mt-1.5 flex items-center gap-1.5 text-[13px] font-semibold" onDoubleClick={() => c.v && setEdit({ id: c.v.id, name: c.v.name })} title={c.v ? "Double-click to rename" : undefined}>
                        {c.v && <Star className={cx("h-3.5 w-3.5 shrink-0", c.current ? "fill-primary text-primary" : "text-muted")} />}<span className="truncate">{c.name}</span></div>}
                  <div className="mt-0.5 text-[11px] font-normal text-muted">{c.rev !== null ? `rev ${c.rev}` : "not built"}{c.v?.by ? ` · ${c.v.by}` : ""}</div>
                  <div className="mt-2 flex items-center gap-1">
                    {c.current ? <Badge tone="primary">Current</Badge>
                      : <Button size="sm" loading={busy === c.key} disabled={busy !== null} onClick={() => makeCurrent(c)}>Make current</Button>}
                    {!c.current && c.rev !== null && <Tip content="3D compare with the current design" side="bottom"><button onClick={() => { onCompare(c.rev!); onClose(); }} className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-primary" aria-label={`3D compare ${c.name}`}><GitCompare className="h-4 w-4" /></button></Tip>}
                    {c.v && <Tip content="Remove variant (the revision stays)" side="bottom"><button onClick={() => remove(c.v!)} className="ml-auto rounded p-1.5 text-muted hover:bg-text/5 hover:text-danger" aria-label={`Remove ${c.name}`}><Trash2 className="h-3.5 w-3.5" /></button></Tip>}
                  </div>
                </th>))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {row("Material", c => c.s.material ?? "—", new Set(cols.map(c => c.s.material)).size > 1)}
            {row("Envelope (mm)", c => c.s.bbox?.map(v => +v.toFixed(2)).join(" × ") ?? "—", new Set(cols.map(c => JSON.stringify(c.s.bbox))).size > 1)}
            {row("Volume (mm³)", c => c.s.volume != null ? <>{num(c.s.volume, 0)}{delta(c.s.volume, ref?.volume)}</> : "—", new Set(cols.map(c => c.s.volume?.toFixed(3))).size > 1)}
            {row("Mass (g)", c => c.s.mass_g != null ? <>{num(c.s.mass_g, 1)}{delta(c.s.mass_g, ref?.mass_g)}</> : "—", new Set(cols.map(c => c.s.mass_g?.toFixed(3))).size > 1)}
            {row("Checks", c => c.s.ok ? <span className="text-success">Passed</span> : <span className="text-danger">Failing</span>)}
            {pkeys.map(k => row(k, c => { const v = c.s.params?.[k]; return v === undefined ? <span className="text-muted">—</span> : String(v); }, differs(k)))}
            {hidden > 0 && <tr><td colSpan={cols.length + 1} className="px-3 py-2 text-[12px]">
              <button onClick={() => setAllParams(!allParams)} className="link">{allParams ? "Hide identical parameters" : `Show ${hidden} identical parameter${hidden > 1 ? "s" : ""}`}</button></td></tr>}
            {cols.some(c => c.v?.note) && row("Note", c => <span className="whitespace-pre-wrap text-[12px] text-muted">{c.v?.note || ""}</span>)}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}
