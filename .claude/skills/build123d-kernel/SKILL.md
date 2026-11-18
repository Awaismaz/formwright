---
name: build123d-kernel
description: Working notes for Formwright's CAD kernel (build123d 0.13 on OCP 7.9 / OCCT): conventions, verification patterns, and pitfalls already found in this repo. Use before writing or debugging geometry code (fw.py, toolbox.py, recognize.py, topo.py, checks.py, runner.py, demo parts, test fixtures), and when a build, check, STEP export or determinism result looks wrong.
---

# build123d / OCCT in Formwright

## Conventions (the viewer, checks and agent all assume them)
- Units mm. Z is up. Parts sit on Z=0 unless stated. The front view looks along +Y.
- Algebra mode: `Box(l, w, h, align=(Align.CENTER, Align.CENTER, Align.MIN))`, `Pos(x, y, z) * shape`,
  `Rot(...) * shape`, booleans `+ - &`. Fillets and chamfers go last, on explicitly selected edges.
- Multi-part output: `Compound(children=[...])` with `.label` set on each child, and `EXPECTED["solids"] = n`.

## Verification, the core rule
Acceptance is deterministic checks, never renders (`src/aicad/checks.py`, `src/aicad/agent/runner.py`):

| ID | What | Tolerance |
|---|---|---|
| CHK-02 | valid B-rep, expected solid count | exact |
| CHK-03 | closed manifold: no edge used != 2 times (degenerate pole edges skipped) | 0 |
| CHK-04 | bbox vs EXPECTED | 0.01 mm |
| CHK-05 | volume vs EXPECTED (analytic) | 1e-3 rel (`volume_tol` to relax) |
| CHK-06 | cylinder census by radius | exact counts |
| CHK-07 | STEP export → reimport | volume 1e-6 rel, bbox 1e-6, same faces |
| CHK-08 | determinism: fingerprint + STEP bytes identical | exact |
| CHK-09 | (code) symmetric-difference volume vs imported reference | 1e-3 rel |

- EXPECTED must come from **hand formulas over the input variables**, never from measuring the built shape. That
  independence is what makes the check meaningful. Tests follow the same rule: `pytest.approx(<formula>)`.
- Doc drift: `docs/VALIDATION.md` defines CHK-09 as *metamorphic*, but the code uses CHK-09 for the imported-reference
  match. Use the code meaning, and don't create a second CHK-09.
- Never describe passing checks as manufacturing validity. They prove geometric consistency only.

## Determinism (CHK-08), traps already hit
- The STEP header timestamp is fixed (`STEP_TIMESTAMP`) and `normalize_step()` rewrites the header. Keep exports on
  `_export_atomic`/`_exports`.
- OCCT numbers assembly occurrences (`NEXT_ASSEMBLY_USAGE_OCCURRENCE`) with a **process-wide counter**, so STEP
  bytes differ on a warm worker. `runner.normalize_step()` renumbers them after export. Keep that step whenever
  you touch Compound export.
- Cosmetic threads (CAD-027) are written into the STEP header (`runner.stamp_threads`, FILE_DESCRIPTION lines). Any code
  that exports a STEP to compare bytes with `part.step` (the CHK-08 rebuild) must stamp the same threads, or the bytes differ.
  Threads are metadata (`fw._STATE["threads"]`, cached with the base script): never model a helix.
- No dict-order, set-order, time or random dependence in geometry. Toolbox generators carry `VERSION`; bump it on any
  geometry change (see `toolbox-component`).

## Topology identity
- Never select by index; indices change on any rebuild. Use `fw.edges_near` / `fw.faces_near` (by location).
- `fw.face_key(face)` identifies the *underlying surface* (plane equation, axis+radius, sphere centre+radius). A face
  that a later boolean merely trims is therefore still credited to the feature that created it. The feature tree and
  face highlighting rely on this (`fw.feature(name, part)`).
- `src/aicad/topo.py` exports exact edges and faces (`topo.json`) for snapping and measurement. Measurements must
  match the kernel to about 1e-9 (`test_topology_is_exact_brep`).

