"""Raster drawings, sketches and photos: the design agent's vision reads the image (no paid OCR service).

The agent gets one image and the Read tool only (confined to the upload folder), and must answer with a fenced
``fw-read`` JSON block listing exactly what is written, with a confidence and location for each value, plus what is
unreadable or missing. Its texts then go through the same deterministic token parser as vector PDFs, so a value is
never accepted just because the model said so: every vision reading is shown for review, and low-confidence or
ambiguous ones become questions. ``run_agent`` is the only function that calls the model; tests replace it.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from aicad.image2cad.tokens import parse

LOW_CONFIDENCE = 0.75

VISION_INSTRUCTIONS = """You read engineering drawings, hand sketches and photos of parts for a mechanical design \
team. You never model anything and never write files. You report only what is actually written or clearly drawn.
Rules:
- Never estimate a size from the picture. Never assume a scale. Never fill in a value that is not written.
- If a number is hard to read, give your best reading with a low confidence and list the other readings.
- If you cannot tell whether a number is a diameter or a radius (or similar), say so in kind_unclear.
- Plain engineering language. Answer with exactly one fenced block tagged fw-read, nothing else after it."""

VISION_PROMPT = """Open the image file `{image}` in the current folder with the Read tool and study it.

Return exactly one fenced block:

```fw-read
{{"drawing_kind": "drawing" | "sketch" | "photo",
 "part": "one line: what the part appears to be",
 "title": "the part title written in the title block, without the drawing number, or null",
 "drawing_no": "the drawing or part number written in the title block, or null",
 "units": "mm" | "in" | null, "units_evidence": "where the units are written, or null",
 "scale": "1:2" | null,
 "projection": "first" | "third" | null, "projection_evidence": "the projection symbol or text you saw, or null",
 "views": [{{"id": "v1", "label": "text written next to it or null", "looks_like": "front | top | side | \
isometric | section | detail | unknown", "box": [x0, y0, x1, y1]}}],
 "dimensions": [{{"text": "the callout exactly as written, e.g. 4X Ø6.6 THRU", "x": 0.42, "y": 0.31, \
"view": "v1", "confidence": 0.9, "alternatives": [], "kind_unclear": [], "describes": "what it measures, e.g. \
overall width"}}],
 "unreadable": [{{"note": "what is there but cannot be read", "x": 0.5, "y": 0.5}}],
 "missing": [{{"what": "a size needed to make the part that is not given, e.g. plate thickness", \
"why": "e.g. only one view is drawn"}}]}}
```

x, y and box are fractions of the image width and height measured from the top-left corner (0 to 1), at the \
centre of the text. Use the symbols Ø, R, ±, ° and X as written. List every dimension you can see, even partly \
readable ones (with low confidence). An empty list is a valid answer.
"describes" says what a dimension measures in plain words; leave out colour or legend tags (such as "red: \
INFERRED"). "projection" comes from the ISO projection symbol or a written note; null when neither is there.
"missing" lists only sizes needed to make the shape. Tolerances, approval status, surface finish, material and \
other title-block fields are not sizes: leave them out of "missing"."""

_BLOCK = re.compile(r"```(?:fw-read|json)?\s*\n(.*?)\n?```", re.DOTALL)


async def run_agent(folder: Path, image: str, budget_usd: float | None = None) -> tuple[str, float | None]:
    """One read-only vision turn. Returns (assistant text, estimated cost in USD). ``budget_usd``: hard cap for
    the turn (the SDK stops it there), so a read can never spend more than the workspace holds."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        HookMatcher,
        ResultMessage,
        TextBlock,
        query,
    )

    from aicad.agent.session import AGENT_BUFFER_BYTES, make_guard

    opts = ClaudeAgentOptions(
        cwd=str(folder), tools=["Read"], allowed_tools=["Read"], permission_mode="dontAsk",
        system_prompt={"type": "preset", "preset": "claude_code", "append": VISION_INSTRUCTIONS},
        setting_sources=[], max_turns=4, max_buffer_size=AGENT_BUFFER_BYTES,
        hooks={"PreToolUse": [HookMatcher(matcher="Read", hooks=[make_guard(folder)])]})
    if budget_usd is not None:
        opts.max_budget_usd = max(0.01, budget_usd)
    texts: list[str] = []
    cost: float | None = None
    async for msg in query(prompt=VISION_PROMPT.format(image=image), options=opts):
        if isinstance(msg, AssistantMessage):
            texts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd
    return "\n".join(texts), cost


def parse_block(text: str) -> dict[str, Any] | None:
    """The last JSON object in a fenced fw-read (or json) block, else a bare JSON object, else None."""
    cands = [m.group(1) for m in _BLOCK.finditer(text)]
    if not cands:
        i, j = text.find("{"), text.rfind("}")
        cands = [text[i:j + 1]] if 0 <= i < j else []
    for raw in reversed(cands):
        try:
            v = json.loads(raw)
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return None


def _f(v: Any, lo: float = 0.0, hi: float = 1.0) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else min(max(x, lo), hi)


def _s(v: Any, n: int = 160) -> str:
    """One-line text, at most n characters; a longer text ends at a word with an ellipsis (never mid-word)."""
    t = " ".join(str(v or "").split())
    if len(t) <= n:
        return t
    cut = t[:n - 1].rsplit(" ", 1)[0] if " " in t[:n - 1] else t[:n - 1]
    return cut.rstrip(" ,;:") + "…"


# colour-legend tags a reader copies from a sheet's legend, e.g. "(red: INFERRED)", "[blue = SPEC]", "- green: REF"
_LEGEND = re.compile(r"\s*(?:[(\[]\s*|[-–—,;]\s*)?\b(?:red|blue|green|black|orange|grey|gray|amber|purple)\s*[:=]\s*"
                     r"[A-Z][A-Z ]{1,20}?\b\s*[)\]]?", re.IGNORECASE)


