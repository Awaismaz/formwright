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
as a 6-character fingerprint). `web/src/pages/admin/GoldenSuite.tsx`: Simulated / Live switch; summary row (cases
passing, pass rate per suite run, suite wall time, tokens, last run and sha) with sparklines; one row per case with
the latest PASS/FAIL (and an arrow when it changed), its failing expectations (got / want), wall-time, token and
pass-rate sparklines, runs passed; a row opens the expectation grid over the last 8 runs (pass, fail, not measured)
with the phase times and counts. Data shaping in `web/src/pages/admin/golden.ts` (vitest, 7 tests).

### CI-like hook
`tests/test_golden.py::test_simulated_suite_fast_cases` runs the two `fast` cases (a and R1) simulated, about 45 s.
The full suite is the separate command `uv run aicad golden` (about 3.5 min); it is not run by pytest.

## Results

### Simulated suite (all cases, one at a time, workers reaped)
SIM_TABLE

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
FINDINGS

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
- `tests/test_golden.py` (9 tests): every case loads, and its replayed plan has the part lines, pieces and kinds the
  case expects (head nouns, `scope.kind_of`); world boxes, gaps and loose parts by hand; the keyed gear case passes on
  its hand layout (office-small numbers) and fails exactly the expectations a broken snapshot breaks; selectors, `pick`,
  `auto` axes, stacks, reuse; the history is append-only and the public rows carry no model names; the admin endpoint
  is 403 for a normal user, 404 in production and returns the runs for the super-admin; and the CI hook (the two
  fast cases simulated, every expectation, 0 tokens).
- `web/src/pages/admin/golden.test.ts` (7 vitest tests): rolling pass rate, per-case summaries per mode, cases only in
  the history, the summary row per suite run, sparkline paths with gaps, plain value formatting, the expectation grid.
- GATE_LINE

## Walkthrough
WALK_LINE

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

## Files
New: `src/aicad/eval/golden.py`, `src/aicad/eval/golden_run.py`, `src/aicad/eval/golden_cases/` (9 cases, 8 plans),
`tests/test_golden.py`, `web/src/pages/admin/GoldenSuite.tsx`, `web/src/pages/admin/golden.ts`,
`web/src/pages/admin/golden.test.ts`, this report and `docs/reports/golden-suite/` (screenshots, the run records).
Changed (shared): `src/aicad/cli.py` (the `golden` command), `src/aicad/platform/routers/admin.py`
(`GET /api/admin/golden`), `web/src/pages/admin/Admin.tsx` (the tab, God mode only), `.gitignore`
(`eval/golden/history/`). No office, graph, Studio or data files touched.
