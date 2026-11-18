"""Prompt refinement layer: settings + the user's words + facts about the part -> one precise image prompt.

Two engines, same output shape `{"prompt", "negative", "engine", "note"}`:
- `compose()`  the deterministic template composer (the default, and the fallback whenever the AI polish is
               unavailable). Same inputs -> same prompt, byte for byte.
- `polish()`   a short one-shot Claude call (no tools, one turn) through the Claude Agent SDK, which rewrites the
               template into a tighter photographer's brief. Its output is parsed from a fenced block; anything
               unusable falls back to the template.

Whatever the engine (and whatever the user edits), `guarded()` re-inserts the geometry-preservation clause and the
negative-instruction section before the prompt is sent to OpenAI, so they can't be lost.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from aicad.airender import options

GEOMETRY_CLAUSE = ("Use the attached reference image as the exact geometry of the part. Keep the exact shape, "
                   "silhouette, holes, slots, edges and proportions; do not add, remove, merge, move or resize any "
                   "feature; keep the number and position of holes exactly as in the reference.")
NEGATIVE_BASE = [
    "no added or missing features, holes, ribs, fillets, threads or fasteners",
    "no change to the proportions or the outline of the part",
    "no text, logos, labels, watermarks or dimensions",
    "no extra copies of the part",
    "no warped, melted or blurred edges",
]
MAX_PROMPT = 4000
_ASKS_TEXT = re.compile(r"\b(text|logo|label|lettering|engrav\w*|brand\w*|wordmark|caption)\b", re.IGNORECASE)
_BLOCK = re.compile(r"```(?:fw-prompt|json)?\s*\n(.*?)\n?```", re.DOTALL)


# ------------------------------------------------------------------ part facts
def part_facts(ws: Path, name: str) -> dict[str, Any]:
    """What the prompt may say about the part: name, material, overall size and named features (from status.json)."""
    try:
        st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    bb = st.get("bbox_minmax")
    size = None
    if isinstance(bb, list) and len(bb) == 6:
        size = [round(abs(float(bb[i + 3]) - float(bb[i])), 1) for i in range(3)]
    feats = []
    for f in st.get("features") or []:
        if isinstance(f, dict) and not f.get("suppressed") and f.get("name"):
            n = str(f["name"]).strip()
            if n and n not in feats:
                feats.append(n[:60])
    material = st.get("material")
    if not isinstance(material, str) or material.lower() in ("unspecified", ""):
        material = None
    return {"name": (str(st.get("part") or "").replace("_", " ").strip() or name)[:80], "material": material,
            "size_mm": size, "features": feats[:8], "build_id": st.get("build_id")}


def _size_text(size: list[float] | None) -> str | None:
    if not size:
        return None
    return " × ".join(f"{v:g}" for v in size) + " mm"


# ------------------------------------------------------------------ template engine
def negatives(settings: options.Settings, user_prompt: str = "") -> list[str]:
    out = list(NEGATIVE_BASE)
    if _ASKS_TEXT.search(user_prompt or ""):
        out = [n for n in out if not n.startswith("no text")]
    if settings.scene != "in_hand":
        out.append("no people or hands")
    if settings.scene == "catalogue":
        out.append("do not split the part into pieces")
    return out


def compose(facts: dict[str, Any], settings: options.Settings, user_prompt: str = "") -> dict[str, Any]:
    s = settings
    subject = facts.get("name") or "the mechanical part"
    finish = s.finish or (facts.get("material") and f"{facts['material']}") or "its engineering material"
    parts = [
        f"{options.STYLES[s.style]['prompt'][0].upper()}{options.STYLES[s.style]['prompt'][1:]}.",
        f"Subject: {subject}, an engineered mechanical part (the part in the reference image).",
        f"Scene: {options.SCENES[s.scene]['prompt']}.",
        f"Material and finish: {finish}.",
        f"Lighting: {options.LIGHTING[s.lighting]['prompt']}.",
        f"Camera: {options.CAMERAS[s.camera]['prompt']}.",
        f"Background: {options.BACKGROUNDS[s.background]['prompt']}.",
    ]
    size = _size_text(facts.get("size_mm"))
    if size:
        parts.append(f"The real part measures about {size}; keep everything around it at a consistent scale.")
    if facts.get("features"):
        parts.append("Its modelled features include: " + "; ".join(facts["features"]) + ".")
    if (user_prompt or "").strip():
        parts.append("Additional direction: " + " ".join(user_prompt.split())[:options.MAX_USER_PROMPT] + ".")
    parts.append(GEOMETRY_CLAUSE)
    return {"prompt": "\n".join(parts), "negative": negatives(s, user_prompt), "engine": "template", "note": None}


def guarded(prompt: str, negative: list[str] | None) -> str:
    """The text sent to OpenAI: the (possibly edited) prompt with the geometry clause guaranteed and the
    negative-instruction section appended."""
    body = (prompt or "").strip()[:MAX_PROMPT]
    if GEOMETRY_CLAUSE not in body:
        body = (body + "\n" + GEOMETRY_CLAUSE).strip()
    negs = [" ".join(str(n).split())[:160] for n in (negative or []) if str(n).strip()][:12]
    if not any(n.startswith("no added or missing features") for n in negs):
        negs.insert(0, NEGATIVE_BASE[0])
    return body + "\n\nAvoid: " + "; ".join(negs) + "."


# ------------------------------------------------------------------ Claude polish (one shot, no tools)
POLISH_SYSTEM = """You write prompts for an image model that EDITS a reference photo of a real engineered part.
Rewrite the draft brief into one precise, vivid image prompt of 80-180 words for a marketing visual.
Rules: keep every setting in the draft (scene, finish, lighting, camera, background, style, size, user direction);
never invent features, dimensions, text or logos; keep the sentence that starts "Use the attached reference image"
word for word at the end. Answer with only a fenced block:
```fw-prompt
{"prompt": "...", "negative": ["no ...", "..."]}
```"""


async def run_refiner_agent(system: str, prompt: str) -> tuple[str, float | None]:
    """One Claude turn, no tools. Returns (text, cost USD). Tests replace this function (no live calls)."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    opts = ClaudeAgentOptions(tools=[], allowed_tools=[], permission_mode="dontAsk", system_prompt=system,
                              setting_sources=[], max_turns=1)
    texts: list[str] = []
    cost: float | None = None
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            texts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd
    return "\n".join(texts), cost


