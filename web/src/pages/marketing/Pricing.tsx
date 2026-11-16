import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, Coins, Minus } from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog } from "@/lib/types";
import { money, num } from "@/lib/format";
import { SALES } from "./Landing";
import { PageLoader, StatusBadge } from "@/components/ui";
import { PlanCards } from "@/components/PlanCards";

export default function Pricing() {
  useTitle("Pricing");
  const nav = useNavigate();
  const { me } = useSession();
  const signedIn = !!me?.user;
  const q = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog") });
  if (!q.data) return <PageLoader />;
  const { plans, addons, topups, modules, typical_run: run } = q.data;
  const trial = q.data.trial_tokens ?? 1000;
  const paid = plans.filter(p => p.code !== "trial");
  return (
    <main className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <div className="mx-auto max-w-2xl text-center">
        <div className="label">Pricing</div>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight">Pay for the engineering you use.</h1>
        <p className="mt-3 text-muted">Every plan starts with a free 14-day trial: {num(trial)} tokens (about 3 new parts) and every module on your own parts. Add modules when you need them, top up tokens any time.</p>
      </div>

      <div className="mt-12">
        <PlanCards plans={paid} onChoose={(p) => p.contact_sales ? (location.href = SALES) : nav(signedIn ? "/app/billing" : `/signup?plan=${p.code}`)}
          ctaLabel={(p) => p.contact_sales ? "Contact sales" : signedIn ? `Switch to ${p.name}` : "Start free trial"} />
      </div>

      <section className="mt-20">
        <h2 className="text-xl font-semibold">Compare plans</h2>
        <div className="mt-5 overflow-x-auto rounded-lg border border-border bg-panel">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-panel2 text-left text-[12px] text-muted">
              <tr><th className="px-4 py-3 font-medium">Module</th>{plans.map(p => <th key={p.code} className="px-4 py-3 text-center font-medium">{p.name}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-border">
              {modules.map(m => (
                <tr key={m.code}>
                  <td className="px-4 py-3"><span className="mr-2">{m.name}</span><StatusBadge status={m.status} /></td>
                  {plans.map(p => <td key={p.code} className="px-4 py-3 text-center">
                    {p.modules.includes(m.code) ? <Check className="mx-auto h-4 w-4 text-success" />
                      : addons.some(a => a.modules.includes(m.code)) && !p.contact_sales ? <span className="text-xs text-muted">Add-on</span>
                      : <Minus className="mx-auto h-4 w-4 text-muted/60" />}
                  </td>)}
                </tr>
              ))}
              <tr><td className="px-4 py-3 font-medium">Tokens included</td>{plans.map(p => <td key={p.code} className="px-4 py-3 text-center tabular-nums">{p.contact_sales ? "Custom" : p.tokens.toLocaleString() + (p.interval ? " / mo" : "")}</td>)}</tr>
              <tr><td className="px-4 py-3 font-medium">Seats</td>{plans.map(p => <td key={p.code} className="px-4 py-3 text-center">{p.contact_sales ? "Unlimited" : p.seats}</td>)}</tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-20 grid gap-10 lg:grid-cols-[1.6fr_1fr]">
        <div>
          <h2 className="text-xl font-semibold">Add-on modules</h2>
          <p className="mt-1 text-sm text-muted">Unlock individual modules on any plan. Each one opens straight on the part you designed.</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {addons.map(a => {
              const m = modules.find(x => x.code === a.modules[0]);
              return (
                <div key={a.code} className="card flex items-start justify-between gap-3 p-4">
                  <div><div className="flex items-center gap-2 font-medium">{a.name}{m && <StatusBadge status={m.status} />}</div>
                    <div className="mt-1 text-xs text-muted">{a.tagline}</div></div>
                  <div className="whitespace-nowrap text-sm font-semibold">{money(a.price_cents, a.interval)}</div>
                </div>
              );
            })}
          </div>
        </div>
        <div>
          <h2 className="text-xl font-semibold">Token packs</h2>
          <p className="mt-1 text-sm text-muted">One-off top-ups that never expire while your account is active.</p>
          <div className="mt-5 space-y-3">
            {topups.map(t => (
              <div key={t.code} className="card flex items-center gap-3 p-4">
                <Coins className="h-5 w-5 text-accent" />
                <div className="flex-1"><div className="font-medium">{t.name}</div>{t.tagline && <div className="text-xs text-success">{t.tagline}</div>}</div>
                <div className="font-semibold">{money(t.price_cents)}</div>
              </div>
            ))}
          </div>
          {run && <div className="mt-5 rounded-lg border border-border bg-panel p-4 text-xs leading-relaxed text-muted">
            <div className="mb-1 font-medium text-text">What a run costs</div>
            A new part from a written brief typically uses <b className="text-text">{run.new.low}–{run.new.high} tokens</b> (measured; most about {run.new.typical}).
            A change to an existing part usually uses {run.change.low}–{run.change.high}. Parameter edits, manual features, Toolbox parts and restores are free.
            Every run shows a live meter, stops at the budget you set and is never charged beyond it.
          </div>}
        </div>
      </section>
    </main>
  );
}
