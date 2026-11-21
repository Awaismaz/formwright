# Feature recognition per stretch along a line (PD-276, branch `wip/recognize-stretch`)

`src/aicad/recognize.py` is the feature recognition behind STEP import, the Studio's recognition panel, assembly
snapshots (mates, fasteners, Fitz), the Design Office's conformance (Gage), the engineering calculators and the
master-model measurement's stock reading. It had the flaw the master measurement fixed in its version 2
(`docs/reports/master-icd-fix.md`): cylindrical faces were summed over a whole axis line.

## Root cause

Cylinder faces were grouped by (line, radius) only, then:

1. **angles summed over the line**: two 180 degree half bores at the two ends of a housing split on its axis made
   360, so each half "had" a full hole, one hole from end to end, centred on the split face;
2. **extents mixed across frames**: each face's axial extent is measured from its own surface's axis origin, but
   the group kept the first face's origin and took min / max of all faces' numbers. Two separate coaxial bores of one
   diameter came back as one hole (the second one lost, its extent read in the first's frame);
3. **one body did not bound a group**: faces of different solids of one compound joined one "hole".

Reproduced before the fix (a split housing half, 120 long, Ø40 half bores in 15 mm end walls): one Ø40 x 120 through
"hole" at X 0. Two Ø10 x 30 blind bores from the two ends of a 100 mm block: one hole at X -35, the other missing.

## Change

- `recognize.py` (VERSION 4):
  - cylinder faces are keyed by (body, line, radius, concave) and measured in **one frame per line** (t from the foot
    of the world origin on the line);
  - `_stretches`: faces that **overlap or touch** axially form one stretch; a face beyond a gap starts another.
    A stretch's angle is the **most it covers at one point** along it (sum of the faces over that point), not a sum
    over the line: two halves of one bore make 360, a half bore split along its length stays 180, and a hole whose
    halves exit an inclined face differently is still full where they overlap;
  - classification per stretch: under 179 degrees the faces are fillets or partial cylinders as before; convex is a
    boss (now one per stretch); concave at 270 degrees or more is a **hole** (`full` at 359 or more: a keyed bore,
    about 325, stays a hole with `full` false, as before); concave between 179 and 270 is a **partial bore**:
    `rec["partials"]` (d, axis, centre, ends, depth, through, open, dir, `angle`), a `partial_bore` feature
    ("Half bore Ø40 (180° of a turn)") with its faces, a summary line, and in the agent prompt data. It is never a
    hole, so no pattern, hole edit, fastener or mate takes it for one;
  - partial bore faces stay out of the rotational (gear tooth) search, as hole faces always were;
  - `rec["version"]` carries VERSION.
- `assembly/geometry.py`: a hole's topo face ids are only the faces within its own stretch (two holes on one line
  each get their own faces); `info.json` carries `partials` (with face ids) when the part has any.
- `office/frames.py`: `info_in` maps `partials` like holes. `office/conformance.py`: an ICD hole marked `split` (half of
  a bore across a joint) is also matched against the part's partial bores; the old summed "hole" used to stand in.
- Caches that key on recognition:
  - `assembly/store.part_ready` compares `info.json`'s `recognize_version` with VERSION: every stored assembly
    snapshot is prepared again on next use;
  - `engineering/project.geometry`'s cache key now includes `recognize.VERSION` (was only `GEOMETRY_VERSION`, which
    nobody bumped for recognizer changes);
  - `out/recognition.json` (Studio recognition, design memory facts, Office briefs) was current by `build_id` only;
    `memory.facts.recognition_current` and `library._current_recognition` now also need `version == VERSION`, so the
    next brief or recognition request reads the part again (`design_projects.refresh_recognition` already re-runs
    when it is not current);
  - not re-read on purpose: an imported STEP project's own `RECOGNITION` file (the model script's `fw.imported_blank`
    / `fw.redefine_holes` refer to its feature ids; re-reading would renumber them under the user's model).
