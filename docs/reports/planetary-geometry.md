# Planetary gear geometry: ring gears, planets on their bearings, recognition and conformance

Branch `wip/planetary-geometry` (from main 3104737). Founder's standing benchmark: "Build a single stage planetary
Gearbox". Attempt A1 (his account, program `078f86e77b1a`) planned the set correctly (sun z30, three planets z30, ring
z90, m2, a = 60, ratio 4) and then failed on two parts:

- **Ring gear**: no internal gear generator, so it went to the AI designer; and Gage sent it back every round with
  "IF-14 planet/ring mesh (internal): m2 x 90 teeth specified, measured no gear teeth recognised". Internal teeth
  were not recognised, so a correct ring could never pass.
- **Planet gear**: "bearing seat Ø47 H7 (planet bore) is not a gear feature this can build", so it went to the
  designer too.

Both now go direct (no AI) and conform. Measured on a read-only in-memory copy of the A1 program (nothing written
under `data/`), built through the Studio gate into the scratch dir:

| Part | Path | Build + CHK-02..08 | Faces | Conformance |
|---|---|---|---|---|
| Ring gear m2 z90, Ø197 x 26 | direct (was: designer, never passed) | 11.7 s, verified | 363 | ok: seating face Z -13; IF-14 / 18 / 22 "internal gear m2 x 90 teeth", measured "m2 x 90 teeth, axis 0.000 mm off" |
| Planet gear m2 z30, 6204 seat | direct (was: designer) | 3.8 s, verified | 185 | ok: seat Ø47 H7 measured Ø47.000 (x3 interfaces), shoulder Z 7.000, six meshes |
| Sun gear m2 z30, keyed | direct (unchanged path, now with backlash) | 3.7 s, verified | 186 | ok: bore Ø20 H7, keyway 6.000 x 2.800, three meshes |

## What was built

### `fw_std.internal_gear` (new) and `fw_std.spur_gear(seats=...)` (new option)
- `internal_gear(module, teeth, face_width, *, rim_od | rim, pressure_angle, backlash, holes=(n, pcd, d),
  hole_angle, flange_od, flange_t, name, z0)`:
  - True involute internal teeth as splines (like `spur_gear`), profile shift 0. Addendum inward: tip Ø m (z - 2).
    Dedendum outward: root Ø m (z + 2.5). The tooth spaces are where an external gear of the same z has its teeth, so
    a **tooth space is centred on +X**. When the tip circle is inside the base circle (z < 34 at 20°), the flank
    below the base circle is radial, as on the external gear.
  - Working backlash: each space widened by backlash / 2 per flank at the pitch circle. The Toolbox and direct paths
    pass 0.04 m, the same as the Toolbox spur gears.
  - Outside: a plain rim (Ø `rim_od`, or root Ø + 2 `rim`, default rim 3 m), an optional flange on the Z = z0
    face, and optional axial holes on a bolt circle (through the rim when they fit there, else through the flange).
  - Refusals with the reason: z outside 20..400, tooth spaces that come to a point, a rim under half a module, holes
    that break into the tooth roots or into each other, a flange no larger than the rim.
  - EXPECTED by hand, without the CAD kernel: rim disc less the toothed bore, the bore = tip disc + z spaces, each
    space ∫ 2 σ(r) r dr from the tip circle to the root circle (Simpson), radial part below the base circle.
- `spur_gear(..., seats=[(D, depth, side)])`: a bearing seat Ø D bored from the -Z (side -1) or +Z (side +1) face to
  `depth`, ending on the shoulder at the through `bore`. At most one seat per face; refused with a keyway, hub or
  helix, or when the seats leave no shoulder or no rim under the teeth. Volume: less π/4 (D² - bore²) x depth.

### Toolbox: "Ring gear (internal)" (`internal_gear`)
- Parameters: M, Z (30..300), B, OD, and N, PCD, HOLE for optional holes through the rim.
- Backlash 0.04 m. Keywords: ring gear, internal gear, annulus, annular gear, planetary ring. "ring gear m2 z90"
  pre-fills M and Z.
- New component, so no `VERSION` bump. The agent prompt lists it, `fw_std.internal_gear` and the planet `seats`
  option.

