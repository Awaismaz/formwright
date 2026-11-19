import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleX, Eye, History, Lock, SlidersHorizontal } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { fmtNum } from "@/lib/collab";
import { num } from "@/lib/format";
import { PageLoader } from "@/components/ui";
import { Badge3D, Button3D, Card3D, SiteLogo, SiteScope, ThemeSwitch } from "@/components/landing/site";
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
    return (
      <SiteScope className="s-grid flex min-h-screen flex-col items-center justify-center p-6">
        <div className="w-full max-w-md">
          <Card3D screws inner="p-8 text-center">
            <Link to="/" aria-label="Formwright home" className="inline-block"><SiteLogo size={24} /></Link>
            <Lock className="mx-auto mt-8 h-9 w-9 text-ink2" strokeWidth={1.5} aria-hidden="true" />
            <h1 className="s-h2 mt-4 text-[24px] text-ink">{msg}</h1>
            <p className="mt-2 text-[15px] text-ink2">Ask the person who shared it for a new link.</p>
            <Button3D to="/" finish="steel" className="mt-7">Go to Formwright</Button3D>
          </Card3D>
        </div>
      </SiteScope>
    );
  }
  const d = q.data;
  const fp = d.status.fingerprint;
  const base = `/api/share/${token}/files`;
  const tabs: [typeof tab, string, JSX.Element][] = [["params", "Parameters", <SlidersHorizontal key="p" className="h-3.5 w-3.5" />], ["checks", "Checks", <CheckCircle2 key="c" className="h-3.5 w-3.5" />],
    ["revs", "Revisions", <History key="r" className="h-3.5 w-3.5" />], ...(d.has_drawing ? [["drawing", "Drawing", <Eye key="d" className="h-3.5 w-3.5" />] as [typeof tab, string, JSX.Element]] : [])];
  return (
    <SiteScope className="flex h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-ink/80 bg-sheet px-4">
        <Link to="/" aria-label="Formwright home" className="shrink-0"><SiteLogo size={22} /></Link>
        <span className="h-6 w-px bg-rule2" aria-hidden="true" />
        <h1 className="min-w-0 truncate text-[15px] font-semibold text-ink" style={{ fontFamily: "inherit", fontStretch: "normal", letterSpacing: 0 }}>{d.project.name}</h1>
        <span className="hidden sm:inline-flex">{d.status.ok ? <Badge3D tone="live">Checks passed</Badge3D> : d.project.builds ? <Badge3D tone="hi">Checks failing</Badge3D> : <Badge3D>No build yet</Badge3D>}</span>
        <span className="ml-auto flex items-center gap-3">{d.workspace && <span className="hidden text-[13px] text-ink2 md:inline">Shared by {d.workspace}</span>}<Badge3D>View only</Badge3D><span className="hidden lg:inline-flex"><ThemeSwitch /></span></span>
      </header>
      <div className="grid min-h-0 flex-1 md:grid-cols-[minmax(0,1fr)_340px]">
        <div className="relative min-h-[320px]">
          <Viewer3D topoUrl={d.files.includes("topo.json") ? `${base}/topo.json` : null} version={d.status.build_id} tool={tool} onToolChange={setTool} selection={sel} onSelectionChange={setSel}
            empty={<div className="text-sm text-muted">This part has no 3D model yet.</div>} />
        </div>
        <aside className="flex min-h-0 flex-col border-l border-ink/70 bg-slab">
          <div role="group" aria-label="Panels" className="flex flex-wrap gap-1.5 border-b border-ink/70 px-2.5 py-2.5">{tabs.map(([v, l, icon]) => (
            <Button3D key={v} size="xs" finish="steel" pressed={tab === v} onClick={() => setTab(v)} icon={icon}>{l}</Button3D>))}</div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3.5 text-[14px] text-ink">
            {tab === "params" && (d.params.length ? <table className="w-full"><tbody className="divide-y divide-border">{d.params.map(p => (
              <tr key={p.name}><td className="py-1.5 text-muted">{p.label ?? p.name}</td><td className="py-1.5 text-right font-medium tabular-nums">{fmtNum(p.value, p.unit)}</td></tr>))}</tbody></table>
              : <p className="text-muted">No editable parameters.</p>)}
            {tab === "checks" && <ul className="space-y-1.5">{(d.status.checks ?? []).map(c => <li key={c.id} className="flex items-center gap-1.5">{c.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <CircleX className="h-3.5 w-3.5 text-danger" />}{c.name ?? c.title ?? c.id}</li>)}
              {!(d.status.checks ?? []).length && <li className="text-muted">No checks yet.</li>}</ul>}
            {tab === "revs" && <ul className="space-y-1.5">{d.revisions.map(r => <li key={r.n}><b>Revision {r.n}</b> <span className="text-muted">{r.why ?? ""}{r.by ? ` · ${r.by}` : ""}</span></li>)}</ul>}
            {tab === "drawing" && <img src={`${base}/drawing.svg`} alt="Drawing sheet" className="w-full rounded border border-border bg-white" />}
          </div>
          <div className="border-t border-ink/70 bg-sheet2 px-3.5 py-2.5 font-anno text-[11.5px] text-ink2">
            {fp ? <>{fp.bbox.map(n => n.toFixed(1)).join(" × ")} mm · {num(fp.volume, 0)} mm³{d.status.material ? ` · ${d.status.material}` : ""}</> : "n/a"}
            {d.expires_at && <div>Link expires {new Date(d.expires_at).toLocaleDateString()}</div>}
            <div className="mt-1">Geometry checks are deterministic; they don't certify a part for manufacture.</div>
          </div>
        </aside>
      </div>
    </SiteScope>
  );
}
