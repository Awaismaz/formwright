"""Placeholder bodies (CD-011): an item's envelope solid carrying its named interface features, so the program
assembly exists before any part is designed. Kernel side (worker / tests only).

Spec (part frame, mm; built by ``aicad.office.icd.placeholder_spec``):
  {"shape": "box" | "cylinder", "size": [L, W, H] (a cylinder: [D, D, H] along Z), "holes": [{"c": [x, y], "d": Ø}]}
Holes are through along Z. The body is centred on the origin (the part frame of the ICD).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def shape(spec: dict[str, Any]) -> Any:
    from build123d import Box, Cylinder, Pos

    L, W, H = (float(x) for x in spec["size"])
    body = Box(L, W, H) if spec["shape"] == "box" else Cylinder(L / 2, H)
    for h in spec.get("holes") or []:
        body = body - Pos(float(h["c"][0]), float(h["c"][1]), 0) * Cylinder(float(h["d"]) / 2, H + 2)
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
