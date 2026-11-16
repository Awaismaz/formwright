# Punch List

Last updated: 2026-11-16 (Session 1i, project skills). Synchronized with `ROADMAP.md`.

## Legend

- **Priority:** P0 = required for current milestone / blocks others · P1 = important, next milestone · P2 = later / opportunistic
- **Status:** Backlog · Ready (deps met, can start) · In Progress · Blocked (reason in Notes) · Done (objective evidence required)
- **Scope:** MVP = part of M1 vertical slice · LT = long-term
- **Owner:** Founder (product/commercial decisions, pilots) · Eng (implementation; Claude Code + founder review) · Counsel (legal)
- **Definition of done (all items):** acceptance criteria met; evidence column links to test/artifact/commit/doc; docs updated; no unresolved P0 warnings. Engineering-related items additionally require explicit advice level (VALIDATION §4).
- Evidence links to commits are not possible until the directory is a git repository (R-OPS-03).

## Summary

| Module | Items | Done | In Progress | Blocked |
|---|---|---|---|---|
| GOV / ARC / LEG / COM | 33 | 16 | 1 | 7 |
| CAD / IO / PRN / DRW / ASM | 67 | 0 | 8 | 2 |
| AGT / EVAL | 22 | 1 | 2 | 1 |
| MFG / ENG | 24 | 0 | 0 | 0 |
| MSH | 12 | 0 | 0 | 0 |
| PLT / SEC / UX / INF / DOC | 39 | 1 | 4 | 1 |
| **Total** | **212** | **38** | **33** | **11** |

Implemented so far: the **Formwright platform** (auth, workspaces, roles, onboarding, tours, billing with tokens and add-ons, admin console, God mode) and the live **Design Studio** (AI agent, checks, live viewer, parameter edits, revisions). Other CAD modules are honest **Preview** placeholders (ADR-016). Per-module rows above are not re-split; the Total row is authoritative.

---

## Governance, architecture, legal, commercial

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GOV-001 | Governance | Audit repo + runtime (OS, Python, Node, pkg mgrs, Docker, GPU, CAD apps) | P0 | Done | M0 | MVP | Eng | — | Findings recorded with commands run | SESSION_LOG 2026-11-16 §A | Repo empty; no Docker/WSL distro |
| GOV-002 | Governance | Create doc skeleton (7 docs) | P0 | Done | M0 | MVP | Eng | — | All 7 files exist and cross-reference | `docs/` | |
| GOV-003 | Governance | Initial traceable punch list covering master prompt §2 | P0 | Done | M0 | MVP | Eng | GOV-002 | Every §2 bullet maps to ≥1 ID (see trace table at end) | This file §Trace | |
| GOV-004 | Governance | Initialize git repo, `.gitignore`, commit docs | P0 | Done | M0 | MVP | Eng | approval | `git log` shows initial commit | `.git` + initial commit |  |
| GOV-005 | Governance | Session start/end ritual (read punch list + log; update both) | P0 | In Progress | All | MVP | Eng | GOV-002 | Every session has a log entry with completed/blocked/next/decision | SESSION_LOG; `formwright-ship` skill | Ongoing |
| GOV-006 | Governance | Project Claude Code skills for repeatable workflows (ship, review, studio feature, kernel, toolbox, design agent, module graduation, e2e, dev setup) | P1 | Done | All | MVP | Eng | GOV-005 | Skills committed in repo; CLAUDE.md lists them | `.claude/skills/*/SKILL.md`; SESSION_LOG 2026-11-16 (i) | Skills encode recipes from code as of 74dfc5d; e2e template not yet executed (toolchain missing on new machine) |
| ARC-001 | Architecture | Initial critical architecture recommendation | P0 | Done | M0 | MVP | Eng | GOV-001 | ARCHITECTURE §1 with stack, changes, risks, wedge | ARCHITECTURE.md | Draft; approval pending |
| ARC-002 | Architecture | Approve wedge + direction (ADR-001/002/003) | P0 | Done | M0 | MVP | Founder | ARC-001 | ADRs marked Accepted | DECISIONS ADR-001/002/003/005 Accepted 2026-11-16 | Founder: "Go ahead" |
| ARC-003 | Architecture | Kernel comparison build123d/CadQuery/FreeCAD/OCCT | P0 | Done | M0 | MVP | Eng | — | Table with all §6 criteria | ARCHITECTURE §3.1 | Qualitative; spike ARC-010 verifies |
| ARC-004 | Architecture | Web app vs plugin comparison | P1 | Done | M0 | MVP | Eng | — | Table + decision | ARCHITECTURE §3.2 | |
| ARC-005 | Architecture | Code-gen vs DSL vs hybrid comparison | P0 | Done | M0 | MVP | Eng | — | Table + decision | ARCHITECTURE §3.4 | |
| ARC-006 | Architecture | Mesh approach comparison | P2 | Done | M0 | LT | Eng | — | Table + deferral | ARCHITECTURE §3.3 | Benchmark later (MSH-010) |
| ARC-007 | Architecture | Deployment comparison | P1 | Done | M0 | MVP | Eng | — | Staged plan | ARCHITECTURE §3.5 | |
| ARC-008 | Architecture | Drawings/sketch/mates/history approach survey | P1 | Done | M0 | MVP | Eng | — | Table per area | ARCHITECTURE §3.6 | |
| ARC-010 | Architecture | Geometry spike: uv venv Py3.12 + build123d; build FX-01 from hand-written code; STEP export/reimport; volume/bbox checks | P0 | Done | M0 | MVP | Eng | ARC-002 | FX-01 passes CHK-02..08; timings recorded | `tests/test_plate.py` (20 tests pass); `out/fx01_plate/status.json`: CHK-02..08 pass, vol rel err 5e-16, build+checks 0.5 s | Hand-written build123d, no DSL yet |
| ARC-011 | Architecture | Part Spec DSL v0 schema design (features, params, IDs, selectors, assumptions, open questions) | P0 | Backlog | M0 | MVP | Eng | ARC-010 | JSON schema + 3 example specs validate; reviewed by founder | — | Deprioritised by ADR-013: DSL now optional (structured param editing / LLM-free regeneration) |
| ARC-012 | Architecture | Python 3.12 vs 3.13 wheel compatibility check | P2 | Done | M0 | MVP | Eng | ARC-010 | Decision recorded in ADR-005 | ADR-005: Py 3.12.13 chosen; 3.13 not tested | Revisit if a dependency requires 3.13 |
| LEG-001 | Legal | Record licenses of direct deps (metadata) | P0 | Done | M0 | MVP | Eng | — | List with versions | SESSION_LOG §A; ARCHITECTURE §5 | Metadata only, not legal review |
| LEG-002 | Legal | Transitive dependency license audit (pip-licenses or similar) + SBOM | P0 | Backlog | M0 | MVP | Eng | ARC-010 | Report of every package/license; copyleft flagged | — | |
| LEG-003 | Legal | Counsel review: OCCT LGPL-2.1 in SaaS and in any distributed desktop/plugin | P0 | Blocked | M0 | MVP | Counsel | LEG-002 | Written guidance | — | Needs counsel; R-LIC-01/02 |
| LEG-004 | Legal | Counsel review: Blender GPL / FreeCAD LGPL / SolveSpace GPL use patterns | P2 | Blocked | M5 | LT | Counsel | LEG-002 | Written guidance | — | Needs counsel |
| LEG-005 | Legal | Review Anthropic commercial/API terms (output ownership, retention, training, embedding) | P0 | Blocked | M1 | MVP | Counsel | — | Summary + counsel sign-off | — | Needs counsel |
| LEG-006 | Legal | Review SOLIDWORKS/Creo API & EULA terms for automation/bridges | P1 | Blocked | M2 | LT | Counsel | — | Written guidance | — | Needs counsel |
| LEG-007 | Legal | IP checklist: assignment, contractor agreements, confidentiality, trademark search, patents-where-justified | P1 | Blocked | M1 | MVP | Counsel | — | Checklist drafted (not legal advice) and reviewed | — | Draft can be prepared by Eng; sign-off by counsel |
| LEG-008 | Legal | Privacy, data retention, DPA template for pilots | P1 | Blocked | M2 | LT | Counsel | — | DPA + retention policy | Draft privacy/terms/AUP pages (marked Draft) | Needs counsel (PD-05) |
| LEG-009 | Legal | Export-control (ITAR/EAR) screening process for uploads | P1 | Blocked | M2 | LT | Counsel | — | Screening policy + upload attestation | — | |
| LEG-010 | Legal | AI-assisted authorship + provenance record for code and fixtures | P1 | Backlog | M1 | MVP | Eng | GOV-004 | PROVENANCE section in repo; fixtures carry provenance | — | |
| COM-001 | Commercial | 5–10 pilot interviews (consultancies, shops, independent PEs) | P0 | Backlog | M1 | MVP | Founder | — | Notes per interview; wedge W3 vs W4 decision | — | Validates AS-01/02/04/05 |
| COM-002 | Commercial | Pricing hypotheses + willingness-to-pay test | P1 | Backlog | M2 | LT | Founder | COM-001 | Documented hypotheses and results | — | |
| COM-003 | Commercial | Pilot onboarding pack + success metrics (time saved) | P1 | In Progress | M2 | LT | Founder | COM-001 | Pack exists; metrics captured for ≥3 pilots | Onboarding wizard, tours, checklist, CUSTOMER_JOURNEY.md | Pilot success metrics TBD |
| COM-004 | Commercial | Pilot telemetry (consented) | P1 | In Progress | M2 | LT | Eng | PLT-008 | Opt-in telemetry dashboard | JourneyEvent instrumentation + Admin funnel | Consent banner pending (PD-05) |
| COM-005 | Commercial | Billing/usage controls | P2 | In Progress | M4 | LT | Eng | PLT-009 | Usage caps enforced per tenant | Plans/add-ons/token packs, Stripe + simulated checkout; `tests/test_platform.py` | Stripe test mode needs keys (PD-06) |
| COM-006 | Commercial | Support workflow (issue intake, SLAs for pilots) | P2 | In Progress | M2 | LT | Founder | COM-003 | Documented process | Help center, feedback form, support mailto | Ticketing/SLAs pending |
| COM-007 | Commercial | Stripe test-mode end-to-end (keys, webhook, portal) | P0 | Blocked | M2 | LT | Founder | PD-06 | Real test checkout updates plan via webhook | — | Code done; needs Stripe account |

