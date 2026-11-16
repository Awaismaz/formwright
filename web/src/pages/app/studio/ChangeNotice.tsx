import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, ClipboardCopy, FileWarning, Hand, Library, Printer, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Modal, Spinner } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";

interface Notice {
  revision: number; base: number | null; first: boolean; part?: string; material?: string; created_at: string; base_created_at?: string;
  why?: string | null; kind?: string | null; by?: string | null; ok: boolean; views: boolean; base_views?: boolean;
  latest: boolean; superseded_by: number | null; project: { id: string; name: string };
  changes: { lines: string[]; checks?: { to_ok: boolean; failing: string[] } };
}

const KIND: Record<string, { label: string; icon: React.ReactNode }> = {
  agent: { label: "Design agent", icon: <Bot className="h-3.5 w-3.5" /> },
  params: { label: "Parameter edit", icon: <SlidersHorizontal className="h-3.5 w-3.5" /> },
  manual: { label: "Manual edit", icon: <Hand className="h-3.5 w-3.5" /> },
  library: { label: "Library", icon: <Library className="h-3.5 w-3.5" /> },
};

const when = (iso: string) => new Date(iso + "Z").toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function asText(n: Notice): string {
  return [`CHANGE NOTICE: ${n.project.name}${n.part ? ` (${n.part})` : ""}`,
    `Revision ${n.revision}${n.base ? `, supersedes revision ${n.base}` : ""} · ${when(n.created_at)}${n.by ? ` · ${n.by}` : ""}`,
    n.latest ? "Status: CURRENT" : `Status: SUPERSEDED by revision ${n.superseded_by}`, "",
    `Why: ${n.why ?? "not recorded"}`, "", "What changed:", ...n.changes.lines.map(l => `  - ${l}`), "",
    n.ok ? "Geometry checks: passed (geometric consistency only; not a manufacturing approval)" : "Geometry checks: FAILING"].join("\n");
}

/** One-page change notice for the shop: why the revision exists, what changed, before/after views. */
export default function ChangeNotice({ projectId, n, onClose }: { projectId: string; n: number | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["notice", projectId, n], enabled: n !== null, retry: false,
    queryFn: () => api.get<Notice>(`/api/projects/${projectId}/revisions/${n}/notice`) });
  const d = q.data;
  const img = (rev: number) => `/api/projects/${projectId}/revisions/${rev}/files/views.png`;
  const k = KIND[d?.kind ?? ""] ?? null;
  return (
    <Modal wide open={n !== null} onOpenChange={o => !o && onClose()} title={`Change notice · Rev ${n ?? ""}`}
      description="What changed and why, ready for the shop floor."
      footer={d && <>
        <Button variant="ghost" className="mr-auto" icon={<ClipboardCopy className="h-4 w-4" />} onClick={async () => {
          try { await navigator.clipboard.writeText(asText(d)); toast.success("Notice copied: paste it into an email or chat"); }
          catch { toast.error("Copy failed"); } }}>Copy text</Button>
        <Button variant="secondary" onClick={onClose}>Close</Button>
        <Button icon={<Printer className="h-4 w-4" />} onClick={() => window.print()}>Print / PDF</Button></>}>
      {q.isLoading ? <div className="flex justify-center py-10"><Spinner /></div>
        : q.error ? <p className="py-6 text-sm text-muted">{q.error instanceof ApiError ? q.error.message : "Couldn't load the notice"}</p>
        : d && (
        <div className="fw-print space-y-4 text-[13px]">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-[16px] font-semibold">{d.project.name}{d.part && d.part !== d.project.name && <span className="ml-2 text-[13px] font-normal text-muted">{d.part}</span>}</div>
              <div className="mt-0.5 text-[12px] text-muted">
                Revision <b className="text-text">{d.revision}</b>{d.base && <> · supersedes revision {d.base}</>} · {when(d.created_at)}{d.by && <> · {d.by}</>}{d.material && <> · {d.material}</>}
              </div>
            </div>
            <span className={cx("shrink-0 -rotate-3 rounded border-2 px-2.5 py-1 text-[12px] font-bold uppercase tracking-wider",
              d.latest ? "border-success/70 text-success" : "border-danger/70 text-danger")}>
              {d.latest ? "Current" : `Superseded by rev ${d.superseded_by}`}</span>
          </div>

          <div className="rounded-lg border-l-4 border-primary bg-primary-soft/60 px-3 py-2.5">
            <div className="mb-0.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary">Why{k && <span className="flex items-center gap-1 font-medium normal-case tracking-normal text-muted">· {k.icon}{k.label}</span>}</div>
            <div className="whitespace-pre-wrap">{d.why ?? <span className="text-muted">Not recorded (revision made before change notices existed).</span>}</div>
          </div>

          {!d.first && d.base !== null && (
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
              {[d.base, d.revision].map((r, i) => (
                <div key={r} className={cx(i === 1 && "col-start-3")}>
                  <div className="fw-crop relative aspect-[4/3] overflow-hidden rounded-lg border border-border bg-gradient-to-b from-[#eef2f8] to-[#dfe6f0] dark:from-[#232a35] dark:to-[#1b2029]">
                    {(i === 0 ? d.base_views : d.views) ? <IsoThumb src={img(r)} /> : <div className="flex h-full items-center justify-center text-[12px] text-muted">No view</div>}
                  </div>
                  <div className="mt-1 text-center text-[11.5px] text-muted">{i === 0 ? `Before · rev ${r}` : `After · rev ${r}`}</div>
                </div>)).reduce<React.ReactNode[]>((a, el, i) => (i ? [...a, <ArrowRight key="arr" className="h-5 w-5 text-muted" />, el] : [el]), [])}
            </div>)}

          <div>
            <div className="label mb-1.5">What changed</div>
            <ul className="divide-y divide-border rounded-lg border border-border">
              {d.changes.lines.map(l => <li key={l} className="px-3 py-2 tabular-nums">{l}</li>)}
            </ul>
          </div>

          <div className="flex items-center gap-2 text-[12px] text-muted">
            {d.ok ? <Badge tone="success">Geometry checks passed</Badge> : <Badge tone="danger"><FileWarning className="h-3 w-3" />Checks failing</Badge>}
            Checks prove geometric consistency only. This notice is not a manufacturing approval.
          </div>
          {d.created_at && <div className="hidden print:block pt-6 text-[12px]">Reviewed by: ____________________ Date: ____________</div>}
        </div>)}
    </Modal>
  );
}
