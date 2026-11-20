import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Aperture, Box as BoxIcon, Download, FolderOpen, ImageIcon, Info, Lock, RefreshCw, RotateCcw, Settings2,
  Shuffle, Sparkles, Trash2, Wand2,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Project } from "@/lib/types";
import { Badge, Button, Card, EmptyState, Input, Modal, PageLoader, Progress, Spinner, StatusBadge } from "@/components/ui";
import { PartCard } from "../ModuleHeader";
import type { ModuleAppProps } from "../registry";
import { Section, Seg } from "../mesh/LookPanel";
import { ConsentCard, OpenAIKeyCard, Setup, useIntegration } from "./Connect";
import { etaSeconds, keepsGeometry, negativesToText, refineKey, sizeLabel, textToNegatives, wordCount, type AirSettings } from "./prompt";
import { FileButtons } from "@/components/NativeExport";
import { moduleExportUrl } from "@/lib/native";
import type { AirJob, Choice, Options, ProjectInfo, Refined } from "./types";

const ACTIVE = (j?: AirJob | null) => !!j && (j.state === "queued" || j.state === "running");
const GEOMETRY_START = "Use the attached reference image as the exact geometry of the part.";

function Caption({ text, className }: { text: string; className?: string }) {
  return <div className={cx("flex items-start gap-1.5 text-[11.5px] leading-snug text-muted", className)} data-caption><Info className="mt-px h-3.5 w-3.5 shrink-0" /><span>{text}</span></div>;
}

function Tiles({ name, value, options, onChange }: { name: string; value: string; options: Choice[]; onChange: (v: string) => void }) {
  return (
    <div role="radiogroup" aria-label={name} className="grid grid-cols-2 gap-1.5">
      {options.map(o => (
        <button key={o.id} role="radio" aria-checked={value === o.id} data-opt={`${name}:${o.id}`} onClick={() => onChange(o.id)}
          className={cx("rounded-md border px-2 py-1.5 text-left text-[12.5px] leading-tight transition",
            value === o.id ? "border-primary bg-primary-soft font-medium text-primary" : "border-border text-text hover:border-primary/40")}>{o.label}</button>
      ))}
    </div>
  );
}

/** Scenes with their own surroundings take the environment as background; studio scenes go back to white. */
function sceneBackground(scene: string, bg: string): string {
  const studio = scene === "studio" || scene === "catalogue";
  if (!studio && (bg === "white" || bg === "gradient")) return "environment";
  if (studio && bg === "environment") return "white";
  return bg;
}

