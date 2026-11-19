# Office polish: the truth at the ICD gate and in Archie's words (branch `wip/office-polish`)

Source: the live Design Office run of the founder's 1:3 spur gear pair, 2026-11-19
(`docs/reports/assembly-fix/live-gear-run.md`). The founder's rule is that agents see and speak: a gate never passes
silently, and a message is never wrong or reassuring without grounds. Every item below was a defect seen in that run.
No live LLM runs were made. All checks used tests and simulated agents.

## 1. ICD gate `no_interface`: "Keep as separate parts" (PD-85 stays blocking by default)
**Before.** A designed part with no interface always blocked the ICD gate. A kit, or two shafts made on their own,
could never be approved. `test_gage_sends_back_then_approves_and_caps_retries` (two independent shafts) failed with
409, as it already did on main.

**After.** The engineer can record a decision at the gate.
- `interfaces.keep_separate(root, doc, items | None, keep, actor)` works per part or for every flagged part
  (`items=None`). `keep=False` undoes the decision. The decision lives in `icd.overrides.separate`
  (`{item: {by, at}}`), so it survives every rebuild, edit, autofix and the approval freeze. `icd.build` copies it to
  `skeleton.separate`.
- `icd.issues`: a kept part becomes `no_interface` with `severity: "warning"` and `acknowledged: true`, and this
  text: "Input shaft: kept as a separate part (your decision at the interfaces gate). No interface connects it, so
  Fitz places it beside the assembly." It shows under Layout warnings, and approval is not blocked. Kept parts are
  also exempt from `row_layout` (when only one other part remains) and from `shaft_support`. Every other problem
  still blocks.
- An ICD history entry (`kind: "separate"` / `"connect"`, by, at, items) plus an `icd.separate` / `icd.connect`
  activity event and an audit row. Only a part that is actually flagged can be kept separate. A connected part gets
  a 409.
- API: `POST /api/office/programs/{pid}/icd/separate {items?, keep?}`. When the decision clears the gate, Archie
  looks at the layout once more and says so.
- Archie stops raising these parts:
  - `visual.merge_issues` skips acknowledged issues.
  - `visual.quick_skeleton` leaves kept parts out of the touch groups.
  - `visual.relations_from_skeleton` leaves them out of the relations.
  - `visual_office.known_loose` drops a row or floating finding made up only of kept parts (plus at most one other).
  - For an all-separate kit, `layout_message` says: "...kept separate as you decided, so there is nothing to
    assemble and no interface to check."
- Archie offers the decision himself. `layout_message` adds a `keep_separate` action, which is a new Archie action
  type with normalise, describe and apply support. A model reply can propose it with
  `{"type": "keep_separate", "parts": [...]}`.
