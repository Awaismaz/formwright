# Session Log

Newest first. Each entry: what was done, evidence, blocked, next item, decision needed.

---

## 2026-11-16 (c) — Chat-driven design agent (Claude Agent SDK)

**Founder input:** "Just a view — where do I give a prompt?" The founder rejected a plain chat-API approach, which lacks Claude Code's agentic power, and asked for the UI to be driven by a Claude Code session. For development it should use the founder's subscription, not paid API calls.

**Research (docs fetched 2026-11-16):** the Claude Agent SDK is "Claude Code as a library": the same tools, agent loop and context management. Use is governed by the Commercial Terms. The overview page says: *"Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK."* So subscription auth is used **only for the founder's own development on this PC** (R-LIC-05, AGT-015).

### Done (evidence)
- **Dependencies:** claude-agent-sdk 0.2.182 (MIT on PyPI; it bundles the CLI, 2.1.325), fastapi, uvicorn 0.54, vtk 9.7.2, httpx (dev).
- **Smoke test:** `apiKeySource: none` (subscription login), model claude-opus-5-5. With `setting_sources=[]`, the founder's personal plugins and hooks are not loaded into the product agent.
- **New code:**
  - `agent/runner.py`: subprocess build of the AI-written script, checks, artifacts, import tripwire.
  - `agent/render.py`: VTK offscreen 2×2 views, about 2 s.
  - `agent/tools.py`: the `build_model` MCP tool returns the report plus an image.
  - `agent/prompt.py`: the CAD workflow, script contract and honesty rules.
  - `agent/session.py`: `ClaudeSDKClient`, tool allow-list, workspace path guard, SSE events.
  - `studio/app.py`: the FastAPI server.
  - Chat panel added to the viewer page.
  - `aicad studio --project NAME [--api-key]`.
- **Tests:** 43 pass, with no model calls: runner, tripwire, path/web guard and endpoint tests. `ruff` clean.
- **E2E (live, subscription):** prompt for a 6061 L-bracket (60/40 legs, 50 wide, 5 thick, 4× M5 clearance holes, R3 inside fillet).
  - The agent stated requirements and assumptions, wrote `model.py` with an analytic `EXPECTED` (section area + r²(1−π/4) fillet material − holes), built once, and all gating checks passed.
  - Volume: 23 371.4049 mm³, rel err 0.
  - 3 turns, 38.4 s. API-equivalent estimate $0.55, **not billed** (subscription).
  - It also flagged a real ambiguity: the vertical leg's holes end up only 10 mm apart, and it asked about it.
  - Screenshot of the studio UI checked.

### Findings
- Headless-Chrome screenshots hang with `--virtual-time-budget` while the SSE stream is open; use `--timeout`.
- VTK: `AddActor2D` is not available; use `AddViewProp`.
- An earlier `uv pip list` showed packages from base conda (VIRTUAL_ENV leak), not the project venv. Always `unset VIRTUAL_ENV`.

### Blocked / risks
SEC-004 sandbox is still blocked (no Docker/WSL distro). It is now the gate for any customer use, because the agent writes and runs Python.

### Next highest-leverage item
Add DRW-001..004 (3-view drawing) as a second agent tool, so the loop produces a manufacturing drawing as well as STEP. In parallel, run 5–10 real prompts from the founder's own work as a qualitative benchmark (EVAL-003).

### Decision required
None now. Before any pilot user: an API key or approved auth (AGT-015), and Docker/WSL for the sandbox (SEC-004).

---

## 2026-11-16 (b) — Approval, geometry spike, live viewer

**Founder decision:** approved the M1 wedge and direction ("Go ahead"). ADR-001, 002, 003 and 005 are Accepted. New request: a live viewer instead of checking STEP files in SOLIDWORKS → ADR-012.

### Done (evidence)
- **GOV-004** `git init`, `.gitignore`, initial commit.
- **ARC-010 / ADR-005** `.venv` with Python 3.12.13 (uv), build123d 0.13.0 pinned, cadquery-ocp 7.9.3.1.1, `uv.lock`. Base conda untouched.
- **FX-01** `src/aicad/parts/plate.py` (hand-coded, no LLM), `specs/fx01_plate.json`.
- **Checks** `src/aicad/checks.py`. FX-01 results:

| Check | Result |
|---|---|
| CHK-02 valid, 1 solid | pass |
| CHK-03 free/non-manifold edges | 0 |
| CHK-04 bbox | 120 × 80 × 10, max err 3.6e-15 mm |
| CHK-05 volume vs analytic | 89 663.7582 mm³, rel err 4.9e-16 |
| CHK-06 cylinders | r 3.3 × 4 (holes), r 3.0 × 4 (pocket corners) |
| CHK-07 STEP round-trip | equal volume/bbox/faces |
| CHK-08 determinism | fingerprint equal; STEP bytes identical (fixed header timestamp) |

  Build + export + checks + GLB took about 0.5 s on this workstation (not representative of cloud, AS-08).
