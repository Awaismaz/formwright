# Project context (portable memory)

This file carries the working context that otherwise lives only in a Claude Code session, so work can continue
from any machine. Keep it current at the end of every session (see `CLAUDE.md`).

## Founder and way of working
- Founder: mechanical design engineer building Formwright as a venture; validated the concept with Claude Code
  and insists the in-app agent has Claude Code-level agentic power (Claude Agent SDK, not plain chat).
- Prefers autonomy: "make the best judgement; if a decision is truly mine, park it and keep building".
- Wants a production-grade, user-centric product (customer journey, guided tours, billing, God mode for demos),
  then module-by-module depth. **Current priority: mature the Design Studio before other modules.**
- Familiar with SOLIDWORKS: expects native CAD conventions (CommandManager, PropertyManager, feature tree,
  orthographic views, sketch relations, Toolbox).
- Does not want backend internals visible to users (no "Reading model.py"); plain engineering language only.
- Wants everything (code, plans, feature list, context) in the GitHub repo and docs updated every session.
- Imported/foreign geometry must stay EXACT and editable ("Imported blank" + resolved features); recognition should be
  AI-driven (look at the part), not a brittle geometric recogniser that drops faces. Prefers compact UI with
  collapsible panels (feature panel left, agent right, collapsible command bar, no wasted header space).

## Standing decisions (details in docs/DECISIONS.md)
- Landing page (founder decision 2026-11-18): launch-state marketing — present features as they will be at market launch, no 'coming soon'/'preview' labels; the in-app product keeps strict honesty labels. Before public launch: legal review of claims, and official vendor logos only with permission (own icon tiles until then; drop-in slot `web/public/landing/logos/`).
- Name/brand: **Formwright** (trademark unchecked, PD-01). SOLIDWORKS-like blue/grey theme (docs/BRAND.md).
- Stack: Python 3.12 (uv), FastAPI, SQLAlchemy (SQLite now), build123d 0.13 / OCP 7.9 (OCCT), React 18 + TS +
  Vite + Tailwind + Radix + TanStack Query + three.js. Agent: Claude Agent SDK (`aicad.agent.session`).
- Dev-only agent auth via the founder's Claude Code subscription login (no API charges in development).
- Tokens: plans include tokens, top-ups/add-ons purchasable; God-mode accounts have unlimited tokens.
- Founder login is a superadmin with God mode (credentials in `data/ADMIN_CREDENTIALS.txt`, never committed).
- Toolbox generators are deterministic and versioned (`aicad/toolbox.py`, `VERSION`); bump the version on any
  geometry change so old models stay reproducible.

- Installable web app (UX-022): build-time service worker from `web/pwa/` (never caches `/api`); bump nothing by hand,
  the build id follows the built files. Icons: `scripts/pwa_icons.py`. Anything needing locally installed software
  goes inside `components/DesktopOnly.tsx`. Compact layouts: `lib/media.ts` (PHONE < 768, COMPACT < 1024).

## Architecture in one screen
- Formwright files (IO-020…025): every module saves/opens its work as a signed, checksummed zip (`.fwpart .fwasm .fwdrw
  .fwprog .fwrender .fwmfg .fwcalc .fwprint .fwread`), one container in `src/aicad/native/`, spec `docs/FORMATS.md`.
  Imports are untrusted input; parts are rebuilt and verified against the exported fingerprint.
- `src/aicad/llm/` — **every model call goes through `LLMProvider`** (AGT-001): `llm.complete(CallRequest(role=...))`
  for single calls (text, JSON schema, images, metering) and `get_provider("design_agent").agent_client(opts)` for the
  Studio session. Providers `claude-sdk` (default), `anthropic-api` (off; own key), `stub`, `replay` (dev only); routing
  `FW_LLM_PROVIDERS` (server-only, never in the UI). Never import `claude_agent_sdk.query` / `anthropic` / `openai`
  elsewhere: `tests/test_llm_providers.py` fails on it. New call site = new role in `llm/base.py` `ROLES`.
- `src/aicad/agent/` — `session.py` (Agent SDK session, event scrubbing, `fw-questions` choice blocks),
  `prompt.py` (agent instructions), `runner.py` (build + checks CHK-02..09, fast path, exports, determinism),
  `worker.py` (warm per-org build worker).
- `src/aicad/fw.py` — helper lib used by model scripts: feature provenance, selections, manual features
  (fillet, chamfer, hole/patterns, extrude, sketch profiles, shell, mirror), imported STEP reference.
- `src/aicad/topo.py` exact B-rep topology for the viewer; `recognize.py` STEP feature recognition + parametric
  draft; `toolbox.py` standard components; `checks.py` deterministic checks.
