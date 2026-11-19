# Golden mechanism suite and trend dashboard (branch `wip/golden-suite`, WORKLIST 46, EVAL-003)

Goal: make "is it better?" a number. A fixed set of mechanisms, each a brief with hand-checked expectations, runs
through the Design Office end to end; every run appends one record per case to a history; a God-mode admin page
shows the latest result per case, pass or fail per expectation, and trends.

## What was built

### Cases (`src/aicad/eval/golden_cases/*.toml`)
One small TOML file per case: the brief, where it came from, the plan a simulated run replays, limits (tokens and
wall time), and the expectations, with the hand formulas in comments. Format (documented in `eval/golden.py`):

- `[sim] planner = "standard"` (the office's own planner on the brief) or `[sim] plan = "<case>.plan.json"` (Archie's
  plan, replayed: a recorded plan or a reference plan written the way Archie writes them).
- `[limits] tokens` (the live cap per case), `wall_simulated_s`, `wall_live_s`.
- `[expect]` counts: `complete`, `light` (the one-step path), `parts` (part lines), `pieces`, `subs`, `tickets`,
  `kinds = {kind = pieces}` (head noun, `scope.kind_of`), `no_extras`, `instances`, `clashes` (the whole-program check;
  a check that did not finish never counts as 0), `binned`, `loose`, `placeholders`, `blocked` (tickets that stopped
  for the engineer), `icd_problems` (first draft), `conformance` (every ICD feature Gage measured), `direct_min`
  (parts built without AI), `supervisor_max`, and `only_simulated = [...]` for counts only a replayed plan fixes.
- Geometry checks on final-assembly instances: `at` (instance origins), `span` (box along an axis), `along` (which
  axis a part lies along), `distance` (box centres, in a plane), `within` (inside another part or between two),
  `touch`, `same_span`, `count`, `stacks` (fastener stacks by style and size), `reuse` (Toolbox code of a ticket).
  Selectors: `{kind = "key"}` or `{name = "regex"}`, `pick = "smallest" | "largest"`; `modes = ["simulated"]` for
  numbers that depend on sizes the replayed plan fixes.

| | Case | Source | Simulated plan |
|---|---|---|---|
| a | `keyed-gear` Spur gear on a stepped shaft, keyed | founder's sentence, 2026-11-19 | the office's standard planner |
| b | `gear-pair` 1:3 pair, m2 20/60, Ø20 shafts, four 6204, no housing | founder's standing test case | Archie-style plan (`tests/test_office_shaft_line.py` PAIR) |
| c | `reducer` single-stage 3:1, split housing and caps | founder's Gear Reducer program | Archie's live plan with the founder's gate edits |
| d | `bracket` bolted bracket on a base plate | FX-04 design intent and sizes | reference plan |
| e | `roller` conveyor roller, bearings in side plates | WORKLIST 46 list | reference plan |
| f | `linear-stage` carriage on two guide rods in end blocks | WORKLIST 46 list | reference plan |
| g | `hinge-arm` arm on a Ø8 pin in a clevis | FX-06 design intent and sizes | reference plan |
| R1 | `r-test5` regression: the founder's "Test 5" | his program, Archie's first plan | recorded (copied read-only from `data/office`) |
| R2 | `r-shaft-gear` regression: the founder's "Shaft Gear" | his program, Archie's plan | recorded (copied read-only) |

Founder failures behind R1/R2 (read from his programs, nothing changed there): Test 5 forced a housing by the
shaft-support rule and binned the key (9 tickets for 3 parts); Shaft Gear blocked twice on "Gear circlip 25 mm touches
nothing", the founder moved three tickets to Integrated by hand. FX-05 (keyed shaft in a housing) is covered by (b),
(c) and R2, so it got no case of its own.

### Runner (`src/aicad/eval/golden_run.py`, `uv run aicad golden`)
- Each case runs in its own throwaway platform: a temporary data folder and database, the real FastAPI app in
  process, a fresh workspace with a wallet. It creates the program from the brief, waits for the plan, takes the
  one-step light path where the office offers it (else approves the plan, presses "Fix with Archie" once if the
  interfaces have problems, approves the ICD and presses Run), waits for the run, then for the whole-program clash
  check, and reads everything back through the API and the program's assembly documents.