## A. AI Design Studio — geometry & CAD

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CAD-001 | CAD | Spec compiler: base block (box/extruded profile) | P0 | In Progress | M1 | MVP | Eng | ARC-011 | Unit tests: dims, volume exact | `src/aicad/parts/plate.py` (hand-coded) | Spec compiler not built yet |
| CAD-002 | CAD | Holes: through/blind, clearance tables (ISO metric, UNC/UNF) | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Census check CHK-06 passes | Through holes in FX-01; CHK-06 census | Blind holes + clearance tables pending |
| CAD-003 | CAD | Hole patterns (rect, circular, linear) | P0 | Backlog | M1 | MVP | Eng | CAD-002 | Count/positions within 0.01 mm | — | |
| CAD-004 | CAD | Rectangular/rounded pockets (blind/through) | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Volume analytic match | Rounded blind pocket in FX-01; analytic volume match |  |
| CAD-005 | CAD | Slots | P1 | Backlog | M1 | MVP | Eng | CAD-001 | Volume analytic match | — | |
| CAD-006 | CAD | Edge fillets/chamfers via semantic edge selectors | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Valid solid; volume within 1 % | Top-perimeter chamfer via edge group selector | Fillets + semantic selectors pending |
| CAD-007 | CAD | Semantic selectors & stable feature IDs (topological-naming mitigation) | P0 | Backlog | M1 | MVP | Eng | ARC-011 | Param change keeps selector → same logical faces (tests) | — | R-TEC-04 |
| CAD-008 | CAD | Parameter table with ranges/units; derived params | P0 | Backlog | M1 | MVP | Eng | ARC-011 | Out-of-range rejected with typed error | — | |
| CAD-009 | CAD | Deterministic regeneration + geometry fingerprint | P0 | In Progress | M1 | MVP | Eng | CAD-001 | CHK-08 passes | CHK-08: fingerprint + STEP bytes identical on rebuild | Not yet via spec compiler |
| CAD-010 | CAD | Emit readable build123d source per spec (for transparency/export) | P1 | Backlog | M1 | MVP | Eng | CAD-001 | Running emitted source reproduces fingerprint | — | |
| CAD-011 | CAD | Natural language → Part Spec (via AGT) with controllable dims & intent | P0 | Backlog | M1 | MVP | Eng | AGT-003 | Benchmark EVAL-003 pass-rate reported | — | §2.A bullet 1 |
| CAD-012 | CAD | Conversational revisions: spec diffs, undo/redo, version list | P0 | In Progress | M1 | MVP | Eng | CAD-009 | Revision N reproducible; undo restores fingerprint | Conversational revisions + revision snapshots + restore + param edits | Undo/redo of single steps pending |
| CAD-020 | CAD | Vector-PDF drawing → spec (dimension text extraction, view association) | P1 | Backlog | M2 | LT | Eng | COM-001 | 10 original drawings: dims recovered, ambiguities flagged | — | Candidate W3 |
| CAD-021 | CAD | Raster drawing → spec (OCR + vision), flag missing views/tolerances | P2 | Backlog | M2 | LT | Eng | CAD-020 | Ambiguity list on every run | — | |
| CAD-022 | CAD | Image/photo/sketch → spec with explicit missing-dimension questions | P1 | Backlog | M2 | LT | Eng | AGT-006 | Never invents scale; asks for ≥1 reference dim | — | §2.A bullet 2 |
| CAD-023 | CAD | Additional part families: L-brackets/gussets (FX-02) | P1 | Backlog | M2 | LT | Eng | CAD-006 | FX-02 passes checks | — | |
| CAD-024 | CAD | Revolved parts: shafts, steps, grooves, keyways (FX-03) | P1 | Backlog | M2 | LT | Eng | CAD-001 | FX-03 passes checks | — | |
| CAD-025 | CAD | Shells, bosses, ribs, draft (enclosures, FX-04) | P2 | Backlog | M2 | LT | Eng | CAD-006 | FX-04 passes checks | — | |
| CAD-026 | CAD | Sheet metal features (flange, bend, flat pattern) | P2 | Backlog | M4 | LT | Eng | CAD-001 | Flat pattern length within K-factor tolerance | — | |
| CAD-027 | CAD | Cosmetic threads + thread callouts | P1 | Backlog | M2 | LT | Eng | CAD-002 | Thread metadata in STEP/drawing | — | Modelled threads later |
| CAD-028 | CAD | Approval gate: interpreted requirements echo-back before build | P0 | Backlog | M1 | MVP | Eng | AGT-003 | User sees assumptions; can edit before build | — | R-TEC-01 |
| CAD-030 | CAD | STEP import as reference geometry (clearly labelled non-parametric) | P1 | Backlog | M2 | LT | Eng | IO-005 | Imported solids marked "dumb solid" in UI and metadata | — | Honesty requirement |
| CAD-060 | CAD | Sketch entities + constraint solver evaluation (planegcs, SolveSpace, own) | P2 | Backlog | M5 | LT | Eng | LEG-004 | ADR with license-cleared choice | — | |
| CAD-061 | CAD | Feature tree UI-backed native history (edit any feature, regenerate) | P2 | Backlog | M5 | LT | Eng | CAD-007 | Edit mid-tree → valid regeneration in tests | — | §2.A bullet 7 |
| CAD-062 | CAD | Feature graph revision model (branching, compare) | P2 | Backlog | M5 | LT | Eng | CAD-012 | Diff two revisions visually + structurally | — | |
| CAD-070 | CAD | SOLIDWORKS export pathway via STEP with explicit disclosure (no native history) | P1 | Backlog | M2 | LT | Eng | IO-001 | Disclosure text in UI and docs; SW 2025 opens file | — | §2.A bullet 9 |
| CAD-071 | CAD | SOLIDWORKS API bridge spike (feature recreation from spec) | P2 | Blocked | M3 | LT | Eng | LEG-006 | Spike report: feasibility, licensing, deployment | — | Blocked on API/EULA review |
| CAD-072 | CAD | Creo bridge spike | P2 | Blocked | M5 | LT | Eng | LEG-006 | Spike report | — | Blocked on API/EULA review |

