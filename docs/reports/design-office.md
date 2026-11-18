# Design Office — Phase 2 report (CD-001…CD-005, CD-017)

Branch `wip/design-office`, 2026-11-18. Plan: `docs/plans/CHIEF_DESIGNER.md`.

## What exists now

**Office home** (`/app/office`, nav entry "Design Office", labelled Preview): programs with roll-up progress and ETA
range, the reviews inbox (brief gates waiting for approval, tickets in review with Approve / Changes), token spend vs
budget, and the team roster (state derived from assigned tickets; hover an idle agent to see its working
animation; "Meet the team" shows every agent in every state).

**New program** (`/app/office/new`): name, brief, example briefs, planner choice: **Archie** (AI, metered, capped at
200 tokens) or **Standard breakdown** (deterministic templates, free). Concurrency (default 3) and token budget.

**Brief gate / plan review**: Archie's narrative, summary, assumptions, and any fallback note in amber. Every
sub-assembly and part is editable (name, family, complexity, qty; add/remove). A live preview shows the ticket count,
total effort and ETA range at the program's concurrency (client math mirrors the server, tested). Approve (with or
without edits), Ask Archie to revise (notes), or switch to the standard breakdown.

**Program board**: Backlog → Ready → In design → In review → Changes requested → Approved → Integrated; one
swimlane per sub-assembly (with its roll-up and ETA) plus the final assembly. Cards: specialist avatar in its state
(progress ring while in design), key, title, qty, Toolbox / assembly markers, checks badge from the linked Studio
build, tokens, comments, estimate outline with progress fill. Drag to move (HTML5 drag; a real drag was verified in
headless Chrome); live over SSE with a polling safety net; optimistic moves.

**Ticket drawer**: specialist, column, complexity, milestones (checkboxes), brief, dependencies, comments, history,
and **Start**: a part ticket creates one Design Studio project (name "Program · Part") and opens it with the ticket
brief ready in the chat box (not sent); an integration ticket creates an Assembly Studio document and opens it.

**Program tree**: program → sub-assemblies → parts, effort-weighted progress, effort, ETA ranges at assembly levels,
status. **Activity**: the event log in plain language.

Honest labelling everywhere: "Archie plans programs today. Auto-run arrives with the orchestrator: until then you
move tickets on the board, and Start opens the part in Design Studio with its brief ready to send." Comments say
they reach the agent once auto-run arrives. Gage/Ortho/Smithy show "Auto-run soon" / "Later". The ICD gate shows
"later".

## Architecture

| Piece | File |
|---|---|
| Roster, families → specialist | `src/aicad/office/roster.py` |
| Estimating constants + progress, roll-up, critical path, ETA | `src/aicad/office/estimates.py` |
| Archie (fw-plan block) + standard planner | `src/aicad/office/planner.py` |
| Program documents + event log (`<data>/office/<org>/<pid>/`) | `src/aicad/office/store.py` |
| Operations, event emit, in-process bus, views | `src/aicad/office/service.py` |
| API (`/api/office/...`) | `src/aicad/platform/routers/office.py` |
| UI | `web/src/pages/app/office/` (Home, NewProgram, PlanReview, ProgramPage, Board, Tree, TicketDrawer, Avatars + avatars.css, model.ts, api.ts, types.ts) |

Shared files touched minimally: `platform/app.py` (router registration), `web/src/App.tsx` (one lazy route),
`web/src/layouts/AppLayout.tsx` (one import line + one `NavItem`), `studio/ShopStatus.tsx` (`gearPath` exported).

### Estimates (one place: `estimates.py`)
- estimate = complexity (1–5) × minutes per unit: machined 4, turned 3.5, gear 4, sheet 4.5, plastic 5,
  standard 0.5, integration 3. Integration complexity = ceil(children / 3).
- progress = weight of the furthest milestone: brief read 5 · first build 35 · gating checks pass 70 · self-review
  85 · approved 100. Moving to Approved/Integrated adds "approved"; moving back removes it; Changes requested drops
  self-review. First build / checks pass are derived from the linked Studio project (and drop back if the latest
  build fails a check).
