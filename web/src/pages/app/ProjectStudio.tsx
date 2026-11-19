import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Box, Boxes, Camera, Check, CircleHelp, Download, Factory, FileCode2, FileText, Gauge, GitCompare, History, ListTree, Loader2, MessageSquare, PanelLeft, PanelRight, PenLine, Printer, Redo2, Scale, ScanLine, SlidersHorizontal, Sparkles, Trash2, TriangleAlert, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AgentEdit, BuildStatus, Catalog, Impact, ImpactChange, ManualFeature, Project, RepairItem } from "@/lib/types";
import { cx, num } from "@/lib/format";
import { Button, Input, Modal, PageLoader, Tab, TabList, TabPanel, Tabs, Tip } from "@/components/ui";
import { Icon } from "@/components/icons";
import Viewer3D, { type Tool, type ViewerApi } from "@/components/Viewer3D";
import NotFoundPanel from "@/components/NotFoundPanel";
import { ProjectStatus } from "@/components/ProjectCard";
import { useDeliverables } from "@/components/Release";
import { runTour, seenTour, STUDIO_TOUR } from "@/lib/tour";
import type { Pick, SketchPreview, Topo, V3, ViewName } from "@/viewer/types";
import { dimFaces, onModel, resolveDims, type DimsDoc } from "@/viewer/dims";
import Chat from "./studio/Chat";
import FeatureManager, { planePreview, selectKindsFor, xDirFor, type FeatureOp } from "./studio/FeatureManager";
import CommandManager, { type Command, type MakeModule } from "./studio/CommandManager";
import SketchEditor, { type SketchPreset } from "./studio/SketchEditor";
import { offsetPlane, sketchLines, type PlaneDef, type RefPlane } from "@/viewer/planes";
import StepImport from "./studio/StepImport";
import Toolbox from "./studio/Toolbox";
import { SimilarPartsDialog } from "@/components/SimilarParts";
import { useWhereUsed, WhereUsed } from "./modules/assembly/WhereUsed";
import { DatasheetChip } from "./modules/mesh/DatasheetChip";
import ParamEditPM from "./studio/ParamEditPM";
import { agentSteps, prefillPm, treeChange } from "./studio/agentEdit";
import ImpactPanel from "./studio/ImpactPanel";
import { ChecksPanel, FilesPanel, MassPanel, ParamsPanel, RevisionsPanel, SourcePanel, TreePanel, type Recognition } from "./studio/Panels";
import StudioCommands, { SHORTCUTS } from "./studio/StudioCommands";
import CollabBar, { CollabBanner, NewBranchDialog } from "@/components/collab/CollabBar";
import ActivityPanel from "@/components/collab/ActivityPanel";
import { can, whyNot } from "@/lib/collab";
import { COMPACT, PHONE, useMedia } from "@/lib/media";

interface CompareState { base: number; added: Topo | null; removed: Topo | null; added_mm3: number; removed_mm3: number; params: Record<string, { from: unknown; to: unknown }> }

/** Downstream modules offered on the Make tab when they are Live: each opens the module on this part. */
const MAKE: Record<string, Omit<MakeModule, "code">> = {
  drawings: { name: "Drawing Studio", icon: <FileText className="h-5 w-5" />, tip: "Generate the manufacturing drawing of this part" },
  manufacturing: { name: "Manufacturing Advisor", icon: <Factory className="h-5 w-5" />, tip: "Check manufacturability and get a relative cost estimate" },
  print: { name: "3D Print Prep", icon: <Printer className="h-5 w-5" />, tip: "Prepare this part for 3D printing: checks, orientation, export" },
  engineering: { name: "Engineering Advisor", icon: <Gauge className="h-5 w-5" />, tip: "Engineering calculations pre-filled from this part" },
  assembly: { name: "Assemble", icon: <Boxes className="h-5 w-5" />, tip: "Mate with other parts, check clashes, fit ISO fasteners" },
  mesh: { name: "Render", icon: <Camera className="h-5 w-5" />, tip: "Photoreal renders and turntables of this part (visualisation)" },
  airender: { name: "AI render", icon: <Sparkles className="h-5 w-5" />, tip: "AI marketing visuals of this part on your own OpenAI key (Beta; illustrative, not dimensionally exact)" },
};

/** Live input modules offered on the Library tab: they bring outside geometry into this part. */
const LIBRARY: Record<string, Omit<MakeModule, "code">> = {
  image2cad: { name: "From Drawing", icon: <ScanLine className="h-5 w-5" />, tip: "Turn a drawing PDF, scan or sketch into this part: every dimension read, nothing guessed" },
};