### IO — formats

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IO-001 | IO | STEP export (AP214/AP242), units mm, part name/metadata | P0 | In Progress | M1 | MVP | Eng | CAD-001 | CHK-07 passes; opens in SW 2025 + Creo 11 | CHK-07 round-trip pass; byte-identical STEP with fixed timestamp (`test_step_bytes_deterministic`) | Not yet opened in SW/Creo |
| IO-002 | IO | STL export with tolerance control | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Watertight mesh; deviation ≤ tol | `part.stl` exported, tol 0.01 mm | Watertight/deviation checks pending |
| IO-003 | IO | GLB export for web viewer | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Loads in Three.js; scale correct | `model.glb` loads in Three.js viewer (screenshot, session log) | Unit scale inferred in viewer; explicit check pending |
| IO-004 | IO | 3MF export | P1 | Backlog | M2 | LT | Eng | IO-002 | Opens in a slicer; units preserved | — | |
| IO-005 | IO | STEP import + validation (size limits, isolated parse) | P1 | Backlog | M2 | LT | Eng | SEC-005 | Malformed files rejected safely | — | |
| IO-006 | IO | Assembly STEP export (hierarchy, placements) | P1 | Backlog | M3 | LT | Eng | ASM-001 | Reimport preserves tree & transforms | — | |
| IO-007 | IO | DXF export of drawings/flat patterns | P2 | Backlog | M2 | LT | Eng | DRW-001 | Opens in CAD; scale 1:1 | — | ezdxf (MIT) candidate |
| IO-008 | IO | Coordinate system + unit preservation tests across all formats | P0 | Backlog | M1 | MVP | Eng | IO-001 | Round-trip test matrix green | — | |

### PRN — 3D printing preparation

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| PRN-001 | Print | Manifold/watertight validation | P1 | Backlog | M2 | LT | Eng | IO-002 | Detects seeded defects in test meshes | — | trimesh/manifold3d candidates |
| PRN-002 | Print | Wall thickness analysis | P1 | Backlog | M2 | LT | Eng | PRN-001 | Flags walls < threshold on fixtures | — | |
| PRN-003 | Print | Overhang/support guidance | P2 | Backlog | M2 | LT | Eng | PRN-001 | Overhang map vs angle threshold | — | |
| PRN-004 | Print | Orientation suggestions (support area, height, strength axis) | P2 | Backlog | M4 | LT | Eng | PRN-003 | Ranked options with rationale | — | |
| PRN-005 | Print | Mesh repair | P2 | Backlog | M4 | LT | Eng | PRN-001 | Repairs seeded defects; reports changes | — | |
| PRN-006 | Print | "Not slicer-verified" disclosure unless checks run | P1 | Backlog | M2 | LT | Eng | PRN-001 | UI text present | — | Honesty requirement |

### DRW — 2D manufacturing drawings

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DRW-001 | Drawing | HLR orthographic views (front/top/right) + iso to SVG | P0 | Backlog | M1 | MVP | Eng | CAD-001 | View extents match bbox (CHK-12) | — | |
| DRW-002 | Drawing | Dimensions from spec features, tagged spec/inferred | P0 | Backlog | M1 | MVP | Eng | DRW-001 | Every spec dim appears once | — | R-TEC-03 |
| DRW-003 | Drawing | Hole callouts (dia, depth, qty) | P0 | Backlog | M1 | MVP | Eng | DRW-002 | Callouts match census | — | |
| DRW-004 | Drawing | Title block: material, units, scale, revision, "NOT APPROVED" banner | P0 | Backlog | M1 | MVP | Eng | DRW-001 | Fields populated from spec/run | — | |
| DRW-005 | Drawing | PDF export (license-cleared library) | P0 | Backlog | M1 | MVP | Eng | DRW-001, LEG-002 | PDF renders identically to SVG | — | |
| DRW-006 | Drawing | Layout/overlap check (no dimension collisions) | P1 | Backlog | M1 | MVP | Eng | DRW-002 | Zero bbox overlaps of text on fixtures | — | |
| DRW-010 | Drawing | Section views | P1 | Backlog | M2 | LT | Eng | DRW-001 | Section of FX-03 correct | — | |
| DRW-011 | Drawing | Detail views | P2 | Backlog | M2 | LT | Eng | DRW-001 | | — | |
| DRW-012 | Drawing | General tolerances block + per-dim tolerances from spec | P1 | Backlog | M2 | LT | Eng | DRW-002 | Only approved tolerances shown as such | — | |
| DRW-013 | Drawing | GD&T frames where specified (never invented) | P2 | Backlog | M4 | LT | Eng | DRW-012 | Frames only from explicit input | — | |
| DRW-014 | Drawing | BOM table on assembly drawings | P1 | Backlog | M3 | LT | Eng | ASM-008 | BOM matches assembly tree | — | |
| DRW-015 | Drawing | Associative regeneration on model change + change tracking (rev table) | P1 | Backlog | M2 | LT | Eng | CAD-012 | Param change → drawing updates; rev row added | — | §2.A bullet 5 |
| DRW-016 | Drawing | STEP-in → auto drawing (wedge W4 candidate) | P1 | Backlog | M2 | LT | Eng | IO-005, DRW-002 | Pilot-rated usefulness ≥ agreed bar | — | Inferred dims only, clearly labelled |

### ASM — assemblies

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ASM-001 | Assembly | Multi-part project model (parts, subassemblies, instances) | P1 | Backlog | M3 | LT | Eng | CAD-012 | Tree persisted and reloaded | — | |
| ASM-002 | Assembly | Relative placement / joints (build123d joints) | P1 | Backlog | M3 | LT | Eng | ASM-001 | FX-05 placed correctly | — | |
| ASM-003 | Assembly | Mate/constraint solver (coincident, concentric, distance, angle) | P1 | Backlog | M3 | LT | Eng | ASM-002 | Solver tests; over/under-constraint reported | — | |
| ASM-004 | Assembly | Interference/collision check | P1 | Backlog | M3 | LT | Eng | ASM-002 | Seeded interferences detected with volumes | — | |
| ASM-005 | Assembly | Clearance/fit checks | P1 | Backlog | M3 | LT | Eng | ASM-004 | Min clearance reported per mate | — | |
| ASM-006 | Assembly | DOF analysis where feasible | P2 | Backlog | M3 | LT | Eng | ASM-003 | FX-06 DOF count correct | — | |
| ASM-007 | Assembly | Exploded views | P2 | Backlog | M3 | LT | Eng | ASM-002 | Render + drawing view | — | |
| ASM-008 | Assembly | BOM generation (qty, material, standard parts) | P1 | Backlog | M3 | LT | Eng | ASM-001 | BOM matches tree | — | |
| ASM-009 | Assembly | Standard fastener library (original/licensed data) | P1 | Backlog | M3 | LT | Eng | CAD-027 | Dims match cited standard tables | — | Provenance required |
| ASM-010 | Assembly | AI assembly planning from description | P2 | Backlog | M3 | LT | Eng | ASM-003, AGT-003 | FX-05 from text | — | |
| ASM-011 | Assembly | Motion range check / simple kinematics | P2 | Backlog | M5 | LT | Eng | ASM-006 | Range-of-motion collision sweep | — | |
| ASM-012 | Assembly | Golden fixtures FX-04/05/06 (original designs) | P1 | Backlog | M3 | LT | Eng | ASM-001 | Fixtures with provenance + checks | — | |

