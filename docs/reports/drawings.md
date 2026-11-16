# Drawing Studio (module `drawings`): report

Branch `module/drawings`. Drawing Studio is now **Live**: it turns a project's latest verified build into a
drawing sheet (SVG, PDF and DXF), gated by the deterministic check **CHK-12**. Every sheet carries a
"NOT APPROVED FOR MANUFACTURE" banner.

## What was built

| Area | What it does |
|---|---|
| Views (DRW-001) | Front / top / right plus isometric. Exact OCCT hidden-line removal through build123d `Shape.project_to_viewport(viewport_origin, viewport_up, look_at)` (signature checked in the installed 0.13 source: it returns `(visible, hidden)` edge lists in camera coordinates relative to `look_at`). Visible lines are solid at 0.5 mm, hidden lines dashed at 0.25 mm, centre lines are chain lines, and the isometric view has no hidden lines. First-angle (ISO method E, the default) or third-angle (method A) layout, with the ISO 5456-2 projection symbol. |
| Sheet and scale | A3 or A4 landscape with ISO 5457 margins. Scale is the largest ISO 5455 ratio (10:1 … 1:100) at which every view, dimension and block fits. The isometric view may drop up to two steps and is then labelled with its own scale. |
| Dimensions (DRW-002) | Overall extents. Turned diameters (Ø) replace the extents across the axis of a turned body. Step chains run between planar levels on each axis, with one segment shown as a reference dimension in parentheses. Hole locations run from the nearest edge. A pitch-circle diameter (PCD) is given for circular patterns. Each measurement is dimensioned once. Every value is measured from the model. It is tagged **spec** (upright, blue) when it equals a declared `PARAMS` value of a compatible kind (diameter, length, position or PCD, judged from the parameter name and label) and that match is unambiguous; otherwise it is tagged **inferred** (italic, brown). The sheet has a legend. Parameters that never map are listed in the notes ("NOT DIMENSIONED: CH, PL, PR"). |
| Hole callouts (DRW-003) | Built from an exact census: concave, full 360° cylinders found from the B-rep surfaces. Through or blind is decided by a point-in-solid test just past each end. Callouts read like `4X Ø6.6 THRU`, `Ø6 DEEP 10` and `6X Ø14 THRU / EQ SP ON PCD Ø120`, each with a leader, centre marks and axis lines. |
| Title block (DRW-004) | ISO 7200-style, 180 mm wide. Fields: title, drawing number, material (from `status.json`), units mm, scale, projection symbol, sheet, drawn by (the user), date, revision (= model revision), general tolerances, "Checked: —" and "Approved: — (not approved)". A red **NOT APPROVED FOR MANUFACTURE** banner sits across the top. |
| PDF (DRW-005) | reportlab draws the same primitive list as the SVG. `invariant=1` makes the output deterministic. |
| Layout check (DRW-006) / CHK-12 | `src/aicad/drawing/check.py` runs five sub-checks: (1) every value is tagged spec or inferred; (2) every mapped parameter is on the sheet, no measurement appears twice and every dimension was placed; (3) each principal view's HLR extents equal the model bbox projection within 0.01 mm; (4) no two texts' bboxes overlap, no dimension text sits on view geometry, and no text leaves the frame; (5) hole callouts match the census (count per Ø). Placement avoids collisions as it goes: rows, outside text and cross-side reservations. |
| Section A-A (DRW-010) | The cutting plane passes through the bbox centre, normal to X, Y or Z (Y by default when switched on). The half facing away from the viewer is kept and drawn with visible lines only. The cut faces are traced from their B-rep wires and hatched at 45°. The reference view shows the cutting-plane line with thick ends, viewing arrows and the letters "A". |
| General tolerances (DRW-012, partial) | Defaults to "Not specified". The user can pick an ISO 2768-1 class (f/m/c/v), which is printed by designation only (no table values), or enter custom text. The value goes into the title block and the notes. Nothing is ever invented. Per-dimension tolerances are not implemented. |
| Associative (DRW-015) | Each generation reads the latest verified `out/part.step` and `out/status.json`. When the build changes, a row is appended to `<ws>/drawings/history.json` (model revision, parameter diff such as "Regenerated: L 120→150", date, user) and appears in the sheet's revision table. The API reports `stale` when the model has changed. The app regenerates automatically on open for editors. Regenerating the same build reuses its row, so the same model and options give byte-identical SVG. |
| DXF (IO-007) | build123d `ExportDXF` (ezdxf) at **true size**: paper mm ÷ drawing scale. Layers are VISIBLE, HIDDEN (HIDDEN linetype), CENTER, DIM, HATCH, SHEET and TEXT. Texts are added to the same ezdxf document. |
| Performance | All kernel work runs in a warm drawing-worker subprocess (`aicad.drawing.worker`), so the web process never imports the kernel. Projections and the census are cached per STEP file. On a warm worker a demo part takes 0.36–0.96 s in total, about 1.8–3 s end-to-end in the UI including the PDF and DXF. A cold start takes 8–18 s because importing the kernel is slow on this machine. |
| API | `src/aicad/platform/routers/mod_drawings.py` serves `/api/m/drawings/...`: `GET /projects`, `GET /projects/{id}`, `POST /projects/{id}/generate`, and `GET /projects/{id}/files/{sheet.svg|sheet.pdf|sheet.dxf}` (add `?download=1` to download). All routes are scoped to the org (another org gets 404). They return 402 when the module is locked (plan or `addon_drawings`, or the God-mode `bypass_paywall`). Viewers can read and download but get 403 on generate. A project without a verified build gets 409. File names are on an allow-list. |
| Frontend | `web/src/pages/app/modules/drawings/` (`index.tsx`, `SheetViewer.tsx`, `types.ts`). A project picker shows verified projects with ISO thumbnails and their drawing state. The workspace has: a toolbar (model revision, sheet and scale, CHK-12 badge with a tooltip, Regenerate, SVG/PDF/DXF downloads, a link back to the Design Studio); a side panel with tabs **Sheet** (sheet size, projection, views, hidden lines, section on/off and axis, general tolerances, tag legend with counts), **Dimensions** (callouts and dimensions with their tags and parameters, plus parameters not on the sheet), **Check** (CHK-12 sub-checks) and **History** (revisions); and an inline SVG viewer with wheel zoom about the cursor, drag to pan, double-click to fit, and native tooltips on dimensions ("spec: parameter L"). Option changes regenerate after a 250 ms debounce. `?project=<id>` opens a project directly. |
| Catalog | `drawings` is set to `"live"`, and the summary and bullets now describe what ships. |

