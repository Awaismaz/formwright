# Session Log

Newest first. Each entry: what was done, evidence, blocked, next item, decision needed.

---

## 2026-11-18 (p) — Design Office Phase 2 (branch wip/design-office): programs, Archie, board, roll-up, avatars

### Done
- CD-001 program data model + per-org storage and event log; CD-002 Archie planning (fw-plan block, metered, capped)
  with a deterministic standard planner fallback and an editable brief gate; CD-003 Jira-style board with swimlanes,
  drag, SSE live updates; CD-004 estimates, milestone progress, effort-weighted roll-up, critical path, ETA ranges;
  CD-005 office home, roster, reviews inbox, spend vs budget; CD-017 SVG avatars with role animations and states.
  Start on a ticket opens a Design Studio project with the brief (or an Assembly Studio doc for integration).
  Details and the Phase 3 hook list: `docs/reports/design-office.md`.

### Evidence
- `tests/test_office.py` 20 passed (no live AI); vitest `office/model.test.ts` 6 passed; tsc, vite build, ruff clean.
- Browser walkthrough on port 8794 with a throwaway data dir (puppeteer-core 25.18.1, standard planner only, no
  agent runs): home, plan review with edit, approve (14 tickets), real drag Ready → In design, every column state,
  drawer, tree (34 %, ETA 20 min–1 h), activity, roster, Start → Studio with brief in the chat box, reduced motion;
  0 console errors. Fixed from screenshots: lane header wrapping, glyphs spilling outside the badge.

### Not done / next
- No live Archie run yet (prompt quality on benchmark briefs unverified). Budget not enforced (CD-016). Avatars not
  yet in the Studio chat. Next: Phase 3 orchestrator (CD-006…009) on the hooks listed in the report.

### Decision parked
- PD-39 Design Office Phase 2 defaults.

---

## 2026-11-18 (o) — Punch list reconciliation; Design Office (Chief Designer) plan

### Done
- Reconciled the punch list against the code: 20 rows the Studio work had already delivered closed with evidence
  (holes/patterns, pockets, slots, fillets, params, determinism, revisions, brackets, revolve, shell/rib/draft, STEP
  import, sketch solver, feature history, viewer, tree, hand-off pack, agent loop); 8 Part-Spec-DSL rows marked
  **Superseded** by ADR-013; CAD-007 moved to In Progress. New status "Superseded" in the legend.
- Founder asked for AI assembly with automatic Toolbox / own-part picking and a Chief Designer that runs named
  specialist agents in parallel with a Jira-style board and rolled-up progress. Refined plan written:
  `docs/plans/CHIEF_DESIGNER.md` (interfaces-first skeleton + ICD, proxy bodies so assembly runs in parallel,
  change requests, reuse-before-design, critical-path priority, milestone-based progress, independent Checker,
  user as engineering manager, 11 named agents). Punch list: ASM-019, CD-001…CD-016; ASM-010 raised to P1.

### Decisions parked
PD-35 agent names, PD-36 concurrency/budget defaults, PD-37 mandatory gates.

### Next
Phase 1 of the plan: ASM-010 + ASM-019 (assembly from a description with automatic component picking).

## 2026-11-17 (n): Ruthless product audit, then fixes across every area

### Done
- **Audit** ([docs/reports/AUDIT_2026-11-17.md](reports/AUDIT_2026-11-17.md)). Four independent auditors, each with an
  isolated app (ports 8771-8774), headless Chrome and their screenshots read, every export opened, the calculators
  hand-checked. 18 P0, 54 P1, 49 P2, 20 ideas, grouped into six themes: wrong money story, wrong geometry that checks
  missed, fragile edits, honesty leaks, modules that feel like separate apps, and a long first run with the
  differentiators hidden. Area reports are in `docs/reports/audit/`.
- **Fixes** (four fixers in worktrees, branches `polish/{platform,make,ami,studio}`, merged in that order; each wrote
  `docs/reports/audit/<area>-fixes.md` with a status and evidence per finding):
  - **Platform** (32/34 fixed):
    - Runs are now charged per run. The SDK cost is cumulative per session, so follow-ups had been overcharged.
    - Run budget with a live meter; the balance never goes negative.
    - Trial raised to 1,000 tokens.
    - Honest landing page.
    - Trial access to every Live module.
    - 24 h email grace and a one-screen onboarding.
    - Dashboard start box and a "Next for this part" card.
    - Proration preview, notifications, project actions, phone layout.
  - **Make modules** (24/29 fixed plus partials):
    - Dimension placement fixed, and CHK-12 now catches misplaced dimensions.
    - Sign-offs are bound to the build, with distinct advice wording.
    - Drawings: editable title block, notes and tolerances.
    - Honest DFM, with ISO 273 clearance.
    - Calculation package PDF.
    - **Release gate "Issue Rev A"**: one staleness rule, carried in the handoff pack.
    - **Fix-it loop.**
  - **Assembly / Mesh / Image**:
    - Fastener grip fixed: bracket on plate gives grip 15, M5x25, 0 clashes.
    - Through-hole recognition fixed.
    - Mates follow dimension changes and can be repaired.
    - Mesh: no white clipping, a quick lane, monotonic progress, revision flags.
    - Image to CAD shows read and build costs and runs a preflight.
    - **Fasten these two parts**, **drawing round-trip check** and **assembly renders** built.
  - **Studio** (all 7 P0):
    - Exact one-edge picks.
    - Picks follow dimension changes.
    - The build worker matches replies by request id.
    - Plain error messages.
    - The Source view is superadmin-only.
    - Undo/redo, keyboard map, SOLIDWORKS mouse, ribbon overflow.
    - **Repair, don't block**, the **Hole Wizard** and **typed commands** built.
  - **Master**: after a successful checkout from a module's unlock page, "Open <module>" returns to the module on the
    part the user came from (STU-18; Make-tab lock and status came from the Make fixer).

