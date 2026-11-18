"""Placeholder bodies (CD-011): an item's envelope solid carrying its named interface features, so the program
assembly exists before any part is designed. Kernel side (worker / tests only).

Spec (part frame, mm; built by ``aicad.office.icd.placeholder_spec`` / ``icd.body_spec``):
  {"shape": "box" | "cylinder", "size": [L, W, H] (a cylinder: [D, D, H] along Z),
   "holes":    [{"c": [x, y], "d": Ø}]                              through along Z
   "seats":    [{"c": [x, y], "d": Ø, "z0", "z1"}]                  a bore over a Z range (bearing seat, clearance)
   "journals": [{"c": [x, y], "d": Ø, "z0", "z1"}]                  a shaft turned down to Ø over a Z range
   "keyways":  [{"on": "shaft" | "hub", "c", "d", "b", "depth", "dir": [dx, dy], "z0", "z1"}]  DIN 6885 grooves}
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


def cut(body: Any, spec: dict[str, Any]) -> Any:
    """Cut the spec's interface features into a body centred on the part frame."""
    from build123d import Cylinder, Pos

    L, _W, H = (float(x) for x in spec["size"])
    for j in spec.get("journals") or []:  # turned down: remove the ring outside the journal Ø
        z0, z1 = float(j["z0"]), float(j["z1"])
        lo = z0 - 1.0 if z0 <= -H / 2 + 1e-6 else z0
        ring = Pos(float(j["c"][0]), float(j["c"][1]), (lo + z1) / 2) * (
            Cylinder(L / 2 + 1, z1 - lo) - Cylinder(float(j["d"]) / 2, z1 - lo + 0.02))
        body = body - ring
    for h in spec.get("holes") or []:
        body = body - Pos(float(h["c"][0]), float(h["c"][1]), 0) * Cylinder(float(h["d"]) / 2, H + 2)
    for sd in spec.get("seats") or []:
        z0, z1 = float(sd["z0"]), float(sd["z1"])
        # a seat open at a face is cut 1 mm past it so the face is clean
        lo = z0 - 1.0 if z0 <= -H / 2 + 1e-6 else z0
        hi = z1 + 1.0 if z1 >= H / 2 - 1e-6 else z1
        body = body - Pos(float(sd["c"][0]), float(sd["c"][1]), (lo + hi) / 2) * Cylinder(float(sd["d"]) / 2, hi - lo)
    for k in spec.get("keyways") or []:
        body = body - _keyway(k, H)
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
