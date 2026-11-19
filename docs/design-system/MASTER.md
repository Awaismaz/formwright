# Formwright public website: the "Sheet" design system

Canonical design system for the public website: landing, pricing, why, legal, the auth pages, onboarding, 404 and the
share view. The signed-in app (`/app/*`) keeps its own SOLIDWORKS-like tokens (`docs/BRAND.md`); nothing here changes
them. Code: `web/src/components/landing/site.css` (tokens and primitives) and `web/src/components/landing/site.tsx`
(React primitives). Written 2026-11-19 by working through the UI UX Pro Max workflow by hand from its tables (its
Python scripts were not run on this machine; see `docs/reports/site-revamp.md`).

## 1. The product, and what follows from it

- **Product:** an AI-native mechanical CAD SaaS. Users are mechanical engineers, CAD modellers and draftsmen at
  consultancies, machine shops and product firms. They read drawings all day and distrust marketing.
- **Consequence:** the site speaks their visual language. Everything is an engineering drawing: sheet grid, zone
  numbers, dimension lines, feature control frames, BOM balloons, title blocks, section hatching, phantom lines,
  third-angle projection symbol. The 3D on the page is real Formwright geometry (GLB exported from the exact models).
- **Avoid on purpose:** the warm cream and terracotta palette, centred heroes over gradient blobs, bento grids,
  glow, glass, "AI sparkle" iconography and AI copywriting tics (long dashes, "not X, but Y", "seamless", "unlock").

## 2. Choices from the skill's tables, with reasons

| Decision | Table rows used | Why |
|---|---|---|
| Style: **Swiss Modernism 2.0** grid discipline, with **3D Product Preview** for the parts | `styles.csv` 50, 1, 64 | A rational grid, one vibrant accent and real rotatable parts suit a precision tool. |
| Rejected styles | `styles.csv` 39/53 (Bento), 43 (AI-Native UI), 10 (Aurora), 3 (Glassmorphism), 41/51 (Cyberpunk, HUD) | These read as generic AI SaaS or sci-fi; the brief rules them out. |
| Product profile | `products.csv` 51 Construction/Architecture ("Grey + safety orange + Blueprint Blue, blueprint aesthetic"), 81 Developer Tool | Closest rows to mechanical CAD. We keep blueprint blue and the safety colour, but move from safety **orange** to safety **yellow** (ISO 3864 / machine-guard yellow) to stay well clear of the terracotta family. |
| Palette base | `colors.csv` 51 (industrial grey + safety accent) | Cool industrial greys for paper, deep cyanotype for the dark theme. |
| Type | `typography.csv` 9 Developer Mono (JetBrains Mono + IBM Plex Sans), 44 (Archivo) | Plex Sans has engineering heritage and reads well at 16 px; **Archivo** at 110 to 125 % width and weight 800 gives machine-nameplate headlines; **IBM Plex Mono** (same family as the body, instead of JetBrains) does all annotations. |
| Landing pattern | `landing.csv` 3 Product Demo + Features, 10 Scroll-Triggered Storytelling, 29 Interactive 3D Configurator | Hero shows the product working (the Design Office building PG-5), a sticky chapter assembles a real gearbox as you scroll, then feature views. |
| Rules applied | `references/quick-reference.md` sections 1 to 7, `ux-guidelines.csv`, `stacks/react.csv` | Contrast, focus, 44 px targets, reduced motion, CLS, lazy loading, route splitting. |

## 3. Tokens (CSS custom properties on `.fw-site`)

| Token | Paper (light) | Blueprint (dark) | Use |
|---|---|---|---|
| `--s-sheet` | `#F3F5F7` | `#08162E` | page |
| `--s-sheet-2` | `#E8ECF1` | `#0C1E3C` | alternate bands |
| `--s-slab` | `#FBFCFD` | `#0D2244` | plates, cards, inputs |
| `--s-ink` | `#0C1016` | `#ECF2FA` | text, strong lines |
| `--s-ink-2` | `#475260` (7.4:1 on sheet) | `#A4B6D0` (8:1) | secondary text |
| `--s-rule` / `--s-rule-2` | `#CBD3DC` / `#7B8898` (3.3:1) | `#243E68` / `#5674A4` | hairlines / meaningful lines |
| `--s-bp` | `#1642C4` (7.7:1) | `#7EB2FF` | drafting blue: dimensions, links, numbers |
| `--s-hi` | `#FFC400` | `#FFCC1A` | safety yellow: primary keys, highlights. Never text on paper. |
| `--s-red` | `#C82424` | `#FF7062` | redline: phantom parts, "not found", sparingly |
| `--s-print` | `#091833` | `#040E1E` | blueprint bands (notes, footer, office board) |
| `--s-pass` | `#16804A` | `#5CD692` | pass ticks |

The site maps the app tokens (`--bg`, `--panel`, `--text`, `--muted`, `--primary`, ...) onto these inside `.fw-site`,
so shared components (inputs, fields, the 3D viewer) follow the sheet. Tailwind names: `sheet sheet2 slab ink ink2
rule rule2 bp bpsoft hi redline print pass`; variant `sd:` = site dark. The theme is the visitor's choice (Paper /
Blueprint switch, `localStorage fw.site.theme`), else the OS preference, and is separate from the app theme.

## 4. Type

