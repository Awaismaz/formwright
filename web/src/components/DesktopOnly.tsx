import type { ReactNode } from "react";
import { Monitor } from "lucide-react";
import { DESKTOP, useMedia } from "@/lib/media";

/** Wraps anything that needs a desktop computer (local CAD plugins, a SOLIDWORKS/Blender bridge, anything that
 * installs software): on phones and tablets it shows a short "available on desktop" note instead (UX-018). */
export default function DesktopOnly({ what, children }: { what: string; children: ReactNode }) {
  const desktop = useMedia(DESKTOP);
  if (desktop) return <>{children}</>;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-dashed border-border p-4 text-sm" data-desktop-only>
      <Monitor className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
      <p className="text-muted"><b className="text-text">{what}</b>: available on desktop. This needs software installed on your computer.</p>
    </div>
  );
}
