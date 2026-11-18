import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, GitBranch, GitMerge, GitPullRequest, Lock, Plus, Share2, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { blockingLock, can, initials, lockText, presenceRows, whyNot, type BranchInfo, type CollabState, type PresenceUser } from "@/lib/collab";
import { ago, cx } from "@/lib/format";
import { Badge, Button, Field, Input, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Modal, Tip } from "@/components/ui";
import ShareDialog from "./ShareDialog";

const hue = (s: string) => [...s].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;

function Face({ u, ring }: { u: PresenceUser; ring?: boolean }) {
  return <span className={cx("inline-flex h-6 w-6 items-center justify-center rounded-full border-2 text-[9.5px] font-semibold text-white", ring ? "border-warning" : "border-panel2")}
    style={{ background: `hsl(${hue(u.name)} 45% 45%)` }}>{initials(u.name)}</span>;
}

/** Live presence over server-sent events (falls back to the polled snapshot). */
export function usePresence(projectId: string, branch: string, initial?: CollabState) {
  const [state, setState] = useState<Pick<CollabState, "users" | "locks"> | null>(null);
  useEffect(() => {
    if (!projectId) return;
    const es = new EventSource(`/api/projects/${projectId}/presence/stream`);
    es.onmessage = m => { try { const ev = JSON.parse(m.data); if (ev.type === "presence") setState({ users: ev.users, locks: ev.locks }); } catch { /* ignore */ } };
    return () => es.close();
  }, [projectId, branch]);
  return state ?? (initial ? { users: initial.users, locks: initial.locks } : { users: [], locks: [] });
}

export function useCollab(projectId: string) {
  return useQuery({ queryKey: ["collab", projectId], queryFn: () => api.get<CollabState>(`/api/projects/${projectId}/collab`), refetchInterval: 20_000 });
}

