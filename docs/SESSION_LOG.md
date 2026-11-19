# Session Log

Newest first. Each entry: what was done, evidence, blocked, next item, decision needed.

---

## 2026-11-19 (d) — Hosted server: AI for super-admins only (FW_AI_SUPERADMIN_ONLY)

### Done
- The app is hosted at https://formwright.codingthebrains.com in development mode, so God mode is available. The founder asked that only the God mode super-admin uses AI and that other sign-ups get no AI.
- New setting `FW_AI_SUPERADMIN_ONLY` (default off, so behaviour is unchanged unless it is set). When it is on:
  - `can_run_agent` refuses non-super-admins with "AI features are turned off for this account." That covers the design agent chat, Design Office, collaboration, drafting and image-to-CAD, which already show this kind of message in the app.
  - Backstop: `AIAccessMiddleware` (pure ASGI, `platform/deps.py`) marks each `/api` request with whether the real person (the actor, also while viewing as someone) is a super-admin. `aicad.llm.get_provider` then raises `AIDisabledError` for any model call made for anyone else. That covers every other AI feature (librarian, render refine falls back to its template, reviewers, planner, vision, reconcile), and the error shows as HTTP 403 with the same message. No request context (CLI, tests, benchmarks) means allowed.

### Verified how
- `tests/test_ai_access.py`: a regular user gets agent.allowed false, a 402 on chat and a 403 on a model call; a signed-out request gets a 403; the super-admin keeps AI; with the setting off everyone keeps AI. Ran `test_ai_access`, `test_platform` and `test_llm_providers` plus `ruff`; the CAD suites were skipped (no CAD code was touched).

### Not done
- The UI still shows AI buttons to regular users; they get the message when used. Hiding them needs a frontend flag (PD-64).

## 2026-11-19 (b) — Quality fixtures: golden assembly fixtures FX-04/05/06 + advisory render similarity (ASM-012, EVAL-006)

Branch `wip/quality-fixtures` (worktree `fw-wt/quality-fixtures`), not merged. PD-62. No live model calls.

### Done
- ASM-012: `src/aicad/fixtures/` — `harness.py` (build parts, CHK-02..05 vs hand sums, STEP, mate solve from perturbed
  starts, hand placements, mechanism freedoms, exact interference, hand min distances, mass + centre of mass, BOM,
  motion sweep), `fx04_bolted_bracket.py`, `fx05_keyed_shaft.py`, `fx06_hinged_arm.py` (original designs, parametric
  build123d scripts + Toolbox fasteners / bearing / gear / dowel, every expected value a hand formula),
  `python -m aicad.fixtures [--write]`. `specs/fixtures/<fx>/assembly.json` (generated definition) +
  `provenance.json` + `specs/fixtures/README.md`.
- EVAL-006: `src/aicad/eval/render_similarity.py` (silhouette SSIM + edge IoU, numpy + Pillow); logged as advisory in
  `aicad bench` (`--save-renders`, `--ref-renders`), `aicad repeat` (`--render`) and the run record
  (`render_similarity` vs the previous review render).

### Verified
- `tests/test_fixtures_asm.py` 10 passed (≈20 s): all three fixtures pass every check; FX-04 mass = hand
  392.03 g, protrusion 3.6 mm; FX-05 freedoms 3, clearances 2.0 / 11.0 mm; FX-06 sweep collides at exactly −40, −30,
  210, 220° (hand contact −25.11° / 205.11°), edge gap at −25° = 0.0486 mm = formula; broken variants fail.
- `tests/test_render_similarity.py` 9 passed: hand IoUs on synthetic images, real VTK sheets in bench/repeat/run record.
- Gate: ruff clean; assembly, assembly motion/AI, ai_quality, repeat, sbom, run_record, plate, library + new tests pass.

### Not done / limits
- Fixtures are code + data, not seeded Studio/Assembly projects (could become God-mode demos later).
- The solver's own `dof` sums per instance; the fixtures use the Jacobian nullity. Not changed in the solver.
- Render similarity is not perceptual and depends on identical framing (same renderer, same views).

### Next
- Merge `wip/quality-fixtures`; optionally seed FX-04..06 as demo assemblies; EVAL-004 FX-02/03 part fixtures in the
  same `specs/fixtures/` form.
## 2026-11-19 (c) — Studio follow-ups: sheet-metal corners / cuts through bends / jog, fw-edit depth / pattern / multi, impact on tree actions (CAD-026, DS-035, ASM-018)

Branch `wip/studio-followups` (worktree `fw-wt/studio-followups`). Report: docs/reports/studio-followups/README.md. PD-63.

### Done
- Sheet metal (`sheetmetal.py`): automatic corner relief where a new flange's edge ends on an existing flange's bend
  start line (earlier flange cut back to the new bend start + w, w = ratio·T; w × w square or radius-w circle at the
  bend-line corner); closed corners (default, gap 0.2 mm, two 90° flanges the same way: walls carried round) or open;
  `Bend.ext` keeps the model volume exact so the flat stays on its exact path. Cuts through bends are traced on the
  neutral surface and unbent into the flat (no more "not shown" note for them). Jog (`sm_jog`, `fw.jog`, ribbon button +
  PropertyManager with the live m / flat-growth line); jogs reuse `flange()` with a given child region / solid. Base
  flange sketch editor: corner type + gap. Agent prompt: jog + corners; scrub covers `fw.jog`. Miter flange not built.
- fw-edit (`agent/edits.py`): `extrude` (depth / end of an existing hand-made extrude or cut), `pattern` (count, spacing,
  circular angle; feature and hole patterns), several edits per block (≤ 8, all validated first, one PM step each in
  order; the Studio opens the next after OK + rebuild; Cancel drops the rest; chat card lists the steps; impact of the
  whole `sequence`). Design state lists extrude depths and pattern counts/spacing.
- Impact (ASM-018): `trial_source` kinds suppress / delete / reorder / design_suppress / design_delete / sequence;
  `ImpactIn` widened. Tree suppress/unsuppress/delete/move (hand-made and agent steps) and Ctrl+K feature / suppress
  commands check first when the part is in an assembly and show the same Apply anyway / Back panel (modal).

### Verified how
- New tests: `test_sheet_metal.py` +11 (corner closed/open × rect/obround/none area, size, bend-line length and the
  folded gap probe; tray with two corners; window 10 × (3 + BA + 6); radial hole vs the integrated neutral trace (0.5 %);
  jog 90°/60°/flipped; jog errors; Studio corner + jog API), `test_studio_intel.py` +5 (depth/pattern/multi parse + errors;
  replayed one-turn two-step edit applied = 24000 − 720 − 80π; trial_source per tree action; fixture assembly suppress /
  delete pin hole = break + 117π, reorder = 27π, sequence = 108π + break, suppress boss = clean), vitest +4.
- Gate: ruff clean; pytest test_sheet_metal, test_studio_intel, test_studio, test_studio_fixes, test_agent,
  test_ai_quality, test_drawings, test_drawing_depth, test_drawings_2d, test_llm_providers, test_assembly: 223 passed
  (11 min, under walkthrough load); tsc clean; vitest 130 passed; vite build OK.
- Browser walkthrough (puppeteer-core 25.18.1, port 8851, throwaway data dir, replay cassette, 0 model calls): 11
  screenshots in docs/reports/studio-followups/, 0 console/page errors (parts A+B and C each finished clean). Observed: jog flat 113.047787 × 60 (= 100 + 2·BA + 4), tray
  4 bends, closed corner, no flat notes; multi-edit volume 23,028.672588 (= 24000 − 720 − 80π); tree / Ctrl+K gate 367.6
  mm³ = 117π. Fixed from it: the next agent step never opened when the
  viewer loaded the rebuilt geometry before the panel's OK callback ran, or before the new build's feature list arrived
  (the queue now records the geometry when a step opens and waits for the feature list). Seen once: right after a
  replayed build the tree loaded with no features until a reload (existing tree query, not changed here; noted).
  Under heavy load the agent's edit sometimes arrived as history and did not auto-open (existing rule; the card's
  button opens it).

### Not done / limitations
- No miter flange or sketched bend; closed corners only for 90°/90° same direction; corners not treated next to hems,
  jogs or flanges that already carry flanges; jog only across a whole panel, before flanges on the moving end.
- Unbent hole outlines in bends are sampled polylines (DXF gets short lines, not arcs).
- fw-edit still has no drafts / sketch geometry; script (agent-made) features change only through parameters.
- Impact does not preview rollback-bar moves or renames. If the trial build fails the action runs and reports its own error.
- After step 1 of a multi edit the chat card still says "Open step 1 of n" (the queue drives the next panels).

### Next
- Merge `wip/studio-followups`; founder try-out of a closed-corner tray with a fabricator's K-factor; one live agent run
  to confirm the model emits multi-step fw-edit blocks (PD-09 subscription).

## 2026-11-19 (a) — Coordinator: batches 23-28 merged + pushed

- Merged into main and pushed: drawing depth (PD-58), engineering hygiene (PD-56), studio intelligence (PD-57), agent
  platform (PD-59), sheet metal (PD-60), Design Office phase 6 (PD-61). PD numbers renumbered at merge where branches
  collided; doc conflicts resolved by keeping both sides.
- Verified: full suite after batch 23-25 = 623 passed; after batch 26-28 = 702 passed + 1 Blender mesh test that failed
  under load and passed alone (`test_highlight_protection_...`). ruff clean, tsc clean, vitest 126, vite build OK.
