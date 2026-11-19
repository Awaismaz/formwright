# Fitz assembles gear trains and shaft lines (ASM-010 / ASM-019), 2026-11-19

Branch `wip/fitz-trains`. Test case of the wave: 1:3 spur pair m2 z20 / z60, two Ø20 shafts, four 6204, no housing.

## What was wrong (reproduced on the isolated app, port 8792)
Text "a spur gear m2 20 teeth, a spur gear m2 60 teeth, two Ø20 shafts and four 6204 bearings", empty assembly:
**8 of 8 parts "placed beside the assembly", 0 mates, 42 DOF** (screenshot `fitz-trains-before.png`). Causes:
1. Fitz only seated a gear / bearing on a shaft *already in the assembly*; shafts named in the same text were inserted
   last ("place") and nothing could go on them. No gear-mesh placement at all.
2. Toolbox shafts have 1 mm end chamfers, so `fitz.seats()` found no end face on them: even with a shaft present a
   bearing had no "free end" to sit flush with.
3. Hex did not read the usual gear shorthand: "m3" was silently ignored (module 2 assumed), "z60" / "20T" too, and the
   founder's own phrasing "spur gear pair 1:3 m2 20T/60T" became **one** z24 gear.
4. Every failure was the same generic "placed beside" sentence, with no code another agent could act on.

## What changed
- `src/aicad/assembly/trains.py` (new): shaft lines and gear trains built by construction.
  - Lines: each shaft carries its hubs (gear, pulley, coupling) on its longest seat, centred on the keyway (Toolbox
    shaft: mid-length) else on the seat; two bearings per shaft, one each side: against a shoulder facing the hubs,
    else flush with the free shaft end, else 5 mm from the hub; < 1 mm clearance or off the journal = reported.
  - Meshes: gears pair in listed order (same module), next axis parallel at a = m(z1+z2)/2, same mid-plane, tooth
    phase `trains.phase()` (a tooth space faces the partner's tooth at the line of centres; u + v constant while
    rolling, v = ½ - u); gear i goes on shaft i; the next shaft is placed from its gear.
  - Toolbox gears are re-bored to their shaft's seat (rule of the gear generator: bore < root Ø − 2 m);
    size-less bearings are sized from the shaft journals.
  - Motion: one revolute joint per line (shaft + hubs), a gear joint per mesh at −z1/z2 (Motion tab works as is).
- Solver: new mate type **`gear`** ("Gear mesh": two axes parallel at the centre distance; 3 equations, analytic
  Jacobian, prealign). `make_mate` fills the value from both gears' module / teeth when left blank. UI: Gear mesh in
  the Mate panel (optional centre distance), cog icon in the tree.
- `fitz.py`: `train` action (plan + run), `CODES` registry, every non-success → `outcomes[]` `{code, severity, item,
  inst, name, text}` (also on the old mount / seat / dowel / fasten / clash paths), `timings` {total, train, solve,
  interference}. `seats()` accepts chamfered ends / filleted shoulders (closing face within r/2).
- Hex (`librarian.py`, `toolbox.match`): "m2", "m1.5", "z60", "20T", "m=1.5 z=40"; "gear pair 20T/60T" (and
  "20/60 teeth") becomes two items (expanded in `split()`, so AI line indices stay aligned).
- Base: with no block the input shaft is the fixed base at the origin, axis +Y, its gear's mid-plane on Y = 0, mesh row
  along +X (PD below). A free shaft already in the assembly is used as is. Into a non-empty assembly with nothing to
  carry it, the line is built beside it and says so (`train_not_attached`).

## Evidence
Tests `tests/test_assembly_trains.py` (8, hand values in the docstring): phase rule (z20/z60 → 3°, rolling
invariance), gear mate residual / Jacobian vs finite differences / prealign, axial stack (plain shaft: gear 52.5..67.5,
bearings 0..14 and 106..120; stepped: 16..30, 90..104 against shoulders; 40 mm shaft: `no_room_for_bearing` ×2),
plan of the pair (actions, bore Ø20, 6204 sized from shafts, codes), off-axis mesh at 40°: new rule 0 mm³, previous
rule (v = u + ½) clashes; kernel runs through the API: the pair (shaft origins (0,−60,0) and (80,−60,0), gears at
y −7.5..7.5, wheel phase 3.000°, bearings y −60/46, all axes +Y, 14 mates ok, gear mate 80, 0 interference, motion
0..36° in 6 steps: 0 collisions, wheel at −12°), 3-gear train (shafts at x 0 / 60 / 130, ratios −1/2 and −4/3, 0
clashes), odd counts (m3 gear → 4× `module_mismatch`, 5th bearing `bearing_spare`), shaft + pulley (user part) +
2 bearings (pulley y −10..10, bearings −60 / 46), the pair on user stepped shafts (bearings against the shoulders).
Gate: `pytest tests/test_assembly_trains.py test_assembly*.py test_library.py test_office_icd.py test_office.py`: 118 passed (10 min); ruff clean; `tsc --noEmit` clean. Existing smart-assembly tests unchanged.

