import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Circle, Coins, FolderKanban, Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Catalog, Project } from "@/lib/types";
import { money, num } from "@/lib/format";
import { Button, Card, EmptyState, Progress, StatusBadge } from "@/components/ui";
import { Icon } from "@/components/icons";
import ProjectCard from "@/components/ProjectCard";
import NewProjectDialog, { createProject, useTemplates } from "@/components/NewProjectDialog";

const GOAL_MODULE: Record<string, string> = { drawings: "drawings", dfm: "manufacturing", legacy: "image2cad", print: "print", assemblies: "assembly" };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Dashboard() {
  const { me } = useSession();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [newOpen, setNewOpen] = useState(false);
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects") });
  const checklist = useQuery({ queryKey: ["checklist"], queryFn: () => api.get<{ items: { key: string; title: string; done: boolean; link: string }[]; done: number; total: number }>("/api/checklist") });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const tpl = useTemplates();
  const org = me?.org;
  const goals = ((me?.user?.onboarding?.goals as string[]) ?? []).map(g => GOAL_MODULE[g]).filter(Boolean) as string[];
  const suggested = (catalog.data?.modules ?? []).filter(m => goals.includes(m.code)).slice(0, 3);
  const intended = (() => { try { return sessionStorage.getItem("fw_intended_plan"); } catch { return null; } })();
  const intendedPlan = catalog.data?.plans.find(p => p.code === intended);

  const quick = async (code: string, name: string) => {
    try {
      const p = await createProject(name, code);
      await qc.invalidateQueries({ queryKey: ["projects"] });
      nav(`/app/projects/${p.id}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create project"); }
  };

  const items = projects.data?.items ?? [];
  const cl = checklist.data;
  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight">{greeting()}, {me?.user?.name.split(" ")[0]}</h1>
          <p className="mt-1 text-sm text-muted">{org?.name} · {org?.plan_name}{org?.on_trial && !org.expired ? ` · ${org.days_left} days left in trial` : ""}</p>
        </div>
        <Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New project</Button>
      </div>

      {intendedPlan && org?.plan_code === "trial" && (
        <div className="mb-6 flex flex-wrap items-center gap-4 rounded-lg border border-primary/30 bg-primary-soft px-4 py-3">
          <Sparkles className="h-5 w-5 text-primary" />
          <div className="flex-1 text-sm">You picked <b>{intendedPlan.name}</b> on our pricing page. Try everything on the trial first — upgrade whenever you're ready.</div>
          <Button size="sm" variant="secondary" onClick={() => nav("/app/billing")}>See {intendedPlan.name} · {money(intendedPlan.price_cents, intendedPlan.interval)}</Button>
          <button className="text-xs text-muted hover:text-text" onClick={() => { try { sessionStorage.removeItem("fw_intended_plan"); } catch { /* ignore */ } qc.invalidateQueries({ queryKey: ["me"] }); }}>Dismiss</button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-8">
          <section data-tour="quickstart">
            <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">Start from a template</h2>
              <button className="text-sm text-primary hover:underline" onClick={() => setNewOpen(true)}>All options</button></div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(tpl.data?.items ?? []).map(t => (
                <button key={t.code} onClick={() => quick(t.code, t.name)}
                  className="card group flex items-start gap-3 p-4 text-left transition hover:border-primary/50 hover:shadow-pop">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><Icon name={t.icon} className="h-[18px] w-[18px]" /></span>
                  <span className="min-w-0"><span className="flex items-center gap-1 text-sm font-medium">{t.name}<ArrowRight className="h-3.5 w-3.5 opacity-0 transition group-hover:opacity-100" /></span>
                    <span className="mt-0.5 line-clamp-2 text-xs text-muted">{t.prompt}</span></span>
                </button>
              ))}
            </div>
          </section>

          <section>
            <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">Recent projects</h2>
              {items.length > 0 && <Link to="/app/projects" className="text-sm text-primary hover:underline">View all</Link>}</div>
            {items.length === 0 ? (
              <EmptyState icon={<FolderKanban className="h-6 w-6" />} title="No projects yet"
                body="Create your first project from a template above, or describe any part from scratch. Your first verified part takes a couple of minutes."
                action={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>Create your first project</Button>} />
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{items.slice(0, 6).map(p => <ProjectCard key={p.id} p={p} />)}</div>
            )}
          </section>
        </div>

        <aside className="space-y-6">
          {cl && (
            <Card className="p-5" data-tour="checklist">
              <div className="flex items-center justify-between"><h2 className="font-semibold">Getting started</h2><span className="text-xs text-muted">{cl.done}/{cl.total}</span></div>
              <Progress className="mt-3" value={cl.done} max={cl.total} tone={cl.done === cl.total ? "success" : "primary"} />
              <ul className="mt-4 space-y-1">
                {cl.items.map(i => (
                  <li key={i.key}>
                    <button disabled={i.done} onClick={() => {
                      if (i.key === "project") setNewOpen(true);
                      else if (i.link.startsWith("?")) nav("/app" + i.link);
                      else nav(i.link);
                    }} className="flex w-full items-center gap-2.5 rounded px-2 py-1.5 text-left text-[13px] hover:bg-panel2 disabled:cursor-default disabled:hover:bg-transparent">
                      {i.done ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" /> : <Circle className="h-4 w-4 shrink-0 text-muted" />}
                      <span className={i.done ? "text-muted line-through" : ""}>{i.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {org && (
            <Card className="p-5">
              <div className="flex items-center justify-between"><h2 className="font-semibold">Usage</h2><Link to="/app/billing" className="text-xs text-primary hover:underline">Billing</Link></div>
              <div className="mt-4 flex items-end gap-2"><Coins className="mb-1 h-5 w-5 text-accent" /><span className="text-3xl font-semibold tabular-nums">{num(org.token_balance)}</span><span className="mb-1 text-sm text-muted">tokens</span></div>
              <p className="mt-1 text-xs text-muted">{org.on_trial ? "Trial allowance · upgrade for a monthly allowance" : `${num(org.plan_tokens)} included each month on ${org.plan_name}`}</p>
              <div className="mt-4 flex gap-2">
                <Button size="sm" variant="secondary" className="flex-1" onClick={() => nav("/app/billing#tokens")}>Top up</Button>
                {org.on_trial && <Button size="sm" className="flex-1" onClick={() => nav("/app/billing")}>Upgrade</Button>}
              </div>
            </Card>
          )}

          {suggested.length > 0 && (
            <Card className="p-5">
              <h2 className="font-semibold">Recommended for your goals</h2>
              <div className="mt-3 space-y-2">
                {suggested.map(m => (
                  <Link key={m.code} to={`/app/modules/${m.code}`} className="flex items-center gap-3 rounded-lg border border-border p-3 hover:border-primary/50">
                    <Icon name={m.icon} className="h-5 w-5 text-primary" />
                    <div className="min-w-0 flex-1"><div className="text-sm font-medium">{m.name}</div><div className="truncate text-xs text-muted">{m.summary}</div></div>
                    <StatusBadge status={m.status} />
                  </Link>
                ))}
              </div>
            </Card>
          )}
        </aside>
      </div>
      <NewProjectDialog open={newOpen} onOpenChange={setNewOpen} />
    </div>
  );
}
