# Connection layout, architecture v2 step 2 (branch `wip/connection-layout`, WORKLIST 44)

Goal: replace the per-mechanism layout templates with a layout solved from the design graph's connection semantics,
so any combination of known connections lays out without a new template, with the same skeleton, frames and ICD the
office, Fitz, the direct builder, conformance, drawings and the visual check already read.

## What was built

| Piece | What | Files |
|---|---|---|
| Solver | `layout.build(graph, parts, brief, overrides)`: each connection kind places its guest by its registry rule; a breadth-first walk from a fixed base over the axis graph (meshes, belts, couplings); closed loops checked; heights two paths fix solved together; precise `layout_conflict`s; output in exactly the `icd.build` format (items, copies, `ax`, datums, axes, interface kinds and data keys, tooth phase) | `src/aicad/graph/layout.py` (new) |
| Placement rules | keyed hub / hub fit (anchor on the partner's mid-plane, the rest stacked +Y, key centred), shoulder stop (the hub's +Y face on the step, a collar on to the bearing or 5 mm), bearing journal (either side of what turns near it, against a collar or a spacer, flush with the end in a housing), bearing seat (housing walls; pillow block centred on its bearing, seat open outboard), gear mesh (a = m (z1 + z2) / 2, coplanar, teeth phased v = 1/2 - u), belt drive (stated C, else C = D1 + D2), coupling (coaxial, end to end, 2 mm gap, clear of the bearing), bolted joint (cover on its housing, caps over the seats, blocks on their host's face, a bracket under its motor), retaining ring (at the free face), spacer (between two faces) | `graph/layout.py` module doc |
| New kinds | components `pillow_block`, `motor` (bought out, envelope only), `coupling`; connections `belt_drive`, `coupling`; `bearing_seat` hosts pillow blocks and brackets; `bolted_joint` takes pillow blocks and motors; ICD kind `belt_drive` (centre distance, pitch Ø, belt pitch length, wrap) | `graph/registry.py`, `office/icd.py` (KIND_LABEL, EDITABLE) |
| Office hook | a program whose plan carries a design graph is laid out by the solver at plan approval and at every rebuild (ICD edits, change requests, Archie's autofix, frozen envelopes); a plan without a graph, or a graph the solver doesn't lay out yet, uses the template, said in the skeleton notes; `FW_GRAPH_LAYOUT=0` switches graph plans back to the template | `office/interfaces.py` (`_graph_layout`, `_rebuild`, `create`), `icd.new_icd(built=)` |
| Compile | `compile.to_icd` uses the solver (template on `template=True`, the switch, or `Unsupported`); `limits` lists the solver's conflicts (shoulders now lay out) | `graph/compile.py` |
| Shared ICD tweaks (backwards compatible) | `bearing_seat` may name its shaft journals (`journals`: a stepped shaft between them may be larger) and may have no flush end (`flush_z: None`, a pillow block); `issues` reports `layout_conflict` (error) from `skeleton.conflicts`; "Bearing cap screws" are no longer read as unplaced bearings | `office/icd.py` |
| Questions | no "housing?" question when pillow blocks carry the bearings | `graph/questions.py` |
| Reverse adapter | `adapt.from_parts` (item ids, no plan document); caps keep "open / blind" only when their name or description says it | `graph/adapt.py` |
| Parity harness | a pytest plugin that, beside every template layout an existing test builds, reads it back into a graph, re-solves it and records agreement; runner prints the table | `docs/reports/connection-layout/parity_plugin.py`, `parity.py` |
| Tests | five golden mechanisms with hand-checked numbers, conflicts, fallback, freeze stability, office hook | `tests/test_connection_layout.py` (20), `tests/golden/connection_layout/*.json` |

## Golden cases (hand-checked; `tests/test_connection_layout.py`)

1. **Keyed gear on a stepped shaft** (no bearings): shoulder face datum B (Y = 0); gear Y -20 .. 0; seat 2 mm past
   the free face (Y -22); shaft 80 (assumed) Y -22 .. 58, centre 18; key 6 x 6 x 18 at Y -19 .. -1, seated at
   (6.5, -10, 0). Direct: "shaft Ø20 / Ø26 × 80, 1 seat, 1 keyseat".
2. **1:3 pair, four 6204, no housing**: a = 80; gears Y -10 .. 10; bearings Y 15 .. 29 and -29 .. -15 on both axes;
   shafts 78. All four designed parts direct.
3. **3:1 reducer, split housing, four caps, shoulders inside** (the live reply): housing 216 x 84 x 146 (as the
   template sizes it), shafts at X -60 / 20 (80 apart), Z -68; input Ø20 seat, Ø26 step; output Ø30 seat, Ø38 step;
   each gear's +Y face on its shoulder at Y 10 with a 5 mm collar (Y 10 .. 15) in the cavity; the seat from the -Y
   bearing's inner face (-28 / -26) to the shoulder; +Y journal from the collar's end through the wall and the open cap
   (cap bore Ø22, the journal, not the step). `limits` empty ("not laid out yet" is gone), cross-check empty, 0 ICD
   problems. Direct: "shaft Ø20 / Ø26 / Ø20 × 120, 2 bearing journals, 1 seat, 1 keyseat" and "shaft Ø30 / Ø38 / Ø30 ×
   130 ...". The recorded reducer (no shoulders) is identical to the template, number for number.
4. **Belt drive on pillow blocks (new)**: pulleys Ø60 / Ø120 x 20, Ø20 shafts, 6204. C = D1 + D2 = 180 (rule, said);
   belt pitch length 647.74. Axis height max(60 + 6, 23.5 + 11.75) = 66 (the big pulley clears the plate). Bearings 9
   from the pulley faces (Y -33 .. -19, 19 .. 33); pillow blocks 123.5 x 18 x 101.5 at Y +-24, Z 50.75, two M6 each
   48.55 either side; shafts X -90 / +90, 86 long; plate 324 x 106 x 16. Both shafts direct.
5. **Motor on a bracket, coupled to a shaft in two pillow blocks (new)**: bearings 94 apart (the shaft carries
   nothing); coupling 62 long, Ø50, 30 a side, 2 mm gap; axis height 70, set by the motor (120 / 2 + 10 of bracket), so
   the bracket is 10 tall and 173 wide (its own M6 bolts outside the motor's), the pillow blocks 105.5 tall; shaft
   Y 22.5 .. 189.5 (167), motor centre Y -99.5, coupling centre 21.5; plate 193 x 399.

Conflicts (all `layout_conflict`, error, with the part names and connection ids): two shafts that mesh (a = 80) and
are belted at C = 200 ("over-constrained: change a size, or remove one of these connections"); a hub fitted on two
shafts; a part no connection reaches (still drawn beside the program, and said); a stated pillow block centre height
(70) and a stated bracket height that puts the motor axis at 80. A consistent loop (mesh and belt both at 80) is
solved and said ("Closed loops checked ... agree"). Freeze and rebuild give the same layout on all five.

## Parity on the existing layout tests

PARITY_TABLE

## Browser check (port 8809, simulated agents)

WALK

## Known limits

* Shafts run along +Y only. Graphs the solver doesn't lay out yet use the template (said in the notes, never silent):
  blocks with no shafts (plates and brackets bolted together), vertical shafts in a plate or a generic block, a
  housing on a plate or next to free shafts, a coupling inside a housing, a shaft driving more than two others (a 2-D
  train).
* One graph component has one size: a bearing component shared by two shafts of different Ø (the template picks a
  bearing per shaft) can't be read back from such a plan by the reverse adapter (one parity row).
* Part sizes the graph doesn't carry (a block's assumed envelope, a cap's height) still come from `icd._initial` on
  the plan part (the compile writes it from the graph), as do the fastener rules.
* The motor is an envelope (assumed IEC-71-like size unless stated): it gets a designer ticket in the office; a
  bought-out catalogue is not built.
* Pillow block and bracket shapes are boxes in the skeleton; their generators are step 3 (WORKLIST 45).

## Parked decisions (default used)

PDS

## Gate

GATE
