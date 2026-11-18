import { ArrowLeftRight, FileBox } from "lucide-react";
import { LogoMark } from "@/components/ui";
import { cx } from "@/lib/format";
import { Reveal } from "./motion";

/**
 * "Integrates with your CAD": the desktop/cloud CAD and 3D tools Formwright works with. We do not ship vendor logo
 * artwork (trademark licences needed); each tool gets our own monogram tile. To use an official mark once licensed,
 * drop `web/public/landing/logos/<slug>.svg` in place: the glob below picks it up at build time and the tile shows it.
 */

const DROPPED = import.meta.glob("/public/landing/logos/*.svg", { query: "?url", import: "default", eager: true }) as Record<string, string>;
const logoFor = (slug: string) => {
  const hit = Object.keys(DROPPED).find(k => k.endsWith(`/${slug}.svg`));
  return hit ? `/landing/logos/${slug}.svg` : null;
};

type Tool = { slug: string; name: string; mono: string; kind: string; hue: number };
export const CAD_TOOLS: Tool[] = [
  { slug: "solidworks", name: "SOLIDWORKS", mono: "SW", kind: "Parametric CAD", hue: 214 },
  { slug: "creo", name: "Creo", mono: "Cr", kind: "Parametric CAD", hue: 152 },
  { slug: "inventor", name: "Autodesk Inventor", mono: "In", kind: "Parametric CAD", hue: 36 },
  { slug: "fusion", name: "Autodesk Fusion", mono: "Fu", kind: "Cloud CAD / CAM", hue: 22 },
  { slug: "onshape", name: "Onshape", mono: "On", kind: "Cloud CAD", hue: 200 },
  { slug: "nx", name: "Siemens NX", mono: "NX", kind: "Parametric CAD", hue: 178 },
  { slug: "catia", name: "CATIA", mono: "Ca", kind: "Parametric CAD", hue: 228 },
  { slug: "solid-edge", name: "Solid Edge", mono: "SE", kind: "Parametric CAD", hue: 140 },
  { slug: "freecad", name: "FreeCAD", mono: "Fc", kind: "Open-source CAD", hue: 0 },
  { slug: "blender", name: "Blender", mono: "Bl", kind: "Render & mesh", hue: 28 },
];

function Tile({ tool, i }: { tool: Tool; i: number }) {
  const logo = logoFor(tool.slug);
  return (
    <Reveal delay={0.04 * i} className="group relative">
      <div className="card relative flex h-full items-center gap-3 overflow-hidden p-3.5 transition duration-300 hover:-translate-y-0.5 hover:shadow-pop">
        <span className="pointer-events-none absolute inset-y-0 -left-1/2 w-1/3 -skew-x-12 bg-gradient-to-r from-transparent via-white/40 to-transparent opacity-0 transition-all duration-700 group-hover:left-[120%] group-hover:opacity-100 dark:via-white/10" />
        {logo ? (
          <img src={logo} alt="" className="h-10 w-10 shrink-0 object-contain" />
        ) : (
          <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] text-[13px] font-bold tracking-tight text-white shadow-sm"
            style={{ background: `linear-gradient(140deg, hsl(${tool.hue} 32% 42%), hsl(${tool.hue} 38% 26%))` }} aria-hidden>
            <span className="absolute inset-[3px] rounded-[7px] ring-1 ring-white/20" />
            {tool.mono}
          </span>
        )}
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold">{tool.name}</div>
          <div className="truncate text-[11.5px] text-muted">{tool.kind}</div>
        </div>
      </div>
    </Reveal>
  );
}

export default function CadTools() {
  return (
    <section id="cad" className="relative scroll-mt-20 overflow-hidden border-b border-border bg-panel2/60">
      <div className="pointer-events-none absolute -right-40 -top-40 h-96 w-96 rounded-full bg-primary/10 blur-3xl" />
      <div className="relative mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[.9fr_1.3fr] lg:items-center">
        <Reveal>
          <div className="label">Integrations</div>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">Integrates with your CAD.</h2>
          <p className="mt-3 text-muted">
            Native integrations with SOLIDWORKS, Creo, Inventor, Fusion, Onshape, NX, CATIA, Solid Edge, FreeCAD and Blender. Design in
            Formwright, open the part where your team already works, and keep going. Every model also exports as verified STEP, STL and 3MF.
          </p>
          <div className="mt-6 flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-panel shadow-sm ring-1 ring-border"><LogoMark size={26} /></span>
            <span className="relative flex h-6 w-24 items-center overflow-hidden" aria-hidden>
              <span className="absolute inset-x-0 top-1/2 h-px bg-border" />
              <span className="fw-flow absolute top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-primary" />
              <span className="fw-flow absolute top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-accent [animation-delay:-1.1s]" />
              <ArrowLeftRight className="relative mx-auto h-4 w-4 bg-panel2 text-muted" />
            </span>
            <span className="flex h-11 items-center gap-1.5 rounded-xl bg-panel px-3 text-[13px] font-semibold shadow-sm ring-1 ring-border"><FileBox className="h-4 w-4 text-primary" />Your CAD</span>
          </div>
        </Reveal>
        <div className={cx("grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3")}>
          {CAD_TOOLS.map((t, i) => <Tile key={t.slug} tool={t} i={i} />)}
          <Reveal delay={0.4} className="col-span-2 flex items-center rounded-xl border border-dashed border-border px-3.5 py-3 text-[12px] text-muted sm:col-span-1 lg:col-span-2 xl:col-span-2">
            Plus any tool that reads STEP, STL or 3MF.
          </Reveal>
        </div>
      </div>
      <p className="relative mx-auto max-w-6xl px-4 pb-6 text-[11px] text-muted/80 sm:px-6">Product names are trademarks of their respective owners; no endorsement implied.</p>
    </section>
  );
}
