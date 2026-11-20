# Hybrid master model (WORKLIST 50, branch `wip/master-model`)

Founder question (2026-11-20): why does the same prompt succeed in the Design Studio and fail in the Design Office?
The Studio has one agent, one script and one coordinate system, so every body is placed consistently by
construction. The Office chains plan, layout, interfaces, separately designed parts, matching and reassembly, and each
hand-off can lose information. The design graph and the connection-layout solver close that gap for structures the
graph knows. This branch closes it for the rest, and only when needed (founder: "hybrid master model, used only when
needed"; the golden suite decides the default).

**In one paragraph.** At plan time a deterministic rule decides the layout path and records it on the program. The
fast path (design graph, connection solver or standard layout, spec builds) stays the default. When the rule says the
fast path can't lay the program out, Archie spends one design-agent turn on the Opus tier modelling a coarse multibody
master of the whole product in one coordinate system. Code measures the master (frames, envelopes, contacts, hole
patterns, pivot axes, fits, pockets, counterbores) and writes the office's own skeleton and ICD from it, so the ICD
gate, direct builds, Gage, Fitz, revision and the supervisor run unchanged, and Fitz places each detailed part where
its master body sat. Measurement findings are errors or warnings at the gate, never silent.

## Results in one table

Golden suite, simulated (recorded plans, recorded master scripts, simulated designers; 0 live tokens). "Path" is what
the office decided; master time is the master step (build and measure of the recorded script).

| Case | Old planner, before (connection-layout report) | Old planner, now | Graph planner, now | Fast path forced (`FW_MASTER_MODEL=0`) |
|---|---|---|---|---|
| a keyed gear | PASS | PASS, fast | PASS, fast | |
| b gear pair | PASS | PASS, fast | PASS, fast | |
| c reducer | PASS | PASS, fast | PASS, fast | |
| d bracket | PASS | PASS, fast (roles) | PASS, fast | |
| e roller | FAIL | FAIL: rule says master, no recorded master, fast path (said) | PASS, fast | |
| f linear stage | FAIL | FAIL, fast (the template is silently wrong; the rule can't see it) | PASS, fast | |
| g hinge arm | FAIL (pin vanished) | **PASS, master** (5.1 s) | PASS, fast | FAIL (pin missing) |
| h enclosure (new) | | **PASS, master** (5.2 s) | **PASS, master** (5.0 s) | FAIL: M3 x 50 through bolts with nuts at X ±3.5 |
| i motor adapter (new) | | **PASS, master** (5.3 s) | **PASS, master** (5.2 s) | FAIL: plate flat on the bracket, motor on top, no screws |
| j controller (new) | | **PASS, master** (6.7 s) | **PASS, master** (5.2 s) | FAIL: M3 x 40 through bolts with nuts at X ±3.5 |
| R1 Test 5 | PASS | PASS, fast | PASS, fast | |
| R2 Shaft Gear | FAIL (key) | FAIL, fast | PASS, fast | |
| R3 table | PASS | PASS, fast | PASS, fast | |
| **Total** | 6 of 10 | **10 of 13** | **13 of 13** | 0 of 4 |

Records: `docs/reports/master-model/sim-auto-template.json`, `sim-auto-graph.json`, `sim-fast-template.json`,
`sim-force-template.json`, `sim-force-graph.json`, and after merging main (generators, WORKLIST 45/48)
`sim-auto-template-merged.json` / `sim-auto-graph-merged.json` (section 7). The reducer (c) was re-run after the
accessory fix in section 1 (`sim-auto-template-c-rerun.json`: fast, PASS).

**Fast vs master where both apply** (wall seconds, simulated; tokens are the simulated designers' metering, the same
on both paths; the live master turn adds about 13 tokens and 49 s, section 6):

| Case | Planner | Fast path | Master path | Difference |
|---|---|---|---|---|
| d bracket | old | PASS 7.8 s | PASS 13.0 s (forced) | +5.2 s, same parts and stacks |
| d bracket | graph | PASS 7.9 s | PASS 13.3 s (forced) | +5.4 s |
| g hinge arm | graph | PASS 7.7 s | PASS 13.6 s (forced) | +5.9 s |
| g hinge arm | old | FAIL 9.2 s | PASS 13.1 s | only the master passes |
| h enclosure | either | FAIL 8.3 s | PASS 12.8 to 13.0 s | only the master passes |
| i motor adapter | either | FAIL 8.4 s | PASS 15.0 to 16.0 s | only the master passes |
| j controller | either | FAIL 8.7 s | PASS 13.1 to 16.1 s | only the master passes |

**The default per job kind, from these numbers:** where the graph or the template covers the mechanism (a, b, c, d,
R1, R3 and every graph-path case) both paths give the same result and the fast path is about 5 s faster simulated and
about 50 s and 13 tokens cheaper live, so the fast path stays the default there. Where the rule fires (free-form
products, custom adapters, a structure the solver can't place, a gate failure, a joint part nothing places) only the
master path passes, so the master is the default there. The rule never sent a passing case to the master path (c was
the one false trigger, an oil plug; fixed, section 1). The decision itself costs 1 to 20 ms (a trial layout, no CAD).

## 1. When the master model is used: the decision rule (`src/aicad/master/decide.py`)

Deterministic, run when a plan is set (and again after a design-graph plan's questions are answered), recorded on
the program as `plan["layout_path"] = {path, reasons [{code, text}], words, mode, trial}`. All matching reasons are
recorded; the first names the path in plain words on the plan review.

| Order | Code | When | Plan review says |
|---|---|---|---|
| 1 | `product` | the brief or a designed part reads as a free-form product (enclosure, shells, controller, handheld, appliance, moulded ...) and the plan has no shafts, gears, bearings or pulleys | Laid out from a master model (free-form product) |
| 2 | `adapter` | a designed part is a custom adapter (adapter or interface plate, transition piece) | ... (custom adapter part) |
| 3 | `unsupported` | the design graph has connections the solver can't place (`layout.Unsupported`) | ... (new structure) |
| 4 | `conflict` | the solver reports a `layout_conflict` | ... (the fast layout has a conflict) |
| 5 | `unreachable` | a part no connection reaches, or a bought-out JOINT part (pin, pivot, axle, rod, shaft) no interface places (`part_unplaced`); an accessory like an oil plug is not one | ... (a part no connection reaches) |
| 6 | `gate` | the fast layout fails a placement check at the interfaces gate (`icd.problems`) | ... (the fast layout fails a placement check) |

The rule runs the fast path's own layout as a trial on the very plan the gate will see (same code, same input, same
result). Otherwise: "Laid out by the connection solver (fast path)", "... from the parts' roles (fast path)" or
"... with the standard layout (fast path)". Switch `FW_MASTER_MODEL`: `auto` (default), `0` (always fast), `force`
(always master: the golden comparison). Tests run with it off (`tests/conftest.py`) unless they turn it on. Programs
with more than 40 designed bodies keep the fast path and say why (PD-184). When the master turn or its build fails,
the plan says "Laid out on the fast path (the master model could not be made: ...)".

## 2. The master model (`src/aicad/master/run.py`, `prompt.py`, `kit.py`)

* **One design-agent turn** with the Studio agent machinery (`AgentSession`: the CAD build tool, the warm per-org
  worker, the tripwire, the run record), a dedicated instruction set (`prompt.MASTER_INSTRUCTIONS` on the compact base
  prompt, no PARAMS or review block) and the routed `design_agent.complex` model (Opus). It runs in the planning phase:
  the program stays "planning" (stage `master`) until the master is measured, then the plan review opens.
* **What it models:** a coarse multibody skeleton in one coordinate system: one solid per planned designed part,
  named as the plan names it, copies as separate solids; envelopes, walls and pockets, mating faces exactly
  coincident, bores and the holes where fasteners go; no bought-out parts (their holes only), no fillets or threads,
  every face square to the axes.
* **Helpers** (`aicad.master.kit`): `mk.box`, `mk.cyl`, `mk.drill`, `mk.master({name: body or [copies]})` (labelled
  solids), `mk.count()`; build123d and the `fw` helpers as in the Studio.
* **Measured in its own process** (`python -m aicad.master.measure`, the model-script tripwire applies).
* **Metering** like Archie's planning turn: debited to the workspace and added to the program's planning tokens; cap
  120 tokens per turn. **Targets:** at most 60 platform tokens and 120 s per master turn, measurement included.
  Measured: 13 tokens and 54.6 s (section 6).
* **Development replay:** `FW_MASTER_REPLAY` (a script, or a folder of `*.master.py` matched by the plan's designed
  part names) replays a recorded master instead of a turn; refused in production. The golden runner replays each
  case's `[sim] master` script.

## 3. Measuring the master (`src/aicad/master/measure.py`)

From the master B-rep (build123d / OCCT; `recognize.py` for holes and cylinders; `assembly/geometry.min_distance` for
touching):

* **Bodies:** envelope (min, max, size, centre), volume, axis-aligned planar faces, full cylinders, holes (Ø, axis,
  extent, through or blind), and the **open pocket** of a non-convex body (an L bracket's inside corner, a clevis slot)
  when the empty part of its envelope is one clean box (spanned by the surrounding flat faces, empty to 99.5 %; bosses
  in a cavity make it not a pocket).
* **Planar contacts:** coplanar (0.05 mm) opposed overlapping faces, merged per plane, with the holes crossing the
  plane paired by position: fastener-size pairs are **bolts**, larger through pairs are **openings across the joint**
  (a pilot bore in a window); blind recesses on both sides (a shell's inside) are neither.
* **Coaxial fits:** a bore on a pin (radial gap at most 0.5 mm). **Pivot axes:** one hole line through two or more
  bodies that is not a bolt (a hinge pin's bores; the pin is bought out).
* **Findings:** overlaps (shared volume), bodies that touch nothing, edge or point touches, faces off the axes, a
  fastener-size hole on a joint with material across it and nothing matching it.

## 4. Into the office, unchanged downstream (`src/aicad/master/skeleton.py`)

`skeleton.build(measured, parts, brief, overrides)` returns `(skeleton, interfaces)` in exactly the format of
`icd.build` / `layout.build`; `interfaces._graph_layout` takes it first when the plan's path is `master`, so creation,
edits, change requests, autofix, revision and every rebuild use it (a frozen ICD rebuilds identically: tested).

* **Frame:** the base (a name that reads as a base, frame, lower shell or housing; else the lowest body, then the
  largest) has datum A on the top of its envelope, X and Y centred, +Z up.
* **Items:** one per designed part, one copy per body, envelope = the body's box, position = its centre (parts are
  modelled centred, as everywhere in the office), so Fitz places each detailed part where its master body sat. A
  pocket becomes the item's `cavity` (`kind: pocket`, `open_through`); the ICD excerpt describes it.
* **Interfaces:** `hole_pattern` from bolts (tap-drill blind holes are the tapped side, ISO 2306; clearance ISO 273;
  through bolts when both are clearance; the planned screw line of that size as `fastener_item`; measured tap depth;
  **counterbores** over the clearance holes carried as seats; **openings across the joint** carried as clearance
  holes); `face` from a contact with no holes; `shaft_bore` from a bore on a turned pin; `dowel` from a pivot axis with
  a planned pin (ISO 8734). Spigots between two blocks stay a note (a block carries no boss feature).
* **Screw check at the gate:** Fitz's own length rule (`assembly/fasteners`: ISO lengths, 2 d engagement in an unknown
  material, a washer under the head) on the measured clamp and tapped depth; no standard length is a warning at the
  gate instead of a surprise at assembly.
* **Honesty:** overlaps, bodies that touch nothing or aren't connected to the base, bodies matching no planned part,
  planned parts with no body and copies that differ in size are `layout_conflict` errors (the gate blocks); edge
  touches, faces off the axes, lone fastener holes, a pivot with no planned pin, thread mismatches and screws that
  can't fit are warnings (`skeleton["findings"]`, read by `icd.issues`).
* **Design graph feedback:** `skeleton.graph()` writes what was measured as a design graph (components with measured
  envelopes; bolted joints with their screws, seating faces, pin joints, fits; source "layout", note "measured from
  the master model") on `plan["master"]["graph"]`; the plan's own intent graph stays as it is. Each designed part's
  plan envelope becomes its measured size, so the tickets' briefs match the master.

## 5. What the engineer sees (browser walkthrough, port 8813)

Throwaway data, God mode, the controller case (j): Archie's plan replayed (`planner=replay`, every other role on the
stub provider), the master replayed (`FW_MASTER_REPLAY`), simulated designers. puppeteer-core 24, **0 console or page
errors**. Planned in 6.4 s with the master stage seen; plan approved: 0 problems, 0 warnings, 1 interface; run
complete 18.7 s after creation; final assembly: both shells, 4 SHCS M3 x 16 with washers, 0 clashes. Screenshots read
(`docs/reports/master-model/`):

1. `1-master-modelling.png`: "Archie is modelling a master of Controller housing", "Modelling every part in one
   coordinate system...", and the reason in plain words.
2. `2-plan-review.png`, `3-layout-path-card.png`: "Laid out from a master model (free-form product)" with the
   "Master model measured" badge, "Archie modelled the whole product as 2 bodies in one coordinate system...", and the
   measured connection "Lower shell bolted to Upper shell (Shell screw M3x16)".
3. `4-interfaces.png`: skeleton notes "Laid out from a master model: 2 bodies in one coordinate system ...", datum A
   "Lower shell top (envelope)", IF-01 "4 x M3 into tapped holes (measured)".
4. `5-assembly.png`: the two shells stacked, 4 fastener stacks, 0 clashes, every level assembled.

No file names, tools, model names or code appear in the UI.

## 6. The live run (one master turn, budget 80 tokens)

The controller case (j), the real design agent through the development login, `run.run` with an 80-token budget
(`docs/reports/master-model/live-j_controller.json`, the script it wrote: `live-j_controller.master.py`):

| | Target | Measured |
|---|---|---|
| Tokens | at most 60 | **13** ($0.129; 4 model calls, all Opus; 2,951 output tokens) |
| Time | at most 120 s | **54.6 s** (turn 48.9 s with 3 builds, the first two failed and were fixed; measure 5.7 s) |
| Result | | 2 bodies, its own original outline (a slab with two front grip lobes), 1 bolted joint: 4 x M3 into tapped bosses of the upper shell, screwed from below, 0 errors, 0 measurement findings |

Hand check against the brief: lower shell 150 x 95 x 18 (Z 0 to 18) and upper 150 x 95 x 14 (Z 18 to 32) as stated;
4 screws from below into the upper shell, side a (tapped) the upper shell, its face looking -Z. The screw check found
a real problem: Ø6 x 9 counterbores leave a 9 mm clamp and the bosses are tapped 7 mm, so an M3 screw would have to be
exactly 15.5 mm (no ISO length). Replaying the live script through the whole office (simulated designers,
`live-j_downstream.json`) showed it twice: first as a bug of mine (blind lobe interiors read as openings across the
joint; fixed: openings must be through on both sides), then as this screw problem, which Fitz reported at assembly
("No standard M3 length fits"). Since then the master path says it at the gate (warning, tested). The recorded case
uses Ø8 x 9 counterbores in Ø11 bosses (room for the ISO 7089 washer) and 8 mm taps: M3 x 16 fits.

## 7. After merging main (generators, WORKLIST 45/48)

`git merge main` brought in the generators (parts built from the interface spec without AI, WORKLIST 45/48). The
whole suite was run again on both planners (`sim-auto-template-merged.json`, `sim-auto-graph-merged.json`):

| | Old planner | Graph planner |
|---|---|---|
| Passing | **10 of 13** (the same cases as before the merge: e, f, R2 fail on the template, as before this branch) | **13 of 13** |
| Master path | g, h, i, j (5.3 to 5.6 s master step) | h, i, j (5.2 to 5.8 s) |
| Simulated designer tokens on master-path cases | g 70, h 70, i 105, j 70 | h 70, i 70, j 35 |

On the graph planner the generators now build some master-path parts without a design turn too (i: 105 to 70, j: 70
to 35): the master's measured ICD is the same format, so the direct path reads it unchanged. Every other number is
within the run-to-run noise of a loaded machine (the reducer's run time varies 23 to 59 s between runs).

## 8. Tests and checks

* `tests/test_master_model.py`, 21 tests, recorded master scripts, no tokens, about 14 s: hand-checked measurements
  (enclosure bosses at ±53.5 / ±33.5, M3 Ø2.5 x 8; the L bracket's pocket and window passage; the hinge's pivot axis
  and pin at X -25, Z -6, 40 long), skeletons and ICDs of h, i, j and g, counterbores as seats, the live master's
  screw warning, findings at the gate (overlap, touches nothing, unknown body, missing body, copies that differ), the
  decision rule (product, adapter, gate, unreachable pin, the reducer's oil plug stays fast, size cap, off and force),
  route / attach / fallback, the office rebuild through `interfaces._rebuild` (and after a freeze), the master step
  end to end in its own process, replay matching, golden case loading.
* Other suites run green on this branch: `test_office_icd` + `test_golden` 28, `test_connection_layout` +
  `test_program_revision` 42, `test_office_orchestrator` + `test_design_graph` 48, `test_office` + `test_master_model`
  41. `ruff check src tests` clean; `npx tsc --noEmit` clean; `npx vite build` built.
* One test fixed on the way: `test_office.py::test_api_archie_plan_is_parsed...` waited for a plan while the rule sent
  the winch's plan (template gate problems) to a master turn; tests now run with the master switched off unless they
  turn it on (`tests/conftest.py`), like the supervisor and the visual check.

## 9. Files

New: `src/aicad/master/` (`__init__`, `decide`, `kit`, `measure`, `prompt`, `run`, `skeleton`),
`tests/test_master_model.py`, `web/src/pages/app/office/MasterModel.tsx`, golden cases `h_enclosure`,
`i_motor_adapter`, `j_controller` (`.toml`, `.plan.json`, `.intent.json`, `.master.py`), recorded masters
`d_bracket.master.py`, `g_hinge_arm.master.py`, `docs/reports/master-model/` (records, live run, screenshots).

Shared files touched (small, said here): `office/interfaces.py` (the master layout first in `_graph_layout`),
`office/icd.py` (measured findings as gate issues; `passages` and `counterbore` features of a bolted joint; the pocket
line of the ICD excerpt), `platform/routers/office.py` (route after a plan is set, spawn the master task, strip the raw
measurement from the program view), `eval/golden.py` and `eval/golden_run.py` (`[sim] master`, `path` expectation,
master replay, path columns), `golden_cases/d_bracket.toml` and `g_hinge_arm.toml` (their master scripts),
`tests/conftest.py` (master off in tests), `web/.../office/PlanReview.tsx` and `types.ts`. Not touched:
`office/generators.py`, `office/direct.py`, Studio files, `fw.py`.

## 10. Known limits (honest)

* **One skeleton per sub-assembly placed by the solver is not built.** Programs above 40 designed bodies keep the fast
  path (PD-184).
* **Generators on master-path parts are partial.** After the merge the direct path builds some master-path parts
  (section 7); shells with bosses and other free-form bodies still go to a designer, with the master's description.
* **Axis-aligned only:** off-axis faces and holes are warned about and not measured as joints. One part frame per item
  (copies must be the same size and orientation).
* **Coarse bodies stay boxes in the ICD:** a hollow shell's inside and its bosses are described in the plan text, not
  as ICD features (only clean pockets are); simulated designers therefore build solid envelopes, which is why the
  recorded scripts' counterbores matter.
* **The rule can't see a silently wrong template** (case f on the old planner): nothing flags it, so it stays fast.
  The graph planner lays f out correctly.
* **e (roller) on the old planner** routes to the master but has no recorded master: it falls back, said.
* **A plan edited at approval** keeps the master measured from the plan before the edit; renamed or added parts
  become gate errors ("matches no part", "no body"), and there is no "model the master again" button yet (PD-188).
* **The gate-time trigger** ("the fast path fails a placement check at the gate") is evaluated at plan time on the
  same plan with the same code; a failure that only appears after an edit at approval is shown at the gate as before,
  without a master turn.
* The live check was one turn on one case (j) and the downstream with simulated designers; no live designer turns.

## 11. Parked decisions (default used)

| PD | Decision | Default used |
|---|---|---|
| PD-180 | Master model on by default? | `FW_MASTER_MODEL=auto`: the rule decides; the fast path stays the default where it passes (the numbers above). `0` switches it off, `force` is for comparisons |
| PD-181 | When and on which tier the master turn runs | at plan time (planning stage "master"), one Opus design-agent turn, metered like Archie's plan, cap 120 tokens, targets 60 tokens / 120 s |
| PD-182 | What counts as a free-form product | words in the brief or a designed part's name (enclosure, shells, controller, handheld, appliance, moulded ...) and no shaft, gear, bearing or pulley in the plan; adapters by part name |
| PD-183 | Base and frame of a master layout | base by name (base, frame, lower, bottom, housing, body), else the lowest, then the largest body; datum A on the top of its envelope |
| PD-184 | Large programs | above 40 designed bodies: the fast path, said; per-sub-assembly masters placed by the solver are the next step |
| PD-185 | Coarse bodies in the ICD | boxes with clean pockets only; shells, bosses and lobes stay in the plan text for the designer |
| PD-186 | Screw fit at the gate | Fitz's own rule (ISO lengths, 2 d engagement when the material is unknown, washer under the head) as a warning |
| PD-187 | Openings across a joint | through holes on both sides (windows, pilot bores) become ICD clearance holes on both parts; blind recesses don't |
| PD-188 | Plan edited at approval | the master measurement is kept; mismatches are gate errors; no re-model button yet |
| PD-189 | Severity of findings | overlap, touches nothing, not connected, unknown or missing body, copies that differ: errors; edge touches, off-axis faces, lone holes, pin not planned, thread mismatch, no screw length: warnings |
| PD-190 | Bought-out parts that trigger "unreachable" | joint parts only (pin, dowel, pivot, hinge, axle, rod, shaft); accessories (plugs, seals) don't |

Entry points for the master to add later (not done here): a "Model the master again" action on the plan review, and
an Admin golden dashboard column for the layout path.
