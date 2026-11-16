import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, Coins, CreditCard, ExternalLink, FlaskConical, Gauge, Lock, Receipt, RotateCcw, ShieldCheck, Users, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { Catalog, Org, Product } from "@/lib/types";
import { cx, date, money, num, PAGE } from "@/lib/format";
import { Badge, Button, Card, Input, Modal, PageHeader, PageLoader, Progress, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { PlanCards } from "@/components/PlanCards";
import { buy } from "./Modules";

interface Overview {
  org: Org; catalog: Catalog; addons: string[]; can_purchase: boolean;
  run_budget: { tokens: number; min: number; max: number }; account_credit_cents: number; extra_seats: number;
  ledger: { id: string; delta: number; balance_after: number; reason: string; detail: string; user: string | null; created_at: string }[];
  payments: { id: string; product_code: string; kind: string; amount_cents: number; status: string; provider: string; created_at: string; paid_at: string | null }[];
  usage_30d: { date: string; tokens: number }[];
}

interface SwitchPreview {
  from: { code: string; name: string; price_cents: number } | null;
  to: { code: string; name: string; price_cents: number; tokens: number };
  direction: "up" | "down"; unused_credit_cents: number; account_credit_cents: number; charge_cents: number;
  leftover_credit_cents: number; period_end: string; seats: { used: number; limit: number; over: number };
  cancels_addons: { module: string; name: string; price_cents: number }[]; loses_modules: string[];
}

const label = (s: string) => s.replace("_", " ").replace(/^./, c => c.toUpperCase());

/** The default stop-at budget for design-agent runs in this workspace. */
function RunBudget({ value, min, max, manage }: { value: number; min: number; max: number; manage: boolean }) {
  const qc = useQueryClient();
  const [v, setV] = useState(String(value));
  const [busy, setBusy] = useState(false);
  useEffect(() => setV(String(value)), [value]);
  const n = Number(v);
  const save = async () => {
    setBusy(true);
    try { await api.patch("/api/billing/run-budget", { tokens: n }); toast.success(`Runs now stop at ${num(n)} tokens`); qc.invalidateQueries({ queryKey: ["billing"] }); qc.invalidateQueries({ queryKey: ["estimate"] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  };
  return (
    <div className="mt-5 rounded-lg border border-border bg-panel2/60 p-3">
      <div className="flex items-center gap-2 text-[13px] font-medium"><Gauge className="h-4 w-4 text-primary" />Run budget</div>
      <p className="mt-0.5 text-xs text-muted">Each design-agent run stops cleanly at this many tokens and is never charged more. People can lower it for a single run.</p>
      <div className="mt-2 flex items-center gap-2">
        <input type="number" min={min} max={max} step={50} value={v} disabled={!manage} onChange={e => setV(e.target.value)}
          className="input h-8 w-28 tabular-nums" aria-label="Run budget in tokens" />
        <span className="text-xs text-muted">tokens per run</span>
        {manage && <Button size="sm" variant="secondary" className="ml-auto" loading={busy} disabled={!(n >= min && n <= max) || n === value} onClick={save}>Save</Button>}
      </div>
    </div>
  );
}

function UsageChart({ data }: { data: { date: string; tokens: number }[] }) {
  const max = Math.max(10, ...data.map(d => d.tokens));
  const total = data.reduce((a, d) => a + d.tokens, 0);
  return (
    <div>
      <div className="flex items-baseline justify-between"><span className="label">Usage · last 30 days</span><span className="text-sm font-medium tabular-nums">{num(total)} tokens</span></div>
      <div className="mt-3 flex h-24 items-end gap-[3px]" role="img" aria-label={`Token usage over 30 days, ${total} total`}>
        {data.map(d => (
          <div key={d.date} className="group relative flex-1">
            <div className={cx("w-full rounded-t-sm transition", d.tokens ? "bg-primary group-hover:bg-accent" : "bg-text/[.07]")} style={{ height: `${Math.max(3, (d.tokens / max) * 96)}px` }} />
            <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded bg-chrome px-1.5 py-0.5 text-[10px] text-white group-hover:block">{d.date.slice(5)} · {d.tokens}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Billing() {
  const { me, refresh } = useSession();
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [switching, setSwitching] = useState<{ plan: Product; preview: SwitchPreview } | null>(null);
  const q = useQuery({ queryKey: ["billing"], queryFn: () => api.get<Overview>("/api/billing") });

  useEffect(() => {
    const c = params.get("checkout");
    if (c === "success") { toast.success("Payment successful — your workspace is updated."); refresh(); }
    if (c === "canceled") toast("Checkout canceled. No charge was made.");
    if (c) { params.delete("checkout"); params.delete("payment"); setParams(params, { replace: true }); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (loc.hash === "#tokens") setTimeout(() => document.getElementById("tokens")?.scrollIntoView({ behavior: "smooth" }), 200); }, [loc.hash, q.data]);

  if (!q.data) return <PageLoader />;
  const { org, catalog, ledger, payments, usage_30d, addons } = q.data;
  const manage = canManage(me?.org?.role);
  const mode = catalog.stripe_mode;
  const planProduct = catalog.plans.find(p => p.code === org.plan_code);
  const seat = catalog.seats?.[0];
  const checkout = async (p: Product) => {
    if (p.contact_sales) { location.href = "mailto:sales@formwright.dev?subject=Formwright%20Enterprise"; return; }
    if (!manage) { toast.error("Only owners and admins can make purchases."); return; }
    setBusy(p.code);
    try {
      track("upgrade_clicked", { product: p.code });
      if (p.kind === "plan") { // always show what the switch costs (credit, seats, add-ons) before paying
        const preview = await api.post<SwitchPreview>("/api/billing/preview", { product_code: p.code });
        setSwitching({ plan: p, preview });
      } else await buy(p.code, nav);
    }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Checkout failed"); } finally { setBusy(null); }
  };
  const confirmSwitch = async () => {
    if (!switching) return;
    setBusy(switching.plan.code);
    try { await buy(switching.plan.code, nav); setSwitching(null); await refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Checkout failed"); } finally { setBusy(null); }
  };
  const portal = async () => {
    const r = await api.post<{ url: string | null; message?: string }>("/api/billing/portal");
    if (r.url) location.href = r.url; else toast(r.message ?? "Managed in-app");
  };

  return (
    <div className={PAGE}>
      <PageHeader title="Billing & tokens" subtitle={`Plan, token wallet, add-ons and invoices for ${org.name}.`}
        actions={mode !== "simulated" && manage && <Button variant="secondary" icon={<ExternalLink className="h-4 w-4" />} onClick={portal}>Manage in Stripe</Button>} />
      {mode !== "live" && (
        <div className="mb-6 flex items-center gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3 text-sm">
          <FlaskConical className="h-4 w-4 text-accent" />
          {mode === "simulated" ? <span><b>Simulated payments.</b> No payment provider is configured in this environment — checkouts run through a labelled test page and no money moves.</span>
            : <span><b>Stripe test mode.</b> Use card 4242 4242 4242 4242 with any future date and CVC.</span>}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_1.15fr]">
        <Card className="p-5">
          <div className="flex items-start justify-between">
            <div><div className="label">Current plan</div><div className="mt-1 text-2xl font-semibold">{planProduct?.name ?? org.plan_name}</div></div>
            <Badge tone={org.plan_status === "active" ? "success" : org.plan_status === "trialing" ? "primary" : "danger"}>{org.plan_status === "trialing" ? "Trial" : label(org.plan_status)}</Badge>
          </div>
          <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-muted">{org.on_trial ? "Trial ends" : "Renews"}</dt><dd className="font-medium">{org.on_trial ? date(org.trial_ends_at) : date(org.current_period_end)}</dd></div>
            <div><dt className="text-muted">Price</dt><dd className="font-medium">{planProduct ? (planProduct.price_cents ? money(planProduct.price_cents, planProduct.interval) : "Free") : "—"}</dd></div>
            <div><dt className="text-muted">Seats</dt><dd className={cx("font-medium", org.seats_used > org.seat_limit && "text-warning")}>{org.seats_used} / {org.seat_limit >= 1000 ? "∞" : org.seat_limit}{org.seats_used > org.seat_limit && " · over the plan"}</dd></div>
            <div><dt className="text-muted">Monthly tokens</dt><dd className="font-medium">{org.on_trial ? "—" : num(org.plan_tokens)}</dd></div>
          </dl>
          {org.on_trial && <div className="mt-4"><Progress value={14 - (org.days_left ?? 0)} max={14} tone={org.expired ? "danger" : "primary"} /><div className="mt-1 text-xs text-muted">{org.expired ? "Trial ended" : `${org.days_left} of 14 days left`}</div></div>}
          {q.data.account_credit_cents > 0 && <p className="mt-4 text-xs text-muted">Account credit: <b className="text-text">{money(q.data.account_credit_cents)}</b>, applied to your next plan charge.</p>}
          {org.plan_code === "team" && seat && <div className="mt-4 flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-[13px]">
            <Users className="h-4 w-4 text-primary" /><span className="flex-1">Extra seats: <b>{q.data.extra_seats}</b> · {money(seat.price_cents, seat.interval)} each</span>
            {manage && <Button size="sm" variant="secondary" loading={busy === seat.code} onClick={() => checkout(seat)}>Add a seat</Button>}
            {me?.org?.role === "owner" && q.data.extra_seats > 0 && org.seats_used < org.seat_limit &&
              <Button size="sm" variant="ghost" onClick={async () => { try { await api.del("/api/billing/seats"); toast.success("Seat removed"); await qc.invalidateQueries(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } }}>Remove one</Button>}
          </div>}
          {manage && org.plan_code !== "trial" && org.plan_status !== "canceled" && me?.org?.role === "owner" &&
            <button className="mt-5 text-xs text-muted hover:text-danger" onClick={() => setCancelOpen(true)}>Cancel subscription</button>}
        </Card>

        <Card className="p-5" id="tokens">
          <div className="flex items-start justify-between">
            <div><div className="label">Token wallet</div><div className="mt-1 flex items-center gap-2 text-3xl font-semibold tabular-nums"><Coins className="h-6 w-6 text-accent" />{num(org.token_balance)}</div></div>
          </div>
          <div className="mt-5"><UsageChart data={usage_30d} /></div>
          <div className="mt-5 grid grid-cols-3 gap-2">
            {catalog.topups.map(t => (
              <button key={t.code} disabled={!manage || busy !== null} onClick={() => checkout(t)}
                className={cx("rounded-lg border p-3 text-left transition hover:border-primary disabled:opacity-60", t.highlight ? "border-primary/50 bg-primary-soft/40" : "border-border")}>
                <div className="text-sm font-semibold">{t.name}</div><div className="text-xs text-muted">{money(t.price_cents)}</div>
                {t.tagline && <div className="mt-1 text-[10px] font-semibold text-success">{t.tagline}</div>}
              </button>
            ))}
          </div>
          {!manage && <p className="mt-3 text-xs text-muted">Ask an owner or admin to top up tokens.</p>}
          <RunBudget value={q.data.run_budget.tokens} min={q.data.run_budget.min} max={q.data.run_budget.max} manage={manage} />
        </Card>
      </div>

      <section className="mt-10">
        <h2 className="mb-4 text-lg font-semibold">Plans</h2>
        <PlanCards plans={catalog.plans.filter(p => p.code !== "trial")} current={org.plan_status === "active" || org.plan_status === "past_due" ? org.plan_code : null} busy={busy} onChoose={checkout}
          ctaLabel={p => p.contact_sales ? "Contact sales" : org.plan_code !== "trial" && org.plan_status === "active" && planProduct ? `${p.price_cents > planProduct.price_cents ? "Upgrade" : "Switch"} to ${p.name}` : `Choose ${p.name}`} />
      </section>

      <section className="mt-10">
        <h2 className="mb-1 text-lg font-semibold">Add-on modules</h2>
        <p className="mb-4 text-sm text-muted">In-app purchases that unlock individual modules on top of your plan.</p>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {catalog.addons.map(a => {
            const m = catalog.modules.find(x => x.code === a.modules[0]);
            const ownedVia = addons.includes(a.modules[0]!) ? "addon" : org.modules.includes(a.modules[0]!) ? "plan" : null;
            return (
              <div key={a.code} className="card flex flex-col p-4">
                <div className="flex items-center justify-between"><span className="font-medium">{a.name}</span>{m && <Badge tone={m.status === "live" ? "live" : "preview"}>{m.status === "live" ? "Live" : "Preview"}</Badge>}</div>
                <p className="mt-1 flex-1 text-xs text-muted">{a.tagline}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-sm font-semibold">{money(a.price_cents, a.interval)}</span>
                  {ownedVia ? <Badge tone="success"><CheckCircle2 className="h-3 w-3" />{ownedVia === "plan" ? "In plan" : "Owned"}</Badge>
                    : <Button size="sm" variant="secondary" icon={<Lock className="h-3.5 w-3.5" />} disabled={!manage} loading={busy === a.code} onClick={() => checkout(a)}>Unlock</Button>}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-10">
        <Tabs defaultValue="payments">
          <TabList><Tab value="payments"><Receipt className="h-4 w-4" />Payments</Tab><Tab value="ledger"><Coins className="h-4 w-4" />Token ledger</Tab></TabList>
          <TabPanel value="payments" className="pt-4">
            <div className="card overflow-x-auto">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-panel2 text-left text-xs text-muted"><tr><th className="px-4 py-2.5 font-medium">Date</th><th className="px-4 py-2.5 font-medium">Item</th><th className="px-4 py-2.5 font-medium">Amount</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 text-right font-medium">Receipt</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {payments.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-muted">No payments yet.</td></tr>}
                  {payments.map(p => {
                    const prod = [...catalog.plans, ...catalog.addons, ...catalog.topups, ...(catalog.seats ?? [])].find(x => x.code === p.product_code);
                    return <tr key={p.id}><td className="px-4 py-2.5 text-muted">{date(p.created_at)}</td><td className="px-4 py-2.5">{prod?.name ?? p.product_code}</td>
                      <td className="px-4 py-2.5 tabular-nums">{money(p.amount_cents)}</td>
                      <td className="px-4 py-2.5"><Badge tone={p.status === "paid" ? "success" : p.status === "failed" ? "danger" : "neutral"}>{label(p.status)}</Badge></td>
                      <td className="px-4 py-2.5 text-right">{p.status === "paid" ? <a href={`/api/billing/payments/${p.id}/receipt`} target="_blank" rel="noopener" className="link text-[13px]">View</a> : <span className="text-muted">—</span>}</td></tr>;
                  })}
                </tbody>
              </table>
            </div>
          </TabPanel>
          <TabPanel value="ledger" className="pt-4">
            <div className="card overflow-x-auto">
              <table className="w-full min-w-[600px] text-sm">
                <thead className="bg-panel2 text-left text-xs text-muted"><tr><th className="px-4 py-2.5 font-medium">Date</th><th className="px-4 py-2.5 font-medium">Description</th><th className="px-4 py-2.5 font-medium">By</th><th className="px-4 py-2.5 text-right font-medium">Change</th><th className="px-4 py-2.5 text-right font-medium">Balance</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {ledger.map(r => <tr key={r.id}><td className="px-4 py-2.5 text-muted">{date(r.created_at)}</td><td className="px-4 py-2.5"><Badge className="mr-2">{label(r.reason)}</Badge>{r.detail}</td><td className="px-4 py-2.5 text-muted">{r.user ?? "—"}</td>
                    <td className={cx("px-4 py-2.5 text-right tabular-nums font-medium", r.delta > 0 ? "text-success" : "text-text")}>{r.delta > 0 ? "+" : ""}{num(r.delta)}</td><td className="px-4 py-2.5 text-right tabular-nums text-muted">{num(r.balance_after)}</td></tr>)}
                </tbody>
              </table>
            </div>
          </TabPanel>
        </Tabs>
      </section>

      {switching && <Modal open onOpenChange={o => !o && setSwitching(null)}
        title={`${switching.preview.direction === "up" ? "Upgrade" : "Switch"} to ${switching.plan.name}`}
        description={switching.preview.from && switching.preview.from.code !== "trial" ? `From ${switching.preview.from.name}. The new plan starts today with a fresh monthly period.` : "Your plan starts today."}
        footer={<><Button variant="secondary" onClick={() => setSwitching(null)}>Cancel</Button>
          <Button loading={busy === switching.plan.code} onClick={confirmSwitch}>{switching.preview.charge_cents ? `Continue to pay ${money(switching.preview.charge_cents)}` : "Switch now"}</Button></>}>
        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between"><dt className="text-muted">{switching.plan.name} plan, first month</dt><dd className="tabular-nums">{money(switching.preview.to.price_cents)}</dd></div>
          {switching.preview.unused_credit_cents > 0 && <div className="flex justify-between"><dt className="text-muted">Credit for unused {switching.preview.from?.name} time</dt><dd className="tabular-nums text-success">−{money(switching.preview.unused_credit_cents)}</dd></div>}
          {switching.preview.account_credit_cents > 0 && <div className="flex justify-between"><dt className="text-muted">Account credit</dt><dd className="tabular-nums text-success">−{money(switching.preview.account_credit_cents)}</dd></div>}
          <div className="flex justify-between border-t border-border pt-1.5 font-semibold"><dt>Due today</dt><dd className="tabular-nums">{money(switching.preview.charge_cents)}</dd></div>
          {switching.preview.leftover_credit_cents > 0 && <p className="text-xs text-muted">{money(switching.preview.leftover_credit_cents)} of credit is left over and applies to your next plan charge.</p>}
          <p className="pt-1 text-xs text-muted">Adds {num(switching.preview.to.tokens)} tokens now. Tokens you already have are kept.</p>
        </dl>
        {(switching.preview.seats.over > 0 || switching.preview.cancels_addons.length > 0 || switching.preview.loses_modules.length > 0) && <div className="mt-4 space-y-2">
          {switching.preview.seats.over > 0 && <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-[13px]"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>{switching.plan.name} includes {switching.preview.seats.limit} seat{switching.preview.seats.limit === 1 ? "" : "s"}; this workspace has {switching.preview.seats.used} members. Everyone keeps access, but no one new can join until {switching.preview.seats.over} member{switching.preview.seats.over === 1 ? " is" : "s are"} removed.</span></div>}
          {switching.preview.cancels_addons.length > 0 && <div className="rounded-lg border border-border bg-panel2/60 p-3 text-[13px]">
            {switching.plan.name} includes {switching.preview.cancels_addons.map(a => a.name).join(", ")}, so {switching.preview.cancels_addons.length === 1 ? "that add-on stops" : "those add-ons stop"} billing separately
            (saving {money(switching.preview.cancels_addons.reduce((a, c) => a + c.price_cents, 0), "month")}).</div>}
          {switching.preview.loses_modules.length > 0 && <div className="rounded-lg border border-border bg-panel2/60 p-3 text-[13px]">Not included in {switching.plan.name}: {switching.preview.loses_modules.join(", ")}. Your parts stay; those modules lock unless you add them.</div>}
        </div>}
      </Modal>}

      <Modal open={cancelOpen} onOpenChange={setCancelOpen} title="Cancel subscription?" description="You'll lose access to plan modules and the monthly token allowance. Purchased tokens stay in your wallet."
        footer={<><Button variant="secondary" onClick={() => setCancelOpen(false)}>Keep plan</Button>
          <Button variant="danger" onClick={async () => { try { await api.post("/api/billing/cancel"); toast.success("Subscription canceled"); setCancelOpen(false); await qc.invalidateQueries(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } }}>Cancel subscription</Button></>} />
    </div>
  );
}

export function Checkout() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { me, refresh } = useSession();
  const q = useQuery({ queryKey: ["payment", id], queryFn: () => api.get<{ id: string; status: string; provider: string; amount_cents: number; product: Product | null }>(`/api/billing/payments/${id}`) });
  const cat = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [card, setCard] = useState("4242 4242 4242 4242");
  if (!q.data) return <PageLoader />;
  const p = q.data;
  const prod = p.product;
  const simulate = async (outcome: "success" | "fail") => {
    setBusy(outcome);
    try { await api.post(`/api/billing/payments/${id}/simulate`, { outcome }); await qc.invalidateQueries(); await refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(null); }
  };

  if (p.status === "paid") return (
    <div className="mx-auto max-w-lg px-6 py-16 text-center">
      <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-success/10"><CheckCircle2 className="h-9 w-9 text-success" /></div>
      <h1 className="mt-5 text-2xl font-semibold">Payment successful</h1>
      <p className="mt-2 text-muted">{prod?.name} · {money(p.amount_cents)}{prod?.interval ? ` per ${prod.interval}` : ""}</p>
      <Card className="mt-8 p-5 text-left text-sm">
        {prod?.kind === "plan" && <p>You're now on <b>{prod.name}</b>. {num(prod.tokens)} tokens were added and these modules are unlocked: {prod.modules.map(c => cat.data?.modules.find(m => m.code === c)?.name ?? c).join(", ")}.</p>}
        {prod?.kind === "addon" && <p><b>{prod.name}</b> is unlocked for {me?.org?.name}.</p>}
        {prod?.kind === "topup" && <p><b>{num(prod.tokens)} tokens</b> were added to your wallet. New balance: {num(me?.org?.token_balance)}.</p>}
        {prod?.kind === "seat" && <p>One more seat was added to {me?.org?.name}. You can invite another teammate now.</p>}
        <p className="mt-2 text-xs text-muted"><a className="link" href={`/api/billing/payments/${p.id}/receipt`} target="_blank" rel="noopener">View the receipt</a> · also in Billing → Payments.</p>
      </Card>
      <div className="mt-6 flex justify-center gap-2"><Button onClick={() => nav("/app/projects")}>Go to projects</Button><Button variant="secondary" onClick={() => nav("/app/billing")}>View billing</Button></div>
    </div>
  );

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <Link to="/app/billing" className="mb-6 inline-flex items-center gap-1 text-sm text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Back to billing</Link>
      <div className="mb-6 flex items-center gap-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-3 text-sm"><FlaskConical className="h-4 w-4 text-accent" /><span><b>Simulated checkout.</b> This environment has no payment provider. Nothing is charged; use the buttons to simulate an approved or declined payment.</span></div>
      <div className="grid overflow-hidden rounded-xl border border-border bg-panel shadow-card md:grid-cols-2">
        <div className="bg-panel2 p-8">
          <div className="text-sm text-muted">Formwright · {me?.org?.name}</div>
          <div className="mt-6 text-sm text-muted">{prod?.kind === "topup" ? "One-time purchase" : "Subscription"}</div>
          <div className="mt-1 text-xl font-semibold">{prod?.name}</div>
          <div className="mt-2 text-4xl font-semibold tracking-tight">{money(p.amount_cents)}{prod?.interval && p.amount_cents === prod.price_cents && <span className="text-base font-normal text-muted"> / {prod.interval}</span>}</div>
          {prod?.interval && p.amount_cents !== prod.price_cents && <div className="mt-1 text-sm text-muted">today, after credit for unused time; then {money(prod.price_cents, prod.interval)}</div>}
          <ul className="mt-6 space-y-1.5 text-sm text-muted">{(prod?.features ?? []).slice(0, 5).map(f => <li key={f}>· {f}</li>)}</ul>
        </div>
        <div className="p-8">
          {p.status === "failed" && <div className="mb-4 flex flex-wrap items-center gap-2 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"><XCircle className="h-4 w-4" /><span className="flex-1">Payment declined (simulated). Nothing was charged.</span>
            {prod && <Button size="sm" variant="secondary" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy === "retry"} onClick={async () => { setBusy("retry"); try { await buy(prod.code, nav); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not start a new checkout"); } finally { setBusy(null); } }}>Try again</Button>}</div>}
          <label className="text-[13px] font-medium">Card information</label>
          <div className="mt-1.5 overflow-hidden rounded border border-border">
            <Input value={card} onChange={e => setCard(e.target.value)} className="rounded-none border-0 border-b" aria-label="Card number" />
            <div className="grid grid-cols-2"><Input defaultValue="12 / 34" className="rounded-none border-0 border-r" aria-label="Expiry" /><Input defaultValue="123" className="rounded-none border-0" aria-label="CVC" /></div>
          </div>
          <label className="mt-4 block text-[13px] font-medium">Name on card</label>
          <Input className="mt-1.5" defaultValue={me?.user?.name} />
          <Button className="mt-6 w-full" size="lg" icon={<CreditCard className="h-4 w-4" />} loading={busy === "success"} disabled={!!busy || p.status !== "pending"} onClick={() => simulate("success")}>Pay {money(p.amount_cents)}</Button>
          <Button className="mt-2 w-full" variant="ghost" loading={busy === "fail"} disabled={!!busy || p.status !== "pending"} onClick={() => simulate("fail")}>Simulate a declined card</Button>
          <div className="mt-6 flex items-center justify-center gap-1.5 text-xs text-muted"><ShieldCheck className="h-3.5 w-3.5" />In production, payments are processed by Stripe.</div>
        </div>
      </div>
    </div>
  );
}
