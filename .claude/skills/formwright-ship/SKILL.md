---
name: formwright-ship
description: Formwright end-of-session ritual — run the full gate (pytest, ruff, tsc, vite build), review the diff, update PUNCH_LIST / SESSION_LOG / DECISIONS / CONTEXT, then commit and push to main. Use at the end of every working session, when the founder says "push", "ship it", "wrap up", or before handing work back.
---

# Ship a session

CLAUDE.md requires this before the final commit of every session. Do the steps in order, and don't skip the docs:
they are the project's memory across machines.

## 1. Gate (from the repo root, Git Bash)
```bash
unset VIRTUAL_ENV
uv run pytest -q                       # ≈2–4 min, builds real CAD; must be all green
uv run ruff check src tests
cd web && npx tsc --noEmit && npm test && npx vite build && cd ..   # npm test = vitest (sketch geometry)
```
If the environment is missing (no uv, `.venv` or `node_modules`), use `dev-setup`. If a gate step can't run, say so
explicitly in the session log and in the final message. Never report it as passed.

## 2. Review
Run the `formwright-review` checklist on `git diff`. For UI-visible changes, a `studio-e2e` walkthrough should
already be in the evidence.

## 3. Docs
- `docs/PUNCH_LIST.md`: status and evidence for every row touched (test names, observed numbers, session-log refs),
  new rows for founder requests (Design Studio rows are `DS-*`), and the "Last updated" line.
- `docs/SESSION_LOG.md`: **newest first**, inserted under the header. Format:
  ```
  ## YYYY-MM-DD (letter) — <title>
  <founder request / context in 1–3 lines>
  ### Done
  ### Evidence        (pytest count, ruff, tsc/vite, browser walkthrough numbers)
  ### Not done / limits
  ### Decisions parked (PD-xx)
  ### Next
  ```
  The letter continues the day's sequence: (a), (b), … Check the latest entry.
- `docs/DECISIONS.md`: a new PD-xx row in "Parked founder decisions" for anything that is the founder's call, with the
  default used. Check existing PDs first, never re-ask.
- `docs/CONTEXT.md`: only if a preference, standing decision, machine note or way of working changed.

## 4. Commit and push
- Stage explicit paths. Never stage `data/`, `.venv`, `web/dist` or `.claude/settings.local.json`. `.gitignore`
  covers them, so check `git status` anyway.
- One commit per coherent change, with a short imperative subject in the existing style (`git log --oneline`), ending
  with the attribution trailer the session requires.
- `git push` to `origin main` (Git Credential Manager; `gh` may be absent). Report the commit hash.
