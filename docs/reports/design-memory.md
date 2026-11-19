# Projects, project context and design memory (branch `wip/design-memory`)

Founder request (2026-11-19): "There must be context and memory system in the software suitably integrated … the
software learns about his habits and how he designs … parts might be related. So Agent must know if you are working
on same project. So there must be Project System, where a chat can be tied to a project and context of that project
is maintained."

## What was built

### 1. Projects that hold related parts
- **Naming.** In code and API a `Project` stays what it always was: one part (model, workspace, revisions, chat). The
  new container is `DesignProject` (`/api/design-projects`), shown to users as **Project**; the per-part object is
  now called **Part** in the UI where the two meet (Projects page, New part dialog, Dashboard). URLs are unchanged
  (`/app/projects/<part id>` is still the Studio); a project page is `/app/p/<id>`.
- **Data model (additive, no migration needed).** `design_projects` (name, purpose, notes, optional Design Office
  `program_id`), `design_project_parts` (part id is the primary key → a part is in at most one project),
  `design_project_decisions`. `create_all` adds them to an existing database; existing parts stay **unsorted** (no
  automatic "Unsorted" project row; the Projects page simply lists them as parts).
- **Design Office.** Every program appears as a project holding its tickets' parts (created once, on the first
  project list; a part the person already put elsewhere stays there). The project page links back to the program.
- **Flows.** Projects page: a Projects strip (New project, cards with part thumbnails), "Add to project… / Move to
  another project…" in each part's menu, a project chip on part cards and a Project column in the catalogue view.
  Project page: parts (with their mating features), **Decisions** (add / remove; source shown), **Notes**,
  **Activity** (part revisions + decisions), "New part" (creates the part inside the project and opens the Studio),
  "Add parts" (move existing parts in), rename / purpose, archive, delete (parts are kept). Studio: an indicator in
  the chat header ("Pump skid PS-1 · 2 parts · 🧠"); hover shows exactly what the agent knows; click opens the same
  list with "Open project" / "Add to project" / "Manage my memory". "Save as" keeps the copy in the same project.
- **Permissions.** A project is a workspace object: all members see it, viewers read only, engineers+ edit, delete
  = creator or workspace admin/owner. Guests (part grants only) never see projects. Each part keeps its own
  collaboration permissions: lists and the agent brief contain only the parts the person can read (a private part is
  counted as "private to others", never named or described); adding a part needs edit access to it; parts and
  projects of another workspace are 404.

### 2. Project context for the agent
`aicad.memory.context.turn_context(db, user, part, prompt)` is the **single** function that builds the text a turn
carries (merge-friendly). Called from `projects._memory_for_turn` right after `design_state` in `agent_chat`.
- **Brief** (≤ 2 000 characters): project name and how many other parts, purpose, the first 240 characters of the
  notes, active decisions, then one line per sibling part:
  `name (rev, material): size; mating features; key parameters`. Mating features come from geometric recognition
  when it is current for the build (`out/recognition.json`, refreshed for siblings before the turn, at most 6 s,
  no AI, no tokens), otherwise from a census of full cylindrical faces in `topo.json` (rounded corners / fillets are
  excluded by angular coverage), plus Hole Wizard holes from the model (standard size, type, fit). Parts the request
  names are described first when space is short; built parts before unbuilt; unbuilt parts are named only.
- **Preferences** (≤ 700 characters, ≤ 8 facts): pinned first, then stated / edited, then learned by evidence ×
  confidence; facts relevant to the request (fillet, hole, material… keywords) win the slots; written in a stable
  order. Wording tells the agent an explicit instruction always wins and not to mention the list.
- **Once per conversation.** The block is sent on a conversation's first turn and again only when its content
  changes (`.fw/context.json` digest; a new conversation always gets it). The chat shows the user's own words only;
  the change-notice "why" (`last_prompt`) strips the block.
