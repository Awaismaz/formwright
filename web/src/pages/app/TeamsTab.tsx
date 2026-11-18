import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2, UserMinus, UserPlus, Users } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { TEAM_ROLE_HELP } from "@/lib/collab";
import { Avatar, Badge, Button, Card, EmptyState, Field, Input, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Modal, PageLoader } from "@/components/ui";

type TeamRole = "admin" | "editor" | "viewer";
interface TeamRow { id: string; name: string; description: string; color: string; my_role: TeamRole | null; can_manage: boolean; projects: number;
  members: { user_id: string; name: string; email: string; role: TeamRole }[] }
interface TeamsData { items: TeamRow[]; members: { user_id: string; name: string; email: string; role: string }[]; roles: TeamRole[]; colors: string[]; can_create: boolean }

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Failed");

function TeamForm({ init, colors, onSave, onClose, title }: { init?: Partial<TeamRow>; colors: string[]; title: string; onClose: () => void; onSave: (v: { name: string; description: string; color: string }) => Promise<void> }) {
  const [name, setName] = useState(init?.name ?? "");
  const [description, setDescription] = useState(init?.description ?? "");
  const [color, setColor] = useState(init?.color ?? colors[0] ?? "#2563eb");
  const [busy, setBusy] = useState(false);
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={title} description="Teams own projects: their members get access by team role."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!name.trim()} onClick={async () => { setBusy(true); try { await onSave({ name, description, color }); onClose(); } catch (e) { err(e); } finally { setBusy(false); } }}>Save team</Button></>}>
      <div className="space-y-4">
        <Field label="Name"><Input autoFocus value={name} onChange={e => setName(e.target.value)} maxLength={80} placeholder="e.g. Gearbox team" /></Field>
        <Field label="Description"><Input value={description} onChange={e => setDescription(e.target.value)} placeholder="What the team works on" /></Field>
        <Field label="Colour"><div className="flex flex-wrap gap-2">{colors.map(c => (
          <button key={c} onClick={() => setColor(c)} aria-label={`Colour ${c}`} className="h-7 w-7 rounded-full ring-offset-2 ring-offset-panel" style={{ background: c, boxShadow: color === c ? `0 0 0 2px ${c}` : undefined }} />))}</div></Field>
      </div>
    </Modal>);
}

