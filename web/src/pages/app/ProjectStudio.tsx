import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, CircleHelp, Download, FileCode2, GitCompare, History, ListTree, Scale, SlidersHorizontal, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { BuildStatus, Catalog, ManualFeature, Project } from "@/lib/types";
import { num } from "@/lib/format";
import { Input, PageLoader, Tab, TabList, TabPanel, Tabs, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import Viewer3D, { type Tool } from "@/components/Viewer3D";
import { ProjectStatus } from "@/components/ProjectCard";
import { runTour, seenTour, STUDIO_TOUR } from "@/lib/tour";
import type { Pick, SketchPreview, Topo, V3 } from "@/viewer/types";
import Chat from "./studio/Chat";
import FeatureManager from "./studio/FeatureManager";
import { ChecksPanel, FilesPanel, MassPanel, ParamsPanel, RevisionsPanel, SourcePanel, TreePanel } from "./studio/Panels";

interface CompareState { base: number; added: Topo | null; removed: Topo | null; added_mm3: number; removed_mm3: number; params: Record<string, { from: unknown; to: unknown }> }

export default function ProjectStudio() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { me } = useSession();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [tool, setTool] = useState<Tool>("orbit");
  const [selection, setSelection] = useState<Pick[]>([]);
  const [topo, setTopo] = useState<Topo | null>(null);
  const [hl, setHl] = useState<number[]>([]);
  const [showCom, setShowCom] = useState(false);
  const [sketch, setSketch] = useState<SketchPreview | null>(null);
  const [pm, setPm] = useState<{ op: ManualFeature["op"]; editing: ManualFeature | null } | null>(null);
  const [compare, setCompare] = useState<CompareState | null>(null);
  const [tab, setTab] = useState("tree");
  const [manualBusy, setManualBusy] = useState(false);

  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/api/projects/${id}`), refetchInterval: 15_000 });
  const hasBuilds = (project.data?.builds ?? 0) > 0;
  const status = useQuery({ queryKey: ["status", id, hasBuilds], enabled: hasBuilds,
    queryFn: () => fetch(`/api/projects/${id}/files/status.json`).then(r => (r.ok ? (r.json() as Promise<BuildStatus>) : null)) });
  const manual = useQuery({ queryKey: ["manual", id, status.data?.build_id], enabled: hasBuilds, queryFn: () => api.get<{ features: ManualFeature[] }>(`/api/projects/${id}/manual`) });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const p = project.data;
  const st = status.data ?? undefined;

  useEffect(() => { if (p) setName(p.name); }, [p?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!p || seenTour("studio")) return;
    const t = setTimeout(() => runTour(STUDIO_TOUR, "studio"), 900);
    return () => clearTimeout(t);
  }, [p?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (st?.build_id) setCompare(null); }, [st?.build_id]);

  const refresh = () => {
    for (const k of ["status", "project", "manual", "revisions", "params"]) qc.invalidateQueries({ queryKey: [k, id] });
    qc.invalidateQueries({ queryKey: ["me"] }); qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const previewMods = useMemo(() => (catalog.data?.modules ?? []).filter(m => ["drawings", "manufacturing", "engineering"].includes(m.code)), [catalog.data]);
  const selectKinds = useMemo<Pick["kind"][] | undefined>(() => (pm ? (pm.op === "fillet" || pm.op === "chamfer" ? ["edge"] : ["face"]) : undefined), [pm]);

  const openPm = (op: ManualFeature["op"], ed: ManualFeature | null = null) => {
    setPm({ op, editing: ed }); setTool("select");
    setSelection(s => s.filter(x => (op === "fillet" || op === "chamfer" ? x.kind === "edge" : x.kind === "face")));
  };
  const manualCall = async (fn: () => Promise<unknown>, ok: string) => {
    setManualBusy(true);
    try { await fn(); toast.success(ok); refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setManualBusy(false); }
  };
  const runCompare = async (base: number) => {
    try {
      const r = await api.post<{ added_url: string | null; removed_url: string | null; added_mm3: number; removed_mm3: number; params_changed: CompareState["params"] }>(`/api/projects/${id}/compare`, { base });
      const load = (u: string | null) => (u ? fetch(u).then(x => x.json() as Promise<Topo>) : Promise.resolve(null));
      const [added, removed] = await Promise.all([load(r.added_url), load(r.removed_url)]);
      setCompare({ base, added, removed, added_mm3: r.added_mm3, removed_mm3: r.removed_mm3, params: r.params_changed });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Compare failed"); }
  };

  if (project.isLoading) return <PageLoader />;
  if (!p) return <div className="p-10 text-center text-muted">Project not found. <Link to="/app/projects" className="link">Back to projects</Link></div>;
  const fp = st?.fingerprint;
  const mf = manual.data?.features ?? [];
  const tabs: [string, React.ReactNode, string][] = [["tree", <ListTree className="h-3.5 w-3.5" />, "Tree"], ["checks", <Check className="h-3.5 w-3.5" />, "Checks"],
    ["params", <SlidersHorizontal className="h-3.5 w-3.5" />, "Params"], ["mass", <Scale className="h-3.5 w-3.5" />, "Mass"],
    ["revs", <History className="h-3.5 w-3.5" />, "Revisions"], ["files", <Download className="h-3.5 w-3.5" />, "Files"], ["src", <FileCode2 className="h-3.5 w-3.5" />, "Source"]];

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-panel px-3">
        <Link to="/app/projects" className="rounded p-1.5 text-muted hover:bg-text/5" aria-label="Back to projects"><ArrowLeft className="h-4 w-4" /></Link>
        {editing ? <Input autoFocus value={name} onChange={e => setName(e.target.value)} className="h-8 w-64"
          onBlur={async () => { setEditing(false); if (name.trim() && name !== p.name) { await api.patch(`/api/projects/${p.id}`, { name }); refresh(); } }}
          onKeyDown={e => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
          : <button onClick={() => setEditing(true)} className="truncate rounded px-1.5 py-1 text-[15px] font-semibold hover:bg-text/5" title="Rename">{p.name}</button>}
        <ProjectStatus p={p} />
        <nav className="ml-4 hidden items-center gap-1 lg:flex" data-tour="studio-tabs">
          <span className="inline-flex items-center gap-1.5 rounded bg-primary-soft px-2.5 py-1 text-[13px] font-medium text-primary"><Icon name="box" className="h-3.5 w-3.5" />Design</span>
          {previewMods.map(m => (
            <Link key={m.code} to={`/app/modules/${m.code}?project=${p.id}`} className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-[13px] text-muted hover:bg-text/5 hover:text-text">
              <Icon name={m.icon} className="h-3.5 w-3.5" />{m.name.replace(" Studio", "").replace(" Advisor", "")}<span className="rounded bg-accent/12 px-1 text-[9px] font-bold uppercase text-accent">Prev</span>
            </Link>))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Tip content="Studio tour" side="bottom"><button onClick={() => runTour(STUDIO_TOUR, "studio")} className="rounded p-1.5 text-muted hover:bg-text/5"><CircleHelp className="h-4 w-4" /></button></Tip>
          {fp && <a href={`/api/projects/${p.id}/files/part.step`} className="inline-flex h-8 items-center gap-1.5 rounded bg-primary px-3 text-[13px] font-medium text-white hover:brightness-110"><Download className="h-4 w-4" />STEP</a>}
        </div>
      </div>

      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[370px_minmax(0,1fr)_340px] max-xl:grid-cols-[330px_minmax(0,1fr)] max-md:grid-cols-1">
        <Chat project={p} topo={topo} selection={pm ? [] : selection} onSelectionChange={setSelection} onActivity={refresh} />
        <div className="relative min-h-[320px] min-w-0 overflow-hidden">
          <Viewer3D topoUrl={hasBuilds ? `/api/projects/${p.id}/files/topo.json` : null} version={fp ? st?.build_id : `keep`}
            tool={tool} onToolChange={setTool} selection={selection} onSelectionChange={setSelection} selectKinds={selectKinds}
            highlightFaces={hl} com={showCom ? (st?.mass?.com_mm as V3 | undefined) ?? null : null} sketch={sketch}
            compare={compare ? { added: compare.added, removed: compare.removed } : null} onTopo={setTopo}
            empty={<div className="text-center text-sm text-muted"><Icon name="box" className="mx-auto mb-2 h-10 w-10 text-muted/40" />Your model appears here after the first build.</div>} />
          {st?.error && (
            <div className="absolute left-1/2 top-16 max-w-md -translate-x-1/2 rounded-lg border border-danger/40 bg-panel/95 px-3 py-2 text-[12.5px] shadow-card">
              <b className="text-danger">Last build failed</b> — showing the last successful geometry.{project.data?.agent?.busy ? " The agent is working on it." : ""}
            </div>)}
          {compare && (
            <div className="absolute right-3 top-3 w-64 rounded-lg border border-border bg-panel/95 p-3 text-[12.5px] shadow-card">
              <div className="flex items-center justify-between"><span className="flex items-center gap-1.5 font-semibold"><GitCompare className="h-4 w-4 text-primary" />Rev {compare.base} → current</span>
                <button onClick={() => setCompare(null)} aria-label="Exit compare"><X className="h-4 w-4 text-muted" /></button></div>
              <div className="mt-2 flex justify-between"><span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-[#22a85a]" />Added</span><span className="tabular-nums">{num(compare.added_mm3, 1)} mm³</span></div>
              <div className="flex justify-between"><span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-[#d8402f]" />Removed</span><span className="tabular-nums">{num(compare.removed_mm3, 1)} mm³</span></div>
              {Object.keys(compare.params).length > 0 && <div className="mt-2 border-t border-border pt-2">{Object.entries(compare.params).map(([k, v]) =>
                <div key={k} className="flex justify-between font-mono text-[11px]"><span>{k}</span><span>{String(v.from)} → {String(v.to)}</span></div>)}</div>}
            </div>)}
        </div>
        <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden border-l border-border bg-panel max-xl:hidden">
          {pm ? (
            <FeatureManager key={`${pm.op}-${pm.editing?.id ?? "new"}`} project={p} op={pm.op} editing={pm.editing} topo={topo} selection={selection}
              onSelection={setSelection} onSketch={setSketch} onDone={() => { setPm(null); setSketch(null); refresh(); setTool("orbit"); }}
              onCancel={() => { setPm(null); setSketch(null); setSelection([]); setTool("orbit"); }} />
          ) : (
            <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
              <TabList className="gap-0 overflow-x-auto px-1 [scrollbar-width:none]">
                {tabs.map(([v, icon, label]) => <Tab key={v} compact value={v} title={label}>{icon}{tab === v && label}</Tab>)}
              </TabList>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <TabPanel value="tree"><TreePanel status={st} topo={topo} manual={mf} busy={manualBusy} onHover={setHl}
                  onAdd={op => openPm(op)} onEdit={f => openPm(f.op, f)}
                  onToggle={f => manualCall(() => api.patch(`/api/projects/${id}/manual/${f.id}`, { feature: { suppressed: !f.suppressed } }), f.suppressed ? "Feature unsuppressed" : "Feature suppressed")}
                  onMove={(f, d) => { const ids = mf.map(x => x.id); const i = ids.indexOf(f.id); [ids[i], ids[i + d]] = [ids[i + d]!, ids[i]!]; manualCall(() => api.post(`/api/projects/${id}/manual/reorder`, { ids }), "Features reordered"); }}
                  onDelete={f => manualCall(() => api.del(`/api/projects/${id}/manual/${f.id}`), `${f.name} deleted`)} /></TabPanel>
                <TabPanel value="checks"><ChecksPanel status={st} /></TabPanel>
                <TabPanel value="params"><ParamsPanel project={p} status={st} onChanged={refresh} /></TabPanel>
                <TabPanel value="mass"><MassPanel project={p} status={st} showCom={showCom} onShowCom={setShowCom} /></TabPanel>
                <TabPanel value="revs"><RevisionsPanel project={p} onChanged={refresh} version={st?.build_id} onCompare={runCompare} comparing={compare?.base ?? null} /></TabPanel>
                <TabPanel value="files"><FilesPanel project={p} status={st} /></TabPanel>
                <TabPanel value="src"><SourcePanel project={p} version={st?.build_id} /></TabPanel>
              </div>
            </Tabs>)}
        </aside>
      </div>

      <div className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-panel2 px-3 text-[11.5px] text-muted">
        <span>{st?.part ?? p.name}</span>
        {st?.material && <span>{st.material}</span>}
        {fp && <><span>{fp.bbox.map(n => n.toFixed(2)).join(" × ")} mm</span><span>{num(fp.volume, 1)} mm³</span><span>{fp.faces} faces</span></>}
        {selection.length > 0 && <span className="text-primary">{selection.length} selected</span>}
        {st?.timings_s?.total_s !== undefined && <span>build {st.timings_s.total_s}s</span>}
        <span className="ml-auto">Units: {me?.user?.preferences?.units === "in" ? "in (display) · model mm" : "mm"}</span>
        <span>{p.builds} builds</span>
      </div>
    </div>
  );
}
