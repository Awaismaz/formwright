import { useMemo, useRef, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight, Boxes, Calculator as CalcIcon, CheckCircle2, ClipboardCheck, Clock, Factory, FileStack, GitBranch,
  Layers, Package, Repeat2, ScanLine, ShieldCheck, Sparkles, Users, Wrench, Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog } from "@/lib/types";
import { cx } from "@/lib/format";
import LazyScene from "@/components/landing/LazyScene";
import { Badge3D, Button3D, Card3D, Dim, Fcf, SectionHead as SheetHead, useScrollProgress } from "@/components/landing/site";
import Calculator from "./why/Calculator";
import { CountUp, Reveal, useReduced, useSeen } from "./why/motion";
import {
  EXAMPLES, FALLBACK_PACKS, FALLBACK_PLANS, HIRE, PROFILES, defaultInputs, exampleCost, heroStats, hireYearOne, packTokenPrice,
  planYear, range, usd, usdRange, type PackLike, type PlanLike,
} from "./why/roi";

const DEMO = "mailto:sales@formwright.dev?subject=Formwright%20demo";

/* Sources, cited by number in small print. Modelled figures are marked "est." where they appear. */
const SOURCES = [
  "U.S. Bureau of Labor Statistics, Occupational Outlook Handbook (2024): Mechanical Engineers, median pay May 2023.",
  "U.S. Bureau of Labor Statistics, Occupational Outlook Handbook (2024): Drafters, mechanical drafters median pay May 2023.",
  "U.S. Bureau of Labor Statistics, Employer Costs for Employee Compensation (2024): wages and salaries ≈ 70% of total compensation, private industry, so total cost ≈ 1.4 × pay.",
  "SHRM, Talent Acquisition Benchmarking Report (2022): average cost per hire and average time to fill.",
  "Estimate: published consultancy rate cards and freelance marketplace rates for mechanical design (2024); varies by region and specialism.",
  "Estimate: published list prices for mainstream mechanical CAD subscriptions plus PDM (2024).",
];

function Sup({ n }: { n: number }) {
  return <a href="#sources" className="ml-0.5 align-super text-[10px] font-medium text-primary hover:underline">[{n}]</a>;
}

function SectionHead({ n, eyebrow, title, body }: { n: string; eyebrow: string; title: ReactNode; body?: ReactNode }) {
  return <Reveal className="max-w-3xl"><SheetHead n={n} kicker={eyebrow} title={title} body={body} /></Reveal>;
}

