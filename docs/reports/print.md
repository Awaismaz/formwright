# Module report: 3D Print Prep (`print`)

Branch `module/print`. Status: **Live** (catalog `print` → `"live"`). Date 2026-11-16.

## What was built
A print-preparation workspace for a project's verified model, or for an uploaded STL / OBJ / 3MF mesh.

- **Source.** For a project, the exact B-rep in `out/part.step` is meshed at a chosen absolute chordal tolerance
  (0.1 / 0.05 / 0.02 / 0.01 mm). The **measured** deviation is recorded: edge midpoints and centroids are projected onto
  the exact surface, and the mesh volume is compared with the exact volume. Each triangle keeps its exact face ID, so
  thin regions are reported per face with the Studio feature name from `topo.json`. Uploads are size-capped
  (40 MB, 600k triangles), type-sniffed from content, and parsed with our own strict parsers: no DTDs or entities in
  3MF, a zip-bomb cap, and no paths taken from the upload. 3MF units are honoured; for STL and OBJ the user picks the
  units.
- **Mesh and geometry checks** (labelled *Verified calculation*):
  - PP-01 watertight (open edges, hole loops)
  - PP-02 manifold edges
  - PP-03 consistent winding with outward normals
  - PP-04 degenerate triangles
  - PP-05 self-intersection (BVH candidate pairs plus segment-triangle tests; coplanar overlaps not detected)
  - PP-06 shells
  - PP-07 tessellation deviation against the tolerance
  - PP-08 minimum wall thickness: ray cast along the inward normal, per-triangle heatmap, per-face regions
  - PP-09 narrow gaps: ray cast along the outward normal
  - PP-10 / PP-11 small holes and thin pins, from exact cylindrical faces (span ≥180° / ≥300°, so fillets are
    excluded)
  - PP-12 small loose pieces
  - PP-17 the Design Studio's own `part.stl`, read back: closed, and its deviation from the exact model (the open part
    of IO-002)
- **Per-orientation checks:**
  - PP-13 build-volume fit (also tried with X and Y swapped)
  - PP-14 overhang beyond a configurable angle (default 45° from vertical). Rule: n_z < −sin(angle); triangles in
    contact with the bed are excluded. Reports overhang area, projected support area, and a support-envelope volume
    from downward rays to the bed or to the part.
  - PP-15 bridges: horizontal undersides, with their shortest span from a minimum-area rectangle, compared with the
    bridge limit
  - PP-16 bed contact (FDM)
- **Orientation optimiser.** Candidates are:
  - as modelled
  - each of ±X, ±Y and ±Z down
  - flat faces lying on a supporting plane of the part
  - ± principal axes, from exact area-weighted second moments
  Candidates are de-duplicated within 2°. Each is aligned on the bed by a minimum-area footprint rectangle with the
  long side along X. The ranking cost combines support area, height, bed contact, a load-direction penalty (FDM is
  weak across layers) and a build-volume misfit. Every candidate returns its rationale, a strength note, the 3×3
  rotation, and the fixed-axis X→Y→Z angles to type into a slicer.
- **Estimates** (labelled *Preliminary estimate*):
  - volume, area and solid mass, using densities from `aicad.materials` plus one flagged resin value
  - for FDM, printed mass from shell and infill, support mass, and time as (deposit ÷ flow) plus a per-layer overhead
  - for SLA and SLS, layers × time per layer
- **Process presets** for FDM 0.4 mm, SLA and SLS (`printprep/presets.py`). These are documented, editable defaults
  taken from the 3D Hubs / Protolabs Network design-rules table; build volumes and time constants are our
  assumptions. The UI says so ("limit is an assumption").
- **Repair** for uploads. It welds vertices, removes degenerate and duplicate triangles, makes the winding consistent
  (BFS), fills holes (ear clipping in the loop plane, falling back to a centroid fan) and reverses inward shells. The
  report lists before/after counts. The original is kept and can be restored.
- **Exports.** Oriented binary STL and 3MF (`unit="millimeter"`, with deterministic zip bytes), placed at the plate
  centre on Z=0. Projects write to `<workspace>/print/`; uploads write to
  `<data>/print_uploads/<org>/<id>/print/`. Every export is **read back** to confirm the volume and units.
- **"Not slicer-verified" disclosure** in every analysis response, in the viewer and in the exports panel (PRN-006).

## Files
- Backend:
  - `src/aicad/printprep/__init__.py` (disclosure, version)
  - `mesh.py` (tessellation, deviation, parsers, STL / 3MF writers)
  - `bvh.py` (numpy BVH: wavefront ray queries, overlap pairs)
  - `analysis.py` (checks, thickness, orientations, estimates)
  - `repair.py`
  - `presets.py`
  - `service.py` (sources, cache, uploads, exports)
