"""Render presets: finishes (physically based material recipes), lighting rigs, camera views and quality levels,
plus the mapping from a project's free-text material ("Aluminium 6061-T6, black anodised") to a finish.

Finish recipes are look-development values for a believable presentation render. They are NOT measured optical
data for any real alloy or coating and say nothing about the part's real material or surface finish.
"""

from __future__ import annotations

import re
from typing import Any

# ------------------------------------------------------------------ colours (sRGB hex; converted to linear for Blender)
ANODISE_COLOURS: dict[str, tuple[str, str]] = {
    "clear": ("Clear (natural)", "#c9ccd1"), "black": ("Black", "#3a3b40"), "grey": ("Titanium grey", "#6c7077"),
    "blue": ("Blue", "#1f5fae"), "red": ("Red", "#b3202a"), "gold": ("Gold", "#c99a45"),
    "green": ("Green", "#2f7d4b"), "purple": ("Purple", "#5b3a8c"), "orange": ("Orange", "#d0632a"),
}
PLASTIC_COLOURS: dict[str, tuple[str, str]] = {
    "black": ("Black", "#1e1f21"), "white": ("White", "#deded9"), "grey": ("Grey", "#8a8d91"),
    "red": ("Red", "#c0262d"), "blue": ("Blue", "#1f5bb5"), "yellow": ("Yellow", "#e8b923"),
    "orange": ("Orange", "#e0602a"), "green": ("Green", "#2e8b57"), "natural": ("Natural (off-white)", "#e3dccb"),
}
RUBBER_COLOURS: dict[str, tuple[str, str]] = {
    "black": ("Black", "#1a1a1a"), "grey": ("Grey", "#55585c"), "red": ("Red", "#8e2525"),
}


def srgb_to_linear(hex_colour: str) -> list[float]:
    h = hex_colour.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(round(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4, 5))
    return out


# ------------------------------------------------------------------ finishes
# base: sRGB hex (or colour table), metallic, roughness, rough_var (noise amplitude on roughness), aniso
# (anisotropy 0..1 with tangent around the part's main axis, i.e. turned/lathe marks), brushed (directional
# brushing bump strength), grain (fine isotropic bump: blasting / texture), coat (clear coat weight).
FINISHES: dict[str, dict[str, Any]] = {
    "anodised": {"label": "Anodised aluminium", "group": "Metal", "colours": ANODISE_COLOURS, "default_colour": "clear",
                 "metallic": 1.0, "roughness": 0.3, "rough_var": 0.04, "aniso": 0.0, "grain": 0.03,
                 "grain_mm": 0.3, "coat": 0.0},
    "bead_blasted": {"label": "Bead-blasted aluminium", "group": "Metal", "base": "#a3a5a8", "metallic": 1.0,
                     "roughness": 0.45, "rough_var": 0.05, "aniso": 0.0, "grain": 0.0, "grain_mm": 0.12,
                     "coat": 0.0},
    "brushed_aluminium": {"label": "Brushed aluminium", "group": "Metal", "base": "#c3c6ca", "metallic": 1.0,
                          "roughness": 0.3, "rough_var": 0.04, "aniso": 0.7, "brushed": 0.05, "grain": 0.0,
                          "grain_mm": 0.05, "coat": 0.0},
    "machined_steel": {"label": "Machined steel", "group": "Metal", "base": "#a9abad", "metallic": 1.0,
                       "roughness": 0.22, "rough_var": 0.05, "aniso": 0.55, "grain": 0.02, "grain_mm": 0.2,
                       "coat": 0.0},
    "stainless_brushed": {"label": "Brushed stainless steel", "group": "Metal", "base": "#b4b2ae", "metallic": 1.0,
                          "roughness": 0.27, "rough_var": 0.04, "aniso": 0.75, "brushed": 0.05, "grain": 0.0,
                          "grain_mm": 0.05, "coat": 0.0},
    "black_oxide": {"label": "Black oxide steel", "group": "Metal", "base": "#47474b", "metallic": 1.0,
                    "roughness": 0.36, "rough_var": 0.08, "aniso": 0.25, "grain": 0.04, "grain_mm": 0.2,
                    "coat": 0.35, "coat_roughness": 0.18},
    "brass": {"label": "Brass", "group": "Metal", "base": "#d7b36b", "metallic": 1.0, "roughness": 0.2,
              "rough_var": 0.05, "aniso": 0.35, "grain": 0.02, "grain_mm": 0.2, "coat": 0.0},
    "copper": {"label": "Copper", "group": "Metal", "base": "#d58d62", "metallic": 1.0, "roughness": 0.22,
               "rough_var": 0.05, "aniso": 0.3, "grain": 0.02, "grain_mm": 0.2, "coat": 0.0},
    "titanium": {"label": "Bead-blasted titanium", "group": "Metal", "base": "#a29d95", "metallic": 1.0,
                 "roughness": 0.42, "rough_var": 0.05, "aniso": 0.0, "grain": 0.0, "grain_mm": 0.12, "coat": 0.0},
    "abs": {"label": "ABS plastic (textured)", "group": "Plastic", "colours": PLASTIC_COLOURS, "default_colour": "black",
            "metallic": 0.0, "roughness": 0.5, "rough_var": 0.06, "aniso": 0.0, "grain": 0.15, "grain_mm": 0.35,
            "coat": 0.0, "subsurface": 0.0},
    "pla": {"label": "PLA plastic (satin)", "group": "Plastic", "colours": PLASTIC_COLOURS, "default_colour": "white",
            "metallic": 0.0, "roughness": 0.34, "rough_var": 0.04, "aniso": 0.0, "grain": 0.03, "grain_mm": 0.3,
            "coat": 0.0, "subsurface": 0.04},
    "rubber": {"label": "Rubber", "group": "Elastomer", "colours": RUBBER_COLOURS, "default_colour": "black",
               "metallic": 0.0, "roughness": 0.72, "rough_var": 0.05, "aniso": 0.0, "grain": 0.06, "grain_mm": 0.25,
               "coat": 0.0, "sheen": 0.25},
    "clay": {"label": "Studio clay (neutral review)", "group": "Neutral", "base": "#c7c5c0", "metallic": 0.0,
             "roughness": 0.6, "rough_var": 0.0, "aniso": 0.0, "grain": 0.0, "grain_mm": 0.1, "coat": 0.0},
}

