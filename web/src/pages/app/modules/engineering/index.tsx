import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, Calculator, ClipboardCheck, FileSignature, FolderOpen, Library as LibraryIcon, Play, Ruler, Search, ShieldAlert, Sparkles, Weight, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card, EmptyState, Modal, PageLoader, Spinner, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { cx } from "@/lib/format";
import type { ModuleAppProps } from "../registry";
import { ModuleHeader } from "../ModuleHeader";
import { CalcForm, LevelBadge, type LoadOption, ResultView } from "./CalcForm";
import { type CalcResult, type CalcSchema, type CalcSet, type Catalog, type FormState, type LoadCase, type ModelInfo, type Suggestion, type UnitSystem, applyPrefill, exampleKeys, fmt, initialForm, toInputs } from "./types";
import SetsPanel from "./Sets";
import LoadCasesPanel from "./LoadCases";
import StackupsPanel from "./Stackups";
import ReviewPanel from "./Review";
import LibraryPanel from "./Library";

interface ProjectRow { id: string; name: string; built: boolean; part: string | null; material: string | null; thumbnail: string | null; sets: number; signed: number; model_changed?: number; load_cases: number }

export interface Editing { setId: string; itemId: string; title: string; confirmed?: string[] }

export default function EngineeringApp({ projectId }: ModuleAppProps) {
  const [params, setParams] = useSearchParams();
  const [pid, setPid] = useState<string | null>(projectId);
  const [tab, setTab] = useState(params.get("tab") || "calc");
  const [sys, setSys] = useState<UnitSystem>(() => { try { return (localStorage.getItem("fw_eng_units") as UnitSystem) || "SI"; } catch { return "SI"; } });
  useEffect(() => { try { localStorage.setItem("fw_eng_units", sys); } catch { /* ignore */ } }, [sys]);
  const cat = useQuery({ queryKey: ["eng-catalog"], queryFn: () => api.get<Catalog>("/api/m/engineering/catalog"), staleTime: 600_000 });
  const projects = useQuery({ queryKey: ["eng-projects"], queryFn: () => api.get<{ items: ProjectRow[] }>("/api/m/engineering/projects") });
  const model = useQuery({ queryKey: ["eng-model", pid], enabled: !!pid, queryFn: () => api.get<ModelInfo>(`/api/m/engineering/projects/${pid}/model`), staleTime: 60_000 });
  // calculator workspace state lives here so other tabs can open a calculator pre-filled
  const [calcId, setCalcId] = useState("beam");
  const [form, setForm] = useState<FormState | null>(null);
  const [prov, setProv] = useState<Record<string, string> | null>(null);
  const [result, setResult] = useState<CalcResult | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [confirmed, setConfirmed] = useState<string[]>([]);

  useEffect(() => { if (projectId) setPid(projectId); }, [projectId]);
  const choose = (id: string | null) => {
    setPid(id); setEditing(null); setProv(null);
    if (id) params.set("project", id); else params.delete("project");
    setParams(params, { replace: true });
  };
  const goTab = (t: string) => { setTab(t); params.set("tab", t); setParams(params, { replace: true }); };

  if (cat.isError) return <div className="p-10 text-center text-muted">{cat.error instanceof ApiError ? cat.error.message : "Failed to load"}</div>;
  if (!cat.data) return <PageLoader />;
  const c = cat.data;
  const calc = c.calculators.find(x => x.id === calcId) ?? c.calculators[0]!;
  const openCalc = (id: string, inputs?: Record<string, unknown>, provenance?: Record<string, string> | null, edit?: Editing | null) => {
    const s = c.calculators.find(x => x.id === id);
    if (!s) return;
    setCalcId(id);
    setForm(inputs ? applyPrefill(s, initialForm(s), inputs) : initialForm(s));
    setProv(provenance ?? null); setResult(null); setEditing(edit ?? null); setConfirmed(edit?.confirmed ?? []);
    goTab("calc");
  };
  const current = projects.data?.items.find(p => p.id === pid);

  return (
    <div>
    <ModuleHeader code="engineering" icon={<Calculator className="h-4 w-4" />} title="Engineering Advisor" projectId={pid} projectName={current?.name}
      projects={projects.data?.items.map(p => ({ id: p.id, name: p.name }))} onSwitch={choose}
      actions={<>
        {!pid && <><FolderOpen className="h-4 w-4 text-muted" />
          <select aria-label="Project" className="input h-8 w-[240px] py-0 text-[12.5px]" value="" onChange={e => choose(e.target.value || null)}>
            <option value="">No part: standalone calculators</option>
            {projects.data?.items.map(p => <option key={p.id} value={p.id}>{p.name}{p.built ? "" : " (not built)"}</option>)}
          </select></>}
        <div className="inline-flex rounded border border-border bg-panel p-0.5 text-[12px]" role="group" aria-label="Display units">
          {(["SI", "US"] as const).map(s => <button key={s} onClick={() => setSys(s)} className={cx("rounded px-2 py-0.5", sys === s ? "bg-primary text-white" : "text-muted")}>{s === "SI" ? "mm · N · MPa" : "in · lbf · ksi"}</button>)}
        </div>
      </>} />
    <div className="mx-auto max-w-[1500px] px-5 py-5">
      <Disclaimer cat={c} />
      <Tabs value={tab} onValueChange={goTab}>
        <TabList className="mb-4">
          <Tab value="calc"><Calculator className="h-4 w-4" />Calculators</Tab>
          <Tab value="sets"><FileSignature className="h-4 w-4" />Calculation sets{current?.sets ? <Badge className="ml-1">{current.sets}</Badge> : null}</Tab>
          <Tab value="loads"><Weight className="h-4 w-4" />Load cases</Tab>
          <Tab value="stack"><Ruler className="h-4 w-4" />Stack-ups</Tab>
          <Tab value="review"><ClipboardCheck className="h-4 w-4" />Failure modes</Tab>
          <Tab value="library"><LibraryIcon className="h-4 w-4" />Library</Tab>
        </TabList>
        <TabPanel value="calc">
          <CalcWorkspace cat={c} calc={calc} form={form ?? initialForm(calc)} setForm={setForm} prov={prov} setProv={setProv} result={result} setResult={setResult}
            pick={id => openCalc(id)} sys={sys} pid={pid} model={model.data} modelLoading={model.isLoading} openCalc={openCalc} editing={editing} setEditing={setEditing}
            confirmed={confirmed} setConfirmed={setConfirmed} />
        </TabPanel>
        <TabPanel value="sets">{pid ? <SetsPanel pid={pid} cat={c} sys={sys} openCalc={openCalc} /> : <NeedProject />}</TabPanel>
        <TabPanel value="loads">{pid ? <LoadCasesPanel pid={pid} cat={c} model={model.data} /> : <NeedProject />}</TabPanel>
        <TabPanel value="stack">{pid ? <StackupsPanel pid={pid} cat={c} sys={sys} /> : <NeedProject />}</TabPanel>
        <TabPanel value="review">{pid ? <ReviewPanel pid={pid} cat={c} openCalc={openCalc} /> : <NeedProject />}</TabPanel>
        <TabPanel value="library"><LibraryPanel cat={c} /></TabPanel>
      </Tabs>
    </div>
    </div>
  );
}

