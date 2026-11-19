import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BadgeCheck, Fingerprint, LockKeyhole, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog, Module } from "@/lib/types";
import { cx, num } from "@/lib/format";
import { Icon } from "@/components/icons";
import OfficeHero from "@/components/landing/hero/OfficeHero";
import manifest from "@/components/landing/hero/gearbox.json";
import CadTools from "@/components/landing/CadTools";
import AppDevices from "@/components/landing/AppDevices";
import Showcase from "@/components/landing/Showcase";
import ExplodeOnScroll from "@/components/landing/ExplodeOnScroll";
import { Reveal } from "@/components/landing/motion";
import { Badge3D, Button3D, Card3D, Crosshair, Dim, Fcf, SectionHead, Zones } from "@/components/landing/site";

export const SALES = "mailto:sales@formwright.dev?subject=Formwright%20Enterprise";

/* ---------------------------------------------------------------- content */

const SPEC: [string, string][] = [
  ["Input", "A written brief, a sketch or a STEP file"],
  ["Output", "Parametric part or assembly, drawing, BOM"],
  ["Checks", "Deterministic geometry checks on every build"],
  ["Edits", "Dimensions on the model. Free, no AI"],
  ["Export", "STEP, STL, 3MF"],
];

/** A routing card: the operations a part goes through. */
const OPS: { op: string; name: string; who: string; out: string; path: string }[] = [
  { op: "10", name: "Brief", who: "You", out: "Material, envelope, holes, intent. Missing a critical dimension? It asks instead of guessing.",
    path: "M6 4h20l8 8v28H6Z M26 4v8h8 M11 20h18 M11 26h18 M11 32h11" },
  { op: "20", name: "Plan", who: "Archie, Chief Designer", out: "A machine is split into a product tree, the interfaces are frozen and the work is estimated before a token is spent.",
    path: "M20 4v8 M20 12H8v8 M20 12h12v8 M8 20v6 M32 20v6 M4 26h8v10H4Z M28 26h8v10h-8Z M16 18h8v8h-8Z" },
  { op: "30", name: "Model and check", who: "Specialist agents, Gage checks", out: "Parametric CAD for each part, measured against values worked out from your numbers on every build.",
    path: "M20 6a14 14 0 1 0 0.01 0Z M20 13a7 7 0 1 0 0.01 0Z M20 2v6 M20 32v6 M2 20h6 M32 20h6" },
  { op: "40", name: "Release", who: "You sign off", out: "Edit any dimension for free, then hand over STEP, STL, 3MF, the drawing and a change notice.",
    path: "M6 14l14-8 14 8v16l-14 8-14-8Z M6 14l14 8 14-8 M20 22v16" },
];

const NOTES: [string, string][] = [
  ["Checked, never guessed.", "Every build passes deterministic checks: valid solid, bounding box, volume against a hand calculation, STEP round-trip, repeatability. A render is never the proof."],
  ["Edits cost nothing.", "Change a dimension, suppress a feature, sketch and extrude by hand. Instant, free and the same answer every time. The agent helps when you ask it to."],
  ["Reuse before you remodel.", "Search parts you already made by shape or by size (type 120x80x10) across the workspace, with the reasons they match."],
  ["Revisions the shop can trust.", "Each revision records what changed and why. One click hands over STEP, drawing, DFM report and change notice with a SHA-256 manifest."],
  ["One part, every next step.", "The drawing, the manufacturability review, the engineering hand calcs and print prep open on the part you just designed."],
  ["Labelled honestly.", "Requirements, assumptions, measurements and inferences are kept apart. Nothing is called validated without evidence, and sign-off stays with your engineers."],
];

const TRUST: [typeof LockKeyhole, string, string][] = [
  [LockKeyhole, "Workspace isolation", "Each organisation's projects and files are kept apart, with roles for owners, admins, engineers and viewers."],
  [ShieldCheck, "Audit trail", "Sign-ins, purchases, role changes and admin actions are logged."],
  [Fingerprint, "You own the output", "Models, parametric source and exports belong to your organisation."],
  [BadgeCheck, "Sign-off stays human", "Nothing is labelled validated or ready for manufacture without your engineer."],
];

