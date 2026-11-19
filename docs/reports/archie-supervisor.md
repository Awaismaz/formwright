# Archie supervises the running program (branch `wip/archie-supervisor`, WORKLIST 49)

Founder, 2026-11-20: *"I also need Archie to have more powers during a program is under execution. It should be able
to modify plan on the go to solve problems. It should ask from user before making a major change. It should be able to
temporarily alter rules as per a fair judgement if something is unnecessarily stuck. There should be more smart feeling
in the whole process. For that to be done, Archie must have super powers over whole Design program, just like you solve
problems from here when I tell you."*

## What was built
`src/aicad/office/supervisor.py` (new) makes Archie the program supervisor. He watches, diagnoses, acts through typed
tools, asks before major changes, can relax a rule with a recorded reason and expiry, and keeps a log with undo.

### 1. Watch (event driven, plus a heartbeat)
- The orchestrator records a trigger on the program (`supervisor.notify`) and its runner kicks a pass on the next
  tick (`supervisor.tick`). Triggers:
  - a ticket becomes blocked (`Runner._fail`), including the no-progress guard and the round caps;
  - a ticket fails the same way twice: the same block after Archie acted becomes a `repeat`, and he escalates instead
    of retrying again;
  - the budget stops the office;
  - a level's visual check says "looks wrong".
- `detect()` (deterministic, no AI) also finds:
  - blocked tickets the events missed (after a restart);
  - a working ticket with no update for 20 min;
  - the budget at 90 %;
  - the interfaces gate blocked with problems for 30 min;
  - a planned part of a kind the brief excludes.
- Heartbeat: every runner tick checks the clock (120 s). A server-level loop (`heartbeat_all`, started by the office
  router) covers programs that wait without a runner, such as one at the interfaces gate or a stopped office.
- Every situation has a signature, so it is handled once, not on every heartbeat. Passes are debounced (2 s), and an
  asyncio lock per program makes sure two passes never run at once. A trigger that arrives during a pass makes exactly
  one more pass afterwards.

### 2. Diagnose before acting
- `state_view()` gives Archie a compact, structured view of the program:
  - the program, the brief, the budget and the wallet;
  - the triggers;
  - every ticket, and for the ones in trouble: review rounds, design turns, attempts, whether the latest build passes,
    the blocked reason, Gage's latest measurable findings, their **feature keys** (`IF-01:hole 1`), advisory points,
    Gage's last three reviews, relaxed checks and the visual line;
  - ICD problems and interfaces with their changeable fields;
  - change requests, active overrides, his own earlier actions;
  - the plan while it can still change;
  - the rules he may relax, each marked "measures geometry" or "procedural".
- The call goes through the provider layer as the new role **`supervisor`** (`llm/base.py` ROLES; `routing.py`
  DEFAULT_ROUTES `supervisor: opus` after the merge with `wip/agent-latency`). The model is `claude-opus-5-5` unless
  `FW_LLM_MODELS` routes it elsewhere.
  - The call uses a standalone system prompt with no tools (`standalone_system=True`), so it carries no harness
    context. This is never free-form code.
  - He answers with a cause (part, measurement, spec, rule, plan, interfaces, budget, capacity), a diagnosis, evidence,
    what to tell the engineer, and typed actions, all in a fenced `fw-supervisor` block.
  - The reply is scrubbed (`agent.session.scrub`, `service.plain_names`). Unknown tools are dropped.
- `rule_plan()` is the rule-based reading of the known patterns. It runs when AI is unavailable, in simulated mode, or
  when the hourly cap is reached. With AI it is also given to the model as a "first reading (may be wrong)". The
  patterns:
  - the measurement loop → relax conformance for that feature (major);
  - the round cap with only advisory notes left → approve with notes (minor);
  - the round cap with a measurable failure → send back with the exact finding;
  - failed builds → retry once;
  - a clash → send back with the clash;
  - budget near its limit → raise the budget to what the wallet allows (major);
  - an excluded part → remove it (major);
  - a stale gate → keep separate.