- Flake note: `test_datasheet_shots_go_stale_and_requeue` failed twice under load before the sheet-metal merge made
  `runner.finalize()` write status.json atomically (likely cause: a half-written status.json read as "no build"); it
  passed in the full run since.
- Founder to-do: open one "Export for SOLIDWORKS" zip in SW 2025 (EVAL-005); decide PD-41/PD-48 (live agent runs).
- Next: remaining engineering backlog (ASM-012 golden fixtures, EVAL-006 render similarity, sheet-metal corner relief,
  fw-edit for more feature kinds); founder/legal items stay with the founder.

## 2026-11-18 (w) — Agent platform: LLMProvider, second provider, SOLIDWORKS STEP pathway, Blender IO rows (AGT-001, AGT-013, CAD-070, IO-008b)

Branch `wip/agent-platform` (worktree `fw-wt/agent-platform`), not merged. PD-59. No live model calls: fakes,
stub and replay only.

### Done
- AGT-001: `src/aicad/llm/` — typed `LLMProvider`: `complete(CallRequest)` (role, system, prompt, images, JSON
  schema, budget, cwd, model) → `CallResult` (text, validated `data`, `Metering`: provider, role, model id, tokens,
  cost + source reported/estimated/none, latency, ok); `agent_client(options)` for the Studio session. Roles per call
  site; routing `FW_LLM_PROVIDERS` (`Settings.llm_providers`; dev-only providers refused in production);
  `llm.metering` (structured `aicad.llm` log line, listeners, ring buffer shown in super-admin `/api/admin/system`).
  Migrated: Studio session (`session.provider_client`, also `aicad bench` / `aicad repeat` live paths), Archie plan
  + change review, Gage review, image vision read (image passed as `images=`), AI Render prompt polish, drafting
  assist, assembly librarian, merge reconcile. Wrapper function names kept, so existing tests and fakes are
  untouched. The run record now stores `provider`.
- AGT-013: `stub` (deterministic: schema examples, image fingerprints, a one-turn session client) and
  `anthropic-api` (official SDK, `beta.messages.create`, images as base64 blocks, `output_config` JSON schema,
  server-side refusal fallback, refusal → ProviderError; own key `FW_LLM_ANTHROPIC_API_KEY`; off by default; no
  sessions; `anthropic` imported lazily). `replay` provider wraps the cassette (new optional `calls` list).
- CAD-070: `native/solidworks.py` + `GET /api/projects/{id}/export/solidworks?schema=ap214` (or `ap242`): zip of
  a STEP with one product named after the part (build123d's exporter wraps a solid in an assembly of one and always
  writes an AP214 header, so we write the XCAF document ourselves and take the header after the transfer; located
  shapes have the placement baked in), mm, colour from the material finish; read back and compared with the build
  (volume, bbox corners, solid count) before it is offered; parameters CSV; README with the disclosure (dumb solid,
  no feature history, Native CAD bridge, not opened in SOLIDWORKS by Formwright). UI: "Export for SOLIDWORKS" in
  the Studio Files panel and the Projects row menu (dialog with the disclosure + AP214/AP242 choice); Help text.
- IO-008b: Mesh Studio's Blender GLB / OBJ / STL in the IO matrix (real export job, spec readers incl. new
  `read_obj`): GLB metres +Y up, OBJ/STL mm Z up, frame kept, positive signed volume. Skips without Blender; ran
  here (Blender 5.1). No axis or unit error found.

### Verified how
- New: `tests/test_llm_providers.py` (35: contract ×4 providers for text/metering, structured, invalid JSON,
  vision, session-or-refusal; option shapes; request body; key/refusal; routing; production refusal; every call
  site routed; choke-point scan), `tests/test_solidworks_export.py` (9), IO-008b row in `tests/test_io_roundtrip.py`.
- Existing suites for agent, ai_quality, run_record, repeat, office, office_orchestrator, airender, image2cad,
  drawings_2d, assembly_ai, collab: 214 passed after the migration. Full suite 668 passed (25 min); ruff clean; web
  gate green (tsc, vitest 121, vite build).

### Not done / limitations
- The Messages API provider has no agent-session loop (the Studio agent needs the Claude Code harness); never run
  live. `anthropic` is not a dependency yet (AGT-015 adds it with the API-key switch).
- AI Render's OpenAI image generation is outside the LLM interface (image model, BYO key).
- Replay provider replays single calls but `RecordingClient` still records sessions only.
- CAD-070's "SOLIDWORKS 2025 opens the file" is EVAL-005 (founder manual check, Backlog). Cosmetic thread notes
  from the build's STEP header are not carried into the SOLIDWORKS STEP.

### Next
- Merge `wip/agent-platform`; founder: open one "Export for SOLIDWORKS" zip in SW 2025 (EVAL-005).
- AGT-015: add `anthropic`, route single-call roles to `anthropic-api` in the pilot build, then a Messages-API
  session loop.

### Decision parked
- PD-59 (provider routing, Messages API defaults, SOLIDWORKS export defaults).
## 2026-11-18 (y) — Sheet metal: base flange, edge flange, hem, flat pattern + DXF, drawing sheet, DFM (CAD-026, MFG-011)

Branch `wip/sheet-metal` (worktree `fw-wt/sheet-metal`). Report + screenshots: docs/reports/sheet-metal/. PD-60. No live
model calls.

### Done
- Kernel `src/aicad/sheetmetal.py`: immutable panel + bend model kept next to the solid; base flange (closed sketch
  region + T), edge flange on a picked straight sheet edge (length outer virtual sharp / tangent, angle 0–180°, own R,
  position material inside / outside / bend outside, flip, end offsets with rectangular / obround reliefs), open hem;
  flat pattern solid (+ placed over the base), outline entities, bend centre lines, DXF (OUTLINE, BEND_UP / BEND_DOWN
  dashed, BEND_NOTES "UP 90° R2", NOTES). Cuts made in panels after the flanges carry into the flat (common with each
  panel prism); material outside panels / cut through bends is reported, not drawn.
- `fw`: manual ops `sm_base` / `sm_flange` / `sm_hem` (validated in `studio.validate_feature`, picks in REF_OPS so they
  follow size and thickness edits), helpers `fw.base_flange/edge_flange/hem` for model scripts; runner caches the
  sheet state with the base, writes `out/flat.topo.json|dxf|json` and `status.sheet_metal` (served files; flat DXF in
  DOWNLOADS as `<part>_flat.dxf`).
- Studio: Sheet Metal ribbon tab (Base Flange, Edge Flange, Hem, Flatten/Fold, Flat DXF); Base Flange mode in the
  sketcher (T, bend R, K, relief type / ratio, reverse); flange / hem PropertyManager with live BA; viewer chip
  Folded / Flat pattern with flat size; tree Flat-Pattern node with the bend table; Files tab flat DXF.
- Drawing Studio: sheet 2 = flat pattern (`drawing/flat.py`: outline at a standard scale, bend centre lines + labels,
  overall size, bend table, BA / K notes; SVG / PDF / DXF with the outline in model space at true size); sheet switcher
  and downloads in the UI; `drawing.json.flat_pattern`.
- Manufacturing Advisor: a part with a sheet model is sheet metal of its T; SHM-03 flat size + bend count, SHM-04
  flange < 4·T, SHM-05 R < T (warnings, advisory); sheet cost line from the flat blank / outline / bends.
- Agent prompt: Sheet metal section; scrub hides `fw.base_flange/edge_flange/hem/sheet`; Benny's practice note now
  uses the tools.
- Fixed on the way: `runner.finalize()` rewrote status.json non-atomically (an HTTP 500 on `/recognition` seen in the
  walkthrough while it ran).

### Verified how
- `tests/test_sheet_metal.py` (15): flat lengths vs hand formulas (bend deduction form for 90°, 60° material outside,
  120° bend outside tangent, 135° inside, K ∈ {0, 0.33, 0.44, 0.5}, ΔK shift = θ·ΔK·T, U-channel + return flange, hem,
  relief areas, hole after flanges), folded bbox / volume, DXF layers / perimeter / notes, Studio lifecycle (thickness
  edit re-resolves the flange, suppress, 422s, clean error for a non-sheet edge), a sheet model script passing
  CHK-02/03/04/05/07/08 (determinism), drawing sheet (CHK-12 on sheet 1, flat DXF true size), DFM rules, scrub.
- Browser walkthrough (puppeteer-core, port 8831, throwaway data dir): base flange 100×60×2 → 12 000 mm³; flange 25 mm
  → flat Y 81.524 (formula 81.5239); 45° outside flange on the now-56 mm edge; hem; folded bbox 111.44×60×25, gating
  checks pass; flat 114.78×92.43, bends UP 90° R2 BA 4.524 / UP 45° R2 2.262 / UP 180° R1 5.906; flat.dxf 200 with
  UP/DOWN layers; drawing CHK-12 passed, flat sheet 2:1, 3 bends; Advisor SHM-03 + SHM-01 (hem R1 below the steel
  table, correct). Screenshots 01–08 reviewed; one HTTP 500 (finalize race, fixed above).
- Gate: ruff clean; web tsc, 121 vitest, vite build OK; targeted pytest (sheet metal, manufacturing, drawings,
  drawing depth, studio ×3, agent, io round-trip, office: 195 passed; `test_datasheet_shots_go_stale_and_requeue` failed once under load and passed alone).

### Not done / limitations
- No automatic corner relief / closed corners (adjacent flanges just touch), no sketched bend, jog, miter flange,
  flanges on curved edges or partial edges other than end offsets; holes through a bend are not in the flat.
