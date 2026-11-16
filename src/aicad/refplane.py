"""Reference plane placement (pure Python, no CAD kernel), shared by `fw` (model builds) and the Studio API."""

from __future__ import annotations

import math
from typing import Any

NON_GEOMETRIC = {"plane", "sketch2d"}  # reference planes and sketch nodes: in the tree, never change the solid

V = tuple[float, float, float]


def _unit(v: V) -> V:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-12:
        raise ValueError("zero-length direction")
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: V, b: V) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: V, b: V) -> V:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _rot(v: V, k: V, ang: float) -> V:
    """Rotate v about the unit axis k by ang radians (Rodrigues)."""
    c, s = math.cos(ang), math.sin(ang)
    kxv, kv = _cross(k, v), _dot(k, v) * (1 - c)
    return (v[0] * c + kxv[0] * s + k[0] * kv, v[1] * c + kxv[1] * s + k[1] * kv, v[2] * c + kxv[2] * s + k[2] * kv)


def ref_plane(f: dict[str, Any]) -> dict[str, list[float]]:
    """Resolved placement of a reference plane feature: its base plane, optionally turned by `angle` degrees about
    the base plane's own X or Y axis (through the base origin), then moved `offset` mm along the resulting normal.
    A pure function of the feature's numbers, so it is identical on every rebuild and in any tree order."""
    b = f["base"]
    o: V = tuple(float(c) for c in b["origin"])  # type: ignore[assignment]
    n = _unit(tuple(float(c) for c in b["normal"]))  # type: ignore[arg-type]
    x0: V = tuple(float(c) for c in (b.get("x_dir") or (1, 0, 0)))  # type: ignore[assignment]
    d = _dot(x0, n)
    x = _unit((x0[0] - n[0] * d, x0[1] - n[1] * d, x0[2] - n[2] * d))
    y = _cross(n, x)
    ang = math.radians(float(f.get("angle") or 0))
    if abs(ang) > 1e-12:
        k = y if f.get("rot_axis") == "y" else x
        n, x = _unit(_rot(n, k, ang)), _unit(_rot(x, k, ang))
    off = float(f.get("offset") or 0)
    o = (o[0] + n[0] * off, o[1] + n[1] * off, o[2] + n[2] * off)

    def clean(v: V) -> list[float]:
        return [round(c, 12) + 0.0 for c in v]
    return {"origin": clean(o), "normal": clean(n), "x_dir": clean(x)}