## Files

- New: `src/aicad/drawing/{__init__,geometry,dims,layout,check,render,generate,worker}.py`,
  `src/aicad/platform/routers/mod_drawings.py`, `tests/test_drawings.py`, `web/src/pages/app/modules/drawings/*`.
- Shared files touched (as allowed): `src/aicad/platform/catalog.py` (the drawings entry only), and
  `pyproject.toml` / `uv.lock` (`uv add reportlab`).

## Licences (LEG-002)

| Package | Version | Licence | Use |
|---|---|---|---|
| reportlab | 5.1.0 | BSD (ReportLab open-source licence, OSI BSD classifier) | PDF writer and Helvetica text metrics. New direct dependency. |
| ezdxf | 1.4.5 | MIT | DXF, through build123d `ExportDXF` (already a transitive dependency of build123d). |
| svglib | — | **LGPL-3.0, rejected** | Not used. Both renderers draw the same primitives instead. |
| puppeteer-core | 25.17.0 | Apache-2.0 | Walkthrough only. Lives in the scratch directory, not a project dependency. |

## Punch-list status

| ID | Status | Evidence |
|---|---|---|
| DRW-001 | Done | `test_view_extents_equal_bbox_projections`: front/top/right extents equal the hand bbox projections within 0.01 mm, and the iso width equals (L+W)/√2. `test_hidden_lines_present_for_holes`. |
| DRW-002 | Done | `test_dimensions_tagged_and_callouts_match_census`: L/W/T/HOLE_D/EDGE/BLIND_D are spec, spacings are inferred, one Z segment is a reference. `test_coincident_values_are_not_claimed_as_spec`. |
| DRW-003 | Done | Callouts `4X Ø8 THRU` and `Ø6 DEEP 10` match the census (5 holes). The flange shows `6X Ø14 THRU / EQ SP ON PCD Ø120`. |
| DRW-004 | Done | Title fields come from `status.json` and the run. `test_sheet_passes_chk12` checks the material; the banner is checked in `test_exports_are_valid`. |
| DRW-005 | Done | The PDF is valid (`%PDF-` … `%%EOF`) and drawn from the same primitives as the SVG. |
| DRW-006 | Done | CHK-12 overlap sub-check passes on all 4 demo parts and fails on a seeded overlap (`test_chk12_fails_on_seeded_overlap_and_extent_error`). |
| DRW-010 | Done | The fixture's section cut-face area equals L·T − Ø6×10 by the shoelace formula (rel 1e-6). X/Y/Z sections run on all demo parts and pass CHK-12. FX-03 does not exist as a fixture; the stepped-shaft demo is the nearest substitute. |
| DRW-012 | Partial | General block only (none / ISO 2768 class / custom text), as asked. Per-dimension tolerances from the spec are not done. |
| DRW-015 | Done | `test_associative_regeneration_adds_revision`: L 100→120 gives a second row, "Regenerated: L 100→120". Walkthrough: parameter edit L 120→150 → model rev 2, then 150→160 → rev 3. |
| IO-007 | Done | The DXF reads back in ezdxf with the expected layers, and the VISIBLE layer has 100 mm and 20 mm lines at 1:1. |
| CHK-12 | Implemented | Pass and fail fixtures cover overlap, an extent error of +0.5 mm, an untagged dimension and a missing callout. |

