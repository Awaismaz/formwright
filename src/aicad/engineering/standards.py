"""Standards and handbook data used by the calculators, each table with its provenance and a version (ENG-003).

Values are transcribed from public references and textbooks. They are **typical / tabulated values: verify against
the current edition of the standard and the supplier certificate before release.** Bump ``VERSION`` whenever a value
changes so stored calculation sets show which data they used.
"""

from __future__ import annotations

from typing import Any

VERSION = "std-1.0.0"

SHIGLEY = "Budynas & Nisbett, Shigley's Mechanical Engineering Design, 10th/11th ed. (McGraw-Hill)"

# ----------------------------------------------------------------------------- ISO metric threads
# ISO 261 coarse pitch series (mm). Basic profile per ISO 68-1 / ISO 724.
COARSE_PITCH: dict[str, tuple[float, float]] = {
    "M3": (3.0, 0.5), "M4": (4.0, 0.7), "M5": (5.0, 0.8), "M6": (6.0, 1.0), "M8": (8.0, 1.25),
    "M10": (10.0, 1.5), "M12": (12.0, 1.75), "M14": (14.0, 2.0), "M16": (16.0, 2.0), "M20": (20.0, 2.5),
    "M24": (24.0, 3.0), "M30": (30.0, 3.5), "M36": (36.0, 4.0),
}
THREAD_SOURCE = "ISO 261 (coarse pitches), ISO 724 (basic dimensions), ISO 898-1 (tensile stress area formula)"

# ISO 273 clearance holes (mm): fine / medium / coarse series. Used to recognise a bolt size from a hole.
CLEARANCE_ISO273: dict[str, tuple[float, float, float]] = {
    "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0),
    "M8": (8.4, 9.0, 10.0), "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5), "M14": (15.0, 15.5, 16.5),
    "M16": (17.0, 17.5, 18.5), "M20": (21.0, 22.0, 24.0), "M24": (25.0, 26.0, 28.0), "M30": (31.0, 33.0, 35.0),
    "M36": (37.0, 39.0, 42.0),
}
CLEARANCE_SOURCE = "ISO 273 clearance holes for bolts and screws (fine / medium / coarse)"


def basic_diameters(d: float, p: float) -> dict[str, float]:
    """ISO 724 basic dimensions of a metric thread of nominal diameter d and pitch p (mm)."""
    return {"d2": d - 0.649519 * p,      # pitch diameter (external d2 = internal D2)
            "D1": d - 1.082532 * p,      # internal-thread minor diameter
            "d3": d - 1.226869 * p}      # external-thread minor diameter (root), ISO 898-1


def tensile_stress_area(d: float, p: float) -> float:
    """ISO 898-1: As = (π/4)·((d2 + d3)/2)², which reduces to (π/4)·(d − 0.938194·p)²."""
    b = basic_diameters(d, p)
    return 3.141592653589793 / 4 * ((b["d2"] + b["d3"]) / 2) ** 2


def bolt_from_clearance(hole_d: float, tol: float = 0.06) -> dict[str, Any] | None:
    """Nominal metric size whose ISO 273 clearance hole (any series) matches ``hole_d``."""
    best = None
    for size, series in CLEARANCE_ISO273.items():
        for name, v in zip(("fine", "medium", "coarse"), series, strict=True):
            err = abs(v - hole_d)
            if err <= tol and (best is None or err < best["err"]):
                best = {"size": size, "series": name, "clearance": v, "err": err}
    return best


# ----------------------------------------------------------------------------- ISO 898-1 property classes
# (min proof strength Sp, min tensile strength Sut, min yield strength Sy) in MPa, by nominal diameter range.
# ISO 898-1:2013 Table 3; same values in Shigley Table 8-11 (metric mechanical-property classes).
PROPERTY_CLASSES: dict[str, list[dict[str, float]]] = {
    "4.6": [{"d_max": 36, "Sp": 225, "Sut": 400, "Sy": 240}],
    "4.8": [{"d_max": 16, "Sp": 310, "Sut": 420, "Sy": 340}],
    "5.8": [{"d_max": 24, "Sp": 380, "Sut": 520, "Sy": 420}],
    "8.8": [{"d_max": 16, "Sp": 580, "Sut": 800, "Sy": 640}, {"d_max": 36, "Sp": 600, "Sut": 830, "Sy": 660}],
    "9.8": [{"d_max": 16, "Sp": 650, "Sut": 900, "Sy": 720}],
    "10.9": [{"d_max": 36, "Sp": 830, "Sut": 1040, "Sy": 940}],
    "12.9": [{"d_max": 36, "Sp": 970, "Sut": 1220, "Sy": 1100}],
}
PROPERTY_CLASS_SOURCE = "ISO 898-1:2013 Table 3 (also Shigley Table 8-11): minimum values"

# Fully corrected endurance strength of bolts with rolled threads, axial loading (MPa). Shigley Table 8-17.
BOLT_ENDURANCE: dict[str, float] = {"5.8": 93.0, "8.8": 129.0, "9.8": 140.0, "10.9": 162.0, "12.9": 190.0}
BOLT_ENDURANCE_SOURCE = "Shigley Table 8-17 (fully corrected, rolled threads, includes Kf)"


def property_class(cls: str, d: float) -> dict[str, float] | None:
    for row in PROPERTY_CLASSES.get(cls, []):
        if d <= row["d_max"] + 1e-9:
            return row
    return None