## Agent orchestration & evaluation

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AGT-001 | Agent | LLMProvider interface (structured output, vision, metering) | P0 | Backlog | M1 | MVP | Eng | ARC-011 | Typed interface + tests | — | ADR-009 |
| AGT-002 | Agent | Recorded/replay provider for CI (zero paid calls) | P0 | Backlog | M1 | MVP | Eng | AGT-001 | CI passes offline | — | |
| AGT-003 | Agent | Requirement interpretation → Part Spec + assumptions + open questions | P0 | Backlog | M1 | MVP | Eng | AGT-001 | Schema-valid output on benchmark prompts | — | |
| AGT-004 | Agent | Generate–check–render–critique–revise loop (shared orchestrator) | P0 | In Progress | M1 | MVP | Eng | AGT-003, EVAL-001 | Bounded; stops on criteria/limits; all artifacts saved | `aicad studio`: agent writes model.py → build_model → checks + render → revise; SESSION_LOG 2026-11-16 (c) e2e L-bracket | Loop owned by Agent SDK (ADR-013); stop = agent judgement + max_turns 80 |
| AGT-005 | Agent | Domain validator plug-in interface (CAD now, mesh later) | P0 | In Progress | M1 | MVP | Eng | AGT-004 | CAD validators registered via interface | `src/aicad/agent/tools.py` build_model MCP tool; checks provider-neutral | Mesh validators later |
| AGT-006 | Agent | Vision critique: observed vs uncertain findings, structured | P1 | In Progress | M1 | MVP | Eng | UX-003 | Structured output; never overrides gates | build_model returns 4-view PNG to agent (`agent/render.py`) | Critique is the agent's own; no structured findings schema yet |
| AGT-007 | Agent | Revision on spec (not exported file) | P0 | In Progress | M1 | MVP | Eng | AGT-004 | Revisions are spec diffs | Agent revises model.py source, never the STEP |  |
| AGT-008 | Agent | Iteration/time/cost caps + human-approval stop | P0 | In Progress | M1 | MVP | Eng | AGT-004 | CHK-14 enforced | max_turns=80, 180 s build timeout, Stop button (interrupt) | No per-session cost cap under subscription auth |
| AGT-009 | Agent | Run record: prompts (policy-permitting), model IDs, versions, costs, timings | P0 | Backlog | M1 | MVP | Eng | AGT-001 | `run.json` complete | — | |
| AGT-010 | Agent | Live Claude provider | P0 | In Progress | M1 | MVP | Eng | AGT-001, LEG-005 | Live benchmark run completes | Agent SDK 0.2.182 on claude-opus-5-5 via subscription login (dev); `--api-key` flag for API billing | Dev auth only (R-LIC-05) |
| AGT-011 | Agent | Gated free-form build123d code fallback | P2 | Backlog | M2 | LT | Eng | SEC-004 | Runs only in sandbox; extra checks | — | ADR-002 |
| AGT-012 | Agent | Prompt-injection defences (file text as data, tool allowlist) | P0 | In Progress | M1 | MVP | Eng | AGT-003 | Injection test prompts don't change tool behaviour | Tool allow-list, no Bash, workspace path guard, WebFetch host allow-list; `tests/test_agent.py` | No injection test prompts yet |
| AGT-013 | Agent | Second provider stub (portability check) | P2 | Backlog | M2 | LT | Eng | AGT-001 | Same tests pass with alt provider | — | Vendor lock-in |
| AGT-014 | Agent | Claude Agent SDK session per project workspace (tool allow-list, hooks, settings isolation, SSE events) | P0 | Done | M1 | MVP | Eng | ADR-013 | Prompt in UI → agent builds part → checks pass → viewer updates; no file access outside workspace | SESSION_LOG 2026-11-16 (c) e2e L-bracket; `tests/test_agent.py` guard + endpoint tests | Prototype; dev auth = subscription |
| AGT-015 | Agent | Switch to API-key (or Anthropic-approved) auth before any non-founder user | P0 | Backlog | M2 | LT | Founder | LEG-005 | Pilot build refuses subscription auth | — | R-LIC-05 |
| EVAL-001 | Eval | Deterministic check suite CHK-01..10, 12, 14 | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Each check unit-tested with pass and fail fixtures | `src/aicad/checks.py`: CHK-02..08 implemented + negative tests | CHK-01 (schema), 10, 12, 14 pending |
| EVAL-002 | Eval | Metamorphic/property tests (hypothesis) | P0 | Done | M1 | MVP | Eng | CAD-008 | ≥50 random param sets, no crashes | `test_random_specs_build_valid_or_fail_cleanly` (80 seeded random specs, ≥50 built, volume/bbox/manifold asserted); `test_metamorphic_length_increase` | Seeded `random`, not hypothesis yet |
| EVAL-003 | Eval | LLM benchmark: 20 original prompts, plate/bracket family | P0 | Backlog | M1 | MVP | Eng | AGT-004 | Report: first-pass & ≤3-iter rates, cost, latency | — | Opt-in (paid) |
| EVAL-004 | Eval | Golden fixtures FX-01..03 | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Fixtures with provenance + expected values | FX-01 at `specs/fx01_plate.json` (provenance recorded) | FX-02, FX-03 pending |
| EVAL-005 | Eval | Manual CAD interop check (SW 2025, Creo 11) | P0 | Backlog | M1 | MVP | Founder | IO-001 | Screenshots + measured dims logged | — | Downgraded to periodic interop spot check (ADR-012). Live viewer covers routine visual review but uses the same OCCT reader |
| EVAL-006 | Eval | Render similarity metric (advisory) | P2 | Backlog | M2 | LT | Eng | UX-003 | Metric logged, not gating | — | |
| EVAL-007 | Eval | Human review rubric + feedback capture | P1 | Backlog | M2 | LT | Founder | PLT-007 | Rubric used in pilots | — | |
| EVAL-008 | Eval | Repeatability: same prompt ×5 variance report | P1 | Backlog | M1 | MVP | Eng | EVAL-003 | Variance report | — | |
| EVAL-009 | Eval | Custom-model decision gate (only if EVAL-003 shows inadequacy) | P2 | Backlog | M5 | LT | Founder | EVAL-003 | ADR with data rights + ROI | — | Do not train by default |


