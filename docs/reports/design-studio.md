# Design Studio: DS-026 report (branch `module/studio`)

Owner: Design Studio continuation agent. Scope: punch-list row **DS-026** (sweep, loft, draft, rib, sketch tools, reference
planes, feature mirror, feature-tree polish), done one item at a time in the order the founder asked for. Each item is
committed separately on `module/studio` with tests and a browser walkthrough on a throwaway data dir (port 8771).

Status legend: **Done** = implemented, tested (analytic), walked in the browser, screenshots reviewed.

| # | Item | Status | Commit |
|---|------|--------|--------|
| 1 | Sketcher tools: trim, extend, offset, slot, polygon, sketch fillet, mirror entities, angle dimension | Done | see git log "DS-026 (1)" |
| 2 | Mirror features (selected bosses/cuts/revolves/holes about a principal plane or picked face) | Done | see git log "DS-026 (2)" |
| 3 | Reference plane features | Done | see git log "DS-026 (3)" |
| 4 | Draft and Rib | Not started | |
| 5 | Sweep and Loft (sketch-only tree nodes) | Not started | |
| 6 | Feature tree polish (rollback, rename, context menu) | Not started | |

## 1. Sketcher tools (Done)

**What was built**
- `web/src/sketch/tools.ts` (new): pure, React-free geometry for every tool. Bounded intersections line/line, line/circle,
  line/arc, circle/circle (arcs are circles with an angular range).
  - **Trim** (power trim): click a portion and it is cut back to the nearest intersections on either side. An entity
    with no intersections is deleted, and a circle needs two to become an arc. New end points reuse an existing point at the
    same spot, or get an on-line / on-circle relation to the entity they meet, so the profile stays closed when solved.
    A split line keeps its H/V/parallel/perpendicular relations on both pieces, and its length relation is dropped.
  - **Extend**: the free end nearest the click runs to the next entity along the line (or round the arc). Connected
    ends are refused with a message.
  - **Offset entities**: selected lines/arcs/circles. Connected ones are offset as a chain and re-joined at their
    carrier intersections. Closed chains and circles grow outward by default, open chains go to the left of their direction,
    and "Reverse side" flips it. Lines get a parallel relation; arcs and circles share the original centre (concentric).
    There is a live dashed preview.
  - **Straight slot**: two centres plus a width point. Built as two lines tangent to two equal arcs on a construction
    centerline; 5 DOF (two centres plus radius).
  - **Polygon**: n sides (3–64), inscribed (vertex on the circle) or circumscribed (side midpoint on the circle). It is
    held regular by equal sides plus vertices on / sides tangent to a construction circle (2 DOF with a fixed centre:
    size and rotation).
  - **Sketch fillet**: click a corner where exactly two lines meet. Both lines are trimmed back by r/tan(θ/2) and joined
    by a tangent arc with a radius dimension.
  - **Mirror entities**: about one selected centerline. Points on the axis are shared; the others get a new
    **symmetric** relation, so the copy follows the original when it is edited.
  - **Angle dimension**: between two lines, measured at their corner; editable 0–180°.
- `web/src/sketch/model.ts`: new solver relations `angle` and `symmetric`. Profiles now chain end points **by position**
  (not just by shared id), and open chains are returned as ordered segment lists, ready for rib and sweep paths.
  Fixed a solver defect: a tangent relation between a line and an arc that share an end point had a zero gradient at the
  solution. That hid a degree of freedom (wrong DOF count) and could stall the solver. It now uses a
  radius-perpendicular-to-line residual at the shared point.
- `SketchEditor.tsx`: new tool buttons (slot, polygon, sketch fillet, trim, extend, angle), action buttons (offset
  entities, mirror entities, plus a **Symmetric** relation for two points and a line), a floating tool-options bar (polygon sides
  and mode, fillet radius, offset distance and side, and per-tool hints), and a dashed preview for slot, polygon and offset.
  UX fixes found in the walkthrough:
  - The sketch canvas no longer moves when a tool is picked or the DOF status text changes length. The options bar and
    the "Under defined · n DOF" status are overlays now, not toolbar rows. Before, clicks landed about 7 mm off after
    the toolbar re-wrapped.
  - A new dimension's value box now receives keyboard focus with the value selected, so you can type the value and press
    Enter. Before, the click that placed the dimension stole the focus; this affected Smart Dimension too.
  - Mirror requires exactly one centerline in the selection (no implicit "last line" axis).
