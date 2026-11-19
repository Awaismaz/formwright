# Public website revamp (branch `wip/site-revamp`)

Founder's request (2026-11-19): revamp the landing page and the rest of the public website with the UI UX Pro Max
skill, highly creative, not "Claude like", no long dashes anywhere; then (same evening) real 3D objects, a
solid-modelled mechanical theme for every control, scroll animations, neat and bug-free.

## Direction, and why

**An engineering drawing you can scroll.** Mechanical engineers read drawings all day, so the site is one: a 5 mm /
25 mm sheet grid, zone numbers along the header, numbered sections like zones, dimension lines that draw themselves,
a GD&T feature control frame as the eyebrow, BOM balloons, title blocks (the hero's live view, the CTA "Drawn: you ·
Checked: Formwright · Approved: your engineer", and the footer with projection symbol, units, scale and sheet), section
hatching instead of drop shadows, phantom lines on the 404, a drafting crosshair with a live X/Y readout in mm.

- **Two themes that are both intentional:** *Paper* (cool drafting paper, ink, drafting blue) and *Blueprint*
  (white linework on cyanotype). A Paper / Blueprint rocker in the header; it follows the OS until chosen and never
  touches the visitor's app theme.
- **Safety yellow, not orange.** The skill's closest product row (Construction/Architecture) suggests blueprint blue +
  safety orange; we moved to machine-guard yellow to stay well away from the cream/terracotta look.
- **Type with character:** Archivo at 118 % width, weight 800, uppercase, for nameplate headlines ("WRITE THE BRIEF.
  GET THE SOLID."); IBM Plex Sans for body; IBM Plex Mono for every annotation.
- **Solid-modelled controls:** `Button3D` keys have a chamfered face over a visible side face, milled texture and an
  engraved label; they lift on hover and travel down on press. `Card3D` plates have two chamfered corners and a
  hatched cut face showing their thickness. `Badge3D` is a stamped tag with a punched hole. Inputs are milled pockets.
  All transform-only, so presses never move layout.
- **Real 3D, honestly labelled:** the existing Design Office hero (PG-5 planetary gearbox with real kinematics) is
  reframed as "View 1" on the sheet; a new sticky chapter assembles the same 29 real parts group by group as you
  scroll while the parts list ticks off; the Why page has a Toolbox spur gear that turns with the scroll; the auth
  pages show the flange turning on blueprint. Every scene lazy-loads near the viewport, renders only on screen, has
  an SVG line-drawing poster (loading, no WebGL, devices with 2 cores or fewer or under 2 GB) and a still frame under
  reduced motion.
- **Copy:** short, concrete, engineer to engineer; removed AI tics ("not X, but Y", long dashes); ranges read "to".

## Skill tables that informed it

UI UX Pro Max was used as reference data, by hand: `SKILL.md` workflow and priority table; `styles.csv` rows 50
(Swiss Modernism 2.0), 1 and 64 (3D Product Preview), and rejected 39/53 (Bento), 43 (AI-Native UI), 10 (Aurora),
3 (Glassmorphism), 41/51; `products.csv` 51 and 81; `colors.csv` 51; `typography.csv` 9 and 44; `landing.csv` 3, 10
and 29; `references/quick-reference.md` sections 1 to 7 and the pre-delivery checklist in `references/pro-rules.md`.
Its Python scripts were **not run**: the permission system blocked them at the start, and blocked them again after
the master's later message allowed them; I did not work around that. Full write-up: `docs/design-system/MASTER.md`.

## What changed (files)

- New: `web/src/components/landing/site.css`, `site.tsx` (tokens and primitives: `SiteScope`, `ThemeSwitch`,
  `Button3D`, `KeyButton`, `Card3D`, `Badge3D`, `Dim`, `Fcf`, `SectionHead`, `Zones`, `ThirdAngle`, `Crosshair`,
  `useScrollProgress`), `ExplodeOnScroll.tsx`, `web/public/fonts/*` (OFL, latin subsets, README), `web/src/noLongDashes.test.ts`,
  `docs/design-system/MASTER.md`.
- Rebuilt: `layouts/MarketingLayout.tsx` (header, mobile menu, skip link, title-block footer), `layouts/AuthLayout.tsx`,
  `pages/marketing/Landing.tsx`, `Pricing.tsx` (own plan plates; shared `PlanCards` untouched), `Legal.tsx`, `pages/NotFound.tsx`.
- Restyled: `Why.tsx` (+ `why/Calculator.tsx`: "conventional" is now hatched graphite, not copper), `CadTools.tsx`,
  `Showcase.tsx`, `OfficeBoard.tsx`, `AppDevices.tsx`, `hero/OfficeHero.tsx` (frame only), `pages/auth/*`, `ShareView.tsx`.
- `PartScene.tsx`: new `turn`, live `zoom`, `poster` and per-part `fitExplode`; **bug fixed**: a kick between frames
  could make the frame step negative, and the easing then diverged (the camera flew off and the canvas went blank).
  `LazyScene.tsx`: poster while waiting and on low-end devices.
- Shared files touched: `web/tailwind.config.js` (adds site colour names, `display/body/anno` fonts and an `sd:`
  variant; no existing token changed). `web/index.html` ends unchanged: Google Fonts was tried and removed because the
  CSP blocks third-party stylesheets. App tokens in `styles.css` are unchanged; the site maps them inside
  `.fw-site` only.

## Honesty

- Integrations: "Every model exports as verified STEP, STL and 3MF ... Open it in SOLIDWORKS, Creo ..."; a "Today /
  Next" list says native bridges that rebuild the feature tree are next (NCB-* backlog). AppDevices no longer says the
  native bridges run on your workstation. Auth panel: "Native bridges are on the way."
- Modules table shows each module's catalog status (Live, Live · beta, Preview) from `/api/billing/catalog`.
- "Never claim manufacturing validity" kept: "Approved: your engineer, always", "Sign-off stays human".
- Facts used are from the code and docs: 29 parts / 0 interferences / 5.00:1 (hero manifest and story), CHK-04 style
  checks described without counts, SOLIDWORKS export pack (CAD-070), 3MF (IO-004), Blender GLB/OBJ/STL (Mesh Studio).

## Verification

- `npx tsc --noEmit`: clean. `npx vitest run`: 22 files, 148 tests pass. `npx vite build`: clean
  (main bundle +8 KB raw, about +2.5 KB gzip; `PartScene` 6.9 KB, three.js stays in its lazy chunk).
- No-long-dash test: `web/src/noLongDashes.test.ts` covers `pages/marketing`, `pages/auth`, `components/landing`,
  `layouts/{MarketingLayout,AuthLayout}`, `pages/{NotFound,ShareView}` and itself (UTF escapes only).
- Puppeteer (puppeteer-core 25.18.1, headless Chrome with SwiftShader WebGL) on an isolated app at :8804, screenshots
  in `C:\Users\awais\AppData\Local\Temp\claude\ae5066db278ece3d\6657173d-006b-4ae9-a4dd-ffbf9518d104\scratchpad\fw-e2e-8804\`:
  - full pages at 1440 px, light and dark: `s3\`, `s4\` (landing), `s5\` (pricing, why, legal, login, signup), `s6\`
    (404, share error, signup, forgot, reset, verify, invite);
  - 390 px, light and dark: `m1\` (landing, pricing, why, legal, login, 404), `s4\landing-390-light-*`;
  - mid-scroll states of the exploded gearbox: `ex1\` (light 0/30/60/100 %), `ex2\` (390 px dark 0/50/100 %),
    `ex5\`/`ex7\` (after the camera fixes);
  - signed-in: `appshots\` (app home and Studio unchanged, real share link, landing signed in).
- Every page: 0 console errors (the share page with a bogus token logs the expected 404 for the API call),
  0 px horizontal overflow at 390 and 1440, **CLS 0.0 to 0.043** (landing 0.039 to 0.043, pricing 0.039, others under
  0.014; measured with a layout-shift observer while the page was walked).
- Timings on this machine (local server, headless): FCP 150 to 500 ms for most pages, landing 0.5 to 1.1 s (2.5 s on
  the very first cold load); DOMContentLoaded about 0.2 to 0.3 s. Scroll frame time through the 3D section in headless
  SwiftShader (software WebGL) was 117 ms median; that measures the CPU rasteriser, not a real GPU. The scene renders
  only while visible and only while something moves.

## Known limits

- Lighthouse was not run (no Lighthouse install; Performance API timings above instead).
- Real-GPU frame timing not measured here; headless uses software WebGL.
- The founder-supplied product marks are shown as-is on white tiles; permission to use them is still the founder's
  item from 2026-11-18.

## Parked decisions (defaults used; numbers are proposals, the master may renumber)

| PD | Decision | Default used | Revisit when |
|---|---|---|---|
| PD-88 | Integration wording | Honest: verified STEP/STL/3MF that open in the named tools today, native bridges labelled "Next". This overrides the 2026-11-18 "launch-state marketing, no coming soon labels" rule for this one claim, per the master's brief. | Founder prefers launch-state wording, or the SOLIDWORKS bridge (NCB-001..006) ships. |
| PD-89 | Website identity | "Sheet" system: engineering-drawing language, Paper and Blueprint themes, safety yellow + drafting blue, Archivo / IBM Plex. The app keeps its SOLIDWORKS-like theme and the logo mark is unchanged (copper facet kept). | Brand review, or the founder wants the app to share the site look. |
| PD-90 | Site theme vs app theme | Separate: Paper / Blueprint rocker on public pages, stored in `localStorage fw.site.theme`, OS preference until chosen. | Founder wants one theme setting across site and app. |
| PD-91 | Fonts | Self-hosted Archivo and IBM Plex (OFL, about 180 KB woff2, latin only) because the CSP blocks Google Fonts; precached by the service worker. | Non-latin markets, or a CDN/CSP change. |
| PD-92 | Hero and section copy | "Write the brief. Get the solid." and engineer-voice section titles (routing card, general notes, parts list, title block CTA). | Founder copy review. |
