import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Box, Lock, Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { cx } from "@/lib/format";
import { Button, Input, Modal, PageLoader, Spinner, Tab, TabList, TabPanel, Tabs } from "@/components/ui";
import { IsoThumb } from "@/components/ProjectCard";
import type { Sources, ToolboxComp } from "./types";

export function InsertDialog({ open, onOpenChange, onInsert, busy }: {
  open: boolean; onOpenChange: (v: boolean) => void; busy: boolean;
  onInsert: (body: { project_id: string } | { toolbox: { code: string; params: Record<string, number> } }) => void;
}) {
  const q = useQuery({ queryKey: ["asm-sources"], queryFn: () => api.get<Sources>("/api/m/assembly/sources"), enabled: open, staleTime: 30_000 });
  const [tab, setTab] = useState("projects");
  const [code, setCode] = useState<string | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => { if (!busy) setPending(null); }, [busy]);
  useEffect(() => { if (open) api.post("/api/m/assembly/warm").catch(() => undefined); }, [open]);
  const comp = q.data?.toolbox.find(c => c.code === code) ?? null;
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
      description="Project parts come in at their latest verified build. Toolbox parts are generated from standard tables.">
      {!q.data ? <PageLoader /> : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabList><Tab value="projects"><Box className="h-4 w-4" />Project parts</Tab><Tab value="toolbox"><Wrench className="h-4 w-4" />Toolbox</Tab></TabList>
          <TabPanel value="projects" className="pt-4">
            <div className="grid max-h-[52vh] gap-3 overflow-y-auto sm:grid-cols-3">
              {q.data.projects.map(p => (
                <button key={p.id} type="button" disabled={!p.verified || busy} onClick={() => { setPending(p.id); onInsert({ project_id: p.id }); }} data-insert-project={p.id}
                  title={p.verified ? `Insert ${p.name}` : "Build and verify this model in the Design Studio first"}
                  className={cx("card flex flex-col overflow-hidden text-left transition", p.verified ? "hover:-translate-y-0.5 hover:shadow-pop" : "cursor-not-allowed opacity-60")}>
                  <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-border">
                    {p.thumbnail ? <IsoThumb src={p.thumbnail} /> : <Box className="h-8 w-8 text-muted/50" />}
                    {pending === p.id && busy && <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-panel/80 text-[12px] font-medium text-muted">
                      <Spinner className="h-4 w-4" />Snapshotting the part…<span className="text-[11px] font-normal">exact faces and holes</span></div>}
                  </div>
                  <div className="p-2.5">
                    <div className="truncate text-[13px] font-semibold">{p.name}</div>
                    <div className="flex items-center gap-1 truncate text-[11.5px] text-muted">{!p.verified && <Lock className="h-3 w-3" />}{p.verified ? (p.material ?? "—") : "No verified build"}</div>
                  </div>
                </button>
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
                        {c.name}<span className="ml-1 text-[11px] text-muted">{c.standard !== "—" ? c.standard : ""}</span>
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