- `src/aicad/platform/` — FastAPI app, models, routers (`projects`, `studio` = manual features/materials/compare,
  `library` = Toolbox/STEP import/recognition, auth, billing, admin, god, team, journey).
- `src/aicad/platform/collab/` — collaboration: teams, **one permission module** (`require_project`, level by HTTP
  method unless given), sharing/guests/read-only links, per-project branches (sibling copy-on-write workspaces, the
  active branch per person via a cookie that `workspace_for` resolves), merge requests (3-way merge of parameters,
  manual features and source). New project endpoints must go through `projects._project(ctx, id, need)`; new project
  lists through `permissions.visible`. Details: docs/ARCHITECTURE.md §6.
- `web/src/pages/app/ProjectStudio.tsx` — Studio shell; `studio/` CommandManager, FeatureManager (PropertyManager),
  SketchEditor (2D constraint sketcher, solver in `web/src/sketch/model.ts`), Chat, Panels, Toolbox, StepImport.
  Viewer engine in `web/src/viewer/` (Z-up, ortho default, B-rep edges, snapping, section caps).

## Machine notes (founder's Windows workstation)
- `unset VIRTUAL_ENV` before `uv run`. Git Bash heredocs with quotes/backticks often break: write patch scripts
  to a file and run them. `gh` CLI is not installed; plain `git push` works (Git Credential Manager).
- Repo: https://github.com/Awaismaz/formwright (branch `main`).
- SOLIDWORKS 2025, Creo 11 and Blender are installed locally (useful for manual cross-checks of exported STEP).
- Puppeteer e2e: Radix menus/tabs need real pointer events. Recipe + template: `.claude/skills/studio-e2e/`.
- Second workstation (repo at `D:\AI CAD\formwright`, Windows 11 build 26300, 2026-11-16): fresh clone with **no uv, no
  `.venv`, no `web/node_modules`** yet; Node, Git, Chrome and Edge are present. Run `dev-setup` before the gate.
- Second workstation hardware: Xeon W-2135, 12 logical CPUs, 32 GB RAM, so keep parallel CAD-building agents at
  about 5 or fewer. Blender 5.3 is installed (`C:/Program Files/Blender Foundation/Blender 5.3`; Mesh Studio). uv installed 2026-11-16 (`~/.local/bin`).
- Orchestration (founder request 2026-11-16): the main session is the master; module agents work in git worktrees
  `D:\AI CAD\fw-worktrees\<module>` (branch `module/<module>`), follow `docs/AGENT_BRIEF.md`, report in
  `docs/reports/`; the master merges. Claude's built-in worktree isolation fails here (d:\ vs D:\ case), so create
  worktrees manually with `git worktree add`.
- Founder God-mode login exists in this machine's `data/` (see `data/ADMIN_CREDENTIALS.txt`); the app runs on 8765.
- Workflow recipes live in project skills (`.claude/skills/`, listed in `CLAUDE.md`); `.gitignore` tracks only
  `.claude/skills/` (local settings stay ignored).

## Module status (2026-11-17, after the audit)
All eight modules are Live: Design Studio, Drawing Studio, Image & Drawing to CAD, Assembly Studio, Manufacturing
Advisor, Engineering Advisor, 3D Print Prep, Mesh Studio (Blender render studio). AI Render Studio (MSH-013) is Live/Beta on the customer's own OpenAI
key (BYO; key encrypted with `FW_SECRET_KEY`; `FW_AI_RENDER_FAKE=1` simulates OpenAI in development only). Downstream modules open on the
current part from the Studio's **Make** tab (with status/lock); input modules (From Drawing) from the **Library** tab.

**Platform differentiators:**
- similar-part search
- change notices
- design variants
- release gate "Issue Rev A" (the single staleness rule for every module output, frozen into the shop handoff pack)
- fix-it loop from findings
- Hole Wizard
- repair-don't-block
- typed commands
- fasten-two-parts
- drawing round-trip check
- run budget with a live cost meter

**A full product audit ran on 2026-11-17:** `docs/reports/AUDIT_2026-11-17.md`, with area reports and `*-fixes.md` status
files in `docs/reports/audit/`. Its remaining "partly" and "not done" items are the natural next work.

**Token economics (measured):**
- a new part costs about 260-280 tokens when the agent starts cold, about 45 when it is warm
- a change costs about 26
- the trial is 1,000 tokens
- plan allowances are the founder's call (PD-26)

Trial workspaces can use every Live module.

