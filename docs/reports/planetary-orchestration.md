# Planetary orchestration: faithful placeholders, swap-in clash logic, the rim rule, golden case k (branch `wip/planetary-orchestration`)

The founder's standing benchmark is "Build a single stage planetary Gearbox", built through the Design Office and
retried until it is right. Attempt A1 (program `078f86e77b1a`, read only from a temp copy) planned the gears right
(sun z30, 3 planets z30, ring z90 internal, m2, a = 60, i = 4) and failed in orchestration. This branch fixes the
orchestration side. The ring's own geometry (internal gear generator, recognition, conformance) is the
`wip/planetary-geometry` agent's work; none of its files were touched.

## What A1 did wrong, measured on A1's own ICD

| Pair | A1 recorded (real part vs ring placeholder) | Old placeholder rule, re-measured | New placeholder |
|---|---:|---:|---:|
| Ring gear vs Input shaft | 6858.5 mm³ | 6864.1 mm³ | 0 |
| Ring gear vs Planet pin (each of 3) | 7823.6 mm³ | 7854.0 mm³ | 0 |
| Ring gear vs Sun gear | 49911.2 mm³ | 49911.2 mm³ | 0 |
| Ring gear vs Planet gear (each of 3) | (not swapped yet) | 32259.4 mm³ | 0 |

Correction to the brief: the old ring placeholder was not the 197 mm envelope but the gear rule's pitch cylinder,
Ø180 x 26, solid to the centre. Either way it claimed the whole room the sun, planets, pins and shaft run in. The
input shaft and the three pins were each sent back twice and then blocked "still clashes ... after 3 rounds" (the
supervisor had already granted one extra round) for overlapping empty space.

The planet bearing 6204 (D 47) in a z30 m2 planet (root Ø55) left a rim of (55 - 47) / 2 = 4 mm = 2 m.

## Fixes

### 1. Faithful placeholders (`office/icd.py`, `graph/layout.py`)
`icd.placeholder_spec` never claims material where the ICD says there is none:
- **Internal gear**: the rim's envelope OD (197) open to the root circle of its teeth,
  `internal_opening = m (z + 2.5)` = 185 (ISO 53 dedendum 1.25 m). See PD-260 for why the root circle and not
  "tip minus a clearance".
- **External gears**: pitch cylinder as before, with bore, bearing seats and passes.
- **New ICD "passes"** on `bearing_seat` data, emitted by the planetary layout and read by `side_features`, so
  placeholders, simulated parts, the direct builder and Gage all see them:
  - the shaft clearance Ø(d + 2) through each end wall's shoulder, from the inner seat to the cavity (A1's housing
    ICD left that 4 mm shoulder solid);
  - in each planet, the bearing entry at Ø D from the -Y face, and the pin clearance Ø(d + 2) behind the seat's
    shoulder (A1 left the bore beyond the 14 mm bearing solid, so a pin would "clash" with a planet placeholder).
- **Two bearings side by side in one bore** (both input or both output bearings in one end wall) no longer get a
  fictitious "bearing shoulder" face between them. Gage measured that face at the tapped-hole bottoms 4 mm away
  and failed the housing on it.
- Bores of hubs and carriers and the housing cavity were already carried; a test now proves it for the set.

### 2. Swap-in clash logic (`office/program_assembly.py`, `office/orchestrator.py`, `office/platform_env.py`, `office/supervisor.py`)
- `swap()` sorts the swapped parts' fresh clashes:
  - **real vs real** goes to `state["clashes"]` as before;
  - **anything vs a placeholder** goes to `state["pending_clashes"]`, tagged with the placeholder's item
    (`placeholder_side`).
- Pending entries are dropped when either side is swapped again. When the placeholder part is built, its swap
  re-measures it against everything, real vs real.
