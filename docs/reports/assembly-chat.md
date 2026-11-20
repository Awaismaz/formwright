# Assembly Studio chat: the assembly agent (WORKLIST 51, branch `wip/assembly-chat`)

Founder, 2026-11-20: *"In assembly, I want the Chat to flow, instead of new prompt everytime. The chat maintains the
context. The Agent intelligently decides based on history and understanding of project what is needed. When I ask it
to make a part, it makes part and bring in assembly. If I ask it to bring a part, it brings from existing parts or
toolbox. When I ask it to assemble, it should. Even if I ask at once to assembly all intelligently, it should
understand what to assembly where."*

## What was built

### 1. One persistent conversation per assembly
- Stored server side next to the assembly: `<assembly>/chat/chat.json` (messages, the steps each reply ran with their
  results, the running turn, design jobs). It survives reloads and server restarts (a turn cut by a restart says so
  and asks to be repeated). "New conversation" archives it (`chat.<n>.json`), never deletes it.
- Every turn the model reads the whole recent conversation (14 messages, older ones counted) plus a compact live
  summary written by code (`chat.summary`): each instance with its id, role, where it is, what it is mated to and
  whether the solver satisfies those mates; shaft seats, keyseats and circlip grooves; loose parts; the last clash and
  motion checks (only when current); parts being designed; the workspace's verified parts it can bring; and the
  project context and design memory (DS-040, `memory.context.turn_context`, the same function the Studio uses).
- UI: a **Chat** tab, first and default in the Assembly Studio (editors). The Studio chat's look: user bubbles,
  agent replies in Markdown, one line per step with its result (collapsible), clickable part chips that select the
  part in the view, clickable question chips, a status chip from the solver ("all mates satisfied", "2 unplaced"),
  time and tokens per reply, the shop-floor status line while it works (polled every 1.2 s with the step being run),
  and a card per running design job with a link to the part. The one-shot panel stays as **Quick add** (was
  "Describe").

### 2. The agent decides; typed tools act (`src/aicad/assembly/agent.py`)
One model call per turn returns `{"say", "actions", "questions"}` (`chat.REPLY_SCHEMA`, validated; an unknown action
is dropped; at most 2 questions). The model never writes code. Actions run in order, each deterministic:

| action | what it does |
|---|---|
| find | assembly instances, workspace parts (Hex `find_parts`) and the Toolbox (Hex `read_toolbox` / `toolbox.match`) |
| bring | a Toolbox component (only the stated parameters; the rest sized from the part it is "for": `makers.size_for_host`) or a workspace part; comes in unplaced |
| make | **direct** (no AI geometry): a stepped shaft (journals, hub seat against a collar, DIN 6885 keyseat, DIN 471 groove), a spur gear (bore, keyway, face width from the shaft), a spacer sized from the gap between two parts and put in it; built as a new workspace part through the normal check gate (`library.install_model`, strict). **Otherwise** a Design Studio design-agent turn on a new part (`projects.agent_chat`, metered by the Studio), followed in the chat as a job and inserted only when `runner.is_verified` |
| mate | keyed_hub / hub_fit / shoulder_stop / bearing_journal / ring_retained / key_in_seat: the shaft line is placed again by construction (`trains` + new `fixings`); gear_mesh: both lines; bolted_joint / mounted_on: `fitz.mount` (+ bolts); else coaxial on the main round faces |
| assemble | the same over named parts or everything; plates mount on the base by hole pattern; asks instead of guessing when a gear/hub could go on several shafts |
| check | exact interference + clearance (`service.analyse`), motion range (`service.motion_check`), visual check (advisory, PD-73) |
| move / remove / replace / resize | a resize changes the part's own parameters (Toolbox parameters, or the design's PARAMS through `set_params`) and keeps its mates (`remap_refs`) |
| explain | the state in plain words, written by code |

References resolve from history and state: ids from the summary, `$labels` of the same turn, or names ("the gear",
"the first bearing", "the left one", "the gear I just made"); several equally good matches become a question.
Placing a line again keeps the instance ids, names and tree order (`_rekey`), so later references hold; mates to
parts outside the line (a spacer) are put back when the part returns unchanged.

