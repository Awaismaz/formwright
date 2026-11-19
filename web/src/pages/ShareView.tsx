import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleX, Eye, History, Lock, SlidersHorizontal } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { fmtNum } from "@/lib/collab";
import { cx, num } from "@/lib/format";
import { Badge, Logo, PageLoader } from "@/components/ui";
import Viewer3D, { type Tool } from "@/components/Viewer3D";
import type { Pick } from "@/viewer/types";

interface Shared {
  project: { id: string; name: string; description: string; builds: number; updated_at: string }; workspace: string | null;
  status: { ok?: boolean; part?: string; material?: string; fingerprint?: { bbox: number[]; volume: number; faces: number }; build_id?: string;
    checks?: { id: string; name?: string; title?: string; passed: boolean; gating?: boolean }[]; mass?: { mass_g?: number } };
  params: { name: string; value: number; label?: string; unit?: string; group?: string }[];
  revisions: { n: number; why: string | null; kind: string | null; by: string | null }[];
  has_drawing: boolean; files: string[]; expires_at: string | null;
}

/** Public read-only viewer opened from a share link: 3D, parameters, checks, revisions and the drawing. No editing. */
export default function ShareView() {
  const { token = "" } = useParams();
  const q = useQuery({ queryKey: ["share", token], retry: false, queryFn: () => api.get<Shared>(`/api/share/${token}`) });
  const [tab, setTab] = useState<"params" | "checks" | "revs" | "drawing">("params");
  const [tool, setTool] = useState<Tool>("orbit");
  const [sel, setSel] = useState<Pick[]>([]);
  if (q.isLoading) return <PageLoader />;
  if (!q.data) {
    const msg = q.error instanceof ApiError ? q.error.message : "This link can't be opened.";
    return <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-bg p-6 text-center"><Logo /><Lock className="h-8 w-8 text-muted" /><h1 className="text-lg font-semibold">{msg}</h1>
      <p className="text-sm text-muted">Ask the person who shared it for a new link.</p></div>;
  }
  const d = q.data;
  const fp = d.status.fingerprint;
  const base = `/api/share/${token}/files`;
  const tabs: [typeof tab, string, JSX.Element][] = [["params", "Parameters", <SlidersHorizontal key="p" className="h-3.5 w-3.5" />], ["checks", "Checks", <CheckCircle2 key="c" className="h-3.5 w-3.5" />],
    ["revs", "Revisions", <History key="r" className="h-3.5 w-3.5" />], ...(d.has_drawing ? [["drawing", "Drawing", <Eye key="d" className="h-3.5 w-3.5" />] as [typeof tab, string, JSX.Element]] : [])];
  return (
    <div className="flex h-screen flex-col bg-bg text-text">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-panel px-4">
        <Link to="/" aria-label="Formwright"><Logo size={24} /></Link>
        <span className="h-5 w-px bg-border" />
        <span className="min-w-0 truncate font-semibold">{d.project.name}</span>
        {d.status.ok ? <Badge tone="success"><CheckCircle2 className="h-3 w-3" />Checks passed</Badge> : d.project.builds ? <Badge tone="danger">Checks failing</Badge> : <Badge>No build yet</Badge>}
        <Badge className="ml-auto"><Lock className="h-3 w-3" />View only</Badge>
        {d.workspace && <span className="hidden text-[12px] text-muted sm:inline">Shared by {d.workspace}</span>}
      </header>
      <div className="grid min-h-0 flex-1 md:grid-cols-[minmax(0,1fr)_340px]">
        <div className="relative min-h-[320px]">
          <Viewer3D topoUrl={d.files.includes("topo.json") ? `${base}/topo.json` : null} version={d.status.build_id} tool={tool} onToolChange={setTool} selection={sel} onSelectionChange={setSel}
            empty={<div className="text-sm text-muted">This part has no 3D model yet.</div>} />
        </div>
        <aside className="flex min-h-0 flex-col border-l border-border bg-panel">
          <div className="flex gap-1 border-b border-border px-2 py-1.5">{tabs.map(([v, l, icon]) => (
            <button key={v} onClick={() => setTab(v)} className={cx("inline-flex items-center gap-1 rounded px-2 py-1 text-[12px]", tab === v ? "bg-primary-soft font-semibold text-primary" : "text-muted hover:text-text")}>{icon}{l}</button>))}</div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 text-[12.5px]">
            {tab === "params" && (d.params.length ? <table className="w-full"><tbody className="divide-y divide-border">{d.params.map(p => (
              <tr key={p.name}><td className="py-1.5 text-muted">{p.label ?? p.name}</td><td className="py-1.5 text-right font-medium tabular-nums">{fmtNum(p.value, p.unit)}</td></tr>))}</tbody></table>
              : <p className="text-muted">No editable parameters.</p>)}
            {tab === "checks" && <ul className="space-y-1.5">{(d.status.checks ?? []).map(c => <li key={c.id} className="flex items-center gap-1.5">{c.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <CircleX className="h-3.5 w-3.5 text-danger" />}{c.name ?? c.title ?? c.id}</li>)}
              {!(d.status.checks ?? []).length && <li className="text-muted">No checks yet.</li>}</ul>}
            {tab === "revs" && <ul className="space-y-1.5">{d.revisions.map(r => <li key={r.n}><b>Revision {r.n}</b> <span className="text-muted">{r.why ?? ""}{r.by ? ` · ${r.by}` : ""}</span></li>)}</ul>}
            {tab === "drawing" && <img src={`${base}/drawing.svg`} alt="Drawing sheet" className="w-full rounded border border-border bg-white" />}
          </div>
          <div className="border-t border-border bg-panel2 px-3 py-2 text-[11.5px] text-muted">
            {fp ? <>{fp.bbox.map(n => n.toFixed(1)).join(" × ")} mm · {num(fp.volume, 0)} mm³{d.status.material ? ` · ${d.status.material}` : ""}</> : "n/a"}
            {d.expires_at && <div>Link expires {new Date(d.expires_at).toLocaleDateString()}</div>}
            <div className="mt-1">Geometry checks are deterministic; they don't certify a part for manufacture.</div>
          </div>
        </aside>
      </div>
    </div>
  );
}