- `last.deferred` / `deferred_by_item` travel through `PlatformEnv.swap_in`.
- **Fitz (`_fit`)**:
  - a placeholder overlap is a note on the ticket ("... against the placeholder of Ring gear, which is not built
    yet; re-checked when Ring gear is built") and in the done line;
  - the built part is never sent back for it (`clash_pending` on the ticket);
  - only real-vs-real clashes count toward `MAX_CLASH_ROUNDS`, so "still clashes after N rounds" fires only for
    those;
  - clash records with an `until` that arrive in `clashes` (an older env) are treated the same way.
- `clash_status` keeps the count to real clashes and adds "; N overlaps with placeholders, re-checked when those
  parts are built".
- **Already-blocked programs like A1 heal**: `refit_placeholder_clash` acts on a part blocked (or sent back) only
  for clashes with parts that are still placeholders (`program_assembly.placeholder_only` reads the ticket's
  clash lines). It:
  - moves the part back to Approved;
  - resets `clash_round`;
  - re-queues it to Fitz, unchanged, with its own `ticket.refit` event.
  It runs from `heal_review_blocks` whenever the office starts on a program.
- **Archie**:
  - `rule_plan` reads such a block as cause `measurement`: "a measurement artefact, not a fault in this part";
  - its action is `retry`, which `execute` turns into the refit;
  - `state_view` marks the row "every clash is with the placeholder of ...";
  - the supervisor instructions say a placeholder clash is a measurement artefact and the part must never be sent
    back to be redesigned for it.

### 3. Planetary rim rule (`graph/planetary.py`)
- **The rule**: `RIM_MIN_M = 2.7`. Rim s_R >= 1.2 h_t, with h_t = 2.25 m for full-depth teeth:
  - ISO 6336-3 gives the rim thickness factor Y_B = 1 there;
  - AGMA 2001-D04 gives K_B = 1 at the backup ratio 1.2;
  - this is within the usual 2.5 to 3 m. Flagged "verify" (PD-261).
- **Choosing the bearing** (`planet_bearing`), from the Toolbox's 60xx / 62xx table: the bearing with
  D <= root Ø - 2 x 2.7 m. It prefers:
  1. the pin's bore;
  2. then the largest bore;
  3. then the larger bearing.
  When the bearing changes, the pin Ø and journal follow, unless the brief fixed them.
- **No bearing fits** and the teeth are code's own: the planets grow, z + 1 at a time. The ring grows with them
  (z_r = z_s + 2 z_p); the assembly condition and the no-touch check are kept, and the new ratio is said.
- **A bearing the brief names** is kept, with a "Check:" note.
- **Notes** (idempotent):
  - "Planet bearing: 6004 (Ø20 x Ø42 x 12) instead, because 6204 (OD 47) left a rim of 4 mm = 2 m under the
    planet's Ø55 root, less than 2.7 m."
  - "Planet bearing 6004: rim (Ø55 root - Ø42) / 2 = 6.5 mm = 3.25 m ..., at least 2.7 m (ISO 6336-3 / AGMA
    2001-D04 ...)".
- `layout._planetary` adds a "Check:" note if a rim below 2.7 m ever reaches it. Its hard conflict (rim < 1 m)
  is unchanged.

### 4. Golden case `k_planetary.toml` (`eval/golden_cases/`, `eval/golden.py`, `eval/golden_run.py`)
- **Brief**: "Build a single stage planetary Gearbox".
- **`k_planetary.intent.json`**: A1's intent reply, rebuilt from A1's resolved graph. It keeps only the values the
  reply gave ("the model's guess") and restores the planet-bearing seat in the housing that the graph's notes show
  normalise had dropped. The 3 planets were the engineer's answer and are written as qty.
- **`k_planetary.plan.json`**: A1's plan, for the old path.
- **New check `[[expect.planetary]]`** (`golden.planetary_rows`, one row per rule):
  - on the plan's design graph (now in the snapshot):
    - z_r = z_s + 2 z_p;
    - planets = 3;
    - (z_s + z_r) / N whole;
    - ratio 1 + z_r / z_s = 4;
    - rim >= 2.7 m;
    - the mounting chain: sun on the input, carrier on the output, ring fixed in the housing, each planet on its
      bearing on its pin, pin in the carrier;
  - on the final assembly:
    - 3 planets at a = 60, 120 deg apart about the sun;
    - every gear on one mid-plane;
    - sun within the input shaft's span, carrier within the output shaft's span, ring inside the housing.