- `--simulated` (default): simulated agents, the case's plan replayed into Archie's planning turn, the supervisor and
  the visual checks in their simulated, rule-based modes. Any live model call fails the case (the model entry points
  are replaced by a tripwire). One case at a time; the CAD workers are reaped after each case.
- `--live`: the real agents (development Claude Code login). The program budget is the case's cap and a watchdog
  pauses the office as soon as the wallet has spent it. `--cap N` overrides.
- `--case a,b` (ids or letters), `--fast`, `--list`, `--keep`, `--work`, `--history`, `--json`, and `--env
  FW_NAME=VALUE` (a server switch under comparison, recorded with each run, e.g. `FW_DESIGN_GRAPH=1` for PD-110).
- A run whose every open ticket waits for the engineer ends after a grace period (20 s simulated, 90 s live) so the
  supervisor gets its chance; the runner never answers the supervisor's questions (there is no engineer).
- Measured per case: completion, wall time per phase (plan, gates, run, clash check), tokens (wallet delta), clashes,
  binned, loose and placeholder parts, tickets that stopped, interface conformance, parts built without AI,
  supervisor interventions, visual verdicts, and every expectation (got / want).

### Results store (`eval/golden/history/runs.jsonl`, gitignored; `FW_GOLDEN_DIR` overrides)
Append-only JSONL, one record per case run: case, mode, pass, status, metrics, expectations, detail (tickets,
instance boxes, stacks, warnings, looks, supervisor lines), git sha + dirty flag, model routing (tier per role) and its
fingerprint, flags, suite id. Outside `data/`.

### Dashboard (Admin console, tab "Golden suite", God mode only)
`GET /api/admin/golden` (super-admin, 404 when God mode is off or in production) returns the cases and the latest
runs per case through `golden.public` (numbers and plain labels; no model names, prompts or internals; routing only
as a 6-character fingerprint). `web/src/pages/admin/GoldenSuite.tsx`: one track per mode and switch set (Simulated,
Live, Simulated with `FW_DESIGN_GRAPH=1` ...), so trends never mix configurations; summary row (cases
passing, pass rate per suite run, suite wall time, tokens, last run and sha) with sparklines; one row per case with
the latest PASS/FAIL (and an arrow when it changed), its failing expectations (got / want), wall-time, token and
pass-rate sparklines, runs passed; a row opens the expectation grid over the last 8 runs (pass, fail, not measured)
with the phase times and counts. Data shaping in `web/src/pages/admin/golden.ts` (vitest, 8 tests).

### CI-like hook
`tests/test_golden.py::test_simulated_suite_fast_cases` runs the two `fast` cases (a and R1) simulated, about 45 s.
The full suite is the separate command `uv run aicad golden` (about 3.5 min); it is not run by pytest.

## Results

