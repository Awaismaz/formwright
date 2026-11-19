# Pipeline speed (PS-01..PS-05): faster part modelling for the design agent

Branch `wip/pipeline-speed`. Founder ask: "make the part modelling and assembly substantially faster".

## Summary

The agent's `build_model` call used to run everything on the critical path: build, checks, topology, STEP export,
STEP re-import (CHK-07), a second full rebuild (CHK-08), STL/GLB/3MF, then a render of the 0.01 mm STL. On the
agent's own 125-line gear script that was **~54 s per build**. Now:

1. **PS-01 Deferred verification.** The report returns after build + CHK-02..05 + topology + a render of the viewer
   mesh (**~12 s** on that script under load, **0.5 s** for a plate, **2.6 s** for the same gear built with the new
   helper). Exports, CHK-07 and CHK-08 run in the background on the same warm worker, and the turn's verdict waits
   for them.
2. **PS-02 Cheaper steps.** Topology export 2-6x faster with output identical by value, `is_valid` run once instead
   of twice, wrapper-free fingerprint counts, a plane `face_key` without surface integrals, a cheaper module purge
   after each script, and the render reads a light preview mesh (0.4 s instead of 12 s).
3. **PS-03 Short scripts.** `fw.spur_gear`, `fw.stepped_shaft`, `fw.shaft_keyway`, `fw.hole` / `holes_at` /
   `bolt_circle`, `fw.din6885`, with EXPECTED values from hand formulas. The prompt tells the agent to prefer them. The
   gear becomes about 15 lines and 248 faces instead of 125 lines and 2048 faces.
4. **PS-04 Start-up.** The agent process is started when the Studio opens a project, and dropped if nobody uses it
   within 10 minutes. A compact system prompt is available behind `FW_AGENT_SYSTEM_PROMPT=compact`. It was measured
   and **parked**: the default is unchanged.
5. **PS-05 Assembly checks.** Findings only (see below). No code changes there, so this branch does not collide with
   `wip/fitz-trains` or `wip/asm-visual`.

## PS-01: what "verified" means now (semantics)

- An agent build is a fast build (`runner.main(fast=True, determinism=True)`). The result has `CHK-07` and `CHK-08`
  marked `pending` (non-gating placeholders), `exports_pending: true`, `pending_checks: ["CHK-07","CHK-08"]` and
  `verified: false`. `ok` means only that the gating checks run so far passed.
- `runner.is_verified(status)` is the single test for "verified": `ok`, no error, nothing pending. Old status files
  without the new keys are judged on `ok` and `exports_pending`.
- Background chain (`agent/deferred.py`, `DeferredChecks`) on the same worker:
  - `finalize(stage="exports")`: STEP/STL/GLB/3MF + CHK-07.
  - `finalize(stage="determinism")`: CHK-08. This re-runs **the source text that was built**, so the agent editing
    the file meanwhile cannot fake or break it. The fingerprint and STEP bytes are compared as before.
  - `status.json` is merged in place and keeps its `build_id`, so the viewer does not reload.
- A newer build supersedes the chain. A step that hasn't started yet is cancelled. If a stale status reaches
  `finalize`, it returns 3 and writes nothing.
- If the previous build's deferred check failed, the failure is prepended to the next report ("BACKGROUND CHECKS
  ON YOUR PREVIOUS BUILD FAILED").
- End of turn (`AgentSession.send`):
  - The `ResultMessage` is held until `deferred.settle()` has finished. If that takes a moment, the chat shows a
    "Finishing verification" step.
  - The result event carries `build_verified`.
  - If a deferred check failed, the agent gets **one** automatic follow-up ("[Background verification] ...") in the
    same turn. The turn still produces one result, and its cost comes from the cumulative report, so it is charged
    once.
  - A self-review written while checks were pending is reconciled against the settled status before it is shown.
- `settle()` never raises:
  - If the worker lost the shape (recycled or crashed), it runs `finalize`. If that returns 2 while checks are still
    pending, it rebuilds the part in full.
  - The worker is never recycled right before a `finalize` request.
- Consumers:
  - The projects router judges the turn on the settled `status.json` (`runner.is_verified`). It refreshes
    `p.last_status`.
  - Revision snapshots no longer copy the previous build's stale `part.step`; STEP and status are added when the
    background work finishes.
  - `wait_finalized(project_id)` (modules reading `part.step`) waits for the exports. `wait_finalized(..., full=True)`
    (release `issue()`) waits for every check.
  - The handoff gate (`handoff._verified`) blocks with "still being verified" while checks are pending.
  - Studio: the checks panel shows "Checks so far pass · finishing verification…", CHK-08 shows "Being verified in
    the background…", and `status.json` is polled every 2.5 s while anything is pending.
- Interactive edits (parameters, manual features, restore) keep their semantics: CHK-07 deferred, CHK-08 skipped.
- `docs/VALIDATION.md` now describes when CHK-07/08 run.

Determinism runs eagerly after each agent build rather than only on the last one. The agent's thinking time between
builds (10-60 s) normally hides it, and a newer build cancels it if it hasn't started. Running it only at the end of
the turn would add its full cost (2-8 s) to every turn's end.

