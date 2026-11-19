# Validation Plan

Principle: **renders and vision critique are signals; deterministic geometric checks gate acceptance.** Nothing here has been run yet.

## 1. Check catalogue (precision CAD)

| Check ID | Check | Method | Gate? |
|---|---|---|---|
| CHK-01 | Spec schema valid, units explicit (mm) | Pydantic validation | Yes |
| CHK-02 | Exactly N solids (M1: 1), shape valid | `BRepCheck_Analyzer`, solid count | Yes |
| CHK-03 | Closed shells / no free edges | Topology exploration | Yes |
| CHK-04 | Bounding box matches spec | ±0.01 mm | Yes |
| CHK-05 | Volume matches independent analytic estimate | ±0.1 % (exact features); ±1 % when fillets present | Yes |
| CHK-06 | Feature census: hole count, diameters, depths, pocket dims | Cylindrical/planar face analysis vs spec | Yes |
| CHK-07 | STEP round-trip | Export → reimport: solids, volume (rel. 1e-6), bbox equal | Yes |
| CHK-08 | Determinism | Same spec twice → identical geometry fingerprint (volume, bbox, face/edge counts, STEP hash excluding header timestamp) | Yes |
| CHK-09 | Metamorphic | Param change → expected bbox/volume delta (property tests, hypothesis) | Yes (CI) |
| CHK-10 | Render produced | 4 views, fixed cameras, non-empty, part in frame | Yes |
| CHK-11 | Vision critique | Model compares views vs requirements; output structured findings with observed vs uncertain | Advisory |
| CHK-12 | Drawing consistency | Every spec'd dimension appears once; each dimension tagged spec/inferred; view projections match model bbox | Yes |
| CHK-13 | DFM rules (CNC) | Min internal corner radius vs tool, hole depth/diameter ratio, thin walls, standard drill sizes | Advisory, reported |
| CHK-14 | Budget | iterations ≤ 3, wall time ≤ 120 s, LLM cost ≤ job cap | Yes |

**When CHK-07/08 run (PS-01).** An agent build returns its report after CHK-02..05 (and CHK-09/10); CHK-07 (with
the STEP/STL/GLB exports) and CHK-08 run straight after on the same warm worker, in the background, and are shown
as pending. They still gate: `status.json` carries `pending_checks` and `verified` (`runner.is_verified`), and a
build counts as verified only when every gating check has run and passed. The agent turn's verdict, run record,
notifications, the release gate and modules reading `part.step` wait for them; a failure is reported to the agent at
its next build or as one automatic follow-up at the end of the turn. Interactive edits defer CHK-07 the same way and
skip CHK-08 (the structure was verified at the agent build).

## 2. Vertical slice VS-1 (proposed for M1)

**Demo:** user types
> "6061 aluminium mounting plate, 120 × 80 × 10 mm, four M6 clearance holes 10 mm in from each corner, centred rectangular pocket 40 × 30 × 4 mm deep with 3 mm corner radius, 1 mm chamfer on top outer edges."

**Pipeline:** text → LLM → Part Spec JSON (+ assumptions, open questions) → echo-back for approval (auto-approve in CLI flag) → compiler → build123d → checks CHK-01…10 → renders → vision critique (optional) → revise spec if a gate fails (max 3) → drawing (CHK-12) → DFM notes → artifact bundle + report.

**Artifacts:** `spec.json`, `model.py` (generated, readable), `part.step`, `part.stl`, `part.glb`, `views/{iso,front,top,right}.png`, `drawing.svg` + `drawing.pdf`, `checks.json`, `dfm.json`, `run.json` (model IDs, tokens, cost, timings, versions).

**Interface:** M1a = CLI (`aicad make "<prompt>"`); M1b = minimal web UI (prompt box, viewer, parameter panel, downloads).

**Acceptance criteria (measurable)**
1. Golden spec (no LLM) passes CHK-01…10 and CHK-12 on every CI run; zero paid calls in CI.
2. Hand-computed expected volume for the golden plate matches within 0.1 % (fillet-free variant) and 1 % (with pocket corner radii/chamfer computed analytically).
3. STEP opens in SOLIDWORKS 2025 and Creo 11 (manual check, screenshot evidence) with correct units and dimensions measured at 3 locations.
4. Metamorphic suite: ≥ 50 random parameter sets within declared ranges all build valid, single-solid parts or fail with a typed, user-readable error (no crashes).
5. LLM benchmark (opt-in): 20 original prompts in the plate/bracket family; report first-pass and ≤3-iteration pass rates on all gating checks. **Target** ≥ 80 % within 3 iterations — a target, not a claim.
   Harness: `src/aicad/eval/` (plate, bracket, shaft, flange, enclosure; 4 each). A case passes only when the final build's gating checks pass **and** bbox (orientation-free, ±max(0.5 mm, 0.5 %)), volume (±1 %) and the cylinder census match the case's hand-computed expectation; the agent's own summary and self-review are never scored. Run: `aicad bench --dry` (synthetic replays of the reference solutions: harness check, not an agent measurement), `aicad bench --live --record bench-cassettes [--only P01,B02]` (spends tokens; prints the estimate and asks first), `aicad bench --replay bench-cassettes` (re-score recordings offline).