### Generators and the direct decision
- **Ring gear** (`generators.ring_gear_spec` / `ring_gear_script`, kind `ring_gear`). Chosen by `kind_of` for a
  gear item with `internal`.
  - Reads the ICD's internal mesh (module, teeth, pressure angle, each planet's centre distance) and the seating
    faces at ±L/2.
  - The rim: the envelope OD, or a centred boss the ICD fits into the housing (`boss` feature with its fit).
  - Axial holes through the rim, plain or tapped (cosmetic thread), each checked inside the rim band.
  - The teeth run through the ring length (A1: 26 long, mesh face width 20).
  - The script is readable: `PARAMS` and `PARAM_META` (MODULE, TEETH, LENGTH, RIM_OD, PRESSURE_ANGLE). The header
    lists the interfaces, with meshes to the copies of one mate on one line ("IF-14, IF-18, IF-22 mesh with the
    Planet gear"), and the design choices.
  - Anything else on the ring goes to the designer with the reason. Brief extras go to the designer seeded with the
    generator's model: helical, flange, or a size the ICD doesn't explain. "Internal gear" in a ring's brief is not
    an extra.
- **Planet** (`direct._gear_spec` / `gear_script`). A designed spur gear now accepts the ICD's bearing seat (a `seat`
  of a `bearing_seat` interface) with its shoulder face:
  - side from the shoulder's normal; depth = shoulder Z + B/2 (A1: 7 + 10 = 17);
  - the through bore is the shoulder: the interface's shoulder Ø when it gives one, else D - (D - d) / 4 rounded
    down to 0.5 mm (6204: Ø40; 6004: Ø36.5);
  - checked to stay outside the bearing's pitch circle (d + D) / 2, clear of the turning inner ring, and of the pin
    clearance Ø;
  - script parameters BORE, SEAT_D and SEAT_DEPTH with their meta.

  A seat with no shoulder, a keyway on a gear running on its own bearing, or a face inside the gear that is not a
  shoulder all go to the designer.
- **Backlash on designed gears.** Every direct spur gear script now passes `backlash=0.04 * MODULE`, the same as
  the Toolbox gears and the assembly makers. Before, direct sun and planets were exact involutes touching flank to
  flank. `direct.VERSION` is 2.
- `platform_env.toolbox_gear_for` refuses an internal gear, so a ring can never be swapped for an external Toolbox
  gear.

### ICD, layout phase, recognition, conformance
- `icd.side_features`: the internal member of an internal `gear_mesh` carries `internal: true` and the label "m2 x
  90 internal teeth". The internal member is the item flagged `internal`, else the one with more teeth. The planet
  side stays external. The designer's ICD excerpt says "a tooth space is centred on +X" for a phased ring.
- `graph/layout.py` `_phase`: after the external meshes, each ring is turned so its tooth spaces meet its first
  planet's teeth. Both gears look outward along the line of centres, so the line measured from a ring space equals
  the line measured from a planet tooth: u_ring = v_planet, φr = θ - v_p x 360 / z_r (mod 360 / z_r). On the A1
  layout this gives 2° (half a ring pitch). Before, the ring had no phase: the parts would have clashed in the
  program assembly (half a pitch out: 684 mm³ of overlap with one planet).
- `recognize.py` (VERSION 3, so cached snapshots are remade):
  - A repeated band whose inner side is air and outer side is material is an **internal gear**: component kind
    `internal_gear` with teeth, module, tip Ø, root Ø, rim Ø, `internal: true`, axis and origin.
  - The module comes from tip + root = m (2z + 0.5) and is snapped to the standard series within 3 %.
  - The bounding box's three axes are always tried: before, only the first 12 cylinder axes were, and a ring with 12
    bolt holes never had its own axis tried.
  - External gears are unchanged.
- `conformance._gear`: an internal ICD gear needs a recognised internal gear, and an external one a spur gear. A
  mismatch says so: "external gear teeth, the ICD asks for internal (ring) teeth". Seats in gears are measured by
  the existing `_seat` (Ø in the H7 zone, an edge at the shoulder) and the shoulder by `_face`.

## Tests (`tests/test_internal_gear.py`, 11 tests, about 80 s, no live AI)
All hand values are in the module docstring. Every expected number is a formula, never a measurement:
- **Ring m2 z90.** Pitch / tip / root Ø 180 / 176 / 185, base Ø 180 cos 20°, bbox 197 x 197 x 26. The volume is
  checked by an independent trapezoid integral of the involute space (rel 1e-7) and against the built B-rep (rel
  1e-5).
- **Ring recognition.** z90, m2, internal, tip 176, root 185, rim 197, Z axis on the origin, no unrecognised faces.
  A spur gear is still `spur_gear`.