End to end on 8792 (machine shared with ~5 agents, CPU 50–100 %; Hex reads deterministically, **0 AI tokens**):
| case | result | total | prepare parts | interference |
|---|---|---|---|---|
| founder's phrasing "spur gear pair 1:3 m2 20T/60T, two Ø20 shafts, four 6204 bearings" | 8 parts, 14 mates ok, 0 clashes, 3 joints | 60.6 s | 31.4 s (z60 gear) | 29.3 s (8 pairs) |
| same, parts and pairs cached | same | 0.24 s | 0.19 s | 0.02 s |
| 3 gears z20/z40/z30, 3 shafts, 6 bearings | 12 parts, 0 clashes, 5 joints | 103 s | 31.5 s | 71.6 s (7 new pairs) |
| pair on the demo Stepped Shaft (a real Studio build, Ø20/Ø25/Ø20) | gears bored Ø25, bearings on shoulders (t 26..40, 110..124), 0 clashes | 65 s | 0.7 s | 64.3 s |
| m2 + m3 gears, 2 shafts, 5 bearings | 5 parts beside, each with a code | 56.8 s | 44.5 s | 12.3 s |
The time is the CAD kernel, not Fitz: placement + mates + solve take < 0.1 s. Interference is dominated by the
gear pairs and gear-on-shaft pairs (in-process, loaded machine: shaft/pinion 26 s, pinion/wheel 9.7 s, bearing pairs
1–3 s). Screenshots: `fitz-trains-before.png`, `fitz-trains-plan.png` (Hex/Fitz plan in the Describe tab),
`fitz-trains-after.png` (assembled pair, mates incl. Gear mesh, Motion tab with the 20:60 gear joint).

## Left / caveats
- Under 100 % CPU the worker's 180 s `prepare` timeout was hit twice on the z60 gear (recognition of ~1000 faces);
  the run then fails with the generic "geometry operation failed". A longer prepare timeout or a cheaper recognition
  of Toolbox gears (their parameters are known) would fix it. Not changed here (shared worker code).
- Interference on meshing gears costs 10–30 s per pair cold; a visual check (other agent) or skipping exact booleans
  on pairs placed by construction could cut it; I kept the exact check.
- Compound trains (two gears on one intermediate shaft) are not recognised: gears pair in order, one per shaft;
  extra gears mesh without a shaft (`gear_without_shaft`). Gears from user parts mesh at the right distance but their
  tooth phase is unknown (`tooth_phase_unchecked`; no automatic half-tooth retry yet).
- Office ICD (`office/icd.py` ~l.1381) uses v = (u + ½) mod 1 for the second gear's phase; correct is v = (½ − u) mod 1.
  Same result while u ∈ {0, ½} (every collinear layout today), wrong for meshes off the row or a phased first gear.
  Test `test_phase_rule_meshes_off_axis_where_the_old_rule_clashes` shows it. Not edited (office agent's file).
- "Bore 20 mm (default)" in the plan card: the bore is set by Fitz, not read; the card still says "(default)".

## Outcome codes (for the visual-check / chat agents)
`fitz.CODES` lists them with severity: no_interface, no_mount_pattern, no_shaft_seat, no_free_hole,
no_clearance_holes, fastener_failed, hole_skipped, part_unavailable, needs_design, already_fixed, clash,
no_part_to_mount_shaft, module_mismatch, no_gear_to_mesh, gear_without_shaft, gear_bore_too_large,
gear_not_recognised, tooth_phase_unchecked, bore_mismatch, no_bore, no_shaft_geometry, no_shaft_for_hub,
no_journal_for_bearing, no_room_for_bearing, bearing_spare, bearings_short, hub_overhangs_seat, train_not_attached,
shafts_not_held. Run result: `result.outcomes[]`; plan items carry expected `codes[]`.

## Parked decisions (default used)
- PD: frame of a housing-less train: input shaft fixed at the origin, axis +Y, gear mid-plane Y = 0, shafts side by
  side along +X (Office gearbox convention). Alternative: compact zig-zag / vertical shafts.
- PD: bearings on a plain shaft go flush with the shaft ends (no shaft overhang for a coupling); hubs centred on the
  keyway. Alternative: bearings inboard next to the hub with a fixed gap.
- PD: bearings stay with the ground in the motion joints (outer ring held); the shaft spins in their bore.
- PD: a `gear` mate type was added to the solver (placement only; the ratio lives in the motion gear joint).

Files: `src/aicad/assembly/{trains.py (new), fitz.py, solver.py, service.py, librarian.py}`, `src/aicad/toolbox.py`
(gear shorthand in `match`, no geometry change, no VERSION bump), `src/aicad/platform/routers/mod_assembly.py` (mate
type literal), `web/src/pages/app/modules/assembly/{types.ts, Tree.tsx, MatePanel.tsx, Workspace.tsx, smart.ts}`,
`tests/test_assembly_trains.py` (new).
