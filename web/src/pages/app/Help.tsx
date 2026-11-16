import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Bug, Compass, Keyboard, Lightbulb, MessageCircle, Star } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Button, Card, Field, PageHeader } from "@/components/ui";
import { cx } from "@/lib/format";

const GUIDES = [
  ["Writing a great design brief", "Lead with function and constraints: material, envelope, interfaces (holes, mating faces), loads you know, and what must not change. Give dimensions with units. Say which edges get fillets or chamfers."],
  ["Reading the checks", "Checks compare the built part to EXPECTED values the agent computed from your requirements: valid solid, bounding box, volume, STEP round-trip and repeatability. A pass means geometric consistency, not structural adequacy."],
  ["Editing without spending tokens", "Open Params in the studio, change a named dimension and Apply. The model rebuilds deterministically and is kept only if it still passes its checks."],
  ["Restoring a revision", "Every build is saved. Open Revs and press Restore on any earlier revision — it rebuilds exactly as it was, with no AI call."],
  ["Exporting to your CAD", "Download STEP (AP214) from Files and open it in SOLIDWORKS, Creo, Fusion, Inventor or NX. Imported STEP is a solid body without feature history; the parametric source stays in Formwright."],
  ["How tokens are counted", "Each agent run costs tokens based on the AI compute it used; the exact amount is shown under each run and in Billing → Token ledger. Parameter edits and restores are free."],
];

const KEYS = [["Ctrl + K", "Command palette"], ["Ctrl + Enter", "Send prompt to the agent"], ["Mouse left-drag", "Orbit model"], ["Mouse right-drag", "Pan"], ["Scroll", "Zoom"]];

export default function Help() {
  const nav = useNavigate();
  const [kind, setKind] = useState<"general" | "bug" | "feature">("general");
  const [msg, setMsg] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <PageHeader title="Help & guided tour" subtitle="Guides, shortcuts and a direct line to the team." />
      <div className="mb-8 grid gap-4 md:grid-cols-3">
        <Card className="flex flex-col p-5"><Compass className="h-6 w-6 text-primary" /><h3 className="mt-3 font-semibold">Product tour</h3><p className="mt-1 flex-1 text-sm text-muted">Two minutes around the workspace: projects, modules, tokens and your checklist.</p><Button className="mt-4" onClick={() => nav("/app?tour=1")}>Start tour</Button></Card>
        <Card className="flex flex-col p-5"><BookOpen className="h-6 w-6 text-primary" /><h3 className="mt-3 font-semibold">Studio tour</h3><p className="mt-1 flex-1 text-sm text-muted">Open any project and press the ? icon in the toolbar for a tour of the design studio.</p><Button variant="secondary" className="mt-4" onClick={() => nav("/app/projects")}>Open projects</Button></Card>
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
              try { await api.post("/api/feedback", { kind, message: msg, rating }); toast.success("Thanks — the team reads every message."); setMsg(""); setRating(null); }
              catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
            }}>Send</Button>
          </Card>
        </div>
      </div>
    </div>
  );
}
