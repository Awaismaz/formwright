# Agent latency and model routing (branch `wip/agent-latency`)

Founder asks:
- "For these parts you completely eliminated AI. But what about the parts where AI is involved and we still want to
  make the process faster?"
- PD-82 (2026-11-19): "For smaller jobs, you can even use Sonnet or even Haiku, while major orchestration to be done
  by Opus. This will not only optimize speed, but also reduce cost."

Goal: make AI-designed parts substantially faster and cheaper, in the Studio and in Design Office tickets, without
making the CAD worse.

## Result in one table

Five fixed benchmark turns (`aicad latency`, below). Wall = send to settled verdict (CHK-07/08 included). Pass = every
gating check incl. CHK-07/08 **and** the case's analytic expectation (bbox, volume, cylinder census).

| | Wall, 5 turns | Output tokens | Cost | Pass |
|---|---:|---:|---:|---:|
| Before (main, Opus, default effort) | 204.3 s | 19,996 | $0.866 | 5/5 |
| After, Opus (all latency changes, Opus forced) | 158.8 s (-22 %) | 10,368 (-48 %) | $0.670 (-23 %) | 5/5 |
| **After, routed (PD-82 default: Sonnet for these jobs)** | **95.5 s (-53 %)** | **10,870 (-46 %)** | **$0.349 (-60 %)** | **5/5** |
| Haiku (2 cases only, for information) | slower than Sonnet | 2-3x Sonnet's | about 1/10 of Sonnet | 2/2 |

The same parts come out: on BRK, MMP, EDT and THR every tier built the identical solid (volume equal to 0.1 mm³,
same face count). On the office shaft the agent's finish choices differ slightly (Opus 46,348 mm³ / 23 faces, Sonnet
46,282 mm³ / 21 faces); both pass the ICD-driven expectation and every gate.

**Disclosure (a harness slip, corrected).** A PowerShell edit re-encoded `latency.py` mid-session, so the "After, Opus"
run and the first Sonnet run of BRK, MMP, EDT and THR received the prompts with `×`, `Ø`, `±` and `°` turned into
two-character garbage (for example `90 Ã— 90`). Both tiers saw the same text and still built the exact parts, so the
tier comparison of that run is like for like. The file was repaired and Sonnet re-run on the clean prompts (BRK 21.4 s,
MMP 18.8 s, EDT 12.4 s, THR 12.9 s, all pass, identical solids); the Sonnet column and the totals use the clean runs.
The "After, Opus" column for those four cases was not re-run (about 45 more tokens); OFF reads its prompt from a text
file and was never affected.

## Benchmark (`src/aicad/eval/latency.py`, `aicad latency`)

| Case | What | Job size (PD-82) |
|---|---|---|
| OFF | Design Office ticket: the founder's pinion shaft (ICD-driven turned part), the verbatim office prompt (3.6k chars) | simple (shaft, program of 4 parts) |
| BRK | gusseted L-bracket, fully dimensioned (holes in both legs, two gussets) | simple |
| MMP | NEMA 23 motor plate: pilot bore, M5 pattern, M6 counterbored corners, R5 corners | simple |
| EDT | edit of an existing base plate: six holes become M8 counterbored holes | edit |
| THR | turned pivot pin with a cosmetic M16x1.5 thread and a cross hole | simple |

- Every expectation is a hand formula (the cross hole by the integral of the hole's chord times the bar's chord).
- `aicad latency --dry` replays a reference solution per case and passes 5/5, so the expectations and the harness agree
  before any token is spent.
- The session is pre-connected and the worker warmed before the clock starts, as the Studio does on project open and
  the Office at ICD approval. Metrics come from the AGT-009 run record (`calls[]`, `cost_breakdown`, the new `turn`
  block).
- Single samples on a shared, loaded machine: treat differences under about 5 s as noise.

### Per case and tier

