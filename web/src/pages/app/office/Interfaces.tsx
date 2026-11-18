import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Circle, Crosshair, FileDiff, GitPullRequestArrow, History, Lock, Ruler, ShieldCheck, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Input, Modal } from "@/components/ui";
import { BASE } from "./api";
import { changedValues, crDelta, crTone, FIELD_LABEL, fieldValue, ifaceStatus, ifaceSummary, sideStatus, type SideStatus } from "./model";
import type { ChangeRequest, CheckRow, Icd, IcdSide, Interface, Program } from "./types";

const STATUS: Record<SideStatus, { icon: JSX.Element; label: string }> = {
  pass: { icon: <CheckCircle2 className="h-3.5 w-3.5 text-success" />, label: "Measured: conforms" },
  fail: { icon: <XCircle className="h-3.5 w-3.5 text-danger" />, label: "Measured: does not conform" },
  pending: { icon: <Circle className="h-3.5 w-3.5 text-muted" />, label: "Not built yet" },
};

const fmt = (v: unknown): string => {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  if (Array.isArray(v)) return v.every(x => Array.isArray(x)) ? (v as number[][]).map(p => `(${p.map(fmt).join(", ")})`).join(" ") : `(${v.map(fmt).join(", ")})`;
  return v === null || v === undefined ? "—" : String(v);
};

const DATA_ROWS: Record<Interface["kind"], [string, string][]> = {
  hole_pattern: [["fastener", "Fastener"], ["count", "Holes"], ["d", "Hole Ø (ISO 273 medium)"], ["pattern", "Pattern"], ["pcd", "PCD"],
    ["inset", "Edge distance"], ["plane_z", "Mounting face Z"], ["positions", "Positions (X, Y)"], ["flatness", "Flatness"], ["position_tol", "Position tol. ±"]],
  shaft_bore: [["d", "Nominal Ø"], ["fit", "Fit (ISO 286)"], ["length", "Engagement"], ["axis", "Axis (X, Y)"], ["z", "Along Z"], ["flush_z", "Flush end Z"], ["position_tol", "Position tol. ±"]],
  face: [["plane_z", "Plane Z"], ["flatness", "Flatness"], ["position_tol", "Position tol. ±"]],
  gear_mesh: [["module", "Module"], ["teeth_a", "Teeth (first)"], ["teeth_b", "Teeth (second)"], ["ratio", "Ratio"], ["centre_distance", "Centre distance"],
    ["face_width", "Face width"], ["pressure_angle", "Pressure angle (°)"]],
};

function Rows({ rows }: { rows: CheckRow[] }) {
  return (
    <table className="mt-1 w-full text-[11.5px]">
      <thead><tr className="text-left text-muted"><th className="py-0.5 font-medium">Feature</th><th className="font-medium">Specified</th><th className="font-medium">Measured</th><th /></tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i} className="border-t border-border/60 align-top">
          <td className="py-1 pr-2">{r.feature}</td><td className="pr-2 font-mono text-[11px]">{r.spec}</td>
          <td className={cx("pr-2 font-mono text-[11px]", !r.ok && "text-danger")}>{r.measured}</td>
          <td>{r.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-success" /> : <XCircle className="h-3.5 w-3.5 text-danger" />}</td>
        </tr>))}</tbody>
    </table>
  );
}

function Side({ s, title }: { s: IcdSide; title: string }) {
  const st = sideStatus(s.check);
  return (
    <div className="rounded-md border border-border p-2.5">
      <div className="flex items-center gap-1.5 text-[12.5px]">
        {STATUS[st].icon}<span className="font-semibold">{s.name}</span>
        {s.key && <span className="font-mono text-[10.5px] text-muted">{s.key}</span>}
        <span className="ml-auto text-[11px] text-muted">{title}</span>
      </div>
      <ul className="mt-1 space-y-0.5 text-[11.5px] text-muted">
        {s.features.map((f, i) => <li key={i}>
          {f.type === "hole" ? `${f.label}: Ø${fmt(f.d)}${f.fit ? ` ${f.fit}` : ""} at (${fmt(f.c?.[0])}, ${fmt(f.c?.[1])})`
            : f.type === "boss" ? `${f.label} at (${fmt(f.c?.[0])}, ${fmt(f.c?.[1])})`
              : f.type === "face" ? `${f.label}: Z ${fmt(f.z)}` : f.label}
        </li>)}
      </ul>
      <div className="mt-1 text-[10.5px] text-muted">Part frame: origin at the centre of its envelope.</div>
      {s.check ? <Rows rows={s.check.rows} /> : <div className="mt-1 text-[11.5px] text-muted">{STATUS[st].label}: Gage measures it when the part is built.</div>}
    </div>
  );
}