def parse_polish(text: str) -> dict[str, Any] | None:
    """{"prompt", "negative"} from the agent's fenced block (or bare JSON), else None."""
    m = _BLOCK.findall(text or "")
    raw = m[-1] if m else (text or "").strip()
    try:
        d = json.loads(raw)
    except ValueError:
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e <= s:
            return None
        try:
            d = json.loads(raw[s:e + 1])
        except ValueError:
            return None
    if not isinstance(d, dict) or not isinstance(d.get("prompt"), str) or len(d["prompt"].strip()) < 20:
        return None
    neg = d.get("negative")
    neg = [str(n).strip()[:160] for n in neg if str(n).strip()] if isinstance(neg, list) else []
    return {"prompt": d["prompt"].strip()[:MAX_PROMPT], "negative": neg[:12]}


def _fake_polish(draft: dict[str, Any]) -> str:
    """FW_AI_RENDER_FAKE: a canned polish so the walkthrough runs without calling Claude."""
    body = draft["prompt"].replace(GEOMETRY_CLAUSE, "").strip()
    return "```fw-prompt\n" + json.dumps({"prompt": "Polished brief. " + body + "\n" + GEOMETRY_CLAUSE,
                                          "negative": draft["negative"]}) + "\n```"


async def polish(facts: dict[str, Any], settings: options.Settings, user_prompt: str = "",
                 timeout_s: float = 60.0) -> tuple[dict[str, Any], float | None]:
    """AI-polished prompt, or the template with a note when the polish is unavailable. Returns (result, cost USD)."""
    from aicad.airender import provider

    draft = compose(facts, settings, user_prompt)
    ask = ("Draft brief:\n" + draft["prompt"] + "\n\nNegative instructions:\n- " + "\n- ".join(draft["negative"]))
    try:
        if provider.fake_mode():
            text, cost = _fake_polish(draft), 0.0
        else:
            text, cost = await asyncio.wait_for(run_refiner_agent(POLISH_SYSTEM, ask), timeout_s)
    except Exception:  # noqa: BLE001  # agent unavailable, timed out or failed: the template is always a valid answer
        return {**draft, "note": "The AI polish isn't available right now, so this is the standard template."}, None
    got = parse_polish(text)
    if got is None:
        return {**draft, "note": "The AI polish didn't return a usable prompt, so this is the standard template."}, \
            cost
    prompt = got["prompt"]
    if GEOMETRY_CLAUSE not in prompt:
        prompt = prompt.rstrip() + "\n" + GEOMETRY_CLAUSE
    negs = list(draft["negative"])  # the template's negatives always stay; the agent may add more
    negs += [n for n in got["negative"] if n not in negs]
    return {"prompt": prompt, "negative": negs[:12], "engine": "ai", "note": None}, cost
