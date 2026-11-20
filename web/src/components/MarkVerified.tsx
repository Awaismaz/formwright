import { useState } from "react";
import { ShieldCheck, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button, Modal } from "@/components/ui";

/** ASM-OW: the engineer may mark a built part as verified although a check is open. It is recorded on that build
 * (who, when, reason, the open checks) and revoked by the next rebuild; labels then say "Verified by <name>" with the
 * open checks, never "passed". */
export interface OpenCheck { id: string; name: string }

export function verificationLabel(state: string, open: OpenCheck[], by?: string | null): string {
  const ids = open.map(c => c.id).join(", ") || "a check";
  if (state === "accepted") return `Verified by ${by ?? "an engineer"}; open: ${ids}`;
  if (state === "unverified") return `Unverified: ${ids}`;
  if (state === "verified") return "Verified";
  return "No build";
}

export function MarkVerified({ projectId, open, accepted, onDone, compact }: {
  projectId: string; open: OpenCheck[]; accepted?: boolean; onDone?: () => void; compact?: boolean;
}) {
  const [dlg, setDlg] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try { await fn(); toast.success(ok); setDlg(false); onDone?.(); }
    catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  };
  if (accepted) return (
    <Button size="sm" variant="ghost" icon={<Undo2 className="h-3.5 w-3.5" />} loading={busy} data-copilot="withdraw-verified"
      onClick={() => run(() => api.del(`/api/projects/${projectId}/verify-override`), "Withdrawn: the part is unverified again")}>
      {compact ? "Withdraw" : "Withdraw verification"}</Button>);
  return (<>
    <Button size="sm" variant="secondary" icon={<ShieldCheck className="h-3.5 w-3.5" />} data-copilot="mark-verified"
      onClick={e => { e.stopPropagation(); setDlg(true); }}>{compact ? "Mark verified" : "Mark as verified"}</Button>
    <Modal open={dlg} onOpenChange={setDlg} title="Mark as verified?"
      description="Every module will treat this build as verified, labelled with your name and the checks still open. The next rebuild needs a new decision."
      footer={<><Button variant="ghost" onClick={() => setDlg(false)}>Cancel</Button>
        <Button loading={busy} data-copilot="confirm-mark-verified"
          onClick={() => run(() => api.post(`/api/projects/${projectId}/verify-override`, { reason }), "Marked as verified by you")}>Mark as verified</Button></>}>
      <div className="space-y-3 text-[13px]">
        <div><div className="label mb-1">Open checks</div>
          <ul className="list-disc pl-5 text-muted">{open.length ? open.map(c => <li key={c.id}>{c.id} {c.name}</li>) : <li>None listed</li>}</ul></div>
        <label className="block"><span className="label mb-1 block">Reason (optional)</span>
          <textarea className="input h-auto min-h-[60px] w-full py-1.5" value={reason} maxLength={500} onChange={e => setReason(e.target.value)}
            placeholder="e.g. the spline fit is checked in the assembly" /></label>
        <p className="text-[11.5px] text-muted">The checks stay open and are shown as open. This is an engineering decision, not a pass.</p>
      </div>
    </Modal>
  </>);
}
