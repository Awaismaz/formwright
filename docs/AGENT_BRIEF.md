# Brief for module agents (shared rules)

You are building one module of **Formwright**, an AI-native mechanical CAD SaaS (FastAPI + React; build123d/OCCT).
The founder is away. A master Claude session orchestrates several module agents working in parallel, each in its own
git worktree and branch, and merges the results. Make product decisions with good judgement. Anything that is truly
the founder's call: pick a sensible default and list it under "Parked decisions" in your report.

## Read first
- `CLAUDE.md` (rules), `docs/CONTEXT.md` (founder preferences), `docs/VALIDATION.md` (checks, advice levels §4),
  `docs/PUNCH_LIST.md` (your module's rows), `docs/DECISIONS.md` ADR-016 (Preview vs Live honesty).
- Project skills in `.claude/skills/`: `graduate-module`, `build123d-kernel`, `studio-e2e` (with `lib.mjs`),
  `formwright-review`, `dev-setup`. Follow them.

## Environment (Windows, Git Bash)
- Before every `uv run`: `export PATH="$HOME/.local/bin:$PATH"; unset VIRTUAL_ENV`.
- Your worktree needs its own env once: `uv sync` (fast, cached) and `cd web && npm ci`.
- Git Bash heredocs with quotes or backticks break. Write scripts to files, then run them.
- New Python dependencies: allowed if permissively licensed (MIT/BSD/Apache). Add with `uv add <pkg>`, and note the
  license in your report. No GPL.

## Shared machine rules (learned the hard way)
- The scratch directory is shared by every agent and the master. Use ONLY `$SCRATCH/fw-e2e-<yourport>` for your
  test data, puppeteer install and screenshots. Never `rm` anything else there.
- Pass `FW_DATA_DIR` as a Windows path: `$(cygpath -w "$E2E")\data`. Native Python misreads `/c/Users/...`.
- Stop only your own server: stop the background task you started, or the process whose command line contains
  `--port <yourport>`. Never kill by image name (python.exe, node.exe). Port 8765 is the founder's own app; never
  touch it.
- The machine has 12 threads and 32 GB, shared by about 5 agents. Run your module's tests while iterating; run the full
  suite once before your final commit.
- Already Live on main: Design Studio, Drawing Studio, Manufacturing Advisor, Engineering Advisor, 3D Print Prep.
  The Studio's **Make** tab opens Live modules on the current part (`/app/modules/<code>?project=<id>`). Map your module
  there by telling the master its code. Reuse `@/components/Viewer3D`, `IsoThumb` (`@/components/ProjectCard`) and
  `MatchRow` where they fit.

## Boundaries (so parallel merges stay clean)
- Work only inside your worktree. Commit to your branch. **Do not push and do not merge to main.**
- Never touch `D:\AI CAD\formwright\data` (the founder's data) or the apps on ports 8765/8766.
- Modules plug in **without editing shared files**:
  - Backend: `src/aicad/<module_pkg>/...` for logic, and the API in `src/aicad/platform/routers/mod_<code>.py`
    exposing `router = APIRouter(prefix="/api/m/<code>", ...)`. `app.py` auto-includes every `mod_*.py`.
  - Frontend: `web/src/pages/app/modules/<code>/index.tsx` with a default export component taking
    `ModuleAppProps` (`{ code, projectId }`, from `web/src/pages/app/modules/registry.ts`). It is auto-discovered and
    rendered at `/app/modules/<code>` (optionally `?project=<id>`) once the module is `"live"` in the catalog and
    unlocked for the workspace. Build it as a full page (project picker plus your workspace UI). Other files go in
    the same folder.
  - Tests: `tests/test_<code>.py`.
- Shared-file edits allowed: your module's entry in `src/aicad/platform/catalog.py` (status/summary/bullets),
  `pyproject.toml`/`uv.lock` via `uv add`, and `web/package.json` only if truly needed. **Do not edit Design Studio
  files** (`ProjectStudio.tsx`, `pages/app/studio/*`, `fw.py`, `runner.py`, `routers/studio.py`) or `App.tsx` /
  `AppLayout.tsx` / `Modules.tsx`. The master adds Studio entry points (e.g. "Open in Drawing Studio") after merging;
  describe the ones you want in your report.
- **Do not edit** `docs/PUNCH_LIST.md`, `docs/SESSION_LOG.md`, `docs/DECISIONS.md` or `docs/CONTEXT.md`. Instead write
  `docs/reports/<module>.md`: what was built, files, punch-list IDs with status and evidence, tests, walkthrough
  numbers, known limits, parked decisions (with the default you used).

## How a module works on the user's design
Each project has a workspace (see `aicad.platform.routers.projects.workspace_for`) with `model.py`, and under `out/`
the latest verified build: `part.step`, `part.stl`, `status.json` (fingerprint, checks, mass, features, params),
`topo.json` (exact faces/edges). Your module reads those (or re-imports `part.step` with build123d). Never modify the
user's model unless your brief says so. Write module outputs under `<workspace>/<module>/`. Scope every query by the
caller's org (`Ctx` from `aicad.platform.deps`). Viewers are read-only.
Access: the module's add-on (`addon_<code>`) or God-mode unlock. Reuse `aicad.platform.services.org_modules` /
`module_catalog`. Return 402 with a clear message when locked, as the frontend already handles paywalls.

## Quality bar
- Deterministic computations with **tests against hand calculations or published worked examples** (cite them).
- Honesty: label every output with its advice level (VALIDATION §4); state assumptions; never claim manufacturing or
  engineering validity; no invented standards values (cite sources, or flag "verify"); show "NOT APPROVED" or
  "not slicer-verified" style disclaimers where the punch list asks.
- No agent internals in the UI. Plain engineering language and SOLIDWORKS-like conventions.
- UI: match the existing design system (`web/src/components/ui.tsx`, Tailwind tokens, lucide icons). It must be
  usable, not a mock-up. When a module goes Live, switch its catalog status to `"live"` and replace SAMPLE content
  only where real output now exists.
- Gate before your final commit: `uv run pytest -q tests/test_<module>.py` plus any suite you touched, `uv run ruff check
  src tests`, `cd web && npx tsc --noEmit && npx vite build`.
- Browser walkthrough (`studio-e2e` skill) on **your own port and data dir** (given in your brief): seed demo
  projects with God mode, exercise your module on a real part, Read your screenshots, fix what you see, and record
  the numbers in your report.

## Final message to the master
Branch name, commit hash(es), a summary of what works (with evidence), files touched outside your module, and parked
decisions. Be factual: say what you did not finish.
