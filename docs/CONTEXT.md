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
- Name/brand: **Formwright** (trademark unchecked, PD-01). SOLIDWORKS-like blue/grey theme (docs/BRAND.md).
- Stack: Python 3.12 (uv), FastAPI, SQLAlchemy (SQLite now), build123d 0.13 / OCP 7.9 (OCCT), React 18 + TS +
  Vite + Tailwind + Radix + TanStack Query + three.js. Agent: Claude Agent SDK (`aicad.agent.session`).
- Dev-only agent auth via the founder's Claude Code subscription login (no API charges in development).
- Tokens: plans include tokens, top-ups/add-ons purchasable; God-mode accounts have unlimited tokens.
- Founder login is a superadmin with God mode (credentials in `data/ADMIN_CREDENTIALS.txt`, never committed).
- Toolbox generators are deterministic and versioned (`aicad/toolbox.py`, `VERSION`); bump the version on any
  geometry change so old models stay reproducible.

## Architecture in one screen
- `src/aicad/agent/` — `session.py` (Agent SDK session, event scrubbing, `fw-questions` choice blocks),
  `prompt.py` (agent instructions), `runner.py` (build + checks CHK-02..09, fast path, exports, determinism),
  `worker.py` (warm per-org build worker).
- `src/aicad/fw.py` — helper lib used by model scripts: feature provenance, selections, manual features
  (fillet, chamfer, hole/patterns, extrude, sketch profiles, shell, mirror), imported STEP reference.
- `src/aicad/topo.py` exact B-rep topology for the viewer; `recognize.py` STEP feature recognition + parametric
  draft; `toolbox.py` standard components; `checks.py` deterministic checks.
- `src/aicad/platform/` — FastAPI app, models, routers (`projects`, `studio` = manual features/materials/compare,
  `library` = Toolbox/STEP import/recognition, auth, billing, admin, god, team, journey).
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
  about 5 or fewer. Blender is not installed here. uv installed 2026-11-16 (`~/.local/bin`).
- Orchestration (founder request 2026-11-16): the main session is the master; module agents work in git worktrees
  `D:\AI CAD\fw-worktrees\<module>` (branch `module/<module>`), follow `docs/AGENT_BRIEF.md`, report in
  `docs/reports/`; the master merges. Claude's built-in worktree isolation fails here (d:\ vs D:\ case), so create
  worktrees manually with `git worktree add`.
- Founder God-mode login exists in this machine's `data/` (see `data/ADMIN_CREDENTIALS.txt`); the app runs on 8765.
- Workflow recipes live in project skills (`.claude/skills/`, listed in `CLAUDE.md`); `.gitignore` tracks only
  `.claude/skills/` (local settings stay ignored).

## Module status (2026-11-17)
All eight modules are Live: Design Studio, Drawing Studio, Image & Drawing to CAD, Assembly Studio, Manufacturing
Advisor, Engineering Advisor, 3D Print Prep, Mesh Studio (Blender render studio). Downstream modules open on the
current part from the Studio's **Make** tab; input modules (From Drawing) from the **Library** tab. Platform
differentiators: similar-part search, change notices, design variants, shop handoff pack (see docs/OPPORTUNITIES.md).

## Where things stand
See `docs/PUNCH_LIST.md` (DS-* rows for the Studio) and the latest `docs/SESSION_LOG.md` entry.