### Design Studio roadmap (founder-prioritised 2026-11-16)

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-001 | Studio | Section view: solid capped cut with highlighted hatch, axis X/Y/Z, flip, numeric offset | P0 | Done | M1 | MVP | Eng | UX-004 | Cut face renders filled and highlighted on any axis; no hollow shell | Ported to new engine (`web/src/viewer/engine.ts`); verified on founder gear |  |
| DS-002 | Studio | Snap measurement: hover highlights vertices, edges, circle centres, faces; snaps to them; B-rep-accurate distance, radius/diameter, angle | P0 | Done | M1 | MVP | Eng | UX-004 | Hole Ø and edge lengths measure exactly (±0.001 mm) vs kernel | Exact topology `topo.json` (`src/aicad/topo.py`); snapping to vertex/edge/circle centre/face with occlusion test; B-rep-exact measurements (`web/src/viewer/measure.ts`); `tests/test_studio.py`::test_topology_is_exact_brep; browser walkthrough SESSION_LOG (f): bore snapped as Arc R10.000/Ø20.000, centre (0,0,10) | Hover snaps highlighted; hidden rims ignored |
| DS-003 | Studio | Point and tell: select face/edge/hole in viewer → selection chip in chat → agent receives stable reference | P0 | Done | M1 | MVP | Eng | DS-002 | "Fillet this edge R2" changes only the selected edge | Select tool → chips in chat → exact geometry descriptors to agent; `fw.edges_near/faces_near`; founder used it live ('Remove these holes' → agent identified the 6-hole pattern) |  |
| DS-004 | Studio | Mass properties + material library (density with cited source): mass, CoG, inertia | P1 | Done | M1 | MVP | Eng | ENG-003 | Values match hand calc on fixtures | Mass/area/CoG/inertia in runner; material library with source note; `tests/test_studio.py`::test_mass_properties_match_analytic_box; gear: steel 844.78 g | Densities are typical values, flagged to verify |
| DS-005 | Studio | Reference image/sketch attachment in chat; agent asks for scale/missing dims | P1 | Done | M1 | MVP | Eng | AGT-014 | Sketch + one dimension → model with stated assumptions | Attach/paste/drop images → `refs/` (type-sniffed, 6 MB, max 4) → agent reads them; `tests/test_studio.py`::test_attachment_validation | Live agent run with an image not yet exercised |
| DS-006 | Studio | Smart parameters: agent-declared limits/units/groups, sliders, live preview | P1 | Done | M2 | LT | Eng | UX-005 | Out-of-range values blocked before rebuild | PARAM_META limits/units/groups; sliders + auto-rebuild; server enforces limits; demo plate uses it |  |
| DS-007 | Studio | Revision compare: 3D overlay (added/removed material) + parameter diff | P2 | Done | M2 | LT | Eng | UX-006 | | OCCT boolean diff added/removed overlay + param diff; `tests/test_studio.py`::test_compare_revisions_reports_added_and_removed; browser walkthrough SESSION_LOG (f): removed 502.7 mm³ = π·4²·10 | Revisions before this release have no STEP snapshot |
| DS-008 | Studio | Feature tree: agent-labelled features, highlight in 3D, per-feature parameters | P1 | Done | M2 | LT | Eng | DS-003 | Selecting a tree node highlights its faces | `fw.feature` provenance by underlying surface; tree highlights faces; `tests/test_studio.py`::test_runner_exports_features_meta_mass_and_topology | Older models show no agent features until rebuilt by the agent |
| DS-009 | Studio | Multi-part view: part list, show/hide, transparency, explode slider | P2 | Done | M2 | LT | Eng | UX-004 | | Parts menu: per-part visibility, explode slider (shown when a model has >1 solid) | Part transparency per part not yet |
| DS-010 | Studio | **Manual feature authoring & editing (major epic)** like standard CAD: sketch on face/plane (lines, arcs, circles, dimensions, constraints), extrude / cut / revolve, hole wizard, fillet / chamfer on selected edges, linear/circular pattern, mirror, shell; edit, suppress, delete and reorder features in the tree; no AI, no tokens; manual and agent edits interoperate | P0 | Done | M2 | LT | Eng | DS-003, DS-008, CAD-060 | A user can model the FX-01 plate entirely by hand, then ask the agent to modify it, and vice versa | Steps a+c done: fillet/chamfer/hole(+pattern)/sketch extrude-cut with PropertyManager, edit/suppress/reorder/delete; `tests/test_studio.py`::test_manual_feature_lifecycle | Constraint sketcher (DS-017), shell + mirror (DS-023) added 2026-11-16. Not yet: revolve, pattern of arbitrary features |
| DS-010a | Studio | DS-010 step 1: edge/face operations on selection (fillet, chamfer, hole, delete face) | P0 | Done | M2 | LT | Eng | DS-003 | | Fillet/chamfer on picked edges, hole on picked face |  |
| DS-010b | Studio | DS-010 step 2: sketch mode on a face with dimensions + extrude/cut | P0 | Done | M2 | LT | Eng | DS-010a, CAD-060 | | Rectangle/circle sketch on picked planar face with offsets + extrude/cut + live preview | Superseded by DS-017 constraint sketcher |
| DS-010c | Studio | DS-010 step 3: feature tree edit/suppress/reorder with regeneration | P1 | Done | M2 | LT | Eng | DS-010b, DS-008 | | Feature tree edit/suppress/reorder/delete with deterministic rebuild + rollback |  |
| DS-012 | Studio | CAD orthographic projection by default (true parallel views); perspective toggle with adjustable perspective strength | P0 | Done | M1 | MVP | Eng | UX-004 | Front/Top/Right are true orthographic; setting persists | Orthographic default; Persp toggle with strength (FOV 10–70°) persisted; silhouette zoom-to-fit; browser walkthrough SESSION_LOG (f) |  |
| DS-013 | Studio | True CAD display modes from B-rep edges: shaded+edges, shaded, wireframe (model edges only, no triangles), hidden lines dimmed | P0 | Done | M1 | MVP | Eng | DS-002 | Wireframe shows only geometric edges | Display styles: shaded+edges, shaded, hidden lines visible (dashed), wireframe from B-rep edges only; browser walkthrough SESSION_LOG (f) |  |
| DS-011 | Studio | Quick wins: persist chat history, undo last agent change, 3MF + named-part STEP export, pre-run token estimate | P1 | Done | M1 | MVP | Eng | — | | Chat persisted + agent session resumed after restart; undo last agent change; 3MF export; pre-run token estimate; `tests/test_studio.py`::test_chat_history_and_session_persist |  |
| DS-014 | Studio | Agent progress in plain language: no file names, tools, code or model ids in the UI | P0 | Done | M1 | MVP | Eng | — | No raw agent items visible | `agent/session.py` friendly_step/friendly_result/scrub; prompt section "How you talk to the user" | |
| DS-015 | Studio | SOLIDWORKS-style CommandManager ribbon: Features / Sketch / Evaluate / View / Library tabs | P0 | Done | M1 | MVP | Eng | DS-010 | Every manual workflow reachable from the ribbon | `web/src/pages/app/studio/CommandManager.tsx` | Tab choice persisted |
| DS-016 | Studio | Native-feeling manual edits: optimistic tree updates (suppress/delete/reorder), non-blocking "Rebuilding…", base-geometry cache, build time toast | P0 | Done | M1 | MVP | Eng | DS-010c | Tree reacts instantly; rebuild ≈1–2 s on cache hit | `ProjectStudio.tsx` manualCall optimistic + rollback; runner base cache (gear: 4.6 s → 1.9 s) | |
| DS-017 | Studio | 2D sketcher on a planar face: line (chain), corner rectangle, circle, centre arc, Smart Dimension (length, Ø/R, point distance), relations H/V/parallel/perpendicular/equal/tangent/concentric/point-on/fix, auto H/V, snapping to points and face vertices, drag, undo/redo, DOF status; Exit sketch → boss or cut; re-edit from tree | P0 | Done | M2 | LT | Eng | CAD-060 | Closed profiles (incl. holes in regions) extrude/cut exactly | `web/src/sketch/model.ts` (LM solver, DOF by rank), `SketchEditor.tsx`; `fw.sketch_region`; `tests/test_studio.py`::test_sketch_feature_with_hole_and_arc | Not yet: trim/extend, offset, splines, construction toggle UI, sketch on reference planes |
| DS-018 | Studio | STEP import as an EXACT solid ("Imported blank") with recognised features layered on top; editable by the design agent (booleans on the exact body) and by manual features even where nothing is recognised | P0 | Done | M2 | LT | Eng | IO-* | Imported model is geometrically identical to the file; all gating checks pass | `fw.imported_blank`, `recognize.import_model`; `tests/test_library.py`::test_step_import_is_exact_body_with_editable_recognised_features | Founder rejected the earlier approximate draft approach (2026-11-16 h) |
| DS-019 | Studio | Feature recognition for imports AND any existing model: exact-geometry pass (stock, holes, grid/linear/circular patterns, rotational repetition → gear teeth with module/tip/root, bosses, fillets, chamfers) + AI pass (agent reads standard views + data, classifies the component and names features); results in the feature tree with face highlighting; recognised holes/patterns editable (fill-and-recut on the exact body); full parametric rebuild by agent with CHK-09 | P0 | Done | M2 | LT | Eng | DS-018 | Gear recognised as spur gear z40 m3 with 0 unrecognised faces | `recognize.py` (1.3 s on a 1083-face gear), `/recognition/run`, `/recognition/ai`, `fw-recognition` block; tests `test_gear_is_recognised_as_a_component`, `test_agent_recognition_block_is_parsed`; browser: AI returned "Spur gear, 40 teeth, module 3 (ISO 53, high)" | Pockets/slots are left in the blank (AI explains them) |
| DS-020 | Studio | Toolbox: deterministic, versioned generators — hex bolt ISO 4017, SHCS ISO 4762, hex nut ISO 4032, washer ISO 7089, hex standoff, dowel pin, deep-groove ball bearing 60xx/62xx, involute spur gear, shaft with DIN 6885 keyway, bolted flange, L-bracket | P0 | Done | M2 | LT | Eng | — | Same inputs → byte-identical STEP; analytic EXPECTED passes | `src/aicad/toolbox.py`; `tests/test_library.py`::test_every_toolbox_component_is_deterministic_and_matches_expected; agent can call `toolbox.build` | Threads cosmetic; bearing simplified (no grooves/cage) |
| DS-021 | Studio | Toolbox offer: when a chat request matches a standard component, popup "Use Toolbox component" vs "Continue with custom design" (sizes pre-filled from the request) | P0 | Done | M2 | LT | Eng | DS-020 | Agent path always available | `toolbox.match`, Chat offer modal; `tests/test_library.py`::test_toolbox_validation_and_matching | |
| DS-022 | Studio | Structured clarifying questions: agent emits choice questions → clickable chips (+ Other) → answers sent in one click | P0 | Done | M2 | LT | Eng | — | No typing needed for enumerable answers | `extract_questions` in `agent/session.py`, prompt section, `Chat.tsx` Questions; `tests/test_library.py`::test_agent_questions_block_is_parsed_and_stripped | Live agent run not yet exercised in a browser |
| DS-023 | Studio | Shell (remove faces) and Mirror (face or principal plane) manual features | P1 | Done | M2 | LT | Eng | DS-010 | | `fw._op` shell/mirror; `tests/test_studio.py` | |
| DS-025 | Studio | Studio layout: project header bar removed (back, name, status, help, STEP moved into the command-bar tab row); feature panel left, design agent right; feature panel, agent panel and command bar collapsible (remembered); redundant "Add feature" buttons removed from the tree; model id no longer shown in chat | P0 | Done | M1 | MVP | Eng | DS-015 | | Browser screenshots SESSION_LOG (h) | App sidebar already collapsible (bottom-left) |
| DS-024 | Studio | Next: revolve, sweep, pattern any feature, sketch trim/offset, reference planes/axes, assembly mates with Toolbox parts | P1 | Backlog | M3 | LT | Eng | DS-017, ASM-* | | | Founder to prioritise |

