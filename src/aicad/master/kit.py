"""Helpers for master-model scripts (``model.py`` written by the master turn, or a recorded one).

A master script models the whole mechanism coarsely in ONE coordinate system: one solid per planned part, copies as
separate solids, axis-aligned, mating faces exactly coincident, holes where the fasteners go. It ends with::

    result = mk.master({"Enclosure base": base, "Enclosure lid": lid})      # copies: {"Leg": [leg1, leg2, ...]}
    EXPECTED = {"solids": mk.count()}

``mk.box`` / ``mk.cyl`` are centred primitives; ``mk.drill`` cuts a hole along an axis from a face. Everything else is
plain build123d. Pure helpers: the measurement (``aicad.master.measure``) reads the labelled solids back.
"""

from __future__ import annotations

from typing import Any

from build123d import Axis, Box, Compound, Cylinder, Pos, Rot, Shape

_AXES = {"x": (0, 90, 0), "y": (-90, 0, 0), "z": (0, 0, 0)}
_LAST = {"n": 0}


def box(L: float, W: float, H: float, at: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Any:
    """A box L (X) x W (Y) x H (Z) centred on ``at``."""
    return Pos(*at) * Box(L, W, H)


def cyl(d: float, length: float, at: tuple[float, float, float] = (0.0, 0.0, 0.0), axis: str = "z") -> Any:
    """A cylinder Ø d x length centred on ``at``, its axis along ``axis`` ("x", "y" or "z")."""
    return Pos(*at) * Rot(*_AXES[axis]) * Cylinder(d / 2, length)


def drill(part: Any, at: tuple[float, float, float], d: float, depth: float, axis: str = "z", sign: int = -1) -> Any:
    """A hole Ø d, ``depth`` deep, starting at the point ``at`` (on a face) and going along ``sign`` x ``axis``."""
    k = "xyz".index(axis)
    c = list(at)
    c[k] += sign * depth / 2
    return part - cyl(d, depth, tuple(c), axis)  # type: ignore[arg-type]


def master(bodies: dict[str, Any]) -> Any:
    """The master model: a compound of labelled solids, one per planned part (a list for copies: "Leg #1" ...)."""
    out: list[Shape] = []
    for name, v in bodies.items():
        items = v if isinstance(v, (list, tuple)) else [v]
        for k, s in enumerate(items):
            solids = s.solids() if hasattr(s, "solids") else []
            if len(solids) != 1:
                raise ValueError(f"master body {name!r} must be one solid (got {len(solids)})")
            sol = solids[0]
            sol.label = f"{name} #{k + 1}" if len(items) > 1 else str(name)
            out.append(sol)
    _LAST["n"] = len(out)
    return Compound(children=out)


def count() -> int:
    """The number of bodies the last ``master`` call made (for ``EXPECTED = {"solids": mk.count()}``)."""
    return int(_LAST["n"])


__all__ = ["Axis", "box", "count", "cyl", "drill", "master"]
