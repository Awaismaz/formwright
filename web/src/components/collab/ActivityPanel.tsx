import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CheckCircle2, CornerDownRight, GitBranch, Lock, MessageSquare, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { mentionSegments } from "@/lib/collab";
import { ago, cx } from "@/lib/format";
import { Avatar, Button } from "@/components/ui";

export interface CommentRow {
  id: string; body: string; author: { id: string | null; name: string }; branch: string; revision: number | null; mr_id: string | null;
  parent_id: string | null; resolved: boolean; created_at: string; mine: boolean;
}
interface CommentsData { items: CommentRow[]; people: { id: string; name: string }[]; can_comment: boolean }
interface ActivityRow { id: string; at: string; who: string; kind: string; text: string; branch: string | null }

function Body({ text, people }: { text: string; people: { id: string; name: string }[] }) {
  return <p className="whitespace-pre-wrap break-words text-[12.5px] leading-5">{mentionSegments(text, people).map((s, i) =>
    s.mention ? <span key={i} className="rounded bg-primary-soft px-0.5 font-medium text-primary">{s.text}</span> : <span key={i}>{s.text}</span>)}</p>;
}

/** A comment thread (project-wide, on a revision, or on a merge request) with @mentions. */
export function CommentThread({ projectId, mrId, revision, compact }: { projectId: string; mrId?: string; revision?: number; compact?: boolean }) {
  const qc = useQueryClient();
  const qs = mrId ? `?mr_id=${mrId}` : revision ? `?revision=${revision}` : "";
  const key = ["comments", projectId, mrId ?? revision ?? "project"];
  const q = useQuery({ queryKey: key, queryFn: () => api.get<CommentsData>(`/api/projects/${projectId}/comments${qs}`), refetchInterval: 20_000 });
  const [text, setText] = useState("");
  const [reply, setReply] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const people = q.data?.people ?? [];
  const at = /@(\w*)$/.exec(text);
  const picks = at ? people.filter(p => p.name.toLowerCase().startsWith(at[1]!.toLowerCase()) || p.name.split(/\s+/)[0]!.toLowerCase().startsWith(at[1]!.toLowerCase())).slice(0, 5) : [];
  const refresh = () => { qc.invalidateQueries({ queryKey: key }); qc.invalidateQueries({ queryKey: ["activity", projectId] }); qc.invalidateQueries({ queryKey: ["collab", projectId] }); };
  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await api.post(`/api/projects/${projectId}/comments`, { body: text, mr_id: mrId ?? null, revision: revision ?? null, parent_id: reply }); setText(""); setReply(null); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not post"); } finally { setBusy(false); }
  };
  const items = q.data?.items ?? [];
  const roots = items.filter(c => !c.parent_id);
  const kids = (id: string) => items.filter(c => c.parent_id === id);
  const row = (c: CommentRow, child = false) => (
    <li key={c.id} className={cx("flex gap-2.5", child && "ml-7", c.resolved && "opacity-60")} data-comment>
      <Avatar name={c.author.name} size={child ? 22 : 26} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-[11.5px]"><b className="text-[12.5px]">{c.author.name}</b><span className="text-muted">{ago(c.created_at)}</span>
          {c.revision && <span className="text-muted">on revision {c.revision}</span>}{c.branch !== "main" && <span className="inline-flex items-center gap-0.5 text-muted"><GitBranch className="h-3 w-3" />branch</span>}
          {c.resolved && <span className="text-success">resolved</span>}</div>
        <Body text={c.body} people={people} />
        {q.data?.can_comment && <div className="mt-0.5 flex gap-3 text-[11.5px] text-muted">
          {!child && <button className="hover:text-text" onClick={() => setReply(c.id)}>Reply</button>}
          {!child && <button className="hover:text-text" onClick={async () => { await api.patch(`/api/projects/${projectId}/comments/${c.id}`, { resolved: !c.resolved }); refresh(); }}>{c.resolved ? "Reopen" : "Resolve"}</button>}
          {c.mine && <button className="hover:text-danger" aria-label="Delete comment" onClick={async () => { await api.del(`/api/projects/${projectId}/comments/${c.id}`); refresh(); }}><Trash2 className="inline h-3 w-3" /></button>}
        </div>}
      </div>
    </li>);
  return (
    <div className={cx("space-y-3", compact ? "" : "p-3")}>
      {roots.length === 0 ? <p className="text-[12.5px] text-muted">No comments yet.{q.data?.can_comment ? " Use @name to notify a teammate." : ""}</p>
        : <ul className="space-y-3">{roots.map(c => <div key={c.id} className="space-y-2">{row(c)}{kids(c.id).map(k => row(k, true))}</div>)}</ul>}
      {q.data?.can_comment ? (
        <div className="relative">
          {reply && <div className="mb-1 flex items-center gap-1 text-[11.5px] text-muted"><CornerDownRight className="h-3 w-3" />Replying<button className="ml-1 underline" onClick={() => setReply(null)}>cancel</button></div>}
          <textarea value={text} onChange={e => setText(e.target.value)} placeholder={mrId ? "Comment on this merge request… (@ to mention)" : "Comment… (@ to mention)"}
            onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send(); }} className="input min-h-[64px] w-full text-[12.5px]" aria-label="Comment" />
          {picks.length > 0 && <div className="absolute bottom-full z-10 mb-1 w-56 overflow-hidden rounded-lg border border-border bg-panel shadow-pop">
            {picks.map(p => <button key={p.id} className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] hover:bg-primary-soft"
              onClick={() => setText(t => t.replace(/@(\w*)$/, `@${p.name.split(/\s+/)[0]} `))}><Avatar name={p.name} size={20} />{p.name}</button>)}</div>}
          <div className="mt-1.5 flex justify-end"><Button size="sm" icon={<Send className="h-3.5 w-3.5" />} loading={busy} disabled={!text.trim()} onClick={send}>Comment</Button></div>
        </div>
      ) : <p className="flex items-center gap-1.5 text-[12px] text-muted"><Lock className="h-3.5 w-3.5" />You can view comments; commenting needs comment access.</p>}
    </div>
  );
}