- roll-up = Σ(estimate × progress) / Σ estimate over the subtree, own integration ticket included.
- ETA range: W = remaining work, CP = remaining critical path (integration waits for all children), N = concurrency:
  low = 0.8 × max(CP, W/N), high = 1.3 × (CP + W/N) (Graham's bound for greedy schedules), shown as a range.

## Tests
- `tests/test_office.py` (20 tests, no live AI: `planner.run_agent` is replaced in the fixture by a function that
  fails the test if called): estimate constants and milestones; roll-up, critical path and ETA against hand
  calculations; fw-plan parsing (valid, 6 invalid forms, last valid block wins, scrubbing, alias/clamp); standard
  planner determinism and keywords; ticket building; API CRUD + brief gate with edits; moves, milestones, comments,
  events (order, `after`, SSE `once`), inbox, roster, completion; tenant isolation + viewer read-only; Archie plan
  parsed and metered (7 tokens), revise with notes, fallback on a bad answer and on failure (uncharged); Start
  creates one project with the starter prompt, milestones/tokens/checks derive from the project, integration opens
  an assembly.
- `web/src/pages/app/office/model.test.ts` (6 tests): formatting, client plan preview equals the server's
  `plan_estimate` on the same plan, swimlanes, progress after a move.
- Browser walkthrough (puppeteer-core 25.18.1, port 8794, throwaway data dir, standard planner only): home, new
  program, plan review with an edit, approve, real drag to In design, board with every state, drawer, tree,
  activity, roster, Start → Studio with the brief in the chat box, reduced motion; 0 console/page errors.
  Screenshots: `docs/reports/design-office/`.

## Limitations
- No live Archie run has been made (tests mock it); prompt quality on benchmark briefs is unverified.
- Agents don't run tickets; roster "working" means a ticket assigned to that agent is In design.
- The standard planner has six product templates (gear reducer, conveyor, gripper, enclosure, fixture, linear
  axis) plus a generic breakdown; it is a fallback, not a designer.
- SSE uses EventSource, which cannot send `X-Org`; in a non-default workspace the stream falls back to polling
  (same limitation as the Studio chat stream).
- Budget is shown, not enforced (CD-016). Skeleton/ICD, placeholders, change requests, timeline: later phases.
- Avatars are not yet in the Studio chat; the hand-off slide animation needs agent hand-offs (Phase 3).
- The board needs ~1180 px; narrower screens scroll it horizontally.

## What Phase 3 (orchestrator) plugs into
1. **Operations** (`aicad.office.service`), called under `store.lock(pid)` with load → change → `store.save`:
   `move(root, doc, tid, column, actor)`, `set_milestone(root, doc, tid, code, reached, actor)`,
   `comment(...)`, `update(...)`, `link(root, doc, tid, actor, project_id=/assembly_id=)`. Use
   `service.agent_actor("mill")` as the actor; the board, roll-up, ETA and activity need no change.
2. **Ticket fields reserved**: `run` (null today: put the agent instance, e.g. "Mill #2", start time, status),
   `tokens` (already summed from AgentRuns of the linked project), `checks`, `depends_on` (integration tickets wait
   on their children; use for critical-path priority), `specialist`, `brief` (starter prompt), `project_id`,
   `assembly_id`.
3. **Program fields**: `concurrency` (the cap), `budget.tokens` / `budget.spent` (stops at 80/100 % for CD-016),
   `gates` (ICD gate placeholder `status: "later"`), `items` (tree with stable ids for ICD references).
4. **Events**: `service.emit(root, doc, type, text, actor, ticket_id, **data)` writes `events.jsonl` and publishes
   on `service.bus` (thread-safe) to `program_id` and `org:<org_id>` keys; SSE endpoints
   `/api/office/programs/{pid}/events` and `/api/office/events` relay them. Suggested new types: `ticket.claimed`,
   `ticket.handoff` (drives the avatar slide), `agent.status` (live status line), `budget.stop`.
5. **Milestones from agent events**: `sync_studio` already derives first build / gates pass from the project; the
   orchestrator adds brief read (agent's first turn) and self-review, and Gage sets approved/changes requested.
6. **Running an agent on a ticket**: `routers/projects.get_session(project)` + `AgentSession.send(ticket.brief)`
   on the ticket's project (created by the same code path as Start).

## Parked
PD-39 (estimating constants, ETA formula, Archie cap/fallback, default budget, Preview label).

---

# Design Office — Phase 3 report (CD-006…CD-009, CD-016)

Branch `wip/office-phase3`, 2026-11-18. The office now works its own tickets: press **Run** on a program and up to
`concurrency` agents pick tickets by critical path, Hex reuses what exists, specialists design in their own Studio
projects, Gage checks every part, and Fitz assembles each level. Everything still goes through `service` operations
and events, so the board, roll-up and activity needed no new plumbing.

## What happens when you press Run
1. **Claim** (`orchestrator.Runner.tick`, every second or on any change): claimable tickets (dependencies Approved /
   Integrated; not paused, taken over, blocked or already running; back-off elapsed) sorted by engineer priority, then
   **critical path** (own remaining estimate + the longest chain of tickets waiting for it), then most transitive
   dependents, then ticket order. Claims fill the free slots of `program.concurrency`; every running stage (Hex, a
   part agent, Gage, Fitz) holds a slot. Parallel instances are named Mill, Mill #2, ….
2. **Hex** (`platform_env.hex_lookup`, 0 tokens): standard tickets take the Toolbox reading of the item (default
   sizes are flagged "check it"; fasteners are sized from the holes at assembly) or a company part; designed parts
   reuse only what is unambiguous (an exactly named verified company part, or a fully specified Toolbox gear /
   fastener / dowel). A hit goes straight to Approved: "Hex found Hex bolt ISO 4017 M6×25 in the Toolbox (0 tokens)".
   A standard item Hex can't find waits for the engineer.
3. **Specialist** (`_design`): the ticket's Studio project is created (same shape as Start), then the real
   `AgentSession` gets the trade's practice note (`specialists.PRACTICE`: Mill prismatic machining, Chuck turned
   profiles, Axel Toolbox gear generators, Molly draft/ribs/walls, Benny "sheet metal not supported: solid of the
   blank thickness, say so") plus the approved ticket brief. The ticket brief skips the CAD-028 brief gate (it was
   approved at the program's brief gate; `brief_approved` is set on the session and the turn is sent in Build mode).
   The Studio chat shows a plain request ("Design Office ticket BTR-1 for Mill: …"), never the instructions.
   Milestones come from the session's own events: first text/tool → brief read; build tool result → first build (and
   the line "Mill is roughing out …" / "re-cutting: a check failed"); the project's latest build passing → gating
   checks; a finished turn with a passing build (or the agent's self-review block) → self-review. Tokens are the
   AgentRun metering of the project. A run without a passing build is retried twice with back-off (20 s, 40 s), then
   waits for the engineer.
4. **Gage** (`gage.py`): deterministic first: every gating check (CHK-09 included when the part has a reference) and
   every size the ticket's own brief states (Ø25, 120 x 80 x 10 mm) must be found in the envelope, the parameters or
   the dimension lines (a Ø may be carried as a radius named `*_R` / `RADIUS`). Only when that passes, a one-shot AI
   note (separate model call, own instructions, ≤ 60 tokens, metered and charged to the program; tests and simulated
   mode replace it) may still send the part back. Findings go on the ticket as a Gage comment, the card moves to
   Changes requested, and the findings become the agent's next message. After 2 send-backs the ticket is Blocked for
   the engineer. Gage can never be the designer (no self-approval).
5. **Fitz** (`platform_env.integrate`): once every child is Approved, an Assembly Studio document is created (or
   updated: parts already in it are kept), the approved parts / Toolbox items are inserted and auto-mated with
   `fitz._intend` + `fitz.execute`, and the exact interference check runs. 0 clashes → the children and the
   integration ticket move to Integrated; clashes → Changes requested with the clash list, Blocked for the engineer.
   The final assembly flattens the sub-assemblies (an assembly can't contain an assembly yet).
6. **Budget** (CD-016): `budget.warn` once at 80 %; no new work once fewer than 20 tokens of budget remain
   (`budget.stop`, state "stopped"); each design run's own budget is capped by what is left and by a fair share of
   the workspace balance (balance ÷ concurrency), so three agents can start on a small balance. God mode's token
   bypass is respected (badge "Budget bypass"). Raising the budget (program menu → Budget and agents) and pressing
   Resume continues.
7. **Rate limits**: a rate-limit / overloaded answer puts the ticket in "Waiting for capacity" with exponential
   back-off (30 s → 10 min) and holds new claims for the whole program until then.

**Restart:** the runner's state is the program document. On startup (and lazily on GET) every program whose
orchestrator state is "running" gets a runner; stages that were running are queued again at the same stage (a design
resumes with "the previous session was interrupted"). **Idempotent:** Run twice is one runner; a claim requires a
non-running status; a ticket an agent is working on can't be dragged.

**Engineer controls (CD-009):** comment (queued for the agent while it works, delivered as its next turn; shown as
"queued for Mill" / "sent to Mill"; a comment on a blocked ticket sends it back to the agent), priority high / normal /
low, reassign (designers and Hex for parts, Fitz for assemblies), pause / resume the ticket, take over (interrupts the
agent; continue in the Studio) / hand back, reopen, retry now. Program Pause lets running steps finish.

## UI
Program page: Run / Pause / Resume, a state chip ("Running · 2 of 3 working · 1 needs you", "Waiting for capacity",
"Stopped: budget reached"), an honest note on what running means, a "Simulated agents" badge in dev fake mode, token
meter with bar (amber at 80 %, red at 100 %), budget dialog. Cards: the current holder's avatar (Hex searching, Mill
working with progress ring, Gage inspecting, Fitz assembling), the live status line, chips (Waiting for capacity,
Retry n, Needs you, Paused, You took over), priority flag, spend (design + review). **Hand-off slide:** on
`ticket.handoff` the previous avatar slides out of the card while the next slides in, with a "Mill → Gage" caption
(static under reduced motion). Drawer: holder + line, reuse / integration result, controls, priority, comment
delivery, design and review tokens, sent-back count. Home: the "auto-run arrives" notice is replaced by what Run does
(still Preview); roster lines come from live runs; blocked tickets appear in "Reviews for you"; Benny shows "Solids
only".

## Files
New: `src/aicad/office/orchestrator.py` (scheduling, controls, runner, registry), `specialists.py` (practice notes,
prompts, status lines), `gage.py`, `platform_env.py` (DB, sessions, Hex, Gage call, Fitz), `fake_agents.py`
(simulated model client + Gage note), `tests/test_office_orchestrator.py`. Changed: `office/service.py` (ticket view,
budget/orchestrator in views, inbox/roster from runs, reassign rules), `office/store.py` (load/save retry on Windows
file races), `office/roster.py` (DESIGNERS), `platform/routers/office.py` (run, pause, control, priority, comment
delivery, move guard, startup resume / shutdown), `platform/routers/projects.py` (`session_for`: the session getter
without a request, optional `client_factory`; `get_session` delegates), web `office/` (types, model helpers + tests,
Board, ProgramPage, TicketDrawer, Home, api, avatars.css).

## Simulated agents (dev / tests only)
`FW_OFFICE_FAKE_AGENTS=1` (refused in production) swaps the model client of the real `AgentSession` through its
`client_factory` hook (the same hook as AGT-002 replay) for `fake_agents.FakeClient`: it answers each turn with SDK
messages, writes a tiny valid part (a block sized from the brief, real STEP via build123d, status with passing checks),
emits a self-review block and reports 30 tokens. So the whole Studio path runs: events, metering, revisions, Gage, and
Fitz with the real assembly worker. `FW_OFFICE_FAKE_DELAY` slows it for demos; `FW_OFFICE_FAKE_DEFECTS` (regex)
omits a brief size on the first build so Gage sends it back. A cassette replay was not used because the fake must size
each part from its own brief.

## Verification
- `tests/test_office_orchestrator.py` (15 tests, no model calls: Archie and the real Gage call fail the test if
  reached): critical-path priority on a hand-computed DAG (chains 19/29/12/9/7/3, dependents 2/2/2/1/1/0), ties and
  engineer priority, claimable states and back-off, budget levels, Gage deterministic review and AI-note parsing, Hex
  reuse rules, end to end (Hex bolt 0 tokens, Mill designs in its project, milestones in order from events, hand-offs
  hex → mill → gage → fitz, Fitz integrates three levels with 0 clashes, no internals in event text, the Studio chat
  shows no instructions), concurrency 2 never exceeded over 5 parts, Gage send-back then approve and a 3rd send-back →
  blocked, comments queued → delivered + controls, budget 80 % warn / stop / raise and resume, rate-limit wait,
  restart resume (server stopped mid-run, a new app resumes and completes), tenant isolation.
- Vitest `office/model.test.ts`: 11 tests (5 new: run chips, run-state label, budget tones, fresh hand-offs,
  assignable specialists).
- Browser walkthrough (puppeteer-core 25.18.1, port 8798, throwaway data dir, simulated agents with 2.5 s steps): a
  two-sub-assembly program run end to end, 3 agents working, Hex bolt reuse, Gage send-back then approval, hand-off
  slide, Fitz integration of every level (0 clashes; "0/4 bolts, left to mate by hand" because the simulated blocks
  have no holes), activity, home, and a second program stopped by its 80-token budget. 0 console / page errors.
  Screenshots: `docs/reports/design-office/phase3/`.

## Limitations (honest)
- **No live multi-agent run yet** (PD-48): the founder's subscription is shared; prompt quality of the practice
  notes, real rate-limit behaviour and real costs per ticket are unverified. Rate limits are detected from the
  agent's text ("rate limit", "usage limit", "overloaded", "429"); the CLI's exact wording should be confirmed live.
- Gage's size check is lexical (a size appears somewhere in the model); it does not measure features (that is CD-010
  ICD conformance). A part can carry the number and still be wrong.
- Fitz has no interfaces yet: parts without matching hole patterns or seats are placed beside the assembly ("mate by
  hand"); sub-assemblies are flattened in the final assembly.
- A run in flight may finish up to ~50 tokens past the budget (the minimum run budget).
- Program Pause does not interrupt a running turn (ticket pause / take over do).
- The runner lives in the web process (one process; no multi-worker coordination).

## What Phase 4 needs (ICD, placeholders, change requests)
1. **ICD into the brief and Gage**: `specialists.prompt` takes the ticket brief; add the ICD excerpt for the item's
   interfaces there, and replace `gage.brief_dimensions` / `model_numbers` with deterministic ICD conformance
   measurement (hole patterns, bores, faces against named numbers): `gage.deterministic` is the single place.
2. **Placeholders**: `platform_env.integrate` builds Fitz items from approved children; insert placeholder bodies for
   children that are not approved yet, mate by ICD names, and swap in the real part when its ticket is approved (the
   gage → fitz `ticket.handoff` is the trigger point).
3. **Change requests**: a part agent needs a way to raise a CR instead of silently changing an interface: a new
   ticket kind and a stage for Archie (orchestrator stages are plain `_<stage>` methods and `claimable` returns the
   stage), reopening affected tickets with `control(..., "reopen")`.
4. Nested assemblies (sub-assembly documents inside the final assembly) instead of flattening.
5. Estimate calibration (CD-015) can read real durations: tickets carry `run.started_at` and events carry the
   milestone times.

---

# Design Office — Phase 4 report (CD-010…CD-013 + nested sub-assemblies)

Branch `wip/office-phase4`, 2026-11-18. Interfaces first: after the brief gate Archie lays the program out (skeleton)
and names every interface between two parts with numbers (ICD). The engineer reviews the ICD at the "Architecture and
interfaces" gate; at approval the envelopes freeze, part tickets are released and Fitz assembles the program from
**placeholders** at once. Each part is built against its ICD excerpt, Gage **measures** its interface features on
the exact B-rep, and Fitz **swaps** it in for its placeholder (same instance, mates re-attached by interface name,
interference re-run). Interfaces change only through **change requests** that Archie decides.

## What happens now
1. **Brief gate** (unchanged): items and tickets open, and `interfaces.create` runs the layout engine
   (`office/icd.py`): the skeleton and a draft ICD. Gate "Architecture and interfaces" goes *pending*; Run is refused
   (409) and nothing is claimable until it is approved. Reviews inbox: "Review the interfaces (ICD v1) for …".
2. **Skeleton** (deterministic, `icd.build`): program frame = datums A (top face of the program base, Z = 0, +Z up),
   B (Y = 0), C (X = 0). Roles: *block* (machined / sheet / plastic: box L × W × H), *shaft* (turned with a shaft-like
   name: cylinder along Z through a block, bottom flush with it), *hub* (turned ring / cap / pulley: on a shaft of its
   sub-assembly, else bolted on a bolt circle), *gear* (pitch cylinder m·z × b, on a shaft). Blocks carry a row of
   stations on their top face (+X), grown to fit; neighbouring shafts whose gears mesh are spaced at exactly
   m(z1 + z2)/2. Sizes: Archie's `envelope` hint, else sizes written in the part description, else an assumption
   (marked "assumed" on the ICD page). Part frame = envelope centre, axes parallel to the program axes; copies (qty)
   are translations (up to 8 laid out).
3. **ICD**: `hole_pattern` (bolted joint: mounting face Z, flatness, position tolerance, n × Ø ISO 273 medium
   clearance at stated (X, Y), grid or PCD, fastener from a bolt in the same sub-assembly else by size),
   `shaft_bore` (Ø, ISO 286 fit H7/h6 or H7/k6 with limits, engagement, axis, flush end), `face` (seating plane),
   `gear_mesh` (module, teeth both sides, centre distance, face width, 20°). Every interface names its two items, its
   datums (A|B|C) and, per side, the local features in the part frame. Validity rules (`icd.problems`): ≥ 1 mm wall,
   ≥ 1 mm between holes, a rim on bores, gear bore inside the root, and **the ISO 7089 washers of neighbouring bolts
   must not overlap** (found in testing: Ø9 holes 13.6 mm apart take M8 bolts whose Ø16 washers clash).
4. **ICD page** (`Interfaces` tab): gate banner + Approve; skeleton card (csys, datums, axes, envelope, assumed
   envelopes); table (id, kind, key numbers, both sides' measured status, CRs); detail (all numbers, fit limits, each
   side's features and Gage's measured-vs-specified rows); edit at the gate (only the editable numbers per kind,
   validated, rebuilt deterministically); "Raise a change request" after approval; history (every version and field
   change) and all CRs.
5. **ICD approval**: the envelopes and the bolt patterns' edge distance, count and fastener freeze (overrides), then
   `platform_env.build_program_assembly` runs in the background: one placeholder per designed part
   (`assembly/placeholder.py` through the assembly worker op `placeholder`: the envelope solid with its interface
   holes / bores, cached as `h_<program>_<item>_<spec hash>`), one assembly document per sub-assembly, and the final
   assembly inserting them as **nested sub-assemblies**. Mates by interface name (`program_assembly.icd_mates`):
   bolted joint = coincident mounting faces + concentric on the two farthest holes; shaft in bore = concentric + flush
   ends; seating face = coincident; gear mesh = no mate (the skeleton spaces the shafts; Gage measures the teeth).
   Mates carry `icd` and `icd_role`. Then the exact interference check.
6. **Part agents** get `icd.excerpt` (plain lines + a `fw-icd` block) after the brief; the Studio chat still shows only
   the plain request. They may raise a CR with a `fw-change-request` block instead of changing an interface.
7. **Gage** (`gage.deterministic(sizes=False)` + `conformance.measure`): with an ICD, the lexical "the number appears
   somewhere" check is replaced by measurement on the part snapshot Fitz uses (`info.json`: holes / gear recognised by
   `recognize.py`; `refs.json`: exact planes and cylinders): hole Ø ±0.05 (or the ISO 286 zone for a fitted bore;
   nominal conforms) and position within tolerance, through; shaft Ø in its zone; face Z; gear teeth and module;
   bounding box inside the envelope. Findings read "IF-01 …: hole 1 specified Ø6.6 ±0.05 at (-16.80, -6.80), measured
   Ø6.000 at (-16.30, -6.80), 0.50 mm off position (±0.1)". Programs without an ICD keep the Phase 3 check.
8. **Fitz swap-in** (new orchestrator stage `fit`, status "fitting", holds a slot): after Gage approves, the real part
   replaces the placeholder in its sub-assembly document (same instance id, skeleton placement, ICD mates deleted and
   re-made by name, stacks through the old part removed); the final assembly re-syncs that sub-assembly, re-attaches
   the mates between sub-assemblies, solves and re-runs interference. Clashes involving the part → Changes requested
   on *that* ticket with the clash list as the agent's next message (2 rounds, then the engineer). Integrations wait
   while a child is still being fitted.
9. **Integration** with an ICD (`program_assembly.integrate`): the level's document already holds its real parts; Fitz
   fits the level's fasteners into its own bolted joints (ISO auto-fit through both parts, targets from the ICD
   positions) and puts other standard parts in a parts bin beside the program (no ICD interface for them yet); the
   final assembly fits the joints between sub-assemblies, re-syncs every sub-assembly and re-checks. A part reopened
   during an integration sends the integration back to the backlog.
