"""Reference tables and published design guidance used by the DFM rules.

Every value here is either a standard table typed from public references (flagged "verify against the standard
before production", as for the Toolbox, PD-13) or a published rule of thumb with its source named. Rules compare
measured geometry with these values; they never claim a part is manufacturable.
"""

from __future__ import annotations

import math

TABLES_VERSION = "mfg-tables 1.0 (2026-11-16)"
VERIFY = "Typed from public references; verify against the standard and your shop before production."

# ISO 273 clearance holes for bolts and screws: thread -> (fine, medium, coarse) hole diameter, mm.
ISO_273: dict[str, tuple[float, float, float]] = {
    "M1.6": (1.7, 1.8, 2.0), "M2": (2.2, 2.4, 2.6), "M2.5": (2.7, 2.9, 3.1), "M3": (3.2, 3.4, 3.6),
    "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0), "M8": (8.4, 9.0, 10.0),
    "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5), "M14": (15.0, 15.5, 16.5), "M16": (17.0, 17.5, 18.5),
    "M20": (21.0, 22.0, 24.0), "M24": (25.0, 26.0, 28.0), "M30": (31.0, 33.0, 35.0), "M36": (37.0, 39.0, 42.0),
}
ISO_273_SOURCE = "ISO 273 clearance holes (fine / medium / coarse series)"

# Tap drill diameters for ISO metric coarse threads (ISO 261 pitch), common workshop values (D - P), mm.
TAP_DRILL: dict[str, float] = {
    "M1.6": 1.25, "M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2, "M6": 5.0, "M8": 6.8, "M10": 8.5,
    "M12": 10.2, "M14": 12.0, "M16": 14.0, "M20": 17.5, "M24": 21.0, "M30": 26.5, "M36": 32.0,
}
TAP_DRILL_SOURCE = "Tap drill sizes for ISO metric coarse threads (ISO 261 pitches; DIN 336 workshop practice)"

# Stocked metric twist drill series (DIN 338 / ISO 235 ranges as commonly stocked):
# 0.5-13.0 mm in 0.1 mm steps, 13.0-20.0 in 0.5 mm steps, 20-32 in 1 mm steps.
DRILL_SERIES_SOURCE = "Stocked metric twist drills (DIN 338 / ISO 235 ranges): 0.1 mm steps to 13 mm, " \
                      "0.5 mm to 20 mm, 1 mm to 32 mm"
DRILL_MAX = 32.0
MATCH_TOL = 0.005

# Published CNC design guidance (Hubs / Protolabs Network "CNC machining design guide", public web guide).
HUBS = "Hubs (Protolabs Network) CNC machining design guide"
GUIDE = {
    "hole_ld_recommended": 4.0,  # recommended hole depth 4 x nominal diameter
    "hole_ld_typical_max": 10.0,  # typical maximum 10 x D (deeper needs special drilling)
    "cavity_depth_to_width": 4.0,  # recommended cavity depth up to 4 x width
    "corner_radius_to_depth": 1 / 3,  # internal vertical corner radius >= 1/3 of cavity depth
    "min_wall_metal": 0.8,  # mm
    "min_wall_plastic": 1.5,  # mm
}

# Turning rules of thumb (common workshop practice; verify with your shop).
TURN = {
    "ld_chuck_only": 3.0,  # L/D above which a tailstock centre is normally used
    "ld_steady_rest": 10.0,  # L/D above which a steady rest / special support is normally needed
    "insert_nose_radii": (0.4, 0.8),  # mm, e.g. ISO 1832 insert designations CNMG 120404 / 120408
}
TURN_SOURCE = "Common turning practice; insert nose radii per ISO 1832 designations (e.g. CNMG 120404 / 120408)"

# Moulding / casting guidance (only applied as a screening check).
MOULD = {
    "min_draft_deg": 1.0,  # common injection moulding guidance: 1-2 degrees, 0.5 minimum
    "max_wall_plastic": 4.0,  # mm, typical upper end for thermoplastic walls
    "wall_ratio": 2.0,  # thickest / thinnest wall above which sink and warp risk rise
}
MOULD_SOURCE = "Common injection moulding and casting design guidance (e.g. Protolabs design guidelines)"


def _on_step(d: float, start: float, stop: float, step: float) -> bool:
    if not (start - MATCH_TOL <= d <= stop + MATCH_TOL):
        return False
    k = round((d - start) / step)
    return abs(start + k * step - d) <= MATCH_TOL


def is_stock_drill(d: float) -> bool:
    return _on_step(d, 0.5, 13.0, 0.1) or _on_step(d, 13.0, 20.0, 0.5) or _on_step(d, 20.0, DRILL_MAX, 1.0) \
        or any(abs(d - v) <= MATCH_TOL for v in TAP_DRILL.values())


def nearest_stock_drill(d: float) -> float:
    if d <= 13.0:
        cand = round(d * 10) / 10
    elif d <= 20.0:
        cand = round(d * 2) / 2
    else:
        cand = float(round(d))
    return round(max(0.5, min(DRILL_MAX, cand)), 2)


def match_standard_hole(d: float) -> list[str]:
    """Names of the standard holes a diameter matches, e.g. ['ISO 273 medium clearance for M6']."""
    out: list[str] = []
    for thread, (f, m, c) in ISO_273.items():
        for series, v in (("fine", f), ("medium", m), ("coarse", c)):
            if abs(d - v) <= MATCH_TOL:
                out.append(f"ISO 273 {series} clearance for {thread}")
    for thread, v in TAP_DRILL.items():
        if abs(d - v) <= MATCH_TOL:
            out.append(f"tap drill for {thread} coarse")
    return out


def fmt(v: float, nd: int = 2) -> str:
    """Compact number: 6.6 -> '6.6', 3.0 -> '3', 0.333 -> '0.33'."""
    if not math.isfinite(v):
        return "∞"
    s = f"{v:.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s