function SettingsPanel({ opts, value, onChange, materialFinish }: { opts: Options; value: AirSettings; onChange: (s: AirSettings) => void; materialFinish: string }) {
  const set = (p: Partial<AirSettings>) => onChange({ ...value, ...p });
  const cam = opts.cameras.find(c => c.id === value.camera);
  return (
    <div className="text-sm">
      <Section title="Scene"><Tiles name="scene" value={value.scene} options={opts.scenes} onChange={v => set({ scene: v, background: sceneBackground(v, value.background) })} /></Section>
      <Section title="Material & finish" aside={materialFinish && value.finish !== materialFinish
        ? <button className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline" onClick={() => set({ finish: materialFinish })}><RotateCcw className="h-3 w-3" />From material</button> : undefined}>
        <Input value={value.finish} maxLength={160} placeholder="e.g. black anodised aluminium" onChange={e => set({ finish: e.target.value })} data-field="finish" />
        <p className="mt-1.5 text-[11.5px] text-muted">{materialFinish ? "Pre-filled from the part's material." : "The part has no material set; describe the finish you want."}</p>
      </Section>
      <Section title="Lighting"><Tiles name="lighting" value={value.lighting} options={opts.lighting} onChange={v => set({ lighting: v })} /></Section>
      <Section title="Camera">
        <Tiles name="camera" value={value.camera} options={opts.cameras} onChange={v => set({ camera: v })} />
        {cam && !cam.reliable && <p className="mt-2 flex items-start gap-1.5 text-[11.5px] leading-snug text-warning" data-camera-warning><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />A new viewpoint makes the AI imagine the sides it can&apos;t see in the reference, so the shape is less reliable. Match reference keeps it closest.</p>}
      </Section>
      <Section title="Background"><Tiles name="background" value={value.background} options={opts.backgrounds} onChange={v => set({ background: v })} /></Section>
      <Section title="Style"><Tiles name="style" value={value.style} options={opts.styles} onChange={v => set({ style: v })} /></Section>
      <Section title="Output">
        <div className="space-y-2.5">
          <Seg name="size" value={value.size} options={opts.sizes} onChange={v => set({ size: v })} />
          <Seg name="quality" value={value.quality} options={opts.qualities} onChange={v => set({ quality: v })} />
          <div className="flex items-center gap-2"><span className="w-16 text-[12px] text-muted">Variants</span>
            <div className="flex-1"><Seg name="variants" value={String(value.variants)} options={Array.from({ length: opts.max_variants }, (_, i) => ({ id: String(i + 1), label: String(i + 1) }))} onChange={v => set({ variants: Number(v) })} /></div></div>
        </div>
      </Section>
    </div>
  );
}

function Step({ n, title, done, active, children, aside }: { n: number; title: string; done?: boolean; active?: boolean; children: ReactNode; aside?: ReactNode }) {
  return (
    <Card className={cx("p-4", !active && !done && "opacity-60")} data-step={n}>
      <div className="mb-3 flex items-center gap-2">
        <span className={cx("flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-semibold", done ? "bg-success text-white" : "bg-primary-soft text-primary")}>{n}</span>
        <h3 className="text-[14px] font-semibold">{title}</h3>
        {aside && <div className="ml-auto">{aside}</div>}
      </div>
      {children}
    </Card>
  );
}

function Elapsed({ job }: { job: AirJob }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t); }, []);
  const t0 = Date.parse(`${job.started_at ?? job.created_at}Z`);
  const el = Math.max(0, (now - t0) / 1000);
  const eta = job.eta_s ?? 45;
  return (
    <div className="space-y-1.5" data-progress>
      <div className="flex justify-between text-[12px] text-muted"><span>{job.state === "queued" ? "Waiting to send…" : "OpenAI is generating the image…"}</span><span className="tabular-nums">{Math.round(el)} s · usually about {Math.round(eta)} s</span></div>
      <Progress value={Math.min(94, (el / eta) * 100)} />
    </div>
  );
}