### Evidence
- **Per-branch gates after merging main:**
  - platform: 357 passed plus paywall tests updated.
  - make: 393 passed, 1 failed under load.
  - ami: 418 passed.
  - studio: 427 passed, 1 failed under load.

  Each load failure passes alone (the machine ran 4 fixers at once).
- **Final gate on main:** see the commit "Docs: session log (n)" and the line below.
- **Walkthroughs:**
  - Platform: new user to a first part in 45 s warm for 45 tokens; Pro to Team preview $150.
  - Make: Rev A issued, then a change shows Draft since Rev A.
  - AMI: 0 clashes after insert; HOLE_D change keeps the mates.
  - Studio: one-edge fillet 9980.69 mm3; undo/redo; ribbon at 1366 px.

### Not done / known
- **Studio:**
  - STU-22 (Up To Next/Surface, second direction).
  - Partials STU-14/16/17/21/23/27/28.
  - IDEA 2 (agent fills the PropertyManager) is DS-035.
- **Make:** MAKE-05/06/14 partly done; MAKE-21 not done; IDEA-03/04/05 are MFG-024.
- **Platform:** PLT-29/34 partly done; IDEA-04/05 are PLT-017.
- **AMI:**
  - AMI-10/25 partly done.
  - Server-start warm-ups not done.
  - I3/I5 are ASM-018.
- **Windows race:** `status.json` read while it is being replaced can raise PermissionError (several readers). It needs one
  shared retrying reader. Also, the background export briefly writes a placeholder build id.

### Parked
PD-26 (plan allowances: founder call), PD-27..PD-34 (defaults used).

### Next
1. Founder: decide PD-26 (plan allowances vs measured run cost).
2. Shared retrying `status.json` reader.
3. STU-22 end conditions.
4. DS-035 agent fills the PropertyManager.
5. Server-start warm-ups (Blender, assembly worker).
6. Review each `*-fixes.md` "partly" list.

## 2026-11-17 (m): All eight modules Live; design variants; image-read fix

### Done
- **Merged and Live** (each report read, Make/Library entry added, punch list updated):
  - Design Studio DS-026: sketch tools, feature mirror, reference planes, draft/rib, sweep/loft, tree polish.
  - Image & Drawing to CAD (CAD-020..022): read before modelling, scale never guessed. The Library tab gets
    "From Drawing", and the Preview sample that estimated scale was removed.
  - Assembly Studio (ASM-001..008, IO-006, ASM-013 fastener auto-fit).
  - Mesh Studio (MSH-001/004/007/008/009/012: Blender product render studio, visualisation-labelled).
- **Design variants (DS-030 / O-3)**: named pinned revisions; compare modal with deltas vs current; switch without AI.
- **Founder-reported bug**: an Image & Drawing to CAD upload of a phone photo failed. Cause: the lossless PNG preview
  went to the agent, whose stream carries the image more than once per message and hit the SDK's 1 MB limit. Fix:
  the vision step gets a compact copy (≤1568 px, smaller of JPEG/PNG), and the SDK buffer is raised to 32 MB for
  vision and Studio chat (6 MB attachments had the same latent failure). Verified with the founder's own drawing:
  19 dimensions, views detected, 10 questions, scale held Undefined.

### Evidence
- Full suite on main with all modules: 352 passed + 1 stale assertion fixed (image2cad now 66/66); vitest 19/19;
  ruff, tsc and vite clean.
- Browser:
  - variants flange 6×M12 vs 8×M10, compare + switch, 0 errors;
  - the founder's JPG read on the isolated server;
  - catalog on 8765 lists all 8 modules Live.

### Parked
PD-22 (Studio modelling defaults), PD-23 (image2cad defaults), PD-24 (assembly defaults), PD-25 (Blender GPL
isolation for counsel; sandbox).

### Next
O-5 drawing check refinements; review per-module "Not done" lists for the highest-value gaps; agent-driven
variants ("explore 3 alternatives").

## 2026-11-16 (l): Wave 1 merged (Drawing, Manufacturing, Engineering Live), change notice, handoff pack, wave 2 launched

### Done
- **Merged wave-1 modules** after reading each report:
  - Drawing Studio (DRW-001..006, 010, 015, IO-007; CHK-12);
  - Manufacturing Advisor (MFG-001, 010, 013..018, 020; CHK-13);
  - Engineering Advisor (ENG-001..008, 010..012; 10 calculators vs Shigley/ISO examples).
  Dependency conflicts were resolved (pint + reportlab); details in `docs/reports/*.md`.
- **Change notice (DS-029 / O-2)**: each revision records why and who; a deterministic what-changed diff; notice
  with before/after views, CURRENT/SUPERSEDED stamp, copy-as-text and A4 print. The deferred 4-view render now
  attaches to its revision.
- **Shop handoff pack (PLT-013 / O-4)**: verified zip per revision with SHA-256 manifest; stale outputs left out;
  missing ones point to the module that makes them.
- Honesty copy: the tour and the landing FAQ now follow the catalog; a Live-but-locked module page says "What it
  does" and offers unlocking; the Files panel's drawing card links to the Live Drawing Studio.
- Wave 2 launched: Assembly Studio (with fastener auto-fit), Image & Drawing to CAD (ambiguity checklist),
  Mesh Studio (Blender product render studio). Agent brief gained "Shared machine rules".

### Evidence
- Full suite on merged main (before Drawing): 166 passed. After the Drawing merge: drawings + platform 32 passed;
  ruff, tsc and vite clean.
- New tests: `test_changes.py` (diff lines, API why/what, superseded), `test_handoff.py` (contents, manifest hashes,
  stale exclusion).
