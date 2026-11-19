import { useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, HelpCircle, Ruler, XCircle } from "lucide-react";
import { cx } from "@/lib/format";
import { Badge, Button } from "@/components/ui";

/** PD-73: one look at an assembly's 4-view picture (advisory) plus the measured placement checks. */
export type VisualOverall = "looks_assembled" | "looks_wrong" | "unsure";
export interface VisualVerdict {
  overall: VisualOverall;
  relations: { id: string; text: string; status: "ok" | "wrong" | "unsure"; reason: string }[];
  problems: { kind: string; items: number[]; labels: string[]; text: string }[];
  summary: string; simulated?: boolean;
}
export interface QuickFinding { code: string; severity: "block" | "note"; text: string }
export interface VisualRecord {
  status: "running" | "done" | "failed"; at?: string; verdict?: VisualVerdict | null; line?: string; tokens?: number;
  render_s?: number; vision_s?: number; error?: string; quick?: QuickFinding[]; simulated?: boolean; name?: string;
  level?: string;
}

export const VERDICT_WORD: Record<VisualOverall, string> = {
  looks_assembled: "Looks assembled", looks_wrong: "Looks wrong", unsure: "Can't tell from the picture",
};
const TONE: Record<VisualOverall, "success" | "danger" | "warning"> = { looks_assembled: "success", looks_wrong: "danger", unsure: "warning" };

export function VerdictBadge({ v }: { v: VisualVerdict | null | undefined }) {
  if (!v) return null;
  return <Badge tone={TONE[v.overall]} data-verdict={v.overall}>{VERDICT_WORD[v.overall]}</Badge>;
}

/** The picture, the verdict per relation, the visible problems and the measured findings. */
export function VisualCheck({ rec, image, stale, onLook, looking, canLook, compact }: {
  rec: VisualRecord | null | undefined; image?: string | null; stale?: boolean; onLook?: () => void; looking?: boolean;
  canLook?: boolean; compact?: boolean;
}) {
  const [big, setBig] = useState(false);
  const v = rec?.verdict ?? null;
  const quick = (rec?.quick ?? []).filter(f => f.severity === "block" || !compact);
  return (
    <div className="text-[12px]" data-visual-check={rec?.status ?? "none"}>
      <div className="mb-1.5 flex items-center gap-2 font-semibold">
        <Eye className="h-4 w-4 text-primary" />Visual check<span className="font-normal text-muted">(advisory)</span>
        <span className="ml-auto flex items-center gap-1.5">
          {rec?.status === "running" && <Badge tone="neutral">Looking…</Badge>}
          <VerdictBadge v={v} />
          {stale && <Badge tone="neutral">Changed since</Badge>}
        </span>
      </div>
      {!rec && <p className="text-muted">Fitz draws the assembly from four sides and Claude looks at it against the intended relations, the way an engineer glances at an assembly before measuring it.</p>}
      {rec?.status === "failed" && <p className="text-warning">{rec.error ?? "The visual check couldn't run."}</p>}
      {image && rec?.status === "done" && (
        <button type="button" className="block w-full overflow-hidden rounded border border-border bg-panel2" onClick={() => setBig(b => !b)} aria-label="Enlarge the picture">
          <img src={image} alt="The assembly from four sides: iso, front, top and right" className={cx("w-full object-contain", big ? "max-h-none" : "max-h-[220px]")} data-visual-image />
        </button>)}
      {v && <>
        {v.summary && <p className="mt-1.5">{v.summary}</p>}
        <ul className="mt-1.5 space-y-1">
          {v.relations.map(r => (
            <li key={r.id} className="flex items-start gap-1.5" data-relation={r.status}>
              {r.status === "ok" ? <CheckCircle2 className="mt-px h-3.5 w-3.5 shrink-0 text-success" /> : r.status === "wrong"
                ? <XCircle className="mt-px h-3.5 w-3.5 shrink-0 text-danger" /> : <HelpCircle className="mt-px h-3.5 w-3.5 shrink-0 text-warning" />}
              <span><span className="font-medium">{r.text}</span>{r.reason && <span className="text-muted">: {r.reason}</span>}</span>
            </li>))}
        </ul>
        {v.problems.length > 0 && <ul className="mt-1.5 space-y-0.5 text-danger">
          {v.problems.map((p, k) => <li key={k} className="flex items-start gap-1.5"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />{p.text}</li>)}</ul>}
      </>}
      {quick.length > 0 && <div className="mt-2 rounded border border-border bg-panel2/60 p-2" data-quick-findings>
        <div className="mb-0.5 flex items-center gap-1 font-medium"><Ruler className="h-3.5 w-3.5" />Measured from the placements</div>
        <ul className="space-y-0.5">{quick.map((f, k) => <li key={k} className={f.severity === "block" ? "text-danger" : "text-muted"}>{f.text}</li>)}</ul>
      </div>}
      {rec?.status === "done" && <p className="mt-1.5 text-[10.5px] text-muted">
        {rec.simulated || v?.simulated ? "Simulated look (development): it follows the measured checks." : "A look at a picture, not a measurement: it never accepts geometry on its own; the measured checks and the clash check decide."}
        {rec.tokens ? ` · ${rec.tokens} token${rec.tokens === 1 ? "" : "s"}` : ""}</p>}
      {onLook && canLook !== false && <Button size="sm" variant="secondary" className="mt-2" loading={looking} disabled={looking || rec?.status === "running"}
        icon={<Eye className="h-3.5 w-3.5" />} onClick={onLook} data-visual-look>{rec ? "Look again" : "Look at it"}</Button>}
    </div>
  );
}
