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

## API doubts
Read the installed source, not memory: `uv run python -c "import build123d, inspect; print(inspect.getsourcefile(build123d))"`.
Upstream docs: https://build123d.readthedocs.io (the in-app agent may fetch only that host).
