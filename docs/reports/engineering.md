# Engineering Advisor (module `engineering`): report

Branch `module/engineering`. Status: **Live** (catalog flipped). Module agent session 2026-11-16.

## What was built
A deterministic, unit-safe engineering-calculation and review module. Results are labelled with their advice level
(VALIDATION §4). They never claim validation, and a named engineer can sign calculation sets; any later edit
invalidates the signature.

- **10 calculators** (`src/aicad/engineering/calc_*.py`). Each is a pure function with typed, pint-checked inputs, and
  shows its working (equation, substitution, value, reference per step). Each also cites its sources, states its
  assumptions, and lists the published example its unit test reproduces.
  - Beams & sections: section properties (rect/round/tube/custom), beam deflection and bending stress (cantilever or
    simply supported, any number of point loads plus a UDL, by superposition of Shigley Table A-9)
  - Fasteners & joints: bolted joint (ISO 898-1 stress area, ISO 724 diameters, bolt stiffness, layered frusta
    member stiffness, preload from proof fraction, torque or known preload, nut factor, yield, overload and separation
    factors, Goodman fatigue screening), thread engagement length (Machinery's Handbook / FED-STD-H28 method),
    pin/dowel shear (single/double, bearing on pin and member)
  - Shafts & fits: combined bending and torsion (von Mises, DE-Goodman, first-cycle yield, Marin-factor Se
    estimate, minimum diameter for a required factor), interference fit (Lamé: pressure, hub/shaft stresses, von
    Mises, slip torque and axial force)
  - Bearings & springs: ISO 281 L10 and Lnm = a1·aISO·L10 (hours and revolutions, required C for a target life,
    application factor, X/Y equivalent load), helical compression spring (Shigley ch. 10: rate, index, KB, Sut from
    A/d^m, Ssy, load at yield, solid-safe free length, buckling)
  - Tolerances: 1D stack-up (worst case and RSS, asymmetric bands, sensitivities, contributions, spec checks)
- **Units (ENG-003)**: `units.py` uses pint 0.26.2 (BSD-3-Clause; deps flexcache/flexparser, BSD). API values are
  `{value, unit}`, converted to N / mm / MPa / N·mm. A wrong dimension is rejected with a field-specific 422. The UI
  has an SI ↔ US display toggle.
- **Standards and materials library with provenance and versions (ENG-003)**: `standards.py` (`std-1.0.0`) holds
  ISO 261 pitches, ISO 273 clearance holes, ISO 898-1 property classes, Shigley tables (bolt endurance, nut factors,
  Marin, threaded length, spring wire A/m, Ssy fractions) and ISO 281 a1. `materials.py` was extended **additively**
  (`MECHANICAL`, `mechanical()`, `matlib-1.0.0`): Sut/Sy/E/ν (and fatigue strength for aluminium) for 11 materials.
  Each value carries its condition, basis (typical vs spec minimum) and source (ASM / Aluminum Association, Shigley
  A-20/A-5, ASTM A240/A564/B348/A48), and the note "verify against the supplier certificate". Plastics,
  brass/bronze/copper and 5052 fatigue are deliberately left without strengths, because I had no citable source.
- **Project link**: `project.py` reads `out/status.json` and `.fw/project.json`. From them it derives mass,
  weight, CoG, the inertia tensor scaled by density (kg·mm²), bbox, PARAMS and features. It re-imports `out/part.step`
  and runs the existing `recognize()` plus a new sharp-edge scan, cached in `<ws>/engineering/geometry.json` and
  keyed by the STEP hash. It then produces **pre-fill suggestions with a provenance line per value**: bolted joint
  from an ISO 273 clearance pattern (grip from the hole depth; the mating layer is labelled ASSUMED), pin shear from
  hole groups, thread engagement from tap-drill blind holes, shaft section from the smallest turned diameter, press
  fit from a central bore, and beam/section from the bbox (labelled as an approximation).
- **Load cases (ENG-001)**: structured record per project: loads (type, value + unit with a canonical conversion,
  direction, location/feature, basis specified/measured/derived/assumed, source), supports, cycles, temperature,
  environment and source. The UI can add self-weight from the model mass × g, with derivation text.
- **Failure-mode checklist (ENG-002) and recommended analyses (ENG-006)**: `review.py` produces checklist items
  tied to the recognised features. The modes are static strength, stress concentration, fatigue, bolted/pinned
  joints, buckling (slender bbox), vibration/critical speed, thermal/creep (polymer or temperature in a load case),
  fits/stack-ups, and missing material data. Each item suggests calculators and analyses/tests with a rationale.
  Item status (open / in progress / addressed / n.a.) and notes persist per project. Level: Recommended check.
- **Stress-concentration hints (ENG-010, labelled Heuristic)**: shoulders on turned parts (r/d), holes near an edge
  (e/d < 2, grouped), small internal fillets, and **sharp re-entrant edges found from the B-rep** (edge-convexity
  test against the solid). Coordinates and a "check with calculator" link are included.
- **Safety factors (ENG-005)**: every calculator with a strength check requires *Required safety factor* and
  *Safety factor source* (422 otherwise). Every check shows the achieved factor, the required factor and the source.
  Wording is "meets / below required factor", never "safe".
- **Sign-off (ENG-008)**: a calculation set (items, linked load cases, notes, conclusion) is signed by a named user
  (engineer/admin/owner; not while impersonating; explicit confirmation). The record stores name, email, role, time,
  statement, a `self_check` flag, and the SHA-256 of the canonical content (calculator ids and versions, inputs,
  outputs, checks, linked load cases, notes, library versions). Status is recomputed from the hash on every read, so
  any edit of an input, a note or a linked load case gives "Signature invalid: edited after sign-off". An
  `signature_invalidated` history event is recorded and an audit entry is written. Unsigned sets show
  "Unsigned: not for release". Item level is Preliminary estimate until signed, Verified calculation while the
  signature is valid. Validated simulation is never produced.
- **ENG-012 guard**: `wording.py` detects affirmative claims ("validated", "certified", "is safe", "safe for use",
  "approved for production", "FEA-validated", "verified safe", …) and allows negations and the level name
  "Validated simulation". Tests run it over every calculator schema text, the catalog card and all generated hints.
  The API rejects such wording in set notes/conclusions, sign-off statements, load-case descriptions and checklist
  notes (422 with guidance).
- **API** `src/aicad/platform/routers/mod_engineering.py` (`/api/m/engineering/...`):
  - Calculators and listings: `GET /catalog`, `POST /run`, `GET /projects`, `GET /projects/{pid}/model`.
  - Load cases: `GET|POST /projects/{pid}/loadcases`, `PATCH|DELETE …/loadcases/{id}`. A load case linked to a set
    can't be deleted (409).
  - Calculation sets: `GET|POST …/sets`, `GET|PATCH|DELETE …/sets/{sid}`, `POST …/sets/{sid}/items`,
    `PATCH|DELETE …/items/{iid}`, `POST …/sets/{sid}/signoff`.
  - Stack-ups: `GET|POST …/stackups`, `PATCH|DELETE …/stackups/{id}`.
  - Review: `GET …/review`, `PATCH …/review/items/{id}`.
  - Access: org scoping goes through `_project`; viewers are read-only (403); only admins delete signed sets; a
    missing `engineering` entitlement returns 402 with `cta`. God `bypass_paywall` is honoured. Per-workspace write
    locks.
- **Frontend** `web/src/pages/app/modules/engineering/` (`index.tsx`, `CalcForm.tsx`, `Sets.tsx`,
  `LoadCases.tsx`, `Stackups.tsx`, `Review.tsx`, `Library.tsx`, `types.ts`):
  - Header and project picker: opens `?project=` directly, with a back-to-Studio link and the units toggle. A
    standing disclaimer shows the four advice-level badges.
  - Calculators tab: searchable catalogue by category, a schema-driven form (unit selectors, table inputs,
    conditional fields, a highlighted safety-factor group, and a "from model" badge with provenance under each
    pre-filled field), and a results panel (key outputs, checks with SF and source, warnings, numbered working with
    equations and substitutions, sources, the published example the calculator was checked against, assumptions,
    notes).
  - Project-link card: mass, weight, CoG, inertia, recognised features, "checks from the model".
  - Calculation sets: status banners, expandable items, edit inputs (re-run, invalidates), linked load cases,
    notes/conclusion, sign dialog, history.
  - Load-case editor; stack-up tool with contribution bars; failure-mode checklist with hints and recommended
    analyses; library (materials with sources, standards tables, advice-level definitions).

## Files
- New: `src/aicad/engineering/{__init__,core,units,standards,calc_structures,calc_fasteners,calc_machine,review,project,store,wording}.py`,
  `src/aicad/platform/routers/mod_engineering.py`, `tests/test_engineering.py`,
  `web/src/pages/app/modules/engineering/*`, `docs/reports/engineering.md`.
- Shared files touched (allowed by the brief):
  - `src/aicad/platform/catalog.py`: the `engineering` entry only (status `live`, honest summary and bullets).
  - `src/aicad/materials.py`: additive `MECHANICAL` table and `mechanical()`; existing API unchanged.
  - `pyproject.toml` / `uv.lock`: `pint`, via `uv add`.

## Punch-list status and evidence
| ID | Status | Evidence |
|---|---|---|
| ENG-001 | Done | Load-case record API + editor; `test_api_project_link_signoff_and_invalidation` (create, canonical unit conversion, edit invalidates linked signed set, delete blocked while linked) |
| ENG-002 | Done | Checklist tied to recognised features with persisted status; same API test asserts modes for the mounting plate |
| ENG-003 | Done | pint unit safety (`test_units_convert_and_reject_wrong_dimensions`); versioned standards and material tables with sources; library tab |
| ENG-004 | Done | 10 calculators; table below; level is Preliminary estimate until signed (Verified calculation after review) |
| ENG-005 | Done | `test_safety_factor_source_is_mandatory`; API 422; UI shows required SF + source next to every achieved factor |
| ENG-006 | Done | Recommended analyses/tests with rationale per checklist mode (`review.recommended_analyses`) |
| ENG-007 | Done | Every result, checklist item and hint carries its level; badges in the UI; `test_every_calculator_is_cited_labelled_and_free_of_claims` |
| ENG-008 | Done | Named sign-off with hash; invalidation on item edit and on linked load-case edit (API test + walkthrough) |
| ENG-010 | Done (heuristic) | `test_stress_hints_on_demo_parts`: stepped-shaft sharp shoulder (high, D/d 1.25) and keyway edges; mounting plate 4 × Ø6.6 at 1.52·d and the unfilleted pocket floor; L-bracket R3 junction not flagged |
| ENG-011 | Done | Calculator + stack-up tool; Shigley Probs. 1-21 / 1-24 matched; RSS by hand derivation |
| ENG-012 | Done | `wording.py` guard: unit test on claim and non-claim phrases, scan of all generated text, API rejects claims in saved free text |
| ENG-009 | Not started | Out of scope (external FEA evaluation) |

## Calculator vs published example
Sources are the end-of-chapter solutions of Budynas & Nisbett, *Shigley's Mechanical Engineering Design* (11th ed.
for ch. 3, 4, 8, 10; 10th ed. for ch. 1, 7, 11), read from the university-hosted solution PDFs during this session,
plus the ISO 898-1 stress-area table.