**Testing note:** with several agents running, a few slow tests (mesh render, change notice, param edit) can fail
under load and pass alone. Run the full suite on a quiet machine before deciding a failure is real.

## Founder rule: fix causes and workflows (2026-11-19)

When the founder reports a problem in the app, never fix the instance (their program or data). Find what generated the state and which workflow has no way out, fix that in the product, and make sure a user can recover inside the app on their own: the system corrects itself, or they tell Archie (in-program chat) and Archie proposes the fix. Claude is not available to users in production. Reproduce on temp copies only.

## Founder rule: fast iterations, no full gate per ship (2026-11-19)

Pre-production: don't run the full suite (pytest, npm test, vite build) before every commit/push. Run only quick,
targeted tests for touched code; build web/dist only when the served SPA must change. This overrides the
"run pytest… before the final commit" step in CLAUDE.md until the founder says otherwise.

## Founder rule: parts are checked, assemblies are placed (2026-11-19, PD-71)

Assembling must be quicker than modelling. Parts are quality-checked (Gage, swap-in); Design Office assembly steps place
fasteners straight from the ICD and do no geometry checking; the whole-program clash check is advisory, runs after the
final assembly in the background and never blocks. Assembly checks go through the pair cache (ASM-023, PD-70).

## Founder rule: agents see and speak; Design and Assembly are the core (2026-11-19 evening)

- In-app agents (Archie, Fitz, Gage...) look at assemblies the way an engineer does (rendered pictures, ASM-024) and tell
  the user in plain words, as it happens, when something is wrong, with a fix to apply. A gate must never pass silently
  on a degenerate result (zero interfaces, a row of parts on the floor). Vision is advisory; measurements decide (PD-73).
- Design Studio and Assembly must be state of the art; speed matters a lot ("I can't stand such a slow system"):
  measure, then optimise the build / check / agent pipelines (changes there are allowed). Prefer deterministic no-AI
  paths where the structure allows (e.g. ICD-defined parts).
- Standing assembly test case: 1:3 spur gear pair (m2, 20/60 teeth), Ø20 shafts, four 6204 bearings, no housing.

## Founder direction: architecture v2 and model routing (2026-11-19 night)

"Start and complete everything": AI at the edges (intent in, explanations out), determinism in the middle. One typed
design graph is the source of truth for Studio and Office; layout comes from connection semantics; parts come from
parametric generators where they exist; verification is deterministic with cross-checks; process depth matches job
size; AI image generation is NOT used in planning (a dimensioned preview from the graph instead). Model routing by job
size: Opus orchestrates, Sonnet does smaller design jobs, Haiku parses/matches/checks (PD-82). Ordered work: WORKLIST
41 to 48. Machine limit: at most two module agents at once.

## Founder rules added 2026-11-20

- **Push on every build:** every merged and verified change goes to `origin main` straight away (already the push
  rule; the founder repeated it: "keep pushing updates on every build").
- **No long dashes anywhere** (em dash, en dash as punctuation): UI copy, agent messages, docs, commits, replies.
  `web/src/noLongDashes.test.ts` guards the public site; extend it to the whole app when touching copy.
- **Machine limit:** at most two module agents at once on the founder's PC; reap worker processes after test runs
  (CAD workers are now reaped per test module and killed at exit). Port 8765 is the founder's app; never test on it.
- **Permissions:** this project runs Claude Code in bypass-permissions mode (`.claude/settings.local.json`, local
  only, not in git). Subagents may still hit the auto-mode classifier.
- **Catalogues and standards:** the founder will decide later; the full tiered list is WORKLIST 55 (backlog).
- **New modules later:** Motion Studio (WORKLIST 52) and Simulation / basic static FEA (53), only after the core
  (Design, Office, Assembly) is refined.
- **Naming:** formwright domain unavailable. Candidates the founder liked: MechBrains (fits his "-brains" family:
  meetbrains.com, healthbrains.com; parent company Coding the Brains), KineCAD (all TLDs looked free), Machinica,
  Mechanicum, Kinematica. Undecided; rename everything in one pass once he picks.

## Continue on another PC (handoff 2026-11-20)

1. `git pull` on main, then follow `.claude/skills/dev-setup` (uv venv from uv.lock, `cd web && npm ci`).
2. `data/` is NOT in git: the founder's projects, Design Office programs (Gear Reducer, Test 5, Shaft Gear, TEST
   Project, ...) and `data/ADMIN_CREDENTIALS.txt` exist only on the original workstation. Copy the folder privately
   if needed (it holds credentials), or start fresh (God mode, seed demo).
3. Start the app with the design graph on, as the founder runs it: `FW_DESIGN_GRAPH=1 uv run aicad app --no-browser
   --port 8765` (after `unset VIRTUAL_ENV`).
