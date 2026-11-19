# Design-agent cost (branch `wip/agent-cost`)

Problem: in the 2026-11-19 live Design Office run a cold design turn for a simple part cost **$2.96–$3.01** (about 300
platform tokens of a 1,000-token trial wallet) and took 70–125 s. Goal: find where a turn's cost goes and cut it
without making the CAD worse.

## Result

| Office Pinion shaft ticket (same prompt, 3,617 chars, verbatim) | Before (live run, :8797) | After (this branch, :8801) |
|---|---:|---:|
| Cost (agent's own report) | **$2.955** (296 tokens) | **$0.214** (22 tokens), **−93 %** |
| Live meter at the end of the turn | $1.74 (read 41 % low) | $0.213 (matches the report within 0.2 %) |
| Model calls | 2 | 2 |
| Context of the largest call | 349,947 tokens | 24,069 tokens |
| Cache writes | 347,703 (all 1-hour) | 19,284 (all 5-minute) |
| Output tokens | 8,462 | 5,617 |
| Time to first response | 39.5 s | 21.4 s |
| Turn total (run record) | 82.3 s | 61.3 s |
| Builds | 1, pass | 1, pass |
| Gate | CHK-02..05, 07, 08 pass, verified | CHK-02..05, 07, 08 pass, verified |
| Part | bbox 26 × 26 × 130, 29 faces, V 46,154 mm³, 110-line script | bbox 26 × 26 × 130, 29 faces, V 46,219 mm³, 75-line script |

The "after" part: stepped shaft from `fw.stepped_shaft`, Ø20 journals at |Z| 15–65, Ø26 seat, DIN 6885 pinion keyway
8 × 4 on +X from Z −9 to 9 (ICD IF-04), input-stub keyway, two DIN 471 circlip grooves, end chamfers, R0.6 shoulder
fillets, PARAMS with PARAM_META limits. I read the 4-view render: it matches the ICD. Same quality as before at a
shorter script.

The Gear ticket of the same run ($3.01, 4 calls) had the identical pattern (325,565 tokens written in its second call).

## Where the money went (before)

Per model call, from the Claude Code transcripts of the live run (`~/.claude/projects/...8797.../*.jsonl`):

| Turn | Call | Cache write | Cache read | Output | Asked for |
|---|---:|---:|---:|---:|---|
| Pinion shaft | 1 | 12,235 | 4,783 | 6,860 | Write + build |
| | 2 | **335,468** | 14,477 | 1,602 | final message |
| Gear | 1 | 11,745 | 4,783 | 293 | Glob |
| | 2 | **325,565** | 14,469 | 4,099 | Write |
| | 3 | 4,256 | 340,034 | 56 | build |
| | 4 | 2,707 | 344,290 | 1,294 | final message |

Pinion shaft cost by kind: cache writes **$2.78 (94 %)**, output $0.17, cache reads $0.004, uncached input ~0.

**Driver 1 (≈ 90 % of the cost): the founder's claude.ai connectors were loaded into the design agent.** The Claude
Code harness, logged in with a claude.ai account, connects that account's connectors (Atlassian, Base44, Claude Docs,
Microsoft 365, Vanta, ...) in the background about a second after start. From the second call on, their full tool
schemas ride in every request: `/context` (a local command, no model call) showed **MCP tools 311k tokens** after 20 s,
against 14.5k for the whole harness at start. `setting_sources=[]` does not cover them. The transcript shows them
arriving as `deferred_tools_delta` / `mcp_instructions_delta` and 300-odd `tool_addition` blocks in the second request.
This also meant the in-app agent could see the founder's work tools (they were never allowed: `allowed_tools` and
`permission_mode="dontAsk"` deny them), and the "≈ 48k tokens of harness context" the visual-check agent measured is
the same leak in the single-call path.

**Driver 2: 1-hour cache writes.** On a subscription login the harness writes every cache entry with a 1-hour TTL,
which costs 2× the input price; 5-minute entries cost 1.25×. A design turn's calls are seconds apart.

**Driver 3 (metering, not spend): the live meter under-read by ~40 %.** It priced cache writes at the 5-minute rate
and read output from the `AssistantMessage` usage snapshots, which carry the stream-start value (16 output tokens for a
turn that produced 8,462). So run budgets stopped late. This also explains the live-run oddity "stopped_budget at 19
tokens yet approved": the meter crossed the 138-token budget during the giant second call, the turn was interrupted,
and the interrupted process's cumulative report only covered the first call.

Candidates checked and **not** drivers on this evidence:
- `claude_code` preset size: 10.3k system + 3.9k tools, ~$0.08 cold per new project; with 5-minute writes ~$0.06.
  The preset's first ~4.8k tokens are cached globally (`scope: global`) and are read even on a cold project.
- Round trips: 2–4 calls per cold turn. A Glob on an empty folder (Gear) cost one call (~6 s, ~$0.01 now).
- Tool results: the build report is ~1.4k characters; the 1400 × 1050 render is one image (~2k tokens). Not worth
  degrading what the agent sees (founder rule: agents judge visually).
- Thinking: the harness already sends `effort: medium` (the model default); thinking is inside the output tokens,
  which are now about half of the remaining cost.