- API: `src/aicad/platform/routers/mod_print.py`, under `/api/m/print`:
  - `GET presets`
  - `POST {projects|uploads}/{id}/analyse`
  - `GET …/mesh` (a compact binary mesh with the thickness map)
  - `POST …/export`
  - `GET …/files/{name}`
  - `GET/POST uploads`
  - `DELETE uploads/{id}`
  - `POST uploads/{id}/repair|revert`

  All routes are org-scoped (cross-org access returns 404) and return 402 when the module is locked. Uploads, repair
  and export need the engineer role.
- Frontend: `web/src/pages/app/modules/print/`:
  - `index.tsx` (page and state)
  - `viewer.ts` (three.js print-bed viewer; reuses the Studio palette from `@/viewer/engine`, no Studio file edited)
  - `Viewport.tsx`
  - `SettingsPanel.tsx`
  - `ResultsPanel.tsx`
  - `Sources.tsx`
  - `types.ts`
- Tests: `tests/test_print.py` (14 tests).
- Shared file touched: `src/aicad/platform/catalog.py`, the `print` entry only (status live, honest summary and
  bullets). **No new dependencies.** numpy and scipy (both BSD) already come with build123d. trimesh and manifold3d
  were evaluated and not added.

## Punch-list status and evidence
| ID | Status | Evidence |
|---|---|---|
| PRN-001 | Done | `test_watertight_box_passes_and_box_with_removed_face_fails`: the box passes; removing its bottom face gives 4 open edges and 1 hole → fail. Winding, inward normals and a non-manifold fin are detected. Self-intersection is found on two overlapping boxes and is 0 on one box. |
| PRN-002 | Done | `test_wall_thickness_of_shelled_box_equals_the_wall`: on an open cup with 1.5 mm walls, the minimum thickness is 1.5 mm and the side-wall median is 1.5 mm (both abs 1e-6). Stricter limits turn the check to fail. Heatmap shown in the UI. |
| PRN-003 | Done | `test_overhang_area_of_t_shape_is_analytic`: overhang = (50−10)·20 = 800 mm², support volume = 800·30 mm³, 2 bridges of 20 mm span. `test_overhang_angle_threshold…`: a 30° underside counts 200 mm² at a 45° limit and 0 at 70°. |
| PRN-004 | Done | `test_flat_face_down_ranks_above_orientation_needing_supports`: the T with its bar face down (0 support, 1000 mm² contact, 38 mm tall) ranks above the upright T (800 mm² support). The rotation is orthonormal and maps the chosen face to −Z. Fit and load-direction penalties are tested. |
| PRN-005 | Done | `test_repair_fills_a_seeded_hole_and_fixes_normals`: hole, duplicate and flip are fixed, giving 0 open edges and volume 1000 mm³. A non-convex T-shaped hole is filled to the exact volume. Inward shells are reversed. |
| PRN-006 | Done | `disclosure` is present in every response (asserted in the API test). Banner in the viewer, plus wording in the results and export panels. |
| IO-004 | Done | `test_stl_and_3mf_exports_reload_with_the_same_volume`: STL and 3MF reload with the same volume (rel 1e-5), closed, `unit="millimeter"`, byte-identical on a rewrite. The API export reports `volume_match` and `units: mm`. |
| IO-002 (open part) | Done (finding) | PP-17 reads back the Studio `part.stl` and checks that it is closed and its deviation. **Finding:** `runner._exports` calls `export_stl(tolerance=0.01)`, and build123d meshes that with `isRelative=True`. The measured deviation on Demo · Pipe Flange is **0.0233 mm**, above 0.01 mm (L Bracket 0.0010, Mounting Plate 0.0009, Shaft 0.0050). PP-07 shows this module's own absolute-tolerance mesh stays within the tolerance. |

Suggested new check IDs for VALIDATION.md: the module uses `PP-01..17` internally to avoid colliding with CHK-xx. The
master may map them to CHK-15+ if wanted.

## Tests
- `uv run pytest -q tests/test_print.py tests/test_platform.py` → 30 passed.
- Full suite `uv run pytest -q` → 98 passed (7 min 17 s).
- `uv run ruff check src tests` → clean. `cd web && npx tsc --noEmit && npx vite build` → clean.
- Hand values used: box 20×10×5 = 1000 mm³; cup wall 1.5 mm; T overhang (50−10)×20 = 800 mm², support envelope
  800×30 mm³; slope 10 × (10 / sin 30°) = 200 mm²; cylinder πr²h, with the chordal bound checked.