## B. AI Manufacturing Advisor

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MFG-001 | Mfg | Basic CNC DFM rules for M1 family (internal radii, hole L/D, thin walls, std drill sizes) | P1 | Backlog | M1 | MVP | Eng | CAD-009 | Rules fire on seeded fixtures; findings tied to feature IDs | — | Advisory only |
| MFG-010 | Mfg | Turning DFM rules | P1 | Backlog | M4 | LT | Eng | CAD-024 | Seeded fixture tests | — | |
| MFG-011 | Mfg | Sheet metal DFM rules | P2 | Backlog | M4 | LT | Eng | CAD-026 | Seeded fixture tests | — | |
| MFG-012 | Mfg | Additive DFM rules | P2 | Backlog | M4 | LT | Eng | PRN-002 | Seeded fixture tests | — | |
| MFG-013 | Mfg | Casting / injection molding DFM (draft, wall uniformity, undercuts) | P2 | Backlog | M4 | LT | Eng | CAD-025 | Seeded fixture tests | — | Only where credible |
| MFG-014 | Mfg | Process recommendation (material, qty, geometry, tolerance, finish, machines) | P1 | Backlog | M4 | LT | Eng | MFG-010 | Ranked options with stated assumptions + confidence | — | |
| MFG-015 | Mfg | Shop profile inputs (machines, tooling, rates) | P1 | Backlog | M4 | LT | Eng | PLT-001 | Advice changes with profile | — | |
| MFG-016 | Mfg | Cost-driver/time-reduction suggestions (setups, tolerances, std parts, part count) | P1 | Backlog | M4 | LT | Eng | MFG-014 | Each suggestion cites feature + rationale | — | |
| MFG-017 | Mfg | Relative cost model (no firm quotes) with assumptions | P2 | Backlog | M4 | LT | Eng | MFG-015 | Output labelled estimate; inputs shown | — | Never firm quotes |
| MFG-018 | Mfg | Manufacturability report (PDF) tied to model features | P1 | Backlog | M4 | LT | Eng | MFG-001 | Report links finding → feature → view | — | |
| MFG-019 | Mfg | BOM + manufacturability combined report for assemblies | P2 | Backlog | M4 | LT | Eng | ASM-008, MFG-018 | | — | |
| MFG-020 | Mfg | Material library with provenance/versioning | P1 | Backlog | M4 | LT | Eng | — | Each property cites source + version | — | Shared with ENG-003 |

## C. AI Engineering Advisor

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ENG-001 | Eng | Load case / boundary condition elicitation | P1 | Backlog | M4 | LT | Eng | AGT-003 | Structured load-case record per part | — | |
| ENG-002 | Eng | Failure mode checklist (stress conc., fatigue, buckling, vibration, thermal, fit) | P1 | Backlog | M4 | LT | Eng | ENG-001 | Checklist tied to features; level = Recommended check | — | |
| ENG-003 | Eng | Units/material/standards library with provenance & versions | P1 | Backlog | M4 | LT | Eng | MFG-020 | Unit-safe (pint or equiv.) tests | — | |
| ENG-004 | Eng | Deterministic calculators (beam, bolt, pin shear, bearing, thread engagement) | P1 | Backlog | M4 | LT | Eng | ENG-003 | Verified against textbook worked examples | — | Level = Verified calculation after review |
| ENG-005 | Eng | Safety factor handling with explicit user/standard source | P1 | Backlog | M4 | LT | Eng | ENG-004 | SF always attributed | — | |
| ENG-006 | Eng | Recommend analyses/tests to run | P2 | Backlog | M4 | LT | Eng | ENG-002 | Recommendations listed with rationale | — | |
| ENG-007 | Eng | Advice-level labelling in UI/reports (4 levels) | P0 | Backlog | M4 | LT | Eng | — | Every engineering output labelled | — | VALIDATION §4 |
| ENG-008 | Eng | Engineer sign-off workflow for safety-critical outputs | P1 | Backlog | M4 | LT | Eng | PLT-004 | Named sign-off recorded; unsigned flagged | — | |
| ENG-009 | Eng | External FEA integration evaluation (e.g., CalculiX, SW Simulation) | P2 | Backlog | M5 | LT | Eng | LEG-002 | ADR with license + validation approach | — | |
| ENG-010 | Eng | Stress concentration region highlighting (geometry heuristics) | P2 | Backlog | M4 | LT | Eng | ENG-002 | Highlights on fixtures; labelled heuristic | — | |
| ENG-011 | Eng | Fit/clearance/tolerance stack-up (1D) | P2 | Backlog | M4 | LT | Eng | ASM-005 | Worked example match | — | |
| ENG-012 | Eng | Guard: never claim FEA validation from visual review | P0 | Backlog | M4 | LT | Eng | ENG-007 | Test prompts can't elicit "validated" wording without evidence | — | |