## Measurements

Same machine, same scripts, one warm process per run (as in the worker). The old code is `main@719c329` (extracted to
scratch, run with `PYTHONPATH`); the new code is this branch. The machine was shared with about 5 other agents
(CPU 45-100 %), so each cell is the median of the runs listed, and old and new runs were interleaved.
"Critical" is what the agent waits for: old = full build with determinism + render of `part.stl`; new = fast
build + render of `preview.stl`. "Background" is the deferred exports, CHK-07 and CHK-08.

| Script | Faces | Old critical (s) | New critical (s) | New background (s) | Verdicts |
|---|---:|---:|---:|---:|---|
| Agent's own gear (125 lines, polygon teeth) | 2048 | RESULTS_GEAR_OLD | RESULTS_GEAR_NEW | RESULTS_GEAR_BG | identical (CHK-02..05, 07, 08 pass) |
| Plate with holes, pocket, fillets | 19 | RESULTS_PLATE_OLD | RESULTS_PLATE_NEW | RESULTS_PLATE_BG | identical |
| Same gear via `fw.spur_gear` (15 lines) | 248 | n/a (helper is new) | RESULTS_FW_NEW | RESULTS_FW_BG | all pass; CHK-05 rel. error 1.3e-7 |

The new code's stage timings for the 2048-face gear (`status.timings_s`, one run, loaded machine):

| Stage | Before | After | Change |
|---|---:|---:|---|
| build | 9.8 | 4.2 | module purge |
| checks | 3.1 | 2.2 | one `is_valid` |
| topology | 3.2-5.8 | 2.1 | whole-shape mesh, no wrappers |
| render | 11.9 (part.stl) | 0.37 (preview) | |
| exports + CHK-07 | 23.3 | 18.1 | background |
| CHK-08 | 8.1 | 7.9 | background |

Topology export alone, old vs new (`topocmp.py`; every output compared **by value**, meshes included): agent gear
31.1 s → 7.7 s (loaded), toolbox spur gear 11.0 s → 1.9 s, bearing 2.4 s → 1.2 s, small parts 2-4x faster.

Probes that showed nothing to gain:
- CHK-07 re-import: a plain `STEPControl_Reader` takes the same time as build123d's XCAF `import_step` (10.2/10.4 s
  and 10.5/10.5 s, alternating). Turning shape healing off changes nothing either. The time is in the OCCT 8 transfer
  itself, so CHK-07 is now in the background instead. The reader was left unchanged.
- One shared tessellation: STL, GLB and 3MF already reuse the triangulation the STL pass stores on the shape (3MF
  writing takes 0.06 s).

### Live run (same prompt as the master's baseline, default model and system prompt)

Prompt: "Design a spur gear: module 2, 60 teeth, 20 degree pressure angle, face width 20 mm, bore 20 mm H7 with a
DIN 6885 keyway, hub OD 40 x 30 long on one side. Steel C45."

| | Before (master, idle-ish) | After (this branch, loaded machine) |
|---|---:|---|
| Total | 145 s | LIVE_TOTAL |
| Script written | 125 lines (hand involute), ~61 s to write | LIVE_SCRIPT |
| build_model tool | 58 s | LIVE_BUILD |
| End of turn | ~11 s | LIVE_END |
| Cost | ~305 tokens (cold) | LIVE_COST |
| Verdict | verified | LIVE_VERDICT |

### PS-04: start-up probe (trivial prompt, the same options as the session)

| System prompt | Run | Connect (s) | First message (s) | Cache create (tok) | Cache read (tok) | Cost (USD) |
|---|---|---:|---:|---:|---:|---:|
| claude_code preset + CAD instructions | 1 | 4.9 | 3.3 | 14,996 | 0 | 0.120 |
| | 2 (other folder) | 2.0 | 2.6 | 10,215 | 4,783 | 0.083 |
| compact base + same CAD instructions | 1 | 20.9 (load spike) | 3.7 | 12,778 | 0 | 0.102 |
| | 2 (other folder) | 1.2 | 3.4 | 387 | 12,389 | 0.006 |

- Latency: no measurable difference in time to first message.
- Size: the preset adds about 2.2k tokens.
- Caching: the preset's text depends on the working folder, so its prompt cache breaks after about 4.8k tokens for
  every new project. The compact prompt caches across projects, so the first turn of a new project costs about
  $0.08 less in system-prompt tokens.
- Behaviour: the compact prompt has not been run through an eval yet. It stays opt-in (PD below).
- Pre-connecting saves the connect time (1-5 s) on the first message of a project.

## PS-05: assembly checks (findings, no change)

- `assembly/geometry.py` already screens pairs exactly (instance boxes, then solid boxes, then the declared
  envelope) before any boolean. `pairs.py` caches pair results on disk per part snapshot (ASM-023).
- What remains is the exact `BRepAlgoAPI_Common` on pairs whose boxes overlap. Meshing gears always overlap in their
  boxes. Its cost scales with face count, so the biggest assembly win from this branch is indirect: helper-built
  gears have about 8x fewer faces than hand-written polygon gears.