- UI (Interfaces tab): each no-interface problem gets a "Keep as a separate part" link, and the problems card gets a
  "Keep all N as separate parts" button. Kept parts are listed under Layout warnings ("Recorded by Founder, just
  now") with a "Connect it instead" link. "Fix with Archie" is hidden when only unconnected parts remain, because it
  can't fix those. The program page hint and Archie's "Needs you" line both mention the option.
- **The Gage test passes through this path.** The only change to it is one line:
  `_program(c, "gage@x.com", plan, separate=True)`. `_program` posts `/icd/separate` before approving. The gate is
  not weakened.

## 2. Archie and office message honesty
**(a) The heading follows the verdict.** Before: "It doesn't look right:" was used for every non-clean layout look,
including an *unsure* verdict where every relation was ok. After (`visual_office.layout_message`), the heading
depends on what was found:
- "It doesn't look right:" only when there are ICD problems, a blocking measured finding, or a `looks_wrong` verdict.
- "I can't tell from the picture whether it is assembled as intended:" when the verdict is unsure. The closing
  sentence then says "Nothing measured is wrong, so this is your call".
- "It looks assembled, with notes:" when there are only notes.

**(b) Human names.** Two leaks were found and fixed:
1. Sentences were built from `display_names` (SOLIDWORKS `Gear shaft<1>`). These now use the new
   `assembly.service.human_names`: the part name, with `Name #2` only when two instances share a name. It is used in
   `visual.relations_from_doc`, `visual.quick_doc` (finding texts) and `visual.targeted` (the clash names in a stop
   reason). Assembly Studio's tree keeps `<n>`.
2. The vision model's own words ("Item 3", "Key (3)"). `visual.named()` maps picture tags to part names inside
   `parse_verdict` (problems, reasons, summary). An unknown number is left untouched.

There is also a safety net: `service.plain_names` (`<1>` becomes nothing, `<k>` becomes ` #k`). It is applied to
every agent-authored event and comment, every Archie message, and the card's `run.line` / `run.blocked`. The
engineer's own words are never rewritten.

**(c) One clash count.** Before: integration always set `clashes = []` (PD-71: it measures no clashes) yet said "0
clashes". The summary carried that "0" while the advisory whole-program check later found 2, and the Assembly card
showed "0 clashes" beside a red "2 clashes" chip.

After:
- `program_assembly.clash_status(state)` is the only source, built from `state.clashes` and `state.check`. It returns
  `count = None` while the check is running or failed, and records the scope it covers: placeholders, swapped parts
  or the whole program.
- `summarize()` no longer states a count. Integration says "Fitz's whole-program clash check runs now (advisory)".
- The root integration no longer wipes `state.clashes`.
- The assembly endpoint returns `clash` and appends its text to the summary. The UI chip, badge and clash list all
  use it. The badge reads "Checking clashes…" or "Clashes not checked" while the count is `None`.
- The swap-in line says "0 clashes" only when the swapped parts' check actually ran (`last.checked`).

**(d) "Retry the 0 blocked parts".**
- On Apply, the number retried is stored on the action. The label becomes "Retried N blocked parts…".
- `archie_chat.with_labels` marks a proposed action `stale` when `normalise` says it no longer applies. The chat then
  shows "No longer needed" instead of Apply.
- A proposed retry with nothing blocked reads "Retry the blocked parts (none is blocked now: nothing to retry)".

**(e) Parts the layout never seats.**
- `level_look` excludes parts-bin instances (`office.bin`) from the targeted measurement and lists them
  (`unplaced_names`: "Pinion key", "2 × Circlip").
- `level_message` says plainly: "Pinion key and 2 × Circlip are not placed: the interfaces have no seat for them, so
  Fitz left them in the parts bin beside the assembly, not fitted. Fit them by hand in Assembly Studio, or change the
  plan or the interfaces…"
- "I measured the parts in question and found nothing to confirm it" is gone. When placed parts were measured, the
  message says: "A clash check can't show a part that is loose or in the wrong place, so this is not a confirmation
  either way."
- A level that has unplaced parts always posts to the chat.
- The stop advice now follows what confirmed the stop. A placement measurement gives "comes from the layout or the
  plan". A measured clash gives the reopen or change-request advice, so "comes from the layout" is no longer given
  wrongly.

## 3. Budget sanity
**Default budget.**
- `ProgramIn.budget_tokens` defaults to `None`. That means `service.default_budget(wallet)`: min(3,000, org balance
  minus reservations), or 3,000 when God mode bypasses tokens.
- The New program form shows the same default. Its hint reads "Defaults to your remaining wallet, 1,000 tokens (less
  than the usual 3,000)…", and a warning appears when the typed budget is above the wallet.
- On 8799 a trial workspace got `budget 1000`.

**Stopped by budget, yet approved: why.** The run record
(`fw-e2e-8797/.../runs/32e27f63…/run.json`) shows the following:
- outcome `stopped_budget`, `budget_stopped: true`
- the cost readings disagreed: the live meter said $1.73 and the agent's own report said $0.189. The meter crossed
  the $1.38 (138-token) run budget, so the session interrupted the turn, and 19 tokens were charged from the agent's
  report.
- `checks.ok: true`: the build made before the cut passed.

The office's `after()` looked only at the build state, so the part went to Gage and was approved. The master reports
that main (wip/agent-cost) has since fixed the meter: it now agrees with the agent's report within 0.2 %.

**Fix (whatever the meter does).**
- `PlatformEnv.design` records `budget_stopped` (and the run budget) from the result event.
- The orchestrator never sends a budget-stopped turn to review. The ticket is blocked with: "Chuck stopped at its
  run budget (N tokens) before finishing Spacer: the last build passes its checks but the design isn't finished, so
  it is not sent for review. Retry to let it carry on…". `next: design, resume: true` is set, so Retry continues the
  same session.
- Archie's failure note has budget-specific advice.
- The new per-turn cap from main (`FW_AGENT_TURN_CAP_USD`) sets the same flag, so it is covered too.

## 4. Scheduling: Hex takes no agent slot
- `orchestrator.FREE_STAGES = {"hex", "fit"}`. Hex lookups are claimed at once under the program lock, in queue
  (critical-path) order, without using `free` and without per-agent thread caps.
