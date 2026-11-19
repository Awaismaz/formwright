import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { useTitle } from "@/lib/title";
import { Badge3D, Button3D, Card3D, Dim, SiteLogo, SiteScope, ThemeSwitch } from "@/components/landing/site";

/** 404: a part that isn't in the assembly, drawn in phantom lines. */
export default function NotFound() {
  useTitle("Page not found");
  return (
    <SiteScope className="s-grid flex min-h-full flex-col">
      <header className="flex h-16 items-center justify-between border-b border-ink/80 bg-sheet px-4 sm:px-6">
        <Link to="/" aria-label="Formwright home"><SiteLogo size={24} /></Link><ThemeSwitch />
      </header>
      <main className="mx-auto grid w-full max-w-[1100px] flex-1 items-center gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div>
          <Badge3D tone="hi">Error 404 · part not found</Badge3D>
          <h1 className="s-display mt-6 text-[96px] text-ink sm:text-[150px]">404</h1>
          <Dim label="Missing from this assembly" className="max-w-[420px]" />
          <p className="mt-6 max-w-md text-[17px] leading-relaxed text-ink2">
            There is no page at this address. The link may be broken, or the page may have moved.
          </p>
          <div className="mt-8 flex flex-wrap gap-4">
            <Button3D to="/" size="lg" icon={<ArrowRight className="h-4 w-4" />}>Back to Formwright</Button3D>
            <Button3D to="/pricing" size="lg" finish="steel">Pricing</Button3D>
          </div>
        </div>
        <Card3D inner="p-5" className="mx-auto w-full max-w-[440px]">
          <svg viewBox="0 0 320 260" className="w-full" role="img" aria-label="Drawing of a bracket with a phantom outline where the missing part should be.">
            <g fill="none" stroke="rgb(var(--s-ink))" strokeWidth="1.6">
              <path d="M30 210h120v-30H70V60H30Z" fill="rgb(var(--s-sheet-2))" />
              <circle cx="50" cy="90" r="7" /><circle cx="50" cy="150" r="7" /><circle cx="120" cy="195" r="7" />
            </g>
            <g fill="none" stroke="rgb(var(--s-red))" strokeWidth="1.3" strokeDasharray="14 4 2 4 2 4">
              <path d="M170 210h120v-90h-40v60h-80Z" />
              <circle cx="270" cy="140" r="9" />
            </g>
            <path d="M150 195h20" stroke="rgb(var(--s-ink-2))" strokeWidth="1" strokeDasharray="3 3" />
            <g fontFamily="IBM Plex Mono, monospace" fontSize="10" letterSpacing="1">
              <text x="30" y="236" fill="rgb(var(--s-ink-2))">ITEM 1 · FOUND</text>
              <text x="170" y="236" fill="rgb(var(--s-red))">ITEM 2 · NOT FOUND</text>
            </g>
            <path d="M262 104 300 70h14" fill="none" stroke="rgb(var(--s-red))" strokeWidth="1" />
            <text x="303" y="64" fontFamily="IBM Plex Mono, monospace" fontSize="12" fill="rgb(var(--s-red))">?</text>
          </svg>
        </Card3D>
      </main>
    </SiteScope>
  );
}
