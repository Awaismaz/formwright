"""Deterministic sizing from standards tables and stated design rules (no model, no kernel).

Each function returns the numbers and a short source line (shown in the graph as the value's ``note``). The tables
are the repo's single copies: DIN 6885-1 keys (``toolbox.KEY_ROWS``, equal to ``office.icd.KEYS`` by test), ISO 15
deep-groove ball bearings (``toolbox.BEARING``), DIN 471 retaining rings (``toolbox.DIN471``), ISO 273 clearance holes
and ISO 286 fits (``office.icd``). Values typed from public references are marked "verify" where they are shown.

Rules that are design choices, not standards (stated so they can be checked by hand):
* face width of a spur gear when the brief gives none: b = 10 m (the office layout's rule);
* the larger step behind a hub seat: ``icd.shoulder_for`` (Ø20 -> Ø26);
* the key length: floor(max(b + 2, B - 2)) for a hub B wide, capped at B (the office layout's rule);
* the output shaft of a reduction when the brief gives no size: torsion scales the Ø with the cube root of the
  torque, so d_out = the smallest bearing bore >= d_in x ratio^(1/3) (Ø20 at 3:1 -> 28.8 -> Ø30);
* the teeth of a reduction pair from the ratio: z1 = 20 (no undercut at 20° for z >= 17), z2 = round(i z1).
"""

from __future__ import annotations

import math
from typing import Any

from aicad import toolbox
from aicad.office import icd

PRESSURE_ANGLE = 20.0
PINION_TEETH = 20          # default pinion teeth for a ratio (no undercut at 20 deg for z >= 17)
MIN_TEETH = 12             # the Toolbox generator's lower limit
FACE_PER_MODULE = 10.0     # b = 10 m


# ----------------------------------------------------------------------------- keys (DIN 6885-1 form A)
def key_for_shaft(d: float) -> dict[str, float]:
    """{"b", "h", "t1", "t2"} for a shaft Ø d (over lo, up to hi). ValueError outside the table (8 .. 65)."""
    try:
        b, h, t1, t2 = toolbox.key_row(float(d))
    except toolbox.ToolboxError as e:
        raise ValueError(str(e)) from None
    return {"b": b, "h": h, "t1": t1, "t2": t2}


def key_length(b: float, hub_width: float) -> float:
    """The office layout's key length for a hub ``hub_width`` wide: floor(max(b + 2, B - 2)), never above B."""
    return float(min(math.floor(max(b + 2, hub_width - 2)), math.floor(hub_width)))


# ----------------------------------------------------------------------------- bearings (ISO 15)
def bearing_dims(designation: int) -> dict[str, float]:
    d, D, B = toolbox.BEARING[int(designation)]
    return {"d": float(d), "D": float(D), "B": float(B)}


def bearing_for_journal(d: float, series: str | None = None, designation: int | None = None) -> int | None:
    """The deep-groove ball bearing for a journal Ø d: the written designation if its bore fits, else the 62xx (or
    the asked series) bearing with the largest bore not above d (the office layout's rule, ``icd.bearing_for``)."""
    if designation is not None:
        return icd.bearing_for(float(d), int(designation))
    if series in ("60", "62"):
        fit = [k for k, v in toolbox.BEARING.items() if str(k).startswith(series) and v[0] <= d + 1e-9]
        return max(fit, key=lambda k: toolbox.BEARING[k][0]) if fit else None
    return icd.bearing_for(float(d))


def bearing_bores(series: str = "62") -> list[float]:
    return sorted({float(v[0]) for k, v in toolbox.BEARING.items() if str(k).startswith(series)})


# ----------------------------------------------------------------------------- retaining rings (DIN 471)
def circlip_groove(d: float) -> dict[str, float]:
    """DIN 471 ring for a shaft d1 = d: ring thickness s, groove Ø d2, groove width m, min edge distance n, groove
    depth t = (d1 - d2) / 2."""
    try:
        s, b, d2, m, n = toolbox.ring_row(float(d))
    except toolbox.ToolboxError as e:
        raise ValueError(str(e)) from None
    return {"s": s, "b": b, "d2": d2, "m": m, "n": n, "t": round((float(d) - d2) / 2, 3)}


# ----------------------------------------------------------------------------- spur gears (ISO 53, alpha 20 deg)
def gear_geometry(m: float, z: int, b: float | None = None) -> dict[str, float]:
    """Pitch Ø m z, tip Ø m (z + 2), root Ø m (z - 2.5), face width (10 m unless given), and the largest bore the
    Toolbox generator allows (inside the root circle minus a rim of one module)."""
    m, z = float(m), int(z)
    return {"pitch_d": m * z, "tip_d": m * (z + 2), "root_d": m * (z - 2.5),
            "face_width": float(b) if b else FACE_PER_MODULE * m,
            "max_bore": round(2 * (m * z / 2 - 1.25 * m - m), 3)}


def centre_distance(m: float, z1: int, z2: int) -> float:
    """a = m (z1 + z2) / 2 (external spur pair, no profile shift)."""
    return float(m) * (int(z1) + int(z2)) / 2


def teeth_for_ratio(ratio: float, z1: int = PINION_TEETH) -> tuple[int, int]:
    return int(z1), round(float(ratio) * int(z1))


def bore_fits_gear(m: float, z: int, bore: float, key_t2: float = 0.0) -> bool:
    """The Toolbox gear's rules: the bore inside the root circle minus a rim of one module, and a hub keyway's top
    inside the root circle minus half a module."""
    rf = m * z / 2 - 1.25 * m
    return 0 < bore / 2 < rf - m and (not key_t2 or bore / 2 + key_t2 < rf - m / 2)


# ----------------------------------------------------------------------------- shafts
def shoulder_for(d: float) -> float:
    return icd.shoulder_for(float(d))


def output_shaft(d_in: float, ratio: float, series: str = "62") -> float:
    """d_out = the smallest bearing bore >= d_in x ratio^(1/3) (torsion: d grows with the cube root of torque)."""
    want = float(d_in) * float(ratio) ** (1.0 / 3.0)
    return next((x for x in bearing_bores(series) if x >= want - 1e-9), bearing_bores(series)[-1])


# ----------------------------------------------------------------------------- fits, holes (ISO 286, ISO 273)
FIT_HUB = "H7/k6"        # a keyed hub on its seat (transition fit)
FIT_BEARING_SHAFT = icd.SHAFT_FIT_BEARING  # k6: rotating inner ring, normal load
FIT_BEARING_HOUSING = "H7"


def fit_limits(d: float, fit: str) -> dict[str, Any]:
    hole, shaft = icd.fit_zones(float(d), fit)
    return {"hole": hole, "shaft": shaft}


def clearance_hole(m: int) -> float:
    return float(icd.CLEARANCE[int(m)])


def source_note(kind: str, d: float | None = None) -> str:
    dd = f"Ø{d:g}" if d is not None else "the seat"
    return {"key": f"DIN 6885-1 for {dd}", "bearing": f"ISO 15, largest 62xx bore not above {dd}",
            "ring": f"DIN 471 for {dd} (verify)", "shoulder": "shoulder step max(2.5, 0.1 d + 1) per side",
            "face": "face width 10 m", "mesh": "a = m (z1 + z2) / 2"}.get(kind, kind)
