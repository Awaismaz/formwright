# Golden assembly fixtures (ASM-012)

Three original assemblies, generated for Formwright, that the test suite rebuilds from their parametric scripts and
checks deterministically on every run. They are not copies of any real product, client project or catalogue part
(see each `provenance.json`). The part fixture FX-01 lives in `specs/fx01_plate.json` / `src/aicad/parts/plate.py`.

| Fixture | Folder | What it is | What it exercises |
|---|---|---|---|
| FX-04 | `fx04_bolted_bracket/` | Aluminium angle bracket bolted to a base plate with 2 × M6×30 hex bolts, 4 washers, 2 nuts (Toolbox) | Coincident + concentric mates, 8 fastener spins, through-bolt length rule (grip 18 → M6×30, 3.6 mm protrusion), 0.3 mm hole clearance, BOM |
| FX-05 | `fx05_keyed_shaft/` | Stepped C45 shaft in two 6204 bearings in a grey-iron housing, m2 z30 spur gear driven by a 6 × 6 × 18 key | Multi-solid bearing, keyed group spinning as one (3 freedoms), seat / journal / key contacts with 0 interference, off-axis centre of mass, full-turn sweep |
| FX-06 | `fx06_hinged_arm/` | Arm on a Ø8 pin in a two-lug clevis base | Revolute joint with limits −20..200°, flush + distance mates, collision sweep that hits exactly where the hand formula says (−25.11° / 205.11°) |

## Files

- `src/aicad/fixtures/fx0N_*.py`: the parametric part scripts (build123d, Toolbox generators), the hand values
  (bounding boxes, volume decompositions with centroids, placements, contacts, BOM, motion prediction) and the
  assembly definition. Every expected value is a formula over the parameters, never a measurement of the built shape.
- `specs/fixtures/<fixture>/assembly.json`: the assembly definition as data (parts, instances with hand placements,
  mates in each part's frame, joints, motion cases, expected results). Regenerate after a deliberate change with
  `uv run python -m aicad.fixtures --write`; the tests fail when it is stale.
- `specs/fixtures/<fixture>/provenance.json`: author (generated for Formwright), date, licence, originality,
  design intent, what it exercises.
- `src/aicad/fixtures/harness.py`: the shared runner.

## Checks (all deterministic, all gating in the tests)

| Check | Rule |
|---|---|
| `<part>/CHK-02, CHK-03` | valid B-rep, expected solid count, closed manifold |
| `<part>/CHK-04` | bounding box = hand size (0.01 mm) |
| `<part>/CHK-05` | volume = sum of the hand decomposition (1e-6 relative) |
| `ASM/mates` | every mate satisfied after solving from perturbed start placements (a few mm and degrees off), no conflicts |
| `ASM/dof` | freedoms of the mechanism (6 × free instances − rank of the mate Jacobian) = hand count |
| `ASM/poses` | solved placements = hand placements within 1e-4 mm; free spins compared about their axis only, keyed parts relative to their shaft |
| `ASM/interference` | exact OCCT interference: no overlap above 1e-6 mm³ (touching faces are contacts) |
| `ASM/threads` | thread engagement (cosmetic threads) only on the intended bolt / nut pairs |
| `ASM/contacts` | listed minimum distances = hand values (0 for intended contacts, clearances such as 0.3 mm) within 1e-4 mm |
| `ASM/mass`, `ASM/com` | kernel mass and centre of mass at the hand placements = hand decomposition × nominal density (1e-4 relative, 1e-3 mm) |
| `ASM/bom` | BOM rows and quantities in order |
| `ASM/motion/<case>` | motion sweep (ASM-011) collides at exactly the steps the hand predicate says |
| `FX-04/…`, `FX-06/…` | fixture-specific: bolt length rule and measured protrusion; usable swing and measured edge gap vs formula |

Run them: `uv run python -m aicad.fixtures` (about 30 s), or `uv run pytest tests/test_fixtures_asm.py`.

Limits: masses use nominal densities from `materials.py` (bearings as steel 4140, fasteners as steel 1045); the
bearing and dowel are Toolbox envelopes; threads are cosmetic. Passing these checks proves geometric consistency,
not manufacturability.
