import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Circle, Coins, Download, FolderKanban, Lock, Plus, Sparkles, X } from "lucide-react";
import { api, track } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Catalog, Project } from "@/lib/types";
import { ago, money, num, PAGE } from "@/lib/format";
import { Button, Card, EmptyState, Progress } from "@/components/ui";
import { Icon } from "@/components/icons";
import ProjectCard, { IsoThumb } from "@/components/ProjectCard";
import NewProjectDialog from "@/components/NewProjectDialog";
import StartBox from "@/components/StartBox";

/** What a verified part can become next: each opens the module straight on that part. */
const NEXT: { code: string; label: string; hint: string }[] = [
  { code: "drawings", label: "Make a drawing", hint: "Views, section, dimensions, title block" },
  { code: "manufacturing", label: "Check manufacturability", hint: "DFM findings and a relative cost" },
  { code: "print", label: "Prepare for 3D printing", hint: "Walls, overhangs, orientation" },
  { code: "mesh", label: "Render it", hint: "Product shots and a turntable" },
];

const KIND: Record<string, string> = { agent: "Design agent", params: "Parameters", manual: "Hand edit", library: "Library" };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function NextSteps({ p, owned }: { p: Project; owned: Set<string> }) {
  const nav = useNavigate();
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col sm:flex-row">
        <Link to={`/app/projects/${p.id}`} className="viewport-bg relative block aspect-[4/3] shrink-0 overflow-hidden border-b border-border sm:w-44 sm:border-b-0 sm:border-r">
          {p.thumbnail && <IsoThumb src={`${p.thumbnail}?v=${p.last_status?.build_id ?? 0}`} />}
        </Link>
        <div className="min-w-0 flex-1 p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="truncate font-semibold">Next for {p.name}</h2>
            <a href={`/api/projects/${p.id}/files/part.step`} className="inline-flex shrink-0 items-center gap-1 text-[12px] text-primary hover:underline"><Download className="h-3.5 w-3.5" />STEP</a>
          </div>
          <p className="text-[12px] text-muted">Verified {ago(p.updated_at)}. Each opens on this part.</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {NEXT.map(n => (
              <button key={n.code} onClick={() => { track("next_step_clicked", { module: n.code }); nav(`/app/modules/${n.code}?project=${p.id}`); }}
                className="group flex items-start gap-2.5 rounded-lg border border-border px-3 py-2 text-left transition hover:border-primary/50 hover:bg-primary-soft/40">
                <Icon name={n.code === "drawings" ? "ruler" : n.code === "manufacturing" ? "factory" : n.code === "print" ? "printer" : "shapes"} className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <span className="min-w-0 flex-1"><span className="flex items-center gap-1 text-[13px] font-medium">{n.label}{!owned.has(n.code) && <Lock className="h-3 w-3 text-muted" aria-label="Not in your plan" />}</span>
                  <span className="block truncate text-[11.5px] text-muted">{n.hint}</span></span>
                <ArrowRight className="mt-1 h-3.5 w-3.5 text-muted opacity-0 transition group-hover:opacity-100" />
              </button>))}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function Dashboard() {
  const { me } = useSession();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [newOpen, setNewOpen] = useState(false);
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects") });
  const checklist = useQuery({ queryKey: ["checklist"], queryFn: () => api.get<{ items: { key: string; title: string; done: boolean; link: string }[]; done: number; total: number; hidden: boolean }>("/api/checklist") });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const feed = useQuery({ queryKey: ["revisions-recent"], queryFn: () => api.get<{ items: { project: { id: string; name: string }; n: number; why: string | null; kind: string | null; by: string | null; created_at: string }[] }>("/api/revisions/recent"), staleTime: 30_000 });
  const org = me?.org;
  const owned = new Set(org?.god_unlock ? catalog.data?.modules.map(m => m.code) : org?.modules);
  const intended = (() => { try { return sessionStorage.getItem("fw_intended_plan"); } catch { return null; } })();
  const intendedPlan = catalog.data?.plans.find(p => p.code === intended);
  const unlimited = !!(me?.god?.enabled && me.god.bypass_tokens);
  const typical = catalog.data?.typical_run?.new.typical ?? 250;

  const items = projects.data?.items ?? [];
  const latestVerified = items.find(p => p.builds > 0 && p.last_status?.ok);
  const cl = checklist.data;
  const dismiss = async () => { await api.post("/api/checklist/dismiss"); qc.invalidateQueries({ queryKey: ["checklist"] }); };

  return (
    <div className={PAGE}>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[24px] font-semibold tracking-tight sm:text-[26px]">{greeting()}, {me?.user?.name.split(" ")[0]}</h1>
          <p className="mt-1 text-sm text-muted">{org?.name} · {org?.plan_name}{org?.on_trial && !org.expired ? ` · ${org.days_left} days left in trial` : ""}</p>
        </div>
        <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New part</Button>
      </div>

      {intendedPlan && org?.plan_code === "trial" && (
        <div className="mb-6 flex flex-wrap items-center gap-4 rounded-lg border border-primary/30 bg-primary-soft px-4 py-3">
          <Sparkles className="h-5 w-5 text-primary" />
          <div className="flex-1 text-sm">You picked <b>{intendedPlan.name}</b> on our pricing page. Try everything on the trial first; upgrade whenever you're ready.</div>
          <Button size="sm" variant="secondary" onClick={() => nav("/app/billing")}>See {intendedPlan.name} · {money(intendedPlan.price_cents, intendedPlan.interval)}</Button>
          <button className="text-xs text-muted hover:text-text" onClick={() => { try { sessionStorage.removeItem("fw_intended_plan"); } catch { /* ignore */ } qc.invalidateQueries({ queryKey: ["me"] }); }}>Dismiss</button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-8">
          <StartBox existing={items.map(p => p.name)} />

          {latestVerified && <NextSteps p={latestVerified} owned={owned} />}

          <section>
            <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">Recent parts</h2>
              {items.length > 0 && <Link to="/app/projects" className="text-sm text-primary hover:underline">View all</Link>}</div>
            {items.length === 0 ? (
              <EmptyState icon={<FolderKanban className="h-6 w-6" />} title="No parts yet"
                body="Describe your first part above. The design agent models it, checks the geometry and shows it live; a first part takes about two minutes." />
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{items.slice(0, 6).map(p => <ProjectCard key={p.id} p={p} units={me?.user?.preferences?.units} />)}</div>
            )}
          </section>
        </div>

        <aside className="min-w-0 space-y-6">
          {cl && !cl.hidden && (
            <Card className="p-5" data-tour="checklist">
              <div className="flex items-center justify-between"><h2 className="font-semibold">Getting started</h2>
                <div className="flex items-center gap-2"><span className="text-xs text-muted">{cl.done}/{cl.total}</span>
                  <button onClick={dismiss} className="rounded p-0.5 text-muted hover:bg-text/5 hover:text-text" aria-label="Hide the checklist"><X className="h-3.5 w-3.5" /></button></div></div>
              <Progress className="mt-3" value={cl.done} max={cl.total} />
              <ul className="mt-4 space-y-1">
                {cl.items.map(i => (
                  <li key={i.key}>
                    <button disabled={i.done} onClick={() => {
                      if (i.key === "build" && i.link === "/app") document.getElementById("start-brief")?.focus();
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

          {(feed.data?.items.length ?? 0) > 0 && (
            <Card className="p-5">
              <h2 className="font-semibold">Latest changes</h2>
              <ul className="mt-3 space-y-2.5">
                {feed.data!.items.map(r => (
                  <li key={`${r.project.id}-${r.n}`}>
                    <Link to={`/app/projects/${r.project.id}`} className="group block">
                      <div className="flex items-baseline gap-1.5 text-[13px]"><span className="truncate font-medium group-hover:text-primary">{r.project.name}</span>
                        <span className="shrink-0 text-[11px] text-muted">rev {r.n}</span></div>
                      <div className="line-clamp-2 text-[12px] text-muted" title={r.why ?? undefined}>{r.why ? r.why.split(/(?<=[.!?])\s/)[0] : r.n === 1 ? "First version" : "Rebuilt"}</div>
                      <div className="text-[11px] text-muted/80">{ago(r.created_at)}{r.by ? ` · ${r.by}` : ""}{r.kind && KIND[r.kind] ? ` · ${KIND[r.kind]}` : ""}</div>
                    </Link>
                  </li>))}
              </ul>
            </Card>
          )}

          {org && (
            <Card className="p-5">
              <div className="flex items-center justify-between"><h2 className="font-semibold">Tokens</h2><Link to="/app/billing#tokens" className="text-xs text-primary hover:underline">Billing</Link></div>
              <div className="mt-3 flex items-end gap-2"><Coins className="mb-1 h-5 w-5 text-accent" /><span className="text-3xl font-semibold tabular-nums">{unlimited ? "∞" : num(org.token_balance)}</span><span className="mb-1 text-sm text-muted">tokens</span></div>
              <p className="mt-1 text-xs text-muted">{unlimited ? "God mode: runs are not charged."
                : `About ${Math.max(0, Math.floor(org.token_balance / typical))} new part${Math.floor(org.token_balance / typical) === 1 ? "" : "s"} at a typical ${typical} tokens; changes and hand edits cost less or nothing.`}</p>
              <div className="mt-4 flex gap-2">
                <Button size="sm" variant="secondary" className="flex-1" onClick={() => nav("/app/billing#tokens")}>Top up</Button>
                {org.on_trial && <Button size="sm" className="flex-1" onClick={() => nav("/app/billing")}>Upgrade</Button>}
              </div>
            </Card>
          )}
        </aside>
      </div>
      <NewProjectDialog open={newOpen} onOpenChange={setNewOpen} />
    </div>
  );
}