- Self-contained follow-ups for the assembly owners:
  1. `op.SetRunParallel(True)` on `BRepAlgoAPI_Common` in `_common` (OCCT runs the boolean on several threads).
  2. Cache the world shapes that `_world()` imports with `import_step` across checks of one session (each check
     re-imports every STEP: about 10 s for a 2048-face part).
  3. Try `SetFuzzyValue` for near-touching faces.

  None of these were measured here, to stay out of `wip/fitz-trains` and `wip/asm-visual`.

## Files

- New: `src/aicad/agent/deferred.py`, `src/aicad/fw_std.py`, `tests/test_pipeline_speed.py` (15 tests),
  `tests/test_fw_std.py` (7 tests).
- Changed:
  - `agent/runner.py`: fast/deferred mode, `recompute_ok`, `is_verified`, staged `finalize`, `_exec(source=)`, module
    purge, stage timings.
  - `agent/tools.py`: `build_handler`, fast build + preview render + background chain, PENDING lines in the report.
  - `agent/worker.py`: finalize stage; no recycle before a finalize.
  - `agent/session.py`: held result + settle + one follow-up, held self-review, `preconnect`, compact prompt option,
    scrub of the helper names.
  - `agent/prompt.py`: standard-features section; workflow step 3 explains the PENDING checks.
  - `topo.py`: one parallel mesh, wrapper-free loop, `write_preview_stl`.
  - `checks.py`: wrapper-free counts; reuse of the volume and fingerprint already computed.
  - `fw.py`: `plane_eq`; re-exports the helpers.
  - `handoff.py`: verified = `is_verified`.
  - `platform/routers/projects.py`: settled verdict, revision completion, `wait_finalized(full=)`.
  - `platform/routers/studio.py`: `/warm` pre-connects the agent.
  - `platform/routers/handoff.py`: release waits for all checks.
  - `web/.../ProjectStudio.tsx`: polls status while checks are pending.
  - `web/.../studio/Panels.tsx`: pending verdict and CHK-08 text.
  - `web/src/lib/types.ts`: new status fields.
  - `docs/VALIDATION.md`, skills `design-agent` and `build123d-kernel`.

## Tests

- `tests/test_pipeline_speed.py` covers:
  - A fast agent build is not verified until CHK-07 and then CHK-08 have run. It reaches the same verdicts and the
    same STEP bytes as the old all-in-one build.
  - A non-repeatable script (`random`) passes CHK-02..05 but fails the deferred CHK-08, and is never verified.
  - The deferred CHK-08 re-runs the built source even if the file was edited meanwhile.
  - A superseded finalize writes nothing.
  - Interactive edits keep their semantics.
  - The build tool returns before the exports, and its background chain completes. A failure reaches the next
    report.
  - `settle()` rebuilds when the worker lost the shape.
  - **A turn's result waits for the deferred checks.**
  - **A failed deferred check gets exactly one follow-up and the turn is never reported verified.**
  - A fixed follow-up ends verified.
  - The preview mesh area matches a hand calculation.
  - Pre-connect is reused by the first message and dropped when idle.
- `tests/test_fw_std.py` checks:
  - Gear volume against the exact involute integral (rel. 1e-5), bbox, face count, pitch/root/base diameters.
  - Helical twist and its volume.
  - Input validation.
  - Stepped shaft against a hand calculation, and with chamfers and fillets by Pappus.
  - Keyway removed volume.
  - ISO 273 clearance, tapped holes with threads, counterbore volume by hand.
  - Scrubbing of the helper names.
- Neighbour suites: `RESULTS_TESTS`.

## Parked decisions (defaults used)

- **PD-73: compact system prompt as the default.** Default: unchanged (`claude_code` preset), compact opt-in via
  `FW_AGENT_SYSTEM_PROMPT=compact`. Switch after one EVAL-003 benchmark shows no quality loss. The gain is prompt
  caching across projects (about $0.08 per new project's first turn), not latency.
- **PD-74: model routing for small edits.** Not implemented. Default: the configured model for everything. Script
  writing dominates a turn, but a faster model writes worse CAD. Revisit with EVAL-003 numbers, behind the
  `design_agent` provider configuration.
- **PD-75: one automatic follow-up when a deferred check fails.** Default: 1 per turn (it costs tokens; 0 would leave
  a turn ending unverified with the failure only shown in the next turn).
- **PD-76: pre-connected agent process idle timeout.** Default: 10 min. Each open Studio tab with agent rights holds one
  Claude Code process (~150-300 MB) until then.

## Known limits

- The deferred chain shares the worker. A build requested while the previous build's CHK-08 is mid-run waits for it
  (up to about 8 s on the 2048-face gear, about 2 s on the helper gear).
- The render now uses the viewer mesh (coarser than the 0.01 mm STL). It looks the same at 1400x1050. Exported files
  are unchanged.
- `fw.spur_gear` has no root fillet (trochoid) and no profile shift, and does not model undercut below 17 teeth. The
  docstring says so.
- The DIN 6885 hub depths (t2) are standard table values marked "verify" in `fw_std.DIN6885`.
- No browser walkthrough was run. The UI changes are two strings, a colour and a polling interval (tsc clean).