def clean_describes(text: Any) -> str | None:
    """What a dimension measures, without colour-legend tags copied from the sheet."""
    s = _LEGEND.sub("", _s(text, 160)).strip(" ,;-–—")
    return s[:100] or None


def to_read(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the agent's block into the same read schema as a vector PDF (positions normalised 0..1)."""
    views = []
    for i, v in enumerate((raw.get("views") or [])[:8]):
        if not isinstance(v, dict):
            continue
        box = v.get("box")
        box = [_f(b) for b in box] if isinstance(box, list) and len(box) == 4 else None
        if box and None in box:
            box = None
        label = _s(v.get("label"), 60) or None
        looks = _s(v.get("looks_like"), 20).lower() or "unknown"
        kind = "iso" if looks.startswith("iso") else "section" if looks == "section" else \
            "detail" if looks == "detail" else "ortho"
        views.append({"id": _s(v.get("id"), 8) or f"v{i + 1}", "label": label, "kind": kind, "looks_like": looks,
                      "name": label or (looks.capitalize() + " view" if looks != "unknown" else f"View {i + 1}"),
                      "box": box})
    vids = {v["id"] for v in views}
    dims, unparsed = [], []
    for item in (raw.get("dimensions") or [])[:80]:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        text = _s(item["text"], 60)
        conf = _f(item.get("confidence"))
        conf = 0.5 if conf is None else round(conf, 2)
        x, y = _f(item.get("x")), _f(item.get("y"))
        alts = [_s(a, 40) for a in (item.get("alternatives") or []) if str(a).strip()][:4]
        unclear = [_s(k, 24).lower() for k in (item.get("kind_unclear") or []) if str(k).strip()][:4]
        view = _s(item.get("view"), 8)
        d = parse(text)
        base = {"x": x, "y": y, "box": None, "rot": 0, "dir": None, "view": view if view in vids else None,
                "view_alt": None, "confidence": conf, "source": "vision", "alternatives": alts,
                "kind_unclear": unclear, "describes": clean_describes(item.get("describes")), "style": "regular"}
        if d is None or d["kind"] == "scale":
            if d is None:
                unparsed.append({"text": text, "x": x, "y": y, "confidence": conf,
                                 "describes": base["describes"]})
            continue
        dims.append({**d, **base})
    for i, d in enumerate(dims):
        d["id"] = f"d{i + 1}"
    units = raw.get("units") if raw.get("units") in ("mm", "in") else None
    scale = None
    sd = parse(_s(raw.get("scale"), 20)) if raw.get("scale") else None
    if sd and sd["kind"] == "scale":
        scale = {"ratio": sd["ratio"], "text": sd["text"], "evidence": "Scale written on the drawing (read by vision)"}
    unreadable = [{"note": _s(u.get("note"), 200), "x": _f(u.get("x")), "y": _f(u.get("y"))}
                  for u in (raw.get("unreadable") or [])[:20] if isinstance(u, dict) and u.get("note")]
    missing = [{"what": _s(m.get("what"), 120), "why": _s(m.get("why"), 200) or None}
               for m in (raw.get("missing") or [])[:12] if isinstance(m, dict) and m.get("what")]
    kind = raw.get("drawing_kind") if raw.get("drawing_kind") in ("drawing", "sketch", "photo") else "drawing"
    proj = raw.get("projection") if raw.get("projection") in ("first", "third") else None
    projection = ({"value": proj, "evidence": _s(raw.get("projection_evidence"), 120) or "Read by vision"}
                  if proj else None)
    return {"method": "vision", "drawing_kind": kind, "part": _s(raw.get("part"), 200) or None, "dims": dims,
            "views": views, "title": {}, "title_block": None, "scale": scale,
            "title_text": _s(raw.get("title"), 80) or None, "drawing_no": _s(raw.get("drawing_no"), 40) or None,
            "units": {"value": units, "evidence": _s(raw.get("units_evidence"), 120) or "Read by vision"}
            if units else None, "projection": projection, "unparsed": unparsed[:40], "unreadable": unreadable,
            "missing": missing, "checks": []}


VISION_PX = 1568  # long side Claude reads best; larger images are downscaled by the model anyway


def vision_copy(folder: Path, image: str) -> str:
    """A compact copy of `image` for the vision read: at most VISION_PX on the long side, saved as JPEG or PNG,
    whichever is smaller. Photos as lossless PNG can be several hundred KB, and the agent stream carries the image
    more than once per message, so a large PNG overflowed the transport (found with a 600×851 phone photo)."""
    from PIL import Image

    src = folder / image
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((VISION_PX, VISION_PX), Image.Resampling.LANCZOS)
        im.save(folder / "vision.jpg", "JPEG", quality=88, optimize=True)
        im.save(folder / "vision.png", "PNG", optimize=True)
    jpg, png = (folder / "vision.jpg").stat().st_size, (folder / "vision.png").stat().st_size
    keep, drop = ("vision.jpg", "vision.png") if jpg <= png else ("vision.png", "vision.jpg")
    (folder / drop).unlink(missing_ok=True)
    return keep


async def read_image(folder: Path, image: str = "preview.png",
                     budget_usd: float | None = None) -> tuple[dict[str, Any] | None, float | None]:
    """(read dict or None when the answer had no usable block, cost in USD)."""
    img = vision_copy(folder, image)
    text, cost = await (run_agent(folder, img) if budget_usd is None else run_agent(folder, img, budget_usd=budget_usd))
    raw = parse_block(text)
    return (to_read(raw) if raw is not None else None), cost
