import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Bug, Compass, Keyboard, Lightbulb, MessageCircle, Star } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Catalog } from "@/lib/types";
import { Button, Card, Field, PageHeader } from "@/components/ui";
import { Icon } from "@/components/icons";
import { cx, PAGE } from "@/lib/format";

const GUIDES = [
  ["Writing a great design brief", "Lead with function and constraints: material, envelope, interfaces (holes, mating faces), loads you know, and what must not change. Give dimensions with units. Say which edges get fillets or chamfers."],
  ["Reading the checks", "In the Studio's left panel, open Checks (the tick icon). Checks compare the built part with values computed from your requirements: valid solid, bounding box, volume, STEP round-trip and repeatability. A pass means geometric consistency, not strength or manufacturability."],
  ["Editing without spending tokens", "Open Params (the sliders icon) in the left panel, change a named dimension and press Enter: the part rebuilds and is kept only if it still passes its checks. The command bar's Features and Sketch tabs (extrude, fillet, hole, pattern and more) are also free."],
  ["Restoring a revision", "Every build is saved. Open Revisions (the clock icon) and press Restore on any earlier revision: it rebuilds exactly as it was, with no AI call."],
  ["Exporting to your CAD", "Press STEP at the top right of the Studio, or open Files (the download icon) for STEP, STL and 3MF. STEP (AP214) opens in SOLIDWORKS, Creo, Fusion, Inventor or NX as a solid body; the parametric model stays in Formwright. \"Export for SOLIDWORKS\" (Files, or the project menu) adds the part name, units, colour and a parameter sheet; SOLIDWORKS still imports it without feature history."],
  ["How tokens are counted", "Design-agent runs use tokens for the AI work they do. A meter next to Send shows the run's tokens as it works; the run stops at your run budget (Billing → Run budget) and is never charged more. The total appears under each run and in Billing → Token ledger. Hand edits, parameter changes, Toolbox parts and restores are free."],
];

const MODULE_GUIDES: Record<string, string> = {
  drawings: "Open a verified part, then Make → Drawing Studio. Choose the sheet and projection; views, a section, dimensions (marked spec or inferred) and hole callouts are generated. Export SVG, PDF or DXF. Every sheet is marked not approved for manufacture until your engineer signs it off.",
  image2cad: "Drop a PDF drawing, scan, sketch or photo on Home. Review what was read (each value is pinned on the image), answer what is missing and confirm one real dimension for scale. Then hand it to the design agent, which models from the confirmed values only.",
  assembly: "Insert verified parts and Toolbox components, then add mates; the panel says plainly when a part is under- or over-defined. Check interference and clearances, explode the view, and export the BOM (CSV) and assembly STEP. Fastener auto-fit: pick a hole to get the bolt, washers and nut sized from the clearance and grip.",
  manufacturing: "Make → Manufacturing Advisor on a verified part. Choose the process, quantity and shop profile; findings are ranked with the rule behind each, plus a relative cost (not a quote) and the main cost drivers. Print or save the report.",
  engineering: "Pick a calculation (beam, bolted joint, shaft, fit, spring, tolerance stack and more). Inputs are pre-filled from the model where possible; results show the working and the source. They are estimates for an engineer to review, never validation; a signed set is invalidated when the part changes.",
  print: "Make → 3D Print Prep on a verified part, or upload an STL, OBJ or 3MF. It checks watertightness, wall thickness and overhangs, ranks print orientations and exports an oriented STL or 3MF. Geometric checks and rough estimates, not a slicer.",
  mesh: "Make → Render on a verified part. Pick a finish, lighting and view; previews are instant, and final renders and turntables queue in the background and notify you when they are ready. For presentation, not engineering geometry.",
};

// The real bindings in the app (palette, chat and start box, sketcher, viewer mouse).
const KEYS = [["Ctrl + K", "Search parts, sizes and pages"], ["Ctrl + Enter", "Send to the design agent"],
  ["Esc", "Sketch: cancel the current tool"], ["Delete", "Sketch: delete the selection"], ["Ctrl + Z", "Sketch: undo"],
  ["Left-drag", "Viewer: orbit"], ["Right-drag", "Viewer: pan"], ["Scroll", "Viewer: zoom"]];

