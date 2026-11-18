import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Tip } from "@/components/ui";
import type { Shots } from "./types";

/** Design Studio header chip (ASM-018): the datasheet renders of this part are stale after a revision; one click queues
 *  every stale shot (renders run in the background in Mesh Studio). Renders nothing when nothing is stale. */
export function DatasheetChip({ projectId, buildId }: { projectId: string; buildId?: string | number | null }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["mesh-shots", projectId, buildId], queryFn: () => api.get<Shots>(`/api/m/mesh/projects/${projectId}/shots`),
    retry: false, staleTime: 30_000 });
  const [busy, setBusy] = useState(false);
  const n = q.data?.stale ?? 0;
  if (!n) return null;
  const rerender = async () => {
    setBusy(true);
    try {
      const r = await api.post<Shots>(`/api/m/mesh/projects/${projectId}/shots/rerender`);
      toast.success(`${r.queued?.length ?? 0} datasheet render${(r.queued?.length ?? 0) === 1 ? "" : "s"} queued · Mesh Studio shows the progress`);
      qc.setQueryData(["mesh-shots", projectId, buildId], r);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't queue the renders"); }
    finally { setBusy(false); }
  };
  return (
    <Tip content={`${n} datasheet render${n > 1 ? "s show" : " shows"} an older revision of this part. Re-render queues ${n > 1 ? "them" : "it"}.`} side="bottom">
      <button onClick={() => void rerender()} disabled={busy} data-testid="datasheet-chip"
        className="inline-flex shrink-0 items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-1.5 py-px text-[11px] font-medium text-warning hover:bg-warning/20 disabled:opacity-60">
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Camera className="h-3 w-3" />}{n} render{n > 1 ? "s" : ""} stale · Re-render
      </button>
    </Tip>
  );
}
