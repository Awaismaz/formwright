"""Agent cost controls (docs/reports/agent-cost.md): harness isolation, cache TTL pricing, per-call breakdown in the
run record, and the per-turn cost cap. No model calls: fakes emit the SDK's message and stream-event shapes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock, ToolUseBlock

from aicad.agent import session as session_mod
from aicad.agent.pricing import usage_cost_usd
from aicad.agent.runrecord import CallLog, RunRecorder
from aicad.agent.session import BUDGET_STOP_NOTE, AgentSession, harness_env, turn_cap_usd

OPUS = "claude-opus-5-5"


def _u(inp: int, cw1h: int, cr: int, out: int, cw5m: int = 0) -> dict[str, Any]:
    return {"input_tokens": inp, "cache_creation_input_tokens": cw1h + cw5m, "cache_read_input_tokens": cr,
            "output_tokens": out, "cache_creation": {"ephemeral_1h_input_tokens": cw1h,
                                                     "ephemeral_5m_input_tokens": cw5m}}


# ------------------------------------------------------------------ pricing
def test_one_hour_cache_writes_cost_twice_the_input_price() -> None:
    assert usage_cost_usd(OPUS, _u(0, 1_000_000, 0, 0)) == pytest.approx(8.0)
    assert usage_cost_usd(OPUS, _u(0, 0, 0, 0, cw5m=1_000_000)) == pytest.approx(5.0)
    # no split in the report: the 5-minute price, as before
    assert usage_cost_usd(OPUS, {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(5.0)


def test_live_pinion_shaft_turn_prices_to_the_agents_own_report() -> None:
    """The two calls of the 2026-11-19 live Pinion shaft turn (Claude Code transcript); the agent reported $2.955127.
    The old meter, pricing every write at the 5-minute rate from the message snapshots, read $1.74."""
    calls = [_u(2, 12235, 4783, 6860), _u(2, 335468, 14477, 1602)]
    assert sum(usage_cost_usd(OPUS, u) for u in calls) == pytest.approx(2.955127, rel=1e-3)


# ------------------------------------------------------------------ harness isolation
def test_session_options_isolate_the_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("FW_AGENT_CACHE_TTL", "FW_AGENT_EFFORT"):
        monkeypatch.delenv(k, raising=False)
    o = AgentSession(tmp_path / "ws").options()
    assert o.strict_mcp_config is True
    assert o.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"  # no claude.ai connectors (311k tokens per call)
    assert o.env["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "5m"
    assert o.include_partial_messages is True
    assert o.effort is None  # the harness default unless opted in
    assert list(o.mcp_servers) == ["cad"] and o.setting_sources == []
    monkeypatch.setenv("FW_AGENT_CACHE_TTL", "1h")
    monkeypatch.setenv("FW_AGENT_EFFORT", "low")
    o = AgentSession(tmp_path / "ws2").options()
    assert o.env["CLAUDE_CODE_PROMPT_CACHE_TTL"] == "1h" and o.effort == "low"
    monkeypatch.setenv("FW_AGENT_CACHE_TTL", "forever")
    monkeypatch.setenv("FW_AGENT_EFFORT", "ludicrous")
    assert "CLAUDE_CODE_PROMPT_CACHE_TTL" not in harness_env()
    assert AgentSession(tmp_path / "ws3").options().effort is None


def test_single_calls_are_isolated_too(tmp_path: Path) -> None:
    from aicad.llm.base import CallRequest
    from aicad.llm.claude_sdk import ClaudeAgentSDKProvider

    o = ClaudeAgentSDKProvider().options_for(CallRequest(role="reviewer", system="Review.", prompt="x"), tmp_path)
    assert o.strict_mcp_config is True and o.env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"


def test_turn_cap_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FW_AGENT_TURN_CAP_USD", raising=False)
    assert turn_cap_usd() == pytest.approx(2.5)
    monkeypatch.setenv("FW_AGENT_TURN_CAP_USD", "0")
    assert turn_cap_usd() is None
    monkeypatch.setenv("FW_AGENT_TURN_CAP_USD", "junk")
    assert turn_cap_usd() == pytest.approx(2.5)


# ------------------------------------------------------------------ per-call breakdown
def _ev(event: dict[str, Any]) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="s", event=event)


def _call_events(mid: str, usage: dict[str, Any], out: int) -> list[StreamEvent]:
    start = {k: v for k, v in usage.items() if k != "output_tokens"} | {"output_tokens": 3}
    return [_ev({"type": "message_start", "message": {"id": mid, "model": OPUS, "usage": start}}),
            _ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "x"}}),
            _ev({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": out}}),
            _ev({"type": "message_stop"})]


def _assistant(mid: str, blocks: list[Any], usage: dict[str, Any]) -> AssistantMessage:
    return AssistantMessage(content=blocks, model=OPUS, usage=usage, message_id=mid)


def test_call_log_from_stream_events() -> None:
    t = iter(range(100))
    log = CallLog(clock=lambda: float(next(t)), t0=0.0)
    for e in _call_events("m1", _u(2, 12000, 4000, 0), 900):
        log.stream(e.event)
    log.message("m1", OPUS, {"output_tokens": 3}, ["Write", "cad:build_model"])
    log.tool_result("m1", "cad:build_model", {"text_chars": 400, "images": 1})
    rows = log.rows()
    assert len(rows) == 1
    r = rows[0]
    assert (r["input_tokens"], r["cache_write_1h"], r["cache_read_input_tokens"], r["output_tokens"]) == (
        2, 12000, 4000, 900)
    assert r["tools"] == ["Write", "cad:build_model"] and r["tool_results"][0]["images"] == 1
    assert r["context_tokens"] == 16002 and r["duration_s"] is not None
    s = log.summary()
    assert s["model_calls"] == 1 and s["source"] == "stream"
    assert s["cost_usd"] == pytest.approx(usage_cost_usd(OPUS, _u(2, 12000, 4000, 900)))
    assert sum(s["cost_usd_by_kind"].values()) == pytest.approx(s["cost_usd"])
    assert s["cost_usd_by_kind"]["cache_write"] == pytest.approx(12000 * 8 / 1e6)


def test_run_record_carries_the_breakdown(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    rec = RunRecorder(ws, prompt="gear shaft", mode="build", requested_model=None)
    msgs: list[Any] = [*_call_events("m1", _u(2, 12000, 4783, 0), 4000),
                       _assistant("m1", [ToolUseBlock(id="t1", name="Write", input={"file_path": "model.py"})],
                                  {"output_tokens": 3}),
                       *_call_events("m2", _u(2, 3000, 16783, 0), 800),
                       _assistant("m2", [TextBlock(text="Done.")], {"output_tokens": 3}),
                       ResultMessage(subtype="success", duration_ms=1000, duration_api_ms=900, is_error=False,
                                     num_turns=2, session_id="s", total_cost_usd=0.2)]
    for m in msgs:
        rec.observe(m)
    out = rec.finish(run_cost_usd=0.2)
    assert [c["n"] for c in out["calls"]] == [1, 2] and out["calls"][0]["tools"] == ["Write"]
    b = out["cost_breakdown"]
    assert b["model_calls"] == 2 and b["output_tokens"] == 4800 and b["context_tokens_max"] == 19785
    # the estimate now includes the output the message snapshots never carried
    assert out["cost_usd"]["estimate_from_usage"] == pytest.approx(b["cost_usd"], abs=1e-5)
    assert b["cost_usd"] > usage_cost_usd(OPUS, _u(4, 15000, 21566, 6))


# ------------------------------------------------------------------ the per-turn cap
class _SpendingClient:
    """Each call writes a big cache prefix; never finishes on its own until interrupted."""

    def __init__(self) -> None:
        self.interrupted = False

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def interrupt(self) -> None:
        self.interrupted = True

    async def query(self, prompt: str) -> None:
        return None

    async def receive_response(self) -> Any:
        for i in range(10):
            if self.interrupted:
                break
            for e in _call_events(f"m{i}", _u(2, 100_000, 0, 0), 2000):  # $0.84 per call
                yield e
            yield _assistant(f"m{i}", [TextBlock(text="working")], {"output_tokens": 3})
        yield ResultMessage(subtype="error_during_execution", duration_ms=10, duration_api_ms=10, is_error=True,
                            num_turns=3, session_id="s", total_cost_usd=2.52)


def test_turn_stops_at_the_cap_with_an_honest_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FW_AGENT_TURN_CAP_USD", "2.0")
    events: list[dict[str, Any]] = []
    s = AgentSession(tmp_path / "ws", on_event=events.append)
    client = _SpendingClient()
    s.client_factory = lambda o: client
    assert s.run_budget_usd is None  # no user budget (God mode): the hard cap still applies
    asyncio.run(s.send("make a gearbox"))
    assert client.interrupted
    texts = [e["text"] for e in events if e["type"] == "text"]
    assert texts.count(BUDGET_STOP_NOTE) == 1
    res = [e for e in events if e["type"] == "result"]
    assert len(res) == 1 and res[0]["budget_stopped"] is True
    assert s.run_spent_usd == pytest.approx(3 * 0.84, abs=1e-3)  # stopped after the call that crossed $2
    assert s.last_run_record["cost_breakdown"]["model_calls"] == 3


def test_user_budget_below_the_cap_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FW_AGENT_TURN_CAP_USD", raising=False)
    s = AgentSession(tmp_path / "ws")
    s.run_budget_usd = 0.5
    assert s.limit_usd() == pytest.approx(0.5)
    s.run_budget_usd = 9.0
    assert s.limit_usd() == pytest.approx(session_mod.DEFAULT_TURN_CAP_USD)