### Simulated suite (all cases, one at a time, workers reaped)
`uv run aicad golden`, before merging main (sha 0340058 plus this branch's files):
**5 of 9 pass**, 170 s of program time, 177 s elapsed for the whole suite. The same results came out in three
complete runs (the table is the last one; `docs/reports/golden-suite/simulated-run.json`).

| Case | Result | Wall s | plan / gates / run / check | Tokens (sim) | Clashes | Binned | Loose | Stopped tickets | Parts without AI | Failing expectations (got / want) |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| a keyed-gear | **PASS** | 16.1 | 0.34 / 0.18 / 15.52 / 0.02 | 0 | 0 | 0 | 0 | 0 | 2 | |
| b gear-pair | **PASS** | 23.8 | 0.14 / 0.25 / 23.39 / 0.01 | 0 | 0 | 0 | 0 | 0 | 4 | |
| c reducer | **PASS** | 29.7 | 0.14 / 1.59 / 27.96 / 0.03 | 315 | 0 | 0 | 0 | 0 | 2 | |
| d bracket | **PASS** | 8.1 | 0.15 / 0.61 / 7.34 / 0.01 | 70 | 0 | 0 | 0 | 0 | 0 | |
| e roller | FAIL | 34.9 | 0.38 / 0.28 / 34.21 / 0.0 | 35 | 0 | 0 | 1 | 2 | 2 | not complete (stalled, blocked); loose 1; 2 stops; tube 51.0 mm off the shaft axis (want 0); tube Z -18..182 is not between the plates |
| f linear-stage | FAIL | 11.2 | 0.14 / 0.29 / 10.79 / 0.02 | 105 | 0 | 0 | 0 | 0 | 1 | rods lie along Z (want X, the stage's long axis); rods 0 apart across X (want 60); carriage X 80..160 is not between the end blocks (X -135..-45) |
| g hinge-arm | FAIL | 8.3 | 0.21 / 0.64 / 7.39 / 0.01 | 105 | 0 | 0 | 0 | 0 | 0 | 2 instances (want 3): the pin is missing, so it touches neither the arm nor the clevis |
| R2 r-shaft-gear | FAIL | 23.2 | 0.14 / 0.21 / 22.8 / 0.02 | 35 | 0 | 0 | 0 | 0 | 1 | key X 11..18 (want 8.5..15.5, a Ø25 seat); bearing circlips 3.5 mm from any bearing; gear circlip 17 mm from the gear |
| R1 r-test5 | **PASS** | 15.2 | 0.14 / 0.16 / 14.93 / 0.01 | 0 | 0 | 0 | 0 | 0 | 2 | |

"Tokens (sim)" is the simulated agents' metering (30 to 35 per fake design turn, for parts the office still designs
with AI); it is never real spend. Every case that passes ran with 0 interface problems at the gate, every measured
interface feature conforming, nothing binned and nothing loose.

### Design-graph path, simulated (`--env FW_DESIGN_GRAPH=1`, after merging main)
PD-110 says the graph planner should become the default when this suite passes on the graph path. The runner now
replays the recorded live intent replies of the design-graph report for (a), (b) and (c), takes Archie's defaults
when the graph asks questions (the reducer asked one, about material), and skips cases without a recording.
Results (`simulated-graph-run.json`): **(a) PASS** 17.2 s, **(b) PASS** 26.5 s, **(c) FAIL** 28.9 s: the caps are
held by 16 ISO 4017 M4 x 25 hex bolts and the cover by 4 M6 x 35, while the graph's own plan lists 16 M6 cap screws
and M8 cover bolts (PD-114). The ICD warning reads "Bearing cap screws: 16 of 16 have no bearing seat or journal in
this layout", so the plan's cap screws are read as bearings and the ICD falls back to default bolts. See F6.

### Live pass, cases (a) and (b) only (cap 30 tokens each)
| Case | Result | Wall s | plan / gates / run / check | Tokens | What the office did |
|---|---|---:|---|---:|---|
| a keyed-gear | **PASS** | 46.8 | 14.1 / 0.2 / 32.5 / 0.0 | 6 | Archie: 3 parts, 1 sub-assembly; one step; shaft and gear built from the interfaces (no AI), key from the Toolbox at X 8.5..15.5 (a Ø25 seat: 12.5 - 4.0); 0 clashes; both looks "assembled" |
| b gear-pair | FAIL as recorded, PASS re-scored | 84.0 | 16.7 / 0.4 / 66.9 / 0.0 | 8 | Archie: 6 part lines (bearings as two lines of 2), 8 pieces; centre distance 80.0, gears coplanar Y -10..10, bearings at Y -29..-15 and 15..29 on both shafts, 0 clashes, nothing binned or loose; shafts and pinion from the interfaces, the gear from the Toolbox made to the ICD; 0 design turns |

Total live spend: **14 platform tokens** of the 60 allowed. For comparison: the same sentence (a) took 122 s and 34
tokens live on 2026-11-19 (`office-small.md`), and the gear pair (b) 17 min and 689 tokens (`live-gear-run.md`).

(b) failed three expectations, and all three were mistakes in the eval itself, not in the product. The case counted
part lines (5) and kinds by lines, but the brief fixes pieces ("four 6204 bearings"), and Archie wrote the bearings as
two lines of two. "Built without AI" counted only the direct path, while the gear was made from the Toolbox to the
ICD (also 0 tokens, no design turn). Fixed in the eval: `kinds` counts pieces, `parts` is simulated-only for (b),
`direct_min` counts Toolbox-to-ICD parts. The recorded live snapshot re-scored under the corrected case
passes every expectation. The history keeps the original FAIL record; I did not spend tokens on a second live pass.

## Findings (product, for the master; not fixed here)
- **F1 (e) A shaft whose bearings sit in plates is not understood.** The layout is a row of block stations: the
  shaft stands vertical through side plate 1 (shaft role, "through a bore, bottom flush"), the roller tube stands on
  its own 51 mm off the shaft axis, side plate 2 sits on its own station. Fitz rightly blocks "Side plate #2 touches
  nothing in the rest of the assembly". The supervisor (rule-based in simulation) retried once, the same block came
  back, and the program then waits for the engineer (stall after 20 s). Cause: `icd.build` lays bearings in shaft
  walls only for a planned housing (the gearbox layout, CD-022); plates carrying bearings fall back to the block
  layout. A retry can never clear a layout fault. Target: WORKLIST 44 (layout from connection semantics), and a
  supervisor rule that escalates a repeated "touches nothing" as a layout problem instead of retrying.
- **F2 (f) The linear stage completes green but is wrong.** The rods stand vertical through the base plate, the two
  end blocks sit side by side at one end, and the carriage stands on its own station. 0 clashes, both visual looks
  "assembled", program complete. The ICD has no guide-rod / slide connection, so the result is degenerate but
  passes. That breaks the founder's rule "a gate must never pass silently on a degenerate result". Target: WORKLIST
  44 (a sliding joint), and meanwhile a layout warning when parallel rods end up standing in a base.
- **F3 (g) A planned part silently disappears.** The hinge pin (a standard dowel) gets no skeleton place and no
  interface. It is designed as a bought-out part, then is in neither the final assembly nor the parts bin, and no
  comment reports it; the program completes. The ICD has 0 problems because unconnected standard parts are not
  flagged. The arm is bolted flat on top of the base (`hole_pattern`) instead of pivoting between the lugs: there
  is no pin / revolute interface. Target: report every planned piece that is not placed (as `gearbox-caps` did for
  fasteners), and a pin joint in WORKLIST 44.
- **F4 (R2) The founder's "Shaft Gear" no longer blocks, but two things are wrong.** His failure is gone: 0 stops,
  all three circlips placed, nothing binned, and the keyed gear made from the Toolbox to the ICD (bore, hub
  keyway). But:
  - The gear sits on Ø30, the plan's shoulder Ø and the shaft envelope, not on the Ø25 seat the plan states. The
    key is at X 11..18; by hand it should be at 12.5 - 4.0 = 8.5..15.5. This is the same class as the live misread
    fixed in `office-small`, but the stepped-seat reading only runs for shaft sub-assemblies without bearings.
  - The retaining rings are swapped. The two "Bearing circlip 20 mm" sit against the gear faces (Y ±10..11.5) and
    the "Gear circlip 25 mm" against the outboard face of the -Y bearing (Y -28.2..-27, as a Ø20 ring). The ICD
    fills ring spots in a fixed order (gear faces first, then bearing outboard faces) and matches ring items only
    by Ø when known; it never reads the item's stated role ("locating each bearing inner race", "holding the gear
    against the shoulder").
  - Neither fault showed up: 0 clashes and "looks assembled".
  Target: `icd.py` ring assignment by role, and the seat Ø for stepped shafts carried in bearings.
- **F5 (live b) Mixed generators for one meshing pair.** Live, the pinion was built direct (true involute) and the
  gear from the Toolbox made to the ICD (Hex's path, because the plan's gear text had something the direct builder
  declines). Both conform and mesh with 0 clashes; worth unifying (PD from `office-direct`: designed gears direct).
- **F6 (graph path, c) Cap and cover fasteners lose their planned size.** See the design-graph section: the plan's
  "Bearing cap screws" are read as bearings by the ICD's fastener matching. The graph path is not yet ready to be
  the default for (c) (PD-110).
- **F7 The no-AI fallback planner is generic.** Without Archie, `planner.standard_plan` answers (b) and (d) to (g)
  with templates (for example, the bracket brief becomes "Frame / Mechanism / Covers" with a shaft, a bearing housing
  and a cover; the roller becomes a full conveyor with legs and six carry rollers). It only matters when Archie is
  unavailable; the suite uses replayed plans there (PD-120).
- **What works, measured:** the founder's own sentence (a) and his Test 5 regression assemble in about 16 s
  simulated and 47 s live (6 tokens, 0 design turns). The gear pair (b) gets the exact layout simulated and live
  (8 tokens). The reducer (c) seats 4 caps with 16 M6 cap screws and 4 M8 cover bolts, 0 clashes over 56 instances.
  The bracket (d) bolts down with 2 M6 stacks. 0 clashes and 0 binned parts everywhere it completes.

## Eval fixes made during the runs (disclosed)
- `kinds` counts pieces (was part lines); `only_simulated` for counts a live planner may legitimately change; "built
  without AI" includes designed parts made from the Toolbox to the ICD (see the live (b) note).
- R2 first expected "the gear is not a Toolbox gear". That was wrong: Hex's Toolbox gear made to the ICD (bore,
  DIN 6885 hub keyway, plan material) is the designed behaviour, and conformance covers it. I replaced it with what
  the founder's plan states: the key on the Ø25 seat, and each circlip against what it locates.
