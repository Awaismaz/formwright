import { Suspense, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bell, Check, CheckCircle2, Lock, Sparkles, Unlock } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { Catalog } from "@/lib/types";
import { money, PAGE } from "@/lib/format";
import NotFoundPanel from "@/components/NotFoundPanel";
import { Badge, Button, Card, PageHeader, PageLoader, StatusBadge } from "@/components/ui";
import { Icon } from "@/components/icons";
import ModuleSample from "@/components/ModuleSamples";
import { MODULE_APPS } from "./modules/registry";

function useCatalog() {
  return useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
}
function useWaitlist() {
  return useQuery({ queryKey: ["waitlist"], queryFn: () => api.get<{ modules: string[] }>("/api/waitlist") });
}

/** Where to go after a successful checkout (e.g. the module opened on the part the user came from). */
export const AFTER_CHECKOUT = "fw_after_checkout";
export function afterCheckout(): { to: string; label: string } | null {
  try { const v = sessionStorage.getItem(AFTER_CHECKOUT); return v ? JSON.parse(v) : null; } catch { return null; }
}

export async function buy(code: string, nav: (to: string) => void, returnTo?: { to: string; label: string }) {
  try { if (returnTo) sessionStorage.setItem(AFTER_CHECKOUT, JSON.stringify(returnTo)); else sessionStorage.removeItem(AFTER_CHECKOUT); } catch { /* storage unavailable */ }
  const r = await api.post<{ provider: string; url: string }>("/api/billing/checkout", { product_code: code });
  if (r.provider === "stripe") location.href = r.url; else nav(r.url);
}

