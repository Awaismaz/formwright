import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Box, Layers, Lock, Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, Input, Modal, PageLoader, Spinner, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";
import type { AsmSummary, Sources, ToolboxComp } from "./types";
import { MarkVerified, verificationLabel } from "@/components/MarkVerified";

export function InsertDialog({ open, onOpenChange, onInsert, busy, current, onInsertSub }: {
  open: boolean; onOpenChange: (v: boolean) => void; busy: boolean;
  onInsert: (body: { project_id: string } | { toolbox: { code: string; params: Record<string, number> } }) => void;
  /** Nested assemblies: insert another assembly as a sub-assembly. */
  current?: string; onInsertSub?: (assemblyId: string) => void;
}) {
  const q = useQuery({ queryKey: ["asm-sources"], queryFn: () => api.get<Sources>("/api/m/assembly/sources"), enabled: open, staleTime: 30_000 });
  const asms = useQuery({ queryKey: ["asm-list"], queryFn: () => api.get<{ items: AsmSummary[] }>("/api/m/assembly/assemblies"),
    enabled: open && !!onInsertSub, staleTime: 10_000 });
  const [tab, setTab] = useState("projects");
  const [code, setCode] = useState<string | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => { if (!busy) setPending(null); }, [busy]);
  useEffect(() => { if (open) api.post("/api/m/assembly/warm").catch(() => undefined); }, [open]);
  const comp = q.data?.toolbox.find(c => c.code === code) ?? null;
  const can = (p: { verified: boolean; geometry?: boolean }) => p.verified || !!p.geometry;
  const groups = useMemo(() => {
    const g: Record<string, ToolboxComp[]> = {};
    for (const c of q.data?.toolbox ?? []) (g[c.category] ??= []).push(c);
    return g;
  }, [q.data]);
  const pick = (c: ToolboxComp) => {
    setCode(c.code);
    setVals(Object.fromEntries(c.params.map(p => [p.name, String(p.default)])));
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} wide title="Insert component"
      description="Project parts come in at their latest build; one with a check open is labelled Unverified until it passes or you mark it as verified. Toolbox parts are generated from standard tables.">
      {!q.data ? <PageLoader /> : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabList><Tab value="projects"><Box className="h-4 w-4" />Project parts</Tab><Tab value="toolbox"><Wrench className="h-4 w-4" />Toolbox</Tab>
            {onInsertSub && <Tab value="subs"><Layers className="h-4 w-4" />Sub-assembly</Tab>}</TabList>
          {onInsertSub && <TabPanel value="subs" className="pt-4">
            <p className="mb-2 text-[12px] text-muted">The assembly goes in as one sub-assembly with its own mates and fastener stacks. It is a copy: when the source assembly changes, the tree shows “Updated” and Refresh brings it in again.</p>
            <div className="grid max-h-[52vh] gap-2 overflow-y-auto sm:grid-cols-2">
              {(asms.data?.items ?? []).filter(a => a.id !== current).map(a => (
                <button key={a.id} type="button" disabled={busy || a.instances === 0} onClick={() => onInsertSub(a.id)} data-insert-sub={a.id}
                  className={cx("card flex items-center gap-3 p-2.5 text-left transition", a.instances ? "hover:shadow-pop" : "cursor-not-allowed opacity-60")}>
                  <Layers className="h-5 w-5 shrink-0 text-primary" />
                  <span className="min-w-0"><span className="block truncate text-[13px] font-semibold">{a.name}</span>
                    <span className="text-[11.5px] text-muted">{a.instances} parts · {a.mates} mates</span></span>
                </button>))}
              {asms.data && asms.data.items.filter(a => a.id !== current).length === 0 && <div className="col-span-2 py-8 text-center text-sm text-muted">No other assemblies yet.</div>}
            </div>
          </TabPanel>}
          <TabPanel value="projects" className="pt-4">
            <div className="grid max-h-[52vh] gap-3 overflow-y-auto sm:grid-cols-3">
              {q.data.projects.map(p => (
                <div key={p.id} role="button" tabIndex={0} aria-disabled={!can(p) || busy} onClick={() => { if (!can(p) || busy) return; setPending(p.id); onInsert({ project_id: p.id }); }} data-insert-project={p.id}
                  onKeyDown={e => { if (e.key === "Enter" && can(p) && !busy) { setPending(p.id); onInsert({ project_id: p.id }); } }}
                  title={can(p) ? `Insert ${p.name}` : "Build this model in the Design Studio first"}
                  className={cx("card flex cursor-pointer flex-col overflow-hidden text-left transition", can(p) ? "hover:-translate-y-0.5 hover:shadow-pop" : "cursor-not-allowed opacity-60")}>
                  <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-border">
                    {p.thumbnail ? <IsoThumb src={p.thumbnail} /> : <Box className="h-8 w-8 text-muted/50" />}
                    {pending === p.id && busy && <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-panel/80 text-[12px] font-medium text-muted">
                      <Spinner className="h-4 w-4" />Snapshotting the part…<span className="text-[11px] font-normal">exact faces and holes</span></div>}
                  </div>
                  <div className="p-2.5">
                    <div className="truncate text-[13px] font-semibold">{p.name}</div>
                    <div className="flex items-center gap-1 truncate text-[11.5px] text-muted">{!can(p) && <Lock className="h-3 w-3" />}{p.verified ? (p.material ?? "material not set") : can(p) ? (p.material ?? "material not set") : "No built geometry"}</div>
                    {can(p) && !p.verified && <div className="mt-1 space-y-1" onClick={e => e.stopPropagation()}>
                      <div className={cx("truncate rounded-full border px-1.5 text-[10.5px] font-semibold", p.verification === "accepted" ? "border-warning/40 bg-warning/10 text-warning" : "border-danger/40 bg-danger/10 text-danger")}
                        data-verification={p.verification} title={verificationLabel(p.verification ?? "unverified", p.open_checks ?? [], p.accepted_by)}>
                        {verificationLabel(p.verification ?? "unverified", p.open_checks ?? [], p.accepted_by)}</div>
                      <MarkVerified compact projectId={p.id} open={p.open_checks ?? []} accepted={p.verification === "accepted"} onDone={() => void q.refetch()} />
                    </div>}
                  </div>
                </div>
              ))}
              {q.data.projects.length === 0 && <div className="col-span-3 py-8 text-center text-sm text-muted">No projects yet. <Link to="/app/projects" className="text-primary hover:underline">Create one</Link>.</div>}
            </div>
          </TabPanel>
          <TabPanel value="toolbox" className="pt-4">
            <div className="grid gap-4 sm:grid-cols-[220px_minmax(0,1fr)]">
              <div className="max-h-[52vh] space-y-3 overflow-y-auto pr-1">
                {Object.entries(groups).map(([cat, list]) => (
                  <div key={cat}>
                    <div className="label mb-1">{cat}</div>
                    {list.map(c => (
                      <button key={c.code} type="button" onClick={() => pick(c)} data-tb={c.code}
                        className={cx("block w-full rounded px-2 py-1.5 text-left text-[13px]", code === c.code ? "bg-primary-soft font-medium text-primary" : "hover:bg-text/5")}>
                        {c.name}<span className="ml-1 text-[11px] text-muted">{/^\w/.test(c.standard) ? c.standard : ""}</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
              <div>
                {!comp ? <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border p-8 text-sm text-muted">Choose a component.</div> : (
                  <div className="space-y-3">
                    <div><div className="text-[15px] font-semibold">{comp.name}</div><div className="text-[12px] text-muted">{comp.standard} · {comp.material}</div></div>
                    {comp.params.map(p => (
                      <label key={p.name} className="flex items-center gap-2 text-[13px]">
                        <span className="w-40 text-muted">{p.label}</span>
                        {p.options ? (
                          <select className="input h-8 w-32" value={vals[p.name] ?? ""} onChange={e => setVals(v => ({ ...v, [p.name]: e.target.value }))}>
                            {p.options.map(o => <option key={o} value={o}>{p.name === "D" ? `M${o}` : o}</option>)}
                          </select>
                        ) : (
                          <Input type="number" className="h-8 w-32" value={vals[p.name] ?? ""} min={p.min ?? undefined} max={p.max ?? undefined}
                            step={p.integer ? 1 : "any"} onChange={e => setVals(v => ({ ...v, [p.name]: e.target.value }))} />
                        )}
                        <span className="text-muted">{p.unit}</span>
                      </label>
                    ))}
                    <Button loading={busy} onClick={() => onInsert({ toolbox: { code: comp.code, params: Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)])) } })}
                      data-testid="insert-toolbox">Insert {comp.name.toLowerCase()}</Button>
                  </div>
                )}
              </div>
            </div>
          </TabPanel>
        </Tabs>
      )}
    </Modal>
  );
}