- Retries: one turn in the run rebuilt 3 times after a failed check (Gear's follow-up, $0.62 at the old rates).
- `MAX_TURNS=80`: turns used 2–11. Left unchanged; the new hard cap bounds money instead.

## Changes

1. **Harness isolation** (`agent/session.py` `harness_env()`, used by the session and by `llm/claude_sdk.py` single
   calls): `strict_mcp_config=True` and `ENABLE_CLAUDEAI_MCP_SERVERS=false`. `/context` after 20 s: 15.2k tokens, no
   MCP tools other than `cad`. Applies to Gage / Archie / visual-check single calls too (not measured live; they were
   carrying the same connectors).
2. **5-minute prompt cache** (`CLAUDE_CODE_PROMPT_CACHE_TTL=5m`, opt back with `FW_AGENT_CACHE_TTL=1h`). Same as
   API-key auth already does (production path, PD-09).
3. **Pricing by TTL** (`agent/pricing.py`): 1-hour writes at 2× input, 5-minute at 1.25×. The live Pinion shaft
   calls now price to $2.9547 against the agent's $2.9551.
4. **Per-call instrumentation** (`agent/runrecord.py` `CallLog`; session `include_partial_messages=True`): from the
   stream's `message_start` / `message_delta` / `message_stop`, the run record gains
   - `calls[]`: per model call, input, cache writes 1h / 5m, cache reads, final output, start and duration, context
     size, tools asked for, tool-result sizes (characters, images), cost;
   - `cost_breakdown`: model calls, totals, largest context, cache-hit ratio, cost by kind (input / cache write /
     cache read / output), tool-result characters and images.

   It is admin-only telemetry, as before (`/api/admin/projects/{id}/runs/{run}`), and never published to the chat.
   Clients without stream events (replay cassettes, fakes) fall back to the message snapshots.
5. **Accurate live meter + hard per-turn cap** (`session.py`): the meter prices each call's streamed usage (output
   included). A turn stops at the lower of the run budget and `FW_AGENT_TURN_CAP_USD` (default **$2.50**, `0` = off;
   it also covers God mode, which has no budget). On a stop the chat says, once: "I stopped here because this request
   reached its cost limit. Everything built so far stays in the design, and the checks panel shows where it stands.
   Ask me to continue if you want me to carry on."
6. **Opt-in effort** `FW_AGENT_EFFORT=low|medium|high|xhigh|max`. Default unchanged (harness default, `medium`).
7. Skill `design-agent`: the isolation rule, how to check it for free with `/context`, the new telemetry and settings.

Not changed: the model (PD-82), the compact system prompt default (PD-81, below), `MAX_TURNS`, the render, the
prompt text.

## Tests
- New `tests/test_agent_cost.py` (9 tests, no model calls):
  - TTL pricing.
  - The live Pinion shaft usage prices to the agent's own report.
  - The session and single-call options are isolated, with the env overrides.
  - Cap setting parsing.
  - `CallLog` from stream events.
  - The run record carries `calls` / `cost_breakdown` and an estimate that includes output.
  - A spending fake stops at the cap with one honest message and `budget_stopped`, with no user budget.
  - A user budget below the cap wins.
- `test_agent`, `test_pipeline_speed`, `test_ai_*`, `test_llm_providers`, `test_run_record`, `test_agent_cost`,
  `test_platform`: **134 passed**.
- `ruff check src tests` clean.

## Live spend (founder's subscription, dev login)
- One after-turn: $0.214.
- Probes: about $0.55. The `/context` probes are free when sent from Python, but four of them got `/context` as a Git
  Bash argument, which MSYS rewrote to `C:/Program Files/Git/context`, so each became a small cold model call (~$0.11
  each). There was also one compact-prompt probe at $0.107.
- Total about **77 platform tokens**, within the 120 allowed.
- No baseline turn was re-run: the "before" numbers come from the live run's run records and transcripts, which were
  read only.

## Parked decisions (master numbers them)
- **PD (cache TTL):** 5-minute prompt cache by default for the in-app agents. Default used: 5m (cheaper for turns whose
  calls are seconds apart; a Studio user who comes back after 5–60 min re-writes ~15–25k tokens, ~$0.1, instead of
  reading them). `FW_AGENT_CACHE_TTL=1h` restores the harness default.
- **PD (hard per-turn cap):** $2.50 per turn on top of the run budget, also in God mode. Default used: 2.50 (a cold
  simple part now costs ~$0.2; an iterating complex part well under $1.5).
- **PD (effort):** keep the harness default (`medium`). `low` is opt-in only, since there's no benchmark yet.
- **PD-81 (compact system prompt):** unchanged, still opt-in. The 3-part benchmark the brief asks for didn't fit in the
  live budget. After this fix the gain is small: ~2k tokens, and cross-project caching of ~10k tokens (~$0.05 per new
  project at 5-minute rates).
- **PD (privacy, founder call):** the harness injects the logged-in account's e-mail address and organization id into
  the agent's context (`session_context` / `credential_org` attachments in the transcript). It is harmless for the
  founder's own dev login, but it is one more reason for API-key auth (PD-09 / AGT-015) before any other user.

## Follow-ups (not done)
- Measure the Office's single calls (Gage, Archie, visual check) after the isolation fix. Expected: their ~48k harness
  context drops to ~15k.
- A one-line prompt hint "new design: the folder is empty, write it directly" would save the empty-folder Glob call
  (~6 s). It was left out because prompt changes need a benchmark.
- The render frames slender parts badly (front/right views are clipped at 1400 × 1050, visible on this shaft). This is
  pre-existing and belongs to the render code, not to cost.

## Files
- `src/aicad/agent/pricing.py`: TTL-aware cache-write pricing.
- `src/aicad/agent/runrecord.py`: `CallLog`, `calls`, `cost_breakdown`.
- `src/aicad/agent/session.py`: isolation, cache TTL, partial messages, meter, cap, stop note, opt-in effort.
- `src/aicad/llm/claude_sdk.py`: single calls isolated.
- `tests/test_agent_cost.py` (new).
- `.claude/skills/design-agent/SKILL.md`.
- `docs/reports/agent-cost.md` (this report).
