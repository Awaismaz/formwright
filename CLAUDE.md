# Formwright — instructions for Claude Code

Formwright is an AI-native mechanical design SaaS: a FastAPI + React app whose live **Design Studio** lets an
engineer build verified parametric CAD (build123d/OCCT) by talking to a design agent (Claude Agent SDK), by
hand (feature tree, 2D sketcher, CommandManager), from the Toolbox, or by importing STEP.
The governing brief is `CLAUDE_CODE_AI_ENGINEERING_PLATFORM_MASTER_PROMPT.md`.

## Start of every session (do this first)
1. Read `docs/CONTEXT.md` (founder preferences, standing decisions, how to run, constraints).
2. Read `docs/PUNCH_LIST.md` (feature list + status; Design Studio items are `DS-*`) and the latest entry of
   `docs/SESSION_LOG.md`.
3. Check parked decisions (`docs/DECISIONS.md`, table "Parked founder decisions", PD-xx) before re-asking anything.

## End of every session (always, before the final commit)
1. Update `docs/PUNCH_LIST.md` statuses and evidence for everything touched; add new items the founder asked for.
2. Append a dated entry to `docs/SESSION_LOG.md`: done, verified how, not done, blocked, next step.
3. Park any open founder decision as a new PD-xx row in `docs/DECISIONS.md` (with the default you used).
4. Update `docs/CONTEXT.md` if a preference, decision or way of working changed.
5. Run `pytest`, `ruff check src tests`, `cd web && npx tsc --noEmit && npx vite build`; commit and push.

## How to run and test
- `unset VIRTUAL_ENV` before every `uv run` (a conda env leaks it on this machine).
- App: `uv run aicad app --no-browser --port 8765` (serves the built SPA from `web/dist`). Frontend dev: `cd web && npm run dev`.
- Tests: `uv run pytest -q` (≈2–4 min, builds real CAD). Lint: `uv run ruff check src tests`.
- Founder credentials are in `data/ADMIN_CREDENTIALS.txt` (gitignored, never commit `data/`).

## Project skills (`.claude/skills/`, committed)
`formwright-ship` (end-of-session gate + docs + push) · `formwright-review` (pre-commit checklist) ·
`add-studio-feature` (manual CAD feature end to end) · `build123d-kernel` (kernel conventions, checks, pitfalls) ·
`toolbox-component` · `design-agent` (in-app agent contracts) · `graduate-module` (Preview → Live, Drawing Studio next) ·
`studio-e2e` (isolated app run + puppeteer walkthrough) · `dev-setup` (fresh machine). Update a skill when you learn
something it should have told you.

## Rules that matter
- Honesty labels: only Design Studio is Live; other modules are labelled **Preview**; sample data says SAMPLE.
- Never expose agent internals in the UI (file names, tools, Python, model ids). `agent/session.py` scrubs them.
- Geometry acceptance is deterministic checks (CHK-02..09), never renders. Never claim manufacturing validity.
- The design agent uses the founder's Claude Code login in development only (PD-09: API key before any other user).
  Agent-written scripts run unsandboxed behind an import tripwire (PD-10 / R-SEC-05).
- Don't touch the founder's own projects in `data/` when testing; use God mode → seed/reset demo, or temp dirs.
- When the founder is away: work autonomously, park decisions (PD-xx), don't ask questions.
