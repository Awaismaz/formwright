import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, AlertTriangle, BadgeCheck, ChevronDown, ChevronRight, FileDown, FileSignature, History, Pencil, Plus, RefreshCw, ShieldX, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card, EmptyState, Modal, Spinner } from "@/components/ui";
import { ago, cx } from "@/lib/format";
import { LevelBadge, ResultView } from "./CalcForm";
import type { Editing } from "./index";
import { type CalcSet, type Catalog, type LoadCase, type UnitSystem, display, fmt } from "./types";

export function SignBanner({ s }: { s: CalcSet }) {
  const st = s.status;
  if (st.state === "signed" && s.signoff) {
    const self = s.signoff.self_check;
    return (
      <div className={cx("flex items-start gap-3 rounded-lg border px-4 py-3 text-[13px]", self ? "border-warning/50 bg-warning/5" : "border-success/30 bg-success/5")} data-signoff="signed">
        <BadgeCheck className={cx("mt-0.5 h-5 w-5 shrink-0", self ? "text-warning" : "text-success")} />
        <div><div className={cx("font-semibold", self ? "text-warning" : "text-success")}>{st.label}: signed by {s.signoff.name} ({s.signoff.role}) · {new Date(s.signoff.at).toLocaleString()}{st.signed_on_rev && ` · model rev ${st.signed_on_rev}`}</div>
          {self && <div className="mt-0.5 text-[12px] text-muted">The signer also authored calculations in this set. An independent check needs another engineer&apos;s signature.</div>}
          <div className="mt-0.5 text-muted">“{s.signoff.statement}”</div>
          <div className="mt-1 font-mono text-[11px] text-muted">content hash {st.hash.slice(0, 16)}…</div></div>
      </div>);
  }
  if (st.state === "model_changed" && s.signoff) {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-warning/50 bg-warning/5 px-4 py-3 text-[13px]" data-signoff="model_changed">
        <RefreshCw className="mt-0.5 h-5 w-5 shrink-0 text-warning" />
        <div><div className="font-semibold text-warning">Model changed since sign-off: re-check. Not for release.</div>
          <div className="mt-0.5 text-muted">Signed by {s.signoff.name} on {new Date(s.signoff.at).toLocaleString()} against model rev {st.signed_on_rev ?? "—"}; the part is now rev {st.current_rev ?? "—"}. Results are back to preliminary estimates until the calculations are updated from the current model and signed again. The earlier signature stays in the history.</div></div>
      </div>);
  }
  if (st.state === "invalidated") {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-[13px]" data-signoff="invalidated">
        <ShieldX className="mt-0.5 h-5 w-5 shrink-0 text-danger" />
        <div><div className="font-semibold text-danger">Signature invalid: edited after sign-off. Unsigned: not for release.</div>
          <div className="mt-0.5 text-muted">Signed by {s.signoff?.name} on {s.signoff && new Date(s.signoff.at).toLocaleString()}, but the inputs, results, notes or linked load cases changed since. Review and sign again.</div></div>
      </div>);
  }
  return (
    <div className="flex items-center gap-3 rounded-lg border border-warning/40 bg-warning/5 px-4 py-3 text-[13px]" data-signoff="unsigned">
      <AlertOctagon className="h-5 w-5 shrink-0 text-warning" /><div><span className="font-semibold text-warning">Unsigned: not for release.</span> <span className="text-muted">Results are preliminary estimates until a named engineer reviews and signs this set.</span></div>
    </div>);
}

const STATE_SHORT: Record<CalcSet["status"]["state"], string> = { signed: "Signed", model_changed: "Model changed", invalidated: "Invalid", unsigned: "Unsigned" };