/** Branch picker, presence avatars, merge requests and Share: lives in the CommandManager tab row. */
export default function CollabBar({ projectId, onSwitched }: { projectId: string; onSwitched: () => void }) {
  const { me } = useSession();
  const myId = me?.user?.id;
  const qc = useQueryClient();
  const nav = useNavigate();
  const collab = useCollab(projectId);
  const branchQ = useQuery({ queryKey: ["branches", projectId], queryFn: () => api.get<{ current: string; items: BranchInfo[] }>(`/api/projects/${projectId}/branches`) });
  const cur = collab.data?.branch ?? { id: "main", name: "main" };
  const live = usePresence(projectId, cur.id, collab.data);
  const [share, setShare] = useState(false);
  const [newBranch, setNewBranch] = useState(false);
  const [mrOpen, setMrOpen] = useState(false);
  const access = collab.data?.access;
  const refreshAll = () => { qc.invalidateQueries(); onSwitched(); };
  const checkout = async (id: string, name: string) => {
    try { await api.post(`/api/projects/${projectId}/branches/${id}/checkout`); toast.success(`Switched to ${name}`); refreshAll(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not switch branch"); }
  };
  const { shown, more } = presenceRows(live.users, myId);
  const branches = branchQ.data?.items ?? [];
  const curInfo = branches.find(b => b.id === cur.id);
  const mrForBranch = collab.data?.open_merge_requests.find(m => m.branch_id === cur.id);

  return (
    <div className="flex min-w-0 items-center gap-1.5" data-collab-bar>
      <Menu>
        <Tip content="Branch: work on a copy, switch, or merge" side="bottom">
          <MenuTrigger asChild>
            <button className={cx("inline-flex h-6 max-w-[180px] items-center gap-1 rounded border px-1.5 text-[12px] font-medium",
              cur.id === "main" ? "border-border text-text hover:border-primary" : "border-primary/50 bg-primary-soft text-primary")} data-branch-picker aria-label="Branch">
              <GitBranch className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{cur.name}</span>
              {cur.id === "main" && access?.protected_main && <ShieldCheck className="h-3 w-3 shrink-0 text-success" aria-label="Protected" />}
              <ChevronDown className="h-3 w-3 shrink-0 opacity-60" /></button>
          </MenuTrigger>
        </Tip>
        <MenuContent align="start" className="w-72">
          <MenuLabel>Branches</MenuLabel>
          {branches.filter(b => b.status === "open").map(b => (
            <MenuItem key={b.id} onSelect={() => b.id !== cur.id && checkout(b.id, b.name)}>
              <span className="flex min-w-0 flex-1 items-center gap-2">
                {b.id === cur.id ? <Check className="h-3.5 w-3.5 text-primary" /> : <GitBranch className="h-3.5 w-3.5 text-muted" />}
                <span className="truncate">{b.name}</span>
                {b.lock && <Lock className="h-3 w-3 text-warning" aria-label={lockText(b.lock, myId)} />}
                {b.merge_request?.status === "open" && <Badge tone="primary" className="ml-auto">!{b.merge_request.number}</Badge>}
                {b.head?.revision ? <span className="ml-auto text-[11px] text-muted">r{b.head.revision}</span> : null}
              </span>
            </MenuItem>))}
          <MenuSeparator />
          <MenuItem icon={<Plus />} onSelect={() => setNewBranch(true)}>Work on a copy (new branch)…</MenuItem>
          {cur.id !== "main" && !mrForBranch && <MenuItem icon={<GitPullRequest />} onSelect={() => setMrOpen(true)}>Open a merge request…</MenuItem>}
          {mrForBranch && <MenuItem icon={<GitMerge />} onSelect={() => nav(`/app/projects/${projectId}/merge/${mrForBranch.id}`)}>View merge request !{mrForBranch.number}</MenuItem>}
          <MenuItem icon={<GitPullRequest />} onSelect={() => nav(`/app/projects/${projectId}/merge`)}>All merge requests{collab.data?.open_merge_requests.length ? ` (${collab.data.open_merge_requests.length} open)` : ""}</MenuItem>
          {cur.id !== "main" && curInfo && (curInfo.created_by === me?.user?.name || access?.can_admin) && <><MenuSeparator />
            <MenuItem icon={<Trash2 />} danger onSelect={async () => {
              try { await api.del(`/api/projects/${projectId}/branches/${cur.id}`); toast.success(`Deleted ${cur.name}`); refreshAll(); }
              catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not delete"); }
            }}>Delete this branch</MenuItem></>}
        </MenuContent>
      </Menu>
      {shown.length > 0 && (
        <div className="flex -space-x-1.5" data-presence>
          {shown.map(u => (
            <Tip key={u.user_id} side="bottom" content={u.editing ? lockText(u.editing, myId) : `${u.name} is viewing ${(u.branch_names ?? u.branches).join(", ")} · since ${ago(u.since)}`}>
              <span><Face u={u} ring={!!u.editing} /></span></Tip>))}
          {more > 0 && <span className="inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-panel2 bg-text/20 text-[9.5px] font-semibold">+{more}</span>}
        </div>)}
      <Tip content={can(access, "share") ? "Share with people, teams, guests or a read-only link" : "See who has access"} side="bottom">
        <button onClick={() => setShare(true)} className="inline-flex h-6 items-center gap-1 rounded px-1.5 text-[12px] font-medium text-muted hover:bg-text/5 hover:text-text" data-share-button>
          <Share2 className="h-3.5 w-3.5" />Share</button></Tip>
      {access && !can(access, "edit", cur.id) && (
        <Tip content={whyNot(access, "edit", cur.id) ?? ""} side="bottom">
          <span className="inline-flex h-6 items-center gap-1 rounded bg-text/[.06] px-1.5 text-[11.5px] font-medium text-muted" data-readonly-chip><Lock className="h-3 w-3" />{access.can_edit ? "Protected" : "View only"}</span></Tip>)}
      {share && <ShareDialog projectId={projectId} open onOpenChange={setShare} />}
      {newBranch && <NewBranchDialog projectId={projectId} from={cur} onClose={() => setNewBranch(false)} onDone={refreshAll} />}
      {mrOpen && <OpenMrDialog projectId={projectId} branch={cur} onClose={() => setMrOpen(false)} onDone={id => { qc.invalidateQueries({ queryKey: ["collab", projectId] }); nav(`/app/projects/${projectId}/merge/${id}`); }} />}
    </div>
  );
}

/** The banner over the viewer when someone else's run holds the branch, or main is protected. */
export function CollabBanner({ projectId, onBranch }: { projectId: string; onBranch: () => void }) {
  const { me } = useSession();
  const collab = useCollab(projectId);
  const cur = collab.data?.branch.id ?? "main";
  const live = usePresence(projectId, cur, collab.data);
  const lock = blockingLock(live.locks, cur, me?.user?.id);
  const protectedMain = cur === "main" && collab.data?.access.protected_main && collab.data.access.level !== "admin" && collab.data.access.can_edit;
  if (!lock && !protectedMain) return null;
  return (
    <div className="absolute left-1/2 top-14 z-10 flex max-w-[calc(100%-1.5rem)] -translate-x-1/2 items-center gap-2 rounded-full border border-warning/50 bg-panel/95 px-3 py-1.5 text-[12.5px] shadow-card" data-lock-banner>
      {lock ? <Lock className="h-4 w-4 shrink-0 text-warning" /> : <ShieldCheck className="h-4 w-4 shrink-0 text-success" />}
      <span>{lock ? <><b>{lockText(lock, me?.user?.id)}</b>. Your edits would collide.</> : <>Main is protected: changes go through a reviewed merge request.</>}</span>
      <button onClick={onBranch} className="rounded-full bg-primary px-2.5 py-0.5 font-medium text-white hover:brightness-110">Work on my own branch</button>
    </div>
  );
}

export function NewBranchDialog({ projectId, from, onClose, onDone }: { projectId: string; from: { id: string; name: string }; onClose: () => void; onDone: () => void }) {
  const { me } = useSession();
  const revs = useQuery({ queryKey: ["revisions", projectId, "branch-dialog", from.id], queryFn: () => api.get<{ items: { n: number; why?: string | null; ok: boolean }[] }>(`/api/projects/${projectId}/revisions`) });
  const first = (me?.user?.name ?? "me").split(/\s+/)[0]!.toLowerCase();
  const [name, setName] = useState(`${first}/change`);
  const [rev, setRev] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ name: string }>(`/api/projects/${projectId}/branches`, { name, from_branch: from.id, from_rev: rev ? Number(rev) : null });
      toast.success(`Working on “${r.name}”: your changes stay off ${from.name} until you merge`); onClose(); onDone();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create the branch"); } finally { setBusy(false); }
  };
  return (
    <Modal open onOpenChange={o => !o && onClose()} title="Work on a copy" description={`A branch is your own line of work on this part, started from ${from.name}. Merge it back with a merge request.`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button icon={<GitBranch className="h-4 w-4" />} loading={busy} disabled={!name.trim()} onClick={create}>Create and switch</Button></>}>
      <div className="space-y-4">
        <Field label="Branch name"><Input autoFocus value={name} onChange={e => setName(e.target.value)} maxLength={47} onKeyDown={e => e.key === "Enter" && create()} /></Field>
        <Field label="Start from" hint="The latest revision, or any earlier one">
          <select className="input" value={rev} onChange={e => setRev(e.target.value)} aria-label="Start from revision">
            <option value="">Current state of {from.name}</option>
            {(revs.data?.items ?? []).map(r => <option key={r.n} value={r.n}>Revision {r.n}{r.why ? ` · ${r.why.slice(0, 60)}` : ""}</option>)}
          </select></Field>
      </div>
    </Modal>
  );
}

