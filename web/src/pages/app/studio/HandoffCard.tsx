import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, Download, PackageCheck, Stamp } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button } from "@/components/ui";
import { ReleaseDialog, releaseChip, useDeliverables } from "@/components/Release";

interface Item { kind: "model" | "drawing" | "dfm" | "notice"; label: string; ok?: boolean; stale?: boolean; missing?: boolean; where?: string }
interface Plan { ready: boolean; revision: number | null; items: Item[] }

const WHERE: Record<string, string> = { drawings: "Drawing Studio", manufacturing: "Manufacturing Advisor" };

/** Shop handoff pack plus the release gate: issue a frozen letter revision, or download the current draft pack. */
export default function HandoffCard({ projectId, version }: { projectId: string; version?: number }) {
  const q = useQuery({ queryKey: ["handoff", projectId, version], queryFn: () => api.get<Plan>(`/api/projects/${projectId}/handoff`) });
  const d = useDeliverables(projectId);
  const [rel, setRel] = useState(false);
  const plan = q.data;
  if (!plan) return null;
  const chip = releaseChip(d.data);
  const r = d.data?.release;
  const model = plan.items.filter(i => i.kind === "model");
  const rest = plan.items.filter(i => i.kind !== "model");
  const row = (i: Item, label: React.ReactNode) => (
    <li key={i.kind + i.label} className="flex items-start gap-2">
      {i.missing ? <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted/60" /> : i.stale ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
        : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />}
      <span className={cx("min-w-0 flex-1", i.missing && "text-muted")}>{label}
        {i.stale && <span className="block text-[11px] text-warning">From an older build, left out. Regenerate it first.</span>}
        {i.missing && i.where && <span className="block text-[11px]">Not made yet · <Link to={`/app/modules/${i.where}?project=${projectId}`} className="link">open {WHERE[i.where] ?? i.where}</Link></span>}
      </span>
    </li>);
  return (
    <div className="rounded-lg border border-primary/30 bg-primary-soft/40 p-3" data-card="handoff">
      <div className="flex items-center gap-2 text-sm font-semibold"><PackageCheck className="h-4 w-4 text-primary" />Release and shop handoff
        {chip && <span className={cx("ml-auto rounded-full border px-2 py-0.5 text-[10.5px] font-semibold",
          chip.tone === "success" ? "border-success/25 bg-success/10 text-success" : chip.tone === "warning" ? "border-warning/25 bg-warning/10 text-warning" : "border-border bg-panel text-muted")}
          title={chip.tip}>{chip.text}</span>}</div>
      <p className="mt-0.5 text-[11.5px] text-muted">
        {r ? <>Rev {r.rev} was issued {r.date}{r.by ? ` by ${r.by}` : ""}{r.current ? "." : "; the model has changed since."} </> : null}
        Issuing freezes the model, drawing and reports as one hashed pack the shop can verify.</p>
      <ul className="mt-2 space-y-1.5 text-[12.5px]">
        {model.length > 0 && row({ kind: "model", label: "", ok: true }, <>Model: {model.map(m => m.label.split(" ")[0]).join(" · ")}</>)}
        {rest.map(i => row(i, i.label))}
      </ul>
      <div className="mt-3 flex gap-2">
        <Button className="flex-1" size="sm" icon={<Stamp className="h-3.5 w-3.5" />} disabled={!plan.ready} onClick={() => setRel(true)} data-action="open-release">
          {r?.current ? `Rev ${r.rev} issued` : `Issue Rev ${d.data?.next_rev ?? "A"}…`}</Button>
        {r && <a className="inline-flex items-center gap-1 rounded border border-border bg-panel px-2.5 text-[12px] hover:bg-panel2" href={`/api/projects/${projectId}/releases/${r.rev}/pack.zip`}
          title={`Download the frozen Rev ${r.rev} pack`}><Download className="h-3.5 w-3.5" />Rev {r.rev}</a>}
      </div>
      <button className="mt-1.5 w-full text-center text-[11.5px] text-muted hover:text-primary disabled:opacity-50" disabled={!plan.ready}
        onClick={() => { location.href = `/api/projects/${projectId}/handoff.zip`; }}>{plan.ready ? "Download the current draft pack (unissued)" : "Model not verified"}</button>
      <ReleaseDialog projectId={projectId} open={rel} onOpenChange={setRel} />
    </div>
  );
}