## Tests

- `tests/test_drawings.py`: 16 tests, all passing (~50 s). The fixture is an original box with holes, and the expected values are derived from its inputs. They cover views and extents, hidden lines, the census, the section area, parameter kinds and number formatting, tagging, the coincidence guard, CHK-12 pass and seeded fails, valid SVG/PDF/DXF, determinism (byte-identical SVG for the same model, including a different date and output folder), options (A4, third angle, ISO 2768-m), associative revisions, user errors, and the API (401, 402, add-on unlock, 409 with no build, generate, files, path traversal 404, stale flag, viewer 403, other org 404) plus the catalog being live.
- Gate: `ruff check src tests` clean, `tsc --noEmit` clean, `vite build` OK. `tests/test_drawings.py` and `tests/test_platform.py` pass (31 tests). The full-suite result is in the final message.

## Walkthrough (studio-e2e, port 8772, data `scratch/fw-e2e-8772`)

God mode → `all_modules` → seed-demo (4 real builds, 29 s) → Drawing Studio picker → Mounting plate → turn the
section on → third angle + A4 → ISO 2768-m → Dimensions, Check and History tabs → wheel zoom → flange, bracket
and shaft opened with `?project=` → parameter edit L in the Studio API → reopen gives an automatic update to rev 2/3.
Downloads: SVG 37.9 KB, PDF 13.1 KB, DXF 175 KB, all 200 with the right content types.

| Part | Sheet | Scale | CHK-12 | Spec / inferred dims | Server time (warm) |
|---|---|---|---|---|---|
| Stepped shaft | A3 | 1:1 | pass | 5 / 8 | 0.36 s |
| Pipe flange | A3 | 1:2 | pass | 4 / 1 + 2 spec callouts (BORE, BOLT_D, PCD) | 0.87 s |
| Mounting plate | A4 (third angle, section) | 1:2 | pass | 8 / 7 | 0.96 s |
| L-bracket | A3 | 1:1 | pass | 7 / 6 | 0.36 s |