# ------------------------------------------------------------------ material text -> finish
# Ordered rules: the first finish keyword wins over the alloy family ("6061 black oxide" is not plausible, but
# "steel, black oxide" is). Each rule: (regex, finish).
_FINISH_RULES: list[tuple[str, str]] = [
    (r"black[\s-]*oxide|blacken|gun[\s-]*blue|parkeri", "black_oxide"),
    (r"bead[\s-]*blast|grit[\s-]*blast|sand[\s-]*blast|blasted|matte?\s+alu", "bead_blasted"),
    (r"anodi[sz]|hard[\s-]*coat|type\s*(ii|iii|2|3)\b", "anodised"),
    (r"brush", "stainless_brushed"),
]
_FAMILY_RULES: list[tuple[str, str]] = [
    (r"rubber|epdm|neoprene|nitrile|\bnbr\b|silicone|\btpu\b|\btpe\b|elastomer|viton|fkm|urethane", "rubber"),
    (r"stainless|\b(304|316|303|17-4|420|410)\b|inox|\bss\b", "stainless_brushed"),
    (r"titan|ti-?6al|grade\s*5", "titanium"),
    (r"brass|\bc3[56]0\b|bronze|\bc932\b", "brass"),
    (r"copper|\bc1[01]0\b", "copper"),
    (r"alumin|\b(6061|6063|6082|7075|5052|2024|5083)\b|\bal\b", "anodised"),
    (r"steel|\b(1018|1020|1045|4140|4340|a36|s235|s355|en8|en24)\b|cast\s*iron|\biron\b|carbon\s*steel|mild\s*steel",
     "machined_steel"),
    (r"\bpla\b", "pla"),
    ((r"\babs\b|petg|\bpet\b|nylon|\bpa\s*(6|11|12|66)\b|\bpa(6|11|12|66)\b|acetal|delrin|\bpom\b|polycarb|\bpc\b|"
      r"peek|uhmw|\bhdpe\b|\bpp\b|polyprop|plastic|resin|\basa\b"), "abs"),
]
_COLOUR_WORDS: list[tuple[str, str]] = [
    (r"black", "black"), (r"white", "white"), (r"gr[ae]y|titanium\s*grey|gunmetal", "grey"), (r"\bred\b", "red"),
    (r"blue", "blue"), (r"gold|yellow", "gold"), (r"green", "green"), (r"purple|violet", "purple"),
    (r"orange", "orange"), (r"clear|natural|silver|colou?rless", "clear"),
]