function NeedProject() {
  return <EmptyState icon={<FolderOpen className="h-5 w-5" />} title="Choose a project" body="Load cases, calculation sets, stack-ups and the failure-mode review are stored with a project. Pick one in the project selector above." />;
}

function Disclaimer({ cat }: { cat: Catalog }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-panel px-4 py-2 text-[12px] text-muted">
      <ShieldAlert className="h-4 w-4 text-accent" />
      <span>Hand-calculation methods with cited sources. Results are engineering estimates until a named engineer signs the set; nothing here is a validated simulation or a certification.</span>
      <span className="ml-auto flex items-center gap-1.5">{["recommended_check", "preliminary_estimate", "verified_calculation", "validated_simulation"].map(l => <LevelBadge key={l} level={l} cat={cat} />)}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ calculators tab */
function CalcWorkspace({ cat, calc, form, setForm, prov, setProv, result, setResult, pick, sys, pid, model, modelLoading, openCalc, editing, setEditing, confirmed, setConfirmed }: {
  cat: Catalog; calc: CalcSchema; form: FormState; setForm: (f: FormState) => void; prov: Record<string, string> | null; setProv: (p: Record<string, string> | null) => void;
  result: CalcResult | null; setResult: (r: CalcResult | null) => void; pick: (id: string) => void; sys: UnitSystem; pid: string | null;
  model: ModelInfo | undefined; modelLoading: boolean; openCalc: (id: string, inputs?: Record<string, unknown>, p?: Record<string, string> | null, e?: Editing | null) => void;
  editing: Editing | null; setEditing: (e: Editing | null) => void; confirmed: string[]; setConfirmed: (c: string[]) => void;
}) {
  const qc = useQueryClient();
  const lcq = useQuery({ queryKey: ["eng-lc", pid], enabled: !!pid, queryFn: () => api.get<{ items: LoadCase[] }>(`/api/m/engineering/projects/${pid}/loadcases`) });
  const loadOpts = useMemo<(LoadOption & { lc: string; name: string })[]>(() => (lcq.data?.items ?? []).flatMap(lc => lc.loads
    .filter(l => (l.type === "force" || l.type === "moment") && l.value_canonical !== undefined)
    .map(l => ({ label: `${lc.name}: ${l.name} ${fmt(l.value)} ${l.unit}`, kind: l.type as "force" | "moment", value: l.value_canonical!,
      unit: cat.units[l.type]?.canonical ?? "", lc: lc.name, name: l.name }))), [lcq.data, cat]);
  const examples = exampleKeys(calc, form).filter(k => !confirmed.includes(k));
  const pickLoad = (key: string, l: LoadOption) => {
    const o = loadOpts.find(x => x.label === l.label);
    setForm({ ...form, [key]: { value: String(+l.value.toPrecision(10)), unit: l.unit } });
    setProv({ ...(prov ?? {}), [key]: `Load case “${o?.lc ?? ""}”: ${o?.name ?? l.label}` });
    setResult(null);
  };
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  useEffect(() => { setError(null); }, [calc.id]);
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    return cat.calculators.filter(x => !t || [x.name, x.summary, x.category, ...x.keywords].join(" ").toLowerCase().includes(t));
  }, [cat, q]);
  const cats = [...new Set(filtered.map(x => x.category))];
  const run = async () => {
    setBusy(true); setError(null);
    try { setResult(await api.post<CalcResult>("/api/m/engineering/run", { calc_id: calc.id, inputs: toInputs(calc, form) })); }
    catch (e) { setResult(null); setError(e instanceof ApiError ? e.message : "Calculation failed"); }
    finally { setBusy(false); }
  };
  const saveEdit = async () => {
    if (!editing || !pid) return;
    setBusy(true);
    try {
      await api.patch<CalcSet>(`/api/m/engineering/projects/${pid}/sets/${editing.setId}/items/${editing.itemId}`, { calc_id: calc.id, inputs: toInputs(calc, form), title: editing.title, source: prov, confirmed });
      toast.success("Calculation updated in the set"); qc.invalidateQueries({ queryKey: ["eng-sets", pid] }); qc.invalidateQueries({ queryKey: ["eng-projects"] });
      setEditing(null);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Update failed"); } finally { setBusy(false); }
  };
  const strip = model?.available ? (model.suggestions ?? []) : [];
  return (
    <div className="space-y-3">
    {pid && strip.length > 0 && (
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-primary/25 bg-primary-soft/40 px-3 py-2" data-panel="model-checks">
        <span className="mr-1 inline-flex items-center gap-1.5 text-[12px] font-medium text-primary"><Sparkles className="h-3.5 w-3.5" />Checks from {model?.part || "the model"}</span>
        {strip.map((s: Suggestion, i) => (
          <button key={i} data-suggestion={s.calc_id} title={Object.values(s.provenance)[0] ?? s.title}
            onClick={() => { if (s.calc_id === calc.id && !editing) { setForm(applyPrefill(calc, form, s.inputs)); setProv(s.provenance); setResult(null); } else openCalc(s.calc_id, s.inputs, s.provenance); }}
            className={cx("rounded-full border px-2.5 py-0.5 text-[12px] hover:bg-primary-soft", s.calc_id === calc.id && prov && Object.keys(s.provenance).every(k => prov[k] === s.provenance[k]) ? "border-primary bg-primary-soft text-primary" : "border-primary/30 bg-panel text-primary")}>{s.title}</button>))}
      </div>)}
    <div className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)] xl:grid-cols-[250px_minmax(0,1fr)_minmax(0,1.05fr)]">
      {/* catalogue */}
      <aside className="space-y-3">
        <div className="relative"><Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><input className="input h-8 pl-8 text-[13px]" placeholder="Search calculators" value={q} onChange={e => setQ(e.target.value)} aria-label="Search calculators" /></div>
        <nav className="space-y-3" aria-label="Calculators">
          {cats.map(cg => (
            <div key={cg}>
              <div className="label mb-1 px-1">{cg}</div>
              {filtered.filter(x => x.category === cg).map(x => (
                <button key={x.id} data-calc={x.id} onClick={() => pick(x.id)} className={cx("block w-full rounded px-2 py-1.5 text-left text-[13px]", x.id === calc.id ? "bg-primary-soft font-medium text-primary" : "hover:bg-text/5")}>{x.name}</button>
              ))}
            </div>))}
          {!cats.length && <div className="px-1 text-[12px] text-muted">No calculator matches.</div>}
        </nav>
        {pid && <ProjectLink model={model} loading={modelLoading} />}
      </aside>
      {/* form */}
      <Card className="p-4">
        <div className="mb-3 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-[16px] font-semibold">{calc.name}</h2>
            <p className="mt-0.5 text-[12.5px] text-muted">{calc.summary}</p>
          </div>
        </div>
        {editing && <div className="mb-3 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary-soft px-3 py-2 text-[12.5px] text-primary"><FileSignature className="h-4 w-4" />Editing “{editing.title}” in a calculation set. Saving re-runs it and invalidates any sign-off on that set.<button className="ml-auto underline" onClick={() => setEditing(null)}>Stop editing</button></div>}
        <CalcForm calc={calc} form={form} setForm={f => { setForm(f); }} prov={prov} examples={examples}
          onConfirm={k => setConfirmed([...confirmed, k])} loads={pid ? loadOpts : []} onLoadPick={pickLoad} />
        {examples.length > 0 && <div className="mt-3 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-[12.5px]" data-panel="examples">
          <b className="text-warning">Example loads.</b> {examples.length === 1 ? "One load is" : `${examples.length} loads are`} still the calculator&apos;s illustrative value. Replace {examples.length === 1 ? "it" : "them"} with your loads{pid ? ", pick a load case," : ""} or keep {examples.length === 1 ? "it" : "them"} deliberately. A set can&apos;t be signed while example values remain.</div>}
        {error && <div className="mt-3 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-[13px] text-danger" role="alert">{error}</div>}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button icon={<Play className="h-4 w-4" />} loading={busy} onClick={run} data-action="run">Calculate</Button>
          {editing ? <Button variant="accent" loading={busy} onClick={saveEdit} data-action="save-edit">Save to set</Button>
            : pid && <Button variant="secondary" icon={<Plus className="h-4 w-4" />} disabled={!result || !cat.can_edit} onClick={() => setAddOpen(true)} data-action="add-to-set">Add to calculation set</Button>}
          <Button variant="ghost" onClick={() => { setForm(initialForm(calc)); setProv(null); setResult(null); }}>Reset</Button>
        </div>
      </Card>
      {/* results */}
      <Card className="p-4 lg:col-span-2 xl:col-span-1" data-panel="results">
        {result ? <ResultView r={result} cat={cat} sys={sys} />
          : <div className="flex h-full min-h-[280px] flex-col items-center justify-center text-center text-[13px] text-muted"><Calculator className="mb-2 h-6 w-6" />Enter the inputs and press Calculate. Results show every step, the equations, the source and the advice level.</div>}
      </Card>
      {addOpen && result && pid && <AddToSet pid={pid} calc={calc} inputs={toInputs(calc, form)} prov={prov} confirmed={confirmed} examples={examples.length} onClose={() => setAddOpen(false)} />}
    </div>
    </div>
  );
}

