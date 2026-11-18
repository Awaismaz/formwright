import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, ExternalLink, FileText, Hammer, PackageCheck, PencilRuler, Rocket, Table2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago, cx, num } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Input, Modal, PageLoader, Tip } from "@/components/ui";
import { AgentAvatar } from "./Avatars";
import { BASE } from "./api";
import type { Deliverables as D, Program, ProgramRelease } from "./types";

const g = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x >= 1000 ? `${num(Math.round(x))} g` : `${Math.round(x * 10) / 10} g`);

function ReleaseCard({ program, d }: { program: Program; d: D }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const gate = d.gate;
  const release = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ release: ProgramRelease; program: Program }>(`${BASE}/programs/${program.id}/release`, {
        note, local_date: new Date().toLocaleDateString("en-CA"), tz: Intl.DateTimeFormat().resolvedOptions().timeZone });
      qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...r.program, can_edit: old?.can_edit }));
      qc.invalidateQueries({ queryKey: ["office-deliverables", program.id] });
      toast.success(`${program.name} released as rev ${r.release.rev}: ${r.release.parts.length} parts issued and tagged`);
      setOpen(false);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "The release failed"); } finally { setBusy(false); }
  };
  return (
    <Card className={cx("p-4", gate.ready && "border-success/40")} data-release>
      <div className="flex flex-wrap items-start gap-3">
        <span className={cx("flex h-9 w-9 items-center justify-center rounded-full", gate.released ? "bg-success/15 text-success" : gate.ready ? "bg-primary-soft text-primary" : "bg-panel2 text-muted")}>
          {gate.released ? <PackageCheck className="h-5 w-5" /> : <Rocket className="h-5 w-5" />}</span>
        <div className="min-w-[240px] flex-1">
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-[15px] font-semibold">Release</h3>
            {gate.released && <Badge tone="success">Released · rev {gate.released.rev}</Badge>}</div>
          <p className="text-[12.5px] text-muted">One action: every part the program makes is issued at its next revision through its release gate (frozen
            issue drawing, DFM report) and tagged in its project; one pack holds the parts' STEP, the assembly STEP, the drawings (PDF, DXF), the BOM,
            the DFM summary, the ICD and the program file. Drawings stay NOT APPROVED FOR MANUFACTURE until an engineer approves them.</p>
          {!gate.ready && gate.blocking.length > 0 && <ul className="mt-2 space-y-0.5 text-[12px] text-warning">{gate.blocking.map((b, i) =>
            <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{b}</li>)}</ul>}
        </div>
        {d.can_edit && <Button disabled={!gate.ready} icon={<Rocket className="h-4 w-4" />} onClick={() => setOpen(true)}>
          {gate.released ? `Release rev ${gate.next_rev}` : "Release program"}</Button>}
      </div>
      {gate.releases.length > 0 && <div className="mt-3 divide-y divide-border rounded-md border border-border">
        {gate.releases.map(r => <div key={r.rev} className="flex flex-wrap items-center gap-3 px-3 py-2 text-[12.5px]" data-rev={r.rev}>
          <b className="w-14">Rev {r.rev}</b><span className="text-muted">{r.date} · {r.by} · {r.note}</span>
          <span className="text-muted">{r.parts.length} parts ({r.parts.map(p => `${p.key} rev ${p.rev}`).join(", ")}) · tag “{r.parts[0]?.tag}”</span>
          <a className="ml-auto inline-flex items-center gap-1 font-medium text-primary hover:underline" href={`${BASE}/programs/${program.id}/releases/${r.rev}/pack.zip`}>
            <Download className="h-3.5 w-3.5" />Release pack (.zip{r.pack_bytes ? `, ${Math.round(r.pack_bytes / 1024)} KB` : ""})</a>
        </div>)}
      </div>}
      <Modal open={open} onOpenChange={setOpen} title={`Release ${program.name} rev ${gate.next_rev}`}
        description="Each part is issued at its next revision (or keeps its current one when that exact build was already issued) and tagged in its project."
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={busy} icon={<Rocket className="h-4 w-4" />} onClick={release}>Release</Button></>}>
        <label className="block"><span className="label">Release note</span>
          <Input className="mt-1" value={note} onChange={e => setNote(e.target.value)} maxLength={300} placeholder={gate.releases.length ? "What changed" : "Initial release"} /></label>
        <p className="mt-2 text-[12px] text-muted">Checks prove geometric consistency only; the manufacturing review is advisory and its costs are a relative estimate, not a quote.</p>
      </Modal>
    </Card>
  );
}