10. **Change requests** (`interfaces.py`): raised by a part agent (parsed from its turn) or by the engineer (API / ICD
    page). Archie's deterministic rule rebuilds with the values and rejects if not buildable, if any envelope would
    change, if any item other than the two sides moves, if a gear mesh would break, or if a side is integrated.
    Archie-planned programs then get a one-shot AI note (`planner.run_cr_review`, metered, ≤ 60 tokens; simulated in
    dev) that may still reject, never accept. Accept → ICD v+1 with field-level history; tickets whose features
    changed reopen with the delta (a busy agent gets it after its step; Gage / Fitz hand a part back if the delta lands
    mid-review or mid-fit); integrations already done reopen; placeholders are regenerated (real parts of affected
    items go back to placeholders until re-approved). Reject → the requester gets the reason. Events `cr.raised`,
    `cr.accepted`, `cr.rejected`; CR cards in a lane above the board and on the ICD page.
11. **Live assembly view** (`Assembly` tab, `GET /programs/{pid}/assembly`): the final assembly in the shared
    `AssemblyViewer`: placeholders translucent orange, real parts solid, a part just swapped in drops into place with a
    green glow (static under reduced motion), clash volumes in red, exploded slider, hover tooltip with the item's
    ticket, column, progress, specialist and live line; links to each sub-assembly and the final assembly in Assembly
    Studio; "Rebuild" when the build failed or the add-on was missing.

