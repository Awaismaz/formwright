import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Globe2, Link2, Lock, Mail, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { GRANT_LEVELS, LEVEL_HELP, LEVEL_TEXT, type Access, type Level } from "@/lib/collab";
import { date } from "@/lib/format";
import { Avatar, Badge, Button, Input, Modal, Toggle } from "@/components/ui";

interface Grant { id: string; subject_type: "user" | "team"; subject_id: string; level: Level; guest: boolean; name: string; email: string | null; color: string | null }
interface LinkRow { id: string; label: string; url: string; created_at: string; expires_at: string | null; uses: number; expired: boolean }
interface AccessData {
  me: Access; project: { id: string; name: string; created_by: string | null }; owner: { id: string; name: string; email: string } | null;
  grants: Grant[]; members?: { user_id: string; name: string; email: string; role: string }[];
  teams?: { id: string; name: string; color: string }[]; links?: LinkRow[];
  pending_guests?: { id: string; email: string; level: Level; expires_at: string }[];
}

const err = (e: unknown, fb = "Failed") => toast.error(e instanceof ApiError ? e.message : fb);

function LevelSelect({ value, onChange, levels = GRANT_LEVELS, label }: { value: Level; onChange: (l: Level) => void; levels?: Level[]; label: string }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value as Level)} aria-label={label} title={LEVEL_HELP[value]}
      className="input h-8 w-auto py-0 pr-7 text-[12.5px]">
      {levels.map(l => <option key={l} value={l}>{l === "none" ? "No access" : `Can ${l === "read" ? "view" : l}`}</option>)}
    </select>);
}