| Case | Before (Opus) | After, Opus | Sonnet ² | Haiku |
|---|---|---|---|---|
| OFF wall / out tok / $ | 61.3 s / 5,617 / 0.214 ¹ | 66.3 s / 3,696 / 0.202 | **30.0 s / 3,724 / 0.098** | |
| BRK | 45.5 s / 4,087 / 0.185 | 45.2 s / 2,199 / 0.128 ³ | **21.4 s / 2,393 / 0.078** | |
| MMP | 29.7 s / 3,634 / 0.156 | 18.7 s / 1,905 / 0.120 ³ | **18.8 s / 2,087 / 0.065** | 34.9 s / 6,918 / 0.008 ³ |
| EDT | 21.7 s / 2,163 / 0.129 | 12.4 s / 1,131 / 0.104 ³ | **12.4 s / 1,137 / 0.052** | 16.5 s / 3,455 / 0.004 ³ |
| THR | 46.1 s / 4,495 / 0.181 | 16.2 s / 1,437 / 0.115 ³ | **12.9 s / 1,529 / 0.055** | |
| Model calls (OFF, BRK, MMP, EDT, THR) | 2, 3, 2, 4, 3 | 3, 2, 2, 2, 3 | 2, 2, 3, 2, 2 | 3 (MMP), 2 (EDT) |
| Rebuilds in the turn | BRK (gusset direction), THR (built before the file existed) | OFF, THR (one each) | MMP (an edit excerpt, NOT BUILT, 0.1 s) | MMP |
| Reply length (chars) | 1,200 to 2,140 | 430 to 1,355 | 400 to 910 | 440 to 880 |
| Pass | 5/5 | 5/5 | 5/5 | 2/2 |

¹ OFF "before" is the agent-cost run of the identical prompt on main (same code path), reused to save 21 tokens.
² Earlier Sonnet runs, all passing with identical solids: with the mis-encoded prompts BRK 22.5 s, MMP 18.9 s,
EDT 42.4 s, THR 92.6 s (EDT and THR overlapped a pytest run: builds of 28 s and 64 s instead of under 5 s), then
EDT 13.8 s and THR 17.4 s re-run. The table uses the clean-prompt run.
³ Prompts with mis-encoded symbols (see the disclosure above).

"First response" (run record `first_response`) is in the JSON rows but is not comparable before/after: with a short
plan the first assistant block is now the script itself, so it moved later while the turn got shorter.

## What changed

1. **Fewer output tokens.**
   - The final reply is 1-3 sentences: no restated dimensions, parameters or check results (the app shows them). The
     self-review keeps at most 3 findings per list. Replies went from about 2,000 to about 500 characters.
   - **Adaptive effort** (`agent/speed.py` `choose_effort`): `low` for edits and fully dimensioned simple parts, the
     default otherwise. It is switched on the live agent process per turn by a control request (`apply_flag_settings`
     `effortLevel`; free, no reconnect; verified with `get_settings`). `FW_AGENT_EFFORT` still forces one level;
     `FW_AGENT_ADAPTIVE_EFFORT=0` turns it off.
   - **Compact scripts**: `fw.plate`, `fw.gusset` (avoids the extrude-direction pitfall that cost BRK a rebuild before),
     `fw.cross_hole` (+ `cross_hole_volume`, exact integral), custom counterbore / countersink as a hole spec dict
     (`{"d": 6.6, "cbore": (11, 6.5)}`), and `fw.meta(...)` for PARAM_META (the longest part of every script). Each one
     has a hand formula test (`tests/test_agent_latency.py`).
2. **Fewer round trips.**
   - Every turn gets a hidden `[Project folder: ...]` line: no design yet (write and build now), or the design's line
     count and last verdict. When the agent hasn't seen the current version (new conversation, a parameter edit, a
     manual feature, a seed), its text is inlined. The sha is kept in `.fw/agent.json` `design_seen`.
   - `build_model` now takes `source` (whole script) or `edits` (exact old/new pairs, unique, all or nothing): write and
     build in one call. EDT went from 4 calls (Read, Write the whole file, build, reply) to 2 (edit+build, reply);
     THR no longer calls the build before the file exists.
   - The render stays in the build result (the agent still judges the part visually); the prompt tells it not to open
     image files or rebuild once the gate passes and the render matches.