- Browser (port 8766, 0 errors):
  - notice for OD 150→160: +38,955.7 mm³ (= π(80²−75²)·16), +305.8 g at 7.85 g/cm³;
  - print layout one A4 page with before/after views;
  - handoff card with a current drawing and missing DFM; zip 182 KB.

### Parked
PD-19 (manufacturing defaults), PD-20 (engineering sign-off policy), PD-21 (drawing defaults).

### Next
Merge the Studio agent (DS-026) and wave 2 as they report; O-3 design variants once the Studio branch has landed.

## 2026-11-16 (k): Tree actions without AI, Find similar parts, 3D Print Prep merged, Make tab

Founder (between away periods): fix chat tables; make the feature tree useful (suppress, delete, ask agent);
"why does deleting a clean feature need AI?"; collapse the repeated "Updating the design" lines. Then: keep
building autonomously, research gaps, quality over quantity, no decisions until back.

### Done
- **Chat**: markdown tables, headings and italics render properly (escape-first); repeated steps collapse
  ("Updating the design · 5 edits").
- **Feature tree (DS-027)**: agent-built steps can be suppressed or deleted without AI. A delete is verified
  identical to the suppressed model, or else nothing is deleted. Click a feature to reference it in chat.
  Size/volume checks become informational while steps are suppressed or deleted.
- **Research → docs/OPPORTUNITIES.md** (sources cited): finding existing parts, change notices for the shop,
  variants, handoff packs, drawing checks.
- **Find similar parts (PLT-012 / O-1)**: shape signatures, similar-part ranking with reasons, search by size.
- **3D Print Prep merged and Live** (agent; PRN-001..006, IO-004). Its PP-17 check found that the Studio STL
  tolerance was relative (pipe flange deviated 0.023 mm). Fixed: absolute 0.01 mm deflection (IO-002).
- **Make tab (DS-028)** in the command bar opens Live downstream modules on the current part.
- Ops: the studio-e2e skill made agents share `fw-e2e` and `rm -rf` each other's data. Fixed with per-port
  folders and Windows-style FW_DATA_DIR; all agents told.

### Evidence
- Tests: tree suppress/delete (volumes exact), design_edit rules, search (unit + API), STL deviation
  (R100 cylinder sag 0.031 → 0.005 mm). The print agent's suite on its branch: 98 passed.
- Browser (isolated, port 8766, 0 errors each):
  - suppress Mounting holes → 91032.24 mm³ (= v0 + 4π·3.3²·10), restore → 89663.76;
  - delete via dialog → same volume, tree updated, base feature offers no delete;
  - chat shows "5 edits";
  - size search "120 x 80" → Mounting plate 100 % (exact);
  - Similar Parts on Flange DN100 → copy 100 %, Pipe Flange 79 %, DN150 "Same shape, scaled ×1.50" 48 %;
  - Make → 3D Print opens the flange directly.

### Parked
PD-15..18 (print process limits, permissions, upload retention, check numbering).

### Next
Merge Drawing, Manufacturing, Engineering and Studio agents as they report. Then wave 2 (Assembly,
Image & Drawing to CAD, Mesh Studio; Blender 5.3 is now installed). Then O-2 change notice and O-3 variants.

## 2026-11-16 (j): Design Studio: model from scratch, revolve, feature patterns; agents launched

Founder (going away): "keep building, finish Design Studio, then every remaining module one by one; park decisions";
then "start more agents for the other modules; this session stays the master for talking and orchestrating."

### Done (DS-024; DS-010 acceptance now met)
- Second workstation set up: uv installed, `uv sync`, `npm ci` → 82 passed, ruff, tsc, vite green (INF-001 done).
- **Model from scratch**: the first manual feature on an empty project creates a blank hand-modelled part
  (`result = None`). Front/Top/Right reference planes (plus offset) are in the sketch picker and as tree entries;
  the first boss or revolve creates the body; cuts/fillets etc. on an empty part are refused with a plain message.
- **Revolve / Revolved Cut** about a sketch centerline (new Centerline tool, construction toggle).
- **Extrude end conditions**: blind, mid plane, through all (cuts), reverse direction.
- **Feature patterns**: linear/circular pattern of any earlier boss, cut, revolve or hole; direction/axis from X/Y/Z
  or a picked edge, hole or face. Pattern fails cleanly if its source is suppressed.
- Ribbon: Extruded Boss/Base, Revolved Boss/Base, Extruded Cut, Revolved Cut open the sketcher; only body-dependent
  commands are disabled on an empty part. SOLIDWORKS names (Boss-Extrude1, Cut-Revolve1, LPattern1, CirPattern1).
- Viewer re-fits (same direction) when a rebuilt part would leave the window.
- Agent prompt knows about hand-modelled parts.

### Evidence
- `fw.apply_manual` smoke: revolve, mid-plane disc, through-all cut, circular and linear patterns all match hand
  formulas to about 1e-16.
- New tests `test_part_modelled_from_scratch_with_pattern`, `test_revolved_part_from_scratch` (analytic volumes,
  422 paths).
- Browser (isolated data dir, port 8766, puppeteer-core 25.17.0): empty project → Top plane → rectangle → boss
  40×20×10 = 8000 mm³ → Linear Pattern ×3 @ 20 mm = 80×20×10, 16000 mm³; Revolved Boss on Front plane → bushing
  28274.33 mm³ (= π·300·30) → Extruded Cut from Top +15 mm, through all → Circular Pattern ×6 → 26012.39 mm³
  (= hand calc). 0 console/page errors.
- Found by walkthrough and fixed: tree plane clicks ignored a pending Revolve/Cut command; viewer cropped a part that
  grew; a misleading "checks informational" note on hand-made parts.

### Next
Background agents in git worktrees: Design Studio continuation (DS-026), Drawing Studio, Manufacturing Advisor,
3D Print Prep, Engineering Advisor. This session merges and verifies their work.

