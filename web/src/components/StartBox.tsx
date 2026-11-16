import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Coins, FileUp, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, track } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Catalog, Template } from "@/lib/types";
import { cx, num } from "@/lib/format";
import { Button } from "./ui";
import { Icon } from "./icons";
import { createProject, useTemplates } from "./NewProjectDialog";

const STEP_EXT = /\.(step|stp)$/i;
const DRAWING_EXT = /\.(pdf|png|jpe?g|webp)$/i;
export const START_ACCEPT = ".step,.stp,.pdf,.png,.jpg,.jpeg,.webp";

export async function fileToB64(f: File): Promise<string> {
  const buf = new Uint8Array(await f.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

/** A readable project name from a brief: its first clause, without the trailing dimensions. */
export function nameFromBrief(text: string): string {
  const first = text.trim().split(/[,.;:\n]/)[0]!.replace(/\s+/g, " ").trim();
  const words = first.split(" ").slice(0, 7).join(" ");
  const name = words.length > 48 ? words.slice(0, 48).replace(/\s+\S*$/, "") : words;
  return name ? name[0]!.toUpperCase() + name.slice(1) : "New part";
}

/** Unique among existing projects: "Mounting plate", then "Mounting plate (2)". */
export function uniqueName(name: string, existing: string[]): string {
  const taken = new Set(existing.map(n => n.toLowerCase()));
  if (!taken.has(name.toLowerCase())) return name;
  let n = 2;
  while (taken.has(`${name} (${n})`.toLowerCase())) n++;
  return `${name} (${n})`;
}

/** Hand a file to the right flow: STEP → a new project with the exact import; PDF/photo → Image & Drawing to CAD. */
export async function startFromFile(file: File, nav: (to: string) => void, existing: string[], onStep?: (msg: string) => void) {
  if (STEP_EXT.test(file.name)) {
    onStep?.("Importing the STEP and recognising its features…");
    const p = await createProject(uniqueName(file.name.replace(STEP_EXT, "").slice(0, 80) || "Imported part", existing), null, `Imported from ${file.name}`);
    track("start_box", { kind: "step" });
    try { await api.post(`/api/projects/${p.id}/import-step`, { filename: file.name, data_b64: await fileToB64(file) }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "The STEP file could not be imported"); }
    nav(`/app/projects/${p.id}`);
    return;
  }
  if (DRAWING_EXT.test(file.name)) {
    onStep?.("Uploading the drawing…");
    track("start_box", { kind: "drawing" });
    const r = await api.post<{ upload: { id: string } }>("/api/m/image2cad/uploads", { filename: file.name, data_b64: await fileToB64(file) });
    nav(`/app/modules/image2cad?upload=${r.upload.id}`);
    return;
  }
  throw new ApiError(415, "Drop a STEP file (.step, .stp), a PDF drawing or a photo (PNG, JPEG, WebP).");
}

/** The Dashboard's one way in: describe a part, or drop what you already have. Templates are suggestions under it. */
export default function StartBox({ existing }: { existing: string[] }) {
  const { me } = useSession();
  const nav = useNavigate();
  const qc = useQueryClient();
  const tpl = useTemplates();
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<Template | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [params, setParams] = useSearchParams();
  useEffect(() => { // ?template=<code> (from search): fill the brief, ready to edit or send
    const code = params.get("template");
    const t = code && tpl.data?.items.find(x => x.code === code);
    if (!t) return;
    setText(t.prompt); setPicked(t);
    params.delete("template"); setParams(params, { replace: true });
    setTimeout(() => document.getElementById("start-brief")?.focus(), 50);
  }, [params, tpl.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = catalog.data?.typical_run?.new;
  const unlimited = !!(me?.god?.enabled && me.god.bypass_tokens);
  const viewer = me?.org?.role === "viewer";

  const start = async () => {
    const brief = text.trim();
    if (!brief || busy) return;
    setBusy("Creating the project…");
    try {
      const name = uniqueName(picked && brief === picked.prompt ? picked.name : nameFromBrief(brief), existing);
      const p = await createProject(name, picked && brief === picked.prompt ? picked.code : null);
      try { sessionStorage.removeItem(`fw_starter_${p.id}`); } catch { /* ignore */ }
      track("start_box", { kind: "text", template: picked?.code ?? "" });
      let toolbox = false;
      try { toolbox = (await api.post<{ matches: unknown[] }>("/api/toolbox/match", { prompt: brief })).matches.length > 0; }
      catch { /* matching is optional */ }
      let sent = false;
      if (!toolbox) {
        try { await api.post(`/api/projects/${p.id}/agent/chat`, { prompt: brief }); sent = true; }
        catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not start the design agent"); }
      } else toast("A standard Toolbox component may fit this part. Press Send in the Studio to compare it with a custom design.");
      if (!sent) try { sessionStorage.setItem(`fw_starter_${p.id}`, brief); } catch { /* ignore */ }
      await qc.invalidateQueries({ queryKey: ["projects"] });
      await qc.invalidateQueries({ queryKey: ["checklist"] });
      nav(`/app/projects/${p.id}`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not create the project"); }
    finally { setBusy(null); }
  };

  const onFile = async (f: File | undefined) => {
    if (!f || busy) return;
    try { await startFromFile(f, nav, existing, setBusy); await qc.invalidateQueries({ queryKey: ["projects"] }); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not open that file"); }
    finally { setBusy(null); }
  };

  return (
    <section data-tour="quickstart">
      <div className={cx("card relative overflow-hidden p-4 transition sm:p-5", drag && "border-primary ring-2 ring-primary/30")}
        onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); void onFile(e.dataTransfer.files[0]); }}>
        <label htmlFor="start-brief" className="flex items-center gap-2 text-[15px] font-semibold"><Sparkles className="h-4 w-4 text-accent" />Describe a part, or drop a STEP, PDF drawing or photo</label>
        <textarea id="start-brief" value={text} disabled={!!busy || viewer} rows={3}
          onChange={e => { setText(e.target.value); if (picked && e.target.value !== picked.prompt) setPicked(null); }}
          onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void start(); } }}
          placeholder="e.g. 6061 aluminium L-bracket, 80 × 60 mm legs, 40 wide, 6 thick, two M8 clearance holes per leg, 4 mm inside fillet"
          className="input mt-3 h-auto min-h-[84px] resize-y py-2.5 text-[14px] leading-relaxed" />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept={START_ACCEPT} hidden onChange={e => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
          <Button variant="secondary" size="sm" icon={<FileUp className="h-4 w-4" />} disabled={!!busy || viewer} onClick={() => fileRef.current?.click()}>Import a file</Button>
          <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[12px] text-muted">
            {busy ? <><Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />{busy}</>
              : viewer ? "Viewers can open parts but not create them."
              : <><Coins className="h-3.5 w-3.5 text-accent" />{unlimited ? "Unlimited tokens (God mode)" : run ? `A new part typically uses ${run.low}–${run.high} tokens · balance ${num(me?.org?.token_balance)}` : ""}
                <span className="kbd ml-1 max-sm:hidden">Ctrl ↵</span></>}
          </span>
          <Button icon={<ArrowRight className="h-4 w-4" />} disabled={!text.trim() || !!busy || viewer} onClick={() => void start()}>Design it</Button>
        </div>
      </div>
      {(tpl.data?.items.length ?? 0) > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12px] text-muted">Try one:</span>
          {tpl.data!.items.map(t => (
            <button key={t.code} disabled={!!busy || viewer} onClick={() => { setText(t.prompt); setPicked(t); document.getElementById("start-brief")?.focus(); }}
              className={cx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition disabled:opacity-50",
                picked?.code === t.code ? "border-primary bg-primary-soft text-primary" : "border-border bg-panel text-text hover:border-primary/50")}>
              <Icon name={t.icon} className="h-3.5 w-3.5" />{t.name}
            </button>))}
        </div>)}
    </section>
  );
}