const ICON: Record<string, JSX.Element> = { "comment.added": <MessageSquare className="h-3.5 w-3.5" />, "mr.merged": <CheckCircle2 className="h-3.5 w-3.5 text-success" />,
  "branch.created": <GitBranch className="h-3.5 w-3.5" /> };

/** Studio side tab: comments on the part and who changed what (agent runs, parameters, features, merges). */
export default function ActivityPanel({ projectId }: { projectId: string }) {
  const [view, setView] = useState<"comments" | "activity">("comments");
  const feed = useQuery({ queryKey: ["activity", projectId], enabled: view === "activity", refetchInterval: 20_000,
    queryFn: () => api.get<{ items: ActivityRow[] }>(`/api/projects/${projectId}/activity`) });
  return (
    <div data-activity-panel>
      <div className="flex gap-1 border-b border-border px-3 py-2 text-[12px]">
        {(["comments", "activity"] as const).map(v => <button key={v} onClick={() => setView(v)} className={cx("rounded px-2 py-0.5 capitalize", view === v ? "bg-primary-soft font-semibold text-primary" : "text-muted hover:text-text")}>{v}</button>)}
      </div>
      {view === "comments" ? <CommentThread projectId={projectId} /> : (
        <ul className="divide-y divide-border">
          {(feed.data?.items ?? []).map(a => (
            <li key={a.id} className="flex gap-2 px-3 py-2 text-[12.5px]">
              <span className="mt-0.5 text-muted">{ICON[a.kind] ?? <Activity className="h-3.5 w-3.5" />}</span>
              <span className="min-w-0 flex-1"><b>{a.who}</b> {a.text}
                <span className="block text-[11px] text-muted">{ago(a.at)}{a.branch && a.branch !== "main" ? ` · on ${a.branch}` : ""}</span></span>
            </li>))}
          {feed.data && !feed.data.items.length && <li className="p-3 text-[12.5px] text-muted">Nothing yet.</li>}
        </ul>)}
    </div>
  );
}
