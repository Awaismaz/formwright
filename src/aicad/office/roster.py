"""The Design Office team: named agents with a mechanical pun, a colour and a tool (plan §3, PD-35).

Part families decide which specialist owns a part ticket. Standard parts go to Hex (Toolbox), sub-assembly
integration goes to Fitz. Gage, Ortho and Smithy are on the roster but only start work with the orchestrator
(Phase 3+), which the UI says plainly.
"""

from __future__ import annotations

from typing import Any

AGENTS: list[dict[str, Any]] = [
    {"code": "archie", "name": "Archie", "role": "Chief Designer", "colour": "#364FC7",
     "pun": "After Archimedes, the original engineer", "phase": 2,
     "idle_line": "Archie is ready for a new brief"},
    {"code": "mill", "name": "Mill", "role": "Machined parts", "colour": "#1098AD",
     "pun": "The milling machine", "phase": 3, "idle_line": "Mill is sharpening cutters"},
    {"code": "chuck", "name": "Chuck", "role": "Turned parts", "colour": "#E8590C",
     "pun": "The lathe chuck", "phase": 3, "idle_line": "Chuck is truing up the jaws"},
    {"code": "axel", "name": "Axel", "role": "Gears, pulleys and drives", "colour": "#7048E8",
     "pun": "Axle", "phase": 3, "idle_line": "Axel is checking the tooth count"},
    {"code": "benny", "name": "Benny", "role": "Sheet metal", "colour": "#5C940D",
     "pun": "Bend", "phase": 3, "idle_line": "Benny is flattening a blank"},
    {"code": "molly", "name": "Molly", "role": "Plastic and moulded parts", "colour": "#D6336C",
     "pun": "Mould", "phase": 3, "idle_line": "Molly is polishing the cavity"},
    {"code": "hex", "name": "Hex", "role": "Librarian: Toolbox and company parts", "colour": "#495057",
     "pun": "Hex bolts, the standard-parts shelf", "phase": 3, "idle_line": "Hex is sorting the parts drawers"},
    {"code": "fitz", "name": "Fitz", "role": "Assembly", "colour": "#1971C2",
     "pun": "Makes things fit", "phase": 3, "idle_line": "Fitz is laying out the bench"},
    {"code": "gage", "name": "Gage", "role": "Checker (independent)", "colour": "#AE3EC9",
     "pun": "Gauge", "phase": 3, "idle_line": "Gage is zeroing the caliper"},
    {"code": "ortho", "name": "Ortho", "role": "Drawings", "colour": "#2B8A3E",
     "pun": "Orthographic projection", "phase": 5, "idle_line": "Ortho is sharpening pencils"},
    {"code": "smithy", "name": "Smithy", "role": "Manufacturing review", "colour": "#C92A2A",
     "pun": "The blacksmith's shop", "phase": 5, "idle_line": "Smithy is banking the forge"},
]
AGENT_CODES = {a["code"] for a in AGENTS}

# Part family -> (label, owning specialist). "standard" and "integration" are ticket kinds as well as families.
FAMILIES: dict[str, tuple[str, str]] = {
    "machined": ("Machined (prismatic)", "mill"),
    "turned": ("Turned", "chuck"),
    "gear": ("Gear, pulley or drive", "axel"),
    "sheet": ("Sheet metal", "benny"),
    "plastic": ("Plastic / moulded", "molly"),
    "standard": ("Standard part (Toolbox)", "hex"),
    "integration": ("Assembly integration", "fitz"),
}
PART_FAMILIES = [f for f in FAMILIES if f != "integration"]
DESIGNERS = ("mill", "chuck", "axel", "benny", "molly")

_ALIASES = {
    "prismatic": "machined", "milled": "machined", "machining": "machined", "mill": "machined", "plate": "machined",
    "lathe": "turned", "turning": "turned", "shaft": "turned", "round": "turned",
    "gears": "gear", "pulley": "gear", "drive": "gear", "sprocket": "gear", "transmission": "gear",
    "sheet metal": "sheet", "sheetmetal": "sheet", "sheet_metal": "sheet", "bent": "sheet",
    "moulded": "plastic", "molded": "plastic", "injection": "plastic", "injection moulded": "plastic",
    "printed": "plastic", "polymer": "plastic",
    "toolbox": "standard", "purchased": "standard", "bought-out": "standard", "fastener": "standard",
    "catalogue": "standard", "catalog": "standard", "cots": "standard",
    "assembly": "integration",
}


def normalise_family(v: Any) -> str:
    """A family code from free text; unknown families are treated as machined (the most general shop)."""
    t = str(v or "").strip().lower()
    if t in FAMILIES:
        return t
    return _ALIASES.get(t, "machined")


def specialist_for(family: str) -> str:
    return FAMILIES.get(family, FAMILIES["machined"])[1]


def agent(code: str) -> dict[str, Any]:
    return next((a for a in AGENTS if a["code"] == code), AGENTS[0])
