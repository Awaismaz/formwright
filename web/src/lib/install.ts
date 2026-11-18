/** Install-state helpers for the "Install app" offer (UX-022). Pure functions, so platform detection, standalone
 * detection and the dismissal memory are unit tested without a browser. The live wiring is in `lib/pwa.ts`. */

export type InstallPlatform = "ios" | "android" | "desktop";
/** What the install offer should do on this device right now. */
export type InstallMode =
  | "installed"   // already running as the installed app: offer nothing
  | "prompt"      // the browser gave us a beforeinstallprompt event: one tap installs
  | "ios"         // iPhone/iPad: no prompt API, show the Share → Add to Home Screen steps
  | "unavailable"; // not installable here (yet): offer nothing

export const DISMISS_KEY = "fw_install_dismissed";
/** A dismissed mobile banner stays hidden this long, then may offer once more. */
export const DISMISS_DAYS = 60;

export function detectPlatform(ua: string, maxTouchPoints = 0): InstallPlatform {
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  // iPadOS 13+ Safari reports a desktop Mac user agent; only the touch screen gives it away
  if (/Macintosh/i.test(ua) && maxTouchPoints > 1) return "ios";
  if (/Android/i.test(ua)) return "android";
  return "desktop";
}

/** Running as an installed app: the display-mode media query (all modern browsers) or iOS's navigator.standalone. */
export function isStandalone(displayModeStandalone: boolean, navigatorStandalone?: boolean): boolean {
  return displayModeStandalone || navigatorStandalone === true;
}

export function installMode(o: { platform: InstallPlatform; standalone: boolean; hasPrompt: boolean }): InstallMode {
  if (o.standalone) return "installed";
  if (o.hasPrompt) return "prompt";
  if (o.platform === "ios") return "ios";
  return "unavailable";
}

type Store = Pick<Storage, "getItem" | "setItem">;

export function isDismissed(store: Store | null | undefined, now = Date.now()): boolean {
  try {
    const v = store?.getItem(DISMISS_KEY);
    if (!v) return false;
    const at = Number(v);
    if (!Number.isFinite(at)) return true; // unknown value: respect the dismissal
    return now - at < DISMISS_DAYS * 86_400_000;
  } catch { return false; }
}

export function dismiss(store: Store | null | undefined, now = Date.now()): void {
  try { store?.setItem(DISMISS_KEY, String(now)); } catch { /* private mode: the banner just comes back */ }
}

/** The mobile banner shows only on phones/tablets that can install and haven't said no recently. */
export function showBanner(mode: InstallMode, platform: InstallPlatform, dismissed: boolean): boolean {
  return !dismissed && platform !== "desktop" && (mode === "prompt" || mode === "ios");
}
