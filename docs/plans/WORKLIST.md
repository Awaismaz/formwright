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
| 9 | Phase 3: orchestrator (concurrency, critical path, budget), specialist part agents, Gage checker, ticket comments | CD-006…009, CD-016 | In progress (agent) |
| 10 | Phase 4: skeleton + ICD, placeholder bodies, mates by ICD name, swap-in, change requests, live program assembly | CD-010…013 | Todo |
| 11 | Phase 5: program deliverables (drawings, DFM, BOM, release), estimate calibration, timeline | CD-014, CD-015 | Todo |
| 12 | AI quality: brief echo-back approval gate, recorded/replay provider, structured self-critique, 20-prompt benchmark | CAD-028, AGT-002, AGT-006, EVAL-003 | Done (merged); live benchmark parked PD-41 |
| 13 | Mesh test `test_scene_script_refuses_outputs_outside_its_job_folder` timed out (Blender rendered before checking the output path) | — | Done: paths validated before any render (12 s); test_mesh 90/90 |
| 14 | Mesh render failed on a founder model (degenerate triangle broke custom normals) | — | Done: triangles cleaned before normals; regression test; test_mesh 91/91 |
| 15 | 2D drafting without a model in Drawing Studio (tools, dimensions, title block, SVG/PDF/DXF, AI assist + templates) | DRW-017 | In progress (agent) |
| 16 | AI Render Studio: OpenAI image generation with the user's own key; settings + optional prompt → backend prompt refinement → review → generate from a real reference render; encrypted key, consent, honest captions | MSH-012 | In progress (agent) |
| 17 | Landing hero = Design Office story: detailed planetary gearbox brief → Archie plan → tickets to named agents → parallel part build flash → Fitz assembly → gearbox running with true kinematics; real geometry incl. internal ring gear; no 'coming soon' labels anywhere on the landing page; + 'Works with your CAD' section (text wordmarks, STEP-based claim) | UX-020 | In progress (agent) |
| — | Native CAD bridge (SOLIDWORKS pilot) | NCB-* | Backlog by founder decision |