function AddToSet({ pid, calc, inputs, prov, confirmed, examples, onClose }: { pid: string; calc: CalcSchema; inputs: Record<string, unknown>; prov: Record<string, string> | null; confirmed: string[]; examples: number; onClose: () => void }) {
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["eng-sets", pid], queryFn: () => api.get<{ items: CalcSet[] }>(`/api/m/engineering/projects/${pid}/sets`) });
  const [sel, setSel] = useState<string>("new");
  const [name, setName] = useState("Design checks");
  const [title, setTitle] = useState(calc.name);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (sets.data?.items.length) setSel(sets.data.items[0]!.id); }, [sets.data]);
  const save = async () => {
    setBusy(true);
    try {
      let sid = sel;
      if (sel === "new") sid = (await api.post<CalcSet>(`/api/m/engineering/projects/${pid}/sets`, { name })).id;
      await api.post(`/api/m/engineering/projects/${pid}/sets/${sid}/items`, { calc_id: calc.id, inputs, title, source: prov, confirmed });
      qc.invalidateQueries({ queryKey: ["eng-sets", pid] }); qc.invalidateQueries({ queryKey: ["eng-projects"] });
      toast.success("Added to the calculation set"); onClose();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  const target = sets.data?.items.find(s => s.id === sel);
  return (
    <Modal open onOpenChange={v => !v && onClose()} title="Add to calculation set" description="The calculation is re-run on the server and stored with its inputs, working and sources."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save} data-action="confirm-add">Add</Button></>}>
      {!sets.data ? <Spinner /> : (
        <div className="space-y-3">
          <label className="block space-y-1"><span className="text-[13px] font-medium">Set</span>
            <select className="input" value={sel} onChange={e => setSel(e.target.value)} aria-label="Calculation set">
              {sets.data.items.map(s => <option key={s.id} value={s.id}>{s.name} ({s.items.length})</option>)}
              <option value="new">New set…</option>
            </select></label>
          {sel === "new" && <label className="block space-y-1"><span className="text-[13px] font-medium">New set name</span><input className="input" value={name} onChange={e => setName(e.target.value)} /></label>}
          <label className="block space-y-1"><span className="text-[13px] font-medium">Title</span><input className="input" value={title} onChange={e => setTitle(e.target.value)} aria-label="Calculation title" /></label>
          {examples > 0 && <div className="rounded border border-warning/30 bg-warning/5 px-3 py-2 text-[12.5px]">This calculation still uses example load values. You can add it now, but the set can&apos;t be signed until they are replaced or confirmed.</div>}
          {target?.status.state === "signed" && <div className="rounded border border-warning/30 bg-warning/5 px-3 py-2 text-[12.5px]">This set is signed. Adding a calculation invalidates the signature; it will need to be signed again.</div>}
        </div>
      )}
    </Modal>
  );
}