## Nested sub-assemblies (approach)
Assembly Studio now holds assemblies inside assemblies by **copy with a link**: `assembly.service.insert_subassembly`
copies another document's instances, mates and fastener stacks into a group listed in `doc["subassemblies"]`
(`{id, name, assembly_id, rev, T}`), tagging instances (`sub`, `src`) and mates (`sub`). `sync_subassembly` re-copies
and keeps the parent's instance ids (so mates between sub-assemblies survive); the tree shows "Updated" when the
source revision differs. Chosen over live references because the solver, interference, BOM and viewer keep working on
flat instance lists, and a copy can't recurse. One level is kept (a sub-assembly of a sub-assembly is copied flat).
The STEP export writes sub-assembly → fastener stack → part (re-import verified, `subassemblies` count). API:
`POST /api/m/assembly/assemblies/{id}/subassemblies`, `…/{gid}/refresh`, `DELETE …/{gid}`; Insert dialog tab
"Sub-assembly"; tree sections with their stack count. Placeholders show an orange marker and render translucent in
Assembly Studio too; the BOM lists them as "Placeholder" with no mass.

## Files
New: `src/aicad/office/{icd,conformance,interfaces,program_assembly}.py`, `src/aicad/assembly/placeholder.py`,
`tests/test_office_icd.py`, `web/src/pages/app/office/{Interfaces,AssemblyView}.tsx`,
`web/src/pages/app/office/icd.test.ts`. Changed: `office/{service,orchestrator,platform_env,specialists,gage,planner,
fake_agents}.py`, `platform/routers/{office,mod_assembly}.py`, `assembly/{service,geometry,worker}.py`; web office
`types.ts`, `model.ts`, `ProgramPage.tsx`, `Board.tsx`, `Home.tsx`, `TicketDrawer.tsx`; assembly `viewer.ts`
(placeholder tone, `animateFit`, `instanceAt`), `Viewport.tsx`, `Tree.tsx`, `InsertDialog.tsx`, `Workspace.tsx`,
`types.ts`; `tests/test_office_orchestrator.py` (the helper approves the ICD; the Gage test uses ICD defects).