**Keys and circlips by construction (`assembly/fixings.py`, new):** keyseats (floor, side walls, round ends) and hub
keyways are recognised from the exact references; grooves are short seats closed by two shoulders whose Ø is the
DIN 471 d2. A key lies on the floor, centred, length along the axis (coincident floor, coincident wall, concentric
end); a keyed hub is turned so its keyway faces the keyseat (and the gear's tooth phase for the mesh follows that
turn); a ring sits in its groove against the wall away from the part it holds. **Trains changes:** a hub on a seat
closed by a shoulder sits against the shoulder (design graph `shoulder_stop`, coincident mate), else on the keyway,
else centred (as before); keys and rings join shaft lines and turn with the shaft in the motion joint.

### 3. Model routing and metering
- New role `assembly_agent` (`llm/base.ROLES`); routes `assembly_agent.simple` = Sonnet, `.complex` = Opus
  (`llm/routing.py`). `chat.job_of`: "assemble everything", three kinds of work in one message, or "make" with no
  number is complex; bring, mate, check, a sized part and edits are simple.
- One single call, `standalone_system=True` (no harness context), the JSON contract appended, hard cap
  `chat.TURN_MAX_TOKENS` = 40 platform tokens per turn (also in God mode), never more than the unreserved balance;
  debited like every other AI step ("Assembly Studio · assembly agent"); tracked. A design-agent part is the Studio's
  own metered run.
- No AI (AI off, too few tokens, simulated agents, a provider error or an unreadable answer): the offline reader
  answers the common requests at no cost (assemble everything, check, explain, bring by description, remove, and a
  clicked "which shaft" chip).

### 4. Honest and safe
- What the engineer reads after a turn is code: step lines from what happened, the solver's mate status, unplaced
  parts by name, the clash count only when the check is current. The model's "say" is written before anything runs
  and is told never to claim a result.
- Scrubbed (`chat.scrub` on every line): file names, action names, `$labels`, instance ids, part keys, model names,
  "validated / certified / ready for manufacture"; long dashes removed. The Assembly Studio folder is now inside the
  `noLongDashes` guard (seven placeholders and a comment fixed).
- Unplaced parts are said to be unplaced; a shaft nothing goes on stays where it is and is named; an unplaced part
  left inside the assembled parts is moved aside (it would read as a clash) and that is said.

## Evidence

### Tests: `tests/test_assembly_agent.py` (10 passed, 64 s; stub provider, recorded replies `tests/golden/assembly_agent/replies.json`)
Hand values are in the file's docstring (journal 0..16, seat 16..46, collar 46..54, journal 54..70; keyseat 8 x 4 x 16
centred at z 36, floor 8.5 from the axis; gear 26..46 against the collar; bearings 2..16 and 54..68; groove
24.7..26, ring 24.7..25.9).
1. *"make a stepped shaft Ø20 with a keyseat, then bring a spur gear m2 z40 and a key, then assemble them"*: shaft
   built and verified (volume = hand formula incl. the keyseat integral, rel 1e-4), gear sized bore 25 / keyway 8 x 3.3
   / face 20, gear at z 26..46, key origin (0, 8.5, 36) along Z, every mate satisfied, nothing unplaced.
2. *"bring two 6204 bearings for that shaft and put them on"*: bearings at z 2..16 and 54..68 against the shoulders,
   gear and key unchanged.
3. *"assemble everything"* on 6 loose parts (shaft with keyseat and groove, gear, key, 2 bearings, circlip): every
   placement by the hand numbers above, ring at 24.7..25.9, all mates satisfied, **0 clashes** (exact check), key and
   ring turn with the shaft, bearings don't.
4. *"make the gear 2 mm wider"* ("the gear" from the conversation): face width 20 → 22 through its own parameter,
   still against the collar (24..46), mates kept, then 0 clashes. Plus *"make a spacer between the first bearing and
   the gear"*: Ø25 x 8 spacer at 16..24, mated, 0 clashes.
5. Ambiguity: "assemble everything" with two shafts and one gear asks "Which shaft does Spur gear m2 z30 go on?"
   (code, nothing changed); the chip answer puts it on shaft 1 and moves the idle shaft 2 out of the gear's way;
   then the model asks too ("put the gear on a shaft"), the chip answer moves the gear onto shaft 2 at its keyway.
