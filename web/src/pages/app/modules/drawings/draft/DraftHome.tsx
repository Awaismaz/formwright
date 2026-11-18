import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, PenTool, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Button, Input, Modal } from "@/components/ui";
import { localStamp } from "../types";
import { draftsApi } from "./api";
import { SCALES, SHEETS } from "./geom";

/** The 2D drawings strip on the Drawing Studio picker: "New 2D drawing" and the organisation's drafts. */
export function DraftStrip({ onOpen, canCreate = true }: { onOpen: (id: string) => void; canCreate?: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["drafts"], queryFn: draftsApi.list });
  const [open, setOpen] = useState(false);
  const items = q.data?.items ?? [];
  const remove = async (id: string, name: string) => {
    if (!confirm(`Delete "${name}" and all its revisions?`)) return;
    try { await draftsApi.remove(id); void qc.invalidateQueries({ queryKey: ["drafts"] }); toast.success("Deleted"); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not delete"); }
  };
  return (
    <div className="mb-8" data-testid="draft-strip">
      <div className="mb-3 flex items-end justify-between gap-3">
        <div>
          <h2 className="text-[20px] font-semibold tracking-tight">2D drawings</h2>
          <p className="mt-1 text-sm text-muted">Draft directly in 2D, without a 3D part: gaskets, plates, layouts, sketches for the shop. Same sheet and title block as model drawings.</p>
        </div>
        {canCreate && <Button icon={<FilePlus2 className="h-4 w-4" />} onClick={() => setOpen(true)} data-testid="new-draft">New 2D drawing</Button>}
      </div>
      {items.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map(d => (
            <div key={d.id} className="group relative rounded-lg border border-border bg-panel p-3 transition hover:border-primary/50 hover:shadow-card" data-draft={d.id}>
              <button type="button" className="block w-full text-left" onClick={() => onOpen(d.id)}>
                <div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary-soft text-primary"><PenTool className="h-4 w-4" /></span>
                  <div className="min-w-0"><div className="truncate text-[13.5px] font-semibold">{d.name}</div><div className="text-[11.5px] text-muted">Rev {d.rev} · {ago(d.updated_at)}</div></div></div>
                <div className="mt-2 text-[11.5px] text-muted">{d.summary.sheet} · {d.summary.scale} · {d.summary.entities} entities · {d.summary.dims} dims</div>
              </button>
              {canCreate && <button type="button" aria-label="Delete drawing" onClick={() => void remove(d.id, d.name)}
                className="absolute right-2 top-2 hidden rounded p-1 text-muted hover:bg-danger/10 hover:text-danger group-hover:block"><Trash2 className="h-3.5 w-3.5" /></button>}
            </div>
          ))}
        </div>
      ) : !q.isLoading && <div className="rounded-lg border border-dashed border-border p-4 text-[12.5px] text-muted">No 2D drawings yet.</div>}
      <NewDraftDialog open={open} onOpenChange={setOpen} onCreated={id => { void qc.invalidateQueries({ queryKey: ["drafts"] }); onOpen(id); }} />
    </div>
  );
}

function NewDraftDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (v: boolean) => void; onCreated: (id: string) => void }) {
  const tq = useQuery({ queryKey: ["draft-templates"], queryFn: draftsApi.templates, staleTime: Infinity, enabled: open });
  const [name, setName] = useState("");
  const [size, setSize] = useState("A3");
  const [orientation, setOrientation] = useState<"landscape" | "portrait">("landscape");
  const [scale, setScale] = useState("1:1");
  const [projection, setProjection] = useState<"first" | "third">("first");
  const [units, setUnits] = useState<"mm" | "in">("mm");
  const [template, setTemplate] = useState("");
  const [vals, setVals] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const def = tq.data?.items.find(t => t.name === template);
  const create = async () => {
    setBusy(true);
    try {
      const [n, d] = scale.split(":").map(Number);
      const r = await draftsApi.create({ name: name.trim() || (def ? def.label : "Untitled 2D drawing"), sheet: { size, orientation, scale: [n!, d!], projection, units },
        template: template || null, params: template ? Object.fromEntries((def?.params ?? []).map(p => [p.key, vals[p.key] ?? p.default])) : {}, ...localStamp() });
      onOpenChange(false); onCreated(r.id);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "The drawing could not be created."); }
    finally { setBusy(false); }
  };
  const sel = "input h-9 py-0 text-[13px]";
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="New 2D drawing" description="A drawing made directly in 2D. It is not linked to a 3D model, so no model-consistency check runs on it." wide
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={busy} onClick={() => void create()} data-testid="create-draft">Create drawing</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-[12.5px] sm:col-span-2"><span className="text-muted">Name</span><Input value={name} maxLength={80} autoFocus placeholder="e.g. Pump flange gasket" onChange={e => setName(e.target.value)} data-testid="draft-name" /></label>
        <label className="block text-[12.5px]"><span className="text-muted">Sheet size</span><select className={sel} value={size} onChange={e => setSize(e.target.value)}>{Object.keys(SHEETS).map(s => <option key={s}>{s}</option>)}</select></label>
        <label className="block text-[12.5px]"><span className="text-muted">Orientation</span><select className={sel} value={orientation} onChange={e => setOrientation(e.target.value as "landscape" | "portrait")}><option value="landscape">Landscape</option><option value="portrait">Portrait</option></select></label>
        <label className="block text-[12.5px]"><span className="text-muted">Scale{template ? " (fitted to the part)" : ""}</span><select className={sel} value={scale} disabled={!!template} onChange={e => setScale(e.target.value)}>{SCALES.map(([n, d]) => <option key={`${n}:${d}`}>{`${n}:${d}`}</option>)}</select></label>
        <label className="block text-[12.5px]"><span className="text-muted">Projection</span><select className={sel} value={projection} onChange={e => setProjection(e.target.value as "first" | "third")}><option value="first">First angle (ISO E)</option><option value="third">Third angle (ISO A)</option></select></label>
        <label className="block text-[12.5px]"><span className="text-muted">Units</span><select className={sel} value={units} onChange={e => setUnits(e.target.value as "mm" | "in")}><option value="mm">Millimetres</option><option value="in">Inches</option></select></label>
        <label className="block text-[12.5px]"><span className="text-muted">Start from</span><select className={sel} value={template} onChange={e => { setTemplate(e.target.value); const t = tq.data?.items.find(x => x.name === e.target.value); setVals(Object.fromEntries((t?.params ?? []).map(p => [p.key, p.default]))); }} data-testid="draft-template">
          <option value="">Blank sheet</option>{tq.data?.items.map(t => <option key={t.name} value={t.name}>{t.label} (template)</option>)}</select></label>
      </div>
      {def && <div className={cx("mt-4 grid gap-2 rounded-lg border border-border bg-panel2 p-3 sm:grid-cols-2")}>
        {def.params.map(p => (
          <label key={p.key} className="flex items-center justify-between gap-2 text-[12.5px]"><span className="text-muted">{p.label}</span>
            <input type="number" step={p.integer ? 1 : 0.5} value={vals[p.key] ?? p.default} onChange={e => setVals(v => ({ ...v, [p.key]: parseFloat(e.target.value) }))}
              className="h-8 w-24 rounded border border-border bg-panel px-1.5 text-right tabular-nums outline-none focus:border-primary" /></label>))}
        <p className="text-[11.5px] text-muted sm:col-span-2">Geometry and dimensions are generated exactly from these values (no AI). You can edit everything afterwards.</p>
      </div>}
    </Modal>
  );
}
