import { useState } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Building2, Coins, CreditCard, DollarSign, FolderKanban, Hammer, Mail, MessageSquare, Package, ScrollText, Server, Users } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Product } from "@/lib/types";
import { ago, cx, date, money, num } from "@/lib/format";
import { Badge, Button, Card, Input, Modal, PageHeader, PageLoader, Stat, Toggle } from "@/components/ui";

const TABS = [["", "Overview", Activity], ["users", "Users", Users], ["orgs", "Organizations", Building2], ["catalog", "Pricing catalog", Package],
  ["payments", "Payments", CreditCard], ["feedback", "Feedback", MessageSquare], ["audit", "Audit log", ScrollText], ["outbox", "Email outbox", Mail], ["system", "System", Server]] as const;

function useAdmin<T>(path: string) {
  return useQuery({ queryKey: ["admin", path], queryFn: () => api.get<T>(`/api/admin/${path}`) });
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="bg-panel2 text-left text-xs text-muted"><tr>{head.map(h => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </Card>
  );
}

interface OverviewData {
  kpis: Record<string, number>; funnel: { event: string; label: string; users: number }[];
  signups_30d: { date: string; count: number }[]; plans: Record<string, number>; payments_mode: string; note: string | null;
}

function Overview() {
  const q = useAdmin<OverviewData>("overview");
  if (!q.data) return <PageLoader />;
  const { kpis, funnel, signups_30d, plans, note } = q.data;
  const top = Math.max(1, ...funnel.map(f => f.users));
  const maxS = Math.max(1, ...signups_30d.map(s => s.count));
  return (
    <div className="space-y-6">
      {note && <div className="rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5 text-sm">{note}</div>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="MRR" value={money(kpis.mrr_cents ?? 0)} icon={<DollarSign className="h-4 w-4" />} sub={`${kpis.paid_orgs} paying workspaces`} />
        <Stat label="Users" value={num(kpis.users)} icon={<Users className="h-4 w-4" />} sub={`${kpis.active_7d} active in 7 days`} />
        <Stat label="Projects" value={num(kpis.projects)} icon={<FolderKanban className="h-4 w-4" />} sub={`${num(kpis.builds)} verified builds`} />
        <Stat label="Tokens used · 30d" value={num(kpis.tokens_used_30d)} icon={<Coins className="h-4 w-4" />} sub={`Revenue to date ${money(kpis.revenue_cents ?? 0)}`} />
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card className="p-5">
          <h3 className="font-semibold">Customer journey funnel</h3>
          <p className="text-xs text-muted">Distinct users reaching each step</p>
          <div className="mt-4 space-y-2.5">
            {funnel.map((f, i) => {
              const prev = i ? funnel[i - 1]!.users : f.users;
              return (
                <div key={f.event} className="grid grid-cols-[150px_1fr_80px] items-center gap-3 text-sm">
                  <span className="text-muted">{f.label}</span>
                  <div className="h-6 rounded bg-text/[.05]"><div className="flex h-full items-center rounded bg-primary/85 px-2 text-[11px] font-semibold text-white" style={{ width: `${Math.max(4, (f.users / top) * 100)}%` }}>{f.users}</div></div>
                  <span className="text-right text-xs text-muted">{i && prev ? `${Math.min(100, Math.round((f.users / prev) * 100))}% step` : ""}</span>
                </div>);
            })}
          </div>
        </Card>
        <Card className="p-5">
          <h3 className="font-semibold">Signups · 30 days</h3>
          <div className="mt-4 flex h-28 items-end gap-[3px]">{signups_30d.map(s => <div key={s.date} title={`${s.date}: ${s.count}`} className={cx("flex-1 rounded-t-sm", s.count ? "bg-accent" : "bg-text/[.07]")} style={{ height: `${Math.max(3, (s.count / maxS) * 110)}px` }} />)}</div>
          <h3 className="mt-6 font-semibold">Workspaces by plan</h3>
          <div className="mt-3 flex flex-wrap gap-2">{Object.entries(plans).map(([k, v]) => <Badge key={k} tone="primary">{k}: {v}</Badge>)}</div>
        </Card>
      </div>
    </div>
  );
}

interface AUser { id: string; name: string; email: string; verified: boolean; superadmin: boolean; disabled: boolean; onboarded: boolean; onboarding: Record<string, unknown>; orgs: { id: string; name: string; role: string; plan: string }[]; created_at: string; last_login_at: string | null }

function UsersTab() {
  const [q, setQ] = useState("");
  const { refresh, me } = useSession();
  const nav = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["admin", "users", q], queryFn: () => api.get<{ items: AUser[] }>(`/api/admin/users?q=${encodeURIComponent(q)}`) });
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); toast.success(ok); qc.invalidateQueries({ queryKey: ["admin"] }); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } };
  return (
    <div className="space-y-4">
      <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search name or email" className="max-w-sm" />
      <Table head={["User", "Workspaces", "Status", "Signed up", "Last login", ""]}>
        {(list.data?.items ?? []).map(u => (
          <tr key={u.id}>
            <td className="px-4 py-2.5"><div className="font-medium">{u.name} {u.superadmin && <Badge tone="accent">super-admin</Badge>}</div><div className="text-xs text-muted">{u.email}{u.onboarding?.role ? ` · ${String(u.onboarding.role)}` : ""}</div></td>
            <td className="px-4 py-2.5 text-xs">{u.orgs.map(o => <div key={o.id}>{o.name} <span className="text-muted">({o.role}, {o.plan})</span></div>)}</td>
            <td className="px-4 py-2.5"><div className="flex flex-wrap gap-1">{u.disabled ? <Badge tone="danger">disabled</Badge> : <Badge tone="success">active</Badge>}{!u.verified && <Badge tone="warning">unverified</Badge>}{!u.onboarded && <Badge>not onboarded</Badge>}</div></td>
            <td className="px-4 py-2.5 text-muted">{date(u.created_at)}</td>
            <td className="px-4 py-2.5 text-muted">{ago(u.last_login_at)}</td>
            <td className="space-x-1 whitespace-nowrap px-4 py-2.5 text-right">
              {u.id !== me?.user?.id && !u.disabled && <Button size="sm" variant="secondary" onClick={() => act(async () => { await api.post(`/api/admin/users/${u.id}/impersonate`); await refresh(); nav("/app"); }, `Now viewing as ${u.email}`)}>View as</Button>}
              {!u.verified && <Button size="sm" variant="ghost" onClick={() => act(() => api.patch(`/api/admin/users/${u.id}`, { verify_email: true }), "Email marked verified")}>Verify</Button>}
              {u.id !== me?.user?.id && <Button size="sm" variant="ghost" onClick={() => act(() => api.patch(`/api/admin/users/${u.id}`, { disabled: !u.disabled }), u.disabled ? "User enabled" : "User disabled")}>{u.disabled ? "Enable" : "Disable"}</Button>}
            </td>
          </tr>))}
      </Table>
    </div>
  );
}