- `office/program_assembly._hole_index` (the Design Office's fastener stacks from the ICD): of several holes on one
  line it takes the one nearest the joint plane (each cap's screws go into the wall the cap sits on; the old summed
  hole spanned both walls, so this was never needed).
- `.claude/skills/build123d-kernel`: the per-stretch rule and what VERSION invalidates.

## Verified

| Check | Result |
|---|---|
| `tests/test_recognize_stretch.py` (new, 10) | passed: split half (2 half bores, no hole), both halves in one compound (4 half bores), assembled housing (two Ø40 bores each 15 long, not one 120), two coaxial blind bores (two holes, own centres, depth, open end, direction), assembly face ids per hole, `_stretches` overlap / touch / gap / half bore split lengthwise, keyed gear bore stays a hole and the gear is still recognised, slot ends are partial bores, conformance of a split hole, VERSION re-reads (store, facts) |
| `test_recognize_axis` + `test_internal_gear` | 17 passed |
| `test_office_icd` + `test_office_direct` | 28 passed |
| `test_generators` + `test_toolbox_keys` | 23 passed |
| `test_assembly` + `test_assembly_pairs` | 30 passed |
| `test_dims` + `test_drawings` | 37 passed |
| `test_drawing_depth` + `test_fixtures_asm` | 26 passed |
| `test_studio_intel` + `test_planetary_orchestration` | 33 passed |
| `test_master_icd_fix` + `test_golden` | 19 passed |
| `test_design_memory` + `test_engineering` | 43 passed (fixture `recognition.json` now carries `version`) |
| `test_library` + `test_office_small` | 22 passed |
| `test_office_phase5` + `test_office_phase6_layout` | 14 passed |
| `test_office_shaft_line` + `test_office_supervisor` | 28 passed |
| `test_master_model` + `test_recognize_stretch` | 31 passed (the new file now has 11 tests) |
| `test_io_roundtrip` + `test_office_orchestrator` | 32 passed |
| `test_office_gearbox_caps` | 16 passed |
| after the `_hole_index` change: `test_planetary_orchestration` + `test_office_direct`, `test_office_orchestrator` + `test_no_long_dashes` | 29 passed; 23 passed |
| `uv run aicad golden --simulated` | **13 of 14** (was 14 on main): c reducer "shcs M6 fastener stacks: got 8, want 16", see below; the other 13 pass |
| `ruff check src tests` | clean |

## The golden reducer case (c): a real design gap the old reading hid

With this change the reducer case fits 8 of its 16 M6 cap screws: the two input caps' 8 are not fitted ("No standard
M6 length fits (needs >= 25.6 mm)"). This is not a recognition error; the old reading was wrong in a way that made it
pass:

- the housing base has the planned M6 tapped holes in both end walls, 18 deep (ICD `tap_depth(6)` = 2.5 x 6 + 3 =
  18). Main read one "hole" per line, 19 deep at Y -37.5 (the two 18 mm holes at Y -46..-28 and 28..46 mixed in one
  frame), and lost the other wall's holes;
- Fitz's tapped rule (aluminium, engagement 2 d, blind: keep 2 P clear of the bottom): input cap flange 12 + washer
  1.6, so L from 12 + 1.6 + 12 = 25.6 to 12 + 1.6 + (18 - 2) = 29.6. ISO 4762 has 25 and 30: none fits. With main's
  19 mm the top was 30.6, so M6 x 30 "fitted". The output caps (flange 16: 29.6 to 33.6) take M6 x 30 either way;
- the cause is the ICD rule: `tap_depth` leaves a window of 0.5 d + 3 - 2 P (4 mm for M6, 4.5 for M8), narrower than
  the 5 mm step of standard lengths, so some cap thicknesses have no standard screw. Fixing it (a deeper tap, a cap
  flange chosen for a standard length, or no washer under the cap screw head) changes the ICD, the wall thickness
  (`tap_depth + 3`) and hand values in several office tests, so it is parked (PD-285), not done here.

## Behaviour changes to know

- A slot's round ends (obround slots) were two "holes" of the slot width, often a hole pattern offered for editing
  (a hole edit there filled a full cylinder, which was wrong); they are partial bores now.
- A turned part with one diameter at two places (two journals of one Ø either side of a shoulder) now has two bosses
  instead of one spanning both; the stock reading (largest boss) is unchanged.
- A cross slot or cavity through a hole's line now gives two holes, each with its own depth and through flag, not one
  hole over the whole line.
- A hole whose cylinder is split into faces of different solids of one compound is no longer one hole.

## Not done, open

- A stretch that is a full bore over part of its length and a half bore over the rest (touching) reads as one full
  hole (the most covered point decides). Not seen in the parts at hand.
- Partial bores are not yet offered as mate references in Assembly Studio (they are in `info.json` for that).
- Founder data and the running app were not touched; no browser walkthrough (no UI change beyond the new feature
  name in the recognition list).

## Parked decisions (defaults used)

| PD | Decision | Default used |
|---|---|---|
| PD-280 | Where a partial bore ends and a hole begins | Concave stretch at 270 degrees or more is a hole (a keyed bore, about 325, stays a hole with `full` false); 179 to 270 is a partial bore; under 179 fillets / partial cylinders as before |
| PD-281 | The angle of a stretch | The most covered at any one point along it (faces over that point summed), not the sum over the stretch |
| PD-282 | Faces of different solids on one line | Never one hole: a hole belongs to one body (a split housing in one compound is four half bores) |
| PD-283 | Stale recognitions after VERSION 4 | Assembly snapshots, the engineering cache and `out/recognition.json` are read again; an imported STEP project's own `RECOGNITION` file is kept (its feature ids drive the model script) |
| PD-284 | Conformance of an ICD hole across a joint (`split`) | Matched against holes and partial bores of the part; an ICD hole not marked split is matched against holes only |
| PD-285 | Tapped depth that leaves no standard screw length (golden c: 12 mm input caps into 18 mm M6 taps) | Not changed: Fitz reports the 8 input cap screws as not fitted (true for the planned geometry); the golden reducer case is 13 of 14 until the ICD rule is decided (deeper `tap_depth` so the window covers one length step, or cap flange sized for a standard length, or no washer under cap screw heads) |
