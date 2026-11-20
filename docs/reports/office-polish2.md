# Office polish 2 (branch `wip/office-polish2`, from main 6def675)

Seven fixes from the founder's TEST Project, Archie's live run, the generators report and the program-revision
report. Each has a test; the visible ones were walked in the browser on port 8814 (simulated agents, own data dir).

## 1. Stale "Looks wrong" after a revision or a re-run
**Cause.** The Assembly tab read the look records from disk with no notion of what they described. A revision dropped
the Interfaces tab's copy of the gate look (`icd.look`) but not the record, and a level's record stayed until a new
look overwrote it. The founder's "Top: Looks wrong" had a second cause: the Top level holds the table top alone, and
the relation builder still asked "the other parts mount on Table top", which no picture of one part can show.

**Fix.**
- `visual_office.looks()` (the router's `_looks` now calls it) marks a look `superseded`, with the reason, when:
  - the layout look was taken on an older ICD version (records now carry `icd_version`; older ones are compared with
    the latest revision's time): "Superseded by REV-1 (ICD v2): this look is of the earlier layout";
  - a level runs again (the orchestrator drops `ticket.look` at the start of every integration, as the revision
    already did on reset): "Superseded: Legs runs again; Fitz looks again once it is assembled";
  - the level was judged against a relation today's layout no longer states (the TEST Top case);
  - the level's assembly changed since the look (geometry signature).
- After a revision (and its undo) the program assembly rebuild takes a new look of the revised layout
  (`revision.look_again` → `layout_look(revised=REV-n)`), labelled "Layout (REV-1)", with a short chat message and no
  offers. Metered like the gate look; without a request behind it (undo, restart) only the free checks run.
- `relations_from_skeleton`: no "the other parts mount on X" (and no "assembled as the brief describes") for a level
  of one part; `level_look` skips the picture when there is nothing to judge.
- UI: the chip reads **Superseded** (no old verdict), with the reason above the picture.
- On a copy of the founder's TEST Project (read-only copy): Layout → superseded by REV-1, Top → superseded (relation
  no longer stated), Legs and Final stay "Looks assembled".

## 2. M5 where the brief says M6
**Cause.** `icd.build` took the bolt size from the plan's standard parts' text, else from the span rule
(`fastener_for`); the standard planner's "Frame bolt" said no size, so the cover joint got M5. The graph layout had
the same fallback.
**Fix.** `icd.brief_fastener(brief)`: the one metric size the brief states explicitly (upper-case M, not next to
"module", so "m2, 20/60 teeth" is never a screw; a brief with two sizes leaves it per joint). It wins over the plan's
hints and the span rule in `icd.build` and in the graph layout's fallback; screws the plan names for bearing caps keep
their own size. `planner.brief_fasteners` (in `standard_plan` and `finish`, so Archie's plans too) writes the size on
the plan's bolt lines and the count ("joined by 4 M6 bolts" → qty 4) when there is one bolt line.
Result on the live-run brief: plan "Frame bolt ×4, M6 as the brief states", IF-01 `4 × Ø6.6 (M6)`.

## 3. Stepped coupling bores (generators finding G1)
The graph layout now gives a coupling between two shaft sizes a `bore_z` span per bore: each bore runs from its end
face to the middle of the gap, where they meet. `icd.side_features` turns it into a hole with `z0/z1` and `span`; the
ICD excerpt says so in words; conformance measures a spanned bore like a seat (Ø with its fit and an end inside the
span). The coupling generator already built spanned bores, so the motor-drive coupling (Ø20 / Ø14) is now built
direct and passes the gate: volume π(25² × 62 − 10² × 31 − 7² × 31) = 107,225.7 mm³, matched to 1e-6. An ICD without
spans keeps the old guard (sent to the designer with the reason).

## 4. Toasts over the gate text
`web/src/lib/toaster.ts`: bottom right, max width `min(360px, 100vw − 32px)`, at most 3 visible, close button, 6 s.
`2-gate-toast.png`: the gate card, the approve button and the problem area are clear; the toast sits in the bottom
right corner (box 356 × 128 at x 1212, y 840 of 1600 × 1000).

## 5. Estimates on the decided build path
- `estimates.py`: a ticket's estimate is a range for its path: Toolbox 1 to 6 s, built from the interfaces 3 to 9 s,
  workspace template 6 to 21 s, AI designer 0.6× to 1.5× of complexity × rate. Rates recalibrated from the reports
  (60 to 100 s per AI turn, Gage notes 11 to 19 s): machined 1.2, turned 1.1, gear 1.2, sheet 1.4, plastic 1.5 min per
  complexity unit; standard 0.05, integration 0.25, drawings / DFM 0.1. Tickets carry `estimate_lo`, `estimate_hi`,
  `estimate_path`, and `estimate_min` (midpoint); the ETA uses the low ends for its low and the high ends for its high.
- The path: at plan review, the direct builder's own decision on the drafted layout (`service.decided_paths`,
  cached per plan), else a prediction from the part; at ICD approval `service.reestimate` sets the real one
  (direct, template, AI designer, Toolbox).
- UI: per-part range and path word in plan review ("3 to 9 s, from the interfaces"), total effort and ETA as ranges,
  the ticket drawer shows the range and the path; `fmtEta` reads "20 to 46 min" (no en dash).
- Plate and cover: before "Total effort 29 min"-style numbers, now "34 s to 2 min", ETA "18 s to 2 min"
  (`1-plan-review-estimates.png`); it finished in 14 s.

## 6. Workspace templates in the Studio Toolbox
`GET /api/part-templates` (this organisation's templates, with parameters, labels and limits from `PARAM_META`) and
`POST /api/projects/{id}/part-template` (`templates.studio_source`: only the template's own parameters, finite and
inside its limits; built strict like a Toolbox part, revision kept, use counted, audited). The Toolbox dialog has a
**Templates** section first. Walk: Roller tube, OD 50 → 60 → 60 × 60 × 200 mm, 502,654.8 mm³ (= π(30² − 10²) × 200),
Verified (`7-studio-part-from-template.png`); an out-of-range value is refused in plain words (`6b-after-create-click.png`).

## 7. Run while the placeholder assembly builds
`orchestrator` keeps a per-server count of program assembly builds in flight (`mark_assembly_build`, set the moment
the build is spawned). An integration of a program with an ICD is not claimable while its build runs (gate or
revision); it is woken when the build ends. `PlatformEnv._assembly_ready` replaces the 120 s poll: it waits for a
build in flight, and when none is running (a restart, a failed build) it builds the assembly once itself, then blocks
with the reason instead of taking the bench path ("a row"). Tests that never build are unaffected (nothing is marked).
Walk: Run pressed in the same second as ICD approval; all three levels integrated on the program assembly, 4 fastener
stacks, complete 14 s later.

## Tests
- New `tests/test_office_polish2.py` (12): brief fastener rules, planner + ICD M6, cap screws keep their size, looks
  superseded (layout by revision, level by relation and by re-run, revised look current), one-part level relation,
  revised message, path prediction and ranges, plan estimate in seconds, re-estimate at ICD approval (golden c),
  claimable queueing with counted builds, `_assembly_ready` waits then builds, Studio templates through the API with
  tenant isolation.
- Changed: `test_generators.py` (stepped coupling built and gated, volume by hand), `test_office.py` and
  `test_office_phase5.py` (new rates; calibration hand calcs redone), `model.test.ts`; new `toaster.test.ts`,
  `studio/Toolbox.test.ts`.
- Runs (1 or 2 files each, workers reaped): office + generators 20 / 11, icd + program_revision 33, orchestrator +
  polish 33, direct + phase5 19, supervisor + archie_chat 34, connection_layout + design_graph 54, assembly_visual +
  office_small 37, phase6 layout + review 10, shaft_line + gearbox_caps 21, library + layout_envelopes 15,
  polish2 + library 23. ruff clean, tsc clean, vitest 163 + 1, vite build ok.
- `aicad golden --simulated --env FW_DESIGN_GRAPH=1`: **10 of 10 pass**.

## Browser (port 8814, screenshots read, 0 console or page errors)
`docs/reports/office-polish2/`: 1 plan review estimates, 2 gate with the toast, 4 looks superseded right after REV-1,
5 looks after the re-run ("Layout (REV-1)", Final "Looks assembled"), 6 Studio Toolbox Templates, 6b a refused value,
7 the part built from the template. Fixed from the shots: parameter labels ("Od" → "OD"), markdown asterisks in the
Studio chat note after a Toolbox or template insert.

## Files
- Backend: `office/{icd,planner,estimates,service,interfaces,orchestrator,platform_env,revision,visual_office,
  conformance,templates}.py`, `graph/layout.py`, `assembly/visual.py`, `platform/routers/{office,library}.py`.
- Web: `main.tsx`, `lib/toaster.ts`, `office/{model,types,PlanReview,SpeedPanel,TicketDrawer,AssemblyView}`,
  `studio/Toolbox.tsx` (a Studio file, as the brief asked).

## Known limits
- In the Studio the bottom-right toast can sit over the chat composer for its 6 s (closable). No per-page position.
- A superseded level look still shows its old picture under the note (history), not a placeholder.
- The plan-review path for parts added by hand in an edited plan is "AI designer" until the plan is saved (the
  server decides paths on the saved plan).
- The in-flight build count is per server process (as the assembly lock, PD-53).

## Parked decisions (default used)
- **PD-190 Estimate model.** Path ranges (Toolbox 1 to 6 s, direct 3 to 9 s, template 6 to 21 s, AI designer 0.6× to
  1.5× of complexity × rate) and the recalibrated default rates above. Alternative: keep the old per-family minutes and
  only zero the direct parts.
- **PD-191 Brief fastener size.** One explicit size in the brief wins over the plan's bolt text and the span rule;
  several sizes leave it per joint; bearing-cap screws keep their own; ICD edits and accepted CRs still win.
  Alternative: ask the engineer when the plan and the brief disagree.
- **PD-192 Superseded looks.** A stale look is labelled, not deleted; a revision triggers a new layout look (metered
  as at the gate); undo takes only the free checks. Alternative: no new look until the engineer asks.
- **PD-193 Toast placement.** Bottom right, 360 px, 3 visible, 6 s, closable, everywhere.
- **PD-194 Studio templates.** Any member can start a part from a template (viewers are refused by the install path);
  only the template's own parameters may change, within its `PARAM_META` limits.
- **PD-195 Assembly build wait.** Integrations queue behind a build in flight with no time cap but a 30 min safety
  net; with none running they build it once, then block with the reason (no bench fallback for ICD programs).
