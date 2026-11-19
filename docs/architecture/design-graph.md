# The design graph (architecture v2, step 1)

Founder direction (2026-11-19): AI at the edges (intent in, explanations out), determinism in the middle. One typed
design graph is the single source of truth for the Design Studio and the Design Office. The AI writes the graph through
a validated schema and asks 1 to 3 questions instead of guessing. Sizing comes from standards tables; layout is solved
from the connection semantics (step 2, WORKLIST 44); geometry comes from parametric generators per component;
verification is deterministic.

This document is step 1 (WORKLIST 43): the schema, the core, the compilers to what runs today, the intent compiler,
and the office hook behind `FW_DESIGN_GRAPH=1`. Code: `src/aicad/graph/`. Tests: `tests/test_design_graph.py`.
Results: `docs/reports/design-graph.md`.

## 1. Why

Today a brief travels as prose. Archie writes a plan whose part descriptions are free text ("Steel shaft (42CrMo4)
with 25 mm bearing seats and a 30 mm gear seat"); the layout (`office/icd.py`) re-reads sizes out of that text with
regular expressions; the direct builder (`office/direct.py`) re-reads it again and sends a part to the AI whenever the
text names a size the interfaces don't explain. Every founder complaint of the last week traces back to that chain:
"h6" read as Ø6, Ø25 read as the seat, a housing added that the brief ruled out, a key in the parts bin, a cap on the
wrong seat. The live comparison in the report shows the same thing again: Archie's own plan for the 1:3 pair named a
"22 mm" hub and a "web", so both gears went to the AI; his reducer plan had two blocking ICD problems.

The graph removes the prose from the middle. The model states *what* (parts, how they connect, sizes the brief
states); code decides *how big* (standards), *where* (layout) and *whether it is right* (checks).

## 2. The schema (`graph/model.py`, versioned: `schema = "fw-design-graph"`, `version = 1`)

```
DesignGraph
  name, brief, summary, units = "mm", source = intent | plan | manual
  components : [Component]       one per distinct part (qty for identical pieces)
  connections: [Connection]      typed joints between components
  constraints: Constraints       what the brief rules in and out (hard)
  assumptions, notes             plain words: the model's assumptions; what code changed
  questions  : [Question]        open clarifying questions (fw-questions MCQ format), at most 3
  answers    : {question id: answer}
  layout     : solved positions read back from the skeleton (step 2 makes this the layout's output)

Component   id, kind, name, qty, group (sub-assembly), material, implied (added by code), params {name: Param}
Connection  id, kind, host, guest, via [component ids], params {name: Param}
Param       value, source = brief | answer | standard | rule | assumed | layout | plan, note ("DIN 6885-1 for Ø20")
Constraints named [kinds], excluded [kinds], exclusive (bool)        (kinds are office/scope.py's words)
Question    id, question, options[2..6], default, why
```

Every value carries its source, and the plan review shows it: what the brief said, what a standard sized, what a
stated rule derived, and what was assumed. A value the model gives that is not written in the brief is marked
`assumed` (the model's guess), never `brief`.

### Component registry (`graph/registry.py`)

| kind | family (office) | key params | bought out as |
|---|---|---|---|
| shaft | turned | d (seat Ø), shoulder_d, journal_d, length, stepped, role | |
| spur_gear | gear | module, teeth (required), face_width, bore, role | |
| key | standard | shaft_d, b, h, t1, t2, length | Toolbox `parallel_key`, DIN 6885-1 A |
| bearing | standard | designation, series, d, D, B | Toolbox `bearing`, ISO 15 |
| retaining_ring | standard | shaft_d, d2, m, s | Toolbox `retaining_ring`, DIN 471 |
| spacer, pulley, hub | turned | bore, od, width / length | |
| housing, cover | machined | style, L, W, H | |
| bearing_cap | turned | style (open / blind), seat_D | |
| plate, bracket | machined | L, W, T / H | |
| fastener, nut, washer, dowel, seal | standard | style, size (M), length | Toolbox `hex_bolt` / `shcs` / ... |
| other | machined | none | |

### Connection types: the semantics

| kind | host (carries) | guest | via | host features | guest features | placement rule | ICD |
|---|---|---|---|---|---|---|---|
| keyed_hub | shaft | gear, pulley, hub, spacer | key (added if missing) | seat Ø d k6, keyseat b x t1 | bore Ø d H7, hub keyway b x t2 | coaxial; axially by its shoulder stop, else centred on the seat; key centred in the hub | shaft_bore + key |
| hub_fit | shaft | same | | seat Ø d | bore Ø d | coaxial, as above | shaft_bore |
| shoulder_stop | shaft | hubs, bearing | | shoulder (step to a larger Ø) | face against it | faces coincident at the shoulder | shaft_bore (seat_z, shoulder_z) |
| bearing_journal | shaft | bearing | | journal Ø d k6 | inner ring bore | coaxial; two per shaft, one either side | bearing_journal / bearing_seat |
| bearing_seat | housing | bearing | | bore Ø D H7 through the wall, shoulder | outer ring | shaft axis through the walls | bearing_seat |
| gear_mesh | gear | gear | | | | parallel axes at a = m (z1 + z2) / 2, coplanar, phased | gear_mesh |
| bolted_joint | housing, plate, bracket, cover | cover, cap, plate, bracket | fasteners | face, tapped / clearance holes | face, clearance holes ISO 273 | faces coincident, holes aligned | hole_pattern |
| ring_retained | shaft | hubs, bearing | retaining ring (added) | groove d2 x m DIN 471 | face against the ring | ring in its groove at the free face | retaining_ring |
| mounted_on | any | any | | mounting face | seating face | on the host's face | face |

Axial and radial location are separate connections on purpose, like mates: a keyed hub is "concentric", a shoulder
stop is "coincident". The intent prompt's vocabulary is generated from these registries (`prompt_reference`).

## 3. What the AI does and what code does

| Step | Who | Where |
|---|---|---|
| Read the brief: which parts, how they connect, sizes it states, ambiguities that change the design | **AI** (one call, role `intent`, strict JSON schema) | `graph/intent.py` |
| Hard constraints from the brief ("just", "only", "no X", "without X") | code | `office/scope.py` via `intent.constraints_of` |
| Repair: drop what the brief rules out, unknown kinds read from the name, dangling links | code | `graph/validate.repair` |
| Answers to code's questions (housing, bearings, material) | code | `graph/questions.apply_answers` |
| Completing a named housing (cover, seats, caps, screws, bolts) | code | `graph/questions.complete_housing` |
| Sizing: keys, bearings, rings, shoulders, teeth from the ratio, output shaft, face width, bores, centre distance | code | `graph/resolve.py`, `graph/standards.py` |
| Validation (17 stable codes) | code | `graph/validate.issues` |
| Questions: at most 3, code's first; never about sizes | code (+ the model's, filtered) | `graph/questions.ask` |
| Plan, layout, interfaces | code | `graph/compile.to_plan`, `office/icd.build` |
| Cross-check of the graph against its ICD | code | `graph/compile.check`, `limits` |
| Part geometry | code where a generator exists (`office/direct.py`), else the design agent | unchanged |
| Explanations (plan review narrative, notes) | code today, plain words from the graph | `graph/office.narrative` |

Model routing (PD-82, `llm/routing.py`): the role `intent` with a job size. `intent.job_of(brief)`: a short brief that
names only a shaft and what rides on it (no housing, no machine words) is `simple` and runs on Sonnet; everything else
is `complex` and runs on Opus. Evidence: the three live runs (report) gave the same graph a hand would write on Sonnet
for the two simple cases.

## 4. How the current pieces map onto it

| Today | In the graph | Compiler / adapter |
|---|---|---|
| **Planner plan** (`office/planner.py`: sub-assemblies, parts, family, complexity, qty, description, layout hints) | components (+ group), the plan is generated | `compile.to_plan`: descriptions written from the numbers in the phrases `icd.py` and `direct.py` are tested on; envelope, module, teeth, mounts_on as hints; a small shaft-riding plan is one unit (PD-93) |
| **ICD / skeleton** (`office/icd.py`: roles, envelopes, layouts shaft_line / gearbox / block, interfaces) | connections; `layout` read back | `compile.to_icd` runs `icd.build` exactly as the office does; ICD overrides for values text can't carry (gear face width) by part name, applied in `interfaces.create` |
| **Direct builder** (`office/direct.py`) | components whose generator exists (shafts, spur gears, spacers) | `compile.to_direct` runs `direct.plan` on the compiled, approved-as-is ICD |
| **Fitz trains** (`assembly/trains.py`) | a housing-less train of Toolbox shafts, gears and bearings | `compile.to_fitz_items` gives the smart-insert items (`trains.select` takes them as they are) |
| **Toolbox** (`toolbox.py`) | the bought-out kinds and their tables | `registry.ComponentType.toolbox`; `standards.py` uses the Toolbox tables as the single copies |
| **Scope check** (`office/scope.py`) | `constraints` | `intent.constraints_of`, `validate.repair` / `issues` (`excluded`, `not_named`) |
| Old programs (plan + approved ICD) | a graph with `source = "plan"` | `adapt.from_office` (reverse adapter) |

The cross-check is the deterministic verification of the compile: every connection must come out as the interface
it means, with the numbers the graph sized (centre distance and axis spacing, key b x h and the key piece in the
keyseat, seat and shoulder Ø, bearing designation), nothing excluded may appear, and every designed part must be
placed. `limits` lists what the graph states that today's layout does not realise yet (a shoulder inside a housing:
the gearbox layout seats gears on plain shafts between the bearings). Both are shown at plan review.

