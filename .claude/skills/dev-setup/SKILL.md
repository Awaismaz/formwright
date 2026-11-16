---
name: dev-setup
description: Set up or repair the Formwright dev environment on a Windows machine (uv + Python 3.12 venv from uv.lock, web node_modules, first app start), and diagnose "uv: command not found", missing .venv, VIRTUAL_ENV leakage, or web build failures. Use at the start of a session on a fresh clone or new machine, or when any gate command fails for environmental reasons.
---

# Dev environment

Target: a fresh clone reaches a green gate (INF-001 acceptance) with only these steps. Record anything that
deviates in `docs/CONTEXT.md` → "Machine notes".

## Check what's there
```bash
command -v uv || ls "$USERPROFILE/.local/bin/uv.exe"; node -v; git --version
ls -d .venv web/node_modules 2>/dev/null
```

## Install (ask the founder before installing system tools, unless they asked for setup)
- uv, Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (installs to
  `~/.local/bin`; open a new shell or add it to PATH). Alternatively `winget install astral-sh.uv`.
- Python deps: `unset VIRTUAL_ENV; uv sync` creates `.venv` with Python 3.12 from `uv.lock`, including build123d,
  OCP and the Agent SDK. uv downloads Python 3.12 itself if needed.
- Web: `cd web && npm ci` (lockfile-exact). Then `npx tsc --noEmit && npx vite build`; the app serves `web/dist`.

## Machine quirks
- A conda env leaks `VIRTUAL_ENV`, so prefix every `uv run` with `unset VIRTUAL_ENV;`.
- Git Bash heredocs containing quotes or backticks often break. Write patch scripts to a file and run them.
- `gh` may be absent. Plain `git push` works through Git Credential Manager.
- The design agent authenticates with the local Claude Code login in development (PD-09). Without it, agent chat
  fails while everything else works.

## First run
`uv run aicad app --no-browser --port 8765` creates `data/` and the founder superadmin
(`data/ADMIN_CREDENTIALS.txt`, gitignored, never committed). For testing, use a scratch `FW_DATA_DIR` instead (see
`studio-e2e`).

## Smoke test
`uv run pytest -q` (2–4 min, builds real CAD) and `uv run ruff check src tests`. If both are green on a fresh clone,
mark INF-001's "fresh-clone test" evidence in the punch list.
