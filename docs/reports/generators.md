# Parametric generators and workspace templates (branch `wip/generators`, WORKLIST 45 and 48)

Goal (founder): most parts of a typical mechanism are built from the spec with no AI. Before this branch the direct
path (`office/direct.py`) built shafts, spacers and spur gears. It now also builds housings, covers, bearing caps,
plates and blocks, brackets, pulleys and sprockets, couplings, collars and plain hubs, straight from the design graph
and the approved ICD. A part the designer still makes with AI can be kept as a **workspace template**, and the next
part of the same family starts from it.

## Coverage on the golden suite (simulated, every case, both paths)

"No AI" means a designed part built without a design-agent turn: direct from the interfaces, from the Toolbox to the
ICD, or from a workspace template. "Before" is main 92ff4e0 run in a clean checkout, the same day and machine.

| Case | Graph path before | Graph path after | Old planner before | Old planner after |
|---|---|---|---|---|
| a keyed gear | 2 / 2 | 2 / 2 | 2 / 2 | 2 / 2 |
| b gear pair | 4 / 4 | 4 / 4 | 4 / 4 | 4 / 4 |
| c reducer | 4 / 10 | **10 / 10** | 2 / 11 | **8 / 11** |
| d bracket | 0 / 2 | **2 / 2** | 0 / 2 | **2 / 2** |
| e roller | 1 / 3 | **3 / 3** | 0 / 3 (stops at the ICD gate) | 0 / 3 (same) |
| f linear stage | 1 / 4 | **4 / 4** | 1 / 4 | **2 / 4** |
| g hinge arm | 0 / 2 | **2 / 2** | 0 / 3 | 0 / 3 |
| R2 shaft gear | 2 / 2 | 2 / 2 | 1 / 2 | 1 / 2 |
| R3 table | 0 / 5 | **2 / 5** | 0 / 5 | **2 / 5** |
| R1 test 5 | 2 / 2 | 2 / 2 | 2 / 2 | 2 / 2 |
| **Total** | **16 / 36 (44 %)** | **33 / 36 (92 %)** | **12 / 38 (32 %)** | **23 / 38 (61 %)** |
| Cases passing | 10 / 10 | 10 / 10 | 5 / 10 | 5 / 10 |
| Simulated agent tokens | 700 | **105** | 805 | **420** |

- The graph path's three parts left for the designer are all in the founder's table (R3). The leg hinge bracket
  carries holes on its top and both sides, so it isn't an L bracket mounted by its foot. The wood screw and the pivot
  lock nut are bought-out parts with no Toolbox family.
- Old planner: the parts left are the ones whose plan text states sizes the interfaces don't explain. Examples: the
  reducer shafts' "22 mm pinion seat", the end block's "two Ø12 bores 60 mm apart" (the template layout has no rod
  bores), the clevis "lugs". The oil plug is a bought-out part. The failing cases fail the same way on main (layout
  findings F1 to F4); nothing here changed them.
- Simulated wall time goes **up** where parts go direct (reducer, graph path: 28 s to 59 s). A simulated agent turn
  takes about 0 s, while a direct build is a real CAD build on the program's one worker (0.3 to 7 s a part, the
  housing the longest). Live, a design turn is about 60 s and 22 platform tokens a part (`agent-cost.md`). The
  simulated time understates the gain. The live pass below measures it.
- Records: `docs/reports/generators/` (`{main,after}-{sim,graph}.json`).

## Live pass, case (c) reducer, graph path, cap 60 tokens
`uv run aicad golden --live --case c --cap 60 --env FW_DESIGN_GRAPH=1`, real agents (development login), then the
kept platform served on :8810 and walked with puppeteer-core (`generators/walk.mjs`, 0 console or page errors).