# Nut (torque) factor K, T = K·Fi·d. Shigley Table 8-15; actual K scatters widely (±30 % or more).
NUT_FACTORS: dict[str, float] = {"non-plated, black finish": 0.30, "zinc-plated": 0.20, "lubricated": 0.18,
                                 "cadmium-plated": 0.16}
NUT_FACTOR_SOURCE = "Shigley Table 8-15 (torque factors K); Shigley uses K = 0.2 when the finish is not stated"

# Shigley Table 8-7: threaded length of metric bolts, LT = 2d + 6 (L ≤ 125), 2d + 12 (125 < L ≤ 200), 2d + 25.


def threaded_length(d: float, L: float) -> float:
    return 2 * d + (6 if L <= 125 else 12 if L <= 200 else 25)


# ----------------------------------------------------------------------------- fatigue (Marin factors)
# Surface factor ka = a·Sut^b (Sut in MPa). Shigley Table 6-2 (10th ed.) / Eq. (6-19).
SURFACE_FACTOR: dict[str, tuple[float, float]] = {
    "ground": (1.58, -0.085), "machined": (4.51, -0.265), "cold-drawn": (4.51, -0.265),
    "hot-rolled": (57.7, -0.718), "as-forged": (272.0, -0.995),
}
# Reliability factor ke. Shigley Table 6-5 (10th ed.).
RELIABILITY_KE: dict[str, float] = {"50": 1.000, "90": 0.897, "95": 0.868, "99": 0.814, "99.9": 0.753,
                                    "99.99": 0.702, "99.999": 0.659}
MARIN_SOURCE = "Shigley §6-9, Eqs. (6-8), (6-18)–(6-20), Tables 6-2 and 6-5"

# ----------------------------------------------------------------------------- bearings
# ISO 281:2007 life modification factor for reliability a1 (Table 12).
BEARING_A1: dict[str, float] = {"90": 1.0, "95": 0.64, "96": 0.55, "97": 0.47, "98": 0.37, "99": 0.25,
                                "99.2": 0.22, "99.4": 0.19, "99.6": 0.16, "99.8": 0.12, "99.9": 0.093,
                                "99.92": 0.077, "99.94": 0.064, "99.95": 0.057}
BEARING_SOURCE = "ISO 281:2007 basic rating life L10 = (C/P)^p, p = 3 (ball) or 10/3 (roller); a1 from Table 12"

# ----------------------------------------------------------------------------- springs
# Shigley Table 10-4: Sut = A / d^m. (A in MPa·mm^m, m). Table 10-6: Ssy as a fraction of Sut (static, set removed
# not assumed). Table 10-5 gives G; we suggest a typical G and the user confirms it.
SPRING_WIRE: dict[str, dict[str, Any]] = {
    "A228": {"name": "Music wire (ASTM A228)", "A": 2211.0, "m": 0.145, "ssy": 0.45, "G": 81.0e3,
             "d_range": (0.10, 6.5)},
    "A227": {"name": "Hard-drawn wire (ASTM A227)", "A": 1783.0, "m": 0.190, "ssy": 0.45, "G": 80.0e3,
             "d_range": (0.7, 12.7)},
    "A229": {"name": "Oil-tempered wire (ASTM A229)", "A": 1855.0, "m": 0.187, "ssy": 0.50, "G": 77.2e3,
             "d_range": (0.5, 12.7)},
    "A232": {"name": "Chrome-vanadium wire (ASTM A232)", "A": 2005.0, "m": 0.168, "ssy": 0.50, "G": 77.2e3,
             "d_range": (0.8, 11.1)},
    "A401": {"name": "Chrome-silicon wire (ASTM A401)", "A": 1974.0, "m": 0.108, "ssy": 0.50, "G": 77.2e3,
             "d_range": (1.6, 9.5)},
}
SPRING_SOURCE = "Shigley Tables 10-1 (end types), 10-2 (buckling α), 10-4 (A, m), 10-5 (G), 10-6 (Ssy/Sut)"


def provenance() -> list[dict[str, Any]]:
    """Library listing for the UI (ENG-003): what tables exist, where they come from, which version."""
    return [
        {"table": "ISO metric coarse threads", "source": THREAD_SOURCE, "rows": len(COARSE_PITCH)},
        {"table": "ISO 273 clearance holes", "source": CLEARANCE_SOURCE, "rows": len(CLEARANCE_ISO273)},
        {"table": "Bolt property classes", "source": PROPERTY_CLASS_SOURCE, "rows": len(PROPERTY_CLASSES)},
        {"table": "Bolt endurance strength", "source": BOLT_ENDURANCE_SOURCE, "rows": len(BOLT_ENDURANCE)},
        {"table": "Nut factors K", "source": NUT_FACTOR_SOURCE, "rows": len(NUT_FACTORS)},
        {"table": "Marin surface and reliability factors", "source": MARIN_SOURCE,
         "rows": len(SURFACE_FACTOR) + len(RELIABILITY_KE)},
        {"table": "Bearing reliability factor a1", "source": BEARING_SOURCE, "rows": len(BEARING_A1)},
        {"table": "Spring wire strengths", "source": SPRING_SOURCE, "rows": len(SPRING_WIRE)},
    ]