### 3. Typed, audited tools (`check` → `classify` → `execute`)
`check()` validates each action against the program as it is now. `execute()` applies it through the office's own
functions, and each action goes into the log and the activity stream.

| Tool | Reuses | Class (PD-98) |
|---|---|---|
| retry (interrupts a hung step) | `orchestrator.control("retry")`, `orchestrator.interrupt` | minor |
| pause | `orchestrator.control("pause")` (+ interrupt) | minor |
| reassign | `service.update(specialist=)` | minor |
| send_back with an instruction | new `orchestrator.archie_instruction` (comment + feedback, or inbox for a part in work) | minor |
| approve_with_notes | new `orchestrator.approve_with_notes` (only when `_no_hard_findings`: the build passes its gating checks, no measurable finding, interfaces conform or relaxed; the per-part review gate still applies) | minor |
| relax_rule, procedural (round caps, no-progress guard, design retries) | rule override | minor |
| relax_rule, measures geometry (conformance, envelope, brief size, swap-in clash) | rule override | **major** |
| keep_separate | `interfaces.keep_separate` | minor only when the brief says the parts stand alone, else major |
| remove_part / add_part / set_qty | at plan review: the plan in review; at the interfaces gate with nothing started: `service.revise_plan` (now also `remove` and a whole `plan`) + `service.approve_plan` | **major** |
| resize_part | `interfaces.resize` (draft ICD) | major |
| edit_part | the ticket brief (+ instruction when blocked) | major |
| change_interface | draft: `interfaces.edit`; approved: `interfaces.raise_cr` + `platform_env.decide_cr` | **major** |
| budget | program budget / concurrency (never above spent + wallet) | **major** |

- **Minor** actions he applies at once. He posts one message in the program chat that says what and why, and that it
  is in the Archie log.
- **Major** actions are logged as "Waiting for you" and posted with clickable choices, "Yes, do it" / "No, leave it",
  in the style of the fw-questions MCQ (`SupervisorQuestion` in the chat and on the Archie tab). A yes re-checks the
  action against the program as it is now. If it no longer applies, the log entry reads "No longer applied".
- With the supervisor on, his diagnosis replaces the generic "retry the blocked part" failure note. Before this, two
  different proposals sat next to each other (seen in the first walkthrough).

### 4. Rule overrides, honoured by the gates (never a pass)
- An override is stored in `doc.supervisor.overrides` with these fields:
  - `{rule, scope: ticket | interface | program, feature, reason, expiry: rebuild | rounds, approved_by, uses, status}`.
- The gates honour it:
  - Gage's review: `supervisor.split` / `consume` on keyed findings (`conformance.finding_items`, a refactor of
    `findings` that adds `{rule, key}`). The gating build checks (CHK-02..09) are never relaxed.
  - The round caps: `cap_extra` for `review_rounds`, `design_attempts` and `clash_rounds`.
  - The no-progress guard: `use_rule`.
  - Fitz's swap-in clash: `relaxed_clash`.
- "Until the next rebuild" counts from the build Archie looked at, and the override expires on the first review of a
  newer build.
- A relaxed feature never reads as passed:
  - The ticket gets `relaxed: [{label, feature, text, reason}]`.
  - Gage's note starts "Approved with checks relaxed by Archie (not passed):" and says "0 of 1 interface feature
    measured on the part match ICD v1 … and the rest are relaxed, not passed". Before, it would have said "1 interface
    feature … match".
  - The card line reads "… (1 check relaxed by Archie, not passed)". The board card has a "relaxed" chip, and the
    ticket drawer has a "Checks relaxed by Archie: relaxed, not passed" panel.
  - Archie's status report, "Needs you", the program-done event, the **BOM** (row description, `relaxed` list, a
    "Relaxed check" line in the CSV) and the **release README** ("Checks relaxed by Archie (relaxed, NOT passed …)")
    all list it.

