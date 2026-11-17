import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, RefreshCw, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { BASE, type Full, type RoundTripRow } from "./types";

const ICON: Record<RoundTripRow["status"], JSX.Element> = {
  match: <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />,
  count: <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" />,
  missing: <XCircle className="h-3.5 w-3.5 shrink-0 text-danger" />,
  skipped: <CircleDashed className="h-3.5 w-3.5 shrink-0 text-muted" />,
};

/** Model vs drawing (AMI-I1): the built model's own Drawing Studio sheet, searched for every confirmed value. */
export default function RoundTripCard({ f, uid }: { f: Full; uid: string }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const auto = useRef(false);
  const rt = f.roundtrip;
  const built = !!f.project?.built;

  const run = async (quiet = false) => {
    setBusy(true);
    try { qc.setQueryData(["i2c-upload", uid], await api.post<Full>(`${BASE}/uploads/${uid}/roundtrip`)); }
    catch (e) { if (!quiet) toast.error(e instanceof ApiError ? e.message : "The check could not run"); }
    finally { setBusy(false); }
  };
  useEffect(() => {  // first visit after the model is built: run the check once, without asking
    if (!auto.current && built && !rt && f.can_edit) { auto.current = true; void run(true); }
  }, [built, rt, f.can_edit]);

  const problems = rt ? rt.rows.filter(r => r.status === "missing" || r.status === "count").length : 0;
  return (
    <div className="border-b border-border px-4 py-3.5" data-testid="roundtrip">
      <div className={cx("rounded-lg border p-3", !rt ? "border-border bg-panel2" : rt.ok ? "border-success/30 bg-success/[.06]" : "border-warning/40 bg-warning/[.06]")}>
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold">Model vs this drawing</span>
          {rt && rt.checked > 0 && (
            <span className={cx("rounded-full px-2 py-px text-[11px] font-semibold tabular-nums", rt.ok ? "bg-success/15 text-success" : "bg-warning/15 text-warning")} data-testid="roundtrip-score">
              {rt.matched}/{rt.checked} found</span>
          )}
          {rt?.stale && <span className="rounded-full bg-text/[.06] px-2 py-px text-[11px] text-muted">model changed since</span>}
          {f.can_edit && built && (
            <button type="button" disabled={busy} onClick={() => void run()} className="ml-auto inline-flex items-center gap-1 text-[12px] text-primary hover:underline disabled:opacity-60">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{rt ? "Check again" : "Check now"}</button>
          )}
        </div>
        {!built ? (
          <p className="mt-1 text-[12.5px] text-muted">Runs once the design agent has a verified build of <b className="text-text">{f.project?.name}</b>: the model is drawn and every confirmed value is looked for on its sheet.</p>
        ) : !rt ? (
          <p className="mt-1 flex items-center gap-1.5 text-[12.5px] text-muted">{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Drawing the model and looking for each confirmed value…</p>
        ) : (
          <>
            <p className="mt-1 text-[12.5px] text-text/80">
              {rt.checked === 0 ? "None of the confirmed values is a length or diameter the sheet measures."
                : rt.ok ? `Every checked value is on the model's own drawing.`
                : `${problems} value${problems === 1 ? "" : "s"} to look at in the model.`}
              {rt.skipped > 0 && <span className="text-muted"> {rt.skipped} not measured automatically.</span>}
            </p>
            <details className="group mt-1.5" open={!rt.ok}>
              <summary className="cursor-pointer list-none text-[12px] text-muted hover:text-text">
                <span className="group-open:hidden">Show the {rt.rows.length} values</span><span className="hidden group-open:inline">Values</span>
              </summary>
              <ul className="mt-1 divide-y divide-border overflow-hidden rounded-md border border-border bg-panel">
                {rt.rows.map(r => (
                  <li key={r.id} className="flex items-start gap-2 px-2 py-1.5 text-[12.5px]" data-rt={r.status}>
                    <span className="mt-0.5">{ICON[r.status]}</span>
                    <span className="w-[92px] shrink-0 font-mono font-semibold">{r.label}</span>
                    <span className="min-w-0 flex-1 text-muted">{r.status === "match" ? <>on the sheet as <span className="font-mono text-text">{r.found}</span>{r.describes ? ` · ${r.describes}` : ""}</> : r.note}</span>
                  </li>
                ))}
              </ul>
            </details>
            <p className="mt-2 text-[11.5px] leading-snug text-muted">Measured on the Drawing Studio sheet of the current build. It shows the model carries these values; it is not an inspection and says nothing about tolerances.</p>
          </>
        )}
      </div>
    </div>
  );
}
