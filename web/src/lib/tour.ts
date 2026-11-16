import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { api, track } from "./api";

export const APP_TOUR: DriveStep[] = [
  { popover: { title: "Welcome to Formwright 👋",
    description: "A 2-minute tour of your AI design workspace. You can restart it any time from Help." } },
  { element: "[data-tour=nav-projects]", popover: { title: "Projects",
    description: "Every design lives in a project: its conversation with the design agent, the model, checks, revisions and exports.", side: "right" } },
  { element: "[data-tour=quickstart]", popover: { title: "Start from a template",
    description: "Pick a proven starting prompt — bracket, shaft, flange, enclosure — or describe your own part from scratch.", side: "bottom" } },
  { element: "[data-tour=nav-modules]", popover: { title: "Modules",
    description: "Design Studio is live today. Drawings, manufacturing and engineering advisors are on the roadmap — preview them and join the early-access list.", side: "right" } },
  { element: "[data-tour=tokens]", popover: { title: "Tokens",
    description: "AI work is metered in tokens. Your trial includes 300. You always see the cost of each run, and you can top up or upgrade from Billing.", side: "bottom" } },
  { element: "[data-tour=checklist]", popover: { title: "Your getting-started checklist",
    description: "Follow these steps to get from first idea to a verified, exportable part.", side: "left" } },
  { element: "[data-tour=help]", popover: { title: "Help is always here",
    description: "Guides, keyboard shortcuts (try Ctrl+K), and a direct line to the team.", side: "right" } },
];

export const STUDIO_TOUR: DriveStep[] = [
  { element: "[data-tour=prompt]", popover: { title: "Describe your part",
    description: "Write requirements like you'd brief an engineer: material, key dimensions, holes, fillets. The agent asks if something important is missing.", side: "top" } },
  { element: "[data-tour=viewer]", popover: { title: "Live 3D model",
    description: "Updates on every build. Orbit, switch views, section and measure. The mesh comes from the exported STEP file.", side: "left" } },
  { element: "[data-tour=checks]", popover: { title: "Verified, not guessed",
    description: "Every build is checked numerically: valid solid, dimensions, volume against a hand calculation, STEP round-trip and repeatability.", side: "left" } },
  { element: "[data-tour=studio-tabs]", popover: { title: "Revisions & files",
    description: "Every build becomes a revision you can restore without an AI call. Download STEP and STL from Files.", side: "bottom" } },
];

export function runTour(steps: DriveStep[], name: string, onDone?: () => void) {
  const present = steps.filter(s => !s.element || document.querySelector(s.element as string));
  track("tour_started", { name });
  const d = driver({
    showProgress: true, allowClose: true, popoverClass: "fw-tour", overlayOpacity: 0.45, stagePadding: 6,
    nextBtnText: "Next", prevBtnText: "Back", doneBtnText: "Finish", steps: present,
    onDestroyed: () => {
      const finished = !d.hasNextStep();
      track(finished ? "tour_step" : "tour_skipped", { name, at: d.getActiveIndex() ?? -1 });
      if (name === "app") api.post("/api/tour/complete").catch(() => {});
      try { localStorage.setItem(`fw_tour_${name}`, "1"); } catch { /* ignore */ }
      onDone?.();
    },
  });
  d.drive();
}

export function seenTour(name: string) {
  try { return localStorage.getItem(`fw_tour_${name}`) === "1"; } catch { return true; }
}
