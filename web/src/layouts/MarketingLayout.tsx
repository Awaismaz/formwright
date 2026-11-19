import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ArrowRight, Menu as MenuIcon, X } from "lucide-react";
import { useSession } from "@/lib/session";
import { cx } from "@/lib/format";
import { Button3D, SiteLogo, SiteScope, ThemeSwitch, ThirdAngle } from "@/components/landing/site";

const LINKS = [
  { to: "/#how", label: "How it works" }, { to: "/why", label: "Why Formwright" }, { to: "/#modules", label: "Modules" },
  { to: "/#trust", label: "Security" }, { to: "/pricing", label: "Pricing" },
];

const FOOT: { h: string; l: [string, string][] }[] = [
  { h: "Product", l: [["How it works", "/#how"], ["Modules", "/#modules"], ["Why Formwright", "/why"], ["Pricing", "/pricing"], ["Start free trial", "/signup"]] },
  { h: "Company", l: [["Security", "/#trust"], ["Contact", "mailto:hello@formwright.dev"], ["Enterprise sales", "mailto:sales@formwright.dev?subject=Formwright%20Enterprise"]] },
  { h: "Legal", l: [["Terms of service", "/legal/terms"], ["Privacy policy", "/legal/privacy"], ["Acceptable use", "/legal/aup"]] },
];

/** The website footer: a drawing's title block on blueprint. Also used by pages outside this layout. */
export function SiteFooter() {
  const year = new Date().getFullYear();
  const link = "inline-flex min-h-[32px] items-center text-[15px] text-white/90 hover:text-white hover:underline hover:underline-offset-4";
  return (
    <footer className="s-print s-grid border-t border-ink">
      <div className="mx-auto max-w-[1240px] px-4 py-14 sm:px-6">
        <div className="grid border border-white/40 md:grid-cols-[1.5fr_1fr_1fr_1fr]">
          <div className="border-b border-white/25 p-6 md:border-b-0 md:border-r">
            <SiteLogo size={28} onPrint />
            <p className="mt-4 max-w-xs text-[15px] leading-relaxed text-[#b8c8e0]">An AI design office for mechanical teams. Written brief in, checked and editable CAD out.</p>
          </div>
          {FOOT.map((c, i) => (
            <div key={c.h} className={cx("border-white/25 p-6", i < 2 && "border-b md:border-b-0 md:border-r")}>
              <div className="s-anno text-[#9cc3ff]">{c.h}</div>
              <ul className="mt-4 space-y-1">
                {c.l.map(([t, to]) => (
                  <li key={t}>{to.startsWith("mailto:") ? <a href={to} className={link}>{t}</a> : <Link to={to} className={link}>{t}</Link>}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {/* the sheet's title strip */}
        <div className="grid grid-cols-2 border-x border-b border-white/40 text-white sm:grid-cols-3 lg:grid-cols-[1fr_1fr_1fr_1fr_1.4fr_1fr]">
          {([
            ["Dwg no.", "FW-0001"], ["Rev", "A"], ["Units", "mm"], ["Scale", "1 : 1"],
            ["Projection", <span key="p" className="inline-flex items-center gap-2">Third angle<ThirdAngle className="h-3.5 w-8 text-[#9cc3ff]" /></span>],
            ["Sheet", "1 of 1"],
          ] as const).map(([k, v], i) => (
            <div key={k} className={cx("border-b border-white/25 px-4 py-3 lg:border-b-0", i % 2 === 0 && "border-r sm:border-r-0", "sm:[&:not(:nth-child(3n))]:border-r lg:[&:not(:last-child)]:border-r")}>
              <div className="s-anno text-[9.5px] text-[#9cc3ff]">{k}</div>
              <div className="mt-1 font-anno text-[13px]">{v}</div>
            </div>
          ))}
        </div>
        <p className="mt-6 font-anno text-[12px] text-[#a4b6d0]">© {year} Formwright. Product names are trademarks of their owners; no endorsement implied.</p>
      </div>
    </footer>
  );
}

export default function MarketingLayout() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => {
    setOpen(false);
    if (loc.hash) document.querySelector(loc.hash)?.scrollIntoView({ behavior: "smooth" });
    else window.scrollTo(0, 0);
  }, [loc.pathname, loc.hash]);
  const signedIn = !!me?.user;

  return (
    <SiteScope className="min-h-full">
      <a href="#main" className="s-anno sr-only z-50 bg-hi px-3 py-2 text-[#0c1016] focus:not-sr-only focus:fixed focus:left-3 focus:top-3">Skip to content</a>
      <header className="sticky top-0 z-40 border-b border-ink/80 bg-sheet">
        <div className="mx-auto flex h-16 max-w-[1240px] items-center gap-5 px-4 sm:px-6">
          <Link to="/" aria-label="Formwright home" className="shrink-0"><SiteLogo size={26} /></Link>
          <nav aria-label="Main" className="hidden items-center lg:flex">
            {LINKS.map((l, i) => (
              <NavLink key={l.to} to={l.to} className="group flex min-h-[40px] items-center gap-1.5 px-2.5 text-[14px] font-medium text-ink2 transition-colors hover:text-ink">
                <span className="s-anno text-[10px] text-bp/80 group-hover:text-bp">{String(i + 1).padStart(2, "0")}</span>{l.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-3 lg:flex">
            <ThemeSwitch />
            {signedIn ? <Button3D to="/app" size="sm" icon={<ArrowRight className="h-4 w-4" />}>Open app</Button3D> : <>
              <Link to="/login" className="flex min-h-[40px] items-center px-2 text-[14px] font-medium text-ink hover:underline hover:underline-offset-4">Sign in</Link>
              <Button3D to="/signup" size="sm">Start free trial</Button3D>
            </>}
          </div>
          <button className="ml-auto flex h-11 w-11 items-center justify-center border border-ink/70 lg:hidden" onClick={() => setOpen(!open)}
            aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open} aria-controls="site-menu">
            {open ? <X className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
          </button>
        </div>
        <div className="s-zones h-1" aria-hidden="true" />
        <div id="site-menu" className={cx("border-t border-rule bg-sheet px-4 pb-5 lg:hidden", !open && "hidden")}>
          <nav aria-label="Main menu" className="divide-y divide-rule">
            {LINKS.map((l, i) => (
              <Link key={l.to} to={l.to} className="flex min-h-[48px] items-center gap-3 text-[16px] font-medium">
                <span className="s-anno text-bp">{String(i + 1).padStart(2, "0")}</span>{l.label}
              </Link>
            ))}
          </nav>
          <div className="mt-3 flex items-center justify-between gap-3"><span className="s-anno text-ink2">Theme</span><ThemeSwitch /></div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {signedIn ? <Button3D to="/app" block className="col-span-2">Open app</Button3D> : <>
              <Button3D to="/login" finish="steel" block>Sign in</Button3D>
              <Button3D to="/signup" block>Start free</Button3D>
            </>}
          </div>
        </div>
      </header>

      <div id="main"><Outlet /></div>
      <SiteFooter />
    </SiteScope>
  );
}