3. **Start from something (Design Office seed, first live run).** The interfaces fix the input shaft, the brief adds an
   M12 thread. The direct model was built (3.8 s, verified), then the agent (routed to Sonnet: simple, 4-part program)
   was given it inline and added only the thread: 16.9 s, 3 calls, 1,578 output tokens, $0.066. It kept `LENGTH` / `D`
   and the ICD features, recorded M12x1.75-6g, every gate passed and **ICD conformance passed**. One wrinkle: its first
   `edits` call had an excerpt that didn't match uniquely, so it got "NOT BUILT" and resent (0.06 s, one extra call).
   Nothing in `office/direct.py` needed fixing.
4. **Model routing by job size (PD-82, implemented).**
   - `src/aicad/llm/routing.py`: role (and job size for the design agent) to tier; `llm.complete` fills the routed model
     for every single call that doesn't name one.
   - Job size (`speed.job_of`, deterministic): `edit` (a local change to an existing design), `simple` (fully
     dimensioned, simple part family, at most 8 kinds of feature; office tickets of programs up to 6 designed parts),
     else `complex` (open requests, gears, housings, mechanisms, sheet metal, imported parts, reference images, many
     features, big programs). The office passes the program size (`env.design(..., job=)`).
   - Defaults (`DEFAULT_ROUTES`), with the evidence rule "a cheaper tier only where it matched Opus's pass rate here":

     | Route | Tier | Why |
     |---|---|---|
     | design_agent.complex | Opus | novel or complex geometry (not covered by a cheaper-tier benchmark) |
     | design_agent.simple | **Sonnet** | 4/4 simple cases + office ticket pass, same geometry, 2x faster on cold office turns, half the cost |
     | design_agent.edit | **Sonnet** | edit case passes, identical part, half the cost |
     | planner, change_review, office_chat, reconcile | Opus | orchestration and intent (founder) |
     | vision, render_refine, draft_assist | Opus | not benchmarked here |
     | reviewer (Gage's AI note) | Opus, parked | the note can send a part back (costs a design turn); no Haiku benchmark yet |
     | librarian (parts-list parsing) | Opus, parked | no Haiku benchmark yet |
     | assembly_check | Haiku | already Haiku (PD-73, measured) |

   - Configurable per role and job in the platform config: `FW_LLM_MODELS="design_agent.simple=opus,reviewer=haiku"`
     (tier names, a `claude-` id, or `default`). An explicitly requested session model wins. The model is switched per
     turn on the live process (`set_model`), recorded in the run record's `turn` block, never shown in the UI.
   - Hex fallbacks and classification: there is no model call in Hex matching today (it is deterministic), so nothing
     to route.
   - **Haiku for design: not used.** It passed both cases, but it thinks 2-3x longer, so it is slower than Sonnet and
     needed a rebuild on MMP. It costs about a tenth. Kept for single calls.
5. **Design Office parallelism.** A build worker pool per organisation with project affinity
   (`worker.worker_for`, `FW_BUILD_WORKERS_PER_ORG`, bounded by `MAX_LIVE` and CPU / 3). Every request of a project
   (build, render, CHK-07/08 finalize, dims) goes to the worker that holds its shape. New projects go to the least busy
   worker. The office warms the whole pool at ICD approval and Run.
   - Measured on the 4-part direct program: pool 1: 24.2 / 25.3 s; pool 2: 25.9 / 25.6 s; pool 3: 27.1 s. **No gain**:
     a direct build is about 2 s now, and an extra cold worker costs more than it saves on this machine.
   - Default left at 1 (unchanged) and parked. The founder's PC limits warm workers, so an extra process per
     organisation is a real cost.
   - Pre-warming the agent session at ICD approval: not done. Ticket projects don't exist until their design stage,
     and connect is 1-2 s against 15-60 s turns.

## What did not help / not done
- Worker pool: no measurable gain (above).
- Design-memory "similar part as a starting point" (DS-040): not done. The inlined design plus the helpers already make
  edits two calls; a similarity seed for new parts needs its own benchmark (parked below).
- Effort switching mid-conversation can rewrite the prompt cache when it flips between turns (CLI note); measured
  turns were single-turn, so this cost is not in the numbers. Same for a model switch (caches are per model): an
  Opus build followed by a Sonnet edit re-writes about 20k tokens of cache (about $0.05 at Sonnet rates).

## Live spend (founder's subscription, dev login)
Before 65.2 + after/Opus 67.0 + Sonnet 34.2 + Sonnet re-run 11.5 + Haiku 1.2 + seed 6.6 + Sonnet clean-prompt
re-run 25.1 = **about 211 platform tokens** (budget 250). The `get_settings` / `apply_flag_settings` probes are control requests (free).

## Tests (no model calls)
- `tests/test_agent_latency.py` (10):
  - helpers against hand formulas (plate, gusset flush and volume, cross hole vs an independent midpoint sum, custom
    counterbore);
  - `fw.meta`, scrub of the new helper names;
  - `build_model` source/edits (unique, all or nothing);
  - folder note new / inlined / unchanged / too long;
  - classification and effort; job size and routes; config overrides and validation;
  - session per-turn effort + model switching with a fake client (control requests, chat shows the user's words only,
    `design_seen` persisted);
  - single calls get their routed model;
  - the worker pool's affinity.
- Green, two files per run: `test_agent`, `test_agent_cost`, `test_pipeline_speed` (one assertion now strips the
  folder note), `test_run_record`, `test_fw_std`, `test_ai_quality`, `test_llm_providers`, `test_office_orchestrator`,
  `test_office_direct`, `test_repeat`, `test_platform`. `ruff` clean. No web changes.

## Parked decisions (the master numbers them)
- **PD (routing defaults, PD-82 follow-up):** design_agent.simple and .edit on Sonnet by default, complex on Opus.
  Default used: as measured (5/5 on Sonnet, same parts, -60 % cost, -53 % wall). Revisit if the EVAL-003 golden suite
  shows a gap on a family.
- **PD (Gage's AI note and the librarian on Haiku):** the founder's split says Haiku. Default used: Opus until a review
  benchmark shows the same send-back decisions (a spurious send-back costs a design turn). One line of config turns it on:
  `FW_LLM_MODELS=reviewer=haiku,librarian=haiku`.
- **PD (adaptive effort on by default):** `low` for edits and fully dimensioned simple parts. Default used: on (no pass
  rate change across 5 cases x 2 tiers).
- **PD (build worker pool size):** default 1 (no gain measured); `FW_BUILD_WORKERS_PER_ORG=2` for a bigger machine.
- **PD (design text in the prompt):** the current design (up to 260 lines) is inlined when the agent hasn't seen it.
  Default used: on. It adds 1-3k input tokens to such turns and saves a model call.
- **PD (similar-part seed from design memory):** not built; needs a benchmark of new parts with a related sibling.

## Files
- New:
  - `src/aicad/agent/speed.py`
  - `src/aicad/llm/routing.py`
  - `src/aicad/eval/latency.py`, `src/aicad/eval/latency_office_shaft.txt`
  - `tests/test_agent_latency.py`
  - this report
- Changed:
  - `agent/session.py` (folder note, per-turn effort and model, `design_seen`, `job_hint`, scrub entries);
    `agent/tools.py` (source / edits); `agent/prompt.py` ("Work fast", short reply, helpers); `agent/replay.py`
    (recording client forwards control requests); `agent/worker.py` (pool)
  - `fw_std.py` (helpers), `fw.py` (one import list)
  - `llm/__init__.py` (routed model in `complete`, `describe`), `platform/config.py` (`llm_models`)
  - `office/orchestrator.py` / `office/platform_env.py` (program size hint; warm the pool)
  - `cli.py` (`aicad latency`), `tests/test_pipeline_speed.py` (one assertion), skill `design-agent`
