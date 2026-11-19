# Small programs in the Design Office (branch `wip/office-small`)

Founder, 2026-11-19: *"I gave this command to Design studio 'Build a Spur Gear mounted on stepped Shaft and locked
with a key'. It built that in a minute as multibody part. Same command when given to Design Office, makes it
unnecessarily complex and at the end, it still ends up with wrong assembly. It also forces me to have housing for the
shaft, without which it does not even proceed."*

## What went wrong (founder's program "Test 5", read only)
Brief: *"Build a Spur Gear, mounted on shaft and locked with a key. No extra items. Just a spur gear, a shaft and a
key"*. Events and plan history show five causes, not three:

1. **The gate forced the housing.** Archie's first plan was right (shaft, key, gear, no housing). The layout was a
   shaft line, and the ICD rule `shaft_support` (PD-85) blocked: "runs in 0 bearings ... Plan two more bearings per
   shaft, or a housing." The founder sent the plan back twice; the second time he asked for "one minimal support
   housing ... Its only purpose is to satisfy the shaft support rule." With the housing the layout became `block`.
2. **The key went to the parts bin.** Archie put the key in a "Keyed shaft" group and the gear in its own group.
   `take_key` only looked in the gear's own sub-assembly, so the key interface had `key_item: null` and Fitz binned the
   key ("Fitz integrated Keyed shaft: 1 part in the parts bin").
3. **Archie's prompt forced 2 sub-assemblies** ("2 to 8 sub-assemblies"); his own narrative says "The planning rules
   need at least two sub-assemblies". That doubled the integration tickets.
4. **9 tickets for 3 parts**: 4 parts, 2 sub-assembly integrations, the final assembly, drawings and the manufacturing
   review. The housing and the shaft were designed with AI (Mill 1.0 min, Chuck 44 s).
5. Found on the way: "20 mm h6 diameter" was read as a **Ø6** shaft (the "6" of h6), and in the live run a stepped
   shaft's seat was taken from its envelope (Ø25) instead of "20 mm k6 gear seat".

## What changed
### A. The brief is respected (`office/scope.py`, `planner.py`, router)
- `scope.mentions(brief)` reads which kinds of part the brief names and which it excludes ("no", "without", "not",
  "except"; a comma list after a negation stays negated). `scope.exclusive` spots a limited brief ("just", "only", "no
  extra items", "nothing else"). `scope.kind_of(name)` reads a part's kind by its head noun ("Shaft support housing"
  is a housing, "Pinion key" a key, "Gear shaft" a shaft).