## 5. Studio and Office share it

* **Office (built, behind the flag):** `FW_DESIGN_GRAPH=1` makes Archie's planning turn intent -> graph -> plan.
  The plan carries `plan["graph"]` (data, view, questions, check, limits). Plan review shows a compact list of parts
  (key sizes, coloured by source) and connections, and the questions as clickable choices; approval waits for the
  answers. Everything after plan approval (tickets, ICD gate, direct builds, Fitz, Gage, deliverables) is unchanged.
  The old planner stays the default (PD-110).
* **Studio (next):** the same graph describes a multibody part or a small assembly in the Studio: the design agent
  writes the graph through the same schema instead of free code for standard mechanisms, `compile.to_direct` (and
  the Toolbox generators) give the bodies, and the agent keeps the free-form work. A Studio project stores
  `graph.json` next to `model.py`; "Open in the Design Office" hands the graph over unchanged, and an Office part
  opened in the Studio carries its component and connections (its ICD excerpt today is derived from them).
* **One schema, one validator, one set of standards**, so a key sized in the Studio and in the Office is the same key.

## 6. Migration path

1. **Now (this branch):** schema, core, compilers, reverse adapter, intent compiler, office flag; golden cases pass on
   both paths. Default unchanged.
2. **Flag on by default** once the golden suite (WORKLIST 46) passes on the graph path for every case it holds, with
   the old planner as the fallback when the intent step fails (already wired: a failure falls back to the standard
   breakdown, as an Archie failure does today).
