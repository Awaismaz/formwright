# Connection layout, architecture v2 step 2 (branch `wip/connection-layout`, WORKLIST 44)

Goal: replace the per-mechanism layout templates with a layout solved from the design graph's connection semantics,
so any combination of known connections lays out without a new template, with the same skeleton, frames and ICD the
office, Fitz, the direct builder, conformance, drawings and the visual check already read. Mid-task the master added
the golden suite's layout findings (F1 to F6) and the founder's "foldable Table" program (R3) as acceptance.

## Results in one table: the golden suite, simulated

| Case | Old path before (golden-suite report) | Old path now | Graph path before (`FW_DESIGN_GRAPH=1`) | Graph path now |
|---|---|---|---|---|
| a keyed gear | PASS | PASS | PASS | **PASS** |
| b 1:3 gear pair | PASS | PASS | PASS | **PASS** |
| c reducer (housing, caps) | PASS | PASS | FAIL (F6: 16 M4 hex bolts for the M6 cap screws) | **PASS** |
| d bracket on a plate | PASS | PASS | skipped (no graph reply) | **PASS** |
| e roller, bearings in side plates | FAIL (F1, stalled) | FAIL (now stops at the interfaces gate: side plate #2 unconnected) | skipped | **PASS** |
| f linear stage | FAIL (F2, rods vertical) | FAIL (same) | skipped | **PASS** |
| g hinge arm | FAIL (F3, pin vanished) | FAIL (pin now reported at the gate) | skipped | **PASS** |
| R1 Test 5 | PASS | PASS | skipped | **PASS** |
| R2 Shaft Gear | FAIL (F4: Ø30 seat, circlips swapped) | FAIL (circlips by role fixed; key still on Ø30) | skipped | **PASS** |
| R3 foldable table (new) | (not a case) | **PASS** | (not a case) | **PASS** |
| **Total** | 5 of 9 | **6 of 10** | 2 of 3 run | **10 of 10** |

Graph path: `uv run aicad golden --simulated --env FW_DESIGN_GRAPH=1`, all ten pass (10.97 to 32.88 s per case, 0
clashes, 0 binned, 0 loose, 0 blocked everywhere). Old path: `uv run aicad golden --simulated`, no case that passed
before regresses; R3 passes on both paths, as the master asked. e, f and g stay template failures on the old path
(the template has no joint for side plates, sliding rods or pins); their graphs lay out correctly. The graph replies
for d, e, f, g, R1, R2 and R3 are hand-written (labelled so in each `*.intent.json`): the runner skips a case on the
graph path without one.

## What was built

| Piece | What | Files |
|---|---|---|
| Solver | `layout.build(graph, parts, brief, overrides)`: each connection kind places its guest by its registry rule; a breadth-first walk from a fixed base over the axis graph (meshes, belts, couplings); closed loops checked; heights two paths fix solved together; precise `layout_conflict`s; output in exactly the `icd.build` format (items, copies, `ax`, `rot`, datums, axes, interface kinds and data keys, tooth phase). Callable for any plan or graph (the "revise an approved program" work can re-run it) | `src/aicad/graph/layout.py` (new) |
| Contexts | gearbox (shafts in a housing), pillow blocks on a plate (with a motor on a bracket), supports standing on their own (side plates), free shaft line, shaft sub-assembly, guide rods in end blocks with a sliding carriage, pin joint (clevis and arm), blocks bolted on blocks, a base with connectors and members pivoting on them (the table) | `graph/layout.py` |
| Placement rules | keyed hub / hub fit, shoulder stop (a collar on to the bearing, or 5 mm in a housing), bearing journal, bearing seat (housing walls; supports centred on their bearing, every copy's seat open toward -Y so one part design serves all copies), gear mesh (a = m (z1 + z2) / 2, coplanar, phased v = 1/2 - u), belt drive (stated C, else C = D1 + D2), coupling, bolted joint (on top, or under a top; no more holes than the planned bolts, four when four are planned per joint), retaining ring (at the free face of what it holds), spacer, rod support and slide, pin joint and pivot bolt | `graph/layout.py` module doc |
| New kinds | components `pillow_block`, `motor` (bought out, envelope only), `coupling`; `other` gets an envelope (L, W, H); connections `belt_drive`, `coupling`, `rod_support`, `slide`, `pin_joint` (a pin, or a pivot bolt with washers and nut); `bearing_seat` hosts pillow blocks, brackets and plates; ICD kind `belt_drive` | `graph/registry.py`, `office/icd.py` |
| Office hook | a program whose plan carries a graph is laid out by the solver at plan approval and at every rebuild (ICD edits, change requests, autofix, frozen envelopes); a plan without a graph whose parts read cleanly by role (a top or base, brackets on it, legs or arms on them) is laid out from those roles (`graph/roles.py`), kept for every rebuild; otherwise the template; `FW_GRAPH_LAYOUT=0` switches graph plans back to the template | `office/interfaces.py`, `graph/roles.py` (new), `icd.new_icd(built=)` |
| Gates and checks | `layout_conflict` (error) names parts and connections; `no_interface` per copy (an unconnected copy blocks); `part_unplaced` (warning) for any bought-out part no interface places (nothing vanishes silently); slot cavities (`open_through`) for pins; ICD excerpt describes a slot | `office/icd.py` |
| Fitz | each joint is stacked with the fastener its ICD names, at every level, including joints between sub-assemblies (cap screws stay socket head); a fastener whose joints are between sub-assemblies is said to be fitted in the final assembly, not "not placed"; a program with an ICD waits for its assembly before integrating a level (the kit-level race that laid 28 fasteners in a row); a cluster of parts that joins the rest only at the next level up is a note, not a stop | `office/program_assembly.py`, `office/platform_env.py`, `office/visual_office.py` |
| Graph core | PD-114 sizes for housing fasteners the reply leaves unsized (cap screws M6 x 16 SHCS, cover bolts M8 x 30 hex); circlips on bearings sized to the journal; no "housing?" question when bearings are already seated; an exclusive brief keeps parts it names in its own words ("two guide rods") | `graph/resolve.py`, `graph/questions.py`, `graph/validate.py` |
| Template | circlips assigned by role (what each ring locates, from its name and description), never by order | `office/icd.py` |
| Parity harness | a pytest plugin that, beside every template layout an existing test builds, reads it back into a graph (`adapt.from_parts`), re-solves it and records agreement | `docs/reports/connection-layout/parity_plugin.py`, `parity.py` |
| Tests | 26: five WORKLIST mechanisms with hand-checked numbers, conflicts, fallback, freeze stability, office hook, spacer and circlips, roller, stage, hinge, table (graph and role paths), per-copy gate | `tests/test_connection_layout.py`, `tests/golden/connection_layout/*.json` |
| Golden cases | graph replies for d, e, f, g, R1, R2; new case R3 (the founder's plan, copied read only, and its graph) | `src/aicad/eval/golden_cases/*.intent.json`, `r_table.*` |

## The WORKLIST golden mechanisms (hand-checked; `tests/test_connection_layout.py`)

1. **Keyed gear on a stepped shaft**: shoulder face datum B (Y = 0); gear Y -20 .. 0; shaft 80, Y -22 .. 58; key
   6 x 6 x 18 at (6.5, -10, 0). Direct: "shaft Ø20 / Ø26 × 80, 1 seat, 1 keyseat". Identical to the template.
2. **1:3 pair, four 6204, no housing**: a = 80; bearings Y 15 .. 29 and -29 .. -15 on both axes; shafts 78.
   Identical to the template.
3. **3:1 reducer, split housing, four caps, shoulders inside** (live reply): cap screws M6, cover bolts M8 (PD-114),
   walls 24 (the M8 lid screws), housing 224 x 92 x 146; shafts 80 apart; each gear's +Y face on its shoulder (Y 10),
   a 5 mm collar in the cavity, seat from the -Y bearing's inner face, +Y journal out through the open cap (cap bore
   Ø22). `limits` empty: "not laid out yet" is gone. Direct: "shaft Ø20 / Ø26 / Ø20 × 128, 2 bearing journals, 1
   seat, 1 keyseat".
4. **Belt drive on pillow blocks**: C = 180 (rule), belt 647.74; axis 66 above the plate; pillow blocks 123.5 x 18 x
   101.5; shafts X -90 / +90; plate 324 x 106.
5. **Motor on a bracket, coupled to a shaft in two pillow blocks**: axis 70 (set by the motor), bracket 173 x 180 x 10,
   coupling 62 x Ø50, plate 193 x 399.

Conflicts (each a `layout_conflict` error with part names and connection ids): mesh at a = 80 and belt at C = 200
on the same two shafts; a hub on two shafts; an unconnected part; two stated axis heights that disagree. A consistent
loop is solved and said. Freeze then rebuild gives the same layout on all five.

## The golden suite's findings (master, mid-task)

| Finding | Fix | Evidence |
|---|---|---|
| F1 bearings in side plates | supports standing on their own: the shaft is the base, each plate centred on its bearing, both seats open toward -Y (copies are one design: opening them outboard on each side cut the seat straight through) | e PASS (graph); test `roller` |
| F2 linear stage green but wrong | `rod_support` and `slide`: rods along +Y at the stated spacing and height, ends flush in the end blocks, carriage between them, base turned along the rods | f PASS (graph); test `linear_stage` |
| F3 the pin vanished | `pin_joint`: the pin along Y through the lugs and the arm's bore (placed by `seated`, along its axis); the clevis slot; any bought-out part no interface places is now a `part_unplaced` warning at the gate, on both paths | g PASS (graph); test `hinge` |
| F4 Ø30 seat, circlips swapped | graph: the seat Ø and each ring at the free face of what it retains; template: rings by role. The template's seat Ø on a shaft line with bearings was tried and reverted (the Ø25 seat zone inside a Ø30 envelope trapped the gear and failed conformance) | R2 PASS (graph); old path R2 now fails only on the key position |
| F6 M4 hex bolts for M6 cap screws | PD-114 sizes in `resolve`; Fitz stacks each joint with the fastener the ICD names, at every level | c PASS (graph) |
| Founder's table (R3) | base by role, never the largest box; copies paired with their host's copies (leg i on bracket i), each with its own interfaces; pivot bolt joint (bolt, two washers, lock nut stacked); per-copy `no_interface`; believable assumed sizes (top 1200 x 700 x 18, legs 700, brackets 60 x 30 x 60, said in the notes); plans without a graph read by role | R3 PASS on both paths; tests `foldable_table`, `role path`, `unconnected copy` |

## Parity on the existing layout tests

PARITY

## Browser check (port 8809, simulated agents, the live reducer reply replayed)

Throwaway data, `FW_DESIGN_GRAPH=1`, the intent role on the replay provider (no tokens), `FW_OFFICE_FAKE_AGENTS=1`,
puppeteer-core 24, 0 console and page errors. Plan review: limits `[]` (no "not laid out yet"), check `[]`, one
question (gear material) answered with the default. ICD: 0 problems, 12 interfaces; the skeleton notes state the
solve ("the bores are at the centre distances (the loop through the housing is consistent by construction)",
"Input shaft steps to Ø26 behind the Pinion (a 5 mm collar in the cavity)"). Run: complete in 50.4 s, 20 of 20
tickets, 10 real parts, 46 standard, 0 placeholders, 103 mates, 0 clashes over 110 pairs, every level "Looks
assembled". Read by eye (`docs/reports/connection-layout/2-reducer-assembly.png`): the cover sits on the housing with
its bolts, both blind caps sit flush over the -Y bores with four screws each, nothing floats beside the housing; the
gears and bearings are inside the closed housing (their mesh is confirmed by the axes 80 mm apart and the ICD). The
sub-assembly thumbnails (`3-reducer-subassemblies.png`) show both stepped shafts with their collars. That run was
before the PD-114 fastener sizes (caps then M4).

## Known limits

* The solver lays shafts along +Y only. Graphs it doesn't lay out yet use the template (said in the notes): vertical
  shafts in a plate, a housing on a plate or next to free shafts, a coupling inside a housing, a shaft driving more
  than two others (a 2-D train), blocks with no connection between them.
* Old path: e, f and g still fail (the template has no joint for them); R2's key stays on the Ø30 envelope there.
* The role reader is deliberately narrow (exactly a base, connectors and members); anything else keeps the template.
* Part sizes the graph doesn't carry (an assumed block envelope, a cap's height) still come from `icd._initial` on the
  plan part (the compile writes it from the graph), as do the fastener rules.
* The motor is an envelope (assumed IEC-71-like size unless stated) and gets a designer ticket; pillow blocks,
  brackets and the clevis are boxes with their features (generators are WORKLIST 45).
* `part_unplaced` is a warning (shown at the gate), not blocking.

## Parked decisions (default used)

- **PD-130 Graph plans use the connection solver.** Default: on for every plan with a graph (`FW_GRAPH_LAYOUT=0`
  switches back to the template). Evidence: number-for-number parity on the golden cases and the reverse-adapted
  layouts; 10 of 10 golden cases on the graph path.
- **PD-131 Shoulder collar inside a housing.** A 5 mm collar of the shoulder Ø behind the stopped hub; the +Y bearing
  is located by its seat and cap, not by the collar. Alternative: a collar up to the bearing (enlarges the wall's
  clearance bore).
- **PD-132 Copies of one support are one design.** Every copy's bearing seat opens toward -Y (the +Y bearing goes in
  from the inboard side against an outboard shoulder). Alternative: mirrored parts (two designs).
