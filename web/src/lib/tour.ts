import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { api, track } from "./api";

export const APP_TOUR: DriveStep[] = [
  { popover: { title: "Welcome to Formwright",
    description: "A 1-minute tour of your design workspace. You can restart it any time from Help." } },
  { element: "[data-tour=quickstart]", popover: { title: "Start here",
    description: "Describe a part in plain language, or drop a STEP file, a PDF drawing or a photo. The suggestions below are proven briefs to try.", side: "bottom" } },
  { element: "[data-tour=nav-projects]", popover: { title: "Projects",
    description: "Every part lives in a project: the model, its checks, revisions and exports. Search by name or by size, such as 120x80x10.", side: "right" } },
  { element: "[data-tour=nav-modules]", popover: { title: "Modules",
    description: "Drawing, manufacturability, engineering checks, 3D print prep, assemblies and renders all open straight on your part. Your trial includes every one.", side: "right" } },
  { element: "[data-tour=tokens]", popover: { title: "Tokens",
    description: "Design-agent runs use tokens: up to about 400 for a new part, usually far less for a change. Edits by hand are free. Every run shows a live meter and stops at your budget.", side: "bottom" } },
  { element: "[data-tour=help]", popover: { title: "Help is always here",
    description: "Guides for every module, keyboard shortcuts (try Ctrl+K) and a direct line to the team.", side: "bottom" } },
];

export const STUDIO_TOUR: DriveStep[] = [
  { element: "[data-tour=prompt]", popover: { title: "Describe your part",
    description: "Brief it like you'd brief an engineer: material, key dimensions, holes, fillets. The agent asks when something important is missing. The meter shows what the run costs as it works.", side: "top" } },
  { element: "[data-tour=viewer]", popover: { title: "Live 3D model",
    description: "Updates on every build. Orbit, switch views, section and measure. Select faces or edges to talk about them.", side: "left" } },
  { element: "[data-tour=checks]", popover: { title: "Verified, not guessed",
    description: "Every build is checked numerically: valid solid, dimensions, volume against a hand calculation, STEP round-trip and repeatability.", side: "left" } },
  { element: "[data-tour=command-manager]", popover: { title: "Model by hand",
    description: "Sketch, extrude, fillet, hole, pattern and more, like your desktop CAD. Hand edits are instant and free.", side: "bottom" } },
  { element: "[data-tour=feature-tree]", popover: { title: "Feature tree and history",
    description: "The tabs here hold the feature tree, parameters, revisions and files. Restore any revision without an AI call; download STEP and STL from Files.", side: "right" } },
  { element: "[data-tour=make]", popover: { title: "Make",
    description: "Open the drawing, manufacturability review, print prep or a render on this part.", side: "bottom" } },
];

export function runTour(steps: DriveStep[], name: string, onDone?: () => void) {
  // only steps whose target is on screen (phones hide the sidebar and some studio panels, UX-018)
  const present = steps.filter(s => { if (!s.element) return true; const el = document.querySelector(s.element as string); return !!el && el.getClientRects().length > 0; });
  track("tour_started", { name });
  const d = driver({
    showProgress: true, allowClose: true, popoverClass: "fw-tour", overlayOpacity: 0.45, stagePadding: 6,
    nextBtnText: "Next", prevBtnText: "Back", doneBtnText: "Finish", steps: present,
    onDestroyed: () => {
      const finished = !d.hasNextStep();
      track(finished ? "tour_step" : "tour_skipped", { name, at: d.getActiveIndex() ?? -1 });
      try { localStorage.setItem(`fw_tour_${name}`, "1"); } catch { /* ignore */ }
      // record completion first, so the checklist refreshed by onDone already shows it
      (name === "app" ? api.post("/api/tour/complete") : Promise.resolve()).catch(() => {}).finally(() => onDone?.());
    },
  });
  d.drive();
}

export function seenTour(name: string) {
  try { return localStorage.getItem(`fw_tour_${name}`) === "1"; } catch { return true; }
}
