import { Badge3D, Card3D, SectionHead } from "./site";
import { Reveal } from "./motion";

/**
 * "Opens where you already work": the desktop/cloud CAD and 3D tools that read Formwright's verified exports. Each tool
 * shows its product mark from `web/public/landing/logos/<slug>.(svg|png)` (square symbol, picked up at build time); a
 * tool without one keeps a monogram tile. Marks are the owners' trademarks (footnote below).
 * Honest wording (PD-88): exports open in these tools today; native bridges are on the way and say so.
 */

const DROPPED = import.meta.glob("/public/landing/logos/*.{svg,png}", { query: "?url", import: "default", eager: true }) as Record<string, string>;
const logoFor = (slug: string) => {
  const hit = Object.keys(DROPPED).find(k => k.endsWith(`/${slug}.svg`) || k.endsWith(`/${slug}.png`));
  return hit ? hit.replace(/^\/public/, "") : null;
};

type Tool = { slug: string; name: string; mono: string; via: string; hue: number };
export const CAD_TOOLS: Tool[] = [
  { slug: "solidworks", name: "SOLIDWORKS", mono: "SW", via: "STEP AP214 / AP242", hue: 214 },
  { slug: "creo", name: "Creo", mono: "Cr", via: "STEP", hue: 152 },
  { slug: "inventor", name: "Autodesk Inventor", mono: "In", via: "STEP", hue: 36 },
  { slug: "fusion", name: "Autodesk Fusion", mono: "Fu", via: "STEP, 3MF", hue: 22 },
  { slug: "onshape", name: "Onshape", mono: "On", via: "STEP", hue: 200 },
  { slug: "nx", name: "Siemens NX", mono: "NX", via: "STEP", hue: 178 },
  { slug: "catia", name: "CATIA", mono: "Ca", via: "STEP", hue: 228 },
  { slug: "solid-edge", name: "Solid Edge", mono: "SE", via: "STEP", hue: 140 },
  { slug: "freecad", name: "FreeCAD", mono: "Fc", via: "STEP", hue: 0 },
  { slug: "blender", name: "Blender", mono: "Bl", via: "GLB, OBJ, STL", hue: 28 },
];

function Tile({ tool, i }: { tool: Tool; i: number }) {
  const logo = logoFor(tool.slug);
  return (
    <Reveal delay={0.035 * i} className="min-w-0">
      <Card3D className="h-full" inner="flex items-center gap-3 p-3.5">
        {logo ? (
          <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-white p-1 ring-1 ring-ink/20"><img src={logo} alt="" width={36} height={36} loading="lazy" className="h-9 w-9 object-contain" /></span>
        ) : (
          <span className="flex h-11 w-11 shrink-0 items-center justify-center text-[13px] font-bold text-white ring-1 ring-ink/30"
            style={{ background: `linear-gradient(140deg, hsl(${tool.hue} 32% 42%), hsl(${tool.hue} 38% 26%))` }} aria-hidden="true">{tool.mono}</span>
        )}
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-ink">{tool.name}</div>
          <div className="s-anno truncate text-[10px] text-ink2">{tool.via}</div>
        </div>
      </Card3D>
    </Reveal>
  );
}

export default function CadTools() {
  return (
    <section id="cad" className="scroll-mt-24 border-b border-ink/80">
      <div className="mx-auto grid max-w-[1240px] gap-12 px-4 py-20 sm:px-6 sm:py-24 lg:grid-cols-[minmax(0,.85fr)_minmax(0,1.35fr)] lg:items-start">
        <Reveal>
          <SectionHead n="04" kicker="Interfaces" title="Opens where your team already works."
            body="Every model exports as verified STEP, STL and 3MF, read back and compared before you download it. Open it in SOLIDWORKS, Creo, Inventor, Fusion, Onshape, NX, CATIA, Solid Edge, FreeCAD or Blender and keep going." />
          <div className="mt-8 border-t border-ink/70">
            {[
              ["Today", "Verified neutral files: STEP AP214 and AP242, STL, 3MF. A SOLIDWORKS export pack with a parameters table."],
              ["Next", "Native bridges that rebuild the feature tree inside your CAD, starting with SOLIDWORKS."],
            ].map(([k, v], i) => (
              <div key={k} className="grid grid-cols-[84px_1fr] gap-4 border-b border-rule py-4">
                <span>{i === 0 ? <Badge3D tone="live">{k}</Badge3D> : <Badge3D>{k}</Badge3D>}</span>
                <p className="text-[15px] leading-relaxed text-ink">{v}</p>
              </div>
            ))}
          </div>
        </Reveal>
        <div>
          <ul className="grid grid-cols-1 gap-3 min-[460px]:grid-cols-2 xl:grid-cols-3" aria-label="CAD and 3D tools that open Formwright exports">
            {CAD_TOOLS.map((t, i) => <li key={t.slug} className="min-w-0"><Tile tool={t} i={i} /></li>)}
            <li className="flex min-h-[72px] items-center border border-dashed border-rule2 px-4 text-[14px] text-ink2 min-[460px]:col-span-2 xl:col-span-2">
              Plus any tool that reads STEP, STL or 3MF.
            </li>
          </ul>
          <p className="mt-5 text-[12px] text-ink2">Product names and marks are trademarks of their respective owners; no endorsement implied.</p>
        </div>
      </div>
    </section>
  );
}