## 2026-11-16 (i): Project skills for Claude Code

Founder request: "understand the project and add the relevant skills needed to get this app where it needs to be."

### Done (GOV-006)
- Nine project skills in `.claude/skills/`. Each is a recipe written from the code as of 74dfc5d, citing exact files
  and functions:
  - `formwright-ship`: gate, docs ritual, push
  - `formwright-review`: product, geometry and security checklist
  - `add-studio-feature`: every layer from `fw._op` and `validate_feature` through `types.ts`, FeatureManager,
    CommandManager and tests; drives DS-024
  - `build123d-kernel`: conventions, check table, determinism traps, OCP 7.9 pitfalls
  - `toolbox-component`: tables, analytic EXPECTED, VERSION bumps, matching
  - `design-agent`: prompt, session, scrub, block and runner contracts; AGT-015, EVAL-003
  - `graduate-module`: ADR-016 bar for Preview → Live; Drawing Studio starting points
  - `studio-e2e`: isolated `FW_DATA_DIR` run with its own superadmin; puppeteer template handling the CSRF header,
    pointer clicks, tours and WebGL
  - `dev-setup`: fresh-machine setup
- `.gitignore`: `.claude/` → `.claude/*` + `!.claude/skills/`, so skills are versioned and local settings stay local.
- `CLAUDE.md` lists the skills; `CONTEXT.md` machine notes cover the second workstation.

### Evidence
- `git check-ignore`: `settings.local.json` ignored, skills tracked. `node --check walkthrough.mjs` OK.
- Gate **not run**: this machine (`D:\AI CAD\formwright`) is a fresh clone with no uv, `.venv` or `web/node_modules`.
  This change touches only docs and skills, with no code.

### Findings
- Doc drift: VALIDATION.md defines CHK-09 as *metamorphic*, but the code uses CHK-09 for the imported-reference
  symmetric difference. The skills follow the code; VALIDATION.md needs a renumber (not done).
- The in-app agent uses `setting_sources=[]`, so these developer skills never reach the product agent.

### Not done / limits
- The e2e template has not been executed yet (needs the toolchain). Run it once with `dev-setup` + `studio-e2e`,
  then fix anything it gets wrong.

### Next
`dev-setup` on this machine (installing uv needs founder OK) → full gate → DS-024 with `add-studio-feature`
(revolve first) → Drawing Studio M1 slice with `graduate-module`.

## 2026-11-16 (h) — Exact STEP import, AI feature recognition, Studio layout

Founder feedback: STEP import behaved like a geometric SOLIDWORKS-style recogniser that often fails (a gear came back
with 100 unrecognised faces). Wanted: an exact equivalent solid that is always editable, unrecognised geometry kept as
an "Imported blank", resolved features listed for the AI; AI-based recognition (it should look at the part) for imports
and for existing models; tree without redundant add buttons; chat on the right, panel on the left, everything
collapsible; remove the project header bar.

### Done
- **Exact import** (DS-018): model = `fw.imported_blank(...)` = the imported solid itself + recognised features as
  tree entries (faces highlight). Recognised holes/patterns are parameters (Ø, PCD) edited by fill-and-recut on the exact
  body; at default values the model is identical to the file. The approximate "parametric draft" was removed.
- **Recognition** (DS-019): new rotational-repetition analysis (tolerance clustering + face orientation) recognises gear
  teeth → spur gear with teeth, module, tip/root Ø, bore; per-face classification so face ids match the viewer;
  recognition runs on any model (`/recognition/run`). **AI pass** (`/recognition/ai`): the agent reads the 4-view
  render + geometry data, returns a `fw-recognition` block → component card and feature names in the tree.
  Fixed a 50 s slowdown (shape area recomputed per face) → 1.3 s for a 1083-face gear.
- **Layout** (DS-025): header bar removed; feature panel left, agent right; panels + command bar collapsible.
- Agent prompt: imported parts are edited as solids (booleans/selections on the blank), never approximated.

### Evidence
- `pytest`: 82 passed; ruff clean; tsc + vite build OK.
- Browser (founder login, throwaway project deleted): imported gear STEP → tree "Teeth (40 × circular pattern) 1080
  faces / Bore Ø20 / Imported blank 2 faces"; Recognize features → AI: "Spur gear, 40 teeth, module 3 · ISO 53 · high";
  hovering Teeth highlights all teeth; all panels + command bar collapse to a full-width viewer.

### Not done / limits
- Only holes/patterns are parameter-editable on imports; other recognised features are edited through the agent.
- Gear phase/profile parameters are informational (no regeneration of teeth from parameters on an import yet).

### Next
DS-024 and: offer "Replace with Toolbox gear" when a recognised gear matches a generator (exactness checked by CHK-09).

## 2026-11-16 (g) — CommandManager, 2D sketcher, STEP import + recognition, Toolbox, choice questions

Founder requests (autonomous, "do it completely and push"): hide agent internals; SOLIDWORKS-style command tab;
faster manual add/suppress; full 2D sketcher + more features; STEP import editable by agent or manually; feature
recognition → parametric rebuild; Toolbox of repeatable standard components with a popup offering Toolbox vs
custom design; agent questions as clickable choices; put all context in the repo and push.

### Done (punch list DS-010, DS-010b, DS-014..DS-023)
- **Plain-language agent progress** (DS-014): tool steps and results are translated server-side; file names,
  tools, code and model ids never reach the UI.
- **CommandManager ribbon** (DS-015): Features / Sketch / Evaluate / View / Library tabs drive every manual workflow.
- **Faster manual edits** (DS-016): optimistic suppress/delete/reorder with rollback, non-blocking "Rebuilding…"
  pill, build time in the toast; fast path + base-geometry cache from (e).
