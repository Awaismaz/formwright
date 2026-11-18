"""Anthropic Messages API provider (official ``anthropic`` SDK, API-key billing). OFF by default.

Ties to PD-09 / AGT-015 (API-key auth before any non-founder user): this is the path single calls take once the
product bills an API key instead of the founder's Claude Code login. It is selected only by configuration
(``FW_LLM_PROVIDERS``, e.g. ``vision=anthropic-api``) and needs its own key in ``FW_LLM_ANTHROPIC_API_KEY`` (a
separate variable on purpose: the app strips ``ANTHROPIC_API_KEY`` in development so nothing bills by accident).

* Single calls: ``client.beta.messages.create`` with the system text, image blocks (base64) before the prompt, and
  for structured output ``output_config.format = json_schema`` (validated again on our side). Server-side refusal
  fallback is on (``fallbacks="default"``). A refusal raises ``ProviderError``.
* Agent sessions: not offered. The Studio agent relies on the Claude Code harness (file tools, hooks, sessions,
  ADR-013); a Messages-API tool loop is a separate piece of work (AGT-015 follow-up).
* Cost: estimated from the response's token usage at list prices (``agent/pricing.py``).

The ``anthropic`` package is imported lazily and is not a hard dependency yet; tests inject a fake client.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from aicad.llm.base import (
    CAP_COMPLETE,
    CAP_STRUCTURED,
    CAP_VISION,
    IMAGE_TYPES,
    CallRequest,
    CallResult,
    LLMProvider,
    Metering,
    ProviderError,
    Usage,
)

KEY_ENV = "FW_LLM_ANTHROPIC_API_KEY"
MODEL_ENV = "FW_LLM_ANTHROPIC_MODEL"
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
TIMEOUT_S = 120.0


class AnthropicAPIProvider(LLMProvider):
    name = "anthropic-api"
    capabilities = frozenset({CAP_COMPLETE, CAP_STRUCTURED, CAP_VISION})

    def __init__(self, client: Any = None, api_key: str | None = None, model: str | None = None) -> None:
        self._client = client
        self._key = api_key
        self.model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL

    def client(self) -> Any:
        if self._client is None:
            key = self._key or os.environ.get(KEY_ENV)
            if not key:
                raise ProviderError(f"the Anthropic API provider needs {KEY_ENV}")
            try:
                import anthropic
            except ImportError as e:  # not a hard dependency until AGT-015
                raise ProviderError("the 'anthropic' package is not installed") from e
            self._client = anthropic.AsyncAnthropic(api_key=key, timeout=TIMEOUT_S, max_retries=2)
        return self._client

    def request_body(self, req: CallRequest) -> dict[str, Any]:
        """The Messages API request for a call (public so tests can pin it without a network)."""
        content: list[dict[str, Any]] = []
        for p in req.images:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": IMAGE_TYPES[p.suffix.lower()],
                "data": base64.standard_b64encode(p.read_bytes()).decode("ascii")}})
        prompt = req.prompt
        if req.images:
            names = ", ".join(p.name for p in req.images)
            prompt = (f"The image file(s) {names} are attached to this message; wherever the instructions say to "
                      f"open or read them, use the attached image(s).\n\n{prompt}")
        content.append({"type": "text", "text": prompt})
        body: dict[str, Any] = {"model": req.model or self.model, "max_tokens": req.max_tokens,
                                "system": req.system, "messages": [{"role": "user", "content": content}],
                                "betas": [FALLBACK_BETA], "fallbacks": "default"}
        if req.schema is not None:
            body["output_config"] = {"format": {"type": "json_schema", "schema": req.schema}}
        return body

    async def _complete(self, req: CallRequest) -> CallResult:
        from aicad.agent.pricing import usage_cost_usd

        resp = await self.client().beta.messages.create(**self.request_body(req))
        if getattr(resp, "stop_reason", None) == "refusal":
            raise ProviderError("the model declined this request")
        text = "\n".join(b.text for b in getattr(resp, "content", []) or [] if getattr(b, "type", "") == "text")
        usage = Usage.from_any(getattr(resp, "usage", None))
        model = getattr(resp, "model", None) or req.model or self.model
        return CallResult(text, Metering(self.name, req.role, model, usage,
                                         usage_cost_usd(model, usage.as_dict()), "estimated"))