const FAQ: [string, string][] = [
  ["Does it replace SOLIDWORKS?", "No. Formwright gets you from a brief to a checked, editable model fast. Your team keeps refining and documenting in the CAD it already uses, through STEP today and native bridges later."],
  ["What exactly is checked?", "Shape validity, solid count, closed shells, bounding box and volume against values computed from your requirements, STEP export and re-import, and repeatable regeneration. The checks prove the geometry is consistent. They don't prove strength or manufacturability."],
  ["Who owns the designs?", "You do. Generated models and their source belong to your organisation."],
];

/* ---------------------------------------------------------------- pieces */

function OpIcon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 40 40" className="h-10 w-10 shrink-0 text-bp" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" aria-hidden="true">
      <path className="fw-draw" pathLength={1} style={{ ["--len" as string]: 1 }} d={d} />
    </svg>
  );
}

function ModuleStatus({ m }: { m: Module }) {
  if (m.status !== "live") return <Badge3D>Preview</Badge3D>;
  return <Badge3D tone="live">{m.beta ? "Live · beta" : "Live"}</Badge3D>;
}

/* ---------------------------------------------------------------- page */

export default function Landing() {
  useTitle(null);
  const { me } = useSession();
  const signedIn = !!me?.user;
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog") });
  const trial = catalog.data?.trial_tokens ?? 1000;
  const run = catalog.data?.typical_run;
  const mods = catalog.data?.modules ?? [];
  const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
  const faq: [string, string][] = [
    ...FAQ.slice(0, 2),
    ["What are tokens?", `AI work is metered in tokens, so you pay for what you use. ${run
      ? `A new part from a written brief typically uses ${run.new.low} to ${run.new.high} tokens; a change to an existing part usually uses less. `
      : ""}Parameter edits, manual features, Toolbox parts and restores are free. Every run shows a live meter and stops at the budget you set. The trial includes ${num(trial)} tokens, enough for dozens of simple parts.`],
    ["Which modules are included?", mods.length ? `${list(mods.map(m => m.name))}. The trial includes every module; afterwards, add the ones your team needs.`
      : "Every module in the parts list above. The trial includes all of them."],
    ...FAQ.slice(2),
  ];

  return (
    <main>
      {/* ------------------------------------------------ hero */}
      <section className="s-grid relative overflow-hidden border-b border-ink/80">
        <Crosshair />
        <div className="relative mx-auto max-w-[1240px] px-4 pb-14 pt-10 sm:px-6 lg:pt-14">
          <div className="flex flex-wrap items-center gap-3">
            <Fcf cells={["Ø 0.00", "Brief"]} />
            <span className="s-anno text-ink2">An AI design office for mechanical teams</span>
          </div>

          <h1 className="s-display mt-8 text-[40px] text-ink min-[420px]:text-[48px] sm:text-[72px] md:text-[84px] lg:text-[104px] xl:text-[118px]">
            <span className="s-rise"><span style={{ ["--d" as string]: "0.05s" }}>One brief.</span></span>
            <span className="s-rise pb-[.2em]"><span style={{ ["--d" as string]: "0.16s" }}>
              A complete <span className="underline decoration-hi decoration-[0.12em] underline-offset-[0.1em]">machine.</span>
            </span></span>
          </h1>
          <Dim label="Brief to manufacturing review" load delay={0.55} className="max-w-[760px]" />

          <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,.8fr)] lg:items-start">
            <div className="min-w-0">
              <p className="max-w-[620px] text-[17px] leading-relaxed text-ink2 sm:text-[19px]">
                Archie and a team of specialist agents plan the machine, model every part, assemble it, draw it and review it for
                manufacture. You make every decision, and every number is measured against your spec before you see it.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-4">
                {signedIn ? <Button3D to="/app" size="lg" icon={<ArrowRight className="h-4 w-4" />}>Open the app</Button3D>
                  : <Button3D to="/signup" size="lg" icon={<ArrowRight className="h-4 w-4" />}>Start free · {num(trial)} tokens</Button3D>}
                <Button3D href="#build" size="lg" finish="steel">See it build</Button3D>
                <Link to="/why" className="s-link text-[15px] font-medium">Why buy it</Link>
              </div>
              <p className="s-anno mt-4 text-[10.5px] text-ink2">No credit card · 14-day trial, every module · STEP, STL and 3MF included</p>
            </div>

            <Card3D screws inner="p-5 sm:p-6" className="lg:mt-1">
              <div className="flex items-center justify-between gap-3 border-b border-ink/70 pb-3">
                <span className="s-anno text-ink">Spec sheet</span><span className="s-anno text-ink2">FW-0001 · Rev A</span>
              </div>
              <dl className="mt-1">
                {SPEC.map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[72px_1fr] gap-3 border-b border-rule py-2.5 last:border-b-0">
                    <dt className="s-anno pt-0.5 text-bp">{k}</dt><dd className="text-[14.5px] leading-snug text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card3D>
          </div>

          {/* the live sheet: the Design Office building PG-5 */}
          <div id="build" className="mt-14 scroll-mt-24">
            <div className="flex items-end justify-between gap-3">
              <span className="s-anno text-ink">View 1 · Design Office, live</span>
              <span className="s-anno hidden text-ink2 sm:inline">Play, pause or pick a chapter</span>
            </div>
            <Zones className="mt-2 border-x border-t border-ink/70" />
            <div className="border border-ink/70 p-2 sm:p-3"><OfficeHero /></div>
            <div className="s-tb grid-cols-2 border-t-0 sm:grid-cols-4 lg:grid-cols-[2fr_1fr_1fr_1fr_1fr]">
              {[
                ["Part", "PG-5 planetary gearbox"], ["Ratio", "5.00 : 1"], ["Parts", String(manifest.instances.length)],
                ["Interferences", "0"], ["Geometry", "Real models"],
              ].map(([k, v], i) => (
                <div key={k} className={cx(i === 0 && "col-span-2 sm:col-span-4 lg:col-span-1")}>
                  <span className="s-tb-k">{k}</span><div className="mt-1 truncate font-anno text-[13.5px] text-ink">{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------ issued to */}
      <section aria-label="Who it is for" className="border-b border-ink/80 bg-sheet">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-5 sm:px-6">
          <span className="s-anno text-bp">Issued to</span>
          {["Mechanical design consultancies", "Machine and prototype shops", "Product development firms", "Independent engineers"].map((a, i) => (
            <span key={a} className="flex items-center gap-6 text-[15px] font-medium text-ink">{i > 0 && <span className="h-4 w-px bg-rule2" aria-hidden="true" />}{a}</span>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------ 01 how: a routing card */}
      <section id="how" className="mx-auto max-w-[1240px] scroll-mt-24 px-4 py-20 sm:px-6 sm:py-24">
        <Reveal><SectionHead n="01" kicker="How it works" title="The loop your best engineer runs, on a routing card."
          body="Generate, check, look, correct. Every operation is measured, then signed by a person." /></Reveal>
        <Card3D className="mt-12" inner="p-0">
          <div className="hidden grid-cols-[88px_minmax(0,1.1fr)_minmax(0,.9fr)_minmax(0,2fr)] border-b border-ink/70 lg:grid">
            {["Op", "Operation", "Work centre", "What you get"].map(h => <span key={h} className="s-anno px-5 py-3 text-ink2">{h}</span>)}
          </div>
          <ol>
            {OPS.map((o, i) => (
              <Reveal as="li" key={o.op} delay={i * 0.08}
                className="grid gap-x-4 gap-y-2 border-b border-rule px-5 py-6 last:border-b-0 lg:grid-cols-[88px_minmax(0,1.1fr)_minmax(0,.9fr)_minmax(0,2fr)] lg:items-center lg:gap-0 lg:px-0 lg:py-5">
                <span className="font-display text-[30px] font-extrabold leading-none text-bp lg:px-5" style={{ fontStretch: "120%" }}>{o.op}</span>
                <div className="flex items-center gap-3 lg:px-5"><OpIcon d={o.path} /><h3 className="text-[19px] font-semibold text-ink">{o.name}</h3></div>
                <span className="s-anno text-ink2 lg:px-5">{o.who}</span>
                <p className="text-[15.5px] leading-relaxed text-ink2 lg:px-5">{o.out}</p>
              </Reveal>
            ))}
          </ol>
        </Card3D>
      </section>

      {/* ------------------------------------------------ 02 general notes */}
      <section className="s-print s-grid border-y border-ink">
        <div className="mx-auto max-w-[1240px] px-4 py-20 sm:px-6 sm:py-24">
          <Reveal><SectionHead onPrint n="02" kicker="General notes" title="CAD that checks its own work." /></Reveal>
          <ol className="mt-12 grid gap-x-12 gap-y-9 md:grid-cols-2">
            {NOTES.map(([h, b], i) => (
              <Reveal as="li" key={h} delay={(i % 2) * 0.08} className="flex gap-4">
                <span className="s-balloon text-[#9cc3ff]">{i + 1}</span>
                <div className="border-t border-white/20 pt-3">
                  <h3 className="s-anno text-[12.5px] text-white">{h}</h3>
                  <p className="mt-2 text-[15.5px] leading-relaxed text-[#b8c8e0]">{b}</p>
                </div>
              </Reveal>
            ))}
          </ol>
        </div>
      </section>

      {/* ------------------------------------------------ 03 exploded view on scroll */}
      <ExplodeOnScroll />

      <CadTools />

      <Showcase />

      <AppDevices />

      {/* ------------------------------------------------ 07 modules: the parts list */}
      <section id="modules" className="mx-auto max-w-[1240px] scroll-mt-24 px-4 py-20 sm:px-6 sm:py-24">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <Reveal className="min-w-0 flex-1"><SectionHead n="07" kicker="Modules" title="One part, every next step."
            body="Design in the Studio, then make the drawing, check manufacturability, prepare a print or render it, on the same part. The trial includes every module." /></Reveal>
          <Button3D to="/pricing" finish="steel" icon={<ArrowRight className="h-4 w-4" />}>Compare plans</Button3D>
        </div>
        <Card3D className="mt-12" inner="p-0">
          <table className="w-full text-left">
            <caption className="sr-only">Formwright modules</caption>
            <thead className="border-b border-ink/70">
              <tr>
                <th scope="col" className="s-anno w-[72px] px-4 py-3 font-medium text-ink2 sm:px-5">Item</th>
                <th scope="col" className="s-anno px-2 py-3 font-medium text-ink2">Module</th>
                <th scope="col" className="s-anno hidden px-4 py-3 font-medium text-ink2 md:table-cell">Description</th>
                <th scope="col" className="s-anno px-4 py-3 text-right font-medium text-ink2 sm:px-5">Status</th>
              </tr>
            </thead>
            <tbody>
              {mods.map((m, i) => (
                <tr key={m.code} className="border-b border-rule align-top transition-colors last:border-b-0 hover:bg-bpsoft/40">
                  <td className="px-4 py-4 sm:px-5"><span className="s-balloon h-7 w-7 text-ink">{i + 1}</span></td>
                  <td className="px-2 py-4">
                    <div className="flex items-center gap-2.5"><Icon name={m.icon} className="h-[18px] w-[18px] shrink-0 text-bp" /><span className="text-[16px] font-semibold text-ink">{m.name}</span></div>
                    <p className="mt-1.5 text-[14px] leading-relaxed text-ink2 md:hidden">{m.summary}</p>
                  </td>
                  <td className="hidden px-4 py-4 text-[14.5px] leading-relaxed text-ink2 md:table-cell">{m.summary}</td>
                  <td className="px-4 py-4 text-right sm:px-5"><ModuleStatus m={m} /></td>
                </tr>
              ))}
              {!mods.length && <tr><td colSpan={4} className="px-5 py-10 text-center text-[14px] text-ink2">Loading the module list…</td></tr>}
            </tbody>
          </table>
        </Card3D>
      </section>

      {/* ------------------------------------------------ 08 security */}
      <section id="trust" className="scroll-mt-24 border-y border-ink/80 bg-sheet2">
        <div className="mx-auto grid max-w-[1240px] gap-12 px-4 py-20 sm:px-6 sm:py-24 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.3fr)]">
          <Reveal>
            <SectionHead n="08" kicker="Security and IP" title="Your designs stay yours."
              body="Built for firms that handle client IP every day. Enterprise deployments add SSO, audit export and private hosting." />
            <Button3D href={SALES} finish="steel" className="mt-8">Talk to us about Enterprise</Button3D>
          </Reveal>
          <div className="grid gap-5 sm:grid-cols-2">
            {TRUST.map(([I, t, b], i) => (
              <Reveal key={t} delay={(i % 2) * 0.08}>
                <Card3D className="h-full" inner="p-6">
                  <I className="h-6 w-6 text-bp" strokeWidth={1.6} aria-hidden="true" />
                  <h3 className="mt-4 text-[17px] font-semibold text-ink">{t}</h3>
                  <p className="mt-2 text-[14.5px] leading-relaxed text-ink2">{b}</p>
                </Card3D>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------ 09 faq */}
      <section className="mx-auto max-w-[1000px] px-4 py-20 sm:px-6 sm:py-24">
        <Reveal><SectionHead n="09" kicker="Questions" title="Questions engineers ask." /></Reveal>
        <div className="mt-10 border-t border-ink/80">
          {faq.map(([q, a], i) => (
            <details key={q} className="group border-b border-rule [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex min-h-[64px] cursor-pointer list-none items-center gap-4 py-4">
                <span className="s-anno w-10 shrink-0 text-bp">Q.{String(i + 1).padStart(2, "0")}</span>
                <span className="flex-1 text-[17px] font-semibold text-ink">{q}</span>
                <span className="relative h-4 w-4 shrink-0 text-ink2" aria-hidden="true">
                  <span className="absolute left-0 top-1/2 h-[1.5px] w-4 -translate-y-1/2 bg-current" />
                  <span className="absolute left-1/2 top-0 h-4 w-[1.5px] -translate-x-1/2 bg-current transition-transform duration-200 group-open:scale-y-0" />
                </span>
              </summary>
              <p className="pb-6 pl-14 pr-8 text-[15.5px] leading-relaxed text-ink2">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------ approval: a title block */}
      <section className="px-4 pb-24 sm:px-6">
        <Reveal className="mx-auto max-w-[1192px]">
          <Card3D screws hi inner="p-0">
            <div className="s-hazard h-2.5" aria-hidden="true" />
            <div className="grid lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <div className="border-b border-ink/80 p-7 sm:p-10 lg:border-b-0 lg:border-r">
                <span className="s-anno text-bp">Title</span>
                <h2 className="s-h2 mt-3 text-[34px] text-ink sm:text-[52px]">Your next part, checked before you see it.</h2>
                <p className="mt-4 max-w-xl text-[17px] leading-relaxed text-ink2">
                  {signedIn ? "Pick up where you left off." : `Start with ${num(trial)} free tokens and every module for 14 days. No credit card. Export everything you make.`}
                </p>
                <div className="mt-8">
                  <Button3D to={signedIn ? "/app" : "/signup"} size="lg" icon={<ArrowRight className="h-4 w-4" />}>{signedIn ? "Open the app" : "Start your free trial"}</Button3D>
                </div>
              </div>
              <dl className="grid grid-cols-2 lg:grid-cols-1">
                {[["Drawn", "You, in a written brief"], ["Checked", "Formwright, on every build"], ["Approved", "Your engineer, always"], ["Dwg no.", "Yours to name"]].map(([k, v], i) => (
                  <div key={k} className={cx("border-ink/80 p-5 sm:p-6", i < 2 && "border-b", i % 2 === 0 && "border-r lg:border-r-0", i === 2 && "border-b-0 lg:border-b")}>
                    <dt className="s-tb-k">{k}</dt><dd className="mt-1.5 text-[16px] font-semibold text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </Card3D>
        </Reveal>
      </section>
    </main>
  );
}
