"""Unit safety for engineering calculators (pint, BSD-3-Clause).

Every numeric calculator input and output has a *kind* (length, force, stress, ...). Values arriving from the API carry
their own unit (``{"value": 0.5, "unit": "in"}``); they are converted with pint to the kind's canonical unit before the
calculation runs, and a unit of the wrong dimension (a force given in mm) is rejected. Calculators therefore work in
one consistent set: N, mm, MPa (= N/mm^2), N*mm, rev/min, hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pint


@lru_cache(maxsize=1)
def ureg() -> pint.UnitRegistry:
    return pint.UnitRegistry()


class UnitError(ValueError):
    """An input carried a unit pint does not know or of the wrong dimension."""


@dataclass(frozen=True)
class Kind:
    canonical: str          # pint expression of the unit calculators use internally
    label: str              # display label for the canonical unit
    units: tuple[str, ...]  # units offered in the UI (pint expressions); canonical first


# pint expressions -> UI labels
LABELS = {
    "mm": "mm", "m": "m", "cm": "cm", "in": "in", "ft": "ft", "um": "µm",
    "N": "N", "kN": "kN", "lbf": "lbf", "kip": "kip",
    "MPa": "MPa", "GPa": "GPa", "kPa": "kPa", "psi": "psi", "ksi": "ksi", "Mpsi": "Mpsi",
    "N*mm": "N·mm", "N*m": "N·m", "kN*m": "kN·m", "lbf*in": "lbf·in", "lbf*ft": "lbf·ft",
    "N/mm": "N/mm", "kN/m": "kN/m", "N/m": "N/m", "lbf/in": "lbf/in", "kN/mm": "kN/mm", "MN/m": "MN/m",
    "mm**2": "mm²", "in**2": "in²", "mm**3": "mm³", "in**3": "in³", "mm**4": "mm⁴", "in**4": "in⁴",
    "rpm": "rev/min", "hour": "h", "1e6": "million rev", "kg": "kg", "g": "g", "lb": "lb",
    "kg*mm**2": "kg·mm²", "degree": "°", "": "",
}

KINDS: dict[str, Kind] = {
    "length": Kind("mm", "mm", ("mm", "m", "cm", "um", "in", "ft")),
    "force": Kind("N", "N", ("N", "kN", "lbf", "kip")),
    "stress": Kind("MPa", "MPa", ("MPa", "GPa", "kPa", "psi", "ksi", "Mpsi")),
    "moment": Kind("N*mm", "N·mm", ("N*mm", "N*m", "kN*m", "lbf*in", "lbf*ft")),
    "line_load": Kind("N/mm", "N/mm", ("N/mm", "N/m", "kN/m", "lbf/in")),
    "stiffness": Kind("N/mm", "N/mm", ("N/mm", "kN/mm", "MN/m", "lbf/in")),
    "area": Kind("mm**2", "mm²", ("mm**2", "in**2")),
    "section_modulus": Kind("mm**3", "mm³", ("mm**3", "in**3")),
    "inertia_area": Kind("mm**4", "mm⁴", ("mm**4", "in**4")),
    "speed": Kind("rpm", "rev/min", ("rpm",)),
    "time": Kind("hour", "h", ("hour",)),
    "mass": Kind("kg", "kg", ("kg", "g", "lb")),
    "mass_inertia": Kind("kg*mm**2", "kg·mm²", ("kg*mm**2",)),
    "angle": Kind("degree", "°", ("degree",)),
    "ratio": Kind("", "", ("",)),
    "count": Kind("", "", ("",)),
    "megarev": Kind("", "million rev", ("",)),  # bearing life in millions of revolutions (dimensionless count)
}


def label(unit: str) -> str:
    return LABELS.get(unit, unit)


def _special(unit: str) -> bool:
    return unit in ("", "rpm", "hour", "degree")


def to_canonical(kind: str, value: float, unit: str | None) -> float:
    """Convert ``value [unit]`` to the canonical unit of ``kind``. Raises UnitError on a wrong dimension."""
    k = KINDS[kind]
    if unit is None or unit == "" or unit == k.canonical or unit == k.label:
        return float(value)
    if _special(k.canonical):
        if unit not in k.units:
            raise UnitError(f"'{unit}' is not a valid unit for {kind}")
        return float(value)
    u = _parse_unit(unit)
    try:
        return float(ureg().Quantity(float(value), u).to(k.canonical).magnitude)
    except pint.DimensionalityError as e:
        raise UnitError(f"'{unit}' is not a {kind.replace('_', ' ')} unit") from e


def from_canonical(kind: str, value: float, unit: str | None) -> float:
    k = KINDS[kind]
    if unit is None or unit == "" or unit == k.canonical or _special(k.canonical):
        return float(value)
    u = _parse_unit(unit)
    try:
        return float(ureg().Quantity(float(value), k.canonical).to(u).magnitude)
    except pint.DimensionalityError as e:
        raise UnitError(f"'{unit}' is not a {kind.replace('_', ' ')} unit") from e


def _parse_unit(unit: str) -> str:
    rev = {v: k for k, v in LABELS.items()}
    u = rev.get(unit, unit).replace("·", "*").replace("²", "**2").replace("³", "**3").replace("⁴", "**4")
    if u == "Mpsi":
        return "megapsi"
    try:
        ureg().parse_units(u)
    except (pint.UndefinedUnitError, AttributeError, ValueError, TypeError) as e:
        raise UnitError(f"Unknown unit '{unit}'") from e
    return u


def quantity(kind: str, raw: Any) -> float:
    """Parse an API value: a number (canonical unit) or ``{"value": x, "unit": "in"}``."""
    if isinstance(raw, dict):
        if raw.get("value") is None or raw.get("value") == "":
            raise ValueError("missing value")
        return to_canonical(kind, float(raw["value"]), raw.get("unit"))
    if isinstance(raw, bool):
        raise ValueError("expected a number")  # noqa: TRY004 - callers map ValueError to a 422 message
    return float(raw)


def kinds_for_ui() -> dict[str, dict[str, Any]]:
    return {name: {"canonical": k.canonical, "label": k.label,
                   "units": [{"unit": u, "label": label(u)} for u in k.units]} for name, k in KINDS.items()}