/** A spur gear that turns as the page scrolls past it (real Toolbox geometry). */
function ScrollGear() {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReduced();
  const p = useScrollProgress(ref, !reduced);
  return (
    <div ref={ref} className="viewport-bg relative h-[260px] sm:h-[300px]">
      <LazyScene parts={[{ id: "gear", url: "/landing/gear.glb", color: "#bcc4ce", highlight: { rMin: 21.6, rMax: 26.5, color: "#ffc400" } }]}
        still={reduced} turn={reduced ? undefined : p * 360} view={[1, -1, 1.1]} zoom={1.15}
        poster={<div className="flex h-full items-center justify-center"><svg viewBox="0 0 120 120" className="h-40 w-40 text-ink2" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"><circle cx="60" cy="60" r="48" strokeDasharray="5 3" /><circle cx="60" cy="60" r="40" /><circle cx="60" cy="60" r="10" /></svg></div>}
        label="Spur gear m2, 24 teeth, from the Formwright Toolbox. It turns as you scroll." />
      <span className="s-anno pointer-events-none absolute bottom-3 left-3 bg-sheet/90 px-2 py-1 text-ink">Spur gear m2 · z24 · 0 tokens</span>
    </div>
  );
}

/** One medium part, conventional vs Formwright, filling at the model's relative speeds. */
function RaceCard() {
  const [ref, seen] = useSeen<HTMLDivElement>(0.3);
  const reduced = useReduced();
  const on = seen || reduced;
  const p = PROFILES.medium;
  const fwH = p.convHours * 0.25 + p.briefMinutes / 60;
  const rows = [
    { k: "Conventional", sub: `${p.convHours} h model + drawing`, w: 100, dur: 6, c: "s-conv" },
    { k: "First verified model", sub: `${p.briefMinutes} min`, w: (p.briefMinutes / 60 / p.convHours) * 100, dur: 0.6, c: "bg-primary" },
    { k: "Formwright + review", sub: `${fwH.toFixed(2).replace(/0$/, "")} h incl. 25% review`, w: (fwH / p.convHours) * 100, dur: 1.6, c: "bg-primary" },
  ];
  return (
    <div ref={ref}><Card3D screws inner="relative overflow-hidden p-5 text-left sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold">One medium part, start to signed-off</div>
        <Badge3D>Modelled</Badge3D>
      </div>
      <div className="mt-5 space-y-4">
        {rows.map((r, i) => (
          <div key={r.k}>
            <div className="flex items-baseline justify-between text-xs"><span className="font-medium">{r.k}</span><span className="tabular-nums text-muted">{r.sub}</span></div>
            <div className="mt-1.5 h-3 bg-sheet2 ring-1 ring-rule">
              <div className={cx("h-full", r.c)}
                style={{ width: on ? `${Math.max(1.5, r.w)}%` : "0%", transition: reduced ? "none" : `width ${r.dur}s cubic-bezier(.2,.7,.2,1) ${0.2 + i * 0.15}s` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-5 grid grid-cols-3 gap-2 border-t border-border pt-4 text-center text-[11px] text-muted">
        <div><ShieldCheck className="mx-auto mb-1 h-4 w-4 text-success" />Checked every build</div>
        <div><Factory className="mx-auto mb-1 h-4 w-4 text-accent" />DFM advice per revision</div>
        <div><FileStack className="mx-auto mb-1 h-4 w-4 text-primary" />STEP · drawing · BOM</div>
      </div>
    </Card3D></div>
  );
}

const RISKS: { icon: typeof Repeat2; risk: string; cost: string; fix: string }[] = [
  { icon: Repeat2, risk: "Manual re-modelling and slow iterations", cost: "Every design change costs hours of rework, so teams iterate less.", fix: "Parametric agent edits in seconds: change a dimension, a hole pattern or a material in plain language or by parameter." },
  { icon: ScanLine, risk: "Transcription and dimension errors", cost: "A mistyped dimension survives until the first part is wrong.", fix: "Deterministic geometry checks on every build: validity, bounding box and volume against your requirements, STEP round-trip." },
  { icon: FileStack, risk: "Drawings drifting from the model", cost: "The shop builds from a drawing that no longer matches the CAD.", fix: "Associative drawings regenerate from the current revision, so views and dimensions follow the model." },
  { icon: Factory, risk: "Late DFM surprises", cost: "Undercuts, thin walls and deep pockets found by the supplier, after the quote.", fix: "Manufacturing Advisor runs on every revision: process shortlist, DFM findings and a relative cost, while the design is still cheap to change." },
  { icon: Layers, risk: "Interference found at prototype", cost: "Parts that clash are discovered on the bench, a rebuild later.", fix: "Exact interference checks in assembly, with clearance reported per pair before anything is cut." },
  { icon: GitBranch, risk: "Tribal knowledge and key-person risk", cost: "Design intent lives in one engineer's head and leaves with them.", fix: "Every revision, change note and brief is recorded and restorable, so anyone can pick up the design." },
  { icon: Wrench, risk: "Standard parts redrawn by hand", cost: "Bearings, fasteners and gears modelled again, with fresh chances to get them wrong.", fix: "A deterministic Toolbox of standard bolts, nuts, washers, bearings, gears and shafts, sized from the standard tables." },
  { icon: Package, risk: "Slow, incomplete hand-offs", cost: "Suppliers chase missing files, formats and revisions.", fix: "Hand-off packs in one click: STEP, STL, drawings and BOM from the same revision." },
  { icon: Users, risk: "Scaling means hiring", cost: "More programs need more engineers, months before they are productive.", fix: "Design Office runs named specialist agents in parallel on a program, with your engineers directing and signing off." },
];

export default function Why() {
  useTitle("Why Formwright");
  const { me } = useSession();
  const signedIn = !!me?.user;
  const q = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog") });
  const plans: PlanLike[] = useMemo(() => {
    const live = (q.data?.plans ?? []).filter(p => p.code !== "trial" && !p.contact_sales && p.price_cents > 0 && p.tokens > 0);
    return live.length ? live : FALLBACK_PLANS;
  }, [q.data]);
  const packs: PackLike[] = useMemo(() => {
    const t = (q.data?.topups ?? []).filter(p => p.tokens > 0);
    return t.length ? t : FALLBACK_PACKS;
  }, [q.data]);
  const trial = q.data?.trial_tokens ?? 1000;
  const run = q.data?.typical_run ?? { new: { typical: 250, low: 40, high: 400 }, change: { typical: 60, low: 20, high: 280 } };
  const inputs = useMemo(() => defaultInputs(plans, packs), [plans, packs]);
  const hero = heroStats(inputs);
  const tokenPrice = packTokenPrice(packs);
  const team = plans.find(p => p.code === "team") ?? plans[plans.length - 1]!;
  const hire = hireYearOne();
  const teamYear = planYear(team, 2000, packs);
  const loadedDrafter = (65_000 * HIRE.overhead) / HIRE.hoursPerYear;
  const start = signedIn
    ? <Button3D to="/app" size="lg" icon={<ArrowRight className="h-4 w-4" />}>Open the app</Button3D>
    : <Button3D to="/signup" size="lg" icon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button3D>;

  const STATS = [
    { v: hero.firstModel, f: (n: number) => `${Math.round(n)}×`, l: "sooner to a first verified model", s: `${PROFILES.medium.briefMinutes} min vs ≈ ${PROFILES.medium.convHours * PROFILES.medium.modelShare} h of modelling` },
    { v: hero.costReduction * 100, f: (n: number) => `${Math.round(n)}%`, l: "lower cost per part", s: "including your engineer's review time" },
    { v: hero.throughput, f: (n: number) => `${n.toFixed(1)}×`, l: "more parts per engineer-hour", s: "review and sign-off stay with your engineer" },
    { v: hero.yearly, f: (n: number) => `$${Math.round(n / 1000)}k`, l: "modelled saving per year", s: `${hero.parts} parts a month at US$${hero.rate}/h` },
  ];

  return (
    <main className="overflow-x-clip">
      {/* hero */}
      <section className="s-grid relative overflow-hidden border-b border-ink/80">
        <div className="relative mx-auto grid max-w-[1240px] items-end gap-12 px-4 pb-14 pt-12 sm:px-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:pt-16">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3"><Fcf cells={["Hours", "Per part"]} /><span className="s-anno text-ink2">Why Formwright</span></div>
            <h1 className="s-display mt-7 text-[36px] text-ink min-[420px]:text-[44px] sm:text-[60px] md:text-[72px] lg:text-[62px] xl:text-[72px]">
              <span className="s-rise"><span>Why buy</span></span><span className="s-rise pb-[.18em]"><span style={{ ["--d" as string]: ".1s" }}><span className="underline decoration-hi decoration-[0.12em] underline-offset-[0.1em]">Formwright?</span></span></span>
            </h1>
            <Dim label="Brief to signed-off part" load delay={0.45} className="max-w-[560px]" />
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-ink2 sm:text-[18px]">
              Because your engineers should spend their hours on engineering decisions, not on redrawing plates and brackets.
              Formwright turns a brief into checked, parametric CAD with drawings and DFM advice, so each engineer ships more parts, sooner, for less.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {["Faster", "Checked every build", "Manufacturing-aware", "Cheaper per part"].map(t => <Badge3D key={t}>{t}</Badge3D>)}
            </div>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              {start}
              <Button3D href="#calculator" size="lg" finish="steel" icon={<CalcIcon className="h-4 w-4" />}>Run your numbers</Button3D>
            </div>
          </div>
          <Reveal delay={0.1}><RaceCard /></Reveal>
        </div>
        <div className="relative mx-auto max-w-[1240px] px-4 pb-14 sm:px-6">
          <div className="grid grid-cols-2 gap-px overflow-hidden border border-ink/70 bg-rule lg:grid-cols-4">
            {STATS.map((s, i) => (
              <Reveal key={s.l} delay={i * 0.08} className="h-full bg-slab p-5 sm:p-6">
                <div className="font-display text-[34px] font-extrabold leading-none tracking-tight text-bp sm:text-[46px]" style={{ fontStretch: "112%" }}><CountUp value={s.v} format={s.f} /></div>
                <div className="mt-2 text-sm font-medium">{s.l}</div>
                <div className="mt-1 text-xs text-muted">{s.s}</div>
              </Reveal>
            ))}
          </div>
          <p className="mt-3 text-[12px] text-ink2">
            Modelled estimates from the calculator's opening scenario: {inputs.parts} medium parts a month, US${inputs.rate}/h engineer, {Math.round(inputs.review * 100)}% review kept, {inputs.plan.name} plan. <a href="#calculator" className="underline">See the arithmetic</a>.
          </p>
        </div>
      </section>

      {/* cost of conventional work */}
      <section id="cost" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 py-20 sm:px-6">
        <SectionHead n="01" eyebrow="The status quo" title="Conventional CAD hours are expensive hours."
          body="Every part is modelled, drawn and checked by a skilled engineer. Here is what that time costs, from public figures." />
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { k: "Mechanical engineer", v: "≈ US$99,500/yr", sub: <>median pay<Sup n={1} /> → ≈ <b className="text-text">US${hire.hourly.toFixed(0)}/h</b> fully loaded at 1.4× overhead<Sup n={3} /></> },
            { k: "Mechanical drafter", v: "≈ US$65,000/yr", sub: <>median pay<Sup n={2} /> → ≈ <b className="text-text">US${loadedDrafter.toFixed(0)}/h</b> fully loaded<Sup n={3} /></> },
            { k: "Design consultancy", v: "US$75 to 150/h", sub: <>typical US freelance and consultancy rates; offshore US$25 to 50/h (est.)<Sup n={5} /></> },
            { k: "Hiring a new engineer", v: "≈ 44 days", sub: <>average time to fill and ≈ US$4,700 cost per hire<Sup n={4} />, then 3 to 6 months to full productivity (est.)</> },
          ].map((c, i) => (
            <Reveal key={c.k} delay={i * 0.08} className="card h-full p-5">
              <div className="text-xs font-medium text-muted">{c.k}</div>
              <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{c.v}</div>
              <p className="mt-2 text-xs leading-relaxed text-muted">{c.sub}</p>
            </Reveal>
          ))}
        </div>
        <Reveal className="mt-6 rounded-lg border border-border bg-panel2/60 p-4 text-sm text-muted">
          A medium-complexity part (housing, enclosure, multi-feature machined part) typically takes an experienced engineer
          <b className="text-text"> ≈ {PROFILES.medium.convHours} h</b> to model, draw and self-check (est.). At US$70/h that is
          <b className="text-text"> {usd(PROFILES.medium.convHours * 70)} per part</b> before a single revision.
        </Reveal>
      </section>

      {/* risks */}
      <section id="risks" className="s-print s-grid scroll-mt-20 border-y border-ink">
        <div className="mx-auto max-w-[1240px] px-4 py-20 sm:px-6 sm:py-24">
          <Reveal className="max-w-3xl"><SheetHead onPrint n="02" kicker="Risk, removed" title="The hidden costs of conventional work, and what we do about each."
            body="Hours are only the visible cost. Errors, drift and rework are the expensive ones." /></Reveal>
          <div className="mt-12 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {RISKS.map((r, i) => (
              <Reveal key={r.risk} delay={(i % 3) * 0.08} className="h-full border border-[#7eb2ff]/25 bg-white/[.03] p-5 transition-colors hover:border-[#7eb2ff]/60">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center border border-[#7eb2ff]/40 text-[#9cc3ff]"><r.icon className="h-[18px] w-[18px]" /></div>
                  <h3 className="font-semibold text-white">{r.risk}</h3>
                </div>
                <p className="mt-3 text-[14.5px] text-[#b8c8e0]">{r.cost}</p>
                <div className="mt-3 flex gap-2 border-t border-white/[.12] pt-3 text-[14.5px] text-white">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#6FC79A]" />
                  <span>{r.fix}</span>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* worked examples */}
      <section id="examples" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 py-20 sm:px-6">
        <SectionHead n="03" eyebrow="Worked examples" title="The arithmetic, part by part."
          body={<>Conventional = hours × US$70/h. Formwright = tokens × US${tokenPrice.toFixed(3)} (the smallest top-up pack, our highest per-token price) + your engineer's review at 25% of the conventional hours.</>} />
        <div className="mt-12 grid gap-4 lg:grid-cols-2">
          {EXAMPLES.map((e, i) => {
            const c = exampleCost(e, 70, tokenPrice, 0.25);
            const big = e.key === "gearbox";
            return (
              <Reveal key={e.key} delay={(i % 2) * 0.08} className={cx("card h-full overflow-hidden", big && "lg:col-span-2")}>
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border p-5">
                  <div className="min-w-0">
                    <h3 className="flex items-center gap-2 font-semibold">{big ? <Boxes className="h-4 w-4 text-primary" /> : <Package className="h-4 w-4 text-primary" />}{e.title}</h3>
                    <p className="mt-1 text-sm text-muted">{e.body}</p>
                  </div>
                  <div className="rounded-full bg-success/10 px-2.5 py-1 text-xs font-semibold text-success tabular-nums">
                    ≈ {range([c.saving[1] * 100, c.saving[0] * 100], n => `${Math.round(n)}`)}% lower
                  </div>
                </div>
                <div className={cx("grid divide-y divide-border sm:grid-cols-2 sm:divide-x sm:divide-y-0")}>
                  <div className="p-5">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted"><span className="s-conv h-2.5 w-2.5" />Conventional</div>
                    <div className="mt-2 text-2xl font-semibold tabular-nums">{usdRange(c.conv)}</div>
                    <div className="mt-1 font-mono text-[12px] text-muted">{range(e.convHours, n => `${n}`)} h × $70/h</div>
                    <div className="mt-3 flex items-center gap-1.5 text-xs text-muted"><Clock className="h-3.5 w-3.5" />Calendar: {e.convCalendar}</div>
                    <p className="mt-2 text-xs text-muted">{e.convSteps}</p>
                  </div>
                  <div className="p-5">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted"><span className="h-2 w-2 rounded-sm bg-primary" />Formwright</div>
                    <div className="mt-2 text-2xl font-semibold tabular-nums">{usdRange(c.fw)}</div>
                    <div className="mt-1 space-y-0.5 font-mono text-[12px] text-muted">
                      <div>{range(e.tokens, n => n.toLocaleString("en-US"))} tokens × ${tokenPrice.toFixed(3)} = {usdRange(c.tokensCost)}</div>
                      <div>+ review {range(c.reviewHours, n => `${+n.toFixed(2)}`)} h × $70/h = {usdRange(c.reviewCost)}</div>
                    </div>
                    <div className="mt-3 flex items-center gap-1.5 text-xs text-muted"><Zap className="h-3.5 w-3.5 text-primary" />First verified model: {e.fwTime}</div>
                    <p className="mt-2 text-xs text-muted">{e.fwSteps}</p>
                  </div>
                </div>
              </Reveal>
            );
          })}
        </div>
        <p className="mt-4 text-[11px] text-muted">Hours, token counts and times are typical estimates for an experienced engineer and for Formwright runs of this kind; your parts will differ. Drawings, checks, Toolbox parts and parameter edits use no tokens.</p>
      </section>

      {/* calculator */}
      <section id="calculator" className="scroll-mt-20 border-y border-border bg-panel2/50">
        <div className="mx-auto max-w-[1240px] px-4 py-20 sm:px-6">
          <SectionHead n="04" eyebrow="ROI calculator" title="Run your own numbers."
            body={`Plan prices and token packs are read live from our pricing. Your engineer still reviews and signs off every part; set how much of their time that takes.`} />
          <Reveal className="mt-10"><Calculator key={`${plans.map(p => p.code + p.price_cents + p.tokens).join()}|${packs.length}`} plans={plans} packs={packs} initial={inputs} /></Reveal>
        </div>
      </section>

      {/* hire vs buy */}
      <section id="hire" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 py-20 sm:px-6">
        <SectionHead n="05" eyebrow="Hire or buy" title="Another engineer, or more from the ones you have?"
          body="Formwright doesn't replace your engineers' judgement or sign-off. It removes the hours between a decision and a verified model." />
        <div className="mt-12 grid gap-4 md:grid-cols-2">
          <Reveal className="card h-full p-6">
            <div className="flex items-center gap-2 text-sm font-semibold"><Users className="h-4 w-4 text-accent" />Hire one more mechanical engineer</div>
            <dl className="mt-5 space-y-2.5 text-sm">
              {[
                [<>Median salary<Sup n={1} /></>, usd(HIRE.salary)],
                [<>Benefits and overhead (×{HIRE.overhead})<Sup n={3} /></>, usd(hire.loaded - HIRE.salary)],
                [<>CAD and PDM seat (est.)<Sup n={6} /></>, usd(HIRE.cadSeat)],
                [<>Recruiting<Sup n={4} /></>, usd(HIRE.recruiting)],
              ].map(([k, v], i) => <div key={i} className="flex justify-between gap-3"><dt className="text-muted">{k}</dt><dd className="tabular-nums">{v}</dd></div>)}
              <div className="flex justify-between gap-3 border-t border-border pt-2.5 font-semibold"><dt>First year</dt><dd className="tabular-nums">{usd(hire.total)}</dd></div>
            </dl>
            <p className="mt-4 text-xs text-muted">≈ 44 days to fill<Sup n={4} />, then months of onboarding before full output. One more pair of hands, at the same hours per part.</p>
          </Reveal>
          <Reveal delay={0.08} className="card relative h-full overflow-hidden border-ink p-6 ring-2 ring-hi">
            <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-primary" />Formwright {team.name}</div>
            <dl className="mt-5 space-y-2.5 text-sm">
              <div className="flex justify-between gap-3"><dt className="text-muted">{team.name} plan, 12 months</dt><dd className="tabular-nums">{usd(12 * team.price_cents / 100)}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted">Seats included</dt><dd className="tabular-nums">{team.seats}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted">Pooled tokens</dt><dd className="tabular-nums">{team.tokens.toLocaleString()}/mo ≈ {Math.round(team.tokens / run.new.typical)} new parts</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-muted">Plus 2,000 extra tokens every month</dt><dd className="tabular-nums">{usd(teamYear - 12 * team.price_cents / 100)}</dd></div>
              <div className="flex justify-between gap-3 border-t border-border pt-2.5 font-semibold"><dt>First year</dt><dd className="tabular-nums">{usd(teamYear)}</dd></div>
            </dl>
            <p className="mt-4 text-xs text-muted">Live the day you sign up. At the modelled {hero.throughput.toFixed(1)}× more parts per engineer-hour, a five-person team does the modelling work of many more, and every part is still reviewed and signed off by your people.</p>
            <div className="mt-4 rounded-lg bg-primary-soft px-3 py-2 text-sm text-primary"><b className="tabular-nums">{Math.round(hire.total / teamYear)}×</b> less than one new hire's first year.</div>
          </Reveal>
        </div>
      </section>

      {/* tokens */}
      <section id="tokens" className="scroll-mt-20 border-y border-border bg-panel2/50">
        <div className="mx-auto max-w-[1240px] px-4 py-20 sm:px-6">
          <SectionHead n="06" eyebrow="Tokens, explained" title="You pay for AI work. Clicks are free."
            body="A token is our unit of AI design work. Each agent run is metered live, stops at the budget you set and is never charged beyond it. Everything deterministic is free." />
          <div className="mt-10 grid gap-6 lg:grid-cols-2">
          <div>
            <Reveal className="overflow-hidden rounded-lg border border-border bg-panel">
              <table className="w-full text-sm">
                <thead className="bg-panel2 text-left text-[12px] text-muted"><tr><th className="px-4 py-2.5 font-medium">Work</th><th className="px-4 py-2.5 text-right font-medium">Tokens</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {[
                    ["New part from a written brief", `${run.new.low} to ${run.new.high}`, `typically ≈ ${run.new.typical}`],
                    ["Agent change to an existing part", `${run.change.low} to ${run.change.high}`, `typically ≈ ${run.change.typical}`],
                    ["Parameter edit, manual feature, Toolbox part, restore", "0"],
                    ["Drawing sheet, geometry checks, STEP / STL export", "0"],
                    ["Assembly mates, interference check, BOM", "0"],
                    ["Design Office program, 15 to 20 parts (est.)", "4,000 to 8,000"],
                  ].map(([k, v, sub]) => <tr key={k}><td className="px-4 py-2.5">{k}</td><td className={cx("whitespace-nowrap px-4 py-2.5 text-right tabular-nums", v === "0" ? "font-semibold text-success" : "")}>{v === "0" ? "Free" : v}{sub && <div className="text-[11px] text-muted">{sub}</div>}</td></tr>)}
                </tbody>
              </table>
            </Reveal>
          </div>
          <div>
            <Reveal className="overflow-hidden rounded-lg border border-border bg-panel">
              <table className="w-full text-sm">
                <thead className="bg-panel2 text-left text-[12px] text-muted"><tr><th className="px-4 py-2.5 font-medium">Where tokens come from</th><th className="px-4 py-2.5 text-right font-medium">Price</th><th className="px-4 py-2.5 text-right font-medium">Per token</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {plans.map(p => (
                    <tr key={p.code}><td className="px-4 py-2.5">{p.name} plan · {p.tokens.toLocaleString()} included</td><td className="px-4 py-2.5 text-right tabular-nums">${p.price_cents / 100}/mo</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{(p.price_cents / p.tokens).toFixed(2)}¢</td></tr>
                  ))}
                  {[...packs].sort((a, b) => a.tokens - b.tokens).map(t => (
                    <tr key={t.tokens}><td className="px-4 py-2.5">Top-up · {t.tokens.toLocaleString()} tokens</td><td className="px-4 py-2.5 text-right tabular-nums">${t.price_cents / 100}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{(t.price_cents / t.tokens).toFixed(2)}¢</td></tr>
                  ))}
                </tbody>
              </table>
            </Reveal>
            <Reveal className="mt-4 grid grid-cols-3 gap-3 text-center">
              {[
                ["≈ " + usd(run.new.typical * tokenPrice), "typical new part"],
                ["≈ " + usd(run.change.typical * tokenPrice, 2), "typical agent change"],
                [`${trial.toLocaleString()}`, "free trial tokens"],
              ].map(([v, l]) => <div key={l} className="card p-3"><div className="text-lg font-semibold tabular-nums">{v}</div><div className="text-[11px] text-muted">{l}</div></div>)}
            </Reveal>
            <p className="mt-3 text-[11px] text-muted">Plan prices include the software and modules as well as tokens. Top-up packs never expire while your account is active. Per-part prices at the 500-token top-up price.</p>
          </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="mx-auto max-w-3xl scroll-mt-20 px-4 py-20 sm:px-6">
        <SectionHead n="07" eyebrow="FAQ" title="Questions buyers ask." />
        <div className="mt-10 divide-y divide-border rounded-lg border border-border bg-panel">
          {[
            ["Does Formwright replace my engineers?", "No. It amplifies them. Your engineers write the brief, make the engineering decisions, review every part and sign it off. Formwright removes the hours of modelling, drawing and checking in between."],
            ["Are the parts ready for manufacture?", "Every build passes deterministic geometry checks and every revision gets advisory DFM findings, but neither is a certification. Your engineer reviews and approves parts and drawings before they go to a supplier, exactly as today."],
            ["How did you calculate the savings?", "With the model on this page: conventional hours × your rate, against Formwright tokens at our published prices plus your engineer's review time. The defaults are typical estimates; change them in the calculator to match your work."],
            ["What if a run goes wrong or costs more than expected?", "Every run shows a live token meter and stops at the budget you set, and is never charged beyond it. Parameter edits, manual features and restores are free, so small corrections cost nothing."],
            ["Does it work with our existing CAD?", "Yes. Import STEP from any CAD system and export STEP or STL back into SOLIDWORKS, Creo, Fusion, Inventor or your slicer. The parametric source stays editable in Formwright."],
            ["Who owns the designs?", "You do. Models, parametric source, drawings and exports belong to your organization."],
          ].map(([qq, a]) => (
            <details key={qq} className="group px-5 py-4 [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                {qq}<span className="text-muted transition group-open:rotate-45">+</span>
              </summary>
              <p className="mt-2 text-sm leading-relaxed text-muted">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* CTA: a title block with a gear that turns as you scroll */}
      <section className="px-4 pb-20 sm:px-6">
        <Reveal className="mx-auto max-w-[1192px]">
          <Card3D screws hi inner="p-0">
            <div className="s-hazard h-2.5" aria-hidden="true" />
            <div className="grid lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
              <div className="border-b border-ink/80 p-7 sm:p-10 lg:border-b-0 lg:border-r">
                <span className="s-anno text-bp">Next operation</span>
                <h2 className="s-h2 mt-3 text-[34px] text-ink sm:text-[48px]">Try it on your own parts.</h2>
                <p className="mt-4 max-w-xl text-[17px] leading-relaxed text-ink2">{trial.toLocaleString()} free tokens, every module, 14 days. No credit card. Bring a part your team modelled last month and compare.</p>
                <div className="mt-8 flex flex-wrap items-center gap-4">
                  {start}
                  <Button3D to="/pricing" size="lg" finish="steel">See pricing</Button3D>
                  <Button3D href={DEMO} size="lg" finish="steel" icon={<ClipboardCheck className="h-4 w-4" />}>Book a demo</Button3D>
                </div>
              </div>
              <ScrollGear />
            </div>
          </Card3D>
        </Reveal>
      </section>

      {/* sources + disclaimer */}
      <section id="sources" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 pb-16 sm:px-6">
        <div className="border-t border-border pt-6 text-[11px] leading-relaxed text-muted">
          <div className="font-semibold text-text">Sources and assumptions</div>
          <ol className="mt-2 list-decimal space-y-1 pl-5">{SOURCES.map(s => <li key={s}>{s}</li>)}</ol>
          <p className="mt-3">
            All savings, hours, token counts and times on this page are estimates for illustration, computed from the stated assumptions;
            they are not a quote or a guarantee. Actual savings depend on your parts, your workflow and how much review your engineers do.
            Formwright output is reviewed and approved by your engineers; checks and DFM findings are advisory and do not certify a part for manufacture.
          </p>
        </div>
      </section>
    </main>
  );
}