3. **Step 2 (WORKLIST 44, built on `wip/connection-layout`):** the layout solves positions from the connections
   directly (`graph/layout.py`): each connection kind places its guest by its registry rule, a walk from a fixed base
   (housing, base plate, else the input shaft) over an axis graph of meshes, belts and couplings, closed loops checked
   (a `layout_conflict` names the parts and connections), heights two paths fix solved together. Same skeleton and
   ICD format as `icd.build`; the template stays the fallback for graphs the solver doesn't lay out yet and for plans
   without a graph (`FW_GRAPH_LAYOUT=0` switches graph plans back to it). Shoulders inside housings lay out; `limits`
   is empty on the golden cases. New kinds: `pillow_block`, `motor` (bought out, envelope only), `coupling`;
   connections `belt_drive` and `coupling`. Report: `docs/reports/connection-layout.md`.
4. **Step 3 (WORKLIST 45):** generators for housings, caps, brackets, plates and pulleys from the graph (the direct
   builder grows per component kind).
5. **Instant preview (WORKLIST 47):** the graph plus the solved layout draws a dimensioned 3D preview at plan time.
6. **Studio:** the agent writes graphs for standard mechanisms; old projects are read with `adapt` where they came
   from the Office.
7. Old programs: read through `adapt.from_office` whenever a graph view is wanted; nothing is rewritten.

## 7. Limits today (honest)

* Step 2: the connection solver reads the graph, but part sizes it doesn't carry yet (a block's initial envelope, a
  cap's height) still come through `icd._initial` from the plan part, which the compile writes from the graph.
* The solver lays out shafts along +Y only (housings, pillow blocks, free shaft lines, shaft sub-assemblies); block
  layouts with no shafts, vertical shafts in a plate, a housing on a plate and 2-D trains use the template (said in
  the skeleton notes).
* Fastener sizes and housing envelopes are the layout's rules (`icd.py`), not the graph's.
* Only deep-groove ball bearings (60xx / 62xx) and external spur gears are sized; anything else is "other" and goes
  to the design agent as before.
* Standards tables typed from public references are marked "verify" (PD-13); nothing here claims manufacturing
  validity.
