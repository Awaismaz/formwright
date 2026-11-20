"""AGT-001 / AGT-013: the LLMProvider contract, run against every provider.

No model is called: the Claude Agent SDK provider gets a scripted ``query`` stand-in and a scripted session client,
the Anthropic Messages API provider gets a fake ``AsyncAnthropic``-shaped client, the replay provider a cassette,
and the stub provider needs nothing. Each backend is a tiny deterministic "fake model" (``_answer``) so the same
assertions hold for all four: text, schema-valid JSON (and a clean failure on invalid JSON), images actually
reaching the model, metering (tokens, cost, model id), and the Design Studio session loop.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aicad import llm
from aicad.llm import metering
from aicad.llm.anthropic_api import AnthropicAPIProvider
from aicad.llm.base import CallRequest, parse_json_answer, schema_instruction
from aicad.llm.claude_sdk import ClaudeAgentSDKProvider
from aicad.llm.replay import ReplayProvider
from aicad.llm.stub import StubAgentClient, StubProvider, example_for
from aicad.platform.config import Settings, get_settings, override_settings

SCHEMA = {"type": "object", "properties": {"verdict": {"enum": ["accept", "reject"]},
                                           "reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                                           "score": {"type": "number", "minimum": 0, "maximum": 1}},
          "required": ["verdict", "reasons", "score"], "additionalProperties": False}
GOOD = {"verdict": "accept", "reasons": ["fits the envelope"], "score": 0.8}
BAD = {"verdict": "maybe", "reasons": []}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG_SHA = hashlib.sha256(PNG).hexdigest()[:12]
PROVIDERS = ["stub", "claude-sdk", "anthropic-api", "replay"]


# ------------------------------------------------------------------ one deterministic "model" behind every backend
def _answer(prompt: str, schema: dict[str, Any] | None, images: list[bytes], bad: bool) -> str:
    """What the fake model says. Structured requests get GOOD (or BAD) JSON; images are fingerprinted."""
    if schema is not None:
        text = "Here is the answer.\n```json\n" + json.dumps(BAD if bad else GOOD) + "\n```"
    else:
        text = f"Answer to: {prompt[:40]}"
    for b in images:
        text += f"\nImages read: sha256 {hashlib.sha256(b).hexdigest()[:12]}"
    return text


def _schema_from_system(system: str) -> dict[str, Any] | None:
    m = re.search(r"nothing after it:\n(\{.*\})\s*$", system, re.DOTALL)
    return json.loads(m.group(1)) if m else None


def _sdk_query(bad: bool) -> Any:
    """A scripted ``claude_agent_sdk.query``: honours the options it gets (tools, guard, cwd), like the harness."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock

    async def query(prompt: str, options: Any) -> AsyncIterator[Any]:
        system = options.system_prompt["append"] if isinstance(options.system_prompt, dict) else options.system_prompt
        images: list[bytes] = []
        if "Read" in (options.tools or []):  # the harness opens each named image with Read, through the guard
            guard = options.hooks["PreToolUse"][0].hooks[0]
            for name in re.findall(r"`([^`]+\.(?:png|jpg|jpeg))`", prompt):
                verdict = await guard({"tool_name": "Read", "tool_input": {"file_path": name}}, None, None)
                assert verdict == {}, verdict
                images.append((Path(options.cwd) / name).read_bytes())
        text = _answer(prompt, _schema_from_system(system), images, bad)
        usage = {"input_tokens": 120, "output_tokens": 30}
        yield SystemMessage(subtype="init", data={})
        yield AssistantMessage(content=[TextBlock(text=text)], model="claude-opus-5-5", usage=usage, message_id="m1")
        yield ResultMessage(subtype="success", duration_ms=5, duration_api_ms=4, is_error=False, num_turns=1,
                            session_id="s", total_cost_usd=0.0011, usage=usage)

    return query


class _FakeMessages:
    def __init__(self, bad: bool, refuse: bool = False) -> None:
        self.bad, self.refuse, self.bodies = bad, refuse, []

    async def create(self, **body: Any) -> Any:
        self.bodies.append(body)
        content = body["messages"][0]["content"]
        images = [base64.b64decode(c["source"]["data"]) for c in content if c["type"] == "image"]
        prompt = next(c["text"] for c in content if c["type"] == "text")
        schema = (body.get("output_config") or {}).get("format", {}).get("schema")
        text = _answer(prompt, schema, images, self.bad)
        if schema is not None:  # output_config.format: the text block is the JSON itself
            text = json.dumps(BAD if self.bad else GOOD)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], model=body["model"],
                               stop_reason="refusal" if self.refuse else "end_turn",
                               usage=SimpleNamespace(input_tokens=150, output_tokens=40,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0))