### 5. Archie log, with undo
- There is a new **Archie** tab on the program page (`web/src/pages/app/office/ArchieLog.tsx`), with the number of
  questions waiting in the tab title. It has four parts:
  - "Waiting for your decision", with Yes / No;
  - "Rules relaxed by Archie": scope, expiry, reason, uses, and Undo;
  - "Archie's log", one entry per action: when, what, why, Minor/Major and why, the mode (AI / no AI / Simulated),
    tokens, the outcome, who decided, who undid, and "Show the diagnosis and evidence" for the cause and evidence;
  - "Ask Archie to check now".
- `undo()` reverses rule overrides, plan edits not yet built, budget changes, reassignments, pauses, brief edits not yet
  worked on, keep-separate decisions and draft-interface edits. Undoing a relaxation sends the parts that used it back
  to Gage. A part that was already integrated stays listed as relaxed ("not measured again") until it is reopened
  (PD-102).
- API:
  - `GET /api/office/programs/{pid}/supervisor`
  - `POST …/supervisor/run`
  - `POST …/supervisor/actions/{aid}/decide {choice}`
  - `POST …/supervisor/actions/{aid}/undo`
  - Each is org-scoped through `_load`, needs the editor role and is audited.
- No agent internals in the UI: the view drops the raw action and undo payloads, and the reply is scrubbed.

### 6. Hard limits
- No fake pass: the gate keeps relaxed rows separate, and approve-with-notes refuses a part with a measurable failure
  (tested).
- No manufacturing claim: the instructions forbid it. Gage's note and the README keep the "relaxed, NOT passed" wording.
- The budget never goes past the wallet: `check(budget)` caps it at spent + `wallet_left` (balance minus
  reservations), and `rule_plan` proposes at most that (tested).
- No other workspace: every pass, decide and undo checks that the program's folder belongs to its organisation
  (`_same_org`). Tickets and interfaces are resolved inside the program only (tested).
- **N = 6 model calls per program per hour** (`MAX_CALLS_PER_HOUR`). Past it, the rule-based reading answers (tested).
  Each call is capped at 30 platform tokens and charged to the workspace like Archie's other calls, counted into the
  program's planning tokens.

## "Fix with Archie" at the interfaces gate (founder's follow-up)
Founder: *"Why Fix with Archie button does not resolve? If you can tell me how to fix it, why can't Archie, and why
can't it actually fix it?"*

**Cause.** The button was not Archie's AI. It called `interfaces.autofix`, a deterministic search that only tunes numbers
on existing interfaces: hole inset, fastener size, hole count, shaft Ø. These problems need a plan change, so the click
did nothing visible:
- `no_interface`;
- `shaft_support` with bearings planned;
- `row_layout` / nothing to mount on;
- `line_clash`, `journal_off_shaft`.

**Now** (`POST /programs/{pid}/icd/fix` → `supervisor.fix_gate`):
1. **Step 1, the number fix:** the same deterministic `interfaces.fix`, 0 tokens.
2. **Step 2, Archie:** if problems remain (and the supervisor is on), Archie runs a supervisor pass on the gate.
   - With AI, Opus diagnoses and acts through the typed tools. Without AI, `gate_plan()` reads the structural problems:
     - unconnected parts → keep separate, or remove the part when one part is loose;
     - `shaft_support` → **two bearings per shaft** (`set_qty`, a new plan tool) or **add a housing**, or remove the
       bearings when the brief rules a housing out;
     - nothing to mount on → a housing or a base plate.
   - Each problem says why numbers can't clear it.
   - Several ways to clear one problem are **alternatives**: one question in the chat, "Which change should I make?",
     with one chip per option plus "None of these". Choosing one declines the others.
   - Minor steps are applied; plan changes are major and asked.
   - On a yes, the plan changes and the program is laid out again (`service.revise_plan` + `approve_plan`). The ICD is
     derived again, the gate re-checks, and Archie looks at the new layout once.
3. **Step 3, the account:** the gate card shows the result inline (`fixLines`, unit-tested), with the toast. It says
   which step ran: "Fixed 3 sizes automatically", "No size change could help; Archie proposes 2 plan changes: answer in
   the chat", or "Archie made 1 fix himself". It lists each proposal, each still-open problem with its reason, and a
   button "Answer Archie in the chat".
   - With the supervisor off, the card still lists what is open and why, so a click never looks like it did nothing.
   - The button now shows for every gate problem, including parts with no interface. The help text explains both steps.