function Gallery({ jobs, opts, canEdit, caption, onVariation, onRegenerate, onUsePrompt, onDelete, onOpen }: {
  jobs: AirJob[]; opts: Options; canEdit: boolean; caption: string;
  onVariation: (j: AirJob, index: number) => void; onRegenerate: (j: AirJob) => void; onUsePrompt: (j: AirJob) => void;
  onDelete: (j: AirJob) => void; onOpen: (j: AirJob, index: number) => void;
}) {
  if (!jobs.length) return <div className="p-6 text-center text-sm text-muted"><ImageIcon className="mx-auto mb-2 h-6 w-6 opacity-60" />Generated images appear here, kept with the project.</div>;
  return (
    <ul className="divide-y divide-border" data-gallery>
      {jobs.map(j => (
        <li key={j.id} className="space-y-2 p-3" data-job={j.id} data-state={j.state}>
          <div className="flex items-center gap-2 text-[12px]">
            <span className="font-medium">{j.settings ? `${opts.scenes.find(x => x.id === j.settings.scene)?.label ?? j.settings.scene} · ${opts.styles.find(x => x.id === j.settings.style)?.label ?? j.settings.style}` : "Render"}</span>
            {j.variation_of && <Badge>Variation</Badge>}
            <span className="ml-auto text-muted">{ago(j.created_at)}</span>
          </div>
          {ACTIVE(j) ? <Elapsed job={j} />
            : j.state === "failed" ? <p className="rounded-md border border-danger/25 bg-danger/5 px-2.5 py-2 text-[12.5px] text-danger" data-job-error={j.error_code ?? ""}>{j.error}</p>
            : <div className={cx("grid gap-1.5", j.images.length > 1 ? "grid-cols-2" : "grid-cols-1")}>
              {j.images.map(im => (
                <div key={im.index} className="group relative overflow-hidden rounded-md border border-border bg-panel2">
                  <button className="block w-full" onClick={() => onOpen(j, im.index)} aria-label="Open image"><img src={im.thumb} alt="AI-generated visual" className="aspect-[3/2] w-full object-cover" /></button>
                  <div className="absolute inset-x-0 bottom-0 flex justify-end gap-1 bg-gradient-to-t from-black/60 to-transparent p-1 opacity-0 transition group-hover:opacity-100">
                    <a href={`${im.url}?dl=1`} className="rounded bg-white/90 p-1 text-[11px] text-black" title="Download PNG" data-action="download"><Download className="h-3.5 w-3.5" /></a>
                    {canEdit && <button onClick={() => onVariation(j, im.index)} className="rounded bg-white/90 p-1 text-black" title="Make a variation of this image" data-action="variation"><Shuffle className="h-3.5 w-3.5" /></button>}
                  </div>
                </div>
              ))}
            </div>}
          {j.state === "done" && <Caption text={caption} />}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted">
            {j.reference && <span title={j.reference.detail}>Ref: {j.reference.label}</span>}
            {j.usage?.total_tokens != null && <span title="Image tokens reported by OpenAI for this request (billed to your OpenAI account)">{j.usage.total_tokens.toLocaleString()} OpenAI tokens</span>}
            {j.seconds != null && j.state !== "queued" && <span>{Math.round(j.seconds)} s</span>}
            {canEdit && !ACTIVE(j) && <span className="ml-auto flex gap-2">
              <button className="hover:text-primary" onClick={() => onUsePrompt(j)} title="Load this prompt and its settings">Use prompt</button>
              <button className="inline-flex items-center gap-0.5 hover:text-primary" onClick={() => onRegenerate(j)} data-action="regenerate"><RefreshCw className="h-3 w-3" />Again</button>
              <button className="hover:text-danger" onClick={() => onDelete(j)} aria-label="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
            </span>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Workspace({ pid, opts, canEdit }: { pid: string; opts: Options; canEdit: boolean }) {
  const qc = useQueryClient();
  const base = `/api/m/airender/projects/${pid}`;
  const info = useQuery({ queryKey: ["air-info", pid], queryFn: () => api.get<ProjectInfo>(base), retry: false });
  const jobsQ = useQuery({ queryKey: ["air-jobs", pid], enabled: info.isSuccess, queryFn: () => api.get<{ jobs: AirJob[] }>(`${base}/jobs`),
    refetchInterval: q => ((q.state.data?.jobs ?? []).some(ACTIVE) ? 1000 : false) });
  const [settings, setSettings] = useState<AirSettings | null>(null);
  const [userPrompt, setUserPrompt] = useState("");
  const [polishAI, setPolishAI] = useState(true);
  const [refined, setRefined] = useState<(Refined & { key: string }) | null>(null);
  const [prompt, setPrompt] = useState("");
  const [negText, setNegText] = useState("");
  const [ref, setRef] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<{ job: AirJob; index: number } | null>(null);
  const [studioJob, setStudioJob] = useState<string | null>(null);
  const autoRef = useRef(false);

  useEffect(() => { if (info.data && !settings) setSettings({ ...opts.defaults, finish: info.data.finish }); }, [info.data, settings, opts]);
  const refs = info.data?.references ?? [];
  useEffect(() => { if (!ref && refs[0]) setRef(refs[0].id); }, [refs, ref]);

  // No Cycles render of this part yet: make a quick Mesh Studio preview of the exact model to use as the reference.
  const makeStudioRef = async () => {
    try { const r = await api.post<{ id: string; state: string }>(`${base}/references/studio`); setStudioJob(r.state === "done" ? null : r.id); if (r.state === "done") await info.refetch(); }
    catch (e) { if (autoRef.current) return; toast.error(e instanceof ApiError ? e.message : "Couldn't make a studio reference"); }
  };
  useEffect(() => {
    if (!info.data || autoRef.current || !canEdit) return;
    autoRef.current = true;
    if (info.data.can_make_reference && !info.data.references.some(r => r.kind !== "model")) makeStudioRef();
  }, [info.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const sj = useQuery({ queryKey: ["air-studio", pid, studioJob], enabled: !!studioJob, queryFn: () => api.get<{ state: string; progress: number | null; error: string | null }>(`${base}/references/studio/${studioJob}`),
    refetchInterval: q => (q.state.data && !["queued", "running"].includes(q.state.data.state) ? false : 1000) });
  useEffect(() => {
    if (!sj.data || ["queued", "running"].includes(sj.data.state)) return;
    setStudioJob(null);
    info.refetch().then(r => { const best = r.data?.references[0]; if (best && best.kind !== "model") setRef(best.id); });
  }, [sj.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const err = info.error instanceof ApiError ? info.error : null;
  if (err) return <div className="flex flex-1 items-center justify-center p-8"><EmptyState icon={<Sparkles className="h-5 w-5" />} title={err.status === 409 ? "No verified model yet" : "Can't open this project"} body={err.message}
    action={err.status === 409 ? <Link to={`/app/projects/${pid}`}><Button>Open in Design Studio</Button></Link> : undefined} /></div>;
  if (!info.data || !settings) return <div className="flex flex-1 items-center justify-center"><Spinner className="h-6 w-6" /></div>;

  const d = info.data;
  const jobs = jobsQ.data?.jobs ?? d.jobs;
  const curKey = refineKey(settings, userPrompt);
  const stale = !!refined && refined.key !== curKey;
  const refObj = refs.find(r => r.id === ref) ?? refs[0];
  const running = jobs.filter(ACTIVE);
  const latestDone = jobs.find(j => j.state === "done");
  const q = opts.qualities.find(x => x.id === settings.quality);

  const doRefine = async () => {
    setBusy("refine");
    try {
      const r = await api.post<Refined>(`${base}/refine`, { settings, user_prompt: userPrompt, engine: polishAI ? "ai" : "template" });
      setRefined({ ...r, key: curKey }); setPrompt(r.prompt); setNegText(negativesToText(r.negative));
      if (r.note) toast.message(r.note);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't refine the prompt"); } finally { setBusy(null); }
  };
  const generate = async (over?: { settings?: AirSettings; prompt?: string; negative?: string[]; variation_of?: { job: string; index: number }; reference?: string | null }) => {
    setBusy("gen");
    try {
      const edited = refined && (prompt !== refined.prompt || negativesToText(textToNegatives(negText)) !== negativesToText(refined.negative));
      await api.post<AirJob>(`${base}/generate`, {
        settings: over?.settings ?? settings, prompt: over?.prompt ?? prompt, negative: over?.negative ?? textToNegatives(negText),
        engine: over?.prompt ? "edited" : edited ? "edited" : refined?.engine ?? "template", reference: over?.reference ?? refObj?.id ?? null,
        variation_of: over?.variation_of ?? null,
      });
      await qc.invalidateQueries({ queryKey: ["air-jobs", pid] });
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 428)) await qc.invalidateQueries({ queryKey: ["airender-integration"] });
      toast.error(e instanceof ApiError ? e.message : "Couldn't start the render");
    } finally { setBusy(null); }
  };
  const regenerate = (j: AirJob) => generate({ settings: j.settings, prompt: j.prompt, negative: j.negative, reference: j.reference?.id });
  const variation = (j: AirJob, index: number) => { setLightbox(null); generate({ settings: { ...j.settings, variants: 1 }, prompt: j.prompt, negative: j.negative, variation_of: { job: j.id, index }, reference: j.reference?.id }); };
  const usePrompt = (j: AirJob) => {
    setSettings({ ...j.settings }); setPrompt(j.prompt); setNegText(negativesToText(j.negative));
    setRefined({ prompt: j.prompt, negative: j.negative, engine: j.engine === "ai" ? "ai" : "template", note: null, key: refineKey(j.settings, userPrompt) });
    toast.success("Prompt and settings loaded");
  };
  const remove = async (j: AirJob) => {
    try { await api.del(`${base}/jobs/${j.id}`); await qc.invalidateQueries({ queryKey: ["air-jobs", pid] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't delete"); }
  };
  const lbImg = lightbox?.job.images.find(i => i.index === lightbox.index);

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[272px_minmax(0,1fr)_340px] lg:overflow-hidden">
      <aside className="min-h-0 overflow-y-auto border-r border-border bg-panel" data-panel="settings">
        {canEdit ? <SettingsPanel opts={opts} value={settings} onChange={setSettings} materialFinish={d.finish} />
          : <div className="p-4 text-sm text-muted">You have view access: browse and download AI renders. Engineers can make new ones.</div>}
      </aside>

      <section className="min-h-0 min-w-0 space-y-4 overflow-y-auto bg-panel2/40 p-5" data-panel="flow">
        {canEdit && <>
          <Step n={1} title="Refine" active done={!!refined && !stale}>
            <div className="grid gap-4 md:grid-cols-[200px_1fr]">
              <div data-reference>
                <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted">Geometry reference</div>
                <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden rounded-md border border-border">
                  {refObj ? <img src={refObj.url} alt="Reference render" className="h-full w-full object-contain" data-ref-img={refObj.id} /> : <BoxIcon className="h-8 w-8 text-muted" />}
                  {studioJob && <div className="absolute bottom-2 flex items-center gap-1.5 whitespace-nowrap rounded-full bg-panel/95 px-2.5 py-1 text-[11px] text-muted shadow-card" data-studio-ref><Spinner className="h-3 w-3" />Rendering a studio reference…</div>}
                </div>
                {refs.length > 1 && <select className="input mt-1.5 h-8 py-0 text-[12px]" value={refObj?.id} onChange={e => setRef(e.target.value)} aria-label="Reference image" data-field="reference">
                  {refs.map(r => <option key={r.id} value={r.id}>{r.label}{r.detail ? ` · ${r.detail}` : ""}</option>)}</select>}
                <p className="mt-1.5 text-[11.5px] leading-snug text-muted">{refObj?.kind === "model" ? "From the verified build." : "A render of the exact model."} Sent to OpenAI so the AI keeps the shape.</p>
                {d.can_make_reference && !studioJob && !refs.some(r => r.kind !== "model") && <button className="mt-1 text-[12px] text-primary hover:underline" onClick={makeStudioRef}><Aperture className="mr-1 inline h-3 w-3" />Make a studio reference</button>}
              </div>
              <div className="flex min-w-0 flex-col gap-2.5">
                <label className="text-[12.5px] font-medium" htmlFor="air-user-prompt">Describe the shot (optional)</label>
                <textarea id="air-user-prompt" className="input min-h-[92px] resize-y py-2 text-[13px]" maxLength={1000} value={userPrompt} onChange={e => setUserPrompt(e.target.value)}
                  placeholder="e.g. hero shot for a product page, morning light, a few metal chips on the bench" data-field="user-prompt" />
                <div className="text-[11.5px] text-muted">Part facts used: {d.facts.name}{d.facts.material ? ` · ${d.facts.material}` : ""}{d.facts.size_mm ? ` · ${d.facts.size_mm.join(" × ")} mm` : ""}{d.facts.features.length ? ` · ${d.facts.features.length} named features` : ""}</div>
                <div className="mt-auto flex flex-wrap items-center gap-3">
                  <Button icon={<Wand2 className="h-4 w-4" />} loading={busy === "refine"} onClick={doRefine} data-action="refine">{refined ? "Refine again" : "Refine prompt"}</Button>
                  <label className="flex items-center gap-1.5 text-[12.5px]"><input type="checkbox" checked={polishAI} onChange={e => setPolishAI(e.target.checked)} data-field="polish" />Polish with AI <span className="text-muted">(about 1 to 3 tokens)</span></label>
                </div>
              </div>
            </div>
          </Step>

          <Step n={2} title="Review the prompt" active={!!refined} done={!!refined && !stale}
            aside={refined && <Badge tone={refined.engine === "ai" ? "primary" : "neutral"}>{refined.engine === "ai" ? "Polished by AI" : "Standard template"}</Badge>}>
            {!refined ? <p className="text-sm text-muted">Refine first. You can edit every word before anything is sent to OpenAI.</p> : <div className="space-y-2.5">
              {stale && <p className="flex items-center gap-1.5 text-[12px] text-warning" data-stale><AlertTriangle className="h-3.5 w-3.5" />Settings changed since this prompt was written. Refine again to include them.</p>}
              <textarea className="input min-h-[170px] w-full resize-y py-2 font-mono text-[12.5px] leading-relaxed" value={prompt} onChange={e => setPrompt(e.target.value)} aria-label="Image prompt" data-field="prompt" />
              <div className="flex flex-wrap items-center gap-3 text-[11.5px]">
                {keepsGeometry(prompt, GEOMETRY_START) ? <span className="inline-flex items-center gap-1 text-success" data-geometry="kept"><Lock className="h-3 w-3" />Geometry lock in the prompt</span>
                  : <span className="inline-flex items-center gap-1 text-warning" data-geometry="readded"><Lock className="h-3 w-3" />The geometry lock is added back when sent</span>}
                <span className="text-muted">{wordCount(prompt)} words</span>
              </div>
              <label className="block text-[12.5px] font-medium">Avoid (one per line)</label>
              <textarea className="input min-h-[96px] w-full resize-y py-2 text-[12.5px]" value={negText} onChange={e => setNegText(e.target.value)} aria-label="Negative instructions" data-field="negative" />
            </div>}
          </Step>

          <Step n={3} title="Generate" active={!!refined}>
            <div className="flex flex-wrap items-center gap-3">
              <Button icon={<Sparkles className="h-4 w-4" />} disabled={!refined || prompt.trim().length < 10} loading={busy === "gen"} onClick={() => generate()} data-action="generate">
                Generate {settings.variants} {settings.variants === 1 ? "image" : "images"} <span className="font-normal opacity-80">· {sizeLabel(settings.size)} · {q?.label}</span></Button>
              <span className="text-[12px] text-muted">About {etaSeconds(q?.eta_s ?? 45, settings.variants)} s. Billed by OpenAI to your key ({opts.model}).</span>
            </div>
            {running.length > 0 && <div className="mt-3 space-y-2">{running.map(j => <Elapsed key={j.id} job={j} />)}</div>}
          </Step>
        </>}

        {latestDone && latestDone.images[0] && (
          <Card className="overflow-hidden" data-latest={latestDone.id}>
            <button className="block w-full bg-panel2" onClick={() => setLightbox({ job: latestDone, index: 1 })}><img src={latestDone.images[0].url} alt="Latest AI-generated visual" className="mx-auto max-h-[520px] object-contain" /></button>
            <div className="border-t border-border px-4 py-2.5"><Caption text={d.caption} /></div>
          </Card>
        )}
      </section>

      <aside className="flex min-h-0 flex-col border-l border-border bg-panel">
        <div className="flex h-10 shrink-0 items-center border-b border-border px-3 text-[13px] font-medium">Gallery{running.length > 0 && <span className="ml-1.5 rounded-full bg-primary px-1.5 text-[10.5px] font-semibold text-primary-fg">{running.length}</span>}<span className="ml-auto text-[11.5px] font-normal text-muted">{jobs.length} {jobs.length === 1 ? "request" : "requests"}</span></div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <Gallery jobs={jobs} opts={opts} canEdit={canEdit} caption={d.caption} onVariation={variation} onRegenerate={regenerate} onUsePrompt={usePrompt} onDelete={remove} onOpen={(job, index) => setLightbox({ job, index })} />
        </div>
      </aside>

      <Modal open={!!lightbox} onOpenChange={v => !v && setLightbox(null)} wide title="AI-generated visual" description={lightbox ? `${d.project.name} · ${ago(lightbox.job.created_at)}` : undefined}
        footer={lightbox && lbImg ? <>
          {canEdit && <Button variant="secondary" icon={<Shuffle className="h-4 w-4" />} onClick={() => variation(lightbox.job, lightbox.index)}>Variation</Button>}
          <a href={`${lbImg.url}?dl=1`}><Button icon={<Download className="h-4 w-4" />}>Download PNG</Button></a></> : undefined}>
        {lightbox && lbImg && <div className="space-y-3">
          <img src={lbImg.url} alt="AI-generated visual" className="w-full rounded-md border border-border" data-lightbox />
          <Caption text={d.caption} />
          {lightbox.job.reference_url && <details className="text-[12px] text-muted"><summary className="cursor-pointer">Reference and prompt sent</summary>
            <div className="mt-2 grid gap-3 sm:grid-cols-[160px_1fr]"><img src={lightbox.job.reference_url} alt="Reference sent" className="rounded border border-border" />
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-panel2 p-2 text-[11.5px]">{lightbox.job.sent_prompt ?? lightbox.job.prompt}</pre></div></details>}
        </div>}
      </Modal>
    </div>
  );
}

function Picker({ projects, loading, onPick }: { projects: Project[]; loading: boolean; onPick: (id: string) => void }) {
  const built = projects.filter(p => p.builds > 0 && p.last_status?.ok);
  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <h2 className="text-[20px] font-semibold tracking-tight">AI marketing visuals of your verified parts</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">Pick a project. A render of its real geometry is the reference, your settings and words become a precise image prompt you review, and OpenAI makes the visual on your own key. AI images are illustrative: for exact geometry use Mesh Studio renders or drawings.</p>
      <div className="mt-7 label">Projects with a verified model</div>
      {loading ? <div className="mt-4"><Spinner /></div> : built.length === 0
        ? <Card className="mt-3 p-6 text-sm text-muted">No verified builds yet. Build a part in the Design Studio first.</Card>
        : <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {built.map(p => <PartCard key={p.id} id={p.id} name={p.name} thumbnail={p.thumbnail} version={p.last_status?.build_id ?? 0} updatedAt={p.updated_at}
            sub={p.last_status?.material && p.last_status.material !== "unspecified" ? String(p.last_status.material) : "Material not set"} onPick={onPick} />)}
        </div>}
    </div>
  );
}

export default function AIRenderStudio({ projectId }: ModuleAppProps) {
  const { me } = useSession();
  const [params, setParams] = useSearchParams();
  const [pid, setPid] = useState<string | null>(projectId);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const canEdit = me?.org?.role !== "viewer";
  const integ = useIntegration();
  const opts = useQuery({ queryKey: ["air-options"], queryFn: () => api.get<Options>("/api/m/airender/options"), staleTime: 600_000 });
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects") });
  const choose = (id: string | null) => {
    setPid(id);
    const next = new URLSearchParams(params);
    next.delete("project");
    if (id) next.set("project", id);
    setParams(next, { replace: true });
  };
  const name = useMemo(() => projects.data?.items.find(p => p.id === pid)?.name, [projects.data, pid]);
  if (!opts.data || !integ.data) return opts.error || integ.error ? <div className="p-10 text-center text-muted">{((opts.error ?? integ.error) as Error).message}</div> : <PageLoader />;
  const st = integ.data;
  const ready = st.has_key && st.consent.given;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-panel px-4 py-2">
        {projectId ? <Link to={`/app/projects/${projectId}`} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Back to project</Link>
          : <Link to="/app/modules" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="h-4 w-4" />Modules</Link>}
        <div className="h-5 w-px bg-border" />
        <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-primary" /><h1 className="text-[15px] font-semibold">AI Render Studio</h1><StatusBadge status="live" /><Badge tone="accent">Beta</Badge><Badge>Uses your OpenAI key</Badge></div>
        {pid && ready && <div className="flex min-w-0 items-center gap-2 rounded border border-border bg-panel2 px-2.5 py-1 text-[13px]">
          <BoxIcon className="h-3.5 w-3.5 text-muted" /><span className="max-w-[240px] truncate font-medium">{name ?? "…"}</span><span className="text-muted">verified model</span></div>}
        <div className="ml-auto flex items-center gap-2">
          {pid && <Link to={`/app/modules/mesh?project=${pid}`} className="hidden text-[12px] text-muted hover:text-primary md:inline">Exact renders in Mesh Studio →</Link>}
          <FileButtons ext="fwrender" saveUrl={pid && ready ? moduleExportUrl("ai", pid) : null} saveName={`${name ?? "ai-renders"}.fwrender`} />
          {ready && <Button size="sm" variant="ghost" icon={<Settings2 className="h-4 w-4" />} onClick={() => setSettingsOpen(true)} data-action="air-settings">OpenAI</Button>}
          {pid && ready && <Button size="sm" variant="secondary" icon={<FolderOpen className="h-4 w-4" />} onClick={() => choose(null)}>Change project</Button>}
        </div>
      </header>
      {!ready ? <div className="min-h-0 flex-1 overflow-y-auto"><Setup st={st} /></div>
        : !pid ? <div className="min-h-0 flex-1 overflow-y-auto"><Picker projects={projects.data?.items ?? []} loading={projects.isLoading} onPick={choose} /></div>
        : <Workspace key={pid} pid={pid} opts={opts.data} canEdit={canEdit} />}
      <Modal open={settingsOpen} onOpenChange={setSettingsOpen} title="OpenAI integration" description="The workspace's own OpenAI key and the consent to send images to OpenAI.">
        <div className="space-y-5"><OpenAIKeyCard /><div className="border-t border-border pt-4"><ConsentCard /></div></div>
      </Modal>
    </div>
  );
}
