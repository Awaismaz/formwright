"""Detail views (DRW-011): a circular region of a view, redrawn at a larger standard scale.

Pure Python (no kernel). The user picks a circle on a parent view in that view's model coordinates (U, V in mm, as
in ``geometry``); the detail is the parent's exact projected primitives clipped to that circle, so it regenerates
with the model like every other view. ISO 128-30 style: a thin circle and a capital letter on the parent view, the
detail captioned "DETAIL B (5:1)" with its own scale. Letters follow the section letter (A) and skip I, O and Q.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from aicad.drawing import DrawingInputError

LETTERS = [c for c in "ABCDEFGHJKLMNPRSTUVWXYZ"]  # ISO: I, O and Q are not used as view letters
PARENTS = ("front", "top", "right", "section")
MAX_DETAILS = 6
EPS = 1e-9


def normalize(raw: Any) -> list[dict[str, Any]]:
    """User detail requests, sanitised: [{view, u, v, r, scale "5:1" | None}] (at most six)."""
    out: list[dict[str, Any]] = []
    for d in (raw or [])[:MAX_DETAILS] if isinstance(raw, list) else []:
        if not isinstance(d, dict) or d.get("view") not in PARENTS:
            continue
        try:
            u, v, r = float(d["u"]), float(d["v"]), float(d["r"])
        except (KeyError, TypeError, ValueError):
            raise DrawingInputError("A detail view needs a centre and a radius on a view.") from None
        if not all(math.isfinite(x) and abs(x) < 1e6 for x in (u, v, r)) or r <= 0.05:
            raise DrawingInputError("A detail circle must have a radius above 0.05 mm.")
        sc = d.get("scale")
        scale = None
        if sc:
            try:
                a, b = (int(x) for x in str(sc).split(":"))
            except ValueError:
                raise DrawingInputError(f"Detail scale “{str(sc)[:8]}” must look like 2:1 or 5:1.") from None
            if (a, b) not in STANDARD:
                raise DrawingInputError("Detail scale must be a standard scale (2:1, 5:1, 10:1, 20:1, 1:1, 1:2, 1:5).")
            scale = f"{a}:{b}"
        out.append({"view": d["view"], "u": round(u, 4), "v": round(v, 4), "r": round(r, 4), "scale": scale})
    return out


#: standard scales a detail may use (ISO 5455), largest first
STANDARD = [(50, 1), (20, 1), (10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10)]


def letters(n: int, taken: set[str]) -> list[str]:
    return [c for c in LETTERS if c not in taken][:n]


def choose_scale(requested: str | None, sheet_scale: float, r: float, max_dia: float = 110.0) -> tuple[int, int]:
    """The detail's scale: the requested one when it enlarges the sheet scale, else the largest standard scale at
    least twice the sheet scale whose circle stays within ``max_dia`` paper mm (else the smallest enlargement)."""
    if requested:
        a, b = (int(x) for x in requested.split(":"))
        if a / b > sheet_scale + EPS:
            return a, b
    up = [s for s in STANDARD if s[0] / s[1] > sheet_scale + EPS]
    if not up:
        return STANDARD[0]
    good = [s for s in up if s[0] / s[1] >= 2 * sheet_scale - EPS and 2 * r * s[0] / s[1] <= max_dia + EPS]
    if good:
        return good[0]
    return min(up, key=lambda s: s[0] / s[1])


# ----------------------------------------------------------------------------- clipping to a circle
def _seg_t(p: tuple[float, float], q: tuple[float, float], c: tuple[float, float], r: float) -> tuple[float, float] | None:
    """Parameter interval [t0, t1] within [0, 1] of the segment p-q inside the circle (c, r), or None."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    fx, fy = p[0] - c[0], p[1] - c[1]
    a = dx * dx + dy * dy
    if a < EPS:
        return (0.0, 1.0) if fx * fx + fy * fy <= r * r else None
    b = 2 * (fx * dx + fy * dy)
    cc = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * cc
    if disc <= 0:
        return None
    sq = math.sqrt(disc)
    t0, t1 = max(0.0, (-b - sq) / (2 * a)), min(1.0, (-b + sq) / (2 * a))
    return (t0, t1) if t1 - t0 > EPS else None


