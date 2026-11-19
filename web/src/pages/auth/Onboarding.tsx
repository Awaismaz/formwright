import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog } from "@/lib/types";
import { Input } from "@/components/ui";
import { Button3D, Card3D, KeyButton as Button, SiteLogo, SiteScope, ThemeSwitch } from "@/components/landing/site";
import { cx, num } from "@/lib/format";

const ROLES = ["Design / mechanical engineer", "Engineering manager", "Consultancy owner / principal", "Machinist / shop owner",
  "Product developer / founder", "Student / educator", "Other"];

function Choice({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={cx("flex min-h-[48px] items-center justify-between gap-3 border px-3.5 py-2.5 text-left text-[15px] transition-colors",
        selected ? "border-ink bg-hi/30 text-ink shadow-[inset_0_-3px_0_rgb(var(--s-ink))]" : "border-rule2 bg-slab text-ink hover:border-ink")}>
      <span>{children}</span>
      <span className={cx("flex h-5 w-5 shrink-0 items-center justify-center border", selected ? "border-ink bg-ink text-sheet" : "border-rule2")}>
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
    <SiteScope className="s-grid flex min-h-full flex-col">
      <header className="flex h-16 items-center justify-between border-b border-ink/80 bg-sheet px-4 sm:px-6"><SiteLogo size={24} /><ThemeSwitch /></header>
      <main className="flex flex-1 items-start justify-center px-4 py-10 sm:py-16">
        <div className="w-full max-w-2xl animate-fade-in"><Card3D screws inner="p-6 sm:p-9">
          <span className="s-anno text-bp">Setup · one screen</span>
          <h1 className="s-h2 mt-3 text-[28px] text-ink sm:text-[34px]">Welcome{firstName ? `, ${firstName}` : ""}. A few seconds, then your first part.</h1>
          <p className="mt-1.5 text-muted">All optional: they set your units and tune the examples you see. Change them any time in Settings.</p>

          <div className="mt-8 text-[13px] font-medium">What best describes your role?</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">{ROLES.map(r => <Choice key={r} selected={role === r} onClick={() => setRole(role === r ? "" : r)}>{r}</Choice>)}</div>

          <div className="mt-6 flex flex-wrap items-end gap-6">
            <div><div className="mb-2 text-[13px] font-medium">Units</div>
              <div role="group" aria-label="Units" className="inline-flex gap-1.5">{(["mm", "in"] as const).map(u =>
                <Button3D key={u} size="sm" finish="steel" pressed={units === u} onClick={() => setUnits(u)}>{u === "mm" ? "Millimetres" : "Inches"}</Button3D>)}</div>
            </div>
            <label className="min-w-[220px] flex-1"><div className="mb-2 text-[13px] font-medium">Workspace name</div>
              <Input value={workspace} onChange={e => setWorkspace(e.target.value)} maxLength={120} /></label>
          </div>

          <div className="mt-6 border-l-2 border-bp bg-sheet2 p-4 text-[15px] text-ink2">
            Your <b className="text-text">14-day free trial</b> starts now: <b className="text-text">{num(trial)} tokens</b>, enough for dozens of simple parts, and every module on your own parts. No card needed.
          </div>
          <div className="mt-8 flex items-center justify-end gap-2">
            <Button variant="ghost" loading={busy === "skip"} disabled={!!busy} onClick={() => finish(true)}>Skip</Button>
            <Button size="lg" loading={busy === "go"} disabled={!!busy} icon={<ArrowRight className="h-4 w-4" />} onClick={() => finish(false)}>Start designing</Button>
          </div>
        </Card3D></div>
      </main>
    </SiteScope>
  );
}
