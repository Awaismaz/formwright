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

## Smart assembly: Hex and Fitz (ASM-010, ASM-019), 2026-11-18

Phase 1 of the Design Office plan (docs/plans/CHIEF_DESIGNER.md §2.3, §6). Branch `wip/smart-assembly`.

**What it does.** A new **Describe** tab (the default for an empty assembly). You type what goes in, e.g.
"bolt the motor bracket onto the base plate with 4 M6 bolts, washers and nuts, and two Ø8 dowel pins into the base
plate". **Hex** (librarian) reads it with zero tokens, and **Fitz** (assembly) proposes where each item goes and in
which order. The confirmation list shows, per item: the component, its source (Toolbox / Your part / New design), the
confidence, the quantity, editable parameters (fastener size and washers, bearing designation, dowel Ø and length…),
Hex's status line ("Hex found Hex bolt ISO 4017 M6×25 in the Toolbox") and Fitz's intended placement and mates.
Nothing changes until **Approve**. Fitz then inserts, places and mates the parts, runs the exact interference check and
reports, e.g. "Fitz fixed 1 base part, mated 4/4 bolts, placed and mated 3 parts, 0 clashes". The agents show as round
badges (Hex: a nut on a bolt, amber; Fitz: two parts and a dowel, blue). The badges animate while working and are
static when the system asks for reduced motion (`web/src/components/AgentBadge.tsx`).

