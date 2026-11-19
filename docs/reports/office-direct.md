# Design Office: parts built from the interface spec (no AI)

Branch `wip/office-direct`. Goal (founder): make part modelling in the Design Office substantially faster, without the
LLM wherever the structure allows it.

## What changed

**The direct path.** When a ticket's part is fully fixed by the approved ICD and skeleton, the Design Office writes the
Studio model script itself and builds it through exactly the gate an agent's build goes through. No model call, no
tokens, seconds instead of minutes.

- `src/aicad/office/direct.py` (new, pure, no kernel): `plan(doc, ticket)` decides per ticket and writes the script.
  - **Shafts**: the diameter profile from the interfaces (bearing journals, gear / hub seats, shoulders where a journal
    is turned down below the shaft Ø), DIN 6885 keyseats on the side the key interface states, 45° end chamfers, R0.5
    shoulder fillets where there are shoulders. Every face the ICD states (end face flush with a plate, bearing
    shoulders) is checked to be an end or a shoulder of that profile.
  - **Spacers / sleeves / collars / bushes** (a hub-role item named so): a bored ring to the envelope, 0.5 mm edge breaks.
  - **Spur gears** that the Toolbox doesn't supply: module, teeth, face width, pressure angle, bore, and the hub keyway
    (DIN 6885 t2) at the exact angle in the gear's frame (a gear turned half a pitch for its mesh has its keyway at
    -3°). True involute flanks through `fw.spur_gear`.
  - Everything else (blocks, plates, housings, pulleys, caps) goes to the design agent as before.
- **The script** is a normal Studio script: a docstring that lists every interface the part carries with its span,
  `NAME`, `MATERIAL`, one driving dimension per line, `PARAMS`, `PARAM_META` limits, `fw.stepped_shaft` /
  `fw.shaft_keyway` / `fw.spur_gear` with EXPECTED from their hand formulas. Segment lengths are dimensioned from the
  -Z end, the body takes up the rest of `LENGTH`, so an engineer can tune it in the Studio without tokens (parameter
  edit, viewport dimensions DS-038 map `LENGTH`, both diameters, journal lengths and the keyseat). No agent internals
  appear in it or in the chat.
