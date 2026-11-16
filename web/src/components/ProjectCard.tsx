import { Link } from "react-router-dom";
import { Box, CircleAlert, CircleCheck, Clock } from "lucide-react";
import type { Project } from "@/lib/types";
import { ago } from "@/lib/format";
import { Badge } from "./ui";

/** views.png is a 2×2 grid (ISO top-left); show only the ISO quadrant. */
export function IsoThumb({ src }: { src: string }) {
  return <img src={src} alt="" loading="lazy" className="absolute left-0 top-0 max-w-none transition group-hover:scale-[1.02]"
    style={{ width: "200%", height: "200%", transformOrigin: "0 0" }} />;
}

export function ProjectStatus({ p }: { p: Project }) {
  if (!p.builds) return <Badge><Clock className="h-3 w-3" />No builds yet</Badge>;
  if (p.last_status?.ok) return <Badge tone="success"><CircleCheck className="h-3 w-3" />Verified</Badge>;
  return <Badge tone="danger"><CircleAlert className="h-3 w-3" />Checks failing</Badge>;
}

export default function ProjectCard({ p }: { p: Project }) {
  const bbox = p.last_status?.fingerprint?.bbox;
  return (
    <Link to={`/app/projects/${p.id}`} className="card group flex flex-col overflow-hidden transition hover:-translate-y-0.5 hover:shadow-pop">
      <div className="viewport-bg relative flex aspect-[4/3] items-center justify-center overflow-hidden border-b border-border">
        {p.thumbnail ? <IsoThumb src={`${p.thumbnail}?v=${p.last_status?.build_id ?? 0}`} />
          : <Box className="h-10 w-10 text-muted/50" />}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0"><div className="truncate text-sm font-semibold">{p.name}</div>
            <div className="truncate text-xs text-muted">{p.last_status?.material ?? (p.description || "—")}</div></div>
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 text-xs text-muted">
          <ProjectStatus p={p} />
          <span>{bbox ? `${bbox.map(n => Math.round(n)).join(" × ")} mm` : ""}</span>
        </div>
        <div className="text-[11px] text-muted">Updated {ago(p.updated_at)} · {p.builds} build{p.builds === 1 ? "" : "s"}</div>
      </div>
    </Link>
  );
}
