import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, PenTool, Sparkles, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Input } from "@/components/ui";
import { AgentBadge } from "@/components/AgentBadge";
import { VisualCheck, type VisualRecord } from "@/components/VisualCheck";
import type { AsmView, SmartItem, SmartPlan, SmartResult, Sources, ToolboxParam } from "./types";
import { Section } from "./bits";
import { SOURCE_LABEL, ACTION_LABEL, confidenceTone, paramLine, tokenLine } from "./smart";

const EXAMPLES = [
  "4 M6x25 bolts with washers and nuts for the plate holes",
  "a 6204 bearing on the shaft",
  "the motor bracket from my projects on the plate",
  "two Ø8 dowel pins",
];
const SIZES = [3, 4, 5, 6, 8, 10, 12, 16, 20, 24];

/** "Add components by description" (ASM-019) and assembly planning from text (ASM-010). Hex reads the text into
 * Toolbox components or the workspace's own parts (zero tokens; AI only on request, metered); the confirmation list
 * is editable; Fitz then inserts, places and mates the approved items and runs the interference check. */
export function SmartPanel({ view, aid, onRun, busy }: {
  view: AsmView; aid: string; busy: boolean; onRun: (items: SmartItem[]) => Promise<AsmView | null>;
}) {
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<SmartPlan | null>(null);
  const [items, setItems] = useState<SmartItem[]>([]);
  const [asking, setAsking] = useState<"plan" | "ai" | null>(null);
  const [result, setResult] = useState<SmartResult | null>(null);
  const sources = useQuery({ queryKey: ["asm-sources"], queryFn: () => api.get<Sources>("/api/m/assembly/sources"), staleTime: 30_000 });
  const comp = (code?: string) => sources.data?.toolbox.find(c => c.code === code);

  const ask = async (ai: boolean) => {
    if (text.trim().length < 2) return;
    setAsking(ai ? "ai" : "plan"); setResult(null);
    try {
      const p = await api.post<SmartPlan>(`/api/m/assembly/assemblies/${aid}/smart/plan`, { text, ai });
      setPlan(p); setItems(p.items);
      if (ai) toast.success(`Hex read ${p.ai_read ?? 0} of ${p.ai_lines ?? 0} line${p.ai_lines === 1 ? "" : "s"} with AI · ${p.tokens} tokens`);
    } catch (e) { toast.error((e as Error).message); } finally { setAsking(null); }
  };
  const edit = (id: string, patch: Partial<SmartItem>) => setItems(xs => xs.map(x => x.id === id ? { ...x, ...patch } : x));
  const run = async () => {
    const v = await onRun(items);
    const r = v?.result as SmartResult | undefined;
    if (r) {
      setResult(r); setPlan(null); setItems([]);
      if (r.clashes.length) toast.error(r.summary, { duration: 9000 });
      else if (r.placed_loose) toast.warning(r.summary, { duration: 9000 });
      else toast.success(r.summary);
    }
  };
  const design = async (it: SmartItem) => {
    try {
      const p = await api.post<{ id: string }>("/api/projects", { name: it.title.slice(0, 80) || "New part", description: it.text });
      window.open(`/app/projects/${p.id}?ask=${encodeURIComponent(`Design ${it.text}. It goes into the assembly "${view.assembly.name}".`)}`, "_blank");
    } catch (e) { toast.error((e as Error).message); }
  };
  const ready = items.filter(i => i.enabled && i.source !== "new").length;

  return (
    <div data-testid="smart-panel">
      <Section title="Add components by description">
        <div className="mb-2.5 flex items-center gap-3 text-[11.5px] text-muted">
          <span className="flex items-center gap-1.5"><AgentBadge name="Hex" size={22} state={asking ? "working" : "idle"} /><span><b className="text-text">Hex</b> finds parts</span></span>
          <ArrowRight className="h-3 w-3" />
          <span className="flex items-center gap-1.5"><AgentBadge name="Fitz" size={22} state={busy ? "working" : result ? "done" : "idle"} /><span><b className="text-text">Fitz</b> places and mates</span></span>
        </div>
        <textarea value={text} onChange={e => setText(e.target.value)} rows={3} data-testid="smart-text" disabled={!view.can_edit}
          onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ask(false); } }}
          placeholder="e.g. mount the motor bracket on the plate with 4 M6 bolts, washers and nuts"
          className="input h-auto min-h-[72px] resize-y py-2 text-[12.5px] leading-relaxed" />
        <div className="mt-1.5 flex flex-wrap gap-1">
          {EXAMPLES.map(x => <button key={x} type="button" onClick={() => setText(t => t.trim() ? `${t.trim()}; ${x}` : x)}
            className="rounded-full border border-border bg-panel2 px-2 py-0.5 text-[11px] text-muted hover:text-text">{x}</button>)}
        </div>
        <Button className="mt-2.5 w-full" icon={<Sparkles className="h-4 w-4" />} loading={asking === "plan"} disabled={!view.can_edit || text.trim().length < 2 || !!asking || busy}
          onClick={() => ask(false)} data-testid="smart-ask">Ask Hex</Button>
        <p className="mt-1.5 text-[11px] leading-snug text-muted">Hex looks in the Toolbox first, then in your own verified parts. Nothing changes until you approve the plan.</p>
      </Section>

      {plan && (
        <div className="border-b border-border px-4 py-3.5" data-testid="smart-plan">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="label">Plan · {items.length} item{items.length === 1 ? "" : "s"}</div>
            <span className="text-[11px] text-muted" data-testid="smart-tokens">{tokenLine(plan)}</span>
          </div>
          <ol className="space-y-2">
            {items.map(it => {
              const c = comp(it.code);
              return (
                <li key={it.id} data-smart-item={it.id} className={cx("rounded border border-border bg-panel2/60 p-2.5", !it.enabled && "opacity-55")}>
                  <div className="flex items-start gap-2">
                    {it.source !== "new" && <input type="checkbox" checked={it.enabled} onChange={e => edit(it.id, { enabled: e.target.checked })} className="mt-1" aria-label="Include" />}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] font-semibold text-muted">{it.order}.</span>
                        <span className="text-[12.5px] font-medium">{it.title}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <Badge tone={it.source === "toolbox" ? "primary" : it.source === "project" ? "success" : "warning"}>{SOURCE_LABEL[it.source]}</Badge>
                        <Badge tone={confidenceTone(it.confidence)}>{it.confidence} confidence</Badge>
                        <Badge>{ACTION_LABEL[it.action]}</Badge>
                        {it.ai && <Badge tone="accent">read with AI</Badge>}
                      </div>
                    </div>
                  </div>
                  <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] leading-snug"><AgentBadge name="Hex" size={16} /><span>{it.found}</span></p>
                  {it.source !== "new" && (
                    <div className="mt-2 grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5 text-[11.5px]">
                      {it.action !== "base" && it.action !== "mount" || !it.inst ? <>
                        <span className="text-muted">Qty</span>
                        <Input type="number" min={1} max={64} value={it.qty} className="h-7 w-20 px-1.5 text-[12px]" data-field="qty"
                          onChange={e => edit(it.id, { qty: Math.max(1, Math.min(64, Number(e.target.value) || 1)), qty_explicit: true })} />
                      </> : null}
                      {it.fasten ? <>
                        <span className="text-muted">Size</span>
                        <div className="flex items-center gap-1.5">
                          <select value={it.fasten.size ?? ""} onChange={e => edit(it.id, { fasten: { ...it.fasten!, size: e.target.value ? Number(e.target.value) : null } })}
                            className="h-7 rounded border border-border bg-panel px-1.5 text-[12px]">
                            <option value="">from each hole</option>{SIZES.map(s => <option key={s} value={s}>M{s}</option>)}
                          </select>
                          <span className="text-muted">length from the grip</span>
                        </div>
                        <span className="text-muted">Washers</span>
                        <select value={it.fasten.washers} onChange={e => edit(it.id, { fasten: { ...it.fasten!, washers: e.target.value as "both" } })}
                          className="h-7 w-40 rounded border border-border bg-panel px-1.5 text-[12px]">
                          <option value="both">both sides</option><option value="head">under the head</option><option value="none">none</option>
                        </select>
                      </> : it.source === "toolbox" && c && it.params ? c.params.map((p: ToolboxParam) => (
                        <ParamField key={p.name} p={p} value={it.params![p.name]} onChange={v => edit(it.id, { params: { ...it.params!, [p.name]: v } })} />
                      )) : null}
                    </div>
                  )}
                  {it.source === "toolbox" && it.params && !it.fasten && <p className="mt-1 text-[11px] text-muted">{paramLine(it, c?.params)}</p>}
                  <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] leading-snug text-muted"><AgentBadge name="Fitz" size={16} /><span>{it.plan}</span></p>
                  {it.source === "new" && view.can_edit && (
                    <Button size="sm" variant="secondary" className="mt-2" icon={<PenTool className="h-3.5 w-3.5" />} onClick={() => design(it)}>Design it in the Studio</Button>
                  )}
                </li>
              );
            })}
          </ol>
          {plan.unresolved.length > 0 && !plan.ai_used && (
            <div className="mt-3 rounded border border-warning/30 bg-warning/5 p-2.5 text-[11.5px]">
              <div className="flex items-start gap-1.5 text-warning"><AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
                Hex couldn't read {plan.unresolved.length === 1 ? "one line" : `${plan.unresolved.length} lines`} without AI. Rephrase it (e.g. a size such as M8 or Ø20), design it in the Studio, or let Hex ask the AI.</div>
              <Button size="sm" variant="secondary" className="mt-2" loading={asking === "ai"} disabled={!!asking || busy} onClick={() => ask(true)} data-testid="smart-ai">
                Read with AI (uses tokens)</Button>
            </div>
          )}
          <Button className="mt-3 w-full" loading={busy} disabled={!ready || busy || !!asking} onClick={run} data-testid="smart-run">
            Approve: Fitz assembles {ready} item{ready === 1 ? "" : "s"}</Button>
        </div>
      )}

      {result && (
        <div className="border-b border-border px-4 py-3.5" data-testid="smart-result">
          <div className={cx("mb-2 flex items-start gap-2 rounded border p-2.5 text-[12.5px] font-medium",
            result.clashes.length ? "border-danger/30 bg-danger/5 text-danger" : result.placed_loose ? "border-warning/30 bg-warning/5 text-warning" : "border-success/25 bg-success/5 text-success")}>
            {result.clashes.length ? <XCircle className="mt-px h-4 w-4 shrink-0" /> : <CheckCircle2 className="mt-px h-4 w-4 shrink-0" />}{result.summary}
          </div>
          <ul className="space-y-1.5">
            {result.log.slice(0, -1).map((l, k) => (
              <li key={k} className={cx("flex items-start gap-1.5 text-[11.5px] leading-snug", l.tone === "warn" ? "text-warning" : l.tone === "muted" ? "text-muted" : "text-text")}>
                <AgentBadge name={l.agent} size={16} state={l.tone === "ok" ? "done" : "idle"} /><span>{l.text}</span></li>
            ))}
          </ul>
          {result.clashes.length > 0 && <ul className="mt-2 space-y-0.5 text-[11.5px] text-danger">
            {result.clashes.map((c, k) => <li key={k}>{c.a_name} ↔ {c.b_name}: {c.volume_mm3.toFixed(3)} mm³</li>)}</ul>}
          <p className="mt-2 text-[11px] text-muted">Placements follow the mates Fitz made; check fits and tolerances before release. Edit or delete any mate in the tree.</p>
          {result.checks?.policy && <p className="mt-1 text-[11px] text-muted" data-check-policy={result.checks.policy.exact}>{result.checks.policy.why}</p>}
        </div>
      )}
      {(result || view.instances.length > 0) && <SmartVisual aid={aid} after={result} />}
    </div>
  );
}

