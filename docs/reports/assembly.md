# Assembly Studio (module `assembly`): report

Branch `module/assembly`. Assembly Studio is now **Live**. You can assemble verified project parts and Toolbox
components, mate them with a solver that reports under- and over-defined states, check interference volumes and
clearances exactly, explode the assembly, get a BOM (CSV), and export an assembly STEP that keeps its hierarchy and
is re-import verified. The signature feature is **Fastener auto-fit**: pick a hole (or a recognised pattern) and get
the ISO bolt + washers + nut. The size comes from the clearance hole, and the standard length comes from the grip
measured through the mated parts. The rule used is cited and the result is flagged VERIFY.

## What was built

| Area | What it does |
|---|---|
| Assembly model (ASM-001) | JSON documents in `<data>/assemblies/<org>/<id>/assembly.json`, holding instances, mates and groups. A per-org part cache in `_parts/<key>/` holds `part.step`, `topo.json`, `refs.json` (exact mate geometry, unrounded) and `info.json` (volume, bbox, recognised holes and patterns). Cache keys are immutable: `p_<project>_<build_id>` for a project build and `t_<code>_<hash>_v<toolbox VERSION>` for a Toolbox part. Instances are pinned to a build, so the assembly does not change when the project is rebuilt. Instead the tree shows **"Updated"**, and **Refresh** re-maps each mate reference to the same geometry in the new build, or marks the mate "broken" if that geometry is gone. Instances are named SOLIDWORKS-style (`Mounting Plate<1>`). Fastener stacks are sub-assembly groups. Atomic writes; a per-assembly lock. |
| Placement (ASM-002) | Each placement is a rigid 3×4 transform. The first part goes in fixed at the origin; later parts go in beside the assembly. The Move box offers ±X/Y/Z steps and ±90° rotations about the part centre, or an exact `T` through the API. Moves are re-solved, so only the free directions change. A part held fully by its mates says so instead of moving. |
| Mates (ASM-003) + DOF (ASM-006) | Mate types: Coincident (anti-aligned faces), Flush (aligned, coplanar), Distance (gap, with flip), Angle (between normals) and Concentric (cylinders, circular or straight edges). **Smart** picks coincident or concentric from the two selections. `src/aicad/assembly/solver.py` is a damped Gauss-Newton (Levenberg-Marquardt) solver over 6 variables per free instance, with rotations scaled by the assembly length. Each new mate is first pre-aligned (minimal rotation, then translation), so faces end up facing each other, not back to back. **Conflicts:** when the full solve leaves a residual, mates are re-added one at a time in creation order. A mate that can't be satisfied with the earlier ones is reported as a conflict (with its mm/° residual) and **not applied**, so the parts keep the placement the consistent mates give (status Over-defined, tree prefix `(+)`). **DOF** = 6n − rank(J) from an SVD of the constraint Jacobian at the solution. Per instance it is the rank of that instance's null-space block, split into translations and rotations. When the only freedom left is a spin about a concentric axis, it is labelled a free spin, which is normal for fasteners: "Fully positioned · 16 free spins". Redundant equations are counted, but redundancy is not treated as an error. Coincident + concentric is genuinely 2-redundant. |
| Interference (ASM-004) | Exact OCCT `BRepAlgoAPI_Common` between every pair of instances whose world AABBs overlap, with volumes from `BRepGProp`. Overlaps are shown in red in the viewer: the other parts are ghosted, and the overlay is hidden while the assembly is exploded. **Threads are cosmetic**, so an overlap that lies entirely inside a fastener's nominal thread Ø is classed as "thread engagement", not a clash. Face contact gives zero volume and is not reported as interference. |
| Clearance (ASM-005) | Exact `BRepExtrema_DistShapeShape` for every mated pair, plus every pair whose boxes come within `max(2, 5 % of the assembly size)` mm. Each pair gets a status: clear / contact / thread / interference. Clicking a row draws the minimum-distance line in the viewer. |
| Exploded view (ASM-007) | Deterministic offsets per instance, computed server-side. Each part moves away from the part it sits on, along that part's outward face normal (contact mates first). Otherwise it moves along a concentric axis, and parts with no mates move radially. Offsets accumulate down the mate tree, so a fastener stack spreads in order (washer, then bolt; washer, then nut). A slider runs from 0 to 100 %. |
| BOM (ASM-008) + DRW-014 data | Items are grouped by part snapshot: project parts first, then Toolbox parts by family, size and length. Columns are qty, part, description (project revision or component type), standard (ISO 4017/4032/7089…), designation, material, mass each/total, and the instance ids. Mass = exact volume × nominal density (`materials.guess`), with a "verify" note. CSV download. JSON at `GET /api/m/assembly/assemblies/{id}/bom` is ready for a Drawing Studio BOM table (DRW-014: data only, no table rendered). |
| Assembly STEP (IO-006) | build123d/XCAF export with a root named after the assembly, top-level parts, and one sub-assembly per fastener stack ("Fastener stack 1 (Hex bolt ISO 4017 M6×25 + 2 washers + nut)"). Product names are part names, and each part's geometry is written once and shared by its instances. A fixed timestamp and `normalize_step` make the output deterministic. **Re-import verification on every export:** leaf count, sub-assembly membership, and the world position of every instance's vertices against its transform. The UI reports "18 instances, 4 sub-assemblies; re-import matched (placement deviation 0 mm)". |
| **Fastener auto-fit** (signature) | (1) Pick a hole in the view (recognised holes glow green) or choose one from the list. A recognised pattern ("4 × Ø6.6 grid · along Z") can be fitted as a whole. (2) **Grip probe** (worker): line/solid intersections parallel to the exact hole axis, on a ring of 8 rays just outside the hole, through every instance (transformed into each part's local frame). The clamped stack is the chain of parts touching end to end (within 0.01 mm). A shank probe at 0.95 × d/2 plus an axis probe tells a clearance member from a restricting one. A restricting member at the end of the stack with a coaxial **tap-drill-size** hole (d − 1.25P … d − 0.75P, or modelled at nominal d) makes a **tapped joint**; otherwise the hole is reported as **blocked** by that part. The probe also measures the free space beyond each end, so it can warn when a head or nut would hit something. (3) **Selection** (`fasteners.py`, pure). Size from the ISO 273 clearance table (fine/medium/coarse); a non-ISO hole falls back to the largest size that passes, with a warning. Through joint: L ≥ grip + washers (ISO 7089) + nut m (ISO 4032) + 2 × P (ISO 261), then the next ISO 888 length within the Toolbox range. Tapped joint: engagement ≥ 1.0 d in steel, 1.5 d in cast iron and copper alloys, or 2.0 d in aluminium, plastics and unknown materials. The usable thread is limited in blind holes (depth − 2P), and a through-tapped screw may stick out by up to 1 d. When no standard length fits, the result says so. Every proposal carries the rule text, the sources and a VERIFY flag. (4) **UI:** a to-scale half-section of the joint (clamped parts hatched, washers, head, nut, thread hint, grip / L / protrusion dimensions), the length sum, the ISO 888 series with the chosen length highlighted and shorter lengths struck through, protrusion in threads, the clearance class sentence, warnings, and a per-hole table when lengths differ. (5) **Insert:** the stack goes in as Toolbox instances (generators called unchanged, VERSION untouched), one sub-assembly per hole, placed exactly along the axis. Each stack is mated: every element concentric with the hole, plus a contact chain seat → washer → head and seat → washer → nut. The mates are satisfied by construction, so after insertion the stack shows as positioned with free spins. |
| Worker | `src/aicad/assembly/worker.py`: a warm subprocess per org on the shared `Worker` base, the same pattern as the drawing worker. Ops: `prepare`, `interference`, `clearance`, `analyse`, `probe` and `export`. The web process never imports the kernel. `service.py` / `solver.py` / `fasteners.py` / `store.py` are pure Python + numpy. |
| API | `src/aicad/platform/routers/mod_assembly.py` serves `/api/m/assembly/...` (endpoints listed in the module docstring). Every route is org-scoped (another org gets 404), returns 402 when the module is locked (plan, `addon_assembly`, or God `bypass_paywall`), gives viewers 403 on any change (they can still read, get the BOM and CSV, and download the last STEP), and returns 409 with a plain message for user-fixable problems (no verified build, wrong pick type, blocked hole…). Part topology is served only from the caller's org cache, with keys validated by regex. The list thumbnail upload is checked to be a PNG (magic bytes) of at most 1.4 MB. |
| Frontend | `web/src/pages/app/modules/assembly/`: `index.tsx` (list with snapshot thumbnails, new/delete; `?project=<id>` reuses or creates that project's assembly with the part fixed; `?assembly=<id>` opens one), `Workspace.tsx`, `Viewport.tsx` + `viewer.ts` (its own three.js `AssemblyViewer`: shared per-part geometry, instance matrices, exploded offsets, face and edge picking that returns (instance, local id), hover/pick/mark overlays, red clash volumes, clearance line, ghosting, an isometric snapshot for the list. It imports `LIGHT`/`DARK` and the `Topo` types from `web/src/viewer/` and doesn't edit them), `Tree.tsx` (instances with eye, `(f)/(−)/(+)/⟳` state prefixes, "Updated" refresh chip, fastener stacks grouped, mates list with conflict and broken markers, flip/suppress/delete menus), `MatePanel.tsx` (Smart + 5 types, two reference slots describing the pick, e.g. "Cylinder Ø6.6 · Mounting Plate<1>", value and flip), `FastenPanel.tsx` + `StackDiagram.tsx`, `CheckPanel.tsx` (interference + clearance, plus the BOM panel), `InsertDialog.tsx` (verified projects with thumbnails, Toolbox families with parameter forms). The header has an editable name, the solve chip (Fully positioned / Under-defined · n DOF / Over-defined · n conflicting), Insert, Export STEP and Download STEP. |
| Catalog | `assembly` → `"live"`, with a summary and bullets describing what ships. |

## Files

- New: `src/aicad/assembly/{__init__,xform,solver,fasteners,geometry,store,service,worker}.py`,
  `src/aicad/platform/routers/mod_assembly.py`, `tests/test_assembly.py`,
  `web/src/pages/app/modules/assembly/{index,Workspace,Viewport,Tree,MatePanel,FastenPanel,StackDiagram,CheckPanel,InsertDialog,bits}.tsx`,
  `web/src/pages/app/modules/assembly/{viewer,types}.ts`, `docs/reports/assembly.md`.
- Shared file touched (allowed): `src/aicad/platform/catalog.py` (the `assembly` entry only). No new dependencies.
  No Design Studio, viewer-engine or toolbox files were edited.

## Punch-list rows (proposed status for the master)

| ID | Status | Evidence |
|---|---|---|
| ASM-001 | Done | Documents + per-org part cache; tree persisted and reloaded (API test, walkthrough reload); build pinning + "Updated" + refresh with reference re-mapping (`test_api_full_flow`: stale → refresh, 0 references lost). |
| ASM-002 | Done | Rigid transforms; insert placement; Move box; exact `T` (API test places the block at z = 30, then the mate brings it to z = 10). |
| ASM-003 | Done | 6 solver tests against hand transforms: block bottom centre at exactly (30, 20, 10) to 1e-9; angle 0 → identity rotation; distance 5 → z = 15; angle 30° to 1e-7; conflict isolated (`m3`, residual 5.000 mm, earlier mates kept); redundancy counted (2 for coincident + concentric). UI: picked three mates in the walkthrough; L-bracket fully positioned at (−30, −25, 10) = hand value (−60 + 30, −40 + 15, 10). Over-defined state screenshot. |
| ASM-004 | Done | Two 20 mm cubes offset (5, 3, 2): 4590 mm³ = 15·17·18 (rel 1e-9); Ø10 pin in Ø8 hole × 12 mm: 108π mm³ (rel 1e-9); face contact → none; thread classification. Walkthrough seed: a second plate 2 mm into the first gives **16 343.089 mm³**, matching the hand value 120·80·2 − chamfer (200 − 4/3) − pocket 2·(1200 − (4 − π)·9) − holes 4·π·3.3²·2 = 16 343.089. |
| ASM-005 | Done | Offset cubes: √32 = 5.656854249 mm (abs 1e-9); a rotated neighbour at 2.5 mm; API: bolt shank to plate 0.300 mm = (6.6 − 6)/2; walkthrough minimum clearance 0.2 mm = washer bore (6.4 − 6)/2. |
| ASM-006 | Done (new) | DOF per instance from the Jacobian rank; spin detection (tests and UI). |
| ASM-007 | Done | API test (washer up, bolt further up, nut down); walkthrough screenshot at 70 %. Not yet a drawing view. |
| ASM-008 | Done | BOM quantities in the API test {Plate 1, Block 1, M6×25 bolt 4, washer 8, nut 4}; plate mass = exact volume × 2.70; CSV. Walkthrough total 355.92 g. |
| ASM-009 | Partial | Uses the existing Toolbox tables (ISO 4017/4762/4032/7089) and adds ISO 273 / 261 / 888 data in `fasteners.py`, with sources cited and flagged verify. |
| IO-006 | Done | `test_step_export_reimport_preserves_tree_and_placements` (3 instances, 1 sub-assembly, placement deviation < 1e-9, a single shared product); API export of 18 instances / 4 groups, re-import verified; walkthrough the same (200 611 bytes, deviation 0). |
| DRW-014 | Data only | BOM JSON endpoint for Drawing Studio; no drawing table yet. |
| (new) ASM-013 Fastener auto-fit | Done | Length hand cases (5 through, 2 tapped, including an exact-boundary case and an honest no-fit case); API: 4-hole pattern → 4 × M6×25 + 2 washers + nut, grip 10.000, L_min 20.4, protrusion 6.6 mm; inserted stacks placed at z = 11.6 (bolt head underside) and −1.6 (nut) exactly. |

## Tests

`tests/test_assembly.py`, 19 tests, about 18 s: 6 solver, 2 + 5 parametrised fastener-selection, 5 kernel
(prepare/refs, interference, clearance, STEP) and the API flow. The API flow covers 401/402/409, create from project,
mate, bad pick, propose/accept, BOM/CSV, analyse, explode, export/download, seeded interference, stale/refresh,
thumbnail, viewer 403 and other-org 404s. There is also a catalog test. Gate: `ruff check src tests` is clean,
`npx tsc --noEmit` is clean, `npx vite build` passes. Full suite: **201 passed** (10 min 07 s).

## Walkthrough (port 8776, scratch data, God mode, seeded demos)

Opened from the plate project (`/app/modules/assembly?project=…`); it created "Mounting Plate assembly" with the plate
fixed. Inserted the L-bracket through the dialog. Made three mates by **clicking faces in the viewer**: Smart →
coincident (plate top / bracket bottom), then two flipped distance mates of 30 mm and 15 mm (bracket leg face / plate
end, bracket side / plate front). Status: **fully defined**, bracket at (−30, −25, 10). In the Fasten tab, clicked a
plate hole **in the canvas** and got the proposal: 4 × "Hex bolt ISO 4017 M6×25 + 2 washers + nut", grip 10 mm
(all 4 holes), L_min 20.4 → 25, protrusion 6.6 mm, "Ø6.6 is the ISO 273 medium clearance hole for M6". Inserted
4 stacks (18 instances, 35 mates; Fully positioned · 16 free spins). Check: 0 interferences, 29 pairs checked, 33
clearance rows, minimum 0.2 mm. Seeded interference: 16 343.089 mm³ (hand value above), shown in red. Exploded
to 70 %. BOM: 1 plate 242.09 g, 1 bracket 63.10 g, 4 bolts 8.27 g, 4 nuts 2.38 g, 8 washers 1.02 g; total 355.92
g. STEP: 18 instances, 4 sub-assemblies, re-import matched. Also checked: the over-defined state (a contradicting
5 mm distance mate: red chip, `(+)` on the bracket, mate struck red and not applied) and the Toolbox insert tab.
Every screenshot was read. The run had 0 console or page errors. Fixes made from the screenshots: project
thumbnails in the insert dialog overflowing the modal; the Fasten "Insert" button off-screen (now a sticky footer);
the list card showing "Under-defined" for an assembly whose only freedom was fastener spins; an ambiguous pattern
label (now "along Z"); the list using the project image (now an isometric snapshot of the assembly); the selection
tint competing with picks in the Mate and Fasten tabs.

## Known limits

- The mate set is 5 types: no tangent, gear, slot, cam, width or limit mates, and no plane-to-axis mates. Cones can't be
  mate references (topo.json has no cone apex point). Angle mates are ambiguous about the direction of rotation,
  as in other CAD tools.
- The solver is iterative (LM with a pre-align). A very far-off start on a part that already has other mates can be
  misreported as a conflict. The dialog keeps the mate, so the user can flip or delete it.
- No drag-to-move in the viewer, and no sub-assembly documents (only fastener groups). Assemblies can't be inserted into
  assemblies.
- Fastener auto-fit: metric coarse M3–M24 only. Hex bolt (ISO 4017, fully threaded) or SHCS; no ISO 4014 partial
  thread, countersunk screws, spring washers or lock nuts. Counterbores are not recognised as head seats. The grip
  probe needs flat seats square to the hole (it warns otherwise). Size is chosen from the clearance hole first. The
  length rule is common practice, not a joint calculation: no preload, strength or fatigue (link out to the
  Engineering Advisor's bolted-joint calculator).
- Interference and clearance use nominal geometry. Tolerances, deflection and thread geometry are not modelled.
  Pairs are pre-filtered by AABB, so very large assemblies (hundreds of parts) will be slow, and nothing is cached
  between runs.
- The exploded view has no per-part manual offsets and no explode steps saved as a configuration.
- DRW-014 is data only.
- The list thumbnail is uploaded by an editor's browser after a change. Viewers never update it.

## Parked decisions (defaults used)

| # | Question | Default used |
|---|---|---|
| PD-A1 | Where do assemblies live: inside a project, or as their own documents? | Their own documents per org, with an optional home project (`?project=` reuses it). This keeps project builds untouched. |
| PD-A2 | Should an assembly follow project rebuilds automatically? | No. Instances are pinned to a build and flagged "Updated"; the user refreshes. |
| PD-A3 | Fastener length rule and engagement factors | Protrusion ≥ 2 P beyond the nut; engagement 1.0/1.5/2.0 d (steel / cast iron and copper / aluminium, plastic and unknown); next ISO 888 length; all flagged VERIFY. A company standard could override these later. |
| PD-A4 | Default fastener style | ISO 4017 hex bolt + 2 ISO 7089 washers + ISO 4032 nut; head on the upper side (flip available). |
| PD-A5 | Who may run checks and exports | Engineers and above. Viewers can read, get the BOM/CSV and download the last STEP. |
| PD-A6 | Are redundant (consistent) mates an error? | No. Only conflicts make the assembly over-defined; redundancy is counted internally. |

## Make-tab entry wanted

On the Studio's Make tab, add **"Assemble"** (module code `assembly`, lucide icon `boxes`), linking to
`/app/modules/assembly?project=<id>`. It opens that project's assembly, or creates one with the part fixed at the
origin. Suggested subtitle: "Mate with other parts, check clashes, fit ISO fasteners".
