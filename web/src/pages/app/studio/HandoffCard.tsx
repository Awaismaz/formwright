import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, PackageCheck } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button } from "@/components/ui";

interface Item { kind: "model" | "drawing" | "dfm" | "notice"; label: string; ok?: boolean; stale?: boolean; missing?: boolean; where?: string }
interface Plan { ready: boolean; revision: number | null; items: Item[] }

const WHERE: Record<string, string> = { drawings: "Drawing Studio", manufacturing: "Manufacturing Advisor" };

/** One-click release package for the shop: model files, drawing, DFM report, change notice, hashed manifest. */
export default function HandoffCard({ projectId, version }: { projectId: string; version?: number }) {
  const q = useQuery({ queryKey: ["handoff", projectId, version], queryFn: () => api.get<Plan>(`/api/projects/${projectId}/handoff`) });
  const plan = q.data;
  if (!plan) return null;
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
    <div className="rounded-lg border border-primary/30 bg-primary-soft/40 p-3">
      <div className="flex items-center gap-2 text-sm font-semibold"><PackageCheck className="h-4 w-4 text-primary" />Shop handoff pack</div>
      <p className="mt-0.5 text-[11.5px] text-muted">Everything for rev {plan.revision ?? "—"} in one zip, with a SHA-256 manifest so the shop can verify every file.</p>
      <ul className="mt-2 space-y-1.5 text-[12.5px]">
        {model.length > 0 && row({ kind: "model", label: "", ok: true }, <>Model: {model.map(m => m.label.split(" ")[0]).join(" · ")}</>)}
        {rest.map(i => row(i, i.label))}
      </ul>
      <Button className="mt-3 w-full" size="sm" disabled={!plan.ready} onClick={() => { location.href = `/api/projects/${projectId}/handoff.zip`; }}>
        {plan.ready ? "Download handoff pack" : "Model not verified"}</Button>
    </div>
  );
}
