import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Badge, Modal } from "@/components/ui";
import { BASE } from "../api";
import type { Program } from "../types";
import PlanPreview from "./PlanPreview";
import type { PreviewCompare, PreviewData } from "./types";

/** Items that moved, appeared or went between two layouts (by item id and placement). */
export function layoutDiff(a: PreviewData, b: PreviewData): { moved: string[]; added: string[]; removed: string[] } {
  const place = (d: PreviewData) => {
    const m = new Map<string, string>();
    for (const x of d.bodies) if (!x.standard) m.set(x.item, (m.get(x.item) ?? "") + x.T.map(v => v.toFixed(2)).join(",") + JSON.stringify(x.g) + ";");
    return m;
  };
  const pa = place(a), pb = place(b);
  const moved = [...pb.keys()].filter(k => pa.has(k) && pa.get(k) !== pb.get(k));
  return { moved, added: [...pb.keys()].filter(k => !pa.has(k)), removed: [...pa.keys()].filter(k => !pb.has(k)) };
}

function CompareBody({ program, rkey }: { program: Program; rkey: string }) {
  const q = useQuery({
    queryKey: ["office-preview-compare", program.id, rkey], retry: false, staleTime: 60_000,
    queryFn: () => api.get<PreviewCompare>(`${BASE}/programs/${program.id}/preview/compare/${encodeURIComponent(rkey)}`),
  });
  const [hot, setHot] = useState<string | null>(null);
  const diff = useMemo(() => (q.data ? layoutDiff(q.data.before, q.data.after) : null), [q.data]);
  if (q.error) return <p className="text-[12.5px] text-muted">{q.error instanceof ApiError ? q.error.message : "The comparison could not be laid out."}</p>;
  const changed = diff ? [...diff.moved, ...diff.added, ...diff.removed] : [];
  return (
    <div data-revision-compare={rkey}>
      {diff && <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[12px]">
        <Badge tone={diff.moved.length ? "warning" : "neutral"}>{diff.moved.length} re-placed or resized</Badge>
        <Badge tone={diff.added.length ? "primary" : "neutral"}>{diff.added.length} added</Badge>
        <Badge tone={diff.removed.length ? "danger" : "neutral"}>{diff.removed.length} removed</Badge>
        <span className="text-muted">Changed parts are highlighted in both views; hover a part to find it in the other.</span>
      </div>}
      <div className="grid gap-2 md:grid-cols-2">
        <PlanPreview compact testId="before" data={q.data?.before} loading={q.isFetching} hot={hot} onHot={setHot} height={320}
          highlight={hot ? undefined : changed} title={`Before${q.data?.before.icd_version ? ` (ICD v${q.data.before.icd_version})` : ""}`} />
        <PlanPreview compact testId="after" data={q.data?.after} loading={q.isFetching} hot={hot} onHot={setHot} height={320}
          highlight={hot ? undefined : changed} title={`After${q.data?.after.icd_version ? ` (ICD v${q.data.after.icd_version})` : ""}`} />
      </div>
    </div>
  );
}

/** "Before and after in 3D" for a program revision (applied: its revision id; proposed: Archie's log entry id). */
export default function RevisionCompare({ program, rkey, title }: { program: Program; rkey: string; title: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className="mt-1 inline-flex items-center gap-1 text-[12px] text-primary hover:underline" onClick={() => setOpen(true)} data-compare-open={rkey}>
      <Boxes className="h-3.5 w-3.5" />Before and after in 3D</button>
    <Modal open={open} onOpenChange={setOpen} wide title={title}
      description="Both layouts dimensioned, from the interfaces before and after the revision. No CAD build: the parts are verified when they are rebuilt.">
      {open && <CompareBody program={program} rkey={rkey} />}
    </Modal>
  </>;
}