- Added the `along` check after (f): the first version reported "rods 0 mm apart", which was confusing, when the real
  fault was that the rods stand vertical.
- Visual verdicts are counted as `looks_wrong` (the first version compared against "wrong").
- A case that stops early keeps the phases and tokens measured so far.
- Every run before these fixes stays in the history as recorded.

## Tests
- `tests/test_golden.py` (10 tests): every case loads, and its replayed plan has the part lines, pieces and kinds the
  case expects (head nouns, `scope.kind_of`); world boxes, gaps and loose parts by hand; the keyed gear case passes on
  its hand layout (office-small numbers) and fails exactly the expectations a broken snapshot breaks; selectors, `pick`,
  `auto` axes, stacks, reuse; the history is append-only and the public rows carry no model names; the admin endpoint
  is 403 for a normal user, 404 in production and returns the runs for the super-admin; design-graph runs replay
  only the recorded intent reply (any other model call trips the wire); and the CI hook (the two
  fast cases simulated, every expectation, 0 tokens).
- `web/src/pages/admin/golden.test.ts` (8 vitest tests): rolling pass rate, tracks by mode and switches, per-case summaries per track, cases only in
  the history, the summary row per suite run, sparkline paths with gaps, plain value formatting, the expectation grid.
- Gate after `git merge main` (two files per pytest call, CAD workers reaped): `test_golden` 10 passed (45 s, the CI
  hook included); `test_platform` + `test_office_small` 40 passed; `ruff check src tests` clean; `tsc --noEmit` clean;
  `npm test` 157 passed (23 files); `vite build` ok. The full pytest suite was not run (resource rule).