def _fake_anthropic(bad: bool = False, refuse: bool = False) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=_FakeMessages(bad, refuse)))


def _cassette(bad: bool) -> dict[str, Any]:
    usage = {"input_tokens": 100, "output_tokens": 20}
    return {"version": 1, "calls": [
        {"role": "planner", "text": _answer("Hello", None, [], bad), "model": "claude-opus-5-5", "usage": usage,
         "cost_usd": 0.0009},
        {"role": "change_review", "text": _answer("x", SCHEMA, [], bad), "model": "claude-opus-5-5", "usage": usage,
         "cost_usd": 0.0009},
        {"role": "vision", "text": _answer("x", None, [PNG], bad), "model": "claude-opus-5-5", "usage": usage,
         "cost_usd": 0.0009}],
        "turns": [{"messages": [
            {"type": "system", "subtype": "init", "data": {}},
            {"type": "assistant", "model": "claude-opus-5-5", "usage": usage, "message_id": "r1",
             "content": [{"type": "text", "text": "Recorded reply: no change needed."}]},
            {"type": "result", "subtype": "success", "num_turns": 1, "session_id": "rs", "total_cost_usd": 0.0009,
             "usage": usage}]}]}


def _stub_responder(bad: bool) -> Any:
    def respond(req: CallRequest) -> str | None:
        if req.schema is not None:
            return _answer(req.prompt, req.schema, [], bad)
        return None  # the stub's own deterministic text (and image fingerprints)
    return respond


def make_provider(name: str, bad: bool = False) -> llm.LLMProvider:
    if name == "stub":
        return StubProvider(responder=_stub_responder(bad))
    if name == "claude-sdk":
        return ClaudeAgentSDKProvider(query_fn=_sdk_query(bad), client_factory=StubAgentClient)
    if name == "anthropic-api":
        return AnthropicAPIProvider(client=_fake_anthropic(bad))
    if name == "replay":
        return ReplayProvider(_cassette(bad))
    raise AssertionError(name)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _dev_settings() -> Any:
    saved = get_settings()
    override_settings(Settings(env="development", llm_providers=""))
    yield
    override_settings(saved)


# ================================================================== the contract (parametrised over providers)
@pytest.mark.parametrize("name", PROVIDERS)
def test_contract_text_call_is_metered(name: str, tmp_path: Path) -> None:
    p = make_provider(name)
    assert p.supports(llm.CAP_COMPLETE)
    with metering.capture() as seen:
        res = _run(p.complete(CallRequest(role="planner", system="You plan.", prompt="Hello", cwd=tmp_path)))
    assert res.text.strip()
    m = res.metering
    assert (m.provider, m.role, m.ok) == (name, "planner", True)
    assert m.model and m.usage.input_tokens > 0 and m.usage.output_tokens > 0
    assert m.cost_usd is not None and m.cost_usd >= 0 and m.cost_source in ("reported", "estimated", "none")
    assert m.latency_s >= 0
    assert seen == [m]  # exactly one metering record per call
    assert "Hello" not in json.dumps(m.as_dict())  # metering never carries prompt text


@pytest.mark.parametrize("name", PROVIDERS)
def test_contract_structured_output_validates(name: str, tmp_path: Path) -> None:
    p = make_provider(name)
    assert p.supports(llm.CAP_STRUCTURED)
    res = _run(p.complete(CallRequest(role="change_review", system="Judge.", prompt="Change?", schema=SCHEMA,
                                      cwd=tmp_path)))
    assert res.data == GOOD


@pytest.mark.parametrize("name", PROVIDERS)
def test_contract_structured_output_rejects_invalid_json(name: str, tmp_path: Path) -> None:
    p = make_provider(name, bad=True)
    with metering.capture() as seen, pytest.raises(llm.StructuredOutputError):
        _run(p.complete(CallRequest(role="change_review", system="Judge.", prompt="Change?", schema=SCHEMA,
                                    cwd=tmp_path)))
    assert len(seen) == 1 and seen[0].ok is False  # a failed call is still metered