interface AOrg { id: string; name: string; plan_code: string; plan_status: string; token_balance: number; seats_used: number; modules: string[]; projects: number; created_at: string }

function OrgsTab() {
  const q = useAdmin<{ items: AOrg[]; modules: string[] }>("orgs");
  const plans = useQuery({ queryKey: ["admin", "catalog"], queryFn: () => api.get<{ items: Product[] }>("/api/admin/catalog") });
  const qc = useQueryClient();
  const [grant, setGrant] = useState<AOrg | null>(null);
  const [amount, setAmount] = useState("500");
  const [note, setNote] = useState("");
  const [mods, setMods] = useState<AOrg | null>(null);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); toast.success(ok); qc.invalidateQueries({ queryKey: ["admin"] }); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } };
  if (!q.data) return <PageLoader />;
  return (
    <>
      <Table head={["Workspace", "Plan", "Tokens", "Seats", "Projects", "Modules", ""]}>
        {q.data.items.map(o => (
          <tr key={o.id}>
            <td className="px-4 py-2.5"><div className="font-medium">{o.name}</div><div className="text-xs text-muted">since {date(o.created_at)}</div></td>
            <td className="px-4 py-2.5">
              <select className="input h-8 w-auto text-xs" value={o.plan_code} onChange={e => act(() => api.patch(`/api/admin/orgs/${o.id}`, { plan_code: e.target.value, plan_status: e.target.value === "trial" ? "trialing" : "active" }), "Plan changed")}>
                {(plans.data?.items ?? []).filter(p => p.kind === "plan").map(p => <option key={p.code} value={p.code}>{p.name}</option>)}
              </select> <Badge className="ml-1">{o.plan_status}</Badge></td>
            <td className="px-4 py-2.5 tabular-nums">{num(o.token_balance)}</td>
            <td className="px-4 py-2.5">{o.seats_used}</td>
            <td className="px-4 py-2.5">{o.projects}</td>
            <td className="px-4 py-2.5 text-xs text-muted">{o.modules.join(", ")}</td>
            <td className="space-x-1 whitespace-nowrap px-4 py-2.5 text-right">
              <Button size="sm" variant="secondary" onClick={() => setGrant(o)}>Tokens</Button>
              <Button size="sm" variant="ghost" onClick={() => setMods(o)}>Modules</Button>
            </td>
          </tr>))}
      </Table>
      <Modal open={!!grant} onOpenChange={v => !v && setGrant(null)} title={`Adjust tokens · ${grant?.name}`} description="Positive grants or negative adjustments. Logged in the ledger and audit log."
        footer={<><Button variant="secondary" onClick={() => setGrant(null)}>Cancel</Button><Button onClick={() => { act(() => api.post(`/api/admin/orgs/${grant!.id}/tokens`, { amount: Number(amount), note }), "Tokens adjusted"); setGrant(null); }}>Apply</Button></>}>
        <div className="grid gap-3 sm:grid-cols-2"><Input type="number" value={amount} onChange={e => setAmount(e.target.value)} /><Input value={note} onChange={e => setNote(e.target.value)} placeholder="Note (e.g. pilot grant)" /></div>
      </Modal>
      <Modal open={!!mods} onOpenChange={v => !v && setMods(null)} title={`Module grants · ${mods?.name}`}>
        <div className="space-y-2">{q.data.modules.map(m => {
          const on = q.data!.items.find(x => x.id === mods?.id)?.modules.includes(m) ?? false;
          return <div key={m} className="flex items-center justify-between"><span className="text-sm">{m}</span><Toggle checked={on} onChange={v => act(() => api.post(`/api/admin/orgs/${mods!.id}/modules`, { module: m, enabled: v }), "Updated")} /></div>;
        })}<p className="pt-2 text-xs text-muted">Grants add to what the plan includes. Plan modules can't be removed here.</p></div>
      </Modal>
    </>
  );
}