export default function Modules() {
  const { me } = useSession();
  const cat = useCatalog();
  const wl = useWaitlist();
  if (!cat.data) return <PageLoader />;
  const org = me?.org;
  const owned = new Set(org?.modules);
  return (
    <div className={PAGE}>
      <PageHeader title="Modules" subtitle={org?.on_trial && !org.expired
        ? "Every module opens straight on a part from your projects. Your trial includes all of them."
        : "Every module opens straight on a part from your projects. Unlocked modules show no lock."} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cat.data.modules.map(m => {
          const addon = cat.data.addons.find(a => a.modules.includes(m.code));
          const has = owned.has(m.code) || org?.god_unlock;
          return (
            <Link key={m.code} to={m.code === "design" ? "/app/projects" : `/app/modules/${m.code}`} className="card group flex flex-col p-5 transition hover:-translate-y-0.5 hover:shadow-pop">
              <div className="flex items-start justify-between">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary-soft text-primary"><Icon name={m.icon} className="h-5 w-5" /></div>
                <div className="flex items-center gap-1.5">
                  {wl.data?.modules.includes(m.code) && <Badge tone="primary"><Bell className="h-3 w-3" />On list</Badge>}
                  <StatusBadge status={m.status} />
                  {m.beta && <Badge tone="accent">Beta</Badge>}
                </div>
              </div>
              <h3 className="mt-4 text-[15px] font-semibold">{m.name}</h3>
              {m.tags?.filter(t => t !== "Beta").map(t => <span key={t} className="mt-1 text-[11.5px] font-medium text-muted">{t}</span>)}
              <p className="mt-1.5 flex-1 text-[13px] leading-relaxed text-muted">{m.summary}</p>
              <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-[12px]">
                {has ? <span className="inline-flex items-center gap-1 font-medium text-success"><Check className="h-3.5 w-3.5" />{org?.on_trial && !org.expired ? "In your trial" : "In your plan"}</span>
                  : <span className="inline-flex items-center gap-1 text-muted"><Lock className="h-3.5 w-3.5" />{addon ? `Add-on ${money(addon.price_cents, addon.interval)}` : "Not in plan"}</span>}
                <span className="font-medium text-primary group-hover:underline">{m.status === "live" ? "Open" : "Preview"} →</span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export function ModulePage() {
  const { code = "" } = useParams();
  const [params] = useSearchParams();
  const { me, refresh } = useSession();
  const nav = useNavigate();
  const qc = useQueryClient();
  const cat = useCatalog();
  const wl = useWaitlist();
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { track("module_viewed", { module: code }); qc.invalidateQueries({ queryKey: ["checklist"] }); }, [code]); // eslint-disable-line react-hooks/exhaustive-deps
  if (code === "design") return <Navigate to="/app/projects" replace />;
  if (!cat.data) return <PageLoader />;
  const m = cat.data.modules.find(x => x.code === code);
  if (!m) return <NotFoundPanel title="Module not found" body="There is no module at this address." action={<Link to="/app/modules"><Button>All modules</Button></Link>} />;
  const org = me?.org;
  const owned = org?.modules.includes(code) || org?.god_unlock;
  const addon = cat.data.addons.find(a => a.modules.includes(code));
  const plansWith = cat.data.plans.filter(p => p.modules.includes(code) && !p.contact_sales);
  const onList = wl.data?.modules.includes(code);
  const fromProject = params.get("project");
  const LiveApp = m.status === "live" ? MODULE_APPS[code] : undefined;
  if (LiveApp && owned) return <Suspense fallback={<PageLoader />}><LiveApp code={code} projectId={fromProject} /></Suspense>;

  const join = async () => {
    setBusy("wl");
    try { await api.post("/api/feedback", { kind: "waitlist", topic: code, message: `Early access: ${m.name}` });
      await qc.invalidateQueries({ queryKey: ["waitlist"] }); toast.success("You're on the early-access list. We'll email you when it opens."); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(null); }
  };
  const unlock = async () => {
    if (!addon) return;
    setBusy("buy");
    try { track("upgrade_clicked", { module: code }); await buy(addon.code, nav, { to: `/app/modules/${code}${fromProject ? `?project=${fromProject}` : ""}`, label: `Open ${m.name}` }); await refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Checkout failed"); } finally { setBusy(null); }
  };

  return (
    <div className={PAGE}>
      {fromProject ? <Link to={`/app/projects/${fromProject}`} className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Back to project</Link>
        : <Link to="/app/modules" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />All modules</Link>}
      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary-soft text-primary"><Icon name={m.icon} className="h-6 w-6" /></div>
            <div><h1 className="text-[24px] font-semibold tracking-tight">{m.name}</h1><div className="mt-0.5 flex items-center gap-2"><StatusBadge status={m.status} />{owned && <Badge tone="success">Included in your plan</Badge>}</div></div>
          </div>
          <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted">{m.summary}</p>
          {m.status === "preview" && (
            <div className="mt-5 flex items-start gap-3 rounded-lg border border-accent/30 bg-accent/5 p-4 text-sm">
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
              <div><b>This module is in preview.</b> The screens below illustrate the planned workflow with sample data. It isn't generating results from your projects yet. Join early access and we'll invite you as soon as it does.</div>
            </div>
          )}
          {m.status === "live" && (
            <div className="mt-5 flex items-start gap-3 rounded-lg border border-success/30 bg-success/5 p-4 text-sm">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              <div><b>This module is live.</b> {org?.on_trial && org.expired ? "Your trial has ended. " : ""}Unlock it for {org?.name ?? "your workspace"} to run it on your own parts. It opens straight on a project from the Design Studio's <b>Make</b> tab. The screens below are illustrative samples.</div>
            </div>
          )}
          <div className="mt-6"><ModuleSample code={code} /></div>
          <h2 className="mt-8 font-semibold">{m.status === "live" ? "What it does" : "What it will do"}</h2>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">{m.bullets.map(b => <li key={b} className="flex items-start gap-2 text-sm"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{b}</li>)}</ul>
        </div>
        <aside className="space-y-4">
          {m.status !== "live" && <Card className="p-5">
            <div className="label">Early access</div>
            <p className="mt-2 text-sm text-muted">Be first to use {m.name} on your own projects and help shape it.</p>
            <Button className="mt-4 w-full" variant={onList ? "secondary" : "primary"} icon={onList ? <Check className="h-4 w-4" /> : <Bell className="h-4 w-4" />} disabled={onList} loading={busy === "wl"} onClick={join}>
              {onList ? "You're on the list" : "Join early access"}</Button>
          </Card>}
          <Card className="p-5">
            <div className="label">Availability</div>
            {owned ? <p className="mt-2 flex items-center gap-2 text-sm"><Unlock className="h-4 w-4 text-success" /> Unlocked for {org?.name}. It activates for you automatically when the module goes live.</p> : <>
              {addon && <div className="mt-3 flex items-baseline justify-between"><span className="text-sm">Add-on</span><span className="text-xl font-semibold">{money(addon.price_cents, addon.interval)}</span></div>}
              {plansWith.length > 0 && <p className="mt-2 text-xs text-muted">Also included in: {plansWith.map(p => p.name).join(", ")}.</p>}
              {canManage(org?.role) ? <>
                {addon && <Button className="mt-4 w-full" variant={m.status === "live" ? "primary" : "secondary"} icon={<Lock className="h-4 w-4" />} loading={busy === "buy"} onClick={unlock}>{m.status === "live" ? `Unlock ${m.name}` : "Unlock add-on"}</Button>}
                <Button className="mt-2 w-full" variant="ghost" onClick={() => nav("/app/billing")}>Compare plans</Button>
                {m.status === "preview" && <p className="mt-2 text-[11px] text-muted">Unlocking now reserves the module for your workspace; it switches on for you automatically when it goes live.</p>}
              </> : <p className="mt-3 text-xs text-muted">Ask a workspace admin to unlock this module.</p>}
            </>}
          </Card>
        </aside>
      </div>
    </div>
  );
}