Tests (Python):
- `test_fix_with_archie_clears_shaft_support_with_a_plan_change_the_engineer_picks`: one bearing planned, no number
  change possible. Two alternatives are asked in one question. Picking "Plan 2 × Ball bearing 6204" re-lays out the
  program with 0 problems and declines the housing option. Undo brings the problem back.
- `test_fix_with_archie_on_unconnected_parts_asks_and_never_looks_idle`: a `no_interface` program. Keep-separate is
  asked (major: the brief doesn't say the parts stand alone) and clears the gate on a yes. With the supervisor off, the
  open problems are still reported.

Test (web): `model.test.ts` "fixLines".

Browser (8806, `gate-*.png`, read):
- `gate-1-before.png`: the gate blocked by `shaft_support`.
- `gate-2-fix-result.png`: "No size change could help; Archie proposes 2 plan changes: answer in the chat", the two
  proposals, "Still open: a shaft runs in fewer than two bearings and nothing else carries it; that is a part count,
  not a number on an interface".
- `gate-3-chat-choices.png`: "Which change should I make?" with the chips.
- `gate-4-chosen.png`: the bearing option chosen, the toast "Done: Archie applied it", 2 bearing journals on the
  Interfaces tab.
- `gate-5-gate-cleared.png`: no problem left, Approve ICD v1 enabled, Archie's new look.
- 0 console errors.

Fixed from the shots: the wording for a set of alternatives ("pick one in the question below") and a doubled full stop.

Left as it was: the earlier layout-look message keeps its own "send the plan back with a housing / base plate" Apply
offers (an existing behaviour) until Archie's next look.

## Files
- New:
  - `src/aicad/office/supervisor.py`
  - `tests/test_office_supervisor.py`
  - `web/src/pages/app/office/ArchieLog.tsx`
  - this report and `docs/reports/archie-supervisor/`
- Office:
  - `orchestrator.py`: notify/tick hooks; overrides honoured in `_review`, `_design`, `_fit`; `approve_with_notes`;
    `archie_instruction`; the approval note never counts a relaxed feature as matching.
  - `conformance.py`: `finding_items`.
  - `gage.py`: `GATING_PREFIXES`.
  - `service.py`: `revise_plan` remove/plan; `view` carries `supervisor`.
  - `archie_chat.py`: status and needs-you.
  - `deliverables.py`: BOM and README.
  - `fake_agents.py`: `FW_OFFICE_FAKE_SCRIPT`, a dev-only scripted stuck part.
- `llm/base.py`: role `supervisor`. `llm/routing.py`: one route line, after the merge.
- `platform/routers/office.py`: 4 endpoints and the heartbeat start/stop.
- `tests/conftest.py`: an autouse `FW_OFFICE_SUPERVISOR=0`. Existing tests assert the office's own behaviour, and the
  supervisor test file turns it on.
- Web:
  - `ArchieChat.tsx`: question chips and footer label.
  - `Interfaces.tsx`: Fix with Archie result card; `model.ts` `fixLines` (+ `model.test.ts`).
  - `ProgramPage.tsx`: Archie tab.
  - `Board.tsx`: relaxed chip.
  - `TicketDrawer.tsx`: relaxed panel.
  - `types.ts`.
- Not touched: `agent/session.py`, `llm/claude_sdk.py`.

## Tests (`tests/test_office_supervisor.py`, 21, stub provider with recorded replies, no CAD)
- **(a) Measurement loop.** This is the founder's Gear Reducer pattern: a tapped hole measured "through" while the ICD
  says blind.
  - Gage's real `_review` runs twice on a fake platform boundary, and the no-progress guard blocks the part.
  - Archie (recorded reply) diagnoses "measurement" and proposes relaxing conformance for `IF-1:tapped hole 1`. It is
    major, so he asks: one chat message, the MCQ, no override yet.
  - On yes, the override is active, with builds 4 recorded, and the ticket goes back to Gage.
  - Gage approves it **as relaxed**, and the relaxation shows in the summary, the BOM, the CSV and the README.
  - A rebuild ends the relaxation.
  - The prompt carries the trigger, the feature key, the build facts and the rule classes.
  - The same case runs through the rule-based reading without AI, and a second pass with nothing new makes no call.
- **(b) A part the brief excluded.** This is Test 5's "Shaft support housing" in the engineer's plan.
  - `detect` finds it, Archie proposes removing it (major, so he asks), the yes removes it, and the undo brings it back.
  - A decline changes nothing, and a second answer is refused.
- **(c) Round cap with only advisory notes.** Archie approves with notes himself (minor, logged, "Done: Approve…"). The
  entry is not undoable, and the view hides the action and undo payloads. He refuses a part with a measurable failure,
  or whose latest build fails.
- **(d) Undo of a rule override.** The override is undone and the part goes back to Gage. Gage measures the hole again
  and **sends it back** (the gate blocks it again). The relaxed summary is empty, and a second undo is refused.
- Also covered:
  - the minor/major table;
  - CHK never relaxed;
  - a measured check never program-wide;
  - a relaxation needs a reason;
  - the budget past the wallet is refused;
  - the hourly cap;
  - another workspace;
  - a repeat escalates (retry once, then "failed the same way again after I acted", then quiet);
  - debounce, one pass at a time and one more pass for a trigger during a pass;
  - the runner's notify and heartbeat;
  - reply parsing (an unknown tool is dropped, internals scrubbed);
  - two cases recorded from the live run: procedural relaxations plus a precise instruction are all minor and nothing
    measured is relaxed; an interface change on an approved ICD is major.
- Neighbours, one or two files per run, workers reaped: `test_office_orchestrator` + `test_office_polish` 33,
  `test_office_phase5` + `test_llm_providers` 44, `test_office` + `test_office_archie_chat` 33, after `git merge main`:
  `test_office_supervisor` + `test_agent_latency` 27, `test_llm_providers` + `test_office_polish` 47,
  `test_office_orchestrator` + `test_office_phase6_review_ecn` 26, `test_office_icd` + `test_office_small` 29,
  `test_office` + `test_office_archie_chat` 33, `test_office_phase5` + `test_assembly_visual` 35, `test_office_direct` +
  `test_office_shaft_line` 15, `test_office_orchestrator` + `test_office_polish` 33, `test_office_phase6_layout` +
  `test_office_gearbox_caps` 21; web office vitest 29. `ruff check src tests` is clean, `tsc --noEmit` is clean and `vite build` is ok.

## Browser walkthrough (port 8806, simulated agents, screenshots read)
Setup:
- Program "Plate and cover" (standard planner): Base plate, Frame bolt ×8, Cover, interface IF-01 (bolted joint).
- The fake Benny builds the Cover's first hole 3 mm off on every turn (`FW_OFFICE_FAKE_SCRIPT`, `FW_OFFICE_DIRECT=0`).
- Script `fw-e2e-8806/walk.mjs`.

What happened:
- About 10 s after Run, the no-progress guard blocked the Cover and Archie had asked.
- `sim-1-archie-log-asking.png`: Archie tab, "Waiting for your decision": "Relax the ICD conformance check for hole 1 of
  IF-01 on PAC-4 Cover, until the part's next rebuild", Major, Simulated, Why, Yes / No.
- `sim-2-chat-mcq.png`: in the chat, one diagnosis message ("the designer rebuilt it and the measurement didn't move …
  That points at the measurement or the interface spec, not the part. This needs your decision first …") and the
  question with the chips.
- `sim-3-chat-approved.png`: after the click on **Yes, do it**, the toast "Done: Archie applied it", the chip is filled
  ("Approved by Founder"), the override card reads "Relaxed, not passed · measures geometry", and the log entry reads
  "Done … Outcome: Relaxed (not passed) until the part's next rebuild. PAC-4 went back to work."
- `sim-4-board-relaxed.png`: the Cover card has the **relaxed** and fitted chips. Its line: "Fitz swapped Cover in: …
  0 clashes (1 check relaxed by Archie, not passed)".
- `sim-5-drawer-relaxed.png`: the ticket drawer has the relaxed panel above the red "Interfaces off ICD v1" measurement.
  The failing row stays visible.
- `sim-6-archie-log-applied.png` and `sim-7-after-undo.png`: **Undo** gives the toast "Undone: the rule applies again".
  The override reads "Undone … undone by Founder". The log reads "PAC-4 is already integrated: reopen it so Gage
  measures again; until then the check stays listed as relaxed, not passed."
- `sim-8-archie-log-blocked-again.png`: the Cover was reopened and Run pressed. Gage measured again and the gate
  **blocked it again** within 6 s, and Archie asked again.
- Errors: 0 page errors. 1 console 404 from the ticket drawer's part preview of a fake part ("No preview for this build
  yet"), which is not from this branch.

Fixed from the shots:
- A 500 on decide and undo: the `audit()` keyword clashed with its `action` parameter.
- The duplicate generic retry offer next to Archie's diagnosis.
- Feature keys shown raw (`IF-01:hole 1`); they now read "hole 1 of IF-01".
- Labels too long.
- The Fitz swap line dropped the relaxed note.
- The relaxed chip was off-screen.

## ONE live run (Archie live on Opus, designers simulated)
**Setup.**
- `FW_OFFICE_SUPERVISOR_LIVE=1`, same program and stuck Cover ("Plate and cover live").
- The designers stayed simulated so that the 80-token budget went to Archie. One real design turn costs 25 to 300
  tokens.
- I stopped the server after Archie's third pass to cap the spend.

**Cost.** 3 supervisor calls, **18 platform tokens** (7 + 6 + 5; $0.065, $0.056, $0.048), charged to the workspace and
the program. Archie spoke about 40 s after Run.

**Archie was smarter than the rules.** The rule-based reading would have proposed relaxing the hole check. Archie,
live, refused:
> "Only hole 1 on the Cover is flagged: Ø5.500 is in tolerance but it sits at x -36.00 instead of -39.00, while y
> matches. A single hole off by a clean 3 mm, with the other holes passing, points to a misplaced feature that the
> rebuild did not move, not a misread datum. The Base plate already passed against the same interface, so waiving this
> would put a Cover in assembly whose hole is 3 mm from its mating hole, and the bolt would not go through. … I'm not
> relaxing the hole check on the Cover."

**What he did.**
1. Pass 1, all minor, done himself:
   - relaxed the review-round cap and the no-progress guard for 1 round each (procedural);
   - sent the Cover back with "Move hole 1 (IF-01) so its centre is exactly at x = -39.00, y = -24.00 … Change no other
     features."
2. Pass 2, after the same failure: reassigned the Cover to Molly and gave an even more explicit instruction.
3. Pass 3: paused the Cover and escalated:
   > "IF-01 does not match the brief: the brief calls for M6 bolts, but IF-01 specifies M5 with Ø5.5 holes … My
   > proposal: correct IF-01 to M6 with Ø6.6 clearance holes … Since the Base plate is already done, this means reopening
   > it, so I need your approval before changing the interface."

**A real defect, not one I planted.** The standard planner's ICD says M5 while the brief says M6. Archie caught it from
the evidence. It is recorded in `live-archie-messages.json`. I did not fix it here: it is planner/ICD scope, and the
master should look at it.

**What the live run taught (fixed after it):**
- In pass 3 Archie described the interface change in words but did not put it in his actions, so there was no
  one-click approval. The instructions now say: "Put every change you recommend in actions, major ones too … A change
  you only describe in words can't be approved with one click."
- He reassigned a sheet-metal part to Molly, the plastics designer. The tool list now names each designer's family:
  "reassign only to the designer whose family fits the part".
- A procedural relaxation read "Relaxed (not passed)". It now reads "The review-round cap is relaxed for 1 more round",
  and its badge reads "Relaxed".

Screenshots:
- `live-1-archie-log.png` and `live-3-archie-log-after.png`: the procedural overrides, one of them Expired once used,
  each with Undo.
- `live-2-chat.png`: the full message.

Activity log: `live-activity.txt`.

## Known limits / not done
- Adding or removing parts after part work has started is refused with a reason (PD-100); after release that is an ECN.
- `change_interface` on an approved ICD raises a change request that Archie's existing rule decides
  (`platform_env.decide_cr`). It is tested for classification and validation only; the CR path itself was not run in a
  test or the browser.
- A visual "looks wrong" is noted to the supervisor. In the rule-based reading he only explains it, because measurements
  decide (PD-73). With AI he may propose actions.
- The heartbeat loop for runner-less programs starts with the app. It was exercised in tests through `tick`, not over
  hours on a real server.
- There are no FastAPI endpoint tests. The 4 endpoints were exercised by the browser walkthrough (decide, undo) and
  the live run (decide). A tenant check is in the service layer and in `_load`.
- Master: there is a new program tab ("Archie"), so no Studio entry point is needed. The planner's M5 vs M6 ICD
  mismatch (live run) deserves a ticket.

## Parked decisions (default used)
- **PD-98 Minor vs major (deterministic, `supervisor.classify`).**
  - Minor: retry (including restarting a hung step), pause, reassign, send back with an instruction, approve with notes
    when only advisory notes remain, relax a procedural rule (round caps, the no-progress guard, design retries), and
    keep-separate when the brief says the parts stand alone.
  - Everything else is major: parts added or removed, interface changes (draft or approved), budget or concurrency
    changes, resize, brief edits, relaxing any check that measures geometry (conformance, envelope, brief size, swap-in
    clash).
  - Pause counts as minor because Resume undoes it.
  - Alternative: lowering the budget or concurrency as minor.
- **PD-99 Supervisor limits.**
  - At most 6 model calls per program per hour, and at most 30 platform tokens per call (live calls cost 5 to 7).
  - The heartbeat runs every 120 s.
  - Triggers: "stuck" after 20 min with no update, "gate stale" after 30 min, "budget near" at 90 %.
  - The debounce is 2 s, and a pass takes at most 3 actions.
  - In development with simulated agents he uses the rule-based reading unless `FW_OFFICE_SUPERVISOR_LIVE=1`.
    `FW_OFFICE_SUPERVISOR=0` turns him off and `FW_OFFICE_SUPERVISOR_AI=0` keeps him rule-based.
- **PD-100 Plan edits on the go.** Archie adds or removes parts only while the plan is in review, or at the interfaces
  gate before any part work. The program is then laid out again with the engineer's yes. After that it is an ECN or a
  new program. Alternative: removing an unstarted part from an approved ICD, which needs ICD and placeholder surgery.
- **PD-101 Relaxation scope and expiry.**
  - A measured check is relaxed for one part (optionally one feature) or one interface, until the part's next rebuild,
    never program-wide.
  - A procedural rule is relaxed per part or program-wide, for N extra rounds (defaults: review 2, no-progress 1, design
    2, clash 2).
  - The gating build checks are never relaxed.
- **PD-102 Undoing a relaxation used by an integrated part** does not reopen the part on its own. The check stays listed
  as relaxed and "not measured again" in the summary, BOM and README until someone reopens the part.
- **PD-103 One automatic retry per block.** The same block after Archie acted is a repeat: he escalates to the engineer
  (or proposes a different fix) and never retries the same thing twice.
- **PD-104 One voice on a block.** With the supervisor on, his diagnosis replaces the generic failure note and its retry
  offer. The note still appears when the supervisor is off.
- **PD-105 Metering.** Supervisor calls are charged to the workspace (God-mode token bypass respected) and counted into
  the program's planning tokens, like Archie's planning and chat.
- **PD-106 Fix with Archie.** The number fix runs first (free). Archie handles only what remains, and only when the supervisor is on. Plan changes at the gate are major and are offered as alternatives in one question; the program is laid out again on a yes. Alternative: apply the single obvious fix without asking.
