# Toolbox keys, circlips, chamfered bearings, keyed Toolbox gears (branch `wip/toolbox-keys`)

Follow-up to the live gear-pair run (`docs/reports/assembly-fix/live-gear-run.md`, defects 2, 6 and 8). Brief: make
keys and circlips real, seated parts; give the Toolbox bearing its ISO 582 corner chamfers; never let the Toolbox
path silently drop an ICD feature from a designed gear.

## What was built

### 1. Toolbox families (`src/aicad/toolbox.py`)
| Code | Standard | Parameters | Geometry (frame) | Expected volume (closed form) |
|---|---|---|---|---|
| `parallel_key` | DIN 6885-1 form A | `D` shaft Ø (b × h from the table), `L` | stadium (round ends r = b/2) extruded h; length along X, width Y (centred), underside on Z 0 | h (b (L − b) + π b² / 4) |
| `retaining_ring` | DIN 471 (normal) | `D` = d1 (table sizes 8 … 65) | **as fitted**: annulus Ø d2 … d2 + 2b, thickness s; axis Z, a face on Z 0 | π/4 ((d2 + 2b)² − d2²) s |
| `spur_gear` (extended) | + DIN 6885 hub keyway | new `KEY_B`, `KEY_T2`, `KEY_ANG` (default 0 = no keyway: old models unchanged) | through keyway, top at R + t2, centred on `KEY_ANG` from +X | old − B (b (R + t2) − ∫ √(R² − y²) dy over \|y\| ≤ b/2) |
| `bearing` (changed) | ISO 15 + ISO 582 | — | 45° chamfer of leg r_s min on both bore corners and both outside corners | old − 2·2π(c²/2)(d/2 + c/3) − 2·2π(c²/2)(D/2 − c/3) |

Tables (comments cite them; all flagged **verify**, PD-13):
* `KEY_ROWS` (DIN 6885-1:1968): full row b, h, t1, t2 per shaft range; the ICD's `icd.KEYS` is the same table (a
  test keeps them equal). **d = 20 → 6 × 6, t1 3.5, t2 2.8** (verified: matches the brief).
* `DIN471` (DIN 471:2011-04 values, typed from Aspen Fasteners' reprint "Metric DIN 471 External Retaining Rings
  for Shafts", pages 1–3): s, b (approx.), d2, m, n. **d1 = 20 → s 1.2, d2 19.0, m 1.3, n min 1.5** (verified:
  matches the brief). Note: that table gives s = 1.8 for d1 36–45 (the 1981 edition had 1.75): I used the table.
* `BEARING_RS` (r_s min, as in SKF-style 60xx / 62xx catalogue tables): 6204 → 1.0 (matches the brief).
* `KEY_LENGTHS` (DIN 6885 preferred lengths) shown as help text only; the ICD's key length is not snapped yet.
* **`VERSION` 1 → 2** (bearing geometry changed). Old projects keep `TOOLBOX = {'version': 1}` in their model.py;
  the generator ignores the version, so a rebuilt old bearing project gets the chamfers (same as any earlier bump).

Matching (`toolbox.match`, the Studio "Use Toolbox component" popup): "Pinion key" → parallel key (the host noun no
longer wins: a key / circlip word subtracts 2 from every other family); "6x6x18" pre-fills D and L; "with a keyway",
"with a bore", "with a DIN 6885 keyway" are no longer counted as custom work (they are gear parameters now); "with a
hub" still is. "the key features of this bracket" matches nothing.