function Drawings({ program, d }: { program: Program; d: D }) {
  const drw = d.drawings;
  if (!drw) return null;
  const asm = drw.assembly;
  return (
    <Card className="p-4" data-drawings>
      <div className="mb-2 flex items-center gap-2"><AgentAvatar code="ortho" size={26} still /><h3 className="text-[14px] font-semibold">Drawings</h3>
        <span className="text-[12px] text-muted">by Ortho · {ago(drw.at)}</span></div>
      <div className="grid gap-4 lg:grid-cols-[1fr_minmax(320px,46%)]">
        <div className="space-y-2">
          {drw.sheets.map(s => (
            <div key={s.ticket} className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2 text-[12.5px]" data-sheet={s.key}>
              <PencilRuler className="h-4 w-4 text-muted" /><b>{s.title}</b><span className="font-mono text-[10.5px] text-muted">{s.key}</span>
              {s.ok ? <>
                <span className="text-muted">{s.size} · {s.scale}</span>
                {s.check_passed ? <Tip content="Drawing consistency check (CHK-12) passes"><CheckCircle2 className="h-3.5 w-3.5 text-success" /></Tip>
                  : <Tip content={(s.problems ?? []).join("; ")}><XCircle className="h-3.5 w-3.5 text-danger" /></Tip>}
                <span className="text-muted">{s.spec_dims} spec / {s.inferred_dims} inferred dimensions{s.icd_dims ? ` · ${s.icd_dims} from the ICD` : ""}</span>
                <span className="ml-auto flex items-center gap-2">
                  <a className="text-primary hover:underline" href={`/api/m/drawings/projects/${s.project_id}/files/sheet.pdf?download=1`}>PDF</a>
                  <a className="text-primary hover:underline" href={`/api/m/drawings/projects/${s.project_id}/files/sheet.dxf?download=1`}>DXF</a>
                  <Link className="inline-flex items-center gap-0.5 text-primary hover:underline" to={`/app/modules/drawings?project=${s.project_id}`}>Drawing Studio<ExternalLink className="h-3 w-3" /></Link>
                </span></> : <span className="text-danger">{s.error}</span>}
            </div>))}
          <p className="text-[11.5px] text-muted">Values that equal a model parameter or an interface number of the ICD are tagged spec (fits printed with them);
            the rest are measured from the model and tagged inferred. Every sheet says NOT APPROVED FOR MANUFACTURE.</p>
        </div>
        <div className="rounded-md border border-border p-2">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-[12.5px]"><FileText className="h-4 w-4 text-muted" /><b>Assembly drawing</b>
            {asm.ok ? <span className="text-muted">{asm.scale} · BOM table · {asm.balloons?.length ?? 0} balloons</span> : <span className="text-danger">{asm.error}</span>}
            {asm.urls && <span className="ml-auto flex gap-2">{(["assembly.pdf", "assembly.dxf", "assembly.svg"] as const).filter(n => asm.urls?.[n]).map(n =>
              <a key={n} className="text-primary hover:underline" href={`${asm.urls![n]}?download=1`}>{n.split(".")[1].toUpperCase()}</a>)}</span>}
          </div>
          {asm.urls?.["assembly.svg"] && <a href={asm.urls["assembly.svg"]} target="_blank" rel="noreferrer" title="Open the assembly drawing">
            <img src={asm.urls["assembly.svg"]} alt={`Assembly drawing of ${program.name}`} className="w-full rounded border border-border bg-white" /></a>}
        </div>
      </div>
    </Card>
  );
}