- **Also expected**:
  - complete;
  - 0 clashes, 0 binned, 0 loose, 0 placeholders, 0 blocked;
  - 0 interface problems;
  - conformance;
  - 3 planet gears and 3 pins placed;
  - parts 18 / pieces 38 (replayed plan only);
  - kinds by head noun.
- `--case k_planetary` works: cases are now also found by their file stem.

## Proof: `uv run aicad golden --simulated --case k_planetary`

Before, the same case and the same eval code on main's source (3104737) gave **FAIL**, 390 s:
- 2985 simulated tokens;
- 73 ticket stops;
- 10 clashes in the whole-program check;
- 2 placeholders left;
- conformance 76 of 79;
- rim 4 mm = 2 m (6204).

After, this branch gives **FAIL, only on the ring**, 93 s:
- 130 simulated tokens;
- 0 clashes;
- 1 stop;
- conformance 84 of 85.

| Expectation | main | this branch |
|---|---|---|
| z_r = z_s + 2 z_p (90 = 30 + 2 x 30), 3 planets, (30 + 90) / 3 = 40, ratio 4 | pass | pass |
| Rim >= 2.7 m | **fail** (4 mm = 2 m, 6204) | pass (6.5 mm = 3.25 m, 6004) |
| Mounting chain | pass | pass |
| 3 planets equally spaced at a = 60 (radii 60.0, 59.999, 59.999; steps 120, 120, 120 deg) | pass | pass |
| Gears coplanar (mid-plane Y -16), sun / carrier / ring placed | pass | pass |
| Clashes (whole-program) | **fail** (10) | pass (0) |
| Binned, loose | pass | pass |
| Tickets stopped | **fail** (73) | **fail** (1: Ring gear) |
| Placeholders left | **fail** (2) | **fail** (1: Ring gear) |
| Conformance | **fail** (76 / 79) | **fail** (84 / 85: Ring gear) |
| Program completes | **fail** | **fail** (waits on the ring) |

