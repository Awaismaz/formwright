import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Camera, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button } from "@/components/ui";
import type { Settings, Shots } from "./types";

/** Living datasheet pack (ASM-018): the shots this part's datasheet needs. A shot is stale once the part revised;
 *  "Re-render stale" queues every stale shot with its saved look. */
export default function DatasheetPanel({ base, pid, settings, canEdit }: { base: string; pid: string; settings: Settings | null; canEdit: boolean }) {
  const qc = useQueryClient();
  const key = ["mesh-shots-panel", pid];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<Shots>(`${base}/shots`),
    refetchInterval: d => (d.state.data?.shots.some(s => s.job && (s.job.state === "queued" || s.job.state === "running")) ? 2000 : false) });
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (what: string, fn: () => Promise<Shots>, ok?: (r: Shots) => string) => {
    setBusy(what);
    try { const r = await fn(); qc.setQueryData(key, r); qc.invalidateQueries({ queryKey: ["mesh-shots", pid] }); qc.invalidateQueries({ queryKey: ["mesh-jobs", base] }); if (ok) toast.success(ok(r)); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
    finally { setBusy(null); }
  };
  const d = q.data;
  return (
    <div className="space-y-2 p-3 text-[12.5px]" data-testid="datasheet-panel">
      <p className="text-[12px] text-muted">The renders your datasheet needs. When the part changes, they are marked stale; re-render them in one click.</p>
      {canEdit && <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} disabled={!settings} loading={busy === "add"}
          onClick={() => settings && run("add", () => api.post<Shots>(`${base}/shots`, { ...settings, quality: "final" }), () => "Shot added to the datasheet pack")}>Add current look</Button>
        <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} disabled={!d?.stale} loading={busy === "rerender"}
          onClick={() => run("rerender", () => api.post<Shots>(`${base}/shots/rerender`), r => `${r.queued?.length ?? 0} render${(r.queued?.length ?? 0) === 1 ? "" : "s"} queued`)}>Re-render stale{d?.stale ? ` (${d.stale})` : ""}</Button>
      </div>}
      {!d?.shots.length ? <p className="rounded border border-dashed border-border p-3 text-center text-muted">No shots yet. Set up a look and add it.</p>
        : <ul className="space-y-1.5">{d.shots.map(s => (
          <li key={s.id} className="flex items-center gap-2 rounded border border-border px-2 py-1.5">
            {s.job?.files["thumb.jpg"] ? <img src={s.job.files["thumb.jpg"].url} alt="" className="h-9 w-12 rounded object-cover" /> : <Camera className="h-4 w-4 text-muted" />}
            <div className="min-w-0 flex-1">
              <div className="truncate">{s.label}</div>
              <div className={cx("text-[11px]", s.stale ? "text-warning" : "text-muted")}>
                {s.stale ? (s.build_id == null ? "Not rendered yet" : `Stale: shows rev ${s.revision ?? "?"}, the part is now rev ${d.revision ?? "?"}`)
                  : s.job && (s.job.state === "queued" || s.job.state === "running") ? "Rendering…" : `Current (rev ${s.revision ?? d.revision ?? "?"})`}</div>
            </div>
            {canEdit && <button aria-label="Remove shot" className="rounded p-1 text-muted hover:bg-text/5" onClick={() => run("del", () => api.del<Shots>(`${base}/shots/${s.id}`))}><Trash2 className="h-3.5 w-3.5" /></button>}
          </li>))}</ul>}
    </div>
  );
}
