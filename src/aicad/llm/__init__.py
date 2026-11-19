"""LLM provider abstraction (AGT-001, AGT-013; ADR-009 as revised by ADR-013).

Every model call in Formwright goes through here::

    from aicad import llm
    res = await llm.complete(llm.CallRequest(role="planner", system=..., prompt=...))
    res.text, res.data, res.metering

and the Design Studio session gets its client from ``llm.get_provider("design_agent").agent_client(options)``.

Providers: ``claude-sdk`` (default; Claude Agent SDK), ``anthropic-api`` (Messages API, API key, off by default),
``stub`` (deterministic, offline; dev only), ``replay`` (recorded cassettes; dev only).

Configuration: ``FW_LLM_PROVIDERS`` = comma-separated ``role=provider`` pairs, ``default=`` for the rest, e.g.
``default=claude-sdk,vision=anthropic-api``. Server-side only; the UI never names a provider or model.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from aicad.llm.base import (
    CAP_AGENT,
    CAP_COMPLETE,
    CAP_STRUCTURED,
    CAP_VISION,
    ROLES,
    CallRequest,
    CallResult,
    CapabilityError,
    LLMProvider,
    Metering,
    ProviderError,
    StructuredOutputError,
    Usage,
)

__all__ = [
    "AI_OFF_MESSAGE",
    "CAP_AGENT",
    "CAP_COMPLETE",
    "CAP_STRUCTURED",
    "CAP_VISION",
    "DEFAULT_PROVIDER",
    "PROVIDER_NAMES",
    "ROLES",
    "AIDisabledError",
    "CallRequest",
    "CallResult",
    "CapabilityError",
    "LLMProvider",
    "Metering",
    "ProviderError",
    "StructuredOutputError",
    "Usage",
    "allow_ai",
    "complete",
    "describe",
    "get_provider",
    "parse_config",
    "provider_name",
    "use_provider",
]

DEFAULT_PROVIDER = "claude-sdk"
PROVIDER_NAMES = ("claude-sdk", "anthropic-api", "stub", "replay")
_instances: dict[str, LLMProvider] = {}
_overrides: dict[str, LLMProvider] = {}  # role (or "*") -> provider, tests and benchmarks only
# FW_AI_SUPERADMIN_ONLY: set per request by the platform (aicad.platform.deps.AIAccessMiddleware). None = no
# request context (CLI, tests, benchmarks): allowed. False = the signed-in person may not use AI.
_ai_allowed: ContextVar[bool | None] = ContextVar("fw_ai_allowed", default=None)
AI_OFF_MESSAGE = "AI features are turned off for this account."


class AIDisabledError(ProviderError):
    """A model call was attempted for a request whose user may not use AI (FW_AI_SUPERADMIN_ONLY)."""


def allow_ai(allowed: bool | None) -> None:
    """Whether model calls are allowed for the rest of this request (and the tasks it starts)."""
    _ai_allowed.set(allowed)


def _make(name: str) -> LLMProvider:
    if name == "claude-sdk":
        from aicad.llm.claude_sdk import ClaudeAgentSDKProvider

        return ClaudeAgentSDKProvider()
    if name == "anthropic-api":
        from aicad.llm.anthropic_api import AnthropicAPIProvider

        return AnthropicAPIProvider()
    if name == "stub":
        from aicad.llm.stub import StubProvider

        return StubProvider()
    if name == "replay":
        from aicad.llm.replay import ReplayProvider

        return ReplayProvider()
    raise ProviderError(f"unknown model provider {name!r}")


def parse_config(text: str) -> dict[str, str]:
    """``"default=claude-sdk, vision=stub"`` -> ``{"default": "claude-sdk", "vision": "stub"}`` (validated)."""
    out: dict[str, str] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        role, sep, name = (s.strip() for s in part.partition("="))
        if not sep:  # a bare name sets the default
            role, name = "default", role
        if role != "default" and role not in ROLES:
            raise ValueError(f"FW_LLM_PROVIDERS: unknown role {role!r}")
        if name not in PROVIDER_NAMES:
            raise ValueError(f"FW_LLM_PROVIDERS: unknown provider {name!r}")
        out[role] = name
    return out


def _config() -> dict[str, str]:
    from aicad.platform.config import get_settings

    return parse_config(get_settings().llm_providers)


def provider_name(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown model role {role!r}")
    cfg = _config()
    return cfg.get(role) or cfg.get("default") or DEFAULT_PROVIDER


def get_provider(role: str) -> LLMProvider:
    """The provider configured for ``role``. Development-only providers are refused in production."""
    from aicad.platform.config import get_settings

    if role not in ROLES:
        raise ValueError(f"unknown model role {role!r}")
    if _ai_allowed.get() is False:
        raise AIDisabledError(AI_OFF_MESSAGE)
    p = _overrides.get(role) or _overrides.get("*")
    if p is None:
        name = provider_name(role)
        p = _instances.get(name)
        if p is None:
            p = _instances[name] = _make(name)
    if p.dev_only and get_settings().production:
        raise ProviderError(f"the {p.name} provider is development-only")
    return p


async def complete(req: CallRequest) -> CallResult:
    return await get_provider(req.role).complete(req)


@contextmanager
def use_provider(provider: LLMProvider, roles: tuple[str, ...] | None = None) -> Iterator[LLMProvider]:
    """Route ``roles`` (default: every role) to ``provider`` inside the block. Tests and benchmarks only."""
    keys = list(roles) if roles else ["*"]
    saved = {k: _overrides.get(k) for k in keys}
    for k in keys:
        _overrides[k] = provider
    try:
        yield provider
    finally:
        for k, v in saved.items():
            if v is None:
                _overrides.pop(k, None)
            else:
                _overrides[k] = v


def describe() -> dict[str, Any]:
    """Role -> provider routing and capabilities (super-admin console only; never shown to users)."""
    from aicad.llm import metering

    try:
        routing = {r: provider_name(r) for r in ROLES}
        error = None
    except ValueError as e:
        routing, error = {}, str(e)
    from aicad.llm.anthropic_api import AnthropicAPIProvider
    from aicad.llm.claude_sdk import ClaudeAgentSDKProvider
    from aicad.llm.replay import ReplayProvider
    from aicad.llm.stub import StubProvider

    caps = {k.name: {"capabilities": sorted(k.capabilities), "dev_only": bool(k.dev_only)}
            for k in (ClaudeAgentSDKProvider, AnthropicAPIProvider, StubProvider, ReplayProvider)}
    return {"routing": routing, "config_error": error, "providers": caps, "recent_calls": metering.recent(20)}
