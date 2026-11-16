"""Manufacturing material library (MFG-020): process-relevant properties with provenance and a version.

Builds on `aicad.materials` (densities, unchanged API) and adds, per material: a machining class, process
suitability tags and a placeholder stock price. Every property carries its source. Prices are **placeholders for
relative comparison only** (not market data); users override them in the shop profile.
"""

from __future__ import annotations

from typing import Any

from aicad import materials

LIBRARY_VERSION = "mfg-materials 1.0 (2026-11-16)"

SRC_DENSITY = "aicad.materials: " + materials.SOURCE_NOTE
SRC_CLASS = "Formwright grouping by machinability family (general machining practice)"
SRC_PROCESS = "General process-material practice (screening only); verify with your supplier"
SRC_PRICE = "Formwright placeholder for relative comparison (2026-11), not market data. Set your own price."

# code -> (machining class, processes, placeholder stock price per kg in the profile currency)
# processes: mill, turn, sheet, cast, mould, fdm, sla, sls
_EXTRA: dict[str, tuple[str, tuple[str, ...], float]] = {
    "al_6061": ("aluminium", ("mill", "turn", "sheet", "cast"), 6.0),
    "al_7075": ("aluminium", ("mill", "turn", "sheet"), 10.0),
    "al_5052": ("aluminium", ("mill", "turn", "sheet"), 6.0),
    "steel_1018": ("steel", ("mill", "turn", "sheet", "cast"), 2.5),
    "steel_1045": ("steel", ("mill", "turn", "cast"), 2.5),
    "steel_4140": ("steel", ("mill", "turn", "cast"), 3.5),
    "ss_304": ("stainless", ("mill", "turn", "sheet", "cast"), 6.0),
    "ss_316": ("stainless", ("mill", "turn", "sheet", "cast"), 8.0),
    "ss_17_4": ("stainless", ("mill", "turn", "cast"), 12.0),
    "cast_iron_gray": ("cast_iron", ("mill", "turn", "cast"), 2.0),
    "ti_6al4v": ("titanium", ("mill", "turn", "cast"), 40.0),
    "brass_c360": ("copper", ("mill", "turn", "cast"), 9.0),
    "copper_c110": ("copper", ("mill", "turn", "sheet"), 11.0),
    "bronze_c932": ("copper", ("mill", "turn", "cast"), 12.0),
    "abs": ("plastic", ("mill", "turn", "mould", "fdm", "sla"), 5.0),
    "pla": ("plastic", ("fdm", "sla"), 25.0),
    "petg": ("plastic", ("mill", "mould", "fdm", "sla"), 25.0),
    "pa12": ("plastic", ("mill", "turn", "mould", "sls"), 60.0),
    "pa66": ("plastic", ("mill", "turn", "mould", "sls"), 8.0),
    "pom": ("plastic", ("mill", "turn", "mould"), 8.0),
    "pc": ("plastic", ("mill", "turn", "mould", "fdm", "sla"), 8.0),
    "peek": ("plastic", ("mill", "turn", "mould", "fdm"), 120.0),
    "uhmw": ("plastic", ("mill", "turn"), 8.0),
}

CLASS_LABEL = {"aluminium": "Aluminium alloys", "steel": "Carbon and alloy steels", "stainless": "Stainless steels",
               "cast_iron": "Cast irons", "titanium": "Titanium alloys", "copper": "Copper alloys",
               "plastic": "Engineering plastics"}


def library() -> list[dict[str, Any]]:
    out = []
    for m in materials.MATERIALS:
        cls, procs, price = _EXTRA.get(str(m["code"]), ("steel", ("mill", "turn"), 3.0))
        out.append({
            "code": m["code"], "name": m["name"], "group": m["group"],
            "density_g_cm3": m["density_g_cm3"], "machining_class": cls, "processes": list(procs),
            "price_per_kg": price, "metal": cls != "plastic",
            "provenance": {"density_g_cm3": SRC_DENSITY, "machining_class": SRC_CLASS, "processes": SRC_PROCESS,
                           "price_per_kg": SRC_PRICE},
            "version": LIBRARY_VERSION,
        })
    return out


def get(code: str | None) -> dict[str, Any] | None:
    return next((m for m in library() if m["code"] == code), None)
