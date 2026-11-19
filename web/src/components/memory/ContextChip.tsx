import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Brain, FolderPlus, Folders } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentContextView } from "@/lib/designProjects";
import { Button, Modal } from "@/components/ui";
import ProjectPicker from "./ProjectPicker";

function Contents({ v }: { v: AgentContextView }) {
  return (
    <div className="space-y-2.5 text-[12.5px] leading-snug">
      {v.project ? <div>
        <div className="font-semibold">Project · {v.project.name}</div>
        {v.parts.length ? <ul className="mt-1 space-y-1">{v.parts.map(p => <li key={p.id} className="text-muted"><span className="font-medium text-text">{p.name}</span>{p.summary.slice(p.name.length)}</li>)}</ul>
          : <div className="text-muted">No other parts yet.</div>}
        {v.decisions.length > 0 && <div className="mt-1.5"><div className="font-medium">Decisions</div>
          <ul className="list-disc pl-4 text-muted">{v.decisions.map(d => <li key={d}>{d}</li>)}</ul></div>}
      </div> : <div className="text-muted">This part is not in a project. Add it to one so the agent knows the parts it must fit.</div>}
      {v.preferences.length > 0 ? <div><div className="font-semibold">Your preferences</div>
        <ul className="list-disc pl-4 text-muted">{v.preferences.map(p => <li key={p}>{p}</li>)}</ul></div>
        : !v.use ? <div className="text-muted">Your preferences are switched off for the agent.</div> : null}
    </div>);
}

/** Studio chat: what the design agent knows beyond this part (project siblings, decisions, preferences). */
export default function ContextChip({ projectId, partName, canEdit }: { projectId: string; partName: string; canEdit: boolean }) {
  const q = useQuery({ queryKey: ["agent-context", projectId], staleTime: 20_000,
    queryFn: () => api.get<AgentContextView>(`/api/projects/${projectId}/agent-context`) });
  const [open, setOpen] = useState(false);
  const [pick, setPick] = useState(false);
  const v = q.data;
  if (!v) return null;
  const n = v.parts.length, prefs = v.preferences.length;
  const label = v.project ? v.project.name : prefs ? `${prefs} preference${prefs === 1 ? "" : "s"}` : "No project";
  return (
    <>
      <Tooltip.Root delayDuration={200}>
        <Tooltip.Trigger asChild>
          <button onClick={() => setOpen(true)} data-testid="context-chip"
            className="inline-flex min-w-0 max-w-[55%] items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11.5px] text-muted hover:border-primary/50 hover:text-text">
            {v.project ? <Folders className="h-3.5 w-3.5 shrink-0 text-primary" /> : prefs ? <Brain className="h-3.5 w-3.5 shrink-0 text-accent" /> : <FolderPlus className="h-3.5 w-3.5 shrink-0" />}
            <span className="truncate">{label}</span>
            {v.project && (n > 0 || prefs > 0) && <span className="shrink-0 tabular-nums">· {n ? `${n} part${n === 1 ? "" : "s"}` : ""}{n && prefs ? " · " : ""}{prefs ? <Brain className="inline h-3 w-3 text-accent" /> : null}</span>}
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="bottom" align="start" sideOffset={6} className="z-50 w-80 rounded-lg border border-border bg-panel p-3 text-text shadow-pop">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">The design agent also knows</div>
            <Contents v={v} />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
      <Modal open={open} onOpenChange={setOpen} title="What the design agent knows"
        description="Besides this part, every conversation starts with this. It is sent again only when it changes."
        footer={<>
          <Link to="/app/settings?tab=memory" className="mr-auto self-center text-[13px] text-primary hover:underline" onClick={() => setOpen(false)}>Manage my memory</Link>
          {v.project ? <Link to={`/app/p/${v.project.id}`} onClick={() => setOpen(false)}><Button variant="secondary">Open project</Button></Link>
            : canEdit && <Button icon={<FolderPlus className="h-4 w-4" />} onClick={() => { setOpen(false); setPick(true); }}>Add to project</Button>}</>}>
        <Contents v={v} />
      </Modal>
      {pick && <ProjectPicker open onOpenChange={setPick} part={{ id: projectId, name: partName }} current={v.project} onDone={() => q.refetch()} />}
    </>
  );
}