def _lerp(p: tuple[float, float], q: tuple[float, float], t: float) -> tuple[float, float]:
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def _r(x: float) -> float:
    v = round(x, 6)
    return 0.0 if v == 0 else v


def _arc_ranges(cx: float, cy: float, R: float, a0: float, a1: float, c: tuple[float, float], r: float
                ) -> list[tuple[float, float]]:
    """Sub-ranges (degrees, counter-clockwise from a0) of the arc (cx, cy, R, a0..a1) inside the circle (c, r)."""
    d = math.hypot(c[0] - cx, c[1] - cy)
    if d + R <= r + EPS:
        return [(a0, a1)]
    if d >= R + r - EPS or d + r <= R + EPS:
        return []
    # the two angles where the circles cross, then keep the pieces whose middle lies inside
    base = math.degrees(math.atan2(c[1] - cy, c[0] - cx))
    half = math.degrees(math.acos(max(-1.0, min(1.0, (R * R + d * d - r * r) / (2 * R * d)))))
    cuts = sorted({(x - a0) % 360.0 for x in (base - half, base + half)} | {0.0})
    span = a1 - a0
    cuts = [x for x in cuts if x < span - EPS] + [span]
    out = []
    for s, e in itertools.pairwise(cuts):
        m = math.radians(a0 + (s + e) / 2)
        if math.hypot(cx + R * math.cos(m) - c[0], cy + R * math.sin(m) - c[1]) <= r:
            out.append((a0 + s, a0 + e))
    return out


def clip(prims: list[list[Any]], cu: float, cv: float, r: float) -> list[list[Any]]:
    """View primitives (geometry.py format: line / circle / arc / poly) clipped to the circle (cu, cv, r)."""
    c = (cu, cv)
    out: list[list[Any]] = []
    for p in prims:
        k = p[0]
        if k == "line":
            a, b = (p[1], p[2]), (p[3], p[4])
            t = _seg_t(a, b, c, r)
            if t:
                s, e = _lerp(a, b, t[0]), _lerp(a, b, t[1])
                out.append(["line", _r(s[0]), _r(s[1]), _r(e[0]), _r(e[1])])
        elif k == "poly":
            run: list[tuple[float, float]] = []
            for a0, b0 in itertools.pairwise(p[1]):
                a, b = (a0[0], a0[1]), (b0[0], b0[1])
                t = _seg_t(a, b, c, r)
                if not t:
                    if len(run) > 1:
                        out.append(["poly", [[_r(x), _r(y)] for x, y in run]])
                    run = []
                    continue
                s, e = _lerp(a, b, t[0]), _lerp(a, b, t[1])
                if run and math.dist(run[-1], s) < 1e-9:
                    run.append(e)
                else:
                    if len(run) > 1:
                        out.append(["poly", [[_r(x), _r(y)] for x, y in run]])
                    run = [s, e]
            if len(run) > 1:
                out.append(["poly", [[_r(x), _r(y)] for x, y in run]])
        elif k in ("circle", "arc"):
            cx, cy, R = p[1], p[2], p[3]
            a0, a1 = (0.0, 360.0) if k == "circle" else (p[4], p[5])
            ranges = _arc_ranges(cx, cy, R, a0, a1, c, r)
            if k == "circle" and ranges == [(0.0, 360.0)]:
                out.append(list(p))
                continue
            for s, e in ranges:
                out.append(["arc", cx, cy, R, _r(s % 360.0), _r(s % 360.0 + (e - s))])
    return out


def geometry(view_geom: dict[str, Any], d: dict[str, Any], hidden: bool) -> dict[str, Any]:
    """The detail's own view data: the parent's visible (and hidden) primitives inside the circle, extents = the
    circle's box (so the layout scales the circle, not just what is in it)."""
    u, v, r = d["u"], d["v"], d["r"]
    vis = clip(view_geom.get("visible", []), u, v, r)
    hid = clip(view_geom.get("hidden", []), u, v, r) if hidden else []
    hatch = []
    if view_geom.get("loops"):  # a detail of a section keeps its hatching inside the circle
        hatch = view_geom["loops"]
    return {"visible": vis, "hidden": hid, "extents": [u - r, u + r, v - r, v + r], "circle": [u, v, r],
            "loops": hatch, "parent": d["view"]}