## Walkthrough
Port 8808, throwaway data folder, the server reading this checkout's history (`FW_GOLDEN_DIR`), puppeteer-core,
`docs/reports/golden-suite/dashboard_walk.mjs`: **0 console or page errors**. Screenshots (read):
`g1-simulated.png` (summary row and case rows), `g2-expanded.png` (R2 opened: phase times, counts, the expectation
grid over 3 runs showing the key and circlip checks failing), `g3-live.png` (live track: a PASS 46.8 s / 6 tokens,
b FAIL with its three eval-side failures, the rest "not run"), `g3b-graph-track.png` (the design-graph track), and
`g4-phone.png` (390 px: the table scrolls inside its card). Fixed from the shots: the design-graph runs were first
mixed into the plain simulated trend (now each mode plus switch set is its own track); numbers wrapped away from
their units; a single run drew no sparkline (now a dot); "n/a s" for cases not run; runs made with uncommitted
changes now show the sha with a "+".

## Parked decisions (default used)
- **PD-120 What a simulated run replays.** The case's plan (a recorded or reference plan, fed into Archie's planning
  turn) for every case except (a), where the office's own no-AI planner is the path under test. Alternative: the
  standard planner everywhere. That planner gives generic templates for (b) and (d) to (g), so the cases would mostly
  test the template.
