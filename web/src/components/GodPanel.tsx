import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Database, Map as MapIcon, Sparkles, Trash2, UserRound, X, Zap } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button, Toggle } from "./ui";
import { cx } from "@/lib/format";

interface GodState {
  flags: { enabled: boolean; bypass_paywall: boolean; bypass_tokens: boolean; skip_verification: boolean; skip_onboarding: boolean };
  scenarios: { code: string; label: string }[];
  impersonating: boolean;
}

const FLAGS: { key: keyof GodState["flags"]; label: string; hint: string }[] = [
  { key: "bypass_paywall", label: "Bypass paywalls", hint: "Unlock every module; ignore plan & trial expiry" },
  { key: "bypass_tokens", label: "Bypass token limits", hint: "Agent runs are free and never blocked" },
  { key: "skip_verification", label: "Skip email verification", hint: "Unverified accounts reach the app" },
  { key: "skip_onboarding", label: "Skip onboarding", hint: "Go straight to the dashboard" },
];

const JOURNEY: { label: string; to: string }[] = [
  { label: "Landing page", to: "/" }, { label: "Pricing", to: "/pricing" }, { label: "Sign up", to: "/signup" },
  { label: "Verify email", to: "/verify-email" }, { label: "Onboarding", to: "/onboarding" },
  { label: "Dashboard + tour", to: "/app?tour=1" }, { label: "New project", to: "/app/projects?new=1" },
  { label: "All modules", to: "/app/modules" }, { label: "Drawing Studio", to: "/app/modules/drawings" },
  { label: "Billing & tokens", to: "/app/billing" }, { label: "Team", to: "/app/team" },
  { label: "Admin console", to: "/app/admin" },
];

export default function GodPanel() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { me, refresh } = useSession();
  const q = useQuery({ queryKey: ["god"], queryFn: () => api.get<GodState>("/api/god"), enabled: open });
  const enabled = !!me?.god?.enabled;

  const act = async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try { await fn(); await qc.invalidateQueries(); await refresh(); if (ok) toast.success(ok); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
    finally { setBusy(null); }
  };
  const setFlag = (k: string, v: boolean) => act(k, () => api.patch("/api/god", { [k]: v }));

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button aria-label="God mode"
          className={cx("inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition",
            enabled ? "bg-gradient-to-r from-accent to-[#E0563B] text-white shadow-sm" : "border border-border bg-panel text-text hover:border-accent")}>
          <Zap className={cx("h-3.5 w-3.5", enabled ? "fill-white" : "text-accent")} /> God{enabled ? " · on" : ""}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <Dialog.Content className="fixed bottom-0 right-0 top-0 z-50 flex w-[400px] max-w-full flex-col border-l border-border bg-panel shadow-pop animate-fade-in">
          <div className="flex items-center gap-3 border-b border-border bg-gradient-to-r from-accent/15 to-transparent px-5 py-4">
            <Zap className="h-5 w-5 text-accent" />
            <div className="flex-1">
              <Dialog.Title className="font-semibold">God mode</Dialog.Title>
              <Dialog.Description className="text-xs text-muted">Founder & demo controls. Disabled automatically in production.</Dialog.Description>
            </div>
            <Dialog.Close className="rounded p-1 text-muted hover:bg-text/5"><X className="h-4 w-4" /></Dialog.Close>
          </div>
          <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
            <div className="flex items-center justify-between rounded-lg border border-border bg-panel2 p-3">
              <div><div className="text-sm font-semibold">God mode active</div><div className="text-xs text-muted">Master switch for the bypasses below</div></div>
              <Toggle checked={enabled} onChange={(v) => setFlag("enabled", v)} label="God mode" />
            </div>
            <section className={cx(!enabled && "pointer-events-none opacity-50")}>
              <div className="label mb-2">Bypasses</div>
              <div className="space-y-2.5">
                {FLAGS.map(f => (
                  <div key={f.key} className="flex items-center justify-between gap-4">
                    <div><div className="text-[13px] font-medium">{f.label}</div><div className="text-xs text-muted">{f.hint}</div></div>
                    <Toggle checked={!!q.data?.flags[f.key]} onChange={(v) => setFlag(f.key, v)} label={f.label} />
                  </div>
                ))}
              </div>
            </section>
            <section>
              <div className="label mb-2 flex items-center gap-1.5"><MapIcon className="h-3.5 w-3.5" /> Jump to journey step</div>
              <div className="grid grid-cols-2 gap-1.5">
                {JOURNEY.map(j => (
                  <button key={j.to} onClick={() => { setOpen(false); nav(j.to); }}
                    className="rounded border border-border px-2.5 py-1.5 text-left text-[12.5px] hover:border-primary hover:bg-primary-soft">{j.label}</button>
                ))}
              </div>
            </section>
            <section>
              <div className="label mb-2 flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" /> Account scenarios</div>
              <p className="mb-2 text-xs text-muted">Puts <b>your</b> account/workspace into a state, so each screen can be demoed without walking the whole flow.</p>
              <div className="space-y-1">
                {(q.data?.scenarios ?? []).map(s => (
                  <button key={s.code} disabled={!!busy}
                    onClick={() => act(s.code, () => api.post("/api/god/scenario", { scenario: s.code }), "Scenario applied")}
                    className="flex w-full items-center justify-between rounded border border-border px-3 py-2 text-left text-[12.5px] hover:border-primary hover:bg-primary-soft disabled:opacity-50">
                    <span>{s.label}</span>{busy === s.code && <span className="text-xs text-muted">…</span>}
                  </button>
                ))}
              </div>
            </section>
            <section>
              <div className="label mb-2 flex items-center gap-1.5"><Database className="h-3.5 w-3.5" /> Demo data</div>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" loading={busy === "seed"} icon={<Database className="h-4 w-4" />}
                  onClick={() => act("seed", () => api.post("/api/god/seed-demo"), "Demo projects & teammates created")}>Seed demo</Button>
                <Button size="sm" variant="secondary" loading={busy === "reset"} icon={<Trash2 className="h-4 w-4" />}
                  onClick={() => act("reset", () => api.post("/api/god/reset-demo"), "Demo data removed")}>Reset demo</Button>
              </div>
              <p className="mt-2 text-xs text-muted">Demo projects are real builds of original parts, run through the same checks.</p>
            </section>
            <section>
              <div className="label mb-2 flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5" /> Impersonation</div>
              <Button size="sm" variant="secondary" onClick={() => { setOpen(false); nav("/app/admin/users"); }}>Choose a user to view as…</Button>
            </section>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
