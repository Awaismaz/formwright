# Module report: Manufacturing Advisor (`manufacturing`)

Branch `module/manufacturing` · date 2026-11-16 · status: **Live** (catalog flipped to `"live"`).

## What was built
A deterministic DFM and process advisor that runs on the **exact B-rep** of a project's latest verified build. It
re-imports `out/part.step` with build123d, maps every face to its `topo.json` id (exact type, area and centre match),
and returns:

- **CHK-13 DFM findings (advisory, not a gate).** Each finding has a rule id, severity (critical / warning / info), the
  measured value against its limit, a rationale with its source, a suggested fix, the topo **face ids** (highlighted
  in the viewer and the report) and feature names from the feature tree. The advice level is *Recommended check*.
- **Turning rules** when the part is rotational, meaning at least 60 % of its area is revolved about one axis and the
  outer surface is a coaxial cylinder.
- **Moulding / casting screening** (draft, two-part-mould undercuts, plastic wall thickness). The pull axis is chosen
  automatically as the one with the fewest undercut faces, and the scope note says what is *not* analysed.
- A **process ranking** of CNC milling, turning, sheet metal, FDM, SLA, SLS, casting and injection moulding. Each entry
  shows its score, fit, confidence (never "high"), the reasons for and against, and the assumptions used.
- A **relative cost model** with material, machine time and setup/tooling costs, a quantity curve and cost drivers.
  It is labelled **"Relative estimate, not a quote"** at the *Preliminary estimate* advice level.
- A **shop profile** stored per org: machines, smallest tool, reach and flank length, drill L/D, minimum walls,
  draft, rates, removal rates, tooling costs and material prices. It can be edited in the UI.
- A **manufacturability report** as printable HTML and PDF (reportlab), with z-buffered iso views of every finding's
  faces. It carries the banner "NOT APPROVED FOR MANUFACTURE … relative estimate, not a quote".
- A **material library** (MFG-020) with per-property provenance and a library version. It is additive: it reuses
  `aicad.materials` unchanged.

### Rules and how they measure
| Rule | What | Measurement | Limit (source) |
|---|---|---|---|
| DFM-CNC-01 | Vertical internal corner radius | Concave partial cylinders standing on a perpendicular floor and reachable along their axis | R ≥ smallest tool radius (shop profile) → critical; R ≥ ⅓ cavity depth (Hubs guide) → warning |
| DFM-CNC-02 | Sharp internal corners | Concave straight edges between planes where neither plane can be cut by a tool end face along its principal normal | R0 → critical (EDM or add a radius) |
| DFM-CNC-03 | Internal radii away from a pocket floor | Other concave partial cylinders | Below the tool radius → warning; otherwise info |
| DFM-CNC-04 | Deep / narrow cavity | Floor faces with concave walls; depth from the walls; width = 25th-percentile span across the floor at mid-depth (exact rays) | Width ≥ smallest tool; depth/width ≤ 4 (Hubs) |
| DFM-CNC-05 | Thin walls | Exact rays from area-uniform face samples along −n; only opposed wall pairs (normals within ~37°) count | 0.8 mm metal / 1.5 mm plastic (Hubs; shop profile) |
| DFM-CNC-06 | Undercuts | Per-sample reachability from ±X ±Y ±Z: rays to infinity, tool reach (end) and flank length (walls) | Unreachable faces → warning |
| DFM-CNC-07 | Setup count | Minimal set of principal directions covering every reachable face (exact enumeration over 6 directions) | 3 or more → warning |
| DFM-CNC-08 | Envelope vs machine travel | Bounding box in any orientation against the mill travel | Fits no mill → critical |
| DFM-EDGE-01/02/03 | Acute edges (< 60°), sharp external edges (note), external fillets | Edge convexity from exact normals and an in-face classifier | General practice |
| DFM-HOLE-01 | Hole L/D | Coaxial concave full cylinders; depth from the axial extent; blind / through by axis rays | ≤ 4 recommended, ≤ 10 maximum (shop profile; Hubs) |
| DFM-HOLE-02 | Standard diameters | ISO 273 fine/medium/coarse clearance, tap drills for ISO coarse threads, stocked drill series | Off-series → warning with the nearest size; matches → info naming the table (flagged "verify") |
| DFM-HOLE-03 | Flat-bottom blind holes | Plane hit at the end of the hole axis | Info |
| TRN-01..06 | Turning: detection, L/D slenderness, sharp shoulders vs insert nose radius, secondary (non-revolved) faces, lathe capacity, bore depth | Revolution-axis test | Common practice; ISO 1832 nose radii |
| MLD-00..03 | Mould scope, draft < min (default 1°), two-part undercuts, plastic wall thickness / uniformity | Same ray machinery, along the pull axis | Common moulding guidance |