@pytest.mark.parametrize("name", PROVIDERS)
def test_contract_vision_image_reaches_the_model(name: str, tmp_path: Path) -> None:
    p = make_provider(name)
    assert p.supports(llm.CAP_VISION)
    (tmp_path / "sketch.png").write_bytes(PNG)
    res = _run(p.complete(CallRequest(role="vision", system="Read drawings.", prompt="What is written?",
                                      images=(tmp_path / "sketch.png",), max_turns=4, cwd=tmp_path)))
    assert f"sha256 {PNG_SHA}" in res.text


@pytest.mark.parametrize("name", PROVIDERS)
def test_contract_agent_session_or_clean_refusal(name: str, tmp_path: Path) -> None:
    """Providers with sessions drive the real AgentSession (events, metering, run record naming the provider);
    the others refuse with CapabilityError instead of half-working."""
    from aicad.agent.session import AgentSession

    p = make_provider(name)
    if not p.supports(llm.CAP_AGENT):
        with pytest.raises(llm.CapabilityError):
            p.agent_client(object())
        return
    events: list[dict[str, Any]] = []
    with llm.use_provider(p, roles=("design_agent",)):
        s = AgentSession(tmp_path / "ws", on_event=events.append)
        _run(s.send("Is the plate thick enough?", mode="discuss"))
    kinds = [e["type"] for e in events]
    assert "text" in kinds and "result" in kinds and "error" not in kinds, kinds
    res = next(e for e in events if e["type"] == "result")
    assert res["cost_est_usd"] is not None and res["cost_est_usd"] >= 0
    rec = s.last_run_record
    assert rec is not None and rec["provider"] == name and rec["model"]["used"]
    assert rec["tokens"]["input_tokens"] > 0


# ================================================================== provider-specific behaviour
def test_claude_sdk_single_call_options_match_the_pre_agt001_shape(tmp_path: Path) -> None:
    p = ClaudeAgentSDKProvider()
    o = p.options_for(CallRequest(role="reviewer", system="Review.", prompt="x", budget_usd=0.001), tmp_path)
    assert o.tools == [] and o.allowed_tools == [] and o.permission_mode == "dontAsk" and o.setting_sources == []
    assert o.system_prompt == {"type": "preset", "preset": "claude_code", "append": "Review."}
    assert o.max_turns == 1 and o.max_budget_usd == 0.01 and o.cwd == str(tmp_path) and not o.hooks
    o = p.options_for(CallRequest(role="render_refine", system="Polish.", prompt="x", standalone_system=True),
                      tmp_path)
    assert o.system_prompt == "Polish."
    (tmp_path / "a.png").write_bytes(PNG)
    o = p.options_for(CallRequest(role="vision", system="Read.", prompt="x", images=(tmp_path / "a.png",),
                                  max_turns=4), tmp_path)
    assert o.tools == ["Read"] and o.allowed_tools == ["Read"] and o.max_turns == 4
    guard = o.hooks["PreToolUse"][0].hooks[0]
    denied = _run(guard({"tool_name": "Read", "tool_input": {"file_path": str(tmp_path.parent / "x.png")}}, None,
                        None))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    o = p.options_for(CallRequest(role="planner", system="Plan.", prompt="x", schema=SCHEMA), tmp_path)
    assert o.system_prompt["append"].endswith(schema_instruction(SCHEMA))


def test_claude_sdk_refuses_images_outside_the_call_folder(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG)
    inner = tmp_path / "job"
    inner.mkdir()
    p = make_provider("claude-sdk")
    with pytest.raises(ValueError, match="inside"):
        _run(p.complete(CallRequest(role="vision", system="s", prompt="p", images=(tmp_path / "a.png",), cwd=inner)))


def test_claude_sdk_estimates_cost_when_no_report() -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock

    async def query(prompt: str, options: Any) -> AsyncIterator[Any]:
        yield AssistantMessage(content=[TextBlock(text="ok")], model="claude-opus-5-5",
                               usage={"input_tokens": 1_000_000, "output_tokens": 0}, message_id="m")

    res = _run(ClaudeAgentSDKProvider(query_fn=query).complete(CallRequest(role="librarian", system="s", prompt="p")))
    assert res.metering.cost_source == "estimated" and res.metering.cost_usd == pytest.approx(4.0)


