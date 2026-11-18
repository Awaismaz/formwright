/** "Install app" offer (UX-022): one tap where the browser supports it (Chrome/Edge on Android and desktop), the
 * Share → Add to Home Screen steps on iPhone/iPad, and nothing once Formwright runs as the installed app. */
import { useState } from "react";
import { Download, Share, SquarePlus, X } from "lucide-react";
import { toast } from "sonner";
import { useInstall } from "@/lib/pwa";
import { dismiss, isDismissed, showBanner } from "@/lib/install";
import { cx } from "@/lib/format";
import { LogoMark, MenuItem, Modal } from "@/components/ui";

function safeStorage(): Storage | null { try { return localStorage; } catch { return null; } }

/** Returns what an "Install app" control needs: whether to show it, and what tapping it does. */
export function useInstallAction() {
  const { mode, platform, promptInstall } = useInstall();
  const [sheet, setSheet] = useState(false);
  const can = mode === "prompt" || mode === "ios";
  const run = async () => {
    if (mode === "ios") { setSheet(true); return; }
    const r = await promptInstall();
    if (r === "accepted") toast.success("Formwright is installed. Open it from your home screen or app list.");
  };
  const sheetEl = <IosInstallSheet open={sheet} onOpenChange={setSheet} />;
  return { can, mode, platform, run, sheetEl };
}

/** Steps for iOS Safari, which has no install prompt API. */
export function IosInstallSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const step = (n: number, text: React.ReactNode, art: React.ReactNode) => (
    <li className="flex items-center gap-3 rounded-lg border border-border bg-panel2 p-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-[12px] font-bold text-white">{n}</span>
      <span className="min-w-0 flex-1 text-[14px]">{text}</span>
      <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded-md border border-border bg-panel text-primary" aria-hidden="true">{art}</span>
    </li>
  );
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Install Formwright on this device"
      description="It opens full screen from your home screen, like an app. Your projects stay in your Formwright account.">
      <ol className="space-y-2.5" data-install-sheet>
        {step(1, <>Tap <b>Share</b> in Safari's toolbar.</>, <Share className="h-6 w-6" />)}
        {step(2, <>Scroll down and tap <b>Add to Home Screen</b>.</>,
          <span className="flex items-center gap-1 text-[8px] font-medium text-text"><SquarePlus className="h-5 w-5 text-primary" />Add</span>)}
        {step(3, <>Tap <b>Add</b>. Formwright appears on your home screen.</>,
          <span className="flex flex-col items-center gap-0.5"><LogoMark size={22} /><span className="text-[8px] font-medium text-text">Formwright</span></span>)}
      </ol>
      <p className="mt-3 text-[12.5px] text-muted">Using Chrome or another browser on iPhone? Open the Share menu from the address bar; the steps are the same.</p>
    </Modal>
  );
}

/** Item for the account menu. */
export function InstallMenuItem({ onSelect }: { onSelect: () => void }) {
  return <MenuItem icon={<Download />} onSelect={onSelect}>Install app</MenuItem>;
}

/** Small button for the sidebar footer (graphite chrome). */
export function InstallSidebarButton({ onClick, collapsed }: { onClick: () => void; collapsed?: boolean }) {
  return (
    <button onClick={onClick} data-install-app aria-label="Install app"
      className={cx("flex h-9 items-center gap-2 border-t border-white/[.06] text-[12px] text-chrome-muted hover:text-white",
        collapsed ? "justify-center" : "px-4")}>
      <Download className="h-4 w-4" />{!collapsed && "Install app"}
    </button>
  );
}

/** Dismissible banner on phones and tablets; a dismissal is remembered (lib/install DISMISS_DAYS). */
export function InstallBanner({ onInstall }: { onInstall: () => void }) {
  const { mode, platform } = useInstall();
  const [hidden, setHidden] = useState(() => isDismissed(safeStorage()));
  if (!showBanner(mode, platform, hidden)) return null;
  return (
    <div className="flex items-center gap-3 border-b border-border bg-panel px-3 py-2 lg:hidden" data-install-banner role="region" aria-label="Install the app">
      <LogoMark size={28} className="shrink-0" />
      <div className="min-w-0 flex-1 text-[13px] leading-tight">
        <div className="font-semibold">Install Formwright</div>
        <div className="text-muted">Full screen, from your home screen.</div>
      </div>
      <button onClick={onInstall} className="h-8 shrink-0 rounded bg-primary px-3 text-[13px] font-medium text-white">Install</button>
      <button onClick={() => { dismiss(safeStorage()); setHidden(true); }} className="-mr-1 shrink-0 rounded p-2 text-muted hover:text-text" aria-label="Dismiss install banner">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
