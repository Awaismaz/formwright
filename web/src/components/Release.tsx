import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Info, Stamp } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, Modal, Spinner } from "./ui";

/** One downstream output's state on the current build (the single staleness rule, aicad.deliverables). */
export interface ModuleState {
  state: "current" | "stale" | "missing"; label: string; made_from_rev?: string | null; current_rev?: string | null;
  critical?: number; model_changed?: number; signed?: number; outdated?: number;
}
export interface ReleaseInfo { rev: string; date: string | null; by: string | null; note: string | null; model_rev: string | null; current: boolean }
export interface Deliverables {
  verified: boolean; build: { build_id: string | null; model_rev: string | null }; release: ReleaseInfo | null;
  next_rev: string; changed_since_release: boolean;
  modules: Record<"drawings" | "manufacturing" | "engineering" | "print", ModuleState>;
}
interface GateItem { kind: string; text: string; leavable?: string }
interface Gate {
  ready: boolean; next_rev: string; blocking: GateItem[]; include: GateItem[]; notes: string[]; suggested_note: string;
  release: ReleaseInfo | null; can_issue: boolean;
  releases: { rev: string; date: string; by: string; note: string; model_rev: string | null; pack_sha256: string; left_out?: string[] }[];
}

export const MODULE_LINK: Record<string, { name: string; path: string }> = {
  drawings: { name: "Drawing Studio", path: "drawings" },
  manufacturing: { name: "Manufacturing Advisor", path: "manufacturing" },
  engineering: { name: "Engineering Advisor", path: "engineering" },
  print: { name: "3D Print Prep", path: "print" },
};

/** Status of every downstream output of a part, and its release state. */
export function useDeliverables(projectId: string | null | undefined) {
  return useQuery({
    queryKey: ["deliverables", projectId], enabled: !!projectId, refetchOnWindowFocus: true, staleTime: 5_000,
    queryFn: () => api.get<Deliverables>(`/api/projects/${projectId}/deliverables`),
  });
}

/** Call after a module changes one of its outputs, so headers, the Make tab and the release gate agree. */
export function refreshDeliverables(qc: QueryClient, projectId: string) {
  for (const k of ["deliverables", "release", "handoff"]) void qc.invalidateQueries({ queryKey: [k, projectId] });
}

/** Release state chip text and tone, the same wherever it appears. */
export function releaseChip(d: Deliverables | undefined): { text: string; tone: "neutral" | "success" | "warning"; tip: string } | null {
  if (!d) return null;
  const r = d.release;
  if (!r) return { text: "Not issued", tone: "neutral", tip: `Nothing has been issued yet. Issuing freezes the model, drawing and reports as Rev ${d.next_rev}.` };
  if (r.current) return { text: `Rev ${r.rev} issued`, tone: "success", tip: `Issued ${r.date ?? ""}${r.by ? ` by ${r.by}` : ""}. The model has not changed since.` };
  return { text: `Draft since Rev ${r.rev}`, tone: "warning", tip: `The model changed after Rev ${r.rev} was issued (${r.date ?? ""}). The shop still holds Rev ${r.rev}; issue Rev ${d.next_rev} when the change is ready.` };
}