## Verification
- `tests/test_office_icd.py` (18 tests, simulated agents only; Archie, the real Gage note and the real CR note fail the
  test if reached): hand-checked layout (bracket at (-16, 0, 4), holes at (-32.8 | 0.8, ±6.8), M6 Ø6.6, edge distance
  13.2; spacer ring M3 Ø3.4 on PCD 13 → (40.6, 4.6) …); all 7 templates valid, gear reducer mesh m2 18/54 → a = 72 =
  the shafts' spacing; ISO 286 limits (H7 20.000/20.021, h6 19.987/20.000, k6 20.002/20.015, g6 19.980/19.993, p6 at
  Ø50 50.026/50.042); edits (frozen patterns keep positions; Ø9 → washer rule; Ø16 → overlapping holes);
  **conformance on fixture parts** (good bracket: 5 features pass, face Z -4.000; hole 1 at (-16.3, -6.8) Ø6.0 → the
  measured sentence above; 2 mm oversize → outside in X; shaft Ø20 / 19.99 pass, 20.05 fails h6; gear 18 teeth pass,
  19 fail); placeholders carry their holes at the ICD positions (bbox ±30 / ±20 / ±4); assembly from placeholders: 6
  mates tagged by interface, all satisfied, 0 interference, 2 nested sub-assemblies, STEP export with 2 sub-assembly
  nodes re-imported ok; Assembly Studio insert / refresh (same ids) / remove sub-assembly, self-insert 409;
  **swap-in keeps every mate** (same instance ids, same (interface, role) set, all real, 0 clashes, 4 M6 stacks in the
  joint), Gage sent the 0.5 mm-off bracket back once with the measured position; CR accepted (Ø6.6 → 7: v2, history,
  both sides reopened and re-measured at Ø7.000, placeholders regenerated, delta in the prompts); CR rejections (not
  buildable, washer overlap, Archie's note) and acceptance without the note; the rule as a unit (an integrated side
  refuses; a no-op change); tenant isolation of every new route and of the assembly documents.