| Piece | How |
|---|---|
| Hex: reading (`assembly/librarian.py`) | Splits the text into items. Accessories stay with their fastener ("bolts with washers and nuts"); "with 4 M6 bolts" starts a new item. Reads the quantity (digits, words, "x6", "a pair of"), a target hint ("for the plate holes", "on the shaft", "onto the base plate") and an own-parts hint ("from my projects", "our"). Toolbox reading is deterministic: M-size × length, `62xx/60xx` bearings, Ø × L dowels, Ø shafts, gears via `toolbox.match`, nuts, washers and standoffs. Every value goes through `toolbox.normalize`. Values that were not written are marked "(default)". |
| Hex: your parts | Verified projects of the workspace, matched by name words (description words count half) and, for size queries ("the 120x80 plate"), by `similarity.size_match`. Order of preference: a designation (M6, 6204, Ø8) always means the Toolbox; an own-parts hint means your parts; otherwise a strong name match beats a generic Toolbox noun ("the motor bracket" → your Motor Bracket, not the Toolbox L-bracket). When nothing is found the item is a **New design**, with a "Design it in the Studio" button that creates a project and opens the Studio chat with the line. |
| Hex: AI fallback (opt-in) | Used only for lines the parser could not read, and only when you press "Read with AI (uses tokens)". It is one text-only turn of the design agent's model with no tools (`librarian.ask_ai`, the only model call; tests replace it). The answer is never trusted: codes must exist, parameters must pass `toolbox.normalize`, and parts must be existing project names. Tokens are shown on the plan and charged like any AI step (God mode's bypass is respected); an empty balance gives 402. |
| Fitz: plan (`assembly/fitz.py`) | A target resolves to an instance in the assembly, to another item of the plan, or to one of your parts that the text names ("onto the base plate" adds Base Plate as the base). Insertion order: base → mount → seat → dowel → fasten → place. A bearing without a size is sized from the shaft seat (bore = seat Ø, 62xx first). A gear's bore follows the seat unless it was written. |
| Fitz: mount | Hole-pattern match. On each part, the face where its holes open (the outermost along the axis, preferring the face looking up); then a rigid in-plane fit of the hole centres. The two b holes farthest apart anchor the fit, every hole must land within 0.02 mm on a compatible hole, and the smallest turn wins. Then a coincident mate and 2 concentric mates. With no match the part is placed beside the assembly with "mate it by hand". |
| Fitz: seat | Shaft seats are convex full cylinders. Hole faces are excluded, angular coverage comes from the topo mesh, and separate stretches on one axis are separate seats (so the demo shaft's two Ø20 journals are two seats). Each end is either a shoulder (a flat face looking along the seat) or a free end. Every free shoulder is used first (coincident), then free ends (flush). A seat shorter than the part is noted. |
| Fitz: dowels | Free holes within 0.05 mm of the pin Ø (a hole that already holds a dowel or bolt is skipped). Concentric mate plus an aligned distance mate, so half the pin (or the hole depth, if less) is in the hole. |
| Fitz: fasteners | ASM-013/015 auto-fit (`service.accept`) on the target part's free holes of the asked size. A hole lined up with another part's hole is fitted from the smaller one, so the stack passes both. Without a target: lined-up pairs first, then the base part. If the measured grip needs a different length from the one written, the log says so ("You asked for length 25; the measured grip needs L ≥ 26.4 mm, so 30 mm was used"). |
| API | `POST /api/m/assembly/assemblies/{id}/smart/plan` {text, ai} → the plan (no change). `POST …/smart/run` {items} → the view + `result` {log, summary, clashes, counts}. The edited plan is re-validated on the server (`_clean_items`: Toolbox params, org projects, instances of this assembly). Viewers get 403. |

**Tests** (`tests/test_assembly_ai.py`, 21 tests, about 40 s, no model calls):
- A 12-case Toolbox fixture set (bolts, cap screws, bearings, dowels, nuts, washers, shaft, gear, standoffs);
  accessories + target; splitting; company parts vs Toolbox vs new design; AI answer validation; bearing for a seat.
- Kernel/API, plate + bracket. Plate 160 × 80 × 10 (4 × Ø6.6 + 2 × Ø8), bracket base 120 × 80 × 6 with the same
  pattern, all from one sentence. Bracket at z = 10 exactly, 4 of 4 holes; 4 × M6×30 (grip 16 → L ≥ 26.4); 2 dowels
  with their ends at z = 20. Every mate ok, 0 interference, and the AI stub is never called.
- Stepped shaft (Ø20 / Ø30 / Ø20) + "2 6204 bearings": z 16..30 and z 90..104 (turned over). A third bearing goes
  flush with a free end. 0 interference.
- Empty assembly + "bolt the motor bracket onto the base plate with 4 M6 bolts": base plate fixed, bracket mounted,
  4 stacks.
- AI fallback: runs only on request and only for the unread line; tokens debited exactly; a bad edit is refused (422).
- Frontend: `smart.test.ts` (2 tests).

**Walkthrough** (port 8793, throwaway data dir, God mode, seeded demos, puppeteer-core 25.18.1):
1. Demo stepped shaft + "2 bearings on the shaft". Hex picked a 6204 from the Ø20 seat, and Fitz seated one against
   each shoulder: 0 clashes. A first run had put both on the same journal (one at the shoulder, one at the free end).
   Fixed by splitting seats per stretch and using every free shoulder first.
2. Demo mounting plate + "4 M6x25 bolts with washers and nuts for the plate holes; two Ø8 dowel pins; a gearbox
   housing". The plan said "No free Ø8 hole found" for the dowels and "New design" for the housing. Result: "Fitz
   mated 4/4 bolts, 2 left to mate by hand, 0 clashes" (M6×25, grip 10).
3. Empty assembly, with the test fixtures written into the scratch workspace, + the sentence above. Base Plate added as
   the base, Motor Bracket mounted (4 of 4 holes), 2 dowels, 4 × M6×30. Check: 35 pairs, no interference, minimum
   clearance 0.2 mm. BOM: 20 parts, 6 lines, 1.082 kg.

0 console or page errors. Fixes made from the screenshots:
- The fifth tab was clipped in the 360 px panel: tab icons are now hidden and the padding is tighter.
- Warning results showed a "done" tick.
- For a fastener with no length, Hex's line read "M5×30"; it now says "length to suit the grip".
- "with M5 bolts" did not start a new item.

**Limits.**
- Mounting needs matching hole patterns: no face-only or slot mounting, no pins into slots.
- One interface per item, and Fitz does not invent mates beyond the ones above.
- Fits are nominal. A Ø8 dowel in a Ø8 hole and a 6204 on a Ø20 seat are line-to-line; press fits, tolerances and
  bearing retention (circlips, nuts) are not modelled.
- The AI fallback maps a line to one component; it does not plan placements.
- The plan is not saved: plan again after editing the assembly.