- **Tests:** `uv run pytest` → 20 passed in about 16 s. Covers the golden pipeline, an independent hand calculation, STEP byte determinism, a metamorphic length test, 80 seeded random specs (≥ 50 built and checked), 6 invalid-spec rejections, negative check tests, and viewer allow-list/path-traversal tests. `ruff` is clean.
- **UX-008 live viewer** (`aicad live`): headless-Chrome screenshot of FX-01; then the spec was edited 120 → 150 mm and saved, the viewer auto-rebuilt (new build_id), and the panel showed bbox 150 × 80 × 10 and volume 113 633.7582 (Δ = 23 970 = 30·80·10 − 30·1², matches analytic). Spec reverted to 120.

### Findings
- OCP 7.9 API differences: `TopoDS.Edge` (not `Edge_s`); `TopTools_IndexedDataMapOfShapeListOfShape` is not exposed. Worked around.
- Two of my invalid-spec test cases were actually valid geometry; the validator was right. Fixed the tests, not the code.
- The viewer reads STEP with the same OCCT kernel that wrote it, so it cannot catch reader-specific interop bugs. EVAL-005 is now a periodic spot check.

### Blocked
Unchanged: SEC-004 (no Docker/WSL distro), AGT-010 (no API key), LEG-* (counsel).

### Next highest-leverage item
ARC-011: Part Spec DSL v0 (pydantic schema with features, IDs, semantic selectors, assumptions, open questions), then a compiler that reproduces FX-01 from the DSL with an identical fingerprint. This is the step that lets the LLM drive geometry.

### Decision required
None blocking. Live LLM calls (AGT-010) will need an API key plus approval for paid usage. That decision comes after the DSL exists.

---

## 2026-11-16 — Session 1: M0 discovery kickoff

**Scope:** Section 10 A–D of the master prompt. No application scaffolding, no dependency installs.

### A. Repository and runtime audit (evidence: commands run this session)

| Item | Finding |
|---|---|
| Repository | `c:\Users\Awais\Desktop\AI CAD` contains only the master prompt and `.claude/settings.json`. **No source code, assets, or tests. Not a git repository.** |
| OS | Windows 11 Pro for Workstations 10.0.22621 |
| CPU / RAM / disk | 2× Intel Xeon Gold 6254 (18 cores / 36 threads each, 36 / 72 total), 254.6 GB RAM, 369.7 GB free on C: |
| GPU | NVIDIA Quadro RTX 8000, 48 GB, driver 596.71 |
| Python | 3.13.9 (miniconda base at `C:\Users\Awais\miniconda3`); `py` launcher absent; `python3` is the MS Store stub |
| Package managers | uv 0.11.11, pip 25.2, conda 25.9.1 (envs: base, aims-matlab, erp, sensor), npm 11.12.1; pnpm/yarn absent |
| Node | v24.15.0 |
| Docker | **Not installed** |
| WSL | Installed, **no distributions** |
| Git | 2.52.0 |
| CAD already in base env | cadquery 2.8.0, cadquery-ocp 7.9.3.1.1 (bundles OCCT DLLs via delvewheel), pyvista 0.48.4, vtk 9.6.2 |
| Not installed | build123d, trimesh, fastapi, anthropic SDK |
| Desktop CAD apps | Blender 5.1, SOLIDWORKS 2025 (incl. Simulation-family add-ons, PDM, Visualize), PTC Creo 11.0.1.0 |
| AI credentials | `ANTHROPIC_API_KEY` not set in the environment |
| PyPI reachable | Yes. Latest seen: build123d 0.13.0, cadquery-ocp 8.0.1.1.0, trimesh 5.2.1, fastapi 0.163.1, anthropic 2.8.0, manifold3d 3.5.5 |

License metadata read from package metadata/PyPI (not legal review): build123d Apache-2.0; cadquery Apache-2.0; cadquery-ocp Apache-2.0 for the bindings, **but the wheel's dist-info ships no OCCT license text although it bundles OCCT binaries (OCCT is LGPL-2.1 with exception)**, see RISKS R-LIC-02; pyvista MIT; vtk BSD; trimesh MIT; fastapi MIT; anthropic SDK Apache-2.0; manifold3d Apache-2.0.

### B. Documents created
`docs/PUNCH_LIST.md`, `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/RISKS.md`, `docs/VALIDATION.md`, this log.

### C. Vertical slice proposed
VS-1 "Text/spec → parametric machined plate": see `docs/VALIDATION.md` §2 and ROADMAP M1.

### Completed
- GOV-001 environment audit, GOV-002 documentation skeleton, GOV-003 initial punch list (195 items, trace table to master prompt §2), ARC-001 architecture recommendation (draft), ARC-003..008 comparisons, LEG-001 direct-dependency license metadata. All are document deliverables; **no product code exists.**

### Blocked
- SEC-004 container sandbox: no Docker/WSL distro (installing needs approval).
- AGT-010 live LLM calls: no API key configured (and paid usage needs approval).
- All LEG-* items: need counsel.

### Next highest-leverage item
After approval: ARC-010 geometry spike: isolated uv venv (Python 3.12) + build123d, build the golden plate fixture, run STEP export/reimport and checks. Proves kernel choice on this machine before any app code.

### Decision required
Approve the M1 wedge (ADR-003) and architecture direction (ADR-001, ADR-002).

### Not done / limitations
- Licenses were read from metadata only; transitive dependency audit not yet run.
- No market evidence gathered; wedge reasoning is a hypothesis.
- Directory is not under version control; recommend `git init` once approved (non-destructive).