/** Google-Docs-style sharing: people and teams, guests by email, general access, read-only links, protected main. */
export default function ShareDialog({ projectId, open, onOpenChange }: { projectId: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["access", projectId], enabled: open, queryFn: () => api.get<AccessData>(`/api/projects/${projectId}/access`) });
  const [who, setWho] = useState("");
  const [level, setLevel] = useState<Level>("edit");
  const [expiry, setExpiry] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["access", projectId] }); qc.invalidateQueries({ queryKey: ["collab", projectId] }); qc.invalidateQueries({ queryKey: ["project", projectId] }); };
  const run = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); toast.success(ok); refresh(); } catch (e) { err(e); } };
  const d = q.data;
  const admin = !!d?.me.can_admin;
  const granted = new Set(d?.grants.map(g => `${g.subject_type}:${g.subject_id}`));
  const term = who.trim().toLowerCase();
  const suggestions = !d || !term ? [] : [
    ...(d.teams ?? []).filter(t => t.name.toLowerCase().includes(term) && !granted.has(`team:${t.id}`)).map(t => ({ kind: "team" as const, id: t.id, name: t.name, sub: "Team", color: t.color })),
    ...(d.members ?? []).filter(m => (m.name.toLowerCase().includes(term) || m.email.includes(term)) && !granted.has(`user:${m.user_id}`) && m.user_id !== d.project.created_by)
      .map(m => ({ kind: "user" as const, id: m.user_id, name: m.name, sub: m.email, color: null })),
  ].slice(0, 6);
  const isEmail = /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(who.trim());

  const add = async (s: { kind: "user" | "team"; id: string; name: string }) => {
    setBusy(true);
    try { await api.post(`/api/projects/${projectId}/grants`, { subject_type: s.kind, subject_id: s.id, level }); toast.success(`Shared with ${s.name}`); setWho(""); refresh(); }
    catch (e) { err(e); } finally { setBusy(false); }
  };
  const inviteEmail = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ invited: boolean; guest: boolean }>(`/api/projects/${projectId}/guests`, { email: who.trim(), level });
      toast.success(r.invited ? `Invitation sent to ${who.trim()} (guest: this project only)` : `Shared with ${who.trim()}`); setWho(""); refresh();
    } catch (e) { err(e); } finally { setBusy(false); }
  };
  const copy = async (url: string, id: string) => {
    try { await navigator.clipboard.writeText(url); } catch { /* clipboard blocked: the field is selectable */ }
    setCopied(id); setTimeout(() => setCopied(null), 1500);
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title={<span className="flex items-center gap-2"><Users className="h-4 w-4 text-primary" />Share “{d?.project.name ?? "…"}”</span>}
      description="People and teams you add get access to this part only. Guests outside your workspace don't take a seat.">
      {!d ? <div className="py-6 text-center text-sm text-muted">Loading…</div> : (
        <div className="space-y-5">
          {admin && (
            <div className="relative">
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <UserPlus className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                  <Input value={who} onChange={e => setWho(e.target.value)} placeholder="Add people, teams or an email address" className="pl-9" aria-label="Add people or teams"
                    onKeyDown={e => { if (e.key === "Enter") { if (suggestions[0]) void add(suggestions[0]); else if (isEmail) void inviteEmail(); } }} />
                </div>
                <LevelSelect value={level} onChange={setLevel} label="Access to give" />
                {isEmail && !suggestions.length && <Button size="sm" icon={<Mail className="h-4 w-4" />} loading={busy} onClick={inviteEmail}>Invite</Button>}
              </div>
              {suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-border bg-panel shadow-pop" role="listbox">
                  {suggestions.map(s => (
                    <button key={`${s.kind}:${s.id}`} onClick={() => add(s)} disabled={busy} className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] hover:bg-primary-soft" role="option">
                      {s.kind === "team" ? <span className="flex h-7 w-7 items-center justify-center rounded-md text-white" style={{ background: s.color ?? "#2563eb" }}><Users className="h-3.5 w-3.5" /></span> : <Avatar name={s.name} size={28} />}
                      <span className="min-w-0"><span className="block truncate font-medium">{s.name}</span><span className="block truncate text-[11.5px] text-muted">{s.sub}</span></span>
                    </button>))}
                </div>)}
              {term && !suggestions.length && !isEmail && <p className="mt-1.5 text-[12px] text-muted">No workspace member or team matches. Type a full email address to invite a guest.</p>}
            </div>)}

          <section>
            <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">People with access</h3>
            <ul className="divide-y divide-border rounded-lg border border-border">
              {d.owner && <li className="flex items-center gap-3 px-3 py-2.5"><Avatar name={d.owner.name} size={30} />
                <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{d.owner.name}</span><span className="block truncate text-[11.5px] text-muted">{d.owner.email}</span></span>
                <Badge>Owner</Badge></li>}
              {d.me.team && <li className="flex items-center gap-3 px-3 py-2.5">
                <span className="flex h-[30px] w-[30px] items-center justify-center rounded-md text-white" style={{ background: d.me.team.color }}><Users className="h-4 w-4" /></span>
                <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{d.me.team.name}</span><span className="block text-[11.5px] text-muted">Owning team: access by team role</span></span>
                <Badge tone="primary">Team</Badge></li>}
              {d.grants.map(g => (
                <li key={g.id} className="flex items-center gap-3 px-3 py-2.5">
                  {g.subject_type === "team" ? <span className="flex h-[30px] w-[30px] items-center justify-center rounded-md text-white" style={{ background: g.color ?? "#2563eb" }}><Users className="h-4 w-4" /></span> : <Avatar name={g.name} size={30} />}
                  <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{g.name}{g.guest && <Badge tone="accent" className="ml-1.5">Guest</Badge>}</span>
                    <span className="block truncate text-[11.5px] text-muted">{g.subject_type === "team" ? "Team" : g.email}</span></span>
                  {admin ? <>
                    <LevelSelect value={g.level} label={`Access for ${g.name}`} onChange={l => run(() => api.patch(`/api/projects/${projectId}/grants/${g.id}`, { level: l }), `${g.name} can now ${l === "read" ? "view" : l}`)} />
                    <button onClick={() => run(() => api.del(`/api/projects/${projectId}/grants/${g.id}`), `Removed ${g.name}`)} className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-danger" aria-label={`Remove ${g.name}`}><Trash2 className="h-4 w-4" /></button>
                  </> : <Badge>{LEVEL_TEXT[g.level]}</Badge>}
                </li>))}
              {(d.pending_guests ?? []).map(i => (
                <li key={i.id} className="flex items-center gap-3 bg-panel2/40 px-3 py-2.5">
                  <span className="flex h-[30px] w-[30px] items-center justify-center rounded-full border border-dashed border-border"><Mail className="h-4 w-4 text-muted" /></span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{i.email}</span><span className="block text-[11.5px] text-muted">Guest invitation pending · expires {date(i.expires_at)}</span></span>
                  <Badge>{LEVEL_TEXT[i.level]}</Badge>
                  <button onClick={() => run(() => api.del(`/api/projects/${projectId}/guests/${i.id}`), "Invitation revoked")} className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-danger" aria-label="Revoke invitation"><Trash2 className="h-4 w-4" /></button>
                </li>))}
            </ul>
          </section>

          {d.members && (
            <section className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center gap-3">
                <Globe2 className="h-4 w-4 text-muted" />
                <div className="min-w-0 flex-1"><div className="text-[13px] font-medium">Everyone else in the workspace</div>
                  <div className="text-[11.5px] text-muted">{d.me.team ? "People outside the owning team" : "Workspace viewers can at most view and comment"}</div></div>
                {admin ? <LevelSelect value={d.me.general} levels={["none", "read", "comment", "edit"]} label="General access"
                  onChange={l => run(() => api.patch(`/api/projects/${projectId}/access`, { general: l }), l === "none" ? "Only people with access can open it" : "General access updated")} />
                  : <Badge>{d.me.general === "none" ? "No access" : LEVEL_TEXT[d.me.general]}</Badge>}
              </div>
              {admin && d.teams && d.teams.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
                  <Users className="h-4 w-4 text-muted" />
                  <div className="min-w-0 flex-1"><div className="text-[13px] font-medium">Owned by</div><div className="text-[11.5px] text-muted">A team project gives its members access by team role</div></div>
                  <select className="input h-8 w-auto py-0 pr-7 text-[12.5px]" aria-label="Owning team" value={d.me.team?.id ?? ""}
                    onChange={e => run(() => api.patch(`/api/projects/${projectId}/access`, e.target.value ? { team_id: e.target.value } : { personal: true }), e.target.value ? "Now a team project" : "Now a personal project")}>
                    <option value="">Personal (its creator)</option>
                    {d.teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>)}
              <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-border pt-3">
                <ShieldCheck className="h-4 w-4 text-muted" />
                <div className="min-w-0 flex-1"><div className="text-[13px] font-medium">Protect main</div>
                  <div className="text-[11.5px] text-muted">Changes reach main only through a merge request with {d.me.required_approvals} approval{d.me.required_approvals > 1 ? "s" : ""}</div></div>
                <Toggle checked={d.me.protected_main} disabled={!admin} label="Protect main"
                  onChange={v => run(() => api.patch(`/api/projects/${projectId}/access`, { protected_main: v }), v ? "Main is protected" : "Main is open for direct edits")} />
              </div>
            </section>)}

          {admin && (
            <section>
              <h3 className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted"><Link2 className="h-3.5 w-3.5" />Read-only links</h3>
              <p className="mb-2 text-[12px] text-muted">Anyone with a link can view the part (3D, parameters, checks, drawing) without signing in. They can't edit, download or use the design agent.</p>
              <div className="space-y-2">
                {(d.links ?? []).map(l => (
                  <div key={l.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2">
                    <Input readOnly value={l.url} className="h-8 min-w-0 flex-1 font-mono text-[11.5px]" onFocus={e => e.currentTarget.select()} aria-label="Share link" />
                    <span className="text-[11.5px] text-muted">{l.expired ? "Expired" : l.expires_at ? `Expires ${date(l.expires_at)}` : "No expiry"} · {l.uses} view{l.uses === 1 ? "" : "s"}</span>
                    <Button size="sm" variant="secondary" icon={copied === l.id ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} onClick={() => copy(l.url, l.id)}>{copied === l.id ? "Copied" : "Copy"}</Button>
                    <Button size="sm" variant="ghost" onClick={() => run(() => api.del(`/api/projects/${projectId}/share-links/${l.id}`), "Link turned off")}>Turn off</Button>
                  </div>))}
                <div className="flex items-center gap-2">
                  <select value={expiry} onChange={e => setExpiry(e.target.value)} className="input h-8 w-auto py-0 pr-7 text-[12.5px]" aria-label="Link expiry">
                    <option value="">No expiry</option><option value="1">Expires in 1 day</option><option value="7">Expires in 7 days</option><option value="30">Expires in 30 days</option>
                  </select>
                  <Button size="sm" variant="secondary" icon={<Link2 className="h-4 w-4" />} onClick={() => run(() => api.post(`/api/projects/${projectId}/share-links`, { expires_days: expiry ? Number(expiry) : null }), "Read-only link created")}>Create link</Button>
                </div>
              </div>
            </section>)}
          {!admin && <p className="flex items-center gap-2 rounded-lg bg-panel2 px-3 py-2 text-[12.5px] text-muted"><Lock className="h-4 w-4" />You have {LEVEL_TEXT[d.me.level].toLowerCase()} access. Only the project's admins can change sharing.</p>}
        </div>)}
    </Modal>
  );
}