export default function SetsPanel({ pid, cat, sys, openCalc }: { pid: string; cat: Catalog; sys: UnitSystem; openCalc: (id: string, inputs?: Record<string, unknown>, p?: Record<string, string> | null, e?: Editing | null) => void }) {
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["eng-sets", pid], queryFn: () => api.get<{ items: CalcSet[] }>(`/api/m/engineering/projects/${pid}/sets`) });
  const lcs = useQuery({ queryKey: ["eng-lc", pid], queryFn: () => api.get<{ items: LoadCase[] }>(`/api/m/engineering/projects/${pid}/loadcases`) });
  const [sel, setSel] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  useEffect(() => { if (!sel && sets.data?.items.length) setSel(sets.data.items[0]!.id); }, [sets.data, sel]);
  if (!sets.data) return <Spinner />;
  const refresh = () => { qc.invalidateQueries({ queryKey: ["eng-sets", pid] }); qc.invalidateQueries({ queryKey: ["eng-projects"] }); };
  const s = sets.data.items.find(x => x.id === sel);
  return (
    <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="space-y-2">
        {cat.can_edit && <Button className="w-full" icon={<Plus className="h-4 w-4" />} onClick={() => setNewOpen(true)}>New calculation set</Button>}
        {sets.data.items.map(x => (
          <button key={x.id} onClick={() => setSel(x.id)} className={cx("w-full rounded-lg border p-3 text-left", x.id === sel ? "border-primary bg-primary-soft/60" : "border-border bg-panel hover:bg-panel2")}>
            <div className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{x.name}</span>
              <Badge tone={x.status.state === "signed" ? (x.status.self_check ? "warning" : "success") : x.status.state === "invalidated" ? "danger" : "warning"}>{STATE_SHORT[x.status.state]}{x.status.state === "signed" && x.status.self_check ? " · self" : ""}</Badge></div>
            <div className="mt-1 text-[11.5px] text-muted">{x.items.length} calculation{x.items.length === 1 ? "" : "s"} · edited {ago(x.updated_at)}</div>
          </button>))}
        {!sets.data.items.length && <p className="px-1 text-[12.5px] text-muted">No calculation sets yet. Run a calculator and use “Add to calculation set”.</p>}
      </aside>
      {s ? <SetDetail key={s.id} s={s} pid={pid} cat={cat} sys={sys} lcs={lcs.data?.items ?? []} refresh={refresh} openCalc={openCalc} onDeleted={() => setSel(null)} />
        : <EmptyState icon={<FileSignature className="h-5 w-5" />} title="Calculation sets" body="Group the calculations that support a design decision, link the load cases they use, and have a named engineer sign them. Any later edit invalidates the signature." />}
      {newOpen && <NewSet pid={pid} lcs={lcs.data?.items ?? []} onClose={() => setNewOpen(false)} onMade={id => { refresh(); setSel(id); }} />}
    </div>
  );
}