- **2D sketcher** (DS-017): line chains, rectangle, circle, centre arc, Smart Dimension (inline edit), relations
  H/V/∥/⊥/=/tangent/concentric/point-on/fix, auto H/V, snapping to sketch points and face vertices, drag with
  live solve, undo/redo, DOF status; exit to boss/cut; re-edit from the tree. Bug found in browser test and fixed:
  clockwise loops extruded into the part — loops are now oriented CCW (regression test added).
- **Shell, mirror** (DS-023).
- **STEP import** (DS-018) + **feature recognition** (DS-019): stock, holes (Ø, depth, through), grid / linear /
  circular patterns, bosses, fillets, chamfers; deterministic parametric draft (keeps manual features) or agent
  rebuild; new check **CHK-09** = symmetric-difference volume vs the original (draft of a drilled plate:
  rel. err < 1e-5).
- **Toolbox** (DS-020/021): 11 deterministic, versioned generators with analytic EXPECTED; all pass checks incl.
  byte-identical STEP. Found and fixed: OCCT numbers assembly occurrences with a process-wide counter (STEP bytes
  differed on a warm worker) → ids renumbered after export; sphere pole edges were counted as free edges.
  Chat requests matching a component open a popup: "Use Toolbox: Hex bolt ISO 4017 M8×40" or "Continue with
  custom design".
- **Choice questions** (DS-022): agent emits a `fw-questions` block → chips + Other → one-click answers.
- **Repo context**: `CLAUDE.md` (session start/end ritual) and `docs/CONTEXT.md` (portable memory).

### Evidence
- `pytest`: 78 passed (full suite) + new `tests/test_library.py` (8 tests); ruff clean; `tsc` + `vite build` OK.
- Browser walkthrough (puppeteer, founder login, throwaway project deleted after): Toolbox flange created in
  0.52 s (Verified); Sketch tab → pick top face → rectangle → Exit sketch → boss: bbox 150×150×26 mm, 16 faces;
  Toolbox popup on "I need an M8x40 hex bolt" with sizes pre-filled; Import STEP dialog opens; no console errors.

### Not done / limits
- Live agent run producing choice questions not yet exercised in the browser (parser unit-tested).
- Sketcher: no trim/offset/splines/construction toggle, no reference planes; recognition is heuristic
  (pockets/slots/freeform left to the agent). Toolbox threads are cosmetic; bearing is an envelope model.

### Decisions parked
PD-12 GitHub remote (gh CLI not installed), PD-13 Toolbox standards verification, PD-14 recognition depth.

### Next
DS-024: revolve/sweep, pattern any feature, sketch trim/offset, reference planes, assemblies with Toolbox parts.

## 2026-11-16 (f) — Design Studio maturity: B-rep viewer, measurement, manual features

**Founder request:** mature Design Studio before other modules, building everything on the list. Added during the session: CAD orthographic default with perspective toggle (DS-012), and a fix for wireframe showing triangles (DS-013).

### Delivered
- **Backend:**
  - `src/aicad/topo.py`: exact B-rep topology (faces with type/normal/axis/radius and their own tessellation; edges line/circle/curve with true radius and length; vertices; part labels).
  - Mass properties.
  - `src/aicad/fw.py`: named features with **surface-based provenance**, location selectors, manual features (fillet, chamfer, hole + linear pattern, rectangle/circle extrude or cut).
  - `src/aicad/materials.py`.
  - `routers/studio.py`: materials, settings, estimate, manual-feature CRUD with rollback, revision compare via OCCT booleans.
  - Worker `diff` op; `PARAM_META` limits enforced; 3MF; gzip; image attachments (type-sniffed); persistent chat + resumed agent session; undo metadata; lazy topology upgrade for old projects.
- **Frontend:**
  - New `web/src/viewer/engine.ts`: Z-up CAD camera, ortho default, persp strength, silhouette fit, 4 display styles from real edges, picking with snapping and occlusion test, selection and hover highlights, capped section on X/Y/Z, explode and part visibility, compare overlay, CoG marker, sketch preview.
  - `measure.ts`: exact distances, Ø/R, angles, plane distances.
  - Studio rebuilt: feature tree, PropertyManager, smart params, Mass tab, compare, attachments, selection chips, undo, estimate.
  - God mode moved into the header.
- **Agent contract:** `fw.feature` provenance, `PARAM_META`, act on `[Selected …]` geometry by location, keep the managed manual block, read reference images.

### Evidence
- **Tests:** 70 pass (8 new in `tests/test_studio.py`).
- **Browser walkthroughs on the founder's gear:**
  - Orthographic iso and front (true projection).
  - Wireframe shows only model edges; hidden-lines mode works.
  - Hover snapping finds Arc R10.000 (Ø20.000) and its centre (0, 0, 10.00); a hidden bottom rim is no longer offered.
  - Measure gives a face area of 10761.571 mm²; Mass shows steel at 844.78 g.
- **Temporary demo project** (removed afterwards):
  - The tree highlights the pocket's 9 faces.
  - A Hole was added via the PropertyManager with a live outline.
  - Compare shows removed material of 502.7 mm³, equal to π·4²·10.
- **Live founder use:** point-and-tell sent "Remove these holes" with a hole selected, and the agent identified the 6-hole bolt pattern.

### Findings / fixes during the session
- Face provenance keyed on area mis-attributed trimmed faces; it is now keyed on the underlying surface (plane equation, cylinder axis + radius).
- Tuple-free parameters and integer preservation from the previous session still apply.
- A failed agent build hid the model behind the empty-state overlay; now the last good geometry is kept, with a "Last build failed" banner.
- Radix menus and tabs need real pointer events in automation (test-script note, not a product issue).