function EditForm({ f, mode, program, onDone }: { f: Interface; mode: "edit" | "cr"; program: Program; onDone: () => void }) {
  const qc = useQueryClient();
  const icd = program.icd!;
  const [form, setForm] = useState<Record<string, string>>(() => Object.fromEntries(f.editable.map(k => [k, fieldValue(f, k)])));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm(Object.fromEntries(f.editable.map(k => [k, fieldValue(f, k)]))); }, [f]);
  const values = changedValues(f, form);
  const submit = async () => {
    setBusy(true);
    try {
      if (mode === "edit") {
        const v = await api.patch<Program>(`${BASE}/programs/${program.id}/icd/interfaces/${f.id}`, { values });
        qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
        toast.success(`${f.id} updated`);
      } else {
        const v = await api.post<Program & { cr: { id: string; status: string } }>(`${BASE}/programs/${program.id}/change-requests`, { interface: f.id, values, reason });
        qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
        const cr = v.change_requests?.find(c => c.id === v.cr.id);
        if (cr?.status === "accepted") toast.success(`Archie accepted ${cr.id}: ICD v${cr.version_after}. Affected parts are reopened.`);
        else toast.error(`Archie rejected ${cr?.id}: ${cr?.decision?.reason ?? ""}`);
      }
      onDone();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-2">
        {f.editable.map(k => (
          <label key={k} className="block text-[12px]"><span className="text-muted">{FIELD_LABEL[k] ?? k}</span>
            {k === "fastener" ? <select className="input mt-0.5 h-8" value={form[k] ?? ""} onChange={e => setForm(s => ({ ...s, [k]: e.target.value }))}>
              {icd.fasteners.map(x => <option key={x} value={x}>{x}</option>)}</select>
              : k === "fit" ? <select className="input mt-0.5 h-8" value={form[k] ?? ""} onChange={e => setForm(s => ({ ...s, [k]: e.target.value }))}>
                {icd.fits.map(x => <option key={x} value={x}>{x}</option>)}</select>
                : <Input className="mt-0.5 h-8" type="number" step="any" value={form[k] ?? ""} onChange={e => setForm(s => ({ ...s, [k]: e.target.value }))} />}
          </label>))}
      </div>
      {mode === "cr" && <label className="block text-[12px]"><span className="text-muted">Reason (Archie decides on it)</span>
        <Input className="mt-0.5" value={reason} onChange={e => setReason(e.target.value)} placeholder="Why the interface has to change" /></label>}
      <div className="flex items-center gap-2">
        <Button size="sm" loading={busy} disabled={!Object.keys(values).length || (mode === "cr" && !reason.trim())} onClick={submit}>
          {mode === "edit" ? "Save the change" : "Send to Archie"}</Button>
        <span className="text-[11.5px] text-muted">{Object.keys(values).length ? `Changing ${Object.keys(values).map(k => FIELD_LABEL[k]?.replace(/ \(.*\)$/, "") ?? k).join(", ")}` : "Change a value first."}</span>
      </div>
      {mode === "cr" && <p className="text-[11px] text-muted">Archie accepts a change only if it fits inside the frozen envelopes, moves no other part and both parts can take it. On accept the ICD version goes up, the affected tickets reopen with the change and their placeholders are rebuilt.</p>}
    </div>
  );
}

