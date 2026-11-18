import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Aperture, Box as BoxIcon, Boxes, Camera, ChevronDown, Cpu, Film, FolderOpen, Info, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Project } from "@/lib/types";
import { Button, Card, EmptyState, Menu, MenuContent, MenuItem, MenuTrigger, PageLoader, Progress, Spinner, StatusBadge, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";
import type { ModuleAppProps } from "../registry";
import type { AssemblyPart, Job, Presets, ProjectInfo, Settings } from "./types";
import { LookPanel, Section, Seg, Swatch } from "./LookPanel";
import { FileButtons } from "@/components/NativeExport";
import { moduleExportUrl } from "@/lib/native";
import { CHECKER, deviceLine, Exports, Gallery, MeshPanel } from "./Gallery";
import DatasheetPanel from "./DatasheetPanel";

const ACTIVE = (j?: Job | null) => !!j && (j.state === "queued" || j.state === "running");

const LOOK_KEYS = ["finish", "colour", "lighting", "camera", "aspect", "transparent", "pose", "soften_edges", "explode"] as const;

/** A look (from the server or a past render) narrowed to the settings, when every preset in it still exists. */
function asLook(raw: Partial<Settings> | null | undefined, presets: Presets): Settings | null {
  if (!raw || !presets.finishes.some(f => f.id === raw.finish) || !presets.lighting.some(l => l.id === raw.lighting)
    || !presets.cameras.some(c => c.id === raw.camera) || !presets.aspects.includes(raw.aspect ?? "")) return null;
  const out: Record<string, unknown> = {};
  for (const k of LOOK_KEYS) out[k] = raw[k];
  const look = { pose: "auto", soften_edges: true, transparent: false, colour: null, ...(out as Partial<Settings>) } as Settings;
  if (look.explode == null) delete look.explode;
  return look;
}

/** The project's saved look (shared by the workspace), else the material's suggestion. */
function initial(info: ProjectInfo, presets: Presets): Settings {
  return asLook(info.look, presets) ?? { finish: info.suggested.finish, colour: info.suggested.colour, lighting: "studio", camera: "hero",
    aspect: "4:3", transparent: false, pose: "auto", soften_edges: true, ...(info.kind === "assembly" ? { explode: 0 } : {}) };
}

/** Assemblies: each part keeps the finish its material suggests; the explode slider replaces the finish picker. */
function AssemblyParts({ parts, presets, value, onChange }: { parts: AssemblyPart[]; presets: Presets; value: Settings; onChange: (s: Settings) => void }) {
  const steps = [0, 0.25, 0.5, 0.75, 1];
  return (
    <Section title="Parts and finishes">
      <ul className="space-y-1.5" data-parts>
        {parts.map(p => {
          const f = presets.finishes.find(x => x.id === p.finish);
          const hex = (p.colour && f?.colours?.find(c => c.id === p.colour)?.hex) || f?.swatch || "#ccc";
          return (
            <li key={p.key} className={`flex items-center gap-2 text-[12.5px] ${p.visible ? "" : "opacity-50"}`} title={p.material ? `Material: ${p.material}` : "No material set"}>
              <Swatch hex={hex} metal={f?.group === "Metal"} size={18} />
              <span className="min-w-0 flex-1 leading-tight"><span className="block truncate font-medium">{p.count > 1 ? `${p.count} × ` : ""}{p.name}</span>
                <span className="block truncate text-[11.5px] text-muted">{f?.label ?? p.finish}{p.colour && f?.colours ? `, ${f.colours.find(c => c.id === p.colour)?.label.toLowerCase()}` : ""}{p.visible ? "" : " · hidden"}</span></span>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[11.5px] text-muted">Each finish follows the part&apos;s material. Parts hidden in Assembly Studio are left out.</p>
      <div className="mt-3 mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Explode</div>
      <Seg name="explode" value={String(value.explode ?? 0)} options={steps.map(x => ({ id: String(x), label: `${x * 100}%` }))} onChange={v => onChange({ ...value, explode: Number(v) })} />
    </Section>
  );
}

/** First GPU render on this server: Blender prepares the GPU and prints nothing until it is done, so show what is
 * happening, the elapsed time and an estimate-based bar instead of a bare spinner. */
function WarmUp({ job, estimate }: { job: Job | undefined; estimate: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const t0 = job?.started_at ? Date.parse(`${job.started_at}Z`) : now;
  const el = Math.max(0, Math.round((now - t0) / 1000));
  const mmss = `${Math.floor(el / 60)}:${String(el % 60).padStart(2, "0")}`;
  return (
    <div className="flex max-w-sm flex-col items-center gap-2.5 text-center" data-warmup>
      <Cpu className="h-6 w-6 text-primary" />
      <div className="text-[13.5px] font-medium text-text">Preparing the GPU for the first render on this server</div>
      <div className="text-[12.5px] leading-snug">This happens once after the renderer is installed or updated and takes about {Math.round(estimate / 60)} minutes. Later previews take a few seconds.</div>
      <Progress value={Math.min(95, (el / estimate) * 100)} className="mt-1 w-64" />
      <div className="tabular-nums text-[12px]" data-elapsed>{mmss} elapsed</div>
    </div>
  );
}

function Picker({ projects, loading, onPick }: { projects: Project[]; loading: boolean; onPick: (id: string) => void }) {
  const built = projects.filter(p => p.builds > 0 && p.last_status?.ok);
  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <h2 className="text-[20px] font-semibold tracking-tight">Product renders of your verified parts</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">Pick a project. Its verified model is meshed finely and placed in a studio scene, with a finish suggested from its material. Preview instantly, then render high-resolution stills, turntables and editable Blender scenes for decks, datasheets and web pages.</p>
      <div className="mt-7 label">Projects with a verified model</div>
      {loading ? <div className="mt-4"><Spinner /></div> : built.length === 0 ? (
        <Card className="mt-3 p-6 text-sm text-muted">No verified builds yet. Build a part in the Design Studio first.</Card>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {built.map(p => (
            <button key={p.id} onClick={() => onPick(p.id)} data-project={p.id}
              className="card group overflow-hidden text-left transition hover:-translate-y-0.5 hover:shadow-pop">
              <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden">
                {p.thumbnail ? <IsoThumb src={`${p.thumbnail}?v=${p.last_status?.build_id ?? 0}`} /> : <BoxIcon className="h-10 w-10 text-muted" />}
              </div>
              <div className="border-t border-border p-3">
                <div className="truncate text-[13px] font-semibold">{p.name}</div>
                <div className="mt-0.5 flex items-center justify-between text-[11.5px] text-muted"><span className="truncate">{p.last_status?.material && p.last_status.material !== "unspecified" ? String(p.last_status.material) : "Material not set"}</span><span>{ago(p.updated_at)}</span></div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function useJob(base: string, id: string | null) {
  return useQuery({
    queryKey: ["mesh-job", base, id], enabled: !!id, retry: false,
    queryFn: () => api.get<Job>(`${base}/jobs/${id}`),
    refetchInterval: q => (ACTIVE(q.state.data) ? 600 : false),
  });
}

/** The render workspace for a project (`/api/m/mesh/projects/<id>`) or an assembly (`/api/m/mesh/assemblies/<id>`). */
function Workspace({ id, assembly, presets, canEdit }: { id: string; assembly: boolean; presets: Presets; canEdit: boolean }) {
  const qc = useQueryClient();
  const pid = id;
  const base = `/api/m/mesh/${assembly ? "assemblies" : "projects"}/${id}`;
  const info = useQuery({ queryKey: ["mesh-info", base], queryFn: () => api.get<ProjectInfo>(base), retry: false });
  const jobsQ = useQuery({
    queryKey: ["mesh-jobs", base], enabled: info.isSuccess,
    queryFn: () => api.get<Pick<ProjectInfo, "renders" | "exports" | "previews">>(`${base}/jobs`),
    refetchInterval: q => ([...(q.state.data?.renders ?? []), ...(q.state.data?.exports ?? [])].some(ACTIVE) ? 1200 : false),
  });
  const [settings, setSettings] = useState<Settings | null>(null);
  useEffect(() => { if (info.data && !settings) setSettings(initial(info.data, presets)); }, [info.data, settings, presets]);
  // the look is saved with the project for the whole workspace (a moment after the last change)
  const savedLook = useRef<string>("");
  useEffect(() => {
    if (!settings || !canEdit || !info.data || assembly) return;
    const key = JSON.stringify(settings);
    if (!savedLook.current) { savedLook.current = info.data.look ? JSON.stringify(asLook(info.data.look, presets)) : key; if (savedLook.current === key) return; }
    if (key === savedLook.current) return;
    const t = setTimeout(() => {
      api.post(`${base}/look`, settings).then(() => { savedLook.current = key; }).catch(() => { /* retried on the next change */ });
    }, 1200);
    return () => clearTimeout(t);
  }, [settings, canEdit, base, assembly, info.data, presets]);

  // live preview: one preview in flight at a time; the newest settings win when it finishes
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [shown, setShown] = useState<Job | null>(null);
  const preview = useJob(base, previewId);
  const wanted = useRef<string>("");
  const sent = useRef<string>("");
  const [tab, setTab] = useState("gallery");
  const [busy, setBusy] = useState<string | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  const requestPreview = useCallback(async (s: Settings) => {
    const key = JSON.stringify(s);
    sent.current = key;
    try {
      const j = await api.post<Job>(`${base}/renders`, { ...s, quality: "preview" });
      setPreviewErr(null);
      setPreviewId(j.id);
      qc.setQueryData(["mesh-job", base, j.id], j);
    } catch (e) {
      sent.current = "";
      setPreviewErr(e instanceof ApiError ? e.message : "Preview failed");
    }
  }, [base, qc]);

  useEffect(() => {
    if (!settings || !canEdit) return;
    wanted.current = JSON.stringify(settings);
    const t = setTimeout(() => { if (!ACTIVE(preview.data) && wanted.current !== sent.current) requestPreview(settings); }, 350);
    return () => clearTimeout(t);
  }, [settings, canEdit]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const j = preview.data;
    if (!j) return;
    if (j.state === "done") setShown(j);
    if (j.state === "failed") setPreviewErr(j.error ?? "Preview failed");
    if (!ACTIVE(j) && settings && wanted.current !== sent.current) requestPreview(settings);
  }, [preview.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // viewers: show the newest finished render instead of live previews
  useEffect(() => {
    if (!canEdit && !shown && info.data) setShown(info.data.renders.find(r => r.state === "done") ?? null);
  }, [canEdit, info.data, shown]);

  const queue = async (body: Partial<Settings> & { quality: string }) => {
    const j = await api.post<Job>(`${base}/renders`, body);
    const what = body.quality === "final" ? "Final render" : body.quality === "turntable_draft" ? "Quick turntable" : "Turntable";
    toast.success(j.state === "done" ? "Already rendered with these settings. It's in the gallery." : `${what} queued`);
    setTab("gallery");
    await qc.invalidateQueries({ queryKey: ["mesh-jobs", base] });
  };
  const submit = async (quality: "final" | "turntable" | "turntable_draft") => {
    if (!settings) return;
    setBusy(quality.startsWith("turntable") ? "turntable" : quality);
    try { await queue({ ...settings, quality }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Render failed to start"); }
    finally { setBusy(null); }
  };
  /** Same look as a past render, on the current part (a stale render becomes a fresh one). */
  const rerender = async (j: Job) => {
    try {
      if (j.kind === "export") {
        await api.post<Job>(`${base}/exports`, { finish: j.options.finish, colour: j.options.colour ?? null });
        await qc.invalidateQueries({ queryKey: ["mesh-jobs", base] });
      } else {
        const look = asLook(j.options, presets);
        if (!look) { toast.error("That render used settings that are no longer offered"); return; }
        await queue({ ...look, quality: j.options.quality ?? j.kind });
      }
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Render failed to start"); }
  };
  const useLook = (j: Job) => {
    const look = asLook(j.options, presets);
    if (look) { setSettings(look); toast.success("Settings applied. The preview updates in a moment."); }
    else toast.error("That render used settings that are no longer offered");
  };
  const doExport = async () => {
    if (!settings) return;
    setBusy("export");
    try {
      await api.post<Job>(`${base}/exports`, { finish: settings.finish, colour: settings.colour });
      await qc.invalidateQueries({ queryKey: ["mesh-jobs", base] });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Export failed to start"); }
    finally { setBusy(null); }
  };

  const err = info.error instanceof ApiError ? info.error : null;
  if (err) return (
    <div className="flex flex-1 items-center justify-center p-8">
      <EmptyState icon={<Aperture className="h-5 w-5" />} title={assembly ? "Can't render this assembly" : err.status === 409 ? "No verified model yet" : "Can't open this project"} body={err.message}
        action={assembly ? <Link to={`/app/modules/assembly?assembly=${id}`}><Button>Open in Assembly Studio</Button></Link>
          : err.status === 409 ? <Link to={`/app/projects/${pid}`}><Button>Open in Design Studio</Button></Link> : undefined} />
    </div>
  );
  if (!info.data || !settings) return <div className="flex flex-1 flex-col items-center justify-center gap-3 text-sm text-muted"><Spinner className="h-6 w-6" />Preparing the visualisation mesh…</div>;

  const d = info.data;
  const renders = jobsQ.data?.renders ?? d.renders;
  const exportsL = jobsQ.data?.exports ?? d.exports;
  const fin = presets.finishes.find(f => f.id === settings.finish);
  const finishLabel = `${fin?.label ?? ""}${settings.colour && fin?.colours ? `, ${fin.colours.find(c => c.id === settings.colour)?.label.toLowerCase() ?? ""}` : ""}`;
  const pj = preview.data;
  const [aw, ah] = settings.aspect.split(":").map(Number) as [number, number];
  const fr = presets.quality.final.res[0];
  const finalRes = aw >= ah ? `${fr} × ${Math.round(fr * ah / aw)}` : `${Math.round(fr * aw / ah)} × ${fr}`;
  const img = shown?.files["render.png"]?.url;
  const running = renders.filter(ACTIVE).length;

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[272px_minmax(0,1fr)_320px] lg:overflow-hidden">
      <aside className="min-h-0 overflow-y-auto border-r border-border bg-panel" data-panel="look">
        {canEdit ? <LookPanel presets={presets} value={settings} onChange={setSettings} suggested={d.suggested} material={d.project.material}
          finishSlot={d.parts ? <AssemblyParts parts={d.parts} presets={presets} value={settings} onChange={setSettings} /> : undefined} />
          : <div className="p-4 text-sm text-muted">You have view access: browse and download renders. Engineers can make new ones.</div>}
      </aside>

      <section className="flex min-h-[460px] min-w-0 flex-col bg-panel2/40">
        <div className="relative flex min-h-0 flex-1 items-center justify-center p-5">
          <div className="relative w-full max-w-[1100px] overflow-hidden rounded-lg border border-border shadow-card"
            style={{ aspectRatio: `${aw} / ${ah}`, maxHeight: "100%", ...(settings.transparent ? CHECKER : { background: "#eef0f3" }) }} data-stage>
            {img ? <img src={img} alt={`${d.project.name} render`} className="absolute inset-0 h-full w-full object-contain" data-preview={shown?.id} />
              : <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-sm text-muted">
                {previewErr ? <span className="max-w-sm text-center text-danger">{previewErr}</span>
                  : pj?.warming ? <WarmUp job={pj} estimate={pj.warm_estimate_s ?? presets.renderer.warm_up_estimate_s} />
                  : <><Spinner className="h-6 w-6" />{pj?.state === "queued" ? "Waiting for the renderer…" : pj?.phase && pj.phase !== "Rendering" ? `${pj.phase}…` : "Lighting the studio…"}</>}
              </div>}
            {ACTIVE(pj) && img && (
              <div className="absolute right-3 top-3 flex items-center gap-2 rounded-full border border-border bg-panel/95 px-3 py-1 text-xs text-muted shadow-card" data-previewing>
                <Spinner className="h-3.5 w-3.5" />{pj?.state === "queued" ? "Waiting for the renderer…" : pj?.warming ? "Preparing the GPU (first render on this server)…" : "Updating preview…"}
              </div>
            )}
            {ACTIVE(pj) && !pj?.warming && <div className="absolute inset-x-0 bottom-0"><Progress value={(pj?.progress ?? 0) * 100} className="h-1 rounded-none" /></div>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-border bg-panel px-4 py-2.5">
          <div className="min-w-0 flex-1 text-[12px] text-muted">
            <div className="flex items-center gap-1.5"><Info className="h-3.5 w-3.5 shrink-0" /><span><b className="text-text">Visualisation render</b> of a tessellated mesh, not the exact model.</span></div>
            {shown && <div className="mt-0.5 truncate" data-device>{canEdit ? "Preview · " : ""}{deviceLine(shown)}</div>}
          </div>
          {canEdit && <>
            <Menu>
              <MenuTrigger asChild>
                <Button variant="secondary" icon={<Film className="h-4 w-4" />} loading={busy === "turntable"} data-action="turntable">Turntable<ChevronDown className="h-3.5 w-3.5 opacity-70" /></Button>
              </MenuTrigger>
              <MenuContent>
                <MenuItem onSelect={() => submit("turntable_draft")}><span data-action="turntable-draft">Quick turntable</span><span className="ml-auto pl-4 text-xs text-muted">{presets.quality.turntable_draft.frames} frames · {presets.quality.turntable_draft.res[0]} px</span></MenuItem>
                <MenuItem onSelect={() => submit("turntable")}><span data-action="turntable-full">Full turntable</span><span className="ml-auto pl-4 text-xs text-muted">{presets.quality.turntable.frames} frames · {presets.quality.turntable.res[0]} px</span></MenuItem>
              </MenuContent>
            </Menu>
            <Button icon={<Camera className="h-4 w-4" />} loading={busy === "final"} onClick={() => submit("final")} data-action="final">Render final <span className="font-normal opacity-80">· {finalRes}</span></Button>
          </>}
        </div>
      </section>

      <aside className="flex min-h-0 flex-col border-l border-border bg-panel">
        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <TabList className="px-2">
            <Tab value="gallery">Gallery{running > 0 && <span className="ml-1 rounded-full bg-primary px-1.5 text-[10.5px] font-semibold text-primary-fg">{running}</span>}</Tab>
            {!assembly && <Tab value="exports">Exports</Tab>}
            {!assembly && <Tab value="datasheet">Datasheet</Tab>}
            {d.mesh && <Tab value="mesh">Mesh</Tab>}
          </TabList>
          <TabPanel value="gallery" className="min-h-0 flex-1 overflow-y-auto">
            <Gallery base={base} items={renders} canEdit={canEdit} onChanged={() => qc.invalidateQueries({ queryKey: ["mesh-jobs", base] })}
              onUse={useLook} onRerender={rerender} />
          </TabPanel>
          <TabPanel value="exports" className="min-h-0 flex-1 overflow-y-auto">
            <Exports base={base} items={exportsL} canEdit={canEdit} busy={busy === "export"} onExport={doExport} finishLabel={finishLabel} onRerender={rerender}
              onChanged={() => qc.invalidateQueries({ queryKey: ["mesh-jobs", base] })} />
          </TabPanel>
          {!assembly && <TabPanel value="datasheet" className="min-h-0 flex-1 overflow-y-auto"><DatasheetPanel base={base} pid={pid} settings={settings} canEdit={canEdit} /></TabPanel>}
          {d.mesh && <TabPanel value="mesh" className="min-h-0 flex-1 overflow-y-auto"><MeshPanel info={d} mesh={d.mesh} /></TabPanel>}
        </Tabs>
      </aside>
    </div>
  );
}

export default function MeshStudio({ projectId }: ModuleAppProps) {
  const { me } = useSession();
  const [params, setParams] = useSearchParams();
  const [pid, setPid] = useState<string | null>(projectId);
  const aid = params.get("assembly");
  const canEdit = me?.org?.role !== "viewer";
  const presets = useQuery({ queryKey: ["mesh-presets"], queryFn: () => api.get<Presets>("/api/m/mesh/presets"), staleTime: 600_000 });
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects") });
  const choose = (id: string | null) => {
    setPid(id);
    const next = new URLSearchParams(params);
    next.delete("project");
    if (id) next.set("project", id);
    setParams(next, { replace: true });
  };
  const name = useMemo(() => projects.data?.items.find(p => p.id === pid)?.name, [projects.data, pid]);
  const asmInfo = useQuery({ queryKey: ["mesh-info", `/api/m/mesh/assemblies/${aid}`], enabled: !!aid, retry: false,
    queryFn: () => api.get<ProjectInfo>(`/api/m/mesh/assemblies/${aid}`) });

  if (!presets.data) return presets.error ? <div className="p-10 text-center text-muted">{(presets.error as Error).message}</div> : <PageLoader />;
  const r = presets.data.renderer;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-panel px-4 py-2">
        {aid ? <Link to={`/app/modules/assembly?assembly=${aid}`} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Back to assembly</Link>
          : projectId ? <Link to={`/app/projects/${projectId}`} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Back to project</Link>
          : <Link to="/app/modules" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Modules</Link>}
        <div className="h-5 w-px bg-border" />
        <div className="flex items-center gap-2"><Aperture className="h-4 w-4 text-primary" /><h1 className="text-[15px] font-semibold">Mesh Studio</h1><StatusBadge status="live" /></div>
        {aid && <div className="flex min-w-0 items-center gap-2 rounded border border-border bg-panel2 px-2.5 py-1 text-[13px]">
          <Boxes className="h-3.5 w-3.5 text-muted" /><span className="max-w-[260px] truncate font-medium">{asmInfo.data?.project.name ?? "…"}</span><span className="text-muted">assembly{asmInfo.data?.instances ? ` · ${asmInfo.data.instances} parts shown` : ""}</span>
        </div>}
        {!aid && pid && <div className="flex min-w-0 items-center gap-2 rounded border border-border bg-panel2 px-2.5 py-1 text-[13px]">
          <BoxIcon className="h-3.5 w-3.5 text-muted" /><span className="max-w-[260px] truncate font-medium">{name ?? "…"}</span><span className="text-muted">verified model</span>
        </div>}
        <div className="ml-auto flex items-center gap-3">
          {!aid && <FileButtons ext="fwrender" saveUrl={pid ? moduleExportUrl("mesh", pid) : null} saveName={`${name ?? "renders"}.fwrender`} />}
          <span className="hidden text-[12px] text-muted md:inline" data-renderer>{r.available ? `Renderer: ${r.engine} on ${r.device === "GPU" ? r.gpu ?? "GPU" : "CPU"}` : "Renderer unavailable"}</span>
          {!aid && pid && <Link to={`/app/modules/airender?project=${pid}`} title="AI marketing visuals from this part on your own OpenAI key (Beta, illustrative)" data-action="ai-render"><Button size="sm" variant="ghost" icon={<Sparkles className="h-4 w-4" />}>AI render</Button></Link>}
          {!aid && pid && <Button size="sm" variant="secondary" icon={<FolderOpen className="h-4 w-4" />} onClick={() => choose(null)}>Change project</Button>}
        </div>
      </header>
      {!r.available ? (
        <div className="flex flex-1 items-center justify-center p-8"><EmptyState icon={<Aperture className="h-5 w-5" />} title="Rendering isn't available on this server" body={r.reason ?? "The render engine is not installed."} /></div>
      ) : aid ? <Workspace key={`a-${aid}`} id={aid} assembly presets={presets.data} canEdit={canEdit} />
      : !pid ? (
        <div className="min-h-0 flex-1 overflow-y-auto"><Picker projects={projects.data?.items ?? []} loading={projects.isLoading} onPick={choose} /></div>
      ) : <Workspace key={pid} id={pid} assembly={false} presets={presets.data} canEdit={canEdit} />}
    </div>
  );
}