Sources and tables live in `src/aicad/manufacturing/standards.py` (`TABLES_VERSION`). Table values were typed from
public references and every one is flagged "verify against the standard", as for PD-13.

## Files
New:
- `src/aicad/manufacturing/__init__.py` (version, advice levels), `geometry.py` (`PartGeom`: exact faces, samples,
  edge convexity, rays via `IntCurvesFace_ShapeIntersector`, topo-id mapping), `features.py` (accessibility and setups,
  thickness, holes, corners, pockets, turning, sheet-likeness), `standards.py`, `rules.py`, `process.py`, `cost.py`,
  `shop.py`, `matlib.py`, `analyze.py`, `report.py`
- `src/aicad/platform/routers/mod_manufacturing.py`, which serves `/api/m/manufacturing/`:
  - `meta`, `materials`, `projects`
  - `shop-profile` (GET; PUT/POST to save; DELETE to reset)
  - `projects/{id}/analyse` (POST)
  - `projects/{id}/analysis` (GET; returns null when there is no analysis yet)
  - `projects/{id}/report.html` and `projects/{id}/report.pdf`
- `web/src/pages/app/modules/manufacturing/index.tsx`, `CostChart.tsx`, `ShopProfileDialog.tsx`, `types.ts`
- `tests/test_manufacturing.py` (25 tests)

Shared files touched (all allowed by the brief):
- `src/aicad/platform/catalog.py`: `manufacturing` set to `"live"`, with an honest summary and bullets.
- `pyproject.toml` / `uv.lock`: `uv add reportlab` (5.1.0, **BSD licence**).

The PDF font is DejaVu Sans from the matplotlib package (permissive Bitstream Vera / DejaVu licence), so ≥, Ø and ⅓
render correctly.

Module outputs are written to `<workspace>/manufacturing/analysis.json`, cached by the build's STEP hash, build id,
inputs, shop-profile fingerprint and the analyser, table and library versions. The shop profile is stored at
`<workspaces>/<org>/manufacturing/shop_profile.json`. The user's model is never modified.