| | Result |
|---|---|
| Outcome | **PASS**, every expectation (4 caps, 16 M6 cap-screw stacks, 4 M8 cover stacks, gears 80 apart, 0 clashes, nothing binned or loose) |
| Platform tokens | **12** of the 60 cap (all of it the intent and plan step; 0 for design and review) |
| Wall time | 99.8 s: plan 19.5 s, gates 1.0 s, run 79.2 s, clash check 0.04 s |
| Designed parts | **10 / 10 without AI**: housing, cover, 4 caps, 2 shafts and 2 gears, all "Built from the interface spec (no AI)"; Toolbox keys, bearings, screws and bolts |
| Assembly | 10 real parts, 0 placeholders, 46 standard parts, 103 mates, 20 fastener stacks; whole-program check: 0 clashes over 110 pairs |

For comparison, the same graph path on main left the housing, cover and 4 caps to the designer. Live that is 6 design
turns of about 60 s and 22 tokens each (`agent-cost.md`), about 130 tokens with Gage's notes on top. The founder's
own live "Gear Reducer" (2026-11-19) took 689 tokens. Not re-run: the cap for this pass was 60 tokens.

Screenshots read: `live-03-assembly.png` shows the housing with its cover bolted on top (4 M8 bolts), both blind caps
on the -Y wall with 4 screws each, seated on the raised pads, and nothing floating. `live-02-drawer-housing.png` shows
the housing ticket ("Built from the interface spec (no AI) in 11.3 s", the design notes, and interfaces conforming to
ICD v1, 6 interfaces listed). `live-04-office-home.png` shows the new "Part templates" panel (empty: nothing in this
run needed AI). The visual check said "Can't tell from the picture" for the housing and the final assembly (its
offline heuristic on a closed box), and "Looks assembled" for the shafts and caps.

## What was built

### Generators (`src/aicad/office/generators.py`, pure; `fw_std` helpers)
Each generator reads the part's interface features (`icd.item_features`), and the design-graph component when the
program has one (cap style, seal component, pulley kind). It writes a normal Studio script with these properties:
- `PARAMS` and `PARAM_META`, so every parameter is editable and mapped by the viewport dimensions (DS-038). The tests
  check that every editable parameter has its meta.
- Interface numbers written as parameter expressions (`WIDTH / 2 - SEAT_1_DEPTH`).
- A header listing every interface it carries and every design choice.
- EXPECTED from hand formulas.

The scripts go through the same build, check (CHK-02 to 08) and ICD conformance gate as any part.

