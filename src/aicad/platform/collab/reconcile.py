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
    """Returns ({"resolutions": {...}, "note": str}, estimated cost in USD). Via the LLM provider (AGT-001)."""
    from aicad import llm

    prompt = json.dumps({"part": context, "conflicts": conflicts}, default=str, indent=1)
    res = await llm.complete(llm.CallRequest(role="reconcile", system=INSTRUCTIONS, prompt=prompt, max_turns=2,
                                             budget_usd=budget_usd, cwd=folder))
    return parse(res.text), res.metering.cost_usd


def parse(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"resolutions": {}, "note": "The design agent did not propose a resolution."}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {"resolutions": {}, "note": "The design agent's proposal could not be read."}
    from aicad.agent.session import scrub

    res = data.get("resolutions") if isinstance(data.get("resolutions"), dict) else {}
    return {"resolutions": res, "note": scrub(str(data.get("note") or ""))[:600]}  # no internals in the UI


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