- **Ring options.** 12 x Ø4 on PCD 191 through the rim, and a Ø230 x 8 flange with 8 x Ø9 on PCD 215: hand volumes,
  and the ring is still recognised with 13 hole axes. Refusals: a rim behind the root, holes into the roots, z12.
- **Phased set, built through the Toolbox.** Sun, three planets at θ = 90 / 210 / 330 (phase 6 each by v = 1/2 - u)
  and the ring at the hand phase 2 (u_ring = v_planet): **0 mm³** overlap solid by solid for sun / planet, ring /
  planet and planet / planet. The flank gap is 0.08 cos 20° = 0.0752 mm (measured 0.0752). The unphased ring clashes
  (> 100 mm³), so the check can see a clash.
- **The program layout.** Design graph to layout to ICD for the planetary reply. The layout gives the ring phase 2,
  equal to the hand formula from planet copy 0. Ring, sun and planets placed by `program_assembly.place` overlap
  nowhere (all three planets).
- **Ring, direct.** It goes direct with MODULE 2, TEETH 90, LENGTH and RIM_OD from the envelope and backlash
  0.04 m. It passes CHK-02..05, 07 and 08, its volume matches the hand formula, and conformance is ok (internal
  mesh rows). The same ICD feature measured on an external gear fails with the reason.
- **Ring with ICD holes.** A hole pattern of 6 x Ø4.5 on PCD 191 is cut where the ICD puts it. Gate, hand volume,
  six conforming hole rows. "Helical" or "flanged" in the brief sends it to the designer with a seed.
- **Planet, 6204 and 6004.** SEAT_D 47 / 42, SEAT_DEPTH 17, BORE 40 / 36.5 (hand). Hand volume = involute area x
  20 less the shoulder bore less the counterbore. The 6204 planet passes the gate and conformance: seat Ø47.000 in
  H7, shoulder Z 7, recognised as a z30 spur gear.
- **Refusals.** A seat with no shoulder goes to the designer. Seats that leave no shoulder or no rim raise.
- **Toolbox.** "ring gear m2 z90" ranks the internal gear first with M and Z filled; "spur gear m2 z30" still gets
  the spur gear; an OD behind the root raises; the catalogue lists it. `test_library`'s every-component
  determinism test covers the new component automatically.

Suites run, at most two files per call, no workers left over:

| Files | Result |
|---|---|
| `test_internal_gear` + `test_planetary_layout` | 17 passed |
| `test_fw_std` + `test_generators` | 18 passed (after the fix below) |
| `test_office_direct` + `test_toolbox_keys` | `test_office_direct` all passed; 3 `test_toolbox_keys` failures, also on main (stash check) |
| `test_library` + `test_recognize_axis` | 17 passed |
| `test_design_graph` + `test_connection_layout` | 54 passed |
| `test_office_orchestrator` + `test_golden` | 31 passed |
| `test_office_shaft_line` + `test_office_icd` | 23 passed |
| `test_office_gearbox_caps` + `test_fixtures_asm` | FX-05: 2 failures, also on main (stash check) |
| `test_drawing_depth` | passed |
| `test_engineering` + `test_studio` | 58 passed |

`ruff check src tests` is clean.

Fixed along the way: the first `_exempt` change stopped exempting pulleys and sprockets from "a special gear
form". It now exempts only "internal gear" on a ring.

## Picture check
The phased set (ring at 2°, sun, three planets at phase 6) and the planet were rendered with the app's offscreen
renderer (`aicad.agent.render`) and read:
- set: the teeth interleave all round, with no overlap visible; the ring has a plain 6 mm rim;
- planet: the Ø47 counterbore opens on the -Z face, and the Ø40 shoulder bore shows from +Z.

## Master's request (k_planetary golden case, simulated agents)
- `icd.excerpt`'s `fw-icd` gear block now carries `internal: true`, `tip_d` m (z - 2) and `root_d` m (z + 2.5)
  for an internal gear. A sun or planet block has no `internal` key.
- The direct decision routes the ring to the ring generator before any agent or Toolbox path: `direct.plan` sends
  `internal` gear items to `generators.kind_of`, which returns `ring_gear`. `hex_lookup` returns None for a designed
  gear that plans direct, and `toolbox_gear_for` refuses a ring.
- As a fallback (direct path off), `fake_agents._write_icd_part` builds a ring from the excerpt
  (`fw_std.internal_gear`, rim to the envelope OD, teeth through the length). The test re-imports its STEP and
  recognises z90 internal teeth.