## Punch-list status (proposed; the master updates PUNCH_LIST)
| ID | Status | Evidence |
|---|---|---|
| CHK-13 | Done (advisory) | `run()` returns findings plus a rule summary (pass / flagged / n.a.); `chk13.gate = false`; tests below |
| MFG-001 | Done | Corner radius, sharp corners, hole L/D, standard drills, thin walls, cavities, undercuts, setups, edges, envelope; each rule has a pass and a fail fixture |
| MFG-010 | Done | `test_turning_detected_on_demo_shaft`: axis +Z, Ø25 × 150, L/D 6, 5 keyway faces as secondary, 2 shoulders; `test_plate_is_not_turnable` |
| MFG-013 | Done (screening only) | `test_draft_check` (box: 4 walls at 0°; 2° tapered extrude passes); `test_mould_pull_direction_and_undercuts` (one side hole → pull X, no undercut; crossing holes → undercut) |
| MFG-014 | Done | `test_process_ranking_sanity`: shaft → turning first; plate → milling; ABS shell at 20k → moulding in the top 2 and at 2 parts not first; L-bracket → sheet metal; steel → moulding infeasible; confidence never "high" |
| MFG-015 | Done | Profile per org, edited in the UI; `test_advice_changes_with_shop_profile` (R3 corners pass with Ø3, critical with Ø8); API test repeats this end to end |
| MFG-016 | Done | Drivers cite rule, faces and features, with a saving per part where computable (`test_cost_drivers_cite_features`) |
| MFG-017 | Done | `test_cost_model_monotonic_in_quantity_and_labelled` (unit cost non-increasing and batch cost increasing for every process; material cost hand-checked: 126 × 86 × 16 mm³ × 2.70 g/cm³ × 6.0/kg) |
| MFG-018 | Done | HTML and PDF; each finding links to its feature, face ids and a highlighted view; `test_report_html_and_pdf`; API returns 200 with `%PDF` |
| MFG-020 | Done (first version) | `matlib.library()`: each property cites its source, plus `LIBRARY_VERSION`; prices flagged "placeholder, not market data"; `aicad.materials` API unchanged (`test_material_library_is_additive`) |

Not done (left on the punch list): MFG-011 (sheet-metal DFM: bend radii and reliefs), MFG-012 (additive DFM),
MFG-019 (assemblies), and unit-safe quantities (ENG-003 / pint).

## Tests
`uv run pytest -q tests/test_manufacturing.py tests/test_platform.py`: **44 passed** (25 new) in 2 min 36 s.
`ruff check src tests` is clean, and `npx tsc --noEmit` and `npx vite build` pass. The rest of the suite (studio, library,
plate, viewer, agent) also passes on this branch: **68 passed** in 4 min 29 s, so the full suite is 112 passed.

Hand-checked numbers:
- A 10 mm-deep Ø2 blind hole gives **L/D = 5** (warning); Ø1 × 15 gives L/D = 15 (critical).
- A pocket with R1 corners against a Ø6 tool is **critical**, limit R3.
- A 0.5 mm wall measures **0.5 mm** (abs 1e-6).
- A 4 mm slot 20 mm deep gives **depth/width = 5**.
- A 15:40 wedge has an included angle of **atan(15/40) = 20.56°**.
- The demo plate is reported as 2 setups (+Z, −Z), with its Ø6.6 holes matching "ISO 273 medium clearance for M6".
  The finding's face ids equal the topo ids of the four r = 3.3 cylinders.

## Walkthrough (port 8773, own data dir `fw-e2e-8773`, headless Chrome, puppeteer-core 25.17.0)
- Seeded the demo projects with God mode, opened `/app/modules/manufacturing`, picked a part, and opened
  `?project=<shaft>` directly.
- **0 console or page errors** on the final run.
- I read 12 screenshots and fixed what they showed:
  - The header overflowed, so the analysis inputs moved to a second toolbar row.
  - The painter's-algorithm report views had sorting artefacts, so they were replaced with a z-buffered rasteriser
    that draws model edges.
  - The default findings filter is now the top-ranked process. A metal plate no longer leads with a moulding draft
    warning.
  - The highlight swatch now matches the viewer's highlight colour.
  - An expected 404 is now `null`.
  - "Invalid Date" was fixed.
  - The cost chart's y-range was tightened and rule ids no longer wrap.
- **Mounting plate** (Al 6061-T6, qty 10):
  - 0 critical, 0 milling warnings.
  - 2 setups (+Z, −Z).
  - Ø6.6 ×4 = ISO 273 medium clearance for M6.
  - CNC milling ranked first (score 80, "Good fit").
  - USD 42.96 per part relative: material 2.81, machine time 25.15, setup 15.00. Machine time is 59 %, flagged as a
    cost driver.
  - With the shop's smallest tool set to Ø8, the R3 pocket corners became **critical** (4 corners highlighted).
