import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog } from "@/lib/types";
import { Button, Input, Logo } from "@/components/ui";
import { cx, num } from "@/lib/format";

const ROLES = ["Design / mechanical engineer", "Engineering manager", "Consultancy owner / principal", "Machinist / shop owner",
  "Product developer / founder", "Student / educator", "Other"];

function Choice({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={cx("flex items-center justify-between gap-3 rounded-lg border px-3.5 py-2.5 text-left text-sm transition",
        selected ? "border-primary bg-primary-soft text-primary ring-1 ring-primary" : "border-border bg-panel hover:border-primary/50")}>
      <span>{children}</span>
      <span className={cx("flex h-5 w-5 shrink-0 items-center justify-center rounded-full border", selected ? "border-primary bg-primary text-white" : "border-border")}>
        {selected && <Check className="h-3 w-3" />}
      </span>
    </button>
  );
}

/** One screen: role and units (both optional), then straight to the first part. Everything else is asked in context. */
export default function Onboarding() {
  useTitle("Welcome");
  const { me, refresh } = useSession();
  const nav = useNavigate();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const existing = (me?.user?.onboarding ?? {}) as Record<string, unknown>;
  const [role, setRole] = useState<string>((existing.role as string) ?? "");
  const [units, setUnits] = useState<"mm" | "in">(me?.user?.preferences?.units ?? "mm");
  const firstName = me?.user?.name.split(" ")[0] ?? "";
  const [workspace, setWorkspace] = useState(me?.org?.name ?? (firstName ? `${firstName}'s workspace` : "My workspace"));
  const [busy, setBusy] = useState<"go" | "skip" | null>(null);

  if (me?.next_step === "verify_email") return <Navigate to="/verify-email" replace />;
  if (me?.next_step === "app" && me.user?.onboarding_completed) return <Navigate to="/app" replace />;

  const trial = catalog.data?.trial_tokens ?? 1000;
  const finish = async (skip: boolean) => {
    if (!workspace.trim()) { toast.error("Give your workspace a name"); return; }
    setBusy(skip ? "skip" : "go");
    try {
      await api.post("/api/onboarding", skip ? { workspace_name: workspace } : { role, units, workspace_name: workspace });
      if (skip) track("onboarding_skipped");
      await refresh();
      nav("/app", { replace: true });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); }
    finally { setBusy(null); }
  };

  return (
    <div className="flex min-h-full flex-col bg-bg">
      <header className="flex h-16 items-center border-b border-border bg-panel px-6"><Logo size={24} /></header>
      <main className="flex flex-1 items-start justify-center px-4 py-10 sm:py-16">
        <div className="w-full max-w-2xl animate-fade-in">
          <h1 className="text-[26px] font-semibold tracking-tight">Welcome{firstName ? `, ${firstName}` : ""}. A few seconds, then your first part.</h1>
          <p className="mt-1.5 text-muted">All optional: they set your units and tune the examples you see. Change them any time in Settings.</p>

          <div className="mt-8 text-[13px] font-medium">What best describes your role?</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">{ROLES.map(r => <Choice key={r} selected={role === r} onClick={() => setRole(role === r ? "" : r)}>{r}</Choice>)}</div>

          <div className="mt-6 flex flex-wrap items-end gap-6">
            <div><div className="mb-2 text-[13px] font-medium">Units</div>
              <div className="inline-flex rounded-lg border border-border p-1">{(["mm", "in"] as const).map(u =>
                <button key={u} type="button" onClick={() => setUnits(u)} aria-pressed={units === u} className={cx("rounded px-4 py-1.5 text-sm", units === u ? "bg-primary text-white" : "text-muted")}>{u === "mm" ? "Millimetres" : "Inches"}</button>)}</div>
            </div>
            <label className="min-w-[220px] flex-1"><div className="mb-2 text-[13px] font-medium">Workspace name</div>
              <Input value={workspace} onChange={e => setWorkspace(e.target.value)} maxLength={120} /></label>
          </div>

          <div className="mt-6 rounded-lg border border-border bg-panel2 p-4 text-sm text-muted">
            Your <b className="text-text">14-day free trial</b> starts now: <b className="text-text">{num(trial)} tokens</b>, about 3 new parts, and every module on your own parts. No card needed.
          </div>
          <div className="mt-8 flex items-center justify-end gap-2">
            <Button variant="ghost" loading={busy === "skip"} disabled={!!busy} onClick={() => finish(true)}>Skip</Button>
            <Button size="lg" loading={busy === "go"} disabled={!!busy} icon={<ArrowRight className="h-4 w-4" />} onClick={() => finish(false)}>Start designing</Button>
          </div>
        </div>
      </main>
    </div>
  );
}