## OCP 7.9 API pitfalls
- Downcasts are `TopoDS.Edge(shape)` / `TopoDS.Face(...)`, not `TopoDS.Edge_s`. Static methods elsewhere keep the `_s`
  suffix, e.g. `BRep_Tool.Degenerated_s(e)`.
- `TopTools_IndexedDataMapOfShapeListOfShape` is not exposed. Build edge→face maps yourself (see `free_edge_count`).
- Surface types: `BRepAdaptor_Surface(face.wrapped).GetType()` against `GeomAbs_Plane/Cylinder/Cone/Sphere`.
- Performance: don't recompute `shape.area` or other global properties per face inside loops. Recognition went from
  50 s to 1.3 s on a 1083-face gear by caching. Profile before assuming the kernel is slow.

## Imported geometry (DS-018/019)
- Imports stay **exact**: `fw.imported_blank(REFERENCE_STEP, RECOGNITION)`. Edit by booleans on the blank or by
  `fw.redefine_holes` (fill and recut). Never swap in an approximation unless a full parametric rebuild is requested,
  and then drive CHK-09 to about 0.

## Model-script sandbox (R-SEC-05)
`runner.tripwire` rejects imports of os, subprocess, socket, shutil, ctypes, requests, urllib, http, importlib,
multiprocessing, asyncio, pickle and similar modules, and calls to eval, exec, open, compile, `__import__` and input.
It is a tripwire, **not a sandbox**: the container sandbox is parked as PD-10 / SEC-004. Fixtures and demo scripts must
pass it.

## Units and frames on export (IO-008)
STEP/STL/3MF are mm, Z up, model frame; GLB is metres, +Y up (`export_gltf` turns -90 deg about X: glTF (x, y, z) = (X, Z, -Y)/1000). Any new exporter gets a row in `tests/test_io_roundtrip.py` (asymmetric off-origin fixture; compare corners, signed volume and a feature position, not just sizes). The OCP wheel installed is `cadquery-ocp-novtk`: include that name in version lookups.

## API doubts
Read the installed source, not memory: `uv run python -c "import build123d, inspect; print(inspect.getsourcefile(build123d))"`.
Upstream docs: https://build123d.readthedocs.io (the in-app agent may fetch only that host).

## Sheet metal (CAD-026)
`src/aicad/sheetmetal.py` keeps an immutable panel + bend model in `fw._STATE["sheet"]` (cached with the base script by
the runner, so never mutate it: every op returns a new `Sheet`). Flanges are found on the model's panels, not on B-rep
edges, by transforming the picked point into each panel frame (z = 0 bottom, z = T top). The flat pattern is built from
the same model (BA = θ·(R + K·T)); test flat sizes against the bend-deduction formula, never against the built flat.
A `Location` transforms points via `(loc * Location(v)).position` (`loc * Vector` raises).

## Golden assembly fixtures (ASM-012)
FX-04/05/06 live in `src/aicad/fixtures/` (part scripts + hand values) with data in `specs/fixtures/` (README there).
Every expected value is a hand formula (volume decompositions with centroids, placements, min distances, motion
predicate). After a deliberate change run `uv run python -m aicad.fixtures --write` or `tests/test_fixtures_asm.py`
fails on the stale `assembly.json`. The solver's `Result.dof` sums freedoms per instance; a group that moves as one
(shaft + key + gear) counts once per member there, so compare mechanism freedoms as 6n − rank (see `harness.run`).
Follow-ups (corners, jog, cuts through bends): a corner relief shortens the *earlier* bend through `Bend.ext` (lo, hi)
and edits that wall's panel region, so `model_volume` stays exact and the flat keeps its fast exact path; anything
the model doesn't know (a cut through a bend) makes `flatten` intersect the part with each panel slab and trace each
bend's cut on the neutral surface (`Face.revolve` of a line at radius R + K·T: build123d's `revolve()` of an Edge
returns an empty Part). Chain wire edges by matching endpoints (`_wire_points`): `BRepTools_WireExplorer` orientation
plus `Edge.position_at` double-reverses edges on revolved faces. Make 2D faces counter-clockwise before extruding
(a clockwise polygon face extrudes downwards). Jogs reuse `flange()` with `child_region` / `child_solid`.

