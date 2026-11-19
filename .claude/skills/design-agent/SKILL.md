---
name: design-agent
description: Change the in-app Formwright design agent (Claude Agent SDK) safely: its instructions, the model-script contract, build_model tool, tool allow-list and path/web guard, user-facing progress wording and scrubbing, fenced fw-questions / fw-recognition blocks, metering, and auth. Use for any edit to src/aicad/agent/* or to how the Studio chat behaves, and when planning the agent eval/benchmark (EVAL-003) or API-key auth (AGT-015).
---

# Changing the design agent

The product's promise is "Claude Code-level agentic power, in plain engineering language". Each layer below has a
contract with the others. Change them together.

| Layer | File | Contract |
|---|---|---|
| Instructions | `src/aicad/agent/prompt.py` (`CAD_AGENT_INSTRUCTIONS`, appended to the `claude_code` preset) | workflow, model-script contract, honesty and talk rules |
| Session | `src/aicad/agent/session.py` | `BUILTIN_TOOLS` + `CAD_TOOLS` allow-list, `permission_mode="dontAsk"`, `setting_sources=[]` (isolated from any developer `.claude`, including this repo's skills), PreToolUse `make_guard` (paths inside workspace; WebFetch only `build123d.readthedocs.io`), `MAX_TURNS=80`, resume by `session_id` |
| UI wording | `session.py` `friendly_step`, `friendly_result`, `_SCRUB`, `scrub()` | no file names, tools, code, Python, library or model ids reach the UI (DS-014, CLAUDE.md rule) |
| Structured blocks | `extract_questions` (`fw-questions`), `extract_recognition` (`fw-recognition`), `agent/blocks.py` `extract_brief` (`fw-brief`, CAD-028) and `extract_review` (`fw-review`, AGT-006: reconciled with `out/status.json`, can never pass a failed gate) | JSON in a fenced block; the block is stripped from the visible text and rendered as chips, tree data, the brief card or the Self-review panel |
| PropertyManager edits | `agent/edits.py` `extract_edit` (`fw-edit`, DS-035): small edits (fillet / chamfer / shell / hole / an existing hand-made feature / extrude depth / pattern count-spacing / parameters; `edits: [...]` = several, one PM step each, impact previewed as a `sequence`) resolved on `out/topo.json` and validated by `studio.validate_feature`; `design_state` adds a one-line `[Design state for quick edits: ...]` to short build prompts (never shown) | the session publishes `{"type": "edit"}`; the Studio opens the real PM pre-filled (`studio/agentEdit.ts`), the user presses OK; the agent writes no code |
| Provider | `src/aicad/llm/` (AGT-001): `AgentSession.client_factory` defaults to `session.provider_client` = `llm.get_provider("design_agent").agent_client(options)`; single calls elsewhere use `llm.complete(CallRequest(role=...))` | the session vocabulary stays the Agent SDK message dataclasses; providers `claude-sdk` (default, unchanged behaviour incl. replay/record env), `anthropic-api` (no sessions), `stub`, `replay`; `FW_LLM_PROVIDERS` routes roles; the run record stores `provider` |
| Replay | `agent/replay.py` (`ReplayClient`, `RecordingClient`, `FW_AGENT_REPLAY` / `FW_AGENT_RECORD`, `AgentSession.client_factory`) | tests and demos replay recorded turns with zero model calls |
| Build tool | `src/aicad/agent/tools.py` → `runner.py` via the warm `worker.py` | returns the "Overall gating checks: PASS/FAIL" text plus the 4-view render; `friendly_result` keys on that prefix |
| Deferred checks (PS-01) | `tools.build_handler` → `runner.main(fast=True, determinism=True)`; `agent/deferred.py` `DeferredChecks` | the report comes back in seconds with CHK-07/08 `[PENDING]`; exports + CHK-07 + CHK-08 run in the background on the same worker; a newer build supersedes them; failures are prepended to the next report; `AgentSession.send` holds the `ResultMessage` until `settle()` and gives ONE automatic follow-up on a failure; the verdict is `runner.is_verified(status)` (never `ok` alone) |
| Standard features (PS-03) | `src/aicad/fw_std.py`, re-exported by `fw` | `fw.spur_gear`, `stepped_shaft`, `shaft_keyway`, `hole`/`holes_at`/`bolt_circle`, `din6885` return EXPECTED parts from hand formulas; the prompt tells the agent to prefer them (a hand-written involute cost ~60 s of output and 2048 faces) |
| Editable params | `runner.editable_params` / `param_meta` | only top-level `NAME = <number>` lines declared in `PARAMS`; PARAM_META limits enforced server-side |

## Rules when editing
- If you rename a check string, tool name or block tag, update `friendly_result`, the extractors and `Chat.tsx`
  in the same change.
- Every new identifier the agent might echo (helper names, file names, variable conventions) gets a `_SCRUB` entry.
  Add a test asserting the scrubbed output.
- Never widen the tool allow-list or the guard without parking a PD row. No Bash for the in-app agent: model
  scripts run unsandboxed behind a tripwire (PD-10 / R-SEC-05).
- Honesty rules in the prompt are product requirements: never "validated", "safe" or "ready for manufacture". Keep
  requirement / assumption / measured / observed / inferred distinct, and cite or flag every material value.
- Prompt changes alter behaviour that unit tests can't see. Record the reason in the session log. Before the
  EVAL-003 benchmark exists, do one live run of a representative prompt (see `studio-e2e`). It spends the founder's
  Claude subscription, so keep runs few and log them.

## Model providers (AGT-001 / AGT-013)
- Never call `claude_agent_sdk.query`, `ClaudeSDKClient`, `anthropic` or `openai` outside `src/aicad/llm/` (and
  `agent/replay.py`, `airender/provider.py` for images): `test_no_module_calls_a_model_sdk_directly` fails.
- A new model call = a new role in `llm/base.py` `ROLES` + a thin wrapper function the tests can monkeypatch; it gets
  metering (`llm.metering`) for free. Ask for JSON with `schema=` instead of hand parsing when the answer is pure data.
- Provider changes must keep `tests/test_llm_providers.py` green for every provider (contract suite, fakes only).
- The Messages API provider is the AGT-015 path for single calls; the Studio session still needs the Claude Code
  harness (a Messages-API tool loop is future work).

## Tests (`tests/test_agent.py`, `tests/test_library.py`)
Cover the runner (builds, wrong expectation, script errors, missing `result`), tripwire allow/deny, guard
allow/deny, endpoints, editable params, warm worker recovery, block parsing. Add cases rather than relaxing them.
No test may make a paid or subscription model call: drive agent turns with a replay cassette (AGT-002, see `tests/test_ai_quality.py`).

## Roadmap items this unblocks
- **AGT-015 / PD-09** (before any non-founder user): API-key auth. `aicad app --api-key` exists; the production path
  must refuse subscription auth.
- **EVAL-003**: `aicad bench` (`src/aicad/eval/`): 20 prompts with analytic expectations; `--dry` / `--replay DIR`
  free, `--live [--record DIR]` spends tokens (estimate + confirmation first). Gate on CHK results and the
  expectations, never on the agent's own claims.
- **AGT-009** (done): `agent/runrecord.py` writes `.fw/runs/<id>/run.json` per turn from `AgentSession.send`/`_handle` (never published as an event). If you add a phase, tool or outcome, record it there; read it via `/api/admin/projects/{id}/runs`. Prompt policy `FW_RUN_RECORD_PROMPTS` (hash | redacted (default) | raw, dev only).
- **EVAL-008** (done): `aicad repeat --case P01` (fake ×5), `--replay DIR`, `--live` (confirmed) for variance.