def test_anthropic_request_shape_images_schema_and_fallbacks(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(PNG)
    fake = _fake_anthropic()
    p = AnthropicAPIProvider(client=fake)
    _run(p.complete(CallRequest(role="vision", system="Read.", prompt="Size?", images=(tmp_path / "a.png",),
                                schema=SCHEMA)))
    body = fake.beta.messages.bodies[0]
    assert body["model"] == "claude-opus-5-5" and body["system"] == "Read." and body["max_tokens"] == 16000
    content = body["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "text"]  # images before the text
    assert content[0]["source"]["media_type"] == "image/png"
    assert body["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert body["fallbacks"] == "default" and body["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in body and "tool_choice" not in body  # Opus 5.5: no disabled thinking / forced tools


def test_anthropic_provider_is_off_without_its_own_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FW_LLM_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-used")  # the dev login's variable is never picked up
    with pytest.raises(llm.ProviderError, match="FW_LLM_ANTHROPIC_API_KEY"):
        _run(AnthropicAPIProvider().complete(CallRequest(role="planner", system="s", prompt="p")))


def test_anthropic_refusal_is_a_provider_error() -> None:
    p = AnthropicAPIProvider(client=_fake_anthropic(refuse=True))
    with pytest.raises(llm.ProviderError, match="declined"):
        _run(p.complete(CallRequest(role="planner", system="s", prompt="p")))


def test_replay_without_a_recording_raises_like_a_failed_call() -> None:
    p = ReplayProvider(_cassette(False))
    with pytest.raises(llm.ProviderError):
        _run(p.complete(CallRequest(role="librarian", system="s", prompt="p")))


def test_stub_is_deterministic_and_schema_examples_validate() -> None:
    import jsonschema

    a = _run(StubProvider().complete(CallRequest(role="planner", system="s", prompt="p")))
    b = _run(StubProvider().complete(CallRequest(role="planner", system="s", prompt="p")))
    assert a.text == b.text and a.metering.usage == b.metering.usage
    for schema in (SCHEMA, {"type": "array", "items": {"type": "integer", "minimum": 3}, "minItems": 2},
                   {"anyOf": [{"type": "string", "minLength": 2}, {"type": "null"}]},
                   {"type": "object", "properties": {"n": {"type": "integer", "exclusiveMinimum": 0}},
                    "required": ["n"]}):
        jsonschema.validate(example_for(schema), schema)
    res = _run(StubProvider().complete(CallRequest(role="planner", system="s", prompt="p", schema=SCHEMA)))
    jsonschema.validate(res.data, SCHEMA)


def test_parse_json_answer_takes_the_last_valid_block() -> None:
    text = "```json\n" + json.dumps(BAD) + "\n```\nCorrected:\n```json\n" + json.dumps(GOOD) + "\n```"
    assert parse_json_answer(text, SCHEMA) == GOOD
    assert parse_json_answer("Sure: " + json.dumps(GOOD), SCHEMA) == GOOD
    with pytest.raises(llm.StructuredOutputError):
        parse_json_answer("no json here", SCHEMA)


def test_call_request_rejects_unknown_roles_and_image_types(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CallRequest(role="chatbot", system="s", prompt="p")
    with pytest.raises(ValueError):
        CallRequest(role="vision", system="s", prompt="p", images=(tmp_path / "drawing.pdf",))


# ================================================================== routing / configuration
def test_config_routes_roles_and_validates() -> None:
    assert llm.parse_config("default=stub, vision=anthropic-api") == {"default": "stub", "vision": "anthropic-api"}
    assert llm.parse_config("replay") == {"default": "replay"}
    for bad in ("vision=gpt", "chat=stub"):
        with pytest.raises(ValueError):
            llm.parse_config(bad)
    override_settings(Settings(env="development", llm_providers="default=stub,vision=anthropic-api"))
    assert llm.provider_name("planner") == "stub" and llm.provider_name("vision") == "anthropic-api"
    assert llm.get_provider("planner").name == "stub"
    override_settings(Settings(env="development", llm_providers=""))
    assert llm.provider_name("design_agent") == "claude-sdk"  # default: no behaviour change


def test_dev_only_providers_are_refused_in_production() -> None:
    override_settings(Settings(env="production", llm_providers="default=stub"))
    with pytest.raises(llm.ProviderError, match="development-only"):
        llm.get_provider("planner")
    with llm.use_provider(StubProvider()), pytest.raises(llm.ProviderError):
        llm.get_provider("planner")


def test_describe_lists_routing_and_capabilities_for_admins() -> None:
    d = llm.describe()
    assert set(d["routing"]) == set(llm.ROLES) and d["config_error"] is None
    assert d["providers"]["anthropic-api"]["capabilities"] == ["complete", "structured", "vision"]
    assert d["providers"]["stub"]["dev_only"] is True


# ================================================================== every call site goes through the provider
def test_every_model_call_site_routes_through_the_provider(tmp_path: Path) -> None:
    from aicad.airender import refine
    from aicad.assembly import librarian
    from aicad.drawing import draft_assist
    from aicad.image2cad import vision
    from aicad.office import gage, planner
    from aicad.platform.collab import reconcile

    (tmp_path / "vision.png").write_bytes(PNG)
    stub = StubProvider()
    with llm.use_provider(stub), metering.capture() as seen:
        outs = [
            _run(planner.run_agent(tmp_path, "Gearbox", "A small gearbox")),
            _run(planner.run_cr_review(tmp_path, "change?")),
            _run(gage.run_review(tmp_path, "review?")),
            _run(vision.run_agent(tmp_path, "vision.png", budget_usd=0.5)),
            _run(refine.run_refiner_agent("Polish.", "draft")),
            _run(draft_assist.run_agent("a 100 x 50 plate")),
            _run(librarian.ask_ai(["4 M6 bolts"], ["Plate"])),
            _run(reconcile.propose(tmp_path, [], {"name": "p"})),
        ]
    roles = [c.role for c in stub.calls]
    assert roles == ["planner", "change_review", "reviewer", "vision", "render_refine", "draft_assist", "librarian",
                     "reconcile"]
    assert [m.role for m in seen] == roles
    assert all(cost == 0.0 for _, cost in outs)
    assert stub.calls[3].images == (tmp_path / "vision.png",) and stub.calls[3].budget_usd == 0.5
    assert f"sha256 {PNG_SHA}" in outs[3][0]
    assert stub.calls[4].standalone_system is True  # the polish keeps its plain system text


def test_no_module_calls_a_model_sdk_directly() -> None:
    """Choke point: only the provider package talks to model SDKs. Exceptions are listed with their reason."""
    src = Path(__file__).resolve().parents[1] / "src" / "aicad"
    allowed = {
        "llm/claude_sdk.py": "the Claude Agent SDK provider",
        "llm/anthropic_api.py": "the Messages API provider",
        "agent/replay.py": "make_client / RecordingClient wrap the SDK client for the claude-sdk provider",
        "airender/provider.py": "OpenAI image generation (BYO key, PD-44): an image model, not an LLM call",
    }
    pat = re.compile(r"from claude_agent_sdk import[^\n]*\b(query|ClaudeSDKClient)\b|"
                     r"from claude_agent_sdk import \((?:[^)]*\b(query|ClaudeSDKClient)\b)[^)]*\)|"
                     r"^\s*import (anthropic|openai)\b|^\s*from (anthropic|openai)\b", re.MULTILINE)
    offenders = []
    for f in src.rglob("*.py"):
        rel = f.relative_to(src).as_posix()
        if rel in allowed:
            continue
        if pat.search(f.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == [], offenders


def test_an_answer_only_too_long_is_trimmed_not_thrown_away() -> None:
    """Benchmark A3: a 370-character summary against a limit of 300 lost a correct plan."""
    schema = {"type": "object", "required": ["summary", "items"], "properties": {
        "summary": {"type": "string", "maxLength": 10},
        "items": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 3}},
        "n": {"type": "integer"}}}
    got = parse_json_answer('```json\n{"summary": "much too long here", "items": ["abcd", "e", "f"]}\n```', schema)
    assert got == {"summary": "much too l", "items": ["abc", "e"]}
    with pytest.raises(llm.StructuredOutputError):  # any other violation still fails
        parse_json_answer('{"summary": "ok", "items": [], "n": "x"}', schema)
