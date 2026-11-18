"""Optional step of a merge: ask the design agent to reconcile conflicting changes.

`propose` is the only place that calls the model; tests replace it (no live agent calls). It sees the conflicting
values and design steps of both sides and returns one proposed resolution per conflict, which the person reviews
before merging (a proposal is never applied on its own). Cost is metered in tokens by the caller.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

INSTRUCTIONS = """You reconcile two versions of the same mechanical part that were changed in parallel: "main" and a
branch. For each conflict you get the common starting point ("base") and both versions. Propose ONE resolution per
conflict that keeps the intent of both changes where they are compatible, and otherwise prefers the branch (it is the
change under review). Never invent dimensions that neither side used. Reply with JSON only:
{"resolutions": {"<conflict id>": {"value": <number or null>} | {"text": "<merged lines>"} | {"pick": "ours"|"theirs"}},
 "note": "<one or two plain sentences for the engineer: what you chose and why>"}
Use "value" for parameter conflicts, "pick" for feature conflicts and "text" for design-source conflicts."""


async def propose(folder: Path, conflicts: list[dict[str, Any]], context: dict[str, Any],
                  budget_usd: float | None = None) -> tuple[dict[str, Any], float | None]:
    """Returns ({"resolutions": {...}, "note": str}, estimated cost in USD)."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    from aicad.agent.session import AGENT_BUFFER_BYTES

    folder.mkdir(parents=True, exist_ok=True)
    opts = ClaudeAgentOptions(
        cwd=str(folder), tools=[], allowed_tools=[], permission_mode="dontAsk",
        system_prompt={"type": "preset", "preset": "claude_code", "append": INSTRUCTIONS},
        setting_sources=[], max_turns=2, max_buffer_size=AGENT_BUFFER_BYTES)
    if budget_usd is not None:
        opts.max_budget_usd = max(0.01, budget_usd)
    prompt = json.dumps({"part": context, "conflicts": conflicts}, default=str, indent=1)
    texts: list[str] = []
    cost: float | None = None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            texts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd
    return parse("\n".join(texts)), cost


def parse(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"resolutions": {}, "note": "The design agent did not propose a resolution."}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {"resolutions": {}, "note": "The design agent's proposal could not be read."}
    res = data.get("resolutions") if isinstance(data.get("resolutions"), dict) else {}
    return {"resolutions": res, "note": str(data.get("note") or "")[:600]}


def to_resolution(conflict: dict[str, Any], proposal: Any) -> Any:
    """Turn one agent proposal into a `merge.merge_model` resolution (or None if unusable)."""
    if not isinstance(proposal, dict):
        return None
    if proposal.get("pick") in ("ours", "theirs"):
        return proposal["pick"]
    if conflict["kind"] == "param" and "value" in proposal:
        v = proposal["value"]
        if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            return {"value": v}
    if conflict["kind"] == "source" and isinstance(proposal.get("text"), str):
        return {"text": proposal["text"]}
    return None
