/** Progressive Web App wiring (UX-022): service worker registration with a "New version available" update flow,
 * and the install state (captured beforeinstallprompt, installed detection) for the Install app offer. */
import { useSyncExternalStore } from "react";
import { toast } from "sonner";
import { detectPlatform, installMode, isStandalone, type InstallMode, type InstallPlatform } from "./install";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
let installedNow = false;
const listeners = new Set<() => void>();
const emit = () => { snapshot = compute(); listeners.forEach(l => l()); };

const standaloneQuery = () => (typeof matchMedia === "function" ? matchMedia("(display-mode: standalone)") : null);

export interface InstallState { mode: InstallMode; platform: InstallPlatform }
function compute(): InstallState {
  if (typeof navigator === "undefined") return { mode: "unavailable", platform: "desktop" };
  const platform = detectPlatform(navigator.userAgent, navigator.maxTouchPoints ?? 0);
  const standalone = installedNow || isStandalone(!!standaloneQuery()?.matches, (navigator as Navigator & { standalone?: boolean }).standalone);
  return { mode: installMode({ platform, standalone, hasPrompt: !!deferred }), platform };
}
let snapshot: InstallState = compute();

export function useInstall(): InstallState & { promptInstall: () => Promise<"accepted" | "dismissed" | "unavailable"> } {
  const s = useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => snapshot,
    () => snapshot,
  );
  return { ...s, promptInstall };
}

export async function promptInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  const e = deferred;
  if (!e) return "unavailable";
  deferred = null; // a prompt event can be used once
  await e.prompt();
  const { outcome } = await e.userChoice;
  if (outcome === "accepted") installedNow = true;
  emit();
  return outcome;
}

let started = false;
export function initPwa(): void {
  if (started || typeof window === "undefined") return;
  started = true;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e as BeforeInstallPromptEvent; emit(); });
  window.addEventListener("appinstalled", () => { deferred = null; installedNow = true; emit(); });
  standaloneQuery()?.addEventListener?.("change", emit);
  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    // after first paint, so the worker's precache download never competes with the app's own start-up
    if (document.readyState === "complete") void register();
    else window.addEventListener("load", () => void register(), { once: true });
  }
}

let reloading = false;
async function register(): Promise<void> {
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    const offer = (w: ServiceWorker) => {
      toast("New version available", {
        id: "fw-update", duration: Infinity, description: "Reload to get the latest Formwright.",
        action: { label: "Reload", onClick: () => { reloading = true; w.postMessage({ type: "SKIP_WAITING" }); } },
      });
    };
    // a worker already waiting (an update downloaded while the old tabs were open)
    if (reg.waiting && navigator.serviceWorker.controller) offer(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const w = reg.installing;
      w?.addEventListener("statechange", () => {
        // installed + an existing controller = an update (on first install there is no controller: nothing to say)
        if (w.state === "installed" && navigator.serviceWorker.controller) offer(w);
      });
    });
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (reloading) { reloading = false; location.reload(); }
    });
    // look for a new version every hour, and whenever the app comes back to the foreground
    setInterval(() => void reg.update().catch(() => {}), 3_600_000);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") void reg.update().catch(() => {}); });
  } catch { /* no worker (private mode, old browser): the app works as a plain website */ }
}

/** navigator.onLine as React state, for the in-app "You're offline" banner. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    (l) => { addEventListener("online", l); addEventListener("offline", l); return () => { removeEventListener("online", l); removeEventListener("offline", l); }; },
    () => navigator.onLine,
    () => true,
  );
}
