# AI CAD — engineering design platform (M0 spike)

Status: **prototype.** Chat-driven design agent (`aicad studio`), deterministic geometry checks, local live viewer. No drawings, DFM or sandbox yet. See `docs/` for the plan (`PUNCH_LIST.md`, `ROADMAP.md`, `ARCHITECTURE.md`).

## Setup (Windows, uv)

```sh
uv python install 3.12
uv sync
```

The project uses its own `.venv` (Python 3.12). It does not touch the base conda env. If a conda env is active, uv warns that `VIRTUAL_ENV` is ignored; that is expected.

## Design agent (chat → CAD)

```sh
uv run aicad studio --project my_part        # opens http://127.0.0.1:8765/
```

Type a request in the left panel. The agent (Claude Agent SDK, the same engine as Claude Code) writes `workspace/my_part/model.py` in build123d, builds it, runs the geometry checks, looks at a 4-view render, and fixes problems. The 3D viewer updates on every build. Ask for changes in the same conversation. **New** starts a fresh conversation; the files stay.

- **Auth:** by default it uses this PC's Claude Code login, with no API billing. This is for the founder's own development only. Before anyone else uses it, run with `--api-key` (or an Anthropic-approved method); see `docs/RISKS.md` R-LIC-05.
- **Safety:** the agent can only touch files inside its workspace and has no shell. Model scripts run in a subprocess with a timeout and an import tripwire, but **this is not a sandbox**. Use it only with your own prompts on this PC until the container sandbox exists (SEC-004).

## Spec-file mode (no AI)

```sh
uv run aicad build specs/fx01_plate.json     # build + checks, artifacts in out/fx01_plate/
uv run aicad live  specs/fx01_plate.json     # build, open live viewer, rebuild on every save
uv run pytest -q                             # tests (no network, no paid calls)
```

With `aicad live` running, edit and save `specs/fx01_plate.json`. The browser at http://127.0.0.1:8765/ reloads the model and the check results within about a second. Invalid specs show an error instead of a model.

## What the viewer shows

- The mesh is tessellated from the **re-imported `part.step`**, so it shows what the STEP file contains.
- Iso/front/top/right views, edges, wireframe, an X section plane, and point-to-point measurement. Measurements are mesh picks, so they are approximate to the tessellation tolerance.
- Pass/fail is decided by kernel checks (CHK-02…08), not by the picture.
- The viewer loads Three.js 0.170.0 from the jsdelivr CDN, so it needs internet access the first time.

## Limits

- The viewer reads the STEP file with the same OCCT kernel that wrote it. It cannot detect interop problems in other CAD readers. Occasional SOLIDWORKS/Creo spot checks stay in the plan (EVAL-005).
- The server binds to 127.0.0.1 and serves only an allow-list of artifact names.