## D. AI Mesh Studio (later module)

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MSH-001 | Mesh | Headless Blender worker (separate process, sandboxed) | P2 | Backlog | M5 | LT | Eng | SEC-004, LEG-004 | Script runs headless with limits | — | Blender 5.1 installed locally |
| MSH-002 | Mesh | Text → procedural scene script | P2 | Backlog | M5 | LT | Eng | MSH-001 | Benchmark prompts produce scenes | — | |
| MSH-003 | Mesh | Image → scene/object via vision + script | P2 | Backlog | M5 | LT | Eng | MSH-002 | | — | |
| MSH-004 | Mesh | Objects, modifiers, materials, lighting, camera control | P2 | Backlog | M5 | LT | Eng | MSH-002 | | — | |
| MSH-005 | Mesh | Render → critique → revise loop using shared orchestrator | P2 | Backlog | M5 | LT | Eng | AGT-005 | Mesh validators via plug-in interface | — | |
| MSH-006 | Mesh | Multiview reference support | P2 | Backlog | M5 | LT | Eng | MSH-005 | | — | |
| MSH-007 | Mesh | Editable .blend output + GLB/GLTF/OBJ/STL (FBX where practical) | P2 | Backlog | M5 | LT | Eng | MSH-001 | Exports open in viewers | — | |
| MSH-008 | Mesh | Topology/watertight/manifold/UV checks | P2 | Backlog | M5 | LT | Eng | PRN-001 | | — | |
| MSH-009 | Mesh | Mesh vs B-rep labelling; defensible conversion only | P2 | Backlog | M5 | LT | Eng | — | UI label + conversion limits doc | — | |
| MSH-010 | Mesh | Benchmark: scripted vs generative 3D models vs hybrid | P2 | Backlog | M5 | LT | Eng | MSH-002 | Report per VALIDATION §5 | — | |
| MSH-011 | Mesh | Hybrid pipeline if benchmark favours it | P2 | Backlog | M5 | LT | Eng | MSH-010 | ADR | — | |
| MSH-012 | Mesh | GPU render path on local RTX 8000 vs cloud cost comparison | P2 | Backlog | M5 | LT | Eng | MSH-001 | Measured cost/latency | — | |

## E. Shared platform, security, UX, infra, docs

| ID | Module | Feature/task | Pri | Status | MS | Scope | Owner | Deps | Acceptance criteria | Evidence/test | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| PLT-001 | Platform | Projects/workspaces data model | P1 | Done | M2 | LT | Eng | INF-002 | CRUD + tests | Organizations + projects models/routes; `tests/test_platform.py` | SQLite dev; Postgres via FW_DATABASE_URL untested |
| PLT-002 | Platform | Versioning + provenance per artifact (content hashes) | P0 | In Progress | M1 | MVP | Eng | CAD-009 | Every artifact has hash + producing run | STEP sha256 in status; revision snapshots per build | Content-addressed store pending |
| PLT-003 | Platform | Job model: queue, retries, idempotency, progress events, cancellation | P0 | Backlog | M1 | MVP | Eng | INF-002 | Kill/retry tests; SSE progress | — | SQLite in M1 |
| PLT-004 | Platform | Auth + permissions (single user M1 → multi-user M2) | P1 | Done | M2 | LT | Eng | PLT-001 | Role tests | Email/password auth, roles owner/admin/engineer/viewer, invites, seat limits; `tests/test_platform.py` | SSO/2FA planned (Preview in Settings) |
| PLT-005 | Platform | Per-job cost metering | P0 | Done | M1 | MVP | Eng | AGT-009 | Cost per job in run record + UI | Token ledger + per-run metering `_on_event`; `tests/test_platform.py`::test_agent_result_event_debits_tokens | Compute cost is the SDK estimate (PD-03) |
| PLT-006 | Platform | Human-in-the-loop approval queue | P1 | Backlog | M2 | LT | Eng | CAD-028 | Pending approvals listed; resume job on approve | — | |
| PLT-007 | Platform | User feedback/corrections capture | P1 | Done | M2 | LT | Eng | PLT-001 | Stored with run link | /api/feedback (general, bug, idea, waitlist, ratings) + Admin → Feedback; `tests/test_platform.py` |  |
| PLT-008 | Platform | Consent-gated dataset collection | P2 | Backlog | M2 | LT | Eng | LEG-008 | No data stored without consent flag | — | |
| PLT-009 | Platform | Usage controls per tenant | P2 | In Progress | M4 | LT | Eng | PLT-004 | Caps enforced | Token preflight, plan/trial gating, seat limits | Per-tenant spend caps pending |
| PLT-010 | Platform | Collaboration foundations (sharing, comments) | P2 | Backlog | M4 | LT | Eng | PLT-004 | | — | |
| PLT-011 | Platform | Export bundle (zip of all artifacts + report) | P0 | In Progress | M1 | MVP | Eng | PLT-002 | Bundle reproduces run | STEP/STL downloads per project | Zip bundle pending |
| SEC-001 | Security | M1 isolation: compiler-only execution in subprocess w/ timeout + memory guard | P0 | In Progress | M1 | MVP | Eng | CAD-001 | Timeout test kills runaway job | runner subprocess, timeout, secret-free env, import tripwire (`tests/test_agent.py`) | Tripwire is not a sandbox (R-SEC-05) |
| SEC-002 | Security | Path traversal + filename sanitization in artifact store | P0 | Done | M1 | MVP | Eng | PLT-002 | Fuzz tests | Allow-listed file names per project, workspace path resolution checks; `tests/test_platform.py`::test_projects_crud_and_paywall |  |
| SEC-003 | Security | Secrets management (env/keyring; never in workers or logs) | P0 | Backlog | M1 | MVP | Eng | AGT-001 | Log scrubbing test | — | |
| SEC-004 | Security | Container sandbox: no network, ro mounts, limits, no secrets, per-tenant scratch | P1 | Blocked | M2 | LT | Eng | approval | Escape test suite passes | — | No Docker / WSL distro; install needs approval |
| SEC-005 | Security | Upload validation: type sniffing, size limits, zip-bomb guards, isolated parsing | P1 | Backlog | M2 | LT | Eng | SEC-004 | Malicious fixture suite rejected | — | |
| SEC-006 | Security | Tenant isolation (data + compute) | P1 | In Progress | M2 | LT | Eng | PLT-004 | Cross-tenant access tests fail closed | Org scoping on every query; role checks; cross-org 404s | Compute isolation pending (SEC-004) |
| SEC-007 | Security | Data classification at upload + "no third-party AI" mode | P1 | Backlog | M2 | LT | Eng | LEG-009 | Classified data never reaches provider (test) | — | R-SEC-04 |
| SEC-008 | Security | Threat model document | P1 | Backlog | M2 | LT | Eng | ARC-002 | STRIDE-style doc reviewed | — | |
| SEC-009 | Security | Dependency vulnerability scanning in CI | P1 | Backlog | M1 | MVP | Eng | INF-003 | CI job runs pip-audit/npm audit | — | |
| UX-001 | UX | CLI: `make`, `edit-param`, `revise`, `export` | P0 | Backlog | M1 | MVP | Eng | AGT-004 | End-to-end demo via CLI | — | M1a |
| UX-002 | UX | Minimal web UI: prompt, assumptions approval, params panel, downloads | P0 | Done | M1 | MVP | Eng | INF-004 | VS-1 demo in browser | Full React app: marketing, auth, onboarding, dashboard, studio, modules, billing, team, settings, help, admin; E2E browser walk-through, SESSION_LOG (d) |  |
| UX-003 | UX | Offscreen renderer (fixed cameras) | P0 | In Progress | M1 | MVP | Eng | CAD-001 | CHK-10 passes | `agent/render.py` VTK offscreen 2×2 views | CHK-10 automatic render check pending |
| UX-004 | UX | Three.js viewer: orbit, part tree, selection, measure | P1 | In Progress | M1 | MVP | Eng | IO-003 | Measured dims match spec | React Viewer3D (orbit, 4 views, edges, wireframe, section, measure) | Part tree for assemblies pending |
| UX-005 | UX | Feature tree + parameter editing UI | P1 | In Progress | M2 | LT | Eng | UX-004 | Edit → regenerate | Params tab: deterministic edit + rebuild, no AI/tokens; `tests/test_platform.py`::test_param_edit_* | Only simple numeric top-level assignments |
| UX-006 | UX | Revision history / compare UI | P2 | Done | M2 | LT | Eng | CAD-012 | | Revisions tab with restore (deterministic rebuild) | Visual diff pending |
| UX-007 | UX | Clear capability labels (implemented/prototype/inferred/not approved) | P0 | Done | M1 | MVP | Eng | — | Labels on every output | Live/Preview badges, SAMPLE labels, NOT APPROVED banner, simulated-payment banners |  |
| UX-008 | UX | Live local viewer: auto-reload on spec save, mesh from re-imported STEP, checks panel | P0 | Done | M0 | MVP | Eng | ARC-010 | Save spec → viewer shows new geometry + checks within ~1 s; only allow-listed files served | `aicad live`; headless-Chrome screenshots 120→150 mm rebuild (SESSION_LOG 2026-11-16 b); `tests/test_viewer.py` | Founder request; ADR-012. Three.js from CDN: vendor before offline use |
| UX-009 | UX | Studio chat panel: streaming agent text, tool steps with status, Stop/New, cost-estimate line | P0 | Done | M1 | MVP | Eng | AGT-014 | Prompt typed in browser drives the agent; tool progress visible; result line shows turns/time/est. cost | Screenshot, SESSION_LOG c | Escape-first minimal markdown |
| UX-010 | UX | Marketing site: landing, pricing, legal drafts, responsive | P0 | Done | M1 | MVP | Eng | — | Investor-grade landing with honest Live/Preview roadmap | E2E browser walk-through, SESSION_LOG (d) | Copy reviewed for no over-claims |
| UX-011 | UX | Signup → verify → 5-step onboarding wizard → workspace + trial | P0 | Done | M1 | MVP | Eng | PLT-004 | New user reaches dashboard with 300 tokens in < 2 min | E2E browser walk-through, SESSION_LOG (d); `tests/test_platform.py` | |
| UX-012 | UX | Guided product tour + studio tour + getting-started checklist | P0 | Done | M1 | MVP | Eng | UX-011 | Auto-start once, restartable; checklist reflects real state | E2E browser walk-through, SESSION_LOG (d) | driver.js |
| UX-013 | UX | God mode: bypasses, journey jumps, scenarios, demo seed, impersonation | P0 | Done | M1 | MVP | Eng | PLT-004 | Founder can demo any step in < 10 s; disabled in production | `tests/test_platform.py`::test_god_mode_* ; E2E browser walk-through, SESSION_LOG (d) | ADR-014 |
| UX-014 | UX | Command palette (Ctrl+K), notifications, dark theme, collapsible sidebar | P1 | Done | M1 | MVP | Eng | UX-002 | | E2E browser walk-through, SESSION_LOG (d) | |
| UX-015 | UX | Module preview pages with SAMPLE outputs, waitlist, add-on unlock | P0 | Done | M1 | MVP | Eng | ADR-016 | Every Preview module explains itself honestly | E2E browser walk-through, SESSION_LOG (d) | |
| UX-016 | UX | Super-admin console: KPIs, funnel, users, orgs, catalog editor, payments, feedback, audit, outbox, system | P0 | Done | M1 | MVP | Eng | PLT-004 | | `tests/test_platform.py`::test_admin_console_and_impersonation | |
| UX-017 | UX | Brand identity: name, logo, palette, typography (BRAND.md) | P0 | Done | M1 | MVP | Eng | ADR-015 | | docs/BRAND.md | Trademark check parked (PD-01) |
| UX-018 | UX | Mobile/tablet layout pass for the app shell and studio | P2 | Backlog | M2 | LT | Eng | UX-002 | Usable at 768 px | — | Marketing is responsive; studio is desktop-first |
| INF-001 | Infra | uv venv (Py3.12), lockfile, pinned deps | P0 | In Progress | M1 | MVP | Eng | ARC-010 | Fresh clone → `uv sync` → tests pass | `pyproject.toml`, `uv.lock`, `.venv` Py 3.12.13 | Fresh-clone test not yet run |
| INF-002 | Infra | SQLite persistence + local artifact store | P0 | Done | M1 | MVP | Eng | INF-001 | Migration + tests | SQLAlchemy + SQLite + filesystem workspaces |  |
| INF-003 | Infra | CI (lint, type, tests, no paid calls) incl. Linux runner | P0 | Backlog | M1 | MVP | Eng | GOV-004 | CI green on Win + Linux | — | R-TEC-07 |
| INF-004 | Infra | FastAPI app + SSE progress | P0 | Done | M1 | MVP | Eng | PLT-003 | API contract tests | `aicad.platform.app` FastAPI + SSE + SPA serving; `tests/test_platform.py` |  |
| INF-005 | Infra | Observability: per-stage timings, model calls, tokens, failures | P0 | Backlog | M1 | MVP | Eng | AGT-009 | Structured logs + run summary | — | |
| INF-006 | Infra | Pilot deployment: single VM, Postgres, S3-compatible store, containerized worker | P1 | Backlog | M2 | LT | Eng | SEC-004 | Deploy script; restore test | — | Cloud spend needs approval |
| INF-007 | Infra | Cost-per-design model (CPU-s, tokens, storage) | P1 | Backlog | M2 | LT | Eng | INF-005 | Measured, not estimated from dev box | — | AS-08 |
| INF-008 | Infra | Alembic migrations before first production deploy | P0 | Backlog | M2 | LT | Eng | INF-002 | Schema upgrades without data loss | — | ADR-014 consequence |
| INF-009 | Infra | Distributed rate limiting + session cleanup job | P1 | Backlog | M2 | LT | Eng | INF-006 | | — | Current limiter is in-process |
| DOC-001 | Docs | Known limitations doc (single-view ambiguity, sign-off, no native history) | P0 | Backlog | M1 | MVP | Eng | — | Doc published in repo/UI | — | |
| DOC-002 | Docs | Developer README (setup, run, test) | P0 | In Progress | M1 | MVP | Eng | INF-001 | New machine setup succeeds | `README.md` | Fresh-machine test pending |
| DOC-003 | Docs | Part Spec DSL reference | P1 | Backlog | M1 | MVP | Eng | ARC-011 | Every op documented with example | — | |
| DOC-004 | Docs | Legal checklist draft (IP, confidentiality, TM, privacy, retention, export control) | P1 | Backlog | M1 | MVP | Eng | — | Draft for counsel; marked "not legal advice" | — | Feeds LEG-007..009 |

