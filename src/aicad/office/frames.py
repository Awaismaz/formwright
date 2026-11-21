"""Rigid frames for the Design Office (pure Python): quarter-turn rotations, transforming a part's measured data
(recognised holes, exact planes and cylinders, bounding box) between frames, and the 12-number placements Assembly
Studio uses.

A frame ``F = {"R": 3x3 rows, "t": [x, y, z]}`` maps a point of a part as modelled to its ICD part frame:
``x_icd = R x + t``. Gage finds it by best fit (``conformance.best_frame``); Fitz places the real part through it.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

Mat = list[list[float]]
IDENT: Mat = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
# Canonical feature frames (Phase 6): rotation canonical -> part frame whose canonical Z is the named part axis. A
# cylindrical feature (hole, seat, journal, keyway) or a plane along part axis ``ax`` is written in its canonical
# frame, so every measurement / cut written for Z features works for X and Y features unchanged.
CANON: dict[str, Mat] = {
    "z": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    "y": [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]],   # Rx(-90 deg): canonical Z -> +Y, canonical Y -> -Z
    "x": [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]],   # Ry(+90 deg): canonical Z -> +X, canonical X -> -Z
}


def _clean(v: float) -> float:
    r = round(float(v), 9)
    return 0.0 if r == 0 else r


def rot_z(deg: float) -> Mat:
    """Rotation about +Z by ``deg`` (exact for quarter turns)."""
    q = round(deg / 90.0)
    if abs(deg - 90.0 * q) < 1e-9:
        c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][q % 4]
    else:
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[float(c), float(-s), 0.0], [float(s), float(c), 0.0], [0.0, 0.0, 1.0]]


def mul(a: Mat, b: Mat) -> Mat:
    return [[_clean(sum(a[i][k] * b[k][j] for k in range(3))) for j in range(3)] for i in range(3)]


def apply(R: Mat, v: Any) -> list[float]:
    return [_clean(R[i][0] * float(v[0]) + R[i][1] * float(v[1]) + R[i][2] * float(v[2])) for i in range(3)]


def transpose(R: Mat) -> Mat:
    return [[R[j][i] for j in range(3)] for i in range(3)]


def det(R: Mat) -> float:
    return (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1]) - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
            + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))


def quarter_turns() -> list[Mat]:
    """The 24 proper rotations that map the axes onto the axes (identity first, then turns about Z first)."""
    out: list[Mat] = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            R = [[0.0] * 3 for _ in range(3)]
            for i, j in enumerate(perm):
                R[i][j] = float(signs[i])
            if det(R) > 0:
                out.append(R)

    def key(R: Mat) -> tuple[int, int]:
        z_kept = R[2][2] == 1.0
        return (0 if R == IDENT else 1 if z_kept else 2, out.index(R))
    return sorted(out, key=key)


def label(R: Mat, t: list[float]) -> str:
    """Plain words: "rotated 90° about Z, moved by (0, 0, 5) mm"."""
    bits = []
    if R != IDENT:
        if R[2][2] == 1.0:
            ang = round(math.degrees(math.atan2(R[1][0], R[0][0]))) % 360
            bits.append(f"rotated {ang}° about Z")
        else:
            z = apply(R, [0, 0, 1])
            ax = "XYZ"[max(range(3), key=lambda k: abs(z[k]))]
            bits.append(f"turned so its Z axis lies along {'+' if z['XYZ'.index(ax)] > 0 else '−'}{ax}")
    if any(abs(x) > 1e-6 for x in t):
        bits.append("moved by (" + ", ".join(f"{x:g}" for x in (round(v, 3) + 0.0 for v in t)) + ") mm")
    return ", ".join(bits) if bits else "the ICD frame"


def frame(R: Mat, t: list[float]) -> dict[str, Any]:
    t = [_clean(round(x, 6)) for x in t]
    return {"R": R, "t": t, "identity": R == IDENT and not any(abs(x) > 1e-6 for x in t), "label": label(R, t)}


def to12(R: Mat, t: Any) -> list[float]:
    return [R[0][0], R[0][1], R[0][2], float(t[0]), R[1][0], R[1][1], R[1][2], float(t[1]),
            R[2][0], R[2][1], R[2][2], float(t[2])]


def compose(R1: Mat, t1: Any, R2: Mat, t2: Any) -> tuple[Mat, list[float]]:
    """(R1, t1) after (R2, t2): x -> R1 (R2 x + t2) + t1."""
    return mul(R1, R2), [_clean(a + b) for a, b in zip(apply(R1, t2), t1, strict=True)]


# ----------------------------------------------------------------------------- measured part data in another frame
def info_in(info: dict[str, Any], R: Mat, t: list[float]) -> dict[str, Any]:
    """Recognised holes / gear / bounding box of a part (``info.json``) mapped by x -> R x + t."""
    out = dict(info)
    out["holes"] = [{**h, "center": [a + b for a, b in zip(apply(R, h["center"]), t, strict=True)],
                     "axis": apply(R, h["axis"])} for h in info.get("holes") or []]
    if info.get("partials"):
        out["partials"] = [{**h, "center": [a + b for a, b in zip(apply(R, h["center"]), t, strict=True)],
                            "axis": apply(R, h["axis"])} for h in info["partials"]]
    comp = info.get("component")
    if comp:
        o = comp.get("origin") or [0, 0, 0]
        out["component"] = {**comp, "origin": [a + b for a, b in zip(apply(R, o), t, strict=True)],
                            "axis": apply(R, comp.get("axis") or [0, 0, 1])}
    bb = info.get("bbox")
    if bb:
        pts = [apply(R, (bb[i], bb[j], bb[k])) for i in (0, 3) for j in (1, 4) for k in (2, 5)]
        out["bbox"] = [min(p[a] for p in pts) + t[a] for a in range(3)] + [max(p[a] for p in pts) + t[a] for a in range(3)]
    return out


def refs_in(refs: dict[str, Any], R: Mat, t: list[float]) -> dict[str, Any]:
    """Exact planes (point + normal) and axes (point + direction, radius) of a part's faces and edges, mapped by
    x -> R x + t."""
    def move(d: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for fid, r in d.items():
            q = dict(r)
            if r.get("p") is not None:
                q["p"] = [a + b for a, b in zip(apply(R, r["p"]), t, strict=True)]
            if r.get("v") is not None:
                q["v"] = apply(R, r["v"])
            out[fid] = q
        return out
    return {**refs, "faces": move(refs.get("faces") or {}), "edges": move(refs.get("edges") or {})}


def item_rotation(ax: str = "z", rot: float = 0.0) -> Mat:
    """Part frame -> program frame of an ICD item: its part Z laid along program axis ``ax`` (a horizontal shaft:
    "y"), then turned ``rot`` degrees about its own Z (quarter turns of a block, a gear's tooth phase)."""
    return mul(CANON.get(ax or "z", IDENT), rot_z(rot))


def placed(at: list[float], rot: float = 0.0, f: dict[str, Any] | None = None, ax: str = "z") -> list[float]:
    """Assembly placement of a part: its ICD part frame at ``at`` (part Z along program ``ax``) turned ``rot``
    degrees about its Z, and the part as modelled mapped into that frame by ``f`` (None: modelled in the ICD
    frame)."""
    R, t = item_rotation(ax, rot), [float(x) for x in at]
    if f:
        R, t = compose(R, t, f["R"], f["t"])
    return to12(R, t)