**Why it still fails: ring geometry only, as the brief foresaw.**
- In simulation the ring is built by the simulated designer as the Toolbox *external* spur gear z90 (the ICD
  excerpt's `gear` block has no internal flag).
- Gage fails its seating face: the item is 26 wide (face 20 + 2 x 3 mm lands), while the gear is 20 wide, so
  Z -13 is specified and Z -10 measured.
- After two identical rebuilds Archie proposes relaxing that one feature, and the runner never answers.

Every other part conforms and is swapped in with 0 clashes, including the input shaft and all three pins that A1
blocked. With faithful placeholders none of the parts produced a placeholder overlap at all, so the deferral path
is a safety net here (the unit tests exercise it). Once the internal-gear generator, recognition and conformance
from `wip/planetary-geometry` land:
- the ring is swapped in;
- its real-vs-real check runs against the sun, planets, pins, shaft and carrier;
- the case should pass.

Regression, same run: b gear-pair PASS 29 s, c reducer PASS 73 s, R2 r-shaft-gear PASS 21 s (all graph path).

## Tests
- **New `tests/test_planetary_orchestration.py` (14 tests)**:
  - A1's rim rule: 6004, notes, idempotent;
  - bearing choice by hand (6004, 6203, None when the pin is fixed, None for z17);
  - planets grow when nothing fits: m1 z30 grows to z36 with ring 102 and a 6001 (rim 2.75 m);
  - a brief's bearing is kept with a Check note;
  - placeholder openings (ring Ø185 in Ø197, planet entry / seat / pin clearance, housing shoulders, no
    fictitious shoulder);
  - kernel: A1's old vs new ring placeholder against the shaft, pins and sun;
  - kernel: no two placeholders of the benchmark set overlap, apart from the 0.01 mm³ tangent meshes from rounding
    to 0.01 mm;
  - `placeholder_side`, `pending_text`, `clash_status`;
  - Fitz keeps a placeholder overlap as a note and never sends the part back (both env shapes);
  - a real clash still goes back and blocks after the rounds;
  - A1's blocked shaft is healed to Fitz at office start, but not once the ring is real;
  - Archie's rule reading (measurement artefact, retry leads to refit, state view, instructions);
  - the golden case loads and its planetary rows hold on the hand layout and fail on A1's 6204.
- **`tests/test_planetary_layout.py`**: the planet bore is now 42 (6004), with the hand rim in the comment.
- **Runs, two files per call**:

| Files | Result |
|---|---|
| `test_planetary_orchestration` | 14 passed |
| `test_planetary_layout` + `test_connection_layout` | 34 passed |
| `test_planetary_layout` + `test_office_icd` | 25 passed |
| `test_office_orchestrator` + `test_office_supervisor` | 42 passed |
| `test_golden` + `test_design_graph` | 37 passed after the kinds fix |
| `test_program_revision` | 10 passed, 5 failed |

  The 5 `test_program_revision` failures are **pre-existing on main**: the same 5 fail with main's source
  (supervisor classifies `revise_program` as minor; "orchestrator loop failed"). Not touched here.
- `ruff check src tests` is clean. The full suite was not run (resource rule).

## Files
- **Changed**: `src/aicad/graph/planetary.py`, `src/aicad/graph/layout.py` (planetary passes, rim note),
  `src/aicad/office/icd.py`, `src/aicad/office/program_assembly.py`, `src/aicad/office/orchestrator.py`,
  `src/aicad/office/platform_env.py`, `src/aicad/office/supervisor.py`, `src/aicad/eval/golden.py`,
  `src/aicad/eval/golden_run.py`, `tests/test_planetary_layout.py`.
- **New**: `src/aicad/eval/golden_cases/k_planetary.{toml,intent.json,plan.json}`,
  `tests/test_planetary_orchestration.py`, `tests/golden/planetary_a1_icd.json` (A1's skeleton and interfaces and
  its recorded clashes, copied read only), this report.
- **Not touched**: `fw_std.py`, `generators.py`, `recognize.py`, `conformance.py`, `fake_agents.py`, `data/`.

## Known limits
- The Assembly tab's 3D clash highlight reads the final assembly's analysis. A placeholder overlap measured during
  a swap may still be drawn there until the placeholder part is built; counts and comments use the new split.
- Needle bearings are not in the Toolbox tables, so the rule picks only from 60xx / 62xx and says "a needle
  bearing, a plain bush or larger planets (verify)" when none fits.
- The planet's bearing has a shoulder on one side only. Axial retention on the entry side (circlip, spacer or
  carrier face) is not modelled.
- The golden ratio expectation (4) is A1's own; a live planner may choose other teeth.

## Parked decisions (default used)
- **PD-260 Internal-gear placeholder opening.**
  - Default: the root circle of the internal teeth, Ø m (z + 2.5) = 185 for z90 m2, because a placeholder must
    never claim tooth space and the root circle is where real material can begin.
  - The brief's "tip Ø (176) minus a small clearance" would claim tooth space and overlap the planets' pitch
    placeholders (r 90 > 88).
  - Alternative: the pitch circle (180), which matches the external-gear convention "meshing placeholders touch".
- **PD-261 Rim minimum 2.7 m.**
  - Default: 2.7 m (ISO 6336-3 Y_B = 1 / AGMA 2001-D04 K_B = 1 at s_R / h_t >= 1.2, h_t = 2.25 m), marked verify.
  - Alternative: the brief's 2.5 m example, which would also have allowed nothing larger than the 6004 here.
- **PD-262 Placeholder overlaps are notes, not counted.**
  - Kept in `pending_clashes`, shown beside the clash count, and re-checked when the placeholder part is built.
  - Default: never a send-back and never a round.
  - Alternative: count them as advisory clashes.
- **PD-263 When no bearing fits, the planets grow.**
  - Default: z + 1 at a time, with the ring grown with them. The ratio changes and is said in the notes, even when
    the brief stated a ratio.
  - Alternative: a larger module, which keeps the ratio but makes the set bigger.
- **PD-264 Planet bearing preference.**
  - Default: on the pin's bore first, then the largest bore, then the larger bearing.
  - Alternative: the largest capacity regardless of the pin, which changes the pin Ø more often.
- **PD-265 Automatic refit of A1-like blocks.**
  - Default: the office heals them at start without asking (a minor action: the part is unchanged, Fitz only
    swaps it in again). Archie's rule reading proposes the same thing as `retry`.
  - Alternative: ask the engineer first.
