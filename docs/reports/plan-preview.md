# Instant layout preview at plan time (WORKLIST 47, branch `wip/plan-preview`)

The founder asked whether AI image generation should be used in planning. It should not: a generated picture has no
dimensions and can look right while being wrong. What the engineer gets instead is a true 3D preview of the solved
layout, with dimensions, shown within a fraction of a second of the plan existing. So the engineer approves the real
layout and not a picture of it.

## What was built

| Piece | What | Files |
|---|---|---|
| Preview scene (server) | `preview.for_program(doc, plan=None)` lays the plan out exactly as plan approval does (`interfaces._graph_layout`: the master skeleton, the connection solver, the role layout, else the standard layout; then Archie's automatic adjustments when the first layout has problems). It then turns the skeleton and interfaces into a compact scene. **Bodies**: box, stepped shaft (profile from the direct builder's own `_shaft_spec`), gear blank (tip circle, face width, pitch circle, bore), bearing ring, key, retaining ring, pin, screws as simple cylinders through each bolted joint. Each body carries a 12-number placement. **Paths**: spec-built, Toolbox, workspace template or AI designer, from the ticket's estimate path and `direct.plan`. **Dims**: each with its source tags. **Issues**: mapped to bodies. No CAD kernel runs. Once the ICD exists, the preview is built from it instead. | `src/aicad/graph/preview.py` (new) |
| Revisions | `preview.compare(doc, key)` gives before and after scenes. For an applied revision it uses that revision's snapshot as "before" and the next snapshot (or the program now) as "after". For a revision Archie proposes (a log entry still asking) it uses the candidate, computed and not applied. | same |
| API | `GET /api/office/programs/{pid}/preview`, `POST …/preview {plan}` (lays out the plan review's unsaved edits, saves nothing, viewers allowed), `GET …/preview/compare/{key}` | `platform/routers/office.py` (3 endpoints next to `revision/preview`) |
| Client builder | Pure geometry from the primitives (lathe and box tessellation, segment counts in multiples of 4 so the quadrant points are exact), transforms, world bounds, mapping onto the viewport dimension layout (`viewer/dims.ts`, DS-038, reused unchanged), row-to-item mapping, per-part path override | `web/src/pages/app/office/preview/build.ts`, `types.ts` |
| 3D view | A small three.js view: orthographic, Z up, CAD mouse, render on demand, per-body colour, hover picking (see-through housings picked last), highlight, the same `viewCam()` contract as the Studio viewer | `preview/scene3d.ts` |
| UI | `PlanPreview`: the dimensions in the Studio's style, a "where it came from" popover on click, red problem badges and the issue list (first 3, "Show all"), a legend by build path, a hover readout (build path and the reason a part goes to the AI designer), view buttons, Dimensions and Part sizes toggles, timing. Plan review: the preview sits under Archie's questions. Hovering a row highlights the part and shows its size; hovering a part highlights its row. A coloured dot under each row's avatar gives its build path. Interfaces gate: the preview of the ICD, with the selected interface's two sides highlighted. Archie tab: "Before and after in 3D" on applied revisions and on revision proposals, with a moved, added and removed count. | `preview/PlanPreview.tsx`, `preview/RevisionCompare.tsx`, `PlanReview.tsx`, `Interfaces.tsx`, `ArchieLog.tsx` |

**Live update.** The preview query is keyed on the stored plan, the graph view and questions, the layout path and the
ICD's version, status and interface numbers, so any of these changes refetches it:
* answering Archie's questions;
* an ICD edit or a Fix;
* a revision.

Unsaved plan-review edits are laid out with a 300 ms debounce. The previous preview stays on screen while the new one
loads, and the camera is kept unless the layout's size changes a lot.

**Build-path colours after merging main.** main (`wip/office-polish2`) brought estimates per build path. In the plan
review, the preview now takes each part's colour from the same `plan_estimate.paths` the estimates use (`partPath`).
On the server, a ticket's `estimate_path` wins over the preview's own `direct.plan` reading. The board, the estimates
and the preview therefore always agree.

## Hand-checked numbers (`tests/test_plan_preview.py`, 13 tests)

1. **Keyed gear.**
   * Shaft placed at (0, 18, 0) along +Y. Its own-frame profile is Z -40 .. -18 at Ø20 and -18 .. 40 at Ø26, which
     puts the seat at Y -22 .. 0 and the shoulder at Y 0.
   * Gear at (0, -10, 0): tip Ø64 = m (z + 2), pitch Ø60, face 20, bore 20.
   * Key centre at (9.5, -10, 0), its height along +X. The keyseat floor is 10 - 3.5 = 6.5 from the axis, plus h / 2.
   * Envelope (-32, -22, -32) to (32, 58, 32). The seat Ø20 is tagged "assumed" (the brief gives none).
2. **1:3 gear pair.**
   * Gears at X 0 and X 80.
   * Four 6204 bearings centred at Y ±22 on both shafts.
   * Centre distance: a linear dimension from (0, 0, 0) to (80, 0, 0) reading 80, tagged as a design rule with the
     note "a = m (z1 + z2) / 2 = 2 × (20 + 60) / 2".
   * Envelope X -23.5 (the 6204's Ø47 / 2) to 142 (80 + 124 / 2), Y ±39, Z ±62.
3. **Table (R3).**
   * Legs at (±540, ±280, -370), brackets at (±540, ±305, -48).
   * The four M8 pivot bolts are 50 long (bracket 30 + leg 20). The tip is at the leg's inner face (Y -270) and the
     head is on the bracket's outer face.
   * 16 M5 wood screws.
   * Envelope 1200 × 700 × 720.
4. **Problems drawn in red.**
   * A hub on two shafts gives a `layout_conflict`, with the gear and both shafts red.
   * An unconnected spacer is red, with `no_interface`.
   * A per-copy `no_interface` marks only that copy red (leg #2 of 2).
   * An unplaced pin is listed with its text, since it has no position to draw.
5. **Edits, master path, revisions.**
   * An edited plan is laid out without saving, and its rows keep their plan position.
   * On the master path every number is tagged "measured from the master model".
   * Revision before and after: two legs on two brackets instead of four. Brackets move to (±540, 0, -48) and legs to
     Y 25, both for Archie's proposal and for the applied snapshot.
6. **API.** The plan review preview updates when the housing question is answered, then shows the ICD after approval
   with the same bodies.
7. **Speed.** The reducer and the table each take under 0.5 s server side, with a payload under 60 kB (measured far
   lower: see below).

**Client tests.** vitest in `preview/build.test.ts`, 15 tests:
* the primitives;
* the keyed gear's bodies span exactly the solved envelope;
* the Ø20 seat and Ø26 step at their world Y;
* the key in its keyseat, (6.5, -19, -3) to (12.5, -1, 3);
* the pair's and the table's bounds;
* the dimension mapping and filter;
* row mapping after approval renumbers an edited plan.

## Browser walkthrough (port 8815)

**Setup.** Throwaway data and God mode. The flags were:
* `FW_DESIGN_GRAPH=1`;
* `FW_OFFICE_FAKE_AGENTS=1`;
* `FW_MASTER_MODEL=0`;
* intent on the replay provider and every other role on the stub provider, so no tokens were spent.

The script is at `docs/reports/plan-preview/walkthrough.mjs`. It ran on puppeteer-core 25.18.1 with **0 console or
page errors**. I read all the screenshots.

1. **Plan review with a question** (`1-row-hover.png`). The program is "a 1:2 spur pair m2 20/40 … 6204". The
   preview is there at once and shows:
   * the shafts, gears and bearings at their placements;
   * the centre distance of 60;
   * the journals at Ø20 k6;
   * an envelope of 125.5 × 78 × 84.

   Hovering the Pinion row lights the pinion and shows "m2 × 20, Ø44 × 20" with the readout "Built from the
   interfaces (no AI): spur gear m2 × 20 teeth, face 20, bore Ø20 with a keyway". Hovering a body in 3D highlights
   its plan row (Bearing 6204).
2. **Where a number came from** (`2-dimension-source.png`). Clicking 60 gives "Centre distance 60, design rule,
   a = m (z1 + z2) / 2 = 2 × (20 + 40) / 2".
3. **Question answered, conflict in red** (`3-answer-conflict-red.png`). Choosing "A split housing with bearing caps"
   updates the preview in about **0.66 s** (answer POST, plan refetch, preview and render). The housing and cover
   appear, and the four bearing caps are drawn in red beside the housing, numbered. The issue list says "Layout
   conflict: Input open cap is bolted over a bearing seat of Housing base, but no cap fits over the seats at these
   shaft centres" (12 problems, first 3 shown). This is a real finding: at a = 60, two Ø60 caps cannot sit side by
   side. The engineer sees it before approving. The test for this case pins it down as well.
4. **Unsaved edit.** Removing the Housing cover row gives "Layout preview (your edits)" with the layout re-solved and
   4 problems left. Nothing is saved.
5. **Reducer and table** (`4-reducer.png`, `5-table.png`).
   * Reducer: a see-through housing with gears, shafts and bearings inside, the caps with their screws, and the 4 M8
     cover bolts. Dimensions: 80, Ø20 k6, Ø30 k6, 4× M6 PCD 58, 4× M6 PCD 73, and the envelope 224 × 160 × 171.6
     (bolt heads included).
   * Table: the top, a bracket and leg at each corner, 1200 × 700 × 720.
6. **Interfaces gate** (`6-interfaces-gate-preview.png`). "Layout preview: ICD v1, draft" shows the same layout as at
   plan time (the test asserts the same body ids). Selecting an interface highlights its two parts.
7. **Revision** (`7-revision-before-after.png`). REV-1 (two legs instead of four, through `POST /revision`) gives
   "Before (ICD v1)" with 4 legs and "After (ICD v2)" with 2 legs, labelled "2 re-placed or resized, 0 added,
   0 removed".

### Performance (target: endpoint plus client render under 1 s)

| | Endpoint, wall in the browser (5 calls) | Server compute (`ms.total`) | Client render (load and first frame) | Total |
|---|---|---|---|---|
| Reducer (36 bodies, 20 screws, 17.6 kB) | 41 to 53 ms | 30 to 48 ms | 184 to 294 ms | **about 0.25 to 0.35 s** |
| Table (29 bodies, 20 screws, 12 kB) | 23 to 26 ms | 13 to 16 ms | 246 to 290 ms | **about 0.27 to 0.32 s** |
| Pair after answering (autofix ran) | | 111 to 255 ms | 319 to 333 ms | about 0.6 s |

**Rendering conditions.** The client render was measured in headless Chrome on SwiftShader (software WebGL), so a
real GPU is faster. The first request after a server start pays the imports, about 150 to 270 ms once.

The server cost, broken down warm:

| Step | Time |
|---|---|
| Layout | 3 to 10 ms |
| Build-path decisions | 4 to 13 ms |
| Scene | 2 to 7 ms |

Autofix only runs when the first layout has problems.

## Known limits

* **Screw lengths are indicative.** Engagement is the tapped depth; clamp is up to 3 d. Real lengths are chosen by
  Fitz at assembly. Nuts and washers of pivot stacks are not drawn.
* **Coarse shapes.**
  * Housings, covers, brackets and plates are their envelope boxes. A housing with a cavity is drawn see-through.
  * Gear teeth are ticks on a blank.
  * A shaft whose profile the direct builder cannot read is its envelope cylinder.
* **Graph plans ignore some edits.** On a graph plan, a quantity edited in the plan review does not change the
  solver's layout: the graph still says four bearings, so the preview shows four, exactly as approval would. See
  PD-205.
* **Master path in the walkthrough.** The walkthrough ran with the master model off. The master path is covered by the
  unit test (sources tagged measured) but was not walked live.
* **Undone revisions** have no "after" preview; the button is hidden for them.

## Parked decisions (default used)

| PD | Decision | Default used |
|---|---|---|
| PD-200 | The preview is always on in plan review, at the interfaces gate and for revisions | On, no flag. Reads only, no tokens, no CAD build. |
| PD-201 | Which layout the plan-time preview shows | Exactly what approval drafts, including Archie's automatic number adjustments (said as a note). |
| PD-202 | Colour scheme | Teal for built from the interfaces, olive for workspace template, grey for Toolbox, violet for AI designer, red for a part named by a blocking problem. Warnings are listed, not coloured. |
| PD-203 | Which numbers are always on the model | Centre distances, overall envelope (bolt heads included), shaft Ø at seats and journals, bolt circles. Part sizes appear on hover or with "Part sizes". |
| PD-204 | Source of each number's tag | The design graph's parameter source. When the graph has none: standards for the tip circle and bearing bores, design rule for fits, centre distances and bolt patterns, laid out for envelopes. On the master path every number is "measured from the master model". |
| PD-205 | Plan-review edits that the design graph overrides (a quantity on a graph plan) | The preview shows what approval will do (the graph wins) and does not warn. Alternative: re-sync the graph from the edit as `revision._sync_graph` does, or warn at the row. |
| PD-206 | Screws in the preview | Simple cylinders: tapped engagement plus up to 3 d of clamp, head proportions per ISO 4017 / 4762. Nuts and washers are not drawn. |