| Role | Face | Size |
|---|---|---|
| Display (`.s-display`) | Archivo 800, 118 % wide, uppercase, line-height .9 | 40 to 118 px (`clamp` by breakpoint) |
| Section titles (`.s-h2`) | Archivo 750, 110 % wide, sentence case | 28 to 52 px |
| Body | IBM Plex Sans 400/500/600 | 15.5 to 19 px, line-height 1.6 |
| Annotation (`.s-anno`) | IBM Plex Mono 500, uppercase, +0.12 em | 10 to 12.5 px, labels only |

Fonts are self-hosted (`web/public/fonts`, OFL, latin subsets, `font-display: swap`) so the site makes no
third-party requests and stays inside the CSP.

## 5. Primitives (all in `site.tsx`, used by every page in scope)

- **`Button3D`**: a solid-modelled key. Chamfered face (`clip-path`) over a visible side face, 1.5 px edge, milled
  texture, engraved label. Hover lifts 1.5 px, press travels down to the side face (transform only). Finishes:
  `hi` (safety-yellow anodised, primary) and `steel` (bead-blasted steel; blueprint steel in dark). Sizes xs to lg
  (32 to 56 px tall plus depth; touch targets 44 px or more except the xs theme rocker at 35 px, above the 24 px WCAG
  minimum). `pressed` makes a toggle that stays down (`aria-pressed`). `KeyButton` is a drop-in for the app's
  `Button` props.
- **`Card3D`**: a machined plate. Two chamfered corners, a 1 px edge and a hatched cut face showing its thickness
  (the section-cut replaces drop shadows). Options: `screws` (two screw heads, used on at most one or two plates per
  page), `hi` (ink edge), `lift` (hover lift for links), `flat`.
- **`Badge3D`**: a stamped metal tag with a punched hole; `live` (green hole), `hi` (yellow).
- **`Dim`**: a dimension line with extension lines and arrowheads; draws in on load or on reveal.
- **`Fcf`**: a GD&T feature control frame used as the page eyebrow.
- **`SectionHead`**: zone number, kicker, a leader to the margin, then the title.
- **`Zones`**, **`ThirdAngle`**, **`PositionSymbol`**, `.s-balloon`, `.s-tb` (title block), `.s-hazard` (one
  machine-guard stripe per page at most), `.s-grid` (5 mm / 25 mm sheet grid), `.s-conv` (hatched graphite for
  "conventional" in charts, so it differs from blue by pattern as well as colour).
- **`Crosshair`**: the drafting cursor in the landing hero, with a live X/Y readout in millimetres. Fine pointers
  only; off under reduced motion.
- **3D:** `LazyScene` / `PartScene` (three.js) load only near the viewport, render only while visible, accept a
  `poster` (SVG line drawing) shown while loading, without WebGL and on low-end devices (2 cores or fewer, under
  2 GB), and take `turn` and `zoom` that can be driven by scroll.

## 6. Motion

- Headline lines rise in once (0.8 s, staggered 0.1 s). Dimension lines and section leaders draw in (0.9 s).
- Scroll: `Reveal` (IntersectionObserver) for sections; `useScrollProgress` (IntersectionObserver plus one
  requestAnimationFrame per scroll frame, passive listeners, no layout writes) drives the sticky exploded gearbox
  (parts seat group by group in the Design Office's order, the parts list ticks off, the camera closes in) and the
  gear that turns on the Why page.
- Keys: 130 ms press, transform only. No glow, no parallax blobs, no infinite decorative loops.
- `prefers-reduced-motion`: every animation settles to its final state; the sticky section unpins and shows a still
  exploded view with the full parts list; 3D scenes render one still frame.

## 7. Layout

- Container 1240 px (1192 px content), 16 px gutters on phones, 24 px from 640 px. Breakpoints 420 / 640 / 768 / 1024
  / 1280. No horizontal scroll at 390 px (checked).
- Asymmetric, left-aligned compositions; numbered sections (01 to 09) like zones on a sheet; dark blueprint bands
  separate chapters.

## 8. Copy rules

Short, concrete, engineer to engineer. No em dash or en dash anywhere (enforced by `web/src/noLongDashes.test.ts`).
Ranges read "150 to 250". Honesty: only claim what exists; integrations are verified neutral files today with native
bridges "next"; never "validated" or "ready for manufacture"; modules show their catalog status.

## 9. Pre-delivery checklist (from `references/pro-rules.md`, web-adapted)

- [x] No emoji icons; one icon family (lucide, 1.6 stroke) plus drawn SVG symbols.
- [x] Official product marks only from the founder-supplied files, unaltered, on a white tile.
- [x] Press states do not shift layout (transforms only).
- [x] Semantic tokens only; no per-screen hex outside the dark blueprint bands and the 3D viewport.
- [x] Body text 4.5:1 or better in both themes; meaningful lines 3:1.
- [x] Focus visible on every control (2 px drafting blue, 3 to 4 px offset); skip link on marketing pages.
- [x] Targets 44 px or more (xs rocker 35 px, above WCAG 2.2's 24 px).
- [x] Reduced motion honoured everywhere; sticky story unpins.
- [x] 390 px: no overflow; 1440 px checked; light and dark both checked.
- [x] CLS under 0.1 on every page (measured, see the report).
- [x] Forms keep visible labels, inline errors and password-manager-friendly inputs (unchanged logic).
