import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { Menu as MenuIcon, X } from "lucide-react";
import { useEffect } from "react";
import { useSession } from "@/lib/session";
import { Button, Logo } from "@/components/ui";
import { cx } from "@/lib/format";

const LINKS = [
  { to: "/#how", label: "How it works" }, { to: "/#modules", label: "Modules" },
  { to: "/#trust", label: "Security" }, { to: "/pricing", label: "Pricing" },
];

export default function MarketingLayout() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => {
    setOpen(false);
    if (loc.hash) document.querySelector(loc.hash)?.scrollIntoView({ behavior: "smooth" });
    else window.scrollTo(0, 0);
  }, [loc.pathname, loc.hash]);

  return (
    <div className="min-h-full bg-panel">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-panel/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-4 sm:px-6">
          <Link to="/"><Logo size={26} /></Link>
          <nav className="hidden items-center gap-6 md:flex">
            {LINKS.map(l => <NavLink key={l.to} to={l.to} className="text-sm text-muted hover:text-text">{l.label}</NavLink>)}
          </nav>
          <div className="ml-auto hidden items-center gap-2 md:flex">
            {me?.user ? <Link to="/app"><Button>Open app</Button></Link> : <>
              <Link to="/login"><Button variant="ghost">Sign in</Button></Link>
              <Link to="/signup"><Button>Start free trial</Button></Link>
            </>}
          </div>
          <button className="ml-auto rounded p-2 md:hidden" onClick={() => setOpen(!open)} aria-label="Menu">
            {open ? <X className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
          </button>
        </div>
        <div className={cx("border-t border-border px-4 pb-4 md:hidden", !open && "hidden")}>
          {LINKS.map(l => <Link key={l.to} to={l.to} className="block py-2.5 text-sm">{l.label}</Link>)}
          <div className="mt-2 flex gap-2">
            <Link to="/login" className="flex-1"><Button variant="secondary" className="w-full">Sign in</Button></Link>
            <Link to="/signup" className="flex-1"><Button className="w-full">Start free</Button></Link>
          </div>
        </div>
      </header>
      <Outlet />
      <footer className="border-t border-border bg-chrome text-chrome-fg">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <Logo size={26} dark />
            <p className="mt-4 max-w-xs text-sm text-chrome-muted">The AI design engineer for mechanical teams. From idea to verified, manufacturable CAD.</p>
          </div>
          {[
            { h: "Product", l: [["How it works", "/#how"], ["Modules", "/#modules"], ["Pricing", "/pricing"], ["Start free trial", "/signup"]] },
            { h: "Company", l: [["Security", "/#trust"], ["Contact", "mailto:hello@formwright.dev"], ["Careers", "mailto:hello@formwright.dev"]] },
            { h: "Legal", l: [["Terms of service", "/legal/terms"], ["Privacy policy", "/legal/privacy"], ["Acceptable use", "/legal/aup"]] },
          ].map(c => (
            <div key={c.h}>
              <div className="text-[11px] font-semibold uppercase tracking-[.14em] text-chrome-muted">{c.h}</div>
              <ul className="mt-4 space-y-2.5 text-sm">
                {c.l.map(([t, to]) => <li key={t}>{to.startsWith("mailto:") ? <a href={to} className="hover:text-white">{t}</a> : <Link to={to} className="hover:text-white">{t}</Link>}</li>)}
              </ul>
            </div>
          ))}
        </div>
        <div className="border-t border-white/[.06] py-5 text-center text-xs text-chrome-muted">© {new Date().getFullYear()} Formwright. All rights reserved.</div>
      </footer>
    </div>
  );
}