/** Team page, "Teams" tab (PLT-020): create teams, manage members and team roles. */
export default function TeamsTab() {
  const { me } = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["teams"], queryFn: () => api.get<TeamsData>("/api/teams") });
  const [form, setForm] = useState<{ team?: TeamRow } | null>(null);
  const [adding, setAdding] = useState<TeamRow | null>(null);
  const [pick, setPick] = useState("");
  const [role, setRole] = useState<TeamRole>("editor");
  if (!q.data) return <PageLoader />;
  const d = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ["teams"] });
  const run = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); toast.success(ok); refresh(); } catch (e) { err(e); } };
  return (
    <div data-teams-tab>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="flex-1 text-[13px] text-muted">Group people who work on the same parts. A team project is open to its members by team role and read-only (or hidden) to the rest of the workspace.</p>
        {d.can_create && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setForm({})}>New team</Button>}
      </div>
      {!d.items.length ? <EmptyState icon={<Users className="h-6 w-6" />} title="No teams yet" body="Create a team, add members, then make projects team-owned from their Share dialog."
        action={d.can_create && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setForm({})}>New team</Button>} /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {d.items.map(t => (
            <Card key={t.id} className="overflow-hidden" data-team={t.name}>
              <div className="flex items-start gap-3 border-b border-border p-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-white" style={{ background: t.color }}><Users className="h-5 w-5" /></span>
                <div className="min-w-0 flex-1"><div className="flex items-center gap-2 font-semibold">{t.name}{t.my_role && <Badge tone="primary" className="capitalize">{t.my_role}</Badge>}</div>
                  <div className="text-[12.5px] text-muted">{t.description || "No description"} · {t.members.length} member{t.members.length === 1 ? "" : "s"} · {t.projects} project{t.projects === 1 ? "" : "s"}</div></div>
                {t.can_manage && <Menu>
                  <MenuTrigger asChild><button className="rounded p-1.5 text-muted hover:bg-text/5" aria-label={`Actions for ${t.name}`}><MoreHorizontal className="h-4 w-4" /></button></MenuTrigger>
                  <MenuContent>
                    <MenuItem icon={<UserPlus />} onSelect={() => { setAdding(t); setPick(""); setRole("editor"); }}>Add member…</MenuItem>
                    <MenuItem icon={<Pencil />} onSelect={() => setForm({ team: t })}>Edit team…</MenuItem>
                    <MenuSeparator />
                    <MenuItem icon={<Trash2 />} danger onSelect={() => { if (confirm(`Delete the ${t.name} team? Its projects stay, open to the workspace at their general access.`)) void run(() => api.del(`/api/teams/${t.id}`), "Team deleted"); }}>Delete team</MenuItem>
                  </MenuContent></Menu>}
              </div>
              <ul className="divide-y divide-border">
                {t.members.map(m => (
                  <li key={m.user_id} className="flex items-center gap-3 px-4 py-2.5">
                    <Avatar name={m.name} size={28} />
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{m.name}{m.user_id === me?.user?.id && <span className="ml-1 text-xs text-muted">(you)</span>}</span><span className="block truncate text-[11.5px] text-muted">{m.email}</span></span>
                    {t.can_manage ? (
                      <select value={m.role} title={TEAM_ROLE_HELP[m.role]} aria-label={`Team role of ${m.name}`} className="input h-7 w-auto py-0 pr-7 text-[12px]"
                        onChange={e => run(() => api.patch(`/api/teams/${t.id}/members/${m.user_id}`, { role: e.target.value }), `${m.name} is now team ${e.target.value}`)}>
                        {d.roles.map(r => <option key={r} value={r}>{r[0]!.toUpperCase() + r.slice(1)}</option>)}</select>
                    ) : <Badge className="capitalize">{m.role}</Badge>}
                    {(t.can_manage || m.user_id === me?.user?.id) && <button className="rounded p-1 text-muted hover:text-danger" aria-label={m.user_id === me?.user?.id ? "Leave team" : `Remove ${m.name}`}
                      onClick={() => run(() => api.del(`/api/teams/${t.id}/members/${m.user_id}`), m.user_id === me?.user?.id ? `You left ${t.name}` : `${m.name} removed`)}><UserMinus className="h-4 w-4" /></button>}
                  </li>))}
              </ul>
            </Card>))}
        </div>)}
      <div className="mt-6 grid gap-3 sm:grid-cols-3">{(["admin", "editor", "viewer"] as TeamRole[]).map(r => <div key={r} className="rounded-lg border border-border bg-panel p-3"><div className="text-sm font-medium capitalize">Team {r}</div><div className="mt-0.5 text-xs text-muted">{TEAM_ROLE_HELP[r]}</div></div>)}</div>
      <p className="mt-2 text-[12px] text-muted">Workspace owners and admins manage every team and have admin access to every project. Workspace viewers stay view-and-comment, whatever their team role.</p>
      {form && <TeamForm title={form.team ? `Edit ${form.team.name}` : "New team"} init={form.team} colors={d.colors} onClose={() => setForm(null)}
        onSave={async v => { if (form.team) await api.patch(`/api/teams/${form.team.id}`, v); else await api.post("/api/teams", v); toast.success(form.team ? "Team updated" : `Team ${v.name} created`); refresh(); }} />}
      {adding && <Modal open onOpenChange={o => !o && setAdding(null)} title={`Add to ${adding.name}`} description="Only workspace members can join a team. Invite people from the Members tab first."
        footer={<><Button variant="secondary" onClick={() => setAdding(null)}>Cancel</Button><Button disabled={!pick} onClick={async () => { await run(() => api.post(`/api/teams/${adding.id}/members`, { user_id: pick, role }), "Member added"); setAdding(null); }}>Add</Button></>}>
        <div className="space-y-4">
          <Field label="Person"><select className="input" value={pick} onChange={e => setPick(e.target.value)} aria-label="Person">
            <option value="">Choose a workspace member…</option>
            {d.members.filter(m => !adding.members.some(x => x.user_id === m.user_id)).map(m => <option key={m.user_id} value={m.user_id}>{m.name} · {m.email}</option>)}</select></Field>
          <Field label="Team role" hint={TEAM_ROLE_HELP[role]}><select className="input" value={role} onChange={e => setRole(e.target.value as TeamRole)} aria-label="Team role">
            {d.roles.map(r => <option key={r} value={r}>{r[0]!.toUpperCase() + r.slice(1)}</option>)}</select></Field>
        </div>
      </Modal>}

    </div>
  );
}