- The planet reads its bearing from the ICD `bearing_seat` data (d, D, B, designation, shoulder fields), so the
  other branch's 6004 choice (rim rule of at least 2.7 m) gives SEAT_D 42 and BORE 36.5. This is tested with a 6004
  substituted in the ICD.

## Parked decisions (default used)
- **PD-250 Ring teeth length.** Default: the teeth run through the whole ring length (the envelope; A1: 26), not just
  the mesh face width (20). Plain lips at the ends would stop the planets going in axially. Alternative: teeth over
  the face width only, with relief grooves.
- **PD-251 Planet shoulder Ø.** Default: the interface's shoulder Ø when it gives one, else D - (D - d) / 4 rounded
  down to 0.5 mm (6204: Ø40, 6004: Ø36.5), and never inside the bearing's pitch circle. Check against the bearing
  maker's abutment Da max (verify, PD-13). Alternative: the catalogue Da value per designation (a table).
- **PD-252 Backlash on designed gears.** Default: every direct-path spur gear and ring carries 0.04 m of working
  backlash, like the Toolbox gears, so meshing parts clear by 0.075 mm normal (m2). Alternative: exact involutes
  (they touch flank to flank and can read as a clash).
- **PD-253 Ring tooth convention and phase.** Default: a ring is modelled with a tooth SPACE centred on +X. The layout
  turns it so u_ring = v_planet from its first planet (A1: 2°). Alternative: a ring tooth on +X, with the phase rule
  shifted by half a pitch.
- **PD-254 Ring rim.** Default: a plain rim to the envelope OD (A1: Ø197, rim 6 mm behind the Ø185 root) when the ICD
  gives no fitted boss or holes. How the ring is held (press fit, clamping, pins, screws) is the housing's
  interface. Alternative: always add a flange with screws.
- **PD-255 Internal gears are their own component kind.** Default: recognition reports `internal_gear`, not
  `spur_gear`, so external-gear code (gear trains, Fitz's gear mates, "Replace with Toolbox part") never reads a
  ring as an external gear.
- **PD-256 Toolbox ring gear.** Default: a new "Ring gear (internal)" Toolbox component, Z 30..300, plain rim and
  optional rim holes; values are ISO 53 formulas, no standard table.

## Findings for the master
- **G1 Shared file `graph/layout.py`.** I added the ring phasing to `_phase` (internal meshes, after the external
  ones). The orchestration agent owns planetary sizing and placement. If it phases rings too, keep one rule, with the
  convention above (a ring tooth space on +X).
- **G2 Pre-existing failures on main** (same in a stash check of 3104737):
  - `test_toolbox_keys`: `test_icd_places_keys_and_rings_and_hex_takes_them`,
    `test_keyed_shaft_line_parts_fit_without_interference` and `test_live_plan_assembles_with_keys_and_rings_seated`
    (circlip groove counts and interface naming);
  - `test_fixtures_asm` FX-05: stale since Toolbox v3, the spur gear CHK-05 has rel 1.6e-6 against a tol of 1e-6.
    Fix: `uv run python -m aicad.fixtures --write`, or a looser fixture tolerance for spline gears.
- **G3 A1 layout.** The ring spans Y -29..-3 and the carrier Y -3..17: the turning carrier touches the fixed ring's
  end face, with no gap. This is planetary sizing (orchestration agent).
- **G4 Studio Toolbox panel.** The new Toolbox component shows in the catalogue automatically. No Studio files were
  touched.

## Files
- New: `tests/test_internal_gear.py`, this report.
- Changed: `src/aicad/fw_std.py` (`internal_gear`, `_InternalInvolute`, `spur_gear(seats=)`), `src/aicad/toolbox.py`
  (`internal_gear` component, matching), `src/aicad/office/generators.py` (ring gear generator, `kind_of`, extras),
  `src/aicad/office/direct.py` (planet seats, backlash, `mesh_groups`, VERSION 2), `src/aicad/office/icd.py`
  (internal flag on the ring's gear feature and in the excerpt's gear block, phase wording), `src/aicad/office/conformance.py` (internal gears),
  `src/aicad/recognize.py` (internal gears, VERSION 3), `src/aicad/graph/layout.py` (ring phase),
  `src/aicad/office/platform_env.py` (no Toolbox spur gear for a ring), `src/aicad/agent/prompt.py` (helper list), `src/aicad/office/fake_agents.py` (a ring from the excerpt).
- Not touched: `graph/planetary.py`, placeholders, Fitz, the golden case, Studio files, `data/`.