function BomTable({ program, d }: { program: Program; d: D }) {
  const b = d.bom;
  return (
    <Card className="p-4" data-bom>
      <div className="mb-2 flex flex-wrap items-center gap-2"><Table2 className="h-4 w-4 text-muted" /><h3 className="text-[14px] font-semibold">Bill of materials</h3>
        <span className="text-[12px] text-muted">{b.rows.length} lines · {b.total_qty} pieces · {b.make} make / {b.buy} buy · {g(b.total_mass_g)}{b.mass_unknown ? ` (+${b.mass_unknown} without mass)` : ""}</span>
        <a className="ml-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline" href={`${BASE}/programs/${program.id}/bom.csv`}><Download className="h-3.5 w-3.5" />CSV</a></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[12.5px]">
          <thead><tr className="text-left text-[11px] text-muted"><th className="py-1 font-medium">Item</th><th className="font-medium">Qty</th><th className="font-medium">Part</th>
            <th className="font-medium">Make / buy</th><th className="font-medium">Designation · standard</th><th className="font-medium">Material</th>
            <th className="text-right font-medium">Mass each</th><th className="text-right font-medium">Total</th><th className="pl-3 font-medium">Ticket</th></tr></thead>
          <tbody>{b.rows.map(r => (
            <tr key={r.item} className="border-t border-border/60" data-bom-row={r.item}>
              <td className="py-1 tabular-nums">{r.item}</td><td className="tabular-nums">{r.qty}</td>
              <td><span className="font-medium">{r.part}</span><div className="text-[10.5px] text-muted">{r.description}</div></td>
              <td><Badge tone={r.make_buy === "make" ? "primary" : "neutral"}>{r.make_buy}</Badge></td>
              <td>{r.designation ?? "—"}{r.standard && <span className="text-muted"> · {r.standard}</span>}</td>
              <td>{r.material ?? "—"}</td><td className="text-right tabular-nums">{g(r.mass_each_g)}</td><td className="text-right tabular-nums">{g(r.mass_total_g)}</td>
              <td className="pl-3 font-mono text-[11px] text-muted">{r.key ?? "—"}</td>
            </tr>))}</tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-muted">{b.note}</p>
    </Card>
  );
}

