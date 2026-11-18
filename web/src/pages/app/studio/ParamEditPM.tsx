import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { AgentEdit, Impact, Project } from "@/lib/types";
import { Button, Field, Input, Tip } from "@/components/ui";
import ImpactPanel from "./ImpactPanel";

/** DS-035: "Modify dimensions" PropertyManager for a parameter change the design agent proposed. Pre-filled, shows the
 *  old value, previews the impact on assemblies (ASM-018) and applies through the normal parameter edit (no AI). */
export default function ParamEditPM({ project, rows, summary, usedIn = 0, onDone, onCancel }: {
  project: Project; rows: NonNullable<AgentEdit["params"]>; summary: string; usedIn?: number; onDone: () => void; onCancel: () => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(rows).map(([k, r]) => [k, String(r.to)])));
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [impact, setImpact] = useState<{ data: Impact; key: string } | null>(null);
  const values = Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)]));
  const ready = Object.values(values).every(v => Number.isFinite(v)) && Object.entries(values).some(([k, v]) => v !== rows[k]!.from);

  const submit = async (force = false) => {
    if (!ready || busy) return;
    const key = JSON.stringify(values);
    if (usedIn > 0 && !(force && impact?.key === key)) {
      setChecking(true);
      try {
        const r = await api.post<Impact>(`/api/m/assembly/impact/${project.id}`, { kind: "params", values });
        if ((r.issues ?? 0) > 0) { setImpact({ data: r, key }); return; }
      } catch (err) {
        if (err instanceof ApiError && err.status === 422) { toast.error(err.message); return; }
      } finally { setChecking(false); }
    }
    setImpact(null); setBusy(true);
    try {
      const r = await api.post<{ revision?: number; build_s?: number }>(`/api/projects/${project.id}/params`, { values });
      toast.success(`Parameters updated · rev ${r.revision ?? "?"}${r.build_s ? ` · ${r.build_s.toFixed(1)} s` : ""}`);
      onDone();
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Rebuild failed"); }
    finally { setBusy(false); }
  };
  const submitRef = useRef(submit); submitRef.current = submit;
  useEffect(() => {
    const h = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement | null;
      if (ev.key === "Escape" && !document.querySelector("[role=menu],[role=dialog]")) { ev.preventDefault(); onCancel(); }
      else if (ev.key === "Enter" && !(t && /^(TEXTAREA|SELECT|BUTTON)$/.test(t.tagName))) { ev.preventDefault(); void submitRef.current(); }
    };
    addEventListener("keydown", h);
    return () => removeEventListener("keydown", h);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex h-full flex-col" data-testid="param-pm">
      <div className="flex items-center gap-2 border-b border-border bg-gradient-to-r from-primary-soft to-transparent px-3 py-2.5">
        <span className="flex-1 text-sm font-semibold">Modify dimensions</span>
        <Tip content="OK (Enter)" side="bottom"><button onClick={() => void submit()} disabled={!ready || busy || checking} className="rounded bg-success p-1 text-white disabled:opacity-40" aria-label="OK"><Check className="h-4 w-4" /></button></Tip>
        <Tip content="Cancel (Esc)" side="bottom"><button onClick={onCancel} className="rounded bg-danger p-1 text-white" aria-label="Cancel"><X className="h-4 w-4" /></button></Tip>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-3 text-[13px]">
        <div className="flex gap-2 rounded-lg border border-accent/40 bg-accent/5 p-2.5 text-[12px]" data-agent-edit>
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
          <span><b>Suggested by the design agent:</b> {summary}. Check the values, then OK. Nothing changes until you do.</span></div>
        {impact && <ImpactPanel impact={impact.data} busy={busy} onApply={() => void submit(true)} onBack={() => setImpact(null)} />}
        {Object.entries(rows).map(([k, r]) => (
          <Field key={k} label={`${r.label} (now ${r.from}${r.unit ? ` ${r.unit}` : ""})`}>
            <div className="flex items-center gap-1.5"><Input value={vals[k] ?? ""} onChange={ev => { setVals({ ...vals, [k]: ev.target.value }); setImpact(null); }} inputMode="decimal" className="h-8" aria-label={r.label} />
              <span className="w-7 text-xs text-muted">{r.unit}</span></div>
          </Field>))}
        <p className="text-[11.5px] text-muted">Rebuilds without AI or tokens and is kept only if the checks pass.</p>
      </div>
      <div className="flex gap-2 border-t border-border p-3">
        <Button className="flex-1" onClick={() => void submit()} loading={busy} disabled={!ready || !!impact || checking}>
          {checking ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />Checking assemblies</> : <>Apply <span className="ml-1 text-[10.5px] opacity-70">Enter</span></>}</Button>
        <Button variant="secondary" onClick={onCancel}>Cancel <span className="ml-1 text-[10.5px] opacity-70">Esc</span></Button>
      </div>
    </div>
  );
}
