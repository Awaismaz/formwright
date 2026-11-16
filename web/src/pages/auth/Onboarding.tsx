import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button, Input, Logo, Progress } from "@/components/ui";
import { cx } from "@/lib/format";

const ROLES = ["Design / mechanical engineer", "Engineering manager", "Consultancy owner / principal", "Machinist / shop owner",
  "Product developer / founder", "Student / educator", "Other"];
const SIZES = ["Just me", "2–10", "11–50", "51–200", "200+"];
const TOOLS = ["SOLIDWORKS", "Creo", "Inventor", "Fusion", "Onshape", "CATIA", "Siemens NX", "FreeCAD", "Other"];
const GOALS = [
  ["concepts", "Get from idea to first model faster"],
  ["drawings", "Produce manufacturing drawings"],
  ["dfm", "Reduce manufacturing cost (DFM)"],
  ["legacy", "Rebuild parts from old drawings or photos"],
  ["print", "Prepare parts for 3D printing"],
  ["assemblies", "Design multi-part assemblies"],
];

function Choice({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={cx("flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left text-sm transition",
        selected ? "border-primary bg-primary-soft text-primary ring-1 ring-primary" : "border-border bg-panel hover:border-primary/50")}>
      <span>{children}</span>
      <span className={cx("flex h-5 w-5 shrink-0 items-center justify-center rounded-full border", selected ? "border-primary bg-primary text-white" : "border-border")}>
        {selected && <Check className="h-3 w-3" />}
      </span>
    </button>
  );
}

export default function Onboarding() {
  const { me, refresh } = useSession();
  const nav = useNavigate();
  const existing = (me?.user?.onboarding ?? {}) as Record<string, unknown>;
  const [step, setStep] = useState(0);
  const [role, setRole] = useState<string>((existing.role as string) ?? "");
  const [size, setSize] = useState<string>((existing.company_size as string) ?? "");
  const [tools, setTools] = useState<string[]>((existing.cad_tools as string[]) ?? []);
  const [goals, setGoals] = useState<string[]>((existing.goals as string[]) ?? []);
  const [units, setUnits] = useState<"mm" | "in">(me?.user?.preferences?.units ?? "mm");
  const firstName = me?.user?.name.split(" ")[0] ?? "";
  const [workspace, setWorkspace] = useState(me?.org?.name ?? (firstName ? `${firstName}'s workspace` : "My workspace"));
  const [busy, setBusy] = useState(false);

  if (me?.next_step === "verify_email") return <Navigate to="/verify-email" replace />;
  if (me?.next_step === "app" && step === 0 && me.user?.onboarding_completed) return <Navigate to="/app" replace />;

  const toggle = (list: string[], set: (v: string[]) => void, v: string) => set(list.includes(v) ? list.filter(x => x !== v) : [...list, v]);
  const steps = [
    { title: `Welcome${firstName ? `, ${firstName}` : ""}! What best describes your role?`, sub: "We'll tailor templates and tips to how you work.", valid: !!role,
      body: <div className="grid gap-2 sm:grid-cols-2">{ROLES.map(r => <Choice key={r} selected={role === r} onClick={() => setRole(r)}>{r}</Choice>)}</div> },
    { title: "How big is your team?", sub: "Helps us suggest the right plan — you can change it any time.", valid: !!size,
      body: <div className="grid gap-2 sm:grid-cols-3">{SIZES.map(s => <Choice key={s} selected={size === s} onClick={() => setSize(s)}>{s}</Choice>)}</div> },
    { title: "Which CAD tools do you use today?", sub: "Formwright exports clean STEP into all of them. Pick any that apply.", valid: true,
      body: <div className="grid gap-2 sm:grid-cols-3">{TOOLS.map(t => <Choice key={t} selected={tools.includes(t)} onClick={() => toggle(tools, setTools, t)}>{t}</Choice>)}</div> },
    { title: "What do you want to achieve first?", sub: "Pick your top goals. We'll highlight the modules that help.", valid: goals.length > 0,
      body: <div className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">{GOALS.map(([k, l]) => <Choice key={k} selected={goals.includes(k!)} onClick={() => toggle(goals, setGoals, k!)}>{l}</Choice>)}</div>
        <div><div className="mb-2 text-[13px] font-medium">Preferred units</div>
          <div className="inline-flex rounded-lg border border-border p-1">{(["mm", "in"] as const).map(u =>
            <button key={u} type="button" onClick={() => setUnits(u)} className={cx("rounded px-4 py-1.5 text-sm", units === u ? "bg-primary text-white" : "text-muted")}>{u === "mm" ? "Millimetres" : "Inches"}</button>)}</div>
        </div>
      </div> },
    { title: "Name your workspace", sub: "Usually your company or team name. Projects, tokens and billing live here.", valid: workspace.trim().length > 0,
      body: <div className="space-y-3"><Input value={workspace} onChange={e => setWorkspace(e.target.value)} autoFocus className="h-11 text-base" />
        <div className="rounded-lg border border-border bg-panel2 p-4 text-sm text-muted">Your <b className="text-text">14-day free trial</b> starts now with <b className="text-text">300 tokens</b> — enough for several verified parts.</div></div> },
  ];
  const cur = steps[step]!;
  const last = step === steps.length - 1;

  const next = async () => {
    if (!cur.valid) return;
    if (!last) {
      api.post("/api/onboarding", { role, company_size: size, cad_tools: tools, goals, units }).catch(() => {});
      setStep(step + 1);
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/onboarding", { role, company_size: size, cad_tools: tools, goals, units, workspace_name: workspace });
      await refresh();
      nav("/app", { replace: true });
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); }
    finally { setBusy(false); }
  };

  return (
    <div className="flex min-h-full flex-col bg-bg">
      <header className="flex h-16 items-center justify-between border-b border-border bg-panel px-6">
        <Logo size={24} />
        <div className="flex w-56 items-center gap-3 text-xs text-muted"><Progress value={step + 1} max={steps.length} /> {step + 1}/{steps.length}</div>
      </header>
      <main className="flex flex-1 items-start justify-center px-4 py-12 sm:py-20">
        <div key={step} className="w-full max-w-2xl animate-fade-in">
          <h1 className="text-[26px] font-semibold tracking-tight">{cur.title}</h1>
          <p className="mt-1.5 text-muted">{cur.sub}</p>
          <div className="mt-8">{cur.body}</div>
          <div className="mt-10 flex items-center justify-between">
            <Button variant="ghost" icon={<ArrowLeft className="h-4 w-4" />} disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
            <div className="flex items-center gap-2">
              {step === 2 && <Button variant="ghost" onClick={() => setStep(step + 1)}>Skip</Button>}
              <Button size="lg" onClick={next} disabled={!cur.valid} loading={busy} icon={last ? undefined : <ArrowRight className="h-4 w-4" />}>
                {last ? "Create workspace & start" : "Continue"}
              </Button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
