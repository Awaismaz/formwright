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