| Calculator | Example | Published | Formwright |
|---|---|---|---|
| Tensile stress area | ISO 898-1 table, M3–M36 | 5.03 … 817 mm² | all 13 within 0.5 % (3-sig-fig table) |
| Beam, cantilever | Prob. 4-10 | y = 25.4 mm, M₀ = 9.5e6 N·mm, σ = 163 MPa | 25.43 mm, 9.5e6, 162.9 MPa |
| Beam, simply supported | Prob. 4-12 | y = 0.0978 in at load, 0.1027 in midspan | 0.09783, 0.10272 in |
| Beam (independent) | numerical double integration of M/EI | — | rel. 1e-4, both supports |
| Section properties (independent) | OCCT surface properties | — | A, I match to 1e-9 (rect), 1e-6 (tube) |
| Pin shear | Prob. 8-68 | τ = 32.6 kpsi, n = 2.30, bearing n = 4.06 / 1.31 | 32.59, 2.301, 4.06, 1.31 |
| Bolted joint | Prob. 8-33 (M12 9.8, steel + cast iron) | kb 518.8, km 1456 MN/m, C 0.263, Fi 41.1 kN, np 1.29, nL 11.1, n₀ 11.8 | 518.7, 1456.1, 0.2627, 41.08, 1.294, 11.06, 11.82 |
| Bolt fatigue | Prob. 8-52 (Goodman) | nf = 7.55 | 7.561 (solution rounds At, C) |
| Layered frusta | Probs. 8-19 / 8-20 | km 692.5 / 623.5, kb 292.1 / 247.6 MN/m | 692.6 / 623.7, 292.0 / 247.6 |
| Torque–preload | Prob. 8-30 | T = 115 lbf·ft | 115.0 lbf·ft (and the inverse) |
| Thread engagement | independent hand derivation (no published example) | Le = 5.88 mm (M10 bolt side) | exact |
| Press fit | Prob. 3-130 | p = 8333 psi, σt,o = 21 670 psi | 8333, 21 667 |
| Press fit | Prob. 3-131 (steel in cast iron) | p = 4599 psi, σt,o = 11 960 psi | 4599, 11 956 |
| Press fit (independent) | Lamé displacements close δ | — | 1e-9 |
| Shaft | Prob. 7-1(d) DE-Goodman, n = 2 | d = 27.27 mm | 27.270 mm (nf = 2.000) |
| Shaft Marin | Prob. 7-2 trial 1 | ka 0.69, kb 0.91, Se 54.9 kpsi | 0.688, 0.907, 54.6 kpsi (solution rounds factors) |
| Bearing | Probs. 11-8 / 11-9 / 11-10 | C10 = 20 kN / 5050 lbf / 24.9 kN | 20.00 kN / 5053 lbf / 24.86 kN |
| Bearing (independent) | ISO 281 hand derivation (roller, a1, aISO) | — | exact |
| Spring | Prob. 10-3 (music wire) | k 1.314 N/mm, Sut 1936, Ssy 871.2 MPa, KB 1.117, Fs 167.9 N, L0 162.8, L0cr 149.9 mm | 1.3142, 1935.9, 871.16, 1.1173, 167.86, 162.72, 149.91 |
| Stack-up | Probs. 1-21 / 1-24 | 0.020 ± 0.018 in; 4.012 ± 0.036 in | exact; RSS 0.011225 in by hand |

