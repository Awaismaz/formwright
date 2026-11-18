import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Bot, CheckCircle2, CircleAlert, CircleX, GitBranch, GitCompare, GitMerge, GitPullRequest, Loader2, Lock, ShieldCheck, ThumbsUp, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { featureText, fmtNum, paramRows, readyToMerge, type Choice, type FeatureChange, type ParamDiff } from "@/lib/collab";
import { ago, cx, num, PAGE } from "@/lib/format";
import { Badge, Button, Card, EmptyState, PageHeader, PageLoader } from "@/components/ui";
import Viewer3D, { type Tool } from "@/components/Viewer3D";
import type { Pick, Topo } from "@/viewer/types";
import { CommentThread } from "@/components/collab/ActivityPanel";

interface Conflict {
  id: string; kind: "param" | "feature" | "source"; key: string; label?: string; unit?: string | null;
  base?: unknown; ours?: unknown; theirs?: unknown; ours_changes?: string[]; theirs_changes?: string[];
  code?: { base: string; ours: string; theirs: string };
}
interface MR {
  id: string; number: number; title: string; description: string; status: "open" | "merged" | "closed"; created_at: string;
  author: { id: string; name: string }; merged_by: string | null; merged_at: string | null; merge_rev: number | null;
  branch: { id: string; name: string; status: string; base_rev: number | null; head: { revision: number | null } | null };
  main: { head: { revision: number | null } }; fast_forward: boolean;
  params: { branch: ParamDiff; main: ParamDiff; meta: Record<string, { label?: string | null; unit?: string | null }> };
  features: { branch: FeatureChange[]; main: FeatureChange[] };
  changes: { branch: { n: number; why: string | null; by: string | null }[]; main: { n: number; why: string | null; by: string | null }[] };
  conflicts: Conflict[]; checks: { ok: boolean | null; items: { id: string; name: string; passed: boolean; gating: boolean }[] };
  reviews: { id: string; user: { id: string; name: string }; state: string; body: string; created_at: string }[];
  approvals: number; required_approvals: number; protected_main: boolean; changes_requested: boolean;
  reconcile: { note: string | null; tokens: number | null; ids: string[] }; can_merge: boolean; blockers: string[]; can_review: boolean; can_approve: boolean;
}

const STATUS = { open: { tone: "primary" as const, icon: <GitPullRequest className="h-3 w-3" />, text: "Open" },
  merged: { tone: "success" as const, icon: <GitMerge className="h-3 w-3" />, text: "Merged" }, closed: { tone: "neutral" as const, icon: <CircleX className="h-3 w-3" />, text: "Closed" } };