6. Pure: routing and job size, the reply contract (unknown actions dropped, internals and claims scrubbed, at most 2
   questions), the offline reader, the shaft layout and volume by hand, sizes from the shaft.
7. A part with no direct builder goes to the design agent (offline stand-in): the job is followed, the part is not
   verified, so it is honestly left out of the assembly and the chat says to finish it in the Studio.
8. API rules: empty text 422, an unusable model answer falls back to the offline reader, reset archives.

Also green after the trains / fitz changes (one file per run): `test_assembly_trains.py` 8, `test_assembly_ai.py` 21,
`test_assembly_visual.py` 26, `test_assembly.py` 21, `test_llm_providers.py` 35, `test_agent_latency.py` 9. ruff
clean; `tsc --noEmit` clean; vitest (assembly + `noLongDashes`) 10 passed; `vite build` ok.

### Browser walkthrough (port 8812, scratch data, screenshots in `docs/reports/assembly-chat/`)
- Offline reader (no AI): "bring a Ø20 shaft 120 long, a spur gear m2 z30 and two 6204 bearings and put them on"
  (8.9 s), "check for clashes" (3.2 s, 0 clashes); `dry-offline-reader.png`.
- Chips: two shafts and a gear, "assemble everything" asks, the chip answers, the idle shaft moves aside, check 0
  clashes; `chip-1-question.png`, `chip-2-answered-and-checked.png`.
- **Context survives a reload:** after each walk the page was reloaded and every message came back from the server
  (10 of 10 in the live run, 8 of 8 in the chip run); `live-5-after-reload.png`. 0 console or page errors.

### The live conversation (one, 5 turns, real model through the provider layer)
| # | the engineer said | model | what it did | wall time | tokens |
|---|---|---|---|---|---|
| 1 | make a stepped shaft Ø20 with a keyseat, then bring a spur gear m2 z40 and a key, then assemble them | Opus (complex), 8.2 s, $0.025 | made the shaft (assumed sizes listed), brought the gear sized bore 25 / keyed 8 x 3.3 / face 20 and the 8 x 7 x 16 key, assembled: gear against the shoulder, keyway on the keyseat, key in its seat; said the shaft has no bearings yet; 5 mates all satisfied | 22.7 s | 3 |
| 2 | bring two 6204 bearings for that shaft and put them on | Sonnet, 4.9 s, $0.014 | resolved "that shaft", brought 2 x 6204, seated both against the shoulders (line placed again, gear and key unchanged); 9 mates satisfied | 5.7 s | 2 |
| 3 | make the gear 2 mm wider | Sonnet, 6.8 s, $0.008 | face width 20 → 22 through its parameter, mates kept, checked: 0 clashes | 20.5 s | 1 |
| 4 | check it for clashes and turn it through its range | Sonnet, 5.1 s, $0.008 | interference 0 clashes; motion 24 steps, no collisions | 7.7 s | 1 |
| 5 | what is in it now, and is anything not held? | Sonnet, 6.2 s, $0.008 | explained: base shaft, gear, key and both bearings on it, 9 mates satisfied, nothing unplaced, 0 clashes | 6.6 s | 1 |

**Total: 8 platform tokens ($0.062) of the 80 budgeted**; wall time 63 s for five turns. The model's choices matched
the recorded replies used in the tests (same actions, ids resolved from the summary). Turn time is mostly the CAD
kernel: the first build of the shaft and the z40 gear snapshot (turn 1), the new 22 mm gear snapshot (turn 3).
Per-turn results: `docs/reports/assembly-chat/live-turns.json`.

## Files
- New: `src/aicad/assembly/{chat.py, agent.py, makers.py, fixings.py}`, `src/aicad/platform/routers/mod_assembly_chat.py`,
  `tests/test_assembly_agent.py`, `tests/golden/assembly_agent/replies.json`,
  `web/src/pages/app/modules/assembly/{AssemblyChat.tsx, chat.ts, chat.test.ts}`, this report and its folder.