### 2. ICD interfaces and seating (`src/aicad/office/icd.py`)
* **Keys:** the existing `key` interface (fields unchanged) now names a planned key piece in `key_item` only while
  the key item has pieces left and the same size (`take_key`, one Toolbox size per item). `seated()` places the
  Toolbox key: X along the shaft axis, Z out along `dir`, underside on the keyseat floor `d/2 − t1` from the axis,
  centred on the key span `z` (`icd.key_frame`). Example (founder's case): pinion key base (6.5, 0, 0), length along
  +Y, height along +X.
* **Retaining rings (new kind `retaining_ring`, label "retaining ring"):** shaft lines only (the founder's case).
  Placement order per shaft: both faces of every gear / hub (a plain shaft has no shoulder), then the outboard face of
  each bearing. Pieces: rings of the shaft's own sub-assembly first (all shafts), then leftovers (same line class
  first). Added **after** the gear meshes, so no earlier interface id moves. Ring item recognised by name first
  ("Gear circlip" whose description mentions the 6204 is still a ring).
* `seated()` places rings like bearings (`R = CANON[ax]`, base point = the ring's lower face along the axis).
* Placeholders cut the grooves (`assembly/placeholder.py` `grooves`), conformance measures them
  (`conformance._groove`: circular edges Ø d2 at both groove ends, ±0.1), the designer's excerpt states them.
* `render.scene_from_skeleton` draws seated keys (box) and rings; `program_assembly` reports "seated n keys / retaining
  rings per the ICD"; `assembly/visual.py` tells the visual check "X (a thin retaining ring) sits in a groove on Y".

#### Shaft geometry contract (for `wip/office-direct`, which builds shafts deterministically)
`key` (kind unchanged; side a = hub, side b = shaft; all coordinates in the program frame, 1-D values along the
interface axis `ax`, 2-D values in `PLANE[ax]`):
`d` shaft Ø · `b`, `h` key · `t1` shaft keyseat depth from the shaft surface · `t2` hub keyway depth from the bore ·
`length` key length · `z` [z0, z1] key span on the shaft (keyseat: cut at least this, round-ended or square) ·
`hub_z` hub span (the hub keyway runs through) · `axis` · `dir` keyway side (2-D unit vector, rounded to 0.01; use
`icd.side_features` for the part-frame value) · `key_item` planned key or None · `standard` "DIN 6885-1 A".

`retaining_ring` (new; side a = the shaft, side b = the ring piece):
`d` = d1 shaft Ø at the groove · `d2` groove bottom Ø · `t` groove depth (d − d2)/2 · `m` groove width (H13) ·
`n` min distance from the groove to the shaft end · `s` ring thickness · `b` ring radial width (approx.) ·
**`groove_z` [g0, g1] the groove along the axis (g1 − g0 = m) — cut exactly this** · `z` [r0, r1] the ring's faces
· `face_z` the retained face (gear / hub or bearing) · `side` ±1 (the ring is on that side of the face) ·
`against` "hub" | "bearing" · `against_item`, `against_copy` · `ring_item` · `ring` (title) · `standard` "DIN 471".
On the shaft side `side_features` gives `{"type": "groove", c, z0, z1, d: d2, shaft_d, m, ax}` in the shaft's
canonical frame; `body_spec` emits it as `grooves` (only when present).

#### Lined up with `office/direct.py` (merged from main 111566f)
Checked against the field names `direct.py` reads: its shaft builder takes `type: "groove"` features with `z0`/`z1`,
`d` (= d2) and `shaft_d` (my `side_features` output; it also accepts the interface's `d2` / `m`), and keyseats from
the unchanged `key` features. Its fillet rule reads `r_s_min` from `bearing_journal` / `bearing_seat` data: every
bearing interface now carries `r_s_min` from `toolbox.BEARING_RS` (6204: 1.0, so direct shoulder fillets stay at
≤ 0.8). Result on the founder's case with keys and circlips (`direct.plan`, approved ICD): "Pinion shaft: shaft Ø20 ×
78, 2 bearing journals, 1 seat, 1 keyseat, 2 circlip grooves", "Gear shaft: … 1 keyseat, 4 circlip grooves", both
gears "with a keyway", all `direct`; the end-to-end run completes with Gage approving every direct part (grooves
and keyseats measured), keys and rings seated, 0 clashes.

Merge resolution in `hex_lookup`: with the direct builder on (default) an ICD-fixed gear goes to it (main's rule);
only when it is off or declines does `toolbox_gear_for` decide (keyed Toolbox gear or designed).

### 3. Hex, the BOM and the keyed Toolbox gear (`src/aicad/office/platform_env.py`, `deliverables.py`)
* `NOT_STOCKED` no longer holds keys / circlips / retaining rings / snap rings; `librarian.read_toolbox` reads a key
  or ring by the **head noun of the leading phrase** before any host branch ("Pinion key, DIN 6885 6x6x18" is a key;
  "Bearing 6204, held by a circlip" is a bearing). With an ICD, Hex takes both exactly as seated (0 tokens).
* A designed gear goes to the Toolbox only through `toolbox_gear_for`: every ICD feature of the gear must be carried
  (teeth; one on-axis through bore; at most one on-axis through hub keyway → `KEY_B`, `KEY_T2`, exact `KEY_ANG` from
  the gear's tooth phase; its own two faces). Anything else (a hub, holes, dowels, a second keyway, a keyway past the
  rim) → the gear stays designed. Without an ICD, a gear whose text says key / keyed / keyway / hub / spline stays
  designed.
* The plan's material is read from the description (`plan_material`: 42CrMo4, 18CrNiMo7-6, C45, S355, AISI 4140 …);
  the reuse record carries `material` and `designed: True`. The BOM lists such a gear as **make**, in that material,
  "Designed in this program (Toolbox generator, sized by the ICD)".
* `swap_in` now measures the Toolbox gear against its ICD (Gage's `conformance.measure`, in the fixed −B/2 frame) and
  records it in `icd_check` (ok, interfaces, envelope). It does not block (the ICD sized it); it is evidence.

## Tests (all against hand values)
`tests/test_toolbox_keys.py` (new):
* tables: DIN 6885 rows (20 → 6×6/3.5/2.8, 22 inclusive, 22.5 → 8×7), DIN 471 rows (20, 25, 30), t = 0.5, r_s.
* volumes: key 432 + 54π; ring 67.392π; hub keyway 354.2511 mm³ removed (6 × 12.8 − 59.0874 = 17.7126 mm² × 20);
  bearing chamfer decomposition; rim guard.
* **shoulder fillet vs bearing: r 0.4 → 0 mm³, r 1.0 (= r_s min) → 0 mm³, r 1.5 → clash** (Ø26 shoulder, Ø20 journal,
  6204 against the shoulder).
* ICD of the live plan: key / ring interfaces, ids (rings IF-10…15 after the mesh IF-09), seated positions,
  excerpt, Hex results (pinion keyed 6 × 2.8 in 42CrMo4, gear keyed with `KEY_ANG` = −phase, keys and rings from the
  ICD), a gear with an extra ICD feature stays designed.
* kernel no-interference check: placeholder shaft (keyseat + grooves) + keyed Toolbox pinion + key + 2 rings + 2
  bearings placed by the ICD: every pair < 1e-6 mm³; key touches the keyseat, rings touch the gear faces; shaft and
  keyed gear pass conformance.
* BOM: designed Toolbox gear = make / 42CrMo4, key = buy.
* matching: key / ring / host nouns, "with a keyway" vs "with a hub".
* end to end (office fixture, after the merge with main): the live plan completes; shafts and gears are built
  directly from the ICD with their keyseats, 2 / 4 circlip grooves and hub keyways, Gage approves each; 4 bearings +
  2 keys + 6 rings seated at the hand positions, nothing in the parts bin, 0 clashes.

Changed: `tests/test_office_orchestrator.py::test_hex_does_not_read_a_key_or_circlip_as_its_host` now expects the
key / ring readings (still never the host).

Finding worth keeping: a build123d boolean `Compound & Part` on the multi-solid bearing gave a bogus 95.5 mm³ where
every solid-by-solid intersection was empty; the tests intersect solid by solid.

## Files touched outside the Toolbox
`src/aicad/office/icd.py`, `platform_env.py`, `deliverables.py`, `conformance.py`, `program_assembly.py` (one
message), `src/aicad/assembly/librarian.py`, `placeholder.py`, `render.py`, `visual.py`, `src/aicad/agent/prompt.py`
(Toolbox code list), `web/src/pages/app/office/{types.ts,Interfaces.tsx,model.ts}` (the new interface kind).

## Not done / limits
* DIN 472 internal rings: not added (no housing in the founder's case). Table and an ICD seat for housing bores are
  the next step.
* Rings are placed only in shaft lines; in housing / block layouts a ring item still goes to the parts bin (now as a
  real DIN 471 ring sized from the text, default Ø20).
* The ring is modelled as fitted (plain annulus, no lugs, holes or gap); the key without its edge chamfers.
* ICD key lengths are not snapped to the DIN 6885 length series (the live case's 18 is a series length).
* Gage still does not review a Toolbox-made gear as an AI review; the deterministic ICD measurement is recorded.
* Keys of a hub on a shaft in a housing / block layout get `key_item` too (as before), now capped by quantity.

## Parked decisions (master numbers them)
* **PD-a — circlip placement policy.** Default: in a shaft line, both faces of every gear first, then the outboard
  face of each bearing; own sub-assembly's rings first. Alternative: shoulders + one ring per hub (needs stepped shafts).
* **PD-b — DIN 471 values source.** Default: a distributor's reprint of DIN 471:2011 (s = 1.8 for d1 36–45, where
  older tables say 1.75), flagged verify under PD-13.
* **PD-c — Toolbox gear for designed gears.** Default: the direct builder first (main); otherwise the Toolbox gear
  whenever every ICD feature is representable (now including the hub keyway), regardless of "with a keyway"
  wording; the part is "make" in the plan's material, measured against the ICD at swap-in.
* **PD-d — bearing corner as a 45° chamfer of r_s min** (inside the ISO 582 r_s min arc) rather than a fillet.

## Final gate (after merging main cd6b97a ← 1c11058, worker housekeeping)
Run file by file, workers checked after each: `test_toolbox_keys` 12 passed (incl. the end-to-end live plan),
`test_library` 11, `test_office_icd` + `test_office_shaft_line` 23, `test_assembly_trains` 8, `test_fixtures_asm` 10,
`test_assembly_visual` 26, `test_office_direct` 10, `test_office_polish` 12, `test_office_phase5` 9,
`test_office_orchestrator` 21 — all passed. `ruff check src tests` clean, `tsc --noEmit` clean, `vite build` ok
(before the last two merges, which touched only landing assets and test housekeeping). The whole suite was not run in
one go (founder's PC resource rule).