- **PD-121 Geometry on boxes.** Expectations are judged on world-axis boxes of the placed parts. "Loose" means more
  than 0.5 mm from every other box: deterministic and fast, but lenient (a ring inside a shaft's box is never loose).
  The `touch` and `within` checks with hand values catch what the proxy can't. Alternative: exact B-rep distances in
  the kernel (slower; Fitz already measures).
- **PD-122 History location and contents.** `eval/golden/history/runs.jsonl` in the checkout (gitignored, outside
  `data/`), `FW_GOLDEN_DIR` overrides. Records keep the routing per role server-side; the dashboard shows only a
  fingerprint. Alternative: a database table (would follow the platform's backups).
- **PD-123 Dashboard access.** Super-admin with God mode available, 404 otherwise (production included), like the God
  router. The page reads the server's own history file, so it shows runs made on that machine.
- **PD-124 Live token cap.** Per case from `[limits] tokens` (30 for a and b): the program budget is set to it, and
  the runner pauses the office once the wallet has spent it. Planning tokens count. Alternative: a hard wallet of the
  cap size (the platform's run estimates would then refuse runs it could have finished).
- **PD-125 Simulated tokens.** Simulated design turns are metered (30 to 35 per fake turn) and shown as "simulated
  metering". They never gate: the tokens expectation applies to live runs only.
- **PD-126 CI hook.** pytest runs the two `fast` cases (about 45 s); the full suite stays a separate command.
- **PD-127 Stall rule.** A run whose open tickets all wait for the engineer ends after 20 s (simulated) or 90 s (live)
  and is reported as stopped, with the first blocked ticket and its reason.
- **PD-128 Design-graph runs.** With `--env FW_DESIGN_GRAPH=1` the runner takes Archie's default answer to every
  question (as "Take Archie's defaults"), and a simulated run replays the recorded live intent reply of the
  design-graph report (copied into the case folder for a, b and c); cases without a recording are skipped. Each run
  records its switches and is shown on its own dashboard track. Plan-specific expectations (the replayed plan's part
  lines, ticket titles, sizes) apply only when the case's own plan is replayed.

## Files
New: `src/aicad/eval/golden.py`, `src/aicad/eval/golden_run.py`, `src/aicad/eval/golden_cases/` (9 cases, 8 plans,
3 recorded intent replies),
`tests/test_golden.py`, `web/src/pages/admin/GoldenSuite.tsx`, `web/src/pages/admin/golden.ts`,
`web/src/pages/admin/golden.test.ts`, this report and `docs/reports/golden-suite/` (screenshots, the walkthrough script, the run records and a
snapshot of the history).
Changed (shared): `src/aicad/cli.py` (the `golden` command), `src/aicad/platform/routers/admin.py`
(`GET /api/admin/golden`), `web/src/pages/admin/Admin.tsx` (the tab, God mode only), `.gitignore`
(`eval/golden/history/`). No office, graph, Studio or data files touched.

## For the master
- Branch `wip/golden-suite`; `git merge main` done (the design graph). No push, no merge to main.
- Use: `uv run aicad golden` (all, simulated, about 3 min), `--case a,R1`, `--live --case a,b` (caps from the cases),
  `--env FW_DESIGN_GRAPH=1` for the graph path. Results appear in Admin console > Golden suite (God mode).
- Suggested status: WORKLIST 46 done (EVAL-003 golden suite); the findings F1 to F4 and F6 are product work for
  WORKLIST 44 (layout from connection semantics) and `icd.py` (rings by role, stepped seats with bearings, unplaced
  pieces reported, cap screw matching on the graph path). Each failing case turns green when its finding is fixed, so
  the suite measures that work.
- No entry point in the Studio or the Office is needed.

