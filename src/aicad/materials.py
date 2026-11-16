"""Material library for mass properties.

Densities are TYPICAL nominal values from widely published handbook/supplier data (e.g. ASM Handbook,
MatWeb aggregated datasheets, polymer supplier datasheets). They vary with alloy temper, grade and
process (especially plastics and 3D-printed parts). Always verify against the actual supplier datasheet
before relying on a mass for engineering decisions.
"""

from __future__ import annotations

MATERIALS: list[dict[str, object]] = [
    # metals
    {"code": "al_6061", "name": "Aluminium 6061-T6", "group": "Aluminium", "density_g_cm3": 2.70},
    {"code": "al_7075", "name": "Aluminium 7075-T6", "group": "Aluminium", "density_g_cm3": 2.81},
    {"code": "al_5052", "name": "Aluminium 5052-H32", "group": "Aluminium", "density_g_cm3": 2.68},
    {"code": "steel_1018", "name": "Steel 1018 (low carbon)", "group": "Steel", "density_g_cm3": 7.87},
    {"code": "steel_1045", "name": "Steel 1045 (medium carbon)", "group": "Steel", "density_g_cm3": 7.85},
    {"code": "steel_4140", "name": "Steel 4140 (alloy)", "group": "Steel", "density_g_cm3": 7.85},
    {"code": "ss_304", "name": "Stainless 304", "group": "Stainless", "density_g_cm3": 8.00},
    {"code": "ss_316", "name": "Stainless 316", "group": "Stainless", "density_g_cm3": 8.00},
    {"code": "ss_17_4", "name": "Stainless 17-4 PH", "group": "Stainless", "density_g_cm3": 7.75},
    {"code": "cast_iron_gray", "name": "Grey cast iron", "group": "Cast iron", "density_g_cm3": 7.20},
    {"code": "ti_6al4v", "name": "Titanium Ti-6Al-4V", "group": "Titanium", "density_g_cm3": 4.43},
    {"code": "brass_c360", "name": "Brass C360", "group": "Copper alloys", "density_g_cm3": 8.50},
    {"code": "copper_c110", "name": "Copper C110", "group": "Copper alloys", "density_g_cm3": 8.89},
    {"code": "bronze_c932", "name": "Bearing bronze C932", "group": "Copper alloys", "density_g_cm3": 8.93},
    # plastics
    {"code": "abs", "name": "ABS", "group": "Plastics", "density_g_cm3": 1.04},
    {"code": "pla", "name": "PLA (solid)", "group": "Plastics", "density_g_cm3": 1.24},
    {"code": "petg", "name": "PETG", "group": "Plastics", "density_g_cm3": 1.27},
    {"code": "pa12", "name": "Nylon PA12", "group": "Plastics", "density_g_cm3": 1.01},
    {"code": "pa66", "name": "Nylon PA66", "group": "Plastics", "density_g_cm3": 1.14},
    {"code": "pom", "name": "Acetal POM (Delrin)", "group": "Plastics", "density_g_cm3": 1.41},
    {"code": "pc", "name": "Polycarbonate", "group": "Plastics", "density_g_cm3": 1.20},
    {"code": "peek", "name": "PEEK", "group": "Plastics", "density_g_cm3": 1.30},
    {"code": "uhmw", "name": "UHMW-PE", "group": "Plastics", "density_g_cm3": 0.93},
]

SOURCE_NOTE = ("Typical nominal density from published handbook/supplier data; varies with grade, temper and "
               "process. Verify with your supplier datasheet.")

_KEYWORDS = [("7075", "al_7075"), ("5052", "al_5052"), ("6061", "al_6061"), ("alumin", "al_6061"),
             ("4140", "steel_4140"), ("1045", "steel_1045"), ("1018", "steel_1018"), ("17-4", "ss_17_4"),
             ("316", "ss_316"), ("304", "ss_304"), ("stainless", "ss_304"), ("cast iron", "cast_iron_gray"),
             ("titanium", "ti_6al4v"), ("ti-6", "ti_6al4v"), ("brass", "brass_c360"), ("bronze", "bronze_c932"),
             ("copper", "copper_c110"), ("abs", "abs"), ("pla", "pla"), ("petg", "petg"), ("pa12", "pa12"),
             ("pa66", "pa66"), ("nylon", "pa12"), ("delrin", "pom"), ("acetal", "pom"), ("pom", "pom"),
             ("polycarb", "pc"), ("peek", "peek"), ("uhmw", "uhmw"), ("steel", "steel_1045")]


def guess(material_text: str | None) -> str | None:
    t = (material_text or "").lower()
    for kw, code in _KEYWORDS:
        if kw in t:
            return code
    return None


def get(code: str | None) -> dict[str, object] | None:
    return next((m for m in MATERIALS if m["code"] == code), None)
