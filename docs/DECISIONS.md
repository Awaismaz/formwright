# Architecture Decision Records

Status values: **Proposed** (awaiting approval), **Accepted**, **Superseded**, **Rejected**, **Deferred**.
Each ADR: context, decision, alternatives, consequences, revisit trigger.

---

## Assumptions register

| ID | Assumption | Confidence | How to test | Owner |
|---|---|---|---|---|
| AS-01 | US design consultancies/machine shops will pay for reduced concept-to-drawing effort | Low (no evidence yet) | 5–10 pilot interviews (COM-001) | Founder |
| AS-02 | Simple prismatic machined parts are a frequent, time-consuming task for target users | Medium (founder experience) | Interview + time logs | Founder |
| AS-03 | A general LLM + deterministic CAD toolchain is good enough; no custom model needed | Medium | Benchmark EVAL-003 | Eng |
| AS-04 | Customers accept STEP (no native feature history) for M1–M2 | Medium | Pilot feedback | Founder |
| AS-05 | Customers will allow cloud LLM processing of non-sensitive designs | Low–medium | Pilot security questionnaire | Founder |
| AS-06 | OCCT is robust enough for the M1 feature set (extrude, pocket, holes, fillet, chamfer) | High | ARC-010 spike + fuzz tests | Eng |
| AS-07 | Server-side use of LGPL OCCT in SaaS is acceptable with dynamic linking | Medium | Counsel (LEG-003) | Counsel |
| AS-08 | Dev hardware (72-thread Xeon, RTX 8000) is not representative of production cost | High | Record CPU-seconds per job | Eng |

---

## ADR-001 — Precision geometry backend: build123d on OCP/OCCT
**Status:** Accepted 2026-11-16 (founder approval; spike ARC-010 passed) · **Date:** 2026-11-16
**Context:** Need B-rep solids, STEP AP214/AP242 export, projections for drawings, pip-installable, permissive enough for SaaS.
**Decision:** build123d as primary API; CadQuery permitted as secondary (same OCP kernel, already installed in base env).
**Alternatives:** CadQuery only (mature, larger corpus, slightly less explicit API); FreeCAD (feature history + sketcher but heavy, LGPL, harder to sandbox); direct OCP (too verbose for agent output).
**Consequences:** We own feature history, naming, assembly constraints, drawings. build123d small maintainer team → pin versions, wrap behind our compiler.
**Revisit if:** spike ARC-010 shows instability on Windows/Python 3.12, or FreeCAD's solver becomes necessary.

## ADR-002 — Agent output: typed Part Spec DSL, code generation gated
**Status:** Accepted 2026-11-16
**Context:** No container runtime on dev machine; need deterministic regeneration, edits, revisions, eval.
**Decision:** LLM produces JSON conforming to a versioned Part Spec schema (units, parameters, ordered features with IDs, semantic references, assumptions, open questions). Trusted compiler → build123d. Free-form code generation disabled until SEC-004 sandbox exists; then allowed as a fallback with stricter checks.
**Alternatives:** free-form code (max coverage, unsafe, hard to edit); pure DSL forever (coverage ceiling).
**Consequences:** DSL design becomes core IP; coverage grows feature by feature. Schema changes need migrations (approval gate).

## ADR-003 — M1 wedge: text/spec → prismatic machined part → STEP + drawing
**Status:** Accepted 2026-11-16 (founder: "Go ahead")
**Context:** User preference is image/drawing/text → part → STEP → drawing. Image input has high ambiguity and weak objective evaluation.
**Decision:** M1 input = text (and the structured spec itself). Part class = prismatic machined plates/brackets: base block, through/blind holes, hole patterns, rectangular pockets, slots, edge fillets/chamfers. Output = STEP, STL, GLB, renders, checks report, 3-view drawing (SVG/PDF), basic CNC DFM notes.
**Alternatives:** W2 image, W3 vector PDF, W4 STEP→drawing+DFM (ARCHITECTURE §4).
**Revisit:** after pilot interviews (COM-001); M2 picks W3 or W4.