function Detail({ f, program, crs }: { f: Interface; program: Program; crs: ChangeRequest[] }) {
  const icd = program.icd!;
  const canEdit = program.can_edit !== false;
  const [mode, setMode] = useState<"edit" | "cr" | null>(null);
  useEffect(() => setMode(null), [f.id]);
  const draft = icd.status === "draft";
  const data = f.data as Record<string, unknown>;
  return (
    <Card className="space-y-3 p-4" data-icd-detail={f.id}>
      <div>
        <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[12px] text-muted">{f.id}</span><Badge tone="primary">{f.label}</Badge>
          {f.edited && f.edited.length > 0 && <Badge tone="neutral">edited</Badge>}<span className="ml-auto text-[11px] text-muted">datums {f.datums.join(" | ")}</span></div>
        <h3 className="mt-1 text-[15px] font-semibold">{f.name}</h3>
      </div>
      <table className="w-full text-[12.5px]"><tbody>
        {DATA_ROWS[f.kind].filter(([k]) => data[k] !== undefined && data[k] !== null).map(([k, label]) => (
          <tr key={k} className="border-t border-border/60 first:border-0"><td className="py-1 pr-3 text-muted">{label}</td><td className="py-1 font-mono text-[12px]">{fmt(data[k])}{["d", "pcd", "inset", "plane_z", "length", "flatness", "position_tol", "centre_distance", "face_width", "flush_z"].includes(k) ? " mm" : ""}</td></tr>))}
        {f.limits?.hole && f.limits.shaft && <tr className="border-t border-border/60"><td className="py-1 pr-3 text-muted">Limits (ISO 286, verify)</td>
          <td className="py-1 font-mono text-[12px]">bore {f.limits.hole[0].toFixed(3)}…{f.limits.hole[1].toFixed(3)} · shaft {f.limits.shaft[0].toFixed(3)}…{f.limits.shaft[1].toFixed(3)}</td></tr>}
      </tbody></table>
      <div className="grid gap-2 xl:grid-cols-2">
        <Side s={f.sides.a} title={f.kind === "shaft_bore" ? "bore side" : "carries it"} />
        <Side s={f.sides.b} title={f.kind === "shaft_bore" ? "shaft side" : "sits on it"} />
      </div>
      {canEdit && f.editable.length > 0 && (mode ? <div className="rounded-md border border-primary/30 bg-primary-soft/40 p-3">
        <div className="mb-2 flex items-center gap-2 text-[12.5px] font-semibold">{mode === "edit" ? "Edit before approval" : "Change request"}<button className="ml-auto text-[11.5px] font-normal text-muted hover:text-text" onClick={() => setMode(null)}>Cancel</button></div>
        <EditForm f={f} mode={mode} program={program} onDone={() => setMode(null)} /></div>
        : <Button size="sm" variant="secondary" icon={draft ? <Ruler className="h-4 w-4" /> : <GitPullRequestArrow className="h-4 w-4" />} onClick={() => setMode(draft ? "edit" : "cr")}>
          {draft ? "Edit the numbers" : "Raise a change request"}</Button>)}
      {crs.length > 0 && <div><div className="label mb-1">Change requests</div><div className="space-y-1.5">{crs.map(c => <CrCard key={c.id} c={c} />)}</div></div>}
    </Card>
  );
}

