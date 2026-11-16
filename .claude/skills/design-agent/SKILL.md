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
| Structured blocks | `extract_questions` (fenced `fw-questions`), `extract_recognition` (fenced `fw-recognition`) | JSON in a fenced block; the block is stripped from the visible text and rendered as chips or tree data |
| Build tool | `src/aicad/agent/tools.py` → `runner.py` via the warm `worker.py` | returns the "Overall gating checks: PASS/FAIL" text plus the 4-view render; `friendly_result` keys on that prefix |
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

## Tests (`tests/test_agent.py`, `tests/test_library.py`)
Cover the runner (builds, wrong expectation, script errors, missing `result`), tripwire allow/deny, guard
allow/deny, endpoints, editable params, warm worker recovery, block parsing. Add cases rather than relaxing them.
No test may make a paid or subscription model call (AGT-002 replay provider is still backlog).

## Roadmap items this unblocks
- **AGT-015 / PD-09** (before any non-founder user): API-key auth. `aicad app --api-key` exists; the production path
  must refuse subscription auth.
- **EVAL-003**: an opt-in benchmark of about 20 original prompts (plate/bracket family) reporting first-pass and
  ≤3-iteration pass rates, turns, time and tokens. Gate on CHK results, never on the agent's own claims. Keep prompts
  and expected envelopes in the repo.
- **AGT-009**: a run record (model id, versions, timings, tokens) stored server-side, never shown to users.
