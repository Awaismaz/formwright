# Master-model ICD on split housings, and "Fix with Archie" that really fixes (branch `wip/master-icd-fix`)

Founder report (2026-11-21, planetary benchmark attempts A3 and A4): the office took the master-model path, the master
models were sound, but the interfaces document (ICD) drafted from them had problems that blocked the interfaces gate,
and "Fix with Archie" came back with the problems unchanged, so the program could never start. Founder rule: "Fix with
Archie must really fix"; if Archie can't, the office fixes it deterministically or says exactly what the engineer
should change.

The problems (verbatim):

- A4 (planetary, correct plan): `Housing base: clearance opening 1 Ø47 through (across the joint) Ø47 at (-67.5, 0)
  leaves less than 1 mm of wall to the edge of its envelope.` (and the same on the cover at (60, 0));
  `Master model: Sun gear is not connected to the Housing base through any joint` (and Input shaft, Planet pin #1..3,
  Planet carrier, Output shaft); plus `Planet gear` and `Ring gear`: no interface connects it.
- A3 (two-shaft reducer from a planner fallback): the same two kinds (Ø52 and Ø72 openings; Input shaft and Pinion
  not connected).

Result: both recorded masters now give an ICD with **no problem** (warnings only, all true observations), and a
program stuck with the old reading clears on one "Fix with Archie" click (re-measure, no tokens).

## Root causes

1. **Half bores summed into a "full" hole.** Both housings are split on the shaft axis, so each half has a half
   bore (180 degrees) at each end. The measurement grouped cylinder faces by line and radius and summed their
   angles over the whole line: two half bores at the two ends made 360, so each half "had" a full Ø47 hole centred
   on its own split face. Consequences: (a) the bore opening at the bearing cap's joint was a passage feature
   centred on the envelope edge, hence "less than 1 mm of wall"; (b) the Ø47 line through base and cover (and the
   Ø25 line through both caps, the Ø20 line through sun and carrier) read as a bought-out **pivot pin**; (c) the
   recognised hole's extent mixed two cylinders' frames, so the output end's holes were missed (the output cap's
   screws read as lone holes).
2. **Bearings are bought out, so nothing carried the shafts.** The master never models bearings (by its own rule).
   A shaft in its bearing bore was only a "pass" (a pin in a larger bore), not a joint, so input shaft, sun, output
   shaft, carrier and pins had no path to the base. The bogus pivot pin above happened to connect some bodies,
   which is why the A4 list was partial.
3. **Meshes and the ring seat were not joints.** Pitch circles touching (sun / planet, planet / ring) and the ring
   gear's Ø210 in the split Ø210 cavity were "touch only along an edge": no interface at all for the planets and the
   ring (`no interface connects it`). A non-turned round part (a gear, a ring) in a bore was kept as a "spigot note".
4. **Why "Fix with Archie" changed nothing.** The ICD is rebuilt from the measurement stored on the plan; the fix
   only changes interface numbers and grows envelopes in 2 to 8 mm steps. No number change can make a missing joint,
   and no small growth reaches a Ø47 opening centred on the edge (it needs about 50 mm). Then the supervisor step
   explained them generically ("change the plan, or edit the interface it names"), which was not true for these.

## What changed

- `src/aicad/master/measure.py` (measurement version 2):
  - cylinders are read per stretch along their line (faces that overlap axially); a full turn is a bore or pin, a
    concave half turn is a **half bore** (`halves`); holes are built from these stretches (two tapped holes on one
    line at the two ends are two holes, each 9 deep; a half bore is a hole with `full: false`);
  - **split bores** (`splits`): a half bore in each of two bodies on one line, of one Ø, the line in their joint
    plane; a split bore on a pin of a third body is a fit (`split`, `split_with`) or a pass;
  - **tangent** contacts: two pitch circles touching on parallel axes, external ((d1 + d2) / 2) or internal
    ((D - d) / 2), within 0.1 mm;
  - pivot pins only through full holes on a line no modelled shaft or pin occupies.
