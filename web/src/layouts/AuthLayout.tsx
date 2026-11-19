import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import LazyScene from "@/components/landing/LazyScene";
import { useReducedMotion } from "@/components/landing/motion";
import { Card3D, Dim, SiteLogo, SiteScope, ThemeSwitch } from "@/components/landing/site";

const NOTES: [string, string][] = [
  ["Checked on every build", "Dimensions and volume measured against your requirements, every time it builds."],
  ["Parametric and editable", "Named dimensions you can change on the model, free and repeatable."],
  ["Opens in your CAD", "Verified STEP into SOLIDWORKS, Creo, Fusion and the rest. Native bridges are on the way."],
];

function useWide() {
  const q = "(min-width: 1024px)";
  const [m, setM] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return;
    const f = () => setM(mq.matches);
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  return m;
}

/** Line drawing of the flange: shown while the 3D loads and when WebGL is unavailable. */
const FlangePoster = () => (
  <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true" fill="none" stroke="#9cc3ff" strokeWidth="1">
    <circle cx="100" cy="100" r="75" /><circle cx="100" cy="100" r="30" /><circle cx="100" cy="100" r="60" strokeDasharray="8 3 1 3" opacity=".7" />
    {Array.from({ length: 6 }, (_, i) => { const a = (i * Math.PI) / 3; return <circle key={i} cx={100 + 60 * Math.cos(a)} cy={100 + 60 * Math.sin(a)} r="7" />; })}
  </svg>
);

export default function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  const wide = useWide();
  const reduced = useReducedMotion();
  return (
    <SiteScope className="grid min-h-full lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <aside className="s-print s-grid relative hidden flex-col overflow-hidden border-r border-ink p-10 lg:flex xl:p-12">
        <Link to="/" aria-label="Formwright home" className="self-start"><SiteLogo size={28} onPrint /></Link>

        <div className="relative mx-auto mt-6 aspect-square w-full max-w-[340px]">
          {wide && <LazyScene parts={[{ id: "flange", url: "/landing/flange.glb", color: "#c4ccd6" }]} spin={reduced ? 0 : 9} still={reduced}
            view={[1, -1, 0.9]} zoom={1.1} poster={<FlangePoster />} label="A Formwright flange, Ø150 with six Ø14 holes on PCD 120, turning slowly." />}
          <span className="s-anno pointer-events-none absolute left-0 top-0 text-[#9cc3ff]">View 1 · Flange Ø150</span>
        </div>
        <Dim label="Ø150" className="mx-auto mt-2 w-full max-w-[300px] !text-[#9cc3ff]" />

        <div className="mt-auto max-w-md pt-8">
          <h2 className="s-h2 text-[34px] text-white">Start every part from a checked model.</h2>
          <ol className="mt-7 space-y-5">
            {NOTES.map(([t, b], i) => (
              <li key={t} className="flex gap-3.5">
                <span className="s-balloon text-[#9cc3ff]">{i + 1}</span>
                <div><div className="text-[15.5px] font-semibold text-white">{t}</div><div className="mt-0.5 text-[14.5px] leading-relaxed text-[#b8c8e0]">{b}</div></div>
              </li>
            ))}
          </ol>
        </div>
        <div className="s-anno mt-10 flex justify-between border-t border-white/20 pt-3 text-[10px] text-[#9cc3ff]"><span>© {new Date().getFullYear()} Formwright</span><span>Sheet 1 of 1</span></div>
      </aside>

      <main className="s-grid flex flex-col px-4 py-6 sm:px-8">
        <div className="flex items-center justify-between gap-3">
          <Link to="/" aria-label="Formwright home" className="lg:invisible"><SiteLogo size={24} /></Link>
          <ThemeSwitch />
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[440px]">
            <Card3D inner="p-6 sm:p-8">
              <div className="flex items-center justify-between gap-3 border-b border-ink/70 pb-3">
                <span className="s-anno text-bp">Formwright account</span><span className="s-anno text-ink2">Form FW-A1</span>
              </div>
              <h1 className="s-h2 mt-6 text-[30px] text-ink sm:text-[34px]">{title}</h1>
              {subtitle && <p className="mt-2 text-[15px] leading-relaxed text-ink2">{subtitle}</p>}
              <div className="mt-7">{children}</div>
            </Card3D>
            {footer && <div className="mt-8 text-center text-[15px] text-ink2">{footer}</div>}
          </div>
        </div>
      </main>
    </SiteScope>
  );
}