- **The decision** (`plan`): direct only when the program's ICD is approved, the part is one of the kinds above, every
  ICD feature on it maps onto a generated feature, and the brief asks for nothing more. "Nothing more" is checked on the
  part's own description, plus program-brief sentences about that kind of part, for features the interfaces don't size
  (thread, groove / circlip, undercut, flat, cross hole, spline, knurl, set screw, hex, taper, slot, centre holes,
  helical teeth, hub on a gear, web / recess, seals, flange, special gear forms, a key the ICD doesn't size, a shoulder
  it doesn't place) and for sizes the interfaces don't explain (the part's own planned envelope statement, which the
  approved ICD supersedes, is not an extra). Anything not determined: the agent, with the reasons recorded. An
  incomplete or malformed ICD entry falls back the same way.
- **Seed.** When the interfaces fix the part and only such extras are missing, the direct model is built first and the
  agent is told to start from it and add only the extras (`direct.seed_prompt`).
- `orchestrator.py`: `_direct_plan` / `_direct` before the agent in the design stage. Direct runs on a ticket's first
  design turn, and again on an ICD change only while the model is still byte-for-byte the one it wrote (sha in
  `ticket.direct`): an engineer's or an agent's edit is never overwritten. Findings from Gage or the engineer's
  comments always go to the agent. A direct build that fails the gate falls back to the agent in the same stage.
  Gage still measures ICD conformance and the gating checks; the AI review note is skipped for an unchanged direct
  build (there is nothing in the brief beyond what is measured). Direct tickets don't teach the designer's rate
  (calibration), since seconds of building would skew the estimates.
- `platform_env.py`: `PlatformEnv.design_direct` writes `model.py` and builds through `tools.build_handler` (the design
  agent's build tool: CHK-02..05, topology and render now; exports, CHK-07, CHK-08 in the background on the same warm
  worker), awaits the deferred checks, snapshots the revision (kind `interface`), maps the viewport dimensions, and keeps
  the Studio chat busy meanwhile.
- **Gears and the Toolbox (master's live-run finding 8).** `hex_lookup` no longer takes a designed gear the ICD fixes
  as a plain Toolbox gear (which dropped the ICD keyway and the plan's material, e.g. 42CrMo4): the design stage builds
  it direct with bore, DIN 6885 hub keyway (t2) and the material read from the plan (word-bounded: 42CrMo4 / 4140 →
  Steel 4140, C45 → Steel 1045, stainless, aluminium, bronze, POM...). With the direct path off, a keyed designed gear
  still skips the Toolbox (the designer makes it); an unkeyed one is taken from the Toolbox as before.
- **Grooves and bearing corners, read generically (finding 3).** A shaft feature of type `groove` (the DIN 471 circlip
  groove `wip/toolbox-keys` will put in the ICD) is cut from whatever fields it carries: span `z0`/`z1`, or `z` with
  `width`/`w`/`m`; groove Ø `d2`/`groove_d`, or the shaft Ø less twice `depth`/`t`. Parameters `GROOVE_D`,
  `GROOVE_WIDTH`, `GROOVE_START`; the removed volume π/4 (Ø² − d2²) × m is in EXPECTED. A bearing interface giving
  `r_s_min` (or `r_s`, `corner_chamfer`) caps the shoulder fillet at 0.8 × r_s (default R0.5, below the 6204's r_s min
  1.0). Keyseats come from the key interface (b, t1, span, side). Unknown feature types still fall back to the agent,
  so new ICD fields never produce a wrong part silently. A brief that says "circlip" is not an extra when the ICD
  places the groove.
- **Engine warm-up.** The organisation's build worker is started at ICD approval and again when Run is pressed, so the
  first direct builds don't wait for a cold worker (simulated program 21.4 s → 16.0 s wall).
- `fw_std.py`: backward-compatible options: `stepped_shaft(z0=)`, `spur_gear(z0=, keyway_angle=)`,
  `shaft_keyway(angle=)`. Defaults unchanged (Z from 0, keyways on +Y).
- Ticket UI (`TicketDrawer.tsx`, `Board.tsx`, `types.ts`): a "no AI" badge on the card; in the drawer "Built from the
  interface spec (no AI) in N s: shaft Ø20 × 120, … every size from ICD v1; 0 tokens", or "Designed with AI: <why>"
  (and whether it started from the interface model), or "Started from the interface spec; the designer has changed it
  since".
- Switch: `FW_OFFICE_DIRECT=0` (environment) or `direct_build: false` on a program turns the path off.

## Measurements (founder's test case: 1:3 spur pair m2 20/60, two Ø20 × 120 shafts, four 6204, no housing)

| | Before (LLM per designed part) | After (direct) |
|---|---|---|
| Live, whole program, Run to complete | master's live run 2026-11-19 (`assembly-fix/live-gear-run.md`): about 6.5 min machine time (17 min wall with stops), **689 platform tokens**; design turns 70-125 s and about 300 tokens per part; Gage AI notes 11-19 s per part | **16.4 s, 0 tokens** (this branch on :8798: real platform and build worker, no simulated agents; visual check off). 4 real parts + 4 bearings, 6 mates, **0 clashes** |
| Per designed part, live | gear shaft $2.96 in 3 turns, gear $3.01 in 4 turns, 70-80 s each, then Gage 11-19 s | Pinion 8.4 s, Gear 9.1 s, Input shaft 9.1 s, Output shaft 3.5 s (build 1.9 s + CHK-07/08 1.6 s); Gage 0.9-2.5 s (measurements only) |
| Simulated (fake agents) | 27.4 s wall, 3 fake agent turns (a fake turn takes about 0 s, so this hides the LLM time entirely), 105 tokens | 16.0 s wall, 0 agent turns, 0 tokens |

- The first three parts are claimed together and queue on the organisation's one build worker (about 9 s each); a part
  built alone takes 3-3.5 s (shaft: build 1.7-1.9 s, deferred CHK-07 + CHK-08 1.4-1.6 s).
- Loaded machine (about 5 agents). No live "before" on this branch: the master's live measurement of the same case
  (same day) is the baseline; repeating it would have cost about 600 tokens. Live run spend on this branch: 0 tokens.
- Evidence in `docs/reports/office-direct/`: `live_pair_direct.json`, `sim_direct_on.json`, `sim_direct_off.json`,
  `board.png` ("no AI" badges), `drawer-shaft.png` ("Built from the interface spec (no AI) in 9.1 s: shaft Ø20 × 120,
  2 bearing journals, 1 seat, Steel 1045 (medium carbon). Every size comes from ICD v1; 0 tokens."). Puppeteer-core
  walk on :8798, 0 console / page errors; the badge wrapped on two lines and was fixed.

## Tests (`tests/test_office_direct.py`, 10 tests, about 50 s; no live AI)
- Hand-checked values: journal Ø20 = 6204 bore (ISO 15: d 20, D 47, B 14); shaft 120 from the skeleton, journals Z
  -29..-15 / 15..29; gear tip Ø m (z + 2) = 44 / 124; DIN 6885 for d = 20: b 6, t1 3.5, t2 2.8 (measured on the built
  shaft and pinion: 6.000 wide, 3.5 / 2.8 deep); for d = 25: b 8, t1 4; a Ø25 shaft in 6204s: journals 46 long, body
  48; the output gear's keyway at -3° (half a pitch of 60 teeth); volumes by Pappus (shaft chamfers, spacer, circlip
  groove π/4 (20² - 19²) × 1.3).
- The gate: CHK-02..05, 07, 08 pass and `runner.is_verified`; ICD conformance passes for the plain and stepped shafts,
  the keyed pinion and shaft, the spacer.
- Decision and fallbacks: no approved ICD, standard parts, blocks / plates, a thread / circlip groove / collar size /
  hub / unsized key in the brief (agent, with the seed), program-brief sentences per kind of part, "M2" as a module is
  not a thread, the superseded planned size is not an extra, incomplete ICD entries (agent, no seed), the switch.
- The program end to end (simulated agents): all four designed parts direct, **zero design-agent turns**, 0 tokens,
  Gage's note says why there is no AI note, not used for calibration, a parameter edit without AI (`CHAMFER` 1 → 0.5:
  revision 2 `params` after revision 1 `interface`), final assembly 0 clashes. The plan's keyed 42CrMo4 pinion keeps
  keyway and material (Hex leaves it to the design stage).
- `fw_std` placement options keep the hand formulas. Viewport dimensions (DS-038) map `LENGTH` 140, `D`, `D_JOURNAL`,
  `L_JOURNAL_1/2` 46, `KEY_LENGTH` 18, `KEY_START` 52 on the stepped shaft.
- Neighbours run after `git merge main`: `test_office_shaft_line`, `test_office_orchestrator`, `test_office_icd`,
  `test_pipeline_speed`, `test_dims` (and before the merge every `test_office*`). Failures not from this branch:
  `test_gage_sends_back_then_approves_and_caps_retries` (fails on main, see the live-gear report) and
  `test_office_phase5::test_bearing_seats_keys_dowels_and_rotation_layout` (`icd.seated` returns an extra
  `interfaces` key; `icd.py` is untouched here). `test_program_runs_end_to_end` failed once under heavy load (milestone
  event order) and passed on its own and in its own file; it reads only the latest 500 activity events, so a busier run can cut the plate's first milestones (test fragility, left for the master).

## Coverage and what is left
- Covered: shafts (plain and stepped; journals, seats, shoulders, keyseats, circlip grooves when the ICD gives them,
  end chamfers, shoulder fillets), spacers / sleeves / collars / bushes as bored rings, designed spur gears (bore, hub
  keyway, plan material). Shaft-line and block (plate) layouts.
- Not yet: keyed spacers, gears with hubs (the ICD has no hub size), pulleys, caps, flanges, blocks and plates (holes
  and seats are in the ICD, but outline, pockets and ribs are design choices), helical gears. These go to the agent
  with the reasons shown on the ticket.
- Ticket estimates are still the designer's minutes (the board shows "7 min est." for a 9 s part). Re-estimating
  direct tickets at ICD approval would make the timeline honest; not done.
- The first builds share one worker per organisation; a second worker would cut the queue (about 9 s to 3.5 s).
- The seed path (agent starting from the direct model) is tested at the decision level; not run with a live agent.
- Keys and circlips as parts (seated in the keyseat / groove) are `wip/toolbox-keys`' work; the shaft side here reads
  their interface fields generically.

## Parked decisions (numbers to be assigned by the master)
- **PD-xx Skip Gage's AI note for unchanged direct builds.** Default: skipped (ICD conformance + gating checks are the
  whole review; the brief asked for nothing more). Alternative: keep it (about 15 s and a few tokens per part).
- **PD-xx Designed gears: direct build rather than the Toolbox gear.** Default: direct whenever the ICD fixes the gear
  (keeps keyway and material, gives an editable Studio part and spline involute B-rep). Alternative: Toolbox gear for
  unkeyed gears (no design time, but no material and polygon teeth).
- **PD-xx Default materials and finish of direct parts.** Default: shafts and gears Steel 1045 (C45), spacers Steel
  1018, unless the plan names one; 1 mm × 45° shaft end chamfers (0.5 under Ø15), R0.5 shoulder fillets (at most 0.8
  r_s min when the interface gives it), 0.5 mm spacer edge breaks; a spacer's outside Ø is the layout envelope when the
  brief gives none (said in the script header).
- **PD-xx The direct path is on by default**, switchable per program (`direct_build: false`) and globally
  (`FW_OFFICE_DIRECT=0`); no UI toggle yet.

## Files
- New: `src/aicad/office/direct.py`, `tests/test_office_direct.py`, this report and `docs/reports/office-direct/`.
- Changed: `src/aicad/office/orchestrator.py` (design stage, review note, calibration, warm-up, `Env.design_direct`,
  `Env.warm`), `src/aicad/office/platform_env.py` (`design_direct`, `warm`, `hex_lookup` gears, warm-up at ICD
  approval), `src/aicad/fw_std.py` (z0 / keyway angle options), `web/src/pages/app/office/{Board,TicketDrawer}.tsx`,
  `types.ts`. No Studio files (`fw.py`, `runner.py`, `routers/studio.py`, `ProjectStudio.tsx`) touched.