- `src/aicad/master/skeleton.py`:
  - **bearing seats from the passes**: a shaft in a larger bore is a `bearing_seat` when the plan has a bearing of
    exactly that bore and outside Ø (its written designation, the design graph's, or, when the plan names none, the
    ISO 15 Toolbox table); bearings side by side from the open end (the end farther from the body's middle), one per
    bore first, then the rest of the planned quantity where there is room; the rest of the bore as modelled; the
    first half of a split bore places the bearings, the other carries its half seat; a bearing named after another
    part ("Output bearing") is not used for this one's bore; no shoulder in the master is a warning (`no_shoulder`);
  - fits of round parts (a gear, a ring) in a bore are `shaft_bore` interfaces (the ring in the split cavity: one per
    half, `split`, over the span it sits in);
  - `gear_mesh` interfaces from tangent pitch circles when the plan gives module and teeth of both and the measured
    centre distance agrees (else a note, or a `mesh_mismatch` warning); a mesh never connects a part to the base;
  - passages across a joint carry `split_a` / `split_b`;
  - "not connected" now says what the master shows and what to change (e.g. "it runs on Ø25 in a Ø52 bore of
    Housing base / Housing cover, but no planned bearing is 25 x 52 (a 6205 would fit it). What to change: ...").
- `src/aicad/office/icd.py`: features of a split interface side are marked `split`; the wall check accepts a split
  half's centre on the envelope face of its joint (and still checks the wall the other way); a measured bearing seat
  with no shoulder gets no invented shoulder face; a measured split fit's bore runs over its span; `hole_edge` problems
  carry the envelope size that clears them (`grow`).
- `src/aicad/office/interfaces.py`: `relayout` (lay the draft out again from a new measurement; Archie's automatic
  growth is re-decided; interface overrides dropped if the interface list changed, said in the history); autofix
  tries the exact growth a `hole_edge` problem names before the small steps (still capped by `GROW_CAP`).
- `src/aicad/master/run.py`: `record` (one place that puts a measurement on the plan), `stale`, `remeasure` (measure
  the program's master script again in its own process, no model turn, no tokens, then `relayout`); the master event
  counts bearing seats and meshes.
- `src/aicad/office/supervisor.py`: `fix_gate` re-measures a stale master first; the gate's open list gives master
  problems as they are (they say what to change), without the generic suffix.
- `src/aicad/master/prompt.py`: two rules for the master turn (bearing bore and journal at the bearing's Ø with a
  shoulder; split housings are fine; gears as pitch cylinders whose circles touch).
- Web: `GateFix.remeasured`; `fixLines` says "Measured the master model again" and the result line.
- Tests: `tests/test_master_icd_fix.py` (9 tests) with anonymised fixtures in `tests/golden/master_icd/`
  (`planetary.*`, `two_shaft.*`: the plan's parts, the master script, the old measurement; no ids, names or emails).

## Verified

| Check | Result |
|---|---|
| `tests/test_master_icd_fix.py` | 9 passed (old reading reproduces both problem kinds; both masters measured as split housings; both ICDs have no problem; unborne shaft message; analytic mesh, clusters, growth; Fix with Archie on a stale A4 program: re-measured, 0 problems, base envelope back to the measured 128 x 320 x 135) |
| `tests/test_master_model.py` | 21 passed |
| `tests/test_office_icd.py` | 18 passed |
| `tests/test_design_graph.py` + `tests/test_office_supervisor.py` | 53 passed |
| `tests/test_office_layout_envelopes.py` + `tests/test_planetary_orchestration.py` | 20 passed |
| `tests/test_office_archie_chat.py` + `tests/test_office_orchestrator.py` | 33 passed, 1 failed under load (`test_budget_warns_at_80_and_stops_at_100`, a timing test): passes on its own |
| web `vite build` | built |
| `ruff check src tests` | clean (the raw founder copies removed) |
| web `tsc --noEmit`, `vitest` | clean; 185 of 186 passed: `noLongDashes.test.ts` finds an en or em dash already on main in `AsmRibbon.tsx` line 99 (not touched here) |

A4 now: 25 interfaces (5 bolted, 7 fits incl. the ring in both halves, 6 meshes m2 30/30 and 30/90 internal, 7 bearing
seats: 6204 x 2 per shaft, 6004 per planet; all 7 planned bearings placed). A3 now: 20 interfaces, 6205 and 6207 read
from the bores (the plan names no designation), both shafts carried. Warnings left (non-blocking, true): bores with no
shoulder in the master; M6 cap screws that no standard length fits a 9 mm tapped hole; A3's cover bolts have no M size
in the plan; the A3 mesh has no module or teeth in the plan (a note).

## Not done, open

- The founder's own programs were not touched (rule). They clear on the next "Fix with Archie" click (their master is
  measured version 1, so it is measured again first); not tried in the running app.
- No browser walkthrough of the Fix with Archie result line.
- Placeholders, conformance and Fitz on a split housing with measured bearing seats are not exercised end to end
  (unit level only); the cover half's seat has no `bearing_item` by design (PD-277).
- `recognize.py` has the same angle summing (PD-276), left as is.
- A long dash already on main in `web/src/pages/app/modules/assembly/AsmRibbon.tsx` (line 99) fails `noLongDashes.test.ts`; not part of this branch.

## Parked decisions (defaults used)

| PD | Decision | Default used |
|---|---|---|
| PD-270 | How a bought-out bearing is read from a master | A shaft in a bore whose (bore, outside Ø) equal a planned bearing's; designation from the plan, else the design graph, else the ISO 15 table (first match by designation). A bearing named after another part is not used. |
| PD-271 | Where bearings sit in a measured bore, and a bore with no shoulder | Side by side from the end farther from the body's middle; one per bore first, the rest where there is room; no shoulder is a warning, not an invented face. |
| PD-272 | Meshes from a master | `gear_mesh` only with the plan's module and teeth and the measured centre distance within 0.1 mm; never a carrying joint. |
| PD-273 | Stale masters at "Fix with Archie" | Measured again first, automatically (no tokens); Archie's automatic growth re-decided; interface overrides reset when the interface list changed (said in the history). |
| PD-274 | Wall check on a split half bore | Its centre on the joint face is by design; the wall is still checked across the other direction. |
| PD-275 | Envelope growth for an opening near the edge | The exact size that leaves 1 mm (plus 0.5 mm) tried first, capped by `GROW_CAP` (4 x planned). For a master body this grows the envelope only, the master is not changed. |
| PD-276 | `recognize.py` (Studio STEP recognition) sums cylinder angles over a whole line too | Not changed here (blast radius); the master measurement reads per stretch on its own. |
| PD-277 | Split-housing bearing seats in the ICD | One `bearing_seat` per half; the half nearer the base places the bearings, the other has `bearing_item` none (half seat only). |
