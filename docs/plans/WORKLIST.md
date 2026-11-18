# Work list (autonomous run started 2026-11-18)

The founder is away: no questions, park decisions (PD-xx), build in this order. Update the status column as items
land. Parallel agents work in git worktrees on disjoint files; the main session merges, verifies, and pushes.

| # | Item | Punch list | Status |
|---|---|---|---|
| 1 | Punch list reconciliation | — | Done (2026-11-18) |
| 2 | Design Office plan, agent names, avatars plan; Native CAD bridge plan (backlog) | CD-*, NCB-* | Done |
| 3 | Chat shop-floor status animation | DS-036 | Done |
| 4 | Chat Discuss / Build mode | DS-037 | Done |
| 5 | Sidebar: Design Studio missing from Modules; collapsed icons bigger + spaced; Modules always expanded | UX-019 | Done (merged) |
| 6 | Landing page: animations + live feature previews of the real software | UX-020 | Done (merged) |
| 7 | Phase 1 smart assembly: assembly from a description; Hex picks Toolbox / company parts; Fitz places + mates | ASM-010, ASM-019 | Done (merged) |
| 8 | Phase 2 Design Office: program model, Archie brief → tree → tickets, Jira board, estimates + roll-up, roster, avatars + animations | CD-001…005, CD-017 | Done (merged) |
| 9 | Phase 3: orchestrator (concurrency, critical path, budget), specialist part agents, Gage checker, ticket comments | CD-006…009, CD-016 | Done (merged; live multi-agent run parked PD-48) |
| 10 | Phase 4: skeleton + ICD, placeholder bodies, mates by ICD name, swap-in, change requests, live program assembly (+ nested sub-assemblies) | CD-010…013 | Done (merged) |
| 11 | Phase 5: program deliverables (drawings, DFM, BOM, release), estimate calibration, timeline; + better layouts, bearing/key/dowel interfaces, frame-tolerant measurement, shared assembly lock | CD-014, CD-015 | Done (merged 28de67b) |
| 12 | AI quality: brief echo-back approval gate, recorded/replay provider, structured self-critique, 20-prompt benchmark | CAD-028, AGT-002, AGT-006, EVAL-003 | Done (merged); live benchmark parked PD-41 |
| 13 | Mesh test `test_scene_script_refuses_outputs_outside_its_job_folder` timed out (Blender rendered before checking the output path) | — | Done: paths validated before any render (12 s); test_mesh 90/90 |
| 14 | Mesh render failed on a founder model (degenerate triangle broke custom normals) | — | Done: triangles cleaned before normals; regression test; test_mesh 91/91 |
| 15 | 2D drafting without a model in Drawing Studio (tools, dimensions, title block, SVG/PDF/DXF, AI assist + templates) | DRW-017 | Done (merged) |
| 16 | AI Render Studio: OpenAI image generation with the user's own key; settings + optional prompt → backend prompt refinement → review → generate from a real reference render; encrypted key, consent, honest captions | MSH-013 | Done (merged); enable with your OpenAI key (PD-43/44) |
| 17 | Landing hero = Design Office story: detailed planetary gearbox brief → Archie plan → tickets to named agents → parallel part build flash → Fitz assembly → gearbox running with true kinematics; real geometry incl. internal ring gear; no 'coming soon' labels anywhere on the landing page; + 'Works with your CAD' section (text wordmarks, STEP-based claim) | UX-020 | Done (merged) |
| 18 | 'Why should I buy this' page (/why): sourced cost of conventional work, risks vs Formwright, worked examples (plate → planetary gearbox), interactive ROI calculator, hire-vs-buy, token explainer; button on landing | UX-021 | Done (merged; landing button pending landing merge) |
| 19 | Installable app (PWA): manifest, icons, service worker (never caches API), install button + iPhone steps, standalone polish, mobile/tablet layout pass of key screens; desktop-only bridges hidden on mobile | UX-018, UX-022 | Done (merged; installable, no installability errors) |
| 20 | Landing: animated phone + tablet showing the installable app | UX-020 | Done (merged) |
| 21 | Native file formats .fwpart / .fwasm / .fwdrw / .fwprog: full parametric model travels between accounts (no recognition), verified by rebuild fingerprint; untrusted-input security (zip guards, hashes, tripwire, isolated rebuild); export + import everywhere; extended: Save/Open file in EVERY module (.fwrender, .fwmfg, .fwcalc, .fwprint, .fwread, drafts in .fwdrw); installed app opens them (file_handlers) | IO-020…IO-025 | Done (merged) |
| 22 | Collaboration: Teams inside a workspace with team roles; per-project permissions (read/comment/edit/admin); Share dialog (people, teams, guests, read-only links); presence, activity, comments, soft locks; branches + merge requests with 3D/param diff, 3-way merge, conflict resolution, protected main | PLT-010, PLT-017, CAD-062, PLT-020…024 | Done (merged; PD-50…53 parked) |
| 23 | Drawing depth: cosmetic threads + thread callouts (model metadata → STEP/drawing), detail views, GD&T frames only from explicit input (incl. ICD datums for Design Office sheets), STEP-in → auto drawing with inferred dims labelled | CAD-027, DRW-011, DRW-013, DRW-016, CD-021 (the ICD GD&T row; CD-019 is the frame-tolerant Gage) | Done (merged; DRW-016 awaits a pilot rating; PD-58) |
| 24 | Engineering hygiene: unit/coordinate round-trip matrix across all export formats, dependency licence audit + SBOM, complete agent run record (model ids, versions, cost, timings), same-prompt ×5 repeatability harness (replay-based, no live spend) | IO-008, LEG-002, AGT-009, EVAL-008 | Done (merged 63a9887; PD-56) |
| 25 | Studio intelligence: agent fills the PropertyManager for small edits (OK to apply, no code), change-impact preview before an edit (where-used, broken mates, refit, new interference) | DS-035, ASM-018 | Done (merged; PD-57) |
| 26 | Sheet metal: base flange, edge flange, bends with K-factor, relief, unfold to flat pattern (DXF), Studio UI + agent support, drawing flat-pattern view | CAD-026 | Done (merged; PD-60) |
| 27 | Design Office next: horizontal shafts in side walls with caps over bearings, optional per-part review gate, change notices after release (Rev B flow), motion range check (rotate gear trains / sweep joints for collisions) | CD-022…CD-025, ASM-011, ASM-022 | Done (merged; PD-61) |
| 28 | Agent platform: LLMProvider interface (structured output, vision, metering) + second provider stub passing the same tests, SOLIDWORKS STEP export pathway with disclosure, Blender exports in the IO matrix | AGT-001, AGT-013, CAD-070, IO-008b | Done (merged; PD-59) |
| 29 | Quality fixtures: golden assembly fixtures FX-04/05/06 (original designs, provenance, checks), advisory render similarity metric (logged, never gating) | ASM-012, EVAL-006 | Done (merged; PD-62) |
| 30 | Studio follow-ups: sheet-metal corner relief + holes across bends in the flat + jog/miter flange; fw-edit for extrude/pattern/multi-feature edits; impact preview for tree actions (suppress/delete/reorder) and Ctrl+K commands | CAD-026 follow-ups, DS-035, ASM-018 follow-ups | Done (merged; ; PD-63) |
| — | Native CAD bridge (SOLIDWORKS pilot) | NCB-* | Backlog by founder decision |