- vitest 4.1.12 (MIT) added as a web dev dependency with `npm test` (`vitest run`). `npm audit`: 0 vulnerabilities.
  vitest 3.x pulled a tinypool with critical advisories, so 4.1.12 was used. npm 9 needs `--legacy-peer-deps` to add it,
  and `npm ci` works with the committed lockfile.

**Tests** (`web/src/sketch/tools.test.ts`, 19 tests, hand-computed expectations):
- Intersections: line/line (5,0); y=3 against R10 gives (±√91, 3); line/arc gives the upper half only; circle/circle gives (4, ±3); parallel lines give none.
- Trim: crossing lines (shared corner point, solvable); delete when isolated; a split keeps H on both pieces and drops
  the length; a circle cut by a diameter leaves a semicircle, and trimming the line then gives a closed D of area 50π; two
  R5 circles trimmed into their union outline (area 50π − lens; cusp sweep 2π − 2·atan(3/4)); line/arc gives sweep π/2.
- Extend: line to the next line; arc round to x = −5 at (−5, √75); a connected end is refused.
- Offset: rectangle ±2 → 24×14 / 16×6 with 4 parallel relations; slot r5 → r7 arcs, areas 20·10+25π and 20·14+49π;
  open L chain to the left; circles 4 → 5; an over-large inward offset is refused.
- Slot area 8·30+16π with DOF 5. Hexagon sides of 10 (inscribed R10) and 20·tan30° (circumscribed, apothem 10), DOF 2.
  Corner fillet R3 on 20×10: centre (17,3), sweep π/2, area 200 − (9 − 9π/4), DOF 8. Mirror: images at the mirrored
  coordinates, axis point shared, and dragging the original moves the copy (−3, 1). Angle 60° measured, driven to 45° (DOF 0).
  Coincident-by-position chaining.

**Browser walkthrough** (port 8771, fresh data dir, `sketch-tools.mjs`, 0 console/page errors):
- Boss on the Top plane: 60×30 rectangle, two R5 sketch fillets, an R6 circle on the right edge trimmed into a bump
  (two trims), a 15 mm slot of width 6, and a hexagon R5 (inscribed); extruded 10.
  **Kernel volume 16625.923368 mm³**; hand calculation 10·(1800 − 2(25 − 25π/4) + 18π − (90 + 9π) − 37.5√3) =
  **16625.923368**; the area computed from the saved profiles gives 16625.923366. Bbox 66 × 30 × 10.
- Cut sketch on the top face (Top plane +10): centerline, open line chain, **extend** to the centerline,
  **angle dimension** 22.62° typed to **30°**, **mirror** about the centerline (closed kite), **offset** 1 mm inward
  (reverse side) with preview, then a 2 mm cut: the ring between the kite and its offset. **Kernel 16543.975574 mm³** =
  16625.923368 − 2 × 40.973897 (ring area from the saved profiles: 16543.975573). Angle in the saved profile: 30.000°.
- Screenshots reviewed: sketch before trim, polygon preview, finished sketch, angle dimension, mirror selection, offset preview, final cut.

## 2. Mirror features (Done)

**What was built**
- `fw._op` "mirror" takes an optional `source` list of earlier feature ids. Each source's tool body (the solid a
  boss/cut/revolve/hole adds or removes, including its hole pattern) is reflected about the plane, then added or cut like
  the original. Without `source` it is the existing body mirror. Source resolution is shared with feature patterns
  (`fw._sources`): a source that is missing, suppressed or later in the tree, or a non-tool feature (fillet, chamfer,
  shell...), gives a clean error, and the previous model is restored.
- Validation: plane origin and normal (the normal must be non-zero); `source` takes 1–20 ids. Editing a feature mirror into a body
  mirror sends `source: null`.
- Mirror PropertyManager: **Mirror features | Mirror body** toggle, a feature checklist (the same component as patterns),
  and the plane as Right / Front / Top (through the origin, SOLIDWORKS convention) or **Face** (picked planar face; when
  editing, the original plane is kept until a new face is picked). A green outline in the viewer previews the mirror
  plane, sized to the model. Patterns and mirrors replay their sources **in tree order**, whatever order they were ticked
  in (the walkthrough showed results depending on tick order).
- Agent prompt (manual-features list) now mentions feature mirroring.
- **Viewer crash fixed (pre-existing):** suppressing or deleting a feature while the pointer was over its tree row
  blanked the whole page (`faceOverlay` read a face id from the previous build). Face/edge overlays now skip ids not in
  the current topology, and tree highlights are cleared when a new topology loads.

