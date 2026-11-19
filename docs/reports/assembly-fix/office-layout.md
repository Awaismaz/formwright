# Assembly reliability wave: Design Office layout (branch `wip/office-layout`)

## What was wrong
- `icd.build` only knew block layouts. A mechanism with no base plate or housing (the founder's 1:3 spur pair on two
  Ø20 shafts with four 6204 bearings) fell back to "a row of parts, no interfaces": pinion, gear and shafts at
  x = 20, 112, 194, 226 on the floor, the bearings silently dropped, **0 interfaces and `problems() == []`**, so the
  ICD gate passed and the run "succeeded" with a pile of parts.
- In a block layout, every gear of a sub-assembly went on its *first* shaft (a gear pair on a base plate never meshed).
- Found in the simulated run: a designed gear that Hex takes from the Toolbox (module and teeth written, so "fully
  specified") is approved with no Design Studio build; Fitz then had "nothing to swap in" and the sub-assembly
  integration **waited forever** for the real gear. The same would happen in a live run whose plan names module and
  teeth.
- `icd.seated` returned only the first interface of a bearing item, so one bearing item shared by several shafts was
  only partly seated.

## What changed
- **Shaft lines** (`icd.build`, layout `"shaft_line"`): when no designed part is prismatic but there are shafts, the
  shafts run along +Y (the Phase 6 gearbox convention, so placeholders, excerpts, Gage, Fitz and drawings reuse the
  canonical-frame machinery), parallel, axes on Z = 0. Input shaft (by name, else plan order) on X = 0 and fixed;
  each next shaft at the exact centre distance of its meshing gears; meshes coplanar (the first on Y = 0), further
  gears of a compound shaft stacked 5 mm along +Y; tooth phasing as before. Gears go on shafts by `mounts_on`, then
  by name (pinion → input, wheel → output, intermediate/idler → middle), then plan order (one per shaft, or the
  1-2-…-2-1 compound pattern). Bearings: two per shaft (own sub-assembly and same-named bearings first), one either
  side of everything that turns near them (its own riders and other shafts' gears that reach over its bearing OD),
  5 mm clear (`BEARING_CLEAR`); shaft `SHAFT_END` (10 mm, ≥ d/2) beyond the outer bearing faces, or the planned /
  written length. Sizes written in words ("20 mm diameter, 120 long") are now read for shafts.
- **Datums of a shaft line**: A = the plane of the shaft axes (Z = 0), B = the mesh plane of the first gear pair
  (Y = 0), C = the input shaft's axis plane (X = 0). Notes say the bearings still need pedestals or a frame (not in
  the plan).
- **New interface `bearing_journal`** (a = the shaft journal, b = the bearing standard part, one per bearing,
  `b.copy` = the n-th piece of that bearing item; `b.standard = true`): data designation, d / D / B, `shaft_fit` k6,
  `axis`, `z` (bearing span), `journal_z`, `shoulder_z` (when the shaft is larger than the bore), `side`,
  `bearing_item`. Editable: designation (stored on the shaft item). Shaft side features: journal boss (+ shoulder);
  bearing side: its bore in its own frame. `seated()` collects every seat/journal of a bearing item (adds
  `interfaces`), so Fitz inserts all four 6204s; `integrate` then mates them by name (concentric journal ↔ bore,
  + shoulder). Motion joints, joint axes, drawings' fit datums, excerpts and the web ICD table know the new kind.
  Existing kinds and ids are unchanged.
- **Gear pairs on a planned plate** keep the block layout: gears now go on different shafts by the same rule, so
  they mesh at the centre distance on the plate; a part named "plate" (not housing/case/gearbox) is no longer
  turned into a gearbox casing.
- **ICD problems never silent** (`icd.issues(skel, ifs)` → `{code, severity, text, items, interfaces}`;
  `problems()` keeps returning the error texts, `warnings()` the warning texts; `skel["layout"]` is
  `block | gearbox | shaft_line | row`). New codes: `row_layout`, `no_interface` (errors, block the gate),
  `bearing_unplaced` (warning, shown amber at the gate: Fitz bins them), `shaft_support`, `line_clash`,
  `journal_off_shaft` (errors); existing geometry problems got codes too (`outgrown`, `hole_edge`, `rim`,
  `hole_overlap`, `washer_overlap`, `fit_unknown`, `bearing_depth`, `bearing_wall`, …). The ICD view adds
  `warnings` and `issues` (errors only, computed only when there are problems). A change request may not *add* a
  problem (problems the approved layout already had, e.g. from a newer check, no longer reject every CR).
- **Toolbox gears in an ICD program**: Hex sizes a reused designed gear to the ICD (module, teeth, face width, bore),
  and `swap_in` puts the Toolbox gear in through the frame "moved down B/2" instead of skipping it.

## Evidence
- **Test case layout (hand-checked, `tests/test_office_shaft_line.py`)**: layout `shaft_line`, base = Input shaft,
  `problems() == []`. Centre distance a = m(z1 + z2)/2 = 2(20 + 60)/2 = **80**: pinion at (0, 0, 0), gear at
  (80, 0, 0), both along +Y; envelopes Ø44 × 20 / Ø124 × 20 (tip m(z + 2), face 10 m); shafts Ø20 × 120 (written).
  Bearings 6204 (20 × 47 × 14) on journals Y −29…−15 and 15…29 on each shaft (gears span −10…10, the big gear's tip
  r 62 reaches over the input shaft's bearings, 5 mm clear). Gear phase 3° (half a 6° pitch). Interfaces:
  IF-01/02 bearing_journal (input), IF-03 shaft_bore (pinion), IF-04/05 bearing_journal (output), IF-06 shaft_bore
  (gear), IF-07 gear_mesh. Placeholders: shafts Ø20 × 120, gears at pitch circles Ø40 / Ø120 bored Ø20. Shaft
  placeholders and real Toolbox gears pass Gage conformance; motion joints: two revolute (shaft + its gear) and a
  gear joint −20/60.
- **Generalised**: single shaft + pulley + 2 bearings; compound 3-shaft 18/54 + 18/54 (centres 72, second mesh on
  Y 25, intermediate bearings at −29…−15 / 40…54), same result with unnamed parts; idler 20/30/40 (centres 50/70,
  idler phase 6°); gear pair on a planned base plate stays a block layout, now meshing at 80. Degenerate cases:
  gears only → `row_layout` + 2 × `no_interface` (errors) + `bearing_unplaced` (warning); 3 bearings for 2 shafts →
  `shaft_support`; m1 20/20 with 6204s → `line_clash` (bearings overlap 27 mm) + `rim`; frozen 50 mm shaft →
  `journal_off_shaft`.
- **Simulated end to end** (`FW_OFFICE_FAKE_AGENTS=1`): pytest `test_spur_pair_program_assembles_on_its_shafts`
  passes (445 s under load; it timed out at 1670 s before the Toolbox-gear swap fix). Isolated app on :8791,
  puppeteer: ICD gate 0 problems (4.5 s from create), run **complete in 130 s**, 9/9 tickets, 105 tokens (simulated).
  Final assembly: Pinion (0, 0, 0), Gear (80, −10, 0) (Toolbox gear base face, B/2 below its ICD centre), Input
  shaft (0, 0, 0), Output shaft (80, 0, 0), bearings at (0, −29, 0), (0, 15, 0), (80, −29, 0), (80, 15, 0), every
  part Z along +Y. "4 real parts and 0 placeholders: 6 mates (interfaces mated by name), 0 clashes"; advisory
  whole-program check: **0 clashes over 7 pairs (5.1 s)**; motion check 0°…360°, 24 steps, **0 colliding**;
  drawings (part sheets + assembly drawing with BOM, 5 balloons) and the manufacturing review finished; 0 console
  errors. Screenshots (scratch, not committed): `fw-e2e-8791/shots/01-interfaces-gate.png`,
  `02-assembly-tab.png`, `03-interfaces-approved.png`, `04-deliverables.png`, `05-assembly-studio.png`.
- Tests run: `test_office_shaft_line.py` (5), `test_office_icd.py`, `test_office_phase6_layout.py`,
  `test_office_layout_envelopes.py`, `test_office_phase6_review_ecn.py`, `test_assembly_motion.py`;
  `ruff check src tests` clean; `npx tsc --noEmit` clean; `web/dist` rebuilt locally for the walkthrough only.

## Left / notes
- WORKLIST row 35 "mounts_on layout tree stacks parts (tyres on the floor)": same family (parts with no usable
  interface placed loose, silently). Those parts now surface as `no_interface` problems at the gate; the stacking
  itself (hubs bolted on a block row) is a different cause and is not fixed here.
- Behaviour change: the 2:1 standard gear reducer (caps that don't fit) now shows a blocking `no_interface` problem
  at the gate (test updated). The way out is Archie's re-plan or editing the numbers.
- Follow-up after merge (master's report): crowded plans where Archie hangs a rod / pin on another shaft (`mounts_on`
  an axle: the rover's tie rod, the Archie-chat test's push rod) got `no_interface`. Root cause fixed instead: a
  shaft-role part whose host is a shaft now stands in a bore of the nearest block carrying that shaft (a
  `shaft_bore`, noted in the skeleton). Those plans lay out buildable first time again with 0 problems.
- Standard templates Conveyor (roller bearings in a sheet rail) and Linear stage (lead-screw end bearings) now show a
  `bearing_unplaced` warning (not blocking).
- A designed gear Hex takes from the Toolbox gets no part drawing (the run drew Pinion, Input and Output shaft; the
  Gear had no Design Studio project). It is in the assembly drawing and BOM. Pre-existing for Hex reuse; Ortho
  should draw made Toolbox parts too (not done).
- A shaft is still "shaft" only for family `turned` (a `machined` "shaft" stays a block).
- Not done: pedestals/frame for the bearings (not in the plan); belt/pulley pairs between shafts (no mesh: spaced by
  clearance only); shafts with qty > 1 in a shaft line (copies beyond the first are laid out loose).

## Parked decisions (default used)
- PD: unconnected designed parts (`no_interface`) **block** the ICD gate (default) vs warn only.
- PD: unplaced bearings are a **warning** (default) vs blocking.
- PD: shaft-line datum A = plane of the shaft axes (default) vs the plane under the bearings' outer rings.
- PD: 5 mm gear-to-bearing clearance and 5 mm between gears of a compound shaft, 10 mm shaft ends (assumed, editable
  only through the plan's lengths for now).
