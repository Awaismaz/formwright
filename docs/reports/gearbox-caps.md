# Gearbox caps, cap screws and Hex part kinds (branch `wip/gearbox-caps`)

Follow-up to the founder's live "Gear Reducer" program (2026-11-19): one cap placed, three on the floor, 8 clashes at
the input open cap, Hex reading a nut and a washer as hex bolts and an oil plug as a washer, and 14 fasteners in the
parts bin floating above the housing.

## Root causes
1. **Caps:** `icd.build` (gearbox layout) took only the *first* cap item's copies (`cap_sts[0]`); a plan with four
   different single caps got one interface, and that one went over the -Y seat (where the shaft is flush), not where
   the shaft leaves. Every cap was given a shaft bore, blind ones included.
2. **Wrong screws / clashes:** the cap joint used the sub-assembly's first bolt item (the M8 cover bolts) instead of
   the plan's "Cap screw M6x16", and the PCD rule `D + clearance + 2` left 2.1 mm of wall between the M8 tap drill and
   the Ø47 seat. The real cap was designed with M6 holes (its description), so the ICD's M8 bolts clashed with it.
3. **Hex:** `read_toolbox` tested "is there a fastener word anywhere" first, so "Hex nut M8 for the flange bolts" was
   a bolt; the plan's Toolbox hint was then trusted ("Oil plug M16" with hint `washer`).
4. **Floating fasteners:** Fitz binned every standard part that found no joint: the "nut" and "washer" hex bolts, the
   cap screws (their joint named the cover bolt item, which had already taken all holes) and the plugs. Designed
   bought-out parts with no skeleton place (oil seals, plugs) were silently skipped.

