# Make audit: fixes (MAKE-01..29, IDEA-01/02)

Branch `polish/make`. Fixes for `docs/reports/audit/make.md` across Drawing Studio, Manufacturing Advisor,
Engineering Advisor and 3D Print Prep, plus the release gate (IDEA-01) and the fix-it loop (IDEA-02).

Evidence lives in two places:
- **Tests** (named below).
- **The browser walkthrough** on port 8782, with a fresh data dir after merging `main`. God mode was used to seed
  the demos. The design agent was not used.

`$W` = `C:\Users\awais\AppData\Local\Temp\claude\ae5066db278ece3d\6657173d-006b-4ae9-a4dd-ffbf9518d104\scratchpad\fw-e2e-8782`.
Screenshots are in `$W\shots\`. The script is `$W\w1.mjs` and its log is `$W\w1.log`. The exported PDFs, the Rev A
pack and the four demo sheets (in `$W\sheets\`) were rendered and read back.

## One rule across the four modules (shared work)

| Piece | What it is |
|---|---|
| `src/aicad/deliverables.py` | **Build stamp.** Every output records the build it was made from: build id, STEP SHA-256, material and model revision. The drawing, the DFM analysis, each calc item and sign-off, and each print export all carry one. **Freshness** is `current`, `stale` or `missing`. `same_build` treats an identical STEP plus the same material as the same build. **Advice vocabulary:** adds *Measured from the model* (deterministic geometry) to the VALIDATION §4 levels, and `verified_label(self_check)` gives "Verified calculation · self-checked" or "· independent check". |
| `aicad.handoff` + `routers/handoff.py` | **Release gate** (IDEA-01), built on the existing shop handoff pack. **Deliverables endpoint:** `GET /api/projects/{id}/deliverables` returns the model rev, the release state and one status line per module. |
| `web/.../modules/ModuleHeader.tsx` | One header for all four modules, `ModuleHeader`, containing: <ul><li>← *part* in Studio</li><li>module name and Live badge</li><li>part switcher and "All parts"</li><li>model rev badge</li><li>"Model changed" badge</li><li>release chip, which opens the gate</li><li>module actions</li></ul> One picker card for all four, `PartCard`, with the ISO thumbnail. |
| `web/src/components/Release.tsx` | `useDeliverables`, `releaseChip` and `ReleaseDialog`. These are shared by the module headers and the Studio's handoff card. |
| `docs/VALIDATION.md` §4 | Records how the levels are used across the product, and the staleness rule. |

**The rule, applied in every module and on the Make tab:**
- An output that is older than the model is **badged "Model changed"**, with a one-click update.
- It is never replaced silently. Drawing Studio no longer regenerates on open; it shows "Model changed since this sheet (rev 1 → 2) · Update drawing".
- A stale output never keeps an advice level it no longer earns.
- Once a revision is issued, everything compares against it: "Draft · changes since Rev A".

## Status per finding

| ID | Status | What changed | Evidence |
|---|---|---|---|
| MAKE-01 (P0) | **Fixed** | A chained value sits inside its own span. If it doesn't fit, it goes outside the whole chain on a leader, or onto its own row. CHK-12 gained a **placement** sub-check: each value, projected on its measuring axis, must lie inside its own span, or outside on a leader clear of every other span on that line. Running the old `layout.py` through the new check reports "12.5 (right) sits in the span of 25". Fixed during the walkthrough: <ul><li>An empty dimension row did not check texts on other sides, which overlapped "12"/"12.5" on the bracket at A4 (CHK-12 failed).</li><li>The bracket's R3 leader ran across the whole view. Callouts now go to the side nearest their feature.</li></ul> | `test_chained_values_sit_against_their_own_span` (4 demos × A3/A4), `test_chk12_rejects_a_value_in_its_neighbours_span`, `test_every_demo_sheet_passes_chk12_and_leaders_stay_short`; `$W\shots\drw-bracket_p1.png`, `$W\sheets\l_bracket_A3.png`, `l_bracket_A4.png` |
| MAKE-02 (P0) | **Fixed** | Calc items and the sign-off store the build stamp; it is not hashed, so a model change is not mislabelled "edited". When the model changes, the set reads **"Model changed since sign-off: re-check"** and drops to Preliminary estimate. The old signature stays in its history. The badge shows on the Sets list, the module header ("Model changed") and the Make tab ("1 signed set · model changed"). Re-signing is refused until the model-derived inputs are refreshed. | `test_api_signoff_binds_to_the_model_and_exports_a_package`; walkthrough: shaft set signed (`30-eng-signed.png`), D1 20→18 → `model_changed`, Preliminary estimate (`31-eng-model-changed.png`) |
| MAKE-03 (P0) | **Fixed** | Print mesh checks read **"Measured from the model"**. "Verified calculation" is reserved for signed sets, and the badge itself says "· self-checked" (amber outline) or "· independent check". The DFM analysis has no "verified" level (asserted in a test). | `test_slender_upright_shaft_is_penalised_and_laid_down` (levels), `test_every_output_carries_an_advice_level`, the API sign-off test; `41-print-plate-after-change.png`, `30-eng-signed.png` |
| MAKE-04 | **Fixed** | The server builds the sign statement from facts: "with no load cases linked" or "against load case Gear load, on model revision 1". Signing needs ≥1 linked load case, or an explicit "loads are stated in each calculation", which is enforced and recorded. | API sign-off test |
| MAKE-05 | **Partly** | Fixed: <ul><li>No parameter names on any sheet; the side panel lists parameters by label.</li><li>Radius and chamfer callouts come from the exact faces ("4X R3", "R3", "4X 1 × 45°"), mapped as spec to PR, FILLET_IN and CH.</li><li>The flange's "6X" counts as N_BOLTS.</li><li>The shaft's 70 mm L2 is one spec dimension; the keyway has its own chain, and KW/KD sit on the cross-section.</li></ul> Not done: coinciding values (the plate's PL in a 40 + 40 + 40 chain) stay *inferred* because the build-time parameter perturbation is not built. | `test_radius_and_chamfer_callouts_and_no_parameter_names`; `55-drw-plate-revA.png` |
| MAKE-06 | **Partly** | Saved edits in `drawings/edits.json`, keyed by dimension id and re-applied on every regeneration: <ul><li>hide or show a dimension;</li><li>per-dimension tolerance or fit, marked user-entered;</li><li>title-block fields: title, drawing number, company, checked by;</li><li>free notes.</li></ul> Clicking a dimension locates it on the sheet. CHK-12 still runs on the edited sheet. Not done: dragging dimension text. | `test_user_edits_are_applied_and_checked`, `test_api_edits_copies_and_local_date` |
| MAKE-07 | **Fixed** | Turned parts are drawn axis-horizontal. The duplicate elevation is dropped. Parts with a bore get section A-A in place of the redundant elevation. The scale search shrinks or drops the iso view before stepping the scale down. A4 uses a compact title block. Results: <ul><li>shaft on A4 **1:1** (was 1:5);</li><li>shaft on A3 2:1;</li><li>flange on A3 1:1 with a section.</li></ul> | `test_turned_parts_are_drawn_axis_horizontal`, `test_flange_section_replaces_the_duplicate_elevation`; `drw-shaft-a4_p1.png`, `$W\sheets\pipe_flange_A3.png` |
| MAKE-08 | **Fixed** | Through IDEA-01. The sheet's REV is the issued letter while the model is unchanged, and "DRAFT" otherwise. The revision table lists issued revisions only; the per-build history stays in the History tab. After a release, a draft notes "changes since Rev A are not issued". | `test_revision_is_draft_until_issued`, `test_issue_rev_a_then_draft_then_rev_b`; `55-drw-plate-revA.png`, `57-drw-plate-draft-since-A.png` |
| MAKE-09 | **Fixed** | Review copy (tags, colours, legend) on screen. Downloads default to the issue copy: monochrome, no legend, same layout. `?copy=review` is available. | `test_issue_copy_is_monochrome_and_shares_the_layout`; `drw-bracket_p1.png` |
| MAKE-10 | **Fixed** | Severity counters always count across all processes (tooltip says so), and the default filter is All. The milled keyway also shows under Turning. The fix reads "R = width / 2 = R3, an end-mill keyway, Ø6 end mill". | `test_keyway_finding_attaches_to_turning_and_counts_are_never_filtered`; `20-mfg-shaft.png` (CRITICAL 1), `21-mfg-shaft-finding.png` |
| MAKE-11 | **Fixed** | New sheet-metal rules: <ul><li>SHM-01: minimum inside bend radius, from a table by material and temper labelled "verify";</li><li>SHM-02: a sharp outer corner on a bend is critical.</li></ul> A process whose rules didn't run, or that has an open critical, is capped at 60 "Possible", low confidence. There is a Sheet metal filter chip. The L-bracket goes from Sheet metal 95 "Good fit" to **60 "Possible"** with 2 criticals. | `test_sheet_metal_rules_and_score_cap`, `test_unanalysed_processes_are_capped`; `20-mfg-bracket.png` |
| MAKE-12 | **Fixed** | ISO 273:1979 fine, medium and coarse table in `manufacturing/standards.py`, cited. Through holes are read as clearance holes. Flange Ø14 → **warning: "not a standard clearance hole… Ø13.5 (M12 medium) or Ø14.5 (M12 coarse)"**; the M16 tap-drill reading is offered only as an alternative. Blind holes get the tap-drill reading. | `test_iso273_clearance_table_matches_the_standard`, `test_through_holes_are_clearance_holes_blind_holes_tap_drills`; `20-mfg-flange.png`, `w1.log` |
| MAKE-13 | **Fixed** | Each finding has a plain *where* (e.g. "keyway 6 × 30 mm on the Ø25 section"); no face ids. Per-finding views are zoomed. Shortlisted processes come first, then an "Other screens" appendix. Model rev, build and date are on the cover. | `test_report_html_and_pdf` |
| MAKE-14 | **Partly** | DFM findings now have actions: <ul><li>a deterministic parameter fix, or</li><li>**Fix in Studio**, with a plain prompt and the faces described geometrically, or</li><li>**Add to drawing** for note-type advice. This writes to the drawing's notes, and redraws only a sheet that is up to date.</li></ul> Not done: a `?select=face:` pre-selection in the Studio. It touches viewer and selection code in a Studio file another agent owns. | `test_api_fix_rebuilds_and_reports_the_delta`; `21-mfg-shaft-finding.png`, `22-mfg-note-added.png` |
| MAKE-15 | **Fixed** | Each Make-tab button carries a status line ("Rev A", "Model changed · update", "1 critical", "1 signed set · model changed", "Exports from model rev 1 · outdated"). The **Make** tab shows a warning dot when any output is stale. Fed by `/deliverables`. | `test_issue_rev_a_then_draft_then_rev_b` (labels); `33-studio-make-after-change.png`, `56-studio-make-after-release.png` |
| MAKE-16 | **Fixed** | Exports record the build stamp. File names carry the revision (`…_r1_fdm-o1.3mf`). Outdated exports read "From model rev N: outdated" with the download greyed out. | `test_exports_record_the_build_and_go_stale_when_the_part_changes`; walkthrough: plate L 120→140 → "Exports from model rev 1 · outdated" |
| MAKE-17 | **Fixed** | Slenderness = height ÷ √(contact area). Above 3, the ranking penalty is 0.25 per unit, capped at 1, with a "tall and slender" line. Turned parts suggest axis-horizontal and say why. Hand check for the shaft: 150/√(π·10²) = 8.463; the mesh gives 8.46. | `test_slender_upright_shaft_is_penalised_and_laid_down` |
| MAKE-18 | **Fixed** | Shared `ModuleHeader` and `PartCard` in all four modules. Make-tab labels match the module names (Drawing Studio, Manufacturing Advisor, Engineering Advisor, 3D Print Prep). | every module screenshot |
| MAKE-19 | **Fixed** | Untouched textbook loads are flagged "Example value: replace it with your load". "Keep this value" records them as confirmed. Sign-off returns 422 while any example is unconfirmed. Force and moment fields offer "Use a load case…". | `test_textbook_default_loads_are_flagged_as_examples`, API test, `engineering/types.test.ts` |
| MAKE-20 | **Fixed** | Calculation package PDF (`engineering/report.py`), covering: <ul><li>level, signer, self or independent check, signed-on revision versus current, statement, hash;</li><li>per item: inputs with provenance, working, checks, assumptions and references;</li><li>load cases and limits.</li></ul> `GET …/sets/{sid}/report.pdf`, with a PDF button. Signed sets on the current build go into the release pack. | API test (hash, level, determinism, model-changed warning); `$W\shots\eng-shaft-set_p1.png` |
| MAKE-21 | **Fixed** | Add-on modules show a lock glyph, and the tooltip reads "Add-on, not in your plan yet…". `main` now opens every Live module to trial workspaces, so this mostly affects expired plans. Not done: a free sample generation on the user's own part. | `ProjectStudio.tsx` / `CommandManager.tsx` |
| MAKE-22 | **Fixed** | The Drawing upsell sample no longer shows "40 ±0.1" or "Rev B"; it shows "4× R3" and "Draft". | `ModuleSamples.tsx` |
| MAKE-23 | **Fixed** | "Checks from the model" is a strip above the calculators. The shaft gets the smallest section, each shoulder (Kt 2.7/2.2) and the keyway section, with Kt from Shigley Table 7-1 labelled "verify". | `test_shaft_critical_sections_from_the_model` |
| MAKE-24 | **Fixed** | The message reads "Enter the required safety factor and its source…", and the safety factor is required only when a check is produced. | `test_safety_factor_needed_only_when_a_check_is_produced` (beam σ = 60.0 MPa) |
| MAKE-25 | **Fixed (scope)** | Geometry is in model space at 1:1. The sheet sits in a paper-space layout with a viewport at the drawing scale. Ø, ± and ° use CAD codes. Layers are coloured by type. Iso curves are single polylines. Associative DIMENSION entities remain "later", as the audit says. | drawings tests (DXF read-back) |
| MAKE-26 | **Fixed** | The title block and releases use the browser's local date, with the IANA zone as fallback and UTC last. The calc PDF marks its sign-off time as UTC. | `test_api_edits_copies_and_local_date` |
| MAKE-27 | **Fixed** | A solid shaft is never hatched lengthwise. It gets a cross-section through the keyway (ISO 128-50 note), and dimensions across the axis go on the section. | `test_turned_parts_are_drawn_axis_horizontal`; `drw-shaft-a4_p1.png` |
| MAKE-28 | **Fixed** | Rule ids only appear in the expanded row. The title is "Manufacturability findings". The edge-break advice is one "Drawing note suggested" chip. Screens the material excludes go to "Other screens". | `20-mfg-*.png` |
| MAKE-29 | **Fixed** | The headline reads "Geometry checks passed". For a metal part: "Design material: Aluminium 6061-T6. This print is a form and fit model". | `41-print-plate-after-change.png` |
| IDEA-01 | **Built** | **Release gate "Issue Rev A"**, extending the existing handoff pack. **Blocking:** <ul><li>unverified model or unfinished export;</li><li>drawing missing (when the workspace has Drawing Studio), stale or failing CHK-12;</li><li>this exact build already issued;</li><li>a stale DFM analysis, or a set signed on an earlier model, unless the user chooses "Leave it out".</li></ul> **Issuing** writes `releases/<rev>/pack.zip` plus its manifest, and that pack is frozen. It contains: <ul><li>model STEP/STL/3MF;</li><li>an issue copy of the drawing stamped with the letter (`render_issue`);</li><li>the DFM report;</li><li>signed calculation packages;</li><li>current print exports;</li><li>change notice, README and manifest SHA-256s.</li></ul> The working sheet is redrawn with the letter. Letters skip I O Q S X Z. The change description is prefilled ("Initial issue", or the parameter diff "L 120 → 130"). It is reached from the release chip in every module header and from the Studio's Files → "Release and shop handoff" card. | `test_issue_rev_a_then_draft_then_rev_b`, `test_revision_letters_skip_ambiguous_ones`, `test_same_build_rule`, `test_render_issue_freezes_an_issue_copy`; `52/53/54-release-*.png`, `$W\shots\plate-revA.zip` |
| IDEA-02 | **Built (DFM + print)** | **Deterministic fix:** the server offers it only when exactly one editable parameter of a compatible kind equals the measured value and the target is within that parameter's limits. The user confirms, the model rebuilds without AI, DFM re-runs and a banner shows the delta (counts and unit cost %). **Otherwise "Fix in Studio":** it links to `/app/projects/<id>?ask=<prompt>`. The Studio fills the chat with the prompt and **does not send it**. The `?ask` handler is ~10 lines in `ProjectStudio.tsx`: it writes the existing starter-text slot and opens the chat. Print gets Fix in Studio on thin walls, gaps, small holes, pins and features. Not done: failure-mode (Engineering Review) findings. | `test_parameter_fix_maps_one_compatible_parameter`, `test_fix_delta_hand_case` (−8.0 %), `test_api_fix_rebuilds_and_reports_the_delta` (plate PR 1→2, critical −1); `60-studio-ask-prefill.png` (chat textarea holds the prompt, URL cleaned) |

## Walkthrough numbers (second run, after merging `main`, fresh data; `$W\w1.log`, 0 console/page errors)
- **Drawings:**
  - bracket A3 1:1, CHK-12 passed;
  - shaft A3 2:1 and A4 1:1, both passed;
  - all four demos × A3/A4 pass CHK-12 (`$W\sheets\`).
- **DFM:**
  - shaft: 1 critical (square keyway), turning 85;
  - bracket: 2 critical (sheet-metal bend rules), sheet metal 60 "Possible";
  - flange: Ø14 is a warning, "not a standard clearance hole".
- **Engineering:**
  - shaft set signed "Verified calculation · self-checked";
  - after D1 20→18 it reads `model_changed`, "Model changed since sign-off: re-check", Preliminary estimate.
- **Print:**
  - a plate export `…_r1_fdm-o1.3mf`, then L 120→140, reads "Exports from model rev 1 · outdated";
  - the shaft's #1 orientation is laid down (25 mm tall).
- **Release:**
  - Rev A issued from the Studio's handoff card: model rev 2, note "Initial issue";
  - the frozen pack holds the model, the issue drawing, the change notice, the README and the manifest;
  - after W 80→90 the gate offers Rev B, blocked only by the stale drawing, with the suggested note "W 80 → 90". The header reads "Model changed" and "Draft since Rev A".
- **DFM "Add to drawing":** the bracket's drawing notes now hold "BREAK ALL SHARP EDGES 0.2-0.5 MM UNLESS OTHERWISE SPECIFIED.".
- **Fix in Studio:** `?ask=` put the prompt in the chat box, did not send it, and removed itself from the URL.
- **Fixed from the screenshots:**
  - the R3 leader crossing the bracket view;
  - the "12"/"12.5" overlap on A4;
  - Make-tab labels wrapping over their status;
  - module-header chips wrapping and overlapping;
  - a second sheet-rev chip that repeated the release chip;
  - the release dialog showing "already issued" as a blocker straight after issuing;
  - the calculation PDF printing the statement twice.

## Walkthrough numbers (second run, after merging `main`, fresh data; `$W\w1.log`, 0 console/page errors)
- **Drawings:**
  - bracket A3 1:1, CHK-12 passed;
  - shaft A3 2:1 and A4 1:1, both passed;
  - all four demos × A3/A4 pass CHK-12 (`$W\sheets\`).
- **DFM:**
  - shaft: 1 critical (square keyway), turning 85;
  - bracket: 2 critical (sheet-metal bend rules), sheet metal 60 "Possible";
  - flange: Ø14 is a warning, "not a standard clearance hole".
- **Engineering:**
  - shaft set signed "Verified calculation · self-checked";
  - after D1 20→18 it reads `model_changed`, "Model changed since sign-off: re-check", Preliminary estimate.
- **Print:**
  - a plate export `…_r1_fdm-o1.3mf`, then L 120→140, reads "Exports from model rev 1 · outdated";
  - the shaft's #1 orientation is laid down (25 mm tall).
- **Release:**
  - Rev A issued from the Studio's handoff card: model rev 2, note "Initial issue";
  - the frozen pack holds the model, the issue drawing, the change notice, the README and the manifest;
  - after W 80→90 the gate offers Rev B, blocked only by the stale drawing, with the suggested note "W 80 → 90". The header reads "Model changed" and "Draft since Rev A".
- **DFM "Add to drawing":** the bracket's drawing notes now hold "BREAK ALL SHARP EDGES 0.2-0.5 MM UNLESS OTHERWISE SPECIFIED.".
- **Fix in Studio:** `?ask=` put the prompt in the chat box, did not send it, and removed itself from the URL.
- **Fixed from the screenshots:**
  - the R3 leader crossing the bracket view;
  - the "12"/"12.5" overlap on A4;
  - Make-tab labels wrapping over their status;
  - module-header chips wrapping and overlapping;
  - a second sheet-rev chip that repeated the release chip;
  - the release dialog showing "already issued" as a blocker straight after issuing;
  - the calculation PDF printing the statement twice.

## Gate
- Full suite `uv run pytest -q` after merging `main`: **393 passed, 1 failed**, 28 min 51 s. The machine was loaded at the time (the walkthrough and other agents were running).
  - The failure was `tests/test_changes.py::test_change_notice_api_records_what_and_why`. Its message was cut off at "T…", most likely a timeout.
  - It passes when run alone (27.7 s), and it does not touch the files changed here.
- Module suites: release, handoff, drawings, manufacturing, engineering and print all pass.
- `ruff check src tests`: clean.
- `tsc --noEmit`: clean.
- `npm test`: 20 passed.
- `vite build`: OK.

## Parked decisions (default used)
- **Who can issue a release:** any editor; viewers can only download. There is no approver role yet. An issue records who and when, and it is not an approval: the drawing keeps NOT APPROVED.
- **A release needs a current drawing** that passes CHK-12, whenever the workspace has Drawing Studio.
  - A stale DFM analysis, or a set signed on an earlier model, blocks the release unless the user leaves it out.
  - Unsigned sets are never included.
- **Revision letters:** ASME Y14.35 style, skipping I O Q S X Z, continuing AA, AB, …
- **Older records:**
  - A signature from before model binding (no stamp) counts as signed.
  - A print export from before stamping counts as outdated.
- **Drawing:**
  - Coinciding values stay *inferred*.
  - Hidden dimensions are reported by CHK-12, not failed.
  - The iso view is dropped only below 1:1.
  - "Checked by" may be named; APPROVED always reads "not approved".
- **DFM:**
  - **Bend-radius table:** the upper end of the published ranges, labelled "verify".
  - **Clearance-hole fix target:** ISO 273 medium.
  - **Fix targets:** rounded up to 0.5 mm.
  - **Score cap:** 60 for processes not analysed or with an open critical.
  - **Default filter:** All.
- **Engineering:**
  - Kt first-iteration values come from Shigley Table 7-1, labelled "verify".
  - Zero loads are not treated as examples.
- **Print:** a turned part laid axis-vertical on FDM gets a 0.3 ranking penalty when no load direction is set.
- **Make tab:** the four modules use their full names. "Assemble" and "Product Render" belong to other modules and are unchanged.

## Not built: recommendations
- **IDEA-03 Checker mode.** A second user opens the sheet with CHK-12, DFM and calculation status overlaid, pins redlines to dimension ids (edits are keyed that way now), and approves. Only that named approval would replace NOT APPROVED. It should reuse the engineering sign-off records: hash plus self-checked or independent.
- **IDEA-04 Section-at-a-click.** Pick a plane in the Engineering Advisor, take the exact B-rep section (A, I, c, J), and feed the calculator with provenance "section at z = …". The keyway and shoulder detection added for MAKE-23 is a start.
- **IDEA-05 Fit and tolerance intent.** Tag "bearing seat Ø20 k6" or "M6 clearance, medium" once in the Studio. It would flow to drawing tolerance overrides (the edits store exists), DFM tolerance cost, the ISO 273 check and stack-ups.
- **Also next:**
  - `?select=face:` pre-selection for Fix in Studio;
  - dragging dimension text;
  - the build-time parameter perturbation for coinciding values;
  - Fix in Studio from failure-mode findings.

## Files touched outside the four modules
- **New:**
  - `src/aicad/deliverables.py`
  - `tests/test_release.py`
  - `web/src/components/Release.tsx`
  - `web/src/pages/app/modules/ModuleHeader.tsx`
  - `web/src/pages/app/modules/fixit.ts`
- **Extended:**
  - `src/aicad/handoff.py`
  - `src/aicad/platform/routers/handoff.py`
  - `web/src/pages/app/studio/HandoffCard.tsx`
  - `docs/VALIDATION.md` (§4 usage note)
  - `web/src/components/ModuleSamples.tsx` (drawing sample only)
- **Studio, kept small:**
  - `ProjectStudio.tsx`: `?ask` prefill, Make-tab status and lock, full module names.
  - `studio/CommandManager.tsx`: `MakeModule.status`/`locked`, status line, stale dot. Merged with `main`'s `data-tour="make"`.
