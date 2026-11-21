# Shaft seals on the fast path (branch `wip/shaft-seals`, 2026-11-21)

## Why

Planetary benchmark attempt A11 failed before any part was built. The model added a radial shaft seal mounted on each
open bearing cap ("Input shaft seal", "Output shaft seal"). That is good design, but the connection layout placed no
seal. The fast-path trial reported "Input shaft seal: no interface in this layout places it" (`unreachable`, because
the name contains "shaft"), so the program went to the master-model path, which models planetary sets poorly. The
open cap generator already cut a DIN 3760 recess. What was missing was the seal part, an interface that places it,
and a place for Fitz to seat it.

Fixture: `tests/golden/seals/planetary_with_seals.graph.json` (A11's resolved design graph, anonymised).

## What changed

**Toolbox** (`toolbox.py`, VERSION 3 -> 4)
- The DIN 3760 / ISO 6194-1 table `SEALS` (shaft d -> D, b) moved here from `office/generators.py`. It is one table
  for the Toolbox, the layout and the cap generator. It is marked "verify" (PD-13); `generators.SEALS` is the same
  object.
- New component `shaft_seal(D)`: a radial shaft seal, type A, simplified. It has a plain metal case, a back web and
  one lip that meets the shaft at d / 2 (a contact at nominal size, not an interference).
  - The section is `seal_profile(d, D, b)`, nine points given as fractions of h = (D - d) / 2 and b, so every size
    is the same simple polygon.
  - EXPECTED volume is Pappus over that polygon (closed form).
  - Frame: axis Z, the air-side face on Z 0, the lip toward +Z.
- Matching:
  - keywords: shaft / lip / oil / radial / rotary seal, 3760, 6194;
  - the seal is read from "20x35x7", "for a 20 mm shaft" or "Ø20";
  - "shaft seal" no longer suggests the keyed shaft.
- Hex (`librarian`) has a stocked family `seal`: radial shaft seals only. O-rings, gaskets, and static, face, rod,
  piston and wiper seals stay unstocked, and so do "seal carriers" and other holders. `platform_env.NOT_STOCKED` no
  longer lists `seals?`.
- The agent prompt lists `shaft_seal(D)`.

**ICD** (`office/icd.py`): a new interface kind, `seal_seat`.
- Side a is the open cap and side b is the seal (Toolbox).
- Data:
  - sizes: d, D, b, fit H8 (the recess), shaft_fit h11 (recorded only);
  - placement: ax, axis, z (the seal's span), face_z (the cap's outer face), side (the outward sign);
  - links: seal_item, seal title, shaft_item, shaft_d;
  - relief_depth and standard.
- Cap feature: a `seat` of Ø D, H8, from the outer face, b deep, flagged `seal: True`.
- Seal feature: its lip bore Ø d in its own frame.
- `seated()` returns the `shaft_seal` code, with one base point per piece on the outer face and a frame per piece
  (`Rs`, `seal_frame`). Each seal's +Z points into the housing, so seals at the two ends of a planetary line face
  opposite ways.
- Gate checks:
  - `fit_unknown`;
  - `seal_depth`: the cap must be at least b + relief + 2 mm thick;
  - `seal_bore`: the recess must be larger than the cap bore, and the seal d must equal the shaft Ø.
- `seal_item` counts as "named", so a seated seal is never reported as `part_unplaced`.

**Layout** (`graph/layout.py`): `_plan_seals` and `_seal_seats`, wired into both the planetary path and the parallel
gearbox path.
- Slots are the open-cap copies that a shaft passes through:
  - planetary: both ends;
  - gearbox: the exit side (+Y) only.
- Each slot carries the shaft Ø there: the seat on a planetary shaft, `_exit_d` on a gearbox shaft.
- A seal goes where its connections say:
  - `mounted_on` a cap is assigned first;
  - then a seal carried by a shaft;
  - then one on the housing or with no connection.
- Within that, the ends the seal is named after come first ("Input ..." goes by the input shaft). Each cap copy takes
  one piece.
- Size comes from the Toolbox table for that shaft Ø. If the design names another size, a note says so.
- The cap grows to b + relief + 2 mm when it is thinner. An edited thickness is kept, and the gate reports it.
- Seals not placed are reported in the notes and stay in the BOM.
- The interface places the seal coaxially with the shaft, its outer face flush with the cap's outer face, and its lip
  on the shaft.
- Static seals (O-rings, gaskets and so on, `_NOT_LIP`) are left alone.

**Cap generator** (`office/generators.py`)
- When the ICD has a seal feature, the recess is the ICD's (Ø D, depth b). The generator checks that the recess is
  coaxial, opens from the outer face, and is for the shaft that passes. If it cannot fit the recess, it raises
  `Undetermined` rather than cut another one.
- With no seal in the ICD, the old behaviour stays (a recess from the table when one fits).
- Because both sides read the same table, the ICD's recess and the generator's recess agree by construction.

**Fitz and the rest**
- `program_assembly.integrate` places each piece with its own frame (`Rs`) and says "seated n shaft seals per the
  ICD".
- `assembly/render.py` and `graph/preview.py` draw seals (a ring, with the frame per piece).
- `graph/compile.py` describes a seal as "Radial shaft seal DIN 3760 type A ...", and `registry` maps
  seal -> `shaft_seal`.
- Web: the `seal_seat` kind, its row labels, and a one-line summary (`types.ts`, `Interfaces.tsx`, `model.ts`).

**Golden case (l) `planetary-seals`**
- `l_planetary_seals.intent.json` is A11's reply, rebuilt from the fixture. It keeps only the values the reply gave
  ("the model's guess") and the connection counts.
- `l_planetary_seals.toml` uses the k hand values plus the seals:
  - 20 x 35 x 7;
  - W = 123, end walls at ±61.5;
  - caps 12 thick, outer faces at ±73.5;
  - seals at Y -73.5 .. -66.5 and 66.5 .. 73.5.
- Expectations:
  - path fast;
  - 0 clashes, binned, loose, placeholders and blocked;
  - kinds including seal = 2;
  - both seals reused from the Toolbox;
  - each seal inside its cap along Y and touching its shaft.

## Verified

- `tests/test_shaft_seals.py` (new, 8 tests):
  - The seal volume by hand: Pappus triangle by triangle on the hand-written section, independent of the
    generator's edge sum. The test also covers the bbox, the lip touching a Ø20 cylinder, and three more sizes.
  - The table is shared and matched by the Studio and Hex; O-rings, gaskets and carriers are refused.
  - A11 fixture: `finish` + `decide` give the fast path. The ICD has both `seal_seat` interfaces with the hand
    numbers, and their seated placements and frames are checked. Hex returns the Toolbox seal 20×35×7.
  - The A11 caps go direct with the ICD's recess (SEAL_D 35, SEAL_WIDTH 7, H8).
  - Kernel check, solid by solid: the caps and shafts built by the generators, the Toolbox seals and the bearings,
    placed as Fitz places them, overlap nowhere (< 1e-6 mm³). Each seal touches its cap and its shaft (distance
    < 1e-6). Gage measures the recess as conforming.
  - Parallel gearbox (golden c reducer, with a seal mounted on each open cap): fast path. The seals are 20×35×7
    (input) and 30×42×7 (output, a 6206 journal), the caps are 12 and 16 thick, the seals sit flush on the +Y side,
    no seal goes in a blind cap, and both caps go direct.
  - Seals on the housing and on a shaft: specific seals are assigned first, the leftover piece is noted, and the gate
    is clean.
  - End to end: golden (l) through the Design Office (simulated, graph path, master rule on) passes with 0 tokens,
    0 clashes, 0 binned and 0 placeholders.
- Regression pairs: see the agent's hand-back for the per-file results.

## Defaults used (parked decisions, PD-290..299; not written to DECISIONS.md)

| PD | Decision | Default used |
|---|---|---|
| PD-290 | Seal size when the design names another D / b | The Toolbox DIN 3760 size for the shaft Ø passing the cap; a note names the difference |
| PD-291 | Seal geometry | Simplified type A: plain case, back web, one lip meeting the shaft at nominal d (no spring, dust lip, rubber cover or interference); D and b as catalogued |
| PD-292 | Recess and shaft tolerances | Recess H8 (gate-checked, Gage-measured); shaft h11 recorded in the ICD but no shaft feature added |
| PD-293 | A seal with no open cap to sit in (housing seat with no cap, blind cap) | Not placed: noted, stays in the BOM; no seal bore in a housing wall yet |
| PD-294 | Cap too thin for its seal | The cap grows to b + relief + 2 mm unless its thickness was edited (then the gate says `seal_depth`) |
| PD-295 | Assignment order | Mounted on a cap, then on a shaft, then on the housing or loose; names "input" / "output" pick their end first; one piece per cap copy |
| PD-296 | What Hex stocks as a seal | Radial shaft (lip) seals only; O-rings, gaskets and static, face, rod, piston and wiper seals stay "not stocked" (designed as bought-out parts) |
| PD-297 | Toolbox VERSION | Bumped to 4 as asked, although no existing component's geometry changed |
| PD-298 | ICD kind | New `seal_seat` (not `shaft_bore`): no editable values at the gate (the size follows the shaft) |
| PD-299 | Golden (l) geometry | Box relations (within / touch) in the TOML, which hold for any sizes; exact seal spans are checked on the ICD in pytest, since the graph path does not fix a plan's sizes for `modes = ["simulated"]` |

## Open

- A seal bore in a housing wall, for seats with no cap.
- O-rings and V-rings as their own Toolbox families.
- A shaft-side feature for the seal running surface (h11, surface finish) as a drawing callout.
