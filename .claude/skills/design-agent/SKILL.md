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
| Session | `src/aicad/agent/session.py` | `BUILTIN_TOOLS` + `CAD_TOOLS` allow-list, `permission_mode="dontAsk"`, `setting_sources=[]` (isolated from any developer `.claude`, including this repo's skills), PreToolUse `make_guard` (paths inside workspace; WebFetch only `build123d.readthedocs.io`), `MAX_TURNS=80`, resume by `session_id` ; cost isolation (agent-cost): `strict_mcp_config=True` + `harness_env()` (`ENABLE_CLAUDEAI_MCP_SERVERS=false`, 5-minute prompt cache), `include_partial_messages=True` for per-call usage |
| UI wording | `session.py` `friendly_step`, `friendly_result`, `_SCRUB`, `scrub()` | no file names, tools, code, Python, library or model ids reach the UI (DS-014, CLAUDE.md rule) |
| Structured blocks | `extract_questions` (`fw-questions`), `extract_recognition` (`fw-recognition`), `agent/blocks.py` `extract_brief` (`fw-brief`, CAD-028) and `extract_review` (`fw-review`, AGT-006: reconciled with `out/status.json`, can never pass a failed gate) | JSON in a fenced block; the block is stripped from the visible text and rendered as chips, tree data, the brief card or the Self-review panel |
| PropertyManager edits | `agent/edits.py` `extract_edit` (`fw-edit`, DS-035): small edits (fillet / chamfer / shell / hole / an existing hand-made feature / extrude depth / pattern count-spacing / parameters; `edits: [...]` = several, one PM step each, impact previewed as a `sequence`) resolved on `out/topo.json` and validated by `studio.validate_feature`; `design_state` adds a one-line `[Design state for quick edits: ...]` to short build prompts (never shown) | the session publishes `{"type": "edit"}`; the Studio opens the real PM pre-filled (`studio/agentEdit.ts`), the user presses OK; the agent writes no code |
| Provider | `src/aicad/llm/` (AGT-001): `AgentSession.client_factory` defaults to `session.provider_client` = `llm.get_provider("design_agent").agent_client(options)`; single calls elsewhere use `llm.complete(CallRequest(role=...))` | the session vocabulary stays the Agent SDK message dataclasses; providers `claude-sdk` (default, unchanged behaviour incl. replay/record env), `anthropic-api` (no sessions), `stub`, `replay`; `FW_LLM_PROVIDERS` routes roles; the run record stores `provider` |
| Project context + design memory | `memory/context.turn_context` (the ONLY place turn-level context is assembled), called by `projects._memory_for_turn` in `agent_chat`: `[Project context: …]` (sibling parts' size / material / mating features / params, decisions, notes; ≤ 2 000 chars) + `[Designer preferences …]` (≤ 700 chars); sent once per conversation and when its digest changes (`.fw/context.json`); chat statements captured by `memory/extract.py`; learning in `memory/learn.py` (hooked after manual-feature and param-edit snapshots) | never shown in the chat (`shown` = the user's words; `last_prompt` strips both blocks); the Studio's chat-header chip shows the same content in plain words (`GET /api/projects/{id}/agent-context`). Report: `docs/reports/design-memory.md` |
| Replay | `agent/replay.py` (`ReplayClient`, `RecordingClient`, `FW_AGENT_REPLAY` / `FW_AGENT_RECORD`, `AgentSession.client_factory`) | tests and demos replay recorded turns with zero model calls |
| Build tool | `src/aicad/agent/tools.py` → `runner.py` via the warm `worker.py` | returns the "Overall gating checks: PASS/FAIL" text plus the 4-view render; `friendly_result` keys on that prefix. Takes `source` (whole script) or `edits` ([{old, new}], each unique, all or nothing) to write and build in ONE call (agent-latency); errors start "NOT BUILT:" |
| Turn planning (agent-latency) | `src/aicad/agent/speed.py`, `session._with_folder_note` / `_apply_turn_settings` | every turn gets a hidden `[Project folder: ...]` line (and the design's text when the agent hasn't seen that version: sha in `.fw/agent.json` `design_seen`); effort `low` for edits and fully dimensioned simple parts (`FW_AGENT_ADAPTIVE_EFFORT=0` off); model by job size (`job_of`: edit / simple / complex) through `llm/routing.py` (PD-82, `FW_LLM_MODELS`); both switched on the live process by control requests (`apply_flag_settings` effortLevel, `set_model`), recorded in the run record's `turn` block |
| Deferred checks (PS-01) | `tools.build_handler` → `runner.main(fast=True, determinism=True)`; `agent/deferred.py` `DeferredChecks` | the report comes back in seconds with CHK-07/08 `[PENDING]`; exports + CHK-07 + CHK-08 run in the background on the same worker; a newer build supersedes them; failures are prepended to the next report; `AgentSession.send` holds the `ResultMessage` until `settle()` and gives ONE automatic follow-up on a failure; the verdict is `runner.is_verified(status)` (never `ok` alone) |
| Standard features (PS-03) | `src/aicad/fw_std.py`, re-exported by `fw` | `fw.spur_gear`, `stepped_shaft`, `shaft_keyway`, `hole`/`holes_at`/`bolt_circle` (dict specs for custom cbore/csk), `din6885`, `plate`, `gusset`, `cross_hole`, `meta` (compact PARAM_META) return EXPECTED parts from hand formulas; the prompt tells the agent to prefer them (a hand-written involute cost ~60 s of output and 2048 faces) |
| Editable params | `runner.editable_params` / `param_meta` | only top-level `NAME = <number>` lines declared in `PARAMS`; PARAM_META limits enforced server-side |

## Rules when editing
- **Cost: keep the harness isolated.** On a claude.ai login the Claude Code harness loads the logged-in user's claude.ai
  connectors (Atlassian, Microsoft 365, Vanta, ...) a second after start: ~311k tokens of tool schemas in every call
  after the first, which made a cold turn cost $3. Every `ClaudeAgentOptions` (session and `llm/claude_sdk.py`) must
  keep `strict_mcp_config=True` and `env=harness_env()`. Check with a free `/context` query (a local command; pass it
  from Python, not as a Git Bash argument, which rewrites `/context` to a path and makes it a paid prompt).
- The run record's `calls` / `cost_breakdown` show each model call's input, cache writes (1h/5m), cache reads, output,
  wall time and tool results. The live meter prices the same stream usage; per-turn hard cap `FW_AGENT_TURN_CAP_USD`
  (default 2.50) on top of the run budget. Opt-ins: `FW_AGENT_EFFORT` (forces one level), `FW_AGENT_CACHE_TTL=1h`. Latency benchmark: `aicad latency --dry` (free) / `--live --yes [--model ...]` (5 fixed cases, docs/reports/agent-latency.md).
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

## Design graph intent (architecture v2, `src/aicad/graph/`, docs/architecture/design-graph.md)
- Role `intent` (`llm/base.ROLES`), routed by `intent.job_of(brief)`: `intent.simple` Sonnet, else Opus (PD-111).
  One call with `INTENT_SCHEMA` and `standalone_system=True`; the prompt's vocabulary is generated from
  `graph/registry.py`, so add a component or connection kind there, never in the prompt text.
- The model never sizes: `resolve.py` / `standards.py` do; a value it gives that is not in the brief is `assumed`.
  Exclusions come from `office/scope.py`, never from the model. Questions: `questions.py` (max 3, code's first).
- Tests replay recorded replies with `StubProvider` on role `intent` (`tests/golden/design_graph/*.json`, the
  `*.live.json` files are the live replies). Live comparison: `docs/reports/design-graph/live_intent.py`
  (`--rescore` re-scores recorded replies with no call).
- Every compile is cross-checked against its ICD (`compile.check`); a non-empty check is a bug in the compile.
- Pitfall: Python written through a Git Bash heredoc can turn `\b` into a backspace byte; write scripts with the
  Write tool and grep new files for `\x08`.
