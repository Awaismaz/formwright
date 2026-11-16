# Design Studio audit fixes (`polish/studio`)

Fixes for `docs/reports/audit/studio.md` (STU-01..30, IDEAs 1–5). Branch `polish/studio`, worktree
`D:\AI CAD\fw-worktrees\studio-polish`, merged with `main` at 7a539a6 (platform fixes) before the final gate.

Status legend: **Fixed** · **Partly** (what is left is listed) · **Not done** · **Handled elsewhere**.

## Findings

| ID | Status | What changed | Evidence |
|---|---|---|---|
| STU-01 | Fixed | `edgeMid` is now the arc-length middle of the edge (never an end vertex). Fillet/chamfer payloads also send `edge_refs` (line direction / circle axis). `fw._resolve_edges` picks the single nearest edge of the picked kind and direction; `fw.edges_near` returns the nearest edge per point (a corner point still returns all edges that meet there, so agent scripts and old saved features keep their geometry). | `test_one_picked_edge_fillets_only_that_edge`: 50×20×10, one edge R3 = 9980.6858 mm³ = 10000 − (9 − 9π/4)·10, also when the end vertex is sent with the edge ref. `measure.test.ts` (edgeMid). Browser: one vertical edge picked in the viewer, R3 → **9980.685835 mm³**. |
| STU-02 | Fixed | Tree rows use fixed icon slots (`invisible` until hover, nothing reflows; the eye never moves). The inline trash is gone; Delete lives only in the ⋯ / right-click menu and its toast has **Undo** (Ctrl+Z also works). | Browser: eye x = 285 before and after hover, no inline Delete visible (`04-tree-hover.png`). |
| STU-03 | Fixed | Hand picks (fillet/chamfer edges, hole points, shell/draft faces, Hole Wizard faces) store the body's box at pick time (`ref_bbox`, stamped server-side; older features get it before a parameter change). When a stored point no longer lies on a matching edge/face, `fw._remaps` carries it with the box (boundary points keep their offset from that side; others try centre offset, proportion, then side offsets) and the edge of the same kind/direction is found there. If it still fails, the change is kept and the feature is flagged (IDEA 1) instead of a 422. | `test_manual_fillet_survives_a_length_change` (block L 50→70: V = 70·20·10 − (9 − 9π/4)·10; T 10→15: removal ×1.5), `test_demo_plate_fillet_then_length_120_to_140` (the audit repro: V₁₄₀ = V₁₂₀ + 20·80·10 − 2·20·CH²/2, the corner removal unchanged). Browser: demo plate + "Corner fillets" (R3, two vertical corner edges), Length 120 → 140 and Thickness 10 → 6 both rebuilt with the fillets kept and no repairs. |
| STU-04 | Fixed | Worker: every request carries an id and the reply echoes it; lines that don't match (a late `ready`, a reply to a timed-out request) are dropped. A worker that doesn't start in time is killed and never reused; the caller gets a plain "The geometry engine is starting up. Try again in a moment." (503), timeouts a plain 504. The Studio pre-warms the worker when a project opens (`POST /projects/{id}/warm`). | `test_worker_drops_late_ready_and_stale_replies` (fake worker printing a late ready + a stale reply before each real one; slow start killed). In the walkthrough, with other agents loading the machine, one cold start ran over the limit: the user got the plain "starting up" message and the next request built normally (no desync). Start limit raised to 180 s. |
| STU-05 | Fixed | One mapping (`src/aicad/platform/plain.py`) turns kernel/Python failures into sentences: no exception or function names. Fillets that don't fit say the largest radius that does (computed with `max_fillet` in the worker), chamfer/shell say what to change. Used by manual features, parameter edits, Toolbox/STEP import; failed builds carry `error_plain` for the Checks panel. | `test_rebuild_error_is_flagged_not_blocking_then_repaired` (R23 on a 3 mm block: "…the largest radius that fits is about 2.9 mm", no "ValueError"/"max_fillet"), `test_plain_error_mapping`. Browser toast for R23 on the 50×20×10 block: "“Fillet” couldn't be built: R23 mm is too large for the selected edge(s); the largest radius that fits is about 19.9 mm. The previous model was restored." |
| STU-06 | Fixed | The Source tab is gone for users; superadmins keep it as a labelled support view, and `GET /projects/{id}/source` is 404 for everyone else. | `test_source_view_is_superadmin_only_and_undo_info`. Parked as PD (below). |
| STU-07 | Handled by platform | Token estimate / run budget / Chat cost line are owned by the platform fixer (merged from main). Not touched here. | — |
| STU-08 | Fixed | Hole Wizard (IDEA 3): clearance (ISO 273 fine/medium/coarse), tapped (ISO 261 pitch, tap drill ≈ d − P), counterbore (DIN 974-1 Ø, depth = ISO 4762 k + 0.4), countersink (ISO 10642 head Ø, 90°), or simple Ø; through or blind; placed on a picked face **4 corners at dx/dy from the edges**, **by X/Y from the face's lower-left corner**, or at the picked point. Sizes are resolved server-side from `src/aicad/holes.py` (one source, cross-checked against `engineering/standards.py`). Positions are evaluated in the kernel from the face extent, so holes follow the face when the part changes size. Live preview of every hole + the reference box. | `test_hole_wizard_corner_holes_by_edge_distance` (4×M6 clearance on 100×60×10: 60000 − 4π·3.3²·10; c'bore: 4·[π·5.5²·6.4 + π·3.3²·3.6]; c'sink: frustum + cylinder; L 100→140 moves the centres to x = ±60), `test_hole_wizard_tables_match_the_standards_module`. Browser: 4 × M6 at 10 mm → **58631.5222 mm³** (`05-hole-wizard-preview.png`, `06-holes-done.png`). |
| STU-09 | Fixed | The ribbon measures itself: full labels, then a compact labelled size, then icon-only, then a **More** menu, so no command is ever clipped. In the Studio the app sidebar starts collapsed (remembered separately from other pages). | Browser: 1600 px full labels; 1366×768 compact labelled ribbon, all 18 Features commands visible; 1100 px icon-only, still no command hidden. |
| STU-10 | Fixed | Model undo/redo over revisions: `POST /projects/{id}/undo` goes back to the revision the current one was made from (each revision now records its parent), `POST /redo {to}` re-applies an undone one only if the model is still where the undo left it. Ctrl+Z / Ctrl+Y (and Ctrl+Shift+Z), Undo/Redo buttons in the top bar, Undo on delete/suppress toasts. | `test_undo_redo_walks_the_revisions`. Browser: Hole Wizard → Ctrl+Z → 60000 mm³ → Ctrl+Y → 58631.52224 mm³. |
| STU-11 | Fixed | Enter = OK and Esc = Cancel in every PropertyManager (hints on the buttons). Studio keys: F zoom to fit, Ctrl+1–7 standard views, Esc clears selection / leaves a tool or the plane picker, ? shortcut list, Ctrl+K typed commands. The sketcher no longer reacts to keys typed in selects/text areas. | Walkthrough uses Enter to submit the fillet and repair PMs. |
| STU-12 | Fixed | SOLIDWORKS-style mouse by default: middle-drag (and left-drag) rotates, Ctrl+middle / right-drag pans, wheel zooms at the cursor. **Zoom to Fit keeps the orientation** (new `zoomToFit`). **Normal To** a selected planar face (ribbon + Ctrl+K). Orientation triad bottom-left. | Screens show the triad. View cube not added (recommendation). |
| STU-13 | Fixed | Stepped shaft, pipe flange and L-bracket demo scripts now record `fw.feature` steps (and gained labelled, limited parameters). | Demo builds: flange = Flange body / Raised face / Bore / Bolt holes; shaft = Stepped shaft / Keyway; bracket = Bracket body / Inside fillet / Mounting holes; all checks pass. Browser `01-shaft-tree.png`. |
| STU-14 | Partly | One list in build order (design steps, then hand features with a hand icon; no separate heading). Design features get **Edit parameters** (menu + double-click) that opens Params with that feature's group highlighted (matched by name). Left: a dedicated PM per design feature. | — |
| STU-15 | Fixed | No Toolbox offer when the project already has a model and the prompt is an edit (add/chamfer/fillet/drill/…); matcher penalises edits and plain blocks/plates; the card says "Replaces the current model (it stays in Revisions)"; the "— ·" subtitle is gone. | `test_toolbox_validation_and_matching` (the audit's two false positives now return no match). |
| STU-16 | Partly | Toolbox defaults to **As a new part** (new project, then opens it) when the current project has a model; "Replace this model" is the explicit alternative. Left: live 3D preview, insert into an Assembly. | — |
| STU-17 | Partly | Worker pre-warm on Studio open; chat shows elapsed time and the current step; the prompt box stays editable while the agent works. Left: queued prompts, deterministic fast path for simple edits (see IDEA 2). | — |
| STU-18 | Handled by master | Make → Drawing landing/unlock is resolved at merge by the master. | — |
| STU-19 | Fixed | Edits made without AI fold into one expandable chat line ("3 edits without AI"); Revisions shows two lines of the reason (full text on hover) and folds consecutive no-AI edits into one expandable row. | — |
| STU-20 | Fixed | "Continue with custom design" clears the prompt and attachments. | — |
| STU-21 | Partly | Previews: Hole Wizard (all holes, c'bore/c'sink outlines, reference box), linear/circular pattern instance positions, original pick markers while editing/repairing. Fillet/chamfer still show only the highlighted edges (no radius tube); shell has no wall preview. | — |
| STU-22 | Not done | Up To Next / Up To Surface / direction 2 / two-direction revolve. Recommendation below. | — |
| STU-23 | Partly | Plane picker widened (no wrapping, below the viewer toolbar). Left: swapping the ribbon to a labelled Sketch tab while sketching. | — |
| STU-24 | Fixed | Checks panel: plain titles and one sentence per check ("1 solid, valid geometry", "Watertight: every edge joins exactly two faces", "Re-imported STEP is identical (volume difference < 0.0001 %)"); raw values in the tooltip; informational note in words. | — |
| STU-25 | Fixed | Params show labels only (symbol on hover), out-of-range values turn red and are refused before sending, server range errors use the label ("Length must be between 60 and 400 mm"), chat/compare use labels. | `test_runner_exports_features_meta_mass_and_topology` still passes ("between 60 and 400"). |
| STU-26 | Fixed | Distinct icons (Revolve vs Circular Pattern, Chamfer vs display, Shell vs Shaded, Swept Boss vs Swept Cut, Lofted Cut); View tab = Zoom to Fit, Normal To, View Orientation flyout, Display Style flyout, and a projection button labelled with its action. Hole renamed **Hole Wizard**. | — |
| STU-27 | Partly | Hand-modelled parts start with `MATERIAL = "unspecified"`; status bar says "No material"; Mass panel shows "No material: pick one" and marks mass as ≈ at 6061 density until chosen. Left: Similar Parts still counts "unspecified" as a match (`components/SimilarParts.tsx` / search, outside the Studio). | — |
| STU-28 | Partly | Esc clears a measurement; the compare card sits below the viewer toolbar; the section bar no longer sits under the triad/measure card. Left: global toast position (main.tsx, platform). | — |
| STU-29 | Fixed | Inertia in fixed decimals with a unit selector (kg·mm², g·mm², kg·m²), zeros as 0, axis labels. | — |
| STU-30 | Fixed (Studio side) | "Recognise" menu: **Recognise features (free, geometric)** or **Also classify with AI (uses tokens)**; British spelling in the Studio; proper plurals ("1 face"). `recognize.py` label wording left to the AMI fixer (owner). | — |

## IDEAs

| IDEA | Status | Notes |
|---|---|---|
| 1 Repair, don't block | Fixed | A feature that no longer rebuilds is skipped, the rest builds (`fw.manual_errors`, `status.manual_errors`, agent build summary gets a `[REBUILD ERROR]` line). Tree row turns amber with the reason and **Re-pick / Edit**, **Suppress**, **Ask the agent to repair** (one targeted prompt); a banner over the viewer points to it; the PM opens with a repair note and crosses at the original picks. Adding/editing a feature that fails is still refused (plain message); suppress/delete that would break a dependent feature is refused as before. Browser: plate + "Bottom round" R6 on a bottom edge, Thickness 10 → 6: the change was kept (61 370.8 mm³), the row turned amber with "R6 mm is too large for the selected edge(s); try a smaller radius", the banner appeared over the viewer, Re-pick opened the PM with the repair note and a cross at the original pick, and Suppress cleared the flag. |
| 3 Fastener-aware Hole Wizard | Fixed | See STU-08. Edge checks shown before OK: edge distance vs 1.5 × d (EN 1993-1-8 minimum 1.2 × hole Ø quoted as context), ISO 7089 washer stays on the face, counterbore wall to the edge. Labelled as guidance, not a strength check. |
| 5 Typed commands (Ctrl+K) | Fixed | `fillet 3`, `chamfer 1`, `shell 2` run on the selection (undoable); `hole M6 x4 10 from edges` / `tapped hole M8` open the Hole Wizard pre-filled with preview; `view top`, `fit`, `normal to`, `suppress <name>`, `undo`, `redo`, `measure`, `section`. Parser has unit tests (`commands.test.ts`). No AI, no tokens. |
| 2 Agent fills the PM | Not done | Natural next step: let the agent emit a PM pre-fill (op + values + picks) through the same Ctrl+K plan path. |
| 4 Live design budget | Skipped (as briefed) | — |

## Tests and gate
- New: `tests/test_studio_fixes.py` (10 tests), `web/src/viewer/measure.test.ts`, `web/src/pages/app/studio/commands.test.ts`;
  `tests/test_library.py` gained the STU-15 regression.
- Walkthrough (port 8784, scratch data, headless Chrome, 0 console/page errors): scripts `w1.mjs`, `w2.mjs` in
  `$SCRATCH/fw-e2e-8784`, screenshots in its `shots/` folder. No live agent prompt was used.
- Gate: see "Gate" below.

## Parked decisions (defaults used)
- **PD (Source view)**: model source visible only to superadmins as a labelled support view; API 404 for others.
- **PD (Undo scope)**: Ctrl+Z walks revisions, including agent revisions (the toast names what was undone). Redo is per
  browser session and refused if the model changed since the undo.
- **PD (Suppress/delete with dependents)**: refused with the dependent's reason (as before); parameter changes and
  reorders keep and flag instead (IDEA 1). SOLIDWORKS-style "suppress children too" is a possible later option.
- **PD (Mouse)**: SOLIDWORKS mapping is the default for everyone; left-drag still rotates for trackpads. No setting yet.
- **PD (Hole edge rule)**: 1.5 × d as the shown guidance; counterbore depth k + 0.4 mm and tap drill d − P labelled "verify".
- **PD (Toolbox target)**: a new part by default when the project already has a model.
- **PD (Demo parts)**: L-bracket, flange and shaft demos gained feature steps and parameter limits (no geometry change).

## Recommendations (not done)
- STU-22 end conditions (Up To Next/Surface, direction 2, two-direction revolve) in `fw._extrude_region` + PM.
- STU-23 sketch-mode ribbon with labelled tools; STU-21 fillet radius tube and shell preview.
- View cube; mouse-mapping setting; queued chat prompts; Similar Parts ignoring "unspecified" material.
- Sketch features placed on a face store the plane absolutely; give them the same `ref_bbox` follow-the-body
  treatment as edges/faces so a boss on a top face follows a thickness change.

## Also noticed (pre-existing, not fixed)
- Reading `out/status.json` while the runner replaces it can fail on Windows (`PermissionError` in the server log),
  and `runner.finalize` briefly writes a new `build_id` before restoring the old one, so a poller can see a phantom
  build. Worth an atomic read-retry and a single write in `finalize`.
- In the Studio, Ctrl+K opens the Studio command box; the global search stays available from the header.

## Files touched outside the Studio list
`src/aicad/agent/runner.py` (manual errors, bbox, plain error), `src/aicad/agent/tools.py` (agent sees rebuild errors),
`src/aicad/agent/worker.py`, `src/aicad/holes.py` (new), `src/aicad/platform/plain.py` (new),
`src/aicad/platform/routers/projects.py` (undo/redo, current revision, params errors/labels, source 404),
`src/aicad/platform/routers/library.py` (plain Toolbox/import errors), `src/aicad/toolbox.py` (offer matching only, no
geometry change, VERSION unchanged), `src/aicad/demo/{l_bracket,pipe_flange,stepped_shaft}.py`,
`web/src/components/Viewer3D.tsx` (fit / normal-to API, Esc clears measure), `web/src/layouts/AppLayout.tsx` (Studio
sidebar starts collapsed), `web/src/lib/types.ts`, `tests/test_library.py`.
