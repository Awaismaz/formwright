import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Box, ExternalLink, Layers, Maximize, RefreshCw, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";
import { VisualCheck, VerdictBadge } from "@/components/VisualCheck";
import type { Topo } from "@/viewer/types";
import { AssemblyViewer } from "../modules/assembly/viewer";
import { MotionScrubber, stepScene } from "../modules/assembly/MotionPanel";
import type { MotionResult } from "../modules/assembly/types";
import { AGENT } from "./Avatars";
import { BASE } from "./api";
import { liveCounts, swappedIn } from "./model";
import type { LiveAssembly, LiveInstance, OfficeEvent, Program } from "./types";

const COLUMN_WORD: Record<string, string> = {
  backlog: "Backlog", ready: "Ready", in_design: "In design", in_review: "In review", changes_requested: "Changes requested",
  approved: "Approved", integrated: "Integrated",
};

/** The live program assembly (CD-013): placeholders translucent orange, real parts solid; a part drops into place
 * with a short glow when Fitz swaps it in; clashes in red; exploded slider; hover a part for its ticket's status. */
export default function AssemblyView({ program, recent }: { program: Program; recent: OfficeEvent[] }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["office-assembly", program.id],
    queryFn: () => api.get<LiveAssembly>(`${BASE}/programs/${program.id}/assembly`),
    refetchInterval: d => (d.state.data?.status === "building" ? 2000 : 15_000),
  });
  const host = useRef<HTMLDivElement>(null);
  const eng = useRef<AssemblyViewer | null>(null);
  const kinds = useRef(new Map<string, LiveInstance["kind"]>());
  const [loaded, setLoaded] = useState(0);
  const [explode, setExplode] = useState(0);
  const [tip, setTip] = useState<{ x: number; y: number; id: string } | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [motion, setMotion] = useState<MotionResult | null>(null);
  const [mstep, setMstep] = useState(0);
  const [moving, setMoving] = useState(false);
  useEffect(() => {   // the last motion check of this program (ASM-011)
    let off = false;
    api.get<{ motion: MotionResult | null }>(`${BASE}/programs/${program.id}/assembly/motion`).then(r => { if (!off) setMotion(r.motion); }).catch(() => undefined);
    return () => { off = true; };
  }, [program.id]);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const data = q.data;
  const view = data?.view ?? null;

  // refresh on assembly-related live events
  const lastSeq = useRef(0);
  useEffect(() => {
    const fresh = recent.filter(e => e.seq > lastSeq.current);  // a burst can bring several at once
    if (!fresh.length) return;
    lastSeq.current = Math.max(...fresh.map(e => e.seq));
    if (fresh.some(e => ["ticket.fitted", "assembly.updated", "ticket.integrated", "ticket.comment", "ticket.blocked", "gate.approved", "cr.accepted", "program.done"].includes(e.type)))
      qc.invalidateQueries({ queryKey: ["office-assembly", program.id] });
  }, [recent, qc, program.id]);

  useEffect(() => {
    if (!view) { eng.current?.dispose(); eng.current = null; kinds.current = new Map(); return; }  // rebuilding
    if (!host.current) return;
    if (!eng.current) {
      const v = new AssemblyViewer(host.current, document.documentElement.classList.contains("dark"));
      eng.current = v;
      (window as unknown as { __fwOfficeAsm?: AssemblyViewer }).__fwOfficeAsm = v;
    }
  }, [view]);
  useEffect(() => () => { eng.current?.dispose(); eng.current = null; }, []);

  useEffect(() => {
    const v = eng.current;
    if (!v || !view) return;
    const missing = Object.values(view.parts).filter(p => !v.hasPart(p.key));
    if (!missing.length) { setLoaded(n => n + 1); return; }
    let cancelled = false;
    Promise.all(missing.map(p => api.get<Topo>(p.topo_url).then(t => { if (!cancelled) v.addPart(p.key, t); })))
      .catch(() => undefined).finally(() => { if (!cancelled) setLoaded(n => n + 1); });
    return () => { cancelled = true; };
  }, [view]);

  useEffect(() => {
    const v = eng.current;
    if (!v || !view) return;
    const sc = motion && !motion.stale ? stepScene(motion, mstep) : null;
    v.setInstances(view.instances.map(i => ({ id: i.id, part: i.part, T: sc?.poses?.[i.id] ?? i.T, visible: true, fastener: i.fastener || i.kind === "toolbox",
      tone: i.kind === "placeholder" ? "placeholder" as const : undefined })));
    v.setExplode(view.explode, explode);
    v.setClashes(sc ? sc.meshes : view.clashes.filter(c => c.mesh).map(c => c.mesh!), null);
    v.setHot(sc ? sc.hot : []);
    const fresh = swappedIn(kinds.current, view.instances);
    if (!reduced) for (const id of fresh) v.animateFit(id);
    kinds.current = new Map(view.instances.map(i => [i.id, i.kind]));
  }, [view, loaded, explode, reduced, motion, mstep]);

  if (q.isLoading) return <Card className="flex h-[420px] items-center justify-center"><Spinner className="h-5 w-5" /></Card>;
  if (!data || !data.status) {
    return <EmptyState icon={<Layers />} title="No program assembly yet"
      body="Fitz assembles the program from placeholders as soon as you approve the interfaces (ICD): one block per part, carrying its named holes, bores and faces, mated by interface name." />;
  }
  const rebuild = async () => {
    setRebuilding(true);
    try { await api.post(`${BASE}/programs/${program.id}/assembly/rebuild`); qc.invalidateQueries({ queryKey: ["office-assembly", program.id] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setRebuilding(false); }
  };
  if (data.status !== "ready" || !view) {
    return (
      <Card className="flex flex-col items-center justify-center gap-3 p-10 text-center text-[13px]" data-asm-state={data.status}>
        {data.status === "building" ? <><Spinner className="h-5 w-5" /><div><b>Fitz is assembling the placeholders…</b><div className="text-muted">Envelopes with their interface features, mated by interface name, then an exact interference check.</div></div></>
          : <><AlertTriangle className="h-5 w-5 text-warning" /><div className="max-w-lg">{data.summary}</div>
            {data.can_edit && <Button variant="secondary" loading={rebuilding} icon={<RefreshCw className="h-4 w-4" />} onClick={rebuild}>Rebuild the program assembly</Button>}</>}
      </Card>
    );
  }
  const checkMotion = async () => {
    setMoving(true);
    try {
      const r = await api.post<{ motion: MotionResult }>(`${BASE}/programs/${program.id}/assembly/motion`, { steps: 24 });
      setMotion(r.motion);
      setMstep(r.motion.worst === null ? 0 : Math.max(0, r.motion.steps.findIndex(x => x.i === r.motion.worst)));
      if (r.motion.colliding_steps.length) toast.error(`Collisions in ${r.motion.colliding_steps.length} of ${r.motion.steps.length} steps`);
      else toast.success("The shafts turn through the range without a collision");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setMoving(false); }
  };
  const counts = liveCounts(view.instances);
  const byId = new Map(view.instances.map(i => [i.id, i]));
  const hovered = tip ? byId.get(tip.id) : null;
  const item = hovered?.item ? data.items[hovered.item] : null;
  const clashIds = new Set(view.clashes.flatMap(c => [c.a, c.b]));
  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]" data-live-asm>
      <Card className="relative overflow-hidden">
        <div ref={host} className="viewport-bg h-[520px] w-full max-sm:h-[380px]"
          onPointerMove={e => { const id = eng.current?.instanceAt(e.clientX, e.clientY) ?? null; const r = host.current!.getBoundingClientRect(); setTip(id ? { id, x: e.clientX - r.left, y: e.clientY - r.top } : null); }}
          onPointerLeave={() => setTip(null)} />
        {tip && hovered && (
          <div className="pointer-events-none absolute z-10 max-w-[260px] rounded-md border border-border bg-panel/95 px-2.5 py-1.5 text-[12px] shadow-pop"
            style={{ left: Math.min(tip.x + 14, (host.current?.clientWidth ?? 600) - 270), top: tip.y + 14 }} data-asm-tip>
            <div className="font-semibold">{item?.title ?? hovered.name}</div>
            <div className="text-muted">{hovered.kind === "placeholder" ? "Placeholder: envelope with its interfaces" : hovered.kind === "real" ? "Real part, swapped in" : "Standard part"}</div>
            {item && <div className="mt-0.5"><span className="font-mono text-[11px]">{item.key}</span> · {COLUMN_WORD[item.column] ?? item.column} · {item.progress} % · {AGENT[item.specialist]?.name}</div>}
            {item?.line && <div className="mt-0.5 text-muted">{item.line}</div>}
            {clashIds.has(hovered.id) && <div className="mt-0.5 text-danger">In a clash</div>}
          </div>)}
        <div className="absolute left-2 top-2 flex flex-wrap gap-1.5 text-[11px]">
          <span className="inline-flex items-center gap-1 rounded-full border border-border bg-panel/90 px-2 py-0.5"><span className="h-2.5 w-2.5 rounded-sm border border-[#f08c2e] bg-[#f08c2e]/40" />{counts.placeholders} placeholders</span>
          <span className="inline-flex items-center gap-1 rounded-full border border-border bg-panel/90 px-2 py-0.5"><span className="h-2.5 w-2.5 rounded-sm bg-text/50" />{counts.real} real parts</span>
          {counts.standard > 0 && <span className="inline-flex items-center gap-1 rounded-full border border-border bg-panel/90 px-2 py-0.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#8f99a8]" />{counts.standard} standard</span>}
          {view.clashes.length > 0 && <span className="inline-flex items-center gap-1 rounded-full border border-danger/40 bg-danger/10 px-2 py-0.5 text-danger"><span className="h-2.5 w-2.5 rounded-sm bg-danger" />{view.clashes.length} clash{view.clashes.length > 1 ? "es" : ""}</span>}
        </div>
        <div className="absolute bottom-2 left-2 right-2 flex flex-wrap items-center gap-2 rounded-md border border-border bg-panel/90 px-2 py-1.5 text-[12px]">
          <label className="flex items-center gap-2">Explode<input type="range" min={0} max={100} value={Math.round(explode * 100)} onChange={e => setExplode(Number(e.target.value) / 100)} aria-label="Exploded view" className="w-36" data-explode /></label>
          <button className="ml-auto inline-flex items-center gap-1 text-muted hover:text-text" onClick={() => eng.current?.fit()}><Maximize className="h-3.5 w-3.5" />Fit</button>
        </div>
      </Card>
      <div className="space-y-3">
        <Card className="p-3 text-[12.5px]">
          <div className="mb-1 flex items-center gap-2 font-semibold"><Box className="h-4 w-4 text-primary" />Program assembly
            {view.clashes.length === 0 ? <Badge tone="success" className="ml-auto">0 clashes</Badge> : <Badge tone="danger" className="ml-auto">{view.clashes.length} clashes</Badge>}</div>
          <p className="text-muted">{data.summary}</p>
          {data.check && <p className="mt-1.5 text-[11.5px] text-muted" data-advisory-check>
            {data.check.status === "running" ? "Whole-program clash check running (advisory: nothing waits for it)…" : data.check.text}</p>}
          <div className="mt-2 space-y-1">
            {view.subs.map(s => <div key={s.id} className="flex items-center gap-1.5"><Layers className="h-3.5 w-3.5 text-muted" />{s.name}
              <Link to={`/app/modules/assembly?assembly=${s.assembly_id}`} className="ml-auto inline-flex items-center gap-0.5 text-[11.5px] text-primary hover:underline">open<ExternalLink className="h-3 w-3" /></Link></div>)}
            <Link to={`/app/modules/assembly?assembly=${view.assembly_id}`} className="inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">Open the final assembly in Assembly Studio<ExternalLink className="h-3 w-3" /></Link>
          </div>
        </Card>
        {(data.looks?.length ?? 0) > 0 && <LooksCard looks={data.looks!} />}
        <Card className="p-3 text-[12px]" data-program-motion>
          <div className="mb-1 flex items-center gap-2 font-semibold"><RotateCw className="h-4 w-4 text-primary" />Motion
            <Button size="sm" variant="secondary" className="ml-auto" loading={moving} onClick={checkMotion} data-check-motion>Check motion</Button></div>
          {!motion && <p className="text-muted">Turns every shaft in its bearings through one turn of the input (gear meshes by their ratios) and checks for collisions at each step.</p>}
          {motion && <MotionScrubber m={motion} step={Math.min(mstep, motion.steps.length - 1)} onStep={setMstep} />}
        </Card>
        {view.clashes.length > 0 && <Card className="p-3 text-[12px]">
          <div className="mb-1 font-semibold text-danger">Clashes</div>
          {view.clashes.slice(0, 8).map((c, i) => <div key={i}>{c.a_name} ↔ {c.b_name}: {c.volume_mm3.toFixed(1)} mm³</div>)}
        </Card>}
        <Card className="max-h-[300px] overflow-y-auto p-3 text-[12px]">
          <div className="mb-1 font-semibold">Parts</div>
          {Object.entries(data.items).filter(([, it]) => it.state !== "toolbox").map(([id, it]) => (
            <div key={id} className="flex items-center gap-1.5 py-0.5">
              <span className={cx("h-2.5 w-2.5 shrink-0 rounded-sm", it.state === "real" ? "bg-text/60" : "border border-[#f08c2e] bg-[#f08c2e]/40")} />
              <span className="min-w-0 flex-1 truncate">{it.title}</span><span className="text-muted">{it.state === "real" ? "real" : "placeholder"}</span></div>))}
        </Card>
      </div>
    </div>
  );
}

/** PD-73: the visual checks of the layout and of each level Fitz integrated (advisory), newest first by default. */
function LooksCard({ looks }: { looks: NonNullable<LiveAssembly["looks"]> }) {
  const [sel, setSel] = useState(looks.length - 1);
  const cur = looks[Math.min(sel, looks.length - 1)]!;
  return <Card className="p-3" data-program-looks>
    {looks.length > 1 && <div className="mb-2 flex flex-wrap gap-1">{looks.map((l, k) => (
      <button key={`${l.level}-${k}`} onClick={() => setSel(k)} className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
        k === sel ? "border-primary/50 bg-primary-soft" : "border-border text-muted hover:text-text")}>{l.name.replace(/^Assemble /, "")}<VerdictBadge v={l.verdict} /></button>))}</div>}
    <VisualCheck rec={cur} image={cur.image} compact />
  </Card>;
}