### Remaining on the Design Studio list
- DS-010b full 2D sketcher with constraints (needs a sketch solver, CAD-060).
- Polyline sketches, mirror/shell, patterning any feature.
- Per-part transparency.
- A live agent run with an attached image (the endpoint and validation are tested; the agent path isn't yet).

---

## 2026-11-16 (e) — Rebuild speed-ups, safe parameters, layout fix

**Founder report:** parameter edits on a generated gear were slow despite "no AI"; the Params panel exposed internal variables (`N`, `tooth_int`); the chat panel was clipped.

**Diagnosis (measured on the founder's gear):** each edit started a fresh Python process and loaded build123d/OCCT (~3–5 s), built the geometry (0.6–0.9 s), ran verification including a full second build for the repeatability check (~2.8 s), then rendered 4 views in another new process (~1.5 s). That's ~8–10 s, with no AI involved.

**Changes**
- `agent/worker.py`: a warm build worker per organization with the CAD kernel preloaded. It is recycled every 25 jobs and restarted on timeout or crash. Script stdout is isolated from the protocol. Helper modules imported from the workspace are purged after each build.
- Parameter edits and revision restores skip the repeatability rebuild. CHK-08 is reported as a non-gating INFO ("skipped"). Agent builds still run it.
- The 4-view PNG renders in the background after the response; the viewer uses the GLB.
- A failed edit restores the previous outputs from a snapshot instead of rebuilding again.
- **Editable parameters:** a name is editable only if it is declared in the model's `PARAMS` and assigned exactly once at top level as a plain number (AST check in `runner.editable_params`). The server rejects anything else and the UI shows only `PARAMS`. The agent contract now forbids derived values, loop/accumulator variables and sampling/resolution settings in `PARAMS`.
- Studio layout: grid `minmax(0,1fr)` and a scrollable tab row stop the page-level horizontal overflow that clipped the chat.

**Evidence:** on the founder's gear, warm edits take **2.9 s end to end** (was ~8–10 s); the first edit after a server start takes 8.2 s while the worker warms up. Runner breakdown: geometry 0.88 s, STEP export 0.15 s, STEP re-import 0.50 s, STL 0.18 s, round-trip check 0.30 s, GLB 0.17 s, other checks 0.18 s. `N` is rejected via the API. 62 tests pass (new: editable-params AST, determinism skip, warm worker build/render/stdout isolation). Main area scrollWidth now equals clientWidth at 1915 px.

**Notes / gaps**
- The existing gear still lists `FLANK_PTS` because it was generated under the old rules and declares it in `PARAMS`. New models follow the stricter rule.
- Agent chat transcripts live in memory, so a server restart clears the conversation panel (files, revisions and model are kept). Persisting transcripts is the next small item.
- The timing test added revisions 5–7 to the "Test" project; its final state equals its state before the test.

---

## 2026-11-16 (d) — Formwright: full product platform (autonomous session)

**Founder request:** a production-grade, user-facing application before going deeper on CAD. It should have a modern sidebar UI that feels at home for SOLIDWORKS users, branding and logo, auth and roles, packages and costing with in-app purchases and Stripe, trial tokens, the complete customer journey with a guided tour, God mode to bypass any step, and investor-demo readiness. The existing feature should live inside the product; unbuilt CAD features can be placeholders. The founder then went away: "keep building autonomously… park decisions you can't make".

### Delivered (evidence)
- **Brand:** Formwright — name, logo, palette, typography, voice (`docs/BRAND.md`, ADR-015).
- **Backend** (`src/aicad/platform/`):
  - models, auth, onboarding and journey, team, billing (Stripe or simulated), projects with the per-project design agent and token metering, revisions and restore, deterministic parameter edits, admin console, God mode, security middleware;
  - 4 original demo parts (`src/aicad/demo/`), each passing all checks.
- **Frontend** (`web/`):
  - React, TypeScript, Vite, Tailwind, Radix, TanStack Query, three.js, driver.js; `npm audit` reports 0 vulnerabilities;
  - pages: landing, pricing, legal drafts, signup, login, reset, verify, invite, onboarding wizard, dashboard with tour and checklist, projects, Design Studio (chat, viewer, checks, params, revisions, files, source, status bar), modules and preview pages, billing and checkout, team, settings, help, admin console (9 tabs), God-mode panel and command palette.
- **Tests:** 59 backend tests pass (16 platform tests cover the journey, billing, seats/roles, paywall, God mode on and production-off, admin and impersonation, demo seed, parameter edits, token metering, hashed tokens). TypeScript is strict-clean; `ruff` is clean.
- **E2E (headless Chrome with puppeteer-core, scratchpad only):**
  - *Customer path:* landing → pricing → signup (Pro intent) → verify via dev mailbox → onboarding (5 steps) → dashboard and 7-step tour → template project → studio and its tour → modules → Drawing preview → join early access → billing → simulated Pro checkout → success (tokens 300 → 1,800, modules unlocked) → team invite (402 seat paywall shown correctly) → settings → help → command palette. **0 page errors.**
  - *Founder path:* God panel → seed demo (4 verified real parts with thumbnails) → studio with a live model and passing checks → params → revisions → admin overview, users, catalog, audit. **0 errors.**
  - Screenshots reviewed. Fixed from review: overflowing studio tabs, trial-day rounding, funnel bar overflow, the God button overlapping the status bar, module codes shown on the receipt, and a premature `status.json` request.

### Findings
- Tuple assignments (`L, W, T = …`) can't be edited deterministically. The demo scripts were split one per line, and the agent contract now requires one `DIM = number` per line with EXPECTED computed from the variables.
- Integer parameters (e.g. `N_BOLTS`) must stay integers on edit. Now enforced.
- Ruff in this environment enables extra rule sets (B, C4, FURB, SIM…). FastAPI `Depends` is allowed via config.

### Parked decisions
PD-01…PD-11 in `docs/DECISIONS.md`: name clearance, pricing, token economics, preview add-on billing, data/AI policy wording, Stripe account, email provider, hosting, agent API key, sandbox, contact addresses.

- **Live AI run through the platform UI** (founder's dev login, God bypasses off): L-bracket template prompt → agent finished in 3 turns / 34.5 s → part 80 × 40 × 60 mm, all 6 gating checks pass (volume rel err 1.2e-16) → **16 tokens metered** (300 → 284, ledger row written) → the agent listed assumptions to confirm (hole spacing, Ø9 clearance for M8). Fixed from the screenshot: the viewer framing cropped parts in narrow viewports, so the fit now uses the narrower FOV.

### Not done / honest gaps
- The studio tour's "seen" state is per browser (localStorage); the product tour is stored server-side.
- No Alembic migrations (INF-008). Rate limiting is in-process. The mobile layout of the studio is desktop-first.
- The Stripe path is implemented but unexercised without keys (COM-007).

### Next highest-leverage items
1. Founder review of the demo flow; resolve PD-02/03 (pricing, tokens) and PD-06 (Stripe test keys).
2. First real CAD module: Drawing Studio (DRW-001..006) replacing its Preview.
3. Pre-pilot hardening: API-key agent auth (AGT-015), container sandbox (SEC-004), Alembic (INF-008), SMTP (PD-07).

---

## 2026-11-16 (c) — Chat-driven design agent (Claude Agent SDK)

**Founder input:** "Just a view — where do I give a prompt?" The founder rejected a plain chat-API approach, which lacks Claude Code's agentic power, and asked for the UI to be driven by a Claude Code session. For development it should use the founder's subscription, not paid API calls.

**Research (docs fetched 2026-11-16):** the Claude Agent SDK is "Claude Code as a library": the same tools, agent loop and context management. Use is governed by the Commercial Terms. The overview page says: *"Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK."* So subscription auth is used **only for the founder's own development on this PC** (R-LIC-05, AGT-015).

### Done (evidence)
- **Dependencies:** claude-agent-sdk 0.2.182 (MIT on PyPI; it bundles the CLI, 2.1.325), fastapi, uvicorn 0.54, vtk 9.7.2, httpx (dev).
- **Smoke test:** `apiKeySource: none` (subscription login), model claude-opus-5-5. With `setting_sources=[]`, the founder's personal plugins and hooks are not loaded into the product agent.
- **New code:**
  - `agent/runner.py`: subprocess build of the AI-written script, checks, artifacts, import tripwire.
  - `agent/render.py`: VTK offscreen 2×2 views, about 2 s.
  - `agent/tools.py`: the `build_model` MCP tool returns the report plus an image.
  - `agent/prompt.py`: the CAD workflow, script contract and honesty rules.
  - `agent/session.py`: `ClaudeSDKClient`, tool allow-list, workspace path guard, SSE events.
  - `studio/app.py`: the FastAPI server.
  - Chat panel added to the viewer page.
  - `aicad studio --project NAME [--api-key]`.
- **Tests:** 43 pass, with no model calls: runner, tripwire, path/web guard and endpoint tests. `ruff` clean.
- **E2E (live, subscription):** prompt for a 6061 L-bracket (60/40 legs, 50 wide, 5 thick, 4× M5 clearance holes, R3 inside fillet).
  - The agent stated requirements and assumptions, wrote `model.py` with an analytic `EXPECTED` (section area + r²(1−π/4) fillet material − holes), built once, and all gating checks passed.
  - Volume: 23 371.4049 mm³, rel err 0.
  - 3 turns, 38.4 s. API-equivalent estimate $0.55, **not billed** (subscription).
  - It also flagged a real ambiguity: the vertical leg's holes end up only 10 mm apart, and it asked about it.
  - Screenshot of the studio UI checked.

### Findings
- Headless-Chrome screenshots hang with `--virtual-time-budget` while the SSE stream is open; use `--timeout`.
- VTK: `AddActor2D` is not available; use `AddViewProp`.
- An earlier `uv pip list` showed packages from base conda (VIRTUAL_ENV leak), not the project venv. Always `unset VIRTUAL_ENV`.

### Blocked / risks
SEC-004 sandbox is still blocked (no Docker/WSL distro). It is now the gate for any customer use, because the agent writes and runs Python.

### Next highest-leverage item
Add DRW-001..004 (3-view drawing) as a second agent tool, so the loop produces a manufacturing drawing as well as STEP. In parallel, run 5–10 real prompts from the founder's own work as a qualitative benchmark (EVAL-003).

### Decision required
None now. Before any pilot user: an API key or approved auth (AGT-015), and Docker/WSL for the sandbox (SEC-004).

---

## 2026-11-16 (b) — Approval, geometry spike, live viewer

**Founder decision:** approved the M1 wedge and direction ("Go ahead"). ADR-001, 002, 003 and 005 are Accepted. New request: a live viewer instead of checking STEP files in SOLIDWORKS → ADR-012.

### Done (evidence)
- **GOV-004** `git init`, `.gitignore`, initial commit.
- **ARC-010 / ADR-005** `.venv` with Python 3.12.13 (uv), build123d 0.13.0 pinned, cadquery-ocp 7.9.3.1.1, `uv.lock`. Base conda untouched.
- **FX-01** `src/aicad/parts/plate.py` (hand-coded, no LLM), `specs/fx01_plate.json`.
- **Checks** `src/aicad/checks.py`. FX-01 results:

| Check | Result |
|---|---|
| CHK-02 valid, 1 solid | pass |
| CHK-03 free/non-manifold edges | 0 |
| CHK-04 bbox | 120 × 80 × 10, max err 3.6e-15 mm |
| CHK-05 volume vs analytic | 89 663.7582 mm³, rel err 4.9e-16 |
| CHK-06 cylinders | r 3.3 × 4 (holes), r 3.0 × 4 (pocket corners) |
| CHK-07 STEP round-trip | equal volume/bbox/faces |
| CHK-08 determinism | fingerprint equal; STEP bytes identical (fixed header timestamp) |

  Build + export + checks + GLB took about 0.5 s on this workstation (not representative of cloud, AS-08).
- **Tests:** `uv run pytest` → 20 passed in about 16 s. Covers the golden pipeline, an independent hand calculation, STEP byte determinism, a metamorphic length test, 80 seeded random specs (≥ 50 built and checked), 6 invalid-spec rejections, negative check tests, and viewer allow-list/path-traversal tests. `ruff` is clean.
- **UX-008 live viewer** (`aicad live`): headless-Chrome screenshot of FX-01; then the spec was edited 120 → 150 mm and saved, the viewer auto-rebuilt (new build_id), and the panel showed bbox 150 × 80 × 10 and volume 113 633.7582 (Δ = 23 970 = 30·80·10 − 30·1², matches analytic). Spec reverted to 120.

### Findings
- OCP 7.9 API differences: `TopoDS.Edge` (not `Edge_s`); `TopTools_IndexedDataMapOfShapeListOfShape` is not exposed. Worked around.
- Two of my invalid-spec test cases were actually valid geometry; the validator was right. Fixed the tests, not the code.
- The viewer reads STEP with the same OCCT kernel that wrote it, so it cannot catch reader-specific interop bugs. EVAL-005 is now a periodic spot check.

### Blocked
Unchanged: SEC-004 (no Docker/WSL distro), AGT-010 (no API key), LEG-* (counsel).

### Next highest-leverage item
ARC-011: Part Spec DSL v0 (pydantic schema with features, IDs, semantic selectors, assumptions, open questions), then a compiler that reproduces FX-01 from the DSL with an identical fingerprint. This is the step that lets the LLM drive geometry.

### Decision required
None blocking. Live LLM calls (AGT-010) will need an API key plus approval for paid usage. That decision comes after the DSL exists.

---

## 2026-11-16 — Session 1: M0 discovery kickoff

**Scope:** Section 10 A–D of the master prompt. No application scaffolding, no dependency installs.

### A. Repository and runtime audit (evidence: commands run this session)

| Item | Finding |
|---|---|
| Repository | `c:\Users\Awais\Desktop\AI CAD` contains only the master prompt and `.claude/settings.json`. **No source code, assets, or tests. Not a git repository.** |
| OS | Windows 11 Pro for Workstations 10.0.22621 |
| CPU / RAM / disk | 2× Intel Xeon Gold 6254 (18 cores / 36 threads each, 36 / 72 total), 254.6 GB RAM, 369.7 GB free on C: |
| GPU | NVIDIA Quadro RTX 8000, 48 GB, driver 596.71 |
| Python | 3.13.9 (miniconda base at `C:\Users\Awais\miniconda3`); `py` launcher absent; `python3` is the MS Store stub |
| Package managers | uv 0.11.11, pip 25.2, conda 25.9.1 (envs: base, aims-matlab, erp, sensor), npm 11.12.1; pnpm/yarn absent |
| Node | v24.15.0 |
| Docker | **Not installed** |
| WSL | Installed, **no distributions** |
| Git | 2.52.0 |
| CAD already in base env | cadquery 2.8.0, cadquery-ocp 7.9.3.1.1 (bundles OCCT DLLs via delvewheel), pyvista 0.48.4, vtk 9.6.2 |
| Not installed | build123d, trimesh, fastapi, anthropic SDK |
| Desktop CAD apps | Blender 5.1, SOLIDWORKS 2025 (incl. Simulation-family add-ons, PDM, Visualize), PTC Creo 11.0.1.0 |
| AI credentials | `ANTHROPIC_API_KEY` not set in the environment |
| PyPI reachable | Yes. Latest seen: build123d 0.13.0, cadquery-ocp 8.0.1.1.0, trimesh 5.2.1, fastapi 0.163.1, anthropic 2.8.0, manifold3d 3.5.5 |

License metadata read from package metadata/PyPI (not legal review): build123d Apache-2.0; cadquery Apache-2.0; cadquery-ocp Apache-2.0 for the bindings, **but the wheel's dist-info ships no OCCT license text although it bundles OCCT binaries (OCCT is LGPL-2.1 with exception)**, see RISKS R-LIC-02; pyvista MIT; vtk BSD; trimesh MIT; fastapi MIT; anthropic SDK Apache-2.0; manifold3d Apache-2.0.

### B. Documents created
`docs/PUNCH_LIST.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/RISKS.md`, `docs/VALIDATION.md`, this log.

### C. Vertical slice proposed
VS-1 "Text/spec → parametric machined plate": see `docs/VALIDATION.md` §2 and ROADMAP M1.

### Completed
- GOV-001 environment audit, GOV-002 documentation skeleton, GOV-003 initial punch list (195 items, trace table to master prompt §2), ARC-001 architecture recommendation (draft), ARC-003..008 comparisons, LEG-001 direct-dependency license metadata. All are document deliverables; **no product code exists.**

### Blocked
- SEC-004 container sandbox: no Docker/WSL distro (installing needs approval).
- AGT-010 live LLM calls: no API key configured (and paid usage needs approval).
- All LEG-* items: need counsel.

### Next highest-leverage item
After approval: ARC-010 geometry spike: isolated uv venv (Python 3.12) + build123d, build the golden plate fixture, run STEP export/reimport and checks. Proves kernel choice on this machine before any app code.

### Decision required
Approve the M1 wedge (ADR-003) and architecture direction (ADR-001, ADR-002).

### Not done / limitations
- Licenses were read from metadata only; transitive dependency audit not yet run.
- No market evidence gathered; wedge reasoning is a hypothesis.
- Directory is not under version control; recommend `git init` once approved (non-destructive).