- Phase 2/3 suites updated and passing (`test_office.py`, `test_office_orchestrator.py`).
- Vitest `office/icd.test.ts` (6): summaries, side / interface status, changed values, CR text and tone, swapped-in
  detection, live counts.
- Browser walkthrough: see SESSION_LOG (screenshots in `docs/reports/design-office/phase4/`).

## Limitations (honest)
- The skeleton is a conceptual layout (a row of stations on the program base, shafts vertical), not a product
  architecture. Archie's AI path can give envelopes, `mounts_on`, module and teeth; it can't yet place parts freely or
  rotate them (part frames are translations only).
- Interface kinds: bolted joints, shaft/bore fits, seating faces and gear meshes. No bearing seats, keys, slots,
  dowel pairs or sheet-metal flanges yet; standard parts other than bolts go to a parts bin.
- Conformance measures features along Z in the stated part frame; a correct part modelled in another frame fails
  (the ICD states the frame). Fits accept nominal models (CAD convention); tolerances are not otherwise modelled.
- Interface numbers are planning values for review, never a manufacturing claim; ISO 286 values come from the
  standard tables and are marked "verify".
- The office edits the program assembly documents without Assembly Studio's per-document lock; an engineer editing
  the same document by hand at that moment can lose an edit (the office re-attaches its own mates on the next swap).
- No live AI run of the ICD path (PD-48 still applies); the CR AI note is simulated in dev.

## What Phase 5 needs
1. **Drawings and release (CD-014)**: the ICD numbers (fits with limits, hole patterns with positions, datums A|B|C)
   are ready to become GD&T callouts for Ortho; `icd.side_features` gives each part's toleranced features.
2. **Better layouts**: let Archie propose station order and orientation (rotations in the part frame), multi-row
   packing, and interface kinds for bearings (seat Ø + shoulder), keys and dowels; Fitz's bearing seating can then
   follow the ICD.
3. **Calibration (CD-015)**: CR counts, Gage rounds per interface kind and clash rounds are timestamped events.
4. **Locking**: share Assembly Studio's per-document lock with the office and show "the office is updating this
   assembly" in Assembly Studio.
5. A live run (PD-48) to check that real part agents follow the `fw-icd` excerpt and raise sensible CRs.

---

# Design Office — Phase 5 report (CD-014, CD-015, DRW-014 + Phase 4 follow-ups)

