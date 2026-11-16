import { useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Film, History, Image as ImageIcon, Info, MoreHorizontal, Package, RefreshCw, SlidersHorizontal, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { Badge, Button, Menu, MenuContent, MenuItem, MenuTrigger, Modal, Progress, Spinner } from "@/components/ui";
import type { Job, MeshCheck, ProjectInfo } from "./types";

const DL: Record<string, string> = {
  "render.png": "PNG image", "scene.blend": "Blender scene (.blend)", "turntable.gif": "Turntable GIF",
  "turntable.mp4": "Turntable MP4", "part.glb": "GLB (glTF binary)", "part_obj.zip": "OBJ + MTL (zip)", "part.stl": "STL",
};
export const CHECKER = { backgroundColor: "#f3f4f6", backgroundImage: "linear-gradient(45deg,#e5e7eb 25%,transparent 25%,transparent 75%,#e5e7eb 75%),linear-gradient(45deg,#e5e7eb 25%,transparent 25%,transparent 75%,#e5e7eb 75%)", backgroundSize: "16px 16px", backgroundPosition: "0 0, 8px 8px" };
export const mb = (b: number) => b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} kB`;

export function deviceLine(j: Job): string | null {
  if (!j.device) return null;
  const dev = j.device.device === "GPU" ? `GPU${j.device.gpu ? ` (${j.device.gpu.replace("NVIDIA GeForce ", "")})` : ""}` : "CPU";
  const ev = j.highlights && j.highlights.ev < -0.05 ? ` · exposure ${j.highlights.ev.toFixed(1).replace("-", "−")} EV` : "";
  return `${j.device.engine} ${dev} · ${j.device.samples} samples${j.render_seconds ? ` · ${j.render_seconds.toFixed(1)} s` : ""}${ev}`;
}

/** "about 4 min left" from the job's ETA (seconds), or null before there is one. */
export function etaText(s?: number | null): string | null {
  if (s == null) return null;
  if (s < 50) return "under a minute left";
  return `about ${Math.round(s / 60)} min left`;
}

/** The part revision a render shows; "Earlier revision" when the project has been rebuilt since. */
export function RevChip({ j, className }: { j: Job; className?: string }) {
  if (!j.stale) return null;
  return (
    <span className={`inline-flex items-center gap-1 rounded bg-warning/90 px-1.5 py-0.5 text-[10.5px] font-semibold text-black ${className ?? ""}`} data-stale
      title="The part has been rebuilt since this was made. It shows an earlier revision of the design.">
      <History className="h-3 w-3" />Earlier revision{j.revision ? ` · rev ${j.revision}` : ""}
    </span>
  );
}

function Pending({ j }: { j: Job }) {
  const eta = j.state === "running" ? etaText(j.eta_s) : null;
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-2 px-4 pt-5 text-center text-[12px] text-muted">
      {j.state === "failed" ? <><XCircle className="h-5 w-5 text-danger" /><span>{j.error ?? "Render failed"}</span></> : <>
        <Spinner className="h-5 w-5" />
        <span>{j.state === "queued" ? `Queued${j.queue_position ? ` · #${j.queue_position}` : ""}` : j.phase ?? "Rendering"}</span>
        <Progress value={(j.progress ?? 0) * 100} className="w-3/4" />
        {eta && <span className="text-[11px]" data-eta>{eta}</span>}
      </>}
    </div>
  );
}

function HighlightNote({ j }: { j: Job }) {
  const h = j.highlights;
  if (!h) return null;
  if (!h.ok) return <p className="mt-1.5 flex items-start gap-2 text-[12px] text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />Some highlights are blown out ({Math.round((h.blown ?? 0) * 100)} % of the part is near white). Studio softbox lighting or a darker finish keeps more detail.</p>;
  if (h.ev < -0.05) return <p className="mt-1.5 flex items-start gap-2 text-[12px] text-muted"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />Exposure lowered by {Math.abs(h.ev).toFixed(1)} EV so highlights keep their detail.</p>;
  return null;
}

export function Gallery({ pid, items, canEdit, onChanged, onUse, onRerender }: {
  pid: string; items: Job[]; canEdit: boolean; onChanged: () => void; onUse: (j: Job) => void; onRerender: (j: Job) => void;
}) {
  const [open, setOpen] = useState<Job | null>(null);
  const del = async (j: Job) => {
    try { await api.del(`/api/m/mesh/projects/${pid}/jobs/${j.id}`); onChanged(); if (open?.id === j.id) setOpen(null); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Delete failed"); }
  };
  if (!items.length) return (
    <div className="px-4 py-10 text-center text-[13px] text-muted">
      <ImageIcon className="mx-auto mb-2 h-6 w-6" />Final renders and turntables appear here, with downloads and the editable Blender scene.
    </div>
  );
  return (
    <>
      <div className="grid grid-cols-2 gap-2 p-3" data-gallery>
        {items.map(j => {
          const thumb = j.files["thumb.jpg"]?.url;
          return (
            <div key={j.id} className="group relative overflow-hidden rounded-md border border-border bg-panel2" data-job={j.id} data-state={j.state}>
              <button className="block aspect-[4/3] w-full" onClick={() => j.state === "done" && setOpen(j)} aria-label={`Open ${j.label ?? "render"}`}>
                {j.state === "done" && thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" /> : <Pending j={j} />}
              </button>
              {j.kind === "turntable" && <span className="absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded bg-black/55 px-1.5 py-0.5 text-[10.5px] font-medium text-white"><Film className="h-3 w-3" />{j.frames && j.frames < 72 ? "Quick turntable" : "Turntable"}</span>}
              {j.state === "done" && <RevChip j={j} className="absolute bottom-[38px] left-1.5" />}
              <div className="flex items-center gap-1 border-t border-border bg-panel px-2 py-1">
                <span className="min-w-0 flex-1 leading-tight" title={j.label ?? ""}>
                  <span className="block truncate text-[11.5px] font-medium">{(j.label ?? "Render").split(" · ")[0]}</span>
                  <span className="block truncate text-[10.5px] text-muted">{j.state === "done" ? `${(j.label ?? "").split(" · ").slice(1).join(" · ")} · ${ago(j.finished_at ?? j.created_at)}` : j.state === "failed" ? "Failed" : "In progress"}</span>
                </span>
                <Menu>
                  <MenuTrigger className="rounded p-0.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Render actions"><MoreHorizontal className="h-4 w-4" /></MenuTrigger>
                  <MenuContent>
                    {Object.entries(j.files).filter(([n]) => DL[n]).map(([n, f]) => (
                      <MenuItem key={n} icon={<Download />} onSelect={() => { window.location.href = `${f.url}?dl=1`; }}>{DL[n]} <span className="ml-auto pl-3 text-xs text-muted">{mb(f.bytes)}</span></MenuItem>
                    ))}
                    {canEdit && j.state !== "queued" && j.state !== "running" && <MenuItem icon={<RefreshCw />} onSelect={() => onRerender(j)}>{j.stale ? "Re-render on the current part" : "Render again"}</MenuItem>}
                    {canEdit && j.state === "done" && <MenuItem icon={<SlidersHorizontal />} onSelect={() => onUse(j)}>Use these settings</MenuItem>}
                    {canEdit && <MenuItem danger icon={<Trash2 />} onSelect={() => del(j)}>{j.state === "queued" ? "Cancel" : "Delete"}</MenuItem>}
                  </MenuContent>
                </Menu>
              </div>
            </div>
          );
        })}
      </div>
      <Modal open={!!open} onOpenChange={v => !v && setOpen(null)} wide title={open?.label ?? "Render"}
        description={open ? `${open.revision ? `Revision ${open.revision} · ` : ""}${open.size ? `${open.size[0]} × ${open.size[1]} px · ` : ""}${deviceLine(open) ?? ""}` : undefined}
        footer={open && <>
          {canEdit && <Button size="sm" variant="ghost" icon={<SlidersHorizontal className="h-4 w-4" />} onClick={() => { onUse(open); setOpen(null); }} data-action="use-look">Use these settings</Button>}
          {canEdit && open.stale && <Button size="sm" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} onClick={() => { onRerender(open); setOpen(null); }}>Re-render on the current part</Button>}
          {Object.entries(open.files).filter(([n]) => DL[n]).map(([n, f]) => (
            <a key={n} href={`${f.url}?dl=1`}><Button size="sm" variant={n === "render.png" ? "primary" : "secondary"} icon={<Download className="h-4 w-4" />}>{DL[n]!.replace(" (.blend)", "")}</Button></a>
          ))}
        </>}>
        {open && <>
          <div className="overflow-hidden rounded-md border border-border" style={CHECKER}>
            {open.files["turntable.gif"] ? <img src={open.files["turntable.gif"].url} alt="Turntable" className="block w-full" />
              : <img src={open.files["render.png"]?.url} alt="Render" className="block w-full" />}
          </div>
          {open.stale && <p className="mt-3 flex items-start gap-2 text-[12px] text-warning" data-stale-note><History className="mt-0.5 h-3.5 w-3.5 shrink-0" />This shows an earlier revision{open.revision ? ` (rev ${open.revision})` : ""}. The part has been rebuilt since.</p>}
          <HighlightNote j={open} />
          <p className="mt-1.5 flex items-start gap-2 text-[12px] text-muted"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{open.disclosure}</p>
        </>}
      </Modal>
    </>
  );
}

export function Exports({ pid, items, canEdit, busy, onExport, onChanged, onRerender, finishLabel }: {
  pid: string; items: Job[]; canEdit: boolean; busy: boolean; onExport: () => void; onChanged: () => void; onRerender: (j: Job) => void; finishLabel: string;
}) {
  const del = async (j: Job) => {
    try { await api.del(`/api/m/mesh/projects/${pid}/jobs/${j.id}`); onChanged(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Delete failed"); }
  };
  return (
    <div className="p-3 text-[13px]">
      <p className="text-muted">Visualisation meshes for web viewers, AR, slide tools and other renderers: GLB (metres, Y up, with the finish as a flat PBR colour), OBJ and STL (millimetres, Z up).</p>
      {canEdit && <Button className="mt-3 w-full" variant="secondary" loading={busy} icon={<Package className="h-4 w-4" />} onClick={onExport} data-action="export">Export meshes · {finishLabel}</Button>}
      <div className="mt-3 space-y-2">
        {items.map(j => (
          <div key={j.id} className="rounded-md border border-border p-2.5" data-export={j.id} data-state={j.state}>
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-medium">{j.label}</span>
              {j.state === "done" && <RevChip j={j} />}
              {canEdit && j.state !== "running" && <button aria-label="Delete export" onClick={() => del(j)} className="rounded p-0.5 text-muted hover:text-danger"><Trash2 className="h-3.5 w-3.5" /></button>}
            </div>
            {j.state === "done" ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(j.files).filter(([n]) => DL[n]).map(([n, f]) => (
                  <a key={n} href={`${f.url}?dl=1`} className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[12px] hover:bg-panel2"><Download className="h-3 w-3" />{n.endsWith(".zip") ? "OBJ" : n.split(".").pop()!.toUpperCase()} <span className="text-muted">{mb(f.bytes)}</span></a>
                ))}
                {canEdit && j.stale && <button onClick={() => onRerender(j)} className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[12px] text-primary hover:bg-panel2"><RefreshCw className="h-3 w-3" />Export the current part</button>}
              </div>
            ) : j.state === "failed" ? <div className="mt-1 text-[12px] text-danger">{j.error}</div>
              : <div className="mt-2 flex items-center gap-2 text-[12px] text-muted"><Spinner className="h-3.5 w-3.5" />{j.state === "queued" ? `Queued${j.queue_position ? ` · #${j.queue_position}` : ""}` : j.phase}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

const ICON: Record<MeshCheck["status"], JSX.Element> = {
  pass: <CheckCircle2 className="h-4 w-4 text-success" />, warn: <AlertTriangle className="h-4 w-4 text-warning" />,
  fail: <XCircle className="h-4 w-4 text-danger" />, info: <Info className="h-4 w-4 text-muted" />,
};

export function MeshPanel({ info }: { info: ProjectInfo }) {
  const m = info.mesh;
  return (
    <div className="p-3 text-[13px]">
      <div className="rounded-md border border-warning/30 bg-warning/5 p-2.5 text-[12px]"><b>Visualisation mesh, not the exact model.</b> {info.disclosure}</div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12.5px]">
        <dt className="text-muted">Triangles</dt><dd className="text-right tabular-nums">{m.triangles.toLocaleString()}</dd>
        <dt className="text-muted">Chordal tolerance</dt><dd className="text-right tabular-nums">{m.tolerance_mm} mm</dd>
        <dt className="text-muted">Size</dt><dd className="text-right tabular-nums">{m.bbox_mm.map(x => x.toFixed(1)).join(" × ")} mm</dd>
      </dl>
      <div className="mt-3 label">Mesh checks</div>
      <ul className="mt-1.5 divide-y divide-border rounded-md border border-border" data-checks>
        {m.checks.map(c => (
          <li key={c.id} className="flex items-start gap-2 px-2.5 py-2" data-check={c.id} data-status={c.status}>
            <span className="mt-0.5">{ICON[c.status]}</span>
            <div className="min-w-0"><div className="font-medium">{c.name}</div><div className="text-[12px] text-muted">{c.detail}</div></div>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11.5px] text-muted">Measured by the same mesh checks as 3D Print Prep. <Badge>Verified calculation</Badge></p>
    </div>
  );
}