- The main drawing sheet draws the folded part as before; the flat pattern is a separate sheet.

### Next
- Merge `wip/sheet-metal`; then corner reliefs and sketched bends if the founder wants more sheet-metal depth.

### Decision required
- PD-60 (sheet-metal defaults: K 0.44, R = T, 4·T flange rule, position conventions).

---
## 2026-11-18 (z) — Design Office Phase 6: gearbox layout, review gate, change notices, motion check (CD-022…025, ASM-011, ASM-022)

Branch `wip/office-phase6` (worktree `fw-wt/office-phase6`), WORKLIST row 27. Report: docs/reports/design-office.md
Phase 6. PD-61. No live model calls (PD-41 / PD-48): simulated agents only.

### Done
- CD-022 gearbox layout: shafts in bearings with meshing gears run along +Y in the housing's side walls (seat per wall),
  caps coaxial over the seats with tapped screw holes, cover = lid on a tapped rim, gear cavity; `ax` features in a
  canonical frame (`frames.CANON`) reuse the Z code in placeholders, conformance, Fitz's mates and GD&T; bearings are
  seated with their Z along +Y; tapped holes become one thread note per size on drawings.
- CD-023 optional per-part review gate; CD-024 change notices after release (ECN, Rev B pack with diff, write-once
  packs); ASM-011 / CD-025 motion range check (Assembly Studio joints + program joints from the ICD, scrubber);
  ASM-022 faster interference / clearance screening. (Items 2–4 built in parallel forks, merged on the branch.)
- Fixes found by the walkthrough: one tapped-hole note per interface crowded the housing sheet (CHK-12) → one note per
  thread size; the issue sheet's revision table over the title block met the housing's top view at every scale →
  the layout now tries the table in the top-right, then a narrower one in the top-left corner; `POST .../release`
  without a body crashed (500) → empty body defaults; Fitz re-integrating a level duplicated seated / binned parts →
  removed before placing again.

### Verified
- New tests: `tests/test_office_phase6_layout.py` (5: hand-checked positions, caps that can't fit, Y-feature defects,
  simulated gearbox end to end with 0 clashes, revision table placement), `tests/test_office_phase6_review_ecn.py` (5),
  `tests/test_assembly_motion.py` (10); vitest office `icd.test.ts` (axis labels, axis chips), assembly `motion.test.ts`.
- Gate: ruff clean; office suites 71 passed (11 min); assembly + drawings 80 + 57 passed; tsc clean, vitest 126 passed,
  vite build ok.