---

## Trace: master prompt §2 → punch list

| §2 item | IDs |
|---|---|
| A1 NL → 3D | CAD-011, AGT-003, CAD-001..008 |
| A2 Image/sketch → CAD | CAD-022 |
| A3 Drawing → CAD | CAD-020, CAD-021 |
| A4 3D → 2D drawings | DRW-001..006, DRW-010..014, DRW-016 |
| A5 Associative updates | DRW-015 |
| A6 Assemblies/mates/interference/DOF/exploded | ASM-001..012 |
| A7 Native history/sketches | CAD-007, CAD-060..062 |
| A8 Formats | IO-001..008 |
| A9 SOLIDWORKS pathways | CAD-070, CAD-071, LEG-006 |
| A10 3D printing prep | PRN-001..006 |
| A11 Revisions/undo/versioning | CAD-012, PLT-002, UX-006 |
| B DFM/process/cost/report | MFG-001, MFG-010..020 |
| C Engineering advisor | ENG-001..012 |
| D Mesh Studio | MSH-001..012 |
| E Workspaces/versioning/permissions | PLT-001, PLT-002, PLT-004, PLT-010 |
| E Viewer | UX-004, UX-005 |
| E Orchestration/jobs/metering | AGT-004, PLT-003, PLT-005 |
| E Human approvals | CAD-028, PLT-006, ENG-008 |
| E Provider abstraction | AGT-001, AGT-002, AGT-013 |
| E Secure ingestion/observability/eval | SEC-001..009, INF-005, EVAL-001..009 |
| E Feedback/datasets with consent | PLT-007, PLT-008 |
| E Onboarding/telemetry/billing/support | COM-003..006 |
| Cross-cutting legal | LEG-001..010, DOC-004 |
