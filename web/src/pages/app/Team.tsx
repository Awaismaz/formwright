import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MailPlus, MoreHorizontal, Trash2, UserMinus, Users } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { Org, Role } from "@/lib/types";
import { ago, date, money, PAGE } from "@/lib/format";
import type { Catalog } from "@/lib/types";
import TeamsTab from "./TeamsTab";
import { Avatar, Badge, Button, Card, Field, Input, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Modal, PageHeader, PageLoader, Progress } from "@/components/ui";

interface TeamData {
  org: Org; my_role: Role; roles: Role[];
  members: { id: string; user_id: string; name: string; email: string; role: Role; joined_at: string; last_login_at: string | null }[];
  invites: { id: string; email: string; role: Role; created_at: string; expires_at: string }[];
}

const ROLE_HELP: Record<Role, string> = {
  owner: "Full control, including billing and deleting the workspace",
  admin: "Manage members, billing and all projects",
  engineer: "Create projects and run the design agent",
  viewer: "View projects and download exports",
};

export default function Team() {
  const { me } = useSession();
  const nav = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["team"], queryFn: () => api.get<TeamData>("/api/team") });
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("engineer");
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<{ title: string; body: string; cta: string; danger?: boolean; run: () => Promise<unknown>; ok: string } | null>(null);
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") === "teams" ? "teams" : "members";
  if (!q.data) return <PageLoader />;
  const { org, members, invites, my_role } = q.data;
  const manage = canManage(my_role);
  const full = org.seats_used + invites.length >= org.seat_limit;
  const refresh = () => qc.invalidateQueries({ queryKey: ["team"] });
  const call = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast.success(ok); refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const invite = async () => {
    setBusy(true);
    try { await api.post("/api/team/invites", { email, role }); toast.success(`Invitation sent to ${email}`); setOpen(false); setEmail(""); refresh(); qc.invalidateQueries({ queryKey: ["checklist"] }); }
    catch (e) {
      if (e instanceof ApiError && e.status === 402) { toast.error(e.message, { action: { label: "Upgrade", onClick: () => nav("/app/billing") } }); }
      else toast.error(e instanceof ApiError ? e.message : "Failed");
    } finally { setBusy(false); }
  };
  return (
    <div className={PAGE}>
      <PageHeader title="Team" subtitle={`Members, roles and teams for ${org.name}.`}
        actions={manage && tab === "members" && <Button icon={<MailPlus className="h-4 w-4" />} onClick={() => setOpen(true)}>Invite teammate</Button>} />
      <div className="mb-5 inline-flex rounded-lg border border-border bg-panel p-0.5 text-sm" role="tablist">
        {(["members", "teams"] as const).map(t => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setSp(t === "teams" ? { tab: "teams" } : {}, { replace: true })}
          className={tab === t ? "rounded bg-primary px-3 py-1 capitalize text-white" : "rounded px-3 py-1 capitalize text-muted"}>{t}</button>)}
      </div>
      {tab === "teams" ? <TeamsTab /> : <>
      <Card className="mb-6 flex flex-wrap items-center gap-6 p-5">
        <div className="flex items-center gap-3"><Users className="h-5 w-5 text-primary" /><div><div className="text-sm font-medium">Seats</div><div className="text-xs text-muted">{org.seats_used} used{invites.length ? ` · ${invites.length} pending` : ""} of {org.seat_limit >= 1000 ? "unlimited" : org.seat_limit}</div></div></div>
        {org.seat_limit < 1000 && <Progress className="max-w-xs flex-1" value={org.seats_used + invites.length} max={org.seat_limit} tone={full ? "warning" : "primary"} />}
        {full && manage && (org.plan_code === "team"
          ? <Button size="sm" variant="secondary" onClick={() => nav("/app/billing")}>Add a seat{catalog.data?.seats?.[0] ? ` · ${money(catalog.data.seats[0].price_cents, catalog.data.seats[0].interval)}` : ""}</Button>
          : <Button size="sm" variant="secondary" onClick={() => nav("/app/billing")}>Upgrade to Team for 5 seats</Button>)}
      </Card>
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel2 text-left text-xs text-muted"><tr><th className="px-4 py-2.5 font-medium">Member</th><th className="px-4 py-2.5 font-medium">Role</th><th className="px-4 py-2.5 font-medium">Last active</th><th className="px-4 py-2.5 font-medium">Joined</th><th /></tr></thead>
          <tbody className="divide-y divide-border">
            {members.map(m => (
              <tr key={m.id}>
                <td className="px-4 py-3"><div className="flex items-center gap-3"><Avatar name={m.name} size={32} /><div><div className="font-medium">{m.name}{m.user_id === me?.user?.id && <span className="ml-1.5 text-xs text-muted">(you)</span>}</div><div className="text-xs text-muted">{m.email}</div></div></div></td>
                <td className="px-4 py-3"><Badge tone={m.role === "owner" ? "accent" : m.role === "admin" ? "primary" : "neutral"} className="capitalize">{m.role}</Badge></td>
                <td className="px-4 py-3 text-muted">{ago(m.last_login_at)}</td>
                <td className="px-4 py-3 text-muted">{date(m.joined_at)}</td>
                <td className="px-4 py-3 text-right">
                  {(manage || m.user_id === me?.user?.id) && (
                    <Menu>
                      <MenuTrigger asChild><button className="rounded p-1.5 text-muted hover:bg-text/5" aria-label="Member actions"><MoreHorizontal className="h-4 w-4" /></button></MenuTrigger>
                      <MenuContent>
                        {manage && <><MenuLabel>Change role</MenuLabel>
                          {(["owner", "admin", "engineer", "viewer"] as Role[]).filter(r => r !== m.role && (r !== "owner" || my_role === "owner")).map(r =>
                            <MenuItem key={r} onSelect={() => setAsk(r === "owner"
                              ? { title: `Make ${m.name} an owner?`, body: `${m.name} will get full control of ${org.name}, including billing, members and deleting the workspace. You stay an owner until you change your own role.`, cta: "Make owner", run: () => api.patch(`/api/team/members/${m.id}`, { role: r }), ok: `${m.name} is now an owner` }
                              : { title: `Change ${m.name} to ${r}?`, body: `${ROLE_HELP[r]}.${m.role === "owner" || m.role === "admin" ? ` ${m.name} loses ${m.role} rights.` : ""}`, cta: `Change to ${r}`, run: () => api.patch(`/api/team/members/${m.id}`, { role: r }), ok: `${m.name} is now ${r === "admin" || r === "engineer" ? "an" : "a"} ${r}` })}>
                              <span className="capitalize">{r}</span></MenuItem>)}
                          <MenuSeparator /></>}
                        <MenuItem icon={<UserMinus />} danger onSelect={() => setAsk(m.user_id === me?.user?.id
                          ? { title: `Leave ${org.name}?`, body: "You lose access to its projects, tokens and billing straight away. An admin has to invite you to come back.", cta: "Leave workspace", danger: true, run: () => api.del(`/api/team/members/${m.id}`), ok: "You left the workspace" }
                          : { title: `Remove ${m.name}?`, body: `${m.name} (${m.email}) loses access to ${org.name} and its projects straight away. Their past revisions and ledger entries stay. You can invite them again later.`, cta: "Remove member", danger: true, run: () => api.del(`/api/team/members/${m.id}`), ok: `${m.name} was removed` })}>
                          {m.user_id === me?.user?.id ? "Leave workspace" : "Remove from workspace"}</MenuItem>
                      </MenuContent>
                    </Menu>
                  )}
                </td>
              </tr>
            ))}
            {invites.map(i => (
              <tr key={i.id} className="bg-panel2/40">
                <td className="px-4 py-3"><div className="flex items-center gap-3"><span className="flex h-8 w-8 items-center justify-center rounded-full border border-dashed border-border"><MailPlus className="h-4 w-4 text-muted" /></span><div><div className="font-medium">{i.email}</div><div className="text-xs text-muted">Invitation pending · expires {date(i.expires_at)}</div></div></div></td>
                <td className="px-4 py-3"><Badge className="capitalize">{i.role}</Badge></td><td className="px-4 py-3 text-muted">-</td><td className="px-4 py-3 text-muted">{date(i.created_at)}</td>
                <td className="px-4 py-3 text-right">{manage && <button className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-danger" aria-label="Revoke invitation" onClick={() => call(() => api.del(`/api/team/invites/${i.id}`), "Invitation revoked")}><Trash2 className="h-4 w-4" /></button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(Object.keys(ROLE_HELP) as Role[]).map(r => <div key={r} className="rounded-lg border border-border bg-panel p-3"><div className="text-sm font-medium capitalize">{r}</div><div className="mt-0.5 text-xs text-muted">{ROLE_HELP[r]}</div></div>)}
      </div>
      {ask && <Modal open onOpenChange={o => !o && setAsk(null)} title={ask.title} description={ask.body}
        footer={<><Button variant="secondary" onClick={() => setAsk(null)}>Cancel</Button>
          <Button variant={ask.danger ? "danger" : "primary"} loading={busy} onClick={async () => {
            setBusy(true);
            try { await ask.run(); toast.success(ask.ok); setAsk(null); refresh(); if (ask.cta === "Leave workspace") { await qc.invalidateQueries(); nav("/app"); } }
            catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
          }}>{ask.cta}</Button></>} />}

      <Modal open={open} onOpenChange={setOpen} title="Invite a teammate" description="They'll get an email with a link to join this workspace."
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={invite} loading={busy} disabled={!email}>Send invitation</Button></>}>
        <div className="space-y-4">
          <Field label="Email"><Input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="colleague@company.com" autoFocus /></Field>
          <Field label="Role" hint={ROLE_HELP[role]}>
            <select value={role} onChange={e => setRole(e.target.value as Role)} className="input">
              {(["admin", "engineer", "viewer"] as Role[]).map(r => <option key={r} value={r}>{r[0]!.toUpperCase() + r.slice(1)}</option>)}
            </select>
          </Field>
          {full && <p className="rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs">All seats are in use on your plan. {org.plan_code === "team" ? "Add a seat in Billing first." : "Upgrade to Team for 5 seats."}</p>}
        </div>
      </Modal>
      </>}
    </div>
  );
}