- **Stepped shaft** (Steel 1045):
  - Rotational about +Z, 96.5 % revolved, Ø25 × 150.
  - Turning ranked first (90, medium confidence), milling second (60).
  - The keyway's 4 sharp internal corners are **critical** (R0 against R1.5), highlighted in the view.
  - TRN-02 L/D 6 (tailstock), TRN-03 two sharp shoulders, TRN-04 five secondary keyway faces.
  - Turning USD 38.49 against milling USD 39.76 per part at qty 10 (relative).
- The HTML report renders the banner, highlighted views and all sections. The PDF returns 200.
- Analysis time is about 0.2–0.7 s per demo part. HTML report generation takes about 1–5 s and the PDF about 1–7 s;
  the views are rendered per request.

## Known limits
- **Geometry heuristics:**
  - Setups use the six principal directions only (no 4th/5th axis or angled heads).
  - Planar faces are always counted as machined, and stock faces are not distinguished.
  - Pocket width is a percentile of axis-aligned spans, which is approximate for rounded or irregular pockets.
  - Wall thickness comes from normal rays, so only opposed walls count, and moulding wall checks are restricted to
    plastics.
  - Freeform (B-spline) faces are sampled but no freeform-specific rules exist.
  - Multi-body parts are analysed as one shape.
- **Turning:** detection needs a coaxial outer cylinder. Eccentric turning, threads (they are cosmetic in Formwright)
  and grooves are not modelled.
- **Sheet metal:** screening only. Bend radii, reliefs, flat pattern and K-factor are not analysed (MFG-011). An
  extra *con* is shown when bends lack an outer radius.
- **Cost:** all rates, removal rates, finishing rates, tooling costs and prices are **labelled assumptions**, editable in
  the shop profile. It is a comparison model, never a quote. There is no lead time or certification, and no
  tolerance-per-feature input: tolerance is a single class.
- **Performance:** the report's views are re-rendered on every request; caching them is a candidate. Analyses are
  serialised by a process-wide lock (OCCT safety).
- **Role defaults:** viewers can open saved analyses and reports, but can't run analyses or edit the shop profile.
- **Shared copy outside this module still says manufacturing is on the roadmap:** `web/src/lib/tour.ts` ("Drawings,
  manufacturing and engineering advisors are on the roadmap"). When the add-on is locked, the module page still shows
  the generic Live page with `ModuleSamples` (labelled SAMPLE). The master may want to adjust both.

## Parked decisions (defaults used)
| # | Decision | Default used |
|---|---|---|
| PD-mfg-1 | Who may edit the org shop profile and run analyses | owner, admin, engineer; viewers read-only |
| PD-mfg-2 | Default shop profile values (Ø3 smallest tool, 50 mm reach, 25 mm flank, rates 75/65 per h, MRR table, mould 10k, casting 3k, placeholder material prices) | Labelled "Assumed defaults" in the UI and report until a workspace saves its own |
| PD-mfg-3 | Rule thresholds from public guides (Hubs CNC design guide: 4×D holes, 4× cavity depth, ⅓-depth corner radius, 0.8/1.5 mm walls; 1° draft; 4 mm plastic wall) | Used as defaults (several are shop-editable); flagged as guidance, not standards |
| PD-mfg-4 | Material price data source | Placeholders (USD/kg) marked "not market data"; user overrides per workspace |
| PD-mfg-5 | ADR to record the graduation of Manufacturing Advisor to Live (ADR-016 follow-up) | The master writes the ADR in DECISIONS.md |

## Recommended Studio entry point (for the master)
Add an **"Manufacturability" button to the Studio CommandManager** (Evaluate group, next to mass properties and
compare). It should open `/app/modules/manufacturing?project=<id>` in the same tab; the module's "Studio" back link
returns there. Enable it only when the build is verified (`status.ok`).

Optionally, add a small **DFM badge** on the Studio status bar showing the counts from `GET
/api/m/manufacturing/projects/{id}/analysis` (`chk13.counts`, `stale`), and hide it when the module is locked (402).
