# Design graph, architecture v2 step 1 (branch `wip/design-graph`, WORKLIST 43)

Founder: "Start and complete everything you said." AI at the edges (intent in, explanations out), determinism in the
middle; one typed design graph as the single source of truth for the Studio and the Office; the AI writes it through a
validated schema and asks 1 to 3 questions instead of guessing.

Design doc: `docs/architecture/design-graph.md`. Code: `src/aicad/graph/`. Tests: `tests/test_design_graph.py`.

## What was built

| Stage | What | Files |
|---|---|---|
| 1. Design doc | schema, mapping of planner plan / ICD + skeleton / direct builder / Fitz trains / Toolbox / scope check, AI vs code, Studio and Office, migration path, limits | `docs/architecture/design-graph.md` |
| 2. Schema and core | versioned pydantic models with per-value provenance; component registry (19 kinds) and connection registry (9 kinds: host, guests, via, implied features per side, placement rule, standards, ICD kinds); validation (17 stable codes) and repair; deterministic sizing (DIN 6885 key from the shaft, ISO 15 bearing from the journal, DIN 471 groove, a = m (z1 + z2) / 2, teeth from the ratio, output shaft from the ratio, shoulder, face width) | `graph/model.py`, `registry.py`, `validate.py`, `resolve.py`, `standards.py` |
| 3. Compilers | graph -> office plan (+ ICD overrides) -> ICD / skeleton via `icd.build` unchanged; cross-check graph vs ICD; layout limits; graph -> `direct.py` decisions and scripts; graph -> Fitz train items; layout read back; reverse adapter plan + ICD -> graph | `graph/compile.py`, `adapt.py` |
| 4. Intent compiler | one call, role `intent`, strict JSON schema, routed by job size (PD-82: simple -> Sonnet, complex -> Opus); provenance checked against the brief; exclusions hard (`office/scope.py`); repair; at most 3 questions in the fw-questions format, code's first, never about sizes; code answers its own questions (housing, bearings, material) with no second call; a named housing is completed by code | `graph/intent.py`, `questions.py` |
| 5. Golden cases | recorded replies (hand) + one live reply per case (replayed), graph -> plan -> ICD -> direct -> assembled, hand-checked | `tests/golden/design_graph/*.json`, `tests/test_design_graph.py` |
| 6. Wiring | `FW_DESIGN_GRAPH=1`: Archie's planning turn is intent -> graph -> plan; plan review shows the graph (parts with key sizes coloured by source, connections, notes, "not laid out yet") and the questions as clickable choices; approval waits for the answers; old planner stays the default | `graph/office.py`, `platform/routers/office.py` (flag hook + `POST /plan/answers`), `office/service.py` (approval guard), `office/interfaces.py` (ICD overrides), `web/.../office/DesignGraph.tsx`, `PlanReview.tsx`, `types.ts` |

Files touched outside the new package: `llm/base.py` (role `intent`), `llm/routing.py` (routes `intent`,
`intent.simple` = Sonnet), `office/interfaces.py` (3 lines), `office/service.py` (3 lines),
`platform/routers/office.py` (flag hook in `_plan_task`, one endpoint), `web/src/pages/app/office/PlanReview.tsx`
(two components and the approval guard), `types.ts`. `office/orchestrator.py`, `archie_chat.py` and
`visual_office.py` are untouched (the supervisor branch owns them).

## Golden cases: hand-checked numbers (`tests/test_design_graph.py`)