export function CrCard({ c, compact }: { c: ChangeRequest; compact?: boolean }) {
  const tone = crTone(c.status);
  return (
    <div data-cr={c.id} className={cx("rounded-md border p-2 text-[12px]", tone === "success" ? "border-success/30 bg-success/5" : tone === "danger" ? "border-danger/30 bg-danger/5" : "border-warning/40 bg-warning/5")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <GitPullRequestArrow className="h-3.5 w-3.5 text-muted" /><span className="font-mono text-[11px] font-semibold">{c.id}</span>
        <span className="font-mono text-[11px] text-muted">{c.interface}</span>
        <Badge tone={tone} className="ml-auto">{c.status === "accepted" ? `accepted · v${c.version_after}` : c.status}</Badge>
      </div>
      <div className="mt-0.5 font-medium">{crDelta(c)}</div>
      {!compact && <div className="text-muted">“{c.reason}” · {c.by?.name}{c.created_at ? ` · ${ago(c.created_at)}` : ""}</div>}
      {c.decision && <div className={cx("mt-0.5", compact && "line-clamp-2")}><span className="font-medium">Archie:</span> {c.decision.reason}</div>}
    </div>
  );
}

function SkeletonCard({ icd }: { icd: Icd }) {
  const sk = icd.skeleton;
  const items = Object.values(sk.items);
  const assumed = items.filter(i => i.source === "assumed");
  return (
    <Card className="p-4 text-[12.5px]" data-skeleton>
      <div className="mb-1 flex items-center gap-2"><Crosshair className="h-4 w-4 text-primary" /><span className="font-semibold">Skeleton</span>
        <span className="text-muted">· conceptual layout: real geometry comes from the parts</span></div>
      <p className="text-muted">{sk.csys}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {sk.datums.map(d => <span key={d.id} className="rounded border border-border px-1.5 py-0.5 font-mono text-[11px]" title={d.name}>{d.id} · {d.name}</span>)}
        {sk.axes.map(a => <span key={a.id} className="rounded border border-border px-1.5 py-0.5 font-mono text-[11px]">{a.id} · {a.name} at ({fmt(a.origin[0])}, {fmt(a.origin[1])})</span>)}
      </div>
      <div className="mt-2 grid gap-1 sm:grid-cols-3">
        <div><span className="text-muted">Envelope</span> <span className="font-mono">{sk.envelope.size.map(fmt).join(" × ")} mm</span></div>
        <div><span className="text-muted">Designed parts</span> {items.length} <span className="text-muted">· standard</span> {sk.standard.length}</div>
        <div><span className="text-muted">Interfaces</span> {icd.interfaces.length}</div>
      </div>
      {assumed.length > 0 && <p className="mt-2 text-[11.5px] text-warning">Assumed envelopes (no size in the plan): {assumed.map(i => i.name).join(", ")}. Check them here before you approve.</p>}
      {sk.notes.map((n, i) => <p key={i} className="mt-1 text-[11.5px] text-muted">{n}</p>)}
    </Card>
  );
}

/** The ICD page: every interface with its numbers, the parts on both sides and their measured conformance, the
 * skeleton, edits at the gate, change requests and the version history. */
export default function Interfaces({ program }: { program: Program }) {
  const qc = useQueryClient();
  const icd = program.icd;
  const [sel, setSel] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const crs = useMemo(() => program.change_requests ?? [], [program.change_requests]);
  if (!icd) return <EmptyState icon={<FileDiff />} title="No interfaces document" body="This program was planned before the Design Office named interfaces. New programs get a skeleton and an ICD at the brief gate." />;
  const f = icd.interfaces.find(x => x.id === sel) ?? icd.interfaces[0];
  const canEdit = program.can_edit !== false;
  const approve = async () => {
    setApproving(true);
    try {
      const v = await api.post<Program>(`${BASE}/programs/${program.id}/gates/icd/approve`);
      qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
      toast.success("Interfaces approved: part tickets are released and Fitz is assembling the placeholders.");
      setConfirm(false);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setApproving(false); }
  };
  return (
    <div className="space-y-3" data-icd>
      {icd.status === "draft" ? (
        <Card className="flex flex-wrap items-center gap-3 border-warning/40 bg-warning/5 p-3" data-icd-gate>
          <ShieldCheck className="h-5 w-5 text-warning" />
          <div className="min-w-[260px] flex-1 text-[13px]"><b>Architecture and interfaces: your review.</b> Archie laid the program out and named {icd.interfaces.length} interfaces with numbers. Check them, edit what needs changing, then approve: part tickets are released, the envelopes freeze, and Fitz assembles the placeholders.</div>
          {canEdit && <Button loading={approving} disabled={icd.problems.length > 0} icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setConfirm(true)} data-testid="approve-icd">Approve ICD v{icd.version}</Button>}
        </Card>
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted"><Lock className="h-3.5 w-3.5" />ICD v{icd.version} approved. Interfaces change through a change request; Archie decides.</div>
      )}
      {icd.problems.length > 0 && <Card className="border-danger/40 bg-danger/5 p-3 text-[12.5px] text-danger"><AlertTriangle className="mr-1 inline h-4 w-4" />{icd.problems[0]}</Card>}
      <SkeletonCard icd={icd} />
      <div className="grid gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,6fr)]">
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[12.5px]">
            <thead className="border-b border-border bg-panel2/60 text-left text-[11px] uppercase tracking-wider text-muted">
              <tr><th className="px-3 py-2 font-semibold">Interface</th><th className="px-2 font-semibold">Numbers</th><th className="px-2 font-semibold">Sides</th><th className="px-2 font-semibold" /></tr></thead>
            <tbody>{icd.interfaces.map(x => {
              const st = ifaceStatus(x);
              return (
                <tr key={x.id} onClick={() => setSel(x.id)} data-icd-row={x.id}
                  className={cx("cursor-pointer border-b border-border/60 last:border-0 hover:bg-text/[.03]", f?.id === x.id && "bg-primary-soft/60")}>
                  <td className="px-3 py-2"><div className="font-mono text-[11px] text-muted">{x.id} · {x.label}</div><div className="font-medium">{x.name.split(": ")[0]}</div></td>
                  <td className="px-2 font-mono text-[11.5px]">{ifaceSummary(x)}</td>
                  <td className="px-2"><span className="inline-flex items-center gap-1" title={`${x.sides.a.name}: ${STATUS[sideStatus(x.sides.a.check)].label}`}>{STATUS[sideStatus(x.sides.a.check)].icon}</span>
                    <span className="mx-0.5 text-muted">↔</span><span className="inline-flex items-center gap-1" title={`${x.sides.b.name}: ${STATUS[sideStatus(x.sides.b.check)].label}`}>{STATUS[sideStatus(x.sides.b.check)].icon}</span></td>
                  <td className="px-2 text-right">{x.crs.length > 0 && <Badge tone="warning">{x.crs.length} CR</Badge>}{st === "pass" && <Badge tone="success">conforms</Badge>}</td>
                </tr>);
            })}</tbody>
          </table>
        </Card>
        {f && <Detail f={f} program={program} crs={crs.filter(c => c.interface === f.id)} />}
      </div>
      <Card className="p-4" data-icd-history>
        <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold"><History className="h-4 w-4 text-muted" />History</div>
        <ol className="space-y-2">{[...icd.history].reverse().map((h, i) => (
          <li key={i} className="flex gap-3 text-[12.5px]">
            <Badge tone={h.kind === "cr_accepted" ? "warning" : h.kind === "approved" ? "success" : "neutral"}>v{h.version}</Badge>
            <div className="min-w-0"><div>{h.text}{h.reason ? ` “${h.reason}”` : ""}</div>
              {h.changes.length > 0 && <div className="font-mono text-[11px] text-muted">{h.changes.slice(0, 6).map(c => `${c.interface} ${c.field}: ${fmt(c.before)} → ${fmt(c.after)}`).join(" · ")}{h.changes.length > 6 ? ` · +${h.changes.length - 6}` : ""}</div>}
              <div className="text-[11px] text-muted">{h.by}{h.at ? ` · ${ago(h.at)}` : ""}</div></div>
          </li>))}</ol>
        {crs.length > 0 && <div className="mt-3"><div className="label mb-1">All change requests</div><div className="grid gap-2 md:grid-cols-2">{crs.map(c => <CrCard key={c.id} c={c} />)}</div></div>}
      </Card>
      <Modal open={confirm} onOpenChange={setConfirm} title={`Approve ICD v${icd.version}?`}
        description="Part tickets are released to the office, the envelopes freeze, and later interface changes go through change requests that Archie decides."
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button><Button loading={approving} onClick={approve} data-testid="confirm-approve-icd">Approve</Button></>} />
    </div>
  );
}