- Walkthrough (puppeteer-core 25.18.1, port 8840, throwaway data, simulated agents, 0.3 s steps): standard gear reducer "Gearbox GB-6" (3:1, review gate on), 16 tickets. ICD: 11 interfaces, 10 along Y (2 bearing seats 6205 x 2 in the side walls, 2 shaft fits, a DIN 6885 key 8 x 7, 4 cap joints M4 tapped, the 18/54 mesh) plus the M6 lid joint; placeholder assembly 7 placeholders, 21 mates, 0 clashes (shafts through the walls, caps coaxial, lid on top). Review gate: every part stopped in review; one 'Request changes' note reached Mill and the base came back; the rest approved; parts integrated in 195 s of simulated work: 7 real parts, 53 mates, 8 fastener stacks, 0 clashes; 4 bearings seated with their Z along +Y. Motion: 2 shaft revolutes + the mesh (-1/3), 'No collisions through Input shaft rotation 0-360 deg in 24 steps' in 46 s. Release Rev A: 7 parts tagged "GG6 Rev A", pack 6.8 MB. ECN-001 (Output gear): Gage escalated the simulated rework after 3 rounds (a reason with a size the fake designer can't follow), the engineer approved it by hand; only the gear was redrawn and re-screened; Rev B: 1 part revised (GG6-11 A -> B), 6 unchanged at A, BOM / ICD unchanged, pack 2.8 MB; the Rev A pack downloaded byte-identical (SHA-256) afterwards. 0 console / page errors. Scripts and screenshots: docs/reports/design-office/phase6/ (layout_*, review_*, motion_*, ecn_*; office6_walkthrough.mjs, ecn_finish.mjs, motion_walkthrough.mjs).
- Found by the walkthrough and fixed: one tapped-hole note per interface crowded the housing sheet (CHK-12) -> one note per thread size; the issue copy's revision table over the title block met the housing's top view at every scale (release refused) -> the layout tries the table in the top-right, then a narrower one in the top-left corner; a release POST without a body answered 500 -> defaults; a part the engineer approved by hand kept its 'needs you' status after Fitz integrated it -> cleared on integration; Fitz duplicated seated / binned parts when a level was integrated again -> removed first.

### Not done / limitations
- One gear stage per housing row, no split housing, flat caps; Gage doesn't check tooth phase; ECN BOM diff by name;
  motion joints relative to ground only. Details in the report.

### Next
- Merge `wip/office-phase6`; then a live multi-agent run (PD-48) when the founder approves token use.

## 2026-11-18 (v) — Engineering hygiene: IO round-trip matrix, licence audit + SBOM, agent run record, repeatability (IO-008, LEG-002, AGT-009, EVAL-008)

Branch `wip/eng-hygiene` (worktree `fw-wt/eng-hygiene`). Reports: docs/reports/io-roundtrip.md,
docs/reports/repeatability.md, docs/legal/LICENSES.md. PD-56. No live model calls (PD-41): replay and fakes only.

### Done
- IO-008: coordinate/unit round-trip matrix with an asymmetric off-origin analytic fixture (block + corner boss +
  hole): part STEP (unit entity, exact bbox/volume/feature), STL, 3MF (unit), GLB (metres, +Y up, mapped back), drawing
  DXF ($INSUNITS, true size, no mirror via the hole-minus-boss vector), .fwpart export → install → rebuild, assembly
  STEP (rotated + moved instance against hand transforms), Print Prep STL/3MF writers and inch uploads. Meshes are also
  checked for a positive signed volume (mirror detection). Readers written from the format specs (`tests/io_helpers.py`).
- Bugs fixed: (1) `.fwpart` import verification compared sizes/counts only, so a translated or mirrored rebuild was
  reported "Identical": `native.part.compare` now takes `placement()` (bbox corners + centre of mass) and the import
  route passes it; (2) the OCP version was recorded as "unknown" in build status, `.fwpart` manifests and the
  pipeline (installed wheel is `cadquery-ocp-novtk`). Noted, not changed: assembly STEP leaves of one product share
  its name after re-import (positions correct).
- LEG-002: `scripts/sbom.py` (offline; uv.lock closure with environment markers for Linux/Windows targets + installed
  metadata; npm lockfile) writes CycloneDX 1.5 SBOMs for the server (120 packages) and web (277) plus `licenses.json`;
  classes permissive / weak / strong / network copyleft / proprietary / unknown (OR = best option, AND = worst);
  bundled native libraries listed (OCCT LGPL-2.1+exception, FreeImage, LibRaw, FreeType in the OCP wheel; Claude Code
  CLI in the agent SDK); allow-list with usage notes; `docs/legal/LICENSES.md`. No GPL/AGPL dependency.
- AGT-009: `agent/runrecord.py` + session hooks: every turn writes `.fw/runs/<run id>/run.json` (id = the AgentRun
  metering row when the app runs it): prompt hash + redacted excerpt (policy), model requested/used, app/Python/SDK/CLI/
  build123d/OCP/Toolbox versions, tokens (agent's turn total + per-response sum, repeated responses counted once), cost
  (agent report, list-price estimate, live meter), timings (connect, first response, builds, other tools, model API,
  total), tool calls by name, per-build verdicts, final checks, outcome. Super-admin endpoints list/read them; nothing
  reaches the chat stream, the files endpoint or exports. Failed turns are recorded too.
- EVAL-008: `aicad repeat` (`eval/repeat.py`): same prompt N× (default 5) in fresh workspaces; fake (default) / replay
  / live (explicit flag + confirmation); report.json + report.md with per-metric statistics, check pass rates,
  identical-to-modal share and a verdict.

### Verified how
- New tests: test_io_roundtrip (10), test_sbom (4), test_run_record (6, replay cassette with hand-written usage; app
  route + admin-only access), test_repeat (5: fake ×5 identical; replayed ×5 with known thicknesses → volume stdev
  exactly 4000 mm³). Targeted suites re-run: native formats, AI quality, agent, assembly, drawings, print. ruff clean.
  Web not touched (no tsc/vitest/vite needed).

### Not done / limits
- No UI for run records (API only); Mesh Studio (Blender) exports not in the IO matrix (IO-008b); live variance not
  measured (needs PD-41 approval); licence findings are engineering readings, counsel still needed (LEG-003/004).

### Next
- Merge; then a God-mode "Runs" panel on the admin console if wanted; IO-008b when Blender runs in CI.

---
## 2026-11-18 (w) — Studio intelligence: agent fills the PropertyManager (DS-035), change impact preview + living datasheet pack (ASM-018)

Branch `wip/studio-intel` (worktree `fw-wt/studio-intel`). Report: docs/reports/studio-intel/README.md. PD-57.

### Done
- DS-035: new ```fw-edit``` block (`src/aicad/agent/edits.py`): fillet / chamfer / shell / Hole Wizard, an edit of one
  existing hand-made feature, or declared parameters. Targets are side keywords (outer loop of the outermost flat face)
  or points from the [Selected ...] lines, resolved on `out/topo.json` and validated by `studio.validate_feature`;
  malformed or unusable blocks are dropped with a plain note, never shown raw. The session publishes an `edit` event;
  the Studio opens the real PropertyManager pre-filled with the targets selected/highlighted (`studio/agentEdit.ts`,
  re-finds targets by position if the model was rebuilt) or the new "Modify dimensions" PM for parameters; OK goes
  through the normal manual-feature / parameter endpoints. Prompt section "Small edits: hand them to the
  PropertyManager"; short build prompts carry a hidden one-line `[Design state for quick edits: ...]` so no file read
  is needed. `hello` SSE event carries the backlog size, so only a fresh edit auto-opens. "Undo this change" is only
  offered for turns that built. Fixed a race where a quick reply's selection was cleared by the chat's own send.
- ASM-018: `POST /api/m/assembly/impact/{project}` (`src/aicad/assembly/impact.py`): trial source
  (`studio.trial_source`, `projects.rewrite_params` extracted from the parameter edit) built in a scratch folder on the
  warm worker, snapshotted under a temporary `x_` part key, every using assembly copied in memory, refs remapped +
  re-solved as a refresh would; reports mates that break / follow, parts that move, fastener stacks to refit,
  new / grown / resolved clashes (exact booleans on pairs involving the part or moved parts), Design Office programs
  using the part, datasheet shots. Nothing committed; trial files removed. UI: impact panel on OK in the
  PropertyManager, Modify dimensions and the Params tab ("Apply anyway / Back"), and in the agent's chat card.
- Living datasheet pack: per-project shot list in Mesh Studio (Datasheet tab: add current look, stale per shot,
  "Re-render stale" queues only), Studio header chip "n renders stale · Re-render".

### Verified how
- `tests/test_studio_intel.py` (9): block parse / side keywords / outer loop / points / validation errors / params /
  edit existing feature / design state; replayed "add a 2 mm chamfer to the top edges" = 1 turn, 0 tool events, model
  unchanged; end to end through the app with the analytic volume 24000 − (400 − 32/3); impact on the fixture
  assembly: HOLES 4→0 = 1 mate breaks + new clash 90π mm³, T 10→12 = block moves 2.000 mm, 10×10×3 boss = 300 mm³
  clash, model / assembly / part cache untouched; datasheet shots stale → queued (fake render) → stale after a revision.
  vitest `studio/agentEdit.test.ts` (4).
- Targeted pytest: test_studio_intel, test_agent, test_ai_quality, test_studio, test_studio_fixes, test_assembly,
  test_mesh, test_platform: 219 passed (re-run after the last fixes: intel + agent + ai_quality 46 passed). ruff clean,
  tsc clean, vitest 121 passed, vite build OK.
- Browser walkthrough (puppeteer-core 25.18.1, port 8821, throwaway data dir, replay cassette): 6 screenshots in
  docs/reports/studio-intel/, 0 console/page errors. Found and fixed from it: chat sends with Ctrl+Enter (script);
  the agent's chamfer opened with no edges selected (send cleared the selection after the reply arrived);
  "top edges" included the 4 hole rims (now the outer loop only).
- No live model call was made (replay only).

### Not done / limitations
- Impact runs only when the part is in an assembly; Studio's typed commands (Ctrl+K) and tree suppress/delete/reorder
  don't preview impact yet. A part dropped from a Design Office program's assembly shows in the program list only.
- fw-edit does not cover extrudes, sketches, patterns, drafts or several features in one block.
- Re-render needs Blender on the server; nothing re-renders automatically on revision.

### Next
- Founder try-out on a real assembly; extend impact to tree actions and typed commands; one live agent run to confirm
  the model prefers fw-edit for small requests (PD-09 subscription, a few hundred tokens).
## 2026-11-18 (x) — Drawing depth: cosmetic threads, detail views, GD&T, ICD datums, STEP → drawing (CAD-027, DRW-011, DRW-013, DRW-016, CD-021)

Branch `wip/drawing-depth` (worktree `fw-wt/drawing-depth`). Drawing Studio VERSION 1.1.3 → 1.2.0. PD-58 (may be renumbered at merge).

### Done
- CAD-027 cosmetic threads: `aicad/threads.py` (ISO 261/262 table, ISO 724 sizes, ISO 965 classes, callout text); hole features carry
  `thread` (Hole Wizard "Cosmetic thread" toggle; on by default for Tapped; also on Simple holes); new Studio feature **Cosmetic Thread**
  (Features ribbon) on any picked cylinder, internal / external from the face; agent helper `fw.thread(...)` (prompt + scrub). Threads
  follow hole patterns, feature patterns and mirrors. `status.json.threads`, feature-tree params, STEP header lines + `part.threads.json`
  (deterministic, CHK-07/08 untouched).
- Drawings: thread callouts "2X M8×1.25-6H ▽12" / "Ø6.8 THRU", designation in place of a turned Ø, ISO 6410-1 marks (3/4 root circles,
  root + limit lines), thread note.
- DRW-011 detail views (Annotate tab: radius, scale, pick the centre on the sheet).
- DRW-013 GD&T (Annotate tab: datums and frames attached to a dimension / callout or a picked point); only as entered; ISO 1101 rules;
  line-work symbols in SVG/PDF/DXF; CHK-12 sub-checks `gdt` and `details`; edits API validates datum references (422).
- CD-021 Ortho part sheets get ICD datums / frames (`deliverables.icd_gdt`, part frame from Gage), labelled from the interface spec.
- DRW-016: Drawing Studio "Drawing from a STEP file"; imported sheets are all inferred with a note and an app banner.

### Verified
- `tests/test_drawing_depth.py` (16 tests, hand values: ISO 261 pitches, ISO 724 minor Ø, callout strings, drill volumes, thread
  instance positions incl. circular pattern, STEP header line + byte determinism, 3/4 arcs at r = 3·s, external root gap 2·d3·s and
  thread length 25·s, detail clip chord 8 and 120° arc, scale rules, nothing GD&T by default, ISO 1101 refusals, ICD bracket rules +
  quarter-turn transform, imported sheet all inferred, API 422 / round trip, Studio API thread → status + STEP).
- Targeted suites green (drawings, drawings_2d, studio, studio_fixes, library, office*, handoff, release, agent); ruff; tsc; vitest
  117; vite build.
- Browser walkthrough (studio-e2e, port 8812, scratch data, puppeteer-core 25.18.1): Hole Wizard thread toggle, Cosmetic Thread PM,
  thread callout on the demo plate sheet, detail view by pick, datum A by pick + position frame on the tapped callout (CHK-12 passed),
  STEP file → drawing with the inferred banner (CHK-12 passed). Screenshots: docs/reports/drawing-depth/01…08. 0 console errors.
  Found and fixed in the walkthrough: a 5:1 detail that did not fit pushed the sheet to 1:100 (now a smaller enlargement is tried
  first); the detail letter blocked a callout leader (letters are now placed after callouts, on a free diagonal).

### Not done / limitations
- No dimensions inside detail views; thread marks are not repeated inside details.
- GD&T: no composite frames, datum targets or all-around; ICD frames only for bolted-joint holes (position) and mounting faces
  (flatness); keyways / dowels / gear meshes add none.
- Threads: metric ISO only (no UNC/UNF, pipe threads); internal side views keep plain hidden lines; threads on non-principal axes are
  listed as not drawn.
- DRW-016 acceptance needs a pilot rating (status In Progress).

### Next
- Per-dimension ± tolerances (DRW-012) so GD&T and size tolerances sit together; dimensions inside detail views.

---

## 2026-11-18 (u) — Design Office Phase 5: deliverables, release, calibration, timeline (CD-014, CD-015, DRW-014, CD-018…020)

Branch `wip/office-phase5` (worktree `fw-wt/office-phase5`). Report: docs/reports/design-office.md, Phase 5. PD-55.

### Done
- CD-014: Ortho / Smithy deliverable tickets after integration (drawings per part with ICD spec values, assembly
  drawing with BOM table + balloons = DRW-014, program BOM, DFM summary with relative cost index); one "Release
  program" action (per-part release gate shared with the Studio route, tags "<KEY> Rev A", one hashed pack with STEP
  per part + assembly STEP, PDF/DXF drawings, BOM CSV, DFM, ICD, .fwprog); Release gate real; Deliverables tab.
- CD-015: work / wait segments per ticket, bounded EMA calibration per family persisted per org (live / simulated
  profiles), plans snapshot the rates; Timeline tab (planned vs actual, critical path, agent lanes, waits, CR
  markers), calibration panel, estimate vs actual in the drawer.
- Phase 4 follow-ups: bearing seats (6000/6200), DIN 6885 keys, ISO 8734 dowels, quarter-turn part frames, coaxial
  bearing stacks, size-based spacing (CD-018); frame-tolerant Gage with the transform reported and used by Fitz
  (CD-019); Assembly Studio's lock shared with the office + "updating" banner (CD-020).
- Found in the walkthrough and fixed: (1) a gear's ICD envelope was its pitch circle, so every real gear "left its
  envelope" (now the tip circle; placeholders stay pitch cylinders); (2) two real gears at the exact centre distance
  collided (both Toolbox gears have a tooth on +X): the second gear of a mesh now gets a tooth phase (half a tooth),
  its keyway turning with it; (3) Drawing Studio read the faceted involute flanks as ~120 "chamfers" and the gear
  sheets failed CHK-12 (drawing VERSION 1.1.3: facet legs < 0.1 mm or more than 6 chamfer sizes are not
  chamfers); (4) the BOM listed a bearing twice when two tickets share one Toolbox bearing; (5) "bearings / pins"
  wording; timeline axis label wrap; rates shown to 3 decimals.

### Verified how
- `tests/test_office_phase5.py` (9 tests, fake agents), Phase 3 / 4 office suites, `tests/test_drawings.py` (28),
  vitest `office/timeline.test.ts` (7). Full gate after merging main: pytest 573 passed (22 min, machine shared with
  other work), ruff clean, tsc clean, vitest 117 passed, vite build OK.
- Browser walkthrough (puppeteer-core 25.18.1, port 8805, throwaway data dir, `FW_OFFICE_FAKE_AGENTS=1`, 1.2 s
  steps, God mode paywall/token bypass): standard-planner gear reducer "Gearbox GB-3" (14 tickets: housing base,
  cover, 4 bearing caps, 8 cover bolts, input / output shafts in 6205 seats, pinion 18 / gear 54 keyed, bearings)
  → ICD review (13 interfaces incl. 2 bearing seats and a key) → placeholder assembly (7 placeholders, 23 mates, 0
  clashes) → Run → every part swapped in, 0 clashes, bearings seated by Fitz → Ortho 7 sheets (CHK-12 pass after the
  gear fix) + assembly drawing 1:5 with 14 BOM lines / 14 balloons → Smithy 7 parts → Release rev A from the UI: 7
  parts issued and tagged "GG3 Rev A", pack 31 files / 6.9 MB downloaded (200, application/zip) → timeline (by ticket,
  by agent) and calibration panel → drawers (estimate vs actual). 0 console / page errors. Screenshots:
  docs/reports/design-office/phase5/. Server stopped, scratch data deleted.

### Not done / limitations
- No live AI run (PD-48): calibration learned only in the simulated profile. Layout is still a row with vertical
  shafts (bearing caps are row stations, not coaxial caps). Assembly-drawing balloons anchor at bounding-box centres.
  Interference checks with seated ball bearings take minutes on this machine (OCCT booleans on many balls).

### Next
- Live multi-agent run (PD-48); horizontal-shaft architecture with caps in side walls; GD&T from the ICD datums on
  part sheets.

## 2026-11-18 (t) — Design Office Phase 4: skeleton + ICD, placeholders, swap-in, change requests (CD-010…013)

Branch `wip/office-phase4` (worktree `fw-wt/office-phase4`). Report: docs/reports/design-office.md, Phase 4.

### Done
- CD-010 skeleton + ICD: deterministic layout engine (`office/icd.py`, datums A|B|C, roles block / shaft / hub / gear,
  hole patterns, shaft/bore ISO 286 fits, seating faces, gear meshes, validity incl. ISO 7089 washer spacing); the
  "Architecture and interfaces" gate is real (edit numbers, approve; Run waits for it); ICD page (table, detail,
  measured rows, history, CRs); ICD excerpt + `fw-icd` block in the specialist prompt; Gage's deterministic ICD
  conformance measurement (`office/conformance.py`) replaces the lexical size check for ICD programs.
- CD-011 placeholders (`assembly/placeholder.py`, worker op), program assembly built at ICD approval (sub-assembly
  documents + nested final), mates by interface name, swap-in on Gage approval (same instances, mates re-attached,
  interference re-run, clashes → Changes requested on the part), level integration fits bolts into the ICD joints.
- CD-012 change requests (agent `fw-change-request` block or engineer): Archie's rule + optional AI note; ICD
  versioning; affected tickets reopened with the delta; placeholders regenerated; CR lane on the board.
- CD-013 live program assembly view (Assembly tab): translucent placeholders, solid real parts, fitted drop + glow,
  clashes, explode, per-item tooltip.
- ASM-021 nested sub-assemblies in Assembly Studio (copy with a link; insert / refresh / remove; tree sections;
  STEP sub-assembly nodes). Merged main (collaboration, native formats): `.fwprog` import keeps the ICD and asks for a
  rebuild of the program assembly; `.fwasm` export of an assembly with placeholders is a clear 409.

### Verified how
- `tests/test_office_icd.py` 18 tests (hand-checked layout, ISO 286 limits, conformance on fixture parts with measured
  values, placeholders, assembly from placeholders, swap-in keeps every mate, CR accept / reject / AI reject, rule
  unit, tenant isolation); Phase 2/3 office suites updated and passing; vitest `office/icd.test.ts` 6 tests.
- Full gate after merging main: pytest 563 passed, 1 failed (the budget test: the new washer rule rejected the layout's own 4-hole M3 pattern on a 30 x 20 block, so the generator now picks 2 holes / a larger PCD when washers would overlap; office suites rerun: 53 passed); ruff clean; tsc clean; vitest 110 passed; vite build ok.
- Browser walkthrough (puppeteer-core 25.18.1, port 8804, throwaway data dir, `FW_OFFICE_FAKE_AGENTS=1`, 1.2 s
  steps): program → ICD review + edit form → approve → placeholder assembly (4 placeholders, 7 mates by interface name,
  0 clashes) with tooltip → Run → CR-1 (IF-01 Ø6.6 → 7) accepted, ICD v2 → parts swapped in (glow) → complete: 4 real
  parts, 39 mates, 4 fastener stacks, 0 clashes; exploded; ICD history v2; final assembly nested in Assembly Studio
  (Base / Drive sections, fully positioned, 18 free spins); phone width. 0 console / page errors. Screenshots:
  docs/reports/design-office/phase4/. Fixes from the screenshots: cramped card header + stale "fitted" chip, stale
  assembly summary, live view missing refreshes in an event burst, an integration that finished while a CR reopened
  its parts (now goes back to the backlog). Server stopped, scratch data deleted.

### Not done / limits
- No live AI run (PD-48). Conceptual layout only (translations, row of stations); no bearing / key / dowel interfaces;
  the office does not take Assembly Studio's per-document lock. See the report's Limitations.

### Parked
- PD-54 (Phase 4 defaults).

### Next
- Phase 5: drawings and release from the ICD (CD-014), richer layouts and interface kinds, calibration (CD-015).

## 2026-11-18 (s) — Collaboration: teams, permissions, sharing, branches, merge requests (branch wip/collab)

**Done** (PLT-010, PLT-017 review queue part, PLT-020…024, CAD-062):
- Teams (Team page → Members | Teams): create/edit/delete, colour, members with team roles admin/editor/viewer.
- One permission module (`src/aicad/platform/collab/permissions.py`): none/read/comment/edit/admin = max(workspace
  baseline, owning-team role, grants), owners/admins always admin, viewers capped at comment, guests capped at edit and
  never run the agent. `projects._project` delegates to it with the level taken from the HTTP method unless given, so
  every project router (Studio, library, modules, native export) is covered; module `_project` helpers delegate;
  project lists, search, recent revisions, module pickers and export-all are filtered. Permission changes are audited.
- Sharing: Share dialog (people/teams/levels, general access, owning team, protect main), guests by email (reuses the
  invite flow, role "guest", no seat), read-only links (HMAC-signed id, revocable, optional expiry) opening a public
  viewer `/share/:token` (3D, parameters, checks, revisions, drawing), Shared with me on Projects, lock chips on cards.
- Collaboration in the Studio: branch picker + presence avatars (SSE) + Share in the CommandManager tab row, Activity
  tab (comments with @mentions → notifications; activity feed from the audit log + agent runs, per branch), soft lock
  banner ("Ada is editing main (design agent running)" → Work on my own branch), View-only chip + locked commands.
- Branches: main = existing workspace/history (no data moved); a branch is a sibling copy-on-write workspace forked
  from any revision; the active branch per person/project is a cookie resolved by `workspace_for`, so all existing
  endpoints work on branches unchanged; agent sessions keyed per branch.
- Merge requests: page with 3D compare (main vs branch), parameter table (base / main / branch), feature and change
  lists, checks, reviews (approve / request changes with note), discussion; fast-forward or 3-way (parameters per
  name, manual features per id, source merge3 with parameters masked); conflicts side by side with take main / take
  branch / design-agent proposal (optional, token-metered, faked in tests); rebuild + gating checks or refused;
  protected main needs approvals; tags for releases on main.

**Verified how.** `tests/test_collab.py` (13 tests: merge engine, additive migration on a pre-collab database,
team CRUD, permission matrix, guest invite + read-only link + revoke + expiry, presence/comments/mentions/activity,
branch isolation + soft lock + fast-forward + 3-way + refusal on failing checks, conflicts + reconcile (fake) +
protected main + source conflict + tags), `web/src/lib/collab.test.ts` (12 vitest). Full gate below. Browser
walkthrough (puppeteer-core 25.18.1, port 8803, throwaway data dir, two people in two browser contexts + an anonymous
one): owner creates team "Drivetrain", makes the demo plate team-owned, protects main, creates a read-only link;
Ada (engineer) opens the part (owner sees her avatar; protected-main banner), works on a copy `ada/thicker-plate`,
changes thickness 10 → 12 (branch only; main still 10), opens merge request !1; owner opens it, 3D compare shows
+18,926 mm³ added / 0 removed, approves, merges (fast-forward) → main bbox 120 × 80 × 12, checks ok; activity feed
lists branch/edit/MR/approve/merge; the anonymous link shows the viewer read-only (write via link 403, project API
401). 0 console errors in the final runs. Fixes made from the walkthrough: compare output folder on branches
(and a shorter compare path for long Windows data dirs), agent gate on protected main, MR title capitalised, inline
review note instead of a browser prompt, approve disabled after approving.

**Not done / limits.** Team ownership covers parts only (assemblies, 2D drafts, renders, Design Office programs stay
workspace-scoped, PD-53); presence and locks are in memory (one app process); "their edits go to their own branch"
is offered (409 + one click), not automatic; guests have no workspace home page (they land on the shared part and
Projects → Shared with me); the review queue's part-catalogue columns (rest of PLT-017) are still open; no live
design-agent reconcile was run.

**Parked:** PD-50 (guest billing), PD-51 (permission defaults), PD-52 (branch/merge defaults), PD-53 (team
ownership scope, presence scale).

**Next:** guest landing page; team ownership for assemblies and Design Office programs; review-queue page across
projects ("merge requests waiting for me").

## 2026-11-18 (r) — Coordinator summary of the autonomous run (handoff)

Founder away; work run as parallel agents in git worktrees, merged + pushed one by one.
- Merged today: punch-list reconciliation (20 rows closed with evidence, 8 superseded); Design Office plan, names
  (Archie, Mill, Chuck, Axel, Benny, Molly, Hex, Fitz, Gage, Ortho, Smithy), phase 2; smart assembly (ASM-010/019);
  DS-036 shop-floor status, DS-037 Discuss mode; AI quality (CAD-028, AGT-002, AGT-006, EVAL-003 harness);
  UX-019 sidebar; UX-020 landing v1; UX-021 /why page; MSH-013 AI Render Studio; DRW-017 2D drafting; Mesh fixes.
- Founder decisions recorded: landing page is launch-state marketing (no coming-soon labels; own icon tiles until
  vendor logo permission, PD-42); push after every merge (CLAUDE.md + memory).
- Parked: PD-35…PD-46 (see DECISIONS).
- In flight: office phase 3, landing hero v2 (gearbox story, phone + tablet, CAD section), PWA + mobile,
  native file formats in every module, collaboration (teams, permissions, sharing, branching).
- Known flakes under machine load: warm-worker test, some Blender/mesh render tests — pass when run alone.
## 2026-11-18 (r) — Native Formwright files for every module (IO-020…IO-025), branch wip/native-formats

**Done.** One shared container (`src/aicad/native/`): deterministic signed zip, `manifest.json` with `kind`, sha256 of
every entry, per-workspace HMAC signature, format versions + migration hook. Formats: `.fwpart` (full parametric
model), `.fwasm` (parts embedded once, linked by fingerprint on import), `.fwdrw` (model drawing or 2D draft),
`.fwprog`, `.fwrender` (Mesh Studio / AI Render), `.fwmfg`, `.fwcalc`, `.fwprint` (part setup or uploaded mesh),
`.fwread` (Image-to-CAD), plus "Download all" (zip of .fwpart). API `/api/native/*` (`mod_native.py`,
`native_modules.py`). Import: untrusted-input validation, tripwire + strict allow-list for foreign scripts, rebuild in
the workspace's build worker, fingerprint comparison → "Verified identical" / differences / exact read-only fallback.
UI: import dialog for every Formwright file (Home drop zone, Projects page Import + drag-drop, New project dialog,
every module's "Open .ext"), "Save .ext" in every module header (shared `ModuleHeader`), Studio Files panel .fwpart
with options + import provenance, `/app/open-file` route for the PWA file handler. Spec: `docs/FORMATS.md`.

**Verified.** `tests/test_native_formats.py` (9 tests: container/zip-bomb/path attacks, determinism + signature,
migration hook, script gate, part/assembly/drawing/program/archive round trips into a second workspace, tamper and
malicious re-packs, fallback, all 8 module kinds); vitest `web/src/lib/native.test.ts` (6). Browser walkthrough
(puppeteer-core 25.18.1, port 8802, throwaway data): workspace A saved Demo Mounting Plate .fwpart, an assembly
(plate + L bracket, coincident mate) as .fwasm and a Manufacturing Advisor report as .fwmfg; a second account opened
each: part "Verified identical" (volume 89,663.758238 mm³, 23 faces, 56 edges both sides), parameter Length 120 → 130
rebuilt and verified (97,653.758 mm³); assembly both parts verified, same placement, mate ok; DFM report current.
Screenshots reviewed (dialog title casing fixed; client event tracking removed: the server records exports/imports).

**Not done / limits.** Mesh exports (GLB/OBJ/STL) and `.blend` scenes are never packed; uploaded-mesh repair state
not carried; draft Save exports the last saved revision; assembly mates whose faces don't match the rebuilt part are
dropped (counted); the PWA manifest `file_handlers` entries are listed in FORMATS.md for the PWA branch to add.

**Decision parked.** PD-49 native file defaults.

---

## 2026-11-18 (q) — AI Render Studio (MSH-013, Beta, BYO OpenAI key), branch wip/ai-render

### Done
- New module `airender`: AI marketing visuals of a verified part via the OpenAI Images API (edit with the part's
  reference render) on the workspace's own OpenAI key. Refine → Review → Generate; gallery with download, variation,
  again, use prompt. Report: docs/reports/ai-render.md.
- Key stored Fernet-encrypted (server secret `FW_SECRET_KEY`, dev secret in data/), masked hint only, admin-managed,
  deletable; per-workspace consent to send the reference and prompt to OpenAI.
- Prompt refinement: deterministic template + one-shot Claude polish (no tools), geometry clause and "Avoid" list
  always enforced at send time. Entry points: Make tab, Mesh Studio header, Modules, sidebar, Settings card.

### Verified
- `pytest tests/test_airender.py` 11 pass (all OpenAI/Claude calls mocked), test_platform pass; vitest 4 new;
  ruff, tsc, vite build clean. Browser walkthrough on port 8797 with a throwaway data dir and `FW_AI_RENDER_FAKE=1`:
  0 console errors besides the deliberate rejected-key 400; screenshots reviewed and fixes made.

### Not done / blocked
- No real OpenAI call made (needs the founder's key). Punch-list id MSH-012 was already taken, so this is MSH-013.

### Decisions parked
- PD-43 (model/size/quality defaults, polish metering), PD-44 (BYO only, included with the Design Studio; platform
  key later).

### Next
- Founder adds a key and runs one real render per scene to tune prompts and ETA figures.
## 2026-11-18 (q) — "Why Formwright" buyer page (UX-021), branch wip/why-buy

**Done**
- New marketing page `/why` (`web/src/pages/marketing/Why.tsx`, lazy route in `App.tsx`; "Why Formwright" link in the shared marketing header and footer, `layouts/MarketingLayout.tsx`). Sections: hero (promise + 4 count-up stats + animated "one medium part" race card), cost of conventional work (BLS/SHRM-cited), 9 risk → fix cards, 5 worked examples with the arithmetic shown, interactive ROI calculator, hire-vs-buy, token explainer with per-token prices, FAQ, CTAs (trial / pricing / demo mailto), sources and disclaimer.
- One pure cost model, `web/src/pages/marketing/why/roi.ts`: complexity profiles, cheapest top-up combination, ROI (conventional vs Formwright labour + plan + top-ups, savings, speed-up, payback in working days), hero stats computed from the calculator's default scenario (10 medium parts/mo, US$70/h, 25 % review, Pro: 28× sooner first model, 71 % lower cost, 3.6× parts per engineer-hour, ≈ US$60k/yr), worked-example costs, hire-vs-buy. Plans and packs are read live from `/api/billing/catalog` with catalog-mirroring fallbacks.
- Motion: own reveal/count-up hooks (`why/motion.tsx`, independent of the landing components), bar transitions; everything settles to its end state under prefers-reduced-motion. Chart colours copper (conventional) vs Forge blue (Formwright), validated with the dataviz palette validator in light and dark (CVD ΔE ≥ 25, contrast ≥ 3:1); direct value labels and a legend.

**Verified how**
- `roi.test.ts`: 12 hand-computed cases (default scenario to the cent, Team offshore scenario, pack optimisation, no-payback case, worked examples, hire cost, formatting). `npx tsc --noEmit`, `npm test` (54 pass), `npx vite build` pass.
- Browser walk (puppeteer-core 25.18.1, headless Chrome) on port 8800 with a throwaway data dir: desktop 1440, mobile 390, reduced motion, dark calculator; every section screenshotted; calculator scenarios: default, 20 simple/offshore/50 % review/Team (US$956/mo saving, matches the test), 40 complex/consultancy/Pro, 2 simple/offshore/80 % review (loss case). 0 console errors, 0 px horizontal overflow. Fixes from the screenshots: single-prefix money ranges, collapsed "73–73 %", token table layout, loss-case wording, FTE workload line.

**Not done / limitations**
- Salary/rate figures are well-known public figures cited by publication, not re-fetched this session; consultancy, offshore and CAD-seat ranges are labelled estimates. Conventional hours and per-part token counts are modelled estimates, labelled as such. Parked as PD-45.
- The landing page button to `/why` is added by the landing agent (Landing.tsx not touched).

**Next step**: founder review of the copy and the default scenario; legal review of savings claims before public launch.
## 2026-11-18 (q) — 2D drafting without a model (DRW-017), branch wip/drafting-2d

### Done
- Drawing Studio: "New 2D drawing" (per org, revisions per save) with a drafting editor: draw / modify / annotate /
  dimension ribbon, ISO 128 layers, snaps + ortho/polar + typed coordinates, associative measured dimensions with
  ± / deviations / limits / fits, hatch with planar-face detection, notes, leaders, balloons, ISO 21920 surface and
  ISO 1101 GD&T frames (user-entered), datum symbols, revision table; SVG / PDF / CAD-native DXF exports; templates
  (gasket, washer, plate) and an assist that reads common requests without AI (agent fallback mocked in tests).
  Details, limits and parked defaults (DRW-PD-10..14): `docs/reports/drawings.md` §DRW-017.

### Verified
- pytest `tests/test_drawings.py` + `tests/test_drawings_2d.py` 41 passed; ruff clean; tsc, vitest 42, vite build.
- Browser walkthrough on port 8796 with a throwaway data dir (deleted): plate with holes + dimensions + tolerance +
  datum + GD&T + Ra, PDF / DXF / SVG downloads; gasket from the assist; bush half-section (fillet, chamfer, hatch,
  mirror, trim, revision preview). 0 console errors.

### Not done / next
- Dimensions to midpoints / intersections, hatch angles, user layers, blocks, DXF import into a 2D drawing; open the
  DXF in SOLIDWORKS / AutoCAD by hand. Copy DRW-PD-10..14 into DECISIONS.md when merging.
## 2026-11-18 (p) — Installable web app (UX-022) and mobile/tablet layout pass (UX-018), branch wip/pwa

### Done
- **PWA**: `web/public/manifest.webmanifest` (standalone, start `/app`, scope `/`, theme/background #23272E, shortcuts
  Projects / Design Office), icons rendered from the logo mark by `scripts/pwa_icons.py` (any + maskable 192/512,
  opaque 180 apple-touch-icon), manifest/theme/Apple meta tags and `viewport-fit=cover` in `web/index.html`.
- **Service worker** without a dependency: `web/pwa/sw.js` is a template; `web/pwa/plugin.ts` (Vite, build only) lists
  every built file (70: hashed JS/CSS, Inter fonts, icons, landing GLBs, offline page) and a content-hash build id into
  `dist/sw.js`. Cache-first for those, `/api/*` and `text/event-stream` never touched, navigations network-first with
  `offline.html` ("You're offline. Your projects are safe. Reconnect to keep designing."), which polls `/api/health`
  and reloads itself. A new worker waits; the app shows a "New version available · Reload" toast (`lib/pwa.ts`).
  In-app "You're offline" banner from `navigator.onLine`.
- **Install offer** (`components/InstallApp.tsx`, pure helpers `lib/install.ts`): one tap via a captured
  `beforeinstallprompt`; on iPhone/iPad a bottom sheet with Share → Add to Home Screen steps; hidden when running
  installed. In the account menu, sidebar footer, and a dismissible banner on phones/tablets (not on Studio/module
  pages; dismissal remembered 60 days).
- **Server** (`platform/app.py`): `static_headers()` gives explicit MIME types (Windows can map .js to text/plain) and
  caching: `sw.js`, manifest and offline page `no-cache` (+ `Service-Worker-Allowed: /`), `/assets/*` immutable for a
  year, other public files one hour; CSP adds `manifest-src 'self'`.
- **Standalone polish** (`styles.css`): safe-area padding on `#root` (graphite strips behind iOS's translucent status
  bar in standalone), no overscroll bounce in the app shell, tap highlight off, 16 px fields on iOS, `.fw-hscroll`.
- **Mobile/tablet pass** (UX-018): see the UX-018 row. Studio compact layout (bottom bar on phones, overlays on
  tablets, PropertyManager as a bottom half-sheet), touch ribbon, scrolling viewer toolbar, office board snap scroll
  with sticky lane titles, Modal = bottom sheet on phones, scrollable tab lists, tablet default icon rail,
  `DesktopOnly` for local integrations (Settings → CAD plugins). Fixed: Assembly and 3D Print canvases drew at
  devicePixelRatio× on high-DPI screens.

### Verified
- `npx tsc --noEmit`, `npm test` (49, incl. `lib/install.test.ts` 7), `vite build`; `pytest tests/test_platform.py
  tests/test_pwa.py` (33 passed); `ruff check src tests`.
- Headless Chrome (puppeteer-core 25.18.1) on port 8801 with a throwaway data dir: CDP `Page.getAppManifest` (no
  errors), `Page.getInstallabilityErrors` → `[]`, SW activated and controlling after reload, 70 files in
  `fw-static-<build>`, no `/api` entry in any cache; update flow (changed `sw.js` → toast → Reload → navigation, new
  worker active); offline (page + SW target) → offline page; back online → reloads itself.
- iPhone 14 (390×844, DPR 2, touch, iOS UA) and iPad (820×1180, touch): dashboard, drawer, install sheet, projects,
  Studio (model / features / agent, Fillet PropertyManager), Design Office home, board (scrolled), ticket sheet,
  Assembly Studio, modules, billing, settings (+ CAD plugins note), standalone (no install offer). Touch orbit, pinch
  zoom and two-finger pan change the view (CDP touch events). 0 console errors; 34 screenshots reviewed.

### Not done / limitations
- Selecting several edges/faces on touch still needs Ctrl (no modifier on phones): next step is a "tap adds to the
  selection" mode while a multi-pick PropertyManager is open.
- Drawing, Engineering, 3D Print and Mesh modules were not reworked for phones (they keep the "larger screen" note).
- No offline viewing and no app-store packaging (PD-47). `display-mode` can't be emulated over CDP; standalone was
  verified through iOS's `navigator.standalone`. Real-device checks (iOS Safari, Android Chrome) still to do.

### Next step
Touch multi-select for fillet/chamfer/shell/draft; real-device pass on an iPhone and an Android phone.

---
## 2026-11-18 (p) — Design Office Phase 3 (branch wip/office-phase3): orchestrator, part agents, Gage, Fitz, budget

**Done:** CD-006 orchestrator (Run/Pause per program, critical-path priority, concurrency cap, retry and rate-limit
back-off, restart resume, idempotent), CD-007 specialist part agents in their own Studio projects (Hex reuse first,
per-trade practice notes, milestones and machinist status lines from real session events, CAD-028 gate skipped for
approved ticket briefs), CD-008 Gage (deterministic checks + metered advisory AI note, 2 send-backs then the engineer,
no self-approval), CD-009 comments queued/delivered, priority, reassign, pause, take over / hand back, reopen, retry,
CD-016 budget warn at 80 % and stop, spend per ticket and program. Fitz integrates each level via `fitz.py`.
Board: live holder avatars, status lines, hand-off slide, Run bar, budget meter and dialog. Report:
`docs/reports/design-office.md` (Phase 3 section). Merged `main` (AI quality) first and used its `client_factory`
hook for the simulated agents.

**Verified:** `tests/test_office_orchestrator.py` 15 tests (all agents simulated, no model calls), `test_office.py`
20, vitest office 11; browser walkthrough with simulated agents on port 8798 (throwaway data, deleted), 0 console
errors, screenshots in `docs/reports/design-office/phase3/`. Full gate results in the commit.

**Not done / blocked:** no live multi-agent run (PD-48, needs the founder's go-ahead on subscription use); ICD,
placeholders and change requests are Phase 4.

**Next:** one supervised live run of a small program (3 parts) to calibrate practice notes, rate-limit wording and
costs; then Phase 4 (CD-010…CD-013).
## 2026-11-18 (q) — Landing hero: Design Office gearbox story (UX-020), branch wip/landing-hero

### Done
- **Hero rebuilt** (`web/src/components/landing/hero/`): one scripted ~52 s loop telling the Design Office story for a
  planetary gearbox PG-5 (ring fixed, sun in, carrier out; m1.5, sun 18T, 3 × planet 27T, internal ring 72T, face 12;
  i = 1 + 72/18 = 5, (18 + 72)/3 = 30, a = 33.75): (a) a detailed brief types itself; (b) Archie's product tree,
  gear-set checks, frozen interfaces, estimate, "Plan approved"; (c) a mini board where Axel, Chuck, Mill and Hex work
  in parallel with avatars, progress rings/bars and status lines ("Axel is shaping 72 internal teeth…": internal gears
  are shaped, not hobbed), Gage reviews, Hex's Toolbox parts land at 0 tokens; (d) build flash: 16 unique parts on a
  table, each stock blank machined into the real part by a sweeping cut plane, ✓ labels; (e) Fitz flies them to an
  axial exploded view and seats them bottom-up, "0 interferences", "a = 33.75 ✓"; (f) the gearbox runs: sun spins,
  planets spin and orbit inside the fixed ring, carrier/output at 1/5, output side turns to glass; readouts (5.00 : 1,
  600 → 120 rpm, 12 Nm out / 2.4 Nm in, design point) and an "All gating checks pass · STEP · BOM · Drawings · Shop
  pack" chip row. Play/pause, replay, six click-to-jump chapter chips with progress. Holds at the build chapter until
  the geometry is loaded (the 3D loads during the brief).
- `kinematics.ts`: ratio, carrier speed, Willis planet spin, planet phase φk = θk(1 − Zr/Zp) mod pitch (all 0 for PG-5),
  mesh residuals, spin-up; `kinematics.test.ts` (9 tests, hand-computed, incl. a 13/25/63 × 4 set with half-pitch phases).
- **Real geometry** (`scripts/landing_assets.py`): Toolbox spur gears (sun, planet), bearings 6204/6001/6000, SHCS M5×35,
  dowels; build123d internal ring 72T (disc minus the external-involute outline with swapped tip/root, 0.08 mm
  backlash), carrier plates with posts, planet pins, input shaft (Ø6.35 socket), output shaft (keyway), input/output
  covers (6204 seats, 140 square flange), NEMA 23 motor flange. Manifest `hero/gearbox.json` (29 instances, assembly
  coordinates). New GLB compaction: build123d exports one primitive per B-rep face (hundreds of draw calls); the script
  now rewrites each GLB as one indexed primitive with crease-aware normals: gear.glb 457 → 84 KB, all landing GLBs 1.15 MB.
- Founder direction applied: no Coming soon / Preview / Illustration / (concept) labels on the landing page (OfficeBoard
  copy now present tense, module status badges removed, FAQ rewritten). "Why should I buy this" CTA in the hero and
  "Why Formwright" nav link to `/why` (page built by another agent). New sections: **Integrates with your CAD**
  (`CadTools.tsx`, own monogram tiles; dropping `web/public/landing/logos/<slug>.svg` replaces a tile via a build-time
  glob; trademark notice) and **Formwright in your pocket** (`AppDevices.tsx`, generic phone + landscape tablet frames,
  each with its own loop: home tap → splash → chat → live 3D flange → board → "Gearbox approved ✓" toast; tablet Design
  Studio with live gear, tree, checks, chat, then the Office board; static frames under reduced motion; stacks on mobile).
- Removed the old flange hero (`HeroVisual.tsx`, `heroTimeline*`, flange-blank/bore GLBs).

### Verified
- Interference: every gearbox instance pair intersected in build123d at the assembled pose: only ≤ 0.004 mm³ tolerance
  noise at nominal fits; planet/ring and planet/sun 0 at three sun angles, 234 mm³ when a planet is deliberately
  half a pitch off (the phase formula matters). Tapped holes modelled at nominal Ø (Toolbox cosmetic-thread rule).
- `npx tsc --noEmit`, `npm test` (48), `npx vite build`, `ruff check src tests scripts`, `pytest` (335 passed; `test_mesh::test_highlight_protection…` failed under load and passes alone, known flaky Blender render, no src change).
- Headless Chrome (puppeteer-core) on port 8799 with a throwaway data dir: desktop 1440 shots at every chapter (brief,
  plan, board ×2, build ×2, explode, seating, assembled, run ×2 + mesh close-up), mobile 390 (all chapters), reduced
  motion (assembled still + six static steps), CAD and mobile sections at 1440 and 390; 0 console errors/warnings;
  no horizontal scroll. rAF rate with a GPU (headless d3d11) about 96–98 fps in build/assemble/run (swiftshader is far
  slower, so the story clock runs in real time with dt capped at 0.5 s). Fixed from screenshots: FLIP cards compounding
  transforms (layout rects now measured without the running transform), stock top-face clipping speckle, run view
  clutter (output side to glass), mobile framing (camera keyframes fit half width AND height), compact run HUD,
  mobile build labels (latest only), reduced-motion still frame rendering, phone 3D viewport mounting.

### Not done / limitations
- The story is scripted (deterministic timeline), not a recording of a live run; numbers shown are the design values.
- GLBs are not Draco/meshopt compressed (served gzipped by the app). Housing parts are simple (no fillets or seals).
- Exploded/seating framing leaves some empty space at the bottom on desktop; could be tuned.

### Next
- Merge `wip/landing-hero` after the `/why` page lands; consider meshopt compression if the asset budget tightens.

## 2026-11-18 (p) — Live landing page (UX-020), branch wip/landing

### Done
- Hero is now a scripted replay of a Design Studio session around a LIVE three.js part: the brief types itself,
  machinist status words cycle (shared `WORDS` + `MeshingGears` from ShopStatus), the feature tree grows while the
  flange builds in stages (blank → bore → 6 holes, crossfaded), the five gating checks tick PASS, then "All gating
  checks pass" and a Flange.step chip. Labelled "Replay"; caption says the part is real Formwright output.
- Real geometry: `scripts/landing_assets.py` exports Toolbox parts to `web/public/landing/*.glb` (flange stages,
  spur gear m2 z24, 6204 bearing, M12 bolt/nut/washer, M8 SHCS). `components/landing/PartScene.tsx` renders them
  (env lighting, CAD edges, turntable, drag to orbit, renders only on screen, still frames under reduced motion,
  no orbit capture on touch so the page scrolls); `LazyScene` loads three.js only near the viewport.
- Scroll tour (`components/landing/Showcase.tsx`): Design Studio (ribbon, tree, sketch drawing itself), Toolbox
  carousel, STEP import + recognition (teeth faces pulse; lines are the recognizer's real output for that gear:
  24 teeth, module ≈ 2.0, tip Ø52, root Ø43, bore Ø10, 651/651 faces), Assembly (two flanges + 6 × M12 stacks
  exploding; auto-fit arithmetic 32 + 5 + 10.8 + 3.5 = 51.3 → M12×55), Drawing (flange sheet drawing itself),
  Advisors. Design Office section labelled **Coming soon** with the 11 named agents and a looping FLIP sprint board.
- Live badges with a ping, reveal-on-scroll, hero parallax; everything settles to its end state under
  `prefers-reduced-motion`.

### Verified
- `npx tsc --noEmit`, `npm test` (32 incl. new `heroTimeline.test.ts`), `vite build`, `ruff check scripts src tests`.
- Headless Chrome (swiftshader) on port 8792 with a throwaway data dir: desktop 1440, mobile 390 and
  reduced-motion runs, screenshots at every section; 0 console errors; scrollWidth = viewport width (no horizontal
  scroll). Fixed from screenshots: tag overlaps, cropped gear on narrow stages (fit uses the narrower FOV), drawing
  label collisions, auto-fit table wrapping, sketch chip covering a dimension.

### Not done / limitations
- gear.glb is 457 KB (polyline involute flanks); loads lazily below the fold. Not Draco-compressed.
- Advisors, Drawing and sketcher panels are illustrations (labelled); only the 3D stages are real output.
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
## 2026-11-18 (p): AI quality: brief approval gate, replay provider, self-review, benchmark harness

Branch `wip/ai-quality` (worktree), not merged.

### Done
- **CAD-028 brief gate.** A new part in Build mode first gets the agent's reading of the request (fenced `fw-brief`:
  requirements, assumptions, open questions with defaults), parsed and validated server-side (`agent/blocks.py`) and
  shown as an editable card (Edit / Approve & build, `studio/AgentCards.tsx`). Building is blocked by the same tool
  guard as Discuss mode (mode `brief`). Approve sends the confirmed brief ("Approved design brief…") and the agent
  builds. Setting: Settings → Preferences → "Confirm the brief before building new parts" (default on); "Skip once"
  above the prompt for a single message. Brief runs are recorded as kind `brief`.
- **AGT-002 replay provider.** `agent/replay.py`: `ReplayClient` plays recorded turns (messages + workspace files;
  `rebuild` re-runs the real build so checks are fresh), `RecordingClient` records live turns (`FW_AGENT_RECORD`).
  `FW_AGENT_REPLAY=<cassette>` drives the app with zero model calls (development only, refused in production).
  `AgentSession.client_factory` is the injection point.
- **AGT-006 self-review.** After a build the agent emits a fenced `fw-review` (observed / uncertain, each tied to a
  CHK id or the render). The server reconciles it with `out/status.json`: the gate verdict comes from the checks;
  observed findings on a failed gate, or "all checks pass" when they don't, are marked overridden. Chat shows a
  collapsible "Self-review" with ✓ / ? / ✗ items and a checks-passed/failed pill.
- **EVAL-003 harness.** `src/aicad/eval/`: 20 original prompts (4 each: plate, bracket, shaft, flange, enclosure)
  with analytic bbox/volume/cylinder census and reference solutions; `aicad bench --dry | --replay DIR | --live
  [--record DIR] [--only …] [--yes]`; report.json + report.md (pass, first-pass, ≤3 builds, gates, tokens, time).
  Live mode prints the token estimate and refuses without confirmation.

### Evidence
- `tests/test_ai_quality.py` (9 tests): brief/review blocks valid+invalid, critique cannot pass a failed gate, guard
  denies build/write/edit in `brief`, message round-trip + cassette path safety, replayed questions turn (no files
  touched), replayed build turn (real rebuild, review gates ok), app flow brief → approve → build with a replayed
  agent (builds 0 → 1), setting off / skip once / discuss bypass, benchmark dry run (3 cases) + negative scoring.
- `aicad bench --dry`: 20/20 pass, first-pass 20/20, 31 s, 0 tokens (synthetic: validates harness + expectations).
- Browser (studio-e2e, port 8795, throwaway data dir, `FW_AGENT_REPLAY` scripted cassette, puppeteer-core 24):
  L-bracket prompt → "Brief first" line → brief card → Edit (added an assumption) → Approve & build → build
  60 × 50 × 40 mm, 23,274.8 mm³, gates pass → Self-review (3 ✓, 1 ?, "Checks passed"); Settings toggle. 0 console
  errors. Fixes from the screenshots: the per-message toggle moved out of the crowded send row; review header
  compacted for the narrow chat; expanded review scrolls into view.
- pytest full suite: 437 passed, 1 failed (`test_mesh.py::test_highlight_protection…`: a GPU render job ended
  "failed" while several agents loaded the machine; passes alone in 19 s; Mesh Studio code is untouched here).
  ruff clean, tsc clean, vitest 31 passed (+2 for the approval text), vite build ok.

### Not done / limitations
- No live agent run: the prompt additions (brief, self-review) are exercised only by replays. A real recorded
  cassette is not in the repo yet. Live benchmark not run (PD-41).
- The cylinder census counts holes and outer diameters alike (it is a census, not hole recognition).

### Decisions parked
PD-40 brief gate scope/default, PD-41 first live benchmark spend.

### Next
Founder: approve one live benchmark run with `--record` (PD-41); then commit the cassettes so CI re-scores them.

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
