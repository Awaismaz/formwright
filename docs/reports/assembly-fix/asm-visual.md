# Assembly wave 2026-11-19: visual assembly check + Archie tells the engineer (branch `wip/asm-visual`)

## What was wrong
- Nothing looked at an assembled result. The founder's gear pair (pinion m2 z20, gear m2 z60, two Ø20 shafts,
  4 × 6204, no housing) laid out as a row on the floor; `icd.problems()` was empty and the exact interference check
  said **0 clashes** (parts lying apart don't interfere), so the run "succeeded" with a pile of parts.
- Nobody told the engineer: Archie only spoke when spoken to.

## What changed
1. **Assembly picture** (`src/aicad/assembly/render.py`): 4 views (iso, front, top, right), parallel projection,
   Z up, one colour + numbered tag per item (copies share it), key top-left, floor grid at the lowest point, housings
   that wholly contain other parts drawn see-through. Two sources: an assembly document (exact face meshes from each
   snapshot's `topo.json`) or a Design Office skeleton (envelopes as boxes/cylinders along their axis, plus the
   bearings/dowels the ICD seats). Runs in a subprocess (`python -m aicad.assembly.render`), only the VTK modules
   it needs (import 1.0 s → 0.4 s).
2. **Quick placement checks** (`assembly/visual.py`, deterministic, ~5-10 ms, no kernel): parts that touch nothing
   (a row on the floor, a part floating apart; fastener stacks count as one body, parts-bin items ignored) and gear
   pairs from the recognised `info.component` (equal module, parallel axes): centre distance vs m (z1 + z2) / 2 and
   mid-plane offset (face width in mesh). On a skeleton: the same, plus gears that must mesh (ICD gear meshes, or
   the only two gears of one module in a sub-assembly) and bearings the layout gives no seat.
3. **Visual check** (`assembly/visual.py`): new LLM role `assembly_check` through the provider layer, image +
   intended relations in plain words (from the ICD, the plan's roles, or the document's mates and gear pairs),
   tolerant JSON verdict `looks_assembled / looks_wrong / unsure`, per relation ok/wrong/unsure + reason, visible
   problems (floating/row/interpenetration/orientation/missing). Unreadable answer → `unsure`, never a pass; a pass
   with a wrong relation is downgraded; text scrubbed. Model `haiku`, effort `low` (new optional `CallRequest.effort`,
   passed by the SDK provider), cap 15 platform tokens, 120 s wall clock. Metered and debited like other AI steps;
   simulated (fake agents) programs get a free look that follows the quick checks, labelled "Simulated".
4. **Policy** (`visual.decide` / `visual.confirm`, setting `FW_ASSEMBLY_VISUAL_CHECK`, default on, PD-73):
   - quick checks find a problem → stop with that reason (measured, the picture doesn't decide);
   - picture looks wrong → exact check on the flagged parts first; stop only when a measurement confirms it,
     otherwise report "not confirmed" and carry on (vision alone never stops a step);
   - looks assembled, every relation ok, quick checks clean → the exact check runs **in the background only when
     the estimate says measuring takes longer than looking did** (`estimate_exact`: uncached pairs from the pair cache
     × measured means + part load); otherwise it stays inline (faster *and* more reliable);
   - unsure / no AI / setting off → exact check inline as before.
5. **Assembly Studio**: smart run (`fitz.execute(check=False)` + `checks_by_policy`) logs "Fitz measured: …" lines,
   applies the policy, then looks in the background; `GET|POST /assemblies/{id}/visual`, `GET …/visual.png`;
   the Describe panel shows picture + verdict + measured findings + "Look again".
6. **Design Office, Archie on the go** (`office/visual_office.py`, `archie_chat.post`):
   - (a) at the interfaces gate (after brief approval, and "Look again" on the Interfaces tab): layout picture,
     quick checks, visual check, ICD problems read generically (string or `{code, message, items}`), one chat
     message with Apply-able fixes. New action `revise_plan` (only while the ICD waits and nothing started): the plan
     goes back to review with a note and optionally one part added (housing / base plate). `service.revise_plan`.
   - (b) after each sub-assembly / final integration: `Env.look_level` → quick checks (+ visual check); a measured
     problem blocks the integration ticket with the reason and Archie proposes `retry_blocked`; a parts-without-
     interface part apart from the rest is a note (the engineer was told at the gate); verdict goes on the ticket and,
     for the final assembly or anything not "looks assembled", into the chat.
   - (c) every blocked step (`_fail`) and the first retry of a design/fit/integrate step: what failed and what he
     proposes (no AI).
   - Chat history has its own lock (Archie posts while the orchestrator holds the program lock); the "Talk to Archie"
     button polls and shows an unread badge + toast when Archie spoke first; messages carry the picture and verdict.
   - Assembly tab: "looks" card (layout + each level). Interfaces tab: layout look card.

## Measurements (dev workstation, shared with ~5 agents; bench scripts in the agent scratch dir)
| step | case | time |
|---|---|---|
| render (skeleton, primitives) | gear pair 4 bodies / gearbox 10 bodies | 1.1-1.4 s (12.7 s once under heavy load; 10.5 s cold first run) |
| render (exact meshes) | gear pair, 8 Toolbox instances | 1.3-2.6 s |
| quick placement checks | gear pair / gearbox program | 5-10 ms |
| exact interference, uncached, warm worker | gearbox placeholders, 16 pairs | 0.34 s |
| exact interference, uncached | gear pair (Toolbox gears), 7 pairs | 1.2 s |
| interference + clearance (Studio "Check"), uncached | gearbox placeholders / gear pair | 1.9-2.1 s / 5.5-19.6 s (gear-flank min distance dominates) |
| same, first call in a fresh worker | gear pair | 23.8 s (worker 4.3 s + part load ~5 s) |
| same, cached | any | 0.01-0.02 s |
| visual check (one vision call) | 6 live looks | 8-40 s, median ~20 s; one outlier 400 s under load (now capped at 120 s) |

**Before/after on the steps that block:** at 10-30 instances the exact checks are faster than a look (≤ 2 s for
placeholders, 0.02 s cached), so the policy keeps them inline: no step got slower, and none was relaxed where it
would cost reliability. A look first + background exact check only happens when the estimate exceeds ~20 s (first
check of real gear assemblies with clearance, large programs). The office integration steps already did no geometry
checking (PD-71); they now add the 10 ms quick checks and, with AI, one look (~20 s, 2 tokens) per level.

## What vision catches and misses (live, haiku, low effort)
| case | quick checks (measured) | visual check |
|---|---|---|
| parts in a row on the floor (Studio, and the office layout) | row: N of N touch nothing | **looks_wrong**, every relation wrong, "lie apart in a row" |
| correct gear pair | clean; centre 80.0, offset 0, 20/20 mm in mesh | **looks_assembled**, all ok ("tooth contact depth not visible") |
| gear 5 mm off the mesh plane | gear_plane: 5 mm, 15 of 20 mm face width | **unsure** ("appear offset by a few mm … can't confirm") |
| bearing 60 mm off its shaft | floating: Ball bearing 6204<4> touches nothing | **looks_wrong**, found it (miscounted: "a fifth bearing") |
| office layout of the test case (row, 0 interfaces) | row + 4 bearings with no seat | **looks_wrong**: "neither gear sits on a shaft … bearings loose" |
| office layout after Archie's "add a housing" (today's engine stacks the gear on the pinion's axis) | gear_centre: must mesh 80 mm apart, axes 0 mm apart | **looks_wrong**: "gear centred on the input shaft axis, nothing on the output shaft meshes; output shaft has no bearings" |

Vision judges against the relations it is given: on the stacked layout it marked the ICD's own (wrong) relation
"Gear passes through the bore of Input shaft" as ok. Fixed: the brief's gear mesh (from the plan roles) is now
always among the relations when the ICD has no gear mesh.

So: vision reliably sees gross arrangement errors and explains them in words an engineer would use; it does not
measure (a 5 mm offset is "unsure", counts can be off). Every defect above was also caught deterministically by the
quick checks in milliseconds. That is why the policy never lets a look pass or stop anything alone, and why the cheap
targeted checks run whatever the picture says.

**Cost per look:** $0.010-0.020 = 2 platform tokens with haiku/low (cache creation ~48k tokens per call: the Claude
Code harness context). The default (larger) model hit a $0.30 cap on one look: not used. Live spend this session:
about 57 platform tokens over 12 calls, of which ~45 are two failed looks that hit their caps (the default-model try,
$0.30; one server look that ran 400 s and hit the $0.15 cap under heavy machine load, after which the 120 s limit was
added). The 10 successful looks cost 2 tokens each.

**Robustness seen live:** once the machine was so loaded that the picture took >60 s and was skipped; Archie still
posted the measured findings and the proposal, and "Look again" produced the picture and verdict (30.6 s).

## Evidence
- Tests: `tests/test_assembly_visual.py` (21 tests: render, quick checks on hand-built Toolbox gear pairs, recorded
  replies through the stub provider, policy table, Archie messages, revise-plan, generic ICD problems). `tests/conftest.py`
  turns the live look off for every test unless a test opts in. Ran also: `test_office_archie_chat.py`,
  `test_llm_providers.py`, `test_office_orchestrator.py` (66 passed; one orchestrator test timed out once under
  load and passed alone), ruff clean, `tsc --noEmit` clean, `vite build` ok.
- Walkthrough (port 8793, scratch data, live haiku looks), screenshots in the agent scratch dir
  `fw-e2e-8793/shots/`: `office-2-unread-badge.png` (badge on Talk to Archie), `office-1b-layout-look-card.png`
  (Interfaces tab: picture, verdict per relation, measured findings), `office-4-plan-back-for-review.png` (Archie's
  "add a housing" applied: plan back for review with the Housing row and his note, toast "Archie has something to tell
  you"), `office-6-archie-after-housing.png` + `office-3-archie-chat.png` (second look: stacked gears measured, picture
  in the chat, 2 tokens), `studio-2-visual-check.png` (Assembly Studio after a smart assembly: looks wrong, "8 of 8
  parts touch nothing"). 0 console errors.

## Left / not done
- No full simulated office run through integration with screenshots of the level look (covered by unit tests of
  `level_message`/`known_loose`; the orchestrator path is exercised in simulated mode but not walked in the browser).
- Swap-in and the build-time exact check are unchanged (measured cheap; per-part looks would cost 2 tokens × parts).
- Hex reads "spur gear m2 z20" as z24 / bore 10 (Toolbox default) in Assembly Studio: Hex reading, not this branch.
- Routing `assembly_check` to the API provider (PD-09) would cut each look from ~50k context tokens to ~3k.
- The "add a housing" proposal relies on the layout engine; today it stacks the gears (the next look says so).

## Parked decisions
- **PD-73** (default used): visual check on (`FW_ASSEMBLY_VISUAL_CHECK=1`), model haiku / effort low, 15-token cap,
  120 s limit; vision is advisory: it never stops a step alone (only a measurement does) and never skips the exact
  check unless measuring is estimated slower than looking; the office stops an integration on a measured row /
  floating part / gear mismatch; parts the approved layout leaves without an interface are a note.
