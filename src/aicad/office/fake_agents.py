"""Simulated agents for development and tests (never on by default, refused in production).

``FakeClient`` stands in for the model client of a real ``AgentSession`` (through ``client_factory``, the same hook
the record/replay provider uses), so the whole Studio path runs for real: the session publishes events, the
platform meters the run and snapshots the build, and the Design Office derives milestones from those events. The
fake "designs" a tiny valid part: a block sized from the sizes in the ticket brief, exported to STEP with a status
report, then a self-review block. ``fake_review`` replaces Gage's AI note.

Behaviour can be scripted per ticket (``SCRIPT``: regex on the brief -> what to do) so tests and the walkthrough can
show a send-back, a failed build, a rate limit, or a run that waits on an event.

Enable for a dev server with ``FW_OFFICE_FAKE_AGENTS=1`` (optionally ``FW_OFFICE_FAKE_DELAY`` seconds per step and
``FW_OFFICE_FAKE_DEFECTS`` = a regex: matching tickets omit a brief size on their first build).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from aicad.office import gage

ENV = "FW_OFFICE_FAKE_AGENTS"
SCRIPT: list[tuple[str, dict[str, Any]]] = []  # (regex on the ticket brief, behaviour) - tests set this
STATS: dict[str, Any] = {"active": 0, "max_active": 0, "prompts": []}
COST_USD = 0.3  # 30 tokens per fake turn


def enabled() -> bool:
    if os.environ.get(ENV, "") not in ("1", "true", "yes"):
        return False
    from aicad.platform.config import get_settings

    return not get_settings().production


def delay() -> float:
    try:
        return float(os.environ.get("FW_OFFICE_FAKE_DELAY", "0"))
    except ValueError:
        return 0.0


def behaviour(brief: str) -> dict[str, Any]:
    for rx, b in SCRIPT:
        if re.search(rx, brief, re.IGNORECASE | re.DOTALL):
            return b
    rx = os.environ.get("FW_OFFICE_FAKE_DEFECTS")
    if rx and re.search(rx, brief, re.IGNORECASE):
        return {"omit_turns": 1}
    return {}


def reset() -> None:
    SCRIPT.clear()
    STATS.update(active=0, max_active=0, prompts=[])


def _write_part(ws: Path, name: str, dims: list[float], extra: list[float]) -> dict[str, Any]:
    from build123d import Box, export_step

    L, W, H = (dims + [40.0, 30.0, 10.0][len(dims):])[:3]
    out = ws / "out"
    out.mkdir(parents=True, exist_ok=True)
    lines = [f'NAME = "{name}"', 'MATERIAL = "Aluminium 6061-T6"', f"LENGTH = {L:g}", f"WIDTH = {W:g}",
             f"HEIGHT = {H:g}"] + [f"SIZE_{i + 1} = {v:g}" for i, v in enumerate(extra)]
    params = {"LENGTH": L, "WIDTH": W, "HEIGHT": H, **{f"SIZE_{i + 1}": v for i, v in enumerate(extra)}}
    src = "\n".join(lines) + f"\nPARAMS = dict({', '.join(f'{k}={k}' for k in params)})\n\nfrom build123d import *\n" \
        "result = Box(LENGTH, WIDTH, HEIGHT)\nEXPECTED = {'bbox': [LENGTH, WIDTH, HEIGHT], 'solids': 1}\n"
    (ws / "model.py").write_text(src, encoding="utf-8")
    export_step(Box(L, W, H), str(out / "part.step"))
    checks = [{"id": c, "name": n, "passed": True, "gating": True} for c, n in (
        ("CHK-02", "valid B-rep, solid count"), ("CHK-03", "closed manifold (no free edges)"),
        ("CHK-04", "bounding box"), ("CHK-07", "STEP export -> reimport"))]
    st = {"ok": True, "part": name, "material": "Aluminium 6061-T6", "build_id": uuid.uuid4().hex[:12],
          "params": params, "checks": checks, "fingerprint": {"bbox": [L, W, H], "volume": L * W * H, "solids": 1},
          "expected": {"bbox": [L, W, H]}}
    (out / "status.json").write_text(json.dumps(st), encoding="utf-8")
    return st


class FakeClient:
    """Drop-in for the SDK client: one scripted, deterministic turn per query. Zero model calls."""

    def __init__(self, options: Any) -> None:
        self.workspace = Path(getattr(options, "cwd", None) or ".").resolve()
        self.turns = 0
        self.cost = 0.0
        self.brief = ""
        self._prompt = ""
        self._stop = False

    async def connect(self, prompt: Any = None) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def interrupt(self) -> None:
        self._stop = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self._prompt, self._stop = prompt, False
        m = re.search(r"Ticket [A-Z0-9]+-\d+: (.*)", prompt, re.DOTALL)
        if m:
            self.brief = m.group(1)
        STATS["prompts"].append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
        )

        self.turns += 1
        b = behaviour(self.brief)
        step = float(b.get("delay", delay()))
        usage = {"input_tokens": 1000, "output_tokens": 200}
        STATS["active"] += 1
        STATS["max_active"] = max(STATS["max_active"], STATS["active"])
        try:
            yield SystemMessage(subtype="init", data={"apiKeySource": "none"})
            gate = b.get("gate")  # a threading.Event the test (or demo) releases
            while gate is not None and not gate.is_set() and not self._stop:
                await asyncio.sleep(0.02)
            if self.turns <= int(b.get("rate_limit_turns", 0)):
                yield AssistantMessage(content=[TextBlock(text="API Error: 429 rate limit reached, try again later")],
                                       model="fake", usage=None)
                yield ResultMessage(subtype="error_during_execution", duration_ms=10, duration_api_ms=10,
                                    is_error=True, num_turns=1, session_id="fake", total_cost_usd=self.cost)
                return
            yield AssistantMessage(content=[TextBlock(text="Reading the brief and sizing the stock.")], model="fake",
                                   usage=usage, message_id=f"m{self.turns}a")
            await asyncio.sleep(step)
            if self._stop:
                yield ResultMessage(subtype="error_during_execution", duration_ms=10, duration_api_ms=10,
                                    is_error=True, num_turns=1, session_id="fake", total_cost_usd=self.cost)
                return
            yield AssistantMessage(content=[ToolUseBlock(id=f"b{self.turns}", name="mcp__cad__build_model",
                                                         input={})], model="fake", usage=None,
                                   message_id=f"m{self.turns}a")
            await asyncio.sleep(step)
            fail = self.turns <= int(b.get("fail_turns", 0))
            dims = [v for _l, v in gage.brief_dimensions(gage.ticket_text({"brief": self.brief}))]
            if self.turns <= int(b.get("omit_turns", 0)) and dims:
                dims = dims[1:]
            if b.get("never_dims"):
                dims = []
            box = sorted(dims, reverse=True)[:3]
            extra = [v for v in dims if v not in box]
            name = (re.match(r"Design the (.+?)(?: \(\d+ off\))? for", self.brief) or [None, "Part"])[1]
            if fail:
                st = {"ok": False, "error": "BuildError: fillet failed", "checks": []}
                (self.workspace / "out").mkdir(parents=True, exist_ok=True)
                (self.workspace / "out" / "status.json").write_text(json.dumps(st), encoding="utf-8")
                report = "BUILD FAILED: fillet failed"
            else:
                await asyncio.to_thread(_write_part, self.workspace, name, box, extra)
                report = "Build OK. All gating checks pass."
            yield UserMessage(content=[ToolResultBlock(tool_use_id=f"b{self.turns}",
                                                       content=[{"type": "text", "text": report}], is_error=fail)])
            await asyncio.sleep(step)
            review = {"observed": [{"text": "Envelope matches the brief sizes", "basis": "CHK-04"}], "uncertain": []}
            text = "Done." if fail else "Built and checked.\n```fw-review\n" + json.dumps(review) + "\n```"
            yield AssistantMessage(content=[TextBlock(text=text)], model="fake", usage=usage,
                                   message_id=f"m{self.turns}b")
            self.cost += COST_USD
            yield ResultMessage(subtype="success", duration_ms=int(step * 3000) + 5, duration_api_ms=5,
                                is_error=False, num_turns=2, session_id="fake", total_cost_usd=self.cost)
        finally:
            STATS["active"] -= 1


async def fake_review(folder: Path, prompt: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """Gage's AI note in simulated mode: approves (scripted send-backs come from ``SCRIPT`` 'gage_changes')."""
    for rx, b in SCRIPT:
        if b.get("gage_changes") and re.search(rx, prompt, re.IGNORECASE | re.DOTALL) and b["gage_changes"] > 0:
            b["gage_changes"] -= 1
            note = ('Two edges need attention.\n```fw-gage\n{"verdict": "changes", "findings": '
                    '["Break the outer edges with a 0.5 mm chamfer as the brief asks."]}\n```')
            return note, 0.05
    await asyncio.sleep(delay() / 2)
    return 'Meets the brief.\n```fw-gage\n{"verdict": "approve", "findings": []}\n```', 0.05