function CatalogTab() {
  const q = useAdmin<{ items: Product[] }>("catalog");
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Record<string, { price: string; tokens: string }>>({});
  if (!q.data) return <PageLoader />;
  const save = async (p: Product) => {
    const e = edit[p.code]; if (!e) return;
    try {
      await api.patch(`/api/admin/catalog/${p.code}`, { price_cents: Math.round(Number(e.price) * 100), tokens: Number(e.tokens) });
      toast.success(`${p.name} updated`); setEdit(({ [p.code]: _, ...rest }) => rest); qc.invalidateQueries();
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Failed"); }
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">Prices and allowances are pricing hypotheses — change them here and every pricing surface updates. With Stripe configured, new checkouts use the new price.</p>
      <Table head={["Product", "Kind", "Price (USD)", "Tokens", "Active", ""]}>
        {q.data.items.map(p => {
          const e = edit[p.code] ?? { price: String(p.price_cents / 100), tokens: String(p.tokens) };
          const dirty = !!edit[p.code];
          return (
            <tr key={p.code}>
              <td className="px-4 py-2"><div className="font-medium">{p.name}</div><div className="font-mono text-[11px] text-muted">{p.code}</div></td>
              <td className="px-4 py-2"><Badge>{p.kind}</Badge>{p.interval && <span className="ml-1 text-xs text-muted">/{p.interval}</span>}</td>
              <td className="px-4 py-2"><Input className="h-8 w-28" type="number" step="0.01" value={e.price} disabled={p.contact_sales} onChange={ev => setEdit({ ...edit, [p.code]: { ...e, price: ev.target.value } })} /></td>
              <td className="px-4 py-2"><Input className="h-8 w-28" type="number" value={e.tokens} onChange={ev => setEdit({ ...edit, [p.code]: { ...e, tokens: ev.target.value } })} /></td>
              <td className="px-4 py-2"><Toggle checked={p.active} onChange={v => api.patch(`/api/admin/catalog/${p.code}`, { active: v }).then(() => qc.invalidateQueries())} /></td>
              <td className="px-4 py-2 text-right">{dirty && <Button size="sm" onClick={() => save(p)}>Save</Button>}</td>
            </tr>);
        })}
      </Table>
    </div>
  );
}

function SimpleList<T>({ path, head, row }: { path: string; head: string[]; row: (r: T) => React.ReactNode }) {
  const q = useAdmin<{ items: T[] }>(path);
  if (!q.data) return <PageLoader />;
  return <Table head={head}>{q.data.items.length ? q.data.items.map(row) : <tr><td colSpan={head.length} className="px-4 py-8 text-center text-muted">Nothing yet.</td></tr>}</Table>;
}

function SystemTab() {
  const q = useAdmin<Record<string, unknown>>("system");
  if (!q.data) return <PageLoader />;
  return (
    <Card className="divide-y divide-border">
      {Object.entries(q.data).map(([k, v]) => <div key={k} className="flex justify-between px-5 py-3 text-sm"><span className="text-muted">{k.replace(/_/g, " ")}</span><span className="font-mono text-[13px]">{Array.isArray(v) ? v.join(", ") : String(v)}</span></div>)}
    </Card>
  );
}

export default function Admin() {
  const { me } = useSession();
  if (!me?.user?.is_superadmin && !me?.impersonating) return <Navigate to="/app" replace />;
  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader title="Admin console" subtitle="Platform-wide operations. Every action here is written to the audit log."
        eyebrow={<Badge tone="accent"><Hammer className="h-3 w-3" />Super-admin</Badge>} />
      <nav className="mb-6 flex flex-wrap gap-1 border-b border-border">
        {TABS.map(([to, label, I]) => (
          <NavLink key={to} to={`/app/admin${to ? "/" + to : ""}`} end
            className={({ isActive }) => cx("-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm", isActive ? "border-primary font-medium text-text" : "border-transparent text-muted hover:text-text")}>
            <I className="h-4 w-4" />{label}</NavLink>))}
      </nav>
      <Routes>
        <Route index element={<Overview />} />
        <Route path="users" element={<UsersTab />} />
        <Route path="orgs" element={<OrgsTab />} />
        <Route path="catalog" element={<CatalogTab />} />
        <Route path="payments" element={<SimpleList<{ id: string; org: string; product_code: string; amount_cents: number; status: string; provider: string; created_at: string }> path="payments"
          head={["Date", "Workspace", "Product", "Amount", "Status", "Provider"]}
          row={r => <tr key={r.id}><td className="px-4 py-2.5 text-muted">{date(r.created_at)}</td><td className="px-4 py-2.5">{r.org}</td><td className="px-4 py-2.5 font-mono text-xs">{r.product_code}</td><td className="px-4 py-2.5 tabular-nums">{money(r.amount_cents)}</td><td className="px-4 py-2.5"><Badge tone={r.status === "paid" ? "success" : r.status === "failed" ? "danger" : "neutral"}>{r.status}</Badge></td><td className="px-4 py-2.5 text-muted">{r.provider}</td></tr>} />} />
        <Route path="feedback" element={<SimpleList<{ id: string; user: string; kind: string; topic: string | null; message: string; rating: number | null; created_at: string }> path="feedback"
          head={["Date", "User", "Type", "Message", "Rating"]}
          row={r => <tr key={r.id}><td className="px-4 py-2.5 text-muted">{date(r.created_at)}</td><td className="px-4 py-2.5 text-xs">{r.user}</td><td className="px-4 py-2.5"><Badge tone={r.kind === "waitlist" ? "accent" : r.kind === "bug" ? "danger" : "neutral"}>{r.kind}{r.topic ? ` · ${r.topic}` : ""}</Badge></td><td className="max-w-md px-4 py-2.5">{r.message}</td><td className="px-4 py-2.5">{r.rating ? "★".repeat(r.rating) : "—"}</td></tr>} />} />
        <Route path="audit" element={<SimpleList<{ id: string; actor: string; action: string; target: string | null; meta: Record<string, unknown>; ip: string | null; created_at: string }> path="audit"
          head={["When", "Actor", "Action", "Target", "Details"]}
          row={r => <tr key={r.id}><td className="whitespace-nowrap px-4 py-2 text-muted">{ago(r.created_at)}</td><td className="px-4 py-2 text-xs">{r.actor}</td><td className="px-4 py-2 font-mono text-xs">{r.action}</td><td className="px-4 py-2 text-xs text-muted">{r.target}</td><td className="max-w-sm truncate px-4 py-2 font-mono text-[11px] text-muted">{JSON.stringify(r.meta)}</td></tr>} />} />
        <Route path="outbox" element={<SimpleList<{ id: string; to: string; subject: string; body: string; link: string | null; delivered: string; created_at: string }> path="outbox"
          head={["When", "To", "Subject", "Link", "Delivery"]}
          row={r => <tr key={r.id}><td className="whitespace-nowrap px-4 py-2.5 text-muted">{ago(r.created_at)}</td><td className="px-4 py-2.5 text-xs">{r.to}</td><td className="px-4 py-2.5">{r.subject}</td><td className="px-4 py-2.5">{r.link && <a className="link text-xs" href={new URL(r.link).pathname + new URL(r.link).search}>open</a>}</td><td className="px-4 py-2.5"><Badge>{r.delivered}</Badge></td></tr>} />} />
        <Route path="system" element={<SystemTab />} />
      </Routes>
    </div>
  );
}