| Kind | What the interfaces fix | What the generator adds (said in the script) |
|---|---|---|
| Gearbox housing (block with the ICD's gear cavity and bearing seats) | bearing seats at the centre distance, shaft clearance, cap screw tapped holes on the cap PCD (ligament rule of `gearbox-caps`), cover tapped holes, dowel holes, cavity and floor (sump) | wall rule as the `WALL` minimum (max(B + 4, cap screw depth + 3, 12)); cap pads (outer faces relieved 2 mm round pads cap OD + 4); mounting feet (underside relieved between two feet, 4 tapped holes, M size by footprint, 1.5 d from the edges) |
| Cover (a lid on a housing) | bolt and dowel holes | shelled from below over the housing's cavity, roof max(8, 0.15 H) |
| Bearing cap, open and blind | flange OD, holes on the PCD, relief over the inner ring, mounting face | open caps: shaft passage and a lip-seal recess (the plan's seal when it fits the shaft, else the graph's seal, else DIN 3760 by shaft Ø; verify); rim chamfer. Blind caps: no spigot, said (the ICD has the cap bear flat on the outer ring) |
| Plate, block, side plate, pillow block, end block, carriage, clevis | every ICD hole, bore, seat and slot along any axis; shoulders; tapped holes with cosmetic threads | the brief's "four Ø9 corner holes" at 1.5 d from both edges; edge distance below 1.5 d is noted |
| L bracket with gussets | foot holes | foot and upright thickness (the brief's, from the part's or the program's sentences, else 0.12 × the smaller side), the upright on the edge that clears the ICD's washers (else the designer, with the numbers), gussets via `fw.gusset` when they clear every washer, the brief's upright hole |
| Pulley | bore, DIN 6885 hub keyway, faces | plain flat pulley (rim 0.08 OD, web 0.3 W, hub 1.8 d); timing pulley simplified to its pitch cylinder z p / π with flanges (GT2, GT3, HTD 3M/5M/8M, T2.5/5/10, XL, L); sprocket simplified to its pitch disc p / sin(180° / z), tooth width 0.93 b1 (ISO 606 / ANSI chains). V-belt pulleys go to the designer |
| Rigid sleeve coupling | bores and keyways | jaw, spider, flexible, Oldham and similar couplings go to the designer |
| Set-screw collar | the spacer's bore and envelope | radial tapped hole (the brief's M size, else by bore) |
| Plain hub, tube, drum, flange | bores, keyways | a plain turned part to the envelope (said) |

`fw_std` (new, backward compatible): `machined_volume` / `machined` take a box or disc and subtract axis-aligned box
pockets (round pads can be kept standing) and axis-aligned cylindrical cuts. The hand volume refuses what it can't sum
exactly: cuts crossing other cuts, a cut half inside a pocket or pad, holes breaking out. Also `hub_keyway`, and
`revolved_volume` / `revolved` (Pappus). They are not re-exported from `fw.py` (a Studio file), so scripts import
`fw_std`; the master may add them to `fw.py`'s import list (one line).

### The direct decision (`office/direct.py`)
- Parts the old kinds don't cover go to `generators.plan_part`. A spacer whose brief asks for a set screw becomes a
  collar.
- **Direct** when the interfaces fix every feature and the brief asks nothing beyond them. **Seed** (the designer
  starts from the generator's model) when only brief extras are missing. **Agent**, with the reason, when the
  interfaces don't fix the part. The per-kind extras check works like this:
  - an M size equal to the ICD's fasteners is not "a thread", and "hex bolts" is not "a hex";
  - words the generator builds are allowed (flange on a housing, recess and seal on an open cap, gusset on a bracket);
  - a plan clause about a hole pattern the ICD now fixes is superseded, like the planned envelope;
  - shape words in the description (lugs, slots, pockets, counterbores...) send the part to the designer.
- The ticket records the path: `direct` with kind, generator version and design notes; the seed kind; the template
  used. The drawer and the board say it in plain words: "Built from the interface spec (no AI)", "Built from a
  workspace template (no AI)", or "Designed with AI, starting from ...".

### Workspace templates (`src/aicad/office/templates.py`, row 48)
- **Offer:** a part the designer made with AI, approved, with a parametric script (`PARAMS` and `PARAM_META`). The
  ticket drawer offers "Keep as a template"; the server checks eligibility (422 with the reason otherwise).
- **Record**, at `<org root>/templates/<id>.json` (tenant scoped by the organisation folder):
  - family (the generator kind, else role and head noun);
  - feature signature (counts of type and axis);
  - named interface quantities (envelope, feature Ø, seat depths, keyways, PCDs);
  - parameters with their bindings (bound to quantities by value, or finish, or design value);
  - the script, the material, the source part and the brief extras it answered.
- **Reuse** (`orchestrator._direct_plan`, on a ticket's first design turn when the direct path says agent): same
  family only. Score = 0.5 × feature-multiset overlap + 0.5 × mean envelope size ratio; templates under 0.5 are
  ignored.
  - **Used directly** (labelled, 0 tokens, counted as a use) when all of these hold: the feature sets are equal, every
    parameter is bound or a finish, the bound quantities agree on the new part, and the brief asks nothing its source
    part didn't answer.
  - Otherwise **seeds** the designer, with the parameters that map substituted and the loose ones named.
  - A generator seed wins over a template with other features.
  - The build gate and conformance still check the result; a failed direct build falls back to the designer.
- **API:** `GET /api/office/templates`, `POST /api/office/programs/{pid}/tickets/{tid}/template`,
  `DELETE /api/office/templates/{id}`.
- **UI:** a "Part templates" panel on the Office home (family, how many sizes follow the interfaces, uses, source,
  delete) and the offer in the ticket drawer.
- **Not done:** the Studio's Toolbox panel (`studio/Toolbox.tsx`, a Studio file) doesn't list templates. Entry point
  for the master: a "Workspace templates" section there, reading `GET /api/office/templates`.

## Tests (`tests/test_generators.py`, 11 tests, about 45 s, no live AI)
Hand values, never measured from the built part:
- `machined_volume` on a box with a pocket, holes and a counterbore, and on a disc with a rim chamfer; the refusals;
  a Pappus ring.
- **Reducer (founder's plan):** housing, cover and four caps go direct.
  - Seat X difference 80 = m (z1 + z2) / 2. Seats 47 × 14 and 52 × 15 (ISO 15).
  - Cap PCD 58 and 63 = D + tap drill 5 + 2 × 3. Tap drill 5 and depth 18 (M6). Wall 24 with the rule's minimum 21.
    Feet M8, 1.5 d = 12.
  - Open cap: Ø70, PCD 58, Ø6.6, bore 27, seal 25 × 40 × 7. The plan's 20 × 35 × 7 is superseded, and the script
    says so.
  - Blind cap: spigot note. Cover hollow 176 × 62.
  - Housing, open cap and cover pass CHK-02 to 08 and ICD conformance. The open cap's volume matches the hand
    formula to 1e-6.
- **Base plate (d):** corner holes Ø9 at 13.5. The plan's bracket (8 mm upright) goes to the designer with the
  washer numbers.
- **Graph-path bracket:** 8 mm foot and upright from the brief's sentence; hand volume with gussets; gate and
  conformance. The clevis slot from the layout passes the gate and conformance.
- **Pulley (connection-layout golden):** Ø60 × 20, bore 20, keyway 6 × 2.8, hub 36, rim 4.8; hand volume by Pappus
  less the keyway; gate and conformance. HTD 5M 24T pitch Ø 38.197. V-belt, GT2 without teeth and set screws go to
  the designer.
- **Coupling:** the motor drive's Ø20 and Ø14 bores, each stated through the whole coupling, are refused with the
  reason. With one bore size it is built and conforms.
- Graph reducer: all 10 designed parts direct.
- **Templates:**
  - bindings (OD to D, LENGTH to H, BORE to hole Ø; CHAMFER finish; WALL design);
  - similarity by hand (0.5 + 0.5 × (50/60 + 200/250) / 2);
  - seed with the loose parameter named; direct reuse when every parameter maps; a new brief extra blocks direct use;
  - other families never match; deletion and path safety; eligibility refusals;
  - end to end in the office: a simulated part isn't parametric (422). A parametric one is kept through the API and
    marked on the ticket. A second program's clevis turn starts from the template. Another workspace sees none and
    can't delete it.
- Updated where the behaviour changed on purpose:
  - `test_office_direct` (a plate now goes direct);
  - `test_design_graph` and `test_connection_layout` (the reducer's and the belt drive's housings, caps, pulleys,
    pillow blocks and plates go direct);
  - the agent-path tests now run with `FW_OFFICE_DIRECT=0`, because their blocks used to go to the scripted designer:
    `test_office_orchestrator` end to end and budget, `test_office_icd` swap-in and change request, and
    `test_office_phase5` calibration.
- Gate after `git merge main`, two files per run, workers reaped. Every file passes:
  `test_generators`, `test_office_direct`, `test_office_orchestrator`, `test_golden`, `test_connection_layout`,
  `test_office_gearbox_caps`, `test_design_graph`, `test_program_revision`, `test_office`, `test_office_archie_chat`,
  `test_office_icd`, `test_office_layout_envelopes`, `test_office_phase5`, `test_office_phase6_layout`,
  `test_office_phase6_review_ecn`, `test_office_polish`, `test_office_shaft_line`, `test_office_small`,
  `test_office_supervisor`, `test_assembly_ai`, `test_assembly_visual`, `test_platform`. Also `ruff check src tests`,
  `tsc --noEmit`, `npm test` (157) and `vite build`. The full suite was not run in one go (resource rule).

## Parked decisions (default used)
- **PD-210 Lip seal on open caps.** Default: every open cap gets a seal recess for the shaft the ICD passes (the
  plan's seal when it fits that shaft, else the graph's seal component, else the DIN 3760 table, marked verify). A
  plan seal sized for another shaft is superseded, with a note. Alternative: a seal only when the brief names one.
- **PD-211 Blind caps have no spigot.** Default: the ICD's flat face with the relief locates on the outer ring; a
  brief's "spigot" is noted, not modelled. Alternative: a spigot (the ICD would need the seat deeper than B).
- **PD-212 Housing design additions.** Default: cap pads (2 mm relief, pads cap OD + 4) and mounting feet (2 mm
  underside relief, 4 tapped holes, M6 under 120 long, M8 under 250, M10 under 400, else M12; 1.5 d from the
  edges; depth 2 d), all inside the envelope. Each is dropped (and said) when it would cross an interface feature.
  Alternative: feet as flanges outside the envelope (needs the layout to size them).
- **PD-213 Superseded plan statements.** Default: a plan clause about holes that names one of the ICD's hole Ø or
  fastener sizes is the plan's view of a joint the approved ICD now fixes, so its numbers are not extras. Alternative:
  any unexplained number sends the part to the designer (the old rule).
- **PD-214 Default materials.** Housings, covers and pulleys Aluminium 6061-T6; caps, plates and brackets Steel 1018;
  couplings, collars and hubs Steel 1045; unless the plan or graph names one.
- **PD-215 Brackets.** Default: an L bracket only when every interface feature is on its foot; the upright goes on the
  longer edge that clears the washers; gussets only when they clear every washer. Otherwise the designer, with the
  numbers. Alternative: a solid block bracket (it would conform, but it isn't a bracket).
- **PD-216 Simplified pulleys and sprockets.** Default: timing pulleys as their pitch cylinder with flanges,
  sprockets as their pitch disc (teeth not modelled, said in the script). V-belt pulleys go to the designer.
- **PD-217 Templates are kept on request, not automatically.** Default: the engineer presses "Keep as a template" on an
  approved AI part. Alternative: keep every eligible part automatically.
- **PD-218 Template reuse thresholds.** Default: same family; similarity at least 0.5 to seed; direct only with the same
  feature set and every parameter mapped. Alternative: direct use with design values scaled by the size ratio.
- **PD-219 Live pass on the graph path.** The one live run of (c) used `FW_DESIGN_GRAPH=1` (architecture v2, the path
  the generators read the graph from). The old planner path was measured simulated only.

## Findings for the master (not fixed here)
- **G1 Stepped coupling bores.** The connection layout states both bores of a coupling between Ø20 and Ø14 shafts as
  through holes. No stepped bore can be through twice, so conformance would refuse any model. The coupling goes to
  the designer with that reason; the layout should give each bore its span (depth).
- **G2 Old planner, roller (e).** It stops at the ICD gate ("Side plate #2: no interface connects this copy"), on
  main too. The graph path lays it out and builds all three parts direct.
- **G3 Simulated wall time.** Direct builds show up as slower than simulated agent turns (about 0 s each). The golden
  dashboard should not read the simulated wall time as the product's speed.

## Files
- New: `src/aicad/office/generators.py`, `src/aicad/office/templates.py`, `tests/test_generators.py`,
  `web/src/pages/app/office/Templates.tsx`, this report and `docs/reports/generators/`.
- Changed: `src/aicad/fw_std.py` (new helpers only), `src/aicad/office/direct.py` (dispatch, collar, template
  wording), `src/aicad/office/orchestrator.py` (template lookup, path record), `src/aicad/platform/routers/office.py`
  (3 template endpoints), `web/src/pages/app/office/{TicketDrawer,Board,Home,types}`, `tests/test_office_direct.py`
  (one assertion). No Studio files.
