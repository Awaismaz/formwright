"""Placeholder bodies (CD-011): an item's envelope solid carrying its named interface features, so the program
assembly exists before any part is designed. Kernel side (worker / tests only).

Spec (part frame, mm; built by ``aicad.office.icd.placeholder_spec`` / ``icd.body_spec``):
  {"shape": "box" | "cylinder", "size": [L, W, H] (a cylinder: [D, D, H] along Z),
   "holes":    [{"c": [x, y], "d": Ø}]                              through along Z
   "seats":    [{"c": [x, y], "d": Ø, "z0", "z1"}]                  a bore over a Z range (bearing seat, clearance)
   "journals": [{"c": [x, y], "d": Ø, "z0", "z1"}]                  a shaft turned down to Ø over a Z range
   "keyways":  [{"on": "shaft" | "hub", "c", "d", "b", "depth", "dir": [dx, dy], "z0", "z1"}]  DIN 6885 grooves
   "grooves":  [{"c": [x, y], "d": Ø, "z0", "z1"}]                  a ring groove turned to Ø over a Z range (DIN 471)
   "pockets":  [{"min": [x, y, z], "max": [x, y, z]}]               a box removed (a housing's gear cavity)}
A hole with ``z0`` / ``z1`` is blind over that range (a tapped hole). A feature with ``"ax": "x" | "y"`` runs along
that part axis and is written in its canonical frame (``aicad.office.frames.CANON``: canonical Z = the feature
axis): the body is turned into that frame, cut with the same Z code, and turned back.
The body is centred on the origin (the part frame of the ICD).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


def _keyway(k: dict[str, Any], H: float) -> Any:
    """The material a keyway removes: ``b`` wide across the direction, from the groove bottom (shaft: r - depth) or
    the bore (hub: r - 1) outwards (shaft: r + 1, hub: r + depth), over Z (z0, z1; a hub keyway runs through)."""
    from build123d import Box, Pos, Rot

    r = float(k["d"]) / 2
    a, b_ = (r - float(k["depth"]), r + 1.0) if k["on"] == "shaft" else (r - 1.0, r + float(k["depth"]))
    z0, z1 = float(k["z0"]), float(k["z1"])
    if k["on"] == "hub":
        z0, z1 = -H / 2 - 1.0, H / 2 + 1.0
    dx, dy = float(k["dir"][0]), float(k["dir"][1])
    ang = math.degrees(math.atan2(dy, dx))
    mid = (a + b_) / 2
    cx, cy = float(k["c"][0]) + dx * mid, float(k["c"][1]) + dy * mid
    return Pos(cx, cy, (z0 + z1) / 2) * Rot(0, 0, ang) * Box(b_ - a, float(k["b"]), z1 - z0)


def shape(spec: dict[str, Any]) -> Any:
    from build123d import Box, Cylinder

    L, W, H = (float(x) for x in spec["size"])
    return cut(Box(L, W, H) if spec["shape"] == "box" else Cylinder(L / 2, H), spec)


# part frame -> canonical frame of a feature axis: (axis of the turn, degrees); the size permutation follows
_TO_CANON = {"y": ("X", 90.0, (0, 2, 1)), "x": ("Y", -90.0, (2, 1, 0))}


def cut(body: Any, spec: dict[str, Any]) -> Any:
    """Cut the spec's interface features into a body centred on the part frame."""
    from build123d import Axis, Box, Pos

    L, W, H = (float(x) for x in spec["size"])
    for pk in spec.get("pockets") or []:
        mn, mx = [float(v) for v in pk["min"]], [float(v) for v in pk["max"]]
        half = (L / 2, W / 2, H / 2)
        # open where it reaches a face: cut 1 mm past it so the face is clean
        mn = [m - 1.0 if m <= -half[k] + 1e-6 else m for k, m in enumerate(mn)]
        mx = [m + 1.0 if m >= half[k] - 1e-6 else m for k, m in enumerate(mx)]
        body = body - Pos(*[(a + b) / 2 for a, b in zip(mn, mx, strict=True)]) * Box(*[b - a for a, b in zip(mn, mx, strict=True)])
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key in ("journals", "holes", "seats", "keyways", "grooves"):
        for f in spec.get(key) or []:
            groups.setdefault(str(f.get("ax") or "z"), {}).setdefault(key, []).append(f)
    for ax, g in groups.items():
        if ax == "z":
            body = _cut_z(body, g, L, H)
            continue
        axis, deg, perm = _TO_CANON[ax]
        size = (L, W, H)
        ac = getattr(Axis, axis)
        turned = body.rotate(ac, deg)
        turned = _cut_z(turned, g, size[perm[0]], size[perm[2]])
        body = turned.rotate(ac, -deg)
    return body


def _cut_z(body: Any, spec: dict[str, Any], L: float, H: float) -> Any:
    """Features along Z on a body whose extent along Z is ``H`` (and whose turned Ø is ``L``)."""
    from build123d import Cylinder, Pos

    for j in spec.get("journals") or []:  # turned down: remove the ring outside the journal Ø
        z0, z1 = float(j["z0"]), float(j["z1"])
        lo = z0 - 1.0 if z0 <= -H / 2 + 1e-6 else z0
        ring = Pos(float(j["c"][0]), float(j["c"][1]), (lo + z1) / 2) * (
            Cylinder(L / 2 + 1, z1 - lo) - Cylinder(float(j["d"]) / 2, z1 - lo + 0.02))
        body = body - ring
    for h in spec.get("holes") or []:
        if h.get("z0") is not None:  # blind over a range (open at a face: cut 1 mm past it)
            z0, z1 = float(h["z0"]), float(h["z1"])
            lo = z0 - 1.0 if z0 <= -H / 2 + 1e-6 else z0
            hi = z1 + 1.0 if z1 >= H / 2 - 1e-6 else z1
            body = body - Pos(float(h["c"][0]), float(h["c"][1]), (lo + hi) / 2) * Cylinder(float(h["d"]) / 2, hi - lo)
            continue
        body = body - Pos(float(h["c"][0]), float(h["c"][1]), 0) * Cylinder(float(h["d"]) / 2, H + 2)
    for sd in spec.get("seats") or []:
        z0, z1 = float(sd["z0"]), float(sd["z1"])
        # a seat open at a face is cut 1 mm past it so the face is clean
        lo = z0 - 1.0 if z0 <= -H / 2 + 1e-6 else z0
        hi = z1 + 1.0 if z1 >= H / 2 - 1e-6 else z1
        body = body - Pos(float(sd["c"][0]), float(sd["c"][1]), (lo + hi) / 2) * Cylinder(float(sd["d"]) / 2, hi - lo)
    for k in spec.get("keyways") or []:
        body = body - _keyway(k, H)
    for g in spec.get("grooves") or []:  # a retaining-ring groove: the ring outside Ø d between z0 and z1
        z0, z1 = float(g["z0"]), float(g["z1"])
        body = body - Pos(float(g["c"][0]), float(g["c"][1]), (z0 + z1) / 2) * (
            Cylinder(L / 2 + 1, z1 - z0) - Cylinder(float(g["d"]) / 2, z1 - z0 + 0.02))
    return body


def write(dest: Path, spec: dict[str, Any]) -> Path:
    """Export the placeholder as a deterministic STEP at ``dest`` (a file path)."""
    from build123d import export_step

    from aicad.agent.runner import STEP_TIMESTAMP, normalize_step

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".tmp.step")
    export_step(shape(spec), str(tmp), timestamp=STEP_TIMESTAMP)
    normalize_step(tmp)
    os.replace(tmp, dest)
    return dest
