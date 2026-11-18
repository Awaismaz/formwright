import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Tip } from "@/components/ui";

interface Used { id: string; name: string; instances: number; stale: number; broken_mates: number }

/** "In n assemblies" chip for the Design Studio header (AMI-10): where this part is used, and whether those
 * assemblies still show an older build or have broken mates. Renders nothing without the module or any use. */
export function useWhereUsed(projectId: string, buildId?: string | number | null, enabled = true): Used[] {
  const q = useQuery({
    queryKey: ["asm-where-used", projectId, buildId],
    queryFn: () => api.get<{ items: Used[] }>(`/api/m/assembly/where-used/${projectId}`),
    retry: false, staleTime: 30_000, enabled,
  });
  return q.data?.items ?? [];
}

export function WhereUsed({ projectId, buildId }: { projectId: string; buildId?: string | number | null }) {
  const items = useWhereUsed(projectId, buildId);
  if (!items.length) return null;
  const behind = items.filter(a => a.stale > 0 || a.broken_mates > 0);
  const first = behind[0] ?? items[0]!;
  const tip = items.map(a => `${a.name}${a.stale ? " · shows an older build: refresh it there" : ""}${a.broken_mates ? ` · ${a.broken_mates} broken mate${a.broken_mates > 1 ? "s" : ""}` : ""}`).join("\n");
  return (
    <Tip content={<span className="whitespace-pre-line">{tip}</span>} side="bottom">
      <Link to={`/app/modules/assembly?assembly=${first.id}`} data-testid="where-used"
        className={cx("inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-px text-[11px] font-medium",
          behind.length ? "border-warning/40 bg-warning/10 text-warning" : "border-border text-muted hover:text-text")}>
        <Boxes className="h-3 w-3" />In {items.length} assembl{items.length > 1 ? "ies" : "y"}{behind.length ? " · update" : ""}
      </Link>
    </Tip>
  );
}