## What changed
* `src/aicad/office/icd.py`
  * Cap matching (`_assign_caps`, `_cap_kind`): every seat gets a cap the plan has. Open caps (name, else
    description: open / through / seal / lip) go over the seat on the side the shaft leaves (`EXIT_SIDE` = +Y), blind
    caps (blind / closed / solid / blank) over the other; "input" / "output" in the name ties a cap to that shaft;
    the seat Ø written in the description breaks ties; identical generic caps fill seats in seat order (old
    behaviour). Unmatched caps keep `no_interface` (blocking, as before); seats without a cap are noted.
  * Ligament rule (stated in the notes and in code): wall between the bearing seat and each tap drill
    >= max(3 mm, 0.5 d). PCD = D + tap drill + 2 x ligament, rounded up to 0.5 mm; OD = PCD + ISO 7089 washer OD.
    One screw size for all caps of a housing, from the plan's cap screw item (M6 here), stepping down only if the caps
    can't sit side by side (noted).
  * The caps' `fastener_item` is the plan's cap screw item (a standard item whose name says bolt/screw and whose text
    says it fixes the caps); the cover joint keeps the other bolts.
  * Blind caps have no bore; open caps a bore of shaft Ø + 2. Every cap carries a 1 mm relief Ø (d + D) / 2 in its
    mounting face (clear of the turning inner ring and the shaft end, bearing on the outer ring). Interface data:
    `cap`, `seat_D`, `bearing`, `relief`. Excerpt says open/blind, flat face, no spigot.
  * New gate warning `ligament` when an edit leaves less than the rule (the live ICD's 2.1 mm is flagged).
* `src/aicad/assembly/librarian.py`: `kind_of(text)`: the last part noun of the leading phrase picks the family
  (bolt/screw, nut, washer, key, ring, bearing, dowel/pin, gear, shaft, standoff). Nouns with no Toolbox family
  (plug, breather, vent, seal, o-ring, gasket, spring, nipple, rivet, insert, grommet, clip, coupling, collar, cap,
  cover, bush, sleeve, magnet, dipstick, sight glass, stud) and other kinds of a stocked noun (lock / spring / tab
  washers, lock / wing / flange nuts, set / countersunk / button screws, roller / needle / taper bearings, spring /
  cotter pins, helical / bevel / worm gears, internal circlips) return "not stocked". `read_toolbox` reads only that
  family, never another.
* `src/aicad/office/platform_env.py`: Hex uses the plan's Toolbox hint only when it names the same family, rejects
  any reading of another family, and treats an unstocked head noun as not stocked (a designer models it as a bought-out
  part, as before). Bought-out parts the designer modelled that have no skeleton place now reach Fitz's integration.
* `src/aicad/office/program_assembly.py` (Fitz): fasteners first, then the plan's nuts / washers counted against the
  washers and nuts in the ICD's stacks; surplus and unjointed fasteners, tapped-joint nuts and unplaced bought-out
  parts are **reported, never binned** ("4 more than the ICD's joints take: not placed, in the BOM as planned").
* `src/aicad/office/deliverables.py` (BOM): stack parts match the plan item of the same code **and size**; the plan's
  quantity is listed with "From the plan: n placed by the ICD, m more than the ICD uses (not placed)".

## Evidence
* Founder plan rebuilt (copy of `program.json` in the scratch dir, his gate overrides for items applied): IF-15..18
  = Input blind (-Y), Input open (+Y), Output blind (-Y), Output open (+Y), all M6 on `Cap screw M6x16`, PCD 58 / 63
  (ligament 3.0 mm), no issues.
* `tests/test_office_gearbox_caps.py` (16 tests, hand values in the docstring): cap layout, the old 2.1 mm ligament
  flagged, 12 Hex strings (Hex nut M8 -> ISO 4032 M8, Washer M8 -> ISO 7089 M8, Oil plug M16 / Lock washer M8 /
  Drain plug M16x1.5 / Breather M12 / Taper roller bearing / Helical gear -> not stocked, Cap screw M6x16 and Socket
  head cap screw M8x25 -> ISO 4762), Hex with Archie's wrong hints, and the live plan end to end with simulated
  agents: 4 caps on 4 seats, 16 ISO 4762 M6 stacks through the caps + 4 M8 cover stacks, empty parts bin, whole-program
  check 0 clashes, every surplus reported.
* App on :8803 (simulated agents, scratch data): ICD 0 problems / 0 warnings, run complete in 61 s, "10 real parts and
  0 placeholders: 101 mates, 20 fastener stacks", whole-program check **0 clashes over 108 pairs**, 0 console errors.
  Screenshots read (scratch `fw-e2e-8803/shots/02-assembly.png`, `04-assembly-plusY.png`): blind caps with 4 screws
  each on the -Y face, open caps with 4 screws each on +Y with both shafts leaving through them, cover bolts on top,
  nothing floating. Fitz: "fitted 20 fastener stacks, seated 2 dowel pins, 18 planned parts not placed" (4 flange
  bolts, 8 nuts, 4 washers, 2 plugs).
* Tests run (1 to 2 files per call, no workers left): `test_office_phase6_layout` (hand values updated for the new
  PCD 61.5), `test_office_phase6_review_ecn`, `test_office_icd`, `test_library`, `test_toolbox_keys`,
  `test_office_shaft_line`, `test_office_orchestrator`, `test_assembly_ai`, `test_office_phase5`, `test_office_direct`,
  `test_ai_access`, `test_office_gearbox_caps`: all pass. `ruff check src tests` clean. No web changes (tsc not run).

## Not done / limits
* All shaft extensions leave through +Y. The founder's plan says "input on one side, output on the other"; the
  plan's assumptions are not read by the layout (PD-a).
* The cover joint is tapped into the base (no nuts), so the plan's 8 nuts are reported as unused; 8 flange bolts for a
  4-hole joint: 4 reported. The simulated cover is a solid 80 mm block, so its stacks are M8 x 100.
* "Dowel pin 6x20" is seated as Ø8 x 24 (the ICD sizes dowels from the bolt size): same kind, different size. Not
  changed here.
* Oil seals and plugs are modelled as bought-out parts but have no ICD seat (open cap seal bore, drain boss): reported.

## Parked decisions (default used)
* **PD-a: exit side.** Default: every gearbox shaft leaves through +Y (open caps there). Alternative: read
  "opposite sides" from the plan and mirror the output shaft.
* **PD-b: cap ligament.** Default: >= max(3 mm, 0.5 d) between seat and tap drill, PCD rounded up to 0.5 mm, one
  screw size per housing; a smaller ligament after an edit is a warning, not blocking.
* **PD-c: cap relief.** Default: 1 mm deep, Ø (d + D) / 2 on every cap (verify against the bearing maker's
  abutment diameters).
* **PD-d: surplus standard parts.** Default: reported in Fitz's notes and listed in the BOM at the plan's quantity
  with how many the ICD placed; never put in the parts bin. Alternative: trim the BOM to what is placed.
* **PD-e: unstocked bought-out parts.** Default: a head noun with no Toolbox family is "not stocked" and designed as
  a bought-out part (no substitution), even when Archie's hint names a Toolbox code.

## For the founder's existing program
The approved ICD cannot gain the cap interfaces by a change request or ECN: a CR may change the numbers of one
interface only and is refused when it moves other parts (the three loose caps) or touches integrated parts. Start a
new program from the same brief and approve the same plan on this build (his gate edits: shaft Ø 20 / 25.6, housing
146 high); the ICD then has all four cap interfaces and Fitz seats the caps and their M6 screws.