Branch `wip/office-phase5`, 2026-11-18. After the final assembly is integrated, **Ortho** draws every part the
program makes and the assembly with its BOM and balloons, **Smithy** runs the Manufacturing Advisor on every part,
and one **Release program** action issues every part through its own release gate, tags it, and writes one pack.
Every ticket records its actual agent time; finished tickets **recalibrate** the estimating constants; a **Timeline**
tab shows planned against actual. The ICD gained **bearing seats, DIN 6885 keys, ISO 8734 dowels** and quarter-turn
part frames; Gage **matches a part's own frame** before measuring; the office and Assembly Studio **share one lock**
per assembly document. PD-55 holds the defaults.

## What happens now
1. **Deliverable tickets** (`service.add_deliverables`, orchestrator): when every part and integration ticket is
   integrated (program switch "make the deliverables", default on), two tickets open in the final-assembly lane:
   *Drawings* (Ortho) and *Manufacturing review* (Smithy), complexity = ⌈parts made / 2⌉, estimated with the program's
   calibrated rates. They are claimed like any ticket (stages `drawings` / `dfm`) and show on the board with the
   Ortho / Smithy avatars and progress per sheet ("Ortho is dimensioning sheet 2 of 5"). *complete* still means first
   article assembled; the orchestrator stops when the deliverables are done and the **Release gate goes pending**.
2. **Ortho** (`PlatformEnv.drawing`): per part made, the Drawing Studio sheet of the latest verified build. The ICD
   numbers the part carries (`deliverables.icd_spec`: bore / journal Ø with their ISO 286 class, clearance and dowel
   hole Ø, bearing seat Ø, bolt-circle PCD, keyway notes) are kept with the part (`drawings/spec.json`, so Drawing
   Studio regenerations and release issue copies keep them) and offered to the tagger as spec values. An ICD value is
   offered only when no model parameter already carries it (two names for one size would make both ambiguous); a
   model parameter of the same kind and value carries the fit instead. Fits print after the value ("Ø20 H7") unless
   the engineer wrote a tolerance. A sheet failing CHK-12 blocks the ticket for the engineer.
3. **Assembly drawing (DRW-014)** (`drawing/assembly_sheet.py`, drawing-worker op `assembly`): the final assembly
   placed instance by instance, exact HLR isometric view, A3 with the standard title block and NOT APPROVED banner,
   the program BOM as a table above the title block (22 lines on the sheet, the rest in the CSV), one balloon per BOM
   line with a leader to an instance; balloons sit on an ellipse around the view in the angular order of their
   anchors, pushed apart so they never overlap. SVG / PDF / DXF.
4. **Program BOM** (`deliverables.bom`): the final assembly as built (washers and nuts Fitz added included) merged
   with the plan: planned quantities win for planned parts (the parts bin holds at most four of a kind), rows map back
   to tickets, make = designed or company parts, buy = Toolbox parts with designation and standard, masses from
   nominal densities. CSV download.
5. **Smithy** (`PlatformEnv.dfm`): `analyse_workspace` on every part made (workspace shop profile, quantity
   max(10, ticket qty)); per part the best process, CHK-13 flag counts, top findings, unit cost; the summary adds a
   **relative cost index** (cheapest part = 1.0), each part's share of the batch and the parts needing attention.
   "Relative estimate, not a quote"; advisory, never a gate.
6. **Release program** (`POST /programs/{pid}/release`): refused (409, plain blocking list) until every part and
   integration ticket is integrated and both deliverables are done. Then per part made `routers/handoff.issue` (the
   per-part release gate, refactored out of the route and shared): frozen issue drawing + DFM report + pack at the
   part's next letter (or its current letter when that exact build was already issued) and a collaboration **tag**
   "`<KEY> Rev <letter>`" on main. Then the assembly STEP (exported under the shared lock), the assembly drawing
   stamped with the program letter, BOM CSV, DFM summary (CSV + JSON), the ICD (JSON), the `.fwprog` (refactored
   `mod_native.program_bytes`), README and a SHA-256 manifest, one zip under `<program>/releases/<rev>/pack.zip`. The
   Release gate turns approved; the program shows "Released · rev A".
7. **Calibration (CD-015)** (`office/calibration.py`): every stage the orchestrator runs is recorded on its ticket as a
   work segment (stage, agent instance, start, end); waits for capacity and blocked spells are segments too. When the
   office finishes a ticket, its actual agent time (work only) teaches its family's rate: observed = actual /
   complexity, clamped to ×2 / ÷2 of the rate, EMA α 0.3, bounded 0.05–60 min per unit; the update is kept and
   announced ("estimate.calibrated"). Learned once per ticket; hand-worked tickets never teach. Per organisation, two
   profiles: live and simulated (dev fake agents never move live constants). New plans snapshot the current rates.
8. **Timeline (CD-015)** (`office/timeline.py`, Timeline tab): planned schedule = greedy list scheduling of the
   estimates at the program's concurrency with critical-path priority; critical path = longest estimate chain; rows by
   ticket (planned outline, actual segments in the agent's colour, striped waits for capacity / for the engineer,
   error % per finished ticket) or lanes by agent instance; change-request markers; a "now" line while running. Below
   it the calibration panel (starting vs current rate per specialist, tickets learned from, latest updates in words,
   rolling mean absolute error over 5 tickets). The ticket drawer shows estimate vs actual and rounds per stage.
