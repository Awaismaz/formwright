# Architecture

Status: **DRAFT, awaiting approval** (see DECISIONS ADR-001…ADR-011). Nothing here is implemented yet.

Legend for capability state used across docs: **Implemented** (code + passing tests), **Prototype** (works, not hardened), **Planned**, **Blocked**.

---

## 1. Critical recommendation (short version)

**Preferred stack**
- Geometry: **build123d on OCP/OCCT** (Apache-2.0 bindings; OCCT LGPL-2.1 + exception). CadQuery stays as a fallback; same kernel.
- Agent output: **typed Part Spec (JSON schema) → our compiler → build123d**. Not free-form Python in M1.
- Backend: Python 3.12, FastAPI, Pydantic v2. M1 persistence is SQLite + local filesystem; Postgres + S3-compatible storage at M2.
- Jobs: in-process worker with a durable SQLite job table in M1; move to a real queue (e.g. Postgres-backed queue) only when there is more than one worker.
- Render: VTK/PyVista offscreen, fixed cameras. Already installed and BSD/MIT.
- Frontend (M1b): React + TypeScript + Three.js GLB viewer.
- LLM: provider interface with Claude as primary, plus a **recorded/mock provider so CI never makes paid calls**.

**What I would change from the reference design**
1. **DSL first, code second.** The reference says the LLM "generates executable parametric CAD programs". I recommend the LLM emits a *validated feature spec* (parameters + ordered features with semantic references); our trusted compiler emits build123d. Reasons: (a) no Docker on this machine, so we cannot safely run untrusted code yet; (b) deterministic regeneration and diffable revisions come for free; (c) stable feature IDs sidestep part of topological naming; (d) edits become parameter changes, not code rewrites. Free-form build123d code stays as a gated escape hatch once the container sandbox exists (SEC-004). Cost: DSL coverage limits what parts we can make; acceptable for a narrow wedge.
2. **Text/structured spec before image input.** Single-view image → CAD is ambiguous and hard to score objectively. Start where geometry can be verified exactly; add vector-PDF drawing input in M2 (dimensions are recoverable text), raster/photo after.
3. **No Postgres/object storage/queue in the first slice.** One process, one machine. Add when a second user or worker exists.
4. **Plan a STEP → drawing + DFM path early.** It complements engineers' existing SOLIDWORKS/Creo work without asking them to switch tools, and reuses the M1 drawing and checks code. Treat it as a candidate commercial lead to test with pilots (see §4).

**Major risks** (full register in RISKS.md): drawing generation quality (auto-dimensioning is hard), LLM spec errors that pass geometry checks but miss intent, OCCT robustness for fillets/booleans, no isolation runtime on Windows, license obligations for bundled OCCT binaries, and unvalidated market demand.

**Highest-ROI MVP wedge:** text/spec → editable parametric prismatic machined part → validated STEP + 3-view drawing + basic CNC DFM notes. See §4 and VALIDATION.md §2.

---

## 2. Layered view (target, not current)

```
Browser UI (React/TS, Three.js)  ── chat, parameters, feature tree, viewer, downloads
        │ HTTPS / JSON + SSE progress
API / control plane (FastAPI) ── projects, assets, jobs, audit, usage metering
        │
Orchestrator (generate → check → render → critique → revise loop, bounded)
   ├─ LLM provider interface (Claude | other | recorded/mock)
   ├─ Spec compiler (Part Spec DSL → build123d)            [precision CAD]
   ├─ CAD worker (OCCT via build123d; subprocess, timeout)  [precision CAD]
   ├─ Validators (B-rep, dims, volume, STEP round-trip, DFM rules)
   ├─ Renderer (VTK offscreen)  ├─ Drawing generator (HLR → SVG/PDF)
   └─ Mesh worker (Blender headless, separate process)     [M5, isolated]
        │
Storage: SQLite → Postgres; local FS → S3-compatible object store
```

Execution isolation: M1 runs only our own compiler output (no LLM-authored code). Any LLM-authored code requires container sandbox: no network, read-only mounts, CPU/mem/time limits, no secrets, per-tenant scratch (SEC-004).

---

## 3. Required comparisons (§6 of master prompt)

Scores are qualitative judgements from documentation knowledge plus this session's environment audit, **not benchmarks**. Items marked *verify* need a spike.

### 3.1 Precision geometry backend

| Criterion | build123d | CadQuery | FreeCAD scripting | Direct OCCT (OCP/pythonOCC) |
|---|---|---|---|---|
| Kernel | OCCT | OCCT | OCCT + own feature/sketch layer | OCCT |
| License (metadata) | Apache-2.0 | Apache-2.0 | LGPL-2.0+ | OCCT LGPL-2.1+exc.; OCP Apache-2.0; pythonOCC LGPL-3 |
| LLM-friendliness | High: explicit Python objects, algebra/builder modes | High, fluent chaining; large public corpus | Medium: verbose, GUI-oriented API | Low: very verbose |
| Feature history | None native (we build it) | None native | **Yes** (PartDesign tree, sketcher solver) but brittle topo naming (improved in 1.0, *verify*) | None |
| Sketch constraints | Limited | Limited (sketch API, experimental solver) | **Yes** (planegcs) | None |
| Drawing support | SVG/DXF projection (HLR) | SVG export | TechDraw (rich, GUI-centric) | HLR primitives |
| Assemblies | Joints (positioning, not a solver) | Assembly + basic constraint solver | Assembly workbench (1.0, *verify*) | None |
| Headless/server | Easy pip wheel | Easy pip wheel | Heavy; harder to sandbox and pin | Easy |
| Maintainability | Active, small team (bus-factor risk) | Active, mature | Large project, slower API churn | Stable but low-level |

