# Program revision at any stage (branch `wip/program-revision`, WORKLIST 49 follow-up, PD-100)

Founder, 2026-11-20: *"Analyze TEST Project. It got stuck at Assemble Legs and it can't make any correction now and
asking me for new program. Please diagnose and apply the fix so that such situation does not arise. Even if assembly
needs changing of dependent parts, it must revise even after those parts are done. It should do whatever needs to be
done to solve problem."*

## Diagnosis (founder's TEST Project, read only)
- The block layout made the Folding leg (4 off) the base. It hung the Table top and all four hinge brackets on leg #1
  (IF-01 to IF-05 all name `Folding leg #1`) and laid legs #2 to #4 out loose in a row.
- The ICD gate checks `no_interface` per item, not per copy, so it passed.
- At Assemble Legs, the quick check found leg #2 floating and blocked. Archie paused TP-5 and later TP-11.
- Nothing could revise an approved, partly integrated program. A change request only changes one interface's numbers,
  and it refuses anything that moves other parts or touches integrated ones. Supervisor plan tools were refused after
  part work started (PD-100). So Archie answered "Redo what is needed" with *"Nothing can be redone in this program…
  The proper fix is a new program"*.
- Reproduced on my own data dir (port 8811): the same plan and design graph give the same ICD v1 (5 interfaces, leg
  base, `problems() == []`). The same block happened at TP-5 within 6 s of Run.
- The layout itself (paired copies, per-copy gate, right base, pivot kind) is `wip/connection-layout`'s. This branch
  adds the missing capability: **revising a program after work is done**.

## What was built