6. Each run records latency per stage and cost; p50 end-to-end latency reported (no target fixed until measured).
7. Parameter edit (e.g. length 120 → 150) regenerates model, renders, and drawing deterministically in < 10 s without an LLM call.
8. Drawing: 3 orthographic views + iso, all spec dimensions present, title block with material, units, revision, "NOT APPROVED FOR MANUFACTURE" banner.

**Out of scope for VS-1:** image/PDF input, assemblies, threads (modelled as cosmetic callouts only), GD&T, FEA, multi-user, cloud deployment.

## 3. Golden fixtures (all original; provenance recorded)

| Fixture | Milestone | Purpose |
|---|---|---|
| FX-01 mounting plate (VS-1) | M1 | Holes, pocket, chamfer |
| FX-02 L-bracket with gusset | M1/M2 | Multi-body union, fillets |
| FX-03 stepped shaft with keyway | M2 | Revolve, turning DFM |
| FX-04 bolted bracket assembly (Toolbox bolts, washers, nuts; cosmetic threads) | M3 | Fasteners, length rule, BOM, interference, clearances — `specs/fixtures/fx04_bolted_bracket/` |
| FX-05 keyed shaft in two bearings in a housing, with a keyed gear | M3 | Concentric mates, freedoms (3), contacts, centre of mass, full-turn sweep — `specs/fixtures/fx05_keyed_shaft/` |
| FX-06 hinged arm on a clevis base (revolute joint, limits) | M3 | Distance/flush mates, motion range vs hand contact angles — `specs/fixtures/fx06_hinged_arm/` |

FX-04..06 (ASM-012, 2026-11-19) replaced the earlier placeholder ideas (enclosure, flange, shock-absorber-like); all three
are newly designed for Formwright, with provenance files and hand-computed checks (`specs/fixtures/README.md`).

## 4. Engineering advice validation levels

`Recommended check` → `Preliminary estimate` (hand calc, stated assumptions) → `Verified calculation` (deterministic code, unit-tested, reviewed) → `Validated simulation` (external validated solver + correlation evidence). UI must show level; safety-critical outputs require named engineer sign-off.

How the levels are used across the product (one vocabulary, `aicad.deliverables`, 2026-11-17):
- **Measured from the model**: a deterministic measurement of the geometry (mesh is watertight, wall is 1.2 mm, hole is
  Ø14 through). It states a fact about the model, not an engineering judgement. Print checks and DFM measurements use it.
- **Recommended check** / **Preliminary estimate**: advice and unsigned calculations (DFM findings, calculators).
- **Verified calculation** is reserved for a calculation set **signed by a named engineer on the current build**. The
  badge itself says who checked: "Verified calculation · self-checked" (the signer authored items in the set) or
  "Verified calculation · independent check". When the model changes after sign-off the set reads "Model changed
  since sign-off: re-check" and drops to Preliminary estimate; the old signature stays in its history.
- Every downstream output (drawing, DFM analysis, calculation sign-off, print export) records the build it was made
  from; when the model changes it is badged "Model changed" with a one-click update, never silently replaced. Releases
  (Rev A, B, …) freeze one build; later builds show "Draft: changes since Rev A".

## 5. Mesh Studio benchmark protocol (M5, not started)

Same 15 prompts run through (a) procedural Blender scripts with render–critique loop and (b) ≥ 1 generative 3D service/model. Measure: human-rated prompt fidelity (blind, 1–5), editability (can a requested change be applied in ≤ 2 turns), watertightness/manifold rate, triangle count, wall time, cost per asset. Verify each service's terms before sending prompts.

## 6. Evidence log

| Date | Item | Evidence | Result |
|---|---|---|---|
| 2026-11-16 | GOV-001 environment audit | SESSION_LOG 2026-11-16 §A | Done |
| 2026-11-16 | GOV-003 punch-list coverage | PUNCH_LIST §Trace; item count by script (195) | Done |
| 2026-11-16 | ARC-010 FX-01 spike: CHK-02..08 | `out/fx01_plate/status.json`; `tests/test_plate.py` | All pass; volume rel err 4.9e-16 |
| 2026-11-16 | VS-1 criterion 4 (random specs) | `test_random_specs_build_valid_or_fail_cleanly` | Pass (80 seeded, ≥50 built) |
| 2026-11-16 | UX-008 live viewer rebuild | headless Chrome screenshots, 120→150 mm | Pass (visual + panel values) |