**Decision:** build123d primary (ADR-001), CadQuery available (same kernel, already installed). FreeCAD evaluated later as a source for a sketch solver/TechDraw ideas or an optional worker, not as M1 dependency. Keep our Part Spec kernel-agnostic so a swap is a compiler rewrite, not a product rewrite.

### 3.2 Go-to-market: standalone web app vs CAD plugin

| | Standalone web app (+STEP interop) | SOLIDWORKS/Creo add-in |
|---|---|---|
| Fits user's workflow | Medium: export/import step | High: in-tool |
| Native feature history in their CAD | No (STEP only) | Possible via API feature creation |
| Platform | Any browser | Windows + licensed seat; per-vendor API |
| Legal | Our terms | Vendor API/partner terms, *needs review* |
| Build cost | One codebase | One per vendor; COM/.NET; version churn |
| Data control | Our cloud; customers wary | Can stay local; easier security story |

**Decision:** web app first with STEP in/out (ADR-004). Keep a "SOLIDWORKS bridge" spike in backlog (CAD-071) because SOLIDWORKS 2025 is available locally to test, and a plugin may win with consultancies. Do not promise native history.

### 3.3 Mesh generation (M5)

| | Procedural Blender (bpy) | Dedicated text/image→3D models | Hybrid |
|---|---|---|---|
| Controllability/edits | High (script) | Low | Medium–high |
| Organic shapes | Weak–medium | Strong | Strong |
| Precision | Medium (not B-rep) | Low | Medium |
| Cost | Local CPU/GPU (RTX 8000 available) | Per-call fees or self-host | Both |
| License | Blender GPL-2+; scripts importing bpy may be GPL-covered, SaaS use *counsel* | Model-specific terms, *verify* | Both sets |

**Decision:** defer (ADR-010). Benchmark protocol in VALIDATION.md §5.

### 3.4 Agent output form

| | Free-form code generation | Typed DSL / feature graph | Hybrid (DSL default, gated code fallback) |
|---|---|---|---|
| Coverage | Highest | Limited to DSL ops | High |
| Safety | Needs container sandbox | Safe (our compiler) | Safe by default |
| Determinism / diffs | Weak | Strong | Strong for DSL parts |
| Editability (params, tree) | Must parse code | Native | Native for DSL parts |
| Eval | Hard | Schema + geometry checks | Both |

**Decision:** hybrid, DSL-only in M1 (ADR-002).

### 3.5 Deployment

Local single process (M1) → single VM with containerized workers (M2 pilot) → autoscaled workers when demand proven. No Kubernetes until there is load to justify it (ADR-008). Note the dev machine is much stronger than a typical cloud worker; record per-job CPU-seconds so cloud cost estimates are not based on this hardware.

### 3.6 Drawings, sketch constraints, assembly mates, feature history

| Area | M1 approach | Later candidates |
|---|---|---|
| Drawings | OCCT HLR projections via build123d → SVG; our own dimension placement for spec'd features; title block; PDF export (library TBD, license check) | Richer views/sections; GD&T only from approved inputs; evaluate FreeCAD TechDraw, ezdxf (MIT) for DXF |
| Sketch constraints | None needed: DSL features take dimensions directly | planegcs (FreeCAD, LGPL) or SolveSpace solver (GPL-3, *copyleft risk*) |
| Assembly mates | Not in M1 | build123d joints for placement; own constraint solver or CadQuery's; interference via OCCT booleans/BRepExtrema |
| Feature history | Part Spec *is* the history: ordered features, stable IDs, semantic face selectors ("base.top", "hole_pattern_1") | Persistent naming via feature-generated face tags; revision graph |

---

## 4. Wedge analysis

| Wedge | Buyer value | Feasibility (M1) | Objective eval | Notes |
|---|---|---|---|---|
| **W1 Text/spec → prismatic machined part → STEP + drawing** (recommended M1) | Medium: saves modelling + drawing time on simple parts | High | Exact: dims, volume, holes | Builds the reusable core loop |
| W2 Raster image/photo → part | High demo appeal, lower trust | Low–medium | Hard (ambiguous) | M2+; must ask for missing dims |
| W3 Vector PDF drawing → part | High for shops re-modelling legacy prints | Medium | Good (dims extractable) | M2 candidate |
| W4 STEP in → drawing + DFM report | Potentially highest for consultancies/shops; no tool switch | Medium (auto-dimension quality) | Medium | Reuses W1 drawing + DFM code; validate with pilots |

Recommendation: build W1 for M1 because it exercises every layer with exact acceptance checks; choose between W3 and W4 for M2 based on 5–10 pilot interviews (COM-001). This keeps the user's stated preference (text/drawing → part → STEP → drawing) while not overcommitting to image input.

---

## 5. Smallest M1 dependency set (proposed, none installed yet)

| Package | Purpose | License (metadata) |
|---|---|---|
| build123d (pulls cadquery-ocp, numpy, etc.) | geometry, STEP, SVG projection | Apache-2.0 (+ OCCT LGPL-2.1+exc.) |
| pydantic | Part Spec schema | MIT |
| pyvista / vtk | offscreen render | MIT / BSD |
| pytest, hypothesis, ruff, mypy | tests, lint, types | MIT / MPL-2.0 (hypothesis) / MIT / MIT |
| anthropic (optional extra) | live LLM provider | Apache-2.0 |

Transitive license audit (LEG-002) runs before any of these are locked. Environment: dedicated uv venv with Python 3.12, base conda env untouched (ADR-005).

**Paid services needed for local PoC:** none for geometry, checks, render, drawings, tests. Only the live LLM generation/critique step costs money (API usage); CI and most dev runs use recorded responses.