function OpenMrDialog({ projectId, branch, onClose, onDone }: { projectId: string; branch: { id: string; name: string }; onClose: () => void; onDone: (id: string) => void }) {
  const [title, setTitle] = useState(() => { const t = branch.name.replace(/^[^/]+\//, "").replace(/[-_]/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); });
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try { const r = await api.post<{ id: string; number: number }>(`/api/projects/${projectId}/merge-requests`, { branch_id: branch.id, title, description: desc }); toast.success(`Merge request !${r.number} opened`); onClose(); onDone(r.id); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not open the merge request"); } finally { setBusy(false); }
  };
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={`Merge “${branch.name}” into main`} description="Reviewers see the 3D difference, parameter and feature changes, and the checks."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button icon={<GitPullRequest className="h-4 w-4" />} loading={busy} disabled={!title.trim()} onClick={open}>Open merge request</Button></>}>
      <div className="space-y-4">
        <Field label="Title"><Input autoFocus value={title} onChange={e => setTitle(e.target.value)} maxLength={160} /></Field>
        <Field label="What changed and why"><textarea className="input min-h-[96px]" value={desc} onChange={e => setDesc(e.target.value)} placeholder="e.g. Thicker plate for the new motor; mounting holes unchanged." /></Field>
      </div>
    </Modal>
  );
}