export default function ProjectStudio() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
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
  const [pm, setPmS] = useState<{ op: FeatureOp; editing: ManualFeature | null; preset?: Record<string, unknown> } | null>(null);
  const [paramPm, setParamPm] = useState<{ rows: NonNullable<AgentEdit["params"]>; summary: string; n: number } | null>(null);
  const setPm = (v: typeof pm) => { setPmS(v); if (v) setParamPm(null); };
  /** DS-035 follow-up: the remaining PropertyManager steps of a multi-step agent edit (next opens after OK + rebuild) */
  const [agentQueue, setAgentQueue] = useState<{ steps: AgentEdit[]; total: number; topoAtOpen: Topo | null; done: boolean } | null>(null);
  /** ASM-018 follow-up: a tree action / typed command whose trial rebuild found problems in assemblies */
  const [gate, setGate] = useState<{ impact: Impact; label: string; run: () => void } | null>(null);
  const [sk, setSk] = useState<{ phase: "pick"; preset?: SketchPreset } | { phase: "edit"; plane: PlaneDef; faceId: number | null; editing: ManualFeature | null; preset?: SketchPreset; planeRef?: ManualFeature } | null>(null);
  const [planeOffset, setPlaneOffset] = useState("0");
  const [dialog, setDialog] = useState<"import" | "toolbox" | "similar" | null>(null);
  const [tbInit, setTbInit] = useState<{ code: string; params: Record<string, number> } | null>(null);
  const viewerApi = useRef<ViewerApi | null>(null);
  const [compare, setCompare] = useState<CompareState | null>(null);
  const [tab, setTab] = useState(() => (new URLSearchParams(location.search).get("panel") === "activity" ? "activity" : "tree"));
  const [branchDlg, setBranchDlg] = useState(false);
  const [manualBusy, setManualBusy] = useState(false);
  const [flatView, setFlatView] = useState(false); // sheet metal (CAD-026): show the flat pattern instead of the part
  const [leftOpen, setLeftOpenS] = useState(() => { try { return localStorage.getItem("fw_studio_left") !== "0"; } catch { return true; } });
  const [chatOpen, setChatOpenS] = useState(() => { try { return localStorage.getItem("fw_studio_chat") !== "0"; } catch { return true; } });
  const setLeftOpen = (v: boolean) => { setLeftOpenS(v); try { localStorage.setItem("fw_studio_left", v ? "1" : "0"); } catch { /* */ } };
  const setChatOpen = (v: boolean) => { setChatOpenS(v); try { localStorage.setItem("fw_studio_chat", v ? "1" : "0"); } catch { /* */ } };
  // Phones and tablets (UX-018): the viewer keeps the whole width and the feature panel / design agent open over it,
  // one at a time (phones switch with the bottom bar). The desktop open/closed preferences are left untouched.
  const compact = useMedia(COMPACT);
  const phone = useMedia(PHONE);
  const [pane, setPane] = useState<"model" | "features" | "agent">("model");
  const [chatMounted, setChatMounted] = useState(false); // keep the conversation alive while the agent sheet is closed
  useEffect(() => { if (pane === "agent") setChatMounted(true); }, [pane]);
  const showLeft = compact ? pane === "features" : leftOpen;
  const showChat = compact ? pane === "agent" : chatOpen;
  const openLeft = () => (compact ? setPane("features") : setLeftOpen(true));
  const openChat = () => (compact ? setPane("agent") : setChatOpen(true));
  const [recognizing, setRecognizing] = useState(false);
  const [featureChips, setFeatureChips] = useState<string[]>([]);
  const [chatRequest, setChatRequest] = useState<{ id: number; text: string } | null>(null);
  const [search, setSearch] = useSearchParams();
  useState(() => { const ask = search.get("ask"); if (ask) try { sessionStorage.setItem(`fw_starter_${id}`, ask.slice(0, 4000)); } catch { /* */ } });
  useEffect(() => {
    if (!search.has("ask")) return;
    openChat();
    const n = new URLSearchParams(search); n.delete("ask"); setSearch(n, { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [delTarget, setDelTarget] = useState<string | null>(null);
  const [paramFocus, setParamFocus] = useState<string | null>(null);
  const [redo, setRedo] = useState<number[]>([]); // revisions undone with Ctrl+Z, newest last (Ctrl+Y re-applies)
  const [palette, setPalette] = useState(false);
  const [keys, setKeys] = useState(false);
  const undoBusy = useRef(false);
  // design parameters as dimensions on the model (D): hover links the dimension, its faces and its Params row
  const [dimsOn, setDimsOnS] = useState(() => { try { return localStorage.getItem("fw_view_dims") === "1"; } catch { return false; } });
  const setDimsOn = (v: boolean) => { setDimsOnS(v); try { localStorage.setItem("fw_view_dims", v ? "1" : "0"); } catch { /* */ } };
  const [paramHover, setParamHover] = useState<string | null>(null);

  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const owned = useMemo(() => new Set(me?.org?.god_unlock ? Object.keys(MAKE) : me?.org?.modules ?? []), [me?.org]);
  const deliv = useDeliverables(id);
  const make = useMemo<MakeModule[]>(() => (catalog.data?.modules ?? []).filter(m => m.status === "live" && MAKE[m.code])
    .map(m => {
      const d = deliv.data?.modules[m.code as "drawings"];  // one status line per output (MAKE-15)
      const status = d && { text: d.label, tone: d.state === "stale" ? "warn" as const : d.state === "missing" ? "muted" as const : "ok" as const };
      const locked = !(me?.org?.modules.includes(m.code) || me?.org?.god_unlock);  // MAKE-21
      return { code: m.code, ...MAKE[m.code]!, status: status || undefined, locked };
    }), [catalog.data, deliv.data, me?.org]);
  const libraryModules = useMemo<MakeModule[]>(() => (catalog.data?.modules ?? []).filter(m => m.status === "live" && LIBRARY[m.code])
    .map(m => ({ code: m.code, ...LIBRARY[m.code]! })), [catalog.data]);
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Project>(`/api/projects/${id}`), refetchInterval: 15_000 });
  const hasBuilds = (project.data?.builds ?? 0) > 0;
  const status = useQuery({ queryKey: ["status", id, hasBuilds], enabled: hasBuilds,
    queryFn: () => fetch(`/api/projects/${id}/files/status.json`).then(r => (r.ok ? (r.json() as Promise<BuildStatus>) : null)) });
  const manual = useQuery({ queryKey: ["manual", id, status.data?.build_id], enabled: !!id, queryFn: () => api.get<{ features: ManualFeature[] }>(`/api/projects/${id}/manual`) });
  const recog = useQuery({ queryKey: ["recognition", id, status.data?.build_id], enabled: hasBuilds,
    queryFn: () => api.get<{ recognition: Recognition | null }>(`/api/projects/${id}/recognition`) });
  const p = project.data;
  const st = status.data ?? undefined;
  const dimsQ = useQuery({ queryKey: ["dims", id, st?.build_id], enabled: !!st?.fingerprint && (dimsOn || tab === "params"),
    queryFn: () => api.get<DimsDoc>(`/api/projects/${id}/dims`),
    refetchInterval: q => (q.state.data?.state === "pending" || q.state.data?.state === "paused" ? 1500 : false) });
  const dimSpecs = dimsQ.data?.dims ?? [];
  const dimValues = st?.editable_params ?? {};
  const dimShown = useMemo(() => (topo && dimSpecs.length ? resolveDims(dimSpecs, topo, dimValues).length : 0), [topo, dimSpecs, dimValues]);
  const dimMapped = useMemo(() => new Set(dimSpecs.filter(onModel).map(d => d.param)), [dimSpecs]);
  const hoverFaces = useMemo(() => (paramHover ? dimFaces(dimSpecs.find(d => d.param === paramHover)) : null), [paramHover, dimSpecs]);
  useEffect(() => { setParamHover(null); }, [st?.build_id]);
  const branch = p?.branch ?? "main";
  const readOnly = !!p && !can(p.access, "edit", branch);  // PLT-021: view-only people get the viewer, not the tools
  const usedIn = useWhereUsed(id, st?.build_id, owned.has("assembly")).length;  // ASM-018: edits preview their impact

  useEffect(() => { if (p) setName(p.name); }, [p?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (id) api.post(`/api/projects/${id}/warm`).catch(() => {}); }, [id]);
  useEffect(() => {
    if (!p || seenTour("studio") || compact) return; // the tour walks the desktop layout
    const t = setTimeout(() => runTour(STUDIO_TOUR, "studio"), 900);
    return () => clearTimeout(t);
  }, [p?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (st?.build_id) setCompare(null); }, [st?.build_id]);
  useEffect(() => { setHl([]); }, [topo]);
  // compact: a PropertyManager opens in the feature sheet; the sketcher and a finished feature show the model
  useEffect(() => { if (!compact) return; if (pm) setPane("features"); else if (phone) setPane(v => (v === "features" ? "model" : v)); }, [pm, compact]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (compact && sk) setPane("model"); }, [sk, compact]); // face ids highlighted from a previous build are meaningless now

  const refresh = () => {
    for (const k of ["status", "project", "manual", "revisions", "params", "recognition", "dims"]) qc.invalidateQueries({ queryKey: [k, id] });
    qc.invalidateQueries({ queryKey: ["me"] }); qc.invalidateQueries({ queryKey: ["projects"] });
  };
  const selectKinds = useMemo<Pick["kind"][] | undefined>(() => (pm ? selectKindsFor(pm.op) : sk?.phase === "pick" ? ["face"] : undefined), [pm, sk]);

  const openSketchOn = (faceId: number, preset?: SketchPreset) => {
    const f = topo?.faces[faceId];
    if (!f || f.type !== "plane" || !f.normal) { toast.error("Pick a flat (planar) face to sketch on."); setSelection([]); return; }
    setSk({ phase: "edit", plane: { origin: f.center, normal: f.normal, x_dir: xDirFor(f.normal) }, faceId, editing: null, preset });
    setSelection([]); setTool("orbit");
  };
  const openSketchOnPlane = (name: RefPlane, preset?: SketchPreset, offset = 0) => {
    const off = Number.isFinite(offset) ? offset : 0;
    setPm(null); setSk({ phase: "edit", plane: offsetPlane(name, off), faceId: null, editing: null, preset }); setSelection([]); setTool("orbit");
  };
  /** Sketch on a reference plane feature: the sketch is attached to it and follows it when the plane is edited. */
  const openSketchOnRef = (f: ManualFeature, preset?: SketchPreset) => {
    if (!f.plane) return;
    const n = f.plane.normal as V3;
    setPm(null); setSk({ phase: "edit", plane: { origin: f.plane.origin, normal: n, x_dir: (f.plane.x_dir ?? xDirFor(n)) as V3 }, faceId: null, editing: null, preset, planeRef: f });
    setSelection([]); setTool("orbit"); setSketch(null);
  };
  const openPm = (op: ManualFeature["op"], ed: ManualFeature | null = null, preset?: Record<string, unknown>) => {
    setFlatView(false); // features are picked and previewed on the folded part
    if (op === "revolve" && !ed) { openPm("sketch", null, { feature: "revolve", ...(preset ?? {}) }); return; }
    if (op === "sketch" || op === "revolve" || op === "rib" || op === "sketch2d" || op === "sm_base") {
      if (ed?.plane) {
        const pl = ed.plane; const n = pl.normal as V3;
        const faceId = topo?.faces.find(f => f.type === "plane" && f.normal && Math.abs(f.normal[0] * n[0] + f.normal[1] * n[1] + f.normal[2] * n[2] - 1) < 1e-6
          && Math.abs((f.center[0] - pl.origin[0]) * n[0] + (f.center[1] - pl.origin[1]) * n[1] + (f.center[2] - pl.origin[2]) * n[2]) < 1e-4)?.id ?? null;
        const ref = ed.plane_ref ? manual.data?.features.find(x => x.id === ed.plane_ref) : undefined;
        setSk({ phase: "edit", plane: { origin: pl.origin, normal: n, x_dir: (pl.x_dir ?? xDirFor(n)) as V3 }, faceId: ref ? null : faceId, editing: ed, planeRef: ref });
      } else {
        const sp = preset as SketchPreset | undefined;
        const face = selection.find(x => x.kind === "face");
        if (face && topo?.faces[face.id]?.type === "plane") openSketchOn(face.id, sp); else { setSk({ phase: "pick", preset: sp }); setTool("select"); setSelection([]); }
      }
      setPm(null); return;
    }
    setSk(null); setPm({ op: op as FeatureOp, editing: ed, preset }); setTool("select");
    const kinds = selectKindsFor(op);
    setSelection(s => s.filter(x => kinds.includes(x.kind)));
  };
  /** DS-035: an edit proposed by the design agent opens the real PropertyManager, pre-filled, targets highlighted. */
  const openAgentEdit = (edit: AgentEdit) => {
    const steps = agentSteps(edit);
    if (!steps.length) { toast.error("No change to make"); return; }
    setAgentQueue(steps.length > 1 ? { steps: steps.slice(1), total: steps.length, topoAtOpen: topo, done: false } : null);
    openAgentStep(steps[0]!, steps.length > 1 ? `Step 1 of ${steps.length}: ` : "");
  };
  const openAgentStep = (edit: AgentEdit, prefix = "") => {
    if (readOnly) { toast.error("You can view this part but not change it"); setAgentQueue(null); return; }
    const r = prefillPm(edit, topo, manual.data?.features ?? [], st?.build_id);
    if (r.kind === "error") { toast.error(r.message); setAgentQueue(null); return; }
    openLeft();
    setSk(null);
    if (r.kind === "params") { setPm(null); setParamPm({ rows: r.rows, summary: prefix + edit.summary, n: Date.now() }); return; }
    if (r.op === "sketch" || r.op === "revolve") { openPm(r.op, r.editing); toast(`${prefix}${edit.summary}: check the values, then OK`); return; }
    setPm({ op: r.op as FeatureOp, editing: r.editing, preset: { ...r.preset, agent: prefix + edit.summary, n: Date.now() } });
    setTool("select"); setSelection(r.selection);
    if (r.note) toast.warning(r.note);
  };
  /** OK on one step of a multi-step agent edit: the next step opens once the rebuilt geometry has loaded (the
   *  geometry differs from the one the step was opened on; it may load before or after this call). */
  const agentStepDone = () => setAgentQueue(q => (q && q.steps.length ? { ...q, done: true } : null));
  useEffect(() => {
    const q = agentQueue;
    // ...and the feature list of the new build has loaded (the next step edits a feature from it)
    if (!q || !q.done || !topo || topo === q.topoAtOpen || !manual.data || manual.isFetching) return;
    const [next, ...rest] = q.steps;
    setAgentQueue(rest.length ? { steps: rest, total: q.total, topoAtOpen: topo, done: false } : null);
    if (next) openAgentStep(next, `Step ${q.total - rest.length} of ${q.total}: `);
  }, [topo, agentQueue, manual.data, manual.isFetching]); // eslint-disable-line react-hooks/exhaustive-deps
  /** Tree actions and typed commands preview their impact on the assemblies using this part first (trial rebuild,
   *  nothing applied); problems open the same Apply anyway / Back panel as the PropertyManager. */
  const guarded = async (change: ImpactChange | null, label: string, run: () => void) => {
    if (!change || usedIn <= 0) { run(); return; }
    const t = toast.loading(`Checking ${usedIn} assembl${usedIn > 1 ? "ies" : "y"} on a trial rebuild…`);
    let ok = true;
    try {
      const r = await api.post<Impact>(`/api/m/assembly/impact/${id}`, change);
      if ((r.issues ?? 0) > 0) { ok = false; setGate({ impact: r, label, run }); }
    } catch { /* the change itself reports what is wrong */ }
    finally { toast.dismiss(t); }
    if (ok) run();
  };
  // Sketch: as soon as a face is picked, open the sketcher on it
  useEffect(() => {
    if (sk?.phase !== "pick") return;
    const face = selection.find(x => x.kind === "face");
    if (face) openSketchOn(face.id, sk.preset);
  }, [selection, sk]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Ctrl+Z / Ctrl+Y over the revision history (every edit is a revision; no AI, no tokens). */
  const undo = async () => {
    if (undoBusy.current || manualBusy || p?.agent?.busy) return;
    undoBusy.current = true; setManualBusy(true);
    try { const r = await api.post<{ revision: number; undone: number; why: string }>(`/api/projects/${id}/undo`); setRedo(s => [...s, r.undone]); toast.success(`Undone: ${r.why}`, { action: { label: "Redo", onClick: () => void redoNow([...redo, r.undone]) } }); refresh(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Undo failed"); }
    finally { undoBusy.current = false; setManualBusy(false); }
  };
  const redoNow = async (stack = redo) => {
    const to = stack.at(-1);
    if (to === undefined || undoBusy.current || manualBusy) { if (to === undefined) toast("Nothing to redo"); return; }
    undoBusy.current = true; setManualBusy(true);
    try { const r = await api.post<{ why: string }>(`/api/projects/${id}/redo`, { to }); setRedo(stack.slice(0, -1)); toast.success(`Redone: ${r.why}`); refresh(); }
    catch (e) { setRedo([]); toast.error(e instanceof ApiError ? e.message : "Redo failed"); }
    finally { undoBusy.current = false; setManualBusy(false); }
  };

  /** Optimistic tree update: apply locally first so the tree reacts instantly, then rebuild in the background. */
  const manualCall = async (fn: () => Promise<unknown>, ok: string, optimistic?: (l: ManualFeature[]) => ManualFeature[], undoable = false) => {
    const key = ["manual", id, status.data?.build_id];
    const prev = qc.getQueryData<{ features: ManualFeature[] }>(key);
    if (optimistic && prev) qc.setQueryData(key, { features: optimistic(prev.features) });
    setManualBusy(true);
    try {
      const t0 = performance.now(); const r = await fn() as { repairs?: RepairItem[] } | undefined; setRedo([]);
      const msg = `${ok} · ${((performance.now() - t0) / 1000).toFixed(1)} s`;
      if (r?.repairs?.length) toast.warning(`${msg} · ${r.repairs.length} feature${r.repairs.length === 1 ? "" : "s"} need${r.repairs.length === 1 ? "s" : ""} repair (see the tree)`);
      else toast.success(msg, undoable ? { action: { label: "Undo", onClick: () => void undo() } } : undefined);
      refresh();
    }
    catch (e) { if (prev) qc.setQueryData(key, prev); toast.error(e instanceof ApiError ? e.message : "Failed"); }
    finally { setManualBusy(false); }
  };
  /** Recognise: the exact geometric pass (free, instant); with ai=true the design agent then classifies it (tokens). */
  const recognize = async (ai = false) => {
    setRecognizing(true); setTab("tree"); viewerApi.current?.setView("Iso");
    try {
      const r = await api.post<{ recognition: Recognition }>(`/api/projects/${id}/recognition/run`);
      qc.setQueryData(["recognition", id, status.data?.build_id], r);
      if (!ai) { toast.success("Features recognised from the exact geometry (no AI)"); return; }
      openChat();
      try { await api.post(`/api/projects/${id}/recognition/ai`); toast.success("Geometry analysed — the design agent is classifying the features (see chat)"); }
      catch (e) { toast.warning(e instanceof ApiError ? `Geometric recognition done. AI step unavailable: ${e.message}` : "Geometric recognition done; AI step unavailable"); }
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Recognition failed"); }
    finally { setRecognizing(false); }
  };
  const selFace = selection.find((x): x is Extract<Pick, { kind: "face" }> => x.kind === "face" && topo?.faces[x.id]?.type === "plane");
  const normalTo = () => { const n = selFace && topo?.faces[selFace.id]?.normal; if (n) viewerApi.current?.normalTo(n as V3); };
  const onCommand = (c: Command) => {
    if (readOnly && ["feature", "sketch", "import", "toolbox"].includes(c.kind)) { toast.error(whyNot(p?.access, "edit", branch) ?? "You can't change this part"); return; }
    if (c.kind === "feature") openPm(c.op, null, c.preset);
    else if (c.kind === "sketch") openPm("sketch", null, c.preset);
    else if (c.kind === "tool") { setPm(null); setSk(null); setTool(tool === c.tool ? "orbit" : c.tool); }
    else if (c.kind === "panel") { setPm(null); setTab(c.tab); if (c.extra === "com") setShowCom(true); }
    else if (c.kind === "import") setDialog("import");
    else if (c.kind === "toolbox") { setTbInit(null); setDialog("toolbox"); }
    else if (c.kind === "similar") setDialog("similar");
    else if (c.kind === "normal") normalTo();
  };

  // Keyboard (STU-11): Ctrl+Z/Y undo/redo, F fit, Ctrl+1–7 views, Esc, ? shortcuts, Ctrl+K typed commands (IDEA 5).
  const keyState = useRef({ undo, redoNow, pm, sk, tool, dimsOn, setDimsOn });
  keyState.current = { undo, redoNow, pm, sk, tool, dimsOn, setDimsOn };
  useEffect(() => {
    const VIEWS: ViewName[] = ["Iso", "Front", "Top", "Right", "Back", "Left", "Bottom"];
    const h = (e: KeyboardEvent) => {
      const k = keyState.current;
      const el = e.target as HTMLElement;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); e.stopImmediatePropagation(); setPalette(true); return; }
      if (typing || document.querySelector("[role=dialog]") || k.sk?.phase === "edit") return; // the sketcher has its own keys
      if (mod && !e.shiftKey && e.key.toLowerCase() === "z") { e.preventDefault(); if (!k.pm) void k.undo(); return; }
      if (mod && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) { e.preventDefault(); if (!k.pm) void k.redoNow(); return; }
      if (mod && /^[1-7]$/.test(e.key)) { e.preventDefault(); viewerApi.current?.setView(VIEWS[Number(e.key) - 1]!); return; }
      if (mod || e.altKey) return;
      if (e.key === "f" || e.key === "F") viewerApi.current?.zoomToFit();
      else if (e.key === "?") setKeys(true);
      else if ((e.key === "d" || e.key === "D") && !k.pm && !k.sk) k.setDimsOn(!k.dimsOn);
      else if (e.key === "Escape" && !k.pm) { if (k.sk?.phase === "pick") { setSk(null); setTool("orbit"); } else if (k.tool !== "orbit") { setTool("orbit"); setSelection([]); } else setSelection([]); }
    };
    addEventListener("keydown", h, true);
    return () => removeEventListener("keydown", h, true);
  }, []);
  const runCompare = async (base: number) => {
    try {
      const r = await api.post<{ added_url: string | null; removed_url: string | null; added_mm3: number; removed_mm3: number; params_changed: CompareState["params"] }>(`/api/projects/${id}/compare`, { base });
      const load = (u: string | null) => (u ? fetch(u).then(x => x.json() as Promise<Topo>) : Promise.resolve(null));
      const [added, removed] = await Promise.all([load(r.added_url), load(r.removed_url)]);
      setCompare({ base, added, removed, added_mm3: r.added_mm3, removed_mm3: r.removed_mm3, params: r.params_changed });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Compare failed"); }
  };

  if (project.isLoading) return <PageLoader />;
  if (!p) return <NotFoundPanel title="Project not found" body="It may have been deleted, or it belongs to a workspace you're not signed in to." action={<Link to="/app/projects"><Button>Back to projects</Button></Link>} />;
  const fp = st?.fingerprint;
  const mf = manual.data?.features ?? [];
  const sheetInfo = st?.sheet_metal ?? null;
  const hasSheet = !!sheetInfo && !sheetInfo.flat_error && !!sheetInfo.flat;
  const flatOn = flatView && hasSheet && !!fp;
  const toggleFlat = () => { if (!hasSheet) return; setPm(null); setSk(null); setSelection([]); setTool("orbit"); setFlatView(v => !v); };
  const downloadDxf = () => { const a = document.createElement("a"); a.href = `/api/projects/${p.id}/files/flat.dxf`; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); };
  const tabs: [string, React.ReactNode, string][] = [["tree", <ListTree className="h-3.5 w-3.5" />, "Tree"], ["checks", <Check className="h-3.5 w-3.5" />, "Checks"],
    ["params", <SlidersHorizontal className="h-3.5 w-3.5" />, "Params"], ["mass", <Scale className="h-3.5 w-3.5" />, "Mass"],
    ["revs", <History className="h-3.5 w-3.5" />, "Revisions"], ["files", <Download className="h-3.5 w-3.5" />, "Files"],
    ["activity", <MessageSquare className="h-3.5 w-3.5" />, "Activity"],
    // the model script is never shown to users (STU-06); superadmins keep it as a support view (PD parked)
    ...(me?.user?.is_superadmin ? [["src", <FileCode2 className="h-3.5 w-3.5" />, "Source"] as [string, React.ReactNode, string]] : [])];
  const repairs = st?.manual_errors ?? [];
  /** A value edited on a dimension in the viewport: the same token-free parameter rebuild as the Params panel. */
  const editOnScreen = (param: string, value: number) => {
    const label = st?.param_meta?.[param]?.label ?? param.replace(/_/g, " ").toLowerCase().replace(/^\w/, c => c.toUpperCase()), from = st?.editable_params?.[param];
    const values = { [param]: value };
    void guarded({ kind: "params", values }, `Change ${label} to ${value}`,
      () => void manualCall(() => api.post(`/api/projects/${id}/params`, { values }), `${label} ${from ?? ""} → ${value}`, undefined, true));
  };
  const dimsVisible = dimsOn && !pm && !sk && !flatOn && !compare && !paramPm;
  const repairOf = (f: ManualFeature | null) => (f ? repairs.find(m => m.id === f.id)?.error ?? null : null);

  const sidePanel = (<>
          {pm ? (
            <FeatureManager key={`${pm.op}-${pm.editing?.id ?? "new"}-${JSON.stringify(pm.preset ?? {})}`} project={p} op={pm.op} editing={pm.editing} preset={pm.preset} topo={topo} selection={selection} manual={mf} onBusy={setManualBusy}
              repair={repairOf(pm.editing)}
              onSelection={setSelection} onSketch={setSketch} onDone={() => { setPm(null); setSketch(null); setRedo([]); refresh(); setTool("orbit"); agentStepDone(); }}
              onCancel={() => { setPm(null); setSketch(null); setSelection([]); setTool("orbit"); setAgentQueue(null); }} usedIn={usedIn} sheet={sheetInfo} />
          ) : paramPm ? (
            <ParamEditPM key={paramPm.n} project={p} rows={paramPm.rows} summary={paramPm.summary} usedIn={usedIn}
              onDone={() => { setParamPm(null); setRedo([]); refresh(); agentStepDone(); }} onCancel={() => { setParamPm(null); setAgentQueue(null); }} />
          ) : (
            <Tabs value={tab} onValueChange={t => { setTab(t); if (t !== "params") setParamFocus(null); }} className="flex min-h-0 flex-1 flex-col" data-tour="feature-tree">
              <TabList className="gap-0 overflow-x-auto px-1 [scrollbar-width:none]">
                {tabs.map(([v, icon, label]) => <Tab key={v} compact value={v} title={label}>{icon}{tab === v && label}</Tab>)}
              </TabList>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <TabPanel value="tree"><TreePanel flatOn={flatOn} onFlat={hasSheet ? toggleFlat : undefined} status={st} topo={topo} manual={mf} busy={manualBusy} onHover={setHl}
                  recognition={recog.data?.recognition ?? null} recognizing={recognizing} onRecognize={recognize} onEdit={f => openPm(f.op, f)}
                  selectedFeatures={featureChips} agentBusy={!!p.agent?.busy} onDeleteDesign={setDelTarget}
                  onEditParams={n => { setParamFocus(n); setTab("params"); }}
                  onAskRepair={(f, why) => { openChat();
                    setChatRequest({ id: Date.now(), text: `The feature “${f.name}” that I added by hand no longer rebuilds after my last change (${why}). Repair only that feature so it fits the current geometry, keeping its intent and everything else unchanged, then rebuild and check.` }); }}
                  onPickFeature={n => { setFeatureChips(c => (c.includes(n) ? c.filter(x => x !== n) : [...c, n])); openChat(); }}
                  onSuppressDesign={(n, sup) => void guarded(treeChange({ kind: "design_suppress", name: n, suppressed: sup }), `${sup ? "Suppress" : "Restore"} “${n}”`,
                    () => void manualCall(() => api.post(`/api/projects/${id}/design-features/suppress`, { name: n, suppressed: sup }), sup ? `${n} suppressed` : `${n} restored`, undefined, true))}
                  onSketchPlane={n => (sk?.phase === "pick" ? openSketchOnPlane(n, sk.preset, Number(planeOffset)) : openSketchOnPlane(n))}
                  onSketchOn={f => openSketchOnRef(f, sk?.phase === "pick" ? sk.preset : undefined)}
                  onRename={(f, name) => manualCall(() => api.patch(`/api/projects/${id}/manual/${f.id}`, { feature: { name } }), `Renamed to ${name}`, l => l.map(x => (x.id === f.id ? { ...x, name } : x)))}
                  onRollback={before => manualCall(() => api.post(`/api/projects/${id}/manual/rollback`, { before }), before ? "Rolled back" : "Rolled forward to the end",
                    l => { const k = before ? l.findIndex(x => x.id === before) : l.length; return l.map((x, j) => ({ ...x, rolled_back: j >= k })); })}
                  onPreviewPlane={f => { if (pm || sk) return;
                    if (!f?.plane) { setSketch(null); return; }
                    const pl = { origin: f.plane.origin, normal: f.plane.normal, x_dir: f.plane.x_dir ?? xDirFor(f.plane.normal) };
                    setSketch(f.op === "sketch2d" ? { origin: [0, 0, 0], normal: [0, 0, 1], xDir: [1, 0, 0], kind: "lines", lines: sketchLines(pl, f.profiles, f.chains), cx: 0, cy: 0 }
                      : planePreview(f.plane.origin, f.plane.normal, topo)); }}
                  onToggle={f => void guarded(treeChange({ kind: "toggle", feature: f }), `${f.suppressed ? "Unsuppress" : "Suppress"} “${f.name}”`,
                    () => void manualCall(() => api.patch(`/api/projects/${id}/manual/${f.id}`, { feature: { suppressed: !f.suppressed } }), f.suppressed ? `${f.name} unsuppressed` : `${f.name} suppressed`, l => l.map(x => (x.id === f.id ? { ...x, suppressed: !x.suppressed } : x)), true))}
                  onMove={(f, d) => { const ch = treeChange({ kind: "move", ids: mf.map(x => x.id), id: f.id, by: d < 0 ? -1 : 1 }); if (!ch || ch.kind !== "reorder") return; const ids = ch.ids;
                    void guarded(ch, `Move “${f.name}” ${d < 0 ? "up" : "down"}`, () => void manualCall(() => api.post(`/api/projects/${id}/manual/reorder`, { ids }), "Features reordered", l => ids.map(i2 => l.find(x => x.id === i2)!))); }}
                  onDelete={f => void guarded(treeChange({ kind: "delete", feature: f }), `Delete “${f.name}”`,
                    () => void manualCall(() => api.del(`/api/projects/${id}/manual/${f.id}`), `${f.name} deleted`, l => l.filter(x => x.id !== f.id), true))} /></TabPanel>
                <TabPanel value="checks"><ChecksPanel status={st} /></TabPanel>
                <TabPanel value="params"><fieldset disabled={readOnly} title={readOnly ? whyNot(p.access, "edit", branch) ?? undefined : undefined}><ParamsPanel project={p} status={st} onChanged={() => { setRedo([]); refresh(); }} focus={paramFocus} usedIn={usedIn}
                  onModel={{ on: dimsOn, toggle: () => setDimsOn(!dimsOn), mapped: dimMapped, hover: paramHover, onHover: setParamHover }} /></fieldset></TabPanel>
                <TabPanel value="mass"><MassPanel project={p} status={st} showCom={showCom} onShowCom={setShowCom} /></TabPanel>
                <TabPanel value="revs"><RevisionsPanel project={p} onChanged={refresh} version={st?.build_id} onCompare={runCompare} comparing={compare?.base ?? null} /></TabPanel>
                <TabPanel value="files"><FilesPanel project={p} status={st} /></TabPanel>
                <TabPanel value="activity"><ActivityPanel projectId={p.id} /></TabPanel>
                {me?.user?.is_superadmin && <TabPanel value="src"><SourcePanel project={p} version={st?.build_id} /></TabPanel>}
              </div>
            </Tabs>)}
</>);

  return (
    <div className="flex h-full flex-col">
      <CommandManager touch={compact} onCommand={onCommand} viewerRef={viewerApi} disabled={!fp} activeTool={tool} make={make} library={libraryModules} onMake={code => navigate(`/app/modules/${code}?project=${id}`)} canNormal={!!selFace}
        sheet={{ has: hasSheet, flat: flatOn, onFlat: toggleFlat, onDxf: downloadDxf }}
        left={<div className="flex min-w-0 items-center gap-1.5" data-tour="studio-tabs">
          <Tip content="Back to projects" side="bottom"><Link to="/app/projects" className={cx("rounded text-muted hover:bg-text/5", compact ? "p-2" : "p-1")} aria-label="Back to projects"><ArrowLeft className="h-4 w-4" /></Link></Tip>
          {editing ? <Input autoFocus value={name} onChange={e => setName(e.target.value)} className="h-7 w-48"
            onBlur={async () => { setEditing(false); if (name.trim() && name !== p.name) { await api.patch(`/api/projects/${p.id}`, { name }); refresh(); } }}
            onKeyDown={e => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
            : <button onClick={() => setEditing(true)} className="min-w-0 max-w-[220px] truncate rounded px-1 py-0.5 text-[13.5px] font-semibold hover:bg-text/5" title="Rename">{p.name}</button>}
          {!phone && <ProjectStatus p={p} />}
          <CollabBar projectId={p.id} onSwitched={() => { setRedo([]); setCompare(null); refresh(); }} />
          {owned.has("assembly") && !phone && <WhereUsed projectId={p.id} buildId={st?.build_id} />}
          {owned.has("mesh") && !phone && !readOnly && <DatasheetChip projectId={p.id} buildId={st?.build_id} />}
        </div>}
        right={<>
          <Tip content="Undo (Ctrl+Z)" side="bottom"><button onClick={() => void undo()} disabled={manualBusy || !!p.agent?.busy || !hasBuilds || readOnly} className="rounded p-1 text-muted hover:bg-text/5 hover:text-text disabled:opacity-35" aria-label="Undo"><Undo2 className="h-4 w-4" /></button></Tip>
          <Tip content="Redo (Ctrl+Y)" side="bottom"><button onClick={() => void redoNow()} disabled={manualBusy || !redo.length} className="mr-1 rounded p-1 text-muted hover:bg-text/5 hover:text-text disabled:opacity-35" aria-label="Redo"><Redo2 className="h-4 w-4" /></button></Tip>
          {!phone && <>
          <Tip content={showLeft ? "Hide feature panel" : "Show feature panel"} side="bottom"><button onClick={() => (compact ? setPane(showLeft ? "model" : "features") : setLeftOpen(!leftOpen))} className={cx("rounded p-1 hover:bg-text/5", showLeft ? "text-primary" : "text-muted")} aria-label="Toggle feature panel"><PanelLeft className="h-4 w-4" /></button></Tip>
          <Tip content={showChat ? "Hide design agent" : "Show design agent"} side="bottom"><button onClick={() => (compact ? setPane(showChat ? "model" : "agent") : setChatOpen(!chatOpen))} className={cx("rounded p-1 hover:bg-text/5", showChat ? "text-primary" : "text-muted")} aria-label="Toggle design agent"><PanelRight className="h-4 w-4" /></button></Tip>
          {!compact && <Tip content="Studio tour · keyboard shortcuts (?)" side="bottom"><button onClick={() => runTour(STUDIO_TOUR, "studio")} className="rounded p-1 text-muted hover:bg-text/5"><CircleHelp className="h-4 w-4" /></button></Tip>}
          </>}
          {fp && <Tip content="Download STEP (more formats in Files)" side="bottom"><a href={`/api/projects/${p.id}/files/part.step`} className="ml-1 inline-flex h-7 items-center gap-1.5 rounded bg-primary px-2.5 text-[12.5px] font-medium text-white hover:brightness-110"><Download className="h-3.5 w-3.5" />STEP</a></Tip>}
        </>} />

      <div className="relative grid min-h-0 min-w-0 flex-1" style={{ gridTemplateColumns: compact ? "minmax(0,1fr)" : `${leftOpen ? "330px " : ""}minmax(0,1fr)${chatOpen ? " 370px" : ""}` }}>
        {showLeft && <aside data-studio-sheet="features" className={cx("flex min-h-0 min-w-0 flex-col overflow-hidden border-border bg-panel",
          !compact ? "border-r" : phone ? (pm ? "absolute inset-x-0 bottom-0 z-20 h-[58%] rounded-t-xl border-t shadow-pop" : "absolute inset-0 z-20")
            : "absolute inset-y-0 left-0 z-20 w-[360px] max-w-[85%] border-r shadow-pop")}>
          {sidePanel}
        </aside>}
        <div className="relative min-h-[320px] min-w-0 overflow-hidden" data-tour="viewer">
          <Viewer3D topoUrl={hasBuilds ? `/api/projects/${p.id}/files/${flatOn ? "flat.topo.json" : "topo.json"}` : null} version={fp ? (flatOn ? `${st?.build_id}-flat` : st?.build_id) : `keep`}
            tool={tool} onToolChange={setTool} selection={selection} onSelectionChange={setSelection} selectKinds={selectKinds}
            highlightFaces={hoverFaces ?? hl} com={showCom ? (st?.mass?.com_mm as V3 | undefined) ?? null : null} sketch={sketch}
            compare={compare ? { added: compare.added, removed: compare.removed } : null} onTopo={setTopo} apiRef={viewerApi}
            dims={fp && !flatOn ? { on: dimsVisible, onToggle: () => setDimsOn(!dimsOn), pending: dimsQ.data?.state === "pending" || dimsQ.isLoading, shown: dimShown,
              specs: dimSpecs, values: dimValues, meta: st?.param_meta ?? {}, whole: dimsQ.data?.whole ?? [], hover: paramHover, onHover: setParamHover,
              onEdit: readOnly || p.agent?.busy ? undefined : editOnScreen, busy: manualBusy } : undefined}
            empty={mf.length ? <div className="absolute bottom-10 rounded bg-panel/90 px-3 py-1.5 text-[12.5px] text-muted shadow-card">No solid yet: {mf.length} reference feature(s) in the tree. Add a boss, revolve, sweep or loft to create the body.</div>
              : p.agent?.busy && /^From .+ \(Image & Drawing to CAD\)/.test(p.description) /* AMI-26: first build from a drawing */
              ? <div className="text-center text-sm text-muted"><Loader2 className="mx-auto mb-2 h-8 w-8 animate-spin text-primary" />Building from {/^From (.+?) \(Image/.exec(p.description)?.[1]}…<div className="mt-1 text-[12.5px]">The design agent is modelling from your confirmed values.</div></div>
              : <div className="text-center text-sm text-muted"><Icon name="box" className="mx-auto mb-2 h-10 w-10 text-muted/40" />Describe a part to the design agent, model it by hand, or start from a library part
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                <button onClick={() => openPm("sketch", null, { feature: "extrude", mode: "add" })} className="pointer-events-auto rounded-md border border-primary/50 bg-primary-soft px-3 py-1.5 text-[12.5px] font-medium text-primary hover:border-primary">Sketch on a plane</button>
                <button onClick={() => { setTbInit(null); setDialog("toolbox"); }} className="pointer-events-auto rounded-md border border-border bg-panel px-3 py-1.5 text-[12.5px] font-medium text-text hover:border-primary hover:text-primary">Toolbox component</button>
                <button onClick={() => setDialog("import")} className="pointer-events-auto rounded-md border border-border bg-panel px-3 py-1.5 text-[12.5px] font-medium text-text hover:border-primary hover:text-primary">Import STEP</button>
              </div></div>} />
          <CollabBanner projectId={p.id} onBranch={() => setBranchDlg(true)} />
          {hasSheet && !sk && (
            <div className="absolute right-3 top-3 z-10 flex items-center gap-2 rounded-lg border border-border bg-panel/95 p-1 pr-2 text-[12px] shadow-card" data-sheet-chip>
              <div className="inline-flex overflow-hidden rounded border border-border">
                <button onClick={() => flatOn && toggleFlat()} className={cx("px-2 py-0.5", !flatOn ? "bg-primary text-white" : "text-muted hover:bg-text/5")} aria-pressed={!flatOn}>Folded</button>
                <button onClick={() => !flatOn && toggleFlat()} className={cx("px-2 py-0.5", flatOn ? "bg-primary text-white" : "text-muted hover:bg-text/5")} aria-pressed={flatOn} data-flat-toggle>Flat pattern</button>
              </div>
              <Tip content={`Sheet ${num(sheetInfo!.thickness, 2)} mm · default R${num(sheetInfo!.radius, 2)} · K ${num(sheetInfo!.k_factor, 3)}. Bend allowance = angle × (R + K × T). Flat size is the outline's bounding box.`} side="bottom">
                <span className="whitespace-nowrap text-muted" data-flat-size>{num(sheetInfo!.flat!.size[0], 1)} × {num(sheetInfo!.flat!.size[1], 1)} mm · {sheetInfo!.bend_count} bend{sheetInfo!.bend_count === 1 ? "" : "s"}</span>
              </Tip>
            </div>)}
          {sk?.phase === "pick" && (
            <div className="absolute left-1/2 top-14 z-10 flex max-w-[calc(100%-1.5rem)] -translate-x-1/2 flex-wrap items-center gap-2 whitespace-nowrap rounded-lg border border-primary/40 bg-panel/95 px-3 py-2 text-[12.5px] shadow-card">
              <PenLine className="h-4 w-4 text-primary" />{fp ? "Select a flat face, or a plane:" : "Choose a sketch plane:"}
              {mf.filter(f => f.op === "plane" && f.plane).map(f => <button key={f.id} data-plane={f.name} onClick={() => openSketchOnRef(f, sk.preset)} className="rounded border border-border px-2 py-0.5 font-medium hover:border-primary hover:text-primary">{f.name}</button>)}
              {(["Front", "Top", "Right"] as RefPlane[]).map(n => <button key={n} data-plane={n} onClick={() => openSketchOnPlane(n, sk.preset, Number(planeOffset))} className="rounded border border-border px-2 py-0.5 font-medium hover:border-primary hover:text-primary">{n}</button>)}
              <label className="flex items-center gap-1 text-muted">offset<Input value={planeOffset} onChange={e => setPlaneOffset(e.target.value)} className="h-6 w-14 px-1 text-right" inputMode="decimal" aria-label="Plane offset" />mm</label>
              <button onClick={() => { setSk(null); setTool("orbit"); }} className="ml-1 text-muted hover:text-text" aria-label="Cancel sketch"><X className="h-4 w-4" /></button>
            </div>)}
          {manualBusy && (
            <div className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-border bg-panel/95 px-3 py-1 text-[12px] text-muted shadow-card">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />Rebuilding…
            </div>)}
          {sk?.phase === "edit" && (
            <SketchEditor key={sk.editing?.id ?? "new"} project={p} topo={fp ? topo : null} plane={sk.plane} faceId={sk.faceId} editing={sk.editing}
              preset={sk.preset} hasBody={!!fp} existing={mf} planeRef={sk.planeRef}
              onDone={() => { setSk(null); refresh(); agentStepDone(); }} onCancel={() => { setSk(null); setAgentQueue(null); }} />)}
          {st?.error && (
            <div className="absolute left-1/2 top-16 max-w-md -translate-x-1/2 rounded-lg border border-danger/40 bg-panel/95 px-3 py-2 text-[12.5px] shadow-card">
              <b className="text-danger">Last build failed</b> — showing the last successful geometry.{project.data?.agent?.busy ? " The agent is working on it." : ""}
            </div>)}
          {!st?.error && repairs.length > 0 && !pm && (
            <button onClick={() => { openLeft(); setTab("tree"); }} data-repair-banner
              className="absolute left-1/2 top-14 z-10 flex max-w-md -translate-x-1/2 items-center gap-2 rounded-full border border-warning/50 bg-panel/95 px-3 py-1.5 text-[12.5px] shadow-card hover:border-warning">
              <TriangleAlert className="h-4 w-4 shrink-0 text-warning" />
              <span><b>{repairs.length === 1 ? `“${repairs[0]!.name}”` : `${repairs.length} features`}</b> no longer rebuild{repairs.length === 1 ? "s" : ""}: the rest of the part is built. Repair in the feature tree.</span>
            </button>)}
          {compare && (
            <div className="absolute right-3 top-14 w-64 rounded-lg border border-border bg-panel/95 p-3 text-[12.5px] shadow-card">
              <div className="flex items-center justify-between"><span className="flex items-center gap-1.5 font-semibold"><GitCompare className="h-4 w-4 text-primary" />Rev {compare.base} → current</span>
                <button onClick={() => setCompare(null)} aria-label="Exit compare"><X className="h-4 w-4 text-muted" /></button></div>
              <div className="mt-2 flex justify-between"><span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-[#22a85a]" />Added</span><span className="tabular-nums">{num(compare.added_mm3, 1)} mm³</span></div>
              <div className="flex justify-between"><span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-[#d8402f]" />Removed</span><span className="tabular-nums">{num(compare.removed_mm3, 1)} mm³</span></div>
              {Object.keys(compare.params).length > 0 && <div className="mt-2 border-t border-border pt-2">{Object.entries(compare.params).map(([k, v]) =>
                <div key={k} className="flex justify-between text-[11.5px]"><span>{st?.param_meta?.[k]?.label ?? k}</span><span className="tabular-nums">{String(v.from)} → {String(v.to)}</span></div>)}</div>}
            </div>)}
        </div>
        {(compact ? chatMounted || showChat : chatOpen) && (() => {
          const chat = <Chat key={branch} project={p} topo={topo} selection={pm || sk ? [] : selection} onSelectionChange={setSelection} onActivity={refresh} onToolbox={m => { setTbInit(m ? { code: m.code, params: m.params } : null); setDialog("toolbox"); }}
            features={featureChips} onFeaturesChange={setFeatureChips} request={chatRequest} onEdit={openAgentEdit} usedIn={usedIn} />;
          return compact ? <div data-studio-sheet="agent" className={cx("z-20 grid grid-rows-[minmax(0,1fr)] bg-panel", !showChat && "hidden",
            phone ? "absolute inset-0" : "absolute inset-y-0 right-0 w-[400px] max-w-[85%] border-l border-border shadow-pop")}>{chat}</div> : chat;
        })()}
      </div>

      <Modal open={!!delTarget} onOpenChange={o => !o && setDelTarget(null)} title={`Delete “${delTarget ?? ""}”?`}
        description="Removes this feature's step from the design, without AI and without tokens."
        footer={<><Button variant="ghost" className="mr-auto" disabled={!!p.agent?.busy} onClick={() => {
            const n = delTarget!; setDelTarget(null); setFeatureChips(c => c.filter(x => x !== n)); openChat();
            setChatRequest({ id: Date.now(), text: `Delete the feature “${n}” from the design: remove its geometry and its step, keep everything else unchanged, then rebuild and check.` });
          }}>Ask the design agent instead</Button>
          <Button variant="secondary" onClick={() => setDelTarget(null)}>Cancel</Button>
          <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} disabled={!!p.agent?.busy || manualBusy} onClick={() => {
            const n = delTarget!; setDelTarget(null); setFeatureChips(c => c.filter(x => x !== n));
            void guarded(treeChange({ kind: "design_delete", name: n }), `Delete “${n}”`,
              () => void manualCall(() => api.post(`/api/projects/${id}/design-features/delete`, { name: n }), `${n} deleted`));
          }}>Delete</Button></>}>
        <p className="text-[13px] text-muted">The result is checked to be identical to suppressing it. If anything else would change, nothing is deleted and
          the feature stays suppressed. Then you can ask the design agent to remove it. Undo with <b>Revisions</b>.</p>
      </Modal>
      {branchDlg && <NewBranchDialog projectId={p.id} from={{ id: branch, name: branch === "main" ? "main" : "this branch" }} onClose={() => setBranchDlg(false)} onDone={() => { qc.invalidateQueries(); setRedo([]); }} />}
      <SimilarPartsDialog projectId={p.id} open={dialog === "similar"} onClose={() => setDialog(null)} />
      <StudioCommands open={palette} onOpenChange={setPalette} topo={topo} selection={selection} manual={mf} designFeatures={(st?.features ?? []).filter(f => f.kind === "feature").map(f => f.name)}
        viewer={viewerApi} onPm={(op, preset) => openPm(op, null, preset)}
        onFeature={(f, label) => void guarded({ kind: "feature", feature: f }, label, () => void manualCall(() => api.post(`/api/projects/${id}/manual`, { feature: f }), `${label} added`, undefined, true))}
        onSuppress={f => void guarded(treeChange({ kind: "toggle", feature: f }), `${f.suppressed ? "Unsuppress" : "Suppress"} “${f.name}”`,
          () => void manualCall(() => api.patch(`/api/projects/${id}/manual/${f.id}`, { feature: { suppressed: !f.suppressed } }), f.suppressed ? `${f.name} unsuppressed` : `${f.name} suppressed`, undefined, true))}
        onSuppressDesign={n => void guarded(treeChange({ kind: "design_suppress", name: n, suppressed: true }), `Suppress “${n}”`,
          () => void manualCall(() => api.post(`/api/projects/${id}/design-features/suppress`, { name: n, suppressed: true }), `${n} suppressed`, undefined, true))}
        onUndo={() => void undo()} onRedo={() => void redoNow()} onTool={t => { setPm(null); setSk(null); setTool(t); }} onShortcuts={() => setKeys(true)} />
      <Modal open={!!gate} onOpenChange={o => !o && setGate(null)} title={gate ? `${gate.label}?` : ""}
        description="This part is used in assemblies. The change was tried on a trial rebuild first: nothing is applied yet.">
        {gate && <ImpactPanel impact={gate.impact} onApply={() => { const g = gate; setGate(null); g.run(); }} onBack={() => setGate(null)} />}
      </Modal>
      <Modal open={keys} onOpenChange={setKeys} title="Keyboard shortcuts">
        <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-[13px]">{SHORTCUTS.map(([k, d]) => <div key={k} className="contents"><dt><span className="kbd">{k}</span></dt><dd className="text-muted">{d}</dd></div>)}</dl>
        <p className="mt-3 text-[12px] text-muted">Mouse: middle- or left-drag rotates, Ctrl+middle or right-drag pans, the wheel zooms at the cursor.</p>
      </Modal>
      {dialog === "import" && <StepImport project={p} onClose={() => setDialog(null)} onDone={() => { setDialog(null); refresh(); }} />}
      {dialog === "toolbox" && <Toolbox project={p} initial={tbInit} onClose={() => setDialog(null)} onDone={() => { setDialog(null); refresh(); }} />}

      {phone && <nav className="grid h-14 shrink-0 grid-cols-3 border-t border-border bg-panel" aria-label="Studio panels">
        {([["features", <ListTree className="h-5 w-5" />, pm ? "Feature" : "Features"], ["model", <Box className="h-5 w-5" />, "Model"], ["agent", <Sparkles className="h-5 w-5" />, "Agent"]] as const).map(([k, icon, label]) => (
          <button key={k} data-studio-pane={k} aria-pressed={pane === k} onClick={() => setPane(k)}
            className={cx("relative flex flex-col items-center justify-center gap-0.5 text-[11px] font-medium", pane === k ? "text-primary" : "text-muted")}>
            {pane === k && <span className="absolute inset-x-6 top-0 h-0.5 rounded-b bg-primary" />}
            {icon}{label}
            {k === "agent" && p.agent?.busy && <span className="fw-ping absolute right-[calc(50%-18px)] top-2 h-2 w-2 rounded-full bg-accent" aria-label="The design agent is working" />}
            {k === "features" && repairs.length > 0 && <span className="absolute right-[calc(50%-18px)] top-2 h-2 w-2 rounded-full bg-warning" aria-label="Features need repair" />}
          </button>))}
      </nav>}
      <div className={cx("flex h-7 shrink-0 items-center gap-4 overflow-hidden whitespace-nowrap border-t border-border bg-panel2 px-3 text-[11.5px] text-muted", phone && "hidden")}>
        <span>{st?.part ?? p.name}</span>
        {st?.material && <span>{st.material === "unspecified" ? "No material" : st.material}</span>}
        {fp && <><span>{fp.bbox.map(n => n.toFixed(2)).join(" × ")} mm</span><span>{num(fp.volume, 1)} mm³</span><span>{fp.faces} faces</span></>}
        {selection.length > 0 && <span className="text-primary">{selection.length} selected</span>}
        {st?.timings_s?.total_s !== undefined && <span>build {st.timings_s.total_s}s</span>}
        <span className="ml-auto">Units: {me?.user?.preferences?.units === "in" ? "in (display) · model mm" : "mm"}</span>
        <span>{p.builds} builds</span>
      </div>
    </div>
  );
}