- On a miss, Hex now ends its free task with `status: queued, next: design` ("Waiting for Chuck: Hex found no stock
  part"). The design turn then claims a slot like any other, so a lookup can never smuggle a design turn past the
  cap.
- `Runner.slots_used()` counts only slot-taking work. `max_seen` now measures the slot cap.

## Tests
- New `tests/test_office_polish.py` (12, pure): gate decision (per part, all, undo, history, view, freeze,
  rebuild), refusal for a connected part, Archie's keep-separate action and silence afterwards, `known_loose`,
  heading per verdict, human names / `named()` / `plain_names` / user words untouched / card lines, `clash_status`,
  retry label and stale proposals, unplaced parts said plainly, stop advice, `default_budget`, budget failure note.
- `tests/test_office_orchestrator.py`:
  - the Gage test passes via `separate=True`;
  - concurrency test: "searching" is outside the slots, `max_seen <= 2`;
  - new `test_hex_lookups_run_outside_the_agent_slots`: concurrency 1 with the slot held, and the bolt is approved
    by Hex meanwhile;
  - new `test_a_run_stopped_at_its_budget_is_never_approved`: the fake `meter_overshoot` makes the session stop the
    turn. The ticket is blocked and not reviewed, Archie says why, Apply retry is labelled "Retried 1…", and the part
    then finishes.
- `tests/test_assembly_visual.py`: the names `Ball bearing 6204 #4` and `Pinion meshes with Gear` are updated, the
  row-layout proposal includes `keep_separate`, and the patched name function is updated.
- Results after `git merge main` (111566f): see the final lines below. `ruff check src tests` is clean.
  `npx tsc --noEmit` is clean and `npx vite build` passes.

## Browser check (port 8799, simulated agents, no LLM)
Screenshots in `docs/reports/office-polish/` (script `fw-e2e-8799/polish.mjs`): a trial workspace and a standard-planner program "Shaft kit" (two shafts, no housing).
Screenshots were read:
- `1-gate-blocked.png`: 4 problems. Two no-interface lines each have "Keep as a separate part", the card has "Keep
  all 2 as separate parts", and Approve is disabled. The visual check says "Looks wrong", and Archie's toast
  heading "It doesn't look right" is correct here.
- `2-gate-kept-separate.png`: after one click, Approve is enabled and the problems are gone. Archie looked again
  ("Looks assembled", a new message). Layout warnings list both shafts as "kept as a separate part… Recorded by
  Founder, just now. Connect it instead". The next-step hint now says approve.
- `3-history.png`: the history entry "Founder kept Input shaft and Output shaft as separate parts…".
- `5-archie-stale-action.png`: Archie's first message still offers the housing / base plate re-plans. The
  keep-separate proposal shows **No longer needed**.
- API: `problems []` and two warnings; 0 console or page errors.
- Seen and fixed from the shots:
  - Archie's re-look said "the parts are placed where they connect" for a kit. It now says they are kept separate,
    with nothing to assemble.
  - The relation "each shaft runs in two bearings…" was asked of a kit. Kept parts are now left out of the
    relations.
  - The re-look route had to become async: it spawns a task.

## Files touched
- `src/aicad/office/`: `icd.py` (build/issues/warnings only, not `seated`), `interfaces.py`, `visual_office.py`,
  `archie_chat.py`, `service.py`, `orchestrator.py` (scheduler, design `after()`, fit line, `_set_run`),
  `platform_env.py` (design result, root integration clashes, build event), `program_assembly.py` (summaries,
  `clash_status`), `fake_agents.py` (`meter_overshoot`).
- `src/aicad/assembly/visual.py`, `src/aicad/assembly/service.py` (`human_names`).
- `src/aicad/platform/routers/office.py` (`/icd/separate`, Archie action, budget default, assembly `clash`).
- `web/src/pages/app/office/`: `Interfaces.tsx`, `ArchieChat.tsx`, `AssemblyView.tsx`, `NewProgram.tsx`,
  `ProgramPage.tsx`, `types.ts`.
- `toolbox.py`, Hex matching and `icd.seated` were not touched (wip/toolbox-keys).

## Parked decisions (master numbers them)
- **PD-a: kept-separate parts.** The decision is per part or for all, undoable while the ICD is a draft, recorded in
  the ICD history and audit, and frozen at approval. Kept parts are exempt from `no_interface`, `row_layout` and
  `shaft_support` only. Archie looks again once, and only when the decision clears the gate (a metered look in AI
  mode). Revisit if the founder wants a reason text to be required, or kit parts laid out in a tidy row or kept out
  of the assembly.
- **PD-b: default program budget = min(3,000, remaining wallet).** God mode bypass keeps 3,000. A typed budget above
  the wallet is allowed, with a warning. With the cheaper cold turns on main (about $0.21, about 21 tokens), 3,000
  stays the ceiling. Revisit if the founder wants a smaller default (for example 1,000).
- **PD-c: a budget-stopped design turn is blocked, not reviewed.** Retry resumes the same session with a new run
  budget. The part is never sent to Gage on a cut-off turn, even when its last build passes. Revisit if the founder
  prefers "send the last passing build to Gage, labelled as unfinished".
- **PD-d: charging.** The stopped run charged 19 tokens (the agent's report) while the meter read 173. The master
  says the meter fix on main makes these agree. If they ever disagree again, the default is unchanged: charge the
  agent's report, capped by the budget.
- **PD-e: deterministic stages take no agent slot.** Hex has no cap of its own (it is cheap and synchronous).
  Revisit if Hex ever gains an LLM step.

## Not done
- Item 11's duplicated paragraph was already fixed on main. Origin-triad picture quirks, Smithy MLD-01 on turned
  shafts and the pinion Toolbox swap are out of scope.