function localDay(): { local_date: string; tz: string } {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return { local_date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`, tz: Intl.DateTimeFormat().resolvedOptions().timeZone };
}

/** The release gate: what blocks the next revision, what it will contain, and the issued revisions. */
export function ReleaseDialog({ projectId, open, onOpenChange }: { projectId: string; open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const [leave, setLeave] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const q = useQuery({ queryKey: ["release", projectId, leave.join(",")], enabled: open,
    queryFn: () => api.get<Gate>(`/api/projects/${projectId}/release`) });
  const g = q.data;
  useEffect(() => { if (!open) { setNote(null); setLeave([]); } }, [open]);
  const current = (g?.blocking ?? []).find(b => b.kind === "release");  // this exact model is already issued
  const blocking = (g?.blocking ?? []).filter(b => b.kind !== "release" && !(b.leavable && leave.includes(b.leavable)));
  const left = (g?.blocking ?? []).filter(b => b.leavable && leave.includes(b.leavable));
  const issue = async () => {
    if (!g) return;
    setBusy(true);
    try {
      const r = await api.post<{ release: { rev: string } }>(`/api/projects/${projectId}/releases`, { note: note ?? g.suggested_note, leave_out: leave, ...localDay() });
      toast.success(`Rev ${r.release.rev} issued. The pack is frozen; later changes show as a draft.`);
      refreshDeliverables(qc, projectId);
      for (const k of ["drw", "drw-svg", "drw-projects"]) void qc.invalidateQueries({ queryKey: [k] });
      void q.refetch();
      setNote(null); setLeave([]); onOpenChange(false);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "The revision could not be issued"); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title={g ? `Issue Rev ${g.next_rev}` : "Issue a revision"}
      description="Freezes this exact model with its drawing, manufacturability report, signed calculations and print exports in one hashed pack. Later changes show as a draft until you issue the next revision."
      footer={g && <>
        <Button variant="secondary" onClick={() => onOpenChange(false)}>Close</Button>
        {g.can_issue && <Button icon={<Stamp className="h-4 w-4" />} loading={busy} disabled={blocking.length > 0 || !!current} onClick={() => void issue()} data-action="issue-release">Issue Rev {g.next_rev}</Button>}
      </>}>
      {!g ? <div className="flex justify-center py-8"><Spinner /></div> : (
        <div className="space-y-4 text-[13px]">
          {current && g.release && <div className="flex items-start gap-2 rounded border border-success/30 bg-success/5 px-3 py-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            <span>Rev {g.release.rev} ({g.release.date}) is this exact model. Change the design to issue Rev {g.next_rev}; until then there is nothing new to issue.</span></div>}
          {blocking.length > 0 && (
            <div>
              <div className="label mb-1.5">Before you can issue</div>
              <ul className="space-y-1.5">{blocking.map(b => (
                <li key={b.kind + b.text} className="flex items-start gap-2 rounded border border-warning/30 bg-warning/5 px-2.5 py-1.5">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                  <span className="flex-1">{b.text}{MODULE_LINK[b.kind] && <> <Link className="link whitespace-nowrap" to={`/app/modules/${MODULE_LINK[b.kind]!.path}?project=${projectId}`} onClick={() => onOpenChange(false)}>Open {MODULE_LINK[b.kind]!.name}</Link></>}</span>
                  {b.leavable && <button className="whitespace-nowrap text-[12px] text-muted hover:text-primary" onClick={() => setLeave(l => [...l, b.leavable!])}>Leave it out</button>}
                </li>))}</ul>
            </div>
          )}
          <div>
            <div className="label mb-1.5">Rev {g.next_rev} will contain</div>
            <ul className="space-y-1">{g.include.map(i => <li key={i.kind + i.text} className="flex items-start gap-2"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />{i.text}</li>)}
              {left.map(b => <li key={"l" + b.kind} className="flex items-start gap-2 text-muted"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />Left out: {b.kind === "manufacturing" ? "manufacturability report (older analysis)" : "calculation sets signed on an earlier model"}
                <button className="text-[12px] hover:text-primary" onClick={() => setLeave(l => l.filter(x => x !== b.leavable))}>undo</button></li>)}
              {g.notes.map(n => <li key={n} className="flex items-start gap-2 text-muted"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{n}</li>)}
            </ul>
          </div>
          {g.can_issue && <label className="block">
            <span className="label">Change description</span>
            <input className="input mt-1 w-full" maxLength={300} value={note ?? g.suggested_note} onChange={e => setNote(e.target.value)} data-field="release-note" />
            <span className="mt-1 block text-[11.5px] text-muted">Printed in the drawing's revision table and the pack's README.</span>
          </label>}
          <p className="rounded border border-border bg-panel2 px-3 py-2 text-[12px] text-muted">An issued revision is a record of what was sent, not an approval. Checks prove geometric consistency only; the drawing stays marked NOT APPROVED FOR MANUFACTURE until a qualified engineer approves it.</p>
          {g.releases.length > 0 && (
            <div>
              <div className="label mb-1.5">Issued revisions</div>
              <ul className="divide-y divide-border rounded border border-border">{g.releases.map((r, i) => (
                <li key={r.rev} className="flex items-center gap-3 px-3 py-2">
                  <span className={cx("w-9 text-center font-semibold tabular-nums", i === 0 ? "text-text" : "text-muted")}>{r.rev}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate">{r.note}</span>
                    <span className="block text-[11.5px] text-muted">{r.date} · {r.by}{r.model_rev ? ` · model rev ${r.model_rev}` : ""} · SHA-256 {r.pack_sha256.slice(0, 12)}…</span></span>
                  <a className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline" href={`/api/projects/${projectId}/releases/${r.rev}/pack.zip`}><Download className="h-3.5 w-3.5" />Pack</a>
                </li>))}</ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