- **PD-133 Belt centre distance when unstated: C = D1 + D2** (said in the notes and the ICD). Alternative: ask.
- **PD-134 Motor as an envelope item** (assumed 120 x 180 x 120, shaft Ø14 x 30 unless stated), coupling engagement
  1.5 d a side, bracket at least 10 mm, the axis height set by the highest path. Alternative: a bought-out catalogue.
- **PD-135 Housing fasteners when unsized: M6 x 16 cap screws, M8 x 30 cover bolts** (PD-114's rule applied in
  `resolve`). Alternative: size from the cap spacing (M4 here).
- **PD-136 Plans without a graph are laid out by role when they read cleanly** (a top or base, brackets, legs or
  arms; nothing else), with assumed sizes said in the notes (a table top 1200 x 700 x 18, legs 700). Alternative: only
  when the template's layout fails the gate.
- **PD-137 Per-copy `no_interface` blocks the gate**, like an unconnected item. Alternative: a warning.
- **PD-138 A level's cluster that joins the rest only at the next level up is a note**, not a stop (four
  leg-and-bracket pairs in "Legs", each bolted to the top in "Top"). Alternative: regroup the plan.
- **PD-139 Hand-written graph replies for golden cases without a recording** (d, e, f, g, R1, R2, R3), labelled as
  such. Alternative: one live intent call per case (about 10 platform tokens).

## Gate

GATE
