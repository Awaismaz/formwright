import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight, BadgeCheck, Building2, Code2, FileCheck2, Fingerprint, GitBranch, LockKeyhole, MessageSquareText,
  PackageCheck, ScanSearch, ShieldCheck, Sparkles, Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog } from "@/lib/types";
import { num } from "@/lib/format";
import { Badge, Button, StatusBadge } from "@/components/ui";
import { Icon } from "@/components/icons";
import HeroVisual from "@/components/HeroVisual";
import Showcase, { LiveBadge } from "@/components/landing/Showcase";
import { Reveal, useReducedMotion } from "@/components/landing/motion";

/** Subtle parallax for decorative layers: moves `ref` at `rate` × scroll, off under reduced motion. */
function useParallax(rate: number) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return;
    let raf = 0;
    const on = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const y = window.scrollY;
        if (y < 1200) el.style.transform = `translate3d(0, ${(y * rate).toFixed(1)}px, 0)`;
      });
    };
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => { window.removeEventListener("scroll", on); if (raf) cancelAnimationFrame(raf); el.style.transform = ""; };
  }, [rate, reduced]);
  return ref;
}

const STEPS = [
  { icon: MessageSquareText, title: "Describe the part", body: "Brief it like you'd brief an engineer: material, envelope, holes, fillets, intent. Missing a critical dimension? It asks — it doesn't guess." },
  { icon: Wrench, title: "The agent models and verifies", body: "It writes parametric CAD, builds it, then checks validity, dimensions and volume against a hand calculation, and looks at the result before showing you." },
  { icon: FileCheck2, title: "Refine and export", body: "Iterate in plain language, restore any revision, and export STEP or STL straight into SOLIDWORKS, Creo, Fusion or your slicer." },
];

const DIFFS = [
  { icon: BadgeCheck, title: "Verified, not guessed", body: "Every build passes deterministic geometry checks: valid solid, bounding box, analytic volume, STEP round-trip, repeatability. Pictures are never the proof." },
  { icon: Code2, title: "Edit without the AI toll", body: "Change a dimension, suppress or delete a feature, sketch and extrude by hand: instant, free, and the same answer every time. The agent is there when it helps, never as a toll booth." },
  { icon: ScanSearch, title: "Reuse before you remodel", body: "Find parts you already made by shape or by size (type 120x80x10) across your workspace, with the reasons they match." },
  { icon: PackageCheck, title: "Changes the shop can trust", body: "Every revision records what changed and why. One click hands the shop a verified pack: STEP, drawing, DFM report and change notice, with a SHA-256 manifest." },
  { icon: GitBranch, title: "One part, every next step", body: "The drawing, manufacturability review, engineering calculations and 3D-print prep open straight on the part you just designed. Clean STEP into the CAD your team already uses." },
  { icon: Fingerprint, title: "Honest by design", body: "Requirements, assumptions, measurements and inferences are labelled separately. Nothing is called validated without evidence; engineering sign-off stays with your engineers." },
];

const FAQ = [
  ["Is this a replacement for SOLIDWORKS?", "No. Formwright gets you from idea to a verified, editable starting model fast. Your team keeps refining and documenting in the CAD system it already uses."],
  ["What exactly is checked?", "Shape validity, solid count, closed manifold, bounding box and volume against values computed from your requirements, STEP export/re-import equality and deterministic regeneration. Checks prove geometric consistency — not strength or manufacturability."],
  ["Who owns the designs?", "You do. Generated models and source belong to your organization."],
];

export const SALES = "mailto:sales@formwright.dev?subject=Formwright%20Enterprise";

