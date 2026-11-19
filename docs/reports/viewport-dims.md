# Viewport dimensions: design parameters on the model, edited on screen (DS-038)

Branch `wip/viewport-dims`. Founder request (2026-11-19): "parameters to be toggled on and off on view port. So user must
be able to edit them directly on screen, instead of trying to relate which param means what on model."

## What it does
- **Dimensions toggle** in the viewport toolbar (↔ button next to Section) and the **D** key (listed in the `?`
  shortcuts). The Params tab has the same toggle at the top; rows that have an on-model dimension carry a small ↔.
- Every editable design parameter that is one measurable size is drawn as a CAD dimension in the 3D view:
  linear dimensions with extension lines and arrows between the two faces (or a face and a hole axis / a cylinder
  tangent, two hole axes, or the outer tangents of a slot), `Ø` / `R` leaders on holes, shafts and fillets
  (`4× Ø6.6`, `4× R3`), `N×` on patterns, `Ø120` for a bolt circle, `30°` for angles. Screen-space labels (legible at
  any zoom), extension gap in pixels, nested stacking of dimensions measured the same way, labels that would sit on
  each other are moved along / across their line, hidden when seen end-on, side re-chosen only when the camera moves
  to another side of the part (no flicker while orbiting).
- **Hover** a dimension: its faces are highlighted on the model, the Params row lights up, and a tip shows the
  friendly name ("Length · click to edit"). Hover a Params row: its dimension and faces light up.
- **Click** a value: inline input at the label with the name and limits (`Length · 60–400 mm · Enter / Esc`).
  Enter applies through the existing token-free parameter rebuild (`POST /params`: same limits and whole-number
  checks, assembly impact preview when the part is used, revision + Undo toast, Ctrl+Z / Ctrl+Y); Esc / blur cancel;
  out-of-range values are refused in the input with the panel's wording. View-only users see the dimensions without
  editing; edits are disabled while the agent works or a rebuild runs.
- Parameters that are not a single dimension (e.g. a chamfer size, a gear module) stay editable in the Params panel;
  hovering their row highlights the faces they move.

## How the mapping works (no AI, no tokens)
`src/aicad/dims.py`, run on the warm build worker one request per parameter (`worker` ops `dims_base` / `dims_step`),
orchestrated by `src/aicad/platform/dims_service.py`, stored as `out/dims.json`, served by `GET /api/projects/{id}/dims`.
1. Base: the current build's face table (exact surfaces from the B-rep adaptor: plane = outward normal + offset,
   cylinder = axis + radius, cone, sphere, torus), in `topo.json` face order (`topo.body_list`).
2. For each editable parameter (cap 24): rebuild the script with that value nudged (+1 %, ±1 for whole numbers, the
   other direction at a limit or when the nudged build fails; no exports, no checks, never cached), pair the faces
   before/after **by least movement** (OCCT renumbers faces after a nudge: seen on the pipe flange) and classify:
   linear = a pair whose distance **equals the value and grew by the nudge**; diameter / radius = round faces equal
   to it that grew with it; count = cylinder instances `value × m` → `(value ± 1) × m`; angle = a plane that turned by
   the nudge at the value's angle to a fixed plane. A size picked from a standard list (M8, bearing series) that cannot
   be nudged falls back to round faces equal to the value.
3. Cache: keyed by the script **structure** (the script with editable values blanked + helpers) and the face-type
   signature. After a value edit the previous mapping is re-checked on the new geometry (`dims.validate`, ~10 ms of
   worker time) and reused; only a structure or topology change (e.g. a different hole count) re-maps. The viewer
   also re-checks every dimension against the current topology and value, so a stale mapping never shows a wrong
   number.
4. Background and bounded: scheduled after every build (`_rebuild`, `_finalize_later`, end of an agent run) and on the
   viewer's request; one parameter per worker request so an interactive build waits for at most one nudge; a newer
   build or the agent starting stops the pass; 90 s budget per pass, finished by the next pass (at least one parameter
   per pass, so a loaded machine still converges); nudges count 0.1 job towards worker recycling.
5. Optional override in `PARAM_META`: `"dim": {"kind": "none"}` hides one, `{"kind": "linear", "a": [x,y,z],
   "b": [x,y,z]}` / `{"kind": "label", "at": [...]}` place it (points evaluated by the script). **Not added to the agent
   instructions**: inference mapped every dimension-like parameter of the demo parts, the agent-style motor mount and
   the Toolbox, so there is no gap that justifies more prompt text (PD below).

Side win: `runner._exec` spent ~0.9 s per uncached build on Windows resolving the path of every loaded module in its
helper purge; it now checks only modules the run imported. A nudge (= a full uncached rebuild of a demo part) went
from 0.75 s to 0.03–0.1 s, and every interactive build that misses the base cache gets the same saving.

## Results (mapping per part)
In-process (`dims.map_script`, quiet machine, worker warm):