- **Capturing decisions from chats** (deterministic, `aicad.memory.extract`): a sentence that addresses the whole
  project ("All fasteners M6 ISO 4762", "Use 6061-T6 for every part", "Across this project, tolerances to ISO
  2768-m") becomes a project decision with its category and source ("From a design chat on “Side rail”"); "always /
  never / I prefer" sentences become personal rules. Questions never count. The chat toasts "Added to the project's
  decisions" / "Remembered as your preference" with a Review link.

### 3. Personal design memory
`aicad.memory.learn` (deterministic counting, fixed thresholds). Observed only while "Learn from my work" is on and
never while an admin impersonates:
| Signal | Source | Fact (threshold) |
|---|---|---|
| Material | parts the person created (latest build) | "Usually specifies X" (≥ 2 parts, ≥ 50 %) |
| Fillet / chamfer sizes | hand features added (manual-feature commits) | "Typical hand fillet R2 mm" (≥ 3, ≥ 50 %) |
| Hole Wizard | type/size/fit of holes placed | "Most-used hole: M6 counterbored" (≥ 2, ≥ 50 %); "Clearance holes in the medium fit (ISO 273)" (≥ 2, ≥ 60 %) |
| Edits right after the agent | a hand feature or parameter edit whose parent revision is an agent build < 30 min old | "Adds fillets (R2) by hand after the agent builds: include them in the first build", "Often increases “Thickness” after the agent builds" (≥ 2) |
| Naming | last 12 part names | "Names parts with a code and number first, like “GB-001 Bracket”" (≥ 3, ≥ 50 %) |
| Stated rules | "always / never / I prefer" sentences | verbatim, origin "You said" |
| Units | Settings | "Works in inches" (only when inches) |

Each fact has a source in plain words, an evidence count, a strength (Strong / Likely / Emerging), an origin
(Learned / You said / Yours). **Settings → Memory**: two switches (learn from my work; use my preferences in the
agent), add a preference, edit (becomes yours: never overwritten), pin, delete (a deleted learned fact is a tombstone:
not learned again), share to a project (copies it into that project's decisions), "Forget everything" (this workspace;
parts made before it teach nothing). Private: rows are keyed by (person, workspace); another member sees none of it.

## Files
- New: `src/aicad/memory/{__init__,tables,facts,extract,learn,context,service}.py`,
  `src/aicad/platform/routers/design_projects.py`, `tests/test_design_memory.py`,
  `web/src/lib/designProjects.ts`, `web/src/components/memory/{ContextChip,MemoryPanel,ProjectPicker,ProjectStrip}.tsx`,
  `web/src/pages/app/DesignProject.tsx`.
- Shared files touched (small, listed for the merge): `platform/db.py` (register tables), `platform/app.py` (router),
  `routers/projects.py` (`design_project_id` on create; `design_project` on list/get; duplicate keeps the project;
  param edits observed; `_memory_for_turn` in `agent_chat`, response gains `remembered`), `routers/studio.py` (one
  `learn.observe_revision` call after a manual-feature snapshot), `routers/auth.py` (two allowed preference keys),
  `agent/session.py` (`last_prompt` also strips the two new blocks), `web/src/App.tsx` (route `p/:id`),
  `pages/app/Projects.tsx`, `Dashboard.tsx`, `Settings.tsx` (Memory tab, `?tab=`), `studio/Chat.tsx` (indicator +
  toasts), `components/NewProjectDialog.tsx` ("New part", optional project), `lib/types.ts`.
- **Merge note for `wip/pipeline-speed`:** the system prompt is untouched; everything is appended to the user turn
  by `_memory_for_turn` → `turn_context`. If the pipeline change moves turn assembly, move that one call.

## Punch-list rows (proposed; master to add)
| ID | Item | Status | Evidence |
|---|---|---|---|
| PLT-020 | Projects hold related parts (container, membership, Design Office mapping, flows) | Done | `test_existing_database_gains_memory_tables_parts_stay_unsorted`, `test_project_scoping_permissions_and_private_parts`, `test_design_office_program_maps_onto_a_project`; walkthrough shots 01–04, 07, 09 |
| AGT-020 | Project context in agent turns (sibling facts, decisions, notes; bounded; once per conversation) | Done | `test_three_part_project_brief_is_hand_checked_and_bounded` (hand values, ≤ 700-token bound with 27 siblings, replay prompt carries the facts, second turn doesn't resend); walkthrough replay matched |
| AGT-021 | Personal design memory (learned + stated preferences, Memory panel, privacy) | Done | `test_preferences_learned_from_a_recorded_sequence_of_edits`, `test_share_a_preference_to_a_project_and_chat_decisions`; shot 08 |
| AGT-022 | Project-level agent chat | Not done | Deferred (PD-79): notes + decisions + activity carry project context instead |

## Tests
`uv run pytest -q tests/test_design_memory.py` → 8 passed (≈ 90 s; builds the two demo parts for real). Covers:
statement capture; topo census vs hand values (plate 4× Ø6.6 on 100 × 60 grid centred, flange 6× Ø14 on Ø120 PCD,
bore Ø60.3, pocket R3 corners excluded) and the recognition path; migration of a pre-feature database; a 3-part
project brief checked line by line, its bound with 27 siblings, the replayed agent turn carrying it, the user's
chat bubble without it, no resend on turn 2, no internals in the indicator JSON; permissions (viewer, private part
hidden from others' brief and lists, edit needed to move a part, one project per part, delete rules, other
workspace 404); learning from a recorded edit sequence (3 agent builds each followed by an R2 fillet, 2 M6
counterbores, 1 thickness change), edit/pin/delete/tombstone, learning off records nothing, use off empties the
block, impersonation never learns, another member sees nothing, forget; sharing a fact to a project; chat-captured
decision with source label; Design Office program → project.
`ruff check src tests` clean; `tsc --noEmit` clean; `vite build` OK.

## Walkthrough (port 8796, replay agent, zero model calls)
Isolated app on 8796 (scratch data dir, God-mode superadmin, `FW_AGENT_REPLAY` cassette), puppeteer-core 25.18.1,
Chrome headless. Screenshots in `docs/reports/design-memory/`.

1. Seed the demo parts; Projects page shows the empty Projects strip above **Parts** (`01`).
2. New project "Pump skid PS-1" with a purpose → project page; Add parts → Demo · Mounting Plate and Demo · Pipe
   Flange; decision "All fasteners M6 ISO 4762" (category fastener, "Added by hand").
3. New part in this project → dialog "New part in Pump skid PS-1" (`02`) → Studio opens on "Cover"; the chat header
   shows "Pump skid PS-1 · 2 parts".
4. Chat: "Make the cover for the mounting plate. …". The replay cassette has one turn whose `match` regex requires
   `[Project context: this part (“Cover”) belongs to the project “Pump skid PS-1”` … `All fasteners M6 ISO 4762` …
   `Demo · Mounting Plate (rev 1, Aluminium 6061-T6): 120 × 80 × 10 mm; 4× Ø6.6 … 100 × 60 grid`, and a fallback
   turn saying the context was missing. **Matched** (`04`): the reply came back in 7.5 s (includes the ≤ 6 s
   sibling recognition refresh). The user bubble shows only the typed words.
5. The sentence "All fasteners in this project are ISO 4762 socket head screws" was captured as a project decision
   (toast "Added to the project's decisions" with Review; listed on the project page as "From a design chat on
   “Cover”"); an earlier "Always deburr outside edges 0.5 mm" became a personal rule (toast "Remembered as your
   preference"; Settings → Memory shows it as "You said … on “Cover”", `06`).
6. Hovering the chip lists what the agent knows: both siblings with size, material, hole pattern / PCD / bore,
   key parameters, the decisions and the preference (`03`).
7. Project page after the chat (`05`): 3 parts, 2 built; under each built part its mating features, now from
   recognition ("4× Ø6.6 thru on 100 × 60 grid, axis Z centred (X0, Y0)"); Decisions, Notes, Activity.
8. Projects page (`07`): project card, project chips on the part cards.

Console / page errors: **0** in both passes. One harness note: under heavy machine load the God-mode seed builds hit
the 180 s worker timeout for 3 of 4 demos in the first pass (the indicator then honestly said "not built yet" and
the cassette did not match); I built those demos directly with the runner and re-ran the chat on a new
conversation. Not caused by this branch.
Hand check of the numbers: plate 120 × 80 × 10 mm, holes 10 mm in from each edge → (120 − 20) × (80 − 20) =
100 × 60 grid, Ø6.6 = M6 medium clearance (ISO 273); flange 6 × Ø14 on Ø120 PCD, bore Ø60.3, thickness 16 + 2.

## Token cost (measured)
The block for "Cover" in the walkthrough (2 built siblings, 2 decisions, 1 preference) is **1 352 characters ≈ 340
tokens** (4 chars/token; Ø and × may tokenise a little worse: call it ≤ 450). Hard ceiling by construction: 2 000 +
700 characters ≈ 700 tokens, tested with 27 siblings.

- Sent on the first turn of a conversation only (and when it changes). At the Opus-class input price in
  `agent/pricing.py` ($4–5 per million) that is **≈ $0.002 per new conversation**, i.e. **0.2 Formwright tokens**
  (1 token = $0.01). On later turns it sits in the cached conversation (cache read $0.20–0.50 / M): ≈ $0.0001 per turn.
- Recognition of siblings is geometric (warm worker, no model call, 0 tokens).
- An AI summarisation step for chat → decisions would cost about 1.5 k input + 200 output tokens per message on a
  small model (≈ $0.002–0.003, the same as the whole brief, on *every* message) and adds a model call to every
  send. The deterministic extraction captured every statement in the tests and the walkthrough at 0 tokens, so the AI
  step was not built (PD-78).

## Known limits
- Accepting an agent-proposed edit in the PropertyManager (fw-edit card → OK) is counted as a hand edit right after
  the agent (it is a manual-feature commit on top of an agent revision). Accepted vs rejected suggestions are not
  yet told apart; undo of an agent build is not yet recorded.
- The topo fallback says "round" (it can't tell a hole from a boss); recognition, refreshed before each turn,
  says thru / bore / boss. A cold worker may need longer than the 6 s wait on a first turn; then the census is used
  and recognition lands for the next conversation.
- The rest of the app still says "project" where it means a part (Studio menus, notifications, some module pages).
  Changed only where the two concepts meet.
- No project-level agent chat (PD-79). No team-level memory (PD-77).
- God-mode seed-demo builds can exceed the 180 s worker timeout when the machine is saturated (seen during the
  walkthrough; not caused by this branch).

## Parked decisions (defaults used; renumber if PD-73+ are taken)
| PD | Decision | Default used | Revisit when |
|---|---|---|---|
| PD-73 | Naming of the container | User-facing "Project" = group of related parts; the per-part object is "Part" in the UI; code/API keep `Project` = part, container = `DesignProject` at `/api/design-projects`, page `/app/p/<id>`. Existing parts stay unsorted (no auto "Unsorted" project). | Founder prefers another word (e.g. "Assembly", "Job") or wants an auto Unsorted bucket |
| PD-74 | Project access | Workspace-wide object: members see, viewers read, engineers+ edit, creator or admin deletes (parts kept). Parts keep their own permissions; the agent brief and lists show only parts the person can read; private ones are counted, never named. Guests see no projects. | Teams want team-owned projects or project-level grants |
| PD-75 | What is learned, retention | Materials, hand fillet/chamfer sizes, Hole Wizard type/size/fit, hand edits within 30 min after an agent build, part naming, "always/never/I prefer" statements; thresholds as in the table above; last 400 observations per person and workspace; no time expiry; deleted learned facts are tombstoned for good; admins impersonating never train it. | Founder wants more signals (drawing standards, accepted suggestions), expiry, or different thresholds |
| PD-76 | Captured chat statements go live immediately | Project decisions and personal rules captured from chat are active at once, shown with their source, announced in a toast with Review, removable in one click (not a "proposed, approve first" queue). Only explicit wording is captured. | False captures show up in practice |
| PD-77 | Sharing memory | Personal memory is private to (person, workspace). Sharing copies one fact into a project's decisions. No team-wide memory. | Teams ask for shared house style |
| PD-78 | Prompt budget and AI summarising | Project brief ≤ 2 000 chars, preferences ≤ 700 chars (≈ ≤ 700 model tokens together), sent once per conversation and on change; deterministic extraction only, no AI summarisation step (measured: not worth its tokens, see Token cost). | Projects grow beyond ~15 built parts, or decisions need summarising from long chats |
| PD-79 | Project-level chat | Deferred: project Notes (editable, first 240 chars go to the agent) + Decisions + Activity carry the running context; no separate project agent chat (it would spend tokens without a model to change). | Founder wants to plan a whole project in one conversation (Archie in Design Office already does this for programs) |
