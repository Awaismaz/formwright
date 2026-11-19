import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Coins, Minus } from "lucide-react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog, Product } from "@/lib/types";
import { cx, money, num } from "@/lib/format";
import { SALES } from "./Landing";
import { Reveal } from "@/components/landing/motion";
import { Badge3D, Button3D, Card3D, Dim, Fcf, SectionHead } from "@/components/landing/site";

function PlanPlate({ p, cta, onChoose }: { p: Product; cta: string; onChoose: () => void }) {
  return (
    <Card3D className="h-full" hi={p.highlight} screws={p.highlight} inner="flex h-full flex-col p-6">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-display text-[22px] font-extrabold uppercase leading-none text-ink" style={{ fontStretch: "118%" }}>{p.name}</h3>
        {p.highlight && <Badge3D tone="hi">Most popular</Badge3D>}
      </div>
      <p className="mt-2 min-h-[42px] text-[14px] leading-snug text-ink2">{p.tagline}</p>
      <div className="mt-5 flex items-baseline gap-1.5 border-y border-rule py-4">
        {p.contact_sales ? <span className="font-display text-[34px] font-extrabold text-ink">Custom</span> : <>
          <span className="font-display text-[40px] font-extrabold leading-none tracking-tight text-ink" style={{ fontStretch: "110%" }}>{money(p.price_cents)}</span>
          {p.interval && p.price_cents > 0 && <span className="s-anno text-ink2">/ {p.interval}</span>}
        </>}
      </div>
      <ul className="mt-4 flex-1 space-y-2.5">
        {p.features.map(f => <li key={f} className="flex gap-2.5 text-[14.5px] leading-snug text-ink"><Check className="mt-0.5 h-4 w-4 shrink-0 text-pass" aria-hidden="true" />{f}</li>)}
      </ul>
      <Button3D className="mt-6" block finish={p.highlight ? "hi" : "steel"} disabled={!p.purchasable && !p.contact_sales} onClick={onChoose}
        icon={<ArrowRight className="h-4 w-4" />}>{cta}</Button3D>
    </Card3D>
  );
}