4. Work in flight on the original PC (local worktrees under `D:/AI CAD/fw-worktrees/`): `wip/connection-layout`
   (WORKLIST 44, also golden findings F1-F6 and the TEST Project table layout), `wip/program-revision` (54, will repair
   the founder's TEST Project), `wip/generators` (45/48, paused at 3886b47). Their committed heads are pushed to
   origin as `wip/*` branches for safety; the agents' reports land in `docs/reports/` when they finish.
5. Next in order: 44 and 54 merge, then 51 (Assembly Studio chat), 45/48 resume, 50 (hybrid master model), golden
   suite to 9/9, then 52 and 53. Each merge: targeted tests (1-2 files per run), ruff, tsc, vite build, push.
6. Measure with `uv run aicad golden --simulated` (and `--env FW_DESIGN_GRAPH=1`); dashboard under Admin > Golden suite.

## Where things stand (handoff, updated 2026-11-20)

**Latest (2026-11-20):** WORKLIST 41, 42, 43 (flag), 46, 49 merged and pushed, plus the recognition fix, gearbox caps,
Toolbox keys/rings, agent cost, the site revamp, smooth involute gears and the sidebar fix (SESSION_LOG 2026-11-20;
PUNCH_LIST CD-041..045, DS-041/042, EVAL-009, WEB-010; DECISIONS PD-88..166 index). In flight: 44, 54; paused: 45/48.

**Earlier (2026-11-19 night):** batch WORKLIST 36-39 merged and pushed (CD-040, ASM-024/025, DS-038/039/040;
PD-73..87; SESSION_LOG 2026-11-19 (i)). In flight: live Design Office run of the test case (`wip/live-gear`) and
ICD-defined parts without the LLM (`wip/office-direct`). Open follow-ups: WORKLIST 35 and 40.

**Earlier (2026-11-19 close):** main at the assembly solver patch (ASM-023) after CD-026…CD-039. Founder's F1 program
is complete to the release gate (final assembly, 29 part sheets + assembly drawing, manufacturing review); 2 sheets
flagged for a Drawing Studio touch-up (FC-14, FC-20). Open follow-ups are WORKLIST row 35.

**Read first on a new machine:** this section, `docs/plans/WORKLIST.md` (ordered work list with status),
the newest entries of `docs/SESSION_LOG.md`, and the parked decisions table in `docs/DECISIONS.md` (PD-35…PD-72).

**Live on main (merged + pushed today):** punch-list reconciliation; Design Office plan + phase 2 (programs, Archie
planner, Jira board, roll-up/ETA, roster, 11 animated agent avatars); smart assembly (Hex picks Toolbox/own parts,
Fitz places + mates); chat shop-floor status animation; Discuss/Build chat modes; brief approval gate, self-review,
record/replay agent, 20-prompt benchmark harness; sidebar fixes; animated landing page (v1); `/why` ROI page;
AI Render Studio (OpenAI images with the user's own key — not yet run live); 2D drafting without a model; Mesh
fixes (fail-fast output paths, degenerate triangles).

**Also merged later on 2026-11-18:** Design Office phases 3-4 (orchestrator with Hex/specialists/Gage/Fitz, budgets;
ICD + conformance measurement, placeholders + swap-in, change requests, live program assembly, nested
sub-assemblies); landing hero v2 (planetary gearbox story, CAD tools tiles, phone + tablet); installable PWA +
mobile/tablet pass; Formwright native files in every module (.fwpart/.fwasm/.fwdrw/.fwprog/.fwrender/.fwmfg/
.fwcalc/.fwprint/.fwread, opened by the installed app); collaboration (teams, permissions, sharing, presence,
comments, branches + merge requests). DB backup taken before collaboration went live: `data/backups/` (local only).

**Design Office phase 5 merged + pushed (2026-11-18 night):** program deliverables (Ortho part + assembly drawings
with BOM/balloons, Smithy DFM summary, program BOM, "Release program" → tagged parts + release pack), estimate
calibration (EMA per family, simulated runs in their own profile) + Timeline tab, bearing-seat/key/dowel interfaces,
frame-tolerant Gage (24 axis rotations), shared assembly lock (in-memory, single server — PD-53). Report:
docs/reports/design-office.md Phase 5; defaults PD-55. Drawing Studio VERSION 1.1.3.

**Batch 23-25 merged + pushed (2026-11-18 night):** drawing depth (threads, detail views, GD&T only from explicit
input / ICD, STEP→drawing; PD-58), engineering hygiene (IO matrix, SBOM, run record, repeatability; PD-56), studio
intelligence (agent fills the PropertyManager, change-impact preview, datasheet pack; PD-57). Full suite 623 passed.
**Batch 26-28 merged + pushed (2026-11-19):** sheet metal (CAD-026; PD-60), Design Office phase 6 (gearbox layout,
review gate, change notices / Rev B, motion check, faster clash screening; PD-61), agent platform (LLM provider layer,
Export for SOLIDWORKS, Blender IO; PD-59). Parked decisions now PD-35…PD-63. Batch 29-30 merged 2026-11-19; nothing in flight on branches.
**Quality fixtures (merged 2026-11-19):** golden assembly fixtures FX-04/05/06 in `src/aicad/fixtures/` + `specs/fixtures/` (regenerate definitions with `uv run python -m aicad.fixtures --write`; expected values are hand formulas only), advisory render similarity `eval/render_similarity.py` logged in bench / repeat / run record, never gating (PD-62).
**Studio follow-ups (merged 2026-11-19, WORKLIST 30, PD-63):** sheet metal: automatic corner relief + closed/open corners where flanges on adjacent edges meet (`Bend.ext` shortens the earlier bend), cuts through bends unbent into the flat (neutral-surface trace), jog (`sm_jog` / `fw.jog`); fw-edit: extrude depth, pattern count/spacing, several edits per block (one PM step each); impact preview also for tree suppress/delete/move and Ctrl+K commands (`trial_source` kinds suppress / delete / reorder / design_* / sequence). Report: docs/reports/studio-followups/.

**Design Office phase 6 (merged 2026-11-19):** gearbox-like programs lay their shafts along +Y in the housing's side walls (seat per wall, caps coaxial over the seats with tapped holes, cover = lid, gear cavity); ICD features along X/Y carry `ax` and are written in a canonical frame (`office/frames.CANON`) so the Z code (placeholders, Gage, Fitz, GD&T) is reused; optional per-part review gate (`review_gate`); change notices after release (`office/ecn.py`, Rev B pack + diff, packs write-once); motion range check (ASM-011, `assembly/motion.py`, program joints from the ICD); faster interference / clearance screening (ASM-022). Report: docs/reports/design-office.md Phase 6; defaults PD-61.
**Engineering hygiene (merged 2026-11-18, 63a9887):** every design-agent turn writes a server-side run record `.fw/runs/<id>/run.json` (AGT-009; super-admin API only, prompt hashed + redacted by default, PD-56); licence audit + CycloneDX SBOMs in `docs/legal/` (regenerate with `uv run python scripts/sbom.py` after any dependency change; `tests/test_sbom.py` fails on a stale SBOM or an un-allow-listed copyleft licence); IO round-trip matrix `docs/reports/io-roundtrip.md`; `aicad repeat` repeatability harness (fake/replay by default).
**Studio intelligence (merged 2026-11-18):** DS-035 the design agent answers a small edit with a
```fw-edit``` block (`agent/edits.py`) that opens the real PropertyManager pre-filled with the targets highlighted; the user
presses OK (normal manual-feature / parameter path, no agent code). ASM-018 every Studio edit on a part used in an
assembly is previewed first (`POST /api/m/assembly/impact/{project}`: trial rebuild in the warm worker + in-memory
assembly copies; broken mates, moves, refits, new clashes; nothing committed); Mesh Studio has a per-part datasheet
shot list that goes stale on revision and re-renders (queues) in one click. Defaults PD-57.

**Sheet metal (merged 2026-11-18, CAD-026 / MFG-011):** `src/aicad/sheetmetal.py` keeps a panel + bend model next to the solid; Studio ops `sm_base` / `sm_flange` / `sm_hem`, helpers `fw.base_flange/edge_flange/hem`; every build writes `out/flat.topo.json|dxf|json` and `status.sheet_metal`; Drawing Studio adds a flat-pattern sheet (`flat_sheet.*`), the Manufacturing Advisor reads the model (SHM-03..05). Defaults PD-60.

**Next:** live (non-simulated) agent runs once the founder approves PD-41/PD-48 token use; the
remaining backlog in `docs/PUNCH_LIST.md`. Native CAD bridge (SOLIDWORKS pilot) stays in backlog by founder decision.

**Process rules (founder):** push after every merge; update CONTEXT/PUNCH_LIST/SESSION_LOG/DECISIONS/WORKLIST at
the end of each batch; when away, no questions — park decisions as PD rows; parallel agents in git worktrees
(the built-in worktree isolation fails on this machine because of path casing — create worktrees manually with
`git worktree add -b wip/<name> ../fw-wt/<name> main`).
