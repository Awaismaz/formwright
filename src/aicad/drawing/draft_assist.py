"""Drafting assist (DRW-017): turn a plain request into 2D entities and dimensions placed on the sheet for the user to
edit. Deterministic first: ``draft_templates.read_prompt`` handles gaskets, washers and plates with holes without
AI. Only when that fails is the design agent asked, and it may only answer with a template and its parameters or a
short list of basic shapes (lines, circles, rectangles) in one fenced ``fw-draft`` block. Its answer is validated
and turned into geometry by the same deterministic code, and every dimension is measured from that geometry, so a
size is never accepted just because the model wrote it. ``run_agent`` is the only function that calls the model;
tests replace it. Tolerances, surface finish and GD&T are never added by the assist.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from aicad.drawing import DrawingInputError
from aicad.drawing import draft_templates as T

INSTRUCTIONS = """You help a mechanical engineer start a 2D drawing. You never invent sizes that are not in the \
request, and you never add tolerances, surface finish or geometric tolerances. Plain engineering language. Answer \
with exactly one fenced block tagged fw-draft and nothing after it."""

PROMPT = """The engineer asked: {request!r}

Answer with exactly one fenced block:

```fw-draft
{{"template": "gasket" | "washer" | "plate" | null,
 "params": {{...}},
 "shapes": [{{"type": "circle", "c": [x, y], "d": 20}},
            {{"type": "rect", "c": [x, y], "w": 100, "h": 50}},
            {{"type": "line", "a": [x, y], "b": [x, y]}}],
 "missing": ["a size the request does not give, in plain words"]}}
```

Templates and their parameters (millimetres, part centred on 0,0):
- gasket: od, id, holes (count), hole_d, pcd, start (angle of the first hole in degrees)
- washer: od, id
- plate: length, width, hole_d, nx, ny (hole grid), edge_x, edge_y (hole centre from the end / side), corner_r
Use a template when the part is one of these; otherwise use "shapes" (at most 60). Use only sizes given in the \
request; list anything else that is needed in "missing" instead of guessing."""

_BLOCK = re.compile(r"```(?:fw-draft|json)?\s*\n(.*?)\n?```", re.DOTALL)
MAX_SHAPES = 60


async def run_agent(request: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One tool-less turn of the design agent's model. Returns (assistant text, cost in USD)."""
    from aicad import llm

    res = await llm.complete(llm.CallRequest(role="draft_assist", system=INSTRUCTIONS,
                                             prompt=PROMPT.format(request=request[:400]), budget_usd=budget_usd))
    return res.text, res.metering.cost_usd


def parse_block(text: str) -> dict[str, Any] | None:
    blocks = _BLOCK.findall(text or "")
    for raw in reversed(blocks or [text or ""]):
        try:
            v = json.loads(raw.strip())
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return None


def _f(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise DrawingInputError("The assist answer had a size that is not a number") from None
    if not math.isfinite(f) or abs(f) > 1e5:
        raise DrawingInputError("The assist answer had a size out of range")
    return f


def shapes_fragment(shapes: list[dict[str, Any]], k: float, prefix: str) -> dict[str, Any]:
    """Basic shapes -> entities with associative dimensions (Ø for circles, width and height for rectangles)."""
    f = T.Frag(prefix)
    off = 10.0 / k
    xs: list[float] = []
    ys: list[float] = []
    for s in shapes[:MAX_SHAPES]:
        t = s.get("type")
        if t == "circle":
            cx, cy = _f(s["c"][0]), _f(s["c"][1])
            d = _f(s.get("d"))
            if d <= 0:
                raise DrawingInputError("A circle needs a positive diameter")
            e = f.circle(f.pt(cx, cy), d / 2)
            f.anno(type="centermark", ent=e)
            f.dim(type="diameter", ent=e, pos=[cx + d / 2 + off, cy + d / 2 + off])
            xs += [cx - d / 2, cx + d / 2]
            ys += [cy - d / 2, cy + d / 2]
        elif t == "rect":
            cx, cy, w, h = _f(s["c"][0]), _f(s["c"][1]), _f(s.get("w")), _f(s.get("h"))
            if w <= 0 or h <= 0:
                raise DrawingInputError("A rectangle needs a positive width and height")
            A, B = f.pt(cx - w / 2, cy - h / 2), f.pt(cx + w / 2, cy - h / 2)
            C, D = f.pt(cx + w / 2, cy + h / 2), f.pt(cx - w / 2, cy + h / 2)
            for a, b in ((A, B), (B, C), (C, D), (D, A)):
                f.line(a, b)
            f.dim(type="linear", orient="h", a=A, b=B, pos=[cx, cy - h / 2 - off * 1.5])
            f.dim(type="linear", orient="v", a=A, b=D, pos=[cx - w / 2 - off * 1.5, cy])
            xs += [cx - w / 2, cx + w / 2]
            ys += [cy - h / 2, cy + h / 2]
        elif t == "line":
            a, b = (_f(s["a"][0]), _f(s["a"][1])), (_f(s["b"][0]), _f(s["b"][1]))
            if math.dist(a, b) < 1e-6:
                continue
            f.line(f.pt(*a), f.pt(*b))
            xs += [a[0], b[0]]
            ys += [a[1], b[1]]
    if not f.entities:
        raise DrawingInputError("The request did not describe any geometry")
    return f.out(extent=[max(xs) - min(xs), max(ys) - min(ys)])


def interpret(answer: dict[str, Any], k: float, prefix: str) -> dict[str, Any]:
    """Validated fragment from the agent's structured answer."""
    name = answer.get("template")
    if name in T.TEMPLATES:
        params = {kk: v for kk, v in (answer.get("params") or {}).items() if kk in T.TEMPLATES[name]["params"]}
        frag = T.generate(name, params, k, prefix)
    else:
        shapes = answer.get("shapes")
        if not isinstance(shapes, list) or not shapes:
            raise DrawingInputError("The request could not be turned into a drawing. Try a gasket, washer or plate, "
                                    "or describe the shapes with their sizes.")
        frag = shapes_fragment(shapes, k, prefix)
    missing = [str(m)[:120] for m in (answer.get("missing") or [])[:6] if str(m).strip()]
    frag["missing"] = missing
    return frag


def deterministic(request: str, k: float, prefix: str) -> dict[str, Any] | None:
    hit = T.read_prompt(request)
    if hit is None:
        return None
    frag = T.generate(hit["template"], hit["params"], k, prefix)
    frag["missing"] = []
    return frag


__all__ = ["deterministic", "interpret", "parse_block", "run_agent"]
