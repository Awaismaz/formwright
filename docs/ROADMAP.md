# Roadmap

Milestones are sequencing hypotheses, **not release promises**. Reorder on evidence. Item IDs refer to `PUNCH_LIST.md`.

| Milestone | Goal | Exit criteria | Key items | Status |
|---|---|---|---|---|
| **M0 Discovery & architecture** | Audit, licences, wedge, risks, PoC plan | Docs created; ADR-001/002/003 approved; ARC-010 spike passes golden plate checks; LEG-002 audit run | GOV-001..004, ARC-001..012, LEG-001..006, COM-001 | **In progress**: approved; ARC-010 spike passed; live viewer done; next ARC-011 DSL, LEG-002 audit |
| **M1 Vertical slice (MVP)** | Text/spec → prismatic machined part → STEP + drawing + checks + render + critique loop; CLI then minimal web UI | VS-1 acceptance criteria 1–8 (VALIDATION §2) | CAD-001..012, CAD-028, IO-001..003, IO-008, AGT-001..010, AGT-012, DRW-001..006, EVAL-001..005, EVAL-008, PLT-002/003/005/011, SEC-001..003, SEC-009, UX-001..004, UX-007, INF-001..005, DOC-001..004, MFG-001, LEG-010 | Ready (after approval) |
| **M2 Professional single-part workflow** | Vector-PDF drawing input **or** STEP→drawing+DFM (decided by pilots); revisions; more part classes; persistence; pilot-ready | 3 pilot users complete real tasks; time-saved measured | CAD-020..030, CAD-070, IO-004..005, IO-007, PRN-001..003, PRN-006, DRW-010..016, PLT-001..010, SEC-004..008, INF-006..007, COM-002..004, COM-006 | Backlog |
| **M3 Assemblies** | Multi-part, mates, interference, assembly STEP, BOM, exploded views | FX-04/05/06 pass assembly checks | ASM-001..012 | Backlog |
| **M4 Manufacturing & engineering intelligence** | Multi-process DFM, cost-driver advice, engineering checks with provenance | Rule tests, reviewed calculators, advice-level labelling | MFG-010..020, ENG-001..012 | Backlog |
| **M5 Mesh Studio & deeper native CAD** | Blender pipeline, generative-model benchmark, sketch solver, richer history | Benchmark report; editable scene output | MSH-001..012, CAD-060..072 | Backlog |

## MVP scope vs long-term scope

- **MVP (M1):** one input type (text/spec), one part family (prismatic machined plates/brackets), STEP/STL/GLB out, 3-view drawing, basic CNC DFM notes, bounded critique loop, CLI + minimal web viewer, local only.
- **Long-term:** image/drawing input, assemblies, native feature history and sketches, associative drawings, GD&T, multi-process DFM/costing, engineering advisor, Mesh Studio, CAD plugins, multi-tenant cloud, billing.

## Not planned unless evidence demands

- Training a proprietary CAD model (requires EVAL-003 showing general LLM + toolchain inadequate, plus data rights and ROI case).
- Microservices, Kubernetes, multi-region.