9. **New interface kinds** (`office/icd.py`):
   - *bearing_seat*: a shaft in a sub-assembly with a bearing part runs in Toolbox 62xx / 60xx bearings (the written
     designation when its bore fits, else the 62xx with the largest bore ≤ the shaft; an assumed shaft takes the
     bore); two seats (top + bottom counterbores, housing H7, depth B) when the plan has two bearings per shaft, a
     clearance Ø d + 2 between, journal k6; the housing grows to 2B + 4; hosts machined or moulded, never sheet. Fitz
     seats the bearings; Hex takes exactly the ICD's bearing.
   - *key*: a hub / gear whose name or sub-assembly says "key" gets a DIN 6885-1 form A key with keyways on both sides.
   - *dowel*: block joints in a sub-assembly with a dowel part get two ISO 8734 pins (Ø = bolt size, H7 holes both
     sides) clear of the bolts; Fitz places the pins.
   - *rotations*: a block's part frame can turn by quarter turns about Z (Archie's `rotate` hint or an override).
   - *coaxial stacks / spacing*: bearings in the host, hubs and gears on the shaft; station gaps grow with the parts
     (12 mm or a tenth of the larger); gear meshes still space shafts at exactly m(z1 + z2)/2.
   Placeholders carry every new feature (`placeholder.cut`; the simulated agents use the same code). Conformance
   measures *seat* (Ø in the fit zone, depth through its shoulder, two seats told apart by their circular edges) and
   *keyway* (width ±0.05, depth ±0.1); dowel holes are H7 holes.
10. **Frame-tolerant Gage** (`conformance.best_frame`): a part failing in the ICD frame is matched over the 24
    axis-aligned rotations with translations that pair its features with the ICD's; the best frame (ICD frame wins
    ties) is reported ("rotated 270° about Z, moved by (0, 0, −34.5) mm") and Fitz places the part through it.
11. **Shared lock** (`assembly/locks.py`): build, swap-in, integration, CR regeneration and the release export take
    Assembly Studio's per-document lock (loading inside it); Assembly Studio shows "The Design Office is updating this
    assembly right now" while the office holds it.

## Files
New: `src/aicad/office/{calibration,timeline,deliverables,frames}.py`, `src/aicad/assembly/locks.py`,
`src/aicad/drawing/assembly_sheet.py`, `tests/test_office_phase5.py`, web office `Deliverables.tsx`, `TimelineView.tsx`,
`timeline.ts` + `timeline.test.ts`. Changed: `office/{icd,conformance,orchestrator,service,estimates,roster,
platform_env,program_assembly,fake_agents,interfaces}.py`, `assembly/placeholder.py`, `drawing/{generate,worker}.py`,
routers `office`, `handoff`, `mod_drawings`, `mod_native`, `mod_assembly`; web office `types.ts`, `model.ts`, `api.ts`,
`ProgramPage.tsx`, `TicketDrawer.tsx`, `Board.tsx`, `Home.tsx`, `NewProgram.tsx`, `Interfaces.tsx`, `avatars.css`;
assembly `Workspace.tsx`, `types.ts`; `test_office_icd.py` (gear reducer: bearing seats + key),
`test_office_orchestrator.py` (helper runs without deliverables).

## Verification
- `tests/test_office_phase5.py` (8 tests, fake agents only): calibration EMA hand-computed (4 → 3.4, 4 → 5.2, floor,
  ceiling, 4 → 3.4 → 2.89, profiles, MAPE 50 / 35 / 26.7); timeline on a hand-computed DAG (A 0–10, B 0–20, C 10–15,
  E 15–19, D 20–26, F 26–29 at 2 agents; critical path B → D → F; waits, lanes, CR marker); BOM from fixture rows and
  the DFM summary (relative cost 2.5 / 1.0); new kinds laid out by hand (6204 seats Z −14..0 / −40..−26, key 6 × 6 × 18
  at Z 1..19, dowels at −24.4 / −7.6, rotated bracket); placeholders conform and seeded defects fail with measured
  values (seat Ø47.100 vs H7, keyway 5.000 wide, dowel hole Ø6.200); frame-tolerant measurement (turned + moved shaft
  passes with its transform, strict fails, a wrong part stays wrong); the shared lock; end to end deliverables +
  release (2 sheets passing CHK-12, assembly drawing with BOM and balloons, BOM, DFM, timeline lanes, calibration
  snapshotted into a new plan, rev A with both parts issued and tagged, pack contents and hashes verified).
- Phase 3 / 4 suites pass; vitest `office/timeline.test.ts` (7).
- Browser walkthrough: see SESSION_LOG (screenshots in `docs/reports/design-office/phase5/`).

## Limitations (honest)
- No live AI run yet (PD-48): calibration has only learned from simulated agents here, so the live constants are
  still the starting values; real agent times will move them.
- The layout is still a conceptual row on the program base with vertical shafts: bearing caps stay row stations (not
  coaxial over the seats: on tight gear centres they would collide), rotations are quarter turns about Z only, no
  horizontal shafts in side walls yet.
- Keys sit on the +X side; no circlips, shoulders other than bearing seats, or tolerance stack-ups.
- Assembly drawing: one isometric view, balloons point at an instance's bounding-box centre (can land behind another
  part in the view); BOM over 22 lines continues in the CSV only.
- The release pack issues each part's own release; a part whose drawing fails CHK-12 blocks the whole release.
- Frame fit uses axis-aligned rotations only; a part modelled at an arbitrary angle still fails (with a clear note).
- The shared lock is in memory (one web process, PD-53).

## What remains for the Design Office
1. A live multi-agent run (PD-48) and an API key before other users (PD-09); then real calibration.
2. Product architecture beyond a row: horizontal shafts in side walls, caps coaxial with bearings, multi-row packing,
   Archie placing parts freely.
3. Drawing depth: GD&T from the ICD datums (A|B|C) on part sheets, more assembly views and exploded view with
   balloons on visible faces.
4. Per-part design review gate (optional, PD-37) and program-level change notices after a release.
