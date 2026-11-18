# IO-008: coordinate system and unit round-trip matrix

Test: `tests/test_io_roundtrip.py` (readers in `tests/io_helpers.py`, written from the format specs, not from the
exporters). Run: `uv run pytest -q tests/test_io_roundtrip.py` (about 8 s).

## Fixture FX-IO-1 (asymmetric, off-origin, analytic)

| Element | Definition (mm) |
|---|---|
| Block | X 10..70, Y 20..50, Z 5..15 |
| Boss | Ø8, Z 15..27, axis at (20, 28), near the −X/−Y corner |
| Through hole | Ø6, axis at (60, 42) |

Hand expectations: bbox min (10, 20, 5) max (70, 50, 27); volume 18000 + 102π mm³; boss top-face centre
(20, 28, 27); hole centre minus boss centre in plan = (40, 14). The part has no mirror symmetry and no point at the
origin, so an axis swap, a mirror, a lost translation or a mm↔inch / mm↔m scale error changes at least one value.
Mesh formats are also checked for a **positive signed volume** (a mirror flips the winding).

## Matrix (all green, 2026-11-18)

| Format (where the app writes it) | Declared unit / frame | Read back with | Checks | Tolerance | Result |
|---|---|---|---|---|---|
| Part STEP AP214 (`runner._exports`, every Studio build) | `SI_UNIT(.MILLI.,.METRE.)`, Z up | OCCT `import_step` | unit entity, exact bbox, volume, boss top centre | 1e-6 mm / 1e-6 rel | pass |
| `status.json` placement (`bbox_minmax`, fingerprint) | mm | JSON | corners recorded, not just sizes | 1e-3 mm (OCCT loose box) | pass |
| STL binary (`export_stl_abs`) | mm by convention (STL has no unit) | spec reader (80-byte header + records) | bbox, signed volume > 0 and value, boss top centre | 1e-4 mm, 2e-4 rel | pass |
| 3MF (`build123d.Mesher`) | `unit="millimeter"` | `printprep.mesh.parse_3mf` (unit-aware) | unit = mm, bbox, signed volume, boss | 1e-4 mm, 2e-4 rel | pass |
| GLB / glTF 2.0 (`export_gltf`, viewer + share link) | metres, **+Y up** (glTF convention) | spec reader (JSON + BIN chunks, node TRS/matrix) | tallest point is +Y = 0.027 m; CAD −Y side is glTF +Z; mapped back (x, −z, y)·1000 gives bbox, signed volume, boss | 1e-3 mm (float32 metres) | pass |
| Drawing DXF (`drawing.render.to_dxf`, Drawing Studio) | `$INSUNITS = 4` (mm), model space true size | `ezdxf` | unit header; exactly one Ø8 and one Ø6 circle (top view only); hole − boss = (+40, +14): +X right, +Y up, no mirror; 60 and 30 mm edges | 1e-6 mm | pass |
| 2D drafting DXF (`drawing.draft_dxf`) | mm, true size | `ezdxf` | covered by `tests/test_drawings_2d.py::test_dxf_layers_linetypes_dimensions_and_hatch` (100 mm edge, Ø10 circles at true size) | 1e-6 | pass (existing) |
| Native `.fwpart` (`native.part.export_part` → `install` → rebuild) | manifest `part.units = "mm"` | `container.read_package` + rebuild | manifest corners; rebuilt fingerprint **and placement** identical; carried STEP keeps the boss at (20, 28, 27) | 1e-3 mm | pass (after fix below) |
| Assembly STEP (`assembly.geometry.export`) | mm | OCCT `import_step`, leaves in export order | instance A identity; instance B rotated +90° about Z and moved (100, −50, 0): bbox, volume and boss centre equal the hand-transformed values | 1e-6 mm | pass |
| 3D Print Prep STL / 3MF (`printprep.mesh.write_stl/_3mf`) | mm (`unit="millimeter"`) | spec STL reader, `parse_mesh` | bbox, signed volume, boss; an STL uploaded as inches is scaled ×25.4 on the way in | 1e-4 / 1e-5 mm | pass |

Not in the automated matrix: Mesh Studio's GLB/OBJ/STL are written by Blender (`blender_scene.py`: glTF with
`export_yup=True`, i.e. metres and +Y up; OBJ/STL with `global_scale=1000`, `forward_axis="Y"`, `up_axis="Z"`, i.e. mm
and Z up). They need a local Blender install; `tests/test_mesh.py` runs its Blender tests only when Blender is
present and does not read the exported frame back. Follow-up: add the FX-IO-1 readers to those tests (IO-008b).
Print Prep intentionally re-orients parts for printing; its writers are tested here with the part unrotated.

## Bugs found

1. **`.fwpart` import verification ignored placement (fixed).** `native.part.compare` compared sizes, volume and
   topology counts only, so a rebuild that came back translated, or mirrored about its own centre (same size, volume
   and counts), was reported "Identical". `compare` now also takes `placement()` of both sides (bounding-box corners
   and centre of mass, tolerance 1e-3 mm) and `mod_native._rebuild_verified` passes them; a moved or mirrored rebuild
   is reported as a mismatch with a plain "position: … differ" line. Test:
   `test_fwpart_verification_catches_moved_or_mirrored_rebuild` (fails on the old code).
2. **Kernel version recorded as "unknown" (fixed).** The OCP wheel installed is `cadquery-ocp-novtk`, which the
   version lookups (`runner` status `env`, `.fwpart` manifest `kernel`, `pipeline`) did not try, so every build and
   export recorded the OCP version as "unknown". Added the distribution name to the lookups.
3. **Assembly STEP instance names (noted, not changed).** Instances of the same part share one STEP product, so after
   re-import every instance leaf carries the product's name; positions are correct (`verify_export` already matches
   by order). Naming per occurrence (NAUO names) is a follow-up if customers need instance names in other CAD tools.

No axis, mirror or unit error was found in any exporter.