- `planner.finish(plan, name, brief)` is the post-check on every plan a planner makes (Archie, or the standard
  breakdown, including Archie's fallback). It drops parts of an excluded kind, or, when the brief is exclusive, of a
  kind it doesn't name, and records a note shown at plan review. Founder's case, verbatim: *"You asked for just a spur
  gear, a shaft and a key, so I left out the shaft support housing I'd normally add. Add it back here if you want
  it."* Parts of an unknown kind stay; a plan is never emptied; the engineer's own edits are never touched.
- Archie's prompt: plan exactly what is asked; a limited brief gets those parts and nothing else; "A shaft with what it
  carries ... and no bearings or housing is a normal deliverable: a sub-assembly that goes into the customer's own
  machine. Never add a part only to make the layout complete."; 1 to 8 sub-assemblies, a small product is one; for a
  stepped shaft give the diameters, not step lengths.
- The standard planner no longer falls back to the generic frame-and-housing breakdown when a brief names its parts:
  `scope.named_plan` gives exactly those parts (founder's sentence: Stepped shaft, Spur gear, Parallel key).
- Archie's deterministic layout proposal never offers a housing or base plate when the brief rules one out.

### B. The shaft sub-assembly (`office/icd.py`, `direct.py`, `program_assembly.py`, `assembly/visual.py`)
- A shaft line with **no bearing anywhere in the plan** is a shaft sub-assembly (`skeleton.shaft_subassembly`). The
  shaft is the fixed base, axis +Y on Z = 0.
- **Stepped shaft** (the shaft's text or the brief's shaft sentences say stepped / shoulder): the seat Ø and the step Ø
  come from the description ("20 mm k6 gear seat", "25 mm larger step", Ø values), else the hub's stated bore under a
  larger planned Ø, else the step is `icd.shoulder_for(d)` (assumed, said so). The hub sits on the seat against the
  shoulder; one shaft on its own puts the shoulder face on datum B (Y = 0), the gear on its -Y side; the seat runs
  `SEAT_END` = 2 mm past the free hub face; the body runs on to the planned / written length.
- `shaft_bore` carries `seat_z`, `shoulder_z`, `shoulder_d`, `side`; the shaft side gets the seat boss over its span
  and the shoulder face, the hub side its face against the shoulder. Fitz mates them **concentric + coincident at the
  shoulder**; the `key` interface (from `wip/toolbox-keys`) and `seated()` put the DIN 6885 key in the keyseat.
- `shaft_support` is a **warning** when the plan has no bearings at all ("Stepped shaft: no bearings or housing in the
  plan, so it is delivered as a sub-assembly (the shaft with what it carries); what carries it is outside this
  program."). It still **blocks** when bearings are planned but don't carry the shaft (tested). The visual check reads
  it as a note.
- A key planned in another sub-assembly is now taken (`take_key` falls back to any sub-assembly); in a shaft
  sub-assembly a hub is keyed whenever a key is planned.
- Direct path: a stepped seat, its segment lengths and the key the keyseat takes (h, t2, length) are sizes the
  interfaces explain; "hub keyway" is not a hub; zero bearing journals are not listed; **no shoulder fillet against a
  hub** (the direct gear's bore edge is sharp: an R0.5 fillet overlapped it by 3.08 mm³, found by the kernel test).
- `_worded` / `_diameters` no longer read "h6" / "k6" as a size.

### C. The light path for small programs (PD-93)
- Rule: **at most 6 part lines and 8 pieces** (`scope.small`). A small plan whose parts are all a shaft and what
  rides on it is also merged into **one sub-assembly** (`scope.rides_on_shafts`), so 3 parts make 5 tickets, not 9.
- Plan review shows "Small program · 3 parts" with **Approve and build** (`POST /gates/express`): it approves the
  plan, and when Archie's interfaces have **0 problems** it approves them too and presses Run. With a problem it stops
  at the interfaces gate as usual. What was approved is recorded (`program.express`, ICD history "approved together
  with the plan", activity `gate.express`) and shown on the program page: "Approved in one step by Founder: the plan
  (Stepped shaft, Spur gear, Parallel key) and the interfaces (ICD v1, 2 interfaces: keyed joint, shaft / bore fit; 0
  problems)", with the note.
- Drawings and the manufacturing review: the New program form has a visible choice (Automatic / Always / Only when I
  ask). Automatic = on, except for a small program whose brief doesn't ask for drawings, a BOM, DFM or release. The
  program page says so and has a button **Add drawings and manufacturing review**; after assembly it opens Ortho's and
  Smithy's tickets and runs them at once (they cost no tokens). Never a silent removal.
- Fitz, Gage and the visual check run exactly as before.

## Before and after
| | Before (founder's "Test 5", 2026-11-19) | After, simulated agents (:8805) | After, live agents (:8805, one run) |
|---|---|---|---|
| Plan | 4 parts incl. "Shaft support housing" (forced by the gate), 2 sub-assemblies | 3 parts, 1 sub-assembly (standard planner, no AI) | Archie: 3 parts, 1 sub-assembly, "Bearings, housing, retaining rings and fasteners are left out because the brief doesn't ask for them" |
| Gates | blocked by `shaft_support` until a housing was added (2 plan revisions) | plan + ICD in one click, 0 problems, 1 note | same |
| Tickets | 9 (incl. 2 sub integrations, drawings, DFM) | 5 | 5 |
| Parts built with AI | housing (Mill 1.0 min), shaft (Chuck 44 s) | none (shaft and gear direct, key from the Toolbox) | shaft (Chuck, 70 s, 23 tokens: seat misread, fixed since, see below) |
| Assembly | key in the parts bin; layout `block` on a housing | gear on the seat at the shoulder, key in its keyseat, 0 clashes, nothing binned | gear at the shoulder, key seated, 0 clashes, nothing binned |
| Time, Run / one click to assembled | 84 s (+ 3 s deliverables), after 3 plan approvals | **19.9 s** (quiet machine; pytest 17.7 s); 85 s replaying the live plan with CPU at 53 % from other agents | 122 s (Archie's plan 23 s before that) |
| Tokens | not charged (God mode) | 0 | **34** (Archie plan 6, Chuck 23, two visual looks about 5); wallet 1,000 to 966 |

The live run exposed one more misreading: Archie wrote "stepped shaft with 20 mm k6 gear seat and 25 mm larger step",
with an envelope Ø25; the layout took Ø25 as the seat (8 x 7 key, gear bored 25), so Chuck designed the shaft with AI
(the direct path saw "20 mm" and "6 mm" it couldn't explain, and Chuck added an unasked keyed end) and Hex took a
Toolbox gear. Fixed (`_STEP_D`, `_bore_hint`, written overall length), and that exact plan is now a standing test
(`test_archies_live_plan_reads_its_steps_and_builds_without_ai`). Replaying it through the app with simulated agents:
both parts built from the interfaces (shaft "Ø20 / Ø25 × 120, 1 seat, 1 keyseat", gear "m2 × 40 teeth, face 20, bore
Ø20 with a keyway"), key 6 x 6 x 18 at (6.5, -10, 0), 0 clashes. Expected live cost after the fix: Archie about 6
tokens plus two visual looks, no design turn. I made only the one live run the brief allowed, so that is not measured
live.

## Hand-checked numbers (`tests/test_office_small.py`)
Founder's sentence, standard planner: gear m2 × 30 (assumed), tip Ø m (z + 2) = 64, face 10 m = 20; seat Ø20, step
Ø20 + 2 max(2.5, 0.1 × 20 + 1) = Ø26; shaft 80. Shoulder face Y = 0, gear Y -20..0 (centre (0, -10, 0)), seat Y
-22..0, shaft Y -22..58 (centre (0, 18, 0)). DIN 6885 for Ø20: 6 × 6, t1 3.5, t2 2.8, key length floor(max(b + 2,
B - 2)) = 18, span Y -19..-1 (centred on the hub, inside it), base point (10 - 3.5, -10, 0) = (6.5, -10, 0). Kernel
check of the direct shaft, the direct gear and the Toolbox key where Fitz puts them: every pair overlaps < 1e-6 mm³,
gear and key touch the shaft, the key touches the hub keyway walls; shaft and gear pass Gage's ICD conformance. Live
plan: Ø20 / Ø25 × 120, gear m2 × 40 tip Ø84, shaft centre Y 38.

Tests: `tests/test_office_small.py` 11 passed (scope, planner note, standard plan, prompt, layout, live plan, failing
run's plan, shaft support still blocks with bearings, direct decisions, kernel fit, end to end: 5 tickets, 3
instances, key at (6.5, -10, 0), nothing binned, gates approved together, deliverables off with the reason).
Neighbours, one or two files per run, workers reaped after each: `test_office_shaft_line` + `test_office_icd` 23,
`test_office_direct` + `test_assembly_visual` 36, `test_office_polish` + `test_office_orchestrator` 33,
`test_office` + `test_office_archie_chat` 33, `test_office_phase5` + `test_office_phase6_layout` 14,
`test_office_gearbox_caps` + `test_office_layout_envelopes` 20, `test_toolbox_keys` + `test_office_phase6_review_ecn`
17: all passed. `ruff check src tests` clean; `tsc --noEmit` clean; `vite build` ok.

## Screenshots (read; `docs/reports/office-small/`)
- `1-plan-review-live.png`: Archie's live plan, 3 parts in one sub-assembly, the "Small program · 3 parts" card with
  Approve and build.
- `2-approved-in-one-step.png`: what was approved in one step, the sub-assembly note, the drawings switch.
- `3-interfaces-subassembly.png`: layout warning (not blocking), datum B = shoulder face of the Stepped shaft.
- `4-assembly-standard-plan.png`, `7-assembly-tab.png`: Assembly Studio and the Assembly tab: the gear on the Ø20
  seat against the Ø26 step, the key end visible in the hub keyway, 2 mates (concentric Ø20, coincident at the
  shoulder). Nothing floats.
- `5-assembly-live-before-fix.png`: the live run: assembled correctly, but on a Ø25 seat, with the extra keyed end
  Chuck added.
- `6-assembly-live-plan-after-fix.png`: the same plan after the fix: Ø20 seat, Ø25 step, key seated.
- `live-run-activity.txt`: the live run's activity log.
Fixed from the shots: the one-step button text overflowed its card ("Approve and build" now); the small-program text
repeated its heading; "1 sub-assemblies".

## Parked decisions (default used)
- **PD-93 light path.** Small = at most 6 part lines and 8 pieces. One click approves plan and interfaces and runs when
  the interfaces have 0 problems; drawings and the manufacturing review wait for the engineer unless the brief asks
  (or the program was created with "Always"). A small plan made only of a shaft and what rides on it is one
  sub-assembly. Alternatives: auto-advance with no click at all; a higher limit.
- **PD-94 shaft sub-assembly.** No bearing anywhere in the plan (and no housing, by definition of a shaft line):
  `shaft_support` is a warning, the shaft is delivered as a sub-assembly. Planned bearings that don't carry the shaft
  still block.
- **PD-95 stepped shaft defaults.** Step Ø = round(d + 2 max(2.5, 0.1 d + 1)) when the plan gives none; the seat runs
  2 mm past the free hub face; one shaft: the hub at the -Y end against the shoulder, datum B = the shoulder face;
  unplanned length = seat + max(hub + 10, 2 d).
- **PD-96 shoulder corner against a hub.** Sharp (no fillet), because the direct gear's bore has no chamfer.
  Alternative: a C0.5 bore chamfer on direct gears and an R0.4 shoulder fillet (better for fatigue; changes the gear's
  hand volume formula).
- **PD-97 brief scope.** The post-check runs on planner output only (never on the engineer's edits); parts of an
  unknown kind are kept; "just" and "only" make a brief exclusive.

## Not done / follow-ups
- Plan review still shows designer-minute estimates ("5 tickets, 29 min, ETA 14 to 39 min") for a program that
  assembles in 20 s to 2 min. Direct tickets should be re-estimated (also noted by `wip/office-direct`).
- A one-sub-assembly program looks at the same assembly twice (sub level and final, 11 to 19 s each live). Kept, since
  the brief asked for the visual check to behave the same; reusing the sub-level verdict would save one look.
- The direct gear has no bore chamfer (PD-96).
- Archie's chat can still propose a housing when the engineer asks for one in words (their call); his automatic
  proposals respect the brief.
- The founder's program "Test 5" was not touched; a new program with the same brief now plans, lays out and assembles
  without the housing.

## Files
New: `src/aicad/office/scope.py`, `tests/test_office_small.py`, this report and `docs/reports/office-small/`.
Changed: `src/aicad/office/{icd,direct,planner,service,interfaces,visual_office,program_assembly}.py`,
`src/aicad/assembly/visual.py`, `src/aicad/platform/routers/office.py` (express route, deliverables mode, planner
post-check, deliverables now start at once), `web/src/pages/app/office/{PlanReview,ProgramPage,NewProgram,Deliverables}.tsx`,
`types.ts`. No Studio files, no marketing / auth / landing files.