- Changed in the assembly module: `assembly/trains.py` (key / ring roles, `only_shafts`, shoulder stop for hubs, keyed
  hub turning, keys and rings on lines, joints include them), `assembly/fitz.py` (`part_key`, `shafts`, sizing of
  "a key" / "a circlip" from the line, outcome codes `no_keyseat`, `key_mismatch`, `no_groove`, `ring_mismatch`,
  `made` in the result), `Workspace.tsx` (Chat tab, Quick add label), dash placeholders in `CheckPanel`,
  `InsertDialog`, `PairPanel`, `bits`, `viewer`.
- **Shared files touched:** `src/aicad/llm/base.py` (role), `src/aicad/llm/routing.py` (three routes),
  `web/src/noLongDashes.test.ts` (scope + the assembly folder), `.claude/skills/design-agent/SKILL.md` (a section on
  the assembly agent). No Design Studio files, no `App.tsx`, no catalog change.

## Known limits
- Shaft lines are placed again as a whole when one of their parts is mated: deterministic, but a hand-edited mate on
  that line is replaced (mates to parts outside the line are kept).
- Keys in a square-ended keyseat (the Toolbox shaft) are free to slide along it, and the step says so.
- The code asks only the "which shaft" question; other ambiguity is the model's to ask.
- The design-agent path was tested with the offline stand-in (the job, the not-verified outcome); no live design
  turn was spent from the chat (it costs about 250 tokens cold).
- Housings and bearing seats in a housing are not chat tools yet (`fitz.mount` covers hole-pattern mounting only).
- `graph/compile.to_fitz_items` still leaves keys and rings to the office; trains can now place them (a note for the
  connection-layout work, not changed here).
- Running `test_assembly_trains.py` and `test_assembly_ai.py` in one pytest call hung once with no CAD worker alive;
  each file alone passes (66 s and about 90 s). Not investigated further.

## Parked decisions (default used)
- **PD-170** Model routing for the assembly agent: simple turns Sonnet, complex (assemble everything, three kinds of
  work at once, "make" with no numbers) Opus; 40-token hard cap per turn, also in God mode.
- **PD-171** One conversation per assembly, shared by everyone who can edit it, stored with the assembly; "New
  conversation" archives the old one. Alternative: one per person.
- **PD-172** The Chat tab opens first in the Assembly Studio for editors (viewers open on Mate); the one-shot panel is
  kept as "Quick add".
- **PD-173** "Make a stepped shaft Ø d" rules: journals = the 62xx bearing width + 2 (else 16), seat Ø d + 5, collar Ø
  seat + 5 x 8 long, hub width 20, seat = hub + 10, keyseat DIN 6885 length = longest standard length up to hub - 4,
  centred in the hub against the collar, circlip groove at the hub's free face, 1 mm end chamfers; every one of them
  is listed as assumed in the reply.
- **PD-174** A hub on a seat closed by a shoulder sits against the shoulder (before the keyway centring rule). This
  also changes Quick add / Fitz for user shafts whose hub seat ends in a shoulder.
- **PD-175** A retaining ring bears on its groove wall away from the part it holds (the gap to the part is the groove
  width minus the ring thickness, 0.1 mm for DIN 471 Ø25).
- **PD-176** "Bring" inserts unplaced (the first part becomes the fixed base); placing needs "mate" or "assemble",
  which the agent adds when the engineer says "put them on".
- **PD-177** Sizes from the context: a gear's face width covers its key with 2 mm each side (keyseat + 4), else 10 x
  module up to the seat length; bore = the keyed (else longest) seat; key = the longest DIN length that fits the
  keyseat.
- **PD-178** Parts made in the chat become new workspace parts, joined to the assembly's home part's project when
  there is one; a part that needs the design agent runs with the brief approval skipped (the conversation is the
  brief) on the Studio's normal run budget.
- **PD-179** The chat persona is Fitz's badge with the label "Assembly agent" (Hex and Fitz stay the names in step
  lines).

## For the master
- Module code `assembly`; no new Studio entry point is needed (the Chat tab is in the module). A Studio "Open in
  Assembly Studio" already exists via the Make tab.
- Suggested PUNCH_LIST row: ASM-026 "Assembly agent chat (WORKLIST 51)", status done, evidence this report.
