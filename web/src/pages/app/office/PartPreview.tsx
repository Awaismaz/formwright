import { useState } from "react";
import { ExternalLink } from "lucide-react";
import Viewer3D, { type Tool } from "@/components/Viewer3D";
import { Button } from "@/components/ui";
import type { Pick } from "@/viewer/types";

/** The part's latest verified build, right in the ticket (orbit, measure); the Design Studio stays one click away. */
export default function PartPreview({ projectId, version, done, onOpen }: { projectId: string; version?: string; done: boolean; onOpen: () => void }) {
  const [tool, setTool] = useState<Tool>("orbit");
  const [sel, setSel] = useState<Pick[]>([]);
  return (
    <div className="overflow-hidden rounded-lg border border-border" data-part-preview>
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5 text-[12px]">
        <span className="font-medium">{done ? "Approved part" : "Latest build"}<span className="ml-1.5 text-muted">· drag to orbit, scroll to zoom</span></span>
        <Button size="sm" variant="ghost" icon={<ExternalLink className="h-3.5 w-3.5" />} onClick={onOpen}>Open in Design Studio</Button>
      </div>
      <div className="relative h-[300px]">
        <Viewer3D topoUrl={`/api/projects/${projectId}/files/topo.json`} version={version} tool={tool} onToolChange={setTool}
          selection={sel} onSelectionChange={setSel}
          empty={<div className="flex h-full items-center justify-center text-[12.5px] text-muted">No preview for this build yet.</div>} />
      </div>
    </div>
  );
}
