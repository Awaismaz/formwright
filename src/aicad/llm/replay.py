"""The recorded/replay provider (AGT-002) behind ``LLMProvider``: zero model calls.

* Agent sessions: ``agent.replay.ReplayClient`` on a cassette (unchanged format).
* Single calls: the cassette's optional ``"calls"`` list::

      {"calls": [{"role": "planner", "match": "regex on the prompt (optional)", "text": "...",
                  "model": "claude-...", "usage": {...}, "cost_usd": 0.0012}]}

  The first unused entry of the request's role whose ``match`` fits is replayed (entries without ``match`` are used
  in order). No match raises ``ProviderError``; call sites fall back exactly as when a live call fails.

Development only: refused when ``FW_ENV=production``.
"""

from __future__ import annotations

import json
import os
import re
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
    ProviderError,
    Usage,
)


class ReplayProvider(LLMProvider):
    name = "replay"
    capabilities = frozenset({CAP_COMPLETE, CAP_STRUCTURED, CAP_VISION, CAP_AGENT})
    dev_only = True

    def __init__(self, cassette: dict[str, Any] | Path | str | None = None) -> None:
        from aicad.agent.replay import REPLAY_ENV, load_cassette

        if cassette is None:
            env = os.environ.get(REPLAY_ENV)
            if not env:
                raise ProviderError(f"the replay provider needs a cassette ({REPLAY_ENV})")
            cassette = Path(env)
        if not isinstance(cassette, dict):
            path = Path(cassette)
            data = load_cassette(path)
            files = sorted(path.glob("*.json")) if path.is_dir() else [path]
            calls: list[dict[str, Any]] = []
            for f in files:
                raw = json.loads(f.read_text(encoding="utf-8"))
                calls += raw.get("calls", []) if isinstance(raw, dict) else []
            data["calls"] = calls
            cassette = data
        self.cassette = cassette
        self._used: set[int] = set()

    def agent_client(self, options: Any) -> Any:
        from aicad.agent.replay import ReplayClient

        return ReplayClient(options, self.cassette)

    def _pick(self, req: CallRequest) -> dict[str, Any]:
        calls = [c for c in self.cassette.get("calls", []) if isinstance(c, dict)]
        for want_match in (True, False):
            for i, c in enumerate(calls):
                if i in self._used or c.get("role") != req.role or bool(c.get("match")) is not want_match:
                    continue
                if want_match and not re.search(c["match"], req.prompt, re.DOTALL | re.IGNORECASE):
                    continue
                self._used.add(i)
                return c
        raise ProviderError(f"no recorded call for role {req.role!r}")

    async def _complete(self, req: CallRequest) -> CallResult:
        c = self._pick(req)
        usage = Usage.from_any(c.get("usage"))
        cost = c.get("cost_usd")
        return CallResult(str(c.get("text", "")), Metering(
            self.name, req.role, c.get("model") or "replay", usage,
            float(cost) if isinstance(cost, int | float) else 0.0, "reported" if cost is not None else "none"))