**Tests**: `tests/test_studio.py::test_mirror_features_about_a_principal_plane`. On a 60×40×10 block: a through hole
(R3), a lug 8×10×5 and a blind pin hole (Ø4×6) are mirrored about the Right plane. Volume = 24000 + 2·(−90π + 400 − 24π),
bbox 60×40×15. Editing to a body mirror about x=30 doubles the volume; editing to the hole only gives the expected value.
Suppressing a source gives 422 "mirrored feature" with the model restored; a chamfer as source gives "can't be mirrored";
a zero normal gives 422.

**Browser walkthrough** (`mirror-features.mjs`, 0 console/page errors): ribbon Mirror → PM → tick Hole, Lug and Pin hole
→ Right plane (preview outline visible) → OK. **24083.716875 mm³** (hand calc 24083.716875; before 24041.858437); tree
eye suppress → 24041.858437, unsuppress → 24083.716875; edit from the tree to mirror only the hole → **23759.115099**
(hand calc 23759.115099). Screenshots reviewed: PM with plane preview, mirrored part, suppressed, edit PM, edited result.

## 3. Reference plane features (Done)

**What was built**
- New manual op `plane` (tree name "Plane1", ribbon **Features → Reference Plane**). It holds a first reference
  (Top / Front / Right through the origin, a picked planar face, or another reference plane), an offset distance
  (negative = other side), and an optional angle about the reference's own X or Y axis through its origin (turn first,
  then offset along the new normal). It is reference geometry only and never changes the solid.
- The placement is computed by `aicad/refplane.py` (pure Python, shared by model builds and the API, so the API process
  still doesn't import the CAD kernel) and mirrored in TypeScript (`resolveRefPlane`) for the live preview. It is a pure
  function of the feature's own numbers, so it is identical on every rebuild, in any tree order and when suppressed.
- Sketches attach to a plane with `plane_ref`. At build time `fw.apply_manual` places them on the plane's current
  placement. The API also keeps every attached sketch's stored placement in sync (`sync_planes`). Deleting a plane
  detaches its sketches, which keep their last placement (no broken features).
- From scratch: a hand-modelled part may start with planes. With only reference geometry there is nothing to build, so the
  model is saved without a build, and the tree now loads manual features before the first build.
- UI: PropertyManager with a live green outline of the plane. In the tree, plane rows have a plane icon, a **Sketch on PlaneN**
  pencil, and a hover outline in the viewer. The sketch-plane picker lists user planes next to Front/Top/Right, and the sketcher
  header reads "Sketch on Plane1". Agent prompt updated.
- Limitation: a plane based on another plane copies that plane's placement when created or edited; it doesn't chain-follow
  later edits of the base plane. The PropertyManager says so.

**Tests**: `test_reference_plane_features`: Top turned 90° about X with offset −10 resolves to origin (0,10,0), normal
(0,−1,0), and the volume is unchanged. A through-all R3 cut on it (sent with a stale placement, and the plane wins) gives 24000 − 90π. Editing
the plane offset to 0 moves the sketch, giving 24000 − 180π. Reordering and suppressing the plane leave the volume unchanged, and deleting it detaches the sketch at
its last placement; bad inputs give 422. `test_reference_plane_before_any_solid`: plane Top+5 with no build (revision
None), then a 20×10×10 boss on it: volume 2000, bbox z 5..15.

**Browser walkthrough** (`ref-planes.mjs`, 0 console/page errors), new empty project:
- Reference Plane Top +10 before any solid: tree shows Plane1 (no build). **Sketch on Plane1** → 30×20 rectangle →
  extrude 10: **6000 mm³**, bbox z **10..20**.
- Plane2 = Top turned 90° about X (preview through the origin): resolved normal (0,−1,0). Sketch on Plane2 → R3
  circle at (0,15) → through-all cut: **5717.256661** (6000 − 90π = 5717.256661).
- Edit Plane2 offset 10 → the attached cut moves to y = −10 and runs 20 mm: **5434.513322** (6000 − 180π = 5434.513322).
- Hover Plane1 in the tree: its outline is drawn at the block's bottom face. Screenshots reviewed: plane PM, tree before the first
  build, sketch on a plane, angled plane PM, cut, plane edit, hover outline.

## Parked decisions
- PD (mirror plane default): new body mirrors now default to the Right plane **through the origin** (as in SOLIDWORKS),
  not "YZ through the model centre" as before. Existing features keep their stored plane.