export function MergeRequestList() {
  const { id = "" } = useParams();
  const q = useQuery({ queryKey: ["mrs", id], queryFn: () => api.get<{ items: { id: string; number: number; title: string; status: "open" | "merged" | "closed"; branch: { name: string }; author: string; created_at: string }[] }>(`/api/projects/${id}/merge-requests`) });
  const p = useQuery({ queryKey: ["project", id], queryFn: () => api.get<{ name: string }>(`/api/projects/${id}`) });
  if (!q.data) return <PageLoader />;
  return (
    <div className={PAGE}>
      <PageHeader eyebrow={<Link to={`/app/projects/${id}`} className="inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-text"><ArrowLeft className="h-3.5 w-3.5" />{p.data?.name ?? "Back to the part"}</Link>}
        title="Merge requests" subtitle="Changes made on branches, reviewed before they reach main." />
      {!q.data.items.length ? <EmptyState icon={<GitPullRequest className="h-6 w-6" />} title="No merge requests yet" body="Work on a copy from the branch picker in the Studio, then open a merge request to bring it into main." />
        : <Card className="divide-y divide-border">{q.data.items.map(m => (
          <Link key={m.id} to={`/app/projects/${id}/merge/${m.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-panel2/60">
            <Badge tone={STATUS[m.status].tone}>{STATUS[m.status].icon}{STATUS[m.status].text}</Badge>
            <span className="min-w-0 flex-1"><span className="block truncate font-medium">!{m.number} {m.title}</span>
              <span className="block text-[12px] text-muted"><GitBranch className="inline h-3 w-3" /> {m.branch.name} → main · {m.author} · {ago(m.created_at)}</span></span>
          </Link>))}</Card>}
    </div>
  );
}

function Val({ v, unit }: { v: unknown; unit?: string | null }) {
  if (v === null || v === undefined) return <span className="text-muted">(removed)</span>;
  if (typeof v === "number") return <span className="tabular-nums">{fmtNum(v, unit)}</span>;
  if (typeof v === "object" && v && "name" in v) { const f = v as { name: string; op: string; suppressed: boolean }; return <span>{f.name}{f.suppressed ? " (suppressed)" : ""}</span>; }
  return <span>{String(v)}</span>;
}

export default function MergeRequestPage() {
  const { id = "", mid = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["mr", id, mid], queryFn: () => api.get<MR>(`/api/projects/${id}/merge-requests/${mid}`), refetchInterval: 30_000 });
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [cmp, setCmp] = useState<{ added: Topo | null; removed: Topo | null; added_mm3: number; removed_mm3: number; main_topo: string } | null>(null);
  const [cmpBusy, setCmpBusy] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>("orbit");
  const [sel, setSel] = useState<Pick[]>([]);
  const [showCode, setShowCode] = useState(false);
  const [note, setNote] = useState("");
  const mr = q.data;
  const rows = useMemo(() => (mr ? paramRows(mr.params.branch, mr.params.main, mr.params.meta) : []), [mr]);
  if (q.isLoading) return <PageLoader />;
  if (!mr) return <div className={PAGE}><EmptyState icon={<GitPullRequest className="h-6 w-6" />} title="Merge request not found" /></div>;
  const refresh = () => { qc.invalidateQueries({ queryKey: ["mr", id, mid] }); qc.invalidateQueries({ queryKey: ["collab", id] }); };
  const act = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    try { await fn(); toast.success(ok); refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(null); }
  };
  const compare = async () => {
    setCmpBusy(true);
    try {
      const r = await api.post<{ added_url: string | null; removed_url: string | null; added_mm3: number; removed_mm3: number; main_topo: string }>(`/api/projects/${id}/merge-requests/${mid}/compare`);
      const load = (u: string | null) => (u ? fetch(u).then(x => x.json() as Promise<Topo>) : Promise.resolve(null));
      const [added, removed] = await Promise.all([load(r.added_url), load(r.removed_url)]);
      setCmp({ added, removed, added_mm3: r.added_mm3, removed_mm3: r.removed_mm3, main_topo: r.main_topo });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Compare failed"); } finally { setCmpBusy(false); }
  };
  const ready = readyToMerge(mr.conflicts, choices, mr.reconcile.ids);
  const merge = async () => {
    setBusy("merge");
    try {
      const r = await api.post<{ revision: number; fast_forward: boolean }>(`/api/projects/${id}/merge-requests/${mid}/merge`, { resolutions: choices });
      toast.success(`Merged into main as revision ${r.revision}${r.fast_forward ? " (fast-forward)" : ""}. Rebuilt and checked.`);
      await qc.invalidateQueries(); nav(`/app/projects/${id}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Merge failed", { duration: 9000 }); refresh(); } finally { setBusy(null); }
  };
  const st = STATUS[mr.status];
  const changedB = Object.keys(mr.params.branch).length + mr.features.branch.length;

  return (
    <div className={PAGE}>
      <PageHeader eyebrow={<Link to={`/app/projects/${id}`} className="inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-text"><ArrowLeft className="h-3.5 w-3.5" />Back to the Studio</Link>}
        title={<span className="flex flex-wrap items-center gap-2">!{mr.number} {mr.title}<Badge tone={st.tone}>{st.icon}{st.text}</Badge></span>}
        subtitle={<span className="flex flex-wrap items-center gap-1.5"><span className="inline-flex items-center gap-1 rounded bg-primary-soft px-1.5 font-medium text-primary"><GitBranch className="h-3 w-3" />{mr.branch.name}</span>
          <ArrowRight className="h-3.5 w-3.5" /><span className="rounded bg-text/[.06] px-1.5 font-medium">main</span>
          <span>· opened by {mr.author.name} {ago(mr.created_at)}</span>
          {mr.status === "open" && <span>· {mr.fast_forward ? "main hasn't moved: fast-forward" : `main moved since the branch started: 3-way merge`}</span>}
          {mr.merged_by && <span>· merged by {mr.merged_by} as revision {mr.merge_rev}</span>}</span>} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-5">
          {mr.description && <Card className="p-4 text-[13px] leading-5">{mr.description}</Card>}
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <h2 className="flex items-center gap-1.5 text-[13.5px] font-semibold"><GitCompare className="h-4 w-4 text-primary" />3D difference: main → branch</h2>
              <Button size="sm" variant="secondary" loading={cmpBusy} onClick={compare} disabled={mr.status !== "open"}>{cmp ? "Refresh" : "Compare in 3D"}</Button>
            </div>
            <div className="relative h-[340px]" data-mr-viewer>
              {cmp ? <Viewer3D topoUrl={cmp.main_topo} version={mid} tool={tool} onToolChange={setTool} selection={sel} onSelectionChange={setSel} compare={{ added: cmp.added, removed: cmp.removed }} />
                : <div className="flex h-full items-center justify-center text-center text-[13px] text-muted">{cmpBusy ? <Loader2 className="h-6 w-6 animate-spin text-primary" /> : mr.status === "open" ? "Compare main's part with the branch: added material in green, removed in red." : "This merge request is no longer open."}</div>}
              {cmp && <div className="absolute right-3 top-3 w-48 rounded-lg border border-border bg-panel/95 p-2.5 text-[12px] shadow-card">
                <div className="flex justify-between"><span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-[#22a85a]" />Added</span><span className="tabular-nums">{num(cmp.added_mm3, 1)} mm³</span></div>
                <div className="flex justify-between"><span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-[#d8402f]" />Removed</span><span className="tabular-nums">{num(cmp.removed_mm3, 1)} mm³</span></div></div>}
            </div>
          </Card>

          <Card className="p-4">
            <h2 className="mb-2 text-[13.5px] font-semibold">Parameters</h2>
            {!rows.length ? <p className="text-[12.5px] text-muted">No parameter changed on either side.</p> : (
              <table className="w-full text-[12.5px]" data-param-diff>
                <thead className="text-left text-[11.5px] text-muted"><tr><th className="py-1 font-medium">Parameter</th><th className="font-medium">At branch start</th><th className="font-medium">Main now</th><th className="font-medium">Branch</th></tr></thead>
                <tbody className="divide-y divide-border">{rows.map(r => (
                  <tr key={r.key} className={cx(r.conflict && "bg-warning/10")}>
                    <td className="py-1.5 font-medium">{r.label}{r.conflict && <Badge tone="warning" className="ml-1.5">conflict</Badge>}</td>
                    <td className="tabular-nums text-muted">{fmtNum(r.base, r.unit)}</td>
                    <td className={cx("tabular-nums", r.changedOnMain && "font-semibold")}>{fmtNum(r.main, r.unit)}</td>
                    <td className={cx("tabular-nums", r.changedOnBranch && "font-semibold text-primary")}>{fmtNum(r.branch, r.unit)}</td></tr>))}</tbody>
              </table>)}
          </Card>

          <div className="grid gap-5 md:grid-cols-2">
            <Card className="p-4"><h2 className="mb-2 text-[13.5px] font-semibold">Changes on {mr.branch.name}</h2>
              <ul className="space-y-1 text-[12.5px]">
                {mr.features.branch.map(f => <li key={f.id}>• {featureText(f)}</li>)}
                {mr.changes.branch.map(c => <li key={c.n} className="text-muted">r{c.n} · {c.why ?? "change"}{c.by ? ` · ${c.by}` : ""}</li>)}
                {!changedB && !mr.changes.branch.length && <li className="text-muted">No changes yet.</li>}
              </ul></Card>
            <Card className="p-4"><h2 className="mb-2 text-[13.5px] font-semibold">Changes on main since</h2>
              <ul className="space-y-1 text-[12.5px]">
                {mr.features.main.map(f => <li key={f.id}>• {featureText(f)}</li>)}
                {mr.changes.main.map(c => <li key={c.n} className="text-muted">r{c.n} · {c.why ?? "change"}{c.by ? ` · ${c.by}` : ""}</li>)}
                {mr.fast_forward && <li className="text-muted">None: main hasn't moved.</li>}
              </ul></Card>
          </div>

          {mr.conflicts.length > 0 && mr.status === "open" && (
            <Card className="border-warning/40 p-4" data-conflicts>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <CircleAlert className="h-4 w-4 text-warning" /><h2 className="text-[13.5px] font-semibold">{mr.conflicts.length} conflict{mr.conflicts.length > 1 ? "s" : ""}: both sides changed the same thing</h2>
                <Button size="sm" variant="secondary" className="ml-auto" icon={<Bot className="h-4 w-4" />} loading={busy === "agent"}
                  onClick={() => act("agent", () => api.post(`/api/projects/${id}/merge-requests/${mid}/reconcile`), "The design agent proposed a resolution")}>Ask the design agent to reconcile</Button>
              </div>
              {mr.reconcile.note && <p className="mb-3 rounded-lg bg-primary-soft px-3 py-2 text-[12.5px]"><Bot className="mr-1 inline h-3.5 w-3.5" />{mr.reconcile.note}{mr.reconcile.tokens ? ` · ${mr.reconcile.tokens} tokens` : ""}</p>}
              <div className="space-y-3">
                {mr.conflicts.map(c => (
                  <div key={c.id} className="rounded-lg border border-border p-3" data-conflict={c.id}>
                    <div className="mb-2 text-[12.5px] font-semibold">{c.label ?? c.key}{c.kind === "param" && <span className="ml-1.5 font-normal text-muted">was <Val v={c.base} unit={c.unit} /></span>}</div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {(["ours", "theirs"] as const).map(side => (
                        <label key={side} className={cx("cursor-pointer rounded-lg border p-2.5 text-[12.5px]", choices[c.id] === side ? "border-primary bg-primary-soft" : "border-border hover:border-primary/50")}>
                          <input type="radio" className="mr-1.5" name={c.id} checked={choices[c.id] === side} onChange={() => setChoices(s => ({ ...s, [c.id]: side }))} />
                          <b>Take {side === "ours" ? "main's" : "the branch's"}</b>
                          <div className="mt-1">{c.kind === "source" ? <ul className="space-y-0.5 text-[12px] text-muted">{((side === "ours" ? c.ours_changes : c.theirs_changes) ?? []).map((w, i) => <li key={i}>• {w}</li>)}</ul> : <Val v={side === "ours" ? c.ours : c.theirs} unit={c.unit} />}</div>
                        </label>))}
                    </div>
                    {mr.reconcile.ids.includes(c.id) && (
                      <label className={cx("mt-2 flex cursor-pointer items-center gap-1.5 rounded-lg border p-2.5 text-[12.5px]", choices[c.id] === "agent" ? "border-primary bg-primary-soft" : "border-border")}>
                        <input type="radio" name={c.id} checked={choices[c.id] === "agent"} onChange={() => setChoices(s => ({ ...s, [c.id]: "agent" }))} /><Bot className="h-3.5 w-3.5" /><b>Use the design agent's proposal</b></label>)}
                    {c.code && <button className="mt-2 text-[11.5px] text-muted underline" onClick={() => setShowCode(v => !v)}>{showCode ? "Hide" : "Show"} the script lines (support view)</button>}
                    {c.code && showCode && <div className="mt-2 grid gap-2 text-[11px] sm:grid-cols-2"><pre className="overflow-x-auto rounded bg-panel2 p-2">{c.code.ours}</pre><pre className="overflow-x-auto rounded bg-panel2 p-2">{c.code.theirs}</pre></div>}
                  </div>))}
              </div>
            </Card>)}
          <Card className="p-4"><h2 className="mb-2 text-[13.5px] font-semibold">Discussion</h2><CommentThread projectId={id} mrId={mid} compact /></Card>
        </div>

        <aside className="space-y-4">
          <Card className="p-4" data-checks>
            <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold">{mr.checks.ok ? <CheckCircle2 className="h-4 w-4 text-success" /> : <CircleAlert className="h-4 w-4 text-danger" />}Branch checks</h3>
            <ul className="space-y-1 text-[12px]">{mr.checks.items.filter(c => c.gating).map(c => <li key={c.id} className="flex items-center gap-1.5">{c.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <CircleX className="h-3.5 w-3.5 text-danger" />}{c.name}</li>)}
              {!mr.checks.items.length && <li className="text-muted">The branch has no build yet.</li>}</ul>
            <p className="mt-2 text-[11.5px] text-muted">After merging, main is rebuilt and must pass the gating checks, or the merge is refused and main stays as it was.</p>
          </Card>
          <Card className="p-4" data-reviews>
            <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold">{mr.protected_main ? <ShieldCheck className="h-4 w-4 text-success" /> : <ThumbsUp className="h-4 w-4 text-primary" />}Review
              <span className="ml-auto text-[12px] font-normal text-muted">{mr.approvals}{mr.protected_main ? ` / ${mr.required_approvals}` : ""} approval{mr.approvals === 1 ? "" : "s"}</span></h3>
            <ul className="mb-3 space-y-1.5 text-[12px]">{mr.reviews.filter(r => r.state !== "commented").map(r => <li key={r.id} className="flex items-center gap-1.5">
              {r.state === "approved" ? <ThumbsUp className="h-3.5 w-3.5 text-success" /> : <Undo2 className="h-3.5 w-3.5 text-warning" />}<b>{r.user.name}</b>{r.state === "approved" ? "approved" : "requested changes"}<span className="ml-auto text-muted">{ago(r.created_at)}</span></li>)}
              {!mr.reviews.some(r => r.state !== "commented") && <li className="text-muted">No reviews yet.</li>}</ul>
            {mr.status === "open" && mr.can_review && <>
              <textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Review note (needed to request changes; @ to mention)" className="input mb-2 min-h-[56px] w-full text-[12.5px]" aria-label="Review note" />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" icon={<ThumbsUp className="h-3.5 w-3.5" />} disabled={!mr.can_approve} loading={busy === "approve"}
                  title={mr.can_approve ? undefined : "You can't approve your own merge request, and approving needs edit access"}
                  onClick={() => act("approve", async () => { await api.post(`/api/projects/${id}/merge-requests/${mid}/reviews`, { state: "approve", body: note }); setNote(""); }, "Approved")}>Approve</Button>
                <Button size="sm" variant="ghost" icon={<Undo2 className="h-3.5 w-3.5" />} disabled={!note.trim()} loading={busy === "changes"} title={note.trim() ? undefined : "Write what needs to change first"}
                  onClick={() => act("changes", async () => { await api.post(`/api/projects/${id}/merge-requests/${mid}/reviews`, { state: "request_changes", body: note }); setNote(""); }, "Changes requested")}>Request changes</Button>
              </div></>}
          </Card>
          {mr.status === "open" && (
            <Card className="p-4" data-merge-card>
              <Button className="w-full" icon={<GitMerge className="h-4 w-4" />} disabled={!mr.can_merge || !ready} loading={busy === "merge"} onClick={merge}>
                {mr.fast_forward ? "Merge (fast-forward)" : "Merge into main"}</Button>
              {(mr.blockers.length > 0 || !ready) && <ul className="mt-2 space-y-1 text-[12px] text-muted">
                {mr.blockers.map(b => <li key={b} className="flex gap-1.5"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />{b}</li>)}
                {!ready && <li className="flex gap-1.5"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />Choose a side for every conflict.</li>}</ul>}
              <button className="mt-3 text-[12px] text-muted underline hover:text-text" onClick={() => act("close", () => api.post(`/api/projects/${id}/merge-requests/${mid}/close`), "Merge request closed")}>Close without merging</button>
            </Card>)}
        </aside>
      </div>
    </div>
  );
}