export default function Landing() {
  useTitle(null);
  const { me } = useSession();
  const signedIn = !!me?.user;
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog") });
  const trial = catalog.data?.trial_tokens ?? 1000;
  const run = catalog.data?.typical_run;
  const tokensFaq: [string, string] = ["What are tokens?", `AI work is metered in tokens, so you pay for what you use. ${run
    ? `A new part from a written brief typically uses ${run.new.low}–${run.new.high} tokens; a change to an existing part usually uses less. `
    : ""}Parameter edits, manual features, Toolbox parts and restores are free. Every run shows a live meter and stops at the budget you set. The trial includes ${num(trial)} tokens, about 3 new parts.`];
  const mods = catalog.data?.modules ?? [];
  const glow = useParallax(0.25);
  const grid = useParallax(0.12);
  const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
  const live = list(mods.filter(m => m.status === "live").map(m => m.name));
  const preview = list(mods.filter(m => m.status !== "live").map(m => m.name));
  const faq = [...FAQ.slice(0, 2), tokensFaq, ["Which modules are available today?", mods.length
    ? `Live today: ${live}. ${preview ? `${preview} ${preview.includes(" and ") ? "are" : "is"} on the roadmap and marked Preview in the app.` : ""}`
    : "See the module list above: each is marked Live or Preview."], ...FAQ.slice(2)];
  return (
    <main>
      {/* hero */}
      <section className="relative overflow-hidden border-b border-border">
        <div ref={glow} className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgb(var(--primary)/.12),transparent_60%)]" />
        <div ref={grid} className="pointer-events-none absolute inset-0 opacity-[.35] [background-image:linear-gradient(rgb(var(--border))_1px,transparent_1px),linear-gradient(90deg,rgb(var(--border))_1px,transparent_1px)] [background-size:32px_32px] [mask-image:linear-gradient(to_bottom,black,transparent_75%)]" />
        <div className="relative mx-auto max-w-6xl px-4 pb-16 pt-12 sm:px-6 lg:pt-16">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mb-5 flex flex-wrap justify-center gap-2"><Badge tone="accent" className="animate-fade-in"><Sparkles className="h-3 w-3" /> AI design engineer for mechanical teams</Badge><LiveBadge label="Design Studio is live" /></div>
            <h1 className="text-[40px] font-semibold leading-[1.08] tracking-tight sm:text-[56px]">
              From idea to <span className="bg-gradient-to-r from-primary to-[#5C93E6] bg-clip-text text-transparent">verified</span>, editable CAD.
            </h1>
            <p className="mx-auto mt-5 max-w-2xl text-[17px] leading-relaxed text-muted">
              Describe a part in plain language. Formwright's agent writes parametric CAD, builds it, checks it numerically and shows it live — so your engineers start from a correct model, not a blank sketch.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              {signedIn ? <Link to="/app"><Button size="lg" icon={<ArrowRight className="h-4 w-4" />}>Open the app</Button></Link>
                : <Link to="/signup"><Button size="lg" icon={<ArrowRight className="h-4 w-4" />}>Start free · {num(trial)} tokens</Button></Link>}
              <a href="#tour"><Button size="lg" variant="secondary">See it work</Button></a>
            </div>
            <p className="mt-3 text-xs text-muted">No credit card · 14-day trial with every module · STEP & STL export included</p>
          </div>
          <div className="mx-auto mt-10 max-w-5xl"><HeroVisual /></div>
        </div>
      </section>

      {/* audience */}
      <section className="border-b border-border bg-panel2/60">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-10 gap-y-3 px-4 py-6 text-sm text-muted">
          <span className="font-medium text-text">Built for</span>
          {["Mechanical design consultancies", "Machine & prototype shops", "Product development firms", "Independent professional engineers"].map(a =>
            <span key={a} className="inline-flex items-center gap-2"><Building2 className="h-4 w-4" />{a}</span>)}
        </div>
      </section>

      {/* how */}
      <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <div className="mx-auto max-w-2xl text-center">
          <div className="label">How it works</div>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">The loop your best engineer runs — automated.</h2>
          <p className="mt-3 text-muted">Generate → check → look → correct. Every iteration is measured, not eyeballed.</p>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <Reveal key={s.title} delay={i * 0.1} className="card relative p-6">
              <div className="absolute right-5 top-5 text-4xl font-semibold text-text/[.06]">0{i + 1}</div>
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-soft text-primary"><s.icon className="h-5 w-5" /></div>
              <h3 className="mt-4 font-semibold">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* differentiators */}
      <section className="border-y border-border bg-chrome text-chrome-fg">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <div className="max-w-2xl">
            <div className="text-[11px] font-semibold uppercase tracking-[.14em] text-[#F2B784]">Why Formwright</div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-white">Engineering-grade, not demo-grade.</h2>
          </div>
          <div className="mt-10 grid gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-2">
            {DIFFS.map((d, i) => (
              <Reveal key={d.title} delay={(i % 2) * 0.08} className="bg-chrome p-7">
                <d.icon className="h-6 w-6 text-[#7FAAF0]" />
                <h3 className="mt-4 font-semibold text-white">{d.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-chrome-muted">{d.body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <Showcase />

      {/* modules */}
      <section id="modules" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-2xl">
            <div className="label">Platform</div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">One part, every next step.</h2>
            <p className="mt-3 text-muted">Design in the Studio, then make the drawing, check manufacturability, prepare a print or render it, on the same part. The trial includes every module; afterwards, add the ones your team needs.</p>
          </div>
          <Link to="/pricing" className="link text-sm font-medium">Compare plans →</Link>
        </div>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {(catalog.data?.modules ?? []).map(m => (
            <div key={m.code} className="card flex flex-col p-5 transition hover:-translate-y-0.5 hover:shadow-pop">
              <div className="flex items-center justify-between">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-soft text-primary"><Icon name={m.icon} className="h-[18px] w-[18px]" /></div>
                {m.status === "live" ? <LiveBadge /> : <StatusBadge status={m.status} />}
              </div>
              <h3 className="mt-4 font-semibold">{m.name}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{m.summary}</p>
            </div>
          ))}
        </div>
      </section>

      {/* trust */}
      <section id="trust" className="scroll-mt-20 border-y border-border bg-panel2/60">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.2fr]">
          <div>
            <div className="label">Security & IP</div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">Your designs stay yours.</h2>
            <p className="mt-3 text-muted">Built for firms that handle client IP every day. Enterprise deployments add SSO, audit export and private hosting.</p>
            <a href={SALES} className="mt-6 inline-block"><Button variant="secondary">Talk to us about Enterprise</Button></a>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {[
              [LockKeyhole, "Workspace isolation", "Each organization's projects and files are isolated, with role-based access for owners, admins, engineers and viewers."],
              [ShieldCheck, "Full audit trail", "Sign-ins, purchases, role changes and admin actions are logged."],
              [Fingerprint, "You own the output", "Models, parametric source and exports belong to your organization."],
              [BadgeCheck, "Sign-off stays human", "Nothing is ever labelled validated or ready for manufacture without your engineer."],
            ].map(([I, t, b]) => {
              const C = I as typeof LockKeyhole;
              return <div key={t as string} className="card p-5"><C className="h-5 w-5 text-primary" /><h3 className="mt-3 text-[15px] font-semibold">{t as string}</h3><p className="mt-1.5 text-sm text-muted">{b as string}</p></div>;
            })}
          </div>
        </div>
      </section>

      {/* faq */}
      <section className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
        <h2 className="text-center text-3xl font-semibold tracking-tight">Questions engineers ask</h2>
        <div className="mt-10 divide-y divide-border rounded-xl border border-border bg-panel">
          {faq.map(([q, a]) => (
            <details key={q} className="group px-5 py-4 [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex cursor-pointer items-center justify-between font-medium">{q}<span className="ml-4 text-muted transition group-open:rotate-45">+</span></summary>
              <p className="mt-2 text-sm leading-relaxed text-muted">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* cta */}
      <section className="px-4 pb-20 sm:px-6">
        <div className="relative mx-auto max-w-6xl overflow-hidden rounded-2xl bg-gradient-to-br from-primary to-[#143E80] px-8 py-14 text-center text-white">
          <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-accent/30 blur-3xl" />
          <h2 className="relative text-3xl font-semibold tracking-tight">Your next part, verified in minutes.</h2>
          <p className="relative mx-auto mt-3 max-w-xl text-white/80">{signedIn ? "Pick up where you left off." : `Start with ${num(trial)} free tokens and every module. No credit card. Export everything you make.`}</p>
          <Link to={signedIn ? "/app" : "/signup"} className="relative mt-7 inline-block"><Button size="lg" variant="accent" icon={<ArrowRight className="h-4 w-4" />}>{signedIn ? "Open the app" : "Start your free trial"}</Button></Link>
        </div>
      </section>
    </main>
  );
}