function NewSet({ pid, lcs, onClose, onMade }: { pid: string; lcs: LoadCase[]; onClose: () => void; onMade: (id: string) => void }) {
  const [name, setName] = useState("");
  const [ids, setIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const make = async () => {
    setBusy(true);
    try { const r = await api.post<CalcSet>(`/api/m/engineering/projects/${pid}/sets`, { name: name || "Design checks", load_case_ids: ids }); onMade(r.id); onClose(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  return (
    <Modal open onOpenChange={v => !v && onClose()} title="New calculation set" footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={make}>Create</Button></>}>
      <div className="space-y-3">
        <label className="block space-y-1"><span className="text-[13px] font-medium">Name</span><input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Mounting joint, rev B" /></label>
        <LcPicker lcs={lcs} ids={ids} setIds={setIds} />
      </div>
    </Modal>
  );
}

function LcPicker({ lcs, ids, setIds, disabled }: { lcs: LoadCase[]; ids: string[]; setIds: (x: string[]) => void; disabled?: boolean }) {
  if (!lcs.length) return <p className="text-[12px] text-muted">No load cases recorded for this project yet (Load cases tab).</p>;
  return (
    <div><div className="mb-1 text-[13px] font-medium">Linked load cases</div>
      <div className="flex flex-wrap gap-1.5">{lcs.map(l => { const on = ids.includes(l.id); return (
        <button key={l.id} type="button" disabled={disabled} onClick={() => setIds(on ? ids.filter(i => i !== l.id) : [...ids, l.id])} className={cx("rounded-full border px-2.5 py-0.5 text-[12px]", on ? "border-primary bg-primary-soft text-primary" : "border-border text-muted")}>{l.name}</button>); })}</div></div>
  );
}

function SetDetail({ s, pid, cat, sys, lcs, refresh, openCalc, onDeleted }: { s: CalcSet; pid: string; cat: Catalog; sys: UnitSystem; lcs: LoadCase[]; refresh: () => void; openCalc: (id: string, inputs?: Record<string, unknown>, p?: Record<string, string> | null, e?: Editing | null) => void; onDeleted: () => void }) {
  const [notes, setNotes] = useState(s.notes);
  const [conclusion, setConclusion] = useState(s.conclusion);
  const [ids, setIds] = useState(s.load_case_ids);
  const [open, setOpen] = useState<string | null>(null);
  const [signOpen, setSignOpen] = useState(false);
  const [hist, setHist] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = notes !== s.notes || conclusion !== s.conclusion || ids.join() !== s.load_case_ids.join();
  const ro = !cat.can_edit;
  const save = async () => {
    setBusy(true);
    try { await api.patch(`/api/m/engineering/projects/${pid}/sets/${s.id}`, { notes, conclusion, load_case_ids: ids }); refresh(); toast.success(s.status.state === "signed" ? "Saved. The signature is now invalid." : "Saved"); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  const remove = async (iid: string) => {
    try { await api.del(`/api/m/engineering/projects/${pid}/sets/${s.id}/items/${iid}`); refresh(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  const del = async () => {
    if (!confirm(`Delete the set “${s.name}”?`)) return;
    try { await api.del(`/api/m/engineering/projects/${pid}/sets/${s.id}`); refresh(); onDeleted(); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
  };
  return (
    <div className="space-y-4" data-set={s.id}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[17px] font-semibold">{s.name}</h2><LevelBadge level={s.level} cat={cat} label={s.level_label} selfCheck={s.status.self_check} />
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="ghost" icon={<FileDown className="h-4 w-4" />} disabled={!s.items.length} onClick={() => { location.href = `/api/m/engineering/projects/${pid}/sets/${s.id}/report.pdf`; }} data-action="set-pdf">PDF</Button>
          <Button size="sm" variant="ghost" icon={<History className="h-4 w-4" />} onClick={() => setHist(!hist)}>History</Button>
          {!ro && <Button size="sm" variant="ghost" icon={<Trash2 className="h-4 w-4" />} onClick={del}>Delete</Button>}
          {!ro && <Button size="sm" variant="accent" icon={<FileSignature className="h-4 w-4" />} disabled={!s.items.length || dirty} onClick={() => setSignOpen(true)} data-action="sign">Review and sign</Button>}
        </div>
      </div>
      <SignBanner s={s} />
      {hist && <Card className="max-h-60 overflow-y-auto p-3 text-[12px]"><ul className="space-y-1">{[...s.history].reverse().map((h, i) => <li key={i} className={cx("flex gap-2", h.event === "signature_invalidated" && "text-danger", h.event === "signed" && "text-success", h.event === "resigned_on_new_model" && "text-warning")}><span className="w-36 shrink-0 text-muted">{new Date(h.at).toLocaleString()}</span><span className="w-28 shrink-0">{h.by?.name}</span><span>{h.detail}</span></li>)}</ul></Card>}
      <div className="space-y-2">
        {s.items.map(it => {
          const r = it.result;
          const fails = r.checks.filter(c => c.passed === false).length;
          const isOpen = open === it.id;
          return (
            <Card key={it.id} className="overflow-hidden" data-item={it.calc_id}>
              <div className="flex items-center gap-3 px-3 py-2.5">
                <button onClick={() => setOpen(isOpen ? null : it.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-expanded={isOpen}>
                  {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                  <div className="min-w-0"><div className="truncate text-[13.5px] font-medium">{it.title}</div>
                    <div className="truncate text-[11.5px] text-muted">{r.outputs.filter(o => o.primary).slice(0, 3).map(o => { const d = display(o, sys, k => cat.units[k]?.label ?? ""); return `${o.label} ${d.value} ${d.unit}`; }).join(" · ")}</div></div>
                </button>
                {(it.unconfirmed?.length ?? 0) > 0 && <span title={`Example values: ${it.unconfirmed!.map(e => e.label).join(", ")}. Replace or keep them deliberately before signing.`}><Badge tone="warning"><AlertTriangle className="h-3 w-3" />example loads</Badge></span>}
                {it.model_changed && <span title={`Calculated on model rev ${it.build?.model_rev ?? "—"}; the part has changed since.`}><Badge tone="warning">earlier model</Badge></span>}
                {r.checks.length > 0 && <Badge tone={fails ? "danger" : "success"}>{fails ? `${fails} below requirement` : "all checks met"}</Badge>}
                {r.safety_factor && <span className="hidden text-[11px] text-muted md:inline" title={r.safety_factor.source}>SF {fmt(r.safety_factor.required)} · {r.safety_factor.source.slice(0, 28)}{r.safety_factor.source.length > 28 ? "…" : ""}</span>}
                {!ro && <button aria-label="Edit inputs" title="Edit inputs" className="rounded p-1.5 text-muted hover:bg-text/5" onClick={() => openCalc(it.calc_id, it.raw_inputs, it.source, { setId: s.id, itemId: it.id, title: it.title, confirmed: it.confirmed ?? [] })}><Pencil className="h-4 w-4" /></button>}
                {!ro && <button aria-label="Remove" title="Remove" className="rounded p-1.5 text-muted hover:bg-text/5" onClick={() => remove(it.id)}><Trash2 className="h-4 w-4" /></button>}
              </div>
              {isOpen && <div className="border-t border-border p-3"><ResultView r={r} cat={cat} sys={sys} compact levelLabel={s.level_label} selfCheck={s.status.self_check} />
                <div className="mt-2 text-[11px] text-muted">Added by {it.added_by?.name} {ago(it.added_at)}{it.edited_by && ` · edited by ${it.edited_by.name} ${ago(it.edited_at)}`}</div></div>}
            </Card>);
        })}
        {!s.items.length && <p className="rounded-lg border border-dashed border-border p-4 text-center text-[13px] text-muted">No calculations in this set yet. Run a calculator, then “Add to calculation set”.</p>}
      </div>
      <Card className="space-y-3 p-4">
        <LcPicker lcs={lcs} ids={ids} setIds={setIds} disabled={ro} />
        <label className="block space-y-1"><span className="text-[13px] font-medium">Notes</span><textarea disabled={ro} className="input min-h-[70px] py-2" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Scope, assumptions shared by the calculations, open points" /></label>
        <label className="block space-y-1"><span className="text-[13px] font-medium">Conclusion</span><textarea disabled={ro} className="input min-h-[60px] py-2" value={conclusion} onChange={e => setConclusion(e.target.value)} placeholder="What was checked and against which requirement (e.g. “joint separation factor 11.8 ≥ 2.0 per ES-001”)" /></label>
        {!ro && <div className="flex items-center gap-2"><Button size="sm" disabled={!dirty} loading={busy} onClick={save}>Save</Button>{dirty && s.status.state === "signed" && <span className="text-[12px] text-warning">Saving will invalidate the signature.</span>}</div>}
      </Card>
      {signOpen && <SignDialog s={s} pid={pid} lcs={lcs} onClose={() => setSignOpen(false)} onSigned={refresh} />}
    </div>
  );
}

function SignDialog({ s, pid, lcs, onClose, onSigned }: { s: CalcSet; pid: string; lcs: LoadCase[]; onClose: () => void; onSigned: () => void }) {
  const [statement, setStatement] = useState(s.sign_statement);
  const [ok, setOk] = useState(false);
  const [loadsInCalcs, setLoadsInCalcs] = useState(false);
  const [busy, setBusy] = useState(false);
  const linked = lcs.filter(l => s.load_case_ids.includes(l.id));
  const examples = s.items.filter(i => (i.unconfirmed?.length ?? 0) > 0);
  const older = s.items.filter(i => i.model_changed && i.source);
  const blocked = examples.length > 0 || older.length > 0 || (!linked.length && !loadsInCalcs);
  const sign = async () => {
    setBusy(true);
    try { await api.post(`/api/m/engineering/projects/${pid}/sets/${s.id}/signoff`, { statement, confirm: ok, loads_in_calcs: !linked.length && loadsInCalcs }); onSigned(); toast.success("Set signed"); onClose(); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Sign-off failed"); } finally { setBusy(false); }
  };
  return (
    <Modal open onOpenChange={v => !v && onClose()} title={`Sign “${s.name}”`} description="Your name, role, the time and the model revision are recorded with a hash of every input and result. Any later edit invalidates the signature; a model change sends the set back for a re-check."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="accent" disabled={!ok || blocked} loading={busy} onClick={sign} data-action="confirm-sign">Sign</Button></>}>
      <div className="space-y-3 text-[13px]">
        <div className="rounded-lg bg-panel2 p-3 text-[12px]">{s.items.length} calculation(s): {s.items.map(i => i.title).join(", ")}
          <div className="mt-1 text-muted">{linked.length ? `Load cases: ${linked.map(l => l.name).join(", ")}` : "No load cases linked to this set."}</div></div>
        {examples.length > 0 && <div className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-[12.5px]"><b className="text-warning">Example loads still in use.</b> Replace or confirm them first: {examples.map(i => `${i.title} (${i.unconfirmed!.map(e => e.label).join(", ")})`).join("; ")}.</div>}
        {older.length > 0 && <div className="rounded-lg border border-warning/40 bg-warning/5 px-3 py-2 text-[12.5px]"><b className="text-warning">Pre-filled from an earlier model.</b> Update these from the current model and save them first: {older.map(i => i.title).join(", ")}.</div>}
        {!linked.length && <label className="flex items-start gap-2"><input type="checkbox" checked={loadsInCalcs} onChange={e => setLoadsInCalcs(e.target.checked)} className="mt-0.5 h-4 w-4" aria-label="Loads stated in each calculation" />
          <span>No load case is linked. I confirm the loads are stated in each calculation (or link the load cases first).</span></label>}
        <label className="block space-y-1"><span className="font-medium">Statement</span><textarea className="input min-h-[80px] py-2" value={statement} onChange={e => setStatement(e.target.value)} aria-label="Sign-off statement" /></label>
        <label className="flex items-start gap-2"><input type="checkbox" checked={ok} onChange={e => setOk(e.target.checked)} className="mt-0.5 h-4 w-4" aria-label="Confirm review" />
          <span>I confirm I reviewed these calculations. I understand they are hand-calculation methods (Verified calculation level once signed; marked self-checked if I authored any of them), not a validated simulation, and that they do not certify the design.</span></label>
      </div>
    </Modal>
  );
}