function Dfm({ program, d }: { program: Program; d: D }) {
  const s = d.dfm;
  if (!s) return null;
  const maxRel = Math.max(1, ...s.parts.map(p => p.relative_cost ?? 0));
  return (
    <Card className="p-4" data-dfm>
      <div className="mb-2 flex flex-wrap items-center gap-2"><AgentAvatar code="smithy" size={26} still /><h3 className="text-[14px] font-semibold">Manufacturing review</h3>
        <span className="text-[12px] text-muted">by Smithy · {s.analysed} part{s.analysed !== 1 ? "s" : ""} · {s.critical} critical · {s.warning} warning{s.warning !== 1 ? "s" : ""}</span>
        <Badge tone="warning">{s.label}</Badge></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[12.5px]">
          <thead><tr className="text-left text-[11px] text-muted"><th className="py-1 font-medium">Part</th><th className="font-medium">Process</th><th className="font-medium">Flags</th>
            <th className="font-medium">Relative cost (cheapest part = 1)</th><th className="font-medium">Top finding</th><th /></tr></thead>
          <tbody>{s.parts.map(p => {
            const top = p.findings?.[0];
            const tk = program.tickets.find(x => x.id === p.ticket);
            const pid = tk?.project_id ?? tk?.reuse?.project_id;
            return (
              <tr key={p.ticket} className="border-t border-border/60 align-top" data-dfm-row={p.key}>
                <td className="py-1.5"><span className="font-medium">{p.title}</span> <span className="font-mono text-[10.5px] text-muted">{p.key}</span>
                  {p.qty > 1 && <span className="text-muted"> ×{p.qty}</span>}</td>
                <td>{p.ok ? p.process_name : <span className="text-danger">{p.error}</span>}{p.material && <div className="text-[10.5px] text-muted">{p.material}</div>}</td>
                <td className="whitespace-nowrap">{p.ok && <>
                  {(p.critical ?? 0) > 0 && <span className="mr-1 rounded-full bg-danger/10 px-1.5 text-[11px] font-semibold text-danger">{p.critical} critical</span>}
                  {(p.warning ?? 0) > 0 && <span className="mr-1 rounded-full bg-warning/10 px-1.5 text-[11px] font-semibold text-warning">{p.warning} warning</span>}
                  {!p.critical && !p.warning && <span className="text-[11px] text-success">clear</span>}</>}</td>
                <td className="min-w-[180px]">{p.relative_cost ? <div className="flex items-center gap-2">
                  <div className="h-2 w-28 rounded-full bg-panel2"><div className="h-2 rounded-full bg-primary/70" style={{ width: `${(100 * p.relative_cost) / maxRel}%` }} /></div>
                  <span className="tabular-nums">{p.relative_cost.toFixed(2)}×</span>
                  {p.cost_share_pct !== null && p.cost_share_pct !== undefined && <span className="text-[11px] text-muted">{p.cost_share_pct} % of the batch</span>}</div> : "—"}</td>
                <td className="max-w-[320px] text-[12px]">{top ? <Tip content={`${top.measured} (limit ${top.limit}). ${top.fix}`}><span><span className="font-mono text-[10.5px] text-muted">{top.rule}</span> {top.title}</span></Tip> : "—"}</td>
                <td className="whitespace-nowrap pl-2 text-right">{pid && <Link className="inline-flex items-center gap-0.5 text-[12px] text-primary hover:underline"
                  to={`/app/modules/manufacturing?project=${pid}`}>Advisor<ExternalLink className="h-3 w-3" /></Link>}</td>
              </tr>);
          })}</tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-muted">{s.note}</p>
    </Card>
  );
}

export default function Deliverables({ program }: { program: Program }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const q = useQuery({ queryKey: ["office-deliverables", program.id], queryFn: () => api.get<D>(`${BASE}/programs/${program.id}/deliverables`),
    refetchInterval: program.orchestrator?.state === "running" ? 5000 : false });
  if (q.isLoading) return <PageLoader />;
  const d = q.data;
  if (!d) return null;
  const working = d.tickets.filter(t => t.column !== "approved");
  const core = program.tickets.filter(t => t.kind !== "deliverable");
  const integrated = core.length > 0 && core.every(t => t.column === "integrated");
  const make = async () => {
    setBusy(true);
    try {
      const v = await api.post<Program>(`${BASE}/programs/${program.id}/deliverables`);
      qc.setQueryData(["office-program", program.id], (old: Program | undefined) => ({ ...v, can_edit: old?.can_edit }));
      qc.invalidateQueries({ queryKey: ["office-deliverables", program.id] });
      toast.success("Ortho and Smithy have their tickets: press Run to make the deliverables");
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4">
      <ReleaseCard program={program} d={d} />
      {!d.drawings && !d.dfm && <Card className="p-4">
        <EmptyState icon={<Hammer />} title={d.tickets.length ? "Ortho and Smithy are on it" : "Deliverables follow the first article"}
          body={d.tickets.length ? <>{working.map(t => <div key={t.id} className="flex items-center justify-center gap-2 text-[12.5px]">
            <AgentAvatar code={t.agent ?? t.specialist} state={t.agent_state} size={22} />{t.line ?? `${t.title}: ${t.column.replace("_", " ")}`}</div>)}</>
            : d.auto ? "When the final assembly is integrated, Ortho draws every part (with the ICD's interface numbers as spec dimensions) and the assembly with its BOM, and Smithy runs the Manufacturing Advisor on every part."
              : "This program makes its deliverables on request."}
          action={d.can_edit && !d.tickets.length && integrated ? <Button loading={busy} onClick={make}>Make the deliverables now</Button> : undefined} />
      </Card>}
      <Drawings program={program} d={d} />
      <BomTable program={program} d={d} />
      <Dfm program={program} d={d} />
    </div>
  );
}