function ParamField({ p, value, onChange }: { p: ToolboxParam; value: number | undefined; onChange: (v: number) => void }) {
  return <>
    <span className="text-muted">{p.label}</span>
    {p.options ? (
      <select value={value ?? p.default} onChange={e => onChange(Number(e.target.value))} className="h-7 w-28 rounded border border-border bg-panel px-1.5 text-[12px]">
        {p.options.map(o => <option key={o} value={o}>{p.unit === "mm" && p.name === "D" ? `M${o}` : o}</option>)}
      </select>
    ) : (
      <div className="flex items-center gap-1"><Input type="number" value={value ?? p.default} step={p.integer ? 1 : "any"} min={p.min ?? undefined} max={p.max ?? undefined}
        onChange={e => onChange(Number(e.target.value))} className="h-7 w-20 px-1.5 text-[12px]" />{p.unit && <span className="text-muted">{p.unit}</span>}</div>
    )}
  </>;
}

/** PD-73: the visual check of this assembly (after a smart assembly it runs by itself; "Look again" on demand). */
function SmartVisual({ aid, after }: { aid: string; after: SmartResult | null }) {
  const qc = useQueryClient();
  const key = ["asm-visual", aid];
  const q = useQuery({
    queryKey: key, queryFn: () => api.get<{ visual: VisualRecord | null; image: string | null; stale: boolean; available: boolean }>(`/api/m/assembly/assemblies/${aid}/visual`),
    refetchInterval: d => (d.state.data?.visual?.status === "running" ? 2000 : false),
  });
  const [looking, setLooking] = useState(false);
  useEffect(() => { if (after) void q.refetch(); }, [after]);  // eslint-disable-line react-hooks/exhaustive-deps
  const look = async () => {
    setLooking(true);
    try { qc.setQueryData(key, await api.post(`/api/m/assembly/assemblies/${aid}/visual`)); }
    catch (e) { toast.error((e as Error).message); } finally { setLooking(false); }
  };
  if (!q.data || (!q.data.visual && !q.data.available)) return null;
  return <div className="border-b border-border px-4 py-3.5" data-smart-visual>
    <VisualCheck rec={q.data.visual} image={q.data.image} stale={q.data.stale} onLook={look} looking={looking} canLook={q.data.available} />
  </div>;
}
