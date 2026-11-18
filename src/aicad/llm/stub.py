"""AGT-013: a deterministic second provider (portability check, offline development, tests).

``StubProvider`` serves every capability without any network or model: answers are a pure function of the
request, so the same inputs always give the same text, JSON, token counts and (zero) cost. It passes the same
provider contract suite as the Claude providers (``tests/test_llm_providers.py``), which is the evidence that the
product code depends on the ``LLMProvider`` contract and not on one vendor.

* Text: ``responder(req)`` when given (per-role canned answers for demos), else a short deterministic note.
* Structured: the smallest JSON value that validates against the schema (``example_for``).
* Vision: the image bytes are read and fingerprinted in the answer (proves the image reached the provider).
* Agent sessions: a one-turn stand-in that yields the SDK message dataclasses (init, one text reply, result) and
  changes nothing in the workspace.

Development only: refused when ``FW_ENV=production``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import AsyncIterator, Callable
from typing import Any

from aicad.llm.base import (
    CAP_AGENT,
    CAP_COMPLETE,
    CAP_STRUCTURED,
    CAP_VISION,
    CallRequest,
    CallResult,
    LLMProvider,
    Metering,
    Usage,
)

STUB_MODEL = "stub-1"


def tokens_of(text: str) -> int:
    """A deterministic token estimate (4 characters per token, at least 1 for non-empty text)."""
    return math.ceil(len(text) / 4) if text else 0


def example_for(schema: dict[str, Any]) -> Any:
    """The smallest JSON value that validates against a (common subset of) JSON Schema."""
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for k in ("anyOf", "oneOf"):
        if schema.get(k):
            return example_for(schema[k][0])
    if schema.get("allOf"):
        out: dict[str, Any] = {}
        for s in schema["allOf"]:
            v = example_for(s)
            if isinstance(v, dict):
                out.update(v)
        return out
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object" or (t is None and "properties" in schema):
        props = schema.get("properties", {})
        return {k: example_for(props.get(k, {})) for k in schema.get("required", [])}
    if t == "array":
        return [example_for(schema.get("items", {})) for _ in range(int(schema.get("minItems", 0)))]
    if t == "string":
        return "x" * int(schema.get("minLength", 0))
    if t in ("number", "integer"):
        lo = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        v = lo + (1 if "exclusiveMinimum" in schema else 0)
        return int(v) if t == "integer" else float(v)
    if t == "boolean":
        return False
    return None


class StubProvider(LLMProvider):
    name = "stub"
    capabilities = frozenset({CAP_COMPLETE, CAP_STRUCTURED, CAP_VISION, CAP_AGENT})
    dev_only = True

    def __init__(self, responder: Callable[[CallRequest], str | None] | None = None) -> None:
        self.responder = responder
        self.calls: list[CallRequest] = []

    async def _complete(self, req: CallRequest) -> CallResult:
        self.calls.append(req)
        text = self.responder(req) if self.responder is not None else None
        data = None
        if text is None:
            if req.schema is not None:
                data = example_for(req.schema)
                text = "```json\n" + json.dumps(data, sort_keys=True) + "\n```"
            else:
                digest = hashlib.sha256((req.role + "\0" + req.system + "\0" + req.prompt).encode()).hexdigest()
                text = f"Stub answer for {req.role} ({digest[:12]})."
        if req.images:
            seen = []
            for p in req.images:
                b = p.read_bytes()
                seen.append(f"{p.name}: {len(b)} bytes, sha256 {hashlib.sha256(b).hexdigest()[:12]}")
            text += "\nImages read: " + "; ".join(seen)
        usage = Usage(input_tokens=tokens_of(req.system) + tokens_of(req.prompt) + 1000 * len(req.images),
                      output_tokens=tokens_of(text))
        return CallResult(text, Metering(self.name, req.role, req.model or STUB_MODEL, usage, 0.0, "none"), data)

    def agent_client(self, options: Any) -> Any:
        return StubAgentClient(options)


class StubAgentClient:
    """``ClaudeSDKClient``-shaped: one deterministic reply per query, no tools, no file changes."""

    def __init__(self, options: Any) -> None:
        self.options = options
        self.prompts: list[str] = []
        self._stop = False

    async def connect(self, prompt: Any = None) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def interrupt(self) -> None:
        self._stop = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.prompts.append(prompt)
        self._stop = False

    async def receive_response(self) -> AsyncIterator[Any]:
        from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock

        prompt = self.prompts[-1] if self.prompts else ""
        text = "This workspace runs an offline stand-in for the design agent, so no design was changed."
        usage = {"input_tokens": tokens_of(prompt), "output_tokens": tokens_of(text)}
        yield SystemMessage(subtype="init", data={"apiKeySource": "none"})
        if not self._stop:
            yield AssistantMessage(content=[TextBlock(text=text)], model=STUB_MODEL, usage=usage,
                                   message_id=f"stub-{len(self.prompts)}")
        yield ResultMessage(subtype="success", duration_ms=0, duration_api_ms=0, is_error=False, num_turns=1,
                            session_id=f"stub-session-{len(self.prompts)}", total_cost_usd=0.0, usage=usage)