export default function Help() {
  const nav = useNavigate();
  const [kind, setKind] = useState<"general" | "bug" | "feature">("general");
  const [msg, setMsg] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const mods = (catalog.data?.modules ?? []).filter(m => MODULE_GUIDES[m.code]);
  return (
    <div className={PAGE}>
      <PageHeader title="Help & guided tour" subtitle="Guides, shortcuts and a direct line to the team." />
      <div className="mb-8 grid gap-4 md:grid-cols-3">
        <Card className="flex flex-col p-5"><Compass className="h-6 w-6 text-primary" /><h3 className="mt-3 font-semibold">Product tour</h3><p className="mt-1 flex-1 text-sm text-muted">One minute around the workspace: starting a part, projects, modules and tokens.</p><Button className="mt-4" onClick={() => nav("/app?tour=1")}>Start tour</Button></Card>
        <Card className="flex flex-col p-5"><BookOpen className="h-6 w-6 text-primary" /><h3 className="mt-3 font-semibold">Studio tour</h3><p className="mt-1 flex-1 text-sm text-muted">Open any project and press the ? icon at the top right of the Studio: prompt, viewer, checks, hand modelling, history and Make.</p><Button variant="secondary" className="mt-4" onClick={() => nav("/app/projects")}>Open projects</Button></Card>
        <Card className="flex flex-col p-5"><MessageCircle className="h-6 w-6 text-primary" /><h3 className="mt-3 font-semibold">Talk to us</h3><p className="mt-1 flex-1 text-sm text-muted">Pilots get a direct engineer contact. Email any time and we'll reply within one business day.</p><a href="mailto:support@formwright.dev" className="mt-4"><Button variant="secondary" className="w-full">support@formwright.dev</Button></a></Card>
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card className="p-5">
          <h2 className="font-semibold">Guides</h2>
          <div className="mt-3 divide-y divide-border">
            {GUIDES.map(([q, a]) => (
              <details key={q} className="group py-3 [&_summary::-webkit-details-marker]:hidden">
                <summary className="flex cursor-pointer items-center justify-between text-sm font-medium">{q}<span className="text-muted transition group-open:rotate-45">+</span></summary>
                <p className="mt-2 text-sm leading-relaxed text-muted">{a}</p>
              </details>))}
          </div>
          {mods.length > 0 && <>
            <h2 className="mt-6 font-semibold">Modules</h2>
            <div className="mt-3 divide-y divide-border">
              {mods.map(m => (
                <details key={m.code} className="group py-3 [&_summary::-webkit-details-marker]:hidden">
                  <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium"><Icon name={m.icon} className="h-4 w-4 text-primary" /><span className="flex-1">{m.name}</span><span className="text-muted transition group-open:rotate-45">+</span></summary>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{MODULE_GUIDES[m.code]}</p>
                </details>))}
            </div></>}
        </Card>
        <div className="space-y-6">
          <Card className="p-5">
            <h2 className="flex items-center gap-2 font-semibold"><Keyboard className="h-4 w-4" />Shortcuts</h2>
            <ul className="mt-3 space-y-2 text-sm">{KEYS.map(([k, d]) => <li key={k} className="flex justify-between"><span className="text-muted">{d}</span><span className="kbd">{k}</span></li>)}</ul>
          </Card>
          <Card className="p-5">
            <h2 className="font-semibold">Send feedback</h2>
            <div className="mt-3 flex gap-1.5">
              {([["general", MessageCircle, "General"], ["bug", Bug, "Bug"], ["feature", Lightbulb, "Idea"]] as const).map(([k, I, l]) =>
                <button key={k} onClick={() => setKind(k)} className={cx("flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs", kind === k ? "border-primary bg-primary-soft text-primary" : "border-border")}><I className="h-3.5 w-3.5" />{l}</button>)}
            </div>
            <div className="mt-3"><Field label="Message"><textarea value={msg} onChange={e => setMsg(e.target.value)} rows={4} className="input h-auto py-2" placeholder="What's working, what isn't, what you need next…" /></Field></div>
            <div className="mt-3 flex items-center gap-1">{[1, 2, 3, 4, 5].map(n => <button key={n} onClick={() => setRating(n)} aria-label={`${n} stars`}><Star className={cx("h-5 w-5", rating && n <= rating ? "fill-accent text-accent" : "text-muted")} /></button>)}<span className="ml-2 text-xs text-muted">How's Formwright so far?</span></div>
            <Button className="mt-4" loading={busy} disabled={!msg.trim()} onClick={async () => {
              setBusy(true);
              try { await api.post("/api/feedback", { kind, message: msg, rating }); toast.success("Thanks. The team reads every message."); setMsg(""); setRating(null); }
              catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
            }}>Send</Button>
          </Card>
        </div>
      </div>
    </div>
  );
}
