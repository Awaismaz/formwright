# AI CAD — engineering design platform (M0 spike)

Status: **prototype spike only.** One hand-written part family (FX-01 plate), deterministic checks, local live viewer. No LLM integration yet. See `docs/` for the plan (`PUNCH_LIST.md`, `ROADMAP.md`, `ARCHITECTURE.md`).

## Setup (Windows, uv)

```sh
uv python install 3.12
uv sync
```

The project uses its own `.venv` (Python 3.12). It does not touch the base conda env. If a conda env is active, uv warns that `VIRTUAL_ENV` is ignored; that is expected.

## Use

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
