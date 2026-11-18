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
