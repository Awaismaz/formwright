import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { BadgeCheck, Code2, GitBranch } from "lucide-react";
import { Logo } from "@/components/ui";

export default function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-full lg:grid-cols-[1fr_1.05fr]">
      <aside className="relative hidden overflow-hidden bg-chrome p-12 text-chrome-fg lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -left-24 bottom-[-120px] h-[420px] w-[420px] rounded-full bg-primary/40 blur-[120px]" />
        <div className="pointer-events-none absolute right-[-80px] top-[-80px] h-72 w-72 rounded-full bg-accent/25 blur-[100px]" />
        <div className="pointer-events-none absolute inset-0 opacity-[.08] [background-image:linear-gradient(#fff_1px,transparent_1px),linear-gradient(90deg,#fff_1px,transparent_1px)] [background-size:28px_28px]" />
        <Link to="/" className="relative"><Logo size={28} dark /></Link>
        <div className="relative mt-auto max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight text-white">Start every part from a correct, verified model.</h2>
          <ul className="mt-8 space-y-5">
            {[
              [BadgeCheck, "Numerically verified", "Dimensions and volume checked against your requirements on every build."],
              [Code2, "Parametric and editable", "Named dimensions and readable source — no dumb geometry."],
              [GitBranch, "Works with your CAD", "Export STEP into SOLIDWORKS, Creo, Fusion and more."],
            ].map(([I, t, b]) => {
              const C = I as typeof BadgeCheck;
              return <li key={t as string} className="flex gap-3"><C className="mt-0.5 h-5 w-5 shrink-0 text-[#7FAAF0]" />
                <div><div className="font-medium text-white">{t as string}</div><div className="text-sm text-chrome-muted">{b as string}</div></div></li>;
            })}
          </ul>
        </div>
        <div className="relative mt-12 text-xs text-chrome-muted">© {new Date().getFullYear()} Formwright</div>
      </aside>
      <main className="flex items-center justify-center bg-panel px-4 py-12 sm:px-8">
        <div className="w-full max-w-[400px]">
          <Link to="/" className="mb-10 inline-block lg:hidden"><Logo size={26} /></Link>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1.5 text-sm text-muted">{subtitle}</p>}
          <div className="mt-8">{children}</div>
          {footer && <div className="mt-8 text-center text-sm text-muted">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