def _colour_for(finish: str, text: str) -> str | None:
    table = FINISHES[finish].get("colours")
    if not table:
        return None
    for rx, word in _COLOUR_WORDS:
        if re.search(rx, text):
            if word == "gold" and "yellow" in text and "yellow" in table:
                return "yellow"
            if word == "clear" and finish in ("abs", "pla"):
                return "natural"
            if word in table:
                return word
    return FINISHES[finish]["default_colour"]


def map_material(text: str | None) -> dict[str, Any]:
    """Pick a finish (and colour) from a project's material text. Deterministic; unknown text gives studio clay.

    Returns {"finish", "colour", "matched"}; `matched` is the rule that fired, or None for the neutral fallback.
    """
    t = (text or "").strip().lower()
    if not t or t in ("unspecified", "none", "n/a", "tbd"):
        return {"finish": "clay", "colour": None, "matched": None}
    finish = None
    matched = None
    for rx, fin in _FINISH_RULES:
        if re.search(rx, t):
            finish, matched = fin, rx
            break
    if finish == "stainless_brushed" and re.search(r"alumin|\bal\b|\b[2-7]0\d\d\b", t):
        finish = "brushed_aluminium"
    if finish is None:
        for rx, fin in _FAMILY_RULES:
            if re.search(rx, t):
                finish, matched = fin, rx
                break
    if finish is None:
        return {"finish": "clay", "colour": None, "matched": None}
    if finish == "abs" and re.search(r"nylon|\bpa\s*12|\bpa12|sls|mjf", t):
        colour = _colour_for(finish, t) if re.search("|".join(r for r, _ in _COLOUR_WORDS), t) else "white"
        return {"finish": finish, "colour": colour, "matched": matched}
    return {"finish": finish, "colour": _colour_for(finish, t), "matched": matched}


def resolve_finish(finish: str, colour: str | None) -> dict[str, Any]:
    """The material block for the scene spec (linear colour, all recipe values), for a finish + optional colour."""
    if finish not in FINISHES:
        raise ValueError(f"Unknown finish: {finish}")
    f = FINISHES[finish]
    table = f.get("colours")
    if table:
        colour = colour if colour in table else f["default_colour"]
        hexc = table[colour][1]
    else:
        colour, hexc = None, f["base"]
    out = {k: v for k, v in f.items() if k not in ("label", "group", "colours", "default_colour", "base")}
    out.update(id=finish, colour=colour, base=srgb_to_linear(hexc))
    return out


# ------------------------------------------------------------------ lighting
# Light positions are relative to the camera: azimuth 0 = from the camera's side, negative = camera's left.
# dist and size are in units of the part's bounding-box diagonal; power scales with size^2 so exposure is the same
# for a 10 mm and a 1 m part. Background is composited behind the transparent render (sRGB hex, centre -> edge).
LIGHTING: dict[str, dict[str, Any]] = {
    "studio": {
        "label": "Studio softbox", "hint": "Soft, even product lighting on a light grey sweep",
        "world": {"top": "#d4d8dd", "horizon": "#a3a8af", "bottom": "#62666c", "strength": 0.55},
        "background": {"centre": "#f4f5f7", "edge": "#d3d7dc"}, "shadow": 0.75, "exposure": 0.0,
        "lights": [
            {"name": "Key", "az": -50, "el": 45, "dist": 3.0, "w": 1.4, "h": 1.0, "power": 7.5},
            {"name": "Fill", "az": 60, "el": 20, "dist": 3.2, "w": 1.6, "h": 1.2, "power": 2.5},
            {"name": "Top", "az": 0, "el": 88, "dist": 2.6, "w": 1.6, "h": 1.6, "power": 3.5},
            {"name": "Kick left", "az": -125, "el": 12, "dist": 2.6, "w": 0.22, "h": 1.3, "power": 5.5},
            {"name": "Kick right", "az": 125, "el": 12, "dist": 2.6, "w": 0.22, "h": 1.3, "power": 4.5},
        ],
    },
    "dark": {
        "label": "Dark dramatic", "hint": "Rim-lit on charcoal, for hero shots of metal parts",
        "world": {"top": "#3a3e45", "horizon": "#15171a", "bottom": "#050506", "strength": 0.25},
        "background": {"centre": "#2a2d32", "edge": "#08090b"}, "shadow": 0.9, "exposure": 0.0,
        "lights": [
            {"name": "Key", "az": -60, "el": 40, "dist": 2.6, "w": 0.9, "h": 0.7, "power": 16.0},
            {"name": "Kick left", "az": -120, "el": 15, "dist": 2.4, "w": 0.2, "h": 1.4, "power": 30.0},
            {"name": "Kick right", "az": 120, "el": 15, "dist": 2.4, "w": 0.2, "h": 1.4, "power": 26.0},
            {"name": "Top", "az": 0, "el": 80, "dist": 2.6, "w": 1.0, "h": 1.0, "power": 6.0},
        ],
    },
    "technical": {
        "label": "Technical white", "hint": "Bright, flat lighting on pure white for catalogues and datasheets",
        "world": {"top": "#ffffff", "horizon": "#d5d8dc", "bottom": "#7d8187", "strength": 0.9},
        "background": {"centre": "#ffffff", "edge": "#ffffff"}, "shadow": 0.45, "exposure": 0.15,
        "lights": [
            {"name": "Key", "az": -35, "el": 50, "dist": 2.8, "w": 1.8, "h": 1.4, "power": 26.0},
            {"name": "Fill", "az": 50, "el": 25, "dist": 3.0, "w": 1.8, "h": 1.4, "power": 16.0},
            {"name": "Top", "az": 0, "el": 89, "dist": 2.4, "w": 1.8, "h": 1.8, "power": 14.0},
        ],
    },
}