- **PD-266 Planet bore layout.**
  - Default: bearing entry at Ø D from the -Y face, the seat, then pin clearance Ø d + 2 behind a shoulder,
    written into the ICD as passes. Conformance needs the seat to end inside its span, so a through bore at D
    fails Gage.
  - Alternative: a symmetric seat with circlip grooves (needs DIN 472 rings in the graph).
- **PD-267 No shoulder face between two adjacent seats in one bore.** Default: dropped from the ICD, since the
  physical bore runs on. It only affects layouts that put two bearings side by side in one bore (today the
  planetary end walls).

## For the master
- **Branch** `wip/planetary-orchestration`; `git merge main` done (main had not moved from 3104737). Not pushed,
  not merged.
- **After merging `wip/planetary-geometry`**:
  1. re-run `uv run aicad golden --simulated --case k_planetary`;
  2. if the simulated designer still builds the ring as an external gear, the ICD excerpt's `gear` block needs
     `internal: true` (`icd.excerpt`) and `fake_agents` must honour it. That is a one-line handshake between the
     two branches; I left `fake_agents` alone.
- **Founder's A1 program**: with this branch, restarting the office on it heals the blocked input shaft and pins
  to Fitz (refit). Their swap then keeps the ring overlap as a note. The planet bearing stays 6204 until the
  program is re-planned (the rim rule runs at graph resolution).

## Follow-up: the 5 `test_program_revision` failures on main (master's request)

**Cause.** The copilot work (216e99c, CD-050) added a rule to `supervisor.classify` for `revise_program`. A revision that redoes no modelled work, and removes no part the brief names, is Archie's own plan change, so it is minor (done and told). The rule decided "redoes modelled work" from `impact.parts[].started`. But the impact reaching `classify` is `revision.view(cand)`, and `view` copied only name, class, why, ticket, column, qty and add/remove, never `started`. So every revision read as "nothing modelled is redone" and became minor, including ones that reopen approved or integrated parts. That broke the founder's rule (PD-98..106, PD-150..159), and nobody had meant to relax it.

**Fix.**
- `revision.view` now carries `started`.
- `classify` reads it. For an impact logged before this fix, it falls back to the part's column: anything past Ready counts as worked on.
- The copilot's deliberate part is kept: Archie's own pure re-placement, and changes to parts nobody has worked on yet, stay minor.

**The 5 tests:**
- `test_table_revision_archie_proposes_without_ai_...`: fixed by the code. The table revision redesigns three parts already worked on, so it is major and asked. Before, it was "minor ... nothing modelled is redone".
- `test_archie_proposes_the_revision_asks_with_the_impact_list_and_applies_it`: fixed by the code. Archie's proposal reopens worked parts, so it is asked (1 question, 0 done). The "expected 1, got 0" was the asked list: the minor misclassification had applied the revision directly.
- `test_a_live_reply_that_only_describes_the_fix_...[actions0]` and `[actions1]`: fixed by the code, same cause. The live reply's revision is asked (1 question) instead of applied.
- `test_adding_or_removing_parts_after_work_started_...`: the first expectation is fixed by the code: removing a bracket after work started is major, "it adds or removes parts and it reopens parts already worked on". One expectation was genuinely changed. Archie's own **pure re-placement** (`replace_only`, no engineer request) expected major; it is now minor. That is the copilot's intended rule (founder 2026-11-20: the plan is Archie's own, only the brief binds), and it fits the rule you stated: pure re-placement may be minor. I added assertions that keep the founder's rule:
  - a redesign of a started or integrated part is major;
  - a removal of an approved part is major;
  - a change to a Ready part is minor.

**Tests, in pairs:**

| Files | Result |
|---|---|
| `test_program_revision` + `test_office_supervisor` | 36 passed |
| `test_office_orchestrator` + `test_office_copilot` | 29 passed |

`ruff` is clean.

**Parked:** PD-268, minor/major for revisions. A revision is major when it redesigns or removes a part past Ready, or removes a part the brief names. It is minor for pure re-placement and for changes to parts not started. Alternative: every Archie-initiated revision asked (the pre-copilot behaviour).
