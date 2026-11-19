# Parametric generators and template harvesting (branch `wip/generators`, WORKLIST 45 and 48)

Work in progress. Paused at a clean point on the master's request (machine slot); resumed later with the same
context.

## Status so far
- **Baseline measured** (main 1236baf, simulated, both paths; records in the scratch dir `fw-e2e-8810`):
  - Old planner: 5 of 9 pass. Designed parts built with no AI: a 2/2, b 4/4, c 2/11 (output gear direct, pinion
    from the Toolbox), d 0/2, e 2/3, f 1/4, g 0/3, R2 1/2 (Toolbox gear), R1 2/2.
  - `FW_DESIGN_GRAPH=1`: a 2/2, b 4/4, c 4/10 (shafts and gears; housing, cover and 4 caps go to the AI). (c) fails
    on F6 (cap screw stacks), which is the connection-layout agent's finding.
- **`src/aicad/fw_std.py`** (new helpers, backward compatible; not yet re-exported from `fw.py`, which is a Studio
  file): `machined_volume` / `machined` (a box or disc less axis-aligned box pockets, with round pads kept, and
  axis-aligned cylindrical cuts; pure hand volume that refuses what it can't sum exactly), `hub_keyway`,
  `revolved_volume` / `revolved` (Pappus).
- **`src/aicad/office/generators.py`** (pure, imports cleanly, lint clean, **not wired or tested yet**): expressions
  that carry both script text and value (`V`), script writer with `PARAMS` / `PARAM_META`, and generators for the
  gearbox housing (cavity, seats at the centre distance, cap screw holes on the PCD, cover tapped holes, dowels, wall
  rule in `PARAM_META`, cap pads, mounting feet with M-size by footprint, optional features dropped when they would
  cross an ICD feature), the cover (bolt and dowel holes, shelled over the cavity), open and blind caps (PCD holes,
  relief, bore, DIN 3760 lip-seal recess, spigot note), plates and blocks (every ICD hole, bore and seat along any
  axis, the brief's corner holes at 1.5 d, edge-distance notes), L brackets with gussets (upright placed on an edge
  that clears the washers, else the agent with the reason), plain and timing pulleys and sprockets (pitch Ø
  simplified), rigid sleeve couplings and set-screw collars. Extras check per kind (what the brief asks beyond the
  generator), with the plan's interface clauses superseded by the approved ICD.

## Next steps
1. Wire `generators.plan_part` into `direct.plan` (new kinds when `_kind` is None; spacer + set screw -> collar),
   label and record the path per ticket; seed the agent from a generator model when only extras are missing.
2. `tests/test_generators.py`: build each generator through `runner.main` + `conformance.measure` on the reducer,
   bracket, roller and linear-stage ICDs; hand-checked bores at the centre distance, PCDs, wall rule, pulley pitch Ø.
3. Row 48: workspace templates (harvest an AI part with `PARAMS`, bindings to ICD quantities, similarity by family,
   features and size ratio, reuse direct or as a seed; list and delete in the Office; tenant scoped).
4. Golden suite after (both paths), one live pass of (c) on about 60 tokens with the Assembly screenshot read, report
   with the coverage table and PD-140 onward, `git merge main`, commit.

## Parked decisions (drafted, numbers to confirm)
- PD-140 Open caps get a lip-seal recess by default (DIN 3760 size for the shaft the ICD passes); a plan seal sized
  for another shaft Ø is superseded by the ICD, with a note.
- PD-141 Blind caps: no spigot; the ICD has the cap bear flat on the outer ring with the relief.
- PD-142 Housing feet and cap pads are design additions inside the envelope (relief 2 mm), dropped when they would
  cross an interface feature.
- PD-143 The plan's statements of a hole pattern the ICD now fixes are superseded (like the planned envelope).