## Tests and gate
- `tests/test_engineering.py`: 31 tests, all pass in about 30 s. They cover the examples above, units, the SF
  requirement, the property-class size limits, the claim guard, citation/label completeness, geometry heuristics on
  three demo parts, and the API (402 entitlement, catalog, run errors, project link with mass/CoG/inertia,
  suggestions, checklist, load case, set, sign, edit invalidation, load-case invalidation, stack-ups, viewer 403,
  cross-workspace 404).
- `uv run ruff check src tests`: clean. `npx tsc --noEmit` and `npx vite build`: clean (engineering chunk 76 kB,
  19 kB gzip).
- Full suite `uv run pytest -q`: **115 passed** in 6 min 38 s (8 pre-existing asyncio pipe warnings).

## Browser walkthrough (port 8775, scratch data dir `fw-e2e-8775`)
God mode seeded 4 demo projects; the add-on was bought through simulated checkout; the module was opened at
`/app/modules/engineering?project=<Mounting plate>`.
- Project link: Aluminium 6061-T6 (guessed from the model's material note), mass 242.1 g, weight 2.374 N, CoG
  (0, 0, 4.83) mm, bbox 120 × 80 × 10 mm, Ixx/Iyy/Izz 135 / 301 / 432 kg·mm².
- Calculator 1, **pre-filled from the demo part** ("Check the M6 bolts in 4 × Ø6.6 holes"): M6 8.8, two 10 mm
  aluminium layers (mating layer marked assumed), P = 1.5 kN, SF 2 per "Company standard ES-001 §4.2". Results:
  As 20.12 mm², kb 251.8 kN/mm, km 372.0 kN/mm, C 0.4037, Fi 8754 N, T 10.5 N·m, np 1.25 (**below** required 2),
  nL 4.82, n₀ 9.79.
- Calculator 2, beam (defaults, SF 1.5 per "Customer spec CS-12 §3"): δmax 0.773 mm, σmax 60 MPa.
- Calculator 3, bearing (C = 14 kN, P = 2 kN, 1500 rev/min, target 20 000 h): L10h 3811 h, required C 24.3 kN,
  target check below requirement.
- All three were added to the set "Design checks" (status Unsigned: not for release) and signed by Founder (owner),
  hash `881eb4e4a6ad…`, self-check flag shown. The level changed to Verified calculation.
- The bolt load was edited 1.5 → 2.5 kN from the set and saved. The set showed **"Signature invalid: edited after
  sign-off. Unsigned: not for release"**, the level went back to Preliminary estimate, and history recorded
  "Edited inputs of 'M6 bolts, 4 × Ø6.6 pattern' after sign-off by Founder".
- Also exercised: a load case with model self-weight; a stack-up (mean 0.4, WC 0.25…0.55, RSS 0.288…0.512 mm,
  contributions 80/20 %); the failure-mode review of the plate (7 modes; hints: 4 × Ø6.6 at 1.52·d, 4 curved and 4
  straight sharp pocket-floor edges); the stepped-shaft review (high: shoulder Ø25 → Ø20, sharp; 8 straight keyway
  edges; 2 curved shoulder edges) and a shaft check pre-filled from the model (d = 20 mm, Sut/Sy of 1045 CD: nf 1.82,
  ny 5.20, d_min 20.65 mm); library; modules page showing Engineering Advisor **Live**.
- Final run: **0 console/page errors**. Screenshots were read. Fixes made from them:
  - working steps changed from a cramped 4-column table to a numbered list with equation and substitution lines
  - torque shown in N·m and stiffness in kN/mm
  - duplicate hole-edge hints grouped into one
  - Basis select widened
  - invalid numbers are now sent as text so the server answers "must be a number"
  - clicks scroll targets into view (script)

## Known limits
- Calculators are hand-calculation methods with the stated assumptions: Euler–Bernoulli beams of uniform section,
  concentric bolt loads (no prying, no VDI 2230 embedding/thermal terms), infinite-life Goodman for shafts, static
  springs, and basic thread dimensions (tolerance classes not applied) for engagement.
- Stress-concentration hints rank by geometry only. Kt is never computed from geometry (it is a chart input). The
  sharp-edge scan flags every re-entrant edge, including unloaded ones.
- Pre-fill is heuristic: the bolted-joint mating layer is assumed identical to the part, the beam uses the bbox as a
  uniform section, and the material may be guessed from the model's text note (shown).
- Some table values were transcribed from public references or textbooks in this session (ISO tables, Shigley
  tables). They are marked "verify against the current edition". Materials data is typical or spec-minimum, as
  labelled.
- Stack-ups are stored and computed, but to sign one it has to go into a calculation set through the stack-up
  calculator (the tool page says so).
- Studio entry points are not added (Design Studio files are off limits); see below.
- PDF/print export of a signed calculation set is not built.

## Parked decisions (default used)
- **PD-ENG-1 Self-sign-off**: may the author of a calculation sign it? *Default:* allowed, but recorded as
  `self_check: true` and shown in the banner. Alternative: require a second engineer (four-eyes) for
  release-relevant sets.
- **PD-ENG-2 Who may sign**: *default* engineer, admin and owner roles. Viewers can't, and nobody can while
  impersonating. A dedicated "checker / approver" role may be wanted later.
- **PD-ENG-3 Standards licensing**: ISO and Shigley table values are transcribed and cited, not licensed copies.
  *Default:* ship with "verify" labels (same stance as PD-13).
- **PD-ENG-4 Default required safety factor**: *default* none. The user must enter the value and its source every
  time; no house default is offered.
- **PD-ENG-5 Pricing/plan**: the add-on stays at $29/mo and is not added to the Pro/Team plan module lists (PD-02
  pricing is the founder's call).

## Studio entry point I recommend (for the master to add)
1. **CommandManager → "Evaluate" tab → "Engineering checks"**, which opens `/app/modules/engineering?project=<id>`.
   Also add the same item to the project's ⋯ menu.
2. **Mass properties panel**: an "Use in load case" link to `/app/modules/engineering?project=<id>&tab=loads`.
3. **Feature tree context menu on a hole pattern**: "Check bolts…" opening the module with the project (the module
   shows the matching pre-fill suggestion for that pattern).
4. Optional badge in the Studio header when the project has signed or invalidated calculation sets (from
   `GET /api/m/engineering/projects`, fields `sets` / `signed`).