## Walkthrough (port 8774, scratch data dir, God-mode demo seed, headless Chrome)
- **Picker:** 4 demo projects with thumbnails, plus the uploads list.
- **Demo · L Bracket** (FDM, PLA, 0.05 mm):
  - 852 triangles, measured deviation 0.0064 mm, first analysis 3.8 s including tessellation
  - all mesh checks pass; PP-17 Studio STL passes at 0.0010 mm
  - suggested orientation: as modelled, 40 mm tall, 39 mm² of support (the tops of the horizontal holes), about
    40 min (estimate)
  - volume 23.37 cm³, solid 29.0 g
  - 3MF export `demo-l-bracket_fdm-o3.3mf` (8 kB) read back with the same volume and in mm
- **Demo · Pipe Flange:**
  - 2,376 triangles, deviation 0.0249 mm (tolerance 0.05)
  - suggested: flat on its face, 18 mm tall, 0 support, about 3 h 38 min
  - on-edge options need about 3,400 mm² of support; the overhang map, seen from the underside, shows the hole tops
    in red
  - PP-17 warns, at 0.0233 mm (the finding above)
- **Upload `clip_broken.stl`** (238 triangles; 2 triangles removed, 1 flipped, 0.6 mm fin):
  - before repair: PP-01 fail (4 open edges, 1 hole), PP-03 fail (3 edges), PP-08 fail (0.6 mm fin shown red in the
    heatmap)
  - Repair: flipped 1 triangle and filled 1 hole with 2 triangles, giving 240 triangles; PP-01..03 then pass
  - PP-08 still fails, correctly, because the fin really is 0.6 mm
- **Errors:** 0 console or page errors across the run.
- **Screenshots reviewed and fixed:**
  - camera fit ignored the horizontal field of view, so the part overflowed; fixed
  - the build-volume inputs were truncated; fixed
  - overhangs were invisible from above; added an *Underside* view, chosen automatically in Overhangs mode
  - the thickness cap of 5 mm greyed out most parts; raised to 10 mm
  - wrong face lookup gave a false 6 mm STL deviation; switched to a dense per-face sample lookup
  - plurals in the repair report; fixed
  - side panels were too wide at 1280 px; narrower below 2xl

## Known limits
- The wall-thickness ray method samples triangle centroids (plus 3 interior points on large triangles). Very thin
  regions inside a large triangle that has no sample nearby could be missed. Values beyond the 10 mm cap show as
  "≥ cap".
- Self-intersection: coplanar overlaps are not detected. Skipped above 250k triangles.
- Bridges are any horizontal underside not on the bed. Anchoring at both ends is not verified, so the text says "if
  anchored".
- Holes and pins are checked only with exact geometry (projects). Uploads get thickness and gaps only.
- Tessellated cylinders lying on their side can report a small "flat contact" area from the bottom facet. Escape and
  drain holes for SLA and SLS are not checked (stated in the process notes).
- Time and mass models are rough. Not slicer-verified, and labelled as such.
- Analysis runs in the request threadpool, with an in-process LRU of 6 meshes, not in the build worker. Large uploads
  (around 500k triangles) take tens of seconds.
- Downloads use plain links, so they rely on the default organisation cookie, as Studio downloads do.

## Parked decisions (defaults used)
- **PD-print-1:** Preset values come from the 3D Hubs / Protolabs table. FDM warn-wall 1.2 mm, build volumes
  (220×220×250, 145×145×175, 165×165×300), flow 6 mm³/s, 1.5 s per layer, SLA 9 s per layer, SLS 12 s per layer and
  resin 1.15 g/cm³ are our assumptions, all editable and labelled.
- **PD-print-2:** Who may do what. Viewers may analyse and download. Upload, repair, export and delete need the engineer
  role.
- **PD-print-3:** Uploads are stored per org on disk (`print_uploads/<org>/<id>`) with no DB table and no retention
  limit. Retention or quota is the founder's call.
- **PD-print-4:** Check IDs are `PP-01..17` inside the module (not CHK-xx) until the master assigns IDs.
- **PD-print-5:** The Studio STL export's relative deflection (IO-002 finding). Changing `runner._exports` to an
  absolute 0.01 mm deflection is a Studio-file change left to the master.

## Recommended Studio entry point
Add a CommandManager / project-menu action **"Prepare for 3D printing"** that opens `/app/modules/print?project=<id>`.
The page opens that project directly and has a "Back to project" link. Show it only when the latest build is verified
(`last_status.ok`).