# ------------------------------------------------------------------ cameras
# az: degrees from the front (camera on -Y looking +Y), positive towards +X. el: degrees above the horizon.
# lens in mm on a 36 mm sensor (perspective) or orthographic. fill: fraction of the frame the part may occupy.
CAMERAS: dict[str, dict[str, Any]] = {
    "hero": {"label": "Hero 3/4", "az": 35.0, "el": 24.0, "lens": 85.0, "ortho": False, "fill": 0.8},
    "iso": {"label": "Isometric", "az": 45.0, "el": 35.264, "lens": 0.0, "ortho": True, "fill": 0.8},
    "front": {"label": "Front", "az": 0.0, "el": 0.0, "lens": 0.0, "ortho": True, "fill": 0.78},
    "top": {"label": "Top", "az": 0.0, "el": 90.0, "lens": 0.0, "ortho": True, "fill": 0.78},
    "low": {"label": "Low hero", "az": -30.0, "el": 10.0, "lens": 70.0, "ortho": False, "fill": 0.8},
}

# ------------------------------------------------------------------ quality
# samples are per pixel with adaptive sampling and denoising; frames only for turntables.
QUALITY: dict[str, dict[str, Any]] = {
    "preview": {"label": "Preview", "res": (720, 540), "samples_gpu": 24, "samples_cpu": 12, "bounces": 6},
    "final": {"label": "Final", "res": (1920, 1440), "samples_gpu": 256, "samples_cpu": 96, "bounces": 10},
    "turntable": {"label": "Turntable", "res": (960, 720), "samples_gpu": 48, "samples_cpu": 16, "bounces": 8,
                  "frames": 72, "fps": 24},
}
ASPECTS: dict[str, tuple[int, int]] = {"4:3": (4, 3), "16:9": (16, 9), "1:1": (1, 1), "3:4": (3, 4)}
POSES = {"auto": "Auto (lay long parts down)", "as_modelled": "As modelled"}


def catalog() -> dict[str, Any]:
    """Preset catalogue for the UI (labels, colour swatches)."""
    def colours(f: dict[str, Any]) -> list[dict[str, str]] | None:
        t = f.get("colours")
        return [{"id": k, "label": v[0], "hex": v[1]} for k, v in t.items()] if t else None

    return {
        "finishes": [{"id": k, "label": f["label"], "group": f["group"], "colours": colours(f),
                      "default_colour": f.get("default_colour"), "swatch": f.get("base") or
                      f["colours"][f["default_colour"]][1]} for k, f in FINISHES.items()],
        "lighting": [{"id": k, "label": v["label"], "hint": v["hint"], "background": v["background"]["centre"]}
                     for k, v in LIGHTING.items()],
        "cameras": [{"id": k, "label": v["label"]} for k, v in CAMERAS.items()],
        "aspects": list(ASPECTS),
        "poses": [{"id": k, "label": v} for k, v in POSES.items()],
        "quality": {k: {"label": v["label"], "res": list(v["res"]), "frames": v.get("frames")}
                    for k, v in QUALITY.items()},
    }