function ProjectLink({ model, loading }: { model: ModelInfo | undefined; loading: boolean }) {
  if (loading) return <Card className="flex items-center gap-2 p-3 text-[12px] text-muted"><Spinner className="h-4 w-4" />Reading the model…</Card>;
  if (!model) return null;
  if (!model.available) return <Card className="p-3 text-[12px] text-muted">{model.reason}</Card>;
  const m = model.mass;
  return (
    <Card className="p-3 text-[12px]" data-panel="project-link">
      <div className="mb-2 flex items-center gap-1.5 font-semibold"><Box className="h-4 w-4 text-primary" />{model.part}</div>
      <dl className="space-y-1">
        <Row k="Material" v={model.material?.name ?? "not set"} />
        <Row k="Mass" v={m?.mass_kg ? `${fmt(m.mass_kg * 1000)} g` : "-"} />
        <Row k="Weight" v={m?.weight_N ? `${fmt(m.weight_N)} N` : "-"} />
        <Row k="CoG" v={m?.com_mm ? m.com_mm.map(x => fmt(x, 3)).join(", ") + " mm" : "-"} />
        <Row k="Bounding box" v={model.bbox ? model.bbox.map(x => fmt(x, 4)).join(" × ") + " mm" : "-"} />
        {m?.inertia_kg_mm2 && <Row k="Ixx, Iyy, Izz" v={[0, 1, 2].map(i => fmt(m.inertia_kg_mm2![i]![i], 3)).join(", ") + " kg·mm²"} />}
      </dl>
      <div className="mt-2 text-[10.5px] text-muted">{model.material_source}. {model.mechanical ? `Strengths: ${model.mechanical.source} (${model.mechanical.basis}; verify against the certificate).` : "No cited strengths for this material: enter them in each calculator."}</div>
      {model.recognition?.summary && <ul className="mt-2 space-y-0.5 border-t border-border pt-2 text-[11.5px] text-muted">{model.recognition.summary.slice(0, 6).map(s => <li key={s}>{s}</li>)}</ul>}
    </Card>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between gap-2"><dt className="text-muted">{k}</dt><dd className="text-right tabular-nums">{v}</dd></div>;
}
