import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Box, ScanSearch } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Modal, Spinner } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";

export interface Match { project: Project; score: number; reasons: string[] }

/** One matching part: thumbnail, name, match %, and the reasons it matched. */
export function MatchRow({ m, onOpen }: { m: Match; onOpen?: () => void }) {
  const tone = m.score >= 90 ? "bg-success" : m.score >= 70 ? "bg-primary" : "bg-muted";
  return (
    <Link to={`/app/projects/${m.project.id}`} onClick={onOpen}
      className="group flex items-center gap-3 rounded-lg border border-border bg-panel p-2 transition hover:border-primary/60 hover:shadow-card">
      <div className="relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-md bg-gradient-to-b from-[#eef2f8] to-[#dfe6f0] dark:from-[#232a35] dark:to-[#1b2029]">
        {m.project.thumbnail ? <IsoThumb src={`${m.project.thumbnail}?v=${m.project.last_status?.build_id ?? 0}`} /> : <Box className="h-6 w-6 text-muted/50" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13.5px] font-medium group-hover:text-primary">{m.project.name}</span>
          {m.project.last_status?.material && <span className="truncate text-[11px] text-muted">{m.project.last_status.material}</span>}
        </div>
        <ul className="mt-0.5 space-y-px text-[11.5px] leading-snug text-muted">{m.reasons.slice(0, 3).map(r => <li key={r} className="truncate">{r}</li>)}</ul>
      </div>
      <div className="w-14 shrink-0 text-right">
        <div className="text-[15px] font-semibold tabular-nums">{Math.round(m.score)}%</div>
        <div className="mt-1 h-1 overflow-hidden rounded-full bg-text/10"><div className={cx("h-full rounded-full", tone)} style={{ width: `${Math.max(4, m.score)}%` }} /></div>
      </div>
    </Link>
  );
}

/** Studio dialog: parts in this workspace that look like the current one. */
export function SimilarPartsDialog({ projectId, open, onClose }: { projectId: string; open: boolean; onClose: () => void }) {
  const q = useQuery({ queryKey: ["similar", projectId], enabled: open, retry: false,
    queryFn: () => api.get<{ reference: { dims: number[] }; items: Match[] }>(`/api/search/similar/${projectId}`) });
  const err = q.error instanceof ApiError ? q.error.message : q.error ? "Search failed" : null;
  return (
    <Modal wide open={open} onOpenChange={o => !o && onClose()} title="Similar parts"
      description={q.data ? `Parts in this workspace that resemble this one (${q.data.reference.dims.map(d => +d.toFixed(2)).join(" × ")} mm): same envelope, same proportions, same holes. Reuse before you remodel.` : "Looking through every part in this workspace…"}>
      {q.isLoading ? <div className="flex justify-center py-8"><Spinner /></div>
        : err ? <p className="py-4 text-sm text-muted">{err}</p>
        : !q.data?.items.length ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center text-sm text-muted"><ScanSearch className="h-8 w-8 text-muted/50" />
            Nothing similar yet. This part looks new to your workspace.</div>)
        : <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">{q.data.items.map(m => <MatchRow key={m.project.id} m={m} onOpen={onClose} />)}</div>}
    </Modal>
  );
}