| Part | Params | Mapped on model | Not a single dimension | Pass |
|---|---|---|---|---|
| Mounting plate (demo) | 10 | L, W, T, EDGE (face→hole axis), PL, PW, PD, HOLE_D `4× Ø`, PR `4× R` | CH (chamfer) | 0.8 s (0.08 s/param) |
| Stepped shaft (demo) | 7 | D1, D2 `Ø`, L1, L2, KW, KL, KD (keyway floor → Ø25 tangent) | — | 0.24 s |
| L bracket (demo) | 7 | all 7 (FILLET_IN `R`, HOLE_EDGE face→axis) | — | 0.43 s |
| Pipe flange (demo) | 8 | OD, BORE, RF_D `Ø`, T, RF_H, N_BOLTS `6×`, BOLT_D `6× Ø14`, PCD `Ø120` (opposite holes) | — | 0.44 s |
| Motor mount (agent-style, replayed agent build) | 12 | all but none: incl. SLOT_L (outer tangents), BOLT_PCD `Ø44`, BOLT_N `4×`, FILLET_R `R5` | — | 1.1 s |
| Toolbox: bolts/SHCS/nut (D from list), standoff, dowel, shaft, flange, L bracket | 1–6 | all size params | washer D (clearance ≠ nominal), bearing series, gear M/Z, shaft chamfer | 0.01–0.3 s |

In the app (walkthrough on 8794, `queued_s` = time waiting behind builds/renders on the same worker): mounting plate
toggle → dimensions on screen 4.2 s on first use (mapping 4.0 s on a loaded machine), L bracket page open → shown
2.7 s (mapping 1.0 s), Toolbox insert → ready 2.7–3.6 s (mostly queued behind export + render), on-screen edit
L 120 → 150 → rebuilt and label updated 2.1 s, undo 1.4 s, value edits re-check in ~0.01 s of worker time. Under heavy
load from parallel agents (pytest of 8 dims tests took 10 min instead of 35 s) one pass took 105 s (nudges 5–16 s
each); the time budget and resumable passes handled it.

## Evidence
- `tests/test_dims.py` (10): block L/W/H (faces by hand: normals ±X/±Y/±Z at ±L/2…), plate hole Ø + pattern count +
  pitch (axis–axis), revolved shaft with a step (Ø and shoulder planes at z = 0/40/65), reuse after a value edit and
  re-map on structure/count change, all demo parts (kinds stated by hand), agent-style motor mount (wall height
  planes z = 8/68, slot length over the round ends = 30), explicit override + nudge that fails the script's own
  assert, face pairing after renumbering, endpoint end to end (background pass, resumable passes with a 0 s budget,
  reuse after `POST /params`).
- `web/src/viewer/dims.test.ts` (13): resolve + stale rejection, diameter on circle edges + count text, side choice in
  the Front view, extension/dimension line/arrow pixel positions at 2 px/mm (dimension line 22 px beyond the faces,
  extension 5 px past it, stacking 20 px per level), front-edge choice, end-on hiding, layout of all kinds, view-key
  stability, nesting, label collision moves, edit checks (limits, whole numbers, comma decimal), label formats.
- Puppeteer walkthrough (port 8794, throwaway data, puppeteer-core): screenshots in `docs/reports/viewport-dims/`:
  `01` plate dimensions on, `02` hover length (faces + Params row), `04` inline edit with limits, `05` rebuilt at 150,
  `06` after undo, `10` flange (Ø120 PCD, 6× Ø14, 6×), `12` shaft (keyway depth to the tangent), `20` replayed agent
  build (motor mount), `21` editing the bolt count on screen. 0 page errors in the main run.

## Files
New: `src/aicad/dims.py`, `src/aicad/platform/dims_service.py`, `web/src/viewer/dims.ts`, `web/src/viewer/dims.test.ts`,
`web/src/components/DimOverlay.tsx`, `tests/test_dims.py`, `docs/reports/viewport-dims/` (agent-style script, replay
cassette, screenshots). Changed: `agent/runner.py` (`_exec(source=, store=)`, faster helper purge), `agent/worker.py`
(dims ops, request `weight`), `topo.py` (`body_list`), `routers/projects.py` (`GET /dims`, scheduling hooks),
`viewer/engine.ts` (`onView`, `viewCam`), `components/Viewer3D.tsx` (toggle + overlay), `ProjectStudio.tsx`
(state, D key, hover link, on-screen edit through `guarded` + `manualCall`), `studio/Panels.tsx` (Params toggle, row
hover, ↔ marker), `studio/commands.ts` (shortcut list), `lib/types.ts`, skill `build123d-kernel`.

## Known limits / leftovers
- Dimensions of features hidden behind material are drawn too (as SOLIDWORKS does); no occlusion fading yet.
- Chamfer sizes, gear module / tooth count and other values that are not one distance stay panel-only (their faces are
  highlighted on row hover). A count is recognised for cylinder patterns only.
- Manual (hand-made) features are not mapped: their sizes are edited in their PropertyManager, so no duplicate.
- Dimensions are hidden while a PropertyManager, the sketcher, compare or the flat pattern is open, and ignore part
  explode.
- Live agent runs: none (replayed cassette `docs/reports/viewport-dims/cassette.json`, 0 tokens).

## Parked decisions (defaults used)
- PD-xx Key **D** toggles dimensions (SOLIDWORKS has no default key for "show feature dimensions"); default off,
  remembered per browser.
- PD-xx Single click on a value edits it (Instant3D-like) rather than double click; blur cancels.
- PD-xx No `PARAM_META["dim"]` guidance in the agent prompt until a real part shows an inference gap (override is
  implemented and tested).
- PD-xx Nudge 1 % (±1 for whole numbers), 24-parameter cap, 90 s budget per pass, resumable.
