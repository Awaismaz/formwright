import { useQuery } from "@tanstack/react-query";
import { Loader2, PanelLeftOpen, SlidersHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentEdit, Impact, Project } from "@/lib/types";
import { Button } from "@/components/ui";
import { impactChange } from "./agentEdit";
import { ImpactDetails } from "./ImpactPanel";

const OP_LABEL: Record<AgentEdit["op"], string> = { fillet: "Fillet", chamfer: "Chamfer", shell: "Shell", hole: "Hole Wizard", params: "Modify dimensions" };

/** DS-035: the agent's small edit in the chat. It opens the real PropertyManager pre-filled (automatically when it
 *  arrives); before anything is applied, the impact on assemblies using this part is shown here (ASM-018). */
export default function EditCard({ project, edit, usedIn, active, onOpen }: {
  project: Project; edit: AgentEdit; usedIn: number; active: boolean; onOpen: (e: AgentEdit) => void;
}) {
  const change = impactChange(edit);
  const q = useQuery({
    queryKey: ["impact", project.id, edit.build_id, JSON.stringify(change)],
    queryFn: () => api.post<Impact>(`/api/m/assembly/impact/${project.id}`, change),
    enabled: active && usedIn > 0 && !!change, retry: false, staleTime: Infinity,
  });
  const n = edit.targets?.picks.length ?? 0;
  return (
    <div className="rounded-lg border border-accent/40 bg-accent/5 px-3 py-2.5" data-testid="edit-card">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-accent">
        <SlidersHorizontal className="h-3 w-3" />{OP_LABEL[edit.op]}{edit.feature_id ? " · edit" : ""}</div>
      <div className="text-[13px] font-medium">{edit.summary}</div>
      {edit.op === "params" && edit.params && <ul className="mt-0.5 text-[12px] text-muted">{Object.entries(edit.params).map(([k, r]) =>
        <li key={k}>{r.label}: {r.from} → <b className="text-text">{r.to}</b>{r.unit ? ` ${r.unit}` : ""}</li>)}</ul>}
      {n > 0 && <div className="text-[12px] text-muted">{n} {edit.targets!.kind === "edge" ? "edge" : "face"}{n > 1 ? "s" : ""} highlighted in the viewer</div>}
      {usedIn > 0 && active && <div className="mt-1.5 rounded border border-border bg-panel px-2 py-1.5">
        {q.isLoading ? <span className="flex items-center gap-1.5 text-[12px] text-muted"><Loader2 className="h-3 w-3 animate-spin" />Checking {usedIn} assembl{usedIn > 1 ? "ies" : "y"} on a trial rebuild…</span>
          : q.data ? <ImpactDetails impact={q.data} compact />
          : q.error ? <span className="text-[12px] text-muted">{(q.error as Error).message}</span> : null}
      </div>}
      {active && <div className="mt-2 flex items-center gap-2">
        <Button size="sm" icon={<PanelLeftOpen className="h-3.5 w-3.5" />} onClick={() => onOpen(edit)}>Open in PropertyManager</Button>
        <span className="text-[11px] text-muted">Nothing changes until you press OK</span>
      </div>}
    </div>
  );
}
