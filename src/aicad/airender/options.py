"""The settings that feed an AI render prompt. Every choice has a label for the UI and a prompt fragment.

All settings are optional; `Settings.validate()` fills defaults and rejects unknown ids. The default camera is
"match the reference view": asking the model for a different viewpoint makes it imagine the unseen sides, which is
where it is most likely to change the geometry, so the UI says so next to the other cameras.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_MODEL = "gpt-image-2"  # PD-39: stable GPT Image model with custom sizes; override with FW_AI_RENDER_MODEL


def model() -> str:
    return os.environ.get("FW_AI_RENDER_MODEL", "").strip() or DEFAULT_MODEL


SCENES: dict[str, dict[str, str]] = {
    "studio": {"label": "Studio packshot",
               "prompt": "a clean professional product packshot in a photo studio, the part resting on a seamless "
                         "sweep"},
    "workshop": {"label": "Workshop bench",
                 "prompt": "resting on a well-used steel workbench in a tidy machine shop, tools and machines softly "
                           "out of focus behind it"},
    "machine": {"label": "Industrial installation",
                "prompt": "installed in its working context inside an industrial machine, the surrounding machinery "
                          "out of focus so the part stays the clear subject"},
    "outdoor": {"label": "Outdoor",
                "prompt": "outdoors in natural daylight, in a setting that suits an engineered component"},
    "catalogue": {"label": "Exploded catalogue",
                  "prompt": "a premium supplier-catalogue presentation, the part floating with a soft drop shadow as "
                            "on an exploded-view catalogue page (the part itself stays whole, in one piece)"},
    "in_hand": {"label": "In-hand scale",
                "prompt": "held in an engineer's gloved hand to show its real size"},
}

LIGHTING: dict[str, dict[str, str]] = {
    "softbox": {"label": "Softbox", "prompt": "soft, even studio softbox lighting with gentle reflections"},
    "rim": {"label": "Dramatic rim", "prompt": "dramatic low-key lighting with strong rim lights tracing the edges"},
    "golden": {"label": "Golden hour", "prompt": "warm golden-hour sunlight with long soft shadows"},
    "flat": {"label": "Technical flat", "prompt": "flat, shadow-free technical lighting that shows every surface"},
}

CAMERAS: dict[str, dict[str, Any]] = {
    "match": {"label": "Match reference", "prompt": "the same viewpoint and framing as the reference image",
              "reliable": True},
    "iso": {"label": "Isometric", "prompt": "an isometric three-quarter view from slightly above", "reliable": False},
    "low_hero": {"label": "Low hero angle", "prompt": "a low heroic camera angle looking slightly up at the part",
                 "reliable": False},
    "top_down": {"label": "Top-down", "prompt": "a top-down view looking straight down at the part",
                 "reliable": False},
    "macro": {"label": "Macro detail", "prompt": "a close macro view with shallow depth of field on the main "
                                                 "features", "reliable": False},
}

BACKGROUNDS: dict[str, dict[str, str]] = {
    "white": {"label": "White seamless", "prompt": "a pure white seamless background"},
    "transparent": {"label": "Transparent", "prompt": "a transparent background (the part cut out cleanly)"},
    "gradient": {"label": "Gradient", "prompt": "a subtle dark-to-light grey studio gradient background"},
    "environment": {"label": "Environment", "prompt": "the scene's own environment as the background"},
}

STYLES: dict[str, dict[str, str]] = {
    "photoreal": {"label": "Photoreal", "prompt": "a photorealistic product photograph, sharp focus, accurate "
                                                  "materials"},
    "catalogue": {"label": "Catalogue", "prompt": "a crisp industrial catalogue image, neutral and precise"},
    "technical": {"label": "Technical illustration", "prompt": "a clean technical illustration with fine line work "
                                                              "and flat shading"},
    "blueprint": {"label": "Blueprint", "prompt": "a blueprint-style rendering, white lines on deep blue"},
    "sketch": {"label": "Sketch", "prompt": "a hand-drawn pencil-and-marker industrial design sketch"},
}

SIZES: dict[str, dict[str, str]] = {
    "1024x1024": {"label": "Square 1:1"},
    "1536x1024": {"label": "Landscape 3:2"},
    "1024x1536": {"label": "Portrait 2:3"},
}

QUALITIES: dict[str, dict[str, Any]] = {
    "low": {"label": "Draft", "eta_s": 20},
    "medium": {"label": "Standard", "eta_s": 45},
    "high": {"label": "High", "eta_s": 100},
}

MAX_VARIANTS = 4
MAX_USER_PROMPT = 1000
MAX_FINISH = 160


@dataclass
class Settings:
    scene: str = "studio"
    finish: str = ""
    lighting: str = "softbox"
    camera: str = "match"
    background: str = "white"
    style: str = "photoreal"
    size: str = "1536x1024"
    quality: str = "medium"
    variants: int = 1

    def validate(self) -> Settings:
        for val, table, what in ((self.scene, SCENES, "scene"), (self.lighting, LIGHTING, "lighting"),
                                 (self.camera, CAMERAS, "camera"), (self.background, BACKGROUNDS, "background"),
                                 (self.style, STYLES, "style"), (self.size, SIZES, "size"),
                                 (self.quality, QUALITIES, "quality")):
            if val not in table:
                raise ValueError(f"Unknown {what}: {val}")
        if not 1 <= int(self.variants) <= MAX_VARIANTS:
            raise ValueError(f"Variants must be 1 to {MAX_VARIANTS}")
        self.variants = int(self.variants)
        self.finish = " ".join((self.finish or "").split())[:MAX_FINISH]
        return self

    def dict(self) -> dict[str, Any]:
        return asdict(self)


def catalog() -> dict[str, Any]:
    def rows(t: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "prompt"}} for k, v in t.items()]

    return {"scenes": rows(SCENES), "lighting": rows(LIGHTING), "cameras": rows(CAMERAS),
            "backgrounds": rows(BACKGROUNDS), "styles": rows(STYLES), "sizes": rows(SIZES),
            "qualities": rows(QUALITIES), "max_variants": MAX_VARIANTS, "defaults": Settings().dict()}


def finish_from_material(material: str | None) -> str:
    """Pre-fill "material & finish" from the part's MATERIAL, using Mesh Studio's deterministic finish mapping."""
    from aicad.meshstudio import presets

    text = (material or "").strip()
    if not text or text.lower() in ("unspecified", "none", "n/a", "tbd"):
        return ""
    m = presets.map_material(text)
    if m.get("matched") is None:
        return text[:MAX_FINISH]
    f = presets.FINISHES[m["finish"]]
    colour = m.get("colour")
    cname = f["colours"][colour][0].lower() if colour and f.get("colours") and colour in f["colours"] else None
    finish = f["label"] + (f", {cname}" if cname else "")
    return f"{finish} ({text})"[:MAX_FINISH]
