"""The Claude Agent SDK provider (default): the Claude Code harness behind ``LLMProvider``.

* Agent sessions: ``agent_client(options)`` returns the SDK client exactly as before (``agent.replay.make_client``,
  which still honours ``FW_AGENT_REPLAY`` / ``FW_AGENT_RECORD`` in development). No behaviour change.
* Single calls: one ``claude_agent_sdk.query`` with no tools (or the ``Read`` tool confined to the image folder for
  vision), the role's instructions appended to the ``claude_code`` preset, ``setting_sources=[]``, an optional hard
  budget. This is the same option set every call site used before AGT-001.

Auth is whatever the SDK resolves (development: the local Claude Code login; R-LIC-05 / PD-09 for production).
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
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
    image_hint,
    schema_instruction,
)

QueryFn = Callable[..., AsyncIterator[Any]]


class ClaudeAgentSDKProvider(LLMProvider):
    name = "claude-sdk"
    capabilities = frozenset({CAP_COMPLETE, CAP_STRUCTURED, CAP_VISION, CAP_AGENT})

    def __init__(self, query_fn: QueryFn | None = None, client_factory: Callable[[Any], Any] | None = None) -> None:
        self._query_fn = query_fn  # tests inject a scripted stand-in; None = claude_agent_sdk.query
        self._client_factory = client_factory

    # ------------------------------------------------------------ sessions
    def agent_client(self, options: Any) -> Any:
        if self._client_factory is not None:
            return self._client_factory(options)
        from aicad.agent.replay import make_client

        return make_client(options)

    # ------------------------------------------------------------ single calls
    def options_for(self, req: CallRequest, cwd: Path) -> Any:
        """The ``ClaudeAgentOptions`` of a single call (public so tests can pin the option set)."""
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

        from aicad.agent.session import AGENT_BUFFER_BYTES, make_guard

        system = req.system + (schema_instruction(req.schema) if req.schema is not None else "")
        tools = ["Read"] if req.images else []
        kw: dict[str, Any] = {}
        if req.images:
            kw["hooks"] = {"PreToolUse": [HookMatcher(matcher="Read", hooks=[make_guard(cwd)])]}
        opts = ClaudeAgentOptions(
            cwd=str(cwd), tools=tools, allowed_tools=list(tools), permission_mode="dontAsk",
            system_prompt=system if req.standalone_system else
            {"type": "preset", "preset": "claude_code", "append": system},
            setting_sources=[], max_turns=max(req.max_turns, 2 if req.images else 1),
            max_buffer_size=AGENT_BUFFER_BYTES, **kw)
        if req.budget_usd is not None:
            opts.max_budget_usd = max(0.01, req.budget_usd)
        if req.model:
            opts.model = req.model
        return opts

    async def _complete(self, req: CallRequest) -> CallResult:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        from aicad.agent.pricing import usage_cost_usd

        query = self._query_fn
        if query is None:
            from claude_agent_sdk import query

        tmp = None
        cwd = req.cwd
        if req.images:
            folder = cwd or req.images[0].resolve().parent
            for p in req.images:
                rp = p.resolve()
                if folder.resolve() not in rp.parents:
                    raise ValueError("images must be inside the call's folder")
            cwd = folder
        if cwd is None:
            tmp = tempfile.TemporaryDirectory(prefix="fw-llm-")
            cwd = Path(tmp.name)
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            texts: list[str] = []
            model: str | None = None
            per_msg: dict[str, Usage] = {}
            result_usage: Usage | None = None
            cost: float | None = None
            async for msg in query(prompt=image_hint(req) + req.prompt, options=self.options_for(req, cwd)):
                if isinstance(msg, AssistantMessage):
                    texts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
                    model = msg.model or model
                    if msg.usage:
                        per_msg[msg.message_id or f"m{len(per_msg)}"] = Usage.from_any(msg.usage)
                elif isinstance(msg, ResultMessage):
                    cost = msg.total_cost_usd
                    if msg.usage:
                        result_usage = Usage.from_any(msg.usage)
        finally:
            if tmp is not None:
                tmp.cleanup()
        usage = result_usage or Usage(*(sum(getattr(u, f) for u in per_msg.values()) for f in
                                        ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                         "cache_read_input_tokens")))
        if cost is not None:
            src = "reported"
        elif usage.total:
            cost, src = usage_cost_usd(model, usage.as_dict()), "estimated"
        else:
            src = "none"
        return CallResult("\n".join(texts), Metering(self.name, req.role, model or req.model, usage, cost, src))