export default function Pricing() {
  useTitle("Pricing");
  const nav = useNavigate();
  const { me } = useSession();
  const signedIn = !!me?.user;
  const q = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog") });
  const data = q.data;
  const trial = data?.trial_tokens ?? 1000;
  const paid = (data?.plans ?? []).filter(p => p.code !== "trial");
  const run = data?.typical_run;
  const cols = paid.length >= 4 ? "md:grid-cols-2 xl:grid-cols-4" : paid.length === 3 ? "md:grid-cols-3" : "md:grid-cols-2";

  return (
    <main>
      <section className="s-grid border-b border-ink/80">
        <div className="mx-auto max-w-[1240px] px-4 pb-14 pt-12 sm:px-6 sm:pt-16">
          <div className="flex flex-wrap items-center gap-3">
            <Fcf cells={["Tokens", "Per run"]} /><span className="s-anno text-ink2">Pricing</span>
          </div>
          <h1 className="s-display mt-7 text-[40px] text-ink sm:text-[64px] lg:text-[84px]">
            <span className="s-rise"><span>Pay for the</span></span><span className="s-rise"><span style={{ ["--d" as string]: ".1s" }}>engineering you use.</span></span>
          </h1>
          <Dim label="Trial: 14 days, every module" load delay={0.4} className="mt-2 max-w-[700px]" />
          <p className="mt-6 max-w-2xl text-[17px] leading-relaxed text-ink2 sm:text-[18px]">
            Every plan starts with a free 14-day trial: {num(trial)} tokens (enough for dozens of simple parts) and every module on your own parts.
            Add modules when you need them, top up tokens any time.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-[1240px] px-4 py-16 sm:px-6" aria-label="Plans">
        {!data ? (
          <div className={cx("grid gap-6", cols)} aria-busy="true">
            {[0, 1, 2].map(i => <div key={i} className="h-[420px] animate-pulse bg-sheet2" />)}
          </div>
        ) : (
          <div className={cx("grid gap-6", cols)}>
            {paid.map((p, i) => (
              <Reveal key={p.code} delay={i * 0.06} className="h-full">
                <PlanPlate p={p} cta={p.contact_sales ? "Contact sales" : signedIn ? `Switch to ${p.name}` : "Start free trial"}
                  onChoose={() => p.contact_sales ? (location.href = SALES) : nav(signedIn ? "/app/billing" : `/signup?plan=${p.code}`)} />
              </Reveal>
            ))}
          </div>
        )}
      </section>

      {data && <>
        <section className="mx-auto max-w-[1240px] px-4 pb-20 sm:px-6">
          <Reveal><SectionHead n="01" kicker="Compare" title="What each plan carries." /></Reveal>
          <Card3D className="mt-10" inner="overflow-x-auto p-0">
            <table className="w-full min-w-[640px] text-left">
              <caption className="sr-only">Modules and allowances by plan</caption>
              <thead className="border-b border-ink/70">
                <tr><th scope="col" className="s-anno px-5 py-3.5 font-medium text-ink2">Module</th>
                  {data.plans.map(p => <th key={p.code} scope="col" className="s-anno px-4 py-3.5 text-center font-medium text-ink">{p.name}</th>)}</tr>
              </thead>
              <tbody>
                {data.modules.map(m => (
                  <tr key={m.code} className="border-b border-rule hover:bg-bpsoft/40">
                    <td className="px-5 py-3.5 text-[15px] text-ink"><span className="mr-2">{m.name}</span>{m.status !== "live" && <Badge3D>Preview</Badge3D>}</td>
                    {data.plans.map(p => <td key={p.code} className="px-4 py-3.5 text-center">
                      {p.modules.includes(m.code) ? <><Check className="mx-auto h-4 w-4 text-pass" aria-hidden="true" /><span className="sr-only">Included</span></>
                        : data.addons.some(a => a.modules.includes(m.code)) && !p.contact_sales ? <span className="s-anno text-[10px] text-ink2">Add-on</span>
                        : <><Minus className="mx-auto h-4 w-4 text-ink2/60" aria-hidden="true" /><span className="sr-only">Not included</span></>}
                    </td>)}
                  </tr>
                ))}
                <tr className="border-b border-rule"><td className="px-5 py-3.5 text-[15px] font-semibold text-ink">Tokens included</td>
                  {data.plans.map(p => <td key={p.code} className="px-4 py-3.5 text-center font-anno text-[13px] tabular-nums text-ink">{p.contact_sales ? "Custom" : p.tokens.toLocaleString() + (p.interval ? " / mo" : "")}</td>)}</tr>
                <tr><td className="px-5 py-3.5 text-[15px] font-semibold text-ink">Seats</td>
                  {data.plans.map(p => <td key={p.code} className="px-4 py-3.5 text-center font-anno text-[13px] text-ink">{p.contact_sales ? "Unlimited" : p.seats}</td>)}</tr>
              </tbody>
            </table>
          </Card3D>
        </section>

        <section className="border-t border-ink/80 bg-sheet2">
          <div className="mx-auto grid max-w-[1240px] gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div>
              <Reveal><SectionHead n="02" kicker="Add-ons" title="Unlock one module on any plan."
                body="Each one opens straight on the part you designed." /></Reveal>
              <div className="mt-8 grid gap-4 sm:grid-cols-2">
                {data.addons.map(a => {
                  const m = data.modules.find(x => x.code === a.modules[0]);
                  return (
                    <Card3D key={a.code} inner="flex h-full items-start justify-between gap-3 p-5">
                      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2 text-[15.5px] font-semibold text-ink">{a.name}{m && m.status !== "live" && <Badge3D>Preview</Badge3D>}</div>
                        <div className="mt-1 text-[13.5px] leading-snug text-ink2">{a.tagline}</div></div>
                      <div className="whitespace-nowrap font-anno text-[14px] font-semibold text-ink">{money(a.price_cents, a.interval)}</div>
                    </Card3D>
                  );
                })}
              </div>
            </div>
            <div>
              <Reveal><SectionHead n="03" kicker="Token packs" title="Top up any time." body="One-off packs that never expire while your account is active." /></Reveal>
              <div className="mt-8 space-y-4">
                {data.topups.map(t => (
                  <Card3D key={t.code} inner="flex items-center gap-3 p-4">
                    <Coins className="h-5 w-5 shrink-0 text-bp" aria-hidden="true" />
                    <div className="min-w-0 flex-1"><div className="text-[15.5px] font-semibold text-ink">{t.name}</div>{t.tagline && <div className="text-[13px] text-pass">{t.tagline}</div>}</div>
                    <div className="font-anno text-[15px] font-semibold text-ink">{money(t.price_cents)}</div>
                  </Card3D>
                ))}
              </div>
              {run && <div className="mt-6 border-l-2 border-bp pl-4 text-[14px] leading-relaxed text-ink2">
                <div className="s-anno mb-1.5 text-ink">What a run costs</div>
                A new part from a written brief typically uses <b className="text-ink">{run.new.low} to {run.new.high} tokens</b> (measured; most about {run.new.typical}).
                A change to an existing part usually uses {run.change.low} to {run.change.high}. Parameter edits, manual features, Toolbox parts and restores are free.
                Every run shows a live meter, stops at the budget you set and is never charged beyond it.
              </div>}
            </div>
          </div>
        </section>
      </>}
    </main>
  );
}