1. **"Build a Spur Gear mounted on stepped Shaft and locked with a key"**: 3 parts, one unit. Shaft Ø20 seat (assumed)
   / Ø26 step (20 + 2 max(2.5, 0.1 x 20 + 1)) x 80 (assumed); gear m2 x 30 (assumed), tip Ø64, face 20 (10 m), bore
   Ø20; key DIN 6885 6 x 6, t1 3.5, t2 2.8, length floor(max(8, 18)) = 18. Layout: shoulder face datum B (Y = 0),
   gear Y -20 .. 0, shaft Y -22 .. 58 (centre 18), key Y -19 .. -1 at (6.5, -10, 0). Cross-check empty, 0 ICD
   problems; both parts built with no AI ("shaft Ø20 / Ø26 × 80, 1 seat, 1 keyseat", "spur gear m2 × 30 teeth, face
   20, bore Ø20 with a keyway"). Office end to end (simulated agents): 5 tickets, one click, key at (6.5, -10, 0),
   nothing binned, 0 clashes, 22.4 s approve to assembled.
2. **1:3 pair m2 20 / 60, Ø20 shafts, four 6204, no housing**: a = 2 (20 + 60) / 2 = 80; gears at X 0 and 80;
   bearings 5 mm from the 20 wide gears: Y 15 .. 29 and -29 .. -15 on both shafts; shafts 10 mm beyond: 78 long. All
   four designed parts direct; Fitz items: 2 gears (Z 20, 60), 2 Toolbox shafts, 4 x 6204, accepted by
   `trains.select`. Office end to end: four bearings seated at (0, -29, 0), (0, 15, 0), (80, -29, 0), (80, 15, 0),
   gears 80 apart, 0 clashes, no placeholder left (23.6 s).
3. **"Build a Single stage 3:1 reducer with Spur Gears"** (housing): z1 = 20, z2 = round(3 x 20) = 60, m2 assumed,
   a = 80; input Ø20 (assumed) on 6204; output 20 x 3^(1/3) = 28.8 -> Ø30 on 6206; keys 6 x 6 x 18 and 8 x 7 x 18;
   four caps, open on +Y, blind on -Y; layout `gearbox`, 0 ICD problems, cross-check empty; shafts and gears direct,
   housing / cover / caps go to the designer (no generator yet, WORKLIST 45). Office end to end (two gates): four caps,
   both keys placed, nothing binned, shafts 80 apart, clash check done with 0 (32.3 s).

Plus: standards hand values, every validation code, exclusions as hard constraints (the founder's "Test 5" reply with
a support housing and bearings is cut back to shaft, gear and key), implied key and ring, reverse adapter round trip
on all three (same names, kinds, connections and numbers) and on two pre-graph plans (the 1:3 pair and the live
"Gear Reducer" plan: 5 bolted joints, 2 bearing seats, 2 keyed hubs, 6204 / 6205), routing per job, a bad answer
rejected by the schema (the office falls back), questions (housing / bearings / a model question kept, a size question
dropped, housing answered by code: base, cover, a seat per shaft, 4 caps, screws, bolts, gearbox layout), the flag off
keeps the old planner, approval refused until questions are answered.

Tests: `tests/test_design_graph.py` 32 passed (about 85 s with the three office runs). Neighbours, two files per run,
workers reaped: see "Gate" below.

## Comparison: old path vs graph path (live, one call per case and path)

Same brief, same deterministic scoring for both (`docs/reports/design-graph/live_intent.py`; raw results in
`docs/reports/design-graph/live/*.json`): parts by kind against what the case needs, exclusions, ICD problems of the
compiled layout, the mesh, and how many designed parts the direct builder takes (no AI design turn).

| Case | Path | Model | Plan time | Output tokens | Cost | Platform tokens | Correct at the gate | Designed parts built with no AI |
|---|---|---|---:|---:|---:|---:|---|---|
| Keyed gear | old (Archie) | Opus | 15.8 s | 1,159 | $0.047 | 5 | yes | 2 / 2 |
| | **graph** | Sonnet | **8.1 s** | 401 | $0.012 | **2** | yes | 2 / 2 |
| 1:3 pair | old | Opus | 20.0 s | 1,997 | $0.051 | 6 | yes | 2 / 4 (gears: "22 mm" and "web" in the text) |
| | **graph** | Sonnet | **8.0 s** | 783 | $0.010 | **1** | yes | **4 / 4** |
| Reducer | old | Opus | 33.8 s | 3,529 | $0.081 | 9 | **no**: 2 blocking ICD problems (cover 4.9 x its planned size; body unconnected), no bearing caps | 1 / 6 |
| | **graph** | Opus | **19.7 s** | 2,408 | $0.064 | **7** | yes (1 question: gear material, answered by code) | **4 / 10** (shafts, gears; housing, cover, caps need the designer) |

Totals: graph path 36 s and 10 platform tokens for the three plans, old path 70 s and 20 tokens; correctness 3 / 3
against 2 / 3; parts that skip the AI design turn 10 against 5. Live spend for this report: 30 platform tokens (six
calls), inside the 60 budgeted.

Why the old path loses parts to the AI: its descriptions carry sizes the interfaces don't explain ("Pinion 20T": "the
brief gives a size the interfaces don't explain (22 mm)"; "Wheel 60T": "a web or recess"; reducer shafts: "two
diameters asked for between Z -22.5 and -2.5"). The graph writes each description from its own numbers, so every
size is explained and the cross-check proves it.

Honest notes on the live runs:
* The first live reducer reply exposed a real compile bug: stepped shafts inside a housing were written in the
  shaft-sub-assembly phrasing the gearbox layout doesn't read, so the layout took Ø20 for the output shaft. The
  cross-check flagged all three mismatches (Ø20 vs Ø30 seat, 6 x 6 vs 8 x 7 key, 6204 vs 6206), which is what it is
  for. Fixed (plain Ø in a housing; the shoulder is reported as "not laid out yet" until step 2), and the same recorded
  reply was re-scored (`--rescore`, no new call); the table shows the re-scored result. It is a standing test
  (`test_live_intent_replies_replayed`).
* The live Sonnet replies for cases 1 and 2 gave the same graph a hand would write (the key was named "Gear key").
  That is the evidence for routing simple intents to Sonnet; one sample per case, so treat it as a first signal.
* Downstream of plan approval both paths run the same office, so office time after approval is the same per part;
  the graph path wins there only through the extra direct builds (each AI design turn is 30 to 90 s live).

## Screenshots (read; `docs/reports/design-graph/`)
- `1-keyed-gear-plan-review.png`: plan review with the Design card: 3 parts, 2 connections, "Layout matches"; sizes
  coloured by source (Ø20 and length 80 assumed, step Ø26 a design rule, key b 6 h 6 standard).
- `2-reducer-question.png`: the reducer: "Archie needs one answer before you approve" (gear material, 4 choices,
  default marked), Approve plan disabled with the reason.
- `3-reducer-answered.png`: after "Carbon steel (C45)": the gears show the material, 16 parts, 14 connections,
  "Not laid out yet" lists the two shoulders inside the housing.
Walkthrough: port 8807, throwaway data, `FW_DESIGN_GRAPH=1`, the intent role on the replay provider with the live
replies (no tokens), simulated office agents, puppeteer-core 24, 0 console / page errors (`graph_walk.mjs`). Fixed from
the shots: assumptions listed labels (role, style) as "assumed" sizes; fastener styles shown as code words
("hex_bolt"); material not shown.

## Gate
`uv run ruff check src tests` clean; `npx tsc --noEmit` clean; `npx vite build` ok; tests below.

## Parked decisions (default used)
- **PD-110 Graph path default.** `FW_DESIGN_GRAPH` stays off by default; Archie's free-text planner is the default
  path. Proposal: switch it on when the golden mechanism suite (WORKLIST 46) passes on the graph path; the evidence
  here (3 / 3 correct, half the time and tokens) says it is ready for the founder to try.
- **PD-111 Intent routing.** `intent.simple` (a short brief of a shaft and what rides on it) on Sonnet, everything
  else on Opus. Evidence: two live Sonnet runs gave the hand graph. Alternative: Opus everywhere (slower and dearer).
- **PD-112 Questions block approval.** Open questions must be answered (or "Take Archie's defaults") before the plan
  can be approved; code's questions are housing (shafts on bearings, housing neither named nor excluded), bearing
  series (bearings named without a designation) and material (only when the brief hints at a choice); the model may
  add its own (material questions are answered by code; size questions are dropped). Alternative: approve with the
  defaults and show the questions as notes.
- **PD-113 Output shaft sizing rule.** With no size in the brief, the output shaft of a reduction is the smallest
  bearing bore >= d_in x ratio^(1/3) (torsion scaling; 3:1 from Ø20 gives Ø30). A stated design rule, not a strength
  calculation; the engineer can edit the size at the ICD gate. Alternative: same Ø as the input.
- **PD-114 Housing completion.** A housing named in the graph is completed by code (cover, a seat per shaft bearing
  pair, an open and a blind cap per shaft, 16 M6 cap screws, 4 M8 cover bolts) where the reply lacks those parts; a
  bearing line shared by two shafts is split one pair per shaft. Alternative: ask.
- **PD-115 Graph plans are shown as Archie's.** A graph-made plan is labelled "Planned by Archie (AI)": the AI read
  the brief, code sized and laid it out; the Design card says which values came from where.

## Not done / next
- The Studio side of the shared graph (an agent writing graphs for standard mechanisms, `graph.json` per project) is
  designed (doc section 5), not built.
- The layout still reads plan text (step 2 makes it read the graph); shoulders and rings inside housings are listed as
  "not laid out yet".
- An engineer's edit of a graph plan at review changes the plan but not the stored graph; the reverse adapter can
  re-derive it from the approved ICD (`adapt.from_office`), not wired into the approval yet.
- Entry point wanted from the master: none required; the flag is server-side (`FW_DESIGN_GRAPH=1`).