### 1. `src/aicad/office/revision.py` (new): a revision is ICD v(n+1) at any stage
- **Changes** (`clean_ops`), named by part as in the plan (`Folding leg #2` is fine: one design serves every copy):
  - `base`: the part everything else is carried by;
  - `mount` (`part` on `on`);
  - `size` (envelope L, W, H);
  - `qty`;
  - `add` (to a sub-assembly, new or existing);
  - `remove`;
  - `describe` (a new description, which forces a redesign);
  - `relayout` (only derive the layout again with today's solver).
- **The revised plan** keeps item ids stable: kept parts keep their ticket, build and assembly instances, and new
  parts get new ids. A design-graph plan keeps its graph in step (qty, removed parts, who carries whom), so the
  connection layout reads the same change once it is merged.
- **Derived through the normal path**: `interfaces._rebuild(doc, overrides)`. That is `icd.build` today, and on
  `wip/connection-layout` it becomes `_graph_layout(...) or icd.build(...)`, so a revision uses the new solver
  without any change here.
  - Frozen item sizes and edits of kept parts carry over.
  - A resized part and the base take their size from the plan again.
  - Interface overrides (accepted CRs, edits, the values frozen at approval) follow their **joint** (kind and the two
    part copies), not the interface number, since numbers shift when parts come and go.
- **Base on today's block layout**: the layout picks the largest block as the base. When a revision names another
  base, that part gets a footprint that covers every other block and carries its parts in a row.
- **Paired copies on today's layout**: a host's copy n carries its guest's copy n only when the host's size is
  planned. `complete_pairs` adds that size op (the host's current size) when a revision mounts N copies on N copies.
  This was found in the live run (below).
- **Per-copy placement check** (`loose_copies`, `placement_blocks`), used to accept a candidate:
  - the copies no interface names;
  - plus `assembly.visual.quick_skeleton`, the touch check on the layout.
  A candidate is refused when it adds an ICD problem, when it leaves as much floating as before, when the layout is
  unchanged, or when the asked base isn't the base.

### 2. Impact analysis (deterministic, per item and per copy)
Each part is compared between the old and the new ICD and skeleton. Features are compared in the part's own frame,
without interface numbers.

| class | rule | what happens |
|---|---|---|
| unchanged | same geometry (role, shape, envelope, bore, gear numbers), same feature set, same placement | build kept |
| moved | same geometry and features; new copy positions, rotation, or number of copies | build kept, re-placed |
| redesign | envelope or an interface feature changed, or a new description | ticket reopened even if approved or integrated; precise instruction (features to remove and to add, with positions); new ICD excerpt in the next design turn; a part built from the interface spec is rebuilt by the direct path |
| added | new in the plan | new ticket (and a new integration ticket for a new sub-assembly) |
| removed | out of the plan | ticket retired to `retired_tickets`, with its comments and history |

- **Levels**: a sub-assembly that holds a changed part, or whose integration is stopped, runs again (reset to
  backlog and un-paused). So does the final assembly. Untouched sub-assemblies stay integrated, and their assembly
  documents are kept as they are (`program_assembly.build(keep_subs=…)`).
- **Estimate**: about 26 tokens per agent redesign and 45 per new part (the measured CONTEXT figures). A part built
  from the interface spec costs 0 tokens. Minutes use the program's calibrated rates for the parts and integrations.

### 3. Apply, records, undo
- **`apply`** does all of this:
  - It refuses while an affected ticket is mid-step, and on a released program (that is the change notice's path).
  - It bumps the ICD version, re-freezes the overrides at the new sizes, and drops the stale layout look.
  - It writes an ICD history entry `revised`, an entry in `doc["revisions"]` (the ops, the impact, the snapshot) and
    `ticket["revisions"]` change records on reopened and re-placed parts. It also writes the ECN-style instruction as
    a comment and `icd_delta`.
  - It emits the events `program.revised`, `ticket.retired` and `ticket.opened`.
  - It locks the release gate again if it was pending, and sets the office running.
- **Program assembly**:
  - It is marked `building`. Integrations wait for it (`orchestrator.claimable`, only for a revision rebuild).
  - It is laid out again in the background (`revision.spawn_rebuild` → `platform_env.build_program_assembly`). Kept
    real parts go in at their new places (through Gage's frame now as well), and reopened or added parts go in as
    placeholders.
- **`undo`**:
  - It applies only to the latest revision.
  - It works only while no reopened part has had another turn or direct build, and no added ticket has started.
  - It restores the plan, items, tickets, ICD and skeleton from the snapshot, writes an `undone` history entry and
    rebuilds the assembly.
- **Archie log entry and audit**:
  - Archie's revisions go through the supervisor log (asked, then applied or declined, with undo).
  - Engineer revisions (chat Apply or the API) write the same log entry (`log_revision`).
  - Audit rows: `office.revision`, `office.revision_undo`, and the supervisor decision.

### 4. Archie
- **New supervisor tool `revise_program`** (`changes: [...]`), described in his instructions together with *"Never
  tell the engineer to start a new program: revise this one."*
- **`state_view`** carries the layout facts a revision needs (`revision.context_lines`): each part's copies,
  envelope, what carries it, the plan hints, the per-copy placement check, and earlier revisions.
- **Rule-based reading** (no AI, simulated, hourly cap): a blocked integration whose reason is a placement problem
  gets `revision.propose`. It tries a relayout with today's solver first, then the structural repair:
  - one base with one piece, chosen from the design graph's connections (else the part the interfaces hang on);
  - every other part mounted on the part it connects to;
  - hosts of paired copies keep their size;
  - a part wider than its host stands on its end.
  If nothing clears it, he says so and asks what should carry what. A new program is mentioned only as the last
  resort the engineer can choose.
- **With AI**: if Opus's revision can't be built, or he only describes it in words, the office's own revision is
  added. The engineer always gets a one-click question, never only words.
- **Classification** (PD-150): any part added, removed or redesigned is **major**, and asked with the impact list on
  the chips ("Yes, revise the program" / "No, leave it"). A re-place-only revision is minor when the engineer asked
  for the plan change, major when Archie proposes it.
- **Plan tools after work started** (`remove_part`, `add_part`, `set_qty`) now become a revision instead of the old
  refusal "an engineering change (or a new program)".
- **Messages that used to send the founder to a new program are replaced**:
  - the chat instructions (the old last line, and `revise_program` added as an action);
  - the offline chat reader (a placement block plus "redo / fix / stuck…" proposes the revision);
  - the fallback help line;
  - the stop message after a placement block (`visual_office.level_message`: "A revision of the program fixes it at
    any stage…"). It no longer offers a pointless retry of the same layout.

### 5. A sub-assembly joined through another level is not floating
After the revision each bracket and leg pair stands on the table top, which is in the Top sub-assembly. Alone, the
Legs sub-assembly is four pairs touching nothing of each other. `visual_office.known_loose` now marks a floating group
(or a whole-level row) whose part copies are joined by an interface to a part of another level as a **note**: "It is
joined to Table top of another sub-assembly: the final assembly checks it there." The final assembly runs the same
check over everything. The founder's original leg #2 (no interface at all) still stops (tested).

### 6. API and UI
- **API**:
  - `POST /api/office/programs/{pid}/revision/preview {changes}`: the impact; nothing changes.
  - `POST …/revision {changes, reason}`: the engineer's revision.
  - `POST …/revisions/{rid}/undo`.
  - The chat action `revise_program`.
  - `service.view` returns `revisions` (no snapshots) and `retired_tickets`.
- **Web** (`ArchieLog.tsx`, `types.ts`):
  - `RevisionImpactList`: badges per class, changes, per-part rows with the reason, assemblies run again or kept,
    floating before and after, the estimate. It appears in the question chips, in Archie's log entries and in a new
    **Program revisions** card on the Archie tab, with Undo.
  - The Archie tab's help text says he revises the program.

## Evidence
### Tests: `tests/test_program_revision.py`, 15 tests, hand-checked, no CAD, no model call
- **The founder's table, rebuilt from its plan and graph.**
  - The block reproduces: leg base, 5 interfaces all on leg #1, `problems() == []`, loose copies leg #2 to #4.
  - Archie's rule-based revision:
    - base Table top; bracket on top; leg on bracket; bracket kept at 100 × 70 × 16; leg on its end 90 × 20 × 568.
    - Hand values: top 4 × 100 + 3 × 12 + 2 × 10 = 456 by 70 + 20 = 90; brackets at −168, −56, 56, 168; leg centre
      Z 16 + 284 = 300.
    - Per copy: bracket n ↔ top, leg n ↔ bracket n.
    - Impact: top, leg and bracket redesigned; the 4 bought-out parts unchanged; Top, Legs and final run again;
      Fasteners kept; 78 tokens.
  - Archie's corrected plan (1200 × 600 × 18 top, 80 × 60 × 40 brackets, 40 × 40 × 700 legs):
    - brackets at −138, −46, 46, 138 (4 × 80 + 3 × 12 = 356);
    - legs at Z 40 + 350 = 390.
  - Applied end to end: ICD v2 approved with 8 interfaces; TP-1, TP-3 and TP-4 reopened with the instruction and
    records; TP-2, TP-5 and TP-11 reset and un-paused; kit TP-10 and the bought-out parts stay integrated; event
    recorded. Undo restores ICD v1, the skeleton, the plan and every column. Undo is refused once TP-3 had a turn.
- **A part added to a done program** (plate 200 × 80 × 10 carrying a cover 60 × 40 × 6, adding a 40 × 30 × 20
  bracket):
  - row 60 + 12 + 40 = 112, centred, so the cover is at −26 and the bracket at 36;
  - the cover's holes stay ±19 / ±9 in its own frame, so it is **moved**;
  - in the plate's frame the holes move to −45 / −7, so the plate is **redesign**;
  - bracket **added** (new ticket, in Assemble Frame's dependencies); bolt **unchanged**.
- **A part removed**: the cover is back at X 0 (moved), the plate is redesigned, and the bracket ticket is retired
  with its comments.
- **A size change** (cover H 6 → 8): only the cover is redesigned (its mounting face moves Z −3 → −4 in its frame). The
  plate and the bracket stay approved, and exactly one ticket is reopened.
- **Archie**:
  - Rule-based: he proposes the revision, asks (major, "it reopens parts already worked on"), puts the impact lines
    on the question, and says nothing about a new program. Approve gives REV-1, nothing floating and the office
    running. Undo through the log works.
  - `remove_part` after work started becomes a revision (major).
  - Relayout with the same layout is refused.
  - The minor and major rules.
  - The instructions never name a new program as advice.
  - The chat reader offers the revision.
  - The revision waits for a step in progress and refuses after release.
  - The level check through another sub-assembly.
  - Archie's live ops are completed so copy n carries copy n.
  - A live reply with no action, or with an unbuildable one, still ends in a one-click question.
- **Neighbours, one or two files per run, no workers left from this worktree**:

  | Files | Passed |
  |---|---|
  | `test_office_supervisor` + `test_office_archie_chat` | 34 |
  | `test_office_supervisor` | 21 |
  | `test_assembly_visual` + `test_office_polish` | 38 (one placement-stop assertion updated: no retry offer, the revision text) |
  | `test_office_orchestrator` + `test_office` | 41 |

- `ruff check src tests` is clean, `tsc --noEmit` is clean and `vite build` is OK.

### Browser on the TEST copy (port 8811, own data dir, simulated designers)
The screenshot names below are the scratch names; the copies kept in `docs/reports/program-revision/` are listed at
the end of this section.
Setup: the program was created with TEST's exact plan and graph, and both gates were approved. Run was pressed once
the placeholder assembly was ready.

**Rule-based run (`shots-rules/`)**
- **1-board-blocked, 3-assembly-before**: the founder's picture: four legs in a row, brackets clustered on leg #1, TP-5
  blocked.
- **2-archie-tab-asking**: "Waiting for your decision · Major: asked you", "Revise the program to ICD v2 (…)", 3
  redesigned / 4 kept, about 78 tokens, the per-part list.
- **4/5-chat**: the same question in the chat, "Yes, revise the program", toast "Done: Archie applied it". The header
  shows ICD v2, and REV-1 is under Program revisions.
- **Run to the end, 25 s after the Yes** (simulated designers): every ticket integrated, then the drawings and the
  manufacturing review. The final assembly reads "3 real parts and 0 placeholders: 152 mates, 16 fastener stacks;
  Fitz's whole-program clash check (advisory): no clashes across 72 candidate pairs". Top, Legs and Final "Looks
  assembled".
- **8-assembly-after, read**:
  - the table top is the base;
  - four brackets sit on it, each with its own leg standing on it;
  - nothing is floating and nothing is in a row on the floor.
  - Still today's block layout: the brackets are in a row along the top rather than at the corners (the connection
    layout's job). The top keeps its bracket-sized width (90 mm) because the rule path keeps sizes; Archie's live
    proposal re-sizes it.
- 0 console or page errors.
- **Fixed from the screenshots**:
  - the URL (the program route);
  - the choice chip hidden under the composer (the click now scrolls it into view);
  - a doubled full stop in "Floating now";
  - the Interfaces tab showing the v1 layout look ("looks wrong") after the revision: the stale look is dropped.

**ONE live run (`shots-live/`, `FW_OFFICE_SUPERVISOR_LIVE=1`, Opus, designers simulated)**
- **Pass 1** (the block): Archie diagnosed it exactly. His words: *"The parts are fine, but the layout is upside down.
  Everything hangs off leg #1 … I propose revising to ICD v2: Table top as the base, one hinge bracket per corner
  mounted on the top, and each folding leg mounted on its own bracket, standing upright at 90 × 20 × 568 mm … re-size
  the table top to 800 × 600 × 20 mm"*.
  - It was not actionable: on today's layout his ops put all four legs on bracket #1 (the brackets had no planned
    size), so `check` refused them, and the engineer only got words.
  - Fixed: `complete_pairs` and the office fallback (tested with his recorded ops).
- **Pass 2** (after the fix; "Ask Archie to check now", 4 tokens, $0.037): his own ops plus the bracket size the
  office added. The question gave about 78 tokens and 7.6 min, 3 redesigned and 4 kept. The engineer approved it in
  the chat.
- **Spend**: 2 supervisor calls, **9 platform tokens** in all (the program's planning tokens), against a budget of
  about 60.
- **Result after the Yes**:
  - REV-1 was applied: ICD v1 → v2, TP-1, TP-3 and TP-4 reopened, TP-2 and TP-5 reset.
  - The program was **complete 12 s later**: 13 of 13 tickets, drawings (5 part sheets plus the assembly with 6
    balloons) and the manufacturing review done, "Ready to release".
  - Final assembly: 152 mates, 16 fastener stacks, no clashes over 72 pairs; Top, Legs and Final "Looks assembled".
- **`6-live-assembly-after.png`, read**:
  - the 800 × 600 table top is the base;
  - four brackets stand on it, each carrying its own upright leg;
  - nothing floats.
  - The brackets are in a row near the middle, not at the corners: today's block layout.
- `4-live-revision-record.png`: REV-1 with Archie's reason ("re-basing on the table top and giving each leg its own
  bracket puts an interface on every copy"). It is marked "Undo is no longer possible: TP-1 has been rebuilt for the
  revision".
- Screenshots in `docs/reports/program-revision/`:
  - `1-before-legs-floating`
  - `2-archie-asks-with-impact`
  - `3-live-chat-approved`
  - `4-live-revision-record`
  - `5-rules-assembly-after`
  - `6-live-assembly-after`

  Archie's live message is in `live-archie-message.json`.
- A stale chip remains: the Assembly tab still shows "Layout (interfaces gate): Looks wrong". It is the look taken at
  the v1 gate, kept in the looks list. The Interfaces tab's copy is dropped on revision; this one is not (listed
  under limits).

## How to fix the founder's real TEST Project once merged
Open the program, then **Archie tab > Ask Archie to check now**. TP-5 and TP-11 are blocked, so he proposes the
revision with the impact list. Answer **Yes, revise the program** in the chat or on the Archie tab. The parts are
redesigned by the live designers (about 78 tokens estimated) and the program runs to completion. No new program is
needed. If AI is off, the rule-based reading proposes the same revision.

## Known limits / not done
- The layout is still today's block layout: brackets in a row on the top, not at the corners; a bolted joint between
  bracket and leg, not a pivot. The connection layout (`wip/connection-layout`) improves the result. Revisions call
  it through `interfaces._rebuild` with no change here.
- After the revision, Legs reports "8 planned parts not placed": the pivot bolts, washers and nuts. The layout's
  bolted joint is M5 face to face, with no pivot kind, so Fitz has no seat for the M8 pivot hardware. It is
  advisory, and it is the connection layout's pivot kind.
- A revision on a released program is refused: the change notice (ECN) path handles it there (PD-155).
- The race found on the way (pre-existing): Run pressed while the placeholder assembly is still building lets a kit
  integration take the old non-ICD path and stop as "a row". This branch guards it only during a revision rebuild.
  The general guard would hang tests that never build an assembly.
- The Assembly tab's list of looks keeps the v1 gate look ("Looks wrong") after a revision. The new levels' looks
  read "Looks assembled". The Interfaces tab's look is dropped.
- The impact is computed on the item's interface features in its own frame. A feature the designer added beyond the
  interfaces (a brief requirement) does not make a part "redesign" unless its envelope or interfaces change.

## Parked decisions (default used)
- **PD-150 Minor or major.**
  - Any revision that adds, removes or redesigns a part is major, and Archie asks with the impact list.
  - Re-placing only is minor when the engineer asked for the plan change, and major when Archie proposes it.
- **PD-151 Redesign trigger.** A part is redesigned when its envelope or its interface features (in its own frame)
  change, or its description is changed. Otherwise its build is kept, and re-placed if it moved. Alternative: reopen
  every part touched by a moved joint.
- **PD-152 Levels.**
  - A sub-assembly with any changed part, or a stopped integration, runs again, and so does the final assembly.
  - Untouched sub-assemblies keep their documents and fasteners.
  - Kept parts of a reset level go back from Integrated to Approved.
- **PD-153 Estimate constants.** About 26 tokens per agent redesign and 45 per new part; 0 for a part built from the
  interface spec. Minutes come from the calibrated rates.
- **PD-154 Undo window.** Only the latest revision can be undone, and only until a reopened part has another turn or
  build, or an added part starts.
- **PD-155 After release.** A revision is refused and the change notice (ECN) is the path. Alternative: a revision
  that opens an ECN automatically.
- **PD-156 Base on today's block layout.** The named base gets a footprint covering every other block. Paired copies
  get their host's current size (`complete_pairs`). Both are said in the change list.
- **PD-157 A level joined through another level.** A floating group joined by an interface to a part of another
  sub-assembly is a note at that level; the final assembly checks it.
- **PD-158 AI fallback.** When Opus's revision can't be built, or he only describes one, the office's own revision is
  asked instead, so a placement block always ends in a one-click question.
- **PD-159 Last resort.** A new program is mentioned only when no revision clears the problem, as the engineer's
  choice, after asking what should carry what.

## Files
- **New**:
  - `src/aicad/office/revision.py`
  - `tests/test_program_revision.py`
  - this report
- **Changed**:
  - `office/supervisor.py`: the tool, the rules, check, classify, describe, execute, undo, `log_revision`,
    `revise_now`, the fallback, and the question impact.
  - `office/archie_chat.py`: the instructions, the action, the offline reader, the prompt.
  - `office/visual_office.py`: the stop message, and levels joined through another level.
  - `office/program_assembly.py`: `build(frames, keep_subs)`.
  - `office/platform_env.py`: `build_program_assembly(keep_subs)`, and frames for kept parts.
  - `office/orchestrator.py`: integrations wait for a revision rebuild.
  - `office/service.py`: the view.
  - `platform/routers/office.py`: 3 endpoints, the chat apply, and audit.
  - `tests/test_assembly_visual.py`: one assertion.
  - Web: `ArchieLog.tsx`, `types.ts`.
- Not touched: `icd.py` layout internals and `src/aicad/graph/` (both `wip/connection-layout`'s).