An option matrix (28 combinations: X/Y/Z sections, third angle, A4, reduced views, no hidden lines) ran without
errors. CHK-12 fails **only** when the user switches off the view a hole callout needs, which is by design ("hole
callouts differ from the census").

Fixes made after reviewing the screenshots:
- **Hidden lines disappeared in the app** (the standalone SVG was fine). The inline SVG's layer class `hidden` matched Tailwind's `.hidden {display:none}`. Classes are now namespaced `drw-*`, with a regression assertion in the tests.
- Dimension text collided across sides on the small shaft top view (CHK-12 caught it). Later sides now avoid text already placed on earlier ones.
- Dimension text sat on the cutting-plane arrows. The arrows are now reserved boxes.
- A rectangle of 4 holes was misread as a PCD pattern. Grids are now excluded.
- Notes were shortened, and the tag legend moved into the notes block on A3 (the info column keeps it on A4), so A4 sheets reach 1:2 for the plate, bracket and shaft.
- ISO 2768 class letters were upper-cased in the notes ("2768-M"). Fixed: the class is printed exactly as chosen.
- The title-block projection label overlapped the symbol. The symbol was moved.
- An unknown client analytics event caused 422s. Removed; the server records `drawing_generated`.

## Known limits

- Counterbores and countersinks are called out as separate plain holes, and a modelled drill-point cone can make a blind hole read THRU. Holes off the principal axes, or fully internal, are not called out; a note on the sheet says so.
- Spec mapping is by value plus parameter kind (from name and label). It is not proven by perturbing parameters. Coincidences inside one chain are rejected, but a numeric coincidence across families could still be tagged spec. A metamorphic check (rebuild with ±δ per parameter in the build worker) would make it provable.
- Pockets are dimensioned only through level chains (wall-to-wall). Fillet and chamfer radii and counts are not dimensioned; they are listed as "not dimensioned".
- Layout is a heuristic packer (projection grid plus candidate slots). Large parts on A4 can drop to 1:5 (for example the Ø150 flange). The revision table shows the last 3 rows.
- Not done: DRW-011 detail views, DRW-013 GD&T, DRW-014 BOM, DRW-016 drawings for imported STEP (it should already work for imported projects that have a verified build, since only `part.step` is read, but this is untested), and per-dimension tolerances.
- DXF dimensions are lines plus TEXT entities, not associative DIMENSION entities. DXF bytes are not deterministic (ezdxf handles and header times); the SVG is.
- PDF uses the standard Helvetica font (not embedded). Text is 3.5 mm font size, so cap height is about 2.5 mm.
- Downloads are plain links, so `X-Org` is not sent. This matches the Studio's STEP download and works for the user's default or only workspace.

## Parked decisions (defaults used)

| # | Decision | Default used |
|---|---|---|
| DRW-PD-1 | Default projection method | First angle (ISO method E). Third angle is one click away. |
| DRW-PD-2 | Default sheet and scale policy | A3 landscape. Largest ISO 5455 ratio that fits (no 1:2.5). The iso may drop up to 2 steps and is then labelled. |
| DRW-PD-3 | Meaning of "every spec'd dimension appears once" (CHK-12) | Each measurement is dimensioned once (ISO 129-1). Every parameter that maps unambiguously appears at least once. One parameter may label several dimensions from different features (for example HOLE_D on two hole groups). |
| DRW-PD-4 | General tolerances | "Not specified" by default. An ISO 2768-1 class is printed by designation only (no value table). Custom text up to 60 characters. |
| DRW-PD-5 | Who may generate drawings | Owner, admin and engineer. Viewers can view and download only. No token charge for drawings. |
| DRW-PD-6 | Revision letters vs numbers | REV = model revision number. A revision row is added only when the drawn build changes. Date and drawn-by come from the first generation of that build (keeps sheets deterministic). |
| DRW-PD-7 | Associativity behaviour | An editor opening a drawing whose model has changed gets an automatic regenerate and a toast. No regeneration happens in the background on Studio builds. |
| DRW-PD-8 | Drawing number format | `FW-` plus the first 8 characters of the project id, upper case. |
| DRW-PD-9 | Dimension tag styling | Spec: upright, dark blue. Inferred and reference: italic, brown. A legend is on every sheet, and the italic difference survives black-and-white printing. |

## Studio entry points I recommend (for the master to add)

1. In the Design Studio header next to the STEP download: a "Drawing" button, shown when the build is verified, linking to `/app/modules/drawings?project=<id>`.
2. In the Studio Files panel: a "Drawing sheet (SVG / PDF / DXF)" row with the same link.
3. In the project card menu on Projects: "Open in Drawing Studio".
4. Optional: for a Live module that is still locked, `ModulePage` still shows the Preview "What it will do" sample. Consider live-module wording there.