## ADR-004 — Go-to-market surface: standalone web app with STEP interop first
**Status:** Proposed
**Decision:** Browser app; SOLIDWORKS/Creo bridges are backlog spikes, not M1.
**Consequences:** No native feature trees in customer CAD; honest disclosure required (STEP-in-SLDPRT is dumb solid).

## ADR-005 — Python environment: isolated uv venv, Python 3.12
**Status:** Accepted 2026-11-16 (implemented: `.venv`, Python 3.12.13, build123d 0.13.0 pinned, `uv.lock`)
**Context:** Base miniconda (3.13.9) already holds unrelated packages; modifying it risks other projects.
**Decision:** Project-local `.venv` via uv, Python 3.12 (widest wheel support for OCP/VTK; *verify* 3.13 later), lockfile committed.

## ADR-006 — Rendering: VTK/PyVista offscreen with fixed cameras
**Status:** Proposed
**Decision:** Tessellate B-rep (fixed tolerance), render iso + front/top/right at fixed resolution, deterministic lighting. Store camera params with images.
**Alternatives:** Blender render (GPL, heavier), pyrender/trimesh (fine; second option), Three.js headless (complex).

## ADR-007 — Execution isolation in M1
**Status:** Proposed
**Decision:** M1 executes only compiler-generated code in a subprocess with wall-clock timeout and memory guard; no LLM-authored code. Container sandbox (Docker Desktop or WSL2 + rootless containers) required before ADR-002 code fallback. Installing either needs approval.

## ADR-008 — Deployment and persistence
**Status:** Proposed
**Decision:** M1: single process, SQLite job/asset tables, local FS artifact store with content hashing. M2 pilot: single VM, Postgres, S3-compatible store, containerized worker. Scale only on evidence.

## ADR-009 — LLM provider abstraction
**Status:** Proposed
**Decision:** `LLMProvider` interface (structured output + vision). Implementations: Claude (primary), recorded/replay (CI default), stub for others. Log model ID, tokens, cost, latency per call. Default to latest capable Claude model, configurable.
**Note:** Anthropic commercial/API terms for this use need review (LEG-005); Claude Code subscription usage is a dev tool, not the product's runtime.

## ADR-010 — Mesh Studio deferred
**Status:** Deferred to M5
**Decision:** Blender as separate headless process only; never mixed with precision CAD paths. Benchmark against generative 3D models before committing.

## ADR-011 — Drawing generation approach (M1)
**Status:** Proposed
**Decision:** HLR projections (build123d/OCCT) → SVG; dimensions generated from Part Spec features (not inferred from geometry) and labelled by source: *spec* vs *inferred*. Title block with "NOT APPROVED FOR MANUFACTURE — ENGINEER REVIEW REQUIRED" until signed. PDF library chosen after license check (prefer permissive, e.g. reportlab BSD; avoid LGPL-3 cairosvg unless cleared).

## ADR-012 — Live local viewer instead of per-run checks in desktop CAD
**Status:** Accepted 2026-11-16 (founder request)
**Context:** Opening every STEP in SOLIDWORKS/Creo is slow and manual.
**Decision:** `aicad live` runs a stdlib HTTP server on 127.0.0.1 and serves a Three.js page. The page polls `status.json` and reloads `model.glb` whenever a build finishes. The GLB is tessellated from the **re-imported STEP**, not from the in-memory model, so the view reflects what the file contains. The page also shows kernel check results, measurements, a section plane and downloads. It is the seed of the M1b web viewer (UX-004).
**Alternatives:** OCP CAD Viewer for VS Code (`ocp_vscode`, works well with build123d, but it is a developer tool and cannot become the product UI); `occt-import-js` loading STEP in the browser (LGPL-2.1 WASM, same OCCT kernel, so no independence gained).
**Consequences:** Manual SOLIDWORKS/Creo checks drop from every run to periodic interop spot checks (EVAL-005). Our viewer reads STEP with the same OCCT kernel that wrote it, so it cannot catch reader-specific interop bugs. The page loads Three.js from a CDN, so it needs internet access; vendor it locally before any offline or customer use.
