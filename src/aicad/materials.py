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


# ----------------------------------------------------------------------------- mechanical properties (ENG-003)
# Added for the Engineering Advisor. Only values with a cited source are listed; every value is TYPICAL or a
# specification MINIMUM as labelled, for one stated condition. Verify against the supplier certificate (mill test
# report) before relying on it. Bump MECHANICAL_VERSION on any change.
MECHANICAL_VERSION = "matlib-1.0.0"
MECHANICAL_NOTE = ("Typical or specification-minimum values for the stated condition, as cited. Verify against the "
                   "supplier certificate before release.")

_ASM_AL = "ASM Handbook Vol. 2 / Aluminum Association typical properties"
_SHIGLEY_A20 = "Shigley's Mechanical Engineering Design, Table A-20 (minimum, cold drawn) and Table A-5 (E, ν)"
MECHANICAL: dict[str, dict[str, object]] = {
    "al_6061": {"condition": "T6", "basis": "typical", "Sut_MPa": 310, "Sy_MPa": 276, "E_GPa": 68.9, "nu": 0.33,
                "fatigue_MPa": 96.5, "fatigue_note": "R.R. Moore, 5×10⁸ cycles (no endurance limit)",
                "source": _ASM_AL},
    "al_7075": {"condition": "T6", "basis": "typical", "Sut_MPa": 572, "Sy_MPa": 503, "E_GPa": 71.7, "nu": 0.33,
                "fatigue_MPa": 159, "fatigue_note": "R.R. Moore, 5×10⁸ cycles (no endurance limit)",
                "source": _ASM_AL},
    "al_5052": {"condition": "H32", "basis": "typical", "Sut_MPa": 228, "Sy_MPa": 193, "E_GPa": 70.3, "nu": 0.33,
                "fatigue_MPa": 117, "fatigue_note": "R.R. Moore, 5×10⁸ cycles (no endurance limit)",
                "source": _ASM_AL},
    "steel_1018": {"condition": "cold drawn", "basis": "minimum", "Sut_MPa": 440, "Sy_MPa": 370, "E_GPa": 207,
                   "nu": 0.292, "source": _SHIGLEY_A20},
    "steel_1045": {"condition": "cold drawn", "basis": "minimum", "Sut_MPa": 630, "Sy_MPa": 530, "E_GPa": 207,
                   "nu": 0.292, "source": _SHIGLEY_A20},
    "steel_4140": {"condition": "annealed", "basis": "typical", "Sut_MPa": 655, "Sy_MPa": 415, "E_GPa": 205,
                   "nu": 0.29, "source": "ASM Handbook Vol. 1 typical properties"},
    "ss_304": {"condition": "annealed plate/sheet", "basis": "minimum", "Sut_MPa": 515, "Sy_MPa": 205,
               "E_GPa": 193, "nu": 0.29, "source": "ASTM A240 (minimum); E, ν typical (ASM)"},
    "ss_316": {"condition": "annealed plate/sheet", "basis": "minimum", "Sut_MPa": 515, "Sy_MPa": 205,
               "E_GPa": 193, "nu": 0.29, "source": "ASTM A240 (minimum); E, ν typical (ASM)"},
    "ss_17_4": {"condition": "H900", "basis": "minimum", "Sut_MPa": 1310, "Sy_MPa": 1170, "E_GPa": 197,
                "nu": 0.27, "source": "ASTM A564 Type 630 H900 (minimum); E, ν typical (ASM)"},
    "cast_iron_gray": {"condition": "ASTM A48 class 30", "basis": "minimum", "Sut_MPa": 214, "Sy_MPa": None,
                       "E_GPa": 100, "nu": 0.26, "brittle": True,
                       "source": "ASTM A48 class 30 / Shigley Table A-24; E varies 90 to 115 GPa with stress level"},
    "ti_6al4v": {"condition": "annealed (Grade 5)", "basis": "minimum", "Sut_MPa": 895, "Sy_MPa": 828,
                 "E_GPa": 114, "nu": 0.34, "source": "ASTM B348 Grade 5 (minimum); E, ν typical (ASM)"},
}


def mechanical(code: str | None) -> dict[str, object] | None:
    """Mechanical properties with provenance for a material code, or None when no cited values exist."""
    m = get(code)
    props = MECHANICAL.get(code or "")
    if m is None or props is None:
        return None
    return {"code": code, "name": m["name"], **props, "version": MECHANICAL_VERSION, "note": MECHANICAL_NOTE}
